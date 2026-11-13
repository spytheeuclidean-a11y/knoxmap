"""Inside a finished plan: stairs, cores, walls, windows and furniture."""
from __future__ import annotations

from .. import catalog as C
from .. import furnish_rules as FR
from ..uses import FRONT_ROOMS
from collections import deque
from dataclasses import dataclass
from dataclasses import field
import heapq
import random

from typing import TYPE_CHECKING
from .core import BATHROOM_TILES, MANSION_EXTRA, MIN_ROOM, Plan, RETAIL_ROOMS, ROOM_STYLE, Room, STAIR_RUN
from .openings import _boundary_edges, _outside_runs, _room_at
from .malls import _refit, _renumber
from .dwellings import _mend_fragments

if TYPE_CHECKING:
    from .core import Plan



# Tiles of wall per window bay, by what the building is, on its front and on
# its other sides. Not a setting: how glazed a facade is follows from what the
# building is. A tile is about a metre, and real buildings put a window in
# roughly every room-width of wall: a house every four metres or so across its
# front and fewer down the side; flats every three metres on every side, since
# each flat looks out wherever it can; offices and hotels close to a band of
# glass; a works or a barn only a few high windows. The old spacings (nine and
# sixteen tiles for flats) left city blocks looking like warehouses.
FACADE_SPACING = {
    "house": (3, 4), "apartment": (3, 3), "barn": (10, 20), "shed": (12, 24),
    "garage": (12, 24),
    "industrial": (6, 9), "shop": (3, 5), "restaurant": (3, 5),
    "civic": (2, 2), "school": (3, 3), "church": (4, 5), "medical": (3, 3),
}
DEFAULT_FACADE_SPACING = (4, 6)
# Towers are glass: from this many storeys an office or hotel is glazed on
# every tile of its outside wall.
GLASS_TOWER_FROM_LEVELS = 8
# The ground floor of a shop or restaurant is its shop front: glass across the
# front, broken only by the door.
SHOP_FRONT_KINDS = {"shop", "restaurant"}
# Buildings laid out like a house, where each room takes only the windows it
# needs. Elsewhere a room takes whatever its stretch of facade offers - an
# open office along a glazed wall is not limited to one window.
HOUSE_LIKE_KINDS = {"house", "barn", "shed", None}
# A house window per this many tiles of a room's outside wall, and the tiles
# kept clear either side of a shuttered window (its shutters, and a gap).
HOUSE_WINDOW_EVERY = 3
WINDOW_CLEARANCE_SHUTTERED = 2
# Most windows one room may take, whatever the facade offers it.
ROOM_WINDOW_CAP = {
    "bathroom": 1, "storage": 1, "hall": 1, "garage": 0, "shed": 1, "elevator": 0,
    "kitchen": 2, "bedroom": 3, "dining": 3, "office": 2, "livingroom": 5,
    "kidsbedroom": 2, "closet": 0, "laundry": 1,
    "generalstore": 6, "conveniencestore": 6, "clothingstore": 6, "cafe": 6,
}
DEFAULT_ROOM_WINDOW_CAP = 4
# Outside house-like buildings a facade keeps its rhythm whatever is behind
# it - a stockroom or washroom on an office front still has its window - so
# only these are capped. Limiting bathrooms and storerooms as in a house left
# a third of an office block's bays empty, holes all over the grid.
SERVICE_WINDOW_CAP = {"garage": 0, "mechanic": 0, "elevator": 0, "shed": 1}
# Rooms that must not be left without daylight.
# Kept to the rooms that matter: guaranteeing every office and dining room a
# window as well pushed facades back up to 1.09 windows per ten tiles of wall.
# Those rooms still get windows from the bays; they just are not promised one.
LIVED_IN = {"livingroom", "openplan", "bedroom", "kidsbedroom", "kitchen",
            "classroom", "restaurant"}
MIN_WALL_FOR_WINDOW = 3
# What "a shelf" is, by the room it stands in.
#
# One generic wooden shelf was on nearly every room's list and was always the
# same sprite, which made it the third commonest object in a town. Varying it
# per home was worse: it put warehouse wire racking in people's bathrooms. A
# shelf is a different piece of furniture in a kitchen, a study and a garage,
# so the room picks, and only a room that would really have one gets the
# racking.
# wall_cabinet is not in here on purpose. It is an upper cabinet that hangs
# above a counter, on the roof layer so it draws over one, and the kitchen
# already puts them there. Offering it as a shelf stood one on any wall with
# nothing underneath, taking floor space it does not stand on.
# "shelf" here means the plain household shelf in any of its styles. It used
# to mean one sprite, furniture_shelving_01_001-004, which is on nearly every
# room's list: it came to 4% of all the furniture in a town, one shelf you saw
# in every house. Knox County's most-used single shelf is 12% of its shelving
# and the rest is spread over a dozen styles, so ours spreads over three.
SHELVES = ("shelf", "shelf_1", "shelf_2")
SHELVING = {
    # Nothing stands along a concourse wall: that edge is the shopfronts.
    "concourse": (),
    # No dresser: a chest of drawers by the toilet is a bedroom piece.
    "bathroom": SHELVES,
    "kitchen": SHELVES,
    "laundry": SHELVES + ("dresser",),
    "livingroom": ("bookshelf",) + SHELVES,
    "dining": ("bookshelf",) + SHELVES,
    "bedroom": ("bookshelf",) + SHELVES,
    "kidsbedroom": ("bookshelf",) + SHELVES,
    "hall": SHELVES + ("bookshelf",),
    "office": ("bookshelf", "filing_cabinet"),
    "library": ("bookshelf",),
    "classroom": ("bookshelf",) + SHELVES,
    "storage": ("metal_rack", "crate") + SHELVES,
    "garage": ("metal_rack", "crate"),
    "shed": ("metal_rack",) + SHELVES,
    "warehouse": ("metal_rack", "crate"),
    "factory": ("metal_rack", "crate"),
    "workshop": ("metal_rack",) + SHELVES,
}
DEFAULT_SHELVING = SHELVES + ("bookshelf",)
# What goes on a corridor's walls, and how much of its facade may be used
# before the windows lose their columns. Rugs go on the floor because they
# are the one thing you can walk over.
CORE_WALL_ART = ("painting", "mirror", "painting", "corkboard")
# ...and nothing at all down a workplace corridor.
CORE_WALL_ART_CIVIC: tuple = ()
CORE_FACADE_SHARE = 4
# One piece of art per this many wall slots. Hanging one on every slot filled
# a corridor edge to edge and made pictures the commonest thing in a house.
CORE_ART_EVERY = 3
# Pictures and mirrors a room may hold, however long its wishlist, and how
# often a room gets one at all. They repeat where other things do not and
# they are on nearly every room's list, so almost every room had one or two
# and wall art came to 11.8% of everything in a house. Not every room in a
# house has a picture in it.
WALL_ART_CAP = 1
# What a mansion hangs in a room: two or three pictures down a wall, where a
# house hangs one. Pictures take wall squares, not floor, so this costs a room
# nothing but the wall.
MANSION_ART_CAP = 3
WALL_ART_CHANCE = 0.55
# Workplaces hang nothing. Knox County's school rooms carry 0.19 pieces of
# wall decoration per 10 m2 and ours sat at 0.21, but with Erika's Tiles
# installed the substitution below turns every picture and mirror into one
# of her 59 wall-art sprites - among them round faces that read as clocks,
# and a school came out with a wall of them. A classroom, a corridor and a
# police office get none.
ART_FREE_KINDS = {"police", "civic", "school", "medical", "fire",
                  "fire_police", "military", "library"}
# Buildings that are places of work, not homes, and the rooms in them whose
# usual wishlist is a domestic one. A station, a school or a clinic gets a
# noticeboard and a water cooler where a house gets a side table and a
# picture.
# Tiles of floor per piece of furniture, where a room is not the usual 4.
ROOM_DENSITY = {"classroom": 2, "secondaryclassroom": 2, "schoollab": 2,
                "library": 3, "prisoncells": 3}
# Warehouse fittings. A house keeps none of them: its box room had a steel
# rack and a packing crate in it, which is a stockroom, not a cupboard under
# the stairs. Barns and sheds are outbuildings and may keep theirs.
WAREHOUSE_ROLES = {"metal_rack", "crate"}
# A house's cellar is part of the home: without it, its laundry was fitted
# out as a laundromat, coin washers down one wall and dryers down the other.
HOME_KINDS = {None, "house", "apartment", "basement_house", "basement_house_rec",
              "basement_house_workshop", "basement_house_shelter",
              "basement_house_cellar"}
# What a home puts in a box room instead.
HOME_STORE = {"metal_rack": "shelf", "crate": "dresser"}
CIVIC_KINDS = {"police", "civic", "school", "medical", "fire", "fire_police",
               "military", "library"}
CIVIC_ROOMS = {
    "hall": ["plant", "water_cooler", "chair", "painting", "chair"],
    "lobby": ["shop_counter", "chair", "chair", "plant", "painting",
              "chair", "water_cooler"],
    "office": ["desk", "office_chair", "filing_cabinet", "corkboard",
               "filing_cabinet", "plant"],
    "breakroom": ["counter", "fridge", "chair", "chair", "corkboard",
                  "water_cooler"],
}
CORE_RUGS = ("rug_wide", "rug", "rug_small")
# One rug per this many tiles of corridor. It was 3, chosen to reach '7
# pieces per 10 m2' - a figure read off a per-house median over a filtered
# set of houses, not off the halls themselves. Measured over the whole map,
# a Knox County hall carries 1.2 pieces per 10 m2 of everything and 0.08
# rugs: a corridor there is bare floor, not a runner of carpet.
CORE_RUG_EVERY = 125


def _facade_runs(grid: list[list[int]]) -> list[tuple[str, list[tuple[int, int, str, int, int]]]]:
    """The building's outside walls as straight runs.

    Each edge is (x, y, dir, inside_x, inside_y): where BuildingEd draws the
    wall, and the tile of the building behind it.
    """
    h, w = len(grid), len(grid[0])

    def inside(x, y):
        return 0 <= x < w and 0 <= y < h and grid[y][x]

    lines: dict[tuple[str, int], list[int]] = {}
    for y in range(h):
        for x in range(w):
            if not grid[y][x]:
                continue
            if not inside(x, y - 1):
                lines.setdefault(("N", y), []).append(x)
            if not inside(x, y + 1):
                lines.setdefault(("S", y + 1), []).append(x)
            if not inside(x - 1, y):
                lines.setdefault(("W", x), []).append(y)
            if not inside(x + 1, y):
                lines.setdefault(("E", x + 1), []).append(y)
    runs = []
    for (side, fixed), positions in lines.items():
        positions.sort()
        run: list[int] = []
        for p in positions + [None]:
            if run and (p is None or p != run[-1] + 1):
                edges = []
                for m in run:
                    if side == "N":
                        edges.append((m, fixed, "N", m, fixed))
                    elif side == "S":
                        edges.append((m, fixed, "N", m, fixed - 1))
                    elif side == "W":
                        edges.append((fixed, m, "W", fixed, m))
                    else:
                        edges.append((fixed, m, "W", fixed - 1, m))
                runs.append((side, edges))
                run = []
            if p is not None:
                run.append(p)
    return runs


def _room_edges(grid: list[list[int]]) -> set[tuple[int, int, str]]:
    """The walls BuildingEd draws between one room and the next.

    _facade_runs only knows about the outside of the building. These are just
    as real to the renderer: where a room wall meets the facade on the same
    tile, that tile carries both a west and a north wall and is drawn as one
    corner piece.
    """
    h, w = len(grid), len(grid[0])
    out: set[tuple[int, int, str]] = set()
    for y in range(h):
        for x in range(w):
            here = grid[y][x]
            if not here:
                continue
            if x > 0 and grid[y][x - 1] and grid[y][x - 1] != here:
                out.add((x, y, "W"))
            if y > 0 and grid[y - 1][x] and grid[y - 1][x] != here:
                out.add((x, y, "N"))
    return out


def _sides_of(grid: list[list[int]], x: int, y: int, d: str) -> tuple[int, int]:
    """The room ids either side of a wall edge; 0 is outside."""
    h, w = len(grid), len(grid[0])

    def at(px, py):
        return grid[py][px] if 0 <= px < w and 0 <= py < h else 0

    return (at(x - 1, y), at(x, y)) if d == "W" else (at(x, y - 1), at(x, y))


