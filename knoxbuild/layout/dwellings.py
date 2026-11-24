"""Flats and the small rooms that make an apartment block.\n\nSplit from layout.py, which had grown to 8,333 lines; see the package\ndocstring for the shape of the whole thing.\n"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from itertools import accumulate
from math import ceil

from ..sizing import SIZES
from ..sizing import min_area
from ..sizing import programme_for_flat
from ..sizing import split_by_targets
import random

from typing import TYPE_CHECKING
from .core import MAX_DEPTH, MIN_ROOM, MIN_SPLIT, Plan, Room, _inside, _split
from .malls import _refit, _renumber

if TYPE_CHECKING:
    from .furnishing import Building



# What a flat contains, by how many rooms it got. The first entry goes to the
# room the front door opens into; the rest are handed out biggest-first, so the
# bathroom lands on the smallest room.
#
# Size matters: a two-room flat is a bedsit and wants a bathroom more than it
# wants a separate bedroom.
FLAT_PLANS = {
    # A one-room flat is a bedsit: somewhere to sleep, not a sofa and nothing.
    1: ["bedroom"],
    2: ["kitchen", "bathroom"],
    3: ["kitchen", "bedroom", "bathroom"],
    4: ["livingroom", "kitchen", "bedroom", "bathroom"],
    # From five rooms up the flat gets a little hall to open them off. Knox
    # County has 0.12 halls to a flat and two thirds of its floors of flats
    # have none at all - because its flats are small. Ours run to five, six
    # and eight rooms once they trade with the neighbour, and at that size a
    # third of the rooms were two doors deep and some were three or four: a
    # bedroom through a bathroom through a kitchen. Only the big ones get it,
    # which comes to about 0.09 halls a flat.
    5: ["hall", "livingroom", "kitchen", "bedroom", "bathroom"],
}
# From this many rooms up, a flat is entered through a hall.
FLAT_HALL_FROM = 5
# Not every flat is a set of small rectangles. Knox County gives only 0.56
# kitchens to a flat: the rest have no kitchen room at all, just a living room
# with the cooker and the fridge along one wall. The game draws a wall between
# any two rooms, so open plan is not a wall we leave out - it is one room that
# is both, which is what "openplan" is. It reaches the game as a livingroom,
# because the name is what the loot tables key off.
FLAT_PLANS_OPEN = {
    1: ["openplan"],
    2: ["openplan", "bathroom"],
    3: ["openplan", "bedroom", "bathroom"],
    4: ["openplan", "bedroom", "bedroom", "bathroom"],
    5: ["hall", "openplan", "bedroom", "bedroom", "bathroom"],
}
OPEN_PLAN_SHARE = 0.44
# Our room kinds are written out as the game's room names. Where the two
# differ, this maps ours to one the game furnishes and loots.
ROOM_NAME = {
    "openplan": "livingroom",
    # The mall concourse. The game knows it as a hall and the loot tables key
    # off that, so that is the name it is written under; it is a kind of its
    # own here only so it can be furnished as a concourse - planters, bins,
    # vending, the odd kiosk - instead of as the bare corridor a hall is.
    "concourse": "hall",
    # Knox County has 694 rooms called diningroom and 11 called dining. Ours
    # called every house's one "dining", which is a name the loot tables do
    # not know - the same mistake as "cells" for "prisoncells". The kind stays
    # separate from the canteen kind, which is furnished quite differently.
    "dining": "diningroom",
}
FLAT_EXTRA = ["bedroom", "storage"]
# Floor area, in tiles, from which a flat is cut into at least three rooms.
FLAT_MIN_SPLIT_AREA = 30
# Tiles of corridor wall each flat gets. Narrower slices gave two- and
# three-room flats, and with the bathroom going to the smallest room, a flat
# of two big rooms had a bathroom the size of its living room.
# This is the fallback: _flat_frontage works it out from how deep the
# floorplate is, because one fixed frontage cannot suit every building. At 8
# to 11 tiles a deep plate gave 117 m2 flats of six rooms; at 5 to 7 a shallow
# one gave 40 m2 flats that could not hold three.
FLAT_FRONTAGE = (5, 7)
# What a flat should come out at. Knox County's are 57 m2; a little over gives
# room for the separate kitchen ours each need.
FLAT_TARGET_AREA = 62


def _flat_frontage(depth: int) -> tuple[int, int]:
    """How wide to slice flats off a corridor a given depth of floor deep.

    A flat wants about FLAT_TARGET_AREA of floor however deep the building is,
    so the frontage falls as the plate gets deeper. The lower bound is what
    three rooms can physically be cut from: below MIN_SPLIT * MIN_ROOM a room
    cannot be halved again, so a narrow flat comes out as two rooms whatever
    the plan asks for.
    """
    want = max(MIN_ROOM + 1, round(FLAT_TARGET_AREA / max(1, depth)))
    least = max(MIN_ROOM + 1, (MIN_SPLIT * MIN_ROOM * 2) // max(1, depth))
    low = max(want, least)
    return (low, low + 2)
# What a flat is. Knox County's blocks hold, per block, 13.8 bathrooms, 13.7
# living rooms, 10.6 bedrooms, 7.7 kitchens and 4.8 closets. Counting one
# bathroom to a flat - the surest marker, being the commonest room - that is
# about 3.8 rooms to a flat. Ours were 6 rooms in 117 m2: two flats' worth of
# floor cut into two flats' worth of rooms and called one home, which is why a
# floor read as a grid of cells rather than as somewhere people live.
#
# The game gives only 0.56 kitchens to a flat, the rest being a kitchenette in
# the living room. Ours gives every flat one, because a flat with no kitchen
# room spawns no food: the room name is what the loot tables key off.
FLAT_ROOMS = 4
# An open-plan flat is cut into fewer: the living end is one room that is
# also the kitchen, so it has to stay big enough to hold a sofa facing a
# television. At FLAT_ROOMS the open room came out at 16 m2.
FLAT_ROOMS_OPEN = 2
# A floorplate deeper than this gets two ranks of flats back to back, the way
# a real block does, rather than one flat running the whole depth of it.
FLAT_MAX_DEPTH = 11
# A hotel room is narrower than a flat: a room and its bathroom.
HOTEL_FRONTAGE = (4, 6)


def _slices(length: int, rng: random.Random,
            lo: int, hi: int) -> list[tuple[int, int]]:
    """Cut 0..length-1 into runs close to lo..hi, sized evenly.

    Taking random lengths from one end and giving the last slice whatever was
    left made the final flat on each side up to twice the size of the others -
    a 26-tile corridor came out as flats of 7 and 19. Deciding how many flats
    fit first and then sharing the length out keeps them comparable, with a
    tile of jitter so a row of flats is not perfectly regular.
    """
    count = max(1, round(length / ((lo + hi) / 2)))
    widths = [length // count] * count
    for i in range(length - sum(widths)):
        widths[i] += 1
    for i in range(count - 1):
        shift = rng.choice((-1, 0, 1))
        if widths[i] + shift >= lo and widths[i + 1] - shift >= lo:
            widths[i] += shift
            widths[i + 1] -= shift
    out, a = [], 0
    for wdt in widths:
        out.append((a, a + wdt - 1))
        a += wdt
    return out


def _corridor_axis(plan: Plan, spine=None) -> str | None:
    """"y" or "x" for the direction a corridor runs, None without one."""
    if plan.core is None or not plan.corridor:
        return None
    x0, y0, x1, y1 = spine or plan.core
    return "y" if (y1 - y0) >= (x1 - x0) else "x"


def _corridor_slices(plan: Plan, axis: str, across: tuple[int, int],
                     spine: tuple[int, int], rng: random.Random,
                     flat_count: int | None = None) -> list[tuple[int, int]]:
    """Balance flat areas while keeping usable proportions and hall access."""
    a, b = across
    first, last = spine
    length = plan.height if axis == "y" else plan.width
    areas = [(_inside(a, i, b, i, plan.mask) if axis == "y"
              else _inside(i, a, i, b, plan.mask)) for i in range(length)]
    sums = list(accumulate(areas, initial=0))
    # The end flats can extend past the hall. Interior flats need enough width
    # for their depth, even when the floor could fit more nominal-sized homes.
    min_width = max(MIN_ROOM + 1, ceil(sums[-1] / (2 * length)))
    first_cut = max(min_width, first + MIN_ROOM)
    last_cut = min(length - min_width, last + 1 - MIN_ROOM)
    capacity = 1 if first_cut > last_cut else 2 + (last_cut - first_cut) // min_width
    preferred = flat_count if flat_count is not None else round(sums[-1] / FLAT_TARGET_AREA)
    count = max(1, min(capacity, preferred))
    cuts = [0]
    for i in range(1, count):
        low = max(first_cut, cuts[-1] + min_width)
        high = last_cut - (count - i - 1) * min_width
        target = sums[-1] * i / count + rng.choice((-1, 0, 1)) * (b - a + 1) / 2
        cuts.append(min(range(low, high + 1), key=lambda cut: abs(sums[cut] - target)))
    return [(start, end - 1) for start, end in zip(cuts, cuts[1:] + [length])]


def _planned_flat(box, edge, mask, open_plan, approach=None, *, service=None, alternate_bath=False):
    """A short service band at the entry, with living rooms on the facade."""
    x0, y0, x1, y1 = box
    if mask is not None:
        cells = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if mask[y][x]]
        if not cells:
            return None
        xs, ys = zip(*cells)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    vertical = edge in ("N", "S")
    depth, span = (y1 - y0 + 1, x1 - x0 + 1) if vertical else (x1 - x0 + 1, y1 - y0 + 1)
    if depth < 5 or span < 4:
        return None
    if service is None:
        service = 3 if depth >= 8 else 2
    if depth - service < 3:
        return None
    bedrooms = 0 if span < 6 else 2 if span >= 11 and depth >= 8 else 1
    sections = []

    def add(kind, u0, u1, v0, v1):
        if v1 > v0:
            sections.append((kind, u0, u1, v0, v1))

    # The foyer reaches the actual shared landing, even where the rest of
    # this side of the apartment touches its neighbour instead.
    width = min(4 if span >= 8 else 2, span - 2)
    pivot = (approach - (x0 if vertical else y0)) if approach is not None else (span - 1) // 2
    start = min(span - width, max(0, pivot - (width - 1) // 2))
    if span <= 5:
        start = 0 if pivot <= (span - 1) // 2 else span - width
    if start == 1:
        start = 0
        width += 1
    end = start + width
    if span - end == 1:
        end = span
    sides = [(a, b) for a, b in ((0, start), (end, span)) if b - a >= 2]
    if not sides:
        return None
    lo, hi = sorted(sides, key=lambda band: band[1] - band[0])[int(alternate_bath and len(sides) > 1)]
    # Keep the remaining service rooms on the entry side of the bathroom.
    # A cupboard behind the bath could otherwise need a door through a bedroom.
    bath_left = hi == start
    if hi - lo == 4:
        if bath_left:
            hi = start = start - 1
        else:
            lo = end = end + 1
    bath_lo, bath_hi = (lo, min(lo + 3, hi)) if bath_left else (max(lo, hi - 3), hi)
    add("hall", 0, service, start, end)
    add("bathroom", 0, service, bath_lo, bath_hi)
    rests = [(a, b) for left, right in ((0, start), (end, span))
             for a, b in ((left, min(right, bath_lo)), (max(left, bath_hi), right))
             if b > a]
    kitchen = max(rests, key=lambda band: band[1] - band[0], default=None)
    if not bedrooms or (open_plan and span < 9) or kitchen is None or kitchen[1] - kitchen[0] < 3:
        kitchen = None
    for a, b in rests:
        add("kitchen" if (a, b) == kitchen else "storage", 0, service, a, b)
    living = "livingroom" if kitchen is not None else "openplan"
    if bedrooms == 2:
        side = max(3, span // 4)
        add("bedroom", service, depth, 0, side)
        add(living, service, depth, side, span - side)
        add("kidsbedroom", service, depth, span - side, span)
    elif bedrooms == 1:
        side = max(3, min(span - 3, span // 2))
        living_right = start + end > 2 * side
        add("bedroom" if living_right else living, service, depth, 0, side)
        add(living if living_right else "bedroom", service, depth, side, span)
    else:
        add(living, service, depth, 0, span)

    def tile(u, v):
        if vertical:
            return x0 + v, y0 + u if edge == "N" else y1 - u
        return (x0 + u if edge == "W" else x1 - u), y0 + v

    rooms = []
    for kind, u0, u1, v0, v1 in sections:
        ax, ay = tile(u0, v0)
        bx, by = tile(u1 - 1, v1 - 1)
        room = Room(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by),
                    kind=kind, fixed=True)
        if mask is not None:
            visible = _kept_piece(room, mask)
            actual = _inside(room.x0, room.y0, room.x1, room.y1, mask)
            if (len(visible) != actual or len(visible) < min(room.area, SIZES[kind].lo)
                    or len({x for x, _ in visible}) < 2 or len({y for _, y in visible}) < 2):
                return None
        rooms.append(room)
    return rooms


def _landing_flats(plan, entrance):
    """Two flats beside the flight and two beyond the rear landing."""
    if entrance is None:
        return []
    x0, y0, x1, y1 = plan.core
    x, y, d = entrance
    if d == "W":
        # Build the same division in exchanged axes for a west/east stair.
        flipped = Plan(plan.height, plan.width, core=(y0, x0, y1, x1),
                       mask=[list(row) for row in zip(*plan.mask)] if plan.mask is not None else None)
        sides = {"E": "S", "W": "N", "S": "E", "N": "W"}
        return [((b, a, e, c), sides[edge], at)
                for (a, b, c, e), edge, at in _landing_flats(flipped, (y, x, "N"))]
    if x1 - x0 != 1:
        return []
    south = y == y1 + 1
    a, b = (y0, plan.height - 1) if south else (0, y1)
    c, e = (0, y0 - 1) if south else (y1 + 1, plan.height - 1)
    if min(b - a, e - c, x0 - 1, plan.width - x1 - 2) < 3:
        return []
    edge = "S" if south else "N"
    front = y0 + 1 if south else y1 - 1
    boxes = [((0, a, x0 - 1, b), "E", front),
             ((x1 + 1, a, plan.width - 1, b), "W", front),
             ((0, c, x0, e), edge, x0),
             ((x1, c, plan.width - 1, e), edge, x1)]
    if plan.mask is not None:
        total = sum(map(sum, plan.mask))
        covered = _inside(x0, y0, x1, y1, plan.mask)
        if total != covered + sum(_inside(*box, plan.mask) for box, _, _ in boxes):
            return []
    return boxes


def _flat_by_kind(box: tuple[int, int, int, int], rng: random.Random,
                  open_plan: bool, mask: list[list[bool]] | None,
                  edge: str, *, entry_first: bool = False, approach=None) -> list[Room] | None:
    """A flat's rooms cut to its programme's sizes, the living room on `edge`.

    Kinds are set and fixed here, so a bathroom is cut bathroom-sized rather
    than named after whichever piece came out smallest. A programme no cut
    can carve (four rooms in a strip five tiles deep) steps down to the next
    smaller one. None when none fits: the caller falls back.
    """
    x0, y0, x1, y1 = box
    area = (sum(mask[y][x] for y in range(y0, y1 + 1) for x in range(x0, x1 + 1))
            if mask is not None else (x1 - x0 + 1) * (y1 - y0 + 1))
    if entry_first:
        for service, alternate in ((None, False), (None, True), (2, False), (3, False),
                                   (2, True), (3, True)):
            if rooms := _planned_flat(box, edge, mask, open_plan, approach,
                                      service=service, alternate_bath=alternate):
                return rooms

    def cut(kinds):
        rooms = split_by_targets(box, kinds, rng, mask, edge)
        # Cut to the footprint, only one flat in seven on an irregular or
        # turned one found a cut at all. Failing that, the whole box is cut
        # and _paint clips it - kept only where every room keeps a piece of
        # its kind's least floor inside the walls that _mend_fragments will
        # not fold away as a sliver, or the bathroom is the first to go.
        if not rooms and mask is not None:
            rooms = split_by_targets(box, kinds, rng, None, edge)
            if rooms and any(
                    len(p) < SIZES[r.kind].lo or _too_small(p)
                    for r in rooms for p in [_kept_piece(r, mask)]):
                rooms = None
        return rooms

    while kinds := programme_for_flat(area, rng, open_plan):
        if entry_first:
            body = [kind for kind in kinds if kind != "hall"]
            hall = ["hall", *body]
            if area >= min_area(hall) and (rooms := cut(hall)):
                return rooms
            if "kitchen" in body:
                body = ["kitchen", *[kind for kind in body if kind != "kitchen"]]
            if body[0] in ("kitchen", "openplan") and (rooms := cut(body)):
                return rooms
        else:
            if kinds[0] == "hall":
                kinds = kinds[1:2] + kinds[:1] + kinds[2:]
            if rooms := cut(kinds):
                return rooms
        area = min_area(kinds) - 1
    return None


def _apartment_rooms(plan: Plan, rng: random.Random, target: int,
                     frontage: tuple[int, int] = FLAT_FRONTAGE, *,
                     section: bool = False, entry_first: bool = False, entrance=None,
                     spine=None, flat_count: int | None = None) -> None:
    """Lay a floor out as flats either side of a corridor.

    The order is what matters. Splitting the whole floor into rooms, grouping
    those into flats and then painting a corridor over the top - the first
    attempt at this - left most flats not touching the corridor at all, and cut
    rooms in half where the corridor ran through them. 191 of 200 blocks came
    out with a room nobody could get into.

    Here the corridor exists first. Each side of it is sliced into flats that
    run from the corridor wall to the outside wall, so every flat has a front
    door onto the corridor and a window onto the street by construction, and
    only then is each flat divided into its own rooms.
    """
    axis = _corridor_axis(plan, spine)
    if axis is None:
        # No corridor fits (an irregular footprint, usually). One flat per
        # floor is a real kind of building, so lay it out as that.
        _split(0, 0, plan.width - 1, plan.height - 1, rng, MAX_DEPTH,
               plan.rooms, target_area=target, mask=plan.mask)
        for room in plan.rooms:
            room.unit = 1
        return

    if spine is None and entry_first and (boxes := _landing_flats(plan, entrance)):
        for unit, (box, edge, approach) in enumerate(boxes, 1):
            rooms = _flat_by_kind(box, rng, False, plan.mask, edge,
                                  entry_first=True, approach=approach)
            if not rooms:
                break
            for r in rooms:
                r.unit = unit
            plan.rooms.extend(rooms)
        else:
            return
        plan.rooms.clear()

    cx0, cy0, cx1, cy1 = spine or plan.core
    unit = 0
    a0, a1, first, last = (cx0, cx1, cy0, cy1) if axis == "y" else (cy0, cy1, cx0, cx1)
    end = (plan.width if axis == "y" else plan.height) - 1
    length = plan.height if axis == "y" else plan.width
    if spine is not None:
        # Split the floor between the corridor's lanes. Its own tiles were
        # already reserved, so each wing includes only the private end space.
        middle = (a0 + a1) // 2
        sides = ((0, middle), (middle + 1, end))
    else:
        sides = ((0, a0 - 1), (a1 + 1, end))
    wing_counts = (None, None)
    if spine is not None and flat_count is not None:
        areas = [(_inside(a, 0, b, length - 1, plan.mask) if axis == "y"
                  else _inside(0, a, length - 1, b, plan.mask)) for a, b in sides]
        total_area = sum(areas)
        if total_area:
            first_count = round(flat_count * areas[0] / total_area)
            wing_counts = (first_count, flat_count - first_count)
    # The side of each flat's box that faces the corridor.
    edges = ("E", "W") if axis == "y" else ("S", "N")
    for (a0, a1), edge, wing_count in zip(sides, edges, wing_counts):
        if a1 - a0 + 1 < MIN_ROOM:
            continue
        # Each side sliced independently, so the flats do not line up across
        # the corridor like a spreadsheet.
        # A floorplate deeper than one flat gets two ranks back to back, the
        # way a real block does, rather than one flat running the whole depth.
        depth = a1 - a0 + 1
        if not section and frontage == FLAT_FRONTAGE and depth > FLAT_MAX_DEPTH + MIN_ROOM:
            ranks = [(a0, a0 + depth // 2 - 1), (a0 + depth // 2, a1)]
        else:
            ranks = [(a0, a1)]
        for b0, b1 in ranks:
            if spine is not None:
                slices = _corridor_slices(plan, axis, (b0, b1), (first, last), rng, wing_count)
            else:
                cut = (_flat_frontage(b1 - b0 + 1) if frontage == FLAT_FRONTAGE else frontage)
                slices = _slices(length, rng, *cut)
            for s0, s1 in slices:
                unit += 1
                box = (b0, s0, b1, s1) if axis == "y" else (s0, b0, s1, b1)
                area = (_inside(*box, plan.mask) if spine is not None
                        else (b1 - b0 + 1) * (s1 - s0 + 1))
                approach = ((max(s0, first) + min(s1, last)) // 2 if spine is not None else None)
                flat: list[Room] = []
                # A flat is cut towards FLAT_ROOMS rooms, not towards the
                # building's own room size: at that size a 117 m2 flat came
                # out as six rooms, where the game's 57 m2 flat has three.
                # An open-plan flat is cut towards fewer, so the living end
                # stays one big room instead of two small ones.
                open_plan = (frontage == FLAT_FRONTAGE
                             and rng.random() < OPEN_PLAN_SHARE)
                if open_plan:
                    plan.open_units.add(unit)
                rooms_wanted = FLAT_ROOMS_OPEN if open_plan else FLAT_ROOMS
                want = (max(target, area // rooms_wanted)
                        if frontage == FLAT_FRONTAGE else target)
                # A flat is cut by what it holds, sized by kind; a hotel, and
                # a flat no programme fits, is cut as it always was.
                by_kind = (_flat_by_kind(box, rng, open_plan, plan.mask, edge,
                                         entry_first=entry_first, approach=approach)
                           if frontage == FLAT_FRONTAGE else None)
                if by_kind:
                    flat = by_kind
                else:
                    _split(*box, rng, MAX_DEPTH, flat, target_area=want,
                           mask=plan.mask)
                # A flat that came out as one or two rooms was all living
                # room: in a small block every flat on every floor had nothing
                # else, not a bed or a bathroom in the building. Cut it into a
                # home's rooms when it is big enough for them.
                if (frontage == FLAT_FRONTAGE and not open_plan
                        and not by_kind and len(flat) < 3
                        and area >= FLAT_MIN_SPLIT_AREA):
                    flat = []
                    _split(*box, rng, MAX_DEPTH, flat,
                           target_area=max(MIN_SPLIT * MIN_ROOM, area // 3),
                           mask=plan.mask)
                for room in flat:
                    room.unit = unit
                plan.rooms.extend(flat)

    if spine is not None:
        return
    # In the older layout the rooms at each end fill the width of the core.
    if axis == "y":
        caps = [(cx0, 0, cx1, cy0 - 1), (cx0, cy1 + 1, cx1, plan.height - 1)]
    else:
        caps = [(0, cy0, cx0 - 1, cy1), (cx1 + 1, cy0, plan.width - 1, cy1)]
    for x0, y0, x1, y1 in caps:
        if x1 < x0 or y1 < y0:
            continue
        unit += 1
        cap: list[Room] = []
        _split(x0, y0, x1, y1, rng, MAX_DEPTH, cap, target_area=target, mask=plan.mask)
        for room in cap:
            room.unit = unit
        plan.rooms.extend(cap)


# How many flats trade a room with the one next door, so the two of them come
# out L-shaped around each other instead of both being boxes. Every flat used
# to be one rectangle sliced off the corridor, which is what made a floor read
# as a spreadsheet however well the rooms inside it were arranged.
FLAT_STAGGER_SHARE = 0.35


def _contiguous(members: list[int], adj: dict[int, dict[int, int]]) -> bool:
    """Whether these rooms all touch each other, directly or through others."""
    if len(members) <= 1:
        return True
    want = set(members)
    seen = {members[0]}
    edge = [members[0]]
    while edge:
        nxt = []
        for i in edge:
            for n in adj.get(i, ()):
                if n in want and n not in seen:
                    seen.add(n)
                    nxt.append(n)
        edge = nxt
    return seen == want


def _stagger_flats(plan: Plan, rng: random.Random) -> None:
    """Hand a room from one flat to the flat next door, where both survive it.

    A flat is cut as a rectangle, so a floor of them is a grid. Giving a
    boundary room to the neighbour leaves both of them L-shaped around each
    other, which is how a real block comes out once the flats are not all the
    same size. A room only moves when what it leaves behind still holds
    together and neither flat is emptied.
    """
    adj = _neighbours(plan)
    units: dict[int, list[int]] = {}
    for i, room in enumerate(plan.rooms, 1):
        if room.unit:
            units.setdefault(room.unit, []).append(i)
    order = sorted(units)
    rng.shuffle(order)
    for unit in order:
        members = units.get(unit, [])
        if len(members) < 3 or rng.random() >= FLAT_STAGGER_SHARE:
            continue
        # The room to give away: one on the flat's edge, touching another flat.
        # A room cut to its kind moves only if it is a bedroom: giving away a
        # living room, kitchen or bathroom would leave its flat without one.
        options = [(i, plan.rooms[n - 1].unit)
                   for i in members
                   if not plan.rooms[i - 1].fixed
                   or plan.rooms[i - 1].kind in ("bedroom", "kidsbedroom")
                   for n in adj.get(i, ())
                   if plan.rooms[n - 1].unit
                   and plan.rooms[n - 1].unit != unit]
        rng.shuffle(options)
        for give, to in options:
            left = [i for i in members if i != give]
            if not _contiguous(left, adj):
                continue
            gained = units.get(to, []) + [give]
            if not _contiguous(gained, adj):
                continue
            # Touching is not enough: the flat has to be able to put a door
            # between them. A room joined across two tiles of wall could not
            # be reached from its new flat's front door, so the door tree
            # fell through to its last resort and joined two flats together
            # or gave one of them a second front door - 175 and 89 of them.
            if max((adj[give].get(n, 0) for n in units.get(to, ())),
                   default=0) < MIN_SPLIT:
                continue
            plan.rooms[give - 1].unit = to
            units[unit] = left
            units[to] = gained
            plan.open_units.discard(unit)
            plan.open_units.discard(to)
            break


def _neighbours(plan: Plan) -> dict[int, dict[int, int]]:
    """Room index -> {neighbour index: length of shared wall in tiles}."""
    adj: dict[int, dict[int, int]] = {i: {} for i in range(1, len(plan.rooms) + 1)}
    for y in range(plan.height):
        for x in range(plan.width):
            a = plan.grid[y][x]
            if not a:
                continue
            for bx, by in ((x + 1, y), (x, y + 1)):
                if bx >= plan.width or by >= plan.height:
                    continue
                b = plan.grid[by][bx]
                if b and b != a:
                    adj[a][b] = adj[a].get(b, 0) + 1
                    adj[b][a] = adj[b].get(a, 0) + 1
    return adj


def _assign_flat_kinds(plan: Plan, hotel: bool = False,
                       reception: bool = False,
                       rng: random.Random | None = None, *, entry_first: bool = False) -> None:
    """Give every flat its own set of rooms, arranged around its front door.

    The room touching the corridor is where you walk in, so it becomes the
    living room; the rest follow by size, with the bathroom on the smallest.
    In a hotel each "flat" is guest rooms with a bathroom.
    """
    rng = rng or random.Random(len(plan.rooms))
    adj = _neighbours(plan)
    corridor = {i for i, r in enumerate(plan.rooms, 1) if r.unit == 0}
    units: dict[int, list[int]] = {}
    for i, room in enumerate(plan.rooms, 1):
        if room.unit == 0:
            room.kind = "hall"
        else:
            units.setdefault(room.unit, []).append(i)
    for u, members in units.items():
        entry = [i for i in members if any(n in corridor for n in adj[i])]
        by_size = sorted(members, key=lambda i: -plan.rooms[i - 1].area)
        # A flat cut by kind (_flat_by_kind) keeps its kinds while its living
        # room still opens off the corridor. One that took in a neighbour's
        # rooms keeps a single living room, kitchen and hall - the one by the
        # door first - and the doubles, like any piece the cut never named,
        # are handed out as extras. A living room cut off from the corridor
        # throws the flat back to being named by size.
        kinds_at_door = ("hall", "kitchen", "openplan") if entry_first else ("livingroom", "openplan")
        door = [i for i in entry if plan.rooms[i - 1].fixed
                and plan.rooms[i - 1].kind in kinds_at_door]
        if door and not hotel:
            keep = min(door, key=lambda i: (kinds_at_door.index(plan.rooms[i - 1].kind),
                                            -plan.rooms[i - 1].area) if entry_first
                       else (0, -plan.rooms[i - 1].area))
            taken: set[str] = set()
            extra = 0
            for i in [keep] + [i for i in by_size if i != keep]:
                room = plan.rooms[i - 1]
                slot = "livingroom" if room.kind == "openplan" else room.kind
                if room.fixed and (slot not in ("livingroom", "kitchen", "hall")
                                   or slot not in taken):
                    taken.add(slot)
                    continue
                room.kind = FLAT_EXTRA[extra % len(FLAT_EXTRA)]
                extra += 1
            continue
        first = max(entry, key=lambda i: plan.rooms[i - 1].area) \
            if entry else by_size[0]
        # In a flat big enough for a hall, the hall is the first of the plan,
        # so it has to fall on the room that can actually serve as one: the
        # one touching the most of the others. Giving the name to the room by
        # the door instead left it bordering two rooms out of six, and the
        # rest still opened through each other.
        if len(members) >= FLAT_HALL_FROM and not hotel:
            inside = {i: sum(1 for n in adj[i] if n in members)
                      for i in members}
            first = max(members, key=lambda i: (inside[i],
                                                i in entry,
                                                plan.rooms[i - 1].area))
        ordered = [first] + [i for i in by_size if i != first]
        # Some flats are open plan: one room for the kitchen and the living
        # room together rather than a wall between them.
        open_plan = u in plan.open_units
        kinds = ((FLAT_PLANS_OPEN if open_plan else FLAT_PLANS)
                 .get(len(ordered)))
        if hotel:
            # A guest room, its bathroom, and a wardrobe closet in a big one.
            kinds = (["motelroom", "closet"][:max(1, len(ordered) - 1)]
                     + ["motelroom"] * max(0, len(ordered) - 3) + ["bathroom"])[:len(ordered)]                 if len(ordered) > 1 else ["motelroom"]
            if reception and u == min(units):
                kinds[0] = "lobby"
        elif kinds is None:
            base = FLAT_PLANS_OPEN[5] if open_plan else FLAT_PLANS[5]
            extra = [FLAT_EXTRA[k % len(FLAT_EXTRA)]
                     for k in range(len(ordered) - 5)]
            kinds = base[:-1] + extra + base[-1:]
        for i, kind in zip(ordered, kinds):
            plan.rooms[i - 1].kind = kind


def _flats_keep_bathrooms(plan: Plan) -> None:
    """Give a bathroom back to any flat of two rooms or more that lost it.

    A bathroom cut to its kind is 3x3: a lift shaft landing on it, or a notch
    in the footprint parting it from its flat, leaves a sliver folded into
    the room next door or a piece handed to the neighbouring flat. The
    smallest room that is not the living room - a kitchen last - takes over.
    """
    units: dict[int, list[Room]] = {}
    for room in plan.rooms:
        if room.unit and not room.is_shaft:
            units.setdefault(room.unit, []).append(room)
    for rooms in units.values():
        bathrooms = [r for r in rooms if r.kind == "bathroom"]
        if plan.private_flats and len(bathrooms) > 1:
            keep = min(bathrooms, key=lambda r: (not r.surveyed, abs(r.area - SIZES["bathroom"].target)))
            for room in bathrooms:
                if room is not keep and not room.surveyed:
                    room.kind = "storage"
        if len(rooms) < 2 or bathrooms:
            continue
        spare = [r for r in rooms if not r.surveyed and r.kind not in ("livingroom", "openplan")]
        if spare:
            min(spare, key=lambda r: (r.kind == "kitchen", r.area)).kind = "bathroom"


def _graph_distance(adj: dict[int, dict[int, int]], start: int) -> dict[int, int]:
    dist = {start: 0}
    frontier = [start]
    while frontier:
        nxt = []
        for cur in frontier:
            for n in adj[cur]:
                if n not in dist:
                    dist[n] = dist[cur] + 1
                    nxt.append(n)
        frontier = nxt
    return dist


# A building laid out this thin keeps at least this many rooms: a shed, a
# corner shop or a two-room flat is already as coarse as it can be, and a map
# that needs fewer than that per building is asking for no interiors at all.
THIN_MIN_ROOMS = 4


def thin_plan(plan: Plan, limit: int) -> int:
    """Merge rooms until the storey has `limit` of them; how many went.

    The cheapest pair joins first: the two rooms that together cover the least
    ground, so a box room or a second bathroom is folded into the hall beside
    it rather than a house losing its kitchen. Only rooms in the same dwelling
    are joined, and nothing structural is touched - a stair shaft or a stair
    core - or a plan somebody drew by hand.

    Walls, doors and furniture stay exactly where they are: the tiles of the
    room that goes simply belong to the room that stays, so the two read as
    one room with a doorway in it. `knoxbuild/build.py` thins a map that would
    otherwise be past the game's 10 MB save buffer (tools/make_map_mod.py).
    """
    if plan.drawn or limit < 1 or len(plan.rooms) <= limit:
        return 0
    from .openings import FLAT_END_ROOMS

    def protected(room):
        return (room.is_core or room.is_shaft or room.is_balcony or room.apartment_entry or room.surveyed
                or room.business is not None
                or (plan.private_flats and room.kind in FLAT_END_ROOMS))

    merged = 0
    while len(plan.rooms) > limit:
        adj = _neighbours(plan)
        best = None
        for a, near in adj.items():
            ra = plan.rooms[a - 1]
            if protected(ra):
                continue
            for b, wall in near.items():
                rb = plan.rooms[b - 1]
                if protected(rb) or rb.unit != ra.unit:
                    continue
                # the least ground given up, and on the least unlikely wall
                key = (ra.w * ra.h + rb.w * rb.h, -wall)
                if best is None or key < best[0]:
                    best = (key, a, b)
        if best is None:
            break                      # nothing left that may be joined
        keep, gone = (best[1], best[2]) if best[1] < best[2] else (best[2], best[1])
        for y in range(plan.height):
            row = plan.grid[y]
            for x in range(plan.width):
                if row[x] == gone:
                    row[x] = keep
        plan.rooms[gone - 1].kind = None
        _renumber(plan)
        merged += 1
    return merged


def thin_building(building: "Building", limit: int) -> int:
    """Merge a building's rooms down to `limit`; how many went.

    Each storey gives up rooms in proportion to what it has, so the ground
    floor keeps its shop partitions while the flats above lose theirs - and
    never below `THIN_MIN_ROOMS` a storey, which is worth more than the last
    few bytes: a building laid out that coarse is not a building any more.
    """
    total = len(building.rooms)
    if limit <= 0 or total <= limit:
        return 0
    merged = 0
    for storey in building.storeys:
        share = max(THIN_MIN_ROOMS, round(len(storey.rooms) * limit / total))
        merged += thin_plan(storey, min(share, len(storey.rooms)))
    while len(building.rooms) > limit:
        biggest = max(building.storeys, key=lambda s: len(s.rooms))
        if len(biggest.rooms) <= THIN_MIN_ROOMS:
            break
        went = thin_plan(biggest, len(biggest.rooms) - 1)
        if not went:
            break
        merged += went
    return merged


def _paint(plan: Plan, shared_tiles: set[tuple[int, int]] | None = None,
           shells: list[set[tuple[int, int]]] | None = None) -> set[int]:
    plan.grid = [[0] * plan.width for _ in range(plan.height)]
    for idx, r in enumerate(plan.rooms, start=1):
        if shells is not None:
            for x, y in shells[idx - 1]:
                plan.grid[y][x] = idx
            continue
        for y in range(r.y0, r.y1 + 1):
            for x in range(r.x0, r.x1 + 1):
                if plan.mask is not None and not plan.mask[y][x]:
                    continue
                plan.grid[y][x] = idx

    # The stair shaft is painted over whatever is beneath it, identically on
    # every storey. Stairs used to be dropped wherever five tiles happened to be
    # inside the building, which on 80% of them meant a flight crossing a room
    # boundary and running into an interior wall.
    if shared_tiles:
        xs, ys = zip(*shared_tiles)
        plan.rooms.append(Room(min(xs), min(ys), max(xs), max(ys), kind="hall", unit=0,
                               is_core=True))
        idx = len(plan.rooms)
        for x, y in shared_tiles:
            plan.grid[y][x] = idx
    elif plan.core is not None:
        cx0, cy0, cx1, cy1 = plan.core
        plan.rooms.append(Room(cx0, cy0, cx1, cy1, kind="hall", unit=0,
                               is_core=True))
        idx = len(plan.rooms)
        for y in range(cy0, cy1 + 1):
            for x in range(cx0, cx1 + 1):
                if not plan.private_flats or plan.mask is None or plan.mask[y][x]:
                    plan.grid[y][x] = idx

    _renumber(plan)
    merged = _mend_fragments(plan)
    _refit(plan)
    return merged


# A room piece smaller than this, or only this thick, is not a room. Along a
# diagonal wall the grid cuts the corners of every rectangle into wedges of a
# few tiles; left alone each became a room of its own - a house turned 38
# degrees came out with 18 rooms, most of them triangles you could not stand in.
SLIVER = 10
SLIVER_THICKNESS = 2


def _too_small(cells, drawn: bool = False) -> bool:
    """Whether a piece of room is a sliver _mend_fragments folds away."""
    if len(cells) < 4:
        return True
    if drawn:
        # Hand-drawn: a strip two tiles thick is a corridor if that is
        # what it was drawn as. Folding those into the room next door ate
        # rooms people had just drawn - draw a room, draw another over
        # part of it, and what was left of the first became part of the
        # second, under a name they never picked.
        return False
    xs = {x for x, _ in cells}
    ys = {y for _, y in cells}
    # A whole rectangle of 3x3 or more is a real room - a small bathroom
    # is exactly that. Only the ragged wedges a diagonal wall leaves go.
    if len(cells) == len(xs) * len(ys) and min(len(xs), len(ys)) >= 3:
        return False
    return (len(cells) < SLIVER
            or min(len(xs), len(ys)) < 2
            or (min(len(xs), len(ys)) <= SLIVER_THICKNESS
                and len(cells) < 3 * SLIVER))


def _pieces(room: Room, mask: list[list[bool]]) -> list[set[tuple[int, int]]]:
    """The connected pieces of a room left inside the footprint, biggest first."""
    cells = {(x, y) for y in range(room.y0, room.y1 + 1)
             for x in range(room.x0, room.x1 + 1) if mask[y][x]}
    out = []
    while cells:
        stack = [cells.pop()]
        piece = set(stack)
        while stack:
            x, y = stack.pop()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in cells:
                    cells.remove(n)
                    piece.add(n)
                    stack.append(n)
        out.append(piece)
    return sorted(out, key=len, reverse=True)


def _kept_piece(room: Room, mask: list[list[bool]]) -> set[tuple[int, int]]:
    """The biggest connected piece of a room left inside the footprint."""
    return (_pieces(room, mask) or [set()])[0]


def _mend_fragments(plan: Plan) -> set[int]:
    """Split rooms that were cut in two, and fold slivers into a neighbour.

    An irregular footprint or the stair shaft can cut one rectangle into pieces
    that no longer touch. BuildingEd treats them as one room, so the only door
    lands in one piece and the other is sealed; the game then has a room with
    no way in. Each piece becomes a room of its own, and pieces too small to
    be a room are given to whatever they border, preferring the same flat.
    """
    merged = set()
    for idx in range(1, len(plan.rooms) + 1):
        cells = {(x, y) for y in range(plan.height) for x in range(plan.width)
                 if plan.grid[y][x] == idx}
        pieces = []
        while cells:
            seed = cells.pop()
            piece = {seed}
            stack = [seed]
            while stack:
                x, y = stack.pop()
                for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if n in cells:
                        cells.remove(n)
                        piece.add(n)
                        stack.append(n)
            pieces.append(piece)
        if len(pieces) <= 1:
            continue
        pieces.sort(key=len, reverse=True)
        base = plan.rooms[idx - 1]
        for piece in pieces[1:]:
            plan.rooms.append(replace(base) if base.surveyed else
                              Room(0, 0, 0, 0, kind=base.kind, unit=base.unit))
            new = len(plan.rooms)
            for x, y in piece:
                plan.grid[y][x] = new

    def too_small(cells) -> bool:
        return _too_small(cells, plan.drawn)

    for idx in range(1, len(plan.rooms) + 1):
        room = plan.rooms[idx - 1]
        if room.is_core or room.is_shaft or room.surveyed:
            continue
        cells = [(x, y) for y in range(plan.height) for x in range(plan.width)
                 if plan.grid[y][x] == idx]
        if plan.private_flats and room.fixed and room.kind in ("hall", "bathroom", "kitchen", "storage"):
            xs, ys = {x for x, _y in cells}, {y for _x, y in cells}
            if min(len(xs), len(ys)) >= 2 and len(cells) == len(xs) * len(ys):
                continue
        if not cells or not too_small(cells):
            continue
        unit = plan.rooms[idx - 1].unit
        options: dict[int, int] = {}
        for x, y in cells:
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < plan.width and 0 <= ny < plan.height:
                    v = plan.grid[ny][nx]
                    if v and v != idx and not (plan.rooms[v - 1].is_shaft or plan.rooms[v - 1].surveyed):
                        options[v] = options.get(v, 0) + 1
        if not options:
            continue
        home = max(options, key=lambda v: (plan.rooms[v - 1].unit == unit,
                                           plan.private_flats and unit and plan.rooms[v - 1].unit > 0,
                                           options[v]))
        recipient = plan.rooms[home - 1].unit
        if recipient and recipient != unit:
            merged.add(recipient)
        for x, y in cells:
            plan.grid[y][x] = home

    _renumber(plan)
    return merged


def inlay_mapped_rooms(plan: Plan, mapped) -> set[int]:
    """Keep surveyed walls inside the dwelling footprint and refit the remainder."""
    for tiles, kind in mapped:
        cells = {}
        free = set()
        for x, y in sorted(tiles):
            rid = plan.grid[y][x]
            if rid:
                room = plan.rooms[rid - 1]
                if room.unit and not room.surveyed:
                    cells[x, y] = room
            elif plan.mask is None or plan.mask[y][x]:
                free.add((x, y))
        if not cells:
            plan.unmapped_room_tiles += len(tiles)
            continue
        unit = Counter(r.unit for r in cells.values()).most_common(1)[0][0]
        room_kind = kind or Counter(r.kind for r in cells.values()).most_common(1)[0][0]
        plan.rooms.append(Room(0, 0, 0, 0, kind=room_kind, unit=unit, fixed=True, surveyed=True))
        for x, y in cells.keys() | free:
            plan.grid[y][x] = len(plan.rooms)
        plan.unmapped_room_tiles += len(tiles) - len(cells) - len(free)
    merged = _mend_fragments(plan)
    _refit(plan)
    return merged


def _join_undersized_flats(plan: Plan, minimum: int | None = None) -> set[int]:
    """Rejoin slivers left where the entrance passage cuts a dwelling."""
    areas = Counter(plan.rooms[i - 1].unit for row in plan.grid for i in row
                    if i and plan.rooms[i - 1].unit)
    if minimum is None:
        minimum = min_area(["openplan", "bathroom"])
    if not areas or min(areas.values()) >= minimum:
        return set()
    members: dict[int, list[int]] = {}
    for i, room in enumerate(plan.rooms, 1):
        if room.unit:
            members.setdefault(room.unit, []).append(i)
    neighbours = _neighbours(plan)
    merged = set()
    for unit in sorted(areas, key=areas.get):
        if not 0 < areas[unit] < minimum:
            continue
        border: Counter[int] = Counter()
        for i in members[unit]:
            for other, length in neighbours[i].items():
                home = plan.rooms[other - 1].unit
                if home and home != unit:
                    border[home] += length
        if border:
            recipient = max(border, key=lambda home: (
                border[home], -abs(FLAT_TARGET_AREA - areas[home] - areas[unit]), -home))
            for i in members[unit]:
                plan.rooms[i - 1].unit = recipient
            members[recipient].extend(members.pop(unit))
            areas[recipient] += areas.pop(unit)
            merged.add(recipient)
    return merged


def _unit_touches_corridor(plan: Plan) -> set[int]:
    """Make every flat one connected piece with a wall on the corridor.

    A flat can be cut in two by a notch in the footprint, and a flat sliced
    where the building narrows can border only its neighbours. Either way,
    some of its rooms could only be reached by walking through somebody
    else's home. Working piece by piece: a piece that reaches the corridor
    stays a flat of its own (split off if it had become separated from the
    rest), and a piece that does not is joined to the neighbouring flat it
    shares most wall with.
    """
    merged = set()
    corridor_units = {r.unit for r in plan.rooms if r.unit == 0}
    if not corridor_units:
        return merged
    for _ in range(len(plan.rooms) + 1):
        adj = _neighbours(plan)
        by_unit: dict[int, list[int]] = {}
        for i, room in enumerate(plan.rooms, 1):
            if room.unit:
                by_unit.setdefault(room.unit, []).append(i)

        def pieces(members: list[int]) -> list[set[int]]:
            left, out = set(members), []
            while left:
                seed = left.pop()
                piece, stack = {seed}, [seed]
                while stack:
                    cur = stack.pop()
                    for n in adj[cur]:
                        if n in left:
                            left.remove(n)
                            piece.add(n)
                            stack.append(n)
                out.append(piece)
            return out

        def reaches(piece: set[int]) -> bool:
            return any(not (room.unit or room.is_shaft or room.access_role)
                       for i in piece for n in adj[i] if (room := plan.rooms[n - 1]))

        changed = False
        next_unit = max(by_unit, default=0) + 1
        for unit, members in by_unit.items():
            parts = pieces(members)
            if len(parts) == 1 and reaches(parts[0]):
                continue
            touching = [part for part in parts if reaches(part)]
            # Every separate piece that reaches the corridor becomes its own
            # flat; the first keeps the flat's number.
            for extra in touching[1:]:
                for i in extra:
                    plan.rooms[i - 1].unit = next_unit
                next_unit += 1
                changed = True
            for part in parts:
                if reaches(part):
                    continue
                border: dict[int, int] = {}
                for i in part:
                    for n, length in adj[i].items():
                        u = plan.rooms[n - 1].unit
                        if u and n not in part:
                            border[u] = border.get(u, 0) + length
                if not border:
                    continue
                into = max(border, key=lambda u: border[u])
                for i in part:
                    plan.rooms[i - 1].unit = into
                merged.add(into)
                changed = True
            if changed:
                break
        if not changed:
            break
    return merged
