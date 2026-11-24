"""Plan a block's street level once, around the cores of its residential sections."""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, replace
import random
from typing import TYPE_CHECKING

from ..entrances import FacadeDoor, bind_facade, closed_edges, closed_entrance, ground_entrance, residential_entrance
from ..uses import GroundBusiness, ground_businesses
from .access import door_sides, shared_paths, stair_tiles
from .assemble import SHOP_FLOOR_SCALE, build_building
from .core import Plan, Room, mapped_room_tiles
from .furnishing import (
    Building, _blocks, _cells_for, _clear_the_way, _facade_runs, _furnish, _place_windows,
)
from .malls import ANCHOR_KINDS, _refit, _renumber
from .openings import _boundary_edges, _door_spot, _room_at

if TYPE_CHECKING:
    from ..pedestrian_access import DoorApproach

_INWARD = {"N": (0, 1), "S": (0, -1), "W": (1, 0), "E": (-1, 0)}
_OPPOSITE = {"N": "S", "S": "N", "W": "E", "E": "W"}


@dataclass(frozen=True)
class Section:
    x: int
    y: int
    width: int
    height: int
    mask: list[list[bool]] | None
    street: str | None
    entrances: tuple
    lobbies: tuple = ()
    estimated_flats: int | None = None
    mapped_rooms: dict[int, list] | None = None


@dataclass(frozen=True)
class ApartmentSite:
    sections: tuple[Section, ...]
    businesses: tuple[GroundBusiness, ...]
    entrances: tuple = ()
    approaches: tuple[DoorApproach, ...] | None = None
    commercial_ground: bool = False


def site_from_osm(fp, tags, points, entrances, rooms_by_floor, levels, layout_mode,
                  ground_mode, proj, street_side, profile, *, commercial_area=False,
                  dense_retail=False, stock_venues=False):
    from ..apartment_sections import split_sections
    from ..profile import apartment_access_rules
    from ..street_context import _entrances_by_unit, _rooms_by_unit

    street = street_side(fp.x0, fp.y0, fp.width, fp.height)
    surveyed = [tiles for entries in rooms_by_floor.values()
                for ring, _ in _rooms_by_unit(entries, fp, [fp], proj, round_points=False)[0]
                if (tiles := mapped_room_tiles(ring, fp.width, fp.height))]
    parts = split_sections(fp, entrances, levels, layout_mode, street, surveyed=surveyed,
                           rules=apartment_access_rules(profile)) if levels > 1 else [fp]
    portals = _entrances_by_unit(entrances, parts)
    lobbies = [room for room in rooms_by_floor.get(0, ())
               if str(room.get("room") or "").strip().casefold() == "lobby"]
    section_lobbies = _rooms_by_unit(lobbies, fp, parts, proj, round_points=False)
    section_rooms = {z: _rooms_by_unit([r for r in entries if z or r not in lobbies],
                                      fp, parts, proj, round_points=False)
                     for z, entries in rooms_by_floor.items()}
    try:
        declared_flats = int(tags.get("building:flats") or 0)
    except (TypeError, ValueError):
        declared_flats = 0
    sections = tuple(Section(p.x0 - fp.x0, p.y0 - fp.y0, p.width, p.height, p.mask_list(),
                             street_side(p.x0, p.y0, p.width, p.height), tuple(e),
                             tuple(ring for ring, _ in lobby),
                             declared_flats * p.tiles // fp.tiles if declared_flats > 0 else None,
                             {z: per_section[n] for z, per_section in section_rooms.items()
                              if per_section[n]})
                     for n, (p, e, lobby) in enumerate(zip(parts, portals, section_lobbies)))
    local_points = [(tx - fp.x0, ty - fp.y0, item) for x, y, item in points
                    for tx, ty in [fp.transform_point(x, y)]]
    local_entrances = tuple((x - fp.x0, y - fp.y0, t) for x, y, t in entrances)
    businesses = ground_businesses(tags, local_points, local_entrances, mode=ground_mode,
                                   commercial_area=commercial_area)
    homes = {"bedroom", "livingroom", "openplan", "kitchen", "kidsbedroom"}
    surveyed_home = any(kind in homes for by_section in section_rooms.get(0, ())
                        for _ring, kind in by_section)
    uses = str(tags.get("building:use") or "").lower().split(";")
    declared_use = {part.strip() for part in uses if part.strip()}
    declared_retail = bool(declared_use) and declared_use <= {"commercial", "retail"}
    # A map's explicit use of the floor wins. Otherwise keep the commercial
    # ground storey the standard generator would have made.
    commercial_ground = (ground_mode == "auto" and not surveyed_home
                         and (declared_retail or dense_retail or (stock_venues and bool(businesses))))
    if commercial_ground and not businesses:
        businesses = (GroundBusiness("generalstore", "storage", None),)
    return ApartmentSite(sections, businesses, local_entrances,
                         commercial_ground=commercial_ground)