def _doors_off_corners(storey, edges: set, corners: set) -> int:
    """Slide a door off an inside corner, where there is somewhere to slide to.

    A door has the same trouble a window does - BuildingEd draws a tile
    carrying both a west and a north wall as one corner piece, and a door on
    one comes out as neither door nor wall. On a shipped town map 989 doorways
    of 57,357 sat on one, over 741 buildings, which is what a player reads as
    a door that will not open.

    It moves along its own wall to the nearest tile that is not a corner, and
    where that whole boundary is corners - a stepped diagonal wall is one or
    two tiles long - to a clean wall the room shares with some other
    neighbour. Never at the cost of shutting a room off: every swap is checked
    against the rooms that could be reached before it.
    """
    keep_off = set(storey.party) | set(getattr(storey, "wall_pieces", ()))
    # Every wall that is not a corner, by the pair of rooms it stands between.
    # Sliding along the door's own wall is not enough: a stepped diagonal side
    # is a wall one or two tiles long, so there is nowhere on it to slide to.
    # A door only has to separate the same two spaces, and the rest of that
    # boundary will do.
    boundary: dict[tuple[int, int], list] = {}
    for (ex, ey, ed) in edges:
        if (ex, ey) in corners or (ex, ey, ed) in keep_off:
            continue
        boundary.setdefault(_sides_of(storey.grid, ex, ey, ed), []).append((ex, ey, ed))

    def homes(pair) -> tuple:
        """Which dwellings a wall stands between; -1 is the outside."""
        return tuple(sorted(storey.rooms[r - 1].unit if r else -1 for r in pair))

    def joinable(pair) -> bool:
        """Whether a door may hang between these two rooms at all."""
        a, b = pair
        if a == b or (a and storey.rooms[a - 1].is_shaft) \
                or (b and storey.rooms[b - 1].is_shaft):
            return False
        # Never a door from one person's flat into the next.
        ua, ub = homes(pair)
        return not (ua > 0 and ub > 0 and ua != ub)

    # Not from outside: a floor above the ground has no outside door, so a
    # walk that started there reached nothing and the check below waved
    # everything through. From a room, so it holds on every storey, and with
    # the outside among the rooms it reaches, so a front door cannot be moved
    # indoors either.
    start = next((i for i, r in enumerate(storey.rooms, 1) if not r.is_shaft), 0)

    def reaches(doors) -> set:
        """What can be walked to from inside, through doors alone. 0 is the
        outside, so it is in the set when a way in survives."""
        adj: dict[int, set] = {}
        for (x, y, d) in doors:
            a, b = _sides_of(storey.grid, x, y, d)
            if a == b:
                continue
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
        seen, stack = {start}, [start]
        while stack:
            here = stack.pop()
            # The outside counts as reached, so a way in cannot be moved
            # away, but it is not a corridor: going out of the front door and
            # round to the back is not how a room is got into.
            if here == 0:
                continue
            for nxt in adj.get(here, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    moved = 0
    for i, (x, y, d) in enumerate(storey.doors):
        if (x, y) not in corners:
            continue
        want = _sides_of(storey.grid, x, y, d)
        taken = set(storey.doors)
        before = reaches(storey.doors)
        spots = [s for s in boundary.get(want, ()) if s not in taken]
        if not spots:
            # That boundary is corners end to end. The room still has to open
            # onto something, so any clean wall it shares with a neighbour
            # will do - as long as the door keeps its job. A wall between the
            # same two dwellings only: move a flat's front door onto an inside
            # wall and the flat has no front door, move it onto the corridor
            # somewhere else and the flat it lands on has two.
            mine = {r for r in want if r}
            role = homes(want)
            spots = [s for pair, places in boundary.items()
                     if joinable(pair) and mine & set(pair) and homes(pair) == role
                     for s in places if s not in taken]
        # The nearest first, so a front door stays on the front of the house.
        spots.sort(key=lambda s: (abs(s[0] - x) + abs(s[1] - y), s))
        for spot in spots[:DOOR_SPOTS_TRIED]:
            trial = list(storey.doors)
            trial[i] = spot
            if reaches(trial) >= before:
                storey.doors[i] = spot
                moved += 1
                break
    return moved


def _front_side(building: "Building", kind: str | None) -> set[str]:
    """Which walls count as the front, and get the closer window spacing.

    For a house, the wall with the front door. For a block of flats, both long
    sides: the ends are where the corridor comes out, and the flats look out
    over the street from the sides.
    """
    ground = building.storeys[0]
    if kind == "apartment" and ground.core is not None:
        x0, y0, x1, y1 = ground.core
        return {"W", "E"} if (y1 - y0) >= (x1 - x0) else {"N", "S"}
    for x, y, d in ground.doors:
        # An outside door has building on exactly one side of it.
        if d == "N":
            above, below = _room_at(ground, x, y - 1), _room_at(ground, x, y)
            if bool(above) != bool(below):
                return {"N"} if below else {"S"}
        else:
            left, right = _room_at(ground, x - 1, y), _room_at(ground, x, y)
            if bool(left) != bool(right):
                return {"W"} if right else {"E"}
    return {"S"}


def _bays(by_side: dict, front: set[str], near: int, far: int,
          only: set[str] | None = None) -> list[tuple[int, int, str, int, int]]:
    """Window positions along each side, `near` tiles apart on the front and
    `far` elsewhere. `only` limits them to those sides."""
    bays: list[tuple[int, int, str, int, int]] = []
    for side, edges in by_side.items():
        if only is not None and side not in only:
            continue
        # Position along the side: x for north and south faces, y for west
        # and east.
        along = (lambda e: e[3]) if side in ("N", "S") else (lambda e: e[4])
        positions = sorted({along(e) for e in edges})
        if len(positions) < MIN_WALL_FOR_WINDOW:
            continue
        spacing = max(1, near if side in front else far)
        if side not in front and len(positions) < spacing:
            continue            # a short side stays blank
        inner = positions[1:-1]
        if spacing == 1:
            chosen = set(inner)
        else:
            count = max(1, round(len(inner) / spacing))
            step = len(inner) / count
            chosen = {inner[int((i + 0.5) * step)] for i in range(count)}
        bays.extend(e for e in edges if along(e) in chosen)
    return bays


def _place_windows(building: "Building", kind: str | None,
                   shop_ground: bool = False) -> None:
    """Windows in bays down the facade, the same bays on every storey.

    Two things made the buildings look wrong. Windows were spaced along every
    wall at the same pitch, so a house was as glazed down its side as across
    its front; and each storey placed its own, so no window sat above the one
    below. Real facades are built in bays: the positions are decided once for
    the building and repeated floor by floor, and a storey skips a bay only
    where the room behind has no use for a window.

    How many bays there are is not a setting. It follows from what the
    building is (FACADE_SPACING): a glass tower, a shop front, a block of
    flats and a barn are glazed nothing alike, and one dial for all of them
    could only ever be right for one.

    Bays are counted along each side of the building rather than along each
    straight run of wall. A building on its real footprint at 38 degrees has
    no straight runs at all - its sides are staircases of one- and two-tile
    steps - and requiring three tiles of straight wall left such a house with
    two windows. Counting along the side puts a window every few steps of the
    staircase, the way it would sit on the real diagonal wall.
    """
    if not building.storeys:
        return
    front = _front_side(building, kind)
    near, far = FACADE_SPACING.get(kind or "house", DEFAULT_FACADE_SPACING)
    if kind == "civic" and len(building.storeys) >= GLASS_TOWER_FROM_LEVELS:
        near = far = 1
    by_side: dict[str, list[tuple[int, int, str, int, int]]] = {}
    for side, wall in _facade_runs(building.storeys[0].grid):
        by_side.setdefault(side, []).extend(wall)
    bays = _bays(by_side, front, near, far)
    ground_bays = bays
    glass: list[tuple[int, int, str, int, int]] = []
    glass_set: set = set()
    # A storey stepped back from the ones below has its own outside walls.
    bays_by_grid: dict = {}

    def bays_for(grid):
        key = tuple(tuple(bool(v) for v in row) for row in grid)
        if key not in bays_by_grid:
            sides: dict[str, list] = {}
            for side, wall in _facade_runs(grid):
                sides.setdefault(side, []).extend(wall)
            bays_by_grid[key] = _bays(sides, front, near, far)
        return bays_by_grid[key]

    if kind in SHOP_FRONT_KINDS or shop_ground:
        glass = _bays(by_side, front, 1, far, only=front)
        # Glass only where there is a shop behind it: a block of flats' long
        # sides are both "front", and its offices and toilets were glazed
        # like the shops.
        g0 = building.storeys[0]
        sales = RETAIL_ROOMS | FRONT_ROOMS | {"restaurant"}
        glass = [b for b in glass if g0.grid[b[4]][b[3]]
                 and g0.rooms[g0.grid[b[4]][b[3]] - 1].kind in sales]
        glass_set = set(glass)
        ground_bays = glass + [b for b in bays if b not in glass_set]
    house_like = kind in HOUSE_LIKE_KINDS

    for level, storey in enumerate(building.storeys):
        # Where the floor below put its windows. A house is laid out room by
        # room on every storey, so its rooms upstairs are not the rooms
        # downstairs and its windows landed wherever this floor's rooms
        # happened to want them: looking up at one from the street, 27 of
        # every 100 upstairs windows stood above a window. A wall that has a
        # window below it takes that column first, and the even spacing fills
        # whatever is left.
        under = set(building.storeys[level - 1].windows) if level else set()
        blocked = set(getattr(storey, "wall_pieces", set())) | storey.party
        # Every tile of whatever hangs on a wall, not only the one it is anchored
        # on: wall_pieces holds one edge per piece, so a three-tile whiteboard
        # kept a window off its first tile and had one through the other two.
        for role, fx, fy, fd in storey.furniture:
            if _is_wall_piece(role):
                try:
                    cells = _cells_for(role, fx, fy, fd)
                except KeyError:
                    cells = [(fx, fy)]
                blocked |= {_wall_edge(cx, cy, fd) for cx, cy in cells}
        # Edges with a dresser, shelf or lamp behind them. A window there has
        # its square cleared, and in a full room the piece has nowhere else
        # to go and is thrown away: nine in ten of the pieces the clear-up
        # took out stood at a window. A house window moves along its wall to
        # a clear stretch when there is one; a room gets its window anyway.
        behind = set()
        cover = set()
        for role, fx, fy, fd in storey.furniture:
            if _blocks(role):
                cover.update(_tiles_under(role, fx, fy, fd))
            if _blocks(role) and not _under_a_window(role):
                for cx, cy in _tiles_under(role, fx, fy, fd):
                    behind |= {(cx, cy, "N"), (cx, cy + 1, "N"), (cx, cy, "W"), (cx + 1, cy, "W")}

        def hemmed(edge) -> bool:
            """A window whose square has furniture both sides of it along the
            wall: the gap between two dressers, a pocket nobody can open it
            from."""
            x, y, d = edge
            sides = ((x - 1, y), (x + 1, y), (x - 1, y - 1), (x + 1, y - 1)) if d == "N"                 else ((x, y - 1), (x, y + 1), (x - 1, y - 1), (x - 1, y + 1))
            return (sides[0] in cover and sides[1] in cover) or (sides[2] in cover and sides[3] in cover)

        def worse(edge) -> int:
            return 2 if edge in behind else 1 if hemmed(edge) else 0
        # No window where a tile carries both a west and a north wall - the
        # inside corner of every step down a diagonal side. BuildingEd draws
        # that corner as one piece; a window there replaced it with a window
        # facing one way, and the other half of the wall was left out.
        #
        # A room wall counts as much as the facade does. This used to ask
        # _facade_runs alone, which only knows the outside of the building, so
        # the corner where a room's wall meets the facade was not blocked -
        # and that is most of them. Counted on a city map: 290 windows over
        # 60 buildings hanging in a gap, every one of them where an inside
        # wall arrives at the outside one on the same tile.
        edges = {(x, y, d) for _side, wall in _facade_runs(storey.grid)
                 for x, y, d, _ix, _iy in wall} | _room_edges(storey.grid)
        on_corner = {(x, y) for x, y, d in edges
                     if (x, y, "N" if d == "W" else "W") in edges}
        blocked |= {(x, y, d) for x, y, d in edges if (x, y) in on_corner}
        # Doors land on those corners too, and break them the same way. They
        # move along their wall rather than being dropped, so nothing is shut
        # in - and it happens before the windows are placed, which keep clear
        # of wherever the doors end up.
        _doors_off_corners(storey, edges, on_corner)
        # Shuttered windows need the tile either side for their shutters: a
        # window two tiles from a door or another window had its shutters
        # jammed against the frame or overlapping the next one's.
        clear = WINDOW_CLEARANCE_SHUTTERED if house_like else 1
        for x, y, d in storey.doors:
            for off in range(-clear, clear + 1):
                blocked.add((x + off, y, d) if d == "N" else (x, y + off, d))
        placed: list[tuple[int, int, str]] = []

        def spaced(x, y, d):
            for px, py, pd in placed:
                if pd != d:
                    continue
                if d == "N" and py == y and abs(px - x) <= clear:
                    return False
                if d == "W" and px == x and abs(py - y) <= clear:
                    return False
            return True

        def add(edge):
            # Never across the hole in a mall floor. That edge is a railing
            # over the concourse below, and glazing it put windows in mid-air
            # inside the building.
            if edge in storey.railing or edge in storey.open_edge:
                return
            storey.windows.append(edge)
            placed.append(edge)

        taken: dict[int, int] = {}
        if house_like and under:
            # Every column the floor below glazed, in one pass over the
            # facade rather than room by room: the room boundaries upstairs
            # are not the ones downstairs, and asking per room left half the
            # columns to the even spacing again.
            where = {(x, y, d): (ix, iy)
                     for _side, wall in _facade_runs(storey.grid)
                     for x, y, d, ix, iy in wall}
            for edge in sorted(under):
                spot = where.get(edge)
                if spot is None or edge in blocked or not spaced(*edge):
                    continue
                # A facade is built in columns. Where the window below stands
                # and a dresser or a shelf is against the wall upstairs, the
                # window goes in anyway: the clear-up moves the piece, and
                # dropping the column instead is what gave the town away.
                # A hemmed edge - furniture both sides of a pocket - still
                # gives way, because there the window cannot be opened.
                if worse(edge) and edge not in behind:
                    continue
                idx = storey.grid[spot[1]][spot[0]]
                if not idx:
                    continue
                room = storey.rooms[idx - 1]
                cap = 0 if room.is_core else ROOM_WINDOW_CAP.get(
                    room.kind, DEFAULT_ROOM_WINDOW_CAP)
                if room.is_shaft or taken.get(idx, 0) >= cap:
                    continue
                add(edge)
                taken[idx] = taken.get(idx, 0) + 1
        if house_like:
            # A house's windows are placed room by room, centred on each
            # outside wall and evenly spread along it, as Knox County's are.
            # Bays laid out for the whole facade put two or three windows
            # side by side in one room and none along the rest of the wall.
            for idx, room in enumerate(storey.rooms, 1):
                if room.is_shaft:
                    continue
                cap = ROOM_WINDOW_CAP.get(room.kind, DEFAULT_ROOM_WINDOW_CAP)
                if room.is_core:
                    cap = 0
                runs = sorted(_outside_runs(storey, idx), key=lambda r: -len(r[1]))
                for _side, wall in runs:
                    if taken.get(idx, 0) >= cap or len(wall) < MIN_WALL_FOR_WINDOW:
                        continue
                    n = max(1, min(cap - taken.get(idx, 0),
                                   (len(wall) + 1) // HOUSE_WINDOW_EVERY))
                    for k in range(n):
                        i = int((k + 0.5) * len(wall) / max(1, n))
                        # The nearest spot to the even spacing that is clear
                        # of doors, corners and the other windows.
                        for j in sorted(range(1, len(wall) - 1),
                                        key=lambda j: (worse(wall[j]), abs(j - i))):
                            edge = wall[j]
                            if edge not in blocked and spaced(*edge):
                                add(edge)
                                taken[idx] = taken.get(idx, 0) + 1
                                break
        for x, y, d, ix, iy in ([] if house_like else (ground_bays if level == 0 else bays_for(storey.grid))):
            if (x, y, d) in blocked:
                continue
            idx = storey.grid[iy][ix]
            if not idx:
                continue
            room = storey.rooms[idx - 1]
            if house_like:
                cap = ROOM_WINDOW_CAP.get(room.kind, DEFAULT_ROOM_WINDOW_CAP)
            else:
                cap = SERVICE_WINDOW_CAP.get(room.kind, 1 << 30)
            if room.is_shaft:
                continue
            # A corridor or stair hall along an outside wall gets that wall's
            # windows like any room: capped at one, a corridor running the
            # length of a tower's side left sixty tiles of blank brick.
            if taken.get(idx, 0) >= cap:
                continue
            add((x, y, d))
            taken[idx] = taken.get(idx, 0) + 1
            if level == 0 and (kind in SHOP_FRONT_KINDS or shop_ground) \
                    and (x, y, d, ix, iy) in glass_set:
                storey.shop_front.add((x, y, d))

        # The bays keep windows in columns, but a room they miss would have no
        # daylight at all. Any room people spend time in that still has none
        # gets one in the middle of its longest outside wall.
        for idx, room in enumerate(storey.rooms, 1):
            if taken.get(idx) or room.kind not in LIVED_IN:
                continue
            for _side, wall in _outside_runs(storey, idx):
                # A straight wall keeps its corners clear; a one- or two-tile
                # step of a diagonal wall has no corners to spare.
                inner = wall[1:-1] if len(wall) >= MIN_WALL_FOR_WINDOW else wall
                candidates = sorted(inner, key=lambda e: (worse(e), abs(
                    wall.index(e) - len(wall) // 2)))
                spot = next((e for e in candidates if e not in blocked and spaced(*e)), None)
                if spot is not None:
                    add(spot)
                    taken[idx] = 1
                    break


# A piece against a wall should have its back to that wall. Most pieces define
# all four facings; the few that only define N and W fall back to the nearest.
_ORIENT_FALLBACK = {"S": "N", "E": "W", "N": "N", "W": "W"}


def _facing(role: str, wanted: str) -> str:
    """The orientation to actually emit for `role` against a given wall."""
    have = C.FURNITURE[role]
    if wanted in have:
        return wanted
    alt = _ORIENT_FALLBACK[wanted]
    return alt if alt in have else next(iter(have))


def _cells_for(role: str, x: int, y: int, orient: str) -> list[tuple[int, int]]:
    """Tiles a furniture piece covers, derived from its tile-offset keys."""
    out = []
    for key in C.FURNITURE[role][orient]:
        dx, dy = (int(v) for v in key.split(","))
        out.append((x + dx, y + dy))
    return out


def _wall_anchor(role: str, x: int, y: int, orient: str,
                 wall: str) -> tuple[int, int]:
    """Anchor a multi-tile piece so its footprint ends at the named wall."""
    cells = _cells_for(role, 0, 0, orient)
    if wall == "E":
        x -= max(cx for cx, _cy in cells)
    elif wall == "S":
        y -= max(cy for _cx, cy in cells)
    return x, y


SWITCH = "switch"
# One light switch per this much floor, in tiles, and never more than this
# many in a room. A room of a hundred tiles keeps its single switch; a
# supermarket's sales floor gets one about every eight metres.
LIGHT_EVERY_TILES = 110
MAX_SWITCHES = 8
# How often a room too small to need one by area gets a switch anyway. In a
# house every room has one and there are eight rooms; a school has forty and
# a switch in each came to 0.20 per 10 m2 against Knox County's 0.03 - a
# wall of light switches down every corridor. Workplaces get them sparsely.
# These are the round wall fittings that read as clocks in a render, and
# there were dozens of them: 0.27 per 10 m2 against Knox County's 0.12 over
# the same cells. Not every room in any building has one.
SWITCH_SHARE_CIVIC = 0.14
SWITCH_SHARE_HOME = 0.22
SWITCHES_APART = 7
# Things fixed to a wall rather than standing against it. A painting has only
# north and west sprites, so on a south or east wall the fallback drew it on
# the far edge of the tile, hanging in mid-air a tile into the room; shelves
# and mirrors on those walls rendered as planks floating over the floor. They
# go on north and west walls only. (The switch has true east and south
# sprites, and every room needs one, so it may go anywhere.)
# Pieces that read the same whichever wall they are against: a table has no
# front, so the north sprite on a south wall is not wrong, it is just a table.
_EITHER_WAY = {"table", "coffee_table", "dining_table", "diner_table", "crib", "door_mat",
               "picnic_table", "pizza_table", "bath_mat", "rug", "rug_small",
               "rug_wide", "shag_rug", "roof_ac",
               "elevator_door"}
# Anything with no south or east sprite, worked out from the catalogue rather
# than listed by hand. The fallback draws such a piece with its north or west
# sprite, which puts it on the far edge of the tile: a corkboard on a south
# wall hangs a tile into the room, a rack faces its own back. Listing them by
# hand meant a role added later was quietly wrong, which is how 1076 pieces
# in 200 houses ended up against a wall they have no sprite for.
#
# Painting, mirror and shelf are here despite having all four: on a south or
# east wall they render as planks floating over the floor.
NORTH_WEST_ONLY = (
    {role for role, facings in C.FURNITURE.items() if set(facings) <= {"N", "W"}}
    - _EITHER_WAY
    | {"painting", "mirror", "shelf"}
    | set(getattr(C, "ERIKA_WALL_ART", ()))
    | set(getattr(C, "ERIKA_SHOP_ADS", ())))
# With Erika's Tiles: shops hang its drinks and magazine posters instead of
# paintings, and these rooms get a drinks machine.
SHOP_DECOR_ROOMS = {"generalstore", "conveniencestore", "clothingstore", "cafe", "bar",
                    "grocery", "liquorstore", "pharmacy", "bookstore", "toolstore",
                    "restaurant", "gym"}
VENDING_ROOMS = {"cafe", "lobby", "gym", "classroom", "clinic", "breakroom"}
ERIKA_SHELF_SHARE = 0.5

_ERIKA: list[bool] = []
# Set from the map's settings before anything is laid out. None means nobody
# has said, and the answer is whatever is installed.
_ERIKA_ALLOWED: list[bool] = []


def use_mod_tiles(allowed: bool) -> None:
    """Say whether this map may use Erika's Tiles, whatever is installed.

    A map built with the mod's tiles needs the mod to look right, and a player
    who would rather keep to the game's own art - or hand the map to somebody
    who has not subscribed - has no way back once it is built. The settings
    carry the answer (vanilla_tiles), and the build sets it here before the
    first building, because the check below is asked once and remembered.
    """
    _ERIKA_ALLOWED[:] = [bool(allowed)]
    _ERIKA.clear()


def _erika_ready() -> bool:
    """Whether buildings may use Erika's Tiles; asked once per process."""
    if _ERIKA_ALLOWED and not _ERIKA_ALLOWED[0]:
        return False
    if not _ERIKA:
        import os
        try:
            import knoxpaths
            _ERIKA.append(os.environ.get("KNOXMAP_NO_MOD_TILES") != "1"
                          and knoxpaths.erikas_tiles_ready())
        except Exception:      # noqa: BLE001 - no tools, no mod tiles
            _ERIKA.append(False)
    return _ERIKA[0]


def _is_wall_piece(role: str) -> bool:
    """Hung on a wall rather than standing on the floor. Rugs are on their own
    floor layer but are floor pieces: placed as wall pieces, their 2x2
    footprint was never checked against the room and hung out through the
    outside wall, floating beside the building."""
    return C.FURNITURE_LAYERS.get(role, "Furniture") not in ("Furniture", "FloorFurniture")


def _wall_edge(x: int, y: int, facing: str) -> tuple[int, int, str]:
    """The wall a piece facing `facing` on tile (x, y) hangs on, as a door or
    window would name it."""
    if facing == "N":
        return (x, y, "N")
    if facing == "S":
        return (x, y + 1, "N")
    if facing == "W":
        return (x, y, "W")
    return (x + 1, y, "W")


# What stands in the middle of a room, as (role, dx, dy, orient) laid out for
# a room wider than it is deep; turned for the other way. Orient is the side a
# piece has its back to, as for pieces against a wall, so a chair north of a
# table has its back to the north. Rugs go on the floor layer under the rest.
# The group, and a clear tile all round it, has to fit inside the room away
# from the furniture along its walls and the tiles in front of doors, or the
# room keeps an open floor instead. `repeat` is how many a big room may take.
# FALLBACK_GROUPS are smaller sets tried when the first does not fit.
CENTRE_GROUPS: dict[str, tuple[list[tuple[str, int, int, str]], int]] = {
    # The sofa facing the television across the coffee table, an armchair at
    # the side: how every lived-in living room in Knox County is arranged.
    "livingroom": ([("rug_wide", 0, 1, "W"), ("sofa", 0, 0, "N"), ("armchair", 3, 2, "E"),
                    ("coffee_table", 0, 2, "N"), ("tv", 1, 4, "S")], 1),
    "motelroom": ([("double_bed", 0, 0, "W"), ("sidetable", 0, 2, "W"),
                   ("tv", 3, 0, "E"), ("armchair", 3, 2, "W")], 1),
    # An open-plan flat: the same seating, set out in the middle of the floor,
    # because the cooking end has the walls.
    "openplan": ([("rug_wide", 0, 1, "W"), ("sofa", 0, 0, "N"),
                  ("coffee_table", 0, 2, "N")], 1),
    "lobby": ([("rug_wide", 0, 0, "W"), ("coffee_table", 1, 0, "W")], 2),
    "dining": ([("rug_wide", 0, 0, "W"), ("dining_table", 1, 1, "W"),
                ("chair", 0, 1, "W"), ("chair", 3, 1, "E"),
                ("chair", 1, 0, "N"), ("chair", 2, 2, "S")], 1),
    # A mat under the table. Rugs lie on their own layer and block nothing, so
    # it costs the group a row of clearance and nothing else.
    "kitchen": ([("rug_small", 0, 0, "W"), ("round_table", 1, 0, "W"),
                 ("chair", 0, 0, "W"), ("chair", 2, 0, "E")], 1),
    # A canteen is rows of long tables, not one table in the middle.
    "diningroom": ([("dining_table", 1, 1, "W"), ("chair", 0, 1, "W"),
                    ("chair", 3, 1, "E"), ("chair", 1, 0, "N"),
                    ("chair", 2, 2, "S")], 10),
    # A bedroom has no centre group. Its whole group used to be a rug, which
    # put one in every bedroom in the town: 63% of our rugs sat in bedrooms
    # against Knox County's 6%, where two thirds of them are in living
    # rooms. The bed and its tables come from bed_against_wall instead.
    "office": ([("dining_table", 0, 1, "W"), ("chair", 0, 0, "N")], 3),
    "library": ([("dining_table", 1, 1, "W"), ("chair", 0, 1, "W"),
                 ("chair", 3, 1, "E")], 3),
    "classroom": ([("dining_table", 0, 0, "W"), ("chair", 0, 1, "S"),
                   ("chair", 1, 1, "S")], 6),
    "church": ([("table", 2, 0, "W"), ("chair", 0, 2, "S"),
                ("chair", 2, 2, "S"), ("chair", 4, 2, "S"),
                ("chair", 1, 4, "S"), ("chair", 3, 4, "S")], 1),
    "cafe": ([("round_table", 1, 0, "W"), ("chair", 0, 0, "W"),
              ("chair", 2, 0, "E")], 3),
    "restaurant": ([("round_table", 1, 1, "W"), ("chair", 0, 1, "W"),
                    ("chair", 2, 1, "E"), ("chair", 1, 0, "N"),
                    ("chair", 1, 2, "S")], 6),
}
# An exam room's couch stands out from the wall where the doctor can reach
# both sides of it, and a ward's beds stand in rows with room to walk between.
CENTRE_GROUPS["clinic"] = ([("bed_plain", 0, 0, "W")], 1)
CENTRE_GROUPS["medical"] = ([("bed_plain", 0, 0, "W")], 4)
# Every dining room seats people the same way, however it is named; the salon
# and the ice cream parlour have tables too.
# (Dining rooms, cafés and bars are fitted out by interiors.furnish_dining.)
CENTRE_GROUPS["breakroom"] = CENTRE_GROUPS["cafe"]
CENTRE_GROUPS["theatre"] = ([("chair", 0, 0, "S"), ("chair", 1, 0, "S"), ("chair", 2, 0, "S"),
                             ("chair", 3, 0, "S"), ("chair", 4, 0, "S"), ("chair", 5, 0, "S")], 40)
# A stockroom is not one wall of shelving: racks stand out in the floor in
# rows with the boxes beside them, and the aisles between are walked. A home's
# box room gets none (_furnish_middle).
STOCK_GROUP = ([("metal_rack", 0, 0, "N"), ("metal_rack", 0, 1, "N"),
                ("crate", 3, 0, "N"), ("crate", 3, 1, "N")], 4)
STOCKROOMS = {"storage", "warehouse", "factory", "workshop", "armory", "evidenceroom"}
for _kind in list(ROOM_STYLE) + list(STOCKROOMS):
    if (_kind in STOCKROOMS or _kind.endswith("storage")) and _kind not in CENTRE_GROUPS:
        CENTRE_GROUPS[_kind] = STOCK_GROUP
# Commercial kitchens are fitted with counters wall to wall, like a home's.
# Rooms of a business laid out by their trade (interiors.furnish_*), not by
# the wishlist round the walls.
TRADE_LAYOUTS = {"bar": "furnish_bar", "laundry": "furnish_laundromat",
                 "gym": "furnish_gym", "church": "furnish_church"}
KITCHENS = {"kitchen", "openplan", "breakroom", "restaurantkitchen", "pizzakitchen", "burgerkitchen",
            "dinerkitchen", "chinesekitchen", "sushikitchen", "mexicankitchen", "seafoodkitchen",
            "cafekitchen", "bakerykitchen", "icecreamkitchen"}
FALLBACK_GROUPS: dict[str, list[list[tuple[str, int, int, str]]]] = {
    "motelroom": [[("double_bed", 0, 0, "W"), ("tv", 3, 0, "E")]],
    "church": [[("table", 1, 0, "W"), ("chair", 0, 2, "S"),
                ("chair", 2, 2, "S")]],
    "livingroom": [[("sofa", 0, 0, "N"), ("coffee_table", 0, 2, "N"), ("tv", 0, 4, "S")],
                   [("sofa", 0, 0, "N"), ("coffee_table", 0, 2, "N")],
                   [("rug_small", 0, 0, "W"), ("coffee_table", 0, 0, "N")]],
    "dining": [[("dining_table", 1, 0, "W"), ("chair", 0, 0, "W"), ("chair", 3, 0, "E")],
               [("round_table", 1, 0, "W"), ("chair", 0, 0, "W"), ("chair", 2, 0, "E")]],
    # Half the game's kitchens have a table in them and one in eight of ours
    # did: the group and its aisle want a five-by-three clear block, and a
    # kitchen four tiles across with two doors in it has nowhere to put one.
    # A table on its own is the last thing tried, as it is what a kitchen too
    # small to eat in still has.
    "kitchen": [[("round_table", 0, 0, "W"), ("chair", 1, 0, "E")],
                [("round_table", 0, 0, "W")]],
    "lobby": [[("rug_small", 0, 0, "W"), ("coffee_table", 0, 0, "N")]],
}
_TURN = {"W": "N", "N": "W", "E": "S", "S": "E"}


# For a television on each wall: where the wall starts, the way along it and
# the way into the room.
_TV_WALLS = {"N": ("x0", "y0", (1, 0), (0, 1)), "S": ("x0", "y1", (1, 0), (0, -1)),
             "W": ("x0", "y0", (0, 1), (1, 0)), "E": ("x1", "y0", (0, 1), (-1, 0))}
_SIDE_OF_VECTOR = {(1, 0): "E", (-1, 0): "W", (0, 1): "S", (0, -1): "N"}
_OPPOSITE_SIDE = {"N": "S", "S": "N", "W": "E", "E": "W"}


def _furnish_living(plan: Plan, idx: int, room: Room,
                    occupied: set[tuple[int, int]],
                    keep_clear: set[tuple[int, int]],
                    palette: dict[str, str], keeps_open=None) -> bool:
    """The television against a wall, the sofa straight across from it facing
    it, the coffee table between, an armchair at the side and a rug under the
    table: how people arrange a living room. Tries each wall and each spot
    along it, the most open first, and takes the first that fits. In a tight
    room it can omit the table. Returns false if no aligned pair fits."""
    cells = {(x, y) for y in range(room.y0, room.y1 + 1)
             for x in range(room.x0, room.x1 + 1) if _room_at(plan, x, y) == idx}
    if len(cells) < 9:
        return False
    sofa = palette.get("sofa", "sofa")
    armchair = palette.get("armchair", "armchair")
    if any(r not in C.FURNITURE for r in (sofa, armchair, "tv", "coffee_table")):
        return False
    taken = occupied | keep_clear

    def footprint(role, orient, tile):
        """The tiles a piece covers with its middle on `tile`, and its anchor."""
        base = _cells_for(role, 0, 0, orient)
        xs, ys = [c[0] for c in base], [c[1] for c in base]
        px = tile[0] - (min(xs) + (max(xs) - min(xs)) // 2)
        py = tile[1] - (min(ys) + (max(ys) - min(ys)) // 2)
        return (px, py), [(cx + px, cy + py) for cx, cy in base]

    bounds = {"x0": room.x0, "x1": room.x1, "y0": room.y0, "y1": room.y1}
    options = []
    for side, (ox_name, oy_name, along, into) in _TV_WALLS.items():
        origin = (bounds[ox_name], bounds[oy_name])
        length = (room.x1 - room.x0 + 1) if along[0] else (room.y1 - room.y0 + 1)
        depth = (room.y1 - room.y0 + 1) if along[0] else (room.x1 - room.x0 + 1)
        if depth < 3 or length < 3:
            continue

        def tile(a, d, origin=origin, along=along, into=into):
            return (origin[0] + along[0] * a + into[0] * d,
                    origin[1] + along[1] * a + into[1] * d)
        blocked = sum(tile(a, 0) in keep_clear or tile(a, 1) in keep_clear
                      for a in range(length))
        # The windows go in last and along the outside walls, so a television
        # (or a sofa's back) there ends up in front of one: an inside wall
        # first.
        outside = sum(_room_at(plan, tile(a, 0)[0] - into[0], tile(a, 0)[1] - into[1]) == 0
                      for a in range(length))
        options.append((blocked, outside, -min(depth, 8), side, tile, length, depth, along))
    options.sort(key=lambda o: o[:4])

    fallback = None
    for _blocked, _outside, _d, side, tile, length, depth, along in options:
        # Leave out the table when the room only fits the television and sofa.
        sofa_d = 4 if depth >= 6 else min(3, depth - 1)
        centre = length // 2
        spots = sorted(range(1, length - 1), key=lambda a: (abs(a - centre), a))
        table_orient = "N" if side in "NS" else "W"
        for a in spots:
            tv_at, tv_cells = footprint("tv", _facing("tv", side), tile(a, 0))
            tb_at, tb_cells = footprint("coffee_table", table_orient, tile(a, 2))
            sf_orient = _facing(sofa, _OPPOSITE_SIDE[side])
            sf_at, sf_cells = footprint(sofa, sf_orient, tile(a, sofa_d))
            tv_orient = _facing("tv", side)
            pair = [("tv", tv_orient, tv_at, tv_cells),
                    (sofa, sf_orient, sf_at, sf_cells)]
            parts = pair + [("coffee_table", table_orient, tb_at, tb_cells)]
            # The armchair at the end of the table, turned to face it.
            for lateral in (1, -1):
                back = _SIDE_OF_VECTOR[(along[0] * lateral, along[1] * lateral)]
                ac_orient = _facing(armchair, back)
                ac_at, ac_cells = footprint(armchair, ac_orient, tile(a + 3 * lateral, 2))
                trial = parts + [(armchair, ac_orient, ac_at, ac_cells)]
                if _living_fits(plan, idx, trial, cells, taken, tile(a, 1), keeps_open):
                    parts = trial
                    break
            else:
                if not _living_fits(plan, idx, parts, cells, taken, tile(a, 1), keeps_open):
                    if fallback is None and _living_fits(
                            plan, idx, pair, cells, taken, tile(a, 1), keeps_open):
                        fallback = (pair, tile(a, 1))
                    continue
            rug = "rug_wide" if side in "NS" else "rug"
            rug_at, rug_cells = footprint(rug, "W", tile(a, 2))
            if len(parts) > 2 and rug in C.FURNITURE and all(c in cells for c in rug_cells):
                plan.furniture.append((rug, rug_at[0], rug_at[1], "W"))
            for role, orient, at, cs in parts:
                plan.furniture.append((role, at[0], at[1], orient))
                occupied.update(cs)
            occupied.add(tile(a, 1))
            return True
    if fallback is not None:
        parts, gap = fallback
        for role, orient, at, cs in parts:
            plan.furniture.append((role, at[0], at[1], orient))
            occupied.update(cs)
        occupied.add(gap)
        return True
    return False


def _living_fits(plan, idx, parts, cells, taken, gap, keeps_open) -> bool:
    every = [c for _r, _o, _a, cs in parts for c in cs]
    if len(set(every)) != len(every) or gap in taken:
        return False
    if any(c not in cells or c in taken for c in every):
        return False
    return not (keeps_open and not keeps_open(set(every)))


def _furnish_middle(plan: Plan, idx: int, room: Room,
                    occupied: set[tuple[int, int]],
                    keep_clear: set[tuple[int, int]],
                    palette: dict[str, str] | None = None,
                    keeps_open=None) -> int:
    """Put the room's centre group(s) in its open middle. Returns how many.
    keeps_open(tiles), when given, may refuse a spot that cuts the floor."""
    spec = CENTRE_GROUPS.get(room.kind)
    if room.kind == "lobby" and (plan.kind in CIVIC_KINDS or plan.kind == "apartment"):
        spec = ([("shop_counter", 1, 0, "N"), ("chair", 0, 2, "S"),
                 ("chair", 1, 2, "S"), ("chair", 2, 2, "S")], 1)
    if spec is None or room.is_core or room.is_shaft:
        return 0
    if spec is STOCK_GROUP and plan.kind in HOME_KINDS:
        return 0          # a box room in a house is a cupboard, not a stockroom
    palette = palette or {}
    if room.kind == "livingroom" and _furnish_living(
            plan, idx, room, occupied, keep_clear, palette, keeps_open):
        return 1
    if room.kind == "livingroom":
        return 0

    def own(group):
        return [(palette.get(role, role), dx, dy, o) for role, dx, dy, o in group]

    group, repeat = spec
    before = len(plan.furniture)
    placed = _place_group(plan, idx, room, own(group), repeat, occupied, keep_clear,
                          keeps_open)
    fallbacks = FALLBACK_GROUPS.get(room.kind, ())
    if room.kind == "lobby" and (plan.kind in CIVIC_KINDS or plan.kind == "apartment"):
        fallbacks = [[("shop_counter", 0, 0, "N"), ("chair", 0, 2, "S")],
                     [("shop_counter", 0, 0, "N")]]
    for smaller in fallbacks:
        if placed:
            break
        placed = _place_group(plan, idx, room, own(smaller), 1, occupied, keep_clear,
                              keeps_open)
    if placed:
        _seat_the_table(plan, idx, keep_clear, plan.furniture[before:], keeps_open)
    return placed


# A kitchen's working run along one wall, by how much wall there is: the fridge
# at the end, the stove with worktop either side of it, the sink in the
# worktop. "sink" is the household's kitchen sink, set into a counter later.
KITCHEN_RUNS = (("fridge", "counter", "stove", "counter", "sink"),
                ("fridge", "stove", "counter", "sink"))


def _kitchen_run(plan: Plan, idx: int, slots, occupied: set, no_go: set,
                 wishlist: list, counter: str, side_rank: dict, keeps_open=None) -> bool:
    """Fridge, stove and sink in one run of worktop along a wall.

    Placed one at a time wherever a wall had room, only a third of kitchens
    had the three in one connected run, and two in five had the stove hard
    against the sink. Takes the longest run the best wall offers - the
    plumbing wall first, as the wishlist would - and leaves the room as it
    was when no wall is long enough."""
    want = {
        "fridge": next((w for w in wishlist if w.startswith("fridge")), None),
        "stove": next((w for w in wishlist if w.startswith("stove")), None),
        "sink": next((w for w in wishlist if _is_sink(w)), None),
        "counter": counter,
    }
    if not (want["fridge"] and want["stove"] and want["sink"])             or any(want[k] not in C.FURNITURE for k in want):
        return False
    inward = {"N": (0, 1), "S": (0, -1), "W": (1, 0), "E": (-1, 0)}
    by_wall: dict = {}
    for x, y, facing in slots:
        line = y if facing in ("N", "S") else x
        by_wall.setdefault((facing, line), []).append((x, y))
    runs = []
    for (facing, _line), tiles in by_wall.items():
        along = sorted(tiles, key=lambda t: t[0] if facing in ("N", "S") else t[1])
        run = [along[0]]
        for t in along[1:]:
            prev = run[-1]
            if abs(t[0] - prev[0]) + abs(t[1] - prev[1]) == 1:
                run.append(t)
            else:
                runs.append((facing, run))
                run = [t]
        runs.append((facing, run))
    runs.sort(key=lambda fr: (side_rank.get(fr[0], 9), -len(fr[1])))

    # The fridge and stove a tile off every doorway: doors slide off corners
    # after the room is furnished, and a stove beside one ended up in the way
    # and was taken out. Worktop may run up to the door.
    near_door = {(x + dx, y + dy) for x, y in _door_tiles(plan)
                 for dx in (-1, 0, 1) for dy in (-1, 0, 1)}

    def usable(t, facing, key):
        fx, fy = inward[facing]
        front = (t[0] + fx, t[1] + fy)
        if key in ("fridge", "stove") and (t in near_door or front in near_door):
            return False
        return (t not in occupied and t not in no_go and _room_at(plan, *t) == idx
                and front not in occupied and _room_at(plan, *front) == idx)

    for pattern in KITCHEN_RUNS:
        n = len(pattern)
        for facing, run in runs:
            for i in range(len(run) - n + 1):
                tiles = run[i:i + n]
                # The fridge at whichever end of the run is nearer a corner.
                order = pattern if i <= len(run) - n - i else pattern[::-1]
                if not all(usable(t, facing, k) for t, k in zip(tiles, order)):
                    order = order[::-1]
                    if not all(usable(t, facing, k) for t, k in zip(tiles, order)):
                        continue
                if keeps_open and not keeps_open(set(tiles)):
                    continue
                fx, fy = inward[facing]
                for (x, y), key in zip(tiles, order):
                    role = want[key]
                    orient = _facing(role, facing)
                    plan.furniture.append((role, x, y, orient))
                    occupied.add((x, y))
                    if _needs_front(role):
                        occupied.add((x + fx, y + fy))
                for key in ("fridge", "stove", "sink"):
                    wishlist.remove(want[key])
                for _ in range(order.count("counter")):
                    if counter in wishlist:
                        wishlist.remove(counter)
                return True
    return False


def _pair_up(plan: Plan, idx: int, occupied: set, no_go: set, keeps_open=None) -> None:
    """What goes with a piece, where the room laid the piece out on its own:
    a coffee table a step in front of a sofa, chairs round a dining table, a
    lamp on a desk someone sits at. A sofa set against a wall by the wishlist
    had no table (two in three), and an open-plan flat's sofa almost never."""
    def free(cells) -> bool:
        return all(_room_at(plan, *c) == idx and c not in occupied and c not in no_go
                   for c in cells) and (keeps_open is None or keeps_open(set(cells)))

    mine = [f for f in plan.furniture if _room_at(plan, f[1], f[2]) == idx]
    roles = {f[0] for f in mine}
    for role, x, y, o in mine:
        if (role == "sofa" or role.startswith("sofa_")) and "coffee_table" not in roles                 and "coffee_table" in C.FURNITURE and o in _STEP:
            sx, sy = _STEP[_OPPOSITE[o]]
            t_or = "N" if o in ("N", "S") else "W"
            ax, ay = (1, 0) if o in ("N", "S") else (0, 1)      # along the sofa
            gap = [(cx + sx, cy + sy) for cx, cy in _cells_for(role, x, y, o)]
            if not all(_room_at(plan, *g) == idx and g not in occupied for g in gap):
                continue
            # Squarely in front, else half a seat to either side.
            for k in (0, -1, 1):
                at = (x + 2 * sx + k * ax, y + 2 * sy + k * ay)
                cells = _cells_for("coffee_table", *at, t_or)
                if free(cells):
                    plan.furniture.append(("coffee_table", at[0], at[1], t_or))
                    occupied.update(cells)
                    roles.add("coffee_table")
                    break
    tables = [f for f in mine if f[0] in SEATS_AT]
    if tables:
        taken = {c for f in plan.furniture if _blocks(f[0]) for c in _cells_for(*f)}
        for role, tx, ty, orient in tables:
            seats = sum(1 for f in plan.furniture if f[0] == "chair" and any(
                abs(f[1] - cx) + abs(f[2] - cy) == 1 for cx, cy in _cells_for(role, tx, ty, orient)))
            for cell in _cells_for(role, tx, ty, orient):
                for (dx, dy), side in _BESIDE:
                    c = (cell[0] + dx, cell[1] + dy)
                    if seats >= SEATS_AT[role] or c in taken or not free([c]):
                        continue
                    plan.furniture.append(("chair", c[0], c[1], _facing("chair", side)))
                    taken.add(c)
                    occupied.add(c)
                    seats += 1
    chairs = {(f[1], f[2]) for f in plan.furniture if f[0] == "office_chair"}
    lit = {(f[1], f[2]) for f in plan.furniture if f[0] == "lamp"}
    for role, x, y, o in mine:
        if role not in DESK_ROLES or o not in _STEP or "lamp" not in C.FURNITURE:
            continue
        cells = _cells_for(role, x, y, o)
        sx, sy = _STEP[_OPPOSITE[o]]
        if not any((cx + sx, cy + sy) in chairs for cx, cy in cells) or set(cells) & lit:
            continue
        # On the end of the desk away from the chair's middle.
        lx, ly = cells[-1]
        plan.furniture.append(("lamp", lx, ly, o))
        lit.add((lx, ly))


# Every piece in a centre group needs its own clear block and a tile of aisle
# all round the group, so in a kitchen four tiles across only the bare table
# ever fitted: 0.17 chairs a kitchen against the game's 1.10. A chair is
# tucked against the table, not given an aisle of its own, so they go on after
# the group is down.
TABLE_SEATS = 2
# A dining table is set for four, one each end and one each long side: the
# game's own are, and two chairs round one read as a table pushed aside.
SEATS_AT = {"dining_table": 4}
_BESIDE = (((-1, 0), "W"), ((1, 0), "E"), ((0, -1), "N"), ((0, 1), "S"))


def _seat_the_table(plan: Plan, idx: int, keep_clear: set[tuple[int, int]],
                    added: list, keeps_open=None) -> None:
    """Chairs on the free tiles beside a table the centre group just put down."""
    tables = [(role, x, y, o) for role, x, y, o in added
              if role in ("round_table", "dining_table")]
    if not tables:
        return
    taken = {c for role, x, y, o in plan.furniture
             if C.FURNITURE_LAYERS.get(role, "Furniture") == "Furniture"
             for c in _cells_for(role, x, y, o)}
    # Only up to what the group would have seated anyway: a dining table that
    # already came with four chairs is not given two more.
    already = sum(1 for role, *_ in added if role == "chair") // len(tables)
    for role, tx, ty, orient in tables:
        seats = already
        for cell in _cells_for(role, tx, ty, orient):
            for (dx, dy), side in _BESIDE:
                if seats >= SEATS_AT.get(role, TABLE_SEATS):
                    break
                x, y = cell[0] + dx, cell[1] + dy
                if (x, y) in taken or (x, y) in keep_clear or _room_at(plan, x, y) != idx:
                    continue
                if keeps_open and not keeps_open({(x, y)}):
                    continue
                plan.furniture.append(("chair", x, y, _facing("chair", side)))
                taken.add((x, y))
                seats += 1


# Pieces a room has one of, however big it is.
ONCE = {"sofa", "tv", "double_bed", "bed", "bath", "toilet", "stove", "fridge", "washer",
        "vanity", "crib",
        "shower", "kitchen_sink", "sink", "coffee_table", "dining_table", "wardrobe",
        "water_cooler", "whiteboard", "corkboard", "vending"}


def _once(role: str) -> bool:
    return role in ONCE or role.startswith(("sofa_", "double_bed", "bed_", "wardrobe", "erika_vending"))


def _place_group(plan: Plan, idx: int, room: Room,
                 group: list[tuple[str, int, int, str]], repeat: int,
                 occupied: set[tuple[int, int]],
                 keep_clear: set[tuple[int, int]], keeps_open=None) -> int:
    """Up to `repeat` copies of one group, nearest the room's middle first,
    skipping a spot whose solid tiles keeps_open(tiles) refuses."""
    if (room.x1 - room.x0) < (room.y1 - room.y0):
        # Rugs are drawn one way round whatever their orient, so a turned
        # group swaps the wide rug for the long one.
        swap = {"rug_wide": "rug", "rug": "rug_wide"}
        group = [(swap.get(role, role), dy, dx, _TURN[o]) for role, dx, dy, o in group]
    pieces = [(role, dx, dy, _facing(role, o)) for role, dx, dy, o in group]
    shape = [(dx + cx, dy + cy) for role, dx, dy, o in pieces
             for cx, cy in _cells_for(role, 0, 0, o)]
    gx0 = min(x for x, _ in shape)
    gy0 = min(y for _, y in shape)
    gx1 = max(x for x, _ in shape)
    gy1 = max(y for _, y in shape)
    solid = {(dx + cx, dy + cy) for role, dx, dy, o in pieces
             if C.FURNITURE_LAYERS.get(role, "Furniture") == "Furniture"
             for cx, cy in _cells_for(role, 0, 0, o)}
    mid_x, mid_y = (room.x0 + room.x1) / 2, (room.y0 + room.y1) / 2
    spots = sorted(
        ((x, y) for y in range(room.y0 - gy0, room.y1 - gy1 + 1)
         for x in range(room.x0 - gx0, room.x1 - gx1 + 1)),
        key=lambda p: abs(p[0] + (gx0 + gx1) / 2 - mid_x)
        + abs(p[1] + (gy0 + gy1) / 2 - mid_y))
    placed = 0
    for ox, oy in spots:
        if placed >= repeat:
            break
        ring = {(x, y) for y in range(oy + gy0 - 1, oy + gy1 + 2)
                for x in range(ox + gx0 - 1, ox + gx1 + 2)}
        # The aisle round the group may run over the walkway or a doorway's
        # clearance - it is bare floor there - but nothing solid may.
        if any(_room_at(plan, x, y) != idx or (x, y) in occupied for x, y in ring):
            continue
        if any((ox + x, oy + y) in keep_clear for x, y in solid):
            continue
        if keeps_open and not keeps_open({(ox + x, oy + y) for x, y in solid}):
            continue
        for role, dx, dy, o in pieces:
            plan.furniture.append((role, ox + dx, oy + dy, o))
        # The whole footprint and its ring stay clear of the next copy, so
        # tables in a classroom keep an aisle between them.
        occupied.update(ring)
        occupied.update((ox + x, oy + y) for x, y in solid)
        placed += 1
    return placed


def _bathroom_wishlist(area: int, public: bool) -> list[str]:
    if public:
        basins = max(1, min(3, area // 12))
        return [role for _ in range(basins) for role in ("toilet", "sink_public")] \
            + ["mirror"]
    # Biggest fixture first. The tub and the cubicle are two tiles against
    # everything else's one, and with the slots now dealt out in a fixed order
    # rather than shuffled, a toilet and a basin taking the plumbing wall first
    # left no run of two anywhere and 86 of 227 bathrooms got neither - the
    # mat follows the tub it is laid beside, and the mirror the basin it hangs
    # over, so both of those still come after their own fixture.
    fixtures = ["bath" if area >= BATHROOM_TILES else "shower",
                "toilet", "sink", "mirror"]
    # A tub is two tiles and its mat two more, which a bathroom the size this
    # generator aims for takes without trouble: the band above is 9 to 12
    # tiles, matching Knox County's 6.5 m2, and a Knox County bathroom has a
    # bath in it. Asking for 14 asked for more than the generator ever cuts -
    # 1.5% of them - so every bathroom got the shower instead and 378 baths in
    # 200 houses became none. Below the band, in a flat's or a motel's
    # bathroom, there is only room for the shower.
    if area >= BATHROOM_TILES:
        fixtures.append("bath_mat")
    if area >= 18:
        fixtures.append("shelf")
    return fixtures


def _bath_mat_spot(plan: Plan, idx: int, room: Room,
                   occupied: set[tuple[int, int]], keep_clear: set[tuple[int, int]]):
    tub = next(((x, y, orient) for role, x, y, orient in plan.furniture
                if role == "bath" and _room_at(plan, x, y) == idx), None)
    if tub is None:
        return None
    tx, ty, orient = tub
    tub_cells = _cells_for("bath", tx, ty, orient)
    center_x, center_y = (room.x0 + room.x1) / 2, (room.y0 + room.y1) / 2
    candidates = []
    for x, y in tub_cells:
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            ax, ay = x + dx, y + dy
            for mat_orient in C.FURNITURE["bath_mat"]:
                cells = _cells_for("bath_mat", ax, ay, mat_orient)
                if any(_room_at(plan, cx, cy) != idx or (cx, cy) in occupied
                       or (cx, cy) in keep_clear for cx, cy in cells):
                    continue
                mat_x = sum(cx for cx, _cy in cells) / len(cells)
                mat_y = sum(cy for _cx, cy in cells) / len(cells)
                distance = abs(mat_x - center_x) + abs(mat_y - center_y)
                candidates.append((distance, ay, ax, mat_orient, cells))
    if not candidates:
        return None
    _distance, ay, ax, mat_orient, cells = min(candidates)
    return ax, ay, mat_orient, cells


def _door_tiles(plan: Plan) -> set[tuple[int, int]]:
    """Tiles every way in keeps clear, DOOR_CLEAR_DEPTH deep either side."""
    door_tiles: set[tuple[int, int]] = set()
    # An opened shopfront is a way in just as much as a door, so it gets a
    # door's clearance. The game's mall keeps its openings empty; ours had a
    # shelf or a chiller across 64% of them, which is no way into a shop.
    ways_in = list(plan.doors) + sorted(plan.open_edge)
    for x, y, d in ways_in:
        # Two tiles deep either side: one clear tile in front of a door still
        # had a fridge or a bookcase on the next, and nobody could step past.
        for k in range(DOOR_CLEAR_DEPTH):
            door_tiles.add((x + k, y) if d == "W" else (x, y + k))
            door_tiles.add((x - 1 - k, y) if d == "W" else (x, y - 1 - k))
    return door_tiles


SHOP_STAFF_ROOMS = {"storage", "grocerystorage", "office", "bathroom"}


def SHOP_FLOOR_KINDS() -> set:
    from .. import interiors
    return set(interiors.STORES)


def _room_walkway(plan: Plan, idx: int, door_tiles: set,
                  stairs: tuple[int, int, str] | None) -> set[tuple[int, int]]:
    """Tiles of room idx nothing standing may cover: a path joining its ways
    in (doors, opened shopfronts, the stair landings), or a spine from its one
    way in, plus the door clearance that touches it. Empty for the core or a
    lift shaft, which take nothing standing anyway.

    Clearance that does not touch the path is left out: the second tile in
    front of a door across a one-tile hall lands in the room beyond, cut off
    from its walkway. door_tiles keeps it clear all the same."""
    r = plan.rooms[idx - 1]
    if r.is_core or r.is_shaft:
        return set()
    cells = {(x, y) for y in range(r.y0, r.y1 + 1) for x in range(r.x0, r.x1 + 1)
             if plan.grid[y][x] == idx}
    entries = []
    shop = r.kind in SHOP_FLOOR_KINDS()
    for x, y, d in list(plan.doors) + sorted(plan.open_edge):
        inside, other = (((x, y), (x - 1, y)) if d == "W" else ((x, y), (x, y - 1)))
        if inside not in cells:
            inside, other = other, inside
        # A shop's customers do not walk to its staff doors: the way through
        # joins the street to the rest of the sales floor, and the stock room
        # and office doors open onto whatever aisle is beside them. Counting
        # them put the walkway along the back wall, where the coolers go.
        if shop and (x, y, d) in plan.doors and _room_at(plan, *other) and                 plan.rooms[_room_at(plan, *other) - 1].kind in SHOP_STAFF_ROOMS:
            continue
        entries += [(x, y), (x - 1, y) if d == "W" else (x, y - 1)]
    if stairs is not None:
        sx, sy, sd = stairs
        dx, dy = (0, 1) if sd == "N" else (1, 0)
        entries += [(sx - dx, sy - dy), (sx + dx * STAIR_RUN, sy + dy * STAIR_RUN)]
    walk = FR.walkway(cells, entries)
    clear = door_tiles & cells
    todo = sorted(walk)
    while todo:
        x, y = todo.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n in clear and n not in walk:
                walk.add(n)
                todo.append(n)
    return walk


def _furnish(plan: Plan, rng: random.Random,
             stairs: tuple[int, int, str] | None = None,
             street: str | None = None) -> None:
    """Push furniture against room walls, skipping tiles a door needs clear.

    Every room, the corridor and stair hall included, first gets a light
    switch on the wall beside its door. The game hangs a room's ceiling light
    off its switch, so a room without one has no light at all - which is why
    so many rooms were pitch dark: the switch was only on some rooms'
    wishlists, and even there it was written to the floor rather than a wall.
    """
    door_tiles = _door_tiles(plan)
    door_edges = set(plan.doors) | set(plan.open_edge)
    # The lift doors take their stretch of wall: nothing hangs on it.
    for _rect, (lx, ly, ld) in plan.shafts:
        door_edges |= {(lx, ly + i, "W") if ld == "W" else (lx + i, ly, "N")
                       for i in range(SHAFT_SIZE)}
    # Tiles of the flight. A switch hung there would be deleted along with the
    # furniture cleared off the staircase, leaving the stair hall dark.
    stair_tiles: set[tuple[int, int]] = set()
    if stairs is not None:
        sx, sy, sd = stairs
        dx, dy = (0, 1) if sd == "N" else (1, 0)
        stair_tiles = {(sx + dx * i, sy + dy * i) for i in range(STAIR_RUN)}

    for _rect, (lx, ly, ld) in plan.shafts:
        plan.furniture.append(("elevator_door", lx, ly, ld))

    from .. import interiors
    # Each home its own furniture: one palette per flat, or per storey of a
    # house, drawn from a seed of this storey's own.
    home_seed = rng.random()
    palettes: dict[int, dict[str, str]] = {}
    # Who lives in each home (interiors.household), and which of its rooms
    # are a child's so far, for a teenager to be given one.
    households: dict[int, dict] = {}
    kid_rooms: dict[int, int] = {}

    for idx, r in enumerate(plan.rooms, start=1):
        # A lift car has no switch and no furniture: it is a sealed box.
        if r.is_shaft:
            continue
        start = len(plan.furniture)
        # Walls this room has, as (x, y, facing) for a piece standing on the
        # tile with its back to that wall.
        slots = []
        for y in range(r.y0, r.y1 + 1):
            for x in range(r.x0, r.x1 + 1):
                if plan.grid[y][x] != idx or (x, y) in stair_tiles:
                    continue
                for facing, nx, ny in (("N", x, y - 1), ("S", x, y + 1),
                                       ("W", x - 1, y), ("E", x + 1, y)):
                    if _room_at(plan, nx, ny) != idx:
                        slots.append((x, y, facing))
        used_walls: set[tuple[int, int, str]] = set()
        # Outside walls are where the windows go, and the windows are laid out
        # last, in columns up the facade: a painting or switch hung there took
        # the bay and left a hole in the column. Hang things inside first.
        step = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}

        def on_facade(slot: tuple[int, int, str]) -> bool:
            x, y, facing = slot
            ox, oy = step[facing]
            return not _room_at(plan, x + ox, y + oy)

        def hang(role: str, x: int, y: int, facing: str) -> bool:
            if role in NORTH_WEST_ONLY and facing in ("S", "E"):
                return False
            orient = _facing(role, facing)
            cells = _cells_for(role, x, y, orient)
            # Every tile of the piece in this room: a two-tile mirror hung at
            # the end of a wall reached through the outside wall.
            if any(_room_at(plan, cx, cy) != idx for cx, cy in cells):
                return False
            edges = {_wall_edge(cx, cy, facing) for cx, cy in cells}
            if edges & (door_edges | used_walls | plan.wall_pieces):
                return False
            plan.furniture.append((role, x, y, orient))
            used_walls.update(edges)
            plan.wall_pieces.update(edges)
            return True

        # The switch: on a wall one tile from this room's door, the way people
        # actually fit them, or on any wall if the door is awkward.
        mine = [(x, y) for x, y in door_tiles if _room_at(plan, x, y) == idx]
        by_reach = sorted(
            slots,
            key=lambda s: min((abs(s[0] - dx) + abs(s[1] - dy) for dx, dy in mine),
                              default=0) + (4 if on_facade(s) else 0))
        # The game hangs one ceiling light off each switch, and that light
        # only reaches so far, so a sales floor or a warehouse lit by the one
        # switch beside its door was dark everywhere else - "lighting seems
        # somewhat broken". A big room gets a switch every so often, spread
        # out along its walls, the way a real shop is wired.
        # Every room keeps one. The game lights a room from the switch in
        # it, so a room without one is dark whatever the sprite count says -
        # tools/audit_layouts.py fails a plan for it. Thinning these out to
        # match Knox County's 0.12 per 10 m2 left 1,945 rooms unlit, and it
        # was chasing the wrong thing anyway: the round fittings that read as
        # clocks were school_desk, not these.
        floor_switch = 1
        want_switches = max(floor_switch,
                            min(MAX_SWITCHES,
                                r.area // LIGHT_EVERY_TILES))
        lit: list[tuple[int, int]] = []
        for x, y, facing in by_reach:
            if len(lit) >= want_switches:
                break
            if (x, y) in mine and _wall_edge(x, y, facing) in door_edges:
                continue
            if lit and min(abs(x - lx) + abs(y - ly) for lx, ly in lit) < SWITCHES_APART:
                continue
            if hang(SWITCH, x, y, facing):
                lit.append((x, y))
        if not lit and want_switches:
            for x, y, facing in by_reach:
                if hang(SWITCH, x, y, facing):
                    break

        # The walkway: a path joining this room's ways in, or a spine from its
        # one door, that nothing standing may cover. Placed round it rather
        # than cleared afterwards, which deleted toilets and beds along with
        # the plants.
        walk = _room_walkway(plan, idx, door_tiles, stairs)
        keep_clear = door_tiles | stair_tiles | walk
        room_cells = {(x, y) for y in range(r.y0, r.y1 + 1)
                      for x in range(r.x0, r.x1 + 1) if plan.grid[y][x] == idx}
        # A walkway one tile wide is a squeeze: a wardrobe on one side and a
        # sofa on the other and the way through is a needle's eye, which is
        # what "furniture blocks the doorway" looks like in the game. Keep a
        # sleeve of floor either side of the way in, and either side of the
        # door itself, so the way through is never narrowed below two tiles.
        sleeve = {(x + dx, y + dy) for x, y in walk
                  for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))}
        sleeve |= {(x + dx, y + dy) for x, y in door_tiles
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))}
        sleeve = (sleeve - walk - door_tiles) & room_cells
        no_go = door_tiles | walk

        floor = FR.OpenFloor(room_cells, walk, POCKET_TILES)
        counted = [start]

        def keeps_open(tiles) -> bool:
            """Whether a new blocking piece on `tiles` leaves the walkway clear
            and cuts off no patch of floor bigger than a pocket. Only this
            room's pieces have gone in since `start`, and only by appending
            (_stand_on_something inserts once the room is done)."""
            for role, x, y, o in plan.furniture[counted[0]:]:
                if _blocks(role):
                    floor.block(_cells_for(role, x, y, o))
            counted[0] = len(plan.furniture)
            return floor.keeps_open(tiles)
        # Nothing standing goes in the stair hall or corridor: a flat's front
        # door and the only way past the flight both run through it, and one
        # bookcase beside the stairs closes the corridor.
        if r.is_core:
            # The walls are fair game, though, and a rug is walked over.
            # Sparingly: a hall in Knox County holds 1.2 pieces per 10 m2
            # all told, most of it a chair or a light rather than anything
            # underfoot.
            inside = [s for s in slots if not on_facade(s)]
            facade = [s for s in slots if on_facade(s)]
            # Inside walls first and most of the facade left alone, because
            # the windows are laid out last and in columns: a picture on a
            # bay takes it and leaves a hole up the front of the building.
            hung = 0
            for n, slot in enumerate(
                    inside + facade[:max(1, len(facade) // CORE_FACADE_SHARE)]):
                if n % CORE_ART_EVERY:
                    continue
                art_set = (CORE_WALL_ART_CIVIC
                           if plan.kind in ART_FREE_KINDS else CORE_WALL_ART)
                if not art_set:
                    break
                if hang(art_set[hung % len(art_set)], *slot):
                    hung += 1
            laid = 0
            for n, (x, y) in enumerate(
                    (x, y) for y in range(r.y0, r.y1 + 1)
                    for x in range(r.x0, r.x1 + 1)
                    if plan.grid[y][x] == idx and (x, y) not in keep_clear):
                if n % CORE_RUG_EVERY:
                    continue
                # A rug is two or three tiles wide, so every tile of it has to
                # be this room's floor and clear; one hanging over the edge is
                # a rug through the wall.
                order = CORE_RUGS[laid % len(CORE_RUGS):] + CORE_RUGS[:laid % len(CORE_RUGS)]
                for role in order:
                    cells = _cells_for(role, x, y, "N")
                    if any(_room_at(plan, cx, cy) != idx or (cx, cy) in keep_clear
                           for cx, cy in cells):
                        continue
                    plan.furniture.append((role, x, y, "N"))
                    laid += 1
                    break
            continue
        # A shop's sales floor is fitted out as a whole - rows of shelving,
        # the till by the door - not from a list pushed against its walls.
        if r.kind in interiors.STORES and interiors.furnish_store(
                plan, idx, r, rng, door_tiles, stair_tiles | walk, street):
            interiors.dress_room(plan, idx, r, random.Random(f"{home_seed}:{idx}:dress"),
                                 door_edges, no_go, keeps_open, walk)
            continue
        pal = palettes.get(r.unit)
        if pal is None:
            pal = palettes[r.unit] = interiors.palette(
                random.Random(f"{home_seed}:{r.unit}"), profile=plan.profile)
        _, _, base = ROOM_STYLE[r.kind]
        # A one-tile-wide spot takes nothing standing (see _off_narrow_spots).
        # Counted as taken from the start, the piece goes somewhere it can be
        # used instead of being placed there and thrown out afterwards.
        occupied: set[tuple[int, int]] = {
            (x, y) for x, y in room_cells if _narrow(plan.grid, x, y)}
        office = r.kind == "office" and plan.kind not in HOUSE_LIKE_KINDS
        office_fitted = False
        classroom = r.kind == "classroom" and plan.kind in CIVIC_KINDS
        eatery = r.kind in interiors.DINING_ROOMS
        salon = r.kind == "aesthetic" and plan.kind not in HOME_KINDS
        trade = (TRADE_LAYOUTS.get(r.kind)
                 if plan.kind not in HOME_KINDS and plan.kind != "apartment" else None)
        trade_fitted = False
        commercial_kitchen = r.kind in interiors.COMMERCIAL_KITCHENS
        if r.kind in ("garage", "mechanic", "firegarage") and interiors.furnish_service_bay(
                plan, idx, r, rng, door_tiles, keep_clear,
                mechanic=(r.kind in ("mechanic", "firegarage"))):
            continue
        if office:
            base, office_fitted = interiors.furnish_office(
                plan, idx, r, rng, occupied, keep_clear, keeps_open)
        elif classroom:
            base, office_fitted = interiors.furnish_classroom(
                plan, idx, r, rng, occupied, keep_clear, keeps_open)
        elif salon:
            base = interiors.furnish_salon(plan, idx, r, rng, occupied, no_go, keeps_open)
        elif trade is not None:
            got = getattr(interiors, trade)(plan, idx, r, rng, occupied, no_go, keeps_open)
            if got is not None:
                base, trade_fitted = got, True
        elif eatery:
            base = interiors.furnish_dining(plan, idx, r, rng, occupied,
                                            stair_tiles | walk, door_tiles, street,
                                            keeps_open)
        elif commercial_kitchen:
            base = interiors.KITCHEN_KIT.get(r.kind, interiors.DEFAULT_KITCHEN_KIT)
        elif r.kind == "bathroom":
            public = plan.kind not in HOUSE_LIKE_KINDS | {"apartment"}
            base = _bathroom_wishlist(r.area, public)
            if public and r.area >= 9:
                # The toilet occupies the cubicle; its front stays clear for the door.
                fitted = 0
                for x, y, facing in slots:
                    if "toilet" not in base:
                        break
                    if facing not in ("N", "W") or (x, y, facing) in door_edges:
                        continue
                    dx, dy = (0, 1) if facing == "N" else (1, 0)
                    inside = {(x, y)}
                    front = (x + dx, y + dy)
                    if facing == "N":
                        side_edges = {(x, y, "W"), (x + 1, y, "W")}
                    else:
                        side_edges = {(x, y, "N"), (x, y + 1, "N")}
                    if (x, y) in no_go or (x, y) in occupied or front in occupied \
                            or front in door_tiles or _room_at(plan, *front) != idx \
                            or side_edges & door_edges or not keeps_open(inside):
                        continue
                    plan.furniture.append(("toilet", x, y, _facing("toilet", facing)))
                    occupied.update(inside | {front})
                    no_go.add(front)
                    plan.stalls.append((x, y, facing))
                    plan.wall_pieces.add((x, y, facing))
                    plan.wall_pieces.update(side_edges)
                    base.remove("toilet")
                    fitted += 1
                if fitted:
                    base = [role for role in base if role != "toilet"]
        elif plan.kind in CIVIC_KINDS and r.kind in CIVIC_ROOMS:
            # A police station's corridor is not somebody's hallway. The
            # wishlist for hall and lobby is a domestic one - side table,
            # picture, bookcase, sofa - and a station was getting 8.2 side
            # tables, 6.9 chests and 5.3 pictures a building, which is what
            # reads as a living room with a cell block attached. Knox County
            # furnishes a police office out of location_business_office at
            # 3.15 pieces per 10 m2 and almost nothing else.
            base = list(CIVIC_ROOMS[r.kind])
        if not base:
            # A room with nothing on its wishlist: the lift shaft, which the
            # builder puts in as machinery rather than a room, and anything
            # drawn as one by hand (knoxbuild/designer.py). Nothing to stand
            # in it, and asking for one piece in a list of none used to end
            # the whole building in "integer modulo by zero".
            continue
        shelving = [s for s in SHELVING.get(r.kind, DEFAULT_SHELVING)
                    if s in C.FURNITURE] or ["shelf"]
        if plan.kind in HOME_KINDS:
            # No warehouse racking in somebody's house.
            keep = [s for s in shelving if s not in WAREHOUSE_ROLES]
            shelving = keep or ["shelf"]
        base = [rng.choice(shelving) if role == "shelf" else pal.get(role, role)
                for role in base]
        if plan.kind in HOME_KINDS:
            base = [HOME_STORE.get(role, role) for role in base]
        # A mansion dresses every room past its wishlist: the pictures, rugs and
        # bookcases a house with money has. Before the art is drawn from the
        # game's own tiles, so a mansion hangs a different print in each room.
        if plan.grand and r.kind in MANSION_EXTRA:
            base = base + MANSION_EXTRA[r.kind]
        if _erika_ready():
            # With Erika's Tiles installed, pictures and plants come from its
            # far larger range, so no two living rooms hang the same print.
            shop = r.kind in SHOP_DECOR_ROOMS
            base = [rng.choice(C.ERIKA_SHOP_ADS) if role == "painting" and shop and C.ERIKA_SHOP_ADS
                    else rng.choice(C.ERIKA_WALL_ART)
                    if role in ("painting", "mirror") and C.ERIKA_WALL_ART
                    and plan.kind not in ART_FREE_KINDS
                    and not (role == "mirror" and (salon or r.kind == "bathroom"))
                    else rng.choice(C.ERIKA_PLANTS)
                    if role == "plant" and C.ERIKA_PLANTS and plan.kind in HOME_KINDS
                    else rng.choice(C.ERIKA_SHELVES)
                    if role == "bookshelf" and C.ERIKA_SHELVES and rng.random() < ERIKA_SHELF_SHARE
                    else role for role in base]
            if r.kind in VENDING_ROOMS and C.ERIKA_VENDING:
                base = base + [rng.choice(C.ERIKA_VENDING)]
        # Scale the wishlist with floor area, or a 12x9 living room ends up
        # with four items rattling around in it.
        # Knox County's rooms hold 8-13 pieces per 10 m2 of floor (counting
        # each tile a piece covers); one piece per 7 tiles gave 3-4. Only the
        # small things repeat: a big living room got a second sofa and
        # television, a big bathroom two baths.
        # A house's laundry is mostly not in the kitchen. Knox County has a
        # washer or dryer in 16% of its kitchens; ours had one in 80%, because
        # anything on the wishlist proper is placed every time. Added before
        # the target is counted, so it is one of the pieces the room is worth
        # rather than an extra on top.
        if r.kind == "kitchen" and rng.random() < LAUNDRY_IN_KITCHEN:
            base = base + ["washer"]
        if plan.kind in HOME_KINDS and not r.is_core:
            home = households.get(r.unit)
            if home is None:
                seed = plan.profile.seed if plan.profile else home_seed
                home = households[r.unit] = interiors.household(
                    random.Random(f"{seed}:{r.unit}:household"), plan)
            base = interiors.for_household(base, r, home, kid_rooms, random.Random(
                f"{home_seed}:{idx}:who"))
            base = interiors.extras(base, r, random.Random(f"{home_seed}:{idx}:extras"))
        # One piece per four tiles, which is 2.5 per 10 m2 - about what a
        # living room or a bedroom holds. A room packed with furniture by
        # its nature gets more: Knox County's classrooms run to 8.2 pieces
        # per 10 m2, nearly all of them desks, and at the standard rate ours
        # could only reach 1.36 of 2.97.
        per = ROOM_DENSITY.get(r.kind, 4)
        if plan.profile:
            per = max(1, round(per * (1.18 - 0.36 * plan.profile.clutter)))
        target = max(len(base), min(40, r.area // per))
        if (eatery or salon or commercial_kitchen or office_fitted or trade_fitted
                or r.kind in {"bathroom", "theatre"}):
            target = len(base)       # fitted out; nothing more to scatter
        wishlist = []
        art_chance = WALL_ART_CHANCE
        art_cap = WALL_ART_CAP
        if plan.profile:
            art_chance = max(0.2, min(0.85,
                                     art_chance + (plan.profile.wealth - 0.5) * 0.25
                                     - plan.profile.wear * 0.12))
            if plan.profile.wealth >= 0.78 and plan.profile.wear < 0.3:
                art_cap = 2
        if plan.grand:
            # A mansion's walls carry a gallery where a house's walls carry one
            # print, and every one of its rooms is hung: the cap is what stops
            # a floor-area wishlist turning into wallpaper.
            art_cap = MANSION_ART_CAP
        art = (art_cap if plan.kind in ART_FREE_KINDS
               else 0 if (plan.grand or rng.random() < art_chance) else art_cap)
        for i in range(target):
            role = base[i % len(base)]
            if i >= len(base) and _once(role):
                continue
            # Pictures and mirrors are the one thing that repeats freely, so
            # scaling the list with floor area turned a big room into a
            # gallery. Everything else keeps its share.
            if role in ("painting", "mirror") or role.startswith(("erika_art", "erika_ad")):
                if art >= art_cap:
                    continue
                art += 1
            # Counters have a budget of their own (_counter_runs), and the
            # wishlist cycling round put a big kitchen over it before the
            # budget was ever consulted.
            if role.startswith("counter") and wishlist.count(role) >= WISHLIST_COUNTERS:
                continue
            wishlist.append(role)
        plumbing_rooms = KITCHENS | {"kitchen", "bathroom", "laundry"}
        side_scores = {side: [0, 0, 0] for side in step}
        for x, y, facing in slots:
            dx, dy = step[facing]
            neighbor = _room_at(plan, x + dx, y + dy)
            linked_plumbing = (neighbor and neighbor != idx
                               and r.kind in plumbing_rooms
                               and plan.rooms[neighbor - 1].kind in plumbing_rooms)
            side_scores[facing][0] += int(bool(linked_plumbing))
            side_scores[facing][1] += int(not on_facade((x, y, facing)))
            side_scores[facing][2] += 1
        side_order = sorted(step, key=lambda side: (
            -side_scores[side][0], -side_scores[side][1], -side_scores[side][2], side))
        side_rank = {side: rank for rank, side in enumerate(side_order)}
        door_frontier = [(x, y) for x, y in door_tiles
                         if _room_at(plan, x, y) == idx]

        def slot_order(slot):
            x, y, facing = slot
            distance = min((abs(x - dx) + abs(y - dy) for dx, dy in door_frontier),
                           default=0)
            return side_rank[facing], -distance, y, x

        floor_slots = sorted(slots, key=slot_order)
        # Boxes are not a wall of them: a few, apart, some stacked two high.
        crates: set[tuple[int, int]] = set()
        crate_cap = max(2, len(floor_slots) // CRATE_ONE_IN)

        def centre():
            # The middle, with an aisle round it the wall pieces must leave
            # free; placed after them, it almost never found room.
            before = len(plan.furniture)
            if not office and not eatery and not trade_fitted:
                _furnish_middle(plan, idx, r, occupied, keep_clear, pal, keeps_open)
            if r.kind == "livingroom" and not any(
                    role == "tv" for role, *_ in plan.furniture[before:]):
                wishlist[:] = [role for role in wishlist if role != "tv"]
            # The center group already supplied its focal pieces; do not add
            # them again from the room wishlist.
            for role, *_ in plan.furniture[before:]:
                consumed = (_once(role)
                            or (r.kind == "church" and role == "table")
                            or (r.kind == "livingroom" and role.startswith("armchair"))
                         or (r.kind in ("clinic", "medical") and role.startswith("bed"))
                         or (r.kind == "motelroom" and role == "sidetable")
                            or (r.kind == "lobby"
                                and (plan.kind in CIVIC_KINDS or plan.kind == "apartment")
                                and role == "shop_counter"))
                if role in wishlist and consumed:
                    wishlist.remove(role)

        def place(role):
            if role == "bath_mat":
                # A mat is walked over, so it may lie on the walkway.
                mat = _bath_mat_spot(plan, idx, r, occupied, door_tiles | stair_tiles)
                if mat is not None:
                    mx, my, mat_orient, mat_cells = mat
                    plan.furniture.append((role, mx, my, mat_orient))
                    occupied.update(mat_cells)
                return
            if role == "mirror" and r.kind == "bathroom":
                basin = next(((x, y, orient) for basin_role, x, y, orient
                              in plan.furniture
                              if _is_sink(basin_role) and _room_at(plan, x, y) == idx),
                             None)
                if basin is not None:
                    bx, by, facing = basin
                    near_basin = sorted(
                        (slot for slot in slots if slot[2] == facing),
                        key=lambda slot: abs(slot[0] - bx) + abs(slot[1] - by))
                    for slot in near_basin:
                        if not hang("mirror", *slot):
                            continue
                        mirror_orient = _facing("mirror", slot[2])
                        occupied.update(_cells_for("mirror", slot[0], slot[1],
                                                   mirror_orient))
                        return
            if _is_wall_piece(role):
                # A picture goes on bare wall before it goes behind a dresser,
                # and on the north wall before the west one. Both are the same
                # drawing question: the game draws a floor piece after the
                # thing on the wall of its own tile, so a picture hung where a
                # wardrobe or a piano stands is drawn over the piece instead of
                # behind it - a framed print floating across a bookshelf. Bare
                # wall first; then the north wall, which is drawn first.
                for x, y, facing in sorted(
                        floor_slots,
                        key=lambda s: ((s[0], s[1]) in occupied,
                                       0 if s[2] == "N" else 1, on_facade(s))):
                    if hang(role, x, y, facing):
                        break
                return
            # A toilet is sat on from the square before it, and a dresser once
            # stood there. Only the room's essentials may take it: in a tight
            # bathroom the basin has nowhere else, and kept off it the basin
            # went onto the window square and was cleared away.
            toilet_fronts = set() if FR.priority(role, r.kind) == FR.ESSENTIAL else {
                (tx - _STEP[o][0], ty - _STEP[o][1]) for t, tx, ty, o in plan.furniture
                if t == "toilet" and o in _STEP and _room_at(plan, tx, ty) == idx}
            for (x, y, wanted) in floor_slots:
                if role in NORTH_WEST_ONLY and wanted in ("S", "E"):
                    continue
                orient = _facing(role, wanted)
                ax, ay = _wall_anchor(role, x, y, orient, wanted)
                cells = _cells_for(role, ax, ay, orient)
                if any(c in occupied or c in no_go or c in toilet_fronts for c in cells):
                    continue
                # A bed or a stove may stand in the sleeve round the way
                # through; a dresser or a plant may not, or the way through
                # is a needle's eye between two tall pieces.
                if (sleeve and FR.priority(role, r.kind) != FR.ESSENTIAL
                        and any(c in sleeve for c in cells)):
                    continue
                if any(_room_at(plan, cx, cy) != idx for cx, cy in cells):
                    continue
                front = set()
                if _needs_front(role):
                    # A fridge, a stove or a wardrobe is opened from the tile
                    # in front of it; that tile stays floor.
                    fx, fy = {"N": (0, 1), "S": (0, -1), "W": (1, 0), "E": (-1, 0)}[wanted]
                    front = {(cx + fx, cy + fy) for cx, cy in cells} - set(cells)
                    if any(c in occupied or _room_at(plan, *c) != idx for c in front):
                        continue
                if role == "crate" and (len(crates) >= crate_cap or any(
                        n in crates for cx, cy in cells
                        for n in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)))):
                    continue
                # Nothing standing that shuts off a patch of the floor.
                if _blocks(role) and not keeps_open(cells):
                    continue
                occupied.update(cells)
                occupied.update(front)
                plan.furniture.append((role, ax, ay, orient))
                if role == "crate":
                    crates.update(cells)
                    if rng.random() < CRATE_STACKED:
                        plan.furniture.append(("crate_top", ax, ay, orient))
                return

        # Most important first, so a plant cannot take the fridge's place:
        # the whiteboard, the centre group if it holds an essential (the
        # sofa), the bed, the other essentials, the centre group otherwise,
        # then the rest, secondary before decoration.
        if r.kind == "classroom" and "whiteboard" in wishlist:
            preferred = "N" if r.w >= r.h else "W"
            board_slots = sorted(
                (s for s in slots if s[2] == preferred),
                key=lambda s: (on_facade(s),
                               abs(s[0] - (r.x0 + r.x1) / 2)
                               + abs(s[1] - (r.y0 + r.y1) / 2)))
            for slot in board_slots:
                if hang("whiteboard", *slot):
                    wishlist.remove("whiteboard")
                    break
        centre_first = any(
            FR.priority(pal.get(role, role), r.kind) == FR.ESSENTIAL
            for role, *_ in CENTRE_GROUPS.get(r.kind, ((), 0))[0])
        if centre_first:
            centre()
        # A bed goes head to a wall between its bedside tables.
        if r.kind in ("bedroom", "kidsbedroom"):
            bed = next((role for role in wishlist if role in (pal.get("double_bed"), pal.get("bed"))
                        or role.startswith(("double_bed", "bed", "bunk_bed"))), None)
            if bed and interiors.bed_against_wall(plan, idx, r, slots, occupied, no_go,
                                                  bed, "nightstand", keeps_open):
                wishlist.remove(bed)
                if "sidetable" in wishlist:
                    wishlist.remove("sidetable")
                # The bedside lamp on a bedside table, not on a chest of its
                # own somewhere else in the room.
                stand = next((f for f in plan.furniture if f[0] == "nightstand"
                              and _room_at(plan, f[1], f[2]) == idx), None)
                if stand and "lamp" in wishlist:
                    plan.furniture.append(("lamp", stand[1], stand[2], stand[3]))
                    wishlist.remove("lamp")
        if r.kind in ("kitchen", "openplan") and not commercial_kitchen:
            _kitchen_run(plan, idx, slots, occupied, no_go, wishlist,
                         pal.get("counter", "counter"), side_rank, keeps_open)
        for role in [x for x in wishlist if FR.priority(x, r.kind) == FR.ESSENTIAL]:
            place(role)
        # Pictures take the wall before the furniture does. A dresser, a
        # bookshelf or a piano keeps off a wall that already carries something
        # (keep_off), so art hung last - which is where decoration sorts -
        # ended up sharing its tile with the piece in front of it, and the
        # game draws that piece over the picture. Hung first, the picture has
        # bare wall behind it and the room stands off it.
        for role in [x for x in wishlist if _is_wall_piece(x) and x != SWITCH]:
            place(role)
        if not centre_first:
            centre()
        for role in FR.in_priority_order(
                [x for x in wishlist if FR.priority(x, r.kind) != FR.ESSENTIAL
                 and not (_is_wall_piece(x) and x != SWITCH)], r.kind):
            place(role)

        if commercial_kitchen:
            # Steel counters, and no wall cupboards or microwave. A working
            # kitchen really is worktop wall to wall, so it keeps no budget.
            _counter_runs(plan, idx, slots, occupied, no_go, stair_tiles,
                          "counter_2", cabinets=False, keeps_open=keeps_open)
        elif r.kind in KITCHENS:
            _counter_runs(plan, idx, slots, occupied, no_go, stair_tiles,
                          pal.get("counter", "counter"), area=r.area, rng=rng,
                          keeps_open=keeps_open)
        _pair_up(plan, idx, occupied, no_go, keeps_open)
        _stand_on_something(plan, idx, r, pal)
        plan.sleeve |= sleeve
        if not r.is_core:
            interiors.dress_room(plan, idx, r, random.Random(f"{home_seed}:{idx}:dress"),
                                 door_edges, no_go, keeps_open, walk)


# Pieces drawn at worktop height: a sink, a television, a table lamp, a pot
# plant. Put down on their own they float over bare floor - a sink plumbed into
# the ground - so each gets something to stand on first, the way the game's
# own houses have them. Found by the height of their sprites (a floating
# piece's lowest pixel sits well above the floor diamond); the television is
# drawn standing, but no home keeps one on the carpet.
# Pieces drawn with their base part-way up the tile, so they need something
# under them. Sinks are matched by name as well: three more were added with
# the sink variety and every one of them hung in the air, because the set was
# a list of the two that existed at the time.
SURFACE_ROLES = {"kitchen_sink", "sink", "lamp", "tv", "register",
                 "coffee_maker", "toaster", "radio", "phone"}


def _is_sink(role: str) -> bool:
    return role != "sink_public" and role.startswith(("sink", "kitchen_sink"))
WORKTOP_ROOMS = ({"kitchen", "bathroom", "laundry", "breakroom", "openplan"}
                 | KITCHENS)
# Opened from the front: the tile before them is kept clear.
FRONT_CLEAR_ROLES = {"fridge", "stove", "stove_alt", "washer", "dryer", "wardrobe",
                     "bookshelf", "dresser", "dresser_alt", "filing_cabinet"}
DOOR_CLEAR_DEPTH = 2


def _needs_front(role: str) -> bool:
    # A shop's coolers and drinks machines too: one moved off a window used to
    # land in a corner with a shelf across its door.
    return role in FRONT_CLEAR_ROLES or role.startswith(
        ("wardrobe", "dresser", "fridge", "shop_fridge", "shop_freezer", "vending"))


def _needs_surface(role: str) -> bool:
    return role in SURFACE_ROLES or _is_sink(role) or role.startswith("erika_plant")


# Sprite geometry, read off the tiles themselves. A small thing is drawn with
# its base part-way up its 256-pixel tile, and whatever it stands on has to
# reach that high or it hangs in the air: a lamp's base is 153 pixels down and
# a pot plant's 151, a bedside chest's top edge is at 97 and a counter's at
# 125, but a coffee table's is at 172. A lamp on a coffee table floated a
# quarter of a tile above it. Knox County stands 180 of its 270 table lamps on
# furniture_storage_01, a bedside chest, and not one of them on a low table.
LOW_TABLES = {"table", "sidetable", "coffee_table",
              "low_table_tan", "low_table_black", "low_table_white"}
# What goes under one instead. Both of these are tiles the game itself puts
# lamps on (furniture_storage_01 8 and 12).
NIGHTSTANDS = ("dresser", "dresser_alt")


def _stand_on_something(plan: Plan, idx: int, room: Room, palette: dict) -> None:
    """A counter, a chest or a table under every piece of this room that needs
    one and does not have one - and a taller one under anything left standing
    on a piece too low to reach it."""
    standing: set[tuple[int, int]] = set()
    low: dict[tuple[int, int], int] = {}
    mine = []
    for n, (role, x, y, o) in enumerate(plan.furniture):
        if _room_at(plan, x, y) != idx or _is_wall_piece(role):
            continue
        mine.append(n)
        if _needs_surface(role):
            continue
        cells = _cells_for(role, x, y, o)
        if role in LOW_TABLES:
            for cell in cells:
                low[cell] = n
        else:
            standing.update(cells)
    added, swapped = [], []
    for n in mine:
        role, x, y, o = plan.furniture[n]
        if not _needs_surface(role) or (x, y) in standing:
            continue
        if room.kind in WORKTOP_ROOMS or _is_sink(role) or role == "register":
            support = palette.get("counter", "counter")
        elif role == "tv":
            support = "dresser"
        else:
            support = ("filing_cabinet"
                       if plan.kind in CIVIC_KINDS
                       and "filing_cabinet" in C.FURNITURE
                       else NIGHTSTANDS[(x + y) % len(NIGHTSTANDS)])
        if support not in C.FURNITURE:
            continue
        # A lamp already sitting on a coffee table: the table goes, the chest
        # takes its place, rather than two pieces on the one tile.
        under = low.pop((x, y), None)
        if under is not None:
            swapped.append((under, (support, x, y, _facing(support, o))))
        else:
            added.append((n, (support, x, y, _facing(support, o))))
        standing.add((x, y))
    for n, piece in swapped:
        plan.furniture[n] = piece
    # Each support goes in just before its piece, so it is drawn underneath.
    for n, piece in sorted(added, reverse=True):
        plan.furniture.insert(n, piece)


# Counter and cupboard are the same tileset (fixtures_counters_01: the wall
# cupboards are 24-27), so Knox County's kitchens are counted together: 3.9
# pieces over a median 21 m2, which is the rate below. Filling both long walls
# end to end instead put 7.1 in ours - a galley of worktop with a gangway down
# the middle. The figure this was first tuned against, 12 per 10 m2, was every
# piece of furniture in the room, not the counters.
COUNTER_PER_M2 = 0.186
# Counters come first out of that budget and cupboards take what is left, so a
# small kitchen is worktop rather than cupboard doors.
CABINET_SHARE = 0.4
# Knox County cooks on 1.2 appliances and the stove is one of them, so a
# microwave is the exception rather than the rule.
MICROWAVE_SHARE = 0.2
# How often a house keeps its washing machine in the kitchen rather than a
# laundry, a bathroom or the garage. Knox County: 16% of kitchens.
LAUNDRY_IN_KITCHEN = 0.16

# What a room kind's floor may be, in the shares Knox County lays them. Each
# building draws once per kind, so a town has variety between houses while one
# house stays coherent. Measured over 86,045 interior tiles: a bedroom is
# tilesandwood_01_42 a third of the time and carpet the rest, a bathroom is
# almost always hard tile, a hall has its own runner.
FLOOR_CHOICES = {
    "bedroom":     ["wood_pale", "carpet_brown", "carpet_grey",
                    "carpet_green", "carpet_beige"],
    "kidsbedroom": ["carpet_grey", "carpet_brown", "carpet_green",
                    "wood_pale", "carpet_red"],
    "livingroom":  ["wood_pale", "wood_pale", "carpet_brown", "wood_mid",
                    "carpet_grey"],
    "openplan":    ["wood_pale", "wood_mid", "carpet_brown", "wood_dark"],
    "dining":      ["wood_pale", "wood_pale", "wood_mid", "carpet_grey"],
    "diningroom":  ["wood_pale", "wood_pale", "wood_mid", "carpet_grey"],
    "kitchen":     ["wood_pale", "wood_mid", "tile_small", "tile_grey"],
    "bathroom":    ["tile_white", "tile_white", "tile_grey", "tile_cream",
                    "wood_mid"],
    # No hall_runner (tilesandwood_01_28). It was picked because it is 44% of
    # the hall *tiles* in Knox County - but that is a handful of big halls,
    # and by room it is 2 of 33. The halls the game actually builds are
    # tilesandwood 42, 45, 44 and 17, which are plain; _28 has a line through
    # it that tiles into a grid across a floor.
    "hall":        ["wood_pale", "wood_mid", "office_grey", "civic_pale"],
    "closet":      ["wood_pale", "wood_pale", "wood_pale", "wood_dark"],
    "office":      ["wood_mid", "carpet_red", "carpet_brown", "carpet_grey"],
}

# Floors for the rooms of a particular kind of building, where they differ
# from the house ones above. A station's hall is not somebody's hallway, and
# the runner measured over houses looked like carpet down the middle of a
# police station. Knox County floors its stations hard throughout - its cells
# are one tile and nothing else - and the offices it does carpet are left
# uncarpeted here on purpose.
KIND_FLOOR_CHOICES = {
    "garage": {
        "garage": ["concrete"],
        "mechanic": ["concrete"],
    },
    "school": {
        "classroom":    ["wood_pale", "school_pale", "school_warm"],
        "secondaryclassroom": ["wood_pale", "school_pale"],
        "schoollab":    ["wood_pale", "school_pale"],
        "gym":          ["wood_pale"],
        "library":      ["school_wood", "wood_pale"],
        "lobby":        ["school_pale", "school_warm", "wood_mid",
                         "school_wood"],
        "hall":         ["school_pale", "wood_pale", "school_warm"],
        "diningroom":   ["wood_pale", "school_pale"],
        "schoolstorage": ["school_warm", "wood_pale"],
        "sportstorage": ["school_warm", "wood_pale"],
        "office":       ["school_wood", "wood_mid"],
        "janitor":      ["civic_scuff", "school_warm"],
        "bathroom":     ["tile_white", "tile_cream", "civic_pale"],
    },
    "police": {
        "hall":              ["civic_hall", "civic_pale", "civic_grey"],
        "prisoncells":       ["civic_hall"],
        "policeoffice":      ["civic_pale", "civic_grey", "civic_hall"],
        "policehall":        ["civic_hall", "civic_pale"],
        "policelocker":      ["civic_pale", "civic_scuff"],
        "policegunstorage":  ["civic_pale", "civic_grey", "civic_scuff"],
        "policeoutfitstorage": ["civic_pale", "civic_scuff"],
        "policearchive":     ["civic_pale", "civic_grey"],
        "officestorage":     ["civic_pale", "civic_scuff"],
        "interrogationroom": ["civic_pale", "civic_grey"],
        "security":          ["civic_pale", "civic_grey"],
        "breakroom":         ["civic_pale", "civic_worn"],
        "janitor":           ["civic_scuff", "civic_worn"],
        "bathroom":          ["civic_pale", "civic_worn"],
        "office":            ["civic_pale", "civic_grey"],
        "storage":           ["civic_scuff", "civic_pale"],
    },
    "fire": {
        "firegarage":        ["concrete"],
        "firestorage":       ["civic_scuff", "concrete"],
        "hall":              ["civic_hall", "civic_pale", "civic_grey"],
        "lobby":             ["civic_hall", "civic_pale", "civic_grey"],
        "office":            ["civic_pale", "civic_grey"],
        "kitchen":           ["civic_pale", "civic_worn"],
        "bathroom":          ["tile_white", "civic_pale"],
        "bedroom":           ["civic_pale", "civic_grey"],
        "storage":           ["civic_scuff", "civic_pale"],
    },
    "fire_police": {
        "firegarage":        ["concrete"],
        "firestorage":       ["civic_scuff", "concrete"],
        "hall":              ["civic_hall", "civic_pale", "civic_grey"],
        "lobby":             ["civic_hall", "civic_pale", "civic_grey"],
        "prisoncells":       ["civic_hall"],
        "policeoffice":      ["civic_pale", "civic_grey", "civic_hall"],
        "policehall":        ["civic_hall", "civic_pale"],
        "policelocker":      ["civic_pale", "civic_scuff"],
        "policegunstorage":  ["civic_pale", "civic_grey", "civic_scuff"],
        "policeoutfitstorage": ["civic_pale", "civic_scuff"],
        "policearchive":     ["civic_pale", "civic_grey"],
        "officestorage":     ["civic_pale", "civic_scuff"],
        "interrogationroom": ["civic_pale", "civic_grey"],
        "security":          ["civic_pale", "civic_grey"],
        "breakroom":         ["civic_pale", "civic_worn"],
        "janitor":           ["civic_scuff", "civic_worn"],
        "bathroom":          ["tile_white", "civic_pale"],
        "office":            ["civic_pale", "civic_grey"],
        "bedroom":           ["civic_pale", "civic_grey"],
        "kitchen":           ["civic_pale", "civic_worn"],
        "storage":           ["civic_scuff", "civic_pale"],
    },
}
# The most counters a wishlist may ask for however big the room; past this the
# budget above decides.
WISHLIST_COUNTERS = 2
# Boxes against a wall: at most one wall slot in this many, never two side by
# side, and this share of them with another box on top.
CRATE_ONE_IN = 6
CRATE_STACKED = 0.5


def _counter_runs(plan: Plan, idx: int, slots, occupied: set,
                  door_tiles: set, stair_tiles: set, counter: str = "counter",
                  cabinets: bool = True, area: int = 0,
                  rng: random.Random | None = None, keeps_open=None) -> None:
    """Fitted counters along a kitchen's two longest walls, up to what the
    floor is worth.

    Knox County sets the sink and stove into a run of worktop rather than
    standing them against bare wall, so the gaps along the two longest walls
    fill with counters - but only as far as COUNTER_PER_M2, and never in front
    of a door. Whatever the wishlist placed stays and counts against the same
    budget.
    """
    rng = rng or random.Random(idx)
    # One budget for the whole tileset, counters and cupboards together, since
    # that is how the 3.9 was counted. Spending it on counters first and then
    # hanging cupboards on top of it is what left ours at 6.6.
    budget = max(3, round(area * COUNTER_PER_M2)) if area else 99
    # A commercial kitchen asks for no cupboards and for the worktop to run
    # wall to wall (area=0). Taking the cupboard share out of that budget all
    # the same left it at 99 - 99 = 0, so no run was ever drawn: a restaurant
    # kitchen had the one counter off its wishlist and bare wall beside it.
    if not cabinets:
        room_cabinets = 0
    elif area:
        room_cabinets = max(1, round(budget * CABINET_SHARE))
    else:
        room_cabinets = 99
    already = sum(1 for role, x, y, _o in plan.furniture
                  if role.startswith("counter") and _room_at(plan, x, y) == idx)
    left = max(0, budget - room_cabinets - already)
    placed = []
    by_wall: dict[str, list[tuple[int, int, str]]] = {}
    for x, y, facing in slots:
        by_wall.setdefault(facing, []).append((x, y, facing))
    for facing in sorted(by_wall, key=lambda f: -len(by_wall[f]))[:2]:
        for x, y, _f in by_wall[facing]:
            if len(placed) >= left:
                break
            orient = _facing(counter, facing)
            ax, ay = _wall_anchor(counter, x, y, orient, facing)
            cells = _cells_for(counter, ax, ay, orient)
            if any(c in occupied or c in door_tiles or c in stair_tiles for c in cells):
                continue
            if any(_room_at(plan, cx, cy) != idx for cx, cy in cells):
                continue
            if keeps_open and not keeps_open(cells):
                continue
            # A corner tile is on two walls; one counter is enough.
            occupied.update(cells)
            plan.furniture.append((counter, ax, ay, orient))
            placed.append((ax, ay, orient))

    # Cupboards on the wall above the counters, and sometimes a microwave on
    # one. North and west walls only, as for everything fixed to a wall; the
    # windows then keep off those tiles.
    if not cabinets:
        return
    hung = 0
    microwave = rng.random() >= MICROWAVE_SHARE      # True means: already done
    for role, x, y, orient in list(plan.furniture):
        if hung >= room_cabinets:
            break
        if role != counter or orient not in ("N", "W") or _room_at(plan, x, y) != idx:
            continue
        edge = _wall_edge(x, y, orient)
        if edge in plan.wall_pieces or _room_at(plan, *((x, y - 1) if orient == "N" else (x - 1, y))) == idx:
            continue
        plan.furniture.append(("wall_cabinet", x, y, _facing("wall_cabinet", orient)))
        plan.wall_pieces.add(edge)
        hung += 1
        if not microwave:
            plan.furniture.append(("microwave", x, y, _facing("microwave", orient)))
            microwave = True


@dataclass
class Building:
    """One or more storeys stacked into a single .tbx.

    A .tbx holds a list of <floor> elements and one building-wide room list; a
    floor's grid indexes into that shared list. So each storey is laid out as
    its own plan and the room lists are concatenated, with every storey's grid
    shifted by the rooms that came before it.
    """
    width: int
    height: int
    storeys: list[Plan] = field(default_factory=list)
    # Per storey below the top: where its staircase rises from.
    stairs: list[tuple[int, int, str]] = field(default_factory=list)
    # Where a mall's escalators stand, in this building's own tiles: the top
    # of the run, the end that lands on the upper floor. They are packed as
    # their own lot (knoxbuild/structures.pack_loose), not written into this
    # .tbx, because a square of one carries two tiles.
    escalators: list[tuple[int, int]] = field(default_factory=list)
    profile: object | None = None
    # A large house (Plan.grand): its rooms take a mansion's finishes.
    grand: bool = False

    @property
    def rooms(self) -> list[Room]:
        return [r for s in self.storeys for r in s.rooms]

    def grid_for(self, level: int) -> list[list[int]]:
        """That storey's grid, renumbered into the shared room list."""
        offset = sum(len(s.rooms) for s in self.storeys[:level])
        grid = self.storeys[level].grid
        return [[v + offset if v else 0 for v in row] for row in grid]
MANY = 1 << 30     # further than any search goes
# How many places a door stuck on a corner may be offered before it stays put.
DOOR_SPOTS_TRIED = 40
CORE_WIDE = 3      # the shaft is the flight plus a landing beside it


CORRIDOR_WIDE = 3   # a landing wide enough to be circulation, not a cupboard
# How wide a corridor is, in the shares Knox County builds them: of its 259
# school corridor rectangles the narrow side is 3 in 101, 4 in 45, 2 in 43
# and 6 in 23. Ours was always exactly 3, which is the commonest but the
# only one we ever built.
CORRIDOR_WIDTHS = (2, 3, 3, 3, 4, 4, 6)
# Every other building with a corridor keeps to what a corridor is. A clinic or
# a station with one six tiles wide was a third hall.
NARROW_CORRIDOR_WIDTHS = (2, 3, 3, 3, 4)


def _pick_corridor(width: int, height: int, mask: list[list[bool]] | None,
                   rng: random.Random, widths=CORRIDOR_WIDTHS
                   ) -> tuple[int, int, int, int] | None:
    """A corridor through the floor, with room for the stairs inside it.

    Flats need something to open onto, and it has to reach all of them: a
    compact shaft in the middle leaves the flats in the corners touching
    nothing. A strip along the building's length touches the flats either side
    of it by construction.

    The strip used to have to span the bounding box end to end. Placed on its
    real footprint, a block of flats turned 30 degrees has triangles of empty
    box at every corner, so no such strip ever fitted and the block fell back
    to one flat per floor. Now the longest strip that lies wholly inside the
    footprint is taken, as long as it runs most of the building's length;
    flats beyond its ends are folded into neighbours that do reach it.
    """
    along_y = height >= width
    span = height if along_y else width
    across = width if along_y else height
    # This building's corridor width, narrowing if the floor is too thin
    # for the one drawn.
    wide = rng.choice(widths)
    while wide > CORRIDOR_WIDE and across < wide + 2 * MIN_ROOM:
        wide -= 1
    if span < STAIR_RUN + 2 or across < wide + 2 * MIN_ROOM:
        return None

    def inside(a: int, b: int) -> bool:
        x, y = (b, a) if along_y else (a, b)
        return mask is None or mask[y][x]

    # How far the building actually extends along its length.
    extent = [a for a in range(span) if any(inside(a, b) for b in range(across))]
    if not extent:
        return None
    needed = max(STAIR_RUN + 2, int(0.6 * (extent[-1] - extent[0] + 1)))

    best = None
    for start in range(MIN_ROOM, across - wide - MIN_ROOM + 1):
        run_start = None
        for a in range(span + 1):
            ok = a < span and all(inside(a, b) for b in range(start, start + wide))
            if ok and run_start is None:
                run_start = a
            if not ok and run_start is not None:
                length = a - run_start
                if length >= needed:
                    centre = abs((start + wide / 2) - across / 2)
                    score = (-length, centre)
                    if best is None or score < best[0]:
                        if along_y:
                            rect = (start, run_start, start + wide - 1, a - 1)
                        else:
                            rect = (run_start, start, a - 1, start + wide - 1)
                        best = (score, rect)
                run_start = None
    return best[1] if best else None


def _pick_core(width: int, height: int, mask: list[list[bool]] | None,
               rng: random.Random, street: str | None = None, min_gap: int = 1
               ) -> tuple[int, int, int, int] | None:
    """Reserve a stair shaft: the same rectangle on every storey.

    Returned as (x0, y0, x1, y1) inclusive, oriented either way round, and
    always wholly inside the footprint - a shaft half outside an L-shaped
    building would put the flight in the garden.

    With the street known the stairs go at the back against a side wall,
    where a shop or a restaurant keeps its stairs; in the middle of the floor,
    a terrace of narrow shops had a flight of stairs in the middle of every one.

    The floor left on each side of the shaft is none or at least `min_gap`
    tiles: a house five tiles wide had its stairs down the middle and every
    room a one-tile strip round them, with nowhere to put a single piece.
    """
    shapes = [(CORE_WIDE, STAIR_RUN + 1), (STAIR_RUN + 1, CORE_WIDE)]
    best: list[tuple[int, int, int, int]] = []
    best_score = None
    for cw, ch in shapes:
        if cw > width or ch > height:
            continue
        for y0 in range(height - ch + 1):
            for x0 in range(width - cw + 1):
                if mask is not None and not all(
                        mask[y][x]
                        for y in range(y0, y0 + ch)
                        for x in range(x0, x0 + cw)):
                    continue
                if any(0 < g < min_gap for g in (x0, width - (x0 + cw),
                                                 y0, height - (y0 + ch))):
                    continue
                # Central, so the flight is not jammed against the windows.
                score = (abs((x0 + cw / 2) - width / 2)
                         + abs((y0 + ch / 2) - height / 2))
                if street in STEP_OF:
                    # Back and side: distance from the wall opposite the
                    # street, then from the nearer side wall.
                    back = {"S": y0, "N": height - (y0 + ch), "E": x0,
                            "W": width - (x0 + cw)}[street]
                    side = min(x0, width - (x0 + cw)) if street in ("N", "S") \
                        else min(y0, height - (y0 + ch))
                    score = back * 2 + side
                if best_score is None or score < best_score - 1e-9:
                    best_score, best = score, [(x0, y0, x0 + cw - 1,
                                                y0 + ch - 1)]
                elif abs(score - best_score) < 1e-9:
                    best.append((x0, y0, x0 + cw - 1, y0 + ch - 1))
    return rng.choice(best) if best else None


STEP_OF = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}


# Buildings this tall get a lift. Four flights is a fair climb; a thirty-storey
# tower on stairs alone is not something anyone built.
ELEVATOR_FROM_LEVELS = 5
# ...if it is more than a townhouse: a lift in a building five tiles wide
# took half its ground floor.
ELEVATOR_MIN_SIDE = 10
# A mall has a lift from its first floor up: it stands in the centre court
# beside the stairs and the escalators.
MALL_LIFT_FROM_LEVELS = 2
SHAFT_SIZE = 2


def _pick_shaft(core: tuple[int, int, int, int], width: int, height: int,
                mask: list[list[bool]] | None, stairs: tuple[int, int, str] | None
                ) -> tuple[tuple[int, int, int, int], tuple[int, int, str]] | None:
    """A 2x2 elevator shaft beside the stair hall, and the wall its doors go in.

    The Elevators mod finds a lift by its door tiles - vanilla
    fixtures_escalators_01_48-51 - repeated at the same square on every floor
    it serves, with a small sealed box behind them. So the shaft is fixed once
    for the whole building, like the stairs, and sits against the long side of
    the stair hall so its doors open onto the landing on every storey.
    """
    cx0, cy0, cx1, cy1 = core
    s = SHAFT_SIZE
    stair_cells = set()
    if stairs is not None:
        sx, sy, d = stairs
        stair_cells = {(sx, sy + i) if d == "N" else (sx + i, sy) for i in range(STAIR_RUN)}

    def inside(x0, y0):
        if x0 < 0 or y0 < 0 or x0 + s > width or y0 + s > height:
            return False
        return mask is None or all(mask[y][x] for y in range(y0, y0 + s)
                                   for x in range(x0, x0 + s))

    options = []
    if (cy1 - cy0) >= (cx1 - cx0):
        # Hall runs north-south: shafts to its west or east, doors in a W wall.
        mid = (cy0 + cy1) / 2
        for y0 in range(cy0, cy1 - s + 2):
            for x0, door_x, side_col in ((cx0 - s, cx0, cx0), (cx1 + 1, cx1 + 1, cx1)):
                if not inside(x0, y0):
                    continue
                if any((side_col, y0 + i) in stair_cells for i in range(s)):
                    continue
                options.append((abs(y0 + s / 2 - 1 - mid), (x0, y0, x0 + s - 1, y0 + s - 1),
                                (door_x, y0, "W")))
    else:
        mid = (cx0 + cx1) / 2
        for x0 in range(cx0, cx1 - s + 2):
            for y0, door_y, side_row in ((cy0 - s, cy0, cy0), (cy1 + 1, cy1 + 1, cy1)):
                if not inside(x0, y0):
                    continue
                if any((x0 + i, side_row) in stair_cells for i in range(s)):
                    continue
                options.append((abs(x0 + s / 2 - 1 - mid), (x0, y0, x0 + s - 1, y0 + s - 1),
                                (x0, door_y, "N")))
    if not options:
        return None
    options.sort(key=lambda o: (o[0], o[1]))
    return options[0][1], options[0][2]


def _cut_off_by_the_shaft(plan: Plan) -> None:
    """Take out any part of the storey the shaft has just walled off.

    Nothing opens into a lift shaft - it is a sealed box - so where the shaft
    lands in the neck of an L or a T it is a wall across it, and the rooms up
    the arm are rooms with no door anywhere: their only neighbour is the
    shaft. One fire station in a few thousand came out with four of them.
    Those tiles are better off not being part of the storey at all, which is
    what the arm is from the outside: roof.
    """
    sealed = {i for i, r in enumerate(plan.rooms, 1) if r.is_shaft}
    if not sealed:
        return
    touching: dict[int, set[int]] = {}
    for (a, b) in _boundary_edges(plan):
        if a in sealed or b in sealed:
            continue
        touching.setdefault(a, set()).add(b)
        touching.setdefault(b, set()).add(a)
    rooms = [i for i in range(1, len(plan.rooms) + 1) if i not in sealed]
    if not rooms:
        return
    # Out from the biggest room, which is the body of the building.
    start = max(rooms, key=lambda i: plan.rooms[i - 1].area)
    seen, stack = {start}, [start]
    while stack:
        for nxt in touching.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    gone = [i for i in rooms if i not in seen]
    if not gone:
        return
    for y in range(plan.height):
        for x in range(plan.width):
            if plan.grid[y][x] in gone:
                plan.grid[y][x] = 0
    _renumber(plan)
    _refit(plan)


def _carve_shaft(plan: Plan, shaft: tuple[int, int, int, int],
                 door: tuple[int, int, str]) -> None:
    """Paint the elevator shaft over the storey as a sealed room of its own."""
    x0, y0, x1, y1 = shaft
    plan.rooms.append(Room(x0, y0, x1, y1, kind="elevator", unit=0, is_shaft=True))
    idx = len(plan.rooms)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            plan.grid[y][x] = idx
    if plan.shaft is None:
        plan.shaft = shaft
        plan.shaft_door = door
    plan.shafts.append((shaft, door))
    _renumber(plan)
    _mend_fragments(plan)
    _refit(plan)


def _stairs_in_core(core: tuple[int, int, int, int]
                    ) -> tuple[int, int, str]:
    """The flight inside a shaft. Runs along the shaft's long axis.

    Set one tile in from the end so the corridor is still walkable past it.
    """
    x0, y0, x1, y1 = core
    if (y1 - y0) >= (x1 - x0):
        start = min(y0 + 1, y1 - (STAIR_RUN - 1))
        return x0 + (x1 - x0) // 2, max(y0, start), "N"
    start = min(x0 + 1, x1 - (STAIR_RUN - 1))
    return max(x0, start), y0 + (y1 - y0) // 2, "W"


def _clear_for_stairs(plan: Plan, x: int, y: int, d: str) -> None:
    """Drop furniture standing where the staircase goes."""
    dx, dy = (0, 1) if d == "N" else (1, 0)
    blocked = {(x + dx * i, y + dy * i) for i in range(STAIR_RUN)}
    plan.furniture = [
        f for f in plan.furniture
        if _is_wall_piece(f[0])
        or not (set(_cells_for(f[0], f[1], f[2], f[3])) & blocked)
    ]


def _blocks(role: str) -> bool:
    """Whether a piece stands on the floor and stops you walking through."""
    return C.FURNITURE_LAYERS.get(role, "Furniture") == "Furniture"


def _tiles_under(role: str, x: int, y: int, orient: str):
    """Every tile a piece covers, from the offsets in its catalog entry: a
    double bed is four of them and a sofa two, not one each."""
    spots = C.FURNITURE.get(role, {}).get(orient) or {"0,0": None}
    for key in spots:
        dx, _, dy = key.partition(",")
        yield x + int(dx), y + int(dy)


def _ways_in(building: "Building", level: int, storey: "Plan") -> set:
    """The tiles a player arrives on: the outside doors on the ground floor,
    the stairs on every floor above."""
    w, h = storey.width, storey.height

    def room(x, y):
        return storey.grid[y][x] if 0 <= x < w and 0 <= y < h else 0

    out = set()
    if level == 0:
        for (x, y, d) in storey.doors:
            a = (x - 1, y) if d == "W" else (x, y - 1)
            if room(*a) and not room(x, y):
                out.add(a)
            elif room(x, y) and not room(*a):
                out.add((x, y))
    for lvl, (sx, sy, sd) in enumerate(building.stairs):
        if lvl not in (level - 1, level):
            continue
        dx, dy = (0, 1) if sd == "N" else (1, 0)
        out |= {(sx + dx * i, sy + dy * i) for i in range(STAIR_RUN)
                if room(sx + dx * i, sy + dy * i)}
    return out


# Bare floor you cannot step onto that is allowed to stay shut off: a corner
# behind a bed or at the end of a bath, rather than a part of the room.
POCKET_TILES = 2
# What may stand on the square at a window. The pass below clears that square
# so the window can be opened, climbed through and seen out of, which is right
# for a bookcase or a wardrobe and wrong for these: a bath under the bathroom
# window and a bed under the bedroom one are what Knox County does, and taking
# them out cost 78 baths and 247 beds in 200 houses.
def _under_a_window(role: str) -> bool:
    # Low chests too - the dressers and bedside drawers are all IsLow in the
    # game, the same as a table - and the lamp that stands on one. Moved off
    # their window squares in full bedrooms and living rooms, they had nowhere
    # to go and were the pieces the clear-up threw out most.
    return (role in {"bath", "bath_mat", "sofa", "table", "coffee_table",
                     "sidetable", "desk", "bench", "nightstand", "lamp",
                     "radio", "coffee_maker", "toaster", "bin", "phone", "box",
                     "box_battered", "hamper", "sale_sign"}
            or role.startswith(("bed", "double_bed", "sofa_", "counter", "dresser",
                                "low_table_", "sink", "kitchen_sink")))


# A cost (essentials, secondary, decoration) packed into one int that sorts
# the same way: a tuple sum per step was a third of _open_up's time.
RANK_COST = (1 << 40, 1 << 20, 1)
ZERO = 0
NONE = 1 << 62


def _open_up(storey: "Plan", starts: set) -> set:
    """Which pieces have to go for every room to be walked into."""
    w, h, grid = storey.width, storey.height, storey.grid
    doors = set(storey.doors)
    at: dict = {}
    # What standing on a tile costs: the pieces that would have to go, counted
    # (essentials, secondary, decoration) by the room each one stands in, so
    # the search below gives up any number of plants before one toilet.
    weight: dict = {}
    for i, (role, fx, fy, orient) in enumerate(storey.furniture):
        if not _blocks(role):
            continue
        idx = grid[fy][fx] if 0 <= fx < w and 0 <= fy < h else 0
        rank = FR.priority(role, storey.rooms[idx - 1].kind if idx else "")
        for tile in _tiles_under(role, fx, fy, orient):
            at.setdefault(tile, set()).add(i)
            weight[tile] = weight.get(tile, ZERO) + RANK_COST[rank]

    def step(ax, ay, bx, by) -> bool:
        """Whether you can walk from one tile to the next: same room, or a
        doorway in the wall between them."""
        if not (0 <= bx < w and 0 <= by < h) or not grid[by][bx]:
            return False
        if grid[ay][ax] == grid[by][bx]:
            return True
        if bx == ax + 1:
            return (bx, by, "W") in doors
        if ax == bx + 1:
            return (ax, ay, "W") in doors
        if by == ay + 1:
            return (bx, by, "N") in doors
        return (ax, ay, "N") in doors

    # A search out from the way in: stepping onto an empty tile is free,
    # stepping onto an occupied one costs the pieces standing there. What
    # comes back is the fewest essentials, then secondary pieces, then
    # decoration that have to move for each room to open.
    best: dict = {}
    back: dict = {}
    heap: list = []
    for tile in sorted(starts):
        cost = weight.get(tile, ZERO)
        if cost < best.get(tile, NONE):
            best[tile], back[tile] = cost, None
            heapq.heappush(heap, (cost, tile))
    while heap:
        here, (x, y) = heapq.heappop(heap)
        if here != best[(x, y)]:
            continue
        for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not step(x, y, *nxt):
                continue
            cost = here + weight.get(nxt, ZERO)
            if cost < best.get(nxt, NONE):
                best[nxt], back[nxt] = cost, (x, y)
                heapq.heappush(heap, (cost, nxt))

    walked = {grid[y][x] for (x, y), cost in best.items() if cost == ZERO}
    want: dict = {}
    for (x, y), cost in best.items():
        idx = grid[y][x]
        if not idx or idx in walked or storey.rooms[idx - 1].is_shaft:
            continue
        if cost < want.get(idx, (NONE, None))[0]:
            want[idx] = (cost, (x, y))
    goals = [tile for _cost, tile in want.values()]

    # A room is not walkable just because one corner of it can be reached: the
    # floor you are left standing on should hang together, and both sides of a
    # door and the square at a window have to be reachable or they cannot be
    # used. A tile or two you cannot step onto, though - behind the bed, beside
    # the bath - is how a furnished room works, and insisting on every bare
    # square took out 78 baths and 247 beds in 200 houses, three times what
    # this pass used to clear. Only a pocket bigger than that is opened up.
    for x, y, facing in doors | set(storey.windows):
        sides = ((x - 1, y), (x, y)) if facing == "W" else ((x, y - 1), (x, y))
        for tx, ty in sides:
            if not (0 <= tx < w and 0 <= ty < h) or not grid[ty][tx]:
                continue
            if best.get((tx, ty), NONE) == ZERO:
                continue
            if (x, y, facing) not in doors and all(
                    _under_a_window(storey.furniture[n][0])
                    for n in at.get((tx, ty), ())):
                continue
            goals.append((tx, ty))
    shut = {(x, y) for y in range(h) for x in range(w)
            if grid[y][x] and (x, y) not in at and best.get((x, y), NONE) > ZERO}
    seen: set = set()
    for tile in shut:
        if tile in seen:
            continue
        seen.add(tile)
        pocket, edge = [], deque([tile])
        while edge:
            cx, cy = edge.popleft()
            pocket.append((cx, cy))
            for nxt in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if nxt in shut and nxt not in seen and step(cx, cy, *nxt):
                    seen.add(nxt)
                    edge.append(nxt)
        if len(pocket) > POCKET_TILES:
            goals.append(min(pocket, key=lambda t: best.get(t, NONE)))

    gone: set = set()
    for tile in goals:
        while tile is not None:
            gone |= at.get(tile, set())
            tile = back.get(tile)
    return gone


_STEP = {"N": (0, -1), "W": (-1, 0), "S": (0, 1), "E": (1, 0)}


def _stay_reachable(cells: set, blocked: set, walk: set, squares: set) -> bool:
    """Whether each of `squares` can still be walked to from the walkway, over
    the room's bare floor. A room with no walkway has nothing to join."""
    start = [t for t in walk if t in cells and t not in blocked]
    if not start or not squares:
        return True
    seen, todo = set(start), list(start)
    while todo:
        x, y = todo.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n in cells and n not in blocked and n not in seen:
                seen.add(n)
                todo.append(n)
    return squares <= seen


def _make_way_for_windows(storey: "Plan", stairs: tuple[int, int, str] | None) -> int:
    """Stand whatever blocks a window square against another wall of its room.

    Windows go in after the rooms are furnished, so nobody knew where they
    would land, and the square inside one had to be cleared for the window to
    be opened, climbed through and seen out of. Deleting what stood there was
    nine in ten of everything the clear-up took out. A one-tile piece, and
    what stands on it, moves to the nearest free wall tile of the same room
    that keeps the floor in one piece; with no such tile it trades places with
    a one-tile piece of the same room that may stand at a window. Only what
    cannot move is left for _open_up. Returns the number of pieces moved.

    A door slid off a corner after furnishing (_doors_off_corners) can land
    with a piece in its clearance; that clearance is cleared the same way,
    with no exception for what may stand at a window."""
    w, h, grid = storey.width, storey.height, storey.grid
    squares = set()
    for x, y, d in storey.windows:
        for tx, ty in (((x - 1, y), (x, y)) if d == "W" else ((x, y - 1), (x, y))):
            if 0 <= tx < w and 0 <= ty < h and grid[ty][tx]:
                squares.add((tx, ty))
    door_tiles = _door_tiles(storey)
    at_door = {(x, y) for x, y in door_tiles if 0 <= x < w and 0 <= y < h and grid[y][x]}
    if not squares and not at_door:
        return 0
    off = squares | door_tiles
    for x, y, facing in storey.stalls:
        off.add((x, y))
        off.add((x, y + 1) if facing == "N" else (x + 1, y))
    if stairs is not None:
        sx, sy, sd = stairs
        dx, dy = (0, 1) if sd == "N" else (1, 0)
        off |= {(sx + dx * i, sy + dy * i) for i in range(STAIR_RUN)}
    furniture = storey.furniture
    cells_of = [_cells_for(role, x, y, o) for role, x, y, o in furniture]
    on_floor: dict = {}
    for i, f in enumerate(furniture):
        if not _is_wall_piece(f[0]):
            for c in cells_of[i]:
                on_floor.setdefault(c, []).append(i)
    hung = {(f[1], f[2]) for f in furniture if f[0] in ("wall_cabinet", "microwave")}

    def fits(pieces, x, y, face) -> bool:
        """Whether each piece, turned to face that wall, still covers one tile:
        a side table is one tile one way and two the other."""
        return all(_cells_for(furniture[i][0], x, y, _facing(furniture[i][0], face))
                   == [(x, y)] for i in pieces)

    def put(pieces, x, y, face) -> None:
        for i in pieces:
            for c in cells_of[i]:
                on_floor[c].remove(i)
            role = furniture[i][0]
            furniture[i] = (role, x, y, _facing(role, face))
            cells_of[i] = [(x, y)]
            on_floor.setdefault((x, y), []).append(i)

    def wall_of(t, facings):
        return next((f for f in facings
                     if (t[0] + _STEP[f][0], t[1] + _STEP[f][1]) not in cells), None)

    def nearest(tiles):
        return sorted(tiles, key=lambda d: (abs(d[0] - t[0]) + abs(d[1] - t[1]), d[1], d[0]))

    rooms: dict = {}
    moved = 0
    for t in sorted(squares | at_door):
        stack = sorted(on_floor.get(t, ()))
        roles = [furniture[i][0] for i in stack]
        if (not any(_blocks(r) for r in roles)
                or (t not in at_door and all(_under_a_window(r) for r in roles))
                or any(len(cells_of[i]) > 1 for i in stack)
                or t in hung):
            continue
        idx = grid[t[1]][t[0]]
        if idx not in rooms:
            r = storey.rooms[idx - 1]
            cells = {(x, y) for y in range(r.y0, r.y1 + 1)
                     for x in range(r.x0, r.x1 + 1) if grid[y][x] == idx}
            rooms[idx] = cells, _room_walkway(storey, idx, door_tiles, stairs)
        cells, walk = rooms[idx]
        blocked = {c for i, f in enumerate(furniture) if _blocks(f[0])
                   for c in cells_of[i]} & cells
        blocked.discard(t)
        # The tile something is opened from stays floor.
        fronts = {(cx - _STEP[f[3]][0], cy - _STEP[f[3]][1])
                  for i, (f, cs) in enumerate(zip(furniture, cells_of))
                  if _needs_front(f[0]) and f[3] in _STEP and i not in stack
                  for cx, cy in cs}
        nw_only = any(r in NORTH_WEST_ONLY for r in roles)
        facings = ("N", "W") if nw_only else ("N", "W", "S", "E")
        front = any(_needs_front(r) for r in roles)

        def opened(d, face) -> bool:
            ahead = (d[0] - _STEP[face][0], d[1] - _STEP[face][1])
            return not front or (ahead in cells and ahead not in blocked)

        covered = {c for cs in cells_of for c in cs}
        floor = FR.OpenFloor(cells, walk, POCKET_TILES)
        floor.block(blocked)
        # Every window square of the room that is bare floor, this one once
        # it is cleared: each has to stay joined to the walkway.
        opens = (squares & cells) - blocked
        opens.add(t)
        for d in nearest(cells - off - walk - covered - fronts):
            face = wall_of(d, facings)
            if (face is None or not opened(d, face) or not fits(stack, *d, face)
                    or not floor.keeps_open({d})
                    or not _stay_reachable(cells, blocked | {d}, walk, opens - {d})):
                continue
            put(stack, *d, face)
            moved += len(stack)
            break
        else:
            # No free wall: trade places with a one-tile piece that may stand
            # at a window - a bare counter for the sink, a table for the
            # dresser. Both tiles stay taken, so the floor is as it was.
            if t in at_door:
                continue
            here = wall_of(t, "NWSE")
            # A wall cabinet keeps a counter under it.
            keep = off if any(r.startswith("counter") for r in roles) else off | hung
            for c in nearest(set(on_floor) & cells - keep):
                other = sorted(on_floor[c])
                if not any(_blocks(furniture[j][0]) for j in other) or any(
                        len(cells_of[j]) > 1 or not _under_a_window(furniture[j][0])
                        for j in other):
                    continue
                face = wall_of(c, facings)
                if (face is None or here is None or not opened(c, face)
                        or not fits(stack, *c, face) or not fits(other, *t, here)):
                    continue
                put(stack, *c, face)
                put(other, *t, here)
                moved += len(stack) + len(other)
                break
    return moved


def _doors_off_stairs(building: "Building") -> int:
    """Move a door that opens onto the steps of a flight to somewhere else on
    the same wall between the same two rooms.

    The steps between the two landings cannot be walked across, so a door
    hung on one - or on the wall beside one - leads nowhere, and the rooms
    behind it are cut off. Left where it is only when no other clean stretch
    of that boundary exists.
    """
    if not building.stairs:
        return 0
    x, y, d = building.stairs[0]
    dx, dy = (0, 1) if d == "N" else (1, 0)
    steps = {(x + dx * i, y + dy * i) for i in range(1, STAIR_RUN - 1)}

    def on_steps(door) -> bool:
        dxx, dyy, dd = door
        before = (dxx - 1, dyy) if dd == "W" else (dxx, dyy - 1)
        return (dxx, dyy) in steps or before in steps

    moved = 0
    for storey in building.storeys:
        bad = [i for i, door in enumerate(storey.doors) if on_steps(door)]
        if not bad:
            continue
        edges = {(ex, ey, ed) for _side, wall in _facade_runs(storey.grid)
                 for ex, ey, ed, _ix, _iy in wall} | _room_edges(storey.grid)
        corners = {(ex, ey) for ex, ey, ed in edges
                   if (ex, ey, "N" if ed == "W" else "W") in edges}
        keep_off = set(storey.party) | set(getattr(storey, "wall_pieces", ()))
        for i in bad:
            door = storey.doors[i]
            want = _sides_of(storey.grid, *door)
            taken = set(storey.doors)
            spots = [e for e in edges
                     if e not in taken and e not in keep_off
                     and (e[0], e[1]) not in corners and not on_steps(e)
                     and _sides_of(storey.grid, *e) == want]
            if spots:
                spots.sort(key=lambda e: (abs(e[0] - door[0]) + abs(e[1] - door[1]), e))
                storey.doors[i] = spots[0]
                moved += 1
            else:
                # Nowhere else on that wall. Where the rooms are reached
                # another way the door only has to go; where it was the one
                # way in, a door to some other neighbour takes its place.
                if not _joined_without(storey, i):
                    for e in sorted(edges, key=lambda e: (abs(e[0] - door[0]) + abs(e[1] - door[1]), e)):
                        pair = _sides_of(storey.grid, *e)
                        if (e in taken or e in keep_off or (e[0], e[1]) in corners
                                or on_steps(e) or 0 in pair or pair[0] == pair[1]
                                or not set(pair) & set(want) or set(pair) == set(want)
                                or any(storey.rooms[r - 1].is_shaft for r in pair)):
                            continue
                        ua, ub = (storey.rooms[r - 1].unit for r in pair)
                        if ua and ub and ua != ub:
                            continue
                        storey.doors.append(e)
                        if _joined_without(storey, i):
                            taken.add(e)
                            break
                        storey.doors.pop()
                if _joined_without(storey, i):
                    storey.doors[i] = None
                    moved += 1
        storey.doors = [d for d in storey.doors if d is not None]
    return moved


def _joined_without(storey, skip: int) -> bool:
    """Whether the two rooms either side of door `skip` still meet through the
    other doors and open edges, so that door can go without shutting one in."""
    adj: dict[int, set] = {}
    links = [d for j, d in enumerate(storey.doors) if j != skip and d is not None]
    for x, y, d in list(links) + list(getattr(storey, "open_edge", ())):
        a, b = _sides_of(storey.grid, x, y, d)
        if a and b and a != b:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    a, b = _sides_of(storey.grid, *storey.doors[skip])
    seen, stack = {a}, [a]
    while stack:
        for nxt in adj.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return b in seen


# The share of a room's floor its furniture may cover before the smallest
# pieces come out. A bedroom with bed, two chests, a desk and a shelf in 16
# tiles is a room you turn sideways in; Knox County's sit near a third.
CLUTTER_CAP = {"hall": 0.36, "bedroom": 0.5, "kidsbedroom": 0.5,
               "livingroom": 0.5, "bathroom": 0.62, "kitchen": 0.58,
               "dining": 0.5}


def _thin_clutter(building: "Building") -> int:
    """Take the decoration, then the secondary pieces, out of a room that is
    more furniture than floor. Essentials stay whatever the room."""
    removed = 0
    for storey in building.storeys:
        w, h, grid = storey.width, storey.height, storey.grid
        area: dict = {}
        for row in grid:
            for v in row:
                if v:
                    area[v] = area.get(v, 0) + 1
        by_room: dict = {}
        for i, (role, fx, fy, orient) in enumerate(storey.furniture):
            if not _blocks(role) or not (0 <= fx < w and 0 <= fy < h) or not grid[fy][fx]:
                continue
            by_room.setdefault(grid[fy][fx], []).append(
                (i, role, sum(1 for _ in _tiles_under(role, fx, fy, orient))))
        gone: set = set()
        for idx, pieces in by_room.items():
            room = storey.rooms[idx - 1]
            cap = CLUTTER_CAP.get(room.kind)
            if cap is None or room.is_core or area[idx] < MIN_ROOM * MIN_ROOM:
                continue
            fill = sum(t for _i, _r, t in pieces)
            order = sorted((p for p in pieces if FR.priority(p[1], room.kind) != FR.ESSENTIAL),
                           key=lambda p: (-FR.priority(p[1], room.kind), p[2], p[0]))
            for i, _role, tiles in order:
                if fill <= cap * area[idx]:
                    break
                gone.add(i)
                fill -= tiles
        if gone:
            # What stood on a piece goes with it: a lamp left over bare floor
            # hangs in the air, a cabinet over nothing is on a bare wall.
            cells = {c for i in gone
                     for c in _tiles_under(*storey.furniture[i])}
            for i, (role, fx, fy, _o) in enumerate(storey.furniture):
                if (fx, fy) in cells and (_needs_surface(role)
                                          or role in ("wall_cabinet", "microwave")):
                    gone.add(i)
            storey.furniture = [f for i, f in enumerate(storey.furniture) if i not in gone]
            removed += len(gone)
    return removed


def _narrow(grid, x: int, y: int) -> bool:
    """A room tile with its own room on neither side across one axis: a strip
    one tile wide, or a single square sticking out of the room."""
    idx = grid[y][x]
    h, w = len(grid), len(grid[0])

    def mine(nx, ny):
        return 0 <= nx < w and 0 <= ny < h and grid[ny][nx] == idx
    return (not mine(x - 1, y) and not mine(x + 1, y)) or \
        (not mine(x, y - 1) and not mine(x, y + 1))


def _off_narrow_spots(building: "Building") -> int:
    """Nothing stands on a tile of a room that is one tile wide.

    A kitchen with a one-tile tail had its counters and sink run down it, with
    the outside on one side and the hall wall on the other, and a bathroom's
    one-square nub took the toilet: nowhere to stand to use either, and the
    spot read as a mistake in the game (Piqua, 2026-10-31). What hangs on the
    walls stays; what stood on a piece that goes, goes with it."""
    removed = 0
    for storey in building.storeys:
        grid, w, h = storey.grid, storey.width, storey.height
        gone = {i for i, (role, fx, fy, orient) in enumerate(storey.furniture)
                if _blocks(role) and not role.startswith("elevator")
                and any(0 <= cx < w and 0 <= cy < h and grid[cy][cx]
                        and _narrow(grid, cx, cy)
                        for cx, cy in _tiles_under(role, fx, fy, orient))}
        if not gone:
            continue
        cells = {c for i in gone for c in _tiles_under(*storey.furniture[i])}
        gone |= {i for i, (role, fx, fy, _o) in enumerate(storey.furniture)
                 if (fx, fy) in cells and (_needs_surface(role)
                                           or role in ("wall_cabinet", "microwave"))}
        storey.furniture = [f for i, f in enumerate(storey.furniture) if i not in gone]
        removed += len(gone)
    return removed


DESK_ROLES = {"desk", "desk_dark", "desk_long", "desk_long_pale"}
_OPPOSITE = {"N": "S", "S": "N", "W": "E", "E": "W"}


def _seat_the_desks(building: "Building") -> int:
    """Put each desk's office chair at it, as if someone sat there.

    A desk too big for the middle of a room goes against a wall, and its chair
    was then placed on its own wherever a wall had room, two tiles off or
    across the office. A chair not already at a desk moves to a free tile on
    the desk's open side, facing it; no chair is added."""
    moved = 0
    # The flight and the tile at either end of it, on every floor it touches.
    stairs = set()
    for x, y, d in building.stairs:
        dx, dy = (0, 1) if d == "N" else (1, 0)
        stairs |= {(x + dx * i, y + dy * i) for i in range(-1, STAIR_RUN + 1)}
    for storey in building.storeys:
        grid, w, h = storey.grid, storey.width, storey.height
        furn = storey.furniture
        taken = {c for role, x, y, o in furn if _blocks(role)
                 for c in _tiles_under(role, x, y, o)}
        doors = _door_tiles(storey)
        # The squares either side of a window are kept clear to open it.
        doors |= {t for x, y, d in storey.windows
                  for t in ((x, y), (x, y - 1) if d == "N" else (x - 1, y))}

        def room(x, y):
            return grid[y][x] if 0 <= x < w and 0 <= y < h else 0

        def fronts(i):
            role, x, y, o = furn[i]
            sx, sy = _STEP[_OPPOSITE[o]]
            return [(cx + sx, cy + sy) for cx, cy in _tiles_under(role, x, y, o)]

        desks = [i for i, f in enumerate(furn) if f[0] in DESK_ROLES and f[3] in _STEP]
        seated = {c for i in desks for c in fronts(i)}
        chairs = [i for i, f in enumerate(furn) if f[0] == "office_chair"]
        for d in desks:
            if any((furn[c][1], furn[c][2]) in fronts(d) for c in chairs):
                continue
            here = room(furn[d][1], furn[d][2])
            loose = [c for c in chairs if (furn[c][1], furn[c][2]) not in seated
                     and room(furn[c][1], furn[c][2]) == here]
            spot = next((t for t in fronts(d) if room(*t) == here and t not in taken
                         and t not in doors and t not in stairs), None)
            if not loose or spot is None:
                continue
            c = min(loose, key=lambda c: abs(furn[c][1] - spot[0]) + abs(furn[c][2] - spot[1]))
            taken.discard((furn[c][1], furn[c][2]))
            furn[c] = ("office_chair", spot[0], spot[1], _OPPOSITE[furn[d][3]])
            taken.add(spot)
            seated.add(spot)
            moved += 1
    return moved


def _off_the_doorways(storey: Plan) -> int:
    """Nothing standing on the tiles a door keeps clear.

    Furnishing keeps off them, but a door can be moved or added afterwards -
    when the flight is in the way of the door first chosen - and it can land
    on a bed already in place: a bedroom whose only way in was a bed's foot.
    """
    clear = _door_tiles(storey)
    gone = {i for i, f in enumerate(storey.furniture)
            if _blocks(f[0])
            and set(_cells_for(f[0], f[1], f[2], f[3])).intersection(clear)}
    if gone:
        storey.furniture = [f for i, f in enumerate(storey.furniture)
                            if i not in gone]
    return len(gone)


def _clear_the_way(building: "Building") -> int:
    """Take out whatever stands between a doorway and the rooms behind it.

    Rooms are furnished one at a time, so nothing stopped a shelf landing in
    the only doorway or a counter spanning the only way through. The plan was
    connected - every audit of it passed - but the furnished building was not.
    """
    _doors_off_stairs(building)
    removed = sum(_off_the_doorways(storey) for storey in building.storeys)
    stairs = building.stairs[0] if building.stairs else None
    for level, storey in enumerate(building.storeys):
        _make_way_for_windows(storey, stairs)
        starts = _ways_in(building, level, storey)
        if not starts:
            continue
        for _round in range(6):
            gone = _open_up(storey, starts)
            if not gone:
                break
            # What hangs over a counter goes with it: a wall cabinet left over
            # bare floor was a cupboard on a wall with nothing beneath.
            under = {(f[1], f[2]) for i, f in enumerate(storey.furniture)
                     if i in gone and f[0].startswith("counter")}
            gone |= {i for i, f in enumerate(storey.furniture)
                     if f[0] in ("wall_cabinet", "microwave") and (f[1], f[2]) in under}
            storey.furniture = [f for i, f in enumerate(storey.furniture)
                                if i not in gone]
            removed += len(gone)
    # Last, after the windows have moved pieces off their squares: a piece stood
    # against another wall can land on a one-tile spot.
    removed += _off_narrow_spots(building)
    _thin_clutter(building)
    # Last, so nothing moves a chair away again; it only takes a free tile that
    # is not a doorway's or a window's, so the way through stays open.
    _seat_the_desks(building)
    return removed
