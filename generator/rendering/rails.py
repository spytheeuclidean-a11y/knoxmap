"""Fit connected vanilla rail assemblies to mapped railway centre lines."""
from collections import defaultdict
import heapq
import logging
import math

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import LineString, box

import knoxstop

from ..rail_tiles import ASSEMBLIES, RAIL_END_RADIUS, rail_colour
from .geometry import _feature_coords_px, _is_polygon


def rail_paths(features, proj):
    rings = [ring for feat in features
             if not _is_polygon(feat) and feat.tags.get("service") not in ("spur", "yard", "crossover")
             for ring in _feature_coords_px(feat, proj)]
    yield from continuous_tracks(rings, (proj.width, proj.height))


def continuous_tracks(rings, bounds=None):
    """Straighten minor drift, fitting neighbouring tracks as one corridor."""
    groups = []
    turns = []
    for ring in joined_tracks(rings):
        line = LineString(ring)
        if bounds is not None:
            line = line.intersection(box(-4, -4, bounds[0] + 4, bounds[1] + 4))
        parts = list(line.geoms) if line.geom_type == "MultiLineString" else [line]
        for part in parts:
            if part.is_empty or part.geom_type != "LineString" or part.length < 1:
                continue
            points = list(part.simplify(24).coords)
            runs = []
            for a, b in zip(points, points[1:]):
                delta = np.subtract(b, a)
                if abs(delta[0]) >= 2 * abs(delta[1]):
                    axis = (1, 0)
                elif abs(delta[1]) >= 2 * abs(delta[0]):
                    axis = (0, 1)
                else:
                    axis = (1, 1) if delta[0] * delta[1] >= 0 else (1, -1)
                if runs and runs[-1][0] == axis:
                    runs[-1][1].append(b)
                else:
                    runs.append((axis, [a, b]))
            fitted = []
            for axis, pts in runs:
                normal = (-axis[1], axis[0])
                uv = np.asarray(pts) @ np.array((axis, normal)).T
                slope, intercept = np.polyfit(uv[:, 0], uv[:, 1], 1)
                fitted.append((axis, normal, uv, slope, intercept))
            if len(fitted) != 1:
                # Major turns meet at intersections of their fitted grid lines.
                normals = [np.array(n) for d, n, uv, m, c in fitted]
                offsets = [round(float(np.mean(uv[:, 1]))) for d, n, uv, m, c in fitted]
                start, end = np.asarray(points[0]), np.asarray(points[-1])
                start = start + normals[0] * (offsets[0] - np.dot(start, normals[0])) / np.dot(normals[0], normals[0])
                end = end + normals[-1] * (offsets[-1] - np.dot(end, normals[-1])) / np.dot(normals[-1], normals[-1])
                corners = [np.linalg.solve(np.array([a, b]), [u, v])
                           for a, b, u, v in zip(normals, normals[1:], offsets, offsets[1:])]
                turns.append([tuple(start)] + [tuple(p) for p in corners] + [tuple(end)])
                continue
            axis, normal, uv, slope, intercept = fitted[0]
            record = {"lo": float(uv[:, 0].min()), "hi": float(uv[:, 0].max()),
                      "slope": float(slope), "intercept": float(intercept)}
            group = None
            for candidate in groups:
                reference = candidate[1][0]
                lo, hi = max(reference["lo"], record["lo"]), min(reference["hi"], record["hi"])
                at = (lo + hi) / 2
                gap = abs((reference["slope"] - slope) * at + reference["intercept"] - intercept)
                if candidate[0] == axis and lo < hi and abs(reference["slope"] - slope) < 0.08 and gap < 16 * math.hypot(*axis):
                    group = candidate
                    break
            if group is None:
                group = (axis, [])
                groups.append(group)
            group[1].append(record)
    for axis, records in groups:
        normal = (-axis[1], axis[0])
        norm = np.dot(axis, axis)
        lo, hi = min(r["lo"] for r in records), max(r["hi"] for r in records)
        at = (lo + hi) / 2
        offsets = sorted(r["slope"] * at + r["intercept"] for r in records)
        kept = []
        for offset in offsets:
            value = round(offset - (0.5 if axis == (1, -1) else 0)) + (0.5 if axis == (1, -1) else 0)
            if kept:
                value = max(value, kept[-1] + math.ceil(5 * math.sqrt(norm)))
            kept.append(value)
            yield [tuple((np.array(axis) * u + np.array(normal) * value) / norm) for u in (lo, hi)]
    yield from turns


def joined_tracks(rings):
    """Keep a railway continuous when OSM splits it into several ways."""
    rings = [list(map(tuple, ring)) for ring in rings if len(ring) > 1]
    ends = defaultdict(list)
    for index, ring in enumerate(rings):
        for point in (ring[0], ring[-1]):
            ends[point].append(index)
    used = set()
    for index, ring in enumerate(rings):
        if index in used:
            continue
        used.add(index)
        chain = ring[:]
        for _ in range(2):
            while len(ends[chain[-1]]) == 2:
                next_index = next((i for i in ends[chain[-1]] if i not in used), None)
                if next_index is None:
                    break
                used.add(next_index)
                following = rings[next_index]
                if following[0] != chain[-1]:
                    following = list(reversed(following))
                chain.extend(following[1:])
            chain.reverse()
        yield chain


