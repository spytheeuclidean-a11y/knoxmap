"""Malls: concourse, arms, anchors, units, kiosks and the doors between them."""
from __future__ import annotations

import random
from .core import MAX_DEPTH, MIN_ROOM, Plan, Room, SPECIAL_MIXES, _split
from .openings import _boundary_edges, _door_spot, _outside_runs, _room_at



# How much of a mall's depth the concourse takes, and the width it is held
# between. Knox County's mall is 33.6% hall by floor and that hall is one
# room of 5,855 tiles, not a row of corridors: the units open onto it and it
# is where the hundreds of people are. Cut before the units, so it is one
# rectangle rather than whatever the splitter leaves over.
MALL_CONCOURSE_SHARE = 0.16
MALL_CONCOURSE_MIN = 9
MALL_CONCOURSE_MAX = 26
# The gallery either side of the hole on an upper floor. Knox County's mall
# leaves 89% of the ground concourse open to the floor above - 5,185 of its
# 5,855 squares have nothing on them at level 1 - so the two floors read as
# one space. This is how much of the band stays walkable up there.
MALL_GALLERY = 3
# The arms that run off the spine to the far walls: how wide against the
# spine, the bounds on that, how far apart, and how many at most. Knox
# County's concourse is 27% of its bounding box because of these; without
# them a mall is one aisle with rooms down each side.
MALL_ARM_SHARE = 0.60
MALL_ARM_MIN = 5
MALL_ARM_MAX = 8
MALL_ARM_EVERY = 26
MALL_ARMS_MAX = 3
# How far the hole stops short of each end of the spine. The concourse wraps
# round both ends of the opening, which is what joins the two galleries and
# keeps the stairs reachable - so nothing has to bridge the hole and the
# railing runs round one clean opening instead of round each bay.
MALL_HOLE_END = 6

# A mall big enough to be laid out as a US enclosed mall (_mall_plan): two
# anchors with a run of shops and a centre court between them. Anything
# smaller keeps the spine-and-split layout below.
MALL_PLAN_MIN_TILES = 4000
MALL_PLAN_MIN_ACROSS = 36
MALL_PLAN_MIN_LENGTH = 80
# The centre court, square, where the spine widens at its middle.
MALL_COURT = 20
# Anchor department stores: their size, and the size aimed for.
MALL_ANCHOR_MIN = 800
MALL_ANCHOR_MAX = 2500
MALL_ANCHOR_TARGET = 1600
MALL_ANCHOR_LEN = (16, 50)
# Past this a floor has a third and fourth anchor, at the ends of its arms,
# with this much of each arm left between the spine and the anchor's front.
MALL_BIG_FLOOR = 25000
MALL_ARM_STUB = 6
# Inline units: frontage and depth, in tiles. 5-9 by 8-16 is 40-150 tiles,
# the mid-size shop a US mall is lined with.
MALL_UNIT_FRONT = (5, 9)
MALL_UNIT_DEPTH = (8, 16)
MALL_UNIT_MIN_TILES = MALL_UNIT_FRONT[0] * MALL_UNIT_DEPTH[0]
# The service corridor behind each row of units, and the passage from each
# end of it to the outside where storerooms stand between it and the wall.
# Three wide: a strip two tiles thick and that short is folded away as a
# sliver (_mend_fragments).
MALL_SERVICE = 2
MALL_EXIT_WIDE = 3
# The big-store kinds an anchor may be, when the map's own shops name one.
ANCHOR_KINDS = {"departmentstore", "grocery", "furniturestore",
                "electronicsstore", "sportstore"}
# The food court's counters, one of each, in a row behind the seating. Each
# is MALL_COUNTER_FRONT across and 4-6 deep: 20-30 tiles, a kitchen and a
# serving counter, which is what a food court unit is.
FOOD_COUNTERS = ["pizzakitchen", "burgerkitchen", "chinesekitchen",
                 "icecreamkitchen", "mexicankitchen"]
MALL_COUNTER_FRONT = 5
MALL_COUNTER_DEPTH = (4, 6)


