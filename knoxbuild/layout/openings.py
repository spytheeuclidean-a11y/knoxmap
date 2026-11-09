"""Doors, ways in, and the wall runs a door can sit in."""
from __future__ import annotations

from ..sizing import SIZES
from ..uses import FRONT_ROOMS
import random
from .core import HOUSE_OVERSIZE, Plan, RETAIL_ROOMS



def _boundary_edges(plan: Plan) -> dict[tuple[int, int], list[tuple[int, int, str]]]:
    """(room a, room b) with a < b -> every wall edge between them."""
    out: dict[tuple[int, int], list[tuple[int, int, str]]] = {}
    for y in range(plan.height):
        for x in range(plan.width):
            b = plan.grid[y][x]
            if not b:
                continue
            if x > 0:
                a = plan.grid[y][x - 1]
                if a and a != b:
                    out.setdefault((min(a, b), max(a, b)), []).append((x, y, "W"))
            if y > 0:
                a = plan.grid[y - 1][x]
                if a and a != b:
                    out.setdefault((min(a, b), max(a, b)), []).append((x, y, "N"))
    return out


# How far along a wall a door may sit, as a share of the run, and how much
# wall it keeps beside it. Every door used to go at run[len(run) // 2], dead
# centre of the longest wall, which reads as a corridor of identical openings
# rather than as rooms somebody built. Real doors sit off to one side, but not
# hard against the corner: a frame needs a tile beside it.
DOOR_ALONG = (0.18, 0.82)
DOOR_FROM_CORNER = 1


def _door_spot(edges: list[tuple[int, int, str]], min_run: int,
               rng: random.Random | None = None
               ) -> tuple[tuple[int, int, str], int] | None:
    """A place on the longest straight run of wall, and that run's length.

    Somewhere along the run rather than its middle - see DOOR_ALONG. Without
    an rng it still takes the middle, so callers that want the old certainty
    keep it.
    """
    best = None
    for d in ("W", "N"):
        # Along a W edge the wall runs in y; along an N edge, in x.
        keyed = sorted((e[0], e[1]) if d == "W" else (e[1], e[0])
                       for e in edges if e[2] == d)
        run: list[tuple[int, int]] = []
        for fixed, moving in keyed + [(None, None)]:
            if run and (fixed != run[-1][0] or moving != run[-1][1] + 1):
                if len(run) >= min_run and (best is None or len(run) > best[1]):
                    f, m = run[_along(len(run), rng)]
                    spot = (f, m, "W") if d == "W" else (m, f, "N")
                    best = (spot, len(run))
                run = []
            if fixed is not None:
                run.append((fixed, moving))
    return best


def _along(length: int, rng: random.Random | None) -> int:
    """Which tile of a wall run of this length the door goes on."""
    if rng is None or length < 3:
        return length // 2
    low = max(DOOR_FROM_CORNER, int(length * DOOR_ALONG[0]))
    high = min(length - 1 - DOOR_FROM_CORNER, int(length * DOOR_ALONG[1]))
    if high < low:
        return length // 2
    return rng.randint(low, high)


# How much a door between two kinds of room is worth avoiding. Circulation is
# cheap to open onto; rooms a household uses together are cheap to join; a
# bathroom off a kitchen or a bedroom through another bedroom is not how
# anybody builds.
TOGETHER = [{"livingroom", "kitchen"}, {"kitchen", "dining"},
            {"livingroom", "dining"}]
# A flat's front door, by the room it opens into.
FRONT_DOOR_COST = {"livingroom": 0.0, "openplan": 0.0, "hall": 0.5, "kitchen": 1.5,
                   "dining": 1.5, "storage": 6.0, "bedroom": 7.0,
                   "bathroom": 12.0, "motelroom": 0.0}


# Rooms you sleep, wash or work in. A door between two of them is a room you
# have to walk through to reach another, which is what made a plan read as a
# warren rather than a house - the commonest door in a generated town was one
# bedroom into the next. The one pair a real house does have is a bathroom off
# a bedroom, and the kitchen, dining room and living room share their walls
# openly; everything else goes through the hall.
PRIVATE_ROOMS = {"bedroom", "kidsbedroom", "bathroom", "office", "kitchen",
                 "dining", "storage", "closet", "laundry"}
