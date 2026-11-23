"""Rank vacant exterior door edges by the walk to the surrounding street."""
from __future__ import annotations

import heapq
import os
from dataclasses import dataclass

import numpy as np

from generator import pz_colors as colors
from generator.osm import ROAD_HIERARCHY_CODES

from .bitmaps import read_rgb, same_colour
from .entrances import Edge
from .fences import _fenced_sites, _grid_path, _opening_tiles, _openings, _path_crossings

SEARCH_MARGIN = 32
FRONTAGE_RANGE = 24
PATH_REACH = 4
OUTWARD = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}


@dataclass(frozen=True)
class DoorApproach:
    edge: Edge
    side: str
    cost: int
    street: bool
    path: bool


def _step_edge(x: int, y: int, nx: int, ny: int) -> Edge:
    return max(x, nx), max(y, ny), "W" if x != nx else "N"


def _fence_edges(mapped_lines, areas, gates, paths, closed_gates):
    lines = [points for points, _tags in mapped_lines]
    if areas is not None:
        lines.extend(list(shape.exterior.coords) for shape in _fenced_sites(areas))
    if paths:
        from shapely.geometry import LineString
        from shapely.ops import unary_union

        crossings = unary_union([LineString(line) for line in paths])
    else:
        crossings = None

    gate_tiles = {tile for point in gates for tile in _opening_tiles(*point)}
    blocked = set()
    for line in lines:
        clear = gate_tiles | {tile for point in _path_crossings(line, crossings)
                              for tile in _opening_tiles(*point)}
        walk = _grid_path(line)
        for (x, y), (nx, ny) in zip(walk, walk[1:]):
            edge = (min(x, nx), y, "N") if y == ny else (x, min(y, ny), "W")
            if edge[:2] not in clear or edge[:2] in closed_gates:
                blocked.add(edge)
    return blocked


def _in_bounds(shape, x, y):
    return 0 <= y < shape[0] and 0 <= x < shape[1]


def _near(mask: np.ndarray) -> np.ndarray:
    adjacent = np.zeros_like(mask)
    adjacent[1:, :] |= mask[:-1, :]
    adjacent[:-1, :] |= mask[1:, :]
    adjacent[:, 1:] |= mask[:, :-1]
    adjacent[:, :-1] |= mask[:, 1:]
    return adjacent


