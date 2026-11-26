"""Doors, ways in, and the wall runs a door can sit in."""
from __future__ import annotations

from ..entrances import entrance_facade
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


FLAT_ENTRY_KINDS = ("hall", "kitchen", "openplan")
FLAT_END_ROOMS = {"bathroom", "bedroom", "kidsbedroom"}


class ApartmentAccessError(ValueError):
    """This cut of an apartment or landing cannot be connected."""


def _flat_doors(plan: Plan, edges: dict, rng: random.Random,
                direct_entry: int | None = None) -> None:
    """One entrance per home, with private rooms at the ends of the tree."""
    rooms = {i: room for i, room in enumerate(plan.rooms, 1) if not room.is_shaft}
    units = {room.unit for room in rooms.values()} - {0}
    links = {i: {} for i in rooms}
    for (a, b), wall in edges.items():
        if (not wall or rooms[a].access_role or rooms[b].access_role
                or (rooms[a].unit and rooms[b].unit and rooms[a].unit != rooms[b].unit)):
            continue
        straight = [e for e in wall if _room_at(plan, e[0], e[1]) ==
                    (_room_at(plan, e[0] - 1, e[1]) if e[2] == "N"
                     else _room_at(plan, e[0], e[1] - 1))]
        wall = straight or wall
        links[a][b] = links[b][a] = wall
        if rooms[a].unit == rooms[b].unit == 0:
            plan.doors.append(_door_spot(wall, 1, rng)[0])

    for unit in sorted(units):
        members = {i for i, room in rooms.items() if room.unit == unit}
        fronts = [(i, n, wall) for i in sorted(members) for n, wall in links[i].items()
                  if rooms[n].unit == 0]
        if not fronts and any(room.unit == 0 for room in rooms.values()):
            raise ApartmentAccessError(f"Apartment {unit} has no entrance wall off the landing")

        def preference(i):
            kind = rooms[i].kind
            return (FLAT_ENTRY_KINDS.index(kind) if kind in FLAT_ENTRY_KINDS else 3,
                    -sum(n in members for n in links[i]), -rooms[i].area, i)

        if fronts:
            entry, _, wall = min(fronts, key=lambda front: (preference(front[0]), -len(front[2])))
            plan.doors.append(_door_spot(wall, 1, rng)[0])
        else:
            entry = direct_entry if direct_entry in members else min(members, key=preference)

        first = rooms[entry]
        old_kind = first.kind
        first.apartment_entry = True
        if not first.surveyed:
            if len(members) <= 2 and all(rooms[i].kind not in ("bedroom", "kidsbedroom")
                                         for i in members - {entry}):
                first.kind = "openplan"
            elif first.kind not in FLAT_ENTRY_KINDS:
                first.kind = ("openplan" if len(members) <= 2 else
                              "hall" if first.area >= SIZES["hall"].lo else "kitchen")

        reached = {entry}
        depth = {entry: 0}
        parents = set()
        displaced = [old_kind] if old_kind in FLAT_END_ROOMS and old_kind != first.kind else []
        while remaining := members - reached:
            choices = [(a, b, wall) for a in sorted(reached) for b, wall in links[a].items()
                       if b in remaining]
            if not choices:
                raise ApartmentAccessError(f"Apartment {unit} has rooms cut off from its entrance")
            a, b, wall = min(choices, key=lambda edge: (
                rooms[edge[0]].kind in FLAT_END_ROOMS,
                _door_cost(rooms[edge[0]].kind, rooms[edge[1]].kind) + 2 * depth[edge[0]],
                -len(edge[2]), edge[0], edge[1]))
            if rooms[a].kind in FLAT_END_ROOMS and not rooms[a].surveyed:
                # An irregular cut made this room the only way through.
                # Reassign it and put its original use on a suitable leaf.
                displaced.append(rooms[a].kind)
                rooms[a].kind = "hall"
            plan.doors.append(_door_spot(wall, 1, rng)[0])
            parents.add(a)
            reached.add(b)
            depth[b] = depth[a] + 1
        leaves = {i for i in members - parents - {entry} if not rooms[i].surveyed}
        if len(members) > 1 and not any(rooms[i].kind == "bathroom" for i in members):
            displaced.insert(0, "bathroom")
        for kind in dict.fromkeys(displaced):
            if any(rooms[i].kind == kind for i in members) or not leaves:
                continue
            leaf = min(leaves, key=lambda i: (rooms[i].kind in FLAT_END_ROOMS,
                                             abs(rooms[i].area - SIZES[kind].target), i))
            if rooms[leaf].kind == "bathroom":
                continue
            rooms[leaf].kind = kind
            leaves.remove(leaf)


