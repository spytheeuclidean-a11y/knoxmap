"""A road between two junctions as one of vanilla's own street shapes.

Vanilla's stretches between junctions (counted once from the game's
streets.xml: stretch_shapes.json, each shape and how many times it is drawn -
no map data, only the tally) are two thirds dead
straight, and nearly all the rest one or two bends (only shapes vanilla uses
MIN_SEEN times or more are offered): a right angle, sharp or
curved; a 45; a dog-leg out and back; a U. For a link whose ends are fixed
(their corners and the headings its junctions give it) each shape with up
to two bends is fitted: its straights' lengths solved so it lands exactly
on the far corner - one bend has one answer, two bends one free length,
tried along the way - every straight at least the minimum run, its bends
SHARP corners or CURVES as snap.py draws them. A fit is kept if the real
road stays within reach of it; the one chosen is the closest, plus a cost
for how rare its shape is in vanilla (PRIOR_WEIGHT x -log of its share).
Shapes are counted by family - a right angle or a 45 is one bend, sharp or
curved - and each corner's style costs by how often vanilla draws it so: a
loop road can be a U with curved corners though vanilla's few Us are sharp.
"""
from __future__ import annotations

import json
import math
import os

import numpy as np
import shapely

from . import snap

HERE = os.path.dirname(os.path.abspath(__file__))
SHAPES = os.path.join(HERE, "stretch_shapes.json")
PRIOR_WEIGHT = 1.5           # tiles of mean distance from the real road one nat of rarity is worth
MIN_SEEN = 3                 # a shape family vanilla uses fewer times than this is not offered
SAMPLE = 2.0                 # tiles between the real road's sample points
# A shape's bends: S (sharp) by one, two or four notches; C (curved) right
# angle or 45, as snap.curves draws them.
TOKENS = [("S", 1), ("S", 2), ("S", 4), ("C", 4), ("C", 2)]

_stats = None


def _family(key: str) -> str:
    """A shape with its corners' style left out: a right angle or a 45 is one
    bend whether sharp or curved (R, F), so a U is a U, curved or not."""
    out = []
    for tok in key.split():
        kind, turn = tok[0], int(tok[1:])
        out.append(("R" if abs(turn) == 4 else "F" if abs(turn) == 2 else kind) + f"{'+' if turn > 0 else '-'}")
    return " ".join(out)


def _load():
    """Vanilla's shape families' shares, and how often each size of bend is curved."""
    global _stats
    if _stats is None:
        with open(SHAPES, encoding="utf-8") as f:
            counts = json.load(f)
        total = sum(counts.values())
        fam: dict = {}
        curved = {2: [0, 0], 4: [0, 0]}                     # turn -> [curved, all]
        for key, n in counts.items():
            fam[_family(key)] = fam.get(_family(key), 0) + n
            for tok in key.split():
                t = abs(int(tok[1:]))
                if t in curved:
                    curved[t][1] += n
                    curved[t][0] += n * (tok[0] == "C")
        _stats = {"family": fam, "total": total,
                  "curved": {t: c / a for t, (c, a) in curved.items() if a}}
    return _stats


def prior(shape_key: str) -> float:
    """-log of how likely vanilla draws a stretch this way: its family's share,
    times each corner's chance of its style (a right angle is curved 44% of
    the time, a 45 28%)."""
    st = _load()
    cost = -math.log(max(st["family"].get(_family(shape_key), 0), 0.5) / st["total"])
    for tok in shape_key.split():
        t = abs(int(tok[1:]))
        if t in st["curved"]:
            p = st["curved"][t]
            cost -= math.log(p if tok[0] == "C" else 1 - p)
    return cost


def _key(tokens) -> str:
    """The shape's name as stretch_shapes.json has it (mirrored to turn positive first)."""
    if tokens and tokens[0][1] < 0:
        tokens = [(k, -t) for k, t in tokens]
    return " ".join(f"{k}{t:+d}" for k, t in tokens)


def _shapes(max_bends: int = 2):
    """The shapes offered: up to max_bends bends, of a family vanilla uses
    MIN_SEEN times or more (its corners sharp or curved either way)."""
    import itertools
    fam = _load()["family"]
    out = [[]]
    signed = [(k, t * sg) for k, t in TOKENS for sg in (1, -1)]
    for n in range(1, max_bends + 1):
        out += [list(c) for c in itertools.product(signed, repeat=n) if fam.get(_family(_key(list(c))), 0) >= MIN_SEEN]
    return out


def _bend(kind: str, turn: int, h: int, width: int, scale: float):
    """A bend's pieces [(heading, steps)] and the heading after it, or None."""
    if kind == "S":
        return [], (h + turn) % snap.N
    for k, t, pieces in snap.curves(h, width, scale):
        if t == turn and ((k == "half") == (abs(turn) == 2)) and k != "cut":
            return pieces, (h + turn) % snap.N
    return None