ENSUITE = ({"bedroom", "bathroom"}, {"kidsbedroom", "bathroom"})
# Dear enough that the tree takes any other way round, cheap enough that a
# room with no other wall to open on is still reached rather than sealed.
PRIVATE_PAIR_COST = 24.0
# What each room already walked through costs. The tree took the cheapest
# door anywhere on the frontier, which strings rooms into a chain: a third of
# the rooms in a big flat sat two doors from the front door and some sat four,
# a bedroom through a bathroom through a kitchen. Hanging a room off one that
# is already deep now costs more than hanging it off one near the door, so
# the plan fans out instead of running away from the entrance.
# At this weight three rooms deep costs more than PRIVATE_PAIR_COST, so in
# theory the tree would rather open a bedroom into a bedroom than go on -
# measured, it does not: that pair is 0.6% of doors at this setting and 0.5%
# at a third of it, because the frontier rarely offers the choice.
DEPTH_COST = 9.0


def _door_cost(a: str, b: str) -> float:
    kinds = {a, b}
    if a == b == "hall":
        # Two halls side by side - the stair core and the landing - open onto
        # each other before either opens onto a bedroom.
        cost = 0.5
    elif "hall" in kinds or "lobby" in kinds:
        cost = 1.0
    elif kinds in TOGETHER:
        cost = 1.5
    elif "livingroom" in kinds:
        cost = 3.0
    elif kinds in ENSUITE:
        cost = 4.0
    elif kinds <= PRIVATE_ROOMS:
        cost = PRIVATE_PAIR_COST
    else:
        cost = 6.0
    # Where Knox County's bathrooms open, counted off the compiled map: 614 of
    # its 807 bathroom doors are onto a living room, 56 onto a kitchen, 36 off
    # a bedroom. Ours had the living room on the dear side of this and did
    # 30% of its bathrooms as bedroom en-suites against the game's 4%, so the
    # commonest arrangement in the game was the one we almost never built.
    if ("bathroom" in kinds
            and not kinds & {"hall", "lobby", "livingroom", "bedroom",
                             "kidsbedroom"}):
        cost += 6.0
    # ...and a bathroom off a bedroom is the exception there, not the rule.
    if kinds in ENSUITE:
        cost += 5.0
    return cost


