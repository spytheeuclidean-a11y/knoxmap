"""Houses: room budgets by floor, wings, spare rooms, and the house mix."""
from __future__ import annotations

from ..sizing import SIZES
from ..sizing import capacity
from ..sizing import programme_for_house_floor
from ..sizing import split_by_targets
import random
from .core import HOUSE_OVERSIZE, Plan, Room, STAIR_RUN
from .openings import _room_at
from .malls import _renumber
from .dwellings import _graph_distance, _neighbours, _pieces, _too_small



# Knox County's houses (546 measured) have per house about 1.4 bedrooms, 0.4
# children's bedrooms, 0.5 closets and 0.2 laundries - and ours had three
# bedrooms and an office apiece, every spare room another bedroom. A room this
# small is a closet; the rest take turns down these lists.
# A room this size or under is a closet rather than a bedroom. It was 8,
# which no room can ever be: MIN_ROOM and MIN_SPLIT put the smallest room
# the splitter can make at 9 tiles, so the rule never once fired and Knox
# County's commonest small room - 5,397 closets - was one we never built.
SMALL_ROOM_TILES = 10
# Upstairs. The game's houses have 1.39 bedrooms and 0.42 children's rooms
# each; ours had 2.15 and 1.21, an upstairs of nothing but beds. A closet on
# the landing is what it really has - 0.50 a house, and none of ours had one.
# A separate dining room, in Knox County, is in 13% of houses.
DINING_ROOM_SHARE = 0.13
HOUSE_SLEEPING = ["bedroom", "kidsbedroom", "bedroom", "storage"]
# What is left of a floor once its bedrooms, its bathroom and its one office
# are dealt out. Everything past them used to become storage, which turned a
# fourteen-room house into five bedrooms and nine store cupboards - 2747
# storerooms in 200 houses against 321 before, and storage the commonest room
# in a house by three times over. These are the rooms a house has more than
# one of, and they are dealt round in turn.
HOUSE_SPARE = ["storage", "laundry", "office", "storage", "closet", "office"]
UPSTAIRS = ["bedroom", "kidsbedroom", "bedroom", "laundry",
            "bedroom", "office", "storage"]


def _footprint(plan: Plan) -> int:
    return (sum(sum(row) for row in plan.mask)
            if plan.mask is not None else plan.width * plan.height)