def _walk(s, runs):
    """The corners along [(heading, steps)] from s."""
    out = [tuple(s)]
    x, y = s
    for h, n in runs:
        dx, dy = snap.STEP[h]
        for _ in range(n):
            x, y = x + dx, y + dy
            out.append((x, y))
    return out


MAX_SAMPLES = 256            # the real road is compared at most this often


def _samples(real):
    """Points along the real line, shape only.

    Every SAMPLE tiles is right for a street, but a kilometres-long link (a
    beach road on a 119 km2 map) made each candidate comparison quadratic:
    thousands of samples against thousands of corners, again for each shape.
    One link sat here for over half an hour. Cap the count; the fit only needs
    the shape.
    """
    span = np.arange(0, real.length + SAMPLE / 2, SAMPLE)
    if len(span) > MAX_SAMPLES:
        span = np.linspace(0, real.length, MAX_SAMPLES)
    return shapely.line_interpolate_point(real, span)


def fit(real_pts, s, g, hs, ha, width, run_min, reach_tiles, scale=1.0, taken=None, me=None, end_r=8,
        near=None, clear_cost=0.0):
    """The best vanilla-shaped path from corner s on heading hs to corner g
    (arriving on ha; None: any), or None. Returns (path corners, shape key,
    mean distance)."""
    real = shapely.LineString(real_pts)
    samples = _samples(real)
    D = np.array(g, int) - np.array(s, int)
    end_run = max(1, (run_min + 1) // 2)
    best = None
    for tokens in _shapes():
        # Headings of the straights, and the bends' pieces, from hs.
        hs_list, bends = [hs], []
        ok = True
        for kind, turn in tokens:
            b = _bend(kind, turn, hs_list[-1], width, scale)
            if b is None:
                ok = False
                break
            bends.append(b[0])
            hs_list.append(b[1])
        if not ok or (ha is not None and hs_list[-1] != ha):
            continue
        fixed = np.zeros(2, int)
        for pieces in bends:
            for h, n in pieces:
                fixed += n * np.array(snap.STEP[h])
        rest = D - fixed
        U = [np.array(snap.STEP[h]) for h in hs_list]
        mins = [end_run] + [run_min] * (len(U) - 2) + [end_run] if len(U) > 1 else [1]
        solutions = []
        if len(U) == 1:
            u = U[0]
            k = rest @ u / (u @ u)
            if abs(k - round(k)) < 1e-9 and round(k) >= mins[0] and np.array_equal(round(k) * u, rest):
                solutions.append([int(round(k))])
        else:
            # The last two lengths solved from the rest; the first (if three) tried along the way.
            A = np.column_stack([U[-2], U[-1]])
            det = A[0, 0] * A[1, 1] - A[0, 1] * A[1, 0]
            if det == 0:
                continue
            free = [[]] if len(U) == 2 else [[L0] for L0 in range(mins[0], int(np.abs(rest).sum()) + 1)]
            for lead in free:
                r = rest - sum(L * u for L, u in zip(lead, U))
                l1 = (r[0] * A[1, 1] - r[1] * A[0, 1]) / det
                l2 = (A[0, 0] * r[1] - A[1, 0] * r[0]) / det
                if abs(l1 - round(l1)) > 1e-9 or abs(l2 - round(l2)) > 1e-9:
                    continue
                lengths = lead + [int(round(l1)), int(round(l2))]
                if all(L >= m for L, m in zip(lengths, mins)):
                    solutions.append(lengths)
        key = _key(tokens)
        for lengths in solutions:
            runs = []
            for k, L in enumerate(lengths):
                runs.append((hs_list[k], L))
                if k < len(bends):
                    runs += bends[k]
            path = _walk(s, runs)
            if path[-1] != tuple(g):
                continue
            line = shapely.LineString(path).simplify(1.0)
            d = shapely.distance(samples, line)
            if d.max() > reach_tiles:
                continue
            if taken is not None and any(
                    taken.get(p) not in (None, me) and
                    min(abs(p[0] - s[0]) + abs(p[1] - s[1]), abs(p[0] - g[0]) + abs(p[1] - g[1])) > end_r
                    for p in path[1:-1]):
                continue
            score = float(d.mean()) + PRIOR_WEIGHT * prior(key)
            if near is not None:
                # The share of its corners near another road's edge (not by its own ends), as snap costs it.
                H, W = near.shape
                far_end = run_min + 6
                close = sum(1 for p in path if 0 <= p[1] < H and 0 <= p[0] < W and near[p[1], p[0]]
                            and math.dist(p, s) > far_end and math.dist(p, g) > far_end)
                score += clear_cost * close / max(len(path), 1) * 10
            if best is None or score < best[0]:
                best = (score, path, key, float(d.mean()))
    return None if best is None else (best[1], best[2], best[3])