def _doors(plan: Plan, rng: random.Random) -> None:
    """Connect every room, with as few doors as a real plan would have.

    The old rule put a door on every boundary between two rooms. A floor where
    every room opens into every room it touches is a maze of doorways, not a
    home. This grows a tree outward from the circulation instead - hall, then
    living room - choosing the cheapest door each time, so a bedroom gets the
    one door it needs and a bathroom opens off a hall rather than a kitchen.

    Flats are enforced here as well: rooms of the same flat may open onto each
    other, a flat opens onto the corridor once, and two different flats never
    share a door. Only if a room could otherwise not be reached at all are
    those rules relaxed, one at a time, cheapest first.
    """
    n = len(plan.rooms)
    if n <= 1:
        return
    rooms = plan.rooms
    sealed = {i for i, r in enumerate(rooms, 1) if r.is_shaft}
    edges = {k: v for k, v in _boundary_edges(plan).items()
             if k[0] not in sealed and k[1] not in sealed}

    def start_room() -> int:
        # A mall grows from its concourse, not from a service corridor.
        for kind in ("concourse", "hall", "lobby", "livingroom", "openplan"):
            found = [i for i, r in enumerate(rooms, 1) if r.kind == kind]
            # The stairs arrive in the core: grow from there, or a second hall
            # beside it wins on size and the stairs open into a bedroom.
            at_stairs = [i for i in found if rooms[i - 1].is_core]
            if found:
                return max(at_stairs or found, key=lambda i: rooms[i - 1].area)
        return max(range(1, n + 1), key=lambda i: rooms[i - 1].area)

    connected = {start_room()} | sealed
    front: set[int] = set()
    placed: set[tuple[int, int]] = set()
    doors_of: dict[int, int] = {}
    # How many doors from the way in each connected room is, for DEPTH_COST.
    depth: dict[int, int] = {i: 0 for i in connected}

    # Each pass relaxes one rule, and only for rooms still unreached.
    for relax in range(4):
        min_run = 1
        while True:
            best = None
            for (a, b), wall in edges.items():
                if (a in connected) == (b in connected):
                    continue
                ra, rb = rooms[a - 1], rooms[b - 1]
                if ra.unit != rb.unit:
                    flat = ra.unit or rb.unit
                    if ra.unit and rb.unit:
                        if relax < 3:
                            continue
                    elif flat in front and relax < 3:
                        # A flat has one front door. This was relaxed a
                        # pass earlier, and every room that could not be
                        # reached any other way opened its own way onto the
                        # corridor - 101 flats with two or three of them.
                        continue
                spot = _door_spot(wall, min_run, rng)
                if spot is None:
                    continue
                if ra.unit != rb.unit and not (ra.unit and rb.unit):
                    inner = rb if ra.unit == 0 else ra
                    cost = FRONT_DOOR_COST.get(inner.kind, 3.0)
                else:
                    cost = _door_cost(ra.kind, rb.kind)
                # A wall one tile long takes a door, but only if nothing
                # better exists: skipping them outright sent a bedroom through
                # the bathroom to reach a hall it shared a one-tile wall with.
                if spot[1] < 2:
                    cost += 3.0
                # A bathroom is a room you choose to go into, never a way
                # through to somewhere else: once it has its door it takes no
                # other, so nothing is ever reached by walking through it.
                # This was a cost of 12, which the tree simply paid whenever
                # the way round was dearer - 4.8% of rooms were still reached
                # through one. Only the last relax pass may break it, and that
                # runs when the alternative is a room with no door at all.
                if any(rooms[i - 1].kind == "bathroom" and doors_of.get(i)
                       for i in (a, b)):
                    if relax < 2:
                        continue
                    # Last pass: allowed, but dearer than anything else on
                    # the board, so it happens only where a room would
                    # otherwise have no door at all.
                    cost += 100.0
                cost -= min(spot[1], 6) * 0.05
                # Hanging a room off one that is already deep costs more, so
                # the plan fans out from the way in rather than chaining.
                grown = a if a in connected else b
                cost += DEPTH_COST * depth.get(grown, 0)
                if best is None or cost < best[0]:
                    best = (cost, a, b, spot[0])
            if best is None:
                break
            _, a, b, door = best
            plan.doors.append(door)
            placed.add((a, b))
            doors_of[a] = doors_of.get(a, 0) + 1
            doors_of[b] = doors_of.get(b, 0) + 1
            ra, rb = rooms[a - 1], rooms[b - 1]
            if ra.unit != rb.unit and not (ra.unit and rb.unit):
                front.add(ra.unit or rb.unit)
            grown, fresh = (a, b) if a in connected else (b, a)
            depth[fresh] = depth.get(grown, 0) + 1
            connected.add(a)
            connected.add(b)
        if len(connected) == n:
            break

    # A few extra openings between shared rooms of the same household, so a
    # kitchen opens onto both living and dining rooms instead of being reached
    # only through one of them.
    shared = {"livingroom", "kitchen", "dining", "hall", "lobby"}
    for (a, b), wall in edges.items():
        if (a, b) in placed:
            continue
        ra, rb = rooms[a - 1], rooms[b - 1]
        if ra.unit != rb.unit or ra.kind not in shared or rb.kind not in shared:
            continue
        if ra.unit and (ra.kind == "hall" or rb.kind == "hall"):
            continue
        spot = _door_spot(wall, 3, rng)
        if spot and rng.random() < 0.6:
            plan.doors.append(spot[0])

    # A room whose only way in is a bathroom gets a second door, onto any
    # other room of its own household it touches: nobody should have to walk
    # through the bathroom to reach a bedroom.
    baths = {i for i, r in enumerate(rooms, 1) if r.kind == "bathroom"}
    if baths:
        links: dict[int, set[int]] = {}
        for x, y, d in plan.doors:
            a = _room_at(plan, x - 1, y) if d == "W" else _room_at(plan, x, y - 1)
            b = _room_at(plan, x, y)
            if a and b and a != b:
                links.setdefault(a, set()).add(b)
                links.setdefault(b, set()).add(a)
        for i in range(1, n + 1):
            if i in baths or i in sealed or not links.get(i) or not links[i] <= baths:
                continue
            for (a, b), wall in edges.items():
                other = b if a == i else a if b == i else 0
                if not other or other in baths or other in sealed:
                    continue
                if rooms[a - 1].unit != rooms[b - 1].unit:
                    continue
                spot = _door_spot(wall, 1, rng)
                if spot and spot[0] not in plan.doors:
                    plan.doors.append(spot[0])
                    break
    _swap_through_bathrooms(plan)


