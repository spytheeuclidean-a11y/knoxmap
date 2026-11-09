"""Whole-map equivalence: one town routed by both engines (throwaway).

    python tools/equiv_map.py [size]

The real pipeline - route.route -> snap.snap -> snap._route -> snap._search -
run twice on identical input: once with snap.BACKEND = "python", once with
"rust". The roads, the snapped junctions and the states searched (search by
search) must come out the same; where they do not, the first search that
differs is replayed under both engines and their pops are compared.
"""
import json
import os
import sys
import time
from types import SimpleNamespace

# Run from anywhere: the imports below are KnoxMap's own, one folder up from
# tools/, where this file lives now that it is no longer a loose script at the
# top of the repository.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import osm
from generator.roadgraph import modes, route as route_mod, snap

SIZE = 240


def proj(size):
    return SimpleNamespace(width=size, height=size, meters_per_tile=1.0,
                           to_px=lambda lat, lon: (lon, lat), to_latlon=lambda x, y: (y, x))


def town(size):
    """Streets, one curved primary across them, and a house along every street."""
    feats, n = [], 0

    def add(tags, pts):
        nonlocal n
        n += 1
        feats.append(osm.OSMFeature(n, "way", tags, pts))

    step = max(30, size // 4)
    for k in range(step, size - step + 1, step):
        add({"highway": "residential", "name": f"Street {k}"}, [(step, k), (size - step, k)])
        add({"highway": "residential", "name": f"Avenue {k}"}, [(k, step), (k, size - step)])
    q = size / 6
    add({"highway": "primary", "name": "High Pike"},
        [(step, step), (q, q + q / 3), (2 * q, 2 * q - q / 4), (3 * q, 3 * q + q / 3),
         (4 * q, 4 * q - q / 5), (5 * q, 5 * q + q / 4), (size - step, size - step)])
    for k in range(step, size - step + 1, step):
        for x in range(step, size - step, 16):
            for cy in (k - 10, k + 10):
                add({"building": "house"},
                    [(x, cy), (x + 6, cy), (x + 6, cy + 6), (x, cy + 6), (x, cy)])
    return feats


def run(feats, p, backend):
    """The whole town, plus a line per search: which link cost how many states."""
    log = []
    plain = snap._search

    def watched(*a, **k):
        snap.STATES["searched"] = 0
        args = a[:7] + (dict(a[7]),) + a[8:]        # the taken corners as they were
        out = plain(*args, **k)
        log.append(((a[1], a[2], a[3], a[4], a[15], a[16]), snap.STATES["searched"],
                    None if out is None else len(out), args))
        return out

    snap.BACKEND = backend
    snap._search = watched
    t0 = time.perf_counter()
    try:
        out = route_mod.route(feats, p, mode="cost", log=lambda *a: None)
    finally:
        snap._search = plain
    return out, time.perf_counter() - t0, sum(line[1] for line in log), log


def replay(args, trace=None):
    t0 = time.perf_counter()
    got = snap._search(*args, trace=trace)
    return got, time.perf_counter() - t0


def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 else SIZE
    feats = town(size)
    p = proj(size)
    try:
        py, t_py, n_py, lpy = run(feats, p, "python")
        rs, t_rs, n_rs, lrs = run(feats, p, "rust")
        same = json.dumps(py, sort_keys=True, default=list) == json.dumps(rs, sort_keys=True,
                                                                        default=list)
        print(f"size {size}: {len(feats)} features, {len(lpy)} searches, town routed both ways")
        print(f"  python: {t_py:7.2f} s, {n_py:>10,} states")
        print(f"  rust:   {t_rs:7.2f} s, {n_rs:>10,} states")
        print(f"  identical roads: {same}")
        diffs = [k for k in range(min(len(lpy), len(lrs))) if lpy[k][:3] != lrs[k][:3]]
        routes = [k for k in diffs if lpy[k][2] is not None or lrs[k][2] is not None]
        print(f"  searches that differ: {len(diffs)} of {len(lpy)} "
              f"({len(routes)} of them found a path)")
        bad = diffs[0] if diffs else None
        if bad is None and len(lpy) == len(lrs):
            print(f"  every one of the {len(lpy)} searches matched: same states, same corners")
            return
        print(f"  first differing search #{bad}:")
        print(f"    python: {lpy[bad][:3]}")
        print(f"    rust:   {lrs[bad][:3]}")
        args = lpy[bad][3]
        # route.route resets the mode's fields when it returns: put them back, or the
        # replay is a different search.
        modes.prepare("cost", modes.building_rings(feats, p), size, size)
        snap.BACKEND = "python"
        got_py, _ = replay(args, trace=(tp := []))
        snap.BACKEND = "rust"
        snap.TRACE_TO = (tr := [])
        try:
            got_rs, _ = replay(args)
        finally:
            snap.TRACE_TO = None
        snap.BACKEND = "python"
        short = lambda g: None if g is None else len(g)
        print(f"    replayed: python {short(got_py)} ({len(tp)} pops), "
              f"rust {short(got_rs)} ({len(tr)} pops)")
        def starts(trace):
            """The estimate each heading's start state went in with (cost 0)."""
            out = {}
            for f, c, x, y, hd, run, last in trace:
                if c in (0.0, -0.0) and hd not in out:
                    out[hd] = f
            return out
        ps, rs = starts(tp), starts(tr)
        print("    start estimates by heading:")
        for hd in range(snap.N):
            a, b = ps.get(hd), rs.get(hd)
            flag = "" if a == b else "   <-- differs"
            print(f"      hd {hd:2d}: python {a} rust {b}{flag}")
        for want in ((180, 102), (180, 101), (180, 110)):
            print(f"    estimates at {want}:")
            for name, tr_ in (("python", tp), ("rust", tr)):
                got = [e for e in tr_ if (e[2], e[3]) == want][:3]
                print(f"      {name}: " + ("  ".join(
                    f"f={e[0]!r} cost={e[1]:.3f} hd={e[4]} run={e[5]} (h={e[0] - e[1]:.6f})"
                    for e in got) or "not popped"))
        print("    pops 12..20:")
        for i in range(12, 21):
            print(f"      {i:2d}: python {tp[i] if i < len(tp) else None}")
            print(f"          rust   {tr[i] if i < len(tr) else None}")
        k = next((i for i in range(min(len(tp), len(tr))) if tp[i] != tr[i]), None)
        print(f"    first differing pop: {k}")
        if k is not None:
            print(f"      python: {tp[k]}")
            print(f"      rust:   {tr[k]}")
            if k:
                print(f"      before: python {tp[k - 1]}, rust {tr[k - 1]}")
    finally:
        snap.BACKEND = "python"
        modes.reset()


if __name__ == "__main__":
    main()
