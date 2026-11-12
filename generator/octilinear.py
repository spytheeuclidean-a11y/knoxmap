"""Roads in long straight runs at 45-degree steps, the way Knox County's are.

The game's own roads run along the tiles or on the diagonal, nothing between.
A real street at 20 degrees drawn on tiles is a ragged staircase, its kerbs
and markings chopped at every step, and a curving suburban crescent is a
smear. With the "Knox County roads" setting the town is gently redrawn before
anything is painted:

1. The road network becomes a graph: its junctions and the corners left once
   small wiggles are smoothed away.
2. Each stretch between two of those points picks the nearest of the four
   directions the game draws well - along either axis or either diagonal -
   and all the points are moved together, as little as they can be, until
   every stretch runs that way (a least-squares fit; junctions are shared, so
   every road still meets the ones it met). A crescent becomes a few straight
   sides with 45-degree corners; a long road at 10 degrees becomes straight.
3. Everything else - buildings, parks, car parks, water, paths - moves with
   the roads around it, by a smooth blend of how far the nearby roads moved,
   so houses still front their street instead of standing in it.

What is left is a town that reads like the real one, laid out like the game's.

The setting's other two choices route the roads instead (generator/roadgraph:
vanilla's sixteen directions and its own street shapes). The renderer saves
the result as <map>_roadgraph.json and every later step that needs the roads
where the renderer drew them reads that file back (replay) rather than
working them out again.
"""
from __future__ import annotations

import json
import math
import os

import numpy as np

ROAD_CATEGORIES = {"road_major", "road_medium", "road_minor", "road_service",
                   "pedestrian"}
# Wiggles smaller than this, in tiles, are smoothed away first.
SIMPLIFY_TILES = 3.0
# How strongly a point holds to where it really is, against how strongly each
# stretch turns to its direction. Low: roads straighten, the town bends to fit.
HOLD = 0.02
# How far, in tiles, the rest of the town feels a road's move.
BLEND_TILES = 30
# How far straightening may drag a point from where the survey put it. The fit
# on its own has no such limit, and on a big town it used it: a main road at a
# slight angle straightened by moving its far end a couple of blocks, which
# left the road beyond it cut off, and streets on the other side of town ended
# up across the road they used to run beside. Anything that wants to move
# further than this is pinned where it really is and the fit is run again, so
# the straightening gives way rather than the map.
MAX_MOVE_TILES = 24.0
# The hold on a point that has been pinned: large enough that the stretches
# pulling on it cannot drag it anywhere.
PINNED_HOLD = 50.0
# A closed loop smaller than this across is a roundabout, whatever it is
# tagged. Fitting one to the eight directions turned it into a few crossed
# triangles; it is left exactly as it is instead, with its junctions pinned so
# every road still meets it.
ROUNDABOUT_TILES = 60.0
# How far apart the points of one straight run may be across it and still be
# rounded onto the same row, column or diagonal.
ROUND_SPREAD = 2.0
FIELD_CELL = 4                  # tiles per cell of the displacement field
DIRECTIONS = [(1.0, 0.0), (math.sqrt(.5), math.sqrt(.5)), (0.0, 1.0),
              (-math.sqrt(.5), math.sqrt(.5))]


def _key(lat: float, lon: float) -> tuple[int, int]:
    return round(lat * 1e7), round(lon * 1e7)


def _simplify_idx(pts: list[tuple[float, float]], tol: float) -> list[int]:
    """Douglas-Peucker; the indices kept, both ends included."""
    if len(pts) < 3:
        return list(range(len(pts)))
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        best, best_d = -1, tol
        for i in range(a + 1, b):
            d = _dist_to_line(pts[i], pts[a], pts[b])
            if d > best_d:
                best, best_d = i, d
        if best >= 0:
            keep[best] = True
            stack += [(a, best), (best, b)]
    return [i for i, k in enumerate(keep) if k]


