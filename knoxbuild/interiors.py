"""Shops, offices and homes furnished the way Knox County's own are.

A room used to be furnished from a wishlist pushed against its walls, so a
grocery was a ring of bookcases round an empty floor and an office a table and
a chair - and since every flat drew on the same sofa, bed and wardrobe, a
block of flats was one flat repeated. What the game's own buildings do
instead, read off their compiled rooms (tools/building_stats.py and renders
of Muldraugh, West Point and Louisville):

- a shop's sales floor has rows of shelving standing out into the room, their
  ends to the shop front so you see down the aisles from the door, shelves or
  fridges along the other walls, and a counter with the till just inside the
  door; clothes shops have rails in rows and mannequins in the window;
- an office is desks with their chairs in rows, filing cabinets along a wall,
  a water cooler and a board on the wall;
- a home's living room is a sofa facing the television across a coffee
  table, a bedroom a bed with its head to the wall between bedside tables, and
  the furniture differs from home to home.
"""
from __future__ import annotations

import random

from . import catalog as C

OPPOSITE = {"N": "S", "S": "N", "W": "E", "E": "W"}
STEP = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}

# What each kind of shop is fitted with. "rows" stand in the middle, one piece
# after another in lines running back from the shop front; "wall" goes along
# the side walls, "back" along the wall facing the front; "front" stands just
# inside the shop front; "counter" is the till counter by the door.
STORES = {
    "grocery": {"rows": "shop_aisle", "wall": ["shop_shelf", "shop_shelf_white"],
                "back": ["shop_fridge_open", "shop_fridge_double", "shop_freezer"],
                "counter": "shop_counter", "front": ["shop_bin"]},
    "conveniencestore": {"rows": "shop_aisle_red", "wall": ["shop_shelf_red"],
                         "back": ["shop_fridge", "shop_fridge", "shop_fridge_double"],
                         "counter": "shop_counter_red", "front": ["vending", "vending_snacks"]},
    "generalstore": {"rows": "shop_aisle", "wall": ["shop_shelf_wood", "shop_shelf"],
                     "back": ["shop_shelf", "shop_fridge_double"],
                     "counter": "shop_counter", "front": ["shop_bin"]},
    "liquorstore": {"rows": "shop_aisle", "wall": ["shop_shelf_wood"],
                    "back": ["shop_fridge", "shop_fridge_white"],
                    "counter": "shop_counter", "front": []},
    "pharmacy": {"rows": "shop_aisle", "wall": ["shop_shelf_white"],
                 "back": ["shop_display", "shop_shelf_white"],
                 "counter": "shop_counter", "front": ["shop_case"]},
    "clothingstore": {"rows": "clothes_rack", "wall": ["clothes_rack", "shop_shelf_wood"],
                      "back": ["shop_shelf_wood", "mirror"],
                      "counter": "shop_counter", "front": ["mannequin", "mannequin_male",
                                                           "mannequin_dark"]},
    "bookstore": {"rows": "bookcases", "wall": ["bookshelf"], "back": ["bookshelf"],
                  "counter": "shop_counter", "front": []},
    "toolstore": {"rows": "metal_rack", "wall": ["metal_rack", "shop_shelf_wood"],
                  "back": ["metal_rack"], "counter": "shop_display", "front": ["shop_bin"]},
}
# Pieces that stand against a wall on any side, used where a piece above only
# has north and west sprites and the wall is a south or east one.
# The other shops OpenStreetMap names (knoxbuild/uses.py), fitted out like
# one of the above with a few pieces of their own.
_LIKE = {
    "giftstore": ("generalstore", {"front": ["plant"]}),
    "toystore": ("generalstore", {"wall": ["shop_shelf", "bookshelf"]}),
    "candystore": ("conveniencestore", {"front": ["shop_case"]}),
    "gasstore": ("conveniencestore", {}),
    "butcher": ("grocery", {"rows": "shop_display", "back": ["shop_fridge_double", "shop_freezer"]}),
    "bakery": ("generalstore", {"rows": "shop_display", "back": ["shop_shelf_white"],
                                "front": ["shop_case"]}),
    "departmentstore": ("clothingstore", {"wall": ["shop_shelf", "clothes_rack"]}),
    "sportstore": ("clothingstore", {"wall": ["metal_rack", "shop_shelf"], "front": ["mannequin_male"]}),
    "jewelrystore": ("pharmacy", {"rows": "shop_display", "wall": ["shop_case"], "front": ["mirror"]}),
    "camerastore": ("pharmacy", {"rows": "shop_display", "wall": ["shop_shelf_white"]}),
    "musicstore": ("bookstore", {"front": ["shop_case"]}),
    "movierental": ("bookstore", {"wall": ["shop_shelf"]}),
    "gunstore": ("toolstore", {"rows": "shop_display", "wall": ["metal_rack"]}),
    "gardenstore": ("toolstore", {"front": ["plant", "plant"], "wall": ["shop_shelf_wood", "plant"]}),
    "furniturestore": ("generalstore", {"rows": "bookcases", "wall": ["wardrobe", "dresser", "sofa"],
                                        "back": ["double_bed", "wardrobe2"], "front": ["armchair"]}),
}
for _kind, (_base, _over) in _LIKE.items():
    STORES[_kind] = {**STORES[_base], **_over}
