"""Putting a plan together: build_plan, build_building and the roof grid."""
from __future__ import annotations

from .. import catalog as C
from ..entrances import closed_edges, closed_entrance, entrance_facade, ground_entrance
from ..profile import apartment_access_rules
from ..settings import Settings
from ..uses import FRONT_ROOMS
import random
from dataclasses import replace

from typing import TYPE_CHECKING
from .access import door_sides, shared_paths, stair_tiles
from .core import COMMERCIAL, COMMERCIAL_FILL, MAX_DEPTH, MIN_ROOM, Plan, RETAIL_ROOMS, Room, SPECIAL_MIXES, STAIR_RUN, _inside, _mapped_rooms, _split, mapped_room_tiles
from .flat_planning import MIN_STUDIO_AREA, VariantCache, replan_flats
from .openings import ApartmentAccessError, _attach_garage, _back_door, _garage_bay, _make_foyer, _rooms_joined_without, _doors, _exterior_door, _more_ways_in, _outside_runs, _room_at, _widen_vehicle_entry
from .malls import _atrium_railings, _clear_concourse, _mall_doors, _mall_plan_fits, _mall_rooms, _merge_concourse, _merge_halls, _open_shopfronts, _place_kiosks, _renumber
from .dwellings import FLAT_FRONTAGE, HOTEL_FRONTAGE, _apartment_rooms, _assign_flat_kinds, _flats_keep_bathrooms, _join_undersized_flats, _paint, _stagger_flats, _unit_touches_corridor, inlay_mapped_rooms
from . import houses as _houses
from .houses import _assign_house_kinds, _footprint
from .shops import CORRIDOR_WORTH_IT, MERGE_CIRCULATION, NEEDS_CORRIDOR, _arrange_business_rooms, _assign_kinds, _assign_shop_floor, _circulation, _dining_sections, _fit_out_sections, _shop_rooms, _split_to_size
from .furnishing import Building, CORE_WIDE, NARROW_CORE_WIDE, CORRIDOR_WIDTHS, ELEVATOR_FROM_LEVELS, ELEVATOR_MIN_SIDE, HOUSE_LIKE_KINDS, MALL_LIFT_FROM_LEVELS, NARROW_CORRIDOR_WIDTHS, SWITCH, _carve_shaft, _cells_for, _clear_for_stairs, _clear_the_way, _cut_off_by_the_shaft, _facing, _furnish, _is_wall_piece, _pick_core, _pick_corridor, _pick_shaft, _place_windows, _stairs_in_core, _wall_edge
from .furnishing import _facade_runs

if TYPE_CHECKING:
    from ..apartment_sections import AccessLayout
    from .core import Plan
    from .furnishing import Building
    from ..tower import TowerCore