# What a room reached only through its bathroom becomes when the two swap,
# if the bathroom's space is too small for what it was.
SMALLER_KIND = {"bedroom": "kidsbedroom"}
# Rooms of a home that may change places with their bathroom. A hotel's guest
# room and its closet are cut as a pair and stay as they are.
SWAPS_WITH_BATHROOM = {"bedroom", "kidsbedroom", "kitchen", "office", "storage",
                       "dining", "laundry"}


def _swap_through_bathrooms(plan: Plan) -> int:
    """Swap a room reached only through a bathroom with that bathroom.

    The second-door pass above cannot help a room whose only other walls are
    the outside, the corridor or another flat - most of them flat bedrooms
    and kitchens, 0.73% of rooms. The bathroom is then the inner one, an
    en-suite, and the room gets the bathroom's door onto the rest of the
    home. Only where the bathroom's space is big enough for the room (a
    bedroom may become a child's one) and the room's not too big for a
    bathroom."""
    def links() -> dict[int, set[int]]:
        out: dict[int, set[int]] = {}
        for x, y, d in plan.doors:
            a = _room_at(plan, x - 1, y) if d == "W" else _room_at(plan, x, y - 1)
            b = _room_at(plan, x, y)
            if a and b and a != b:
                out.setdefault(a, set()).add(b)
                out.setdefault(b, set()).add(a)
        return out

    area: dict[int, int] = {}
    for row in plan.grid:
        for v in row:
            if v:
                area[v] = area.get(v, 0) + 1
    swapped = 0
    link = links()
    for i, room in enumerate(plan.rooms, 1):
        if room.kind not in SWAPS_WITH_BATHROOM or room.is_shaft or room.is_core:
            continue
        through = link.get(i, set())
        if len(through) != 1:
            continue
        b = next(iter(through))
        bath = plan.rooms[b - 1]
        if bath.kind != "bathroom" or bath.unit != room.unit or len(link.get(b, ())) < 2:
            continue
        kind = room.kind
        if kind not in SIZES or area.get(i, 0) > HOUSE_OVERSIZE * SIZES["bathroom"].hi:
            continue
        # Room for its furniture, not only its least floor: a bedroom of 14
        # tiles in an odd shape had no space for the bed.
        if area.get(b, 0) < SIZES[kind].target:
            kind = SMALLER_KIND.get(kind, kind)
            if area.get(b, 0) < SIZES[kind].target:
                continue
        room.kind, bath.kind = "bathroom", kind
        swapped += 1
        link = links()
    return swapped


def _room_at(plan: Plan, x: int, y: int) -> int:
    if 0 <= x < plan.width and 0 <= y < plan.height:
        return plan.grid[y][x]
    return 0


def _side_edge(side: str, fixed: int, pos: int) -> tuple[int, int, str]:
    """The wall edge at `pos` along a side line, as _outside_runs keys them."""
    if side in ("N", "S"):
        return (pos, fixed, "N")
    return (fixed, pos, "W")


