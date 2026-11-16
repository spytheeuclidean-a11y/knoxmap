"""Ground-up Vanilla 45-degree grid road layout (``straight_roads = 5``).

Every road vertex is snapped to integer tile coordinates and every segment is
strictly one of the 8 octilinear headings (0, 45, 90, 135 degrees — horizontal,
vertical, or exact 1:1 diagonals where ``|dx| == |dy|``). Smooth OSM curves
become clean 45-degree chamfered turns, matching vanilla Project Zomboid's
road network with zero 2:1 slopes or arbitrary-angle staircase teeth.
"""
from __future__ import annotations

import math

from .mapped_roads import ROAD_CATEGORIES, _douglas_peucker
from .osm import OSMFeature

SIMPLIFY_TOLERANCE_TILES = 3.0
LOOP_SIMPLIFY_TOLERANCE_TILES = 1.0
SMALL_LOOP_SPAN_TILES = 18.0
CHAMFER_TILES = 8
MIN_CHAMFER_LEG = 6
MICRO_LEG_TILES = 3


def _snap(pt: tuple[float, float]) -> tuple[int, int]:
    return (int(round(pt[0])), int(round(pt[1])))


def _dir8(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    return ((1 if dx > 0 else -1 if dx < 0 else 0),
            (1 if dy > 0 else -1 if dy < 0 else 0))


def _dist_seg(pt: tuple[float, float], a: tuple[int, int], b: tuple[int, int]) -> float:
    vx, vy = b[0] - a[0], b[1] - a[1]
    wx, wy = pt[0] - a[0], pt[1] - a[1]
    vv = vx * vx + vy * vy
    if vv == 0:
        return math.hypot(wx, wy)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
    return math.hypot(pt[0] - (a[0] + t * vx), pt[1] - (a[1] + t * vy))


def _polyline_deviation(samples: list[tuple[float, float]],
                        a: tuple[int, int], c: tuple[int, int],
                        b: tuple[int, int]) -> float:
    if not samples:
        return 0.0
    return sum(min(_dist_seg(p, a, c), _dist_seg(p, c, b)) for p in samples)


def _route_8way(a: tuple[int, int], b: tuple[int, int],
                samples: list[tuple[float, float]],
                prev_dir: tuple[int, int] | None,
                prefer_major_first: bool = False,
                prefer_major_last: bool = False) -> list[tuple[int, int]]:
    """Connect integer points ``a`` and ``b`` using only 0/45/90-degree legs."""
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if dx == 0 and dy == 0:
        return []
    adx, ady = abs(dx), abs(dy)
    if adx == 0 or ady == 0 or adx == ady:
        return [b]

    sx = 1 if dx > 0 else -1
    sy = 1 if dy > 0 else -1
    d = min(adx, ady)
    s = abs(adx - ady)
    axis_step = (sx * s, 0) if adx > ady else (0, sy * s)
    diag_step = (sx * d, sy * d)

    c1 = (a[0] + axis_step[0], a[1] + axis_step[1])
    c2 = (a[0] + diag_step[0], a[1] + diag_step[1])

    if min(s, d) <= MICRO_LEG_TILES and max(s, d) >= 8:
        if prefer_major_first and prefer_major_last:
            # Keep tiny 1-3 tile jogs away from both pinned junction ends.
            major_step = axis_step if s >= d else diag_step
            minor_step = diag_step if s >= d else axis_step
            half = (int(major_step[0] / 2), int(major_step[1] / 2))
            m1 = (a[0] + half[0], a[1] + half[1])
            m2 = (m1[0] + minor_step[0], m1[1] + minor_step[1])
            return [m1, m2, b]
        if prefer_major_first:
            return [c1, b] if s >= d else [c2, b]
        if prefer_major_last:
            return [c2, b] if s >= d else [c1, b]

    if samples:
        e1 = _polyline_deviation(samples, a, c1, b)
        e2 = _polyline_deviation(samples, a, c2, b)
        if abs(e1 - e2) > 1e-6:
            return [c1, b] if e1 < e2 else [c2, b]

    if prev_dir is not None:
        if _dir8(a, c1) == prev_dir:
            return [c1, b]
        if _dir8(a, c2) == prev_dir:
            return [c2, b]

    return [c1, b] if s >= d else [c2, b]


def _chamfer_right_angles(pts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Bevel sharp 90-degree turns (axis-to-axis and diag-to-diag) into 135-degree bends."""
    if len(pts) < 3:
        return pts
    out: list[tuple[int, int]] = [pts[0]]
    for i in range(1, len(pts) - 1):
        a = out[-1]
        p = pts[i]
        b = pts[i + 1]
        d1 = _dir8(a, p)
        d2 = _dir8(p, b)
        dot = d1[0] * d2[0] + d1[1] * d2[1]
        is_axis_90 = (d1[0] == 0 or d1[1] == 0) and (d2[0] == 0 or d2[1] == 0) and dot == 0
        is_diag_90 = (d1[0] != 0 and d1[1] != 0) and (d2[0] != 0 and d2[1] != 0) and dot == 0
        if is_axis_90 or is_diag_90:
            l1 = max(abs(p[0] - a[0]), abs(p[1] - a[1]))
            l2 = max(abs(b[0] - p[0]), abs(b[1] - p[1]))
            if l1 >= MIN_CHAMFER_LEG and l2 >= MIN_CHAMFER_LEG:
                cut = min(CHAMFER_TILES, l1 // 3, l2 // 3)
                if cut >= 2:
                    q = (p[0] - d1[0] * cut, p[1] - d1[1] * cut)
                    r = (p[0] + d2[0] * cut, p[1] + d2[1] * cut)
                    out.append(q)
                    out.append(r)
                    continue
        out.append(p)
    out.append(pts[-1])
    return out


def _collapse_micro_legs(pts: list[tuple[int, int]],
                         pin_start: bool = False,
                         pin_end: bool = False) -> list[tuple[int, int]]:
    """Smooth tiny <= ``MICRO_LEG_TILES`` interior jogs into clean 8-way bends."""
    if len(pts) < 4:
        return pts
    cur = list(pts)
    changed = True
    while changed and len(cur) >= 4:
        changed = False
        nxt: list[tuple[int, int]] = [cur[0]]
        i = 1
        while i < len(cur) - 2:
            a, b, c, d = nxt[-1], cur[i], cur[i + 1], cur[i + 2]
            leg_bc = max(abs(c[0] - b[0]), abs(c[1] - b[1]))
            at_start = pin_start and len(nxt) == 1
            at_end = pin_end and i + 2 == len(cur) - 1
            if leg_bc <= MICRO_LEG_TILES and not (at_start and at_end):
                bridged = _route_8way(
                    a,
                    d,
                    [],
                    _dir8(a, b),
                    prefer_major_first=at_start,
                    prefer_major_last=at_end,
                )
                if len(bridged) == 1:
                    dev = max(_dist_seg(b, a, d), _dist_seg(c, a, d))
                elif len(bridged) == 2:
                    mid = bridged[0]
                    dev = max(
                        min(_dist_seg(b, a, mid), _dist_seg(b, mid, d)),
                        min(_dist_seg(c, a, mid), _dist_seg(c, mid, d)),
                    )
                else:
                    dev = 1e9
                if dev <= MICRO_LEG_TILES + 1.0:
                    nxt.extend(bridged[:-1])
                    i += 2
                    changed = True
                    continue
            nxt.append(b)
            i += 1
        nxt.extend(cur[i:])
        cur = _merge_collinear(nxt)
    return cur


def _merge_collinear(pts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(pts) < 3:
        return pts
    out: list[tuple[int, int]] = [pts[0]]
    for pt in pts[1:]:
        if pt == out[-1]:
            continue
        if len(out) >= 2 and _dir8(out[-2], out[-1]) == _dir8(out[-1], pt):
            out[-1] = pt
        else:
            out.append(pt)
    return out


def _route_stretch(raw_pts: list[tuple[float, float]],
                   is_small_loop: bool = False,
                   pin_start: bool = False,
                   pin_end: bool = False) -> list[tuple[int, int]]:
    if len(raw_pts) < 2:
        return [_snap(p) for p in raw_pts]
    tol = LOOP_SIMPLIFY_TOLERANCE_TILES if is_small_loop else SIMPLIFY_TOLERANCE_TILES
    simp = _douglas_peucker(raw_pts, tol)
    snapped: list[tuple[int, int]] = []
    simp_to_raw: list[int] = []
    raw_cursor = 0
    for sp in simp:
        while raw_cursor < len(raw_pts) - 1 and raw_pts[raw_cursor] != sp:
            raw_cursor += 1
        q = _snap(sp)
        if not snapped or q != snapped[-1]:
            snapped.append(q)
            simp_to_raw.append(raw_cursor)
    if len(snapped) < 2:
        return [_snap(raw_pts[0]), _snap(raw_pts[-1])]

    routed: list[tuple[int, int]] = [snapped[0]]
    for idx in range(len(snapped) - 1):
        a = routed[-1]
        b = snapped[idx + 1]
        r0 = simp_to_raw[idx]
        r1 = simp_to_raw[idx + 1]
        samples = raw_pts[r0 + 1:r1] if r1 > r0 + 1 else []
        prev_dir = _dir8(routed[-2], routed[-1]) if len(routed) >= 2 else None
        for nxt in _route_8way(
            a,
            b,
            samples,
            prev_dir,
            prefer_major_first=(pin_start and idx == 0),
            prefer_major_last=(pin_end and idx == len(snapped) - 2),
        ):
            if nxt != routed[-1]:
                routed.append(nxt)
    routed = _merge_collinear(routed)
    if not is_small_loop:
        routed = _collapse_micro_legs(routed, pin_start=pin_start, pin_end=pin_end)
        routed = _chamfer_right_angles(routed)
        routed = _merge_collinear(routed)
    return routed


def apply_vanilla_grid(features: list[OSMFeature], proj, classify, is_polygon) -> int:
    """Rewrite road features onto an exact 0/45/90-degree integer tile grid."""
    road_feats: list[OSMFeature] = []
    node_counts: dict[tuple[int, int], int] = {}

    for feat in features:
        if feat.kind != "way" or is_polygon(feat) or len(feat.geometry) < 2:
            continue
        if classify(feat.tags) not in ROAD_CATEGORIES:
            continue
        road_feats.append(feat)
        seen_in_way: set[tuple[int, int]] = set()
        for lat, lon in feat.geometry:
            key = _snap(proj.to_px(lat, lon))
            if key not in seen_in_way:
                seen_in_way.add(key)
                node_counts[key] = node_counts.get(key, 0) + 1

    changed = 0
    for feat in road_feats:
        px_pts = [proj.to_px(lat, lon) for lat, lon in feat.geometry]
        is_closed = _snap(px_pts[0]) == _snap(px_pts[-1]) and len(px_pts) >= 4
        xs = [p[0] for p in px_pts]
        ys = [p[1] for p in px_pts]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        is_small_loop = is_closed and span <= SMALL_LOOP_SPAN_TILES

        pins = {0, len(px_pts) - 1}
        for i in range(1, len(px_pts) - 1):
            if node_counts.get(_snap(px_pts[i]), 0) >= 2:
                pins.add(i)

        sorted_pins = sorted(pins)
        new_px: list[tuple[int, int]] = []
        for a, b in zip(sorted_pins, sorted_pins[1:]):
            pin_a = node_counts.get(_snap(px_pts[a]), 0) >= 2
            pin_b = node_counts.get(_snap(px_pts[b]), 0) >= 2
            seg = _route_stretch(
                px_pts[a:b + 1],
                is_small_loop=is_small_loop,
                pin_start=pin_a,
                pin_end=pin_b,
            )
            if not new_px:
                new_px.extend(seg)
            else:
                new_px.extend(seg[1:])

        if is_closed and new_px:
            new_px[-1] = new_px[0]
        if len(new_px) >= 2:
            feat.geometry = [proj.to_latlon(float(x), float(y)) for x, y in new_px]
            changed += 1
    return changed