def build_building(width: int, height: int, levels: int = 1,
                   commercial: bool = False, seed: int = 0,
                   kind: str | None = None,
                   mask: list[list[bool]] | None = None,
                   settings: Settings | None = None,
                   street: str | None = None,
                   retail: bool = False,
                   uses: list[tuple[str, str]] | None = None,
                   hotel: bool = False,
                   party: dict | None = None,
                   entrances: list[tuple[float, float, dict]] | None = None,
                   profile: object | None = None,
                   mapped: list | dict[int, list] | None = None,
                   garage_door: bool = False,
                   approach_edges: tuple | None = None,
                   mapped_lobbies: tuple = (),
                   section_flats: int | None = None) -> Building:
    """Lay out a building of `levels` storeys.

    `retail` puts shops on the ground floor of a block of flats, as on any
    city street; towers step back above SETBACK_FROM_LEVELS. `uses` are what
    OpenStreetMap says the ground floor is (knoxbuild/uses.py), as (front
    room, back room); `hotel` makes a block of flats' flats hotel rooms.

    Each storey is laid out separately rather than copied, because a block of
    flats whose every floor is identical reads as a rendering error; only the
    staircase has to line up, and it does because the shaft is reserved first.
    """
    levels = max(1, levels)
    if kind == "garage" and mask is None:
        # Ensure rectangular exterior garages are large enough inside for a car
        # (>= 5x5), and keep the shorter span odd for the 30-degree roof.
        width = max(width, 5)
        height = max(height, 5)
        if min(width, height) % 2 == 0:
            if width <= height:
                width -= 1
            else:
                height -= 1
    rng = random.Random(seed ^ 0x5745)
    settings = settings or Settings()
    private_flats = kind == "apartment" and settings.apartment_layout != "classic" and not hotel
    mapped_floors = mapped if isinstance(mapped, dict) else {0: mapped or ()}
    surveyed = {}
    if kind == "apartment" and not hotel:
        surveyed = {z: [(mapped_room_tiles(ring, width, height), room_kind) for ring, room_kind in rooms]
                    for z, rooms in mapped_floors.items() if rooms and 0 <= z < levels}
    reserved = frozenset(tile for rooms in surveyed.values() for tiles, _ in rooms for tile in tiles)
    clear_mask = [[(mask is None or mask[y][x]) and (x, y) not in reserved
                   for x in range(width)] for y in range(height)] if reserved else mask
    access_rules = apartment_access_rules(profile)
    balcony_mode = settings.apartment_stair_balcony
    year = getattr(profile, "source_year", None)
    if balcony_mode in (0, "off"):
        access_rules = replace(access_rules, stair_via_balcony=False)
    elif balcony_mode in (1, "on") or (
            balcony_mode in (2, "auto") and settings.apartment_layout == "auto"
            and year is not None and year >= access_rules.lobby_recent_from_year):
        access_rules = replace(access_rules, stair_via_balcony=True)

    # A block of flats gets a corridor whether or not it is tall enough to
    # need stairs, because the flats have to open onto something. Everything
    # else only needs a shaft, and only once there is a floor above.
    core = None
    corridor = False
    access = None
    # An office tower has its own core, the same on every storey (tower.py);
    # a footprint with no room for one is laid out as any other building.
    from .. import tower as tower_mod
    tcore = None
    if tower_mod.qualifies(kind, levels, width, height):
        tcore = tower_mod.pick_core(width, height, mask,
                                    random.Random(seed ^ 0x70E2))
    if tcore is not None:
        core = tcore.stair
    elif (kind == "apartment"
          and not (levels == 1 and private_flats and min(width, height) < CORE_WIDE + 2 * MIN_ROOM)):
        if private_flats:
            from ..apartment_sections import access_layout

            for avoid in (reserved, frozenset()) if reserved else (reserved,):
                access = access_layout(width, height, mask, levels, settings.apartment_layout,
                                       street, entrances or (), party or {}, rules=access_rules,
                                       approach_edges=approach_edges, reserved=avoid)
                if access is not None:
                    break
            if access is None and entrances:
                access = access_layout(width, height, mask, levels, settings.apartment_layout,
                                       street, entrances, party or {}, rules=access_rules,
                                       inferred=True, approach_edges=approach_edges, reserved=reserved)
            if access is not None:
                core = access.landing
        if core is None:
            core = _pick_corridor(width, height, clear_mask, rng)
            if core is None and reserved:
                core = _pick_corridor(width, height, mask, rng)
        corridor = core is not None
    elif kind in NEEDS_CORRIDOR and (
            width * height >= (4 if kind == "school" else CORRIDOR_WORTH_IT)
            * min((settings.room_size if settings else Settings().room_size)
                  * KIND_ROOM_SCALE.get(kind, 1.0), _room_cap(kind))):
        # A school or a clinic is rooms off a corridor. In Knox County a
        # school's halls are 11% of its rooms and 21% of its floor, and they
        # average 122 tiles: one long one serving a storey, not a dozen square
        # ones relabelled, which is what read as corridors all the way down.
        # Only where there are rooms enough to be worth serving - a two-room
        # library with a corridor through it is a third corridor.
        core = _pick_corridor(width, height, mask, rng,
                              CORRIDOR_WIDTHS if kind == "school" else NARROW_CORRIDOR_WIDTHS)
    hug_wall = (
        tcore is None
        and kind != "mall"
        and (kind != "industrial" or (width * height < 200 and min(width, height) < 12))
    )
    if core is None and levels > 1:
        # A small house has no room for the strip beside its stairs to be
        # folded into, so the strip has to be a room of its own or nothing.
        small = min(width, height) < CORE_WIDE + 2 * MIN_ROOM
        core = _pick_core(width, height, mask, rng, street,
                          min_gap=MIN_ROOM if kind in HOUSE_LIKE_KINDS and small else 1)
        if (core is None and kind in (None, "house") and getattr(profile, "narrow_stairs", False)
                and min(width, height) >= NARROW_CORE_WIDE + 2):   # a tile of hall beside
            core = _pick_core(width, height, mask, rng, street, min_gap=1,
                              core_wide=NARROW_CORE_WIDE)
    if levels > 1 and core is None:
        levels = 1          # nowhere to put a staircase, so one floor it is

    stairs = _stairs_in_core(core, hug_wall=hug_wall) if core is not None and levels > 1 else None
    lift = access.lift if access is not None else None
    shaft = shaft_door = None
    if tcore is not None:
        shaft, shaft_door = tcore.lifts[0]
    elif lift is not None:
        stairs = lift.flight
        shaft, shaft_door = lift.shaft
    elif not private_flats and core is not None and min(width, height) >= ELEVATOR_MIN_SIDE and levels >= (
            MALL_LIFT_FROM_LEVELS if kind == "mall" and _mall_plan_fits(width, height, mask)
            else ELEVATOR_FROM_LEVELS):
        found = _pick_shaft(core, width, height, mask, stairs)
        if found:
            shaft, shaft_door = found
    lobby = None
    if access is not None:
        from ..apartment_sections import ground_lobby

        lobby = ground_lobby(access, width, height, mask, levels, profile, mapped_lobbies,
                             stairs, shaft, party or (), access_rules, section_flats,
                             reserved={tile for tiles, _ in surveyed.get(0, ()) for tile in tiles})
    # A tower's toilet and riser are part of its core too: the step must not
    # cut through them on the upper floors.
    lifts = ([r for r, _ in tcore.lifts] + [r for r, _ in tcore.service]
             if tcore is not None else [shaft])
    # Sections that share walls up to the roof stay joined. The generic
    # setback on each slice would cut an open gap through the same block.
    setback_levels = (0 if access is not None
                      and max((party or {}).values(), default=0) >= levels else levels)
    spine = access.spine if access is not None else None
    oriented = access.oriented if access is not None else None
    if oriented is not None or (lift is not None and lift.balcony):
        # A rectangular setback cannot clip a diagonal hall or expose a new
        # balcony edge without the railing being planned for it.
        setback_levels = 0
    upper_mask, setback_at = _setback(width, height, mask, setback_levels, spine or core,
                                      lifts + [core] if spine else lifts, corridor)
    if setback_at:
        protected = set(lift.lobby) if lift is not None else set()
        protected.update((x, y) for z, rooms in surveyed.items() if z >= setback_at
                         for tiles, _ in rooms for x, y in tiles)
        if any(not upper_mask[y][x] for x, y in protected):
            upper_mask, setback_at = None, 0
    # Shops under flats where the town is dense, and wherever the map puts a
    # shop, a restaurant or a bank in a building that is more than one.
    shops = (tcore is None and core is not None and not surveyed.get(0) and kind in ("apartment", "civic")
             and ((retail and kind == "apartment" and levels >= 3) or (bool(uses) and levels >= 2)))
    # A block of flats repeats its floor plan. Looking up at one from the
    # street the windows line up all the way, because every floor above the
    # ground is the same floor - and ours did not, because each storey was
    # laid out from its own seed. Most windows landed in the same bays anyway
    # and a handful drifted, which is worse than either being aligned or
    # being obviously different. Floors that share a footprint now share a
    # seed, so they share a layout; the ground floor keeps its own (it has the
    # entrance, and the shops when there are any), and a setback starts a new
    # one because the floors above it are a different shape.
    def _plan_seed(lvl: int) -> int:
        if kind != "apartment" or lvl == 0:
            return seed + 977 * lvl
        above = bool(setback_at) and lvl >= setback_at
        return seed + 977 * (1 + int(above))

    flat_variants = {} if private_flats else None
    # Keep a typical storey aligned with the others. Ground-floor businesses
    # can subsequently take space from this residential capacity.
    flat_count = max(1, round(section_flats / levels)) if private_flats and section_flats else None

    def _storey(lvl: int, attempt: int = 0):
        return build_plan(width, height, commercial=commercial or (shops and lvl == 0),
                          seed=_plan_seed(lvl) + 4357 * attempt,
                          kind="retail" if shops and lvl == 0 else kind,
                          mask=upper_mask if setback_at and lvl >= setback_at else mask,
                          ground=(lvl == 0), settings=settings,
                          core=core, level=lvl, levels=levels, stairs=stairs,
                          corridor=corridor, shaft=shaft, shaft_door=shaft_door,
                          street=street, uses=uses, hotel=hotel,
                          extra_shafts=tcore.lifts[1:] if tcore is not None else None,
                          tower=tcore,
                          plant=tcore is not None and lvl == tower_mod.plant_level(levels),
                          entrances=entrances if lvl == 0 else None,
                          profile=profile, mapped=mapped_floors.get(lvl),
                          surveyed_rooms=surveyed.get(lvl),
                          garage_door=garage_door and lvl == 0,
                          apartment_access=access,
                          lobby=lobby if lvl == 0 else None,
                          approach_edges=approach_edges,
                          flat_variants=flat_variants,
                          flat_count=flat_count,
                          flat_balconies=bool(getattr(profile, "apartment_balconies", None) is True
                                             or (levels >= 3 and
                                                 getattr(profile, "apartment_balconies", None) is None)),
                          party={e for e, up in (party or {}).items() if lvl < up})

    # The ground floor first: a mansion's floors above it are opened over its
    # hall, and that has to be known before they are laid out.
    storeys = []
    for lvl in range(levels):
        for attempt in range(3):
            try:
                storeys.append(_storey(lvl, attempt))
                break
            except ApartmentAccessError:
                if attempt == 2:
                    raise
    building = Building(width=width, height=height, storeys=storeys, profile=profile,
                        grand=bool(storeys) and storeys[0].grand,
                        tower=tcore is not None,
                        unplaced_lift_cores=int(private_flats and not shaft and
                                                levels >= access_rules.lift_from_levels and
                                                min(width, height) >= ELEVATOR_MIN_SIDE))
    if stairs is not None:
        from .furnishing import (
            _doors_off_stairs,
            _has_door_on_stairs,
            _valid_stairs_on_building,
        )
        allow_narrow = tcore is not None
        candidates = [stairs]
        if hug_wall and core is not None and spine is None and oriented is None and lift is None:
            for alt in (_stairs_in_core(core, hug_wall=True, far_wall=True),
                        _stairs_in_core(core, hug_wall=False)):
                if alt not in candidates:
                    candidates.append(alt)
        saved_doors = [list(s.doors) for s in storeys]
        saved_limits = [dict(s.entrance_limits) for s in storeys]
        chosen = None
        for cand in candidates:
            if not _valid_stairs_on_building(building, cand,
                                             allow_narrow_core=allow_narrow):
                continue
            for s, orig, limits in zip(storeys, saved_doors, saved_limits):
                s.doors = list(orig)
                s.entrance_limits = dict(limits)
            building.stairs = [cand] * (levels - 1)
            _doors_off_stairs(building)
            if not _has_door_on_stairs(building):
                chosen = cand
                break
            if chosen is None:
                chosen = cand
        if chosen is not None:
            stairs = chosen
            for s, orig, limits in zip(storeys, saved_doors, saved_limits):
                s.doors = list(orig)
                s.entrance_limits = dict(limits)
            building.stairs = [stairs] * (levels - 1)
            _doors_off_stairs(building)
            for lvl in range(levels - 1):
                _clear_for_stairs(storeys[lvl], *stairs)
                _clear_for_stairs(storeys[lvl + 1], *stairs)
        else:
            # No valid staircase (e.g. top landing onto roof or 1-tile hall):
            # drop to a single storey rather than leaving stairs to nowhere.
            for s, orig, limits in zip(storeys, saved_doors, saved_limits):
                s.doors = list(orig)
                s.entrance_limits = dict(limits)
            stairs = None
            building.stairs = []
            building.storeys = storeys[:1]
    # Windows last and for the whole building at once, so they stack in
    # columns instead of each floor scattering its own.
    if stairs is not None:
        for storey in building.storeys:
            if storey.private_flats:
                storey.stair_steps = set(stair_tiles(stairs)[2:-1])
    _place_windows(building, kind, shop_ground=shops)
    if kind == "mall":
        _place_escalators(building)
    # Last of all, because it is the furnished building that has to be
    # walkable, not the plan.
    _clear_the_way(building)
    if private_flats:
        from .furnishing import _blocks
        for level, storey in enumerate(building.storeys):
            storey.public_path = shared_paths(
                storey, building.stairs[level - 1:level] if level else (),
                building.stairs[level:level + 1], ground=level == 0)
            storey.furniture = [f for f in storey.furniture if not (
                _blocks(f[0]) and storey.public_path.intersection(_cells_for(*f)))]
    from .. import interiors
    interiors.one_wood(building, random.Random(f"{seed}:wood"))
    return building


