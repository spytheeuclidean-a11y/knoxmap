"""Choose residential sections and the shared space that their flats open onto."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from heapq import heappop, heappush
import random

from .entrances import Edge, closed_edges, closed_entrance, entrance_facade, ground_entrance, residential_entrance
from .footprint import Footprint, split_at
from .layout.access import door_sides, stair_tiles
from .layout.core import MIN_ROOM, STAIR_RUN
from .layout.furnishing import (
    CORE_WIDE, ELEVATOR_MIN_SIDE, SHAFT_SIZE, _facade_runs, _pick_corridor, _stairs_in_core,
)
from .layout.lift_core import LiftCore, candidates as lift_candidates
from .layout.oriented import OrientedHall, footprint_axis, project
from .profile import ApartmentAccessRules, DEFAULT_APARTMENT_ACCESS

# Leave a clear tile for the landing at either end of the flight.
MIN_CORE_LENGTH = STAIR_RUN + 2
LANDING_LENGTH = MIN_CORE_LENGTH
LANDING_WIDTH = 2
Rect = tuple[int, int, int, int]
Tile = tuple[int, int]


def tiles_in(rect: Rect):
    x0, y0, x1, y1 = rect
    return ((x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1))


def _adjacent(tile: Tile):
    x, y = tile
    return ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))


@dataclass(frozen=True)
class AccessLayout:
    landing: Rect
    entries: tuple[Edge, ...]
    spine: Rect | None = None
    ground_passages: frozenset[Tile] = frozenset()
    oriented: OrientedHall | None = None
    lift: LiftCore | None = None


def _long_access(width, height, mask, street, runs, portals, blocked, approach_edges,
                 lift, reserved, *, compact=False, balcony=False):
    """A narrow hallway along the building, with local access to a vertical core."""
    facade = {(e[3], e[4]) for _side, run in runs for e in run}
    interior = [[(mask is None or mask[y][x]) and (x, y) not in facade and (x, y) not in reserved
                 for x in range(width)] for y in range(height)]
    spine = _pick_corridor(width, height, interior, random.Random(0), (LANDING_WIDTH,))
    if spine is None:
        return None
    along_y = (spine[3] - spine[1]) > (spine[2] - spine[0])
    start, end, low, high = ((spine[1], spine[3], spine[0], spine[2]) if along_y
                             else (spine[0], spine[2], spine[1], spine[3]))
    length = LANDING_LENGTH + (SHAFT_SIZE + 1 if lift else 0)
    depth = width if along_y else height
    # Reserve dwelling space at both ends, including at a shared section wall.
    # One boundary tile was already taken out by the interior mask.
    cap = min(max(4, depth // 3), (end - start + 1 - length) // 2 + 1)
    start += max(0, cap - 1)
    end -= max(0, cap - 1)
    if compact:
        frontage = max(length, round(max(width, height) * 0.55))
        if end - start + 1 > frontage:
            start += (end - start + 1 - frontage) // 2
            end = start + frontage - 1
    spine = (low, start, high, end) if along_y else (start, low, end, high)

    def inside(x, y):
        return 0 <= x < width and 0 <= y < height and interior[y][x]

    if lift:
        floor = {(x, y) for y in range(height) for x in range(width)
                 if mask is None or mask[y][x]}
        return _lifted_access(width, height, inside, street, runs, portals, blocked,
                              approach_edges, reserved, floor, set(tiles_in(spine)),
                              (0, 1) if along_y else (1, 0), compact=compact,
                              balcony=balcony, spine=spine)

    # Keep the flight central so both halves of the floor can reach it.
    landing = None
    for a in sorted(range(start, end - length + 2), key=lambda a: abs(2 * a + length - 1 - start - end)):
        z = a + length - 1
        rect = (low, a, high, z) if along_y else (a, low, z, high)
        if all(inside(x, y) for x, y in tiles_in(rect)):
            landing = rect
            break
    if landing is None:
        return None

    shared = set(tiles_in(spine)) | set(tiles_in(landing))
    return _route_access(width, height, inside, street, runs, portals, blocked, approach_edges,
                         reserved, landing, shared, spine=spine)


def _angled_access(width, height, mask, street, runs, portals, blocked, approach_edges,
                   lift, reserved, axis, mode, balcony=False):
    floor = {(x, y) for y, row in enumerate(mask) for x, kept in enumerate(row) if kept}
    facade = {(e[3], e[4]) for _side, run in runs for e in run}
    interior = floor - facade - reserved
    uv = {tile: project(tile, axis) for tile in floor}
    u0, u1 = min(u for u, _ in uv.values()), max(u for u, _ in uv.values())
    v0, v1 = min(v for _, v in uv.values()), max(v for _, v in uv.values())
    cm, centre = (u0 + u1) / 2, (v0 + v1) / 2
    span, depth = u1 - u0, v1 - v0
    use_spine = mode == "corridor" or (mode == "auto" and span >= max(3 * LANDING_LENGTH, 1.4 * depth))
    length = LANDING_LENGTH
    along_y = abs(axis[1]) > abs(axis[0])
    shared = set()
    if use_spine:
        cap = max(0, min((span - length) / 3, max(3, depth / 3)))
        shared = {p for p in interior if u0 + cap <= uv[p][0] <= u1 - cap
                  and abs(uv[p][1] - centre) <= 1.6}
    if lift:
        if not shared:
            shared = {p for p in interior if abs(uv[p][0] - cm) <= LANDING_LENGTH / 2
                      and abs(uv[p][1] - centre) <= 1.6}
        hall = OrientedHall(axis, centre, frozenset(shared))
        return _lifted_access(width, height, lambda i, j: (i, j) in interior, street,
                              runs, portals, blocked, approach_edges, reserved, floor, shared,
                              axis, compact=not use_spine, balcony=balcony,
                              oriented=hall, limits=(u0, u1, v0, v1))
    trials = 0
    for x, y in sorted(interior, key=lambda p: ((uv[p][0] - cm) ** 2 + 3 *
                                               (uv[p][1] - centre) ** 2, p)):
        for vertical in (along_y, not along_y):
            w, h = (LANDING_WIDTH, length) if vertical else (length, LANDING_WIDTH)
            x0, y0 = x - (w - 1) // 2, y - (h - 1) // 2
            landing = x0, y0, x0 + w - 1, y0 + h - 1
            cells = set(tiles_in(landing))
            if not cells <= interior:
                continue
            trials += 1
            hall = OrientedHall(axis, centre, frozenset(shared))
            if access := _route_access(width, height, lambda i, j: (i, j) in interior,
                                       street, runs, portals, blocked, approach_edges,
                                       reserved, landing, shared | cells, oriented=hall,
                                       limits=(u0, u1, v0, v1)):
                return access
            if trials >= 8:
                return None
    return None


def _facade_passage(door, start, reachable, shared, axis, limits):
    """Follow the inward facade direction between the threshold and hall."""
    u, v = project(door, axis)
    u0, u1, v0, v1 = limits
    dx, dy = axis
    faces = ((abs(u - u0), dx, dy), (abs(u - u1), -dx, -dy),
             (abs(v - v0), -dy, dx), (abs(v - v1), dy, -dx))
    _, nx, ny = min(faces, key=lambda face: face[0])
    queue = [(0., start)]
    distance = {start: 0.}
    previous = {start: None}
    while queue:
        cost, tile = heappop(queue)
        if cost > distance[tile]:
            continue
        if tile in shared:
            path = []
            while tile is not None:
                path.append(tile)
                tile = previous[tile]
            return [door, *path[-1:0:-1]]
        for p in _adjacent(tile):
            if p not in reachable:
                continue
            drift = abs((p[0] - door[0]) * ny - (p[1] - door[1]) * nx)
            # A route may bend around an obstruction, but its arrival at
            # the hall should stay close to the line set by the facade.
            total = cost + 1 + min(1.5, .22 * drift) + (1.5 * drift if p in shared else 0)
            if total < distance.get(p, float("inf")):
                distance[p] = total
                previous[p] = tile
                heappush(queue, (total, p))
    return None


def _lifted_access(width, height, inside, street, runs, portals, blocked, approach_edges,
                   reserved, floor, shared, axis, *, compact, balcony, **layout):
    for outdoor in (True, False) if balcony else (False,):
        for core in lift_candidates(shared, floor, reserved, blocked, axis,
                                    compact=compact, balcony=outdoor):
            occupied = (set(tiles_in(core.stairs)) | set(tiles_in(core.shaft[0]))
                        | core.lobby | core.balcony)
            # Reject a wing that isolates part of the floor from the corridor
            # before any of that space is assigned to flats.
            remaining = floor - occupied - shared
            pending = list(shared)
            while pending and remaining:
                for tile in _adjacent(pending.pop()):
                    if tile in remaining:
                        remaining.remove(tile)
                        pending.append(tile)
            if remaining:
                continue
            if access := _route_access(width, height, inside, street, runs, portals, blocked,
                                       approach_edges, reserved | occupied, core.stairs, shared,
                                       lift=core, **layout):
                return access
    return None


def _route_access(width, height, inside, street, runs, portals, blocked, approach_edges,
                  reserved, landing, shared, *, spine=None, oriented=None, limits=None, lift=None):
    flight = None if lift else _stairs_in_core(landing, hug_wall=True)
    unavailable = set(stair_tiles(flight)[2:-1]) if flight else set()
    if oriented is not None:
        safe = shared - unavailable
        if not safe:
            return None
        seen = {stair_tiles(flight)[-1] if flight else min(safe)}
        pending = list(seen)
        while pending:
            for q in _adjacent(pending.pop()):
                if q in safe and q not in seen:
                    seen.add(q)
                    pending.append(q)
        if seen != safe:
            return None
    parents = dict.fromkeys(sorted(shared - unavailable))
    queue = deque(parents)
    while queue:
        current = queue.popleft()
        for q in _adjacent(current):
            if inside(*q) and q not in reserved and q not in unavailable and q not in parents:
                parents[q] = current
                queue.append(q)

    inward = {"N": (0, 1), "S": (0, -1), "W": (1, 0), "E": (-1, 0)}
    edges = {}
    for side, run in runs:
        dx, dy = inward[side]
        for i, (x, y, direction, ix, iy) in enumerate(run):
            edge = x, y, direction
            next_tile = ix + dx, iy + dy
            if oriented is not None and next_tile not in parents:
                # Just inside a stepped facade the way in can turn before it
                # reaches the first tile that is clear of the outside walls.
                next_tile = next((p for p in _adjacent((ix, iy)) if p in parents), next_tile)
            if edge not in blocked and (ix, iy) not in reserved and next_tile in parents:
                edges[edge] = side, (ix, iy), 0 < i < len(run) - 1, next_tile

    def passage(edge):
        _side, at, _straight, p = edges[edge]
        path = [at]
        while p is not None and p not in shared:
            path.append(p)
            p = parents[p]
        return path

    entries = []
    for x, y, tags in portals:
        bound = entrance_facade(runs, x, y, tags)
        if bound is not None:
            matching = [e for e in bound.edges if e in edges and edges[e][0] == bound.side]
            if matching:
                entries.append(min(matching, key=lambda e: not edges[e][2]))
    if not portals and edges:
        if approach_edges is None:
            entries.append(min(edges, key=lambda e: (
                edges[e][0] != street, not edges[e][2], len(passage(e)),
                abs(edges[e][1][0] - width // 2) + abs(edges[e][1][1] - height // 2), e)))
        else:
            reachable = [e for e in approach_edges if e in edges]
            if reachable:
                entries.append(reachable[0] if oriented else min(reachable, key=lambda e: not edges[e][2]))
    if not entries:
        return None
    passages = []
    for edge in entries:
        side, at, _straight, start = edges[edge]
        path = (_facade_passage(at, start, parents, shared, oriented.axis, limits)
                if oriented is not None else None)
        path = path or passage(edge)
        end = next((p for p in _adjacent(path[-1]) if p in shared and p not in unavailable), None)
        # A single front door can still lead into a two-tile vestibule.
        # Reserve a parallel lane for each straight piece of its route.
        facade = {tile for face, tile, _straight, _start in edges.values() if face == side}
        clear = parents.keys() | facade
        lane = set(path)
        # Keep the wall at the canonical N/W door edge straight when the
        # adjacent facade square fits. The exporter can then keep the pin.
        prior = (at[0] - (edge[2] == "N"), at[1] - (edge[2] == "W"))
        for a, b in zip(path, path[1:] + ([end] if end else [])):
            dx, dy = b[0] - a[0], b[1] - a[1]
            if abs(dx) + abs(dy) != 1:
                continue
            options = [{(x - turn * dy, y + turn * dx) for x, y in (a, b)}
                       for turn in (1, -1)]
            choices = [row for row in options if row <= clear]
            if choices:
                lane.update(min(choices, key=lambda row: (a == at and prior not in row,
                                                           len(row - lane - shared))))
        passages.extend(lane - shared)
    return AccessLayout(landing, tuple(dict.fromkeys(entries)), spine,
                        frozenset(passages), oriented, lift)


def _residential_entrances(entrances):
    """Distinct mapped stairwells at ground level, with one portal per stairwell."""
    found = {}
    for x, y, tags in entrances:
        if not residential_entrance(tags) or closed_entrance(tags) or not ground_entrance(tags):
            continue
        key = tags.get("ref") or tags.get("addr:flats") or (round(x), round(y))
        found.setdefault(key, (x, y, tags))
    return list(found.values())


def split_sections(fp: Footprint, entrances, levels: int, mode: str,
                   street: str | None, *, surveyed=(),
                   rules: ApartmentAccessRules = DEFAULT_APARTMENT_ACCESS) -> list[Footprint]:
    """Keep mapped stairwells and fit plausible additional sections where possible."""
    from .street_context import _entrances_by_unit

    long_axis = fp.width >= fp.height
    span, depth = sorted((fp.width, fp.height), reverse=True)
    known = _residential_entrances(entrances)

    def viable(edges, along_x):
        axis = 0 if along_x else 1
        if any(min(p[axis] for p in room) < edge <= max(p[axis] for p in room)
               for room in surveyed for edge in edges[1:-1]):
            return None
        parts = split_at(fp, edges, along_x=along_x)
        if len(parts) != len(edges) - 1 or sum(part.tiles for part in parts) != fp.tiles:
            return None
        for part, portals, mapped in zip(parts, _entrances_by_unit(entrances, parts),
                                         _entrances_by_unit(known, parts)):
            if len(mapped) > 1:
                return None
            if access_layout(part.width, part.height, part.mask_list(), levels, mode,
                             street, portals, rules=rules) is None:
                return None
        return parts

    if mode == "auto" and levels <= rules.compact_landing_max_levels and span >= 3 * depth:
        # Treat the mapped count as a lower bound. Only supplement it if the
        # footprint fits extra cores and the known entrances get distinct sections.
        count = round(span / max(2 * depth, LANDING_LENGTH * 2))
        if count > max(1, len(known)):
            edges = [round(i * span / count) for i in range(count + 1)]
            if parts := viable(edges, long_axis):
                return parts

    if len(known) >= 2:
        # Opposite facades can put different entrances at the same coordinate
        # along the long axis. Try a cut in the other direction as well.
        for along_x in (long_axis, not long_axis):
            length = fp.width if along_x else fp.height
            positions = sorted(x - fp.x0 if along_x else y - fp.y0 for x, y, _ in known)
            edges = [0]
            for i, (a, b) in enumerate(zip(positions, positions[1:]), 1):
                low, high = round(a) + MIN_ROOM + 1, round(b) - MIN_ROOM
                if low > high:
                    break
                edges.append(max(low, min(high, round(i * length / len(known)))))
            else:
                if parts := viable(edges + [length], along_x):
                    return parts
    return [fp]


def access_layout(width: int, height: int, mask, levels: int, mode: str,
                  street: str | None, entrances, party=(), *,
                  rules: ApartmentAccessRules = DEFAULT_APARTMENT_ACCESS,
                  inferred: bool = False, approach_edges: tuple | None = None,
                  reserved=frozenset()):
    """Fit a continuous landing or corridor starting at a facade door."""
    marked = [(x, y, tags) for x, y, tags in entrances
              if not closed_entrance(tags) and ground_entrance(tags)]
    known = [e for e in marked if residential_entrance(e[2])]
    if not known:
        known = [e for e in marked if e[2].get("entrance") == "main"]
    requested_mode = mode
    use_spine = mode == "corridor"
    if mode == "auto":
        span, depth = max(width, height), min(width, height)
        long_section = span >= max(3 * LANDING_LENGTH, 2 * depth)
        if not long_section and span >= 5 * LANDING_LENGTH:
            # A large, broadly rectangular section also needs more door
            # frontage. Diagonal footprints inflate the bounding box alone.
            long_section = mask is None or sum(map(sum, mask)) >= 0.8 * width * height
        use_spine = long_section or len(known) > 1
        mode = ("corridor" if use_spine
                or levels > rules.compact_landing_max_levels else "landing")

    axis = footprint_axis(mask)
    lift = levels > 1 and levels >= rules.lift_from_levels and min(width, height) >= ELEVATOR_MIN_SIDE
    runs = (_facade_runs(mask if mask is not None else [[True] * width] * height)
            if entrances or mode == "corridor" or axis or lift else ())
    blocked = closed_edges(runs, entrances) if runs else set()
    mapped = bool(known) and not inferred
    for with_lift in (True, False) if lift else (False,):
        if axis:
            access = _angled_access(width, height, mask, street, runs, known if mapped else (),
                                    blocked | set(party), approach_edges, with_lift, reserved,
                                    axis, requested_mode, rules.stair_via_balcony)
            if access is not None:
                return access
        if use_spine or with_lift:
            access = _long_access(width, height, mask, street, runs, known if mapped else (),
                                  blocked | set(party), approach_edges, with_lift, reserved,
                                  compact=not use_spine, balcony=rules.stair_via_balcony)
            if access is not None:
                return access

    if mapped:
        fronts = []
        for x, y, tags in known:
            bound = entrance_facade(runs, x, y, tags)
            if bound is not None:
                ex, ey, _ = bound.edges[0]
                cross, inset = {"N": (x, ey), "S": (x, height - ey),
                                "W": (y, ex), "E": (y, width - ex)}[bound.side]
                fronts.append((bound.side, cross, inset, bound.edges))
    else:
        across = ("N", "S") if width >= height else ("W", "E")
        sides = sorted("NSWE", key=lambda side: (
            (side in across) != (mode == "landing"), side != street))
        fronts = [(side, None, None, None) for side in sides]

    rank = {edge: i for i, edge in enumerate(approach_edges)} if approach_edges is not None and not mapped else None
    best = None
    for front, target, inset, pinned in fronts:
        vertical = front in ("N", "S")
        reverse = front in ("S", "E")
        span, across = (height, width) if vertical else (width, height)
        minimum_width = LANDING_WIDTH if mode == "landing" else CORE_WIDE
        wide = min(LANDING_WIDTH if mode == "landing" else CORE_WIDE + 1,
                   across - 2 * MIN_ROOM)
        if span < MIN_CORE_LENGTH or wide < minimum_width:
            continue

        def cell(step, cross):
            offset = span - 1 - step if reverse else step
            return (cross, offset) if vertical else (offset, cross)

        def inside(step, cross):
            x, y = cell(step, cross)
            return mask is None or mask[y][x]

        aim = across / 2 if target is None else target
        starts = sorted(range(MIN_ROOM, across - wide - MIN_ROOM + 1),
                        key=lambda i: abs(i + wide / 2 - aim))
        for start in starts:
            if target is not None and abs(start + wide / 2 - aim) > wide / 2:
                continue
            band = range(start, start + wide)
            first = next((t for t in range(span) if all(inside(t, c) for c in band)), span)
            if inset is not None and first != inset:
                continue
            end = first
            while end < span and all(inside(end, c) for c in band):
                end += 1
            if end - first < MIN_CORE_LENGTH:
                continue
            end = min(end, first + LANDING_LENGTH)
            door_cross = (start + wide // 2 if target is None
                          else max(start + 1, min(start + wide - 2, int(target))))
            if first and inside(first - 1, door_cross):
                continue
            a, b = cell(first, start), cell(end - 1, start + wide - 1)
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            x, y = cell(first, door_cross)
            entry = (x, y + int(reverse), "N") if vertical else (x + int(reverse), y, "W")
            if entry not in party and entry not in blocked and (pinned is None or entry in pinned):
                candidate = AccessLayout((x0, y0, x1, y1), (entry,))
                if reserved and not reserved.isdisjoint(tiles_in(candidate.landing)):
                    continue
                if rank is None:
                    return candidate
                if entry in rank and (best is None or rank[entry] < rank[best.entries[0]]):
                    best = candidate
    return best


def ground_lobby(access: AccessLayout, width: int, height: int, mask, levels: int,
                 profile, mapped, stairs, shaft, party, rules: ApartmentAccessRules,
                 section_flats: int | None, *, reserved=frozenset()) -> set[Tile]:
    """Reserve usable lobby tiles before the ground-floor flats are cut."""
    shared = set(tiles_in(access.landing)) | access.ground_passages
    if access.spine is not None:
        shared.update(tiles_in(access.spine))
    if access.oriented is not None:
        shared.update(access.oriented.tiles)
    occupied = set(tiles_in(shaft)) if shaft is not None else set()
    if access.lift is not None:
        stairwell = set(tiles_in(access.landing))
        shared -= stairwell
        occupied.update(stairwell | access.lift.lobby | access.lift.balcony)
    occupied.update(reserved)
    if stairs is not None:
        occupied.update(stair_tiles(stairs)[1:-1])

    a, b = door_sides(access.entries[0])
    entry, outside = (a, b) if a in shared else (b, a)
    dx, dy = entry[0] - outside[0], entry[1] - outside[1]

    def inside(p):
        x, y = p
        return 0 <= x < width and 0 <= y < height and (mask is None or mask[y][x])

    def interior(p):
        return inside(p) and all(inside(q) for q in _adjacent(p))

    wanted = set()
    if mapped:
        from shapely.geometry import Point, Polygon

        # A surveyed lobby can touch the entrance facade, but never open a
        # connection through the boundary of a different stairwell section.
        party_tiles = {p for edge in party for p in door_sides(edge)}
        for ring in mapped:
            polygon = Polygon(ring)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if polygon.is_empty:
                continue
            x0, y0, x1, y1 = map(int, polygon.bounds)
            for p in tiles_in((max(0, x0), max(0, y0), min(width - 1, x1), min(height - 1, y1))):
                x, y = p
                on_entry_face = ((x - entry[0]) * dx + (y - entry[1]) * dy == 0
                                 and p not in party_tiles and not inside((x - dx, y - dy)))
                if inside(p) and (interior(p) or on_entry_face) and polygon.covers(Point(x + .5, y + .5)):
                    wanted.add(p)
    surveyed = bool(wanted)
    if not surveyed:
        area = width * height if mask is None else sum(map(sum, mask))
        year = getattr(profile, "source_year", None)
        # Conservative defaults when surveyed geometry is absent. Extra area
        # needs room in the section as well as evidence of a larger entrance.
        recent = year is not None and year >= rules.lobby_recent_from_year
        if section_flats is not None:
            busy = section_flats >= rules.lobby_busy_from_flats
            recent = recent and section_flats >= rules.lobby_busy_from_flats // 2
        else:
            busy = year is None and 4 * levels >= rules.lobby_busy_from_flats
        if levels < 2 or area < rules.lobby_min_section_tiles or not (recent or busy):
            return set()
        half_width = min(3, max(1, area // 180))
        for depth in range(1, 4):
            for side in range(-half_width, half_width + 1):
                p = entry[0] + depth * dx + side * dy, entry[1] + depth * dy - side * dx
                if interior(p):
                    wanted.add(p)

    wanted -= occupied | shared
    parents = dict.fromkeys(sorted(shared - occupied))
    pending = deque(parents)
    connected = set()
    while pending and wanted:
        p = pending.popleft()
        if p in wanted:
            wanted.remove(p)
            path = p
            while path is not None and path not in shared and path not in connected:
                connected.add(path)
                path = parents[path]
        for q in _adjacent(p):
            if q not in parents and q not in occupied and (q in wanted or (surveyed and interior(q))):
                parents[q] = p
                pending.append(q)
    return connected
