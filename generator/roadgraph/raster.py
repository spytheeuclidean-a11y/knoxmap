"""Snapped roads to tiles.

Every vertex is a tile corner and every edge a multiple of 45 degrees. Each
road is drawn from one outline, its edges the centreline offset to each side:
- along the grid by half the road's width (an odd width is drawn half a tile
  over, on a line of tile centres, so its edges are tile edges too);
- on the diagonal by half an even horizontal span (span_of), so the edge runs
  through tile corners;
- on a 2:1 slope by as near half the width as keeps the edge on a line
  through tile corners (lattice_k), where vanilla's 2:1 kerbs meet;
- at a bend the two offsets meet where they cross - a straight edge meets a
  diagonal one at a tile corner, so the outline is the same road width all
  the way round the bend, with no spike or notch;
- at the path's ends it runs on by half its width, into the junction (a dead
  end ends square).
A tile is road if the outline covers three or all of its four quarter
triangles (the quarters between its diagonals), half road if two beside one
another (kept in a mask of their own with the corner of the tile the road
half is in: NE/NW/SE/SW). A full tile wins over a half one; two halves of a
tile make it full.
"""
from __future__ import annotations

import math

import numpy as np
import shapely
import shapely.affinity


# Quarter-triangle centroids of a tile (y down) and the halves two of them make.
QUARTERS = {"N": (0.5, 1 / 6), "E": (5 / 6, 0.5), "S": (0.5, 5 / 6), "W": (1 / 6, 0.5)}
HALVES = {"NE": ("N", "E"), "NW": ("N", "W"), "SE": ("S", "E"), "SW": ("S", "W")}


def span_of(width: int) -> int:
    """A diagonal road's horizontal span in tiles, even: the proposal's table
    (2 -> 4, 4 -> 6, 6 -> 8, 8 -> 12, 14 -> 20)."""
    return max(int(round(width * math.sqrt(2) / 2)) * 2, width + 2)


def _span(a: int, b: int, n: int) -> slice:
    """a..b clipped to 0..n (a road off the map's edge has negative corners:
    an unclipped negative stop counts from the far end)."""
    return slice(min(n, max(0, a)), min(n, max(0, b)))