def _mall_anchor_len(across: int) -> int:
    """How far along the spine each end anchor runs."""
    return max(MALL_ANCHOR_LEN[0], min(MALL_ANCHOR_LEN[1],
                                       -(-MALL_ANCHOR_TARGET // across)))


def _mall_plan_fits(w: int, h: int, mask) -> bool:
    """Whether a floor this size is laid out by _mall_plan.

    build_building asks too: only a mall laid out this way has a court for
    its lift to stand in. The old layout's hole runs the spine's length and
    a lift there stood in it with the railing across its doors.
    """
    across, length = (h, w) if w >= h else (w, h)
    floor_tiles = sum(map(sum, mask)) if mask is not None else w * h
    anchor_len = _mall_anchor_len(across)
    return (floor_tiles >= MALL_PLAN_MIN_TILES and across >= MALL_PLAN_MIN_ACROSS
            and length >= MALL_PLAN_MIN_LENGTH
            and length - 2 * anchor_len >= MALL_COURT + 4 * MALL_UNIT_FRONT[0])


def _mall_plan(plan: Plan, rng: random.Random, target: int, level: int,
               uses: list | None, shaft: tuple | None = None) -> bool:
    """A US enclosed mall, or False when the floor is too small for one.

    Anchors at the two ends of a concourse spine, a centre court where it
    widens at the middle, mid-size units down both sides of it, and behind
    each row a two-tile service corridor to the lavatories, the office, the
    storerooms and the exits. Every room is cut with its kind and fixed, so
    the mix dealt afterwards leaves them alone.
    """
    w, h = plan.width, plan.height
    if not _mall_plan_fits(w, h, plan.mask):
        return False
    along_x = w >= h
    across, length = (h, w) if along_x else (w, h)
    floor_tiles = sum(map(sum, plan.mask)) if plan.mask is not None else w * h
    anchor_len = _mall_anchor_len(across)
    inner0, inner1 = anchor_len, length - anchor_len - 1
    band = max(MALL_CONCOURSE_MIN,
               min(MALL_CONCOURSE_MAX, round(across * MALL_CONCOURSE_SHARE)))
    start = (across - band) // 2
    end = start + band             # first tile past the spine

    def rect(a0, b0, a1, b1):
        return (a0, b0, a1, b1) if along_x else (b0, a0, b1, a1)

    def put(a0, b0, a1, b1, kind):
        if a1 < a0 or b1 < b0:
            return None
        plan.rooms.append(Room(*rect(a0, b0, a1, b1), kind=kind, fixed=True))
        return plan.rooms[-1]

    def inside(a0, b0, a1, b1):
        if plan.mask is None:
            return (a1 - a0 + 1) * (b1 - b0 + 1)
        x0, y0, x1, y1 = rect(a0, b0, a1, b1)
        return sum(plan.mask[y][x] for y in range(y0, y1 + 1)
                   for x in range(x0, x1 + 1))

    # Each side of the spine: (depth of the block, shop depth, corridor width).
    sides = {}
    for side, d in (("lo", start), ("hi", across - end)):
        shop = min(d - MALL_SERVICE, MALL_UNIT_DEPTH[1])
        spare = d - shop - MALL_SERVICE
        corridor = MALL_SERVICE + (spare if spare < MIN_ROOM else 0)
        sides[side] = (d, shop, corridor)
    # The court eats into the units either side, but leaves them 8 deep.
    extra = max(0, min((MALL_COURT - band) // 2,
                       *(s[1] - MALL_UNIT_DEPTH[0] for s in sides.values())))
    c0 = length // 2 - MALL_COURT // 2
    c1 = c0 + MALL_COURT - 1

    # Anchors 1 and 2 at the ends, the full depth of the building where that
    # stays under MALL_ANCHOR_MAX, centred on the spine where it does not.
    anchors = []
    deep = min(across, MALL_ANCHOR_MAX // anchor_len)
    ab0 = max(0, min(across - deep, (start + end) // 2 - deep // 2))
    for a0 in (0, length - anchor_len):
        anchors.append((a0, ab0, a0 + anchor_len - 1, ab0 + deep - 1))
        put(a0, 0, a0 + anchor_len - 1, ab0 - 1, "storage")
        put(a0, ab0 + deep, a0 + anchor_len - 1, across - 1, "storage")

    # One arm in the middle of each half, between the anchor and the court.
    arm = max(MALL_ARM_MIN, min(MALL_ARM_MAX, round(band * MALL_ARM_SHARE)))
    arms = []
    for h0, h1 in ((inner0, c0 - 1), (c1 + 1, inner1)):
        if h1 - h0 + 1 >= MALL_ARM_EVERY + arm:
            mid = (h0 + h1) // 2
            arms.append((mid - arm // 2, mid - arm // 2 + arm - 1))
    # Anchors 3 and 4 on a big floor: at the wall end of each arm, the west
    # one on the low side and the east one on the high side.
    side_anchor = {}
    if floor_tiles > MALL_BIG_FLOOR:
        for (m0, m1), side in zip(arms, ("lo", "hi")):
            d = sides[side][0]
            deep3 = d - MALL_ARM_STUB
            if deep3 < MIN_ROOM:
                continue
            wide = min(-(-MALL_ANCHOR_TARGET // deep3), MALL_ANCHOR_MAX // deep3)
            mid = (m0 + m1) // 2
            a0 = mid - wide // 2
            a1 = a0 + wide - 1
            if a0 < inner0 or a1 > inner1 or c0 <= a1 and a0 <= c1:
                continue
            b0, b1 = ((0, start - MALL_ARM_STUB - 1) if side == "lo"
                      else (end + MALL_ARM_STUB, across - 1))
            anchors.append((a0, b0, a1, b1))
            side_anchor[side] = (a0, a1)

    kinds = [f for f, _b in uses or () if f in ANCHOR_KINDS]
    for n, (a0, b0, a1, b1) in enumerate(anchors):
        put(a0, b0, a1, b1, kinds[n] if n < len(kinds) else "departmentstore")
    plan.anchors = [rect(*r) for r in anchors]

    # The concourse: the spine between the anchors, the court on it, the arms.
    # Cut round the court rather than under it: a room painted over the
    # middle of another leaves it in two pieces, and the second became an
    # office in the middle of the mall.
    put(inner0, start, c0 - 1, end - 1, "concourse")
    put(c1 + 1, start, inner1, end - 1, "concourse")
    cb0, cb1 = start - extra, end - 1 + extra
    g = MALL_GALLERY
    if level > 0 and c1 - c0 + 1 - 2 * g >= 3 and cb1 - cb0 + 1 - 2 * g >= 3:
        # Above the ground floor the court is the hole, with a gallery round
        # it; the stairs and the lift stand in it on their own floor, a
        # walkway out to the nearer gallery.
        put(c0, cb0, c1, cb0 + g - 1, "concourse")
        put(c0, cb1 - g + 1, c1, cb1, "concourse")
        put(c0, cb0 + g, c0 + g - 1, cb1 - g, "concourse")
        put(c1 - g + 1, cb0 + g, c1, cb1 - g, "concourse")
        ha0, hb0, ha1, hb1 = c0 + g, cb0 + g, c1 - g, cb1 - g
        keep = set()
        for box in (plan.core, shaft):
            if box is None:
                continue
            x0, y0, x1, y1 = box
            ka0, kb0, ka1, kb1 = (x0, y0, x1, y1) if along_x else (y0, x0, y1, x1)
            if ka1 < ha0 or ka0 > ha1 or kb1 < hb0 or kb0 > hb1:
                continue
            up = (kb0 - hb0) <= (hb1 - kb1)
            wb0, wb1 = (hb0, kb0 - 1) if up else (kb1 + 1, hb1)
            wa0, wa1 = max(ka0, ha0), min(ka1, ha1)
            put(wa0, wb0, wa1, wb1, "concourse")
            keep |= {(a, b) for a in range(wa0, wa1 + 1)
                     for b in range(min(wb0, kb0), max(wb1, kb1) + 1)}
        for a in range(ha0, ha1 + 1):
            for b in range(hb0, hb1 + 1):
                if (a, b) not in keep:
                    plan.void.add((a, b) if along_x else (b, a))
    else:
        put(c0, cb0, c1, cb1, "concourse")
    plan.spine = rect(inner0, start, inner1, end - 1)
    plan.court = rect(c0, start - extra, c1, end - 1 + extra)
    for m0, m1 in arms:
        for side, (d, shop, _c) in sides.items():
            if side in side_anchor and side_anchor[side][0] <= m1 \
                    and m0 <= side_anchor[side][1]:
                b0, b1 = ((start - MALL_ARM_STUB, start - 1) if side == "lo"
                          else (end, end + MALL_ARM_STUB - 1))
            else:
                # Through to the outer wall, past the corridor and the back
                # zone, with shops down both sides (below).
                b0, b1 = ((0, start - 1) if side == "lo"
                          else (end, across - 1))
            put(m0, b0, m1, b1, "concourse")

    # The units, the corridor and whatever is left behind it, side by side.
    shop_kinds = [f for f, _b in uses or () if f in MALL_SHOP_KINDS]
    # Extra tickets make these shops more likely without displacing mapped uses.
    deal = list(MALL_SHOP_KINDS) + ["gunstore", "jewelrystore"]
    rng.shuffle(deal)
    deal = shop_kinds + deal
    dealt = 0
    units: dict = {"lo": [], "hi": []}
    # The food court takes the units off one side of the court, ground floor
    # only: the seating along the court, the counters in a row behind it.
    food_side = rng.choice(("lo", "hi")) if level == 0 else None
    for side, (d, shop, corridor) in sides.items():
        cuts = sorted([(m0, m1) for m0, m1 in arms] + [(c0, c1)]
                      + ([side_anchor[side]] if side in side_anchor else []))
        edge = inner0
        segments = [(c0, c1)]
        for g0, g1 in cuts:
            if g0 > edge:
                segments.append((edge, g0 - 1))
            edge = max(edge, g1 + 1)
        segments.append((edge, inner1))
        for s0, s1 in sorted(segments):
            n = s1 - s0 + 1
            if n <= 0:
                continue
            depth = shop - extra if (s0, s1) == (c0, c1) else shop
            near = start - extra if (s0, s1) == (c0, c1) else start
            far = end + extra if (s0, s1) == (c0, c1) else end
            b0, b1 = ((near - depth, near - 1) if side == "lo"
                      else (far, far + depth - 1))
            if side == food_side and (s0, s1) == (c0, c1):
                back = max(MALL_COUNTER_DEPTH[0],
                           min(MALL_COUNTER_DEPTH[1], depth - 6))
                seat = ((b1 - depth + back + 1, b1) if side == "lo"
                        else (b0, b0 + depth - back - 1))
                row = ((b0, b0 + back - 1) if side == "lo"
                       else (b1 - back + 1, b1))
                put(s0, seat[0], s1, seat[1], "foodcourt")
                count = n // MALL_COUNTER_FRONT
                for k, kind in enumerate(rng.sample(FOOD_COUNTERS, count)):
                    a = s0 + k * MALL_COUNTER_FRONT
                    put(a, row[0], s1 if k == count - 1 else a + MALL_COUNTER_FRONT - 1,
                        row[1], kind)
                continue
            if n < MALL_UNIT_FRONT[0]:
                put(s0, b0, s1, b1, "storage")
                continue
            count = -(-n // MALL_UNIT_FRONT[1])
            a = s0
            for k in range(count):
                front = n // count + (1 if k < n % count else 0)
                # A unit the footprint cuts too small to trade from is a
                # storeroom instead.
                ok = inside(a, b0, a + front - 1, b1) >= MALL_UNIT_MIN_TILES
                room = put(a, b0, a + front - 1, b1,
                           deal[dealt % len(deal)] if ok else "storage")
                if ok:
                    dealt += 1
                    units[side].append(((a, a + front - 1), room))
                a += front
        # The corridor and the back zone run the inner length, broken only
        # by an anchor standing at the end of an arm.
        # and by each arm running through to the wall.
        runs = [(inner0, inner1)]
        if side in side_anchor:
            x0, x1 = side_anchor[side]
            runs = [(inner0, x0 - 1), (x1 + 1, inner1)]
        through = [(m0, m1) for m0, m1 in arms if not (
            side in side_anchor and side_anchor[side][0] <= m1
            and m0 <= side_anchor[side][1])]
        for m0, m1 in through:
            cut = []
            for r0, r1 in runs:
                if r1 < m0 or r0 > m1:
                    cut.append((r0, r1))
                else:
                    cut += [(r0, m0 - 1), (m1 + 1, r1)]
            runs = [(r0, r1) for r0, r1 in cut if r1 >= r0]
        arm_start = {m0 for m0, _m1 in through}
        arm_end = {m1 for _m0, m1 in through}
        for r0, r1 in runs:
            if r1 < r0:
                continue
            at_arm = (r0 - 1 in arm_end, r1 + 1 in arm_start)
            if at_arm[0] and at_arm[1]:
                # Between two arms the corridor still needs a way outside.
                at_arm = (True, False)
            if side == "lo":
                k0, k1 = start - shop - corridor, start - shop - 1
                back = (0, k0 - 1)
            else:
                k0, k1 = end + shop, end + shop + corridor - 1
                back = (k1 + 1, across - 1)
            put(r0, k0, r1, k1, "hall")
            if back[1] >= back[0]:
                # With storerooms between it and the wall, the corridor
                # reaches the outside down a passage at each end. An end
                # that meets an arm has the arm to the wall instead, and
                # shops down its side.
                if not at_arm[0]:
                    put(r0, back[0], r0 + MALL_EXIT_WIDE - 1, back[1], "hall")
                    r0 += MALL_EXIT_WIDE
                if not at_arm[1]:
                    put(r1 - MALL_EXIT_WIDE + 1, back[0], r1, back[1], "hall")
                    r1 -= MALL_EXIT_WIDE
                n = back[1] - back[0] + 1
                for lined, left in ((at_arm[0], True), (at_arm[1], False)):
                    if not lined or r1 < r0:
                        continue
                    deep = MALL_UNIT_DEPTH[0]
                    if r1 - r0 + 1 - deep < MIN_ROOM:
                        deep = r1 - r0 + 1
                    s0, s1 = (r0, r0 + deep - 1) if left else (r1 - deep + 1, r1)
                    if left:
                        r0 = s1 + 1
                    else:
                        r1 = s0 - 1
                    count = max(1, n // MALL_UNIT_FRONT[1])
                    if n < MALL_UNIT_FRONT[0]:
                        put(s0, back[0], s1, back[1], "storage")
                        continue
                    b = back[0]
                    for k in range(count):
                        front = n // count + (1 if k < n % count else 0)
                        ok = inside(s0, b, s1, b + front - 1) >= MALL_UNIT_MIN_TILES
                        put(s0, b, s1, b + front - 1,
                            deal[dealt % len(deal)] if ok else "storage")
                        dealt += ok
                        b += front
                if r1 < r0:
                    continue
                spare: list = []
                box = rect(r0, back[0], r1, back[1])
                _split(*box, rng, MAX_DEPTH, spare, target_area=target,
                       mask=plan.mask)
                for room in spare:
                    room.kind, room.fixed = "storage", True
                plan.rooms.extend(spare)

    # Back of house: the units nearest the court, west of it, become the
    # lavatories and the office on one side and storerooms on the other.
    for side, roles in (("lo", ("bathroom", "bathroom", "office")),
                        ("hi", ("storage", "storage"))):
        west = [u for u in units[side] if u[0][1] < c0]
        for (_span, room), kind in zip(reversed(west), roles):
            room.kind = kind
    return True


def _mall_rooms(plan: Plan, rng: random.Random, target: int,
                level: int = 0, uses: list | None = None,
                shaft: tuple | None = None) -> None:
    """A branching concourse, with the units filling the blocks between it.

    Knox County's mall concourse is not a corridor down the middle: it is a
    wide spine across the building with arms running off it to the far walls,
    and it covers 27% of its own bounding box. A single band covered 100% of
    one and read as a warehouse aisle. The spine and each arm is its own
    rectangle - a Room here is its rectangle, and the doors and the furnishing
    both read it - and they are all concourse, so the game sees one run of
    hall the shopper walks the length of.

    Above the ground floor the middle of the spine is left open (no room, so
    no floor) with a gallery either side, which is how the mall is one space
    several storeys tall.

    A mall big enough is laid out as a US enclosed mall instead (_mall_plan).
    """
    if _mall_plan(plan, rng, target, level, uses, shaft):
        return
    w, h = plan.width, plan.height
    along_x = w >= h
    across, length = (h, w) if along_x else (w, h)
    band = max(MALL_CONCOURSE_MIN,
               min(MALL_CONCOURSE_MAX, round(across * MALL_CONCOURSE_SHARE)))
    if across - band < 2 * MIN_ROOM:
        _split(0, 0, w - 1, h - 1, rng, MAX_DEPTH, plan.rooms,
               target_area=target, mask=plan.mask)
        return
    start = (across - band) // 2

    def put(a0, b0, a1, b1, kind=None, fixed=False):
        """A room in the building's own axes (a = along, b = across)."""
        if a1 < a0 or b1 < b0:
            return
        if along_x:
            plan.rooms.append(Room(a0, b0, a1, b1, kind=kind or "hall",
                                   fixed=fixed) if kind
                              else Room(a0, b0, a1, b1))
        else:
            plan.rooms.append(Room(b0, a0, b1, a1, kind=kind or "hall",
                                   fixed=fixed) if kind
                              else Room(b0, a0, b1, a1))

    def cut(a0, b0, a1, b1):
        if a1 < a0 or b1 < b0:
            return
        box = (a0, b0, a1, b1) if along_x else (b0, a0, b1, a1)
        _split(box[0], box[1], box[2], box[3], rng, MAX_DEPTH, plan.rooms,
               target_area=target, mask=plan.mask)

    # Where the arms meet the spine, worked out first: the hole in an upper
    # floor stops at them, so each arm carries on across as a bridge. Without
    # that the hole cut the storey in two and half the units had no way to
    # the stairs.
    arm = max(MALL_ARM_MIN, min(MALL_ARM_MAX, round(band * MALL_ARM_SHARE)))
    count = max(1, min(MALL_ARMS_MAX, (length - arm) // MALL_ARM_EVERY))
    centres = [round(length * (k + 1) / (count + 1)) for k in range(count)]
    spans = []
    for c in centres:
        a0 = max(0, min(length - arm, c - arm // 2))
        if not spans or a0 > spans[-1][1] + MIN_ROOM:
            spans.append((a0, a0 + arm - 1))
    # The spine, all the way across.
    hole = band - 2 * MALL_GALLERY
    lo_end, hi_end = MALL_HOLE_END, length - 1 - MALL_HOLE_END
    open_middle = level > 0 and hole >= 3 and hi_end - lo_end >= MIN_ROOM
    if open_middle:
        put(0, start, length - 1, start + MALL_GALLERY - 1, "concourse", True)
        put(0, start + band - MALL_GALLERY, length - 1, start + band - 1,
            "concourse", True)
        # The concourse carries on round both ends of the opening, which is
        # what the galleries walk round to reach each other.
        put(0, start + MALL_GALLERY, lo_end - 1,
            start + band - MALL_GALLERY - 1, "concourse", True)
        put(hi_end + 1, start + MALL_GALLERY, length - 1,
            start + band - MALL_GALLERY - 1, "concourse", True)
        for b in range(start + MALL_GALLERY, start + band - MALL_GALLERY):
            for a in range(lo_end, hi_end + 1):
                plan.void.add((a, b) if along_x else (b, a))
    else:
        put(0, start, length - 1, start + band - 1, "concourse", True)

    # The units fill the blocks between the arms.
    for lo, hi in (0, start - 1), (start + band, across - 1):
        if hi < lo:
            continue
        edge = 0
        for a0, a1 in spans:
            cut(edge, lo, a0 - 1, hi)
            put(a0, lo, a1, hi, "concourse", True)
            edge = a1 + 1
        cut(edge, lo, length - 1, hi)
    # The stairs stand in the middle of the building, which is the middle of
    # the concourse, which is where the hole is: left alone they are a landing
    # in mid-air. The core keeps its floor and a walkway of concourse runs
    # from it out to the nearer gallery. Both come out of the hole, and the
    # walkway is a room of its own or it would have no floor either.
    if plan.void and plan.core:
        cx0, cy0, cx1, cy1 = plan.core
        a0, a1, b0, b1 = ((cx0, cx1, cy0, cy1) if along_x
                          else (cy0, cy1, cx0, cx1))
        lo = start + MALL_GALLERY
        hi = start + band - MALL_GALLERY - 1
        if lo <= b1 and b0 <= hi:
            near_top = (b0 - lo) <= (hi - b1)
            wb0, wb1 = (lo, b0 - 1) if near_top else (b1 + 1, hi)
            put(a0, wb0, a1, wb1, "concourse", True)
            for a in range(a0, a1 + 1):
                for b in range(min(wb0, b0), max(wb1, b1) + 1):
                    plan.void.discard((a, b) if along_x else (b, a))


# What may stand on the concourse: what its own wishlist puts there, plus the
# light switches and lamps every room gets. With Erika's Tiles the plants come
# through as erika_plant_*, so these are matched as prefixes.
CONCOURSE_KEEP = {"plant", "erika_plant", "shop_bin", "vending",
                  "erika_vending", "switch", "lamp", "light", "shop_counter"}

# Kiosks down the middle of a wide concourse: a stall of one or two counters
# every so often, where the spine is wide enough to walk either side of one,
# and never in the court or in the way of a door.
MALL_KIOSK_MIN_SPINE = 14
MALL_KIOSK_EVERY = (12, 16)
MALL_KIOSK_DOOR_CLEAR = 3


def _place_kiosks(plan: Plan, rng: random.Random, ground: bool) -> int:
    """Stand kiosks down the spine's centre line; how many went in."""
    if not ground or plan.spine is None:
        return 0
    x0, y0, x1, y1 = plan.spine
    along_x = x1 - x0 >= y1 - y0
    wide = (y1 - y0 + 1) if along_x else (x1 - x0 + 1)
    if wide < MALL_KIOSK_MIN_SPINE:
        return 0
    mid = (y0 + y1) // 2 if along_x else (x0 + x1) // 2
    a, a_end = (x0, x1) if along_x else (y0, y1)
    taken = {(x, y) for _r, x, y, _d in plan.furniture}
    clear = [(x, y) for x, y, _d in plan.doors] + \
            [(x, y) for x, y, _d in plan.open_edge]

    def fits(x, y):
        return (plan.grid[y][x] and (x, y) not in taken
                and not (plan.court and plan.court[0] <= x <= plan.court[2]
                         and plan.court[1] <= y <= plan.court[3])
                and all(abs(cx - x) + abs(cy - y) > MALL_KIOSK_DOOR_CLEAR
                        for cx, cy in clear))

    placed = 0
    a += rng.randint(*MALL_KIOSK_EVERY) // 2
    while a <= a_end:
        stall = [(a + k, mid) if along_x else (mid, a + k)
                 for k in range(rng.choice((1, 2)))]
        if all(c[0] <= x1 and c[1] <= y1 and fits(*c) for c in stall):
            for x, y in stall:
                plan.furniture.append(("shop_counter", x, y,
                                       "S" if along_x else "E"))
            placed += 1
        a += rng.randint(*MALL_KIOSK_EVERY)
    return placed


def _clear_concourse(plan: Plan) -> int:
    """Take off the concourse whatever the units put there.

    A shop is fitted from its own walls out, and a unit whose front is the
    concourse edge lays its wall pieces on the far side of that wall - a
    furniture shop left fourteen dressers standing in the middle of the mall.
    Anything on a concourse tile that is not concourse fitting comes off.
    """
    concourse = {i for i, r in enumerate(plan.rooms, start=1)
                 if r.kind == "concourse"}
    if not concourse:
        return 0
    kept, dropped = [], 0
    for piece in plan.furniture:
        role, x, y = piece[0], piece[1], piece[2]
        inside = (0 <= y < len(plan.grid) and 0 <= x < len(plan.grid[0])
                  and plan.grid[y][x] in concourse)
        if inside and not any(role.startswith(k) for k in CONCOURSE_KEEP):
            dropped += 1
            continue
        kept.append(piece)
    plan.furniture = kept
    return dropped


def _bridge_core(plan: Plan, along_x: bool) -> None:
    """Keep the stairs out of the hole, and a way to them across it.

    The stair core stands in the middle of the building, which is the middle
    of the concourse, which is exactly where the hole goes: left alone it was
    a landing marooned in mid-air with the galleries out of reach either side.
    The core keeps its floor and a walkway runs from it to the nearer gallery.
    """
    if not plan.core:
        return
    cx0, cy0, cx1, cy1 = plan.core
    rows = [y for x, y in plan.void]
    cols = [x for x, y in plan.void]
    lo, hi = (min(rows), max(rows)) if along_x else (min(cols), max(cols))
    for x in range(cx0, cx1 + 1):
        for y in range(cy0, cy1 + 1):
            plan.void.discard((x, y))
    if along_x:
        # Out of the core to whichever edge of the hole is closer.
        up = (cy0 - lo) <= (hi - cy1)
        span = range(lo, cy0) if up else range(cy1 + 1, hi + 1)
        for y in span:
            for x in range(cx0, cx1 + 1):
                plan.void.discard((x, y))
    else:
        left = (cx0 - lo) <= (hi - cx1)
        span = range(lo, cx0) if left else range(cx1 + 1, hi + 1)
        for x in span:
            for y in range(cy0, cy1 + 1):
                plan.void.discard((x, y))


def _atrium_railings(plan: Plan) -> None:
    """Rail the edge of the hole, and take the windows off it.

    A gallery's inner edge borders the hole, which is nothing, and nothing
    reads as outdoors: it was given an exterior wall with windows in it -
    glazing over a two-storey opening inside the building. It gets a railing
    instead, which is what a balcony over a mall floor has.
    """
    if not plan.void:
        return
    h, w = len(plan.grid), len(plan.grid[0])

    def room_at(x, y):
        return plan.grid[y][x] if 0 <= x < w and 0 <= y < h else 0

    for x, y in plan.void:
        # The square west of the hole, and the one north of it, each carry
        # the edge between them on the hole's own square.
        if room_at(x - 1, y) and (x - 1, y) not in plan.void:
            plan.railing.add((x, y, "W"))
        if room_at(x + 1, y) and (x + 1, y) not in plan.void:
            plan.railing.add((x + 1, y, "W"))
        if room_at(x, y - 1) and (x, y - 1) not in plan.void:
            plan.railing.add((x, y, "N"))
        if room_at(x, y + 1) and (x, y + 1) not in plan.void:
            plan.railing.add((x, y + 1, "N"))
    # The windows themselves are placed later, over the whole building
    # (_place_windows), which skips these edges; nothing is on them yet here.


# How much of a unit's frontage stands open to the concourse. Knox County's
# mall has no door at all between a unit and the hall: of 584 boundary
# squares, 305 are wall and 279 are simply open, which is how a shop is
# entered there.
# The rooms in a mall that stand open to the concourse. A lavatory, the
# centre office and the storerooms behind the units keep their wall and door.
GLAZED_UNITS = {"clothesstore", "shoestore", "sewingstore", "electronicsstore",
                "housewarestore", "cornerstore", "optometrist", "departmentstore",
                "giftstore", "toystore", "bookstore", "furniturestore",
                "sportstore", "jewelrystore", "musicstore", "candystore",
                "toolstore", "pharmacy", "generalstore", "gunstore", "bakery",
                "cafe", "foodcourt", "grocery", "conveniencestore",
                "gardenstore", "armysurplus", "hunting", "artstore", "petstore",
                "camerastore"}
# The kinds an inline unit of a mall is let as: the shops of the mall's own
# mix that stand open to the concourse, less the department store, which is
# an anchor's, and the food court, which has a block of its own.
MALL_SHOP_KINDS = list(dict.fromkeys(
    k for k in SPECIAL_MIXES["mall"][0] + SPECIAL_MIXES["mall"][1]
    if k in GLAZED_UNITS and k not in ("departmentstore", "foodcourt")))
SHOP_OPENING = 0.45
MIN_OPENING = 3


def _mall_doors(plan: Plan, rng: random.Random, ground: bool) -> None:
    """The doors a mall's back of house needs that the door tree leaves out.

    The tree gives each room one way in, and for a unit that is its front
    onto the concourse: every unit also gets a back door onto the service
    corridor behind it, each food counter one onto the seating it serves,
    the corridor's pieces doors between them, and on the ground floor an
    exit at each end.
    """
    rooms = plan.rooms
    halls = {i for i, r in enumerate(rooms, 1)
             if r.kind == "hall" and not r.is_core and not r.is_shaft}
    if not halls:
        return
    back = set(MALL_SHOP_KINDS) | set(FOOD_COUNTERS) | {"bathroom", "office",
                                                        "storage", "foodcourt"}
    joined = set()
    for x, y, d in plan.doors:
        a = _room_at(plan, x - 1, y) if d == "W" else _room_at(plan, x, y - 1)
        joined.add(frozenset((a, _room_at(plan, x, y))))
    for (a, b), wall in _boundary_edges(plan).items():
        ka, kb = rooms[a - 1].kind, rooms[b - 1].kind
        wanted = ((a in halls and (b in halls or kb in back or kb == "concourse"))
                  or (b in halls and (ka in back or ka == "concourse"))
                  or {ka, kb} & set(FOOD_COUNTERS) and "foodcourt" in (ka, kb))
        if not wanted or frozenset((a, b)) in joined:
            continue
        spot = _door_spot(wall, 1, rng)
        if spot:
            plan.doors.append(spot[0])
            joined.add(frozenset((a, b)))
    if not ground:
        return
    for i in halls:
        runs = _outside_runs(plan, i)
        if not runs:
            continue
        run = runs[0][1]
        for door in {run[min(1, len(run) - 1)], run[max(0, len(run) - 2)]}:
            if door not in plan.doors:
                plan.doors.append(door)


def _open_shopfronts(plan: Plan) -> None:
    """Open a run of each unit's frontage, and take its door off it."""
    concourse = {i for i, r in enumerate(plan.rooms, start=1)
                 if r.kind == "concourse"}
    if not concourse:
        return
    h, w = len(plan.grid), len(plan.grid[0])
    runs: dict = {}
    frontage: dict = {}
    for y in range(h):
        for x in range(w):
            here = plan.grid[y][x]
            if not here:
                continue
            for nx, ny, d in ((x - 1, y, "W"), (x, y - 1, "N")):
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                there = plan.grid[ny][nx]
                if not there or there == here:
                    continue
                pair = {here, there}
                if not pair & concourse:
                    continue
                unit = (pair - concourse)
                if not unit:
                    continue
                idx = next(iter(unit))
                if plan.rooms[idx - 1].kind not in GLAZED_UNITS:
                    continue
                runs.setdefault((idx, d, x if d == "W" else y), []).append(
                    y if d == "W" else x)
                frontage.setdefault(idx, set()).add((x, y, d))
    opened = set()
    got_opening: set = set()
    for (idx, d, fixed), along in runs.items():
        along.sort()
        spans, run = [], [along[0]]
        for t in along[1:]:
            if t == run[-1] + 1:
                run.append(t)
            else:
                spans.append(run); run = [t]
        spans.append(run)
        best = max(spans, key=len)
        if len(best) < MIN_OPENING:
            continue
        width = max(MIN_OPENING, round(len(best) * SHOP_OPENING))
        start = best[0] + (len(best) - width) // 2
        for t in range(start, start + width):
            opened.add((fixed, t, d) if d == "W" else (t, fixed, d))
        got_opening.add(idx)
    plan.open_edge |= opened
    # A gap in the wall is the way in, and that is the only way in: the game's
    # mall has not one door between a shop and the concourse, so a unit with
    # an opening gives up every door along its frontage, not just the ones
    # the gap swallowed.
    shut = set(opened)
    for idx in got_opening:
        shut |= frontage.get(idx, set())
    plan.doors = [e for e in plan.doors if e not in shut]


def _merge_concourse(plan: Plan) -> None:
    """Make the whole concourse one room, so no wall runs across it.

    The spine, the galleries and the arms are cut as separate rectangles, and
    a wall appears wherever two rooms meet - which walled the concourse off
    from its own arms and made the hall read as a row of corridors. They all
    become one room here. Its rectangle is the whole box they cover, which
    furnishing is safe with: everything that fills a room checks the grid for
    the tiles that are really its own.
    """
    first = next((i for i, r in enumerate(plan.rooms, start=1)
                  if r.kind == "concourse"), None)
    if first is None:
        return
    rest = [i for i, r in enumerate(plan.rooms, start=1)
            if r.kind == "concourse" and i != first]
    if not rest:
        return
    keep = plan.rooms[first - 1]
    for i in rest:
        room = plan.rooms[i - 1]
        keep.x0, keep.y0 = min(keep.x0, room.x0), min(keep.y0, room.y0)
        keep.x1, keep.y1 = max(keep.x1, room.x1), max(keep.y1, room.y1)
        room.kind = None
    drop = set(rest)
    for y, row in enumerate(plan.grid):
        for x, v in enumerate(row):
            if v in drop:
                row[x] = first
    _renumber(plan)


def _merge_halls(plan: Plan) -> int:
    """Run neighbouring halls together into one concourse.

    Only where the two make a rectangle between them: a Room here is its
    rectangle, and the doors and the furnishing both read it, so an L-shaped
    room would put doors and shelving outside the room. Repeated until nothing
    else will join, which turns a row of corridor cells into one long hall.
    """
    merged = 0
    changed = True
    while changed:
        changed = False
        halls = [(i, r) for i, r in enumerate(plan.rooms, start=1)
                 if r.kind == "hall" and not r.is_core and not r.is_shaft]
        for ai, a in halls:
            for bi, b in halls:
                if ai >= bi or a.kind != "hall" or b.kind != "hall":
                    continue
                side_by_side = (a.y0 == b.y0 and a.y1 == b.y1
                                and (a.x1 + 1 == b.x0 or b.x1 + 1 == a.x0))
                stacked = (a.x0 == b.x0 and a.x1 == b.x1
                           and (a.y1 + 1 == b.y0 or b.y1 + 1 == a.y0))
                if not (side_by_side or stacked):
                    continue
                for y in range(b.y0, b.y1 + 1):
                    for x in range(b.x0, b.x1 + 1):
                        if plan.grid[y][x] == bi:
                            plan.grid[y][x] = ai
                a.x0, a.y0 = min(a.x0, b.x0), min(a.y0, b.y0)
                a.x1, a.y1 = max(a.x1, b.x1), max(a.y1, b.y1)
                b.kind = None          # owns no tiles now; _renumber drops it
                merged += 1
                changed = True
                break
            if changed:
                break
    if merged:
        _renumber(plan)
    return merged


def _renumber(plan: Plan) -> None:
    """Drop rooms that own no tiles and close the gaps in the numbering."""
    used = {v for row in plan.grid for v in row if v}
    if len(used) == len(plan.rooms):
        return
    remap = {}
    kept = []
    for idx, room in enumerate(plan.rooms, start=1):
        if idx in used:
            kept.append(room)
            remap[idx] = len(kept)
    for y in range(plan.height):
        for x in range(plan.width):
            v = plan.grid[y][x]
            if v:
                plan.grid[y][x] = remap[v]
    plan.rooms = kept


def _refit(plan: Plan) -> None:
    """Shrink or grow each room's rectangle to the tiles it actually owns."""
    bounds: dict[int, list[int]] = {}
    for y in range(plan.height):
        for x in range(plan.width):
            v = plan.grid[y][x]
            if v:
                b = bounds.setdefault(v, [x, y, x, y])
                b[0], b[1] = min(b[0], x), min(b[1], y)
                b[2], b[3] = max(b[2], x), max(b[3], y)
    for idx, room in enumerate(plan.rooms, start=1):
        if idx in bounds:
            room.x0, room.y0, room.x1, room.y1 = bounds[idx]
