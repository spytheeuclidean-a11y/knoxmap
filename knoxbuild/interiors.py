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
                "tills": 2, "back_counter": "shop_counter",
                "back": ["shop_fridge_open", "shop_fridge_double", "shop_freezer"],
                "counter": "shop_counter", "front": ["shop_bin"]},
    "conveniencestore": {"rows": "shop_aisle", "wall": ["shop_shelf_red", "shop_fridge"],
                         "back": ["shop_fridge", "shop_fridge", "shop_fridge_double"],
                         "counter": "shop_counter_red", "front": ["vending", "vending_snacks"],
                         "produce": 2},
    "generalstore": {"rows": "shop_aisle", "wall": ["shop_shelf_wood", "shop_shelf"],
                     "back": ["shop_shelf", "shop_fridge_double"],
                     "counter": "shop_counter", "front": ["shop_bin"]},
    "liquorstore": {"rows": "shop_aisle", "wall": ["shop_shelf_wood"],
                    "back": ["shop_fridge", "shop_fridge_white"],
                    "counter": "shop_counter", "front": []},
    "pharmacy": {"rows": "shop_aisle", "wall": ["shop_shelf_white"],
                 "back_counter": "shop_counter",
                 "back": ["shop_display", "shop_shelf_white"],
                 "counter": "shop_counter", "front": ["shop_case"]},
    "clothingstore": {"rows": "clothes_rack", "wall": ["clothes_rack", "shop_shelf_wood"],
                      "back": ["shop_shelf_wood", "mirror"],
                      "counter": "shop_counter", "front": ["mannequin", "mannequin_male",
                                                           "mannequin_dark"]},
    "bookstore": {"rows": "bookcases", "wall": ["bookshelf"], "back": ["bookshelf"], "nook": True,
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
    # A forecourt shop: the drinks coolers along the back wall, snack shelving
    # down the sides and in short aisles, the counter by the door where the
    # cashier can see the pumps. Coolers on every wall was a cold room.
    "gasstore": ("conveniencestore", {"wall": ["shop_shelf_red", "shop_shelf_red", "shop_fridge"],
                                      "front": ["vending", "vending_snacks"], "produce": 1}),
    "butcher": ("grocery", {"back_counter": "shop_counter", "rows": "shop_display", "back": ["shop_fridge_double", "shop_freezer"]}),
    "bakery": ("generalstore", {"back_counter": "shop_counter", "rows": "shop_display", "back": ["shop_shelf_white"],
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
    # The units Knox County's mall is let out to. clothesstore is the game's
    # own spelling - 158 rooms across the county against 9 for the
    # clothingstore we were writing - so it carries the better loot table.
    "clothesstore": ("clothingstore", {}),
    "shoestore": ("clothingstore", {"rows": "shop_shelf_wood",
                                    "wall": ["shop_shelf_wood", "shop_display"],
                                    "front": ["mirror"]}),
    "sewingstore": ("clothingstore", {"rows": "shop_display", "wall": ["shop_shelf_wood"]}),
    "electronicsstore": ("camerastore", {"wall": ["shop_shelf", "shop_case"]}),
    "housewarestore": ("generalstore", {"wall": ["shop_shelf_wood", "dresser"]}),
    "cornerstore": ("conveniencestore", {"produce": 2}),
    "optometrist": ("pharmacy", {"front": ["mirror"]}),
}
# Hanging rails: wall fittings, not aisle ones.
RACKS = {"clothes_rack", "clothes_rack_small"}
# What may stand in an aisle, besides the piece "rows" names.
#
# Every aisle used to be the same piece, so a supermarket or a mall came out
# as a perfectly regular grid of one shelf repeated forty times - "shopping
# malls generate repeated patterns of clothing racks and food shelves". Real
# shops mix their fittings, and a long aisle changes what it holds partway
# along, so the rows are drawn from these instead.
AISLE_MIX = {
    "grocery": ["shop_aisle", "shop_aisle", "shop_shelf"],
    "conveniencestore": ["shop_aisle", "shop_aisle_red", "shop_shelf_red"],
    "generalstore": ["shop_aisle", "shop_shelf", "shop_shelf_wood"],
    "liquorstore": ["shop_aisle", "shop_shelf_wood", "shop_shelf"],
    "pharmacy": ["shop_aisle", "shop_shelf_white"],
    "clothingstore": ["shop_shelf_wood", "shop_display", "shop_shelf_wood"],
    "toolstore": ["metal_rack", "shop_shelf_wood"],
}
for _kind, _mix in AISLE_MIX.items():
    STORES[_kind]["aisles"] = _mix
for _kind, (_base, _over) in _LIKE.items():
    STORES[_kind] = {**STORES[_base], **_over}
    # Fresh produce only where it is said: a candy store is not a greengrocer.
    if "produce" not in _over:
        STORES[_kind].pop("produce", None)
    # A shop given rows of its own does not keep the mix it was based on.
    if "rows" in _over and "aisles" not in _over:
        STORES[_kind]["aisles"] = [_over["rows"]]
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
# Produce stands just inside the door of a grocery: as many as fit, to this.
MAX_STANDS = 6
# A bank of coolers takes this share of its wall; display cases, this many rows.
BANK_SHARE = 0.6
MAX_CASE_ROWS = 2


def is_cooler(role: str) -> bool:
    return "fridge" in role or "freezer" in role


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


def furnish_service_bay(plan, idx: int, room, rng: random.Random,
                        door_tiles: set, keep_clear: set,
                        mechanic: bool = False) -> bool:
    """Furnish the perimeter of a garage while leaving vehicle bays open."""
    L = _layout()
    cells = _cells(plan, idx, room)
    if len(cells) < MIN_SALES_FLOOR or min(room.w, room.h) < 6:
        return False
    front = _front_side(plan, idx, cells, None)
    frame = Frame(cells, front)
    blocked = set(keep_clear) | set(door_tiles)
    for x, y in door_tiles:
        if (x, y) in cells:
            blocked.update((x + dx, y + dy)
                           for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    placed: set[tuple[int, int]] = set()

    def put(role: str, along: int, depth: int, wall: str) -> bool:
        x, y = frame.xy(along, depth)
        orient = L._facing(role, wall)
        got = _fits(plan, idx, role, x, y, orient, blocked | placed)
        if got is None:
            return False
        plan.furniture.append((role, x, y, orient))
        placed.update(got)
        return True

    left, right = (("W", "E") if frame.along_x else ("N", "S"))
    for depth in range(4, frame.depth - 2, 4):
        for along, side in ((0, left), (frame.length - 1, right)):
            put(rng.choice(("metal_rack", "crate")), along, depth, side)

    back = OPPOSITE[front]
    rear_depth = frame.depth - 1
    if mechanic:
        put("counter_2", frame.length // 2, rear_depth, back)
    for along, role in ((max(1, frame.length // 4), "metal_rack"),
                        (min(frame.length - 2, 3 * frame.length // 4), "crate")):
        put(role, along, rear_depth, back)
    return True


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
    # A wide supermarket has more than one till open.
    tills_wanted = 2 if spec.get("tills", 1) > 1 and frame.length >= 16 else 1
    tills = 0
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
            tills += 1
            if tills >= tills_wanted:
                break

    # A service counter along the back wall - the deli, the pharmacist's, the
    # butcher's - with the staff's tile behind it and the customers' in front.
    service = spec.get("back_counter")
    if service and frame.length >= 10 and frame.depth >= 9 and service in C.FURNITURE:
        orient = L._facing(service, back_to)
        done = False
        # As long a counter as the back wall's doors leave room for.
        for span in (min(6, frame.length // 3), 4, 3):
            for start in [frame.length - span - 1, 1] + list(range(2, frame.length - span - 1)):
                spots = [frame.xy(start + k, frame.depth - 3) for k in range(span)]
                if all(_fits(plan, idx, service, x, y, orient, blocked | placed)
                       for x, y in spots):
                    for x, y in spots:
                        put(service, x, y, orient)
                    placed.update(frame.xy(start + k, d) for k in range(-1, span + 1)
                                  for d in (frame.depth - 2, frame.depth - 4))
                    done = True
                    break
            if done:
                break

    # Along the walls. Each wall is walked tile by tile, fitting one piece after
    # another so they stand in a line.
    def fill_wall(side: str, roles: list[str]):
        if not roles:
            return
        # Coolers are not shelves: one kind, side by side along the wall, as in
        # a real shop, then the rest of the wall is shelving.
        coolers = [r for r in roles if is_cooler(r)]
        roles = [r for r in roles if not is_cooler(r)]
        bank_role = rng.choice(coolers) if coolers else None
        line = sorted((c for c in cells if L._room_at(plan, c[0] + STEP[side][0], c[1] + STEP[side][1]) != idx),
                      key=lambda c: (c[0], c[1]))
        on_wall = set(line)
        ix, iy = STEP[OPPOSITE[side]]

        def put_on_wall(role, x, y, orient) -> bool:
            # A cooler is opened, and a shelf is browsed, from the tile in
            # front of it: that tile must be this room's floor, and it stays
            # free - no drinks machine in front of a fridge door, no fridge
            # facing the wall of a notch in the outline.
            front = [(cx + ix, cy + iy) for cx, cy in L._cells_for(role, x, y, orient)]
            if any(c not in cells or c in placed for c in front):
                return False
            if not put(role, x, y, orient):
                return False
            placed.update(front)
            return True
        bank_left = (len(line) if not roles else round(len(line) * BANK_SHARE)) if bank_role else 0
        k = 0
        i = 0
        while i < len(line):
            x, y = line[i]
            if bank_left <= 0 and not roles:
                break
            role = bank_role if bank_left > 0 else roles[k % len(roles)]
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
            if all(c in on_wall for c in L._cells_for(role, x, y, orient)) and \
                    put_on_wall(role, x, y, orient):
                if role == bank_role and bank_left > 0:
                    bank_left -= len(C.FURNITURE[role][orient])
                else:
                    k += 1
                i += len(C.FURNITURE[role][orient])
            else:
                i += 1

    # A shop too narrow for rows keeps its fridges along a side wall as well,
    # or it is one kind of shelf from the door to the back.
    narrow = frame.length < 2 + ROW_EVERY + 2
    sides = [s for s in STEP if s not in (front, back_to)]
    for side in STEP:
        if side == front:
            continue
        if side == back_to:
            fill_wall(side, spec["back"])
        elif narrow and sides and side == sides[0]:
            # A few fridges and then shelves, not one fridge the whole length.
            fill_wall(side, spec["back"][:2] + spec["wall"] * 3)
        else:
            fill_wall(side, spec["wall"])

    # Rows back from the front, starting two tiles in from each side wall and
    # leaving the front and back free to walk along.
    row_role = spec["rows"]
    every = BOOKCASE_ROW_EVERY if row_role == "bookcases" else ROW_EVERY
    orient_row = "W" if frame.along_x else "N"
    # Bookcases stand back to back in pairs and are left alone; every other
    # shop draws each row, and each stretch of a row, from its mix.
    # A clothes rack stands against a wall, never out in the floor: the middle
    # of a clothes shop is tables of folded stock, as in a real one.
    if row_role in RACKS:
        row_role = "shop_shelf_wood"
    mix = [r for r in (spec.get("aisles") or [row_role]) if r in C.FURNITURE and r not in RACKS]
    mix = mix or [row_role]
    row_starts = list(range(2, frame.length - 2, every))
    if row_role == "shop_display":
        # Cases are a deli counter, not a floor of aisles: a row or two.
        row_starts = row_starts[::max(1, len(row_starts) // max(1, frame.length // 12))][:MAX_CASE_ROWS]
    for a in row_starts:
        lines = [(a, "E" if frame.along_x else "S"), (a + 1, "W" if frame.along_x else "N")] \
            if row_role == "bookcases" else [(a, orient_row)]
        if any(a2 > frame.length - 3 for a2, _ in lines):
            continue
        for a2, orient in lines:
            role = "bookshelf" if row_role == "bookcases" else rng.choice(mix)
            # Where the row breaks for a cross aisle, and how far along it
            # changes what it holds: both staggered, so a big shop is not a
            # grid of identical squares.
            cross_at = CROSS_AISLE_EVERY + rng.randint(-2, 3)
            change_at = rng.randint(4, 9)
            d = 4
            since_cross = 0
            since_change = 0
            while d < frame.depth - 2:
                if since_cross >= cross_at:
                    d += 2
                    since_cross = 0
                    cross_at = CROSS_AISLE_EVERY + rng.randint(-2, 3)
                    continue
                if row_role != "bookcases" and since_change >= change_at:
                    role = rng.choice(mix)
                    since_change = 0
                    change_at = rng.randint(4, 9)
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
                    since_change += size
                else:
                    d += 1

    # A place to sit and read, in the front corner away from the till.
    if spec.get("nook") and frame.length >= 12 and frame.depth >= 7:
        for a in (frame.length - 5, 3):
            parts = [("chair", frame.xy(a - 1, 3)), ("chair", frame.xy(a + 1, 3)),
                     ("round_table", frame.xy(a, 3))]
            sides = ["W" if frame.along_x else "N", "E" if frame.along_x else "S", "N"]
            if all(_fits(plan, idx, role, x, y, L._facing(role, side), blocked | placed)
                   for (role, (x, y)), side in zip(parts, sides)):
                for (role, (x, y)), side in zip(parts, sides):
                    put(role, x, y, L._facing(role, side), ring=(role == "round_table"))
                break

    # Just inside the shop front: mannequins in a clothes shop's window, a
    # drinks machine, produce stands. A mannequin looks out at the street;
    # everything else stands with its back to the front and faces the shop -
    # a drinks machine turned to the window shows the shop its back.
    front_roles = spec.get("front") or []
    stands = bool(front_roles) and all(r == "shop_bin" for r in front_roles)
    wanted = (min(MAX_STANDS, frame.length // 3) if stands else FRONT_PIECES) if front_roles else 0
    queue = [front_roles[n % len(front_roles)] for n in range(wanted)]
    aside: list[str] = []
    # Fresh produce in a shop that is not a grocery: a few stands of it.
    queue += ["shop_bin"] * spec.get("produce", 0)
    for a in range(1, frame.length - 1, 2 if stands or not front_roles else 3):
        if not queue:
            break
        role = queue[0]
        side = back_to if role.startswith("mannequin") else front
        orient = L._facing(role, side)
        if orient != side:
            queue.pop(0)            # no sprite that way round: leave it out
            if role.startswith("vending"):
                aside.append(role)
            continue
        x, y = frame.xy(a, 1)
        if put(role, x, y, orient):
            queue.pop(0)
    # The game draws drinks machines facing east and south only, so a shop
    # fronting south or east cannot stand one at its window facing in. It gets
    # one against a west or north wall instead, as near the front as there is
    # room, rather than none.
    for role in aside[:1]:
        # nearest the front first: its step points out through the front wall
        fx, fy = STEP[front]
        spots = sorted(cells, key=lambda c: (-(c[0] * fx + c[1] * fy), c))
        for x, y in spots:
            o = next((o for o in ("W", "N")
                      if o in C.FURNITURE[role]
                      and (x + STEP[o][0], y + STEP[o][1]) not in cells
                      and (x - STEP[o][0], y - STEP[o][1]) in cells), None)
            if o and put(role, x, y, o):
                break
    return True


OFFICE_DESKS = ["desk", "desk_dark", "desk_long", "desk_long_pale"]


# Workstations stand a tile apart along a row, and the rows a tile of aisle
# apart; the room's edge is left a tile clear to walk round.
STATION_GAP = 1
STATION_AISLE = 1


def pack_stations(plan, idx: int, room, group, occupied: set, keep_clear: set,
                  keeps_open=None, gap: int = STATION_GAP,
                  aisle: int = STATION_AISLE):
    """Copies of `group` - [(role, dx, dy, orient)] - in rows across the room,
    stepping round the walkway and doorways, leaving the room's edge clear when
    that still holds some and its walls otherwise. Returns the rows as
    [row_y, x, x, ...] of the group's anchors, and the group's measures
    (gx0, gy0, gw, gh, pieces)."""
    L = _layout()
    pieces = [(role, dx, dy, L._facing(role, o)) for role, dx, dy, o in group]
    shape = [(dx + cx, dy + cy) for role, dx, dy, o in pieces
             for cx, cy in L._cells_for(role, 0, 0, o)]
    gx0, gy0 = min(x for x, _ in shape), min(y for _, y in shape)
    gw = max(x for x, _ in shape) - gx0 + 1
    gh = max(y for _, y in shape) - gy0 + 1
    solid = {(dx + cx, dy + cy) for role, dx, dy, o in pieces
             if C.FURNITURE_LAYERS.get(role, "Furniture") == "Furniture"
             for cx, cy in L._cells_for(role, 0, 0, o)}

    def clear(ox: int, oy: int) -> bool:
        cells = {(ox + x, oy + y) for x, y in shape}
        if any(L._room_at(plan, x, y) != idx or (x, y) in occupied for x, y in cells):
            return False
        return not ({(ox + x, oy + y) for x, y in solid} & keep_clear)

    def station_at(ox: int, oy: int) -> bool:
        mine = {(ox + x, oy + y) for x, y in solid}
        if not clear(ox, oy) or (keeps_open and not keeps_open(mine)):
            return False
        for role, dx, dy, o in pieces:
            plan.furniture.append((role, ox + dx, oy + dy, o))
        occupied.update((ox + x, oy + y) for x, y in shape)
        return True

    def lay(margin: int, shift: int, commit: bool):
        x_lo, x_hi = room.x0 + margin, room.x1 - margin
        y_lo, y_hi = room.y0 + margin, room.y1 - margin
        pitch = gw + gap
        slack = (x_hi - x_lo + 1 + gap) % pitch
        out = []
        oy = y_lo + shift - gy0
        while oy + gy0 + gh - 1 <= y_hi:
            row = []
            ox = x_lo + slack // 2 - gx0
            while ox + gx0 + gw - 1 <= x_hi:
                if (station_at(ox, oy) if commit else clear(ox, oy)):
                    row.append(ox)
                    ox += pitch
                else:
                    ox += 1
            if row:
                out.append([oy] + row)
            oy += gh + aisle
        return out

    def pack(margin: int):
        best = max(range(gh + aisle),
                   key=lambda sh: sum(len(r) - 1 for r in lay(margin, sh, False)))
        return lay(margin, best, True)

    rows = pack(1) or pack(0)
    return rows, (gx0, gy0, gw, gh, pieces)


def furnish_office(plan, idx: int, room, rng: random.Random, occupied: set,
                   keep_clear: set, keeps_open=None) -> tuple[list[str], bool]:
    """Workstations across the floor, a filing cabinet or a plant in the gaps
    between them. Returns what is left for the walls, and whether the floor
    was fitted out (a room too small for a desk in the open is not, and is
    furnished from its walls like any other)."""
    L = _layout()
    desk = rng.choice(OFFICE_DESKS)
    long_desk = len(C.FURNITURE[desk]["N"]) == 3
    group = [(desk, 0, 1, "S"), ("office_chair", 1 if long_desk else 0, 0, "N")]
    cabinet = rng.choice(["filing_cabinet", "filing_cabinet_pale"])
    plant = "plant"
    rows, (gx0, gy0, gw, gh, pieces) = pack_stations(
        plan, idx, room, group, occupied, keep_clear, keeps_open)
    if not rows:
        # Too small for a desk in the open: one against the wall, as before.
        walls = [desk, "office_chair", cabinet, cabinet, "water_cooler", "whiteboard",
                 plant, cabinet, "corkboard", "bookshelf"]
        return walls, False

    def put_extra(role: str, x: int, y: int, orient: str) -> bool:
        got = _fits(plan, idx, role, x, y, orient, occupied | keep_clear)
        if got is None or (keeps_open and not keeps_open(set(got))):
            return False
        plan.furniture.append((role, x, y, orient))
        occupied.update(got)
        return True

    # Between neighbours on a row, on the desk's line a filing cabinet and on
    # the chair's line a plant, and a cabinet at the end of the row.
    desk_dy = pieces[0][2]
    chair_dy = pieces[1][2]
    for oy, *xs in rows:
        for c, ox in enumerate(xs):
            gap = ox + gx0 + gw
            if c % 2 == 0:
                put_extra(cabinet, gap, oy + desk_dy, L._facing(cabinet, "S"))
            elif c % 3 == 1:
                put_extra(plant, gap, oy + chair_dy, "N")
    return ["water_cooler", "whiteboard", "corkboard", "bookshelf", cabinet, plant], True


# A classroom's desks face the board. Students sit at a table two wide with a
# chair to each place, in rows with an aisle between; what is left of the
# walls is bookshelves and a teacher's desk.
CLASS_DESK = [("dining_table", 0, 0, "W"), ("chair", 0, 1, "S"), ("chair", 1, 1, "S")]
_TURNED = {"W": "N", "N": "W", "E": "S", "S": "E"}


def furnish_classroom(plan, idx: int, room, rng: random.Random, occupied: set,
                      keep_clear: set, keeps_open=None) -> tuple[list[str], bool]:
    group = CLASS_DESK
    if (room.x1 - room.x0) < (room.y1 - room.y0):
        # A tall room faces its board on the west wall: the rows turn with it.
        group = [(role, dy, dx, _TURNED[o]) for role, dx, dy, o in group]
    rows, _measures = pack_stations(plan, idx, room, group, occupied, keep_clear,
                                    keeps_open, gap=1, aisle=1)
    if not rows:
        return ["whiteboard", "table", "chair", "chair", "desk", "bookshelf", "shelf"], False
    return ["whiteboard", "desk", "office_chair", "bookshelf", "bookshelf", "shelf"], True


SALON_TILES_PER_CHAIR = 25


def furnish_salon(plan, idx: int, room, rng: random.Random, occupied: set,
                  no_go: set, keeps_open=None) -> list[str]:
    """Hairdresser's chairs out in the floor, and wash basins along the back
    wall each with a commercial counter beside it. Returns what is left for
    the walls: mirrors and a plant, no bookcases."""
    L = _layout()
    cells = _cells(plan, idx, room)
    front = _front_side(plan, idx, cells, None)
    frame = Frame(cells, front)
    back = OPPOSITE[front]
    # The back wall: a basin, then a counter, then a basin. A wall with doors
    # down it has room for one basin or none, so the side walls get a turn.
    basin = rng.choice([s for s in ("sink", "sink_cream") if s in C.FURNITURE] or ["sink"])

    def wash_wall(frame, back) -> int:
        run = [basin if n % 2 == 0 else "shop_counter" for n in range(frame.length)]
        basins = 0
        for a, role in enumerate(run):
            x, y = frame.xy(a, frame.depth - 1)
            orient = L._facing(role, back)
            got = _fits(plan, idx, role, x, y, orient, no_go | occupied)
            if got is None or (keeps_open and not keeps_open(set(got))):
                continue
            plan.furniture.append((role, x, y, orient))
            occupied.update(got)
            basins += role == basin
        return basins

    washed = wash_wall(frame, back)
    for f in (f for f in ("N", "S", "E", "W") if f != front and f != OPPOSITE[front]):
        if washed >= 2:
            break
        washed += wash_wall(Frame(cells, f), OPPOSITE[f])
    # Styling stations: a salon chair a step out from a mirror on the wall,
    # facing it, side by side along a north or west wall (the walls a
    # mirror hangs on). The chairs used to stand in rows in the open floor,
    # office chairs turned to the basins.
    chair = "salon_chair" if "salon_chair" in C.FURNITURE else "office_chair"
    want = max(2, room.area // SALON_TILES_PER_CHAIR)
    chairs = 0
    for wall in ("W", "N"):
        if wall in (front, back):
            continue
        sx, sy = STEP[OPPOSITE[wall]]
        for i, (x, y) in enumerate(_against(plan, idx, cells, wall)[1:-1]):
            if chairs >= want:
                continue
            if (x, y) in occupied or (x + sx, y + sy) in occupied:
                continue
            if not _put(plan, idx, chair, x + sx, y + sy, OPPOSITE[wall], occupied, no_go,
                        keeps_open):
                continue
            occupied.add((x, y))             # the station's own step to the mirror
            _hang(plan, idx, "mirror", x, y, wall)
            chairs += 1
    # Where no side wall takes them: in rows across the floor, as before.
    for d in range(frame.depth - 3, 1, -3):
        for a in range(2, frame.length - 1, 3):
            if chairs >= want:
                break
            x, y = frame.xy(a, d)
            chairs += _put(plan, idx, chair, x, y, L._facing(chair, back), occupied, no_go,
                           keeps_open)
    # A hood dryer for a big salon, against a wall.
    if chairs >= 3 and "hair_dryer" in C.FURNITURE:
        for side in (back, "W", "N", "E", "S"):
            if side != front and any(
                    _put(plan, idx, "hair_dryer", x, y, side, occupied, no_go, keeps_open)
                    for x, y in _against(plan, idx, cells, side)[1:-1]):
                break
    return ["mirror", "plant"]


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
    # Every kitchen in a town had the same steel double sink and every
    # bathroom the same white basin, which is what reads as institutional.
    # Vanilla spreads across nine sets; these are the ones whose facings we
    # could confirm off the map itself.
    "sink": ["sink", "sink_cream"],
    "kitchen_sink": ["kitchen_sink", "kitchen_sink_steel", "kitchen_sink_dark"],
}


def palette(rng: random.Random, profile=None) -> dict[str, str]:
    """Role -> the role this home uses for it."""
    def choose(options, weight):
        return rng.choices(options, weights=[weight(option) for option in options], k=1)[0]

    sofa_sets = [s for s in SOFA_SETS if s[0] in C.FURNITURE and s[1] in C.FURNITURE]
    if profile:
        sofa, armchair = choose(sofa_sets, lambda pair: (
            profile.furniture_weight(pair[0]) + profile.furniture_weight(pair[1])) / 2)
    else:
        sofa, armchair = rng.choice(sofa_sets)
    out = {"sofa": sofa, "armchair": armchair}
    for role, options in CHOICES.items():
        options = [o for o in options if o in C.FURNITURE]
        pick = choose(options, profile.furniture_weight) if profile else rng.choice(options)
        out[role] = pick
    # Both beds of a pair and both wardrobes follow the one choice.
    out["double_bed_alt"] = out["double_bed"]
    out["bed_alt"] = out["bed"]
    out["wardrobe2"] = out["wardrobe"]
    dressers = [o for o in CHOICES["dresser"] if o in C.FURNITURE]
    out["dresser_alt"] = (choose(dressers, profile.furniture_weight)
                           if profile else rng.choice(dressers))
    return out


# A home's wooden furniture is all one wood. The palette above picks the
# wardrobe, dresser and beds on their own, and the bookcase, tables and
# bedside chest were the same for everyone, so one bedroom had a black table,
# dark dressers and a pale bookcase. A house gets one wood throughout; a
# block of flats one per flat. Each kind of piece maps to the one in this
# home's wood; a kind a wood has no piece for is left as it is.
#
# A piece only changes to one of the same height (the game's Surface), or a
# lamp stood on it floats or sinks: a bedside chest is a 34 chest of drawers
# in every wood, never the 15 low table furniture_storage_01 also has.
TONE_KIND = {
    **{r: "wardrobe" for r in CHOICES["wardrobe"]},
    **{r: "dresser" for r in CHOICES["dresser"]},
    "nightstand": "nightstand",
    "bookshelf": "bookshelf", "shelf_1": "bookshelf", "shelf_2": "bookshelf",
    **{r: "double_bed" for r in CHOICES["double_bed"]},
    **{r: "bed" for r in CHOICES["bed"]},
    "coffee_table": "low_table", "sidetable": "low_table",
    "dining_table": "dining_table",
    # The mirrored vanity is light wood: in any other home it is that home's
    # chest of drawers, the same height.
    "vanity": "vanity",
}
TONES = {
    "white": {"wardrobe": "wardrobe", "dresser": "dresser", "nightstand": "dresser",
              "vanity": "dresser",
              "bookshelf": "shelf_2", "low_table": "low_table_white",
              "dining_table": "dining_table_white",
              # No bed is white: a painted room has the black metal frame.
              "double_bed": "double_bed_black", "bed": "bed"},
    "light": {"wardrobe": "wardrobe_tan", "dresser": "dresser_tan", "nightstand": "nightstand",
              "bookshelf": "shelf_2", "low_table": "low_table_tan",
              "dining_table": "dining_table_oak", "double_bed": "double_bed_alt", "bed": "bed_alt"},
    "dark": {"wardrobe": "wardrobe_pale", "dresser": "dresser_alt", "nightstand": "dresser_alt",
             "vanity": "dresser_alt",
             "bookshelf": "bookshelf", "double_bed": "double_bed", "bed": "bed_plain"},
    "black": {"wardrobe": "wardrobe_black", "dresser": "dresser_black",
              "nightstand": "dresser_black", "low_table": "low_table_black",
              "vanity": "dresser_black",
              "double_bed": "double_bed_black", "bed": "bed",
              # The game has no black bookcase: a black chest of drawers on
              # the same tile instead of a dark one in a black room.
              "bookshelf": "dresser_black"},
}
# Dark wood is drawn twice as often as each of the others.
TONE_WEIGHTS = {"white": 1, "light": 1, "dark": 2, "black": 1}
# A table looks the same from any side, so it may take whichever of the new
# piece's sprites fits where the old one stood.
_TONE_ANY_SIDE = {"low_table", "dining_table"}


def _in_tone(role: str, x: int, y: int, orient: str, tone: dict) -> tuple | None:
    """(role, orient) of the piece in this wood that fits on the old one's
    tiles, or None to leave it."""
    kind = TONE_KIND.get(role)
    new = tone.get(kind)
    if not new or new == role or new not in C.FURNITURE:
        return None
    cells = _layout()._cells_for
    under = set(cells(role, x, y, orient))
    sides = [orient] + ([o for o in C.FURNITURE[new] if o != orient]
                        if kind in _TONE_ANY_SIDE else [])
    for side in sides:
        if side in C.FURNITURE[new] and set(cells(new, x, y, side)) <= under:
            return new, side
    return None


def one_wood(building, rng: random.Random) -> None:
    """Every home in `building` furnished in one wood: the whole building if
    it is a house, each flat of a block of flats."""
    L = _layout()
    tones: dict = {}
    for lvl, plan in enumerate(building.storeys):
        if plan.kind not in L.HOME_KINDS:
            continue
        flats = plan.kind == "apartment"
        out = []
        for role, x, y, orient in plan.furniture:
            room = plan.grid[y][x] if 0 <= y < plan.height and 0 <= x < plan.width else 0
            unit = plan.rooms[room - 1].unit if room else 0
            got = None
            if role in TONE_KIND and not (flats and not unit):
                key = (lvl, unit) if flats else None
                if key not in tones:
                    tones[key] = TONES[rng.choices(list(TONE_WEIGHTS),
                                                   weights=list(TONE_WEIGHTS.values()))[0]]
                got = _in_tone(role, x, y, orient, tones[key])
            out.append((got[0], x, y, got[1]) if got else (role, x, y, orient))
        plan.furniture = out


def bed_against_wall(plan, idx: int, room, slots, occupied: set, door_tiles: set,
                     bed: str, side_table: str | None, keeps_open=None) -> bool:
    """A bed with its head to a wall and a bedside table on each side, on the
    longest stretch of inside wall that takes it. A spot or a bedside table
    that keeps_open(tiles) refuses is skipped."""
    L = _layout()
    by_side: dict[str, list] = {}
    for x, y, facing in slots:
        by_side.setdefault(facing, []).append((x, y))
    order = sorted(by_side, key=lambda s: (any(not L._room_at(plan, x + STEP[s][0], y + STEP[s][1])
                                                for x, y in by_side[s]), -len(by_side[s])))
    has_tables = side_table and side_table in C.FURNITURE

    def table_fits(fx, fy, t_or, taken):
        tc = L._cells_for(side_table, fx, fy, t_or)
        return all(c not in taken and c not in door_tiles and L._room_at(plan, *c) == idx
                   for c in tc) and (keeps_open is None or keeps_open(tc))

    # Every spot that takes the bed, in order of preference, and then the
    # first with room for a table each side, else one, else none: the first
    # spot that took the bed was often in a corner with no room beside it,
    # and a bed with a table each side was one in five.
    spots = []
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
            # A row of floor at the foot of the bed, or it wall-to-walls a
            # narrow bedroom and the far side of the room cannot be reached.
            dx, dy = {"N": (0, 1), "S": (0, -1), "W": (1, 0), "E": (-1, 0)}[side]
            foot = {(cx + dx, cy + dy) for cx, cy in got} - set(got)
            if any(c in occupied or L._room_at(plan, *c) != idx for c in foot):
                continue
            if keeps_open and not keeps_open(got):
                continue
            if side in ("N", "S"):
                flank = [(ax - 1, y), (ax + w + 1, y)]
            else:
                flank = [(x, ay - 1), (x, ay + h + 1)]
            t_or = L._facing(side_table, side) if has_tables else None
            fits = 0
            if has_tables and t_or == side:
                taken = occupied | set(got) | foot
                fits = sum(table_fits(fx, fy, t_or, taken) for fx, fy in flank)
            spots.append((fits, bed, ax, ay, orient, got, foot, flank, t_or))
            if fits == 2:
                break
        if spots and spots[-1][0] == 2:
            break
    if not spots:
        return False
    best = max(range(len(spots)), key=lambda i: (spots[i][0], -i))
    _fits_n, bed, ax, ay, orient, got, foot, flank, t_or = spots[best]
    plan.furniture.append((bed, ax, ay, orient))
    occupied.update(got)
    occupied.update(foot)
    # A bedside table with no sprite for this wall is left out rather than
    # drawn facing its own back; the bed still gets its wall.
    if has_tables and t_or == orient:
        for fx, fy in flank:
            if table_fits(fx, fy, t_or, occupied):
                plan.furniture.append((side_table, fx, fy, t_or))
                occupied.update(L._cells_for(side_table, fx, fy, t_or))
    return True


# Eating places. A dining room was chairs pushed against its walls - in a
# narrow shop, a corridor of chairs - and the kitchen behind a pizzeria a
# home kitchen. Knox County's own are booth sets and tables with their chairs,
# a counter across the back, and a kitchen of steel counters, commercial
# ovens, a griddle and fryers.
# The food court is a dining room the size of a car park, ringed by the
# kitchens that serve it - 1,601 tiles of it in Knox County's mall.
DINING_ROOMS = {"restaurantdining", "italianrestaurant", "chineserestaurant", "restaurant",
                "cafe", "icecream", "bar", "foodcourt"}
# A booth, its table and the facing booth, as the game's own set lays them.
BOOTH_SETS = {
    "diner": [("diner_booth", 0, 0, "W"), ("diner_table", 0, 1, "W"), ("diner_booth", 0, 2, "E")],
    "pizza": [("pizza_booth", 0, 0, "W"), ("pizza_table", 0, 1, "W"), ("pizza_booth", 0, 2, "E")],
}
TABLE_SET = [("dining_table", 1, 1, "W"), ("chair", 0, 1, "W"), ("chair", 3, 1, "E"),
             ("chair", 1, 0, "N"), ("chair", 2, 2, "S")]
SMALL_TABLE_SET = [("round_table", 1, 0, "W"), ("chair", 0, 0, "W"), ("chair", 2, 0, "E")]
# The counter across the back of the room, by style: (pieces left to right).
BACK_COUNTERS = {
    "diner": ["diner_counter", "diner_counter", "diner_counter", "diner_counter"],
    "pizza": ["pizza_display", "pizza_counter", "pizza_counter"],
    "tables": ["counter_2", "counter_2", "counter_2"],
    "cafe": ["shop_display", "counter_1", "counter_1"],
    "bar": ["counter_4", "counter_4", "counter_4", "counter_4", "counter_4"],
    "icecream": ["shop_freezer", "shop_counter", "shop_counter", "shop_freezer"],
}
# What a commercial kitchen is fitted with, set into steel counters.
KITCHEN_KIT = {
    "pizzakitchen": ["oven_commercial", "oven_commercial", "hot_counter", "shop_fridge_double",
                     "kitchen_sink", "dishwasher", "metal_rack"],
    "burgerkitchen": ["griddle", "fryer", "fryer", "oven_steel", "shop_fridge_double",
                      "kitchen_sink", "dishwasher", "metal_rack"],
    "dinerkitchen": ["griddle", "fryer", "oven_steel", "oven_steel_alt", "shop_fridge_double",
                     "kitchen_sink", "dishwasher", "metal_rack"],
    "cafekitchen": ["oven_steel", "shop_fridge_double", "kitchen_sink", "dishwasher", "metal_rack"],
    "bakerykitchen": ["oven_commercial", "oven_commercial", "hot_counter", "kitchen_sink",
                      "metal_rack", "crate"],
    "icecreamkitchen": ["shop_freezer", "shop_freezer", "kitchen_sink", "metal_rack"],
}
DEFAULT_KITCHEN_KIT = ["oven_steel", "oven_steel_alt", "griddle", "fryer", "shop_fridge_double",
                       "kitchen_sink", "dishwasher", "metal_rack"]
COMMERCIAL_KITCHENS = {"restaurantkitchen", "pizzakitchen", "burgerkitchen", "dinerkitchen",
                       "chinesekitchen", "sushikitchen", "mexicankitchen", "seafoodkitchen",
                       "cafekitchen", "bakerykitchen", "icecreamkitchen"}
# Tiles along a wall per booth set or table set, with the gap to the next.
WALL_SET_EVERY = 4
MIN_CENTRE_SIDE = 6


def eatery_style(plan, idx: int, room) -> str:
    """How a dining room is fitted: from the kitchen it serves."""
    if room.kind in ("cafe", "bar", "icecream"):
        return room.kind
    L = _layout()
    near = {plan.rooms[j - 1].kind for j in L._neighbours(plan).get(idx, {})}
    if "pizzakitchen" in near:
        return "pizza"
    if near & {"dinerkitchen", "burgerkitchen"}:
        return "diner"
    return "tables"


MIN_PACK_SIDE = 4


def _pack_sets(plan, idx: int, frame, group, occupied: set, blocked: set,
               keeps_open=None) -> int:
    """As many of a seating set as the floor holds, a tile of aisle between
    one set and the next but the aisle shared, so a dining room is rows of
    booths and not three sets with a ring of floor round each. Filled from the
    back of the room, so the way in stays open."""
    L = _layout()
    pieces = [(role, dx, dy, L._facing(role, o)) for role, dx, dy, o in group]
    shape = [(dx + cx, dy + cy) for role, dx, dy, o in pieces
             for cx, cy in L._cells_for(role, 0, 0, o)]
    solid = [(dx + cx, dy + cy) for role, dx, dy, o in pieces
             if C.FURNITURE_LAYERS.get(role, "Furniture") == "Furniture"
             for cx, cy in L._cells_for(role, 0, 0, o)]
    ring = {(x + i, y + j) for x, y in shape for i in (-1, 0, 1) for j in (-1, 0, 1)} - set(shape)
    spot = {frame.xy(a, d): (a, d) for a in range(frame.length) for d in range(frame.depth)}
    origins = sorted(spot, key=lambda c: (-spot[c][1], abs(spot[c][0] - frame.length / 2), c))
    aisle: set = set()
    n = 0
    for ox, oy in origins:
        cells = [(ox + x, oy + y) for x, y in shape]
        if any(L._room_at(plan, *c) != idx or c in occupied or c in blocked or c in aisle
               for c in cells):
            continue
        if keeps_open and not keeps_open({(ox + x, oy + y) for x, y in solid}):
            continue
        for role, dx, dy, o in pieces:
            plan.furniture.append((role, ox + dx, oy + dy, o))
        occupied.update(cells)
        aisle.update((ox + x, oy + y) for x, y in ring)
        n += 1
    return n


def _wall_sets(plan, idx: int, room, group, placed_cells: set, blocked: set) -> int:
    """Sets stood against a long wall one after another, leaving the rest of a
    narrow room as the aisle."""
    L = _layout()
    along_x = room.w >= room.h
    # Laid along x the set is turned so its length runs along the wall.
    pieces = group if not along_x else [(r, dy, dx, L._TURN[o]) for r, dx, dy, o in group]
    pieces = [(r, dx, dy, L._facing(r, o)) for r, dx, dy, o in pieces]
    cells_of = [(dx + cx, dy + cy) for r, dx, dy, o in pieces for cx, cy in L._cells_for(r, 0, 0, o)]
    span = max(x for x, _ in cells_of) + 1 if along_x else max(y for _, y in cells_of) + 1
    n = 0
    start = room.x0 if along_x else room.y0
    end = room.x1 if along_x else room.y1
    depth = max(y for _, y in cells_of) + 1 if along_x else max(x for x, _ in cells_of) + 1
    # Against one long wall, then the other if the room is wide enough to
    # keep an aisle between them.
    across = room.h if along_x else room.w
    walls = [room.y0 if along_x else room.x0]
    if across >= 2 * depth + 2:
        walls.append((room.y1 if along_x else room.x1) - depth + 1)
    for wall in walls:
        t = start
        while t + span - 1 <= end:
            ox, oy = (t, wall) if along_x else (wall, t)
            cells = [(ox + x, oy + y) for x, y in cells_of]
            if all(L._room_at(plan, *c) == idx and c not in placed_cells and c not in blocked
                   for c in cells):
                for r, dx, dy, o in pieces:
                    plan.furniture.append((r, ox + dx, oy + dy, o))
                placed_cells.update(cells)
                n += 1
                t += WALL_SET_EVERY
            else:
                t += 1
    return n


def furnish_dining(plan, idx: int, room, rng: random.Random, occupied: set,
                   keep_clear: set, door_tiles: set, street: str | None,
                   keeps_open=None) -> list[str]:
    """Fit out a dining room, café or bar. Returns what is left for the walls."""
    L = _layout()
    style = eatery_style(plan, idx, room)
    cells = _cells(plan, idx, room)
    # The doorways and the tile either side of each: a small café cannot give
    # a whole ring of floor to every door.
    blocked = set(keep_clear) | set(door_tiles)
    for x, y, d in plan.doors:
        blocked |= {(x - 1, y), (x + 1, y)} if d == "N" else {(x, y - 1), (x, y + 1)}

    # The counter across the back, away from the street door.
    front = _front_side(plan, idx, cells, street)
    frame = Frame(cells, front)
    counter = BACK_COUNTERS.get(style, BACK_COUNTERS["tables"])
    counter = [c for c in counter if c in C.FURNITURE]
    def lay_counter(frame, back) -> bool:
        depth = frame.depth - 1
        if not counter or frame.depth < 5:
            return False
        # An unbroken run: the back wall has doors to the kitchen and
        # storerooms, so the whole run goes where there is clear wall, nearest
        # the middle, and a shorter one when there is none that long.
        run = None
        shorter = []
        for n in range(len(counter), 1, -1):
            for roles in (counter[:n], counter[-n:]):
                if roles not in shorter:
                    shorter.append(roles)
        for roles in shorter:
            n = len(roles)
            for start in sorted(range(frame.length - n + 1),
                                key=lambda s0: abs(s0 + n / 2 - frame.length / 2)):
                a, used, laid = start, set(), []
                for role in roles:
                    x, y = frame.xy(a, depth)
                    orient = L._facing(role, back)
                    got = _fits(plan, idx, role, x, y, orient, blocked | occupied | used)
                    if got is None:
                        laid = None
                        break
                    laid.append((role, x, y, orient))
                    used.update(got)
                    a += len(got)
                if laid:
                    run = (start, a, laid, used)
                    break
            if run:
                break
        if not run:
            return False
        start, a, laid, used = run
        plan.furniture.extend(laid)
        occupied.update(used)
        # Room behind the counter to stand, and in front to queue.
        occupied.update(frame.xy(a2, depth - 1) for a2 in range(start - 1, a + 1))
        return True

    # Across from the street door; failing that along a side wall, as a
    # back wall with doors all down it has no stretch long enough.
    sides = [front] + [f for f in ("N", "S", "E", "W")
                       if f != front and f != OPPOSITE[front]]
    for f in sides:
        if lay_counter(frame if f == front else Frame(cells, f), OPPOSITE[f]):
            break

    # Seating: sets out in the floor where there is room for an aisle all
    # round, else against the long wall.
    if style in BOOTH_SETS:
        group = BOOTH_SETS[style]
    elif style in ("cafe", "icecream", "bar"):
        group = SMALL_TABLE_SET
    else:
        group = TABLE_SET
    group = [g for g in group if g[0] in C.FURNITURE]
    placed = 0
    if min(room.w, room.h) >= MIN_PACK_SIDE:
        placed = _pack_sets(plan, idx, frame, group, occupied, blocked, keeps_open)
    if not placed:
        placed = _wall_sets(plan, idx, room, group, occupied, blocked)
    if not placed:
        # Too small even for that: one small table and its chairs.
        L._place_group(plan, idx, room, [g for g in SMALL_TABLE_SET if g[0] in C.FURNITURE],
                       1, occupied, set(door_tiles), keeps_open)
    return ["plant", "painting", "plant"]


# ---- trades with a layout of their own --------------------------------------
#
# Bars, laundromats, gyms and churches used to get the generic wishlist round
# the walls: a bar with three shelves and a painting, a church with two chairs
# and a table. Each is laid out here the way the trade is, from pieces read off
# the game's own tiles (tools/game_pieces.py). A function returns what is left
# for the walls, or None when the room is too small, and the room is then
# furnished the old way.

def _against(plan, idx: int, cells: set, side: str) -> list[tuple[int, int]]:
    """This room's tiles with a wall on `side`, in order along that wall."""
    L = _layout()
    dx, dy = STEP[side]
    tiles = [(x, y) for x, y in cells if L._room_at(plan, x + dx, y + dy) != idx]
    return sorted(tiles, key=lambda t: (t[0], t[1]) if side in ("N", "S") else (t[1], t[0]))


def _put(plan, idx, role, x, y, orient, occupied: set, no_go: set, keeps_open=None) -> bool:
    if role not in C.FURNITURE or orient not in C.FURNITURE[role]:
        return False
    got = _fits(plan, idx, role, x, y, orient, no_go | occupied)
    if got is None or (keeps_open and not keeps_open(set(got))):
        return False
    plan.furniture.append((role, x, y, orient))
    occupied.update(got)
    return True


def _hang(plan, idx, role, x, y, wall: str) -> bool:
    """A wall piece on (x, y) against `wall`, unless something hangs there."""
    L = _layout()
    if wall not in ("N", "W") and role in L.NORTH_WEST_ONLY:
        return False
    edge = L._wall_edge(x, y, wall)
    if edge in plan.wall_pieces or role not in C.FURNITURE:
        return False
    plan.furniture.append((role, x, y, L._facing(role, wall)))
    plan.wall_pieces.add(edge)
    return True


BAR_MIN_TILES = 30


def furnish_bar(plan, idx: int, room, rng: random.Random, occupied: set, no_go: set,
                keeps_open=None) -> list[str] | None:
    """The bar along the back: bottle shelves on the wall, a step for whoever
    serves, the counter open at both ends, and stools along its front. A pool
    table in the floor if there is room for it and the players, a jukebox and
    an arcade cabinet against the walls."""
    cells = _cells(plan, idx, room)
    if len(cells) < BAR_MIN_TILES:
        return None
    front = _front_side(plan, idx, cells, None)
    frame = Frame(cells, front)
    back = OPPOSITE[front]
    if frame.depth < 6 or frame.length < 5:
        return None
    d_shelf, d_counter, d_stool = frame.depth - 1, frame.depth - 3, frame.depth - 4
    counters = 0
    for a in range(1, frame.length - 1):
        x, y = frame.xy(a, d_counter)
        counters += _put(plan, idx, "bar_counter", x, y, back, occupied, no_go, keeps_open)
    if counters < 2:
        return None
    for a in range(1, frame.length - 1):
        _put(plan, idx, "bar_shelf", *frame.xy(a, d_shelf), back, occupied, no_go, keeps_open)
        # The serving step stays floor.
        occupied.add(frame.xy(a, frame.depth - 2))
    for a in range(1, frame.length - 1, 2):
        _put(plan, idx, "bar_stool", *frame.xy(a, d_stool), front, occupied, no_go, keeps_open)
    # A pool table needs a cue's length round it: a clear ring of two.
    if frame.depth >= 11 and frame.length >= 7:
        orient = "N" if frame.along_x else "W"
        for a in range(2, frame.length - 3):
            x, y = frame.xy(a, 3)
            ring = {(x + dx, y + dy) for dx in range(-2, 4) for dy in range(-2, 4)}
            if all(c in cells and c not in occupied and c not in no_go for c in ring) \
                    and _put(plan, idx, "pool_table", x, y, orient, occupied, no_go, keeps_open):
                occupied.update(ring)
                break
    for role in ("jukebox", "arcade"):
        done = False
        for side in ("N", "W", "E", "S"):
            if done or side == front or side not in C.FURNITURE.get(role, {}):
                continue
            done = any(_put(plan, idx, role, x, y, side, occupied, no_go, keeps_open)
                       for x, y in _against(plan, idx, cells, side)[1:-1])
    return ["plant", "painting"]


def furnish_laundromat(plan, idx: int, room, rng: random.Random, occupied: set, no_go: set,
                       keeps_open=None) -> list[str] | None:
    """Washers down one long wall and dryers down the other, a folding table
    in the middle, a chair or two to wait on."""
    cells = _cells(plan, idx, room)
    if len(cells) < 20:
        return None
    long_a = max(STEP, key=lambda s: len(_against(plan, idx, cells, s)))
    placed = 0
    for side, role in ((long_a, "coin_washer"), (OPPOSITE[long_a], "coin_dryer")):
        fx, fy = STEP[OPPOSITE[side]]
        for x, y in _against(plan, idx, cells, side):
            front = (x + fx, y + fy)
            if front in occupied or front not in cells:
                continue
            if _put(plan, idx, role, x, y, side, occupied, no_go, keeps_open):
                occupied.add(front)      # its door opens onto the floor
                placed += 1
    if placed < 3:
        return None
    return ["table", "chair", "chair", "plant", "shelf"]


def furnish_gym(plan, idx: int, room, rng: random.Random, occupied: set, no_go: set,
                keeps_open=None) -> list[str] | None:
    """Treadmills in a row facing a mirrored wall, weight machines in rows
    behind them with room to step round each."""
    cells = _cells(plan, idx, room)
    if len(cells) < 30:
        return None
    # Mirrors on a north or west wall, the treadmills facing it.
    wall = max(("N", "W"), key=lambda s: len(_against(plan, idx, cells, s)))
    line = _against(plan, idx, cells, wall)
    for x, y in line[1:-1]:
        _hang(plan, idx, "mirror", x, y, wall)
    # A treadmill is drawn facing west or north only: it stands with its
    # back to the east or south, running towards the mirrors.
    run_orient = "E" if wall == "W" else "S"
    sx, sy = STEP[OPPOSITE[wall]]
    machines = 0
    for i, (x, y) in enumerate(line[1:-1]):
        if i % 2 == 0:
            machines += _put(plan, idx, "treadmill", x + sx, y + sy, run_orient, occupied,
                             no_go, keeps_open)
    weights = [w for w in ("weight_machine", "weight_machine_alt") if w in C.FURNITURE]
    frame = Frame(cells, wall)
    for d in range(5, frame.depth - 1, 3):
        for a in range(1, frame.length - 1, 3):
            x, y = frame.xy(a, d)
            machines += _put(plan, idx, rng.choice(weights), x, y, wall, occupied, no_go,
                             keeps_open)
    if machines < 2:
        return None
    return ["shelf", "plant", "water_cooler"]


def furnish_church(plan, idx: int, room, rng: random.Random, occupied: set, no_go: set,
                   keeps_open=None) -> list[str] | None:
    """The altar at the far end from the door, and pews in rows facing it
    either side of an aisle down the middle."""
    cells = _cells(plan, idx, room)
    if len(cells) < 30:
        return None
    door = _front_side(plan, idx, cells, None)
    # The altar faces the door when it can; the game draws it facing south
    # or east only, so where the far wall is a south or east one it goes on
    # a north or west wall instead and the pews turn to face it.
    altars = C.FURNITURE.get("altar", {})
    back = OPPOSITE[door]
    if back not in altars:
        back = next((w for w in ("N", "W") if w in altars and w != door), back)
    front = OPPOSITE[back]
    frame = Frame(cells, front)
    if frame.length < 9 or frame.depth < 7:
        return None
    mid = frame.length // 2
    if back in altars:
        _put(plan, idx, "altar", *frame.xy(mid, frame.depth - 2), back, occupied, no_go,
             keeps_open)
    else:
        _put(plan, idx, "table", *frame.xy(mid, frame.depth - 2),
             "N" if frame.along_x else "W", occupied, no_go, keeps_open)
    # Pews have their backs to the door and face the altar: three seats each,
    # an aisle down the middle and along both walls.
    pews = 0
    for d in range(2, frame.depth - 4, 2):
        for a0 in (mid - 4, mid + 2):
            if a0 < 1 or a0 + 2 > frame.length - 2:
                continue
            x, y = min(frame.xy(a0 + k, d) for k in range(3))
            pews += _put(plan, idx, "pew", x, y, front, occupied, no_go, keeps_open)
    if pews < 2:
        return None
    return ["plant", "painting", "shelf"]


# ---- who lives here -----------------------------------------------------------
#
# A home's rooms used to be the same whoever lived in them. A household is
# drawn once per home (per flat, or per house: the building's own seed, so
# every storey agrees) and changes what its rooms hold: a child's room gets a
# poster and, with a brother or sister, a bunk bed; a teenager's a desk and
# posters instead of a plant and a picture; an older couple's living room a
# second armchair and plants.

FAMILY_SHARE = {None: 0.55, "house": 0.55, "apartment": 0.35}
RETIRED_SHARE = 0.18
# An older building has more of its first owners still in it.
RETIRED_OLD_BUILDING = 0.14
OLD_BUILDING_YEARS = 40
TEEN_SHARE = 0.45
SIBLINGS_SHARE = 0.4
# A family with a baby: the first child's room that is not the teenager's
# gets a cot instead of a bed.
BABY_SHARE = 0.25
# A bunk bed and room to climb into it.
BUNK_MIN_TILES = 12
# A bedroom this small in a family home is a child's.
CHILD_ROOM_MAX_TILES = 14


def household(rng: random.Random, plan) -> dict:
    """{"kind": "family" | "retired" | "adults", "teen": bool, "siblings": bool}."""
    age = getattr(plan.profile, "age", 0) or 0
    retired = RETIRED_SHARE + (RETIRED_OLD_BUILDING if age >= OLD_BUILDING_YEARS else 0)
    roll = rng.random()
    family = FAMILY_SHARE.get(plan.kind, 0.3)
    kind = "family" if roll < family else "retired" if roll < family + retired else "adults"
    return {"kind": kind, "teen": kind == "family" and rng.random() < TEEN_SHARE,
            "siblings": kind == "family" and rng.random() < SIBLINGS_SHARE,
            "baby": kind == "family" and rng.random() < BABY_SHARE}


def for_household(base: list[str], room, home: dict, kid_rooms: dict,
                  rng: random.Random) -> list[str]:
    """The room's wishlist for who lives there."""
    posters = list(getattr(C, "POSTERS", ()))
    kind = room.kind
    if home["kind"] == "retired":
        if kind == "livingroom":
            return base + ["armchair", "plant", "plant"]
        return base
    if home["kind"] != "family":
        return base
    child = kind == "kidsbedroom" or (kind == "bedroom" and room.area <= CHILD_ROOM_MAX_TILES)
    if not child:
        return base
    nth = kid_rooms.get(room.unit, 0)
    kid_rooms[room.unit] = nth + 1
    out = list(base)
    if home["teen"] and nth == 0:
        # The eldest's room: a desk to work at, and posters on the walls.
        out = [r for r in out if r not in ("plant", "painting")]
        out += ["desk", "office_chair"] + ([rng.choice(posters), rng.choice(posters)] if posters else [])
        return out
    if home.get("baby") and not home.get("cot") and "crib" in C.FURNITURE:
        home["cot"] = True
        out = ["crib" if r in ("bed", "double_bed") else r for r in out]
    elif home["siblings"] and room.area >= BUNK_MIN_TILES and "bunk_bed" in C.FURNITURE:
        out = ["bunk_bed" if r in ("bed", "double_bed") else r for r in out]
    if posters:
        out = [rng.choice(posters) if r == "painting" else r for r in out]
    return out


# The small things a home has, measured over the houses of Muldraugh, West
# Point, Riverside and Rosewood: a waste bin in 24% of kitchens and 8% of
# bathrooms, a coffee maker in 13% of kitchens and a toaster in 10%, a small
# mirror over the basin in about one bathroom in five. Each is a share of
# rooms, so not every kitchen is the same kitchen.
KITCHEN_BIN = 0.3
BATHROOM_BIN = 0.15
COFFEE_MAKER = 0.35
TOASTER = 0.25
KITCHEN_CLOCK = 0.3
BASIN_MIRROR = 0.5
LIVING_RADIO = 0.3
# A bedroom's second chest is a mirrored vanity this often (TONES makes it
# the home's own chest where the home is not light wood).
VANITY = 0.3
# What a toaster or a coffee maker stands on (Surface 34, as they need).
WORKTOPS = ("counter",)


def extras(base: list[str], room, rng: random.Random) -> list[str]:
    """A home room's wishlist with its vanity."""
    if room.kind == "bedroom" and rng.random() < VANITY:
        return ["vanity" if r == "dresser_alt" else r for r in base]
    return base


def dress_room(plan, idx: int, room, rng: random.Random, door_edges: set,
               no_go: set, keeps_open) -> None:
    """Small things on what the room already has: a coffee maker and a
    toaster on the worktop and a clock on the wall above it, a mirror over
    the basin, a radio on a living room chest. The one thing on the floor is
    a waste bin, and only on a square against a wall that keeps_open allows:
    on the wishlist it took the wall an essential wanted, and the clear-up
    threw out six more sinks, stoves and counters."""
    L = _layout()
    mine = [f for f in plan.furniture if L._room_at(plan, f[1], f[2]) == idx]
    topped = {(x, y) for role, x, y, _o in mine
              if L._needs_surface(role) and not L._is_wall_piece(role)}
    walls = set(door_edges)
    for role, x, y, o in plan.furniture:
        if L._is_wall_piece(role):
            walls |= {L._wall_edge(cx, cy, o) for cx, cy in L._cells_for(role, x, y, o)}

    def free(starts):
        return [(x, y, o) for role, x, y, o in mine
                if role.startswith(starts) and (x, y) not in topped]

    def stand(item, spots) -> None:
        spots = [s for s in spots if s[2] in C.FURNITURE.get(item, {})]
        if spots:
            x, y, o = rng.choice(spots)
            plan.furniture.append((item, x, y, o))
            topped.add((x, y))

    def hang(item, spots) -> None:
        spots = [s for s in spots if s[2] in C.FURNITURE.get(item, {})
                 and L._wall_edge(*s) not in walls]
        if spots:
            x, y, o = rng.choice(spots)
            plan.furniture.append((item, x, y, o))
            walls.add(L._wall_edge(x, y, o))

    def bin_spot() -> None:
        taken = {c for role, x, y, o in plan.furniture
                 if L._blocks(role) and L._room_at(plan, x, y) == idx
                 for c in L._cells_for(role, x, y, o)}
        spots = [(x, y) for y in range(room.y0, room.y1 + 1)
                 for x in range(room.x0, room.x1 + 1)
                 if plan.grid[y][x] == idx and (x, y) not in taken
                 and (x, y) not in no_go and not L._narrow(plan.grid, x, y)
                 and any(L._room_at(plan, x + dx, y + dy) != idx
                         for dx, dy in STEP.values())]
        rng.shuffle(spots)
        for x, y in spots:
            if keeps_open is None or keeps_open([(x, y)]):
                plan.furniture.append(("bin", x, y, "N"))
                return

    if room.kind in ("kitchen", "openplan"):
        if rng.random() < KITCHEN_BIN:
            bin_spot()
        worktop = [(x, y, o) for role, x, y, o in mine if role.startswith(WORKTOPS)]
        if rng.random() < COFFEE_MAKER:
            stand("coffee_maker", free(WORKTOPS))
        if rng.random() < TOASTER:
            stand("toaster", free(WORKTOPS))
        if rng.random() < KITCHEN_CLOCK:
            hang("clock", worktop)
    elif room.kind == "bathroom":
        if rng.random() < BATHROOM_BIN:
            bin_spot()
        if rng.random() < BASIN_MIRROR and not any(f[0].startswith("mirror") for f in mine):
            hang("mirror_small", [(x, y, o) for role, x, y, o in mine if L._is_sink(role)])
    elif room.kind == "livingroom" and rng.random() < LIVING_RADIO:
        # Every chest in a living room is there to hold a lamp or the
        # television, so the radio takes the place of a second lamp.
        lamps = [n for n, f in enumerate(plan.furniture)
                 if f[0] == "lamp" and L._room_at(plan, f[1], f[2]) == idx]
        if len(lamps) >= 2:
            n = rng.choice(lamps)
            _role, x, y, o = plan.furniture[n]
            plan.furniture[n] = ("radio", x, y, o)