def _doors(plan: Plan, rng: random.Random,
           stairs: tuple[int, int, str] | None = None, *, private_flats: bool = False,
           direct_entry: int | None = None) -> None:
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
    if n <= 1 and not private_flats:
        return
    rooms = plan.rooms
    sealed = {i for i, r in enumerate(rooms, 1) if r.is_shaft}
    from .core import STAIR_RUN

    stair_steps: set[tuple[int, int]] = set()
    if stairs is not None:
        sx, sy, sd = stairs
        sdx, sdy = (0, 1) if sd == "N" else (1, 0)
        stair_steps = {(sx + sdx * i, sy + sdy * i) for i in range(1, STAIR_RUN - 1)}

    def clear_of_stairs(wall: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
        if not stair_steps:
            return wall
        safe = [
            e for e in wall
            if (e[0], e[1]) not in stair_steps
            and ((e[0] - 1, e[1]) if e[2] == "W" else (e[0], e[1] - 1)) not in stair_steps
        ]
        return safe if private_flats else safe or wall

    edges = {k: clear_of_stairs(v) for k, v in _boundary_edges(plan).items()
             if k[0] not in sealed and k[1] not in sealed}

    if private_flats:
        _flat_doors(plan, edges, rng, direct_entry)
        return

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
        if room.kind not in SWAPS_WITH_BATHROOM or room.is_shaft or room.is_core or room.surveyed:
            continue
        through = link.get(i, set())
        if len(through) != 1:
            continue
        b = next(iter(through))
        bath = plan.rooms[b - 1]
        if bath.surveyed or bath.kind != "bathroom" or bath.unit != room.unit or len(link.get(b, ())) < 2:
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


def _has_door_depth(plan: Plan, side: str, edge: tuple[int, int, str]) -> bool:
    """Whether stepping inward from `edge` has at least two tiles in the same room.

    Prevents exterior doors from landing on a 1-tile-deep strip where the
    visitor immediately hits a solid wall one tile inside the doorway.
    """
    ex, ey, _ed = edge
    ix, iy = {
        "N": (ex, ey),
        "S": (ex, ey - 1),
        "W": (ex, ey),
        "E": (ex - 1, ey),
    }[side]
    dx, dy = {"N": (0, 1), "S": (0, -1), "W": (1, 0), "E": (-1, 0)}[side]
    nx, ny = ix + dx, iy + dy
    if not (0 <= ix < plan.width and 0 <= iy < plan.height):
        return False
    if not (0 <= nx < plan.width and 0 <= ny < plan.height):
        return False
    rid = plan.grid[iy][ix]
    return rid > 0 and plan.grid[ny][nx] == rid


def _door_on_run(plan: Plan, side: str,
                 wall: list[tuple[int, int, str]]) -> tuple[int, int, str]:
    """Pick the middle of `wall`, preferring edges with >= 2 tiles of room depth."""
    deep = [e for e in wall if _has_door_depth(plan, side, e)]
    pool = deep if deep else wall
    return pool[len(pool) // 2]


# Where the way in goes, in order of preference. Never straight into a
# bathroom or a bedroom unless there is truly nothing else.
ENTRY_KINDS = ["hall", "lobby", "livingroom", "restaurant", "church",
               "classroom", "clinic", "warehouse", "kitchen", "office",
               "garage", "dining", "storage", "bedroom"]


HOUSE_ESSENTIALS = {"kitchen", "bathroom", "bedroom", "livingroom"}
SPARE_KINDS = {"hall", "office", "storage", "closet", "laundry"}


def _carve_foyer(plan: Plan, front: tuple[int, int, str], side: str,
                 idx: int, avoid: tuple[int, int] | None) -> None:
    """Make the room a residential house's front door opens into its entry
    hall ('hall'), the whole room and not a small room inside it."""
    if plan.kind not in (None, "house") or len(plan.rooms) < 2 or plan.private_flats:
        return
    room = plan.rooms[idx - 1]
    if room.kind == "hall" or room.is_core or room.is_shaft:
        return
    # The house's only kitchen, bathroom, bedroom or living room is not lost:
    # a spare room (a hall, office, store) takes its kind instead.
    if room.kind in HOUSE_ESSENTIALS and sum(r.kind == room.kind for r in plan.rooms) < 2:
        spare = [r for r in plan.rooms if r is not room and r.kind in SPARE_KINDS
                 and not r.is_core and not r.is_shaft]
        if not spare:
            return
        spare.sort(key=lambda r: -r.area)
        spare[0].kind = room.kind
    room.kind = "hall"


def _exterior_door(plan: Plan, rng: random.Random,
                   avoid: tuple[int, int] | None = None,
                   street: str | None = None,
                   entrances: list[tuple[float, float, dict]] | None = None,
                   approach_edges: tuple | None = None) -> None:
    """One way in, into the room a visitor would expect to arrive in.

    `avoid` is the foot of the staircase, so the front door does not open
    straight onto the bottom step.
    """
    if entrances:
        placed = []
        ordered = sorted(entrances, key=_entrance_priority)
        if plan.private_flats:
            from .furnishing import _facade_runs

            runs = _facade_runs(plan.grid)
        for x, y, tags in ordered:
            if plan.private_flats:
                bound = entrance_facade(runs, x, y, tags)
                edge = next((e for e in bound.edges if e not in plan.party
                             and e not in plan.blocked_entrances
                             and _has_door_depth(plan, bound.side, e)), None) if bound else None
            else:
                edge = _entrance_wall(plan, x, y, tags)
            if edge is None or edge in placed or edge in plan.blocked_entrances:
                continue
            plan.doors.append(edge)
            placed.append(edge)
        if placed:
            return
    if approach_edges is not None:
        has_core = any(room.is_core for room in plan.rooms)
        legal = {edge for idx, room in enumerate(plan.rooms, 1)
                 if not room.is_shaft and (room.is_core or not has_core)
                 for side, wall in _outside_runs(plan, idx) for edge in wall
                 if edge not in plan.blocked_entrances and _has_door_depth(plan, side, edge)}
        if (entry := next((edge for edge in approach_edges if edge in legal), None)) is not None:
            plan.doors.append(entry)
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
        deep = any(_has_door_depth(plan, side, e) for e in wall)
        # Facing the street, as front doors do; without that the door went on
        # the south wall and half the paths wrapped round houses.
        return (deep, len(wall) >= 3, side == (street or "S"),
                from_stairs(wall), len(wall))

    # The street comes before the room. Taking the best room first and then
    # its best wall put a house's door wherever its hall happened to be, and
    # a hall that does not reach the street side - most of them - turned the
    # house's back on it: 5 houses in 100 had a door on the street. A room
    # anybody would walk in through and a wall on the street beats the room
    # that would have been first; between two such rooms it is the room's own
    # order, then the stairs, then the longer wall, as it always was.
    def available_runs(idx):
        for side, wall in _outside_runs(plan, idx):
            clear = [edge for edge in wall if edge not in plan.blocked_entrances]
            if clear:
                yield side, clear

    facing = [(idx, run) for idx in candidates
              if plan.rooms[idx - 1].kind in order
              for run in available_runs(idx)
              if run[0] == (street or "S") and len(run[1]) >= 3
              and any(_has_door_depth(plan, run[0], e) for e in run[1])]
    if not facing:
        # No room anybody would arrive in reaches the street side - a large
        # house cut in wings can have nothing but bedrooms there. Any room
        # but a bathroom or a cupboard on the street beats a door round the
        # back.
        facing = [(idx, run) for idx in candidates
                  if plan.rooms[idx - 1].kind not in ("bathroom", "closet")
                  for run in available_runs(idx)
                  if run[0] == (street or "S") and len(run[1]) >= 3
                  and any(_has_door_depth(plan, run[0], e) for e in run[1])]
    if facing:
        idx, (side, wall) = min(facing, key=lambda ir: (
            order.get(plan.rooms[ir[0] - 1].kind, 50),
            -from_stairs(ir[1][1]), -len(ir[1][1])))
        front = _door_on_run(plan, side, wall)
        plan.doors.append(front)
        _carve_foyer(plan, front, side, idx, avoid)
        _more_ways_in(plan, front)
        return

    all_runs = [(idx, side, wall)
                for idx in candidates
                for side, wall in available_runs(idx)]
    if all_runs:
        deep_runs = [(idx, side, wall) for idx, side, wall in all_runs
                     if any(_has_door_depth(plan, side, e) for e in wall)]
        pool = deep_runs if deep_runs else all_runs
        idx, side, wall = max(pool, key=lambda item: (
            -candidates.index(item[0]), score((item[1], item[2]))))
        front = _door_on_run(plan, side, wall)
        plan.doors.append(front)
        _carve_foyer(plan, front, side, idx, avoid)
        _more_ways_in(plan, front)
        return


VEHICLE_BAY_ROOMS = {"firegarage", "garage", "garagestorage", "mechanic", "warehouse", "hangar"}


def _widen_vehicle_entry(plan: Plan, street: str | None) -> None:
    """Turn the street-facing garage entry into a three-tile door opening."""
    multi_room = len(plan.rooms) > 1
    candidates = []
    bay_walls = []
    for room_id, room in enumerate(plan.rooms, start=1):
        is_bay = room.kind in VEHICLE_BAY_ROOMS
        if multi_room and not is_bay:
            continue
        for side, wall in _outside_runs(plan, room_id):
            if is_bay and len(wall) >= 3:
                bay_walls.append((side == (street or "S"), len(wall), wall))
            for door in plan.doors:
                if door in wall:
                    candidates.append((side == (street or "S"), len(wall),
                                       door, wall))
    if not candidates and bay_walls:
        _faces_street, _length, wall = max(bay_walls)
        entry = wall[len(wall) // 2]
        plan.doors.append(entry)
        candidates.append((_faces_street, _length, entry, wall))
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

# A house with room for one gets an attached garage this often: an integral
# garage on the street front, its three-tile door on the street, the way a
# suburb is built. Not every house: most have a drive and no garage, or a
# detached one, and a map where every house had a garage door on the street
# would look stamped.
GARAGE_SHARE = 0.75
GARAGE_MIN_FOOTPRINT = 96        # tiles of ground floor
GARAGE_MIN_ROOMS = 4
GARAGE_AREA = (25, 56)           # tiles; >= 5x5 so a full car + shelves actually fit
GARAGE_MIN_WIDTH = 5             # along the street
GARAGE_MIN_DEPTH = 5             # perpendicular to the garage door
GARAGE_NEVER = {"hall", "kitchen", "livingroom", "openplan", "bathroom", "dining",
                "closet", "garage"}


def _rooms_joined_without(plan: Plan, gone: int) -> bool:
    """Whether every other room still joins up, through doors, with `gone` shut."""
    n = len(plan.rooms)
    links: dict[int, set[int]] = {i: set() for i in range(1, n + 1)}
    for x, y, d in plan.doors:
        a, b = ((_room_at(plan, x, y - 1), _room_at(plan, x, y)) if d == "N"
                else (_room_at(plan, x - 1, y), _room_at(plan, x, y)))
        if a and b and gone not in (a, b):
            links[a].add(b)
            links[b].add(a)
    rest = [i for i in links if i != gone]
    if not rest:
        return True
    seen, todo = {rest[0]}, [rest[0]]
    while todo:
        for nxt in links[todo.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return len(seen) == len(rest)


def _attach_garage(plan: Plan, seed, street: str | None, stair_tiles: set) -> bool:
    """Turn one room on a house's street front into a garage with a street door.

    A room qualifies when it is not a room a home is lived in, is the size of a
    bay, has three tiles or more of street wall with no door in it, holds no
    stairs, and the rest of the house still joins up without it as a way
    through. The room that is nearest a corner and 24 tiles wins: a garage
    stands at the end of a house, not in the middle of its front. Returns
    whether one was made."""
    if (not street or len(plan.rooms) < GARAGE_MIN_ROOMS
            or plan.width * plan.height < GARAGE_MIN_FOOTPRINT
            or random.Random(f"{seed}:garage").random() >= GARAGE_SHARE):
        return False
    best = None
    for idx, room in enumerate(plan.rooms, 1):
        if room.is_core or room.is_shaft or room.kind in GARAGE_NEVER:
            continue
        cells = [(x, y) for y in range(plan.height) for x in range(plan.width)
                 if plan.grid[y][x] == idx]
        if not GARAGE_AREA[0] <= len(cells) <= GARAGE_AREA[1] or stair_tiles & set(cells):
            continue
        walls = [w for side, w in _outside_runs(plan, idx)
                 if side == street and len(w) >= 3 and not any(e in plan.doors for e in w)]
        if not walls or not _rooms_joined_without(plan, idx):
            continue
        xs = [x for x, _ in cells]
        ys = [y for _, y in cells]
        span_x = max(xs) - min(xs) + 1
        span_y = max(ys) - min(ys) + 1
        bay_w, bay_d = (span_x, span_y) if street in ("N", "S") else (span_y, span_x)
        if bay_w < GARAGE_MIN_WIDTH or bay_d < GARAGE_MIN_DEPTH:
            continue
        at_end = (min(xs) == 0 or max(xs) == plan.width - 1
                  or min(ys) == 0 or max(ys) == plan.height - 1)
        score = (at_end, -abs(len(cells) - 30), idx)
        if best is None or score > best[0]:
            best = (score, idx)
    if best is None:
        return False
    plan.rooms[best[1] - 1].kind = "garage"
    _widen_vehicle_entry(plan, street)
    return bool(getattr(plan, "garage_door_tiles", ()))


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
        for side, wall in _outside_runs(plan, idx):
            for ex, ey, direction in wall:
                if (ex, ey, direction) in plan.party:
                    continue
                if direction == "W":
                    dx = ex - x
                    dy = max(ey - y, 0.0, y - ey - 1)
                else:
                    dx = max(ex - x, 0.0, x - ex - 1)
                    dy = ey - y
                distance = dx * dx + dy * dy
                no_depth = 0 if _has_door_depth(plan, side, (ex, ey, direction)) else 1
                choices.append((no_depth, distance, room_rank, ex, ey, direction))
    if not choices:
        return None
    _no_depth, distance, _room_rank, ex, ey, direction = min(choices)
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
    walls: list[tuple[int, str, list]] = []
    for idx in range(1, len(plan.rooms) + 1):
        room = plan.rooms[idx - 1]
        if room.is_shaft:
            continue
        private = room.kind in PRIVATE_ROOMS
        for side, wall in _outside_runs(plan, idx):
            wall = [e for e in wall if e not in plan.blocked_entrances]
            if len(wall) >= 3 and any(_has_door_depth(plan, side, e) for e in wall):
                walls.append((len(wall) - (1000 if private else 0), side, wall))
    perimeter = sum(len(wall) for _rank, _side, wall in walls)
    want = min(MAX_EXTERIOR_DOORS, perimeter // DOOR_EVERY_TILES)
    placed = [(front[0], front[1])]
    # Longest walls first, and never twice on one stretch or beside a door
    # already hung. Rooms nobody enters a building through come last.
    for _rank, side, wall in sorted(walls, key=lambda r: -r[0]):
        if len(placed) >= want:
            break
        spot = _door_on_run(plan, side, wall)
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
                runs = [(side, wall) for side, wall in _outside_runs(plan, idx)
                        if len(wall) >= 3 and (side == wanted if wanted else
                        abs(wall[len(wall) // 2][0] - fx) + abs(wall[len(wall) // 2][1] - fy) > 6)]
                deep = [(side, wall) for side, wall in runs
                        if any(_has_door_depth(plan, side, e) for e in wall)]
                pool = deep if deep else runs
                if pool:
                    side, wall = max(pool, key=lambda item: len(item[1]))
                    plan.doors.append(_door_on_run(plan, side, wall))
                    return