def _dist_to_line(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length == 0:
        return math.hypot(px - ax, py - ay)
    return abs(dx * (ay - py) - (ax - px) * dy) / length


def _legs(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    """From a to b along the grid and the diagonal: half the straight part,
    the diagonal, the other half."""
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    sx, sy = (dx > 0) - (dx < 0), (dy > 0) - (dy < 0)
    diag = min(abs(dx), abs(dy))
    first = (max(abs(dx), abs(dy)) - diag) // 2
    p1 = (ax + sx * first, ay) if abs(dx) >= abs(dy) else (ax, ay + sy * first)
    return [p1, (p1[0] + sx * diag, p1[1] + sy * diag), b]


def _tidy(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Without repeated points or points in the middle of a straight run."""
    out: list[tuple[int, int]] = []
    for p in path:
        if out and p == out[-1]:
            continue
        if len(out) >= 2:
            (x0, y0), (x1, y1) = out[-2], out[-1]
            if (x1 - x0) * (p[1] - y1) == (y1 - y0) * (p[0] - x1) and \
                    (x1 - x0) * (p[0] - x1) + (y1 - y0) * (p[1] - y1) >= 0:
                out[-1] = p
                continue
        out.append(p)
    return out


def _de_dogleg(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Two straight runs a tile apart are one run.

    The fit puts a long street's halves on neighbouring grid lines more often
    than it should, and the step between them reads in game as the road
    shifting sideways for no reason. Everything from the step on moves back
    onto the line it came from, so the street runs straight through.
    """
    out = [tuple(p) for p in path]
    i = 1
    while i <= len(out) - 2:
        a, b, c = out[i - 1], out[i], out[i + 1]
        step = (b[0] - a[0], b[1] - a[1])
        ahead = (c[0] - b[0], c[1] - b[1])
        if abs(step[0]) + abs(step[1]) == 1 and ahead != step \
                and step[0] * ahead[0] + step[1] * ahead[1] == 0 \
                and abs(ahead[0]) + abs(ahead[1]) >= 3:
            dx, dy = -step[0], -step[1]
            # the run after the step, up to where it turns: that run moves
            # onto the line, and the road carries on from the same corner.
            last = i + 1
            while last + 1 < len(out) and \
                    (out[last + 1][0] - out[last][0], out[last + 1][1] - out[last][1]) == ahead:
                last += 1
            for j in range(i, last + 1):
                out[j] = (out[j][0] + dx, out[j][1] + dy)
            del out[i]
            continue
        i += 1
    return out


def _rigid(f, px: list) -> bool:
    """Whether this road is left exactly as it was drawn: a roundabout, or any
    small closed loop, which has no straight sides to fit."""
    if (f.tags.get("junction") or "").lower() in {"roundabout", "circular"}:
        return True
    if len(px) < 4 or math.dist(px[0], px[-1]) > 1e-6:
        return False
    xs = [x for x, _ in px]
    ys = [y for _, y in px]
    return max(max(xs) - min(xs), max(ys) - min(ys)) <= ROUNDABOUT_TILES


def _fit(p0: np.ndarray, segs: np.ndarray, normals: np.ndarray,
         weights: np.ndarray, pinned: np.ndarray | None = None) -> np.ndarray:
    """The points, straightened: once held firmly where they are, then again
    held only loosely to that, which is what takes the last of the slant out."""
    def holds(value: float) -> np.ndarray:
        out = np.full((len(p0), 1), value)
        if pinned is not None:
            out[pinned] = PINNED_HOLD
        return out

    moved = _solve(p0, segs, normals, weights, hold=holds(HOLD))
    return _solve(moved, segs, normals, weights, iterations=1500,
                  hold=holds(HOLD / 50))


def _solve(p0: np.ndarray, segs: np.ndarray, normals: np.ndarray,
           weights: np.ndarray, iterations: int = 400, hold=None) -> np.ndarray:
    """Points as near p0 as they can be with every segment turned along its
    direction: minimise HOLD*|P - p0|^2 + sum w*(n . (P_j - P_i))^2, by
    conjugate gradients on the normal equations."""
    hold = HOLD if hold is None else hold
    i, j = segs[:, 0], segs[:, 1]

    def apply(x):
        out = hold * x
        v = weights * np.einsum("ij,ij->i", normals, x[j] - x[i])
        np.add.at(out, j, v[:, None] * normals)
        np.add.at(out, i, -v[:, None] * normals)
        return out

    b = hold * p0
    x = p0.copy()
    r = b - apply(x)
    p = r.copy()
    rs = float((r * r).sum())
    for _ in range(iterations):
        if rs < 1e-6:
            break
        ap = apply(p)
        alpha = rs / float((p * ap).sum())
        x += alpha * p
        r -= alpha * ap
        rs_new = float((r * r).sum())
        p = r + (rs_new / rs) * p
        rs = rs_new
    return x


def _blur(a: np.ndarray, radius: int) -> np.ndarray:
    """Three box blurs, near enough a Gaussian, along both axes."""
    for axis in (0, 1):
        for _ in range(3):
            pad = [(0, 0), (0, 0)]
            pad[axis] = (radius + 1, radius)
            c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis)
            hi = np.take(c, range(2 * radius + 1, c.shape[axis]), axis=axis)
            lo = np.take(c, range(0, c.shape[axis] - 2 * radius - 1), axis=axis)
            a = (hi - lo) / (2 * radius + 1)
    return a


def _round_together(moved: np.ndarray, segs: np.ndarray, normals: np.ndarray, original: np.ndarray, pinned: np.ndarray, clean: bool = False) -> list:
    """Whole tiles for the points, the same row for every point along one
    east-west run, the same column along a north-south one and the same
    diagonal along a diagonal one - rounded one at a time, the ends of a long
    straight road can land either side of a tile edge, and it jogs."""
    n = len(moved)
    cap = MAX_MOVE_TILES * (1.35 if clean else 1.0)
    reach = cap / math.sqrt(2)
    lower = np.ceil(original - reach).astype(int)
    upper = np.floor(original + reach).astype(int)
    orig_down = original[:, 0] - original[:, 1]
    orig_up = original[:, 0] + original[:, 1]
    down_lo = np.ceil(orig_down - cap).astype(int)
    down_hi = np.floor(orig_down + cap).astype(int)
    up_lo = np.ceil(orig_up - cap).astype(int)
    up_hi = np.floor(orig_up + cap).astype(int)
    if pinned is not None:
        lower[pinned] = upper[pinned] = np.rint(original[pinned]).astype(int)
        down_lo[pinned] = down_hi[pinned] = (lower[pinned, 0] - lower[pinned, 1])
        up_lo[pinned] = up_hi[pinned] = (lower[pinned, 0] + lower[pinned, 1])
    bounds = {
        "row": [list(lower[:, 1]), list(upper[:, 1])],
        "col": [list(lower[:, 0]), list(upper[:, 0])],
        "down": [list(down_lo), list(down_hi)],
        "up": [list(up_lo), list(up_hi)],
    }
    parent = {kind: list(range(n)) for kind in ("row", "col", "down", "up")}

    def find(kind, a):
        p = parent[kind]
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    order = sorted(range(len(segs)), key=lambda i: -math.dist(original[segs[i, 0]], original[segs[i, 1]]))
    for edge in order:
        (a, b), (nx, ny) = segs[edge], normals[edge]
        if abs(nx) < 1e-9:
            kind = "row"                  # runs along x: normal is (0, ±1)
        elif abs(ny) < 1e-9:
            kind = "col"
        elif nx * ny < 0:
            kind = "down"                 # along (1, 1): x - y is constant
        else:
            kind = "up"                   # along (-1, 1): x + y is constant
        ra, rb = find(kind, int(a)), find(kind, int(b))
        if ra != rb:
            if kind in bounds:
                lo, hi = bounds[kind]
                left, right = max(lo[ra], lo[rb]), min(hi[ra], hi[rb])
                if left > right:
                    continue
                lo[rb], hi[rb] = left, right
            parent[kind][ra] = rb

    def shared(kind, values):
        groups: dict[int, list[float]] = {}
        for k in range(n):
            groups.setdefault(find(kind, k), []).append(values[k])
        mean = {g: round(sum(v) / len(v)) for g, v in groups.items()}
        # Axis and diagonal runs share a tile offset within their movement bounds.
        if kind in bounds:
            lo, hi = bounds[kind]
            mean = {g: min(hi[g], max(lo[g], m)) for g, m in mean.items()}
        together = {g: len(v) > 1 and (kind in bounds or max(abs(x - mean[g]) for x in v) <= ROUND_SPREAD)
                    for g, v in groups.items()}
        return ([mean[find(kind, k)] for k in range(n)],
                [together[find(kind, k)] for k in range(n)])

    xs, ys = moved[:, 0], moved[:, 1]
    row, in_row = shared("row", ys)
    col, in_col = shared("col", xs)
    down, in_down = shared("down", xs - ys)
    up, in_up = shared("up", xs + ys)
    out = []
    for k in range(n):
        y = row[k] if in_row[k] else round(ys[k])
        if in_col[k]:
            x = col[k]
            if not in_row[k]:
                if in_down[k]:
                    y = x - down[k]
                elif in_up[k]:
                    y = up[k] - x
        elif in_down[k]:
            if not in_row[k] and not in_up[k]:
                y = round((xs[k] + ys[k] - down[k]) / 2)
                lo_y = max(lower[k, 1], lower[k, 0] - down[k])
                hi_y = min(upper[k, 1], upper[k, 0] - down[k])
                if lo_y <= hi_y:
                    y = min(hi_y, max(lo_y, y))
            x = down[k] + y
        elif in_up[k]:
            if not in_row[k]:
                y = round((ys[k] - xs[k] + up[k]) / 2)
                lo_y = max(lower[k, 1], up[k] - upper[k, 0])
                hi_y = min(upper[k, 1], up[k] - lower[k, 0])
                if lo_y <= hi_y:
                    y = min(hi_y, max(lo_y, y))
            x = up[k] - y
        else:
            x = round(xs[k])
        if not in_row[k] and not in_col[k] and in_down[k] and in_up[k]:
            # Where two diagonals cross, both hold.
            y = (up[k] - down[k]) // 2
            x = down[k] + y
        x = min(upper[k, 0], max(lower[k, 0], x))
        y = min(upper[k, 1], max(lower[k, 1], y))
        out.append((int(x), int(y)))
    return out


def _square_short_bends(p0, segs, normals, pinned, clean: bool = False):
    """Square small kinks between long grid runs, keeping major diagonals."""
    lengths = np.linalg.norm(p0[segs[:, 1]] - p0[segs[:, 0]], axis=1)
    axial = np.min(np.abs(normals), axis=1) < 1e-9
    incident = {}
    all_incident = {}
    for i, (a, b) in enumerate(segs):
        all_incident.setdefault(a, []).append(i)
        all_incident.setdefault(b, []).append(i)
        if axial[i]:
            incident.setdefault(a, []).append(i)
            incident.setdefault(b, []).append(i)
    out = normals.copy()
    max_kink = MAX_MOVE_TILES * (2.0 if clean else 1.0)
    ratio = 1.5 if clean else 2.0
    for i, (a, b) in enumerate(segs):
        if lengths[i] > max_kink or pinned[a] or pinned[b]:
            continue
        if not axial[i]:
            before = [j for j in incident.get(a, ()) if j != i and lengths[j] >= ratio * lengths[i]]
            after = [j for j in incident.get(b, ()) if j != i and lengths[j] >= ratio * lengths[i]]
            if before and after:
                j = max(before + after, key=lambda j: lengths[j])
                out[i] = normals[j]
                continue
        # Also straighten a short kink (axial or diagonal) sandwiched between
        # two longer runs that share the same direction.
        for j in all_incident.get(a, ()):
            if j == i or lengths[j] < ratio * lengths[i]:
                continue
            for k in all_incident.get(b, ()):
                if k == i or lengths[k] < ratio * lengths[i]:
                    continue
                if abs(float(np.dot(normals[j], normals[k]))) > 1.0 - 1e-6:
                    out[i] = normals[j]
                    break
    return out


def _align_snapped_segments(snapped: list[tuple[int, int]], road_vertices: list[list[int]],
                            rigid: list[bool], p0: np.ndarray, pinned: np.ndarray,
                            clean: bool = False) -> None:
    """Eliminate 1-3 tile residual cross-axis shifts along straight and diagonal
    road segments when an unpinned internal vertex can sit on the exact line."""
    v_uses: dict[int, int] = {}
    for held, verts in zip(rigid, road_vertices):
        if held:
            continue
        for idx, v in enumerate(verts):
            v_uses[v] = v_uses.get(v, 0) + (2 if idx in (0, len(verts) - 1) else 1)

    max_err = 4 if clean else 2
    cap = MAX_MOVE_TILES
    for held, verts in zip(rigid, road_vertices):
        if held or len(verts) < 2:
            continue
        for u, v in zip(verts, verts[1:]):
            if u == v:
                continue
            ax, ay = snapped[u]
            bx, by = snapped[v]
            dx, dy = bx - ax, by - ay
            adx, ady = abs(dx), abs(dy)
            if adx == 0 or ady == 0 or adx == ady:
                continue
            axial_err = min(adx, ady)
            diag_err = abs(adx - ady)
            if axial_err <= max_err and max(adx, ady) >= 3 * axial_err:
                for target, ref in ((v, (ax, ay)), (u, (bx, by))):
                    if pinned[target] or (not clean and v_uses.get(target, 0) > 1):
                        continue
                    nx = ref[0] if adx < ady else snapped[target][0]
                    ny = ref[1] if ady < adx else snapped[target][1]
                    if math.hypot(nx - p0[target, 0], ny - p0[target, 1]) <= cap:
                        snapped[target] = (int(nx), int(ny))
                        break
            elif diag_err <= max_err and min(adx, ady) >= 2 * diag_err:
                sx = 1 if dx > 0 else -1
                sy = 1 if dy > 0 else -1
                for target, origin, sign in ((v, (ax, ay), 1), (u, (bx, by), -1)):
                    if pinned[target] or (not clean and v_uses.get(target, 0) > 1):
                        continue
                    tx, ty = snapped[target]
                    step = round((abs(tx - origin[0]) + abs(ty - origin[1])) / 2)
                    nx = origin[0] + sign * sx * step
                    ny = origin[1] + sign * sy * step
                    if math.hypot(nx - p0[target, 0], ny - p0[target, 1]) <= cap:
                        snapped[target] = (int(nx), int(ny))
                        break


def straighten_roads(features: list, proj, classify, is_polygon, clean: bool = False) -> int:
    """Redraw the roads in `features` and move the rest of the town with them,
    in place. Returns how many roads were redrawn."""
    roads = [f for f in features
             if f.kind == "way" and len(f.geometry) >= 2 and not is_polygon(f)
             and classify(f.tags) in ROAD_CATEGORIES]
    if not roads:
        return 0

    # --- the graph: junctions shared, corners per road ---------------------
    uses: dict[tuple[int, int], int] = {}
    for f in roads:
        for n, (lat, lon) in enumerate(f.geometry):
            k = _key(lat, lon)
            uses[k] = uses.get(k, 0) + (2 if n in (0, len(f.geometry) - 1) else 1)
    points: list[tuple[float, float]] = []
    junction: dict[tuple[int, int], int] = {}
    road_vertices: list[list[int]] = []      # per road, its graph points in order
    road_px: list[list[tuple[float, float]]] = []

    def vertex(xy, key=None):
        if key is not None and key in junction:
            return junction[key]
        points.append(xy)
        if key is not None:
            junction[key] = len(points) - 1
        return len(points) - 1

    simplify_tol = SIMPLIFY_TILES * (1.5 if clean else 1.0)
    rigid: list[bool] = []            # roads left exactly as they were drawn
    for f in roads:
        px = [proj.to_px(lat, lon) for lat, lon in f.geometry]
        road_px.append(px)
        rigid.append(_rigid(f, px))
        keys = [_key(lat, lon) for lat, lon in f.geometry]
        cuts = [n for n, k in enumerate(keys) if n in (0, len(keys) - 1) or uses[k] >= 2]
        verts = [vertex(px[0], keys[0])]
        for a, b in zip(cuts, cuts[1:]):
            kept = _simplify_idx(px[a:b + 1], simplify_tol)
            for n in kept[1:-1]:
                verts.append(vertex(px[a + n]))
            verts.append(vertex(px[b], keys[b]))
        road_vertices.append(verts)

    p0 = np.array(points, dtype=float)
    pinned = np.zeros(len(points), dtype=bool)
    segs, normals, weights = [], [], []
    for held, verts in zip(rigid, road_vertices):
        if held:
            # A roundabout holds its own shape and its junctions, so the roads
            # into it still meet it; nothing turns it to the eight directions.
            pinned[verts] = True
            continue
        for a, b in zip(verts, verts[1:]):
            if a == b:
                continue
            d = p0[b] - p0[a]
            length = float(np.hypot(*d))
            if length < 1e-6:
                continue
            u = d / length
            best = max(DIRECTIONS, key=lambda t: abs(u[0] * t[0] + u[1] * t[1]))
            segs.append((a, b))
            normals.append((-best[1], best[0]))
            # Long stretches turn firmly; a short one between two junctions
            # gives way to the roads around it.
            weights.append(min(length, 60.0) / 10.0)
    if not segs:
        return 0
    segs, normals, weights = np.array(segs), np.array(normals), np.array(weights)
    normals = _square_short_bends(p0, segs, normals, pinned, clean=clean)
    moved = _fit(p0, segs, normals, weights, pinned)
    # Nothing may be dragged a block from where the survey put it. Whatever
    # wanted to be is pinned and the fit run again - the roads around it take
    # up the slack, and the ones that cannot simply stay as they were drawn.
    for _ in range(4):
        far = np.hypot(*(moved - p0).T) > MAX_MOVE_TILES
        if not (far & ~pinned).any():
            break
        pinned |= far
        moved = _fit(p0, segs, normals, weights, pinned)

    # --- the roads, from the moved points ---------------------------------
    snapped = _round_together(moved, segs, normals, p0, pinned, clean=clean)
    _align_snapped_segments(snapped, road_vertices, rigid, p0, pinned, clean=clean)
    drawn: list = []                  # each road as it now stands, in tiles
    for f, held, verts in zip(roads, rigid, road_vertices):
        if held:
            drawn.append(None)
            continue
        path = [snapped[verts[0]]]
        for v in verts[1:]:
            path += _legs(path[-1], snapped[v])
        path = _tidy(path)
        if clean:
            path = _tidy(_de_dogleg(path))
        if len(path) < 2:
            drawn.append(None)
            continue
        drawn.append(path)
        f.geometry = [proj.to_latlon(x, y) for x, y in path]

    # --- everything else moves with the roads near it ---------------------
    # Sampled along each road as it is drawn now, against the line it was
    # drawn on: a road that comes out as grid and 45-degree runs leaves that
    # line by up to MAX_MOVE_TILES, and the town has to go with the road that
    # is really there. Sampling the junctions alone said "nothing moved"
    # wherever the run between two junctions had been redrawn.
    samples = []
    for held, px, path in zip(rigid, road_px, drawn):
        if held or path is None:
            continue
        for a, b in zip(path, path[1:]):
            qa, qb = np.array(a, dtype=float), np.array(b, dtype=float)
            steps = max(1, int(np.hypot(*(qb - qa)) / FIELD_CELL))
            for t in np.linspace(0.0, 1.0, steps + 1):
                q = qa + (qb - qa) * t
                was = np.array(_on_line(px, q), dtype=float)
                samples.append((was, q - was))
    _carry(features, roads, displacement(samples, proj))
    return len(roads)


def _on_line(line: list, q) -> tuple[float, float]:
    """The point of `line` - a road's [(x, y), ...] before it was redrawn -
    nearest `q` in tiles, so a corner of the redrawn road knows where the
    road it replaced used to be."""
    best, best_d = line[0], float("inf")
    for (ax, ay), (bx, by) in zip(line, line[1:]):
        dx, dy = bx - ax, by - ay
        span = dx * dx + dy * dy
        t = 0.0 if not span else max(0.0, min(1.0, ((q[0] - ax) * dx + (q[1] - ay) * dy) / span))
        p = (ax + dx * t, ay + dy * t)
        d = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
        if d < best_d:
            best, best_d = p, d
    return best


def displacement(samples, proj):
    """move(lat, lon) -> (lat, lon): the town's move at a point, from `samples`
    [(point before, its move)] in tiles along the roads - their moves blended
    over BLEND_TILES, fading out far from any road."""
    gw, gh = proj.width // FIELD_CELL + 2, proj.height // FIELD_CELL + 2
    weight = np.zeros((gh, gw))
    shift = np.zeros((gh, gw, 2))
    for q, d in samples:
        cx, cy = int(q[0] // FIELD_CELL), int(q[1] // FIELD_CELL)
        if 0 <= cx < gw and 0 <= cy < gh:
            weight[cy, cx] += 1.0
            shift[cy, cx] += d
    radius = max(1, BLEND_TILES // FIELD_CELL)
    w_blur = _blur(weight, radius)
    field_x = _blur(shift[..., 0], radius) / (w_blur + 1e-3)
    field_y = _blur(shift[..., 1], radius) / (w_blur + 1e-3)
    # Far from any road the move fades out rather than jumping to nothing.
    fade = np.clip(w_blur / (w_blur.max() * 0.02 + 1e-9), 0.0, 1.0)
    field_x *= fade
    field_y *= fade

    def move(lat, lon):
        x, y = proj.to_px(lat, lon)
        cx = min(gw - 1, max(0, int(x // FIELD_CELL)))
        cy = min(gh - 1, max(0, int(y // FIELD_CELL)))
        return proj.to_latlon(x + field_x[cy, cx], y + field_y[cy, cx])
    return move


def _carry(features: list, roads: list, move) -> None:
    """Everything in `features` but the roads moved by `move`, in place."""
    road_ids = {id(f) for f in roads}
    for f in features:
        if id(f) in road_ids:
            continue
        if f.geometry and f.kind in ("way", "node"):
            f.geometry = [move(lat, lon) for lat, lon in f.geometry]
        if f.kind == "relation" and getattr(f, "role_geoms", None):
            f.role_geoms = [(role, [move(lat, lon) for lat, lon in ring])
                            for role, ring in f.role_geoms]
            if f.geometry and isinstance(f.geometry[0][0], (list, tuple)):
                f.geometry = [ring for _role, ring in f.role_geoms]


def apply_road_graph(features: list, graph: dict, proj) -> int:
    """The roads as generator/roadgraph routed them, in place of straightening:
    graph {"ways": {osm id: {"geometry": [[lat, lon], ...], "tags": {...}}},
    "drop": [osm id, ...], "shift": [[lat, lon, lat, lon], ...]}. Each routed
    way takes its new line (and any tags given); a dropped way (a lane folded
    into the road beside it, the second half of a dual carriageway) goes;
    "shift" - points along the roads, where they were and where they went -
    moves everything else with the roads near it, as straightening does.
    Returns how many roads were redrawn."""
    ways = {int(k): v for k, v in graph.get("ways", {}).items()}
    drop = set(graph.get("drop", []))
    kept, roads = [], []
    for f in features:
        if f.kind == "way" and f.osm_id in drop:
            continue
        g = ways.get(f.osm_id) if f.kind == "way" else None
        if g:
            f.geometry = [tuple(p) for p in g["geometry"]]
            f.tags = {**f.tags, **g.get("tags", {})}
            roads.append(f)
        kept.append(f)
    features[:] = kept
    samples = []
    for la0, lo0, la1, lo1 in graph.get("shift", []):
        p0, p1 = np.array(proj.to_px(la0, lo0)), np.array(proj.to_px(la1, lo1))
        samples.append((p0, p1 - p0))
    if samples:
        _carry(features, roads, displacement(samples, proj))
    return len(roads)


def graph_path(map_dir: str, map_name: str) -> str:
    return os.path.join(map_dir, f"{map_name}_roadgraph.json")


def replay(features: list, proj, classify, is_polygon, info: dict, map_dir: str, map_name: str) -> int:
    """The roads put where the renderer drew them, for a step after Generate (Build,
    the paper map): straightened again (straight_roads 1, which comes out the same
    every time), or the map's saved road graph read back (2 and 3: routing again would
    take minutes). Returns how many roads were redrawn."""
    mode = int(info.get("straight_roads") or 0)
    if mode in (1, 4):
        return straighten_roads(features, proj, classify, is_polygon, clean=(mode == 4))
    if mode in (2, 3):
        path = graph_path(map_dir, map_name)
        if not os.path.exists(path):
            raise RuntimeError(f"{os.path.basename(path)} is missing: generate the map again")
        with open(path, encoding="utf-8") as fh:
            return apply_road_graph(features, json.load(fh), proj)
    return 0
