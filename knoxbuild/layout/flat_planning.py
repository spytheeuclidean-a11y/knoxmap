"""Improve apartment room shapes and door routes on the final dwelling footprint."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import chain

from ..sizing import SIZES
from .access import door_sides
from .balconies import Balcony, balcony_strips
from .core import Plan, Room
from .malls import _renumber
from .openings import FLAT_END_ROOMS, _door_spot, _room_at
from .oriented import Axis, project

Tile = tuple[int, int]
Edge = tuple[int, int, str]
Cells = frozenset[Tile]
Rooms = tuple[tuple[str, Cells], ...]
BEDROOMS = {"bedroom", "kidsbedroom"}
HABITABLE = BEDROOMS | {"livingroom", "openplan"}
BEDROOM_TRIALS = 3
FOYER_RECTS = (((2, 3), (3, 2)), ((2, 4), (4, 2), (3, 3)),
               ((2, 5), (5, 2), (3, 4), (4, 3)))
BEDROOM_RECTS = ((3, 4), (4, 3), (4, 4), (4, 5), (5, 4), (5, 5))
KITCHEN_RECTS = ((2, 3), (3, 2), (3, 3), (3, 4), (4, 3), (4, 4))
BATH_RECTS = ((3, 2), (2, 3), (3, 3), (2, 2))
STUDIO_LIVING_MIN = 16
MIN_STUDIO_AREA = STUDIO_LIVING_MIN + 4  # A 2x2 bathroom at minimum.


def _neighbors(tile: Tile):
    x, y = tile
    return ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))


def _bounds(cells: Cells) -> tuple[int, int, int, int]:
    xs, ys = zip(*cells)
    return min(xs), min(ys), max(xs), max(ys)


def _connected(cells: Cells) -> bool:
    if not cells:
        return False
    start = next(iter(cells))
    left = set(cells) - {start}
    stack = [start]
    while stack and left:
        for other in _neighbors(stack.pop()):
            if other in left:
                left.remove(other)
                stack.append(other)
    return not left


def _wraps(cells: Cells, shell: Cells) -> bool:
    """A row or column of the room must not reappear behind another room.

    A gap in the building itself ends a scan. This admits L-shaped rooms and
    stepped diagonal walls, while rejecting rings and U-shaped leftovers.
    """
    x0, y0, x1, y1 = _bounds(cells)
    for x, y in cells:
        for dx, dy, limit in ((1, 0, x1 - x), (0, 1, y1 - y)):
            p = x + dx, y + dy
            if limit < 2 or p in cells:
                continue
            for step in range(2, limit + 1):
                if p not in shell:
                    break
                p = x + dx * step, y + dy * step
                if p in cells:
                    return True
    return False


def _room_cost(kind: str, cells: Cells, axis: Axis | None = None) -> float:
    size = SIZES.get(kind)
    if size is None:
        return 0
    x0, y0, x1, y1 = _bounds(cells)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    alignment = 0.
    if axis is not None and kind in BEDROOMS | {"livingroom", "openplan", "kitchen"}:
        xs, ys = zip(*(project(p, axis) for p in cells))
        w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        alignment = 8 * max(0, w * h / len(cells) - 1.2)
    elif kind in ("livingroom", "openplan"):
        # A bigger entrance can leave an L around a bedroom. The remaining
        # living room still needs one usable body instead of two narrow legs.
        alignment = 12 * max(0, w * h / len(cells) - 1.25)
    # The game can furnish a small bathroom with two clear cells per side.
    minimum = {"bathroom": 4, "bedroom": 12, "kitchen": 6}.get(kind, size.lo)
    usable_width = 3 if kind in HABITABLE else 2
    aspect = max(w, h) / min(w, h)
    return (max(0, minimum - len(cells)) + max(0, len(cells) - size.hi)
            + 5 * max(0, aspect - size.aspect) + 7 * max(0, usable_width - min(w, h))
            + 0.1 * abs(len(cells) - size.target) + alignment)


def _wall(a: Cells, b: Cells, occupied: set[Tile]) -> Edge | None:
    if len(a) > len(b):
        a, b = b, a
    edges = []
    for x, y in a:
        for nx, ny in _neighbors((x, y)):
            if (nx, ny) in b and (max(x, nx), max(y, ny)) not in occupied:
                edges.append((max(x, nx), max(y, ny), "W" if x != nx else "N"))
    if not edges:
        return None
    # Give the frame a straight wall when there is a choice on this boundary.
    straight = [e for e in edges
                if (e[0] - (e[2] == "N"), e[1] - (e[2] == "W")) in
                (a if e[:2] in a else b)]
    # Prefer a threshold with room to turn on both sides of the opening.
    roomy = []
    for e in straight or edges:
        p, q = door_sides(e)
        if p not in a:
            p, q = q, p
        if (sum(n in a for n in _neighbors(p)) >= 2
                and sum(n in b for n in _neighbors(q)) >= 2):
            roomy.append(e)
    door, _ = _door_spot(roomy or straight or edges, 1)
    return door


def _touches(a: Cells, b: Cells) -> bool:
    if len(a) > len(b):
        a, b = b, a
    return any(other in b for tile in a for other in _neighbors(tile))


def _rectangles(cells: Cells, anchors: set[Tile], sizes):
    seen = set()
    for w, h in sizes:
        for x, y in sorted(anchors):
            for left in range(x - w + 1, x + 1):
                for top in range(y - h + 1, y + 1):
                    rect = frozenset((i, j) for i in range(left, left + w)
                                     for j in range(top, top + h))
                    if rect <= cells and rect not in seen:
                        seen.add(rect)
                        yield rect


def _body_cuts(body: Cells, entry: Cells, kind: str, axis: Axis | None = None):
    """Cut off one room while keeping a connected, accessible living area."""
    x0, y0, x1, y1 = _bounds(body)
    corners = {(x0, y0), (x1, y0), (x0, y1), (x1, y1)} & body
    sizes = KITCHEN_RECTS if kind == "kitchen" else BEDROOM_RECTS
    minimum = 6 if kind == "kitchen" else 9
    seen = set()
    for room in chain(_rectangles(body, corners, sizes), _strip_cuts(body, axis)):
        if room in seen or len(room) < minimum or len(body) - len(room) < 12:
            continue
        seen.add(room)
        rest = body - room
        if (not entry or _touches(entry, rest)) and _connected(room) and _connected(rest):
            yield room, rest


def _strip_cuts(cells: Cells, axis: Axis | None):
    points = {p: tuple(map(round, project(p, axis))) if axis is not None else p for p in cells}
    for dim in (0, 1):
        first = min(p[dim] for p in points.values())
        last = max(p[dim] for p in points.values())
        for line in range(first + 2, last, max(1, (last - first) // 16)):
            left = frozenset(p for p, coords in points.items() if coords[dim] < line)
            yield left
            yield cells - left


@dataclass(frozen=True)
class _Layout:
    rooms: Rooms
    doors: tuple[Edge, ...]
    cost: float
    balcony: Balcony | None = None


VariantCache = dict[tuple[Cells, Tile, Edge, int, bool, Axis | None, Cells, Cells,
                          tuple[Balcony, ...]], _Layout | None]


def _entry_depth(hall: Cells, front: Edge) -> int:
    a, b = door_sides(front)
    inside, outside = (a, b) if a in hall else (b, a)
    x, y = inside
    dx, dy = x - outside[0], y - outside[1]
    depth = 1
    while (x + dx * depth, y + dy * depth) in hall:
        depth += 1
    return depth


def _quality(rooms: Rooms, routes: dict[int, tuple[int, ...]], bedrooms: int,
             separate_kitchen: bool, front: Edge, axis: Axis | None = None) -> float:
    cost = sum(_room_cost(kind, cells, axis) for kind, cells in rooms)
    kinds = [kind for kind, _ in rooms]
    cost += 14 * max(0, bedrooms - sum(kind in BEDROOMS for kind in kinds))
    cost += 40 * (len(rooms) - len(routes))
    cost += 4 * max(0, kinds.count("hall") - 1) + 5 * ("bathroom" not in kinds)
    cost += 8 * (not any(kind in ("kitchen", "openplan") for kind in kinds))
    cost += 2 * (separate_kitchen and "kitchen" not in kinds)
    entry = next(i for i, path in routes.items() if len(path) == 1)
    cost += 28 * (kinds[entry] in FLAT_END_ROOMS | {"kitchen"})
    if kinds[entry] == "hall":
        hall = rooms[entry][1]
        exits = sum(len(path) == 2 for path in routes.values())
        # Leave room to step in and turn. More doors need more standing
        # space and come at a cost even in a hall big enough to fit them.
        wanted = 6 + 2 * max(0, exits - 2)
        cost += 5 * max(0, wanted - len(hall)) + 3 * max(0, exits - 3)
        cost += 3 * max(0, (3 if exits > 2 else 2) - _entry_depth(hall, front))
        cost += 4 * (not _tile_square(hall, 2))
        living = frozenset().union(*(cells for kind, cells in rooms if kind in ("livingroom", "openplan")))
        sides = sum(any((x + dx, y + dy) in living for x, y in hall)
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        cost += 4 * max(0, sides - 2)
    elif sum(len(cells) for _, cells in rooms) > 32:
        cost += 18  # Prefer a distinct threshold in a larger home.
    for i, path in routes.items():
        approach = [kinds[j] for j in path[:-1]]
        cost += max(0, len(path) - 3) * 4
        cost += sum(18 for kind in approach if kind in FLAT_END_ROOMS or kind == "storage")
        if kinds[i] in FLAT_END_ROOMS:
            cost += 14 * ("kitchen" in approach)
            cost += (14 if kinds[i] == "bathroom" else 10) * any(
                kind in ("openplan", "livingroom") for kind in approach)
    return cost


def _candidate(rooms: Rooms, front: Edge, bedrooms: int, separate_kitchen: bool,
               axis: Axis | None = None) -> _Layout | None:
    occupied = {front[:2]}
    doors = [front]
    routes = {0: (0,)}
    # Route through circulation first, then through the shared living room
    # where necessary. Bedrooms, the bathroom and the kitchen are destinations.
    order = sorted(range(1, len(rooms)), key=lambda i: rooms[i][0] not in ("livingroom", "openplan"))
    for i in order:
        for parent in routes:
            if rooms[parent][0] in ("hall", "openplan", "livingroom"):
                edge = _wall(rooms[parent][1], rooms[i][1], occupied)
                if edge is not None:
                    break
        else:
            return None
        occupied.add(edge[:2])
        doors.append(edge)
        routes[i] = (*routes[parent], i)
    return _Layout(rooms, tuple(doors), _quality(rooms, routes, bedrooms, separate_kitchen, front, axis))


def _habitable_wings(body: Cells, hall: Cells, bedrooms: int):
    """The hall may divide the apartment into separate day and night wings."""
    remaining = set(body)
    wings = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        pending = [seed]
        wing = {seed}
        while pending:
            for p in _neighbors(pending.pop()):
                if p in remaining:
                    remaining.remove(p)
                    wing.add(p)
                    pending.append(p)
        if len(wing) < 9 or not _touches(hall, wing):
            return ()
        wings.append(frozenset(wing))
        if len(wings) > bedrooms + 1:
            return ()
    return tuple(wings)


def _service_zones(shell: Cells, first: Tile, front: Edge, bedrooms: int,
                   facade: Cells, axis: Axis | None):
    """Try an entrance strip, then a hall running alongside the day rooms."""
    boundary = {p for p in shell if any(q not in shell for q in _neighbors(p))}
    strips = {band for band in _strip_cuts(shell, axis)
              if first in band and 8 <= len(band) <= (24 if bedrooms <= 1 else 30)}
    bands = sorted(strips, key=lambda band: (len(band & facade), abs(len(band) - 14),
                                             min(band), max(band)))
    for band in bands[:3]:
        body = shell - band
        if len(body) < STUDIO_LIVING_MIN:
            continue
        baths = _rectangles(band - {first}, band & boundary, BATH_RECTS)
        for bath in sorted(baths, key=lambda room: (len(room & facade), abs(len(room) - 6))):
            hall = band - bath
            if (_tile_square(hall, 2) and _connected(hall) and not _wraps(hall, shell)
                    and (wings := _habitable_wings(body, hall, bedrooms))):
                yield hall, bath, wings
                break

    hall_sizes = FOYER_RECTS
    if bedrooms >= 2:
        # A longer room can serve as a shared route to the private rooms.
        hall_sizes += (((2, 6), (6, 2), (2, 7), (7, 2)),)
    for sizes in hall_sizes:
        found = 0
        boxes = list(_rectangles(shell, {first}, sizes))
        if not boxes:
            # A door at a stepped corner can reach a well-sized hall by
            # turning immediately on the other side of the threshold.
            around = set(_neighbors(first)) & shell
            boxes = [hall | {first} for hall in _rectangles(shell - {first}, around, sizes)]
        halls = sorted(boxes,
                       key=lambda hall: (len(hall & facade), -min(4, _entry_depth(hall, front))))
        for hall in halls:
            adjacent = {other for tile in hall for other in _neighbors(tile)} & (shell - hall)
            baths = _rectangles(shell - hall, adjacent, BATH_RECTS)
            for bath in sorted(baths, key=lambda bath: (len(bath & facade), abs(len(bath) - 6))):
                body = shell - hall - bath
                if (len(body) >= STUDIO_LIVING_MIN
                        and (wings := _habitable_wings(body, hall, bedrooms))):
                    yield hall, bath, wings
                    found += 1
                    break
            if found == 2:
                break

    # A compact studio can give the front door directly to the day room.
    if bedrooms <= 1:
        baths = _rectangles(shell - {first}, boundary, BATH_RECTS)
        found = 0
        for bath in sorted(baths, key=lambda room: (
            min(abs(x - first[0]) + abs(y - first[1]) for x, y in room)
            + 2 * len(room & facade) + 2 * abs(len(room) - 6),
            len(room & facade),
        )):
            body = shell - bath
            if (len(body) >= STUDIO_LIVING_MIN and not _wraps(body, shell) and _connected(body)):
                yield frozenset(), bath, (body,)
                found += 1
                if found == 3:
                    break


def _variants(shell: Cells, first: Tile, front: Edge, bedrooms: int, kitchen: bool,
              facade: Cells, axis: Axis | None, valid, required_living: Cells = frozenset()):
    for hall, bath, wings in _service_zones(shell, first, front, bedrooms, facade, axis):
        if hall and not valid(hall):
            continue
        cuts = []
        for wing in wings:
            if len(wing) >= STUDIO_LIVING_MIN and required_living <= wing:
                beds = tuple(room for room in wings if room != wing)
                if all(valid(room) for room in beds):
                    cuts.append((wing, beds))
        visited = set()
        for count in range(len(wings) - 1, bedrooms + 1):
            next_cuts = []
            for living, beds in cuts:
                entries = [(living, frozenset())]
                if hall and kitchen and len(living) >= 26:
                    separate = _body_cuts(living, hall or frozenset({first}), "kitchen", axis)
                    choices = sorted(separate, key=lambda pair: _room_cost("kitchen", pair[0], axis)
                                     + _room_cost("livingroom", pair[1], axis)
                                     + _window_cost(pair[1], facade))
                    entries.extend((rest, cooking) for cooking, rest in choices[:2])
                for rest, cooking in entries:
                    if len(rest) < STUDIO_LIVING_MIN or not required_living <= rest:
                        continue
                    kind = "livingroom" if cooking else "openplan"
                    if hall:
                        rooms = (("hall", hall), ("bathroom", bath), (kind, rest))
                    else:
                        if first not in rest:
                            continue
                        rooms = ((kind, rest), ("bathroom", bath))
                    extras = (*(("bedroom", bed) for bed in beds),
                              *((("kitchen", cooking),) if cooking else ()))
                    rooms += extras
                    if not all(valid(cells) for _, cells in rooms):
                        continue
                    if candidate := _candidate(rooms, front, bedrooms, kitchen, axis):
                        yield candidate
                if count == bedrooms:
                    continue
                for bed, rest in _body_cuts(living, hall, "bedroom", axis):
                    if not required_living <= rest or not valid(bed):
                        continue
                    if not hall and first not in rest:
                        continue
                    if any(not _touches(rest, cells) and not _touches(hall, cells)
                           for cells in (*beds, bed)):
                        continue
                    key = rest, frozenset((*beds, bed))
                    if key not in visited:
                        visited.add(key)
                        next_cuts.append((rest, (*beds, bed)))
            cuts = sorted(next_cuts, key=lambda pair: _room_cost("openplan", pair[0], axis)
                          + _window_cost(pair[0], facade)
                          + sum(_room_cost("bedroom", bed, axis) + _window_cost(bed, facade)
                                + 14 * (not _tile_square(bed, 3))
                                + 7 * (bool(hall) and not _touches(hall, bed))
                                for bed in pair[1]))[:BEDROOM_TRIALS]
            if not cuts:
                break


def _tile_square(cells: Cells, side: int) -> bool:
    return any(all((x + i, y + j) in cells for i in range(side) for j in range(side))
               for x, y in cells)


def _window_cost(cells: Cells, facade: Cells) -> int:
    """Reserve enough outside wall to place a window away from its corners."""
    frontage = len(cells & facade)
    return 28 if not frontage else 4 * max(0, 3 - frontage)


def _daylight_shape(cells: Cells, facade: Cells, axis: Axis | None) -> float:
    points = [project(p, axis) for p in cells] if axis is not None else cells
    xs, ys = zip(*points)
    box = (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1)
    return (_window_cost(cells, facade)
            + 10 * max(0, box / len(cells) - 1.25)
            + 18 * (not _tile_square(cells, 3)))


def _compact_cost(rooms: Rooms, bedrooms: int) -> float:
    by_kind = {kind: cells for kind, cells in rooms}
    wet = by_kind.get("bathroom", frozenset())
    hall = by_kind.get("hall", frozenset())
    living = by_kind.get("openplan", by_kind.get("livingroom", frozenset()))
    # A living room biting around three sides of a bathroom spends its
    # apparent floor area on the path around the service block.
    sides = sum(any((x + dx, y + dy) in living for x, y in wet)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
    return (45 * (not wet) + (11 * max(0, 6 - len(wet)) if wet else 0)
            + 12 * max(0, sides - 2)
            + 26 * max(0, bedrooms - sum(kind in BEDROOMS for kind, _ in rooms))
            + 3 * max(0, len(hall) - (10 if bedrooms else 8)))


def _open_living_passages(plan: Plan) -> None:
    """Keep privacy doors and make the doorway into the living room open."""
    doors = []
    for edge in plan.doors:
        a, b = (_room_at(plan, *p) for p in door_sides(edge))
        if a and b and a != b:
            left, right = plan.rooms[a - 1], plan.rooms[b - 1]
            if left.unit and left.unit == right.unit and not (left.surveyed or right.surveyed):
                hall, living = (left, right) if left.apartment_entry else (right, left)
                if hall.apartment_entry and hall.kind == "hall" and living.kind in ("livingroom", "openplan"):
                    plan.open_edge.add(edge)
                    continue
        doors.append(edge)
    plan.doors = doors


def replan_flats(plan: Plan, merged_units: set[int],
                 variant_cache: VariantCache | None = None, axis: Axis | None = None,
                 *, balcony_rng=None) -> None:
    """Choose a connected, non-wrapping partition of each final dwelling shell."""
    groups: dict[int, dict[int, set[Tile]]] = defaultdict(lambda: defaultdict(set))
    for y, row in enumerate(plan.grid):
        for x, index in enumerate(row):
            if index and (unit := plan.rooms[index - 1].unit):
                groups[unit][index].add((x, y))
    facade = frozenset((x, y) for y, row in enumerate(plan.grid) for x, i in enumerate(row) if i
                       and any(not _room_at(plan, *p) and
                               (max(x, p[0]), max(y, p[1]), "W" if x != p[0] else "N") not in plan.party
                               for p in _neighbors((x, y))))
    shaft_border = frozenset(p for (x0, y0, x1, y1), _ in plan.shafts
                             for p in chain(((x, y) for x in range(x0, x1 + 1)
                                             for y in (y0 - 1, y1 + 1)),
                                            ((x, y) for y in range(y0, y1 + 1)
                                             for x in (x0 - 1, x1 + 1))))
    balconies = balcony_strips(plan) if balcony_rng is not None else {}
    explicit_balcony = getattr(plan.profile, "apartment_balconies", None) is True
    for unit, parts in groups.items():
        if any(plan.rooms[i - 1].surveyed for i in parts):
            continue
        ids = list(parts)
        indices = {room: i for i, room in enumerate(ids)}
        edges: dict[int, set[int]] = defaultdict(set)
        front = first = None
        old_edges = set()
        for edge in chain(plan.doors, sorted(plan.open_edge)):
            a, b = door_sides(edge)
            i, j = _room_at(plan, *a), _room_at(plan, *b)
            if i in parts and j in parts:
                edges[indices[i]].add(indices[j])
                edges[indices[j]].add(indices[i])
            elif i in parts or j in parts:
                entry, first = (indices[i], a) if i in parts else (indices[j], b)
                front = edge
            else:
                continue
            old_edges.add(edge)
        if front is None:
            continue
        rooms = tuple((plan.rooms[i - 1].kind, frozenset(parts[i])) for i in ids)
        shell = frozenset().union(*(cells for _, cells in rooms))
        previous_bedrooms = sum(kind in BEDROOMS for kind, _ in rooms)
        affordable = max(0, (len(shell) - 28) // 14)
        bedrooms = min(3, max(min(previous_bedrooms, affordable), (len(shell) - 28) // 26))
        kitchen = any(kind == "kitchen" for kind, _ in rooms)
        routes = {entry: (entry,)}
        queue = deque([entry])
        while queue:
            i = queue.popleft()
            for j in edges[i] - routes.keys():
                routes[j] = (*routes[i], j)
                queue.append(j)
        compact = bedrooms <= 1
        windows = facade & shell
        against_shaft = shaft_border & shell
        decks = ()
        if unit in balconies and (explicit_balcony or len(shell) >= 40 and balcony_rng.random() < .65):
            living = frozenset().union(*(cells for kind, cells in rooms
                                         if kind in ("openplan", "livingroom")))
            possible = (deck for deck in balconies[unit]
                        if first not in deck.tiles and len(shell - deck.tiles) >= MIN_STUDIO_AREA)
            ordered = sorted(possible, key=lambda deck: (
                -(len(deck.tiles & living) + len(deck.frontage & living)),
                -len(deck.frontage), -len(deck.tiles), deck.door))
            decks = tuple(dict.fromkeys(ordered))[:4 if explicit_balcony else 2]

        @lru_cache(maxsize=1024)
        def valid(cells):
            return not _wraps(cells, shell)

        @lru_cache(maxsize=256)
        def shape(rooms):
            # Give the shaft wall to a bath or foyer when the dwelling fits.
            noise = 0
            if against_shaft:
                noise = sum((9 if kind in BEDROOMS else 2) * len(cells & against_shaft)
                            for kind, cells in rooms if kind not in {"bathroom", "hall", "closet", "storage"})
            daylight = sum(_daylight_shape(cells, windows, axis)
                           for kind, cells in rooms if kind in HABITABLE)
            return noise + daylight + (_compact_cost(rooms, bedrooms) if compact else 0)

        current = _quality(rooms, routes, bedrooms, kitchen, front, axis) + shape(rooms)
        keep_current = (unit not in merged_units and len(routes) == len(rooms)
                        and all(valid(cells) for _, cells in rooms))
        if keep_current and current < 4 and not decks:
            continue
        key = shell, first, front, bedrooms, kitchen, axis, windows, against_shaft, decks
        if variant_cache is not None and key in variant_cache:
            best = variant_cache[key]
        else:
            def candidates(deck=None, programme=bedrooms):
                indoor = shell - deck.tiles if deck is not None else shell
                required = deck.frontage if deck is not None else frozenset()
                for option in _variants(indoor, first, front, programme, kitchen,
                                        windows & indoor, axis, valid, required):
                    if deck is not None and not any(
                        kind in ("openplan", "livingroom") and required <= cells
                        and len(cells & windows) >= 2 and _tile_square(cells, 3)
                        for kind, cells in option.rooms
                    ):
                        continue
                    yield option

            best = min(candidates(), key=lambda candidate: candidate.cost + shape(candidate.rooms),
                       default=None)
            if best is None and bedrooms > 1:
                # Keep the bathroom and a usable living area when the
                # requested bedrooms cannot be fitted around this entrance.
                best = min(candidates(programme=1), key=lambda c: c.cost + shape(c.rooms),
                           default=None)
            indoor_cost = best.cost + shape(best.rooms) if best is not None else float("inf")
            has_foyer = best is not None and best.rooms[0][0] == "hall"
            for deck in decks:
                # Optional outdoor space must not remove a viable entrance hall.
                options = (c for c in candidates(deck) if not has_foyer or c.rooms[0][0] == "hall")
                choice = min(options, key=lambda c: c.cost + shape(c.rooms), default=None)
                # An inferred balcony must still leave a comparable indoor layout.
                if choice is not None and (explicit_balcony or
                                           choice.cost + shape(choice.rooms) <= indoor_cost + 12):
                    best = replace(choice, balcony=deck)
                    break
            if variant_cache is not None:
                variant_cache[key] = best
        if best is None and unit in merged_units and _connected(shell):
            best = _candidate((("openplan", shell),), front, bedrooms, kitchen, axis)
        if best is None or (best.balcony is None and keep_current
                            and best.cost + shape(best.rooms) >= current):
            continue
        for i, (kind, cells) in enumerate(best.rooms):
            plan.rooms.append(Room(*_bounds(cells), kind=kind, unit=unit, fixed=True,
                                   apartment_entry=i == 0))
            for x, y in cells:
                plan.grid[y][x] = len(plan.rooms)
        plan.doors = [edge for edge in plan.doors if edge not in old_edges]
        plan.open_edge.difference_update(old_edges)
        plan.doors.extend(best.doors)
        if best.balcony is not None:
            deck = best.balcony
            plan.rooms.append(Room(*_bounds(deck.tiles), kind="hall", unit=unit, fixed=True,
                                   access_role="flat_balcony"))
            for x, y in deck.tiles:
                plan.grid[y][x] = len(plan.rooms)
            plan.doors.append(deck.door)
            plan.railing.update(deck.railing)
    _renumber(plan)
    _open_living_passages(plan)