def _outside_runs(plan: Plan, idx: int) -> list[tuple[str, list[tuple[int, int, str]]]]:
    """A room's exterior walls, as (facing, edges) straight runs, longest first.

    Built per room and per side so that a run is a real stretch of one wall.
    Walking the whole building's edge list instead - every tile's four sides
    interleaved - broke the side walls into runs one tile long, which is why
    windows landed where they did.
    """
    sides: dict[str, dict[int, list[int]]] = {"N": {}, "S": {}, "W": {}, "E": {}}
    for y in range(plan.height):
        for x in range(plan.width):
            if plan.grid[y][x] != idx:
                continue
            if not _room_at(plan, x, y - 1):
                sides["N"].setdefault(y, []).append(x)
            if not _room_at(plan, x, y + 1):
                sides["S"].setdefault(y + 1, []).append(x)
            if not _room_at(plan, x - 1, y):
                sides["W"].setdefault(x, []).append(y)
            if not _room_at(plan, x + 1, y):
                sides["E"].setdefault(x + 1, []).append(y)
    # A wall shared with the next building is not outside.
    for side, lines in sides.items():
        for fixed in list(lines):
            lines[fixed] = [p for p in lines[fixed] if _side_edge(side, fixed, p) not in plan.party]
    runs: list[tuple[str, list[tuple[int, int, str]]]] = []
    for side, lines in sides.items():
        for fixed, positions in lines.items():
            positions.sort()
            run: list[int] = []
            for p in positions + [None]:
                if run and (p is None or p != run[-1] + 1):
                    if side in ("N", "S"):
                        runs.append((side, [(m, fixed, "N") for m in run]))
                    else:
                        runs.append((side, [(fixed, m, "W") for m in run]))
                    run = []
                if p is not None:
                    run.append(p)
    runs.sort(key=lambda r: -len(r[1]))
    return runs


# Where the way in goes, in order of preference. Never straight into a
# bathroom or a bedroom unless there is truly nothing else.
ENTRY_KINDS = ["hall", "lobby", "livingroom", "restaurant", "church",
               "classroom", "clinic", "warehouse", "kitchen", "office",
               "garage", "dining", "storage", "bedroom", "bathroom"]