# Towers step back: from this many storeys the top part is set in from the
# edges, the way tall buildings are built for light and wind. A 30-storey
# block that went straight up from its footprint was a featureless box.
SETBACK_FROM_LEVELS = 12
SETBACK_SHARE = 0.65          # the step comes this far up
SETBACK_TILES = 2
SETBACK_MIN_KEEP = 0.5        # the upper part keeps at least this much floor


def _setback(width: int, height: int, mask, levels: int, core, shafts,
             corridor: bool):
    """(the upper storeys' mask, the storey the step is at) or (None, 0)."""
    if levels < SETBACK_FROM_LEVELS or core is None:
        return None, 0
    base = mask or [[True] * width for _ in range(height)]
    k = SETBACK_TILES
    # A block of flats has a corridor end to end: it steps in along its long
    # sides only, so the corridor still reaches both ends.
    x0, y0, x1, y1 = core
    along_x = corridor and (x1 - x0) >= (y1 - y0)
    along_y = corridor and not along_x

    def kept(x, y):
        for dx in range(-k, k + 1):
            for dy in range(-k, k + 1):
                if along_x and dx:
                    continue
                if along_y and dy:
                    continue
                nx, ny = x + dx, y + dy
                if not (0 <= nx < width and 0 <= ny < height and base[ny][nx]):
                    return False
        return True

    upper = [[base[y][x] and kept(x, y) for x in range(width)] for y in range(height)]
    for rx0, ry0, rx1, ry1 in [core] + [r for r in shafts if r]:
        for y in range(ry0, ry1 + 1):
            for x in range(rx0, rx1 + 1):
                if not upper[y][x]:
                    return None, 0
    if sum(map(sum, upper)) < SETBACK_MIN_KEEP * sum(map(sum, base)):
        return None, 0
    return upper, round(levels * SETBACK_SHARE)


def _place_escalators(building: "Building") -> None:
    """A pair of escalators along the atrium, off the end of the concourse.

    They run the length of the opening rather than across it, so they sit in
    the hole instead of bridging it, and the top lands on the floor that wraps
    the end of the concourse. The railing is taken off wherever one arrives,
    or the way off it is fenced.
    """
    if len(building.storeys) < 2:
        return
    upper = building.storeys[1]
    if not upper.void:
        return
    rows = sorted({y for x, y in upper.void})
    cols = sorted({x for x, y in upper.void})
    if len(rows) < C.ESCALATOR_WEST_H or len(cols) < C.ESCALATOR_WEST_W:
        return
    # The top square sits on the floor just west of the opening; the run
    # goes east into it.
    ax = cols[0] - 1
    ay = rows[0] + (len(rows) - (2 * C.ESCALATOR_WEST_H - 1)) // 2
    if ax < 0 or ay < rows[0] or ay + 2 * C.ESCALATOR_WEST_H - 2 > rows[-1]:
        ay = rows[0]
    if ax + C.ESCALATOR_WEST_W - 1 > cols[-1]:
        return
    pair = [(ax, ay)]
    second = ay + C.ESCALATOR_WEST_H - 1
    if second + C.ESCALATOR_WEST_H - 1 <= rows[-1]:
        pair.append((ax, second))
    building.escalators = pair
    _clear_railing_at(building, pair)


def _clear_railing_at(building: "Building", pair: list) -> None:
    """Take the railing off the squares an escalator arrives on.

    The rail runs the whole edge of the opening, the landing included, which
    fenced off the one thing it is there to reach.
    """
    # Only where it arrives - the squares it puts on the upper floor - not
    # the whole length of it. Clearing the lot took six tiles of railing out
    # of each side and left the opening unfenced along the escalator well.
    taken = set()
    for ax, ay in pair:
        for dx, dy, dz, _n in C.ESCALATOR_WEST:
            if dz == 1:
                taken.add((ax + dx, ay + dy))
    for storey in building.storeys:
        if not storey.railing:
            continue
        keep, opened = set(), set()
        for x, y, d in storey.railing:
            if ((x, y) in taken or (x - 1, y) in taken
                    or (x, y - 1) in taken):
                opened.add((x, y, d))
            else:
                keep.add((x, y, d))
        storey.railing = keep
        storey.open_edge |= opened


def _is_t_hangar(width: int, height: int) -> bool:
    """Long, narrow airfield hangar rows are T-hangar blocks with individual bays."""
    long_side = max(width, height)
    short_side = max(1, min(width, height))
    return long_side >= 35 and long_side >= 2.3 * short_side


def _t_hangar_bays(plan: "Plan", width: int, height: int) -> None:
    """Slice a long T-hangar row into ~14-tile-wide aircraft bays."""
    if width >= height:
        n = max(2, round(width / 14))
        for i in range(n):
            x0 = (i * width) // n
            x1 = ((i + 1) * width) // n - 1
            if x1 >= x0:
                plan.rooms.append(Room(x0, 0, x1, height - 1, kind="hangar", fixed=True))
    else:
        n = max(2, round(height / 14))
        for i in range(n):
            y0 = (i * height) // n
            y1 = ((i + 1) * height) // n - 1
            if y1 >= y0:
                plan.rooms.append(Room(0, y0, width - 1, y1, kind="hangar", fixed=True))


