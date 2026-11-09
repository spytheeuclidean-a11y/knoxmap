"""Head-to-head: snap._search against the same search in Rust (throwaway).

    python tools/bench_rust.py [size]

Both are given the same link: the same window, the same costs, the same
settings. The paths must match corner for corner - that is the point of the
port - and the times are the point of the exercise.
"""
import math
import os
import sys
import time
from types import SimpleNamespace

# Run from anywhere: the imports below are KnoxMap's own, one folder up from
# tools/ - where this file lives now that it is no longer a loose script at the
# top of the repository.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import shapely

from generator import osm
from generator.roadgraph import modes, route as route_mod, snap
from generator.roadgraph import rustsearch

SIZE = 800
ROAD_W = 8


def proj(size=SIZE):
    return SimpleNamespace(width=size, height=size, meters_per_tile=1.0,
                           to_px=lambda lat, lon: (lon, lat), to_latlon=lambda x, y: (y, x))


def town(size=SIZE):
    feats, n = [], 0

    def add(tags, pts):
        nonlocal n
        n += 1
        feats.append(osm.OSMFeature(n, "way", tags, pts))

    step = max(40, size // 12)
    for k in range(step, size - step + 1, step):
        add({"highway": "residential", "name": f"Street {k}"}, [(step, k), (size - step, k)])
        add({"highway": "residential", "name": f"Avenue {k}"}, [(k, step), (k, size - step)])
    q = size / 6
    add({"highway": "primary", "name": "High Pike"},
        [(step, step), (q, q + q / 3), (2 * q, 2 * q - q / 4), (3 * q, 3 * q + q / 3),
         (4 * q, 4 * q - q / 5), (5 * q, 5 * q + q / 4), (size - step, size - step)])
    for k in range(step, size - step + 1, step):
        for x in range(step, size - step, 20):
            for cy in (k - 12, k + 12):
                add({"building": "house"},
                    [(x, cy), (x + 8, cy), (x + 8, cy + 8), (x, cy + 8), (x, cy)])
    return feats


def fields(pts, s, g, town_mask, H, W, width, road_w=None,
           band_town=snap.BAND, alpha_town=snap.ALPHA):
    """The window and its costs, exactly as snap._search works them out (near off)."""
    road_w = road_w or width
    pts = [s] + list(pts[1:-1]) + [g]
    line = shapely.LineString(pts)
    wide, free_town = 1, snap.FREE_MAIN
    far = (snap.BAND_OPEN if town_mask is not None else band_town) * wide
    x0 = int(math.floor(min(p[0] for p in pts) - far - 2))
    y0 = int(math.floor(min(p[1] for p in pts) - far - 2))
    x1 = int(math.ceil(max(p[0] for p in pts) + far + 2))
    y1 = int(math.ceil(max(p[1] for p in pts) + far + 2))
    gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
    dist = snap._dist_field(line, gx, gy, far)
    inside = town_mask[np.clip(gy, 0, H - 1), np.clip(gx, 0, W - 1)]
    band = np.where(inside, band_town * wide, snap.BAND_OPEN * wide)
    alpha = np.where(inside, alpha_town, snap.ALPHA_OPEN)
    free = np.where(inside, free_town, snap.FREE_OPEN)
    over = np.maximum(dist - free, 0.0)
    weight = np.where(dist <= band, 1 + alpha * over * over + snap.TIE * dist * dist, np.inf)
    run_here = np.where(inside, width, 2 * width)
    way = np.zeros(gx.shape)
    flat = np.nonzero(dist <= band)
    px, py = gx[flat], gy[flat]
    along = shapely.line_locate_point(line, shapely.points(px, py))
    p0 = shapely.line_interpolate_point(line, np.maximum(along - 2.0, 0.0))
    p1 = shapely.line_interpolate_point(line, np.minimum(along + 2.0, line.length))
    way[flat] = np.degrees(np.arctan2(shapely.get_y(p1) - shapely.get_y(p0),
                                      shapely.get_x(p1) - shapely.get_x(p0))) % 360
    cdens = None
    if snap.COST is not None:
        CH, CW = snap.COST.shape
        cdens = snap.COST[np.clip(gy, 0, CH - 1), np.clip(gx, 0, CW - 1)]
        if snap.JOG is not None:
            run_here = np.where(cdens >= snap.JOG_DENSITY, snap.JOG_RUN * run_here, run_here)
    occw = None
    if snap.OCC is not None and snap.OCC_WEIGHT > 0:
        f = snap.occ_field(road_w)
        FH, FW = f.shape
        occw = snap.OCC_WEIGHT * f[np.clip(gy, 0, FH - 1), np.clip(gx, 0, FW - 1)]
    turnable = None
    if snap.JOG is not None and snap.COST is not None and snap.JOG.get("plots") is None:
        CH, CW = snap.JOG["dist"].shape
        gap = snap.JOG["dist"][np.clip(gy, 0, CH - 1), np.clip(gx, 0, CW - 1)] > road_w / 2 + snap.JOG_GAP
        turnable = ((cdens < snap.JOG_DENSITY) | gap)
    return dict(x0=x0, y0=y0, w=x1 - x0 + 1, h=y1 - y0 + 1, weight=weight, way=way, dens=cdens,
                occ=occw, turnable=turnable, run_here=run_here)


def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 else SIZE
    feats = town(size)
    p = proj(size)
    rings = modes.building_rings(feats, p)
    town_mask = route_mod.town_mask(rings, size, size)
    modes.prepare("cost", rings, size, size)
    try:
        road = [f for f in feats if f.tags.get("highway") == "primary"][0]
        pts = [p.to_px(la, lo) for la, lo in road.geometry]
        s = (int(round(pts[0][0])), int(round(pts[0][1])))
        g = (int(round(pts[-1][0])), int(round(pts[-1][1])))
        q0 = snap._point_along(pts, 8.0)
        head = snap._nearest(snap._bearing(q0[0] - s[0], q0[1] - s[1]))[0]
        qt = snap._point_along(pts[::-1], 8.0)
        arr = snap._nearest(snap._bearing(g[0] - qt[0], g[1] - qt[1]))[0]

        t0 = time.perf_counter()
        f = fields(pts, s, g, town_mask, size, size, ROAD_W,
                   band_town=snap.STROKE_BAND, alpha_town=snap.STROKE_ALPHA)
        t_fields = time.perf_counter() - t0

        # What the first step of the search costs, from the fields themselves.
        i0 = (67 - f["y0"]) * f["w"] + (68 - f["x0"])
        w0 = f["weight"].ravel()[i0]
        d0 = 0.0 if f["dens"] is None else f["dens"].ravel()[i0]
        base0 = snap.LENGTH[1] * snap.SLOPE_COST["2:1"] * w0
        dens0 = 0.0 if f["dens"] is None else snap.LENGTH[1] * snap.COST_SCALE * \
            snap.DIR_PENALTY["2:1"] * d0
        print(f"  at (68,67): weight {w0:.6f}, dens {d0:.6f}, way {f['way'].ravel()[i0]:.3f}, "
              f"run_here {f['run_here'].ravel()[i0]} -> step {base0:.6f} + {dens0:.6f} "
              f"= {base0 + dens0:.6f}")

        run = snap.min_run(ROAD_W)
        cap = int(f["run_here"].max()) * 2
        kwargs = dict(x0=f["x0"], y0=f["y0"], w=f["w"], h=f["h"],
                      s=s, g=g, h_start=head, h_arrive=arr, reach=0, run_min=run, cap=cap,
                      end_run=(run + 1) // 2, end_r=run + 4, road_width=ROAD_W,
                      beta=snap.BETA_MAIN, lean=1.0, limit=None,
                      weight=f["weight"], way=f["way"], dens=f["dens"], occ=f["occ"],
                      turnable=f["turnable"], run_here=f["run_here"],
                      taken_idx=np.zeros(0, "i4"), taken_owner=np.zeros(0, "i4"))

        snap.STATES["searched"] = 0
        py_trace = []
        t0 = time.perf_counter()
        py_path = snap._search(pts, s, g, head, arr, 1, run, {}, 0, 0, town_mask,
                               snap.BETA_MAIN, snap.STROKE_BAND, snap.STROKE_ALPHA,
                               snap.FREE_MAIN, 1.0, 5_000_000, None, ROAD_W, (), trace=py_trace)
        t_py = time.perf_counter() - t0
        py_states = snap.STATES["searched"]

        router = rustsearch.Router()
        try:
            rs_trace, _ = router.search(**{**kwargs, "trace": 300})
            reps = []
            for _ in range(3):
                t0 = time.perf_counter()
                rs_path, rs_states = router.search(**kwargs)
                reps.append(time.perf_counter() - t0)
            t_rs = min(reps)
            print(f"  Rust reps: {', '.join(f'{v:.2f} s' for v in reps)}")
        finally:
            router.close()

        # Where do the two searches first disagree about what to pop?
        n = min(len(py_trace), len(rs_trace))
        bad = next((k for k in range(n) if py_trace[k] != rs_trace[k]), None)
        print(f"  traces: {len(py_trace)} python pops vs {len(rs_trace)} rust pops, "
              f"first disagreement at {bad}")
        if bad is not None:
            print(f"    python: {py_trace[bad]}")
            print(f"    rust:   {rs_trace[bad]}")
            if bad:
                print(f"    (previous: python {py_trace[bad - 1]}, rust {rs_trace[bad - 1]})")

        def length(path):
            return 0.0 if not path else sum(math.dist(a, b) for a, b in zip(path, path[1:]))

        def off(path):
            line = shapely.LineString(pts)
            return 0.0 if not path else max(line.distance(shapely.Point(q)) for q in path)

        print(f"size {size}: road {len(pts)} points, window {f['w']}x{f['h']}")
        print(f"  fields (Python, shared): {t_fields:6.2f} s")
        print(f"  Python search: {t_py:7.2f} s, {py_states:>9,} states, "
              f"path {length(py_path):7.1f} tiles, max {off(py_path):5.1f} off")
        print(f"  Rust search:   {t_rs:7.2f} s, {rs_states:>9,} states, "
              f"path {length(rs_path):7.1f} tiles, max {off(rs_path):5.1f} off")
        def gaps(path):
            """Segments that are not one lattice step: corners the rebuild lost."""
            bad = 0
            for a, b in zip(path or [], (path or [])[1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                k = math.gcd(abs(dx), abs(dy)) or 1
                if (dx // k, dy // k) not in snap.STEP:
                    bad += 1
            return bad

        print(f"  corners off the sixteen directions: python {gaps(py_path)}, rust {gaps(rs_path)}")
        same = (py_path == rs_path)
        print(f"  identical paths: {same}")
        if not same and py_path and rs_path:
            k = next((i for i, (a, b) in enumerate(zip(py_path, rs_path)) if a != b), None)
            print(f"  first difference at corner {k}: python {py_path[k] if k is not None else None} "
                  f"vs rust {rs_path[k] if k is not None else None}, "
                  f"lengths {len(py_path)} vs {len(rs_path)}")
    finally:
        modes.reset()


if __name__ == "__main__":
    main()