def _exterior_door(plan: Plan, rng: random.Random,
                   avoid: tuple[int, int] | None = None,
                   street: str | None = None,
                   entrances: list[tuple[float, float, dict]] | None = None) -> None:
    """One way in, into the room a visitor would expect to arrive in.

    `avoid` is the foot of the staircase, so the front door does not open
    straight onto the bottom step.
    """
    if entrances:
        placed = []
        ordered = sorted(entrances, key=_entrance_priority)
        for x, y, tags in ordered:
            edge = _entrance_wall(plan, x, y, tags)
            if edge is None or edge in placed:
                continue
            plan.doors.append(edge)
            placed.append(edge)
        if placed:
            return
    order = {k: i for i, k in enumerate(ENTRY_KINDS)}
    if plan.kind in ("shop", "restaurant"):
        # Customers come in through the shop, not the staff stairs.
        order.update({k: -1 for k in RETAIL_ROOMS | FRONT_ROOMS})
    candidates = sorted((i for i in range(1, len(plan.rooms) + 1)
                         if not plan.rooms[i - 1].is_shaft),
                        key=lambda i: (order.get(plan.rooms[i - 1].kind, 50),
                                       -plan.rooms[i - 1].area))

    def from_stairs(wall) -> float:
        """How far the middle of this wall is from the foot of the stairs."""
        if avoid is None:
            return 0.0
        mid = wall[len(wall) // 2]
        return abs(mid[0] - avoid[0]) + abs(mid[1] - avoid[1])

    def score(run):
        side, wall = run
        # Facing the street, as front doors do; without that the door went on
        # the south wall and half the paths wrapped round houses.
        return (len(wall) >= 3, side == (street or "S"),
                from_stairs(wall), len(wall))

    # The street comes before the room. Taking the best room first and then
    # its best wall put a house's door wherever its hall happened to be, and
    # a hall that does not reach the street side - most of them - turned the
    # house's back on it: 5 houses in 100 had a door on the street. A room
    # anybody would walk in through and a wall on the street beats the room
    # that would have been first; between two such rooms it is the room's own
    # order, then the stairs, then the longer wall, as it always was.
    facing = [(idx, run) for idx in candidates
              if plan.rooms[idx - 1].kind in order
              for run in _outside_runs(plan, idx)
              if run[0] == (street or "S") and len(run[1]) >= 3]
    if not facing:
        # No room anybody would arrive in reaches the street side - a large
        # house cut in wings can have nothing but bedrooms there. Any room
        # but a bathroom or a cupboard on the street beats a door round the
        # back.
        facing = [(idx, run) for idx in candidates
                  if plan.rooms[idx - 1].kind not in ("bathroom", "closet")
                  for run in _outside_runs(plan, idx)
                  if run[0] == (street or "S") and len(run[1]) >= 3]
    if facing:
        idx, (_side, wall) = min(facing, key=lambda ir: (
            order.get(plan.rooms[ir[0] - 1].kind, 50),
            -from_stairs(ir[1][1]), -len(ir[1][1])))
        front = wall[len(wall) // 2]
        plan.doors.append(front)
        _more_ways_in(plan, front)
        return

    for idx in candidates:
        runs = _outside_runs(plan, idx)
        if not runs:
            continue
        side, wall = max(runs, key=score)
        front = wall[len(wall) // 2]
        plan.doors.append(front)
        _more_ways_in(plan, front)
        return


def _widen_vehicle_entry(plan: Plan, street: str | None) -> None:
    """Turn the street-facing garage entry into a three-tile door opening."""
    candidates = []
    for room_id in range(1, len(plan.rooms) + 1):
        for side, wall in _outside_runs(plan, room_id):
            for door in plan.doors:
                if door in wall:
                    candidates.append((side == (street or "S"), len(wall),
                                       door, wall))
    if not candidates:
        return
    _faces_street, _length, entry, wall = max(candidates)
    if len(wall) < 3:
        return
    width = 3
    center = wall.index(entry)
    start = min(max(0, center - width // 2), len(wall) - width)
    opening = wall[start:start + width]
    ordered = [entry] + sorted((edge for edge in opening if edge != entry),
                               key=lambda edge: (abs(wall.index(edge) - center), edge))

    doors = []
    inserted = False
    for door in plan.doors:
        if door == entry and not inserted:
            doors.extend(ordered)
            inserted = True
        elif door not in opening:
            doors.append(door)
    plan.doors = doors
    # Keep the original entry first for driveway placement; export sorts panels spatially.
    plan.garage_door_tiles = tuple(ordered)

def _entrance_priority(entrance: tuple[float, float, dict]) -> tuple:
    """Main and accessible entrances take precedence when choosing the front."""
    tags = entrance[2]
    value = str(tags.get("entrance") or "yes").lower()
    if value == "main":
        rank = 0 if tags.get("wheelchair") == "yes" else 1
    elif tags.get("wheelchair") == "yes":
        rank = 2
    elif value in ("emergency", "service"):
        rank = 3
    elif value == "exit":
        rank = 5
    else:
        rank = 4
    return rank, entrance[1], entrance[0]


def _entrance_wall(plan: Plan, x: float, y: float,
                   tags: dict) -> tuple[int, int, str] | None:
    """Nearest legal exterior wall edge to one mapped entrance node."""
    if str(tags.get("access") or "").lower() == "no":
        return None
    level = tags.get("level")
    if level not in (None, ""):
        values = [part.strip().lower() for part in str(level).split(";")]
        if "ground" not in values:
            try:
                if not any(float(value) == 0 for value in values):
                    return None
            except ValueError:
                return None

    entrance = str(tags.get("entrance") or "yes").lower()
    preferred = {
        "main": {"lobby", "hall"},
        "emergency": {"clinic", "medical", "firegarage", "policehall", "lobby", "hall"},
        "service": {"storage", "schoolstorage", "firestorage", "kitchen",
                    "diningroom", "warehouse", "firegarage"},
        "exit": {"lobby", "hall"},
    }.get(entrance, set())
    choices = []
    for idx, room in enumerate(plan.rooms, start=1):
        if room.is_shaft:
            continue
        room_rank = 0 if room.kind in preferred else 1
        for _side, wall in _outside_runs(plan, idx):
            for ex, ey, direction in wall:
                if direction == "W":
                    dx = ex - x
                    dy = max(ey - y, 0.0, y - ey - 1)
                else:
                    dx = max(ex - x, 0.0, x - ex - 1)
                    dy = ey - y
                distance = dx * dx + dy * dy
                choices.append((distance, room_rank, ex, ey, direction))
    if not choices:
        return None
    distance, _room_rank, ex, ey, direction = min(choices)
    if distance > 2.25:
        return None
    return ex, ey, direction


# One door per this much exterior wall, in tiles.
#
# A building got exactly one, wherever it landed. On a house that is a front
# door; on a church, a works or a parade of shops a hundred metres round, it
# is one door somewhere along the back, and everyone who walked up to the
# front reported a building with no door anywhere. Real buildings that size
# have several ways in, so these do - about one every thirty-odd metres,
# which is near enough that you meet one whichever side you arrive from.
DOOR_EVERY_TILES = 34
MAX_EXTERIOR_DOORS = 6
# Two doors closer together than this are one entrance, not two.
DOORS_APART_TILES = 12
# Nobody's front door opens into these, and a second one need not either.
PRIVATE_ROOMS = {"bathroom", "bedroom", "kidsbedroom", "closet", "prisoncells"}


def _more_ways_in(plan: Plan, front: tuple[int, int, str]) -> None:
    """Extra doors round a big building, spread along its walls.

    `front` is the door already hung, which the rest keep away from.
    """
    if plan.kind in (None, "house"):
        return          # a house has its front door and its back door
    walls: list[tuple[int, list]] = []
    for idx in range(1, len(plan.rooms) + 1):
        room = plan.rooms[idx - 1]
        if room.is_shaft:
            continue
        private = room.kind in PRIVATE_ROOMS
        for _side, wall in _outside_runs(plan, idx):
            if len(wall) >= 3:
                walls.append((len(wall) - (1000 if private else 0), wall))
    perimeter = sum(len(wall) for _rank, wall in walls)
    want = min(MAX_EXTERIOR_DOORS, perimeter // DOOR_EVERY_TILES)
    placed = [(front[0], front[1])]
    # Longest walls first, and never twice on one stretch or beside a door
    # already hung. Rooms nobody enters a building through come last.
    for _rank, wall in sorted(walls, key=lambda r: -r[0]):
        if len(placed) >= want:
            break
        spot = wall[len(wall) // 2]
        if any(abs(spot[0] - px) + abs(spot[1] - py) < DOORS_APART_TILES
               for px, py in placed):
            continue
        plan.doors.append(spot)
        placed.append((spot[0], spot[1]))


OPPOSITE_SIDE = {"N": "S", "S": "N", "W": "E", "E": "W"}


def _back_door(plan: Plan, street: str | None = None) -> None:
    """A second way out, into the back yard: on the wall facing away from the
    street, from the kitchen if it has that wall, else the room nearest it.

    Knox County's houses have two outside doors as a rule (the median of 546);
    ours had one, and the second one picked any far wall, so it could open
    onto the side of the house instead of the yard behind it.
    """
    if not plan.doors:
        return
    fx, fy, _fd = plan.doors[-1]
    back = OPPOSITE_SIDE.get(street or "S", "N")
    for wanted in (back, None):
        for kind in ("kitchen", "dining", "hall", "livingroom", "laundry", "bedroom"):
            for idx, room in enumerate(plan.rooms, 1):
                if room.kind != kind or room.is_shaft:
                    continue
                runs = [wall for side, wall in _outside_runs(plan, idx)
                        if len(wall) >= 3 and (side == wanted if wanted else
                        abs(wall[len(wall) // 2][0] - fx) + abs(wall[len(wall) // 2][1] - fy) > 6)]
                if runs:
                    wall = max(runs, key=len)
                    plan.doors.append(wall[len(wall) // 2])
                    return