def _t_hangar_bay_doors(plan: "Plan", street: str | None) -> None:
    """Give every T-hangar bay its own 3-tile roll-up bay door on the taxiway side."""
    long_sides = ("N", "S") if plan.width >= plan.height else ("E", "W")
    preferred = street if street in long_sides else long_sides[0]
    bay_tiles = list(getattr(plan, "garage_door_tiles", ()) or ())
    for idx, room in enumerate(plan.rooms, 1):
        if room.kind != "hangar":
            continue
        runs = [(side, wall) for side, wall in _outside_runs(plan, idx)
                if side in long_sides and len(wall) >= 3]
        if not runs:
            continue
        _side, wall = max(runs, key=lambda r: (r[0] == preferred, len(r[1])))
        if any(e in wall for e in bay_tiles):
            continue
        mid = len(wall) // 2
        start = min(max(0, mid - 1), len(wall) - 3)
        opening = wall[start:start + 3]
        for edge in opening:
            if edge not in plan.doors:
                plan.doors.append(edge)
            if edge not in bay_tiles:
                bay_tiles.append(edge)
    plan.garage_door_tiles = tuple(bay_tiles)


def _shop_doors(plan: "Plan", street: str | None) -> None:
    """A street door into each shop on a block of flats' ground floor."""
    from .openings import _door_on_run, _has_door_depth

    for idx, room in enumerate(plan.rooms, 1):
        if room.is_core or room.is_shaft or room.kind not in RETAIL_ROOMS | FRONT_ROOMS:
            continue
        runs = [(side, wall) for side, wall in _outside_runs(plan, idx) if len(wall) >= 3]
        if not runs:
            continue
        deep = [(side, wall) for side, wall in runs
                if any(_has_door_depth(plan, side, e) for e in wall)]
        pool = deep if deep else runs
        side, wall = max(pool, key=lambda r: (r[0] == street, len(r[1])))
        door = _door_on_run(plan, side, wall)
        if door not in plan.doors:
            plan.doors.append(door)


def _stair_foot(stairs: tuple[int, int, str] | None) -> tuple[int, int] | None:
    if stairs is None:
        return None
    x, y, d = stairs
    return (x, y + STAIR_RUN - 1) if d == "N" else (x + STAIR_RUN - 1, y)


# Rooms scale with what the building is: a warehouse is a few great halls, a
# church one nave, a school rooms the size of classrooms.
# A great hall and a concourse are big rooms; neither building is cut into
# bedsits.
KIND_ROOM_SCALE = {"industrial": 6.0, "barn": 16.0, "shed": 20.0, "church": 12.0,
                   # A hangar is one span: cutting it into rooms is the one
                   # thing that stops it reading as a hangar. At this scale a
                   # 46x26 one is a single room and only a genuinely huge
                   # one is divided into bays - which it has to be, because
                   # the game spawns loot per room and a hangar of one room
                   # the size of a street would hold almost nothing.
                   "hangar": 70.0,
                   "terminal": 24.0,
                   "castle": 14.0, "stadium": 11.0, "mall": 16.0,
                   "shop": 2.0, "school": 9.0, "civic": 2.5,
                   "restaurant": 1.5, "medical": 1.3, "offices": 3.0,
                   "police": 2.0, "library": 8.0, "fire": 4.0,
                   "fire_police": 3.0, "military": 4.0,
                   # A bunker under a whole base is thousands of tiles a level.
                   "basement_military": 6.0, "basement_industrial": 6.0,
                   "basement_mall": 4.0, "basement_school": 3.0,
                   "basement_medical": 2.0, "basement_civic": 2.0,
                   "basement_police": 2.0, "basement_church": 3.0}
# A shop's ground floor is a sales floor or a few: rooms the size of a house's
# cut a grocery into cupboards no rows of shelving fit in.
SHOP_FLOOR_SCALE = 4.0
MAX_ROOMS_PER_FLOOR = 90
# No room bigger than this, however big the building.
#
# Loot is capped per room, not per container: every entry in the game's
# Distributions.lua carries a max, which is how many containers in one room
# may be filled from it (RoomDef.proceduralSpawnedContainer counts them), and
# most of the household and office ones are 1, 2 or 4. So a room with twenty
# cabinets in it has loot in the first few and nothing in the rest - "if a
# building is too big, it just stops spawning loot in containers at some
# point". More rooms means more allowances, so no room is bigger than this
# whatever the building is, and the depth cap below has to be loose enough to
# reach it: a 200x200 building needs eleven cuts, and at eight it stopped
# with rooms of two thousand tiles.
MAX_ROOM_AREA = 120
# ...except where the game's own buildings are plainly bigger. Every room in
# Knox County, by what it is called: a church is 39 tiles at the median but
# 340 at the ninth decile and 1132 at the largest, which is one nave with
# small rooms off it; a library room is 100 at the median and 282 at the
# decile; a gym 88 and 314; a warehouse 134 and 461. Held to 120 whatever the
# building was, a church and a library came out as a grid of cubicles where
# the game has a hall. The loot allowance above is the reason for the cap, and
# these are the buildings the game itself spends it on.
KIND_MAX_ROOM = {"church": 340, "library": 280, "school": 170, "gym": 320,
                 "industrial": 460, "barn": 460, "shed": 460, "military": 150,
                 # Knox County's own hangar is one room the size of the
                 # building; 460 would cut it in three.
                 "hangar": 1800,
                 "terminal": 1200,
                 "civic": 170, "fire": 220, "fire_police": 220, "medical": 140,
                 # A great hall and a concourse. Without an entry here the cap
                 # is MAX_ROOM_AREA whatever KIND_ROOM_SCALE says, which is
                 # why no room-size setting moved either of these.
                 "castle": 340, "stadium": 460,
                 # Knox County's mall units: a clothes shop is 306 tiles at
                 # the median, a department store 441, a furniture shop 379.
                 "mall": 440}


def _room_cap(kind: str | None) -> int:
    return KIND_MAX_ROOM.get(kind or "", MAX_ROOM_AREA)


def build_plan(*args, **kw) -> Plan:
    """_build_plan, laid out again without the garage bay when the floor cut
    round it walls a room in behind the garage or leaves the front door no
    street wall: the cut does not know the bay is there."""
    plan = _build_plan(*args, **kw)
    if any(r.kind == "garage" and r.fixed for r in plan.rooms) and not _garage_fits(plan, kw.get("street")):
        plan = _build_plan(*args, garage_bay=False, **kw)
    return plan


def _garage_fits(plan: Plan, street: str | None) -> bool:
    """The carved garage is no way through, and the house has its own street door."""
    g = next(i for i, r in enumerate(plan.rooms, 1) if r.kind == "garage")
    bay_door = set(getattr(plan, "garage_door_tiles", ()))
    if len(bay_door) != 3 or not _rooms_joined_without(plan, g):
        return False
    return any(e in plan.doors and e not in bay_door
               for i in range(1, len(plan.rooms) + 1) if i != g
               for side, wall in _outside_runs(plan, i) if side == street for e in wall)