def _site_entrances(site):
    points = list(site.entrances or tuple(
        (s.x + x, s.y + y, tags) for s in site.sections for x, y, tags in s.entrances))
    seen = {(x, y) for x, y, _ in points}
    for business in site.businesses:
        if business.entrance is not None and business.entrance not in seen:
            points.append((*business.entrance, {"entrance": "shop", "name": business.name}))
            seen.add(business.entrance)
    return points


def _edge_at(edge, dx, dy):
    x, y, direction = edge
    return x + dx, y + dy, direction


def _section_mask(section):
    return section.mask if section.mask is not None else [[True] * section.width] * section.height


def _section_portals(section, runs, closed, shops):
    def local(bound):
        return FacadeDoor(bound.side, tuple(_edge_at(e, -section.x, -section.y) for e in bound.edges))

    portals = []
    for x, y, tags in section.entrances:
        gx, gy = section.x + x, section.y + y
        if closed_entrance(tags) or (round(gx, 7), round(gy, 7)) in shops:
            continue
        if bound := bind_facade(runs, gx, gy):
            portals.append((x, y, {**tags, "_knox_entrance_facade": local(bound)}))
    mask = _section_mask(section)
    for bound in closed:
        bound = local(bound)
        x, y, _ = bound.edges[0]
        if any(0 <= tx < section.width and 0 <= ty < section.height and mask[ty][tx]
               for tx, ty in door_sides(bound.edges[0])):
            portals.append((x, y, {"entrance": "no", "_knox_entrance_facade": bound}))
    return portals


def _section_approaches(section, approaches, mixed, rear):
    if approaches is None:
        return None
    eligible = []
    mask = _section_mask(section)
    for approach in approaches:
        edge = _edge_at(approach.edge, -section.x, -section.y)
        a, b = door_sides(edge)
        ix, iy = b if approach.side in ("N", "W") else a
        if not (0 <= ix < section.width and 0 <= iy < section.height and mask[iy][ix]):
            continue
        cross, span = (ix, section.width) if approach.side in ("N", "S") else (iy, section.height)
        courtyard = not approach.street and approach.path
        rank = (mixed and not courtyard, mixed and not (courtyard and approach.side == rear),
                approach.cost // 6, not approach.path,
                abs(cross + 0.5 - span / 2), approach.cost)
        eligible.append((rank, edge))
    return tuple(edge for _, edge in sorted(eligible))


def _rect_at(rect, dx, dy):
    x0, y0, x1, y1 = rect
    return x0 + dx, y0 + dy, x1 + dx, y1 + dy


def _parties(site, party, levels):
    masks = [_section_mask(s) for s in site.sections]
    owned = {(section.x + x, section.y + y): i
             for i, (section, mask) in enumerate(zip(site.sections, masks))
             for y, row in enumerate(mask) for x, inside in enumerate(row) if inside}
    for i, (section, mask) in enumerate(zip(site.sections, masks)):
        walls = {}
        for y, row in enumerate(mask):
            for x, inside in enumerate(row):
                if not inside:
                    continue
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    edge = (max(x, nx), max(y, ny), "N" if x == nx else "W")
                    where = _edge_at(edge, section.x, section.y)
                    neighbour = owned.get((section.x + nx, section.y + ny))
                    if neighbour is not None and neighbour != i:
                        walls[edge] = levels
                    elif where in party:
                        walls[edge] = party[where]
        yield walls