ANY_WALL = {"shop_aisle": "shop_shelf", "shop_aisle_red": "shop_shelf_red",
            "shop_shelf_wood": "shop_shelf", "shop_fridge_open": "shop_fridge_double",
            "clothes_rack": "shop_shelf", "metal_rack": "shop_shelf", "mirror": "shop_shelf",
            "shop_display": "shop_counter"}
# The shops a ground floor may hold when OpenStreetMap does not say which,
# weighted roughly as Knox County's are.
STORE_WEIGHTS = {"generalstore": 3, "grocery": 2, "conveniencestore": 3, "clothingstore": 3,
                 "liquorstore": 1, "pharmacy": 2, "bookstore": 1, "toolstore": 1}
# Rows of shelving need this much floor, and the rows this much space apart
# (the shelf and a two-tile aisle).
MIN_SALES_FLOOR = 20
ROW_EVERY = 3
BOOKCASE_ROW_EVERY = 4
CROSS_AISLE_EVERY = 8
# Mannequins, drinks machines or bins inside the shop front, at most.
FRONT_PIECES = 3


def store_kind(rng: random.Random, hint: str | None = None) -> str:
    if hint in STORES:
        return hint
    kinds = list(STORE_WEIGHTS)
    return rng.choices(kinds, weights=[STORE_WEIGHTS[k] for k in kinds])[0]


def _layout():
    from . import layout
    return layout


def _cells(plan, idx: int, room) -> set[tuple[int, int]]:
    return {(x, y) for y in range(room.y0, room.y1 + 1) for x in range(room.x0, room.x1 + 1)
            if plan.grid[y][x] == idx}


def _front_side(plan, idx: int, cells: set, street: str | None) -> str:
    """The side of the room its shop front is on: the street side if it has an
    outside wall there, else the side with its outside door, else the side
    with the most outside wall."""
    L = _layout()
    counts = {s: 0 for s in STEP}
    edge = {"N": lambda x, y: (x, y, "N"), "S": lambda x, y: (x, y + 1, "N"),
            "W": lambda x, y: (x, y, "W"), "E": lambda x, y: (x + 1, y, "W")}
    for x, y in cells:
        for s, (dx, dy) in STEP.items():
            # A wall shared with the next building is no shop front.
            if not L._room_at(plan, x + dx, y + dy) and edge[s](x, y) not in plan.party:
                counts[s] += 1
    if street in counts and counts[street] >= 3:
        return street
    for x, y, d in plan.doors:
        for inside, outside, side in (((x, y), (x - 1, y) if d == "W" else (x, y - 1), "W" if d == "W" else "N"),
                                      ((x - 1, y) if d == "W" else (x, y - 1), (x, y), "E" if d == "W" else "S")):
            if inside in cells and not L._room_at(plan, *outside):
                return side
    return max(counts, key=lambda s: counts[s])


