"""Shops, restaurants, filling stations: the sales floor and the back rooms."""
from __future__ import annotations

import random
from .core import MAX_DEPTH, MIN_ROOM, MIN_SPLIT, Plan, Room, _split
from .openings import _outside_runs
from .dwellings import _neighbours
from .houses import CIRCULATION, ROOMS_PER_HALL, _more_halls



SHOP_BACK_ROOMS = ["storage", "office", "storage"]
# A shop's back rooms take this share of its depth, within these many tiles.
SHOP_BACK_SHARE = 0.3
SHOP_BACK_TILES = (3, 7)
MIN_SALES_DEPTH = 8
# A sales floor bigger than this is cut into sections, as a department store
# or a mall is: each about this big, none narrower than the minimum, and
# deeper floors cut into rows of them as well as columns.
SECTION_TILES = 450
MIN_SECTION_WIDTH = 12
SECTION_DEPTH = 22


def _grid(length: int, depth: int) -> tuple[list[int], list[int]]:
    """Column widths along the street and row depths back from it for a sales
    floor `length` by `depth`; one of each for a floor small enough to stay whole."""
    n = round(length * depth / SECTION_TILES)
    rows = max(1, min(round(depth / SECTION_DEPTH), n // 2))
    cols = min(max(1, round(n / rows)), length // MIN_SECTION_WIDTH)
    if rows * cols < 2:
        return [length], [depth]

    def cut(total, parts):
        base, extra = divmod(total, parts)
        return [base + (i < extra) for i in range(parts)]
    return cut(length, cols), cut(depth, rows)


# A petrol station's shop is small and has its back rooms all the same: the
# toilets and the stockroom are what a station is required to have.
GAS_BACK_TILES = (3, 5)
GAS_MIN_SALES_DEPTH = 5


def _shop_rooms(plan: Plan, rng: random.Random, street: str | None,
                gas: bool = False) -> list[int]:
    """A shop's ground floor as one sales floor the width of the shop front,
    and a strip of back rooms behind it: stockroom, office, toilet.

    Cut up like a house, a supermarket was eight rooms of 24 tiles, and the
    one that became the shop was a corridor four tiles wide with nothing but
    a shelf along each wall. A sales floor too big for one shop is cut into
    sections, each its own shop; returns the numbers of the sales rooms.
    """
    w, h = plan.width, plan.height
    side = street if street in ("N", "S", "W", "E") else ("S" if w >= h else "E")
    total = h if side in ("N", "S") else w
    lo, hi = GAS_BACK_TILES if gas else SHOP_BACK_TILES
    back = max(lo, min(hi, round(total * SHOP_BACK_SHARE)))
    if total - back < (GAS_MIN_SALES_DEPTH if gas else MIN_SALES_DEPTH):
        plan.rooms.append(Room(0, 0, w - 1, h - 1))
        return [len(plan.rooms)]
    if side == "S":
        sales, strip = (0, back, w - 1, h - 1), (0, 0, w - 1, back - 1)
    elif side == "N":
        sales, strip = (0, 0, w - 1, h - 1 - back), (0, h - back, w - 1, h - 1)
    elif side == "E":
        sales, strip = (back, 0, w - 1, h - 1), (0, 0, back - 1, h - 1)
    else:
        sales, strip = (0, 0, w - 1 - back, h - 1), (w - back, 0, w - 1, h - 1)
    x0, y0, x1, y1 = sales
    along_x = side in ("N", "S")
    cols, rows = _grid(x1 - x0 + 1 if along_x else y1 - y0 + 1,
                       y1 - y0 + 1 if along_x else x1 - x0 + 1)
    # Rows run back from the street: the one on the street first.
    far_first = side in ("S", "E")
    sections = []
    back_at = (y0 if along_x else x0)
    for depth in (rows[::-1] if far_first else rows):
        at = x0 if along_x else y0
        for width in cols:
            plan.rooms.append(Room(at, back_at, at + width - 1, back_at + depth - 1) if along_x
                              else Room(back_at, at, back_at + depth - 1, at + width - 1))
            sections.append(len(plan.rooms))
            at += width
        back_at += depth
    _split(*strip, rng, MAX_DEPTH, plan.rooms, target_area=max(16, back * 8),
           mask=plan.mask, small=[True])
    return sections
MIN_SHOP_ROOM = 16


def _fit_out_sections(plan: Plan, rng: random.Random, sections: list[int],
                      uses: list | None) -> None:
    """The sections that are not on the street are shops as well, not back
    rooms: a department store's far end is as much sales floor as its front.
    With no known use each section is a different kind of shop while the kinds
    last, as in a mall, not four general stores in a row."""
    from .. import interiors
    if uses:
        for i in sections:
            if plan.rooms[i - 1].kind not in interiors.STORES:
                plan.rooms[i - 1].kind = uses[0][0]
        return
    kinds = list(interiors.STORE_WEIGHTS)
    rng.shuffle(kinds)
    for n, i in enumerate(sections):
        plan.rooms[i - 1].kind = kinds[n % len(kinds)]
    adj = _neighbours(plan)
    for i, room in enumerate(plan.rooms, 1):
        if room.kind == "grocerystorage" and not any(
                plan.rooms[j - 1].kind == "grocery" for j in adj.get(i, ())):
            room.kind = "storage"


def _dining_sections(plan: Plan, sections: list[int], dining: str, kitchen: str) -> None:
    """A restaurant too big for one dining room has several, and a kitchen
    behind each out of the back rooms. Cut as a shop, its second section
    became the kitchen: in Piqua 510 squares of floor with a stove in one
    corner, beside a dining room the same size."""
    adj = _neighbours(plan)
    back = [j for j, r in enumerate(plan.rooms, 1) if j not in sections
            and not r.is_core and not r.is_shaft and r.kind != "bathroom"]
    kitchens: list[int] = []
    for i in sections:
        near = [j for j in adj.get(i, {}) if j in back and j not in kitchens]
        if near:
            kitchens.append(max(near, key=lambda j: plan.rooms[j - 1].area))
    if not kitchens and back:
        kitchens.append(max(back, key=lambda j: plan.rooms[j - 1].area))
    if not kitchens:
        return          # no back room to cook in: keep the shop's cut
    for i in sections:
        plan.rooms[i - 1].kind = dining
    for j in kitchens:
        plan.rooms[j - 1].kind = kitchen


def _assign_shop_floor(plan: Plan, rng: random.Random, street: str | None,
                       uses: list[tuple[str, str]] | None, several: bool) -> None:
    """A commercial ground floor: what is on the street in front, what serves
    it behind.

    The rooms with an outside wall on the street (or on any side, when the
    street is not known) and floor enough become the fronts, taken along the
    street. Each takes the next of the building's real uses
    (knoxbuild/uses.py) - the pizza place's dining room, the bank hall - and
    a room behind it becomes that use's back room: the pizza kitchen, the
    stockroom. A block of flats with more shop fronts than known uses fills
    the rest with shops of the usual kinds; the remaining back rooms are
    storerooms, an office and a toilet.
    """
    from .. import interiors
    rooms = [(i, r) for i, r in enumerate(plan.rooms, 1) if not r.is_core and not r.is_shaft]
    if not rooms:
        return
    uses = list(uses or [])

    def street_wall(i):
        n = 0
        for side, wall in _outside_runs(plan, i):
            if street is None or side == street:
                n += len(wall)
        return n

    fronts = [ir for ir in rooms if street_wall(ir[0]) >= 3 and ir[1].area >= MIN_SHOP_ROOM]
    if not fronts:
        fronts = [max(rooms, key=lambda ir: ir[1].area)]
    if not several:
        fronts = [max(fronts, key=lambda ir: ir[1].area)]
    # Along the street, so the uses keep the order they were found in.
    fronts.sort(key=lambda ir: (ir[1].x0, ir[1].y0) if street in ("N", "S", None) else (ir[1].y0, ir[1].x0))
    adj = _neighbours(plan)
    taken = {i for i, _ in fronts}
    backs: list[tuple[int, str]] = []
    used_fronts: set[str] = set()
    for n, (i, r) in enumerate(fronts):
        if n < len(uses):
            front, back = uses[n]
        else:
            front = interiors.store_kind(rng)
            for _ in range(4):
                if front not in used_fronts:
                    break
                front = interiors.store_kind(rng)
            back = "grocerystorage" if front == "grocery" else "storage"
        used_fronts.add(front)
        r.kind = front
        backs.append((i, back))
    for i, back in backs:
        # The biggest room behind this front that nobody has yet.
        near = sorted((j for j in adj.get(i, {}) if j not in taken
                       and not plan.rooms[j - 1].is_core and not plan.rooms[j - 1].is_shaft),
                      key=lambda j: -plan.rooms[j - 1].area)
        if near:
            plan.rooms[near[0] - 1].kind = back
            taken.add(near[0])
    rest = sorted((ir for ir in rooms if ir[0] not in taken), key=lambda ir: -ir[1].area)
    for n, (i, r) in enumerate(rest):
        r.kind = SHOP_BACK_ROOMS[n % len(SHOP_BACK_ROOMS)]
    if len(rest) >= 2:
        rest[-1][1].kind = "bathroom"
    if any(front == "gasstore" for front, _back in uses):
        # A petrol station has toilets, one a side where there is room.
        back_rooms = [r for _i, r in rest]
        toilets = [r for r in back_rooms if r.kind == "bathroom"]
        spare = sorted((r for r in back_rooms if r.kind != "bathroom"), key=lambda r: r.area)
        want = 2 if len(back_rooms) >= 4 else 1
        for room in spare[:max(0, want - len(toilets))]:
            room.kind = "bathroom"


# At most one room of this kind per this many rooms on a floor. The fill list
# was cycled round-robin once the mix was spent, so every kind in it ended up
# with an equal share however silly that was: a school came out with 61
# lavatories and 58 offices to its 63 classrooms, a police station with seven
# locker rooms, and a church with as many storerooms as nave. A kind that has
# had its share is skipped and the next one in the list takes the room.
# One room in this many may be of that kind. A kind missing from here has no
# cap at all, which is how a police station came out 36% policeoffice: the
# fill fell through to it every time. Measured over Knox County's 13 buildings
# with a policeoffice in them, a station is 31% cells, 17% offices, 13% hall
# and 8% bathroom - so cells get the run of the place and offices do not.
ROOM_CAP_PER = {
    # A school has one library, one gym, one canteen and one janitor,
    # not one per six rooms: at a cap of 6 a 25-room floor came out with
    # four libraries. These are the rooms a building has exactly one of.
    "library": 20, "gym": 40, "kitchen": 40, "diningroom": 40,
    "lobby": 40, "schoollab": 10, "schoolstorage": 16,
    "sportstorage": 30,
    "bathroom": 10, "hall": 12,
    "breakroom": 15, "office": 10, "storage": 8, "garage": 15,
    "policeoffice": 6, "evidenceroom": 25,
    # A few cells, not a cell block: one room in eight at most, so a
    # 30-room station gets three or four rather than the eleven that a
    # cap of 3 gave it.
    "prisoncells": 8, "interrogationroom": 20, "policearchive": 30,
    "lobby_police": 30, "armory": 30, "lockerroom": 20,
    "policegunstorage": 30, "policeoutfitstorage": 30, "policelocker": 15,
    "policehall": 25, "firegarage": 12, "armystorage": 4, "medical": 4,
    # janitor: this was written twice, 40 among the rooms above and 18 here, and the
    # later one is the one that counted. Measured, the difference is small (a police
    # station averages 2.4 of them at 18 and 2.1 at 40, a school gets next to none
    # either way), so the live value stays rather than changing every existing map.
    "clinic": 4, "officestorage": 12, "janitor": 18,
    "security": 25,
    # A castle's chambers. Everything past the mix falls to the fill, and
    # bedroom was the only kind in the castle's with no cap, so it took every
    # room a bigger keep had: 5% of a small one, 51% at the size the landmark
    # growth actually gives them, 63% at the largest. A barracks is unmoved -
    # its fill falls back to bedroom, which is what a dormitory block is.
    "bedroom": 4,
    # A ground has a few counters on the concourse, not a food hall: cafe was
    # the one kind in the stadium's fill with no cap and took 36% of a big
    # one once the rest were spent.
    "cafe": 10,
    # No mall is all one chain. Each unit kind takes a share of the units,
    # the way a fill kind without a cap took the whole of a big castle.
    "clothingstore": 8, "giftstore": 12, "toystore": 14, "bookstore": 14,
    "furniturestore": 14, "sportstore": 14, "departmentstore": 16,
    # No mall is all one chain, and Knox County's lets to about thirty
    # different trades: clothes 11 units, department 21, gift 3, toy 3, shoe
    # 1, jeweller 3, houseware 3. These keep any one of them to a share.
    "clothesstore": 9, "shoestore": 16, "electronicsstore": 18,
    "housewarestore": 16, "sewingstore": 30, "cornerstore": 30,
    "optometrist": 30, "jewelrystore": 16, "musicstore": 20,
    "candystore": 20, "toolstore": 20, "gunstore": 30, "pharmacy": 25,
    "bakery": 25, "foodcourt": 40, "clothesstorage": 12,
    "departmentstorage": 25, }


# How big each kind of room is in Knox County, in tiles. The mix used to be
# handed to rooms in size order, so whatever stood first in the list got the
# biggest room: a station's cells landed on its fifth-largest room and came
# out at 24 m2 against the game's 15, while its corridor got 36 against 51.
# Ordering the mix by these instead puts a cell on a small room and a hall on
# a big one. A kind that is not here keeps its place in the list.
ROOM_MEDIAN_AREA = {
    # Measured over every room of that name in Knox County, not estimated.
    # The first version of this table was guessed and several were far out: a
    # classroom is 24 m2 and had 48, a dining room 22 and had 55, a hall 27
    # and had 51, a closet 2 and had 6. _split_to_size cuts a room down to
    # these, so a wrong number here decides how big rooms actually come out.
    "library": 100, "gym": 88, "church": 110, "policehall": 51,
    "restaurant": 50, "corridor": 45,
    "policeoffice": 30, "office": 30, "livingroom": 29,
    # Knox County's classrooms are 24 m2 and its schools are a warren of
    # them. These are set higher on purpose: a school of a dozen big
    # rooms reads better than one of forty small ones, and _split_to_size
    # cuts a room down to these, so they are what decides it.
    "hall": 27, "lobby": 40, "classroom": 140, "secondaryclassroom": 140,
    "schoollab": 56, "diningroom": 60, "kitchen": 21,
    "policelocker": 24, "lockerroom": 24, "breakroom": 24, "storage": 20,
    "policegunstorage": 18, "policeoutfitstorage": 18, "policearchive": 18,
    "evidenceroom": 18, "armory": 18,
    "interrogationroom": 16, "bedroom": 15, "prisoncells": 15,
    "security": 15, "officestorage": 14, "janitor": 12,
    "bathroom": 6, "closet": 2,
}


def _by_expected_size(kinds: list[str]) -> list[str]:
    """The same kinds, biggest-roomed first, so they meet rooms of their size.

    Stable on anything ROOM_MEDIAN_AREA does not know, which keeps a list
    whose order was chosen for other reasons in the order it was written.
    """
    if not any(k in ROOM_MEDIAN_AREA for k in kinds):
        return kinds
    return sorted(kinds, key=lambda k: -ROOM_MEDIAN_AREA.get(k, 25))


# A room is cut down to its kind's size when it is this many times too big.
# Below that the spread is just how buildings are.
OVERSIZE = 1.6
# Rooms a building has one of. Splitting an oversized one in two gave a
# school four libraries and two gyms however hard the mix was capped,
# because _split_to_size copies the kind into both halves.
# Only these are cut down to their kind's size. The pass was written to
# stop a police cell coming out at 24 m2 when the game's are 15, and
# applying it to every kind quietly became what decided room size
# everywhere: it was shredding a school floor into halls of 43 m2 and
# offices of 48 however big the splitter had made them.
SHRINK_TO_KIND = {"prisoncells", "closet", "policelocker", "lockerroom",
                  "janitor", "officestorage"}
# How many rooms one oversized room may be cut into. In a big building every
# room is big, so a kind that is small everywhere is always oversized and was
# halved until it fit: two changing rooms in a 70x56 ground became sixteen,
# 39% of the building. A cell block of eight is still a cell block.
MAX_SPLIT_PIECES = 4
ONE_OF_A_KIND = {"library", "gym", "kitchen", "diningroom", "lobby",
                 "janitor", "schoollab", "interrogationroom", "armory",
                 "evidenceroom", "security", "breakroom"}


# A bathroom bigger than this keeps a bathroom's worth at one end and the
# rest becomes a store room. Churches, libraries, schools and fire stations
# had bathrooms of up to 95 tiles: a row of toilets along one wall of an
# empty tiled hall. A public toilet with its stalls fits in this.
BATHROOM_MAX_AREA = 30


def _trim_bathroom(plan: Plan, idx: int) -> None:
    """Cut an oversized bathroom down to BATHROOM_MAX_AREA, the rest storage."""
    r = plan.rooms[idx]
    if r.kind != "bathroom" or r.is_core or r.is_shaft or r.area <= BATHROOM_MAX_AREA:
        return
    if r.w >= r.h:
        keep = max(MIN_ROOM, BATHROOM_MAX_AREA // r.h)
        if r.w - keep < MIN_ROOM:
            return
        new = Room(r.x0 + keep, r.y0, r.x1, r.y1, kind="storage", unit=r.unit)
        r.x1 = new.x0 - 1
    else:
        keep = max(MIN_ROOM, BATHROOM_MAX_AREA // r.w)
        if r.h - keep < MIN_ROOM:
            return
        new = Room(r.x0, r.y0 + keep, r.x1, r.y1, kind="storage", unit=r.unit)
        r.y1 = new.y0 - 1
    cells = [(x, y) for y in range(new.y0, new.y1 + 1) for x in range(new.x0, new.x1 + 1)
             if plan.grid[y][x] == idx + 1]
    if len(cells) < MIN_ROOM * MIN_ROOM:
        # The building's outline leaves too little of it there: keep it whole.
        r.x1, r.y1 = new.x1, new.y1
        return
    plan.rooms.append(new)
    for x, y in cells:
        plan.grid[y][x] = len(plan.rooms)


def _split_to_size(plan: Plan, rng: random.Random) -> None:
    """Cut a room that is far bigger than its kind ever is into rooms of it.

    The splitter makes rooms of roughly one size, so a police station came out
    with every room near 34 m2 - which meant its cells were 24 m2 where Knox
    County's are 15, because there was no small room for a cell to be. Sizing
    the kinds afterwards cannot fix that; there has to be a cell block. Once
    the kind is known the room is halved until it is about the size that kind
    is, which turns one oversized cell into a row of them.

    Runs after the kinds are handed out and before the doors, so the doors are
    placed on the rooms that actually exist.
    """
    for idx in range(len(plan.rooms)):
        _trim_bathroom(plan, idx)
        room = plan.rooms[idx]
        want = ROOM_MEDIAN_AREA.get(room.kind)
        if (want is None or room.is_core or room.is_shaft
                or room.kind in ONE_OF_A_KIND
                or room.kind not in SHRINK_TO_KIND):
            continue
        queue = [idx]
        pieces = 1
        while queue:
            i = queue.pop()
            r = plan.rooms[i]
            if r.area < want * OVERSIZE or pieces >= MAX_SPLIT_PIECES:
                continue
            # Halve the long way, so a cell block comes out as a row.
            if r.w >= r.h:
                if r.w < MIN_SPLIT:
                    continue
                cut = r.x0 + r.w // 2
                new = Room(cut, r.y0, r.x1, r.y1, kind=r.kind, unit=r.unit)
                r.x1 = cut - 1
            else:
                if r.h < MIN_SPLIT:
                    continue
                cut = r.y0 + r.h // 2
                new = Room(r.x0, cut, r.x1, r.y1, kind=r.kind, unit=r.unit)
                r.y1 = cut - 1
            if min(r.w, r.h, new.w, new.h) < MIN_ROOM:
                # Put it back: the halves would be slivers.
                if new.x0 > r.x0:
                    r.x1 = new.x1
                else:
                    r.y1 = new.y1
                continue
            plan.rooms.append(new)
            pieces += 1
            at = len(plan.rooms)
            for y in range(new.y0, new.y1 + 1):
                for x in range(new.x0, new.x1 + 1):
                    if plan.grid[y][x] == i + 1:
                        plan.grid[y][x] = at
            queue.extend([i, at - 1])


def _assign_kinds(rooms: list[Room], mix: list[str], fill: list[str]) -> None:
    import collections as _c

    mix = _by_expected_size(mix)
    order = sorted(rooms, key=lambda r: -r.area)
    total = len(order)
    used: _c.Counter = _c.Counter()

    def spare(kind: str) -> bool:
        per = ROOM_CAP_PER.get(kind)
        return per is None or used[kind] < max(1, total // per)

    for i, room in enumerate(order):
        if room.fixed:
            continue        # the kind the mapper gave this room stands
        if i < len(mix):
            kind = mix[i]
        else:
            # Of the fill kinds that still have a share going, the one whose
            # rooms are this size in Knox County. Cycling the list instead
            # handed cells and cupboards whatever room came next, so a
            # station's cells averaged 24 m2 against the game's 15 while its
            # storerooms took the big ones.
            start = (i - len(mix)) % len(fill)
            ready = [fill[(start + k) % len(fill)] for k in range(len(fill))
                     if spare(fill[(start + k) % len(fill)])]
            if ready and any(k in ROOM_MEDIAN_AREA for k in ready):
                kind = min(ready, key=lambda k: abs(
                    ROOM_MEDIAN_AREA.get(k, 25) - room.area))
            else:
                # Every fill kind is spent. Carry on round the list from
                # where this room falls rather than dropping the whole
                # remainder on the first entry: a big building has far more
                # rooms than the mix and the caps together cover, and that
                # gave a stadium sixteen identical corridors and a castle a
                # floor of beds.
                kind = ready[0] if ready else fill[start]
        room.kind = kind
        used[kind] += 1
    # The smallest room makes a far more convincing bathroom than a hall. It
    # trades kinds with whatever the mix made the bathroom rather than adding
    # one, or a nine-room church came out with two lavatories in it. Fixed
    # rooms - drawn with a kind of their own - are neither moved into nor out
    # of: the smallest one the mix still owns takes the trade.
    swappable = [r for r in order if not r.fixed]
    if len(order) >= 3 and "bathroom" in mix and swappable \
            and swappable[-1].kind != "bathroom":
        swap = next((r for r in swappable if r.kind == "bathroom"), None)
        if swap is not None:
            swap.kind = swappable[-1].kind
        swappable[-1].kind = "bathroom"


# Buildings you walk through to get somewhere else. A school of classrooms
# wants a corridor and a police station wants one; a church does not, its nave
# being the way through, and nor does a warehouse or a shop floor. Only houses
# got circulation before this, so a school was classrooms opening into one
# another the way the bedrooms upstairs used to.
# A floor wants a corridor once it holds about this many rooms; below that
# the corridor is more of the building than the rooms it serves.
CORRIDOR_WORTH_IT = 8


NEEDS_CORRIDOR = {"school", "police", "civic", "medical", "fire", "fire_police",
                  "military", "library", "offices"}

# Pairs that belong together when both rooms fit on the floor. Shop and
# restaurant fronts already choose an adjacent back room in _assign_shop_floor.
BUSINESS_NEIGHBOURS = {
    "school": (("kitchen", "diningroom"), ("gym", "sportstorage"),
               ("gym", "lockerroom"), ("classroom", "schoollab"),
               ("office", "officestorage"), ("office", "breakroom")),
    "church": (("lobby", "church"), ("office", "storage")),
    "industrial": (("warehouse", "toolstore"), ("warehouse", "garage"),
                   ("office", "officestorage"), ("kitchen", "diningroom"),
                   ("lockerroom", "bathroom")),
    "barn": (("warehouse", "storage"), ("warehouse", "garage")),
    "military": (("kitchen", "bedroom"), ("armystorage", "office")),
    "castle": (("hall", "church"), ("hall", "kitchen")),
    "stadium": (("lockerroom", "sportstorage"), ("hall", "cafe")),
    "medical": (("clinic", "medical"), ("lobby", "office")),
    "civic": (("lobby", "office"), ("library", "storage")),
    "police": (("policeoffice", "interrogationroom"),
               ("policeoffice", "evidenceroom"), ("policelocker", "lockerroom")),
    "library": (("library", "storage"), ("lobby", "library")),
    "fire": (("firegarage", "firestorage"), ("kitchen", "bedroom")),
    "fire_police": (("firegarage", "firestorage"), ("policeoffice", "policelocker")),
    "offices": (("office", "officestorage"), ("office", "breakroom")),
}


def _arrange_business_rooms(plan: Plan, kind: str) -> None:
    """Improve related-room adjacency without changing the mix or circulation."""
    pairs = BUSINESS_NEIGHBOURS.get(kind, ())
    if not pairs:
        return
    adj = _neighbours(plan)
    rooms = plan.rooms

    def satisfied(pair):
        a, b = pair
        return any(rooms[i - 1].kind == a and
                   any(rooms[j - 1].kind == b for j in neighbours)
                   for i, neighbours in adj.items())

    for pair in pairs:
        if satisfied(pair):
            continue
        before = sum(satisfied(p) for p in pairs)
        done = False
        for i, room in enumerate(rooms, 1):
            if room.kind != pair[0]:
                continue
            for j in sorted(adj[i]):
                candidate = rooms[j - 1]
                if candidate.fixed or candidate.is_core or candidate.is_shaft or candidate.kind in CIRCULATION:
                    continue
                for other in rooms:
                    if (other.kind != pair[1] or other.fixed or other.is_core
                            or other.is_shaft or other.kind in CIRCULATION):
                        continue
                    if max(candidate.area, other.area) > 2 * min(candidate.area, other.area):
                        continue
                    candidate.kind, other.kind = other.kind, candidate.kind
                    if satisfied(pair) and sum(satisfied(p) for p in pairs) > before:
                        done = True
                        break
                    candidate.kind, other.kind = other.kind, candidate.kind
                if done:
                    break
            if done:
                break

MIN_SPECIAL_ROOMS = {
    "school": {"classroom": 1, "diningroom": 1, "kitchen": 1, "gym": 1, "library": 1},
    "police": {"policeoffice": 1, "policelocker": 1},
    "civic": {"office": 1, "lobby": 1},
    "medical": {"clinic": 1, "medical": 1},
    "fire": {"firegarage": 1},
    "fire_police": {"firegarage": 1, "policeoffice": 1, "policelocker": 1},
    "military": {"armystorage": 1},
    "library": {"library": 1},
    "offices": {"office": 1},
}


def _circulation(plan: Plan, rooms: list[Room]) -> int:
    """Rooms turned into halls until the rest all open onto one."""
    adj = _neighbours(plan)
    where = {id(r): i for i, r in enumerate(plan.rooms, 1)}
    protected = set()
    for kind, minimum in MIN_SPECIAL_ROOMS.get(plan.kind or "", {}).items():
        matches = sorted((r for r in rooms if r.kind == kind),
                         key=lambda r: -r.area)
        protected.update(id(r) for r in matches[:minimum])
    free = [where[id(r)] for r in rooms if (r.kind or "") not in CIRCULATION
            and id(r) not in protected]
    seeds = [where[id(r)] for r in rooms if (r.kind or "") in CIRCULATION]
    kinds: dict[int, str] = {}
    made = _more_halls(plan, adj, free, kinds, seeds,
                       len(free) // ROOMS_PER_HALL)
    for i, kind in kinds.items():
        plan.rooms[i - 1].kind = kind
    return made


# Kinds whose rooms are run together into one space rather than left as a row
# of separate corridors. Knox County's mall is one concourse of 5,855 tiles on
# the ground floor - a single room made of 62 rectangles - where ours was
# seven halls of about 300 tiles each, because the splitter's target caps
# every room in a building and a hall is no exception. A mall holds hundreds
# of people and the concourse is the reason it can.
MERGE_CIRCULATION: set[str] = set()