def _join_floor(width, height, level, sections, profile, party, flat_seed):
    floor = Plan(width, height, kind="apartment", profile=profile, private_flats=True)
    floor.grid = [[0] * width for _ in range(height)]
    floor.party = {edge for edge, height in party.items() if height > level}
    floor.flat_furnishing_seed = flat_seed
    unit_offset = 0
    for section, part in sections:
        if level >= len(part.storeys):
            continue
        src = part.storeys[level]
        floor.unmapped_room_tiles += src.unmapped_room_tiles
        dx, dy = section.x, section.y
        offset = len(floor.rooms)
        for r in src.rooms:
            floor.rooms.append(replace(r, x0=r.x0 + dx, x1=r.x1 + dx,
                                       y0=r.y0 + dy, y1=r.y1 + dy,
                                       unit=r.unit + unit_offset if r.unit else 0))
        unit_offset += max((r.unit for r in src.rooms), default=0)
        for y, row in enumerate(src.grid, dy):
            for x, rid in enumerate(row, dx):
                if rid:
                    floor.grid[y][x] = offset + rid
        floor.doors.extend(_edge_at(e, dx, dy) for e in src.doors)
        floor.entrance_limits.update((_edge_at(e, dx, dy),
                                      tuple(_edge_at(option, dx, dy) for option in allowed))
                                     for e, allowed in src.entrance_limits.items())
        floor.blocked_entrances.update(_edge_at(e, dx, dy) for e in src.blocked_entrances)
        floor.furniture.extend((role, x + dx, y + dy, d) for role, x, y, d in src.furniture)
        for key in ("railing", "open_edge", "wall_pieces"):
            getattr(floor, key).update(_edge_at(e, dx, dy) for e in getattr(src, key))
        for key in ("holes", "void", "sleeve", "public_path", "stair_steps", "clear_access"):
            getattr(floor, key).update((x + dx, y + dy) for x, y in getattr(src, key))
        floor.shafts.extend((_rect_at(rect, dx, dy), _edge_at(e, dx, dy))
                            for rect, e in src.shafts)
        floor.stalls.extend(_edge_at(e, dx, dy) for e in src.stalls)
    return floor


def _facades(plan):
    result = defaultdict(list)
    for side, run in _facade_runs(plan.grid):
        for x, y, direction, ix, iy in run:
            edge = x, y, direction
            room = plan.rooms[plan.grid[iy][ix] - 1]
            dx, dy = _INWARD[side]
            nx, ny = ix + dx, iy + dy
            if (room.unit and edge not in plan.party and edge not in plan.blocked_entrances
                    and 0 <= nx < plan.width
                    and 0 <= ny < plan.height):
                inward = plan.grid[ny][nx]
                if inward and plan.rooms[inward - 1].unit == room.unit:
                    result[room.unit].append((side, edge))
    return result