class Frame:
    """Room coordinates as (along the front, depth in from the front)."""

    def __init__(self, cells: set, front: str):
        self.front = front
        xs = [x for x, _ in cells]
        ys = [y for _, y in cells]
        self.x0, self.x1, self.y0, self.y1 = min(xs), max(xs), min(ys), max(ys)
        self.along_x = front in ("N", "S")
        self.length = (self.x1 - self.x0 + 1) if self.along_x else (self.y1 - self.y0 + 1)
        self.depth = (self.y1 - self.y0 + 1) if self.along_x else (self.x1 - self.x0 + 1)

    def xy(self, a: int, d: int) -> tuple[int, int]:
        if self.front == "S":
            return self.x0 + a, self.y1 - d
        if self.front == "N":
            return self.x0 + a, self.y0 + d
        if self.front == "W":
            return self.x0 + d, self.y0 + a
        return self.x1 - d, self.y0 + a


def _fits(plan, idx, role, x, y, orient, blocked) -> list[tuple[int, int]] | None:
    L = _layout()
    if orient not in C.FURNITURE[role]:
        return None
    cells = L._cells_for(role, x, y, orient)
    if any(c in blocked or L._room_at(plan, *c) != idx for c in cells):
        return None
    return cells


def furnish_store(plan, idx: int, room, rng: random.Random, door_tiles: set,
                  keep_clear: set, street: str | None) -> bool:
    """Fit out a shop's sales floor. False if the room is too small to."""
    L = _layout()
    spec = STORES[room.kind]
    cells = _cells(plan, idx, room)
    if len(cells) < MIN_SALES_FLOOR:
        return False
    front = _front_side(plan, idx, cells, street)
    frame = Frame(cells, front)
    blocked = set(keep_clear)
    # A tile's clearance round every door into the room.
    for dx, dy in door_tiles:
        if (dx, dy) in cells:
            blocked |= {(dx + i, dy + j) for i in (-1, 0, 1) for j in (-1, 0, 1)}
    placed: set[tuple[int, int]] = set()

    def put(role, x, y, orient, ring=False) -> bool:
        got = _fits(plan, idx, role, x, y, orient, blocked | placed)
        if got is None:
            return False
        plan.furniture.append((role, x, y, orient))
        placed.update(got)
        if ring:
            placed.update((cx + i, cy + j) for cx, cy in got for i in (-1, 0, 1) for j in (-1, 0, 1))
        return True

    # The till counter: just inside the door, in a short run parallel to the
    # shop front, with its register, and room behind it for the cashier.
    doors_in = [(x, y) for x, y in door_tiles if (x, y) in cells]
    front_tiles = [(a, frame.xy(a, 0)) for a in range(frame.length)]
    door_along = next((a for a, xy in front_tiles if xy in doors_in), frame.length // 2)
    counter = spec["counter"]
    back_to = OPPOSITE[front]
    run = 3 if frame.length >= 9 else 2
    for start in (door_along + 2, door_along - 1 - run, 1, frame.length - run - 1):
        spots = [frame.xy(start + k, 2) for k in range(run)]
        orient = L._facing(counter, back_to)
        if all(_fits(plan, idx, counter, x, y, orient, blocked | placed) for x, y in spots):
            for x, y in spots:
                put(counter, x, y, orient)
            mx, my = spots[len(spots) // 2]
            plan.furniture.append(("register", mx, my, L._facing("register", back_to)))
            # The cashier's tile behind, and a tile in front for customers.
            placed.update(frame.xy(start + k, d) for k in range(-1, run + 1) for d in (1, 3))
            break

    # Along the walls. Each wall is walked tile by tile, fitting one piece after
    # another so they stand in a line.
    def fill_wall(side: str, roles: list[str]):
        if not roles:
            return
        line = sorted((c for c in cells if L._room_at(plan, c[0] + STEP[side][0], c[1] + STEP[side][1]) != idx),
                      key=lambda c: (c[0], c[1]))
        on_wall = set(line)
        k = 0
        i = 0
        while i < len(line):
            x, y = line[i]
            role = roles[k % len(roles)]
            if role not in C.FURNITURE or side not in C.FURNITURE[role]:
                role = ANY_WALL.get(role, role)
            if role not in C.FURNITURE:
                i += 1
                continue
            orient = side if side in C.FURNITURE[role] else None
            if orient is None:
                i += 1
                continue
            # Pieces grow east or south from their anchor; on a south or east
            # wall the anchor is the piece's own first tile all the same.
            if _layout()._is_wall_piece(role):
                if _layout()._wall_edge(x, y, side) not in plan.wall_pieces and \
                        put(role, x, y, orient):
                    plan.wall_pieces.add(_layout()._wall_edge(x, y, side))
                    k += 1
                i += 1
                continue
            # The whole piece against this wall: past a corner or a doorway
            # it would stand out into the room.
            if all(c in on_wall for c in L._cells_for(role, x, y, orient)) and put(role, x, y, orient):
                k += 1
                i += len(C.FURNITURE[role][orient])
            else:
                i += 1

    for side in STEP:
        if side == front:
            continue
        fill_wall(side, spec["back"] if side == back_to else spec["wall"])

    # Rows back from the front, starting two tiles in from each side wall and
    # leaving the front and back free to walk along.
    row_role = spec["rows"]
    every = BOOKCASE_ROW_EVERY if row_role == "bookcases" else ROW_EVERY
    orient_row = "W" if frame.along_x else "N"
    for a in range(2, frame.length - 2, every):
        lines = [(a, "E" if frame.along_x else "S"), (a + 1, "W" if frame.along_x else "N")] \
            if row_role == "bookcases" else [(a, orient_row)]
        if any(a2 > frame.length - 3 for a2, _ in lines):
            continue
        for a2, orient in lines:
            role = "bookshelf" if row_role == "bookcases" else row_role
            d = 4
            since_cross = 0
            while d < frame.depth - 2:
                if since_cross >= CROSS_AISLE_EVERY:
                    d += 2
                    since_cross = 0
                    continue
                x, y = frame.xy(a2, d)
                # A piece in a north-south row is anchored at its north end;
                # walking from a south front, step to that end first.
                size = len(C.FURNITURE[role][L._facing(role, orient)])
                if not frame.along_x and front == "E" or frame.along_x and front == "S":
                    ax, ay = frame.xy(a2, d + size - 1)
                    if frame.along_x:
                        x, y = x, ay
                    else:
                        x, y = ax, y
                if put(role, x, y, L._facing(role, orient)):
                    d += size
                    since_cross += size
                else:
                    d += 1

    # Just inside the shop front: mannequins in a clothes shop's window, a
    # drinks machine, a bin.
    front_roles = spec.get("front") or []
    for n, a in enumerate(range(1, frame.length - 1, 3)):
        if not front_roles or n >= FRONT_PIECES:
            break
        x, y = frame.xy(a, 1)
        role = front_roles[n % len(front_roles)]
        put(role, x, y, L._facing(role, back_to))
    return True


OFFICE_DESKS = ["desk", "desk_dark", "desk_long", "desk_long_pale"]


def furnish_office(plan, idx: int, room, rng: random.Random, occupied: set,
                   keep_clear: set) -> list[str]:
    """Desks with their chairs in rows. Returns what is left for the walls."""
    L = _layout()
    desk = rng.choice(OFFICE_DESKS)
    long_desk = len(C.FURNITURE[desk]["N"]) == 3
    group = [(desk, 0, 1, "S"), ("office_chair", 1 if long_desk else 0, 0, "N")]
    placed = L._place_group(plan, idx, room, group, max(1, room.area // 16), occupied, keep_clear)
    cabinet = rng.choice(["filing_cabinet", "filing_cabinet_pale"])
    walls = [cabinet, cabinet, "water_cooler", "whiteboard", "plant", cabinet, "corkboard",
             "bookshelf"]
    # A room too narrow for a desk out in the floor has one against the wall.
    return ([desk, "office_chair"] if not placed else []) + walls


# A home's own furniture: one choice per flat (or per storey of a house) for
# each of these, so the flat next door has a different sofa, bed, wardrobe and
# kitchen. The sofa and armchair come as a matching pair.
SOFA_SETS = [("sofa", "armchair")] + [(f"sofa_{i}", f"armchair_{i}") for i in range(1, 15)]
CHOICES = {
    "double_bed": ["double_bed", "double_bed_alt", "double_bed_black"],
    "bed": ["bed", "bed_alt", "bed_plain"],
    "wardrobe": ["wardrobe", "wardrobe2", "wardrobe_pale", "wardrobe_black", "wardrobe_oak",
                 "wardrobe_tan"],
    "dresser": ["dresser", "dresser_alt", "dresser_black", "dresser_tan"],
    "counter": ["counter"] + [f"counter_{i}" for i in range(1, 8)],
}


def palette(rng: random.Random) -> dict[str, str]:
    """Role -> the role this home uses for it."""
    sofa, armchair = rng.choice([s for s in SOFA_SETS if s[0] in C.FURNITURE and s[1] in C.FURNITURE])
    out = {"sofa": sofa, "armchair": armchair}
    for role, options in CHOICES.items():
        options = [o for o in options if o in C.FURNITURE]
        pick = rng.choice(options)
        out[role] = pick
    # Both beds of a pair and both wardrobes follow the one choice.
    out["double_bed_alt"] = out["double_bed"]
    out["bed_alt"] = out["bed"]
    out["wardrobe2"] = out["wardrobe"]
    out["dresser_alt"] = rng.choice([o for o in CHOICES["dresser"] if o in C.FURNITURE])
    return out


def bed_against_wall(plan, idx: int, room, slots, occupied: set, door_tiles: set,
                     bed: str, side_table: str | None) -> bool:
    """A bed with its head to a wall and a bedside table on each side, on the
    longest stretch of inside wall that takes it."""
    L = _layout()
    by_side: dict[str, list] = {}
    for x, y, facing in slots:
        by_side.setdefault(facing, []).append((x, y))
    order = sorted(by_side, key=lambda s: (any(not L._room_at(plan, x + STEP[s][0], y + STEP[s][1])
                                                for x, y in by_side[s]), -len(by_side[s])))
    for side in order:
        orient = L._facing(bed, side)
        if orient != side:
            continue
        tiles = sorted(by_side[side])
        for x, y in tiles[len(tiles) // 3:] + tiles[:len(tiles) // 3]:
            cells = L._cells_for(bed, 0, 0, orient)
            w = max(cx for cx, _ in cells)
            h = max(cy for _, cy in cells)
            ax = x - w if side == "E" else x
            ay = y - h if side == "S" else y
            got = L._cells_for(bed, ax, ay, orient)
            if any(c in occupied or c in door_tiles or L._room_at(plan, *c) != idx for c in got):
                continue
            if side in ("N", "S"):
                edge_y = y
                flank = [(ax - 1, edge_y), (ax + w + 1, edge_y)]
            else:
                edge_x = x
                flank = [(edge_x, ay - 1), (edge_x, ay + h + 1)]
            plan.furniture.append((bed, ax, ay, orient))
            occupied.update(got)
            if side_table and side_table in C.FURNITURE:
                t_or = L._facing(side_table, side)
                for fx, fy in flank:
                    tc = L._cells_for(side_table, fx, fy, t_or)
                    if all(c not in occupied and c not in door_tiles and L._room_at(plan, *c) == idx
                           for c in tc):
                        plan.furniture.append((side_table, fx, fy, t_or))
                        occupied.update(tc)
            return True
    return False