def _build_plan(width: int, height: int, commercial: bool = False,
               seed: int = 0, kind: str | None = None,
               mask: list[list[bool]] | None = None,
               ground: bool = True,
               settings: Settings | None = None,
               core: tuple[int, int, int, int] | None = None,
               level: int = 0, levels: int = 1,
               stairs: tuple[int, int, str] | None = None,
               corridor: bool = False,
               shaft: tuple[int, int, int, int] | None = None,
               shaft_door: tuple[int, int, str] | None = None,
               extra_shafts: list | None = None,
               street: str | None = None,
               uses: list[tuple[str, str]] | None = None,
               hotel: bool = False,
               party: set | None = None,
               entrances: list[tuple[float, float, dict]] | None = None,
               profile: object | None = None,
               mapped: list | None = None,
               surveyed_rooms: list | None = None,
               tower: "TowerCore | None" = None,
               plant: bool = False,
               garage_door: bool = False,
               apartment_access: AccessLayout | None = None,
               approach_edges: tuple | None = None,
               flat_variants: VariantCache | None = None,
               lobby: set[tuple[int, int]] | None = None,
               flat_count: int | None = None, flat_balconies: bool = False,
               garage_bay: bool = True) -> Plan:
    """Lay out and furnish one storey of the given tile size.

    `uses` are what OpenStreetMap says a commercial ground floor holds
    (build_building); `hotel` turns flats into hotel rooms.
    `mapped` are the rooms the mapper drew inside the building, as (ring,
    kind) in storey tiles: on the ground floor they are cut as they were
    drawn (_mapped_rooms) on its recorded floor.

    `ground` gates the exterior door: a door in an upper-floor wall opens onto
    a five-metre drop, and the game will happily let a zombie walk through it.

    `tower` (knoxbuild.tower.TowerCore) lays the storey out as an office
    tower round its core instead (_tower_rooms); `uses` and `mapped` are then
    ignored, and `plant` makes it the plant floor.
    """
    settings = settings or Settings()
    rng = random.Random(seed)
    plan = Plan(width=width, height=height, mask=mask, core=core,
                corridor=corridor, kind=kind, party=set(party or ()),
                profile=profile)
    private_flats = kind == "apartment" and settings.apartment_layout != "classic" and not hotel
    plan.private_flats = private_flats
    shared_tiles = None
    shells = None
    spine = apartment_access.spine if apartment_access is not None and private_flats else None
    oriented = apartment_access.oriented if apartment_access is not None and private_flats else None
    lift = apartment_access.lift if apartment_access is not None and private_flats else None
    # A large house, by the ground floor it covers. Counting the whole
    # house's floor against HOUSE_BIG_FLOOR made a 12x11 house with an
    # upstairs a mansion - two storeys of 132 cleared 260 - so half a town got
    # a gallery, a piano and a book-lined study, and bedrooms came out half
    # furniture. A mansion is a big house, not a tall one.
    plan.grand = (kind in (None, "house")
                  and _footprint(plan) >= _houses.MANSION_FLOOR_TILES)
    shop_floor = kind in ("shop", "retail", "restaurant") and ground and tower is None
    mix_kind = "offices" if kind in ("shop", "restaurant") and not ground else kind
    # Rooms in a flat are smaller than rooms in a house, and there have to be
    # enough of them per floor to make several dwellings out of.
    target = settings.room_size * KIND_ROOM_SCALE.get(mix_kind or "", 1.0)
    if shop_floor:
        target = settings.room_size * SHOP_FLOOR_SCALE
    if kind == "apartment":
        target = max(16, round(settings.room_size * 0.4))
    # A factory floor 160 tiles across split into house-sized rooms would be
    # hundreds of cupboards. However big the building, keep it to a number of
    # rooms a person could walk through.
    floor_tiles = sum(map(sum, mask)) if mask is not None else width * height
    target = min(max(target, floor_tiles / MAX_ROOMS_PER_FLOOR),
                 _room_cap(mix_kind))

    arms: list = []
    by_kind = None
    bay = None
    # _shop_rooms numbers the sales rooms before _paint; _paint can drop,
    # split or renumber them. Remember the rooms themselves, not the numbers.
    section_ids: set[int] = set()
    if tower is not None:
        arms = _tower_rooms(plan, tower, ground, plant, street)
    elif kind == "apartment":
        if private_flats and (spine is not None or oriented is not None or shaft is not None or lobby):
            from ..apartment_sections import tiles_in

            reserved = set(tiles_in(shaft)) if shaft is not None else set()
            if spine is not None or oriented is not None or lobby:
                shared_tiles = set(tiles_in(apartment_access.landing))
                if spine is not None:
                    shared_tiles.update(tiles_in(spine))
                if oriented is not None:
                    shared_tiles.update(oriented.tiles)
                if lift is not None:
                    shared_tiles.update(lift.lobby)
                    shared_tiles.update(lift.balcony)
                if ground:
                    shared_tiles.update(apartment_access.ground_passages)
                    shared_tiles.update(lobby or ())
                shared_tiles -= reserved
                reserved |= shared_tiles
            plan.mask = [[(mask is None or mask[y][x]) and (x, y) not in reserved
                          for x in range(width)] for y in range(height)]
        if oriented is not None:
            from .dwellings import FLAT_TARGET_AREA
            from .oriented import apartment_shells

            shells = apartment_shells(plan, oriented, FLAT_TARGET_AREA)
        else:
            _apartment_rooms(plan, rng, target, HOTEL_FRONTAGE if hotel else FLAT_FRONTAGE,
                             section=apartment_access is not None, entry_first=private_flats,
                             entrance=apartment_access.entries[0] if apartment_access else None,
                             spine=spine, flat_count=flat_count)
    elif shop_floor and kind in ("shop", "restaurant"):
        sections = _shop_rooms(plan, rng, street,
                               gas=any(front == "gasstore" for front, _b in (uses or ())))
        section_ids = {id(plan.rooms[i - 1]) for i in sections}
    elif mix_kind == "mall":
        _mall_rooms(plan, rng, target, level, uses, shaft)
    elif mix_kind == "garage":
        room_kind = ("mechanic" if any(front == "mechanic"
                                       for front, _back in (uses or ()))
                     else "garage")
        plan.rooms.append(Room(0, 0, width - 1, height - 1, kind=room_kind))
    elif mix_kind == "hangar" and _is_t_hangar(width, height):
        _t_hangar_bays(plan, width, height)
    else:
        # Reserve one small room for a bathroom when the building's mix has one.
        house_floor = not (shop_floor or commercial
                           or (mix_kind and mix_kind in SPECIAL_MIXES))
        small_room = house_floor or shop_floor or bool(mix_kind in SPECIAL_MIXES and
                                         "bathroom" in SPECIAL_MIXES[mix_kind][0])
        # An integral garage's bay comes off the floor before it is cut, and
        # goes back as the garage once it is.
        if (garage_bay and house_floor and ground and kind in (None, "house") and not garage_door
                and not mapped and (bay := _garage_bay(width, height, mask, core, stairs,
                                                       street, seed, profile))):
            whole = mask
            mask = [[(whole is None or whole[y][x])
                     and not (bay[0] <= x <= bay[2] and bay[1] <= y <= bay[3])
                     for x in range(width)] for y in range(height)]
            plan.mask = mask
        if mapped and (ground or level > 0):
            # The rooms OpenStreetMap has for this building, on the floor the
            # mapper drew them for. Only the remaining floor space is split.
            small = [small_room]
            _mapped_rooms(plan, rng, mapped, target, mask, small)
        else:
            # A house floor is cut by what it holds, each room sized by its
            # kind; one no programme fits, and anything else, as it always was.
            by_kind = _houses._house_by_kind(plan, level, levels, rng) if house_floor else None
            if by_kind:
                plan.rooms = by_kind
            else:
                _split(0, 0, width - 1, height - 1, rng, MAX_DEPTH, plan.rooms,
                       target_area=target, mask=mask, small=[small_room])
    merged_units = _paint(plan, shared_tiles, shells)
    if bay:
        mask = whole
        plan.rooms.append(Room(*bay, kind="garage", fixed=True))
        for y in range(bay[1], bay[3] + 1):
            for x in range(bay[0], bay[2] + 1):
                plan.grid[y][x] = len(plan.rooms)
    plan.mask = mask

    # Kinds are chosen after painting, from the plan as it really is: what a
    # room is depends on what it borders, and that is only known once the
    # footprint and the shaft have had their say.
    if tower is not None:
        pass                # _tower_rooms cut them with their kinds
    elif kind == "apartment":
        merged_units.update(_unit_touches_corridor(plan))
        if oriented is not None:
            merged_units.update(_join_undersized_flats(plan))
        # Trade a room between neighbours before the kinds are handed out, so
        # a flat that has gained or lost one is furnished for the size it
        # ended up, not the size it was cut.
        if not private_flats:
            _stagger_flats(plan, rng)
            _unit_touches_corridor(plan)
        _assign_flat_kinds(plan, hotel=hotel, reception=hotel and ground, rng=rng,
                           entry_first=private_flats)
    elif shop_floor:
        # _paint above can drop, split or renumber rooms, so the old numbers
        # are stale. Rebuild them from the rooms that survived: the sales
        # sections are identified by the room objects themselves.
        sections = [i for i, r in enumerate(plan.rooms, 1) if id(r) in section_ids]
        if kind == "restaurant" and not uses:
            uses = [("restaurantdining", "restaurantkitchen")]
        _assign_shop_floor(plan, rng, street, uses,
                           several=(kind == "retail" or (kind == "shop" and len(sections) > 1)))
        if kind == "restaurant" and len(sections) > 1 and len(uses) == 1:
            _dining_sections(plan, sections, *uses[0])
        if kind == "shop" and len(sections) > 1:
            _fit_out_sections(plan, rng, sections, uses)
    elif mix_kind == "garage":
        pass
    elif mix_kind == "hangar" and _is_t_hangar(width, height):
        pass
    elif mix_kind and mix_kind in SPECIAL_MIXES:
        mix, fill = SPECIAL_MIXES[mix_kind]
        # A room whose kind is already decided - the mall concourse - keeps
        # it; the mix is dealt to the rest.
        rooms = [r for r in plan.rooms if not r.is_core and not r.fixed]
        _assign_kinds(rooms, mix, fill)
        if mix_kind == "castle" and len(rooms) == 1:
            rooms[0].kind = "hall"
        if mix_kind == "stadium" and len(rooms) <= 2 and not any(r.kind == "lockerroom" for r in rooms):
            offices = [r for r in rooms if r.kind == "office"]
            if offices:
                min(offices, key=lambda r: r.area).kind = "lockerroom"
        if mix_kind == "school" and any(r.kind == "diningroom" for r in rooms) \
                and not any(r.kind == "kitchen" for r in rooms):
            classrooms = [r for r in rooms if r.kind == "classroom"]
            candidates = [r for r in rooms if r.kind in {"schoollab", "office", "schoolstorage"}
                          or (r.kind == "classroom" and len(classrooms) > 1)]
            if candidates:
                min(candidates, key=lambda r: r.area).kind = "kitchen"
        if mix_kind in NEEDS_CORRIDOR:
            _circulation(plan, rooms)
        _arrange_business_rooms(plan, mix_kind)
        if mix_kind in MERGE_CIRCULATION:
            _merge_halls(plan)
        if mix_kind == "mall":
            _merge_concourse(plan)
            _atrium_railings(plan)
    elif commercial:
        rooms = [r for r in plan.rooms if not r.is_core and not r.fixed]
        _assign_kinds(rooms, COMMERCIAL, COMMERCIAL_FILL)
        _circulation(plan, rooms)
    else:
        _assign_house_kinds(plan, level, levels, stairs, rng, by_kind=bool(by_kind))
    for room in plan.rooms:
        if room.is_core:
            room.kind = "hall"
    if shaft is not None:
        _carve_shaft(plan, shaft, shaft_door)
    if lift is not None:
        from ..apartment_sections import tiles_in

        lift.place(plan, set(tiles_in(spine)) if spine is not None else oriented.tiles, ground=ground)
    for extra, extra_door in extra_shafts or ():
        _carve_shaft(plan, extra, extra_door)
    # A tower's hall arms go on after the shafts: one tile thick, the
    # _mend_fragments in _paint and _carve_shaft would fold them into the offices they are there to serve.
    for rect in arms:
        plan.rooms.append(Room(*rect, kind="hall"))
        for y in range(rect[1], rect[3] + 1):
            for x in range(rect[0], rect[2] + 1):
                if mask is None or mask[y][x]:
                    plan.grid[y][x] = len(plan.rooms)
    if arms:
        _renumber(plan)

    # A cell is a cell: rooms far bigger than their kind ever is are cut down
    # now the kind is known, before any door is placed on them.
    _split_to_size(plan, rng)
    _cut_off_by_the_shaft(plan)
    if kind == "apartment" and not hotel and tower is None:
        if surveyed_rooms is None and mapped:
            surveyed_rooms = [(mapped_room_tiles(ring, width, height), room_kind)
                              for ring, room_kind in mapped]
        if surveyed_rooms:
            merged_units.update(inlay_mapped_rooms(plan, surveyed_rooms))
            merged_units.update(_unit_touches_corridor(plan))
        _flats_keep_bathrooms(plan)

    direct_entry = None
    portals = ()
    exterior_runs = ()
    if private_flats:
        merged_units.update(_unit_touches_corridor(plan))
        if not surveyed_rooms:
            merged_units.update(_join_undersized_flats(plan, MIN_STUDIO_AREA))
        if ground and entrances:
            exterior_runs = _facade_runs(mask if mask is not None else [[True] * width] * height)
            plan.blocked_entrances = closed_edges(exterior_runs, entrances)
            portals = [p for p in entrances if p[2].get("entrance") in ("yes", "main", "staircase")
                       and not closed_entrance(p[2]) and ground_entrance(p[2])]
        if ground and plan.rooms and not any(r.is_core for r in plan.rooms):
            _exterior_door(plan, rng, street=street, entrances=portals, approach_edges=approach_edges)
            if plan.doors:
                del plan.doors[1:]
                a, b = (_room_at(plan, *p) for p in door_sides(plan.doors[0]))
                direct_entry = a or b
    _doors(plan, rng, stairs=stairs, private_flats=private_flats, direct_entry=direct_entry)
    if private_flats:
        replan_flats(plan, merged_units, flat_variants, oriented.axis if oriented else None,
                     balcony_rng=random.Random(f"{seed}:balconies")
                     if not ground and flat_balconies else None)
    if mix_kind == "mall":
        _mall_doors(plan, rng, ground)
    if ground and tower is not None:
        _tower_entrance(plan, rng, street, entrances)
    elif ground:
        if apartment_access is not None and private_flats:
            plan.doors.extend(apartment_access.entries)
        elif direct_entry is None:
            previous = len(plan.doors)
            _exterior_door(plan, rng, avoid=_stair_foot(stairs), street=street,
                           entrances=portals if private_flats else entrances, approach_edges=approach_edges)
            if private_flats and approach_edges is not None and len(plan.doors) == previous:
                raise ApartmentAccessError("No reachable exterior approach fits the residential entrance")
        for x, y, tags in portals:
            if bound := entrance_facade(exterior_runs, x, y, tags):
                for edge in bound.edges:
                    if edge in plan.doors:
                        plan.entrance_limits.setdefault(edge, bound.edges)
                        break
        if approach_edges is not None:
            for edge in plan.doors:
                if edge in approach_edges and edge not in plan.entrance_limits:
                    axis = int(edge[2] == "N")
                    plan.entrance_limits[edge] = tuple(e for e in approach_edges
                                                       if e[2] == edge[2] and e[axis] == edge[axis])
        if kind in (None, "house"):
            _back_door(plan, street)
        if kind == "retail":
            # Each shop its own street door, before the shop is fitted out
            # round it.
            _shop_doors(plan, street)
    if mix_kind == "mall":
        # Before furnishing: the openings have to exist for _furnish to keep
        # them clear.
        _open_shopfronts(plan)
    if ground and garage_door:
        if kind == "hangar" and len(plan.rooms) > 1:
            _t_hangar_bay_doors(plan, street)
        else:
            _widen_vehicle_entry(plan, street)
    elif ground and kind in (None, "house"):
        flight = set()
        if stairs is not None:
            sx, sy, sd = stairs
            sdx, sdy = (0, 1) if sd == "N" else (1, 0)
            flight = {(sx + sdx * i, sy + sdy * i) for i in range(STAIR_RUN)}
        _attach_garage(plan, seed, street, flight, profile)
    _make_foyer(plan)
    if private_flats:
        if ground and apartment_access:
            plan.clear_access.update(apartment_access.ground_passages)
        plan.public_path = shared_paths(plan, [stairs] if stairs and level else (),
                                        [stairs] if stairs and level + 1 < levels else (),
                                        ground=ground)
    flat_seed = (f"{seed}:{level}:flats"
                 if settings.apartment_furnishing and kind == "apartment" and not hotel else None)
    _furnish(plan, rng, stairs, street, is_ground=ground, flat_seed=flat_seed)
    if mix_kind == "mall":
        _clear_concourse(plan)
        _place_kiosks(plan, rng, ground)
        # Nothing hangs on a railing or on an opened shopfront: a light or a
        # picture left on the edge of an opening stood in mid-air. A piece
        # records the tile it stands on and the way it faces, so the wall it
        # hangs on is _wall_edge of the two - matching the tile itself missed
        # every piece facing east or south and left 27 of them hanging, where
        # the game's own mall has none.
        edges = plan.railing | plan.open_edge
        kept, unlit = [], set()
        for role, x, y, d in plan.furniture:
            # The lift doors stay whatever they sit on: they are the only way
            # off a floor, and a lift shaft is never on an opened shopfront.
            if role.startswith("elevator_door"):
                kept.append((role, x, y, d))
                continue
            nb = ((x - 1, y) if d == "W" else (x, y - 1) if d == "N"
                  else (x + 1, y) if d == "E" else (x, y + 1))
            # Only what hangs on a wall needs one. Most of a shop stands on
            # the floor and keeps its place whatever is behind it; requiring a
            # wall for everything threw out half the fittings in the mall.
            # The catalog says which is which - plan.wall_pieces only records
            # what _furnish hung itself, and a shop's own wishlist puts up
            # mirrors that never go through it.
            if nb not in plan.void and (
                    not _is_wall_piece(role)
                    or _hangs_on_wall(plan, role, x, y, d, edges)):
                kept.append((role, x, y, d))
                continue
            if role == SWITCH:
                unlit.add(_room_at(plan, x, y))
        plan.furniture = kept
        # The game lights a room from the switch inside it, so one that lost
        # its only switch to an opening is re-wired onto a wall it still has.
        _relight(plan, unlit, edges)
    # A ragged mask can leave a room with none of its squares (a basement
    # under an L-shaped police station did): a room nobody can walk into.
    _renumber(plan)
    return plan