def _allocate(plan, businesses, street, room_size, *, keep_home, runs, approaches=None,
              commercial_ground=False):
    """Give each venue frontage first, then let wider ones use an adjacent bay."""
    facades = _facades(plan)
    areas = defaultdict(int)
    protected = {r.unit for r in plan.rooms if r.surveyed}
    for row in plan.grid:
        for rid in row:
            if rid and (unit := plan.rooms[rid - 1].unit):
                areas[unit] += 1
    available = {u for u in facades if areas[u] >= 6 and u not in protected}
    slots = len(areas) - int(keep_home)
    assignments, missed, failures = [], [], {}
    for business in sorted(businesses, key=lambda b: (b.entrance is None, b.position is None)):
        pos = business.entrance or business.position

        def distance(face):
            side, edge = face
            x, y, _ = edge
            nearest = (x - pos[0]) ** 2 + (y - pos[1]) ** 2 if pos else 0
            if business.entrance is None and approaches is not None:
                approach = approaches[edge]
                return not approach.street, nearest, approach.cost
            return nearest, street is not None and side != street

        berth = bind_facade(runs, *business.entrance) if business.entrance is not None else None
        choices = {u: [face for face in facades[u]
                       if ((approaches is None or face[1] in approaches) if business.entrance is None
                           else (berth is not None and face[0] == berth.side and face[1] in berth.edges))]
                   for u in available}
        choices = {u: faces for u, faces in choices.items() if faces}
        if not choices or slots <= 0:
            missed.append(business.name or business.front)
            if business.entrance is not None:
                failures[business.entrance] = "no_commercial_space_on_facade"
            continue
        unit = min(choices, key=lambda u: (min(map(distance, choices[u])), -areas[u], u))
        side, edge = min(choices[unit], key=distance)
        available.remove(unit)
        slots -= 1
        assignments.append((business, {unit}, side, edge))

    neighbours = defaultdict(set)
    for a, b in _boundary_edges(plan):
        ua, ub = plan.rooms[a - 1].unit, plan.rooms[b - 1].unit
        if ua and ub and ua != ub:
            neighbours[ua].add(ub)
            neighbours[ub].add(ua)
    for business, units, side, entrance in assignments:
        if (slots <= 0 or business.front not in ANCHOR_KINDS
                or 2 * SHOP_FLOOR_SCALE * room_size <= sum(areas[u] for u in units)):
            continue
        candidates = (set().union(*(neighbours[u] for u in units)) & available)
        same_side = [u for u in candidates if any(face == side for face, _ in facades[u])]
        if same_side:
            x, y, _ = entrance
            extra = min(same_side, key=lambda u: (
                min((ex - x) ** 2 + (ey - y) ** 2
                    for face, (ex, ey, _d) in facades[u] if face == side),
                -areas[u], u))
            units.add(extra)
            available.remove(extra)
            slots -= 1
    if commercial_ground:
        # Preserve venue doors first. Give spare bays a street entrance,
        # then absorb interior bays into an adjoining commercial space.
        for unit in sorted(available):
            faces = [face for face in facades[unit] if approaches is None or face[1] in approaches]
            if faces:
                side, entrance = min(faces, key=lambda f: (
                    not approaches[f[1]].street if approaches is not None else f[0] != street,
                    approaches[f[1]].cost if approaches is not None else f[1]))
                assignments.append((GroundBusiness("generalstore", "storage", None), {unit}, side, entrance))
        remaining = set(areas) - protected - {u for _b, us, _s, _e in assignments for u in us}
        while remaining:
            frontier = [(u, i) for i, (_business, units, _side, _edge) in enumerate(assignments)
                        for u in set().union(*(neighbours[v] for v in units)) & remaining]
            if not frontier:
                missed.append("commercial space without a reachable frontage")
                break
            u, i = min(frontier, key=lambda pair: (
                sum(areas[n] for n in assignments[pair[1]][1]), pair))
            assignments[i][1].add(u)
            remaining.remove(u)
    return assignments, missed, failures


def _connected(cells):
    if not cells:
        return False
    start = min(cells)
    seen, queue = {start}, deque([start])
    while queue:
        x, y = queue.popleft()
        for p in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if p in cells and p not in seen:
                seen.add(p)
                queue.append(p)
    return len(seen) == len(cells)


def _convert(plan, business, units, index, side, entrance, rng):
    by_room = defaultdict(set)
    for y, row in enumerate(plan.grid):
        for x, rid in enumerate(row):
            if rid and plan.rooms[rid - 1].unit in units:
                by_room[rid].add((x, y))
    cells = set().union(*by_room.values())
    plan.doors = [door for door in plan.doors if not cells.intersection(door_sides(door))]
    plan.open_edge = {edge for edge in plan.open_edge if not cells.intersection(door_sides(edge))}
    door_cell = next(p for p in door_sides(entrance) if p in cells)
    dx, dy = _INWARD[side]
    approach = {door_cell, (door_cell[0] + dx, door_cell[1] + dy)}
    # A rear room is useful only when taking it out leaves a single sales floor.
    back = set()
    for tiles in sorted(by_room.values(), key=lambda ts: (-len(ts), min(ts))):
        if (len(tiles) >= 6 and len(tiles) <= len(cells) // 3
                and not approach.intersection(tiles) and _connected(cells - tiles)):
            back = tiles
            break

    def paint(tiles, kind):
        xs, ys = zip(*tiles)
        plan.rooms.append(Room(min(xs), min(ys), max(xs), max(ys),
                               kind=kind, fixed=True, business=index))
        for x, y in tiles:
            plan.grid[y][x] = len(plan.rooms)
        return len(plan.rooms)

    front = paint(cells - back, business.front)
    if back:
        rear = paint(back, business.back)
        wall = _boundary_edges(plan)[(front, rear)]
        plan.doors.append(_door_spot(wall, 1, rng)[0])
    plan.doors.append(entrance)


