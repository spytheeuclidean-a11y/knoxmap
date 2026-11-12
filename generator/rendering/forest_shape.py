"""Forests with stands, thin patches and clearings, thinning to their edge.

A forest was every tile the same grade, stepped thicker or thinner all at
once by the Forests setting: a wall of trees, or a uniformly thinner one.
Here each forest tile takes its grade from a smooth noise field - blobs about
Stand size across - pulled down near the forest's edge, and the field is cut
at its own quantiles so the share of each grade is exactly what the density
asks for. Lowering the density opens clearings where the noise is lowest and
thins the edge first, rather than thinning every tile.

The woodland pass (generator/rendering/vegetation.py) draws the forest first,
natively on big maps; this re-grades it after.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from .. import pz_colors as C
from .forest_params import ForestParams

FOREST_SEED = 2207            # ForestParams().seed; kept for callers that name it
# Thinnest first: the grade is an index into this.
GRADES = (C.VEG_NOTHING, C.SPARSE_TREES, C.TREES_DARK_GRASS, C.TREES)
NAMES = ("open", "sparse", "grass", "dense")
# (density, (open, sparse, grass, dense)), linear in between.
#
# Dense is a wall: the game's rules put a tree on every one of its tiles,
# where trees in grass has one on about half and sparse on a fifth. A forest
# that was half wall could not be walked through, so at the default only a
# tenth of it is - small thickets where the noise peaks - and even the
# thickest setting leaves most of a wood passable.
#
# And a wood is a wood: it is never given a clearing it does not have. Where
# the map or the land cover data says trees, every tile keeps some - the
# density only decides how many, from sparse to a wall. Bare ground in a wood
# is for turning the density below a half, which asks for the woods to go.
SHARE_TABLE = (
    (0.0, (1.0, 0.0, 0.0, 0.0)),
    (0.5, (0.0, 0.65, 0.33, 0.02)),
    (1.0, (0.0, 0.28, 0.62, 0.10)),
    (2.0, (0.0, 0.12, 0.63, 0.25)),
    (3.0, (0.0, 0.05, 0.55, 0.40)),
)
# A wood is never thinned from its edge in: every tile inside it keeps its
# full value, as far out as the map says it reaches. It spills out instead -
# outside it, a tile's value is scaled from 1 on the edge down to 0 at Edge
# softness out, so trees run on over the open grass beside it, thinning as they
# go. Thinning it inwards carved a bare band inside every wood, and its narrow
# arms, all edge, went first.
#
# How far it spills is moved in and out by smooth noise, up to Edge wobble of Edge
# softness, so the spill keeps to neither WorldCover's 10 m staircase nor a
# mapper's straight line. Beside a narrow arm it spills no further than the arm
# is wide.
# The spill is not graded against the wood's own cuts: those are set for the
# middle of a wood, and nothing scaled much below it got past them, so a 12 m
# spill reached 3 m. Its trees cover all of the grass beside the wood, falling
# in a straight line to none at Edge softness out; where the stand noise is
# high they stand thicker, the top Spill thickness of what grows trees in grass.
SAMPLE_EVERY = 4           # the quantiles are read off every fourth tile
EDGE_STEPS = 8             # a wide edge is measured in about this many steps
STRIP_ROWS = 512
FRINGE_CLEAR = 2           # tiles kept clear of anything that is not grass


DENSE_CAP = 0.9           # Thickets never makes more of a wood than this a wall


def shares(density: float, thickets: float = 1.0) -> tuple[float, float, float, float]:
    """(open, sparse, grass, dense) for a density, from SHARE_TABLE, the dense
    share times `thickets`: what that adds is taken from trees in grass, what
    it frees goes to it, so the wood keeps its open and sparse shares."""
    d = min(max(float(density), SHARE_TABLE[0][0]), SHARE_TABLE[-1][0])
    base = SHARE_TABLE[-1][1]
    for (d0, s0), (d1, s1) in zip(SHARE_TABLE, SHARE_TABLE[1:]):
        if d <= d1:
            t = (d - d0) / (d1 - d0)
            base = tuple(round(a + (b - a) * t, 6) for a, b in zip(s0, s1))
            break
    if thickets == 1.0:
        return base
    o, s, g, dense = base
    new = min(DENSE_CAP, dense * max(0.0, thickets), dense + g)
    return (o, s, round(g - (new - dense), 6), round(new, 6))


VARIETY_SCALE = 2.5       # Stand variety's stands, times Stand size


def stand_lattices(h: int, w: int, cell: int, variety: float, raggedness: float,
                   seed: int) -> list:
    """The stand noise: stands 2.5 times as big weighted 0.5 x variety, Stand
    size and a quarter of it sharing the rest by raggedness. A weight of 0
    builds no lattice, so variety 0 and raggedness 0.25 draw today's two."""
    from .noise import lattices

    specs = []
    if variety > 0:
        specs.append((max(2, int(round(cell * VARIETY_SCALE))), 0.5 * variety))
    rest = 1.0 - 0.5 * variety
    if raggedness < 1:
        specs.append((cell, (1.0 - raggedness) * rest))
    if raggedness > 0:
        specs.append((max(2, cell // 4), raggedness * rest))
    return lattices(h, w, specs, seed)


def _erode(cur: np.ndarray) -> np.ndarray:
    """One step of 3 x 3 erosion, the map's border counting as forest."""
    p = np.pad(cur, 1, mode="edge")
    rows = np.minimum(np.minimum(p[:-2], p[1:-1]), p[2:])
    return np.minimum(np.minimum(rows[:, :-2], rows[:, 1:-1]), rows[:, 2:])


def edge_depth(forest: np.ndarray, reach: int) -> np.ndarray:
    """How many tiles in from the forest's edge each tile is, up to `reach`.
    The map's border is not an edge: the forest runs on past it.

    It only feeds a soft gradient, so a wide edge is measured on a coarser
    grid - blocks of `step` tiles, a block forest only if all of it is - and
    is right to within a block."""
    h, w = forest.shape
    step = max(1, reach // EDGE_STEPS)
    if step > 1:
        hh, ww = -(-h // step) * step, -(-w // step) * step
        padded = np.pad(forest, ((0, hh - h), (0, ww - w)), mode="edge")
        cur = padded.reshape(hh // step, step, ww // step, step).all(axis=(1, 3))
    else:
        cur = forest
    cur = cur.astype(np.uint8)
    depth = np.zeros(cur.shape, dtype=np.uint8)
    for _ in range(-(-reach // step)):
        cur = _erode(cur)
        if not cur.any():
            break
        depth += cur
    if step > 1:
        depth = np.minimum(depth.repeat(step, 0).repeat(step, 1)[:h, :w]
                           .astype(np.int32) * step, 255).astype(np.uint8)
    return depth


def _keys(arr: np.ndarray) -> np.ndarray:
    """Each RGB tile as one number, so a colour is one comparison."""
    return ((arr[..., 0].astype(np.uint32) << 16) | (arr[..., 1].astype(np.uint32) << 8)
            | arr[..., 2])


def _key(colour) -> int:
    return (colour[0] << 16) | (colour[1] << 8) | colour[2]


def _value(ys, xs, lats):
    """The stand noise at rows `ys`, columns `xs`."""
    from .noise import smooth_noise

    return smooth_noise(ys.astype(np.float32), xs.astype(np.float32), lats)


def _spill_out(ys, xs, edge, reach, wobble_share, keep=1.0):
    """How far out of the wood each tile is, as a share of how far it spills
    there (0 beside it, 1 and over past the spill), the spill's reach moved
    by noise, no wider than the wood beside it and - Keep meadows open - no
    more than `keep` of the way across the open space it spills into. Inside
    the wood, 0."""
    from .noise import smooth_noise

    signed, half, jitter, open_half = edge
    at = np.ix_(ys, xs)
    r = np.clip(half[at].astype(np.float32), 1.0, float(reach))
    if open_half is not None:
        r = np.minimum(r, keep * 2 * open_half[at].astype(np.float32))
    d = np.maximum(-signed[at].astype(np.float32) / 2 - 0.5, 0.0)
    wobble = (smooth_noise(ys.astype(np.float32), xs.astype(np.float32), jitter)
              - 0.5) * (2 * wobble_share)
    there = r * (1 + wobble)
    return np.where(there > 0, d / np.maximum(there, 1e-6), np.inf)


def _spread_max(a: np.ndarray, r: int) -> np.ndarray:
    """Each tile's maximum over the square `r` tiles round it, in log(r) steps."""
    out = a.copy()
    for axis in (0, 1):
        done = 0
        while done < r:
            k = min(done + 1, r - done)
            src = out.copy()
            if axis == 0:
                out[k:] = np.maximum(out[k:], src[:-k])
                out[:-k] = np.maximum(out[:-k], src[k:])
            else:
                out[:, k:] = np.maximum(out[:, k:], src[:, :-k])
                out[:, :-k] = np.maximum(out[:, :-k], src[:, k:])
            done += k
    return out


def _edge_fields(forest: np.ndarray, reach: int, h: int, w: int, seed: int,
                 keep: float = 1.0):
    """What the spill needs to know about the edge, or None with no Edge
    softness: the signed distance from it (int16 half tiles, + inside: a tile
    beside the edge on either side is 1 or -1), the half width of the wood
    round each tile (up to `reach`), the lattice that moves the spill, and the
    half width of the open space round each tile - None when Keep meadows
    open is off (`keep` 1) and nothing needs it.

    The open space is measured as far as it has to be: a spill of `reach` is
    only cut short in a space narrower than reach / keep, so that is how deep
    it is looked at (at most 255 tiles, the depth's own limit)."""
    from .noise import lattices

    if not reach:
        return None
    depth = edge_depth(forest, reach)
    # Twice the reach: a tile at the far end of the spill has to see the full
    # depth of the wood it came from, or the spill shrinks as it goes.
    half = _spread_max(depth, 2 * reach)
    outside = edge_depth(~forest, reach).astype(np.int16)
    signed = np.where(forest, 2 * depth.astype(np.int16) + 1,
                      -(2 * outside + 1)).astype(np.int16)
    jitter = lattices(h, w, [(max(3, reach), 1.0)], seed + 1)
    open_half = None
    if keep < 1:
        deep = int(min(255, max(reach, np.ceil(reach / max(2 * keep, 1e-3)))))
        open_half = _spread_max(edge_depth(~forest, deep), deep)
    return signed, half, jitter, open_half


def _free_grass(land: np.ndarray, vegp: np.ndarray, forest: np.ndarray) -> np.ndarray:
    """Open grass outside the wood a fringe may grow on: dark or medium grass
    (not a field's light grass), nothing on it, two tiles clear of anything
    that is not grass - the verge of a road or a drive is the road details
    pass's, not the wood's."""
    lkey = _keys(land)
    grass = (lkey == _key(C.DARK_GRASS)) | (lkey == _key(C.MEDIUM_GRASS))
    near_other = ~grass
    for _ in range(FRINGE_CLEAR):
        near_other = ~_erode((~near_other).astype(np.uint8)).astype(bool)
    return ~forest & grass & ~near_other & np.all(vegp == 0, axis=2)


def shape_forest(veg, landscape, forest, density: float, stand_m: float,
                 edge_m: float, metres_per_tile: float, params: ForestParams | None = None,
                 young_trees: bool = False) -> dict:
    """Re-grade the `forest` tiles (bool, h x w) of `veg` that the woodland
    pass gave a tree grade or left empty, on ground that is not water, and
    grow its fringe on the open grass outside it. Returns tiles per grade name,
    and the fringe's under "fringe".

    Nothing inside the wood is thinned for being near its edge. It spills out
    over the open grass beside it instead, thinning to nothing at Edge softness
    out, that distance moved in and out by noise so the wood keeps to neither
    WorldCover's 10 m staircase nor a mapper's straight line.
    The ground follows the trees: dark grass under them, the medium grass of a
    meadow where a clearing opens, and between the two in sparse woods - not
    the dark block the wood was painted on.

    params: the Forest card's knobs (generator/rendering/forest_params.py);
    stand_m and edge_m always come from the arguments. young_trees: whether
    the tree rules for young trees are installed."""
    p = params or ForestParams()
    vegp = np.array(veg)
    land = np.array(landscape)
    h, w = forest.shape
    vkey = _keys(vegp)
    lkey = _keys(land)
    todo = (forest & np.isin(vkey, [_key(c) for c in GRADES])
            & (lkey != _key(C.WATER)))
    del vkey
    if not todo.any():
        return {**{n: 0 for n in NAMES}, "fringe": 0}

    cell = max(2, int(round(stand_m / metres_per_tile)))
    lats = stand_lattices(h, w, cell, p.stand_variety, p.raggedness, p.seed)
    reach = int(round(edge_m / metres_per_tile))
    edge = _edge_fields(forest, reach, h, w, p.seed, p.keep_meadows)
    # The fringe reaches as far out as the wood beside it is soft: a thin arm's
    # fringe is as thin as its own edge.
    near = (_free_grass(land, vegp, forest)
            & (edge[0] > -2 * np.clip(edge[1].astype(np.int16), 1, reach))
            if reach else np.zeros_like(forest))

    # The cuts: quantiles of the value over the forest, so each grade gets
    # exactly its share. A share of nothing or everything is an infinite cut.
    sy = np.arange(0, h, SAMPLE_EVERY)
    sx = np.arange(0, w, SAMPLE_EVERY)
    sample = _value(sy, sx, lats)[todo[np.ix_(sy, sx)]]
    if sample.size == 0:
        sample = _value(np.arange(h), np.arange(w), lats)[todo]
    cuts, total = [], 0.0
    for share in shares(density, p.thickets)[:3]:
        total += share
        cuts.append(-np.inf if total <= 0 else np.inf if total >= 1
                    else float(np.quantile(sample, total)))
    cuts = np.array(cuts)
    # The spill reads the noise as a rank, 0 to 1 over the wood's own spread
    # of it, so a share of its tiles can be had by a line through that rank.
    lo, hi = (np.quantile(sample, (0.02, 0.98)) if sample.size else (0.0, 1.0))
    spill_on = shares(density, p.thickets)[0] < 1

    counts = np.zeros(4, dtype=np.int64)
    fringe = 0
    colours = np.array(GRADES, dtype=np.uint8)
    xs = np.arange(w)
    dark_k, med_k, light_k = (_key(C.DARK_GRASS), _key(C.MEDIUM_GRASS),
                              _key(C.LIGHT_GRASS))
    for top in range(0, h, STRIP_ROWS):
        bottom = min(h, top + STRIP_ROWS)
        t, n = todo[top:bottom], near[top:bottom]
        if not (t.any() or n.any()):
            continue
        ys = np.arange(top, bottom)
        v = _value(ys, xs, lats)
        grade = np.searchsorted(cuts, v, side="right")
        if n.any():
            # Outside: trees where the noise's rank beats the distance out, so
            # cover falls from all to none; the thickest of them in grass. It
            # never closes into a wall.
            if spill_on:
                u = np.clip((v - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
                t_out = _spill_out(ys, xs, edge, reach, p.edge_wobble, p.keep_meadows)
                with np.errstate(invalid="ignore"):   # t_out is inf where no spill reaches
                    out_grade = np.where(u > t_out + (1 - t_out) * (1 - p.spill_thick), 2,
                                         np.where(u > t_out, 1, 0))
                grade[n] = out_grade[n]
            else:
                grade[n] = 0
        vp = vegp[top:bottom]
        vp[t] = colours[grade[t]]
        grown = n & (grade > 0)
        vp[grown] = colours[grade[grown]]
        lk = lkey[top:bottom]
        lp = land[top:bottom]
        # Inside the wood every tree stands on the wood's dark floor - a
        # thin patch of it is still the wood, not a clearing. Out in its spill
        # only the thick trees do, so the spill fades into the meadow.
        dark = np.where(n, grade >= 2, grade >= 1)
        grassy = (lk == dark_k) | (lk == med_k) | (lk == light_k)
        lp[(t | grown) & grassy & dark] = C.DARK_GRASS
        # A clearing in the wood is a meadow, not the wood's dark floor; a
        # field it was painted over stays the field.
        lp[t & ~dark & (lk == dark_k)] = C.MEDIUM_GRASS
        counts += np.bincount(grade[t], minlength=4)
        fringe += int(grown.sum())
    veg.paste(Image.fromarray(vegp, "RGB"))
    landscape.paste(Image.fromarray(land, "RGB"))
    out = dict(zip(NAMES, counts.tolist()))
    out["fringe"] = fringe
    return out