def _tower_rooms(plan: Plan, tower, ground: bool, plant: bool,
                 street: str | None) -> list:
    """Cut an office tower's storey round its core (knoxbuild/tower.py).

    A hall one tile wide runs round the core block: the lift lobby, which the
    stair hall opens onto at its ends and the toilet and riser open off.
    Beyond it the floor is cut pinwheel-fashion into up to four large areas,
    each with a whole side on that hall, so every one gets its own door onto
    the lift lobby and none is reached through another. A side too thin for a room
    (thinner than MIN_ROOM) is no office: it joins the hall. On the ground
    floor the area facing the street is the lobby; on the plant floor every
    area is storage. The lifts are painted over the hall afterwards, by
    build_plan's shafts, and the stair hall by _paint, as plan.core.

    An office area bigger than _room_cap("civic") is cut into strips running
    away from the hall, each no bigger than the cap and each with its own end
    on the hall. Each area's far end runs on past the hall, alongside the next
    area round (N alongside W, E alongside N, S alongside E, W alongside S),
    so the strips there reach the hall down an arm: one tile of hall taken off
    that neighbour. The arms are returned, for build_plan to paint after
    _paint.
    """
    w, h = plan.width, plan.height
    rects = ([tower.stair] + [r for r, _ in tower.lifts]
             + [r for r, _ in tower.service])
    x0 = max(0, min(r[0] for r in rects) - 1)
    y0 = max(0, min(r[1] for r in rects) - 1)
    x1 = min(w - 1, max(r[2] for r in rects) + 1)
    y1 = min(h - 1, max(r[3] for r in rects) + 1)
    x0 = 0 if x0 < MIN_ROOM else x0
    y0 = 0 if y0 < MIN_ROOM else y0
    x1 = w - 1 if w - 1 - x1 < MIN_ROOM else x1
    y1 = h - 1 if h - 1 - y1 < MIN_ROOM else y1
    hall = Room(x0, y0, x1, y1, kind="hall")
    plan.rooms.append(hall)
    areas = {"N": (0, 0, x1, y0 - 1), "E": (x1 + 1, 0, w - 1, y1),
             "S": (x0, y1 + 1, w - 1, h - 1), "W": (0, y0, x0 - 1, h - 1)}
    areas = {s: r for s, r in areas.items() if r[0] <= r[2] and r[1] <= r[3]}
    size = {s: _inside(*r, plan.mask) for s, r in areas.items()}
    lobby = max(areas, default=None, key=lambda s: (
        s == street and size[s] >= MIN_ROOM * MIN_ROOM, size[s]))
    kinds = {s: "storage" if plant else "lobby" if ground and s == lobby
             else "office" for s in areas}
    cap = _room_cap("civic")
    big = [s for s in areas if kinds[s] == "office" and size[s] > cap]
    arms = []
    # The arm for each side, off the neighbour it runs alongside, and what is
    # left of that neighbour.
    beside = {"N": "W", "E": "N", "S": "E", "W": "S"}
    for side in big:
        nb = beside[side]
        if nb not in areas:
            continue
        a0, b0, a1, b1 = areas[nb]
        arm, rest = {"N": ((a0, b0, a1, b0), (a0, b0 + 1, a1, b1)),
                     "E": ((a1, b0, a1, b1), (a0, b0, a1 - 1, b1)),
                     "S": ((a0, b1, a1, b1), (a0, b0, a1, b1 - 1)),
                     "W": ((a0, b0, a0, b1), (a0 + 1, b0, a1, b1))}[side]
        arms.append(arm)
        areas[nb] = rest
    for side, rect in areas.items():
        for piece in (_strips(rect, side, cap) if side in big else [rect]):
            plan.rooms.append(Room(*piece, kind=kinds[side]))
    if ground and lobby is None:
        hall.kind = "lobby"
    for rect, kind in tower.service:
        plan.rooms.append(Room(*rect, kind=kind))
    return arms