def _house_room_budgets(plan: Plan, levels: int) -> tuple[int, int]:
    floor_area = _footprint(plan) * max(1, levels)
    bedrooms = min(5, max(1, (floor_area + 89) // 90))
    bathrooms = 2 if floor_area >= 900 else 1
    return bedrooms, bathrooms


def _house_bedrooms_on_floor(bedrooms: int, levels: int, level: int) -> int:
    each, remainder = divmod(bedrooms, max(1, levels))
    return each + (level < remainder)


def _house_floor_bedrooms(bedrooms: int, levels: int, level: int) -> int:
    """A house's bedrooms on one floor: all of them in a bungalow, none on
    the ground floor of a house with an upstairs, the rest shared upstairs."""
    if levels <= 1:
        return bedrooms
    return _house_bedrooms_on_floor(bedrooms, levels - 1, level - 1) if level else 0


# Some two-storey houses keep a bedroom downstairs as well - for a guest or
# a grandparent - with a bathroom beside it, when the house has bedrooms
# enough upstairs and the ground floor room for both. All of them had one
# before bedrooms went upstairs; then none, and ground-floor bathrooms went
# with them (18 in 203 multi-storey houses to 5).
GROUND_BEDROOM_SHARE = 0.2
GROUND_EXTRA_TILES = 60


def _ground_bedroom(bedrooms: int, levels: int, floor: int,
                    rng: random.Random) -> bool:
    """Whether a house's ground floor keeps a bedroom of its own."""
    return (levels == 2 and bedrooms >= 2 and floor >= GROUND_EXTRA_TILES
            and rng.random() < GROUND_BEDROOM_SHARE)


def _house_spares(profile, rng: random.Random, upstairs: bool = False,
                  big: bool = False):
    """Rooms for a floor past its bedrooms, in turn: a study (or storage, by
    the household's _house_study_share), then storage and offices. The
    laundry is in the programme, the closets are the pieces a cut leaves.
    Only those: a house has a study and a store room, not a row of them, so
    past that an upper floor takes bedrooms, which are big enough to fill
    it, rather than filling with cupboards; a ground floor's rooms grow."""
    first = "office" if rng.random() < _house_study_share(profile) else "storage"
    yield first
    yield from (k for k in HOUSE_TOP_UP if k != first)
    if big:
        # A large house keeps its bedroom and bathroom budget; the extra
        # floor goes to a dining room and the rooms beside it.
        if not upstairs:
            yield "dining"
        # And past those, the rooms a big house really has more of, dealt
        # round: a floor of four hundred tiles is not seven rooms of sixty.
        while True:
            yield from BIG_HOUSE_FILL
    elif upstairs:
        yield from ("bedroom", "bedroom")


# A house floor cut by kind gets spare rooms while it is bigger than its
# rooms can fill (sizing.capacity: the big ones at their hi), so a big floor
# gets more rooms rather than a living room of 90 tiles - up to one room per
# HOUSE_ROOM_TILES of floor and HOUSE_MAX_SPARE spares.
HOUSE_ROOM_TILES = 22
HOUSE_MAX_SPARE = 40
# A floor this many tiles or more is a large house and takes more rooms of the
# kinds that fill a floor.
HOUSE_BIG_FLOOR = 260
# A house whose storeys add up to that much floor is a mansion: it takes the
# finishes and the dressing of an old, rich house rather than a bigger version
# of a small one. The same line, measured over the whole house, so two storeys
# of 130 count where one floor of 130 does not.
MANSION_FLOOR_TILES = HOUSE_BIG_FLOOR
# And the floors it lays: dark wood and red carpet underfoot, white tile in the
# wet rooms. A kind it does not list keeps the house's own floor. These are
# EXTRA_FLOORS names (tbx.floor_options).
MANSION_FLOORS = {
    "livingroom": ["wood_dark", "carpet_red", "carpet_blue"],
    "dining": ["wood_dark", "carpet_red"],
    "hall": ["wood_dark", "tile_white"],
    "office": ["wood_dark", "carpet_red"],
    "bedroom": ["carpet_red", "carpet_blue", "wood_dark"],
    "kidsbedroom": ["carpet_blue", "carpet_red"],
    "kitchen": ["tile_white", "tile_cream"],
    "bathroom": ["tile_white", "tile_cream"],
}
# On a floor that size the bedrooms still stay bedrooms, not suites: the wings
# give the other rooms the space.
BIG_FLOOR_BEDROOM_OVERSIZE = 1.2
HOUSE_TOP_UP = ["storage", "office"]
HOUSE_GROW_TRIES = 10
BIG_HOUSE_FILL = ["closet", "livingroom", "laundry", "office", "storage",
                  "office", "storage", "livingroom"]
# Rooms a cut may clip away: what is left of one is folded into the room
# beside it or kept as a closet. The hall too, unless it is the landing.
HOUSE_LOSABLE = {"hall", "laundry", *HOUSE_TOP_UP}
# What a too-big closet is called instead, smallest first.
CLOSET_GROWS_INTO = ("storage", "office")
# Shuffles of a programme cut as a whole box before it sheds a room, and of
# the bare programme before the floor falls back: a 3x3 bathroom lands
# clear of a turned footprint's corners only so often.
HOUSE_TRIES = 3
HOUSE_LAST_TRIES = 10
# A footprint filling less of its box than this - a turned or L-shaped
# house - is cut as it always was. The cut is drawn on the whole box, so
# every room the footprint does not clip came out the box's share of it:
# twice its size on a turned house, living rooms of 500 tiles.
HOUSE_MIN_FILL = 0.8


def _wall_shared(a, b, run: int = 2) -> bool:
    """Whether two rectangles (anything with x0 y0 x1 y1) share a wall of at
    least `run` tiles."""
    ox = min(a.x1, b.x1) - max(a.x0, b.x0) + 1
    oy = min(a.y1, b.y1) - max(a.y0, b.y0) + 1
    return ((ox >= run and (a.y1 + 1 == b.y0 or b.y1 + 1 == a.y0))
            or (oy >= run and (a.x1 + 1 == b.x0 or b.x1 + 1 == a.x0)))


# The rooms of a large house's day wing; the rest sleep.
_DAY_ROOMS = {"hall", "livingroom", "openplan", "kitchen", "dining", "laundry",
              "office", "storage"}


def _cut_in_wings(box, kinds: list[str], rng: random.Random, floor, core,
                  landing) -> list[Room] | None:
    """A big house floor cut in two wings, each with a hall of its own.

    One cut over four hundred tiles has to put every bedroom beside a hall,
    and cannot, so a large house came out as rooms that open into rooms. Two
    wings are two small houses side by side: the stairs and the day rooms in
    one, the bedrooms in the other, and the halls meet. Returns None when
    the floor will not split (the caller cuts it whole)."""
    from ..sizing import capacity
    rest = kinds[1:]
    day = [k for k in rest if k in _DAY_ROOMS]
    night = [k for k in rest if k not in _DAY_ROOMS]
    if len(day) < 2 or len(night) < 2:
        # Upstairs is all bedrooms: share them out, the second wing gets a hall.
        half = max(2, len(rest) // 2)
        day, night = rest[:half], rest[half:]
        if len(night) < 2:
            return None
    wing_a, wing_b = ["hall"] + day, ["hall"] + night
    # Split by what each wing can hold, not by its rooms' targets: a floor cut
    # in proportion to the targets gave a wing of three bedrooms the room of
    # five, and bedrooms of fifty tiles.
    ta = capacity(wing_a)
    tb = capacity(wing_b)
    x0, y0, x1, y1 = box
    wide = (x1 - x0) >= (y1 - y0)
    lo, hi = (x0, x1) if wide else (y0, y1)
    cut = lo + round((hi - lo + 1) * ta / (ta + tb))
    cut = min(max(cut, lo + 6), hi - 5)
    if core is not None:
        # The stairs stay in the first wing: the line goes past them, or in
        # front of them if that is nearer the ideal.
        c0, c1 = (core[0], core[2]) if wide else (core[1], core[3])
        if c0 < cut <= c1:
            cut = c1 + 1 if c1 + 1 <= hi - 5 else c0
    a_box = (x0, y0, cut - 1, y1) if wide else (x0, y0, x1, cut - 1)
    b_box = (cut, y0, x1, y1) if wide else (x0, cut, x1, y1)

    def tiles(b):
        return sum(1 for y in range(b[1], b[3] + 1) for x in range(b[0], b[2] + 1)
                   if floor[y][x])

    out = []
    for sub, wing in ((a_box, wing_a), (b_box, wing_b)):
        holds_core = core is not None and not (
            core[2] < sub[0] or core[0] > sub[2] or core[3] < sub[1] or core[1] > sub[3])
        got = split_by_targets(sub, wing, rng, area=tiles(sub),
                               touch=landing if holds_core else None)
        if got is None:
            return None
        out += got
    return out


def _house_by_kind(plan: Plan, level: int, levels: int,
                   rng: random.Random) -> list[Room] | None:
    """A house floor's rooms cut to its programme's sizes, kinds fixed.

    The whole box is cut, sized for the floor inside the walls, and kept
    only where every room keeps one piece of its kind's least floor inside
    the walls and clear of the stair shaft (painted over whatever is beneath
    it) - a bathroom the shaft lands on is not a bathroom - and none comes
    out far bigger than its kind. The hall is cut beside the stairs, so they
    arrive in it. A programme no cut fits sheds its extra rooms. None when
    the floor is too small, the footprint fills too little of its box, or
    nothing fits: the caller falls back to _split.
    """
    if _footprint(plan) < HOUSE_MIN_FILL * plan.width * plan.height:
        return None
    core = plan.core
    floor = [[(plan.mask is None or plan.mask[y][x])
              and not (core and core[0] <= x <= core[2] and core[1] <= y <= core[3])
              for x in range(plan.width)] for y in range(plan.height)]
    area = sum(map(sum, floor))
    kinds = programme_for_house_floor(area, level, levels, rng)
    if kinds is None:
        return None
    need = 5 if levels == 1 else 3      # rooms no floor of its kind goes without
    # An open-plan house has one room for living and cooking, cut as one.
    if level == 0 and rng.random() < _house_open_plan_share(plan.profile):
        kinds[kinds.index("livingroom")] = "openplan"
        kinds.remove("kitchen")
        need -= 1
    # A dining room as often as households have one (_house_dining_share).
    if (level == 0 and area >= (70 if levels == 1 else 45)
            and rng.random() < _house_dining_share(plan.profile)):
        kinds.append("dining")
    bedrooms, bathrooms = _house_room_budgets(plan, levels)
    quota = _house_floor_bedrooms(bedrooms, levels, level)
    spares = _house_spares(plan.profile, rng, level > 0, area >= HOUSE_BIG_FLOOR)
    beds = [i for i, k in enumerate(kinds) if k in ("bedroom", "kidsbedroom")]
    for i in beds[quota:]:     # past the house's bedroom budget
        kinds[i] = next(spares, "storage")
    spare = ["bedroom"] * (quota - len(beds))
    if level == 0:
        if _ground_bedroom(bedrooms, levels, area, rng):
            kinds += ["bedroom", "bathroom"]
        elif levels > 1 and bathrooms > levels - 1:
            spare.insert(0, "bathroom")
        if "laundry" not in kinds:
            spare.append("laundry")
    n = 0
    while (area > capacity(kinds)
           and n < HOUSE_MAX_SPARE and len(kinds) < area // HOUSE_ROOM_TILES):
        more = spare[n] if n < len(spare) else next(spares, None)
        if more is None:
            break
        kinds.append(more)
        n += 1
    box = (0, 0, plan.width - 1, plan.height - 1)
    landing = core if core is not None and kinds[0] == "hall" else None
    losable = HOUSE_LOSABLE - {"hall"} if landing else HOUSE_LOSABLE

    def keeps(room: Room) -> bool:
        ps = _pieces(room, floor)
        return bool(ps) and SIZES[room.kind].lo <= len(ps[0]) and not (
            _too_small(ps[0]) or (len(ps) > 1 and not _too_small(ps[1])))

    def _on_circulation(room: Room, rooms: list, core) -> bool:
        """A bedroom opens onto a hall, the stairs or the living room, else it
        is reached through another bedroom."""
        if room.kind not in ("bedroom", "kidsbedroom"):
            return True
        if core is not None:
            c = Room(*core)
            if _wall_shared(room, c):
                return True
        return any(o is not room and o.kind in ("hall", "livingroom", "openplan")
                   and _wall_shared(room, o) for o in rooms)

    # A big floor has more of everything, and each room may be bigger too.
    oversize = HOUSE_OVERSIZE

    def too_big(room: Room) -> bool:
        return (room.kind != "hall" and sum(map(len, _pieces(room, floor)))
                > (BIG_FLOOR_BEDROOM_OVERSIZE if room.kind in ("bedroom", "kidsbedroom")
                   and area >= HOUSE_BIG_FLOOR else oversize) * SIZES[room.kind].hi)

    grown = 0
    while True:
        always_big = True
        for _ in range(HOUSE_TRIES if len(kinds) > need else HOUSE_LAST_TRIES):
            rooms = (_cut_in_wings(box, kinds, rng, floor, core, landing)
                     if area >= HOUSE_BIG_FLOOR else None)
            if rooms is None:
                rooms = split_by_targets(box, kinds, rng, area=area, touch=landing)
            for r in rooms or ():
                if r.kind == "closet" and too_big(r):
                    # A closet the cut made room-sized is the spare room it
                    # looks like: a big floor failed on these more than on
                    # anything else, and went to the plain splitter.
                    tiles = sum(map(len, _pieces(r, floor)))
                    r.kind = next((k for k in CLOSET_GROWS_INTO
                                   if tiles <= HOUSE_OVERSIZE * SIZES[k].hi), r.kind)
            kept = [r for r in rooms or () if r.kind not in losable]
            big = any(map(too_big, kept))
            # One hall cannot touch every bedroom of a large house, and the
            # wings already give each half its own, so only a smaller floor
            # is held to it.
            if rooms and not big and all(map(keeps, kept)) and (
                    area >= HOUSE_BIG_FLOOR
                    or all(_on_circulation(r, rooms, core) for r in rooms)):
                return rooms
            always_big &= big
        # Every cut had a room too big for its kind. On a large floor that
        # means too few rooms, not too many: add some and cut again, a few
        # times, before the floor is given up to the plain splitter.
        if always_big and area >= HOUSE_BIG_FLOOR and grown < HOUSE_GROW_TRIES:
            grown += 1
            kinds.extend(k for k in (next(spares, None) for _ in range(2)) if k)
            continue
        # Fewer rooms would only come out bigger.
        if always_big or len(kinds) <= need:
            return None
        # Half the rooms it can shed at a time, so a footprint that only
        # takes the bare programme gets there in a few cuts, not a dozen.
        del kinds[len(kinds) - max(1, (len(kinds) - need) // 2):]


def _house_open_plan_share(profile) -> float:
    if profile is None:
        return 0.0
    era_share = {"prewar": 0.03, "midcentury": 0.12, "modern": 0.28}
    share = era_share.get(profile.era, 0.08) * (0.75 + 0.5 * profile.wealth)
    return min(0.38, share + (0.04 if profile.setting == "urban" else 0.0))


def _house_dining_share(profile) -> float:
    if profile is None:
        return DINING_ROOM_SHARE
    era_factor = {"prewar": 1.45, "midcentury": 1.0, "modern": 0.65}
    return min(0.3, DINING_ROOM_SHARE
               * era_factor.get(profile.era, 1.0)
               * (0.75 + 0.5 * profile.wealth))


def _house_study_share(profile) -> float:
    if profile is None:
        return 1.0
    share = 0.25 + 0.45 * profile.wealth
    if profile.era == "modern":
        share += 0.12
    if profile.wear >= 0.75:
        share -= 0.08
    return max(0.1, min(0.9, share))


def _merge_house_open_plan(plan: Plan, living_id: int, kitchen_id: int) -> bool:
    living, kitchen = plan.rooms[living_id - 1], plan.rooms[kitchen_id - 1]
    side_by_side = (living.y0 == kitchen.y0 and living.y1 == kitchen.y1
                    and (living.x1 + 1 == kitchen.x0 or kitchen.x1 + 1 == living.x0))
    stacked = (living.x0 == kitchen.x0 and living.x1 == kitchen.x1
               and (living.y1 + 1 == kitchen.y0 or kitchen.y1 + 1 == living.y0))
    if not (side_by_side or stacked):
        return False
    living.x0, living.y0 = min(living.x0, kitchen.x0), min(living.y0, kitchen.y0)
    living.x1, living.y1 = max(living.x1, kitchen.x1), max(living.y1, kitchen.y1)
    living.kind = "openplan"
    for y in range(plan.height):
        for x in range(plan.width):
            if plan.grid[y][x] == kitchen_id:
                plan.grid[y][x] = living_id
    kitchen.kind = None
    _renumber(plan)
    return True


# Where you walk when you are not in a room. Knox County's houses have a hall
# in 42% of them and a living room in nearly all, and everything opens off one
# or the other; ours had no circulation upstairs at all, so a floor of bedrooms
# was a chain of them - the commonest door in the whole town was one bedroom
# into the next.
CIRCULATION = {"hall", "lobby", "livingroom", "openplan", "concourse"}


def _landing(plan: Plan, adj: dict, free: list,
             stairs: tuple[int, int, str] | None) -> int | None:
    """The room a floor is walked through: where the stairs arrive, or failing
    that whichever room touches the most others."""
    if stairs is not None:
        x, y, d = stairs
        dx, dy = (0, 1) if d == "N" else (1, 0)
        for i in range(STAIR_RUN):
            room = _room_at(plan, x + dx * i, y + dy * i)
            if room in free:
                return room
    if not free:
        return None
    return max(free, key=lambda i: (len([n for n in adj.get(i, ()) if n in free]),
                                    plan.rooms[i - 1].area))


# One more hall per this many rooms on a floor, on top of the corridor and the
# landing. It is a balance between two ways of being wrong, and the number was
# picked by measuring both against Knox County. Too few and rooms chain: at
# one per twelve, 230 doors in 300 buildings went bedroom into bedroom. Too
# many and the plan is corridor: at one per six, a house was a third
# circulation where the game's are a quarter by room. One per eight puts a
# house at 23.3% of its rooms against the game's 23.7%, and bedroom-to-bedroom
# doors at 120 where the old plan had 771.
ROOMS_PER_HALL = 8


def _more_halls(plan: Plan, adj: dict, free: list, kinds: dict,
                seeds: list[int], cap: int, want: list[int] | None = None) -> int:
    """Rooms turned into halls until the rest (or `want`) all open onto one."""
    made = 0
    while made < cap and free:
        covered = set(seeds)
        for i in seeds:
            covered |= set(adj.get(i, ()))
        left = [i for i in (free if want is None else want) if i not in covered]
        if not left:
            break
        seed_set = set(seeds)
        best = max(free, key=lambda i: (
            len([n for n in adj.get(i, ()) if n in left]),
            len(set(adj.get(i, ())) & seed_set),
            plan.rooms[i - 1].area))
        if not any(n in left for n in adj.get(best, ())):
            break
        kinds[best] = "hall"
        free.remove(best)
        seeds.append(best)
        made += 1
    return made


def _assign_house_kinds(plan: Plan, level: int, levels: int,
                        stairs: tuple[int, int, str] | None = None,
                        rng: random.Random | None = None,
                        by_kind: bool = False) -> None:
    """Rooms of a house, placed by what they sit next to.

    Handing kinds out in size order put the kitchen wherever the second-biggest
    rectangle fell, bathrooms opening off living rooms, and a kitchen on every
    storey of a three-storey house. Here the ground floor holds the rooms a
    household shares - the living room, the kitchen beside it, dining beside
    that - and upper floors hold bedrooms. Bedrooms go as far from the living
    room as the plan allows; the bathroom takes the smallest room.

    A floor cut `by_kind` (_house_by_kind) already has its kinds, open plan
    included; only a piece the shaft or the footprint split off a room is
    named here, and a spare room off the hall becomes another hall where
    bedrooms and bathrooms would otherwise open into each other.
    """
    rng = rng or random.Random(plan.width * 31 + plan.height)
    if by_kind:
        for room in plan.rooms:
            if not room.is_core and not room.fixed:
                room.kind = "closet" if room.area <= SMALL_ROOM_TILES else "storage"
        adj = _neighbours(plan)
        rooms = list(enumerate(plan.rooms, 1))
        seeds = [i for i, r in rooms if r.is_core or r.kind in CIRCULATION]
        near = {n for i in seeds for n in adj[i]}
        free = [i for i, r in rooms if i in near and not r.is_core
                and r.kind in ("office", "storage", "laundry")]
        kinds: dict[int, str] = {}
        _more_halls(plan, adj, free, kinds, seeds, 1 + len(rooms) // ROOMS_PER_HALL,
                    want=[i for i, r in rooms
                          if r.kind in ("bedroom", "kidsbedroom", "bathroom")])
        for i, kind in kinds.items():
            plan.rooms[i - 1].kind = kind
        # A bedroom or bathroom still off every hall trades kinds with a
        # spare room on one that is the right size for it.
        def off_hall(i: int) -> bool:
            return not any(plan.rooms[n - 1].is_core
                           or plan.rooms[n - 1].kind in CIRCULATION for n in adj[i])
        for i, room in rooms:
            if room.kind not in ("bedroom", "kidsbedroom", "bathroom") or not off_hall(i):
                continue
            size = SIZES[room.kind]
            swap = [j for j, r in rooms if r.fixed and r.kind in HOUSE_TOP_UP
                    and not off_hall(j)
                    and size.lo <= r.area <= HOUSE_OVERSIZE * size.hi]
            if swap:
                j = min(swap, key=lambda j: abs(plan.rooms[j - 1].area - room.area))
                room.kind, plan.rooms[j - 1].kind = plan.rooms[j - 1].kind, room.kind
        return
    adj = _neighbours(plan)
    # A room the mapper drew with a kind of its own keeps it; only the rest
    # are dealt out, and whatever is left out of that is a core, hence the
    # hall below.
    free = [i for i, r in enumerate(plan.rooms, 1)
            if not r.is_core and not r.fixed]
    for i, room in enumerate(plan.rooms, 1):
        if i not in free and not room.fixed:
            room.kind = "hall"
    if not free:
        return
    area = {i: plan.rooms[i - 1].area for i in free}
    kinds: dict[int, str] = {}
    bedroom_budget, bathroom_budget = _house_room_budgets(plan, levels)
    ground_bed = level == 0 and _ground_bedroom(bedroom_budget, levels,
                                                _footprint(plan), rng)
    bedroom_quota = _house_floor_bedrooms(bedroom_budget, levels, level) + ground_bed
    # A bathroom on every floor with a bedroom, and on the ground floor too
    # when the house has one to spare.
    bathroom_floors = {n for n in range(levels)
                       if _house_floor_bedrooms(bedroom_budget, levels, n)}
    if bathroom_budget > len(bathroom_floors) or ground_bed:
        bathroom_floors.add(0)

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
            # A separate dining room is the exception: Knox County has one in
            # 13% of its houses, the rest eating in the kitchen or the living
            # room. Taking one whenever there was a room to spare gave ours
            # one in 93%.
            if near and len(free) >= 3 and rng.random() < _house_dining_share(plan.profile):
                take(max(near, key=lambda i: area[i]), "dining")
        if free and level in bathroom_floors and (levels == 1 or len(free) >= 2):
            take(min(free, key=lambda i: area[i]), "bathroom")
        # A small room beside the kitchen is its laundry.
        near = [n for n in adj.get(kitchens[0], ()) if n in free
                and area[n] <= SMALL_ROOM_TILES] if (kitchens := [i for i, k in kinds.items()
                                                                  if k == "kitchen"]) else []
        if near:
            take(min(near, key=lambda i: area[i]), "laundry")
        _more_halls(plan, adj, free, kinds, [living] + [i for i, k in kinds.items()
                                                        if k == "hall"],
                    len(free) // ROOMS_PER_HALL)
        dist = _graph_distance(adj, living)
        rest = sorted(free, key=lambda i: -dist.get(i, 99))
        bedroom_count = min(bedroom_quota, len(rest))
        kids_room = bedroom_count > 1 and rng.random() < 0.4
        for n, i in enumerate(rest):
            if n < bedroom_count:
                kinds[i] = "kidsbedroom" if kids_room and n == bedroom_count - 1 else "bedroom"
            elif area[i] <= SMALL_ROOM_TILES:
                kinds[i] = "closet"
            elif n == bedroom_count:
                kinds[i] = ("office" if rng.random() < _house_study_share(plan.profile)
                            else "storage")
            else:
                kinds[i] = HOUSE_SPARE[(n - bedroom_count - 1) % len(HOUSE_SPARE)]
    else:
        # The landing. Without one an upstairs was a row of bedrooms opening
        # into each other, which is what a plan should never ask you to walk
        # through. It is taken before the bathroom, which would otherwise take
        # the smallest room and leave nothing to walk in.
        landing = _landing(plan, adj, free, stairs)
        if landing is not None and len(free) >= 3:
            take(landing, "hall")
        _more_halls(plan, adj, free, kinds,
                    [i for i, k in kinds.items() if k == "hall"],
                    len(free) // ROOMS_PER_HALL)
        if free and level in bathroom_floors:
            take(min(free, key=lambda i: area[i]), "bathroom")
        rest = sorted(free, key=lambda i: -area[i])
        bedroom_count = min(bedroom_quota, len(rest))
        kids_room = bedroom_count > 1 and rng.random() < 0.4
        for n, i in enumerate(rest):
            if n < bedroom_count:
                kinds[i] = "kidsbedroom" if kids_room and n == bedroom_count - 1 else "bedroom"
            elif area[i] <= SMALL_ROOM_TILES:
                kinds[i] = "closet"
            elif level == 1 and n == bedroom_count:
                kinds[i] = "laundry"
            elif n == bedroom_count:
                kinds[i] = ("office" if rng.random() < _house_study_share(plan.profile)
                            else "storage")
            else:
                kinds[i] = HOUSE_SPARE[(n - bedroom_count - 1) % len(HOUSE_SPARE)]

    for i, kind in kinds.items():
        plan.rooms[i - 1].kind = kind
    _house_open_plan(plan, level, rng)


def _house_open_plan(plan: Plan, level: int, rng: random.Random) -> None:
    """Knock the ground floor's living room and kitchen into one, sometimes."""
    if level == 0 and rng.random() < _house_open_plan_share(plan.profile):
        living = next((i for i, room in enumerate(plan.rooms, 1)
                       if room.kind == "livingroom"), None)
        kitchen = next((i for i, room in enumerate(plan.rooms, 1)
                        if room.kind == "kitchen"), None)
        if living is not None and kitchen is not None:
            _merge_house_open_plan(plan, living, kitchen)