def _clear_reserved(plan):
    plan.furniture = [f for f in plan.furniture if not (
        _blocks(f[0]) and plan.public_path.intersection(_cells_for(*f)))]


def entrance_report(site, plan=None, shops=None, failures=None, *, runs=()):
    """One result per supported ground-floor entrance, including closed points."""
    outside = set()
    if plan is not None:
        for door in plan.doors:
            a, b = (_room_at(plan, *tile) for tile in door_sides(door))
            if bool(a) != bool(b) and (plan.rooms[(a or b) - 1].is_core
                                     or plan.rooms[(a or b) - 1].apartment_entry):
                outside.add(door)
    points = []
    matches = []
    for x, y, tags in _site_entrances(site):
        if not ground_entrance(tags):
            continue
        shop = tags.get("entrance") == "shop" or (x, y) in (shops or {}) or (x, y) in (failures or {})
        if not (closed_entrance(tags) or residential_entrance(tags)
                or tags.get("entrance") == "main" or shop):
            continue
        bound = bind_facade(runs, x, y)
        if bound is not None and not shop and not closed_entrance(tags):
            matches.extend((rank, len(points), edge) for rank, edge in enumerate(bound.edges)
                           if edge in outside)
        points.append((x, y, tags, shop, bound))

    # A nearby door should never take precedence over another marker's exact match.
    residential = {}
    for _rank, point, edge in sorted(matches):
        if point not in residential and edge in outside:
            residential[point] = edge
            outside.remove(edge)
    report = []
    for point, (x, y, tags, shop, bound) in enumerate(points):
        actual = None
        status = "unplaced"
        if closed_entrance(tags):
            status, reason = "closed", "mapped_entrance_closed"
        elif plan is None:
            reason = "building_layout_failed"
        elif bound is None:
            reason = "no_facade_near_mapped_point"
        elif all(e in plan.party for e in bound.edges):
            reason = "facade_is_shared_wall"
        elif all(e in plan.party or e in plan.blocked_entrances for e in bound.edges):
            reason = "mapped_facade_blocked"
        elif shop:
            business = (shops or {}).get((x, y))
            if business is not None:
                for edge in bound.edges:
                    if edge in plan.doors and any(
                        (i := _room_at(plan, *tile)) and plan.rooms[i - 1].business == business
                        for tile in door_sides(edge)):
                        actual = edge
                        break
            reason = (failures or {}).get((x, y), "no_matching_commercial_door"
                                          if business is not None else "no_matching_ground_business")
        else:
            actual = residential.get(point)
            reason = "no_residential_door_on_facade"
        if actual is not None:
            status = "placed" if actual == bound.edges[0] else "snapped"
            reason = None
        report.append({"position": [x, y], "kind": tags.get("entrance"),
                       "ref": tags.get("ref") or tags.get("name") or tags.get("addr:flats"),
                       "facade": bound.side if bound else None, "status": status,
                       "reason": reason, "door": list(actual) if actual is not None else None})
    return tuple(report)