@dataclass
class PedestrianContext:
    occupied: np.ndarray
    barriers: np.ndarray
    street: np.ndarray
    service: np.ndarray
    paved: np.ndarray
    fences: set[Edge]

    def approaches(self, fp) -> tuple[DoorApproach, ...] | None:
        """Reachable exterior edges in building coordinates, or no local evidence."""
        map_h, map_w = self.occupied.shape
        x0, y0 = max(0, fp.x0 - SEARCH_MARGIN), max(0, fp.y0 - SEARCH_MARGIN)
        x1, y1 = min(map_w, fp.x0 + fp.width + SEARCH_MARGIN), min(map_h, fp.y0 + fp.height + SEARCH_MARGIN)
        zone = np.s_[y0:y1, x0:x1]
        public = self.street[zone]
        paved = self.paved[zone]
        service = self.service[zone]
        service_extends = (service[0, :].any() or service[-1, :].any()
                           or service[:, 0].any() or service[:, -1].any())
        way = public if public.any() or not service_extends else service
        dry = ~(self.occupied[zone] | self.barriers[zone])
        if way.any():
            seeds = _near(way) & dry
            # The path begins on the street's side of any fence.
            for x, y, direction in self.fences_in(x0, y0, x1, y1):
                a = (x - x0 - (direction == "W"), y - y0 - (direction == "N"))
                b = x - x0, y - y0
                for (sx, sy), (rx, ry) in ((a, b), (b, a)):
                    if (_in_bounds(way.shape, sx, sy) and _in_bounds(way.shape, rx, ry)
                            and seeds[sy, sx] and way[ry, rx]):
                        seeds[sy, sx] = any(
                            _in_bounds(way.shape, sx + dx, sy + dy) and way[sy + dy, sx + dx]
                            and _step_edge(sx + x0, sy + y0, sx + dx + x0, sy + dy + y0) not in self.fences
                            for dx, dy in OUTWARD.values())
        else:
            # A path crossing the search boundary can serve pedestrian-only
            # sites. A paved pocket trapped in a courtyard cannot seed itself.
            seeds = np.zeros_like(paved)
            seeds[[0, -1], :] = paved[[0, -1], :]
            seeds[:, [0, -1]] |= paved[:, [0, -1]]
            seeds &= dry
            if not seeds.any():
                if not any(self.fences_in(x0, y0, x1, y1)):
                    return None
                # A mapped enclosure still distinguishes the yard from
                # surrounding open ground when no road or path was recorded.
                seeds[[0, -1], :] = dry[[0, -1], :]
                seeds[:, [0, -1]] |= dry[:, [0, -1]]

        from .layout.furnishing import _facade_runs

        target = {}
        for side, edges in _facade_runs(fp.mask):
            dx, dy = OUTWARD[side]
            for ex, ey, direction, ix, iy in edges:
                x, y = ix + fp.x0 - x0 + dx, iy + fp.y0 - y0 + dy
                if _in_bounds(dry.shape, x, y) and dry[y, x]:
                    target.setdefault((x, y), []).append(((ex, ey, direction), side))
        return self._route(zone, seeds, dry, way, target, x0, y0)

    def fences_in(self, x0, y0, x1, y1):
        # Iteration follows the local window and not the map-wide fence list.
        if not self.fences:
            return
        for y in range(y0, y1):
            for x in range(x0, x1):
                for d in ("W", "N"):
                    if (x, y, d) in self.fences:
                        yield x, y, d

    def _route(self, zone, seeds, dry, way, target, x0, y0):
        paved = self.paved[zone]
        distance = np.full(dry.shape, np.iinfo(np.int32).max, dtype=np.int32)
        queue = [(0, int(x), int(y)) for y, x in zip(*np.nonzero(seeds))]
        distance[seeds] = 0
        heapq.heapify(queue)
        approaches = []
        while queue and target:
            cost, x, y = heapq.heappop(queue)
            if cost != distance[y, x]:
                continue
            for edge, side in target.pop((x, y), ()):
                dx, dy = OUTWARD[side]
                street = False
                path = bool(paved[y, x])
                for step in range(1, FRONTAGE_RANGE + 1):
                    px, py = x + step * dx, y + step * dy
                    if not _in_bounds(dry.shape, px, py) or _step_edge(
                            px - dx + x0, py - dy + y0, px + x0, py + y0) in self.fences:
                        break
                    if way[py, px]:
                        street = True
                        break
                    if not dry[py, px]:
                        break
                    if step <= PATH_REACH and paved[py, px]:
                        path = True
                approaches.append(DoorApproach(edge, side, cost, street, path))
            for dx, dy in OUTWARD.values():
                nx, ny = x + dx, y + dy
                if not _in_bounds(dry.shape, nx, ny) or not dry[ny, nx]:
                    continue
                step = cost + (1 if paved[ny, nx] else 3)
                if step < distance[ny, nx] and _step_edge(
                        x + x0, y + y0, nx + x0, ny + y0) not in self.fences:
                    distance[ny, nx] = step
                    heapq.heappush(queue, (step, nx, ny))
        return tuple(sorted(approaches, key=lambda item: item.edge))


def pedestrian_context(out_dir, map_name, proj, occupied, hierarchy, road_weight, areas, mapped_lines):
    path = os.path.join(out_dir, f"{map_name}_ground_base.bmp")
    if not os.path.isfile(path):
        path = os.path.join(out_dir, f"{map_name}.bmp")
    if not os.path.isfile(path):
        return None
    ground = read_rgb(path, crop=occupied.shape)
    pavement = same_colour(ground, colors.PALE_CONCRETE) | same_colour(ground, colors.PAVING)
    asphalt = same_colour(ground, colors.MEDIUM_ASPHALT) | same_colour(ground, colors.DARKEST_ASPHALT)
    if hierarchy is None:
        street, service = asphalt, np.zeros_like(asphalt)
    else:
        motor = (asphalt | same_colour(ground, colors.DARK_ASPHALT)
                 | same_colour(ground, colors.LIGHT_ASPHALT))
        street = motor & (hierarchy >= ROAD_HIERARCHY_CODES["residential"])
        service = motor & (hierarchy == ROAD_HIERARCHY_CODES["service"])
        pavement |= hierarchy == ROAD_HIERARCHY_CODES["footway"]
    gates, paths, closed_gates = _openings(out_dir, map_name, proj)
    for path_line in paths:
        for x, y in _grid_path(path_line):
            if _in_bounds(pavement.shape, x, y):
                pavement[y, x] = True
    blocked = same_colour(ground, colors.WATER) | street
    if road_weight is not None:
        blocked |= road_weight == 8  # the rail clearance in street_context
    fences = _fence_edges(mapped_lines, areas, gates, paths, closed_gates)
    if not (street.any() or service.any() or pavement.any() or fences):
        return None
    return PedestrianContext(occupied, blocked, street, service, pavement, fences)