def rail_sections(points, *, backend="rust", should_stop=None):
    """Yield (tile origin x, y, assembly) with matching ports at every join."""
    if backend not in {"rust", "python"}:
        raise ValueError(f"Unknown rail backend: {backend}")
    knoxstop.check(should_stop, "the railways")
    points = [(float(x), float(y)) for x, y in points]
    points = [p for i, p in enumerate(points) if not i or p != points[i - 1]]
    if len(points) < 2:
        return
    # A reversed OSM way should produce exactly the same track.
    if points[-1] < points[0]:
        points.reverse()
    if sum(math.dist(a, b) for a, b in zip(points, points[1:])) < 1:
        return

    actions = defaultdict(list)
    for index, (start, end, incoming, outgoing, pieces) in enumerate(ASSEMBLIES):
        actions[incoming].append((index, start, end, outgoing))
        actions[tuple(-v for v in outgoing)].append(
            (index, end, start, tuple(-v for v in incoming)))

    def direction(a, b):
        angle = round(math.atan2(b[1] - a[1], b[0] - a[0]) / (math.pi / 4))
        return (round(math.cos(angle * math.pi / 4)), round(math.sin(angle * math.pi / 4)))

    first_dir, last_dir = direction(*points[:2]), direction(*points[-2:])
    port = actions[first_dir][0][1]
    start = tuple(2 * round(points[0][i] - port[i] / 2) + port[i] for i in (0, 1)) + first_dir
    target = tuple(2 * v for v in points[-1])
    x0, y0 = (math.floor(min(p[i] for p in points)) - 10 for i in (0, 1))
    x1, y1 = (math.ceil(max(p[i] for p in points)) + 10 for i in (0, 1))
    guide = Image.new("L", (x1 - x0 + 1, y1 - y0 + 1), 255)
    draw = ImageDraw.Draw(guide)
    local = [(x - x0, y - y0) for x, y in points]
    for radius in range(9, -1, -1):
        draw.line(local, fill=radius * radius, width=radius * 2 + 1)
    if backend == "rust":
        from ..roadgraph.rustsearch import rail_search
        sections = rail_search(guide, x0, y0, start, target, last_dir, ASSEMBLIES, should_stop)
        if sections is not None:
            yield from sections
            return
    costs = guide.load()

    def deviation(x, y):
        px, py = round(x / 2) - x0, round(y / 2) - y0
        return costs[px, py] if 0 <= px < guide.width and 0 <= py < guide.height else 255

    def remaining(state):
        return math.hypot(state[0] - target[0], state[1] - target[1]) / 2

    # A small heuristic weight avoids exploring every equivalent track on long ways.
    queue = [(remaining(start) * 1.15, 0.0, start)]
    best, parents = {start: 0.0}, {}
    final = None
    visited = 0
    while queue:
        if visited % 256 == 0:
            knoxstop.check(should_stop, "the railways")
        visited += 1
        _, cost, state = heapq.heappop(queue)
        if cost != best.get(state):
            continue
        if state != start and remaining(state) <= RAIL_END_RADIUS and state[2:] == last_dir:
            final = state
            break
        for index, entry, exit, heading in actions[state[2:]]:
            nx, ny = state[0] + exit[0] - entry[0], state[1] + exit[1] - entry[1]
            samples = [deviation(state[0] + (nx - state[0]) * t,
                                 state[1] + (ny - state[1]) * t) for t in (0.25, 0.5, 0.75, 1)]
            if max(samples) == 255:
                continue
            step = math.hypot(nx - state[0], ny - state[1]) / 2
            candidate = cost + step * (1 + sum(samples) / len(samples) * 0.08)
            candidate += 2 if index >= 4 else 0  # favour a few major turns over small wiggles
            next_state = (nx, ny) + heading
            if candidate >= best.get(next_state, math.inf):
                continue
            best[next_state] = candidate
            parents[next_state] = (state, index, entry)
            heapq.heappush(queue, (candidate + remaining(next_state) * 1.15, candidate, next_state))
    if final is None:
        raise ValueError("Railway cannot fit connected vanilla track within its mapped corridor")
    path = []
    while final != start:
        previous, index, entry = parents[final]
        ox, oy = (previous[0] - entry[0]) // 2, (previous[1] - entry[1]) // 2
        path.append((ox, oy, index))
        final = previous
    yield from reversed(path)


def paint_track(draw, points, should_stop=None):
    """Paint complete connected pieces; never shift a straight strip sideways."""
    try:
        for ox, oy, index in rail_sections(points, should_stop=should_stop):
            for x, y, sheet, tile in ASSEMBLIES[index][4]:
                draw.point((ox + x, oy + y), fill=rail_colour(sheet, tile))
    except ValueError:
        logging.getLogger(__name__).error("Rail fitting failed for tile path %r", points)
        raise