def build_site(site, width, height, levels, settings, profile, party, seed, street):
    sections = []
    if settings.apartment_layout == "classic":
        settings = replace(settings, apartment_layout="auto")
    source = _site_entrances(site)
    mask = [[False] * width for _ in range(height)]
    for section in site.sections:
        for y, row in enumerate(_section_mask(section), section.y):
            mask[y][section.x:section.x + section.width] = [
                previous or inside for previous, inside in
                zip(mask[y][section.x:section.x + section.width], row)]
    runs = _facade_runs(mask)
    closed = [bound for x, y, tags in source if ground_entrance(tags) and closed_entrance(tags)
              and (bound := bind_facade(runs, x, y)) is not None]
    shops = {(round(x, 7), round(y, 7)) for venue in site.businesses if venue.entrance is not None
             for x, y in (venue.entrance,)}
    frontage = Counter(a.side for a in site.approaches or () if a.street)
    rear = _OPPOSITE[frontage.most_common(1)[0][0]] if frontage else None
    for section, walls in zip(site.sections, _parties(site, party, levels)):
        part = build_building(section.width, section.height, levels, kind="apartment",
                              commercial=True, seed=seed + 31 * len(sections),
                              mask=section.mask, settings=settings, street=section.street,
                              entrances=_section_portals(section, runs, closed, shops),
                              profile=profile, party=walls,
                              mapped_lobbies=section.lobbies,
                              mapped=section.mapped_rooms,
                              section_flats=section.estimated_flats,
                              approach_edges=_section_approaches(section, site.approaches,
                                                                bool(site.businesses), rear))
        sections.append((section, part))
    count = max(len(part.storeys) for _section, part in sections)
    floors = [_join_floor(width, height, level, sections, profile, party,
                         f"{seed}:{level}:flats" if settings.apartment_furnishing else None)
              for level in range(count)]
    flights = {level: [_edge_at(f, s.x, s.y) for s, part in sections for f in part.stairs_at(level)]
               for level in range(count - 1)}
    building = Building(width, height, floors, profile=profile, extra_stairs=flights,
                        whole_ground=True,
                        unplaced_lift_cores=sum(b.unplaced_lift_cores for _, b in sections))
    ground = floors[0]
    ground.blocked_entrances.update(closed_edges(runs, source))
    approaches = {a.edge: a for a in site.approaches} if site.approaches is not None else None
    keep_home = not any(r.unit for floor in floors[1:] for r in floor.rooms)
    assignments, missed, failures = _allocate(ground, site.businesses, street, settings.room_size,
                                              keep_home=keep_home, runs=runs, approaches=approaches,
                                              commercial_ground=site.commercial_ground)
    rng = random.Random(f"{seed}:ground")
    mapped_shops = {}
    for index, (business, units, side, edge) in enumerate(assignments, 1):
        _convert(ground, business, units, index, side, edge, rng)
        if business.entrance is not None:
            mapped_shops[business.entrance] = index
            ground.entrance_limits[edge] = bind_facade(runs, *business.entrance).edges
        elif approaches is not None:
            axis = int(edge[2] == "N")
            ground.entrance_limits[edge] = tuple(e for e, a in approaches.items()
                                                 if a.side == side and e[axis] == edge[axis])
    building.unplaced_businesses = tuple(missed)
    _renumber(ground)
    _refit(ground)
    if assignments:
        ground.furniture.clear()
        ground.wall_pieces.clear()
        ground.stalls.clear()
        ground.sleeve.clear()
        ground.public_path = shared_paths(ground, to_above=building.stairs_at(0), ground=True)
        ground.public_path.update(p for flight in building.stairs_at(0) for p in stair_tiles(flight))
        _furnish(ground, rng, street=street, flat_seed=ground.flat_furnishing_seed,
                 additional_stairs=tuple(building.stairs_at(0)))
    _place_windows(building, "apartment", shop_ground=bool(assignments))
    _clear_the_way(building)
    for level, floor in enumerate(floors):
        floor.public_path = shared_paths(floor, building.stairs_at(level - 1),
                                         building.stairs_at(level), ground=level == 0)
        floor.public_path.update(p for flight in building.stairs_at(level) for p in stair_tiles(flight))
        _clear_reserved(floor)
    building.entrance_report = entrance_report(site, ground, mapped_shops, failures, runs=runs)
    if approaches is not None:
        mapped_doors = {tuple(item["door"]) for item in building.entrance_report if item["door"]}
        inferred = []
        for edge in ground.doors:
            if edge in mapped_doors or edge not in approaches:
                continue
            a, b = (_room_at(ground, *tile) for tile in door_sides(edge))
            if bool(a) == bool(b):
                continue
            room = ground.rooms[(a or b) - 1]
            approach = approaches[edge]
            inferred.append({"source": "inferred", "door": list(edge), "facade": approach.side,
                             "kind": "shop" if room.business else "staircase",
                             "street": approach.street, "near_path": approach.path,
                             "walk_cost": approach.cost})
        building.entrance_report += tuple(inferred)
    return building