def _unit(a, b) -> tuple:
    """The step of a run from corner a to corner b (its direction in lowest terms)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    g = math.gcd(dx, dy) or 1
    return dx // g, dy // g


def _heading(a, b) -> int:
    from .snap import STEP
    return STEP.index(_unit(a, b))


def vertices(path):
    """The corners where a path turns (and its ends)."""
    path = [p for k, p in enumerate(path) if k == 0 or p != path[k - 1]]   # a corner given twice once
    if len(path) < 2:
        return list(path) * 2
    out = [path[0]]
    for a, b, c in zip(path, path[1:], path[2:]):
        if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
            out.append(b)
    out.append(path[-1])
    return out


def lattice_k(width: int) -> float:
    """The offset factor of a 2:1 run's edges (offset (-dy, dx) * k, d its
    step in lowest terms): each edge on a line through tile corners - two
    tiles along to one across, through the middle of a tile edge between -
    as vanilla's 2:1 kerbs (street_curbs_01_diag_2, in pairs corner to
    corner) are drawn. The offset moves the line's x - 2y (or 2x - y) by 5k,
    which must be whole (half and a half for an odd width, drawn half a tile
    over): the nearest to half the width."""
    frac = 0.5 if width % 2 else 0.0
    return (round(width / 2 * math.sqrt(5) - frac) + frac) / 5


def _cross(p, d, q, e):
    """Where the line p + t d meets q + s e."""
    det = d[0] * -e[1] - d[1] * -e[0]
    if abs(det) < 1e-9:                      # parallel (a run split in two): join where the next begins
        return q
    t = ((q[0] - p[0]) * -e[1] - (q[1] - p[1]) * -e[0]) / det
    return (p[0] + t * d[0], p[1] + t * d[1])


def _beyond(n: float, d) -> float:
    """The offset factor for at least n tiles more beyond an edge in
    direction d (step in lowest terms), so the edge stays on its lattice: the
    offset moves the edge's line value by k |d|^2, which must stay whole.
    Rounded up: a 1-tile pavement by a 2:1 road rounded to 0.89 tiles lay
    wholly in the part-road squares at the kerb, and was lost."""
    n2 = d[0] ** 2 + d[1] ** 2
    return math.ceil(n * math.sqrt(n2) - 1e-9) / n2


def outline(path, width: int, extra=(0, 0)):
    """The road's outline (a shapely polygon) round a snapped path; with
    `extra`, that many tiles more on each side (its left - the side of (-dy,
    dx) - and right), each edge still on its lattice."""
    vs = vertices(path)
    half_w, half_s = width / 2, span_of(width) / 2
    segs = []
    for a, b in zip(vs, vs[1:]):
        if a == b:
            continue
        d = _unit(a, b)
        diag = abs(d[0]) == abs(d[1])
        # Offset to the left: along the grid half the width; on the diagonal
        # half the span measured across x (the normal (-dy, dx) is sqrt 2 long);
        # on a 2:1 slope as near half the width as keeps the edge on the 2:1
        # lattice through tile corners (lattice_k).
        k = half_s / 2 if diag else lattice_k(width) if abs(d[0]) + abs(d[1]) == 3 else half_w / math.hypot(*d)
        segs.append((a, b, d, [(-d[1] * ks, d[0] * ks) for ks in (k + _beyond(extra[0], d), k + _beyond(extra[1], d))]))
    if not segs:
        return shapely.Polygon()
    left, right = [], []
    for side, out in ((1, left), (-1, right)):
        # Set on the first segment of the run and read from the second on; the
        # `else` below is the only reader, and it is never reached for n == 0.
        out_prev = None
        for n, (a, b, d, offs) in enumerate(segs):
            off = offs[0 if side == 1 else 1]
            pa = (a[0] + side * off[0], a[1] + side * off[1])
            if n == 0:
                run_on = half_w / math.hypot(*d)
                out.append((pa[0] - d[0] * run_on, pa[1] - d[1] * run_on))
            else:
                pa2, d2 = out_prev
                out.append(_cross(pa2, d2, pa, d))
            out_prev = (pa, d)
        a, b, d, offs = segs[-1]
        off = offs[0 if side == 1 else 1]
        pb = (b[0] + side * off[0], b[1] + side * off[1])
        run_on = half_w / math.hypot(*d)
        out.append((pb[0] + d[0] * run_on, pb[1] + d[1] * run_on))
    # One quadrilateral a run, joined: a sharp inner corner can fold back on
    # itself, which a single ring would not survive.
    quads = [shapely.make_valid(shapely.Polygon([left[n], left[n + 1], right[n + 1], right[n]]))
             for n in range(len(segs))]
    shape = shapely.union_all(quads)
    # An odd width centred on corners would have its edges mid-tile: half a tile over.
    return shapely.affinity.translate(shape, 0.5, 0.5) if width % 2 else shape


# Vanilla's junctions (the lot files at its right-angled Ts in Muldraugh,
# Rosewood and Riverside): the two roads crossing, each inner
# corner square or cut at 45 degrees by a tile or two (a 1-tile cut 74 times,
# square 67, 2 tiles 32, 4 tiles 12).
JUNCTION_CUT = 2             # tiles along each road's edge the cut takes
CUT_ANGLES = (60.0, 120.0)   # degrees between two neighbouring roads for their corner to be cut


def junction_cuts(paths: dict, links: list) -> list:
    """[(link index, triangle)]: at each junction, the corner between two
    neighbouring roads meeting near square, cut JUNCTION_CUT tiles along
    each road's edge."""
    arms: dict = {}                                  # corner -> [(link, unit direction, half width)]
    for i, path in paths.items():
        vs = vertices(path)
        if len(vs) < 2 or vs[0] == vs[-1]:
            continue
        for end, nxt in ((vs[0], vs[1]), (vs[-1], vs[-2])):
            d = np.subtract(nxt, end, dtype=float)
            arms.setdefault(tuple(end), []).append((i, d / np.hypot(*d), links[i].width / 2))
    out = []
    for j, arm in arms.items():
        if len(arm) < 2:
            continue
        arm.sort(key=lambda a: math.atan2(a[1][1], a[1][0]))
        for (ia, da, ha), (ib, db, hb) in zip(arm, arm[1:] + arm[:1]):
            turn = math.degrees(math.atan2(da[0] * db[1] - da[1] * db[0], da @ db)) % 360
            if not CUT_ANGLES[0] <= turn <= CUT_ANGLES[1]:
                continue
            # Arm a's edge on b's side, arm b's edge on a's side; the corner where they cross.
            na, nb = np.array([-da[1], da[0]]), np.array([db[1], -db[0]])
            pa, pb = np.array(j, float) + na * ha, np.array(j, float) + nb * hb
            det = da[0] * -db[1] - da[1] * -db[0]
            if abs(det) < 1e-9:
                continue
            t = ((pb[0] - pa[0]) * -db[1] - (pb[1] - pa[1]) * -db[0]) / det
            corner = pa + t * da
            tri = shapely.Polygon([corner, corner + da * JUNCTION_CUT, corner + db * JUNCTION_CUT])
            if tri.area > 0:
                out.append((ia, tri))
    return out


def rasterise(paths: dict, links: list, H: int, W: int):
    """(owner: link index + 1 of each full tile, -1 a tile two halves make,
    0 none; half: {(x, y): set of the road corners of a half tile}). Each
    road's outline, then its junctions' corner cuts."""
    owner = np.zeros((H, W), np.int32)
    half: dict = {}
    shapes = [(i, outline(path, links[i].width)) for i, path in paths.items()] + junction_cuts(paths, links)
    for i, shape in shapes:
        if shape.is_empty:
            continue
        bx0, by0, bx1, by1 = shape.bounds
        x0, y0 = max(0, int(math.floor(bx0))), max(0, int(math.floor(by0)))
        x1, y1 = min(W, int(math.ceil(bx1))), min(H, int(math.ceil(by1)))
        if x1 <= x0 or y1 <= y0:
            continue
        ty, tx = np.mgrid[y0:y1, x0:x1]
        q = {k: shapely.contains_xy(shape, tx + ox, ty + oy) for k, (ox, oy) in QUARTERS.items()}
        count = sum(q.values())
        sub = owner[y0:y1, x0:x1]
        sub[(count >= 3) & (sub == 0)] = i + 1
        for name, (a, b) in HALVES.items():
            for yy, xx in zip(*np.nonzero((count == 2) & q[a] & q[b])):
                half.setdefault((x0 + xx, y0 + yy), set()).add(name)
    # Two halves of one tile (opposite corners) make it road.
    for (x, y), cs in list(half.items()):
        if owner[y, x] or {"NE", "SW"} <= cs or {"NW", "SE"} <= cs:
            if not owner[y, x]:
                owner[y, x] = -1
            del half[(x, y)]
    return owner, half