def _strips(rect, side: str, cap: int) -> list:
    """`rect` cut across its hall `side` into strips of at most `cap` tiles."""
    x0, y0, x1, y1 = rect
    along = side in "NS"            # the hall runs along x
    lo, hi = (x0, x1) if along else (y0, y1)
    depth = (y1 - y0 + 1) if along else (x1 - x0 + 1)
    length = hi - lo + 1
    # ponytail: deeper than cap / MIN_ROOM (56 tiles off the hall, footprints
    # past ~130 across) a strip MIN_ROOM wide is still over the cap; cutting
    # along the depth too would need a corridor down the strip.
    per = max(MIN_ROOM, cap // depth)
    n = max(1, min(-(-length // per), length // MIN_ROOM))
    out = []
    for i in range(n):
        b = lo + length // n + (i < length % n) - 1
        out.append((lo, y0, b, y1) if along else (x0, lo, x1, b))
        lo = b + 1
    return out


def _tower_entrance(plan: Plan, rng: random.Random, street: str | None,
                    entrances: list | None) -> None:
    """The mapped entrances where they are, and the lobby's door to the street."""
    if entrances:
        _exterior_door(plan, rng, street=street, entrances=entrances)
    lobby = next((i for i, r in enumerate(plan.rooms, 1) if r.kind == "lobby"), None)
    if lobby is None:
        return
    for x, y, d in plan.doors:
        pair = {_room_at(plan, x, y),
                _room_at(plan, x - 1, y) if d == "W" else _room_at(plan, x, y - 1)}
        if pair == {lobby, 0}:
            return
    runs = _outside_runs(plan, lobby)
    if not runs:
        return
    wall = max(runs, key=lambda r: (r[0] == (street or "S"), len(r[1])))[1]
    front = wall[len(wall) // 2]
    plan.doors.append(front)
    if not entrances:
        _more_ways_in(plan, front)


def _hangs_on_wall(plan: Plan, role: str, x: int, y: int, d: str,
                   edges: set) -> bool:
    """Is there really a wall for a piece on (x, y) facing `d` to hang on?

    A wall stands between two different rooms, or at the building's edge.
    Matching the opened shopfronts alone was not enough: a picture hung on a
    line inside one room - where the two sides are the same room and no wall
    was ever drawn - stood in open space just the same. Every tile the piece
    covers has to have one, not just the tile it is anchored on: a two-tile
    display with a wall at one end and the opening at the other left half of
    itself hanging.
    """
    try:
        cells = _cells_for(role, x, y, d)
    except KeyError:
        cells = [(x, y)]
    for cx, cy in cells:
        ex, ey, ed = _wall_edge(cx, cy, d)
        if (ex, ey, ed) in edges:
            return False
        near = (ex, ey)
        far = (ex - 1, ey) if ed == "W" else (ex, ey - 1)
        if near in plan.void or far in plan.void:
            return False
        a, b = _room_at(plan, *near), _room_at(plan, *far)
        if a == b:
            return False
        # Two rooms of the same kind go into the game under the same name,
        # and the game merges rooms by name and draws no wall between them -
        # so a mirror hung where two shoe shops meet had nothing behind it.
        if a and b and plan.rooms[a - 1].kind == plan.rooms[b - 1].kind:
            return False
    return True


def _relight(plan: Plan, unlit: set, edges: set) -> None:
    """Hang a switch back in any room that lost its only one to an opening."""
    have = {_room_at(plan, x, y) for role, x, y, _d in plan.furniture
            if role == SWITCH}
    taken = {_wall_edge(cx, cy, d) for r, x, y, d in plan.furniture
             if _is_wall_piece(r) for cx, cy in _cells_for(r, x, y, d)}
    taken |= plan.wall_pieces
    for idx in sorted(unlit - have):
        if not idx:
            continue
        done = False
        for y in range(plan.height):
            for x in range(plan.width):
                if done or plan.grid[y][x] != idx:
                    continue
                for facing in ("N", "W", "S", "E"):
                    edge = _wall_edge(x, y, facing)
                    if edge in edges or edge in taken:
                        continue
                    nb = ((x, y - 1) if facing == "N" else
                          (x - 1, y) if facing == "W" else
                          (x, y + 1) if facing == "S" else (x + 1, y))
                    # A wall stands where the far side is a different room or
                    # the outside; not across the hole, which has none.
                    if _room_at(plan, *nb) == idx or nb in plan.void:
                        continue
                    plan.furniture.append((SWITCH, x, y, _facing(SWITCH, facing)))
                    taken.add(edge)
                    plan.wall_pieces.add(edge)
                    done = True
                    break
            if done:
                break


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
            while stack and heights[stack[-1]] >= cur:
                top = stack.pop()
                left = stack[-1] + 1 if stack else 0
                area = heights[top] * (x - left)
                if area > best_area:
                    best_area = area
                    best = (left, y - heights[top] + 1, x - left, heights[top])
            stack.append(x)
    return best


ROOF_SLIVER_ACROSS = 3      # a roof piece narrower than this is a strip, not a wing


def _roof_strips(inside: list[list[bool]], by_columns: bool) -> list[tuple[int, int, int, int]]:
    """The footprint cut into rectangles along its columns (or its rows): each
    run of cells in a column joins the run just like it in the column before."""
    h = len(inside)
    w = len(inside[0]) if h else 0
    n_lines, length = (w, h) if by_columns else (h, w)

    def cell(line: int, k: int) -> bool:
        return inside[k][line] if by_columns else inside[line][k]

    done: list[tuple[int, int, int, int]] = []
    open_runs: dict[tuple[int, int], int] = {}      # (start, length) -> first line
    for line in range(n_lines + 1):
        runs = set()
        k = 0
        while line < n_lines and k < length:
            if cell(line, k):
                start = k
                while k < length and cell(line, k):
                    k += 1
                runs.add((start, k - start))
            else:
                k += 1
        for run in list(open_runs):
            if run not in runs:
                first = open_runs.pop(run)
                start, size = run
                done.append((first, start, line - first, size) if by_columns
                            else (start, first, size, line - first))
        for run in runs:
            open_runs.setdefault(run, line)
    return done


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
    greedy = []
    while True:
        found = _largest_rectangle(todo)
        if found is None:
            break
        x0, y0, rw, rh = found
        for y in range(y0, y0 + rh):
            for x in range(x0, x0 + rw):
                todo[y][x] = False
        greedy.append(found)

    # A one- or two-tile sliver left beside the biggest roof is a flat strip
    # hanging off a pitched roof, brown where the two meet. The same footprint
    # cut along its columns or its rows often has none: an L is two blocks, not
    # a block and a sliver. Taken only when it has fewer slivers.
    def slivers(parts) -> int:
        return sum(1 for _x, _y, rw, rh in parts if min(rw, rh) < ROOF_SLIVER_ACROSS)

    best = greedy
    for parts in (_roof_strips(inside, True), _roof_strips(inside, False)):
        if (slivers(parts), len(parts)) < (slivers(best), len(best)):
            best = parts

    rects = []
    for x0, y0, rw, rh in best:
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

