"""Turn a footprint rectangle into a furnished floor plan.

Wall model, which the rest of the package depends on: BuildingEd stores walls on
the north and west *edges* of tiles, which is why its per-floor tile grids are
(width+1) x (height+1). So for a building w tiles wide and h tall:

    north exterior wall   y = 0,  dir N,  x in 0..w-1
    west  exterior wall   x = 0,  dir W,  y in 0..h-1
    south exterior wall   y = h,  dir N
    east  exterior wall   x = w,  dir W

Interior walls appear automatically wherever two adjacent tiles hold different
room indices, so we only ever paint rooms - we never emit wall objects.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import catalog as C
from .settings import Settings

MIN_ROOM = 3          # smallest room dimension, in tiles
MIN_SPLIT = MIN_ROOM * 2 + 1
# Keep cutting while a region is bigger than roughly one generous room. This,
# rather than a fixed recursion depth, is what stops a 26x27 shop ending up as
# one cavernous 21x23 space.
TARGET_ROOM_AREA = 56
# Only a safety net against runaway recursion; TARGET_ROOM_AREA is what should
# decide when to stop. At 5 the cap bound first and left 18x18 living rooms in
# large buildings.
MAX_DEPTH = 8


@dataclass
class Room:
    x0: int
    y0: int
    x1: int   # inclusive
    y1: int   # inclusive
    kind: str = "hall"
    # Which dwelling this room belongs to. 0 is shared circulation - the
    # landing and corridor everyone uses. A flat's rooms open onto each other
    # and onto the corridor once, never into the flat next door.
    unit: int = 0
    # The stair shaft or corridor. Kept as a flag rather than recognised by its
    # rectangle, because a sliver folded into it changes the rectangle.
    is_core: bool = False
    # An elevator shaft: a sealed box with the lift doors set into one wall.
    # No doorway, no furniture, no windows, never merged into a neighbour.
    is_shaft: bool = False

    @property
    def w(self) -> int:
        return self.x1 - self.x0 + 1

    @property
    def h(self) -> int:
        return self.y1 - self.y0 + 1

    @property
    def area(self) -> int:
        return self.w * self.h


@dataclass
class Plan:
    width: int
    height: int
    rooms: list[Room] = field(default_factory=list)
    grid: list[list[int]] = field(default_factory=list)   # 1-based room index
    doors: list[tuple[int, int, str]] = field(default_factory=list)
    windows: list[tuple[int, int, str]] = field(default_factory=list)
    furniture: list[tuple[str, int, int, str]] = field(default_factory=list)
    # None = the building fills its rectangle; otherwise True where
    # the real footprint lies. Tiles outside it stay room 0, which is
    # how BuildingEd knows they are not part of the building.
    mask: list[list[bool]] | None = None
    # The stair shaft, as (x0, y0, x1, y1) inclusive, identical on every
    # storey of a building. Painted last so it is always exactly one room.
    core: tuple[int, int, int, int] | None = None
    # True when the core is a corridor flats open onto, not just a stair shaft.
    corridor: bool = False
    # The elevator shaft (x0, y0, x1, y1) inclusive, and where its doors hang:
    # (x, y, "W" or "N") for the two-square wall edge facing the stair hall.
    shaft: tuple[int, int, int, int] | None = None
    shaft_door: tuple[int, int, str] | None = None
    # Wall edges carrying a switch, painting or mirror; windows keep off them.
    wall_pieces: set = field(default_factory=set)


# kind -> (floor tile entry index, display name, furniture wishlist)
ROOM_STYLE = {
    "livingroom": (C.FLOOR_CARPET_RED, "Living Room",
                   ["sofa", "armchair", "tv", "sidetable", "bookshelf",
                    "painting", "plant", "shelf"]),
    "kitchen": (C.FLOOR_TILE_CHECK, "Kitchen",
                ["counter", "fridge", "stove", "sink", "counter", "shelf",
                 "table", "chair", "plant"]),
    "bedroom": (C.FLOOR_CARPET_BLUE, "Bedroom",
                ["bed", "wardrobe", "dresser", "sidetable",
                 "painting", "mirror", "bookshelf"]),
    "bathroom": (C.FLOOR_TILE_PALE, "Bathroom",
                 ["toilet", "bath", "sink", "mirror", "shelf"]),
    "dining": (C.FLOOR_WOOD, "Dining Room",
               ["table", "chair", "chair", "dresser",
                "painting", "plant", "shelf"]),
    "hall": (C.FLOOR_WOOD, "Hall",
             ["shelf", "painting", "plant", "mirror"]),
    "storage": (C.FLOOR_LINO, "Storage",
                ["shelf", "crate", "shelf", "crate", "bookshelf"]),
    "office": (C.FLOOR_WOOD, "Office",
               ["table", "chair", "bookshelf", "painting", "plant"]),
    # Rooms only special buildings use. Every name is in RoomNames.txt, so loot
    # tables recognise them.
    "classroom": (C.FLOOR_TILE_PALE, "Classroom",
                  ["table", "chair", "chair", "bookshelf", "painting", "shelf"]),
    "library": (C.FLOOR_WOOD, "Library",
                ["bookshelf", "bookshelf", "table", "chair"]),
    "gym": (C.FLOOR_WOOD, "Gym", ["shelf", "crate", "painting"]),
    "lobby": (C.FLOOR_TILE_CHECK, "Lobby",
              ["sofa", "armchair", "sidetable", "plant", "painting"]),
    "church": (C.FLOOR_WOOD, "Church",
               ["chair", "chair", "table", "painting", "plant"]),
    "restaurant": (C.FLOOR_TILE_CHECK, "Restaurant",
                   ["table", "chair", "chair", "counter", "plant"]),
    "bar": (C.FLOOR_WOOD, "Bar",
            ["counter", "chair", "chair", "table", "shelf"]),
    "clinic": (C.FLOOR_TILE_PALE, "Clinic",
               ["bed", "sink", "shelf", "counter", "chair"]),
    "medical": (C.FLOOR_TILE_PALE, "Medical",
                ["counter", "shelf", "sink", "bed", "chair"]),
    "warehouse": (C.FLOOR_LINO, "Warehouse",
                  ["crate", "crate", "shelf", "shelf", "crate"]),
    "garage": (C.FLOOR_LINO, "Garage", ["crate", "shelf", "counter"]),
    # Nothing goes in a lift car; the door is hung separately (see _furnish).
    "elevator": (C.FLOOR_LINO, "Elevator", []),
    # The game's own shed room: its loot is carpentry, farming and metalwork
    # tools, where "garage" would stock a garden shed with car parts.
    "shed": (C.FLOOR_WOOD, "Shed", ["counter", "shelf", "crate"]),
}

# Room mixes per building flavour. Order matters: the biggest room gets the
# first kind and so on down. Every name here appears in the game's own
# Distributions.lua, so loot actually spawns in them.
RESIDENTIAL = ["livingroom", "kitchen", "bedroom", "bedroom", "dining",
               "bathroom", "hall"]
COMMERCIAL = ["storage", "office", "storage", "kitchen", "bathroom", "hall"]

# Once the mix above is spent, big buildings cycle through these instead of
# repeating the last entry - otherwise a 26x27 shop comes out as nine halls,
# and halls carry almost no loot.
RESIDENTIAL_FILL = ["bedroom", "storage", "bedroom", "livingroom",
                    "bathroom", "office"]
COMMERCIAL_FILL = ["storage", "office", "storage", "bathroom"]

# Room plans for buildings OSM identifies as something specific. A school full
# of bedrooms reads as wrong immediately; these keep the interior in character,
# and the room names drive what loot spawns there.
SPECIAL_MIXES = {
    "school":     (["classroom", "classroom", "library", "office", "gym",
                    "lobby", "bathroom", "storage", "kitchen"],
                   ["classroom", "office", "storage", "bathroom"]),
    "church":     (["church", "lobby", "office", "storage", "bathroom"],
                   ["church", "storage"]),
    "restaurant": (["restaurant", "kitchen", "bar", "storage", "bathroom",
                    "office"],
                   ["restaurant", "storage"]),
    "shop":       (["storage", "office", "storage", "bathroom", "lobby"],
                   ["storage", "office"]),
    "industrial": (["warehouse", "warehouse", "office", "storage", "bathroom",
                    "garage"],
                   ["warehouse", "storage"]),
    "barn":       (["warehouse", "storage", "garage"], ["warehouse", "storage"]),
    "shed":       (["shed"], ["shed"]),
    "medical":    (["clinic", "medical", "lobby", "office", "bathroom",
                    "storage"],
                   ["clinic", "medical", "storage"]),
    "civic":      (["office", "lobby", "office", "storage", "bathroom",
                    "library"],
                   ["office", "storage"]),
    # A block of flats is not one big house: it is several small dwellings off
    # a shared landing, so the mix repeats a compact bedroom/living/kitchen set
    # rather than laying out one household across the whole floor.
    "apartment":  (["hall", "livingroom", "kitchen", "bedroom", "bathroom",
                    "livingroom", "bedroom", "kitchen", "bathroom", "storage"],
                   ["bedroom", "livingroom", "kitchen", "bathroom"]),
}


def _split(x0: int, y0: int, x1: int, y1: int, rng: random.Random,
           depth: int, out: list[Room],
           target_area: int = TARGET_ROOM_AREA,
           mask: list[list[bool]] | None = None) -> None:
    w, h = x1 - x0 + 1, y1 - y0 + 1
    can_v = w >= MIN_SPLIT
    can_h = h >= MIN_SPLIT
    # Measure the floor that is actually inside the building. On a footprint
    # turned 38 degrees half of every bounding rectangle is empty corner, and
    # sizing rooms by the rectangle kept splitting until a house had fifteen
    # rooms a floor, most of them offices and storerooms.
    area = w * h if mask is None else sum(
        1 for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if mask[y][x])
    if depth <= 0 or not (can_v or can_h) or area <= target_area:
        out.append(Room(x0, y0, x1, y1))
        return
    if not can_h:
        vertical = True
    elif not can_v:
        vertical = False
    else:
        vertical = w > h if w != h else rng.random() < 0.5
    if vertical:
        cut = rng.randint(x0 + MIN_ROOM, x1 - MIN_ROOM)
        _split(x0, y0, cut - 1, y1, rng, depth - 1, out, target_area, mask)
        _split(cut, y0, x1, y1, rng, depth - 1, out, target_area, mask)
    else:
        cut = rng.randint(y0 + MIN_ROOM, y1 - MIN_ROOM)
        _split(x0, y0, x1, cut - 1, rng, depth - 1, out, target_area, mask)
        _split(x0, cut, x1, y1, rng, depth - 1, out, target_area, mask)


# What a flat contains, by how many rooms it got. The first entry goes to the
# room the front door opens into; the rest are handed out biggest-first, so the
# bathroom lands on the smallest room.
#
# Size matters: a two-room flat is a bedsit and wants a bathroom more than it
# wants a separate bedroom.
FLAT_PLANS = {
    1: ["livingroom"],
    2: ["livingroom", "bathroom"],
    3: ["livingroom", "bedroom", "bathroom"],
    4: ["livingroom", "kitchen", "bedroom", "bathroom"],
    5: ["livingroom", "kitchen", "bedroom", "bedroom", "bathroom"],
}
FLAT_EXTRA = ["bedroom", "storage"]
# Tiles of corridor wall each flat gets. Narrower slices gave two- and
# three-room flats, and with the bathroom going to the smallest room, a flat
# of two big rooms had a bathroom the size of its living room.
FLAT_FRONTAGE = (8, 11)


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


def _corridor_axis(plan: Plan) -> str | None:
    """"y" or "x" for the direction a corridor runs, None without one."""
    if plan.core is None or not plan.corridor:
        return None
    x0, y0, x1, y1 = plan.core
    return "y" if (y1 - y0) >= (x1 - x0) else "x"


def _apartment_rooms(plan: Plan, rng: random.Random, target: int) -> None:
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
    axis = _corridor_axis(plan)
    if axis is None:
        # No corridor fits (an irregular footprint, usually). One flat per
        # floor is a real kind of building, so lay it out as that.
        _split(0, 0, plan.width - 1, plan.height - 1, rng, MAX_DEPTH,
               plan.rooms, target_area=target, mask=plan.mask)
        for room in plan.rooms:
            room.unit = 1
        return

    cx0, cy0, cx1, cy1 = plan.core
    unit = 0
    if axis == "y":
        sides = [(0, cx0 - 1), (cx1 + 1, plan.width - 1)]
        length = plan.height
    else:
        sides = [(0, cy0 - 1), (cy1 + 1, plan.height - 1)]
        length = plan.width
    for a0, a1 in sides:
        if a1 - a0 + 1 < MIN_ROOM:
            continue
        # Each side sliced independently, so the flats do not line up across
        # the corridor like a spreadsheet.
        for s0, s1 in _slices(length, rng, *FLAT_FRONTAGE):
            unit += 1
            box = (a0, s0, a1, s1) if axis == "y" else (s0, a0, s1, a1)
            flat: list[Room] = []
            _split(*box, rng, MAX_DEPTH, flat, target_area=target, mask=plan.mask)
            for room in flat:
                room.unit = unit
            plan.rooms.extend(flat)

    # Beyond the ends of a corridor that stops short of the building's ends,
    # its own width of floor would otherwise belong to no room at all.
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


def _assign_flat_kinds(plan: Plan) -> None:
    """Give every flat its own set of rooms, arranged around its front door.

    The room touching the corridor is where you walk in, so it becomes the
    living room; the rest follow by size, with the bathroom on the smallest.
    """
    adj = _neighbours(plan)
    corridor = {i for i, r in enumerate(plan.rooms, 1) if r.unit == 0}
    units: dict[int, list[int]] = {}
    for i, room in enumerate(plan.rooms, 1):
        if room.unit == 0:
            room.kind = "hall"
        else:
            units.setdefault(room.unit, []).append(i)
    for members in units.values():
        entry = [i for i in members if any(n in corridor for n in adj[i])]
        by_size = sorted(members, key=lambda i: -plan.rooms[i - 1].area)
        first = max(entry, key=lambda i: plan.rooms[i - 1].area) \
            if entry else by_size[0]
        ordered = [first] + [i for i in by_size if i != first]
        kinds = FLAT_PLANS.get(len(ordered))
        if kinds is None:
            extra = [FLAT_EXTRA[k % len(FLAT_EXTRA)]
                     for k in range(len(ordered) - 5)]
            kinds = FLAT_PLANS[5][:-1] + extra + FLAT_PLANS[5][-1:]
        for i, kind in zip(ordered, kinds):
            plan.rooms[i - 1].kind = kind


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


def _assign_house_kinds(plan: Plan, level: int, levels: int) -> None:
    """Rooms of a house, placed by what they sit next to.

    Handing kinds out in size order put the kitchen wherever the second-biggest
    rectangle fell, bathrooms opening off living rooms, and a kitchen on every
    storey of a three-storey house. Here the ground floor holds the rooms a
    household shares - the living room, the kitchen beside it, dining beside
    that - and upper floors hold bedrooms. Bedrooms go as far from the living
    room as the plan allows; the bathroom takes the smallest room.
    """
    adj = _neighbours(plan)
    free = [i for i, r in enumerate(plan.rooms, 1) if not r.is_core]
    for i, room in enumerate(plan.rooms, 1):
        if i not in free:
            room.kind = "hall"
    if not free:
        return
    area = {i: plan.rooms[i - 1].area for i in free}
    kinds: dict[int, str] = {}

    def take(i: int, kind: str) -> None:
        kinds[i] = kind
        free.remove(i)

    if level == 0:
        living = max(free, key=lambda i: area[i])
        take(living, "livingroom")
        if free:
            near = [n for n in adj[living] if n in free] or free
            kitchen = max(near, key=lambda i: area[i])
            take(kitchen, "kitchen")
            near = [n for n in adj[kitchen] if n in free]
            if near and len(free) >= 3:
                take(max(near, key=lambda i: area[i]), "dining")
        if free and (levels == 1 or len(free) >= 2):
            take(min(free, key=lambda i: area[i]), "bathroom")
        dist = _graph_distance(adj, living)
        rest = sorted(free, key=lambda i: -dist.get(i, 99))
        for n, i in enumerate(rest):
            if levels == 1:
                kinds[i] = "bedroom" if n < 3 else ("storage" if n % 2 else "office")
            else:
                kinds[i] = ("office", "bedroom", "storage")[n % 3]
    else:
        take(min(free, key=lambda i: area[i]), "bathroom")
        for n, i in enumerate(sorted(free, key=lambda i: -area[i])):
            kinds[i] = "bedroom" if n < 4 else ("office" if n % 2 else "storage")

    for i, kind in kinds.items():
        plan.rooms[i - 1].kind = kind
def _assign_kinds(rooms: list[Room], mix: list[str], fill: list[str]) -> None:
    order = sorted(rooms, key=lambda r: -r.area)
    for i, room in enumerate(order):
        room.kind = mix[i] if i < len(mix) else fill[(i - len(mix)) % len(fill)]
    # The smallest room makes a far more convincing bathroom than a hall.
    if len(order) >= 3 and "bathroom" in mix:
        order[-1].kind = "bathroom"


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


def _paint(plan: Plan) -> None:
    plan.grid = [[0] * plan.width for _ in range(plan.height)]
    for idx, r in enumerate(plan.rooms, start=1):
        for y in range(r.y0, r.y1 + 1):
            for x in range(r.x0, r.x1 + 1):
                if plan.mask is not None and not plan.mask[y][x]:
                    continue
                plan.grid[y][x] = idx

    # The stair shaft is painted over whatever is beneath it, identically on
    # every storey. Stairs used to be dropped wherever five tiles happened to be
    # inside the building, which on 80% of them meant a flight crossing a room
    # boundary and running into an interior wall.
    if plan.core is not None:
        cx0, cy0, cx1, cy1 = plan.core
        plan.rooms.append(Room(cx0, cy0, cx1, cy1, kind="hall", unit=0,
                               is_core=True))
        idx = len(plan.rooms)
        for y in range(cy0, cy1 + 1):
            for x in range(cx0, cx1 + 1):
                plan.grid[y][x] = idx

    _renumber(plan)
    _mend_fragments(plan)
    _refit(plan)


# A room piece smaller than this, or only this thick, is not a room. Along a
# diagonal wall the grid cuts the corners of every rectangle into wedges of a
# few tiles; left alone each became a room of its own - a house turned 38
# degrees came out with 18 rooms, most of them triangles you could not stand in.
SLIVER = 10
SLIVER_THICKNESS = 2


def _mend_fragments(plan: Plan) -> None:
    """Split rooms that were cut in two, and fold slivers into a neighbour.

    An irregular footprint or the stair shaft can cut one rectangle into pieces
    that no longer touch. BuildingEd treats them as one room, so the only door
    lands in one piece and the other is sealed; the game then has a room with
    no way in. Each piece becomes a room of its own, and pieces too small to
    be a room are given to whatever they border, preferring the same flat.
    """
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
            plan.rooms.append(Room(0, 0, 0, 0, kind=base.kind, unit=base.unit))
            new = len(plan.rooms)
            for x, y in piece:
                plan.grid[y][x] = new

    def too_small(cells) -> bool:
        if len(cells) < 4:
            return True
        xs = {x for x, _ in cells}
        ys = {y for _, y in cells}
        # A whole rectangle of 3x3 or more is a real room - a small bathroom
        # is exactly that. Only the ragged wedges a diagonal wall leaves go.
        if len(cells) == len(xs) * len(ys) and min(len(xs), len(ys)) >= 3:
            return False
        return len(cells) < SLIVER or (min(len(xs), len(ys)) <= SLIVER_THICKNESS
                                       and len(cells) < 3 * SLIVER)

    for idx in range(1, len(plan.rooms) + 1):
        if plan.rooms[idx - 1].is_core or plan.rooms[idx - 1].is_shaft:
            continue
        cells = [(x, y) for y in range(plan.height) for x in range(plan.width)
                 if plan.grid[y][x] == idx]
        if not cells or not too_small(cells):
            continue
        unit = plan.rooms[idx - 1].unit
        options: dict[int, int] = {}
        for x, y in cells:
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < plan.width and 0 <= ny < plan.height:
                    v = plan.grid[ny][nx]
                    if v and v != idx and not plan.rooms[v - 1].is_shaft:
                        options[v] = options.get(v, 0) + 1
        if not options:
            continue
        home = max(options, key=lambda v: (plan.rooms[v - 1].unit == unit,
                                           options[v]))
        for x, y in cells:
            plan.grid[y][x] = home

    _renumber(plan)


def _unit_touches_corridor(plan: Plan) -> None:
    """Make every flat one connected piece with a wall on the corridor.

    A flat can be cut in two by a notch in the footprint, and a flat sliced
    where the building narrows can border only its neighbours. Either way,
    some of its rooms could only be reached by walking through somebody
    else's home. Working piece by piece: a piece that reaches the corridor
    stays a flat of its own (split off if it had become separated from the
    rest), and a piece that does not is joined to the neighbouring flat it
    shares most wall with.
    """
    corridor_units = {r.unit for r in plan.rooms if r.unit == 0}
    if not corridor_units:
        return
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
            return any(plan.rooms[n - 1].unit == 0 for i in piece for n in adj[i])

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
                changed = True
            if changed:
                break
        if not changed:
            return


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


def _door_spot(edges: list[tuple[int, int, str]],
               min_run: int) -> tuple[tuple[int, int, str], int] | None:
    """The middle of the longest straight run of wall, and that run's length."""
    best = None
    for d in ("W", "N"):
        # Along a W edge the wall runs in y; along an N edge, in x.
        keyed = sorted((e[0], e[1]) if d == "W" else (e[1], e[0])
                       for e in edges if e[2] == d)
        run: list[tuple[int, int]] = []
        for fixed, moving in keyed + [(None, None)]:
            if run and (fixed != run[-1][0] or moving != run[-1][1] + 1):
                if len(run) >= min_run and (best is None or len(run) > best[1]):
                    f, m = run[len(run) // 2]
                    spot = (f, m, "W") if d == "W" else (m, f, "N")
                    best = (spot, len(run))
                run = []
            if fixed is not None:
                run.append((fixed, moving))
    return best


# How much a door between two kinds of room is worth avoiding. Circulation is
# cheap to open onto; rooms a household uses together are cheap to join; a
# bathroom off a kitchen or a bedroom through another bedroom is not how
# anybody builds.
TOGETHER = [{"livingroom", "kitchen"}, {"kitchen", "dining"},
            {"livingroom", "dining"}]
# A flat's front door, by the room it opens into.
FRONT_DOOR_COST = {"livingroom": 0.0, "hall": 0.5, "kitchen": 1.5,
                   "dining": 1.5, "storage": 6.0, "bedroom": 7.0,
                   "bathroom": 12.0}


def _door_cost(a: str, b: str) -> float:
    kinds = {a, b}
    if "hall" in kinds or "lobby" in kinds:
        cost = 1.0
    elif kinds in TOGETHER:
        cost = 1.5
    elif "livingroom" in kinds:
        cost = 3.0
    else:
        cost = 6.0
    if "bathroom" in kinds and not kinds & {"hall", "lobby", "bedroom"}:
        cost += 6.0
    if a == b == "bedroom":
        cost += 8.0
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
        for kind in ("hall", "lobby", "livingroom"):
            found = [i for i, r in enumerate(rooms, 1) if r.kind == kind]
            if found:
                return max(found, key=lambda i: rooms[i - 1].area)
        return max(range(1, n + 1), key=lambda i: rooms[i - 1].area)

    connected = {start_room()} | sealed
    front: set[int] = set()
    placed: set[tuple[int, int]] = set()
    doors_of: dict[int, int] = {}

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
                    elif flat in front and relax < 2:
                        continue
                spot = _door_spot(wall, min_run)
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
                # A bathroom is a dead end. Once it has a door, walking through
                # it to reach another room is the last thing to try.
                for room_idx in (a, b):
                    if rooms[room_idx - 1].kind == "bathroom" and doors_of.get(room_idx):
                        cost += 12.0
                cost -= min(spot[1], 6) * 0.05
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
        spot = _door_spot(wall, 3)
        if spot and rng.random() < 0.6:
            plan.doors.append(spot[0])


def _room_at(plan: Plan, x: int, y: int) -> int:
    if 0 <= x < plan.width and 0 <= y < plan.height:
        return plan.grid[y][x]
    return 0


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
                   avoid: tuple[int, int] | None = None) -> None:
    """One way in, into the room a visitor would expect to arrive in.

    `avoid` is the foot of the staircase, so the front door does not open
    straight onto the bottom step.
    """
    order = {k: i for i, k in enumerate(ENTRY_KINDS)}
    candidates = sorted((i for i in range(1, len(plan.rooms) + 1)
                         if not plan.rooms[i - 1].is_shaft),
                        key=lambda i: (order.get(plan.rooms[i - 1].kind, 50),
                                       -plan.rooms[i - 1].area))
    for idx in candidates:
        runs = _outside_runs(plan, idx)
        if not runs:
            continue

        def score(run):
            side, wall = run
            mid = wall[len(wall) // 2]
            far = 0.0
            if avoid is not None:
                far = abs(mid[0] - avoid[0]) + abs(mid[1] - avoid[1])
            return (len(wall) >= 3, side == "S", far, len(wall))

        side, wall = max(runs, key=score)
        plan.doors.append(wall[len(wall) // 2])
        return


# Tiles of wall per window bay, by what the building is, on its front and on
# its other sides. A house has windows across its front and few down the side;
# a shop front is mostly glass; a barn barely any.
FACADE_SPACING = {
    "house": (7, 13), "apartment": (9, 16), "barn": (12, 24), "shed": (12, 24),
    "industrial": (9, 18), "shop": (3, 8), "restaurant": (3, 8),
    "civic": (4, 9), "school": (4, 8), "church": (7, 14), "medical": (5, 10),
}
DEFAULT_FACADE_SPACING = (5, 11)
# Most windows one room may take, whatever the facade offers it.
ROOM_WINDOW_CAP = {
    "bathroom": 1, "storage": 0, "hall": 0, "garage": 0, "shed": 1, "elevator": 0,
    "kitchen": 1, "bedroom": 2, "dining": 2, "office": 1, "livingroom": 3,
}
DEFAULT_ROOM_WINDOW_CAP = 4
# Rooms that must not be left without daylight.
# Kept to the rooms that matter: guaranteeing every office and dining room a
# window as well pushed facades back up to 1.09 windows per ten tiles of wall.
# Those rooms still get windows from the bays; they just are not promised one.
LIVED_IN = {"livingroom", "bedroom", "kitchen", "classroom", "restaurant"}
MIN_WALL_FOR_WINDOW = 3


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


def _place_windows(building: "Building", kind: str | None,
                   scale: float = 1.0) -> None:
    """Windows in bays down the facade, the same bays on every storey.

    Two things made the buildings look wrong. Windows were spaced along every
    wall at the same pitch, so a house was as glazed down its side as across
    its front; and each storey placed its own, so no window sat above the one
    below. Real facades are built in bays: the positions are decided once for
    the building and repeated floor by floor, and a storey skips a bay only
    where the room behind has no use for a window.

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
    by_side: dict[str, list[tuple[int, int, str, int, int]]] = {}
    for side, wall in _facade_runs(building.storeys[0].grid):
        by_side.setdefault(side, []).extend(wall)
    bays: list[tuple[int, int, str, int, int]] = []
    for side, edges in by_side.items():
        # Position along the side: x for north and south faces, y for west
        # and east.
        along = (lambda e: e[3]) if side in ("N", "S") else (lambda e: e[4])
        positions = sorted({along(e) for e in edges})
        if len(positions) < MIN_WALL_FOR_WINDOW:
            continue
        spacing = max(3, round((near if side in front else far) * scale))
        if side not in front and len(positions) < spacing:
            continue            # a short side stays blank
        inner = positions[1:-1]
        count = max(1, round(len(inner) / spacing))
        step = len(inner) / count
        chosen = {inner[int((i + 0.5) * step)] for i in range(count)}
        bays.extend(e for e in edges if along(e) in chosen)

    for storey in building.storeys:
        blocked = set(getattr(storey, "wall_pieces", set()))
        for x, y, d in storey.doors:
            for off in (-1, 0, 1):
                blocked.add((x + off, y, d) if d == "N" else (x, y + off, d))
        taken: dict[int, int] = {}
        for x, y, d, ix, iy in bays:
            if (x, y, d) in blocked:
                continue
            idx = storey.grid[iy][ix]
            if not idx:
                continue
            room = storey.rooms[idx - 1]
            cap = ROOM_WINDOW_CAP.get(room.kind, DEFAULT_ROOM_WINDOW_CAP)
            if room.is_core:
                cap = 1 if kind == "apartment" else 0
            if taken.get(idx, 0) >= cap:
                continue
            storey.windows.append((x, y, d))
            taken[idx] = taken.get(idx, 0) + 1

        # The bays keep windows in columns, but a room they miss would have no
        # daylight at all. Any room people spend time in that still has none
        # gets one in the middle of its longest outside wall.
        for idx, room in enumerate(storey.rooms, 1):
            # Turning the Windows setting well down turns this promise off
            # too, or the slider would stop having any effect below it.
            if scale > 1.35:
                break
            if taken.get(idx) or room.kind not in LIVED_IN:
                continue
            for _side, wall in _outside_runs(storey, idx):
                # A straight wall keeps its corners clear; a one- or two-tile
                # step of a diagonal wall has no corners to spare.
                inner = wall[1:-1] if len(wall) >= MIN_WALL_FOR_WINDOW else wall
                candidates = sorted(inner, key=lambda e: abs(
                    wall.index(e) - len(wall) // 2))
                spot = next((e for e in candidates if e not in blocked), None)
                if spot is not None:
                    storey.windows.append(spot)
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


SWITCH = "switch"


def _is_wall_piece(role: str) -> bool:
    return C.FURNITURE_LAYERS.get(role, "Furniture") != "Furniture"


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


def _furnish(plan: Plan, rng: random.Random,
             stairs: tuple[int, int, str] | None = None) -> None:
    """Push furniture against room walls, skipping tiles a door needs clear.

    Every room, the corridor and stair hall included, first gets a light
    switch on the wall beside its door. The game hangs a room's ceiling light
    off its switch, so a room without one has no light at all - which is why
    so many rooms were pitch dark: the switch was only on some rooms'
    wishlists, and even there it was written to the floor rather than a wall.
    """
    door_tiles: set[tuple[int, int]] = set()
    door_edges = set(plan.doors)
    # The lift doors take their stretch of wall: nothing hangs on it.
    if plan.shaft_door is not None:
        lx, ly, ld = plan.shaft_door
        door_edges |= {(lx, ly + i, "W") if ld == "W" else (lx + i, ly, "N")
                       for i in range(SHAFT_SIZE)}
    for x, y, d in plan.doors:
        door_tiles.add((x, y))
        door_tiles.add((x - 1, y) if d == "W" else (x, y - 1))
    # Tiles of the flight. A switch hung there would be deleted along with the
    # furniture cleared off the staircase, leaving the stair hall dark.
    stair_tiles: set[tuple[int, int]] = set()
    if stairs is not None:
        sx, sy, sd = stairs
        dx, dy = (0, 1) if sd == "N" else (1, 0)
        stair_tiles = {(sx + dx * i, sy + dy * i) for i in range(STAIR_RUN)}

    if plan.shaft_door is not None:
        lx, ly, ld = plan.shaft_door
        plan.furniture.append(("elevator_door", lx, ly, ld))

    for idx, r in enumerate(plan.rooms, start=1):
        # A lift car has no switch and no furniture: it is a sealed box.
        if r.is_shaft:
            continue
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

        def hang(role: str, x: int, y: int, facing: str) -> bool:
            edge = _wall_edge(x, y, facing)
            if edge in door_edges or edge in used_walls:
                return False
            orient = _facing(role, facing)
            plan.furniture.append((role, x, y, orient))
            used_walls.add(edge)
            plan.wall_pieces.add(edge)
            return True

        # The switch: on a wall one tile from this room's door, the way people
        # actually fit them, or on any wall if the door is awkward.
        mine = [(x, y) for x, y in door_tiles if _room_at(plan, x, y) == idx]
        by_reach = sorted(
            slots,
            key=lambda s: min((abs(s[0] - dx) + abs(s[1] - dy) for dx, dy in mine),
                              default=0))
        for x, y, facing in by_reach:
            if (x, y) in mine and _wall_edge(x, y, facing) in door_edges:
                continue
            if hang(SWITCH, x, y, facing):
                break

        # Nothing else goes in the stair hall or corridor: a flat's front door
        # and the only way past the flight both run through it, and one
        # bookcase beside the stairs closes the corridor.
        if r.is_core:
            continue
        _, _, base = ROOM_STYLE[r.kind]
        # Scale the wishlist with floor area, or a 12x9 living room ends up
        # with four items rattling around in it.
        target = max(len(base), min(14, r.area // 7))
        wishlist = [base[i % len(base)] for i in range(target)]
        occupied: set[tuple[int, int]] = set()
        floor_slots = [s for s in slots]
        rng.shuffle(floor_slots)
        for role in wishlist:
            if _is_wall_piece(role):
                for x, y, facing in floor_slots:
                    if hang(role, x, y, facing):
                        break
                continue
            for (x, y, wanted) in floor_slots:
                orient = _facing(role, wanted)
                cells = _cells_for(role, x, y, orient)
                if any(c in occupied or c in door_tiles for c in cells):
                    continue
                if any(_room_at(plan, cx, cy) != idx for cx, cy in cells):
                    continue
                occupied.update(cells)
                plan.furniture.append((role, x, y, orient))
                break


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

    @property
    def rooms(self) -> list[Room]:
        return [r for s in self.storeys for r in s.rooms]

    def grid_for(self, level: int) -> list[list[int]]:
        """That storey's grid, renumbered into the shared room list."""
        offset = sum(len(s.rooms) for s in self.storeys[:level])
        grid = self.storeys[level].grid
        return [[v + offset if v else 0 for v in row] for row in grid]


STAIR_RUN = 5      # tiles a staircase occupies, from Stairs::bounds
CORE_WIDE = 3      # the shaft is the flight plus a landing beside it


CORRIDOR_WIDE = 3   # a landing wide enough to be circulation, not a cupboard


def _pick_corridor(width: int, height: int, mask: list[list[bool]] | None,
                   rng: random.Random) -> tuple[int, int, int, int] | None:
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
    if span < STAIR_RUN + 2 or across < CORRIDOR_WIDE + 2 * MIN_ROOM:
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
    for start in range(MIN_ROOM, across - CORRIDOR_WIDE - MIN_ROOM + 1):
        run_start = None
        for a in range(span + 1):
            ok = a < span and all(inside(a, b) for b in range(start, start + CORRIDOR_WIDE))
            if ok and run_start is None:
                run_start = a
            if not ok and run_start is not None:
                length = a - run_start
                if length >= needed:
                    centre = abs((start + CORRIDOR_WIDE / 2) - across / 2)
                    score = (-length, centre)
                    if best is None or score < best[0]:
                        if along_y:
                            rect = (start, run_start, start + CORRIDOR_WIDE - 1, a - 1)
                        else:
                            rect = (run_start, start, a - 1, start + CORRIDOR_WIDE - 1)
                        best = (score, rect)
                run_start = None
    return best[1] if best else None


def _pick_core(width: int, height: int, mask: list[list[bool]] | None,
               rng: random.Random) -> tuple[int, int, int, int] | None:
    """Reserve a stair shaft: the same rectangle on every storey.

    Returned as (x0, y0, x1, y1) inclusive, oriented either way round, and
    always wholly inside the footprint - a shaft half outside an L-shaped
    building would put the flight in the garden.
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
                # Central, so the flight is not jammed against the windows.
                score = (abs((x0 + cw / 2) - width / 2)
                         + abs((y0 + ch / 2) - height / 2))
                if best_score is None or score < best_score - 1e-9:
                    best_score, best = score, [(x0, y0, x0 + cw - 1,
                                                y0 + ch - 1)]
                elif abs(score - best_score) < 1e-9:
                    best.append((x0, y0, x0 + cw - 1, y0 + ch - 1))
    return rng.choice(best) if best else None


# Buildings this tall get a lift. Four flights is a fair climb; a thirty-storey
# tower on stairs alone is not something anyone built.
ELEVATOR_FROM_LEVELS = 5
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
            landing = [(cx0, y0 + i) for i in range(s)] + [(cx1, y0 + i) for i in range(s)]
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


def _carve_shaft(plan: Plan, shaft: tuple[int, int, int, int],
                 door: tuple[int, int, str]) -> None:
    """Paint the elevator shaft over the storey as a sealed room of its own."""
    x0, y0, x1, y1 = shaft
    plan.rooms.append(Room(x0, y0, x1, y1, kind="elevator", unit=0, is_shaft=True))
    idx = len(plan.rooms)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            plan.grid[y][x] = idx
    plan.shaft = shaft
    plan.shaft_door = door
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


def build_building(width: int, height: int, levels: int = 1,
                   commercial: bool = False, seed: int = 0,
                   kind: str | None = None,
                   mask: list[list[bool]] | None = None,
                   settings: Settings | None = None) -> Building:
    """Lay out a building of `levels` storeys.

    Each storey is laid out separately rather than copied, because a block of
    flats whose every floor is identical reads as a rendering error; only the
    staircase has to line up, and it does because the shaft is reserved first.
    """
    levels = max(1, levels)
    rng = random.Random(seed ^ 0x5745)

    # A block of flats gets a corridor whether or not it is tall enough to
    # need stairs, because the flats have to open onto something. Everything
    # else only needs a shaft, and only once there is a floor above.
    core = None
    corridor = False
    if kind == "apartment":
        core = _pick_corridor(width, height, mask, rng)
        corridor = core is not None
    if core is None and levels > 1:
        core = _pick_core(width, height, mask, rng)
    if levels > 1 and core is None:
        levels = 1          # nowhere to put a staircase, so one floor it is

    stairs = _stairs_in_core(core) if core is not None and levels > 1 else None
    shaft = shaft_door = None
    if core is not None and levels >= ELEVATOR_FROM_LEVELS:
        found = _pick_shaft(core, width, height, mask, stairs)
        if found:
            shaft, shaft_door = found
    storeys = [
        build_plan(width, height, commercial=commercial, seed=seed + 977 * lvl,
                   kind=kind, mask=mask, ground=(lvl == 0), settings=settings,
                   core=core, level=lvl, levels=levels, stairs=stairs,
                   corridor=corridor, shaft=shaft, shaft_door=shaft_door)
        for lvl in range(levels)
    ]
    building = Building(width=width, height=height, storeys=storeys)
    if stairs is not None:
        for lvl in range(levels - 1):
            building.stairs.append(stairs)
            _clear_for_stairs(storeys[lvl], *stairs)
            _clear_for_stairs(storeys[lvl + 1], *stairs)
    # Windows last and for the whole building at once, so they stack in
    # columns instead of each floor scattering its own.
    _place_windows(building, kind, (settings or Settings()).window_spacing_scale)
    return building


def _stair_foot(stairs: tuple[int, int, str] | None) -> tuple[int, int] | None:
    if stairs is None:
        return None
    x, y, d = stairs
    return (x, y + STAIR_RUN - 1) if d == "N" else (x + STAIR_RUN - 1, y)


# Rooms scale with what the building is: a warehouse is a few great halls, a
# church one nave, a school rooms the size of classrooms.
KIND_ROOM_SCALE = {"industrial": 6.0, "barn": 5.0, "shed": 8.0, "church": 4.0,
                   "shop": 2.0, "school": 1.6, "civic": 1.5,
                   "restaurant": 1.5, "medical": 1.3}
MAX_ROOMS_PER_FLOOR = 90


def build_plan(width: int, height: int, commercial: bool = False,
               seed: int = 0, kind: str | None = None,
               mask: list[list[bool]] | None = None,
               ground: bool = True,
               settings: Settings | None = None,
               core: tuple[int, int, int, int] | None = None,
               level: int = 0, levels: int = 1,
               stairs: tuple[int, int, str] | None = None,
               corridor: bool = False,
               shaft: tuple[int, int, int, int] | None = None,
               shaft_door: tuple[int, int, str] | None = None) -> Plan:
    """Lay out and furnish one storey of the given tile size.

    `ground` gates the exterior door: a door in an upper-floor wall opens onto
    a five-metre drop, and the game will happily let a zombie walk through it.
    """
    settings = settings or Settings()
    rng = random.Random(seed)
    plan = Plan(width=width, height=height, mask=mask, core=core,
                corridor=corridor)
    # Rooms in a flat are smaller than rooms in a house, and there have to be
    # enough of them per floor to make several dwellings out of.
    target = settings.room_size * KIND_ROOM_SCALE.get(kind or "", 1.0)
    if kind == "apartment":
        target = max(16, round(settings.room_size * 0.4))
    # A factory floor 160 tiles across split into house-sized rooms would be
    # hundreds of cupboards. However big the building, keep it to a number of
    # rooms a person could walk through.
    floor_tiles = sum(map(sum, mask)) if mask is not None else width * height
    target = max(target, floor_tiles / MAX_ROOMS_PER_FLOOR)

    if kind == "apartment":
        _apartment_rooms(plan, rng, target)
    else:
        _split(0, 0, width - 1, height - 1, rng, MAX_DEPTH, plan.rooms,
               target_area=target, mask=mask)
    _paint(plan)

    # Kinds are chosen after painting, from the plan as it really is: what a
    # room is depends on what it borders, and that is only known once the
    # footprint and the shaft have had their say.
    if kind == "apartment":
        _unit_touches_corridor(plan)
        _assign_flat_kinds(plan)
    elif kind and kind in SPECIAL_MIXES:
        mix, fill = SPECIAL_MIXES[kind]
        _assign_kinds([r for r in plan.rooms if not r.is_core], mix, fill)
    elif commercial:
        _assign_kinds([r for r in plan.rooms if not r.is_core],
                      COMMERCIAL, COMMERCIAL_FILL)
    else:
        _assign_house_kinds(plan, level, levels)
    for room in plan.rooms:
        if room.is_core:
            room.kind = "hall"
    if shaft is not None:
        _carve_shaft(plan, shaft, shaft_door)

    _doors(plan, rng)
    if ground:
        _exterior_door(plan, rng, avoid=_stair_foot(stairs))
    _furnish(plan, rng, stairs)
    return plan


def _largest_rectangle(todo: list[list[bool]]) -> tuple[int, int, int, int] | None:
    """Biggest all-True rectangle as (x0, y0, width, height), by histogram."""
    h = len(todo)
    w = len(todo[0]) if h else 0
    heights = [0] * w
    best = None
    best_area = 0
    for y in range(h):
        for x in range(w):
            heights[x] = heights[x] + 1 if todo[y][x] else 0
        stack: list[int] = []
        for x in range(w + 1):
            cur = heights[x] if x < w else 0
            start = x
            while stack and heights[stack[-1]] >= cur:
                top = stack.pop()
                left = stack[-1] + 1 if stack else 0
                area = heights[top] * (x - left)
                if area > best_area:
                    best_area = area
                    best = (left, y - heights[top] + 1, x - left, heights[top])
                start = left
            stack.append(x)
    return best


def roof_rects(grid: list[list[int]]) -> list[tuple[int, int, int, int, dict]]:
    """Flat roofs covering exactly a storey's footprint.

    A BuildingEd roof is a rectangle, and every building here used to get one
    the size of its bounding box. On an L-shaped or notched footprint that
    roof reaches out over the yard - up to 43% of it over nothing on the
    buildings measured. The footprint is covered instead by the largest
    rectangles that fit, biggest first, which keeps the count low on the
    common shapes: an L takes two roofs, a notched block three.

    Each side is capped - drawn with a rim - only where it is the edge of the
    building. Where one roof meets another the rim would draw a ridge across
    the middle of a flat roof, so that side is left open.
    """
    h = len(grid)
    w = len(grid[0]) if h else 0
    inside = [[bool(grid[y][x]) for x in range(w)] for y in range(h)]
    todo = [row[:] for row in inside]
    rects = []
    while True:
        found = _largest_rectangle(todo)
        if found is None:
            break
        x0, y0, rw, rh = found
        for y in range(y0, y0 + rh):
            for x in range(x0, x0 + rw):
                todo[y][x] = False

        def open_side(cells) -> bool:
            return all(0 <= cx < w and 0 <= cy < h and inside[cy][cx]
                       for cx, cy in cells)

        caps = {
            "cappedW": not open_side([(x0 - 1, y) for y in range(y0, y0 + rh)]),
            "cappedE": not open_side([(x0 + rw, y) for y in range(y0, y0 + rh)]),
            "cappedN": not open_side([(x, y0 - 1) for x in range(x0, x0 + rw)]),
            "cappedS": not open_side([(x, y0 + rh) for x in range(x0, x0 + rw)]),
        }
        rects.append((x0, y0, rw, rh, caps))
    return rects
