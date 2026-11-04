"""The road graph snapped to sixteen directions on the tile-corner lattice,
vanilla B42's: along the grid, 2:1, 45 degrees and 1:2 - Muldraugh's curves
are runs on these, turning a notch at a time.

1. Junctions to the nearest tile corner; two junctions joined by a link
   shorter than the half-widths of their side roads plus JUNCTION_GAP are
   one (the side roads could not be drawn apart).
2. Every arm of a junction a heading of the sixteen, at least 90 degrees from
   its neighbours (45 where a junction has more arms than that allows), the
   least total deviation from the arms' true bearings (brute force).
2b. A main road (minor or above) routed whole: its links chained through
   the junctions where it goes straight on (a stroke), routed in one go
   against its line with small wiggles smoothed away (SMOOTH_TILES), turns
   dearer (BETA_MAIN) and room to stray in town (STROKE_BAND); its side
   roads' junctions slide onto it (STROKE_MOVE at most). Elsewhere a through
   road's two arms at a junction are kept opposite (THROUGH_WEIGHT).
2c. Streets straight in OSM squared: each a few degrees off one of the
   eight directions gets it, and the junctions all move together, as little
   as they can (least squares; the main roads' and pins' held; STRAIGHT_MOVE
   at most, STRAIGHT_MOVE_END for a dead end), until every such street runs
   exactly on its direction - then it is one straight run, not a jog.
3. A link leaving and arriving on one heading whose corners are a little
   apart sideways (less than its minimum run) has its lesser junction moved
   onto the line, by ALIGN_MAX at most: otherwise it needs a jog.
4. Each link routed between its two corners by A*: state (corner, heading,
   run since the last turn, in tiles); a move is a step along the heading,
   or, once the run reaches the minimum (min_run, twice it out of town,
   half for the first and last runs), one of vanilla's turns taken whole
   (SHARP corners of one, two or four notches; CURVES: a right angle as
   three pieces 2:1-45-1:2 at the road width's radius, or a corner cut by
   one 45 piece; a 45 as one 2:1 piece - twice the size out of town). Step cost length x (1 + ALPHA
   d^2), d the corner's distance in tiles from the real centreline (its ends
   moved to the snapped corners), plus BETA a turn and REVERSE more for an
   S-bend (a turn back within twice the minimum run). Out of town (the town
   mask, corner by corner) a road may stray far further for far less
   (BAND_OPEN, ALPHA_OPEN): a gentle angle there is a long straight, not a
   staircase. Hard limits: within the band, leaving and arriving on the
   arms' headings, and not through a road already routed. A dead end has no
   heading and may stop within DEAD_END_REACH of its real end; a pin (a road
   leaving the map) is fixed in place and heading. Routed by
   class, highest first; a link with no path tries a wider band, then a
   shorter minimum run, and is logged.

Headings 0-15 step (1,0), (2,1), (1,1), (1,2), (0,1), ... anticlockwise on
screen being clockwise in tiles (x right, y down); 8 notches is the opposite
way. A 2:1 step goes two tiles along and one across.
"""
from __future__ import annotations

import bisect
import heapq
import itertools
import math
import time

import numpy as np
import shapely

from .network import RANK

STEP = [(1, 0), (2, 1), (1, 1), (1, 2), (0, 1), (-1, 2), (-1, 1), (-2, 1),
        (-1, 0), (-2, -1), (-1, -1), (-1, -2), (0, -1), (1, -2), (1, -1), (2, -1)]
N = len(STEP)
ANGLE = [math.degrees(math.atan2(dy, dx)) % 360 for dx, dy in STEP]
SPAN = [max(abs(dx), abs(dy)) for dx, dy in STEP]        # tiles a step goes along the grid
LENGTH = [math.hypot(dx, dy) for dx, dy in STEP]
SLOPE = ["grid" if dx == 0 or dy == 0 else "45" if abs(dx) == abs(dy) else "2:1" for dx, dy in STEP]
# The road's turns, as vanilla's streets.xml draws them: sharp corners of one notch, two (45 degrees) or four (a
# right angle); a right angle curved as three pieces - 2:1, 45, 1:2, near
# equal, each RIGHT_PIECE of the radius - or cut by one 45 piece on a tight
# corner; a 45 curved as one 2:1 piece. Costs are shares of a turn's (beta).
SHARP = {1: 0.5, 2: 0.7, 4: 1.0}
CURVE_COST = {"right": 0.9, "cut": 1.1, "half": 0.8}
RIGHT_PIECE = math.pi / 6    # each of a curved right angle's three pieces: radius x this
CUT_RADIUS = 5.0             # a corner cut by one 45 piece: radius (its piece is radius x pi/2 long)


def curve_radius(width: int) -> float:
    """A curved right angle's radius on a road this wide (vanilla's medians:
    about 12 up to 6 wide, 20 from 8)."""
    return 12.0 if width <= 6 else 20.0 if width >= 8 else 16.0


def _piece_steps(h: int, length: float) -> int:
    """Steps on heading h making a piece about `length` tiles long."""
    return max(1, int(round(length / LENGTH[h])))


_CURVES: dict = {}          # (heading, width, scale) -> what curves() gives back


def curves(hd: int, width: int, scale: float = 1.0) -> list:
    """The curved turns leaving heading hd (a grid or 45 heading): [(kind,
    turn in notches, [(heading, steps), ...])] - the pieces, then the road
    goes on at hd + turn. The same for a heading, a width and a scale, so it
    is worked out once: the search used to do it again at every corner."""
    key = (hd, width, scale)
    out = _CURVES.get(key)
    if out is None:
        out = _CURVES[key] = _built_curves(hd, width, scale)
    return out


def _built_curves(hd: int, width: int, scale: float = 1.0) -> list:
    out = []
    if hd % 2:
        return out                                   # from a 2:1 run, only sharp turns
    r = curve_radius(width) * scale
    for sign in (1, -1):
        out.append(("right", 4 * sign, [((hd + k * sign) % N, _piece_steps((hd + k * sign) % N, r * RIGHT_PIECE))
                                         for k in (1, 2, 3)]))
        cut = (hd + 2 * sign) % N
        out.append(("cut", 4 * sign, [(cut, _piece_steps(cut, CUT_RADIUS * scale * math.pi / 2))]))
        half = (hd + sign) % N
        out.append(("half", 2 * sign, [(half, _piece_steps(half, r * math.pi / 4))]))
    return out


# The turns the search may take from a heading, once per heading and beta:
# [(steps [(heading, count)], new heading, run after, last turn, turn cost)].
_MOVES: dict = {}


def _sharp_moves(hd: int, beta: float) -> tuple:
    """Vanilla's sharp turns leaving heading hd, at this beta."""
    key = ("sharp", hd, beta)
    out = _MOVES.get(key)
    if out is None:
        out = []
        for k, share in SHARP.items():
            for sign in (1, -1):
                turn = k * sign
                nh = (hd + turn) % N
                out.append(([(nh, 1)], nh, SPAN[nh], sign, beta * share))
        out = _MOVES[key] = tuple(out)
    return out


def _curved_moves(hd: int, width: int, scale: float, beta: float) -> tuple:
    """The curved turns leaving heading hd (a 2:1 run takes none of them)."""
    key = ("curve", hd, width, scale, beta)
    out = _MOVES.get(key)
    if out is None:
        out = _MOVES[key] = tuple(
            (pieces, (hd + turn) % N, 0, 1 if turn > 0 else -1, beta * CURVE_COST[kind])
            for kind, turn, pieces in curves(hd, width, scale))
    return out


# Cost a tile on each slope, beside along the grid: vanilla runs 65-72% of its
# kerb along the grid, 10-12% at 2:1 and 4% at 45 (measured from streets.xml),
# 2:1 mostly round curves - so a long 2:1 road pays its way. 45 is let be
# (Knox County's own roads use it).
SLOPE_COST = {"grid": 1.0, "2:1": 1.15, "45": 1.0}
TURN_SHARE = min(min(c / k for k, c in SHARP.items()), CURVE_COST["right"] / 4, CURVE_COST["half"] / 2)
                             # the least a notch of turn can cost (for the search's estimate)
ALPHA, BETA = 0.05, 10.0
REVERSE = 10.0               # more for a turn back the other way soon after one (an S-bend)
BAND, BAND_OPEN = 6, 40      # tiles a road may stray from its line, in town and out of it
ALPHA_OPEN = 0.005           # out of town straying costs little: nobody sees it
FREE_OPEN = 20.0             # ...and nothing within this many tiles of the line: a gentle
                             # angle is then a few long straights, not a staircase
FREE_MAIN = 0.0              # tiles a main road may stray in town for nothing (4 made more bends)
TIE = 0.001                  # within the free distance, a whisper of cost toward the line: the
                             # fewest bends first, then the closest of the routes with that many
MIN_RUN_TILES = 4
JUNCTION_GAP = 2             # tiles of verge at least between two side roads
ARM_LOOK = 8.0               # tiles along a link its arm's bearing is read over
THROUGH_LOOK = 25.0          # ...and a through road's, over a longer stretch (past its wiggles)
THROUGH_DEFLECT = 30.0       # degrees: two arms this near straight on are one road
THROUGH_WEIGHT = 6.0         # cost of a through road turning by 45 degrees at a junction
# Main roads are routed against their line with wiggles under this many tiles
# smoothed away, and pay more for a turn: a long straight, not every wobble.
SMOOTH_TILES = {"motorway": 6.0, "primary": 6.0, "secondary": 5.0, "minor": 5.0, "local": 2.0}
BETA_MAIN = 20.0
MAIN = ("motorway", "primary", "secondary", "minor")
STROKE_BAND, STROKE_ALPHA = 15, 0.01   # a main road routed whole may stray this far in town, for this
STROKE_MOVE = 20             # tiles a junction may slide to sit on its main road
STRAIGHT_TOL = 2.0           # tiles (or 2% of its length if more): a street no further than this
                             # from its chord is straight
STRAIGHT_MIN = 15.0          # ...and at least this long
STRAIGHT_MAX_DEG = 15.0      # ...and this near one of the sixteen directions, to be squared to it
STRAIGHT_MOVE = 15.0         # tiles a junction may move to square its streets
STRAIGHT_MOVE_END = 30.0     # ...a dead end (nothing else hangs on it)
CLEAR_PAD = 4                # tiles beyond a routed road's edge another road pays to come within
CLEAR_COST = 3.0             # ...a tile (a cost, not a wall: a tight spot can still be routed)
TEMPLATE_MIN_END = 40.0      # tiles: a dead end shorter than this is routed, not fitted to a vanilla shape
                             # (it would hook to land exactly on its end; routed it may stop short)
MAX_STATES = 500_000         # a search this big gives up (and the link tries again looser)
EXACT_STATES = 250_000        # ...but first: an exact search this big, then one leaning on its
LEAN_MID, MID_STATES = 1.5, 250_000   # estimate a little harder, then
GREEDY = 2.0                 # estimate this much harder (cost at most this times the best;
                             # a long road out of town with room to stray is too big to search exactly)
# Why the exact search is not given millions: a search that will not fit runs to
# its limit and is thrown away, and its link then searches again looser. On a
# town whose main roads are long and crooked those searches fill the window
# (a diagonal main road's is the whole map) and take a minute each, so a town of
# 1,655 links sat at 0 routed for the best part of an hour. A road that cannot be
# searched exactly in a quarter of a million states is one whose exact route
# nobody can see either; leaning on the estimate at 1.5 finds nearly the same
# road in a few thousand, and the looser tries behind it bound the worst case.
LADDER = ((1.0, EXACT_STATES), (LEAN_MID, MID_STATES), (GREEDY, MAX_STATES))
                             # a full link's tries in order - exact, leaning a little, leaning
                             # hard - and the first that finds a path wins
RETRY_STATES = 200_000       # the looser tries after the first (wider band, shorter runs, headings
                             # let go) give up at this: a failing search runs to its limit, and at
                             # 1.5 million a try a town's 9 unroutable links took 40+ minutes; a
                             # road needing more than this in a widened band would not look right
                             # anyway
SLOW_LINK_S = 5.0            # a link taking longer than this to route is logged, with its states
ALIGN_MAX = 6                # tiles a junction may move to line up a straight road
DEAD_END_REACH = 3           # tiles from its real end a dead end may stop
END_SHORT = 2.0              # cost a tile a dead end stops short
BACK_LIMIT = 101.25          # degrees a step may turn from the way the real line runs
DONE = -1                    # heading of the search's finished state


# Roads by frontage density (mode "cost", modes.py): COST, a 0-1 field of building
# outline near each square (None: off). A step costs, on top, its length x COST_SCALE x
# the density there x DIR_PENALTY of its slope - nothing along the grid, a little at 45,
# much at 2:1 - so a built-up street keeps to the grid, as the buildings along it are.
COST: np.ndarray | None = None
DIR_PENALTY = {"grid": 0.0, "45": 0.5, "2:1": 1.5}
COST_SCALE = 1.0
ARM_COST = 1.0               # a junction's arm off the grid where it is dense: density x
                             # DIR_PENALTY x this, beside its deviation (squared, in 45s)
# ...and where the density is JOG_DENSITY or more (JOG: {"dist": each square's distance to
# a building, "plots": each square's land parcel number, or None}; None: off) a road turns
# only at a junction (within JOG_END tiles, or its width, of its ends), a gap in the
# frontage (no building within JOG_GAP tiles of the road's edge, both sides) or a parcel
# boundary (the squares JOG_SIDE tiles out from the road's edge a tile and a half before
# and after the turn in two parcels, either side), and runs JOG_RUN x the minimum between
# turns there.
JOG: dict | None = None
JOG_DENSITY = 0.5
JOG_GAP = 4.0
JOG_SIDE = 3.0
JOG_END = 6
JOG_RUN = 2
JOG_LET_GO_BAND = 1.5        # a link routed with the jog rule let go (its last try): its band x this
# Occupancy (mode "cost"): OCC, the buildings' footprints (None: off). A
# step costs, on top, OCC_WEIGHT x the building squares under the carriageway there (a disc
# the road's width across, per tile of road): a road drawn over buildings pays for each.
OCC: np.ndarray | None = None
OCC_WEIGHT = 0.0
_OCC_FIELDS: dict = {}       # (id(src), width) -> (src, its field) (worked out once a width)


def occ_field(width: int, src: np.ndarray | None = None) -> np.ndarray:
    """Building squares (OCC, or `src`) within width/2 of each corner, per tile of road
    (over the width)."""
    src = OCC if src is None else src
    key = (id(src), int(width))
    # the array kept with its field: an id is reused once its array is gone, and a new
    # array with an old one's id was handed the old field (a test's, 2026-10-25)
    if key not in _OCC_FIELDS or _OCC_FIELDS[key][0] is not src:
        r = max(0.5, width / 2)
        k = int(math.ceil(r))
        yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
        disc = (xx ** 2 + yy ** 2 <= r * r).astype(float)
        if len(_OCC_FIELDS) > 32:
            _OCC_FIELDS.clear()
        _OCC_FIELDS[key] = (src, np.clip(convolve(src.astype(float), disc), 0, None) / max(1.0, width))
    return _OCC_FIELDS[key][1]


def convolve(a: np.ndarray, k: np.ndarray) -> np.ndarray:
    """a convolved with an odd-sized kernel k, the same size as a (zeros beyond its
    edge), by FFT."""
    kh, kw = k.shape
    H, W = a.shape
    shape = (H + kh - 1, W + kw - 1)
    out = np.fft.irfft2(np.fft.rfft2(a, shape) * np.fft.rfft2(k, shape), shape)
    return out[kh // 2:kh // 2 + H, kw // 2:kw // 2 + W]


def _at(field: np.ndarray, x, y):
    H, W = field.shape
    return field[min(max(int(y), 0), H - 1), min(max(int(x), 0), W - 1)]


def _density(x, y) -> float:
    """The frontage density at a corner (0 with no COST field)."""
    return 0.0 if COST is None else float(_at(COST, x, y))


def _prefers_grid(pts) -> bool:
    """A line to square to the grid's directions: dense (mode "cost")."""
    return COST is not None and bool(pts) and \
        sum(_density(x, y) for x, y in pts) / len(pts) >= JOG_DENSITY


def turn_ok(x, y, hd: int, width: float, s, g, stops=()) -> bool:
    """May a road `width` wide turn at corner (x, y), heading hd before the turn,
    on its way from s to g (and past the junctions `stops`: a main road routed whole)?
    (JOG: always where it is not dense.)"""
    if JOG is None or COST is None or _density(x, y) < JOG_DENSITY:
        return True
    if min(math.dist((x, y), q) for q in (s, g, *stops)) <= max(JOG_END, width):
        return True                                  # at a junction (or a dead end)
    if float(_at(JOG["dist"], x, y)) > width / 2 + JOG_GAP:
        return True                                  # a gap in the frontage
    lab = JOG.get("plots")
    if lab is not None:
        dx, dy = STEP[hd]
        n = math.hypot(dx, dy)
        tx, ty = dx / n, dy / n
        off = width / 2 + JOG_SIDE
        for sgn in (1, -1):
            px, py = x - ty * sgn * off, y + tx * sgn * off
            a, b = int(_at(lab, px - 1.5 * tx, py - 1.5 * ty)), int(_at(lab, px + 1.5 * tx, py + 1.5 * ty))
            if a and b and a != b:
                return True                          # a plot boundary meets the road here
    return False


JOG_LET_GO: list = []        # links the last snap() routed only with the jog rule let go


def _route_no_jog(*args, **kw):
    """_route with the jog rule off for this one search."""
    global JOG
    jog, JOG = JOG, None
    try:
        return _route(*args, **kw)
    finally:
        JOG = jog


def jog_breaks(path, width: float) -> bool:
    """A fitted vanilla shape the cost mode refuses: a step off the grid where it is
    dense (stricter than the search, which only charges for one there), or a turn
    where turn_ok says no."""
    if COST is None or len(path) < 3:
        return False
    hs = [_step_heading(a, b) for a, b in zip(path, path[1:])]
    for k, (a, b) in enumerate(zip(path, path[1:])):
        if SLOPE[hs[k]] != "grid" and max(_density(*a), _density(*b)) >= JOG_DENSITY:
            return True
        if k and hs[k] != hs[k - 1] and not turn_ok(a[0], a[1], hs[k - 1], width, path[0], path[-1]):
            return True
    return False


GRID_HEADINGS = (0, 4, 8, 12)


def _nearest_grid(bearing: float, k: int = 2) -> list:
    return sorted(GRID_HEADINGS, key=lambda h: _adiff(ANGLE[h], bearing))[:k]


def min_run(width: int) -> int:
    """Shortest run between two bends: a road's width (so a bend's two bands
    meet cleanly). Out of town _search asks twice this, read where the bend
    would be: a gentle curve there is a few long straights, not a saw."""
    return max(MIN_RUN_TILES, width)


def _bearing(dx: float, dy: float) -> float:
    """Bearing in degrees, 0-360, as ANGLE measures a heading."""
    return math.degrees(math.atan2(dy, dx)) % 360


def _adiff(a: float, b: float) -> float:
    """Degrees between two bearings."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _notches(a: int, b: int) -> int:
    return min((a - b) % N, (b - a) % N)


def _swing_table() -> tuple:
    """The headings within 90 degrees of a bearing, as a table by bearing.

    Which headings a road may still head on changes only where one of them
    comes into or leaves the half-circle, at each heading's own bearing plus
    and minus 90 degrees; between those the answer is the same, so h reads it
    from a table rather than working through all sixteen for every corner.
    """
    bounds = sorted({round((a + d) % 360.0, 9) for a in ANGLE for d in (90.0, -90.0)})
    table = []
    for k, lo in enumerate(bounds):
        hi = bounds[k + 1] if k + 1 < len(bounds) else bounds[0] + 360.0
        a = (lo + hi) / 2.0 % 360.0
        open_ = [b for b in range(N) if _adiff(ANGLE[b], a) < 90]
        table.append(tuple(min(_notches(hd, b) for b in open_) if open_ else 0
                           for hd in range(N)))
    return tuple(bounds), tuple(table)


SWING_BOUNDS, SWING_TABLE = _swing_table()
SWING_SET = frozenset(SWING_BOUNDS)   # a bearing exactly on one: see h, its strictness




def _nearest(bearing: float, k: int = 1) -> list:
    """The k headings nearest a bearing."""
    return sorted(range(N), key=lambda h: _adiff(ANGLE[h], bearing))[:k]


def _opposite(h: int) -> int:
    return (h + N // 2) % N


def _step_heading(a, b) -> int:
    """The heading of a step from corner a to corner b."""
    return STEP.index((b[0] - a[0], b[1] - a[1]))


def _point_along(pts, dist):
    line = shapely.LineString(pts)
    p = line.interpolate(min(dist, line.length))
    return p.x, p.y


def snap(nodes: dict, links: list, town: np.ndarray | None = None, log=print, pins=None, tick=None):
    """Routed paths {link index: [corners]}, the snapped nodes {id: (x, y)},
    the node merge map {id: id} and what failed. Pins (where roads leave the
    map; {node: the way into the map}) are never merged, moved or let
    wander, and leave on a heading into the map (one along the edge would be
    half off it). tick(done, total), if given, is called before each link is
    routed (a progress readout; it may raise to stop)."""
    pins = pins or {}
    tick = tick or (lambda done, total: None)
    JOG_LET_GO.clear()
    # --- 1. junctions to corners, close ones merged -------------------------------------------
    arm_widths: dict = {}                   # node -> [(link index, width)]
    for i, l in enumerate(links):
        for n in (l.u, l.v):
            arm_widths.setdefault(n, []).append((i, l.width))
    parent = {n: n for n in nodes}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    def side(n, i):                         # the widest other road at a junction
        return max((w for j, w in arm_widths[n] if j != i), default=0)
    # Shortest first, and a merged junction no wider than the distance that
    # merges two: merged one pair at a time, a High Street's side roads
    # chain into one junction a hundred tiles across.
    group_of = {n: [n] for n in nodes}
    for i, l in sorted(enumerate(links), key=lambda il: shapely.LineString(il[1].pts).length):
        limit = (side(l.u, i) + side(l.v, i)) / 2 + JUNCTION_GAP
        ru, rv = find(l.u), find(l.v)
        if ru == rv or l.u in pins or l.v in pins or len(arm_widths[l.u]) < 3 or len(arm_widths[l.v]) < 3 or \
                shapely.LineString(l.pts).length >= limit:
            continue
        group = group_of[ru] + group_of[rv]
        if max(math.dist(nodes[a], nodes[b]) for a in group for b in group) >= limit:
            continue
        parent[ru] = rv
        group_of[rv] = group
    groups: dict = {}
    for n in nodes:
        groups.setdefault(find(n), []).append(n)
    corner = {}
    for root, members in groups.items():
        x = sum(nodes[m][0] for m in members) / len(members)
        y = sum(nodes[m][1] for m in members) / len(members)
        for m in members:
            corner[m] = (int(round(x)), int(round(y)))
    merged = {n: find(n) for n in nodes}
    live = [i for i, l in enumerate(links) if merged[l.u] != merged[l.v]]

    # --- 2. a heading for every arm -------------------------------------------------------------
    arms: dict = {}                         # root node -> [(link index, end 'u'|'v', true heading)]
    far_bearing: dict = {}                  # (link index, end) -> bearing over THROUGH_LOOK
    for i in live:
        l = links[i]
        for end, nid, pts in (("u", l.u, l.pts), ("v", l.v, l.pts[::-1])):
            cx, cy = corner[nid]
            px, py = _point_along(pts, ARM_LOOK)
            if math.hypot(px - cx, py - cy) < 1e-6:
                px, py = pts[-1]
            arms.setdefault(merged[nid], []).append((i, end, _bearing(px - cx, py - cy)))
            qx, qy = _point_along(pts, THROUGH_LOOK)
            far_bearing[(i, end)] = _bearing(qx - cx, qy - cy) if math.hypot(qx - cx, qy - cy) > 1e-6 \
                else arms[merged[nid]][-1][2]
    # Through roads: two arms of one road going straight on (one name, or one
    # class with no name), nearest straight first. They should leave on
    # opposite headings - a main road does not kink at every side road.
    through: dict = {}                      # root -> [(arm index, arm index)]
    for root, arm in arms.items():
        pairs, used, cands = [], set(), []
        for a, b in itertools.combinations(range(len(arm)), 2):
            la, lb = links[arm[a][0]], links[arm[b][0]]
            na, nb = la.tags.get("name"), lb.tags.get("name")
            if not ((na and na == nb) or (not na and not nb and la.cls == lb.cls)):
                continue
            ta, tb = far_bearing[arm[a][:2]], far_bearing[arm[b][:2]]
            bend = 180 - _adiff(ta, tb)
            if bend <= THROUGH_DEFLECT:
                cands.append((bend, a, b))
        for _bend, a, b in sorted(cands):
            if a not in used and b not in used:
                pairs.append((a, b))
                used |= {a, b}
        through[root] = pairs

    # --- 2b. main roads routed whole ----------------------------------------------------------
    # A main road's links chained through its through junctions (a stroke) and
    # routed in one go, junction to junction only where a junction is already
    # fixed (a pin, a stroke routed before); its other junctions slide onto the
    # route (STROKE_MOVE at most). Routed one link at a time, a road at an
    # angle between two of the eight zigzags from side road to side road.
    heading: dict = {}                      # (link index, end) -> heading leaving that end
    taken: dict = {}                        # corner -> link index whose centreline runs there
    paths: dict = {}
    fixed: set = {merged[n] for n in pins}
    near = np.zeros(town.shape, bool) if town is not None else None   # ground near a routed road
    stroke_report = _strokes(links, live, arms, through, merged, groups, corner, pins, fixed,
                             heading, taken, paths, town, log, near, tick)

    # --- 2c. straight streets squared ----------------------------------------------------------
    # A street straight in OSM but a few degrees off one of the eight
    # directions, held near its real line, would jog. Instead its junctions
    # all move together, as little as they can (least squares, the main
    # roads' and the pins' held), until every such street runs exactly on its
    # direction; it is then routed as one straight run.
    ends = {merged[n] for n, a in arm_widths.items() if len(a) == 1}
    straight, square_report = _square_straights(links, live, merged, groups, corner, fixed, paths, heading, ends)
    through_pairs = kinked = 0
    for root, arm in arms.items():
        k = len(arm)
        pairs = through[root]
        through_pairs += len(pairs)
        sep = 89.0 if k <= 4 else 44.0      # degrees between two arms at least
        if k > 7:                           # too many to try: nearest each
            for i, end, t in arm:
                heading.setdefault((i, end), _nearest(t)[0])
            continue
        best, best_cost = None, math.inf
        # Each arm's three nearest headings (or the one it has), every mix tried.
        choices = [[heading[(i, e)]] if (i, e) in heading else _nearest(t, 3) for i, e, t in arm]
        dens = _density(*corner[groups[root][0]])
        for combo in itertools.product(*choices):
            ok = all(_adiff(ANGLE[a], ANGLE[b]) >= sep for a, b in itertools.combinations(combo, 2)) and \
                all(_inward(h, pins.get(links[i].u if e == "u" else links[i].v)) for h, (i, e, _t) in zip(combo, arm))
            if not ok:
                continue
            cost = sum((_adiff(ANGLE[h], t) / 45) ** 2 for h, (_i, _e, t) in zip(combo, arm))
            if dens:                                 # off the grid where it is dense costs (mode "cost")
                cost += ARM_COST * dens * sum(DIR_PENALTY[SLOPE[h]] for h in combo)
            cost += THROUGH_WEIGHT * sum((_adiff(ANGLE[combo[a]], ANGLE[_opposite(combo[b])]) / 45) ** 2
                                         for a, b in pairs)
            if cost < best_cost:
                best, best_cost = combo, cost
        if best is None:
            best = tuple(_nearest(t)[0] for _i, _e, t in arm)
        for h, (i, end, _t) in zip(best, arm):
            heading[(i, end)] = h
        kinked += sum(1 for a, b in pairs if best[a] != _opposite(best[b]))
    log(f"  through roads at junctions: {through_pairs}, of them kinked: {kinked}; {stroke_report}; {square_report}")

    order = sorted(live, key=lambda i: (RANK[links[i].cls], -shapely.LineString(links[i].pts).length))
    dead = {n for n, a in arm_widths.items() if len(a) == 1 and n not in pins}

    # --- 3. straight links lined up ---------------------------------------------------------------
    # A link leaving and arriving on one heading, its corners a little apart
    # sideways, cannot be drawn without a jog at least the minimum run across:
    # the lesser junction moves onto the line. Highest class first; a junction
    # lined up once stays put, and none moves more than ALIGN_MAX.
    home = dict(corner)
    pinned: set = set(fixed)
    strength = {}
    for root, members in groups.items():
        strength[root] = max((w for m in members for _j, w in arm_widths.get(m, [])), default=0)
    for i in order:
        l = links[i]
        if i in paths or i in straight or l.u in dead or l.v in dead:
            continue                        # routed whole or squared; a dead end lands where it likes (below)
        h = heading[(i, "u")]
        if _opposite(heading[(i, "v")]) != h:
            continue
        s, g = corner[l.u], corner[l.v]
        lat = _lateral(s, g, h)
        if lat == 0 or abs(lat) > min_run(l.width):
            continue
        ru, rv = merged[l.u], merged[l.v]
        movable = [r for r in sorted((rv, ru), key=lambda r: strength[r]) if r not in pinned]
        for r in movable:
            new = _shift(corner[l.u if r == ru else l.v], h, lat if r == ru else -lat)
            if max(abs(new[0] - home[r][0]), abs(new[1] - home[r][1])) <= ALIGN_MAX:
                for m in groups[r]:
                    corner[m] = new
                break
        pinned |= {ru, rv}

    # --- 4. route every link, highest class first -------------------------------------------------
    from . import templates
    failed = []
    shapes_used: dict = {}
    for i in order:
        l = links[i]
        if i in paths:
            continue
        # Counted the way the strokes pass counts - links on a route of all of
        # them - so the bar carries on instead of dropping back to nothing.
        tick(min(len(paths), len(order)), len(order))
        # Routed toward a dead end, which has no heading and stops within
        # DEAD_END_REACH of where it really does.
        a, ea, b, eb, pts = l.u, "u", l.v, "v", l.pts
        flip = a in dead and b not in dead
        if flip:
            a, ea, b, eb, pts = b, eb, a, ea, pts[::-1]
        hs = None if a in dead else heading[(i, ea)]
        ha = None if b in dead else _opposite(heading[(i, eb)])
        reach = DEAD_END_REACH if b in dead else 0
        want = min_run(l.width)
        smooth = SMOOTH_TILES.get(l.cls, 0.0)
        target = list(shapely.LineString(pts).simplify(smooth).coords) if smooth else pts
        if i in straight:
            target = [corner[a], corner[b]]   # squared: one straight run between its junctions
        path = None
        # One of vanilla's own street shapes, if one fits (templates.py).
        short_end = b in dead and shapely.LineString(l.pts).length < TEMPLATE_MIN_END
        if i not in straight and hs is not None and not short_end:
            in_town = town is None or _share_in(town, l.pts) >= 0.5
            fitted = templates.fit(pts, corner[a], corner[b], hs, ha, l.width, want,
                                   BAND if in_town else FREE_OPEN, 1.0 if in_town else 2.0, taken, i, want + 4,
                                   near=near, clear_cost=CLEAR_COST)
            if fitted is not None and jog_breaks(fitted[0], l.width):
                fitted = None
            if fitted is not None:
                path = fitted[0]
                shapes_used[fitted[1]] = shapes_used.get(fitted[1], 0) + 1
        t0, s0 = time.perf_counter(), STATES["searched"]
        for wide, run in ((1, want), (1.5, want), (2, 2), (3, 1)):
            if path is not None:
                break
            path = _route(target, corner[a], corner[b], hs, ha, wide, run, taken, i, reach, town,
                          BETA_MAIN if l.cls in MAIN else BETA, free_town=FREE_MAIN if l.cls in MAIN else 0.0,
                          near=near, limit=None if (wide, run) == (1, want) else RETRY_STATES, road_width=l.width)
            if path is not None:
                if (wide, run) != (1, want):
                    log(f"  link {i} ({l.cls}, ways {l.ways[:2]}): routed with band x{wide:g}, min run {run}")
                break
        if path is None and (hs is not None or ha is not None):
            # Last: its ends' headings let go (it may meet a junction at an
            # odd angle) rather than leave a real street off the map.
            path = _route(target, corner[a], corner[b], None, None, 3, 1, taken, i, reach, town,
                          BETA_MAIN if l.cls in MAIN else BETA, free_town=FREE_MAIN if l.cls in MAIN else 0.0,
                          near=near, limit=RETRY_STATES, road_width=l.width)
            if path is not None:
                log(f"  link {i} ({l.cls}, ways {l.ways[:2]}): routed with its headings let go")
        if path is None and JOG is not None:
            # The jog rule let go last (mode "cost"): a street turning mid-frontage
            # rather than none.
            path = _route_no_jog(target, corner[a], corner[b], hs, ha, JOG_LET_GO_BAND, want, taken, i, reach, town,
                                 BETA_MAIN if l.cls in MAIN else BETA, free_town=FREE_MAIN if l.cls in MAIN else 0.0,
                                 near=near, limit=RETRY_STATES, road_width=l.width)
            if path is not None:
                JOG_LET_GO.append(i)
                log(f"  link {i} ({l.cls}, ways {l.ways[:2]}): routed with the jog rule let go")
        took = time.perf_counter() - t0
        if took > SLOW_LINK_S:
            log(f"  link {i} ({l.cls}, ways {l.ways[:2]}): {took:.0f} s, "
                f"{STATES['searched'] - s0:,} states{'' if path is not None else ' (not routed)'}")
        if path is None:
            failed.append(i)
            log(f"  link {i} ({l.cls}, ways {l.ways[:2]}): no path")
            continue
        corner[b] = path[-1]
        paths[i] = path[::-1] if flip else path
        for p in path[1:-1]:
            taken[p] = i
        _mark(near, path, l.width)
    log(f"  vanilla street shapes fitted: {sum(shapes_used.values())} "
        f"({', '.join(f'{k or chr(39) + chr(39)} {v}' for k, v in sorted(shapes_used.items(), key=lambda kv: -kv[1])[:8])})")
    return paths, corner, merged, failed


def _mark(near, path, width: int) -> None:
    """The ground within CLEAR_PAD of a routed road's edges, into `near`."""
    if near is None or len(path) < 2:
        return
    from .raster import outline
    shape = outline(path, width + 2 * CLEAR_PAD)
    if shape.is_empty:
        return
    H, W = near.shape
    bx0, by0, bx1, by1 = shape.bounds
    x0, y0 = max(0, int(bx0)), max(0, int(by0))
    x1, y1 = min(W, int(math.ceil(bx1))), min(H, int(math.ceil(by1)))
    if x1 <= x0 or y1 <= y0:
        return
    ty, tx = np.mgrid[y0:y1, x0:x1]
    near[y0:y1, x0:x1] |= shapely.contains_xy(shape, tx + 0.5, ty + 0.5)


def _share_in(town: np.ndarray, pts) -> float:
    """The share of a line's points inside the town mask."""
    H, W = town.shape
    xs = [min(W - 1, max(0, int(x))) for x, _y in pts]
    ys = [min(H - 1, max(0, int(y))) for _x, y in pts]
    return float(town[ys, xs].mean())


def _inward(h: int, way) -> bool:
    """Heading h goes into the map from a pin (any heading for other nodes)."""
    return way is None or STEP[h][0] * way[0] + STEP[h][1] * way[1] > 0


def _strokes(links, live, arms, through, merged, groups, corner, pins, fixed, heading, taken, paths,
             town, log, near=None, tick=None) -> str:
    """Route each main road whole (see snap, 2b); fills heading, taken, paths
    and moves its junctions in corner. Returns a line for the log."""
    live_set = set(live)
    nxt: dict = {}                          # (link, end) -> (link, end) through the junction
    for root, pairs in through.items():
        arm = arms[root]
        for a, b in pairs:
            (i, ea, _), (j, eb, _) = arm[a], arm[b]
            if links[i].cls in MAIN and links[j].cls in MAIN:
                nxt[(i, ea)] = (j, eb)
                nxt[(j, eb)] = (i, ea)
    seen: set = set()
    strokes = []
    for i in live:
        if i in seen or links[i].cls not in MAIN:
            continue
        # Back to one end of the chain, then forward along it.
        cur, end_in = i, "u"
        guard = 0
        while (cur, end_in) in nxt and guard < len(links):
            cur, end_in = nxt[(cur, end_in)]
            end_in = "v" if end_in == "u" else "u"
            guard += 1
            if cur == i:
                break
        chain, link, start = [], cur, end_in          # start: the end the chain enters by
        while link not in seen and link in live_set:
            seen.add(link)
            chain.append((link, start == "u"))        # forward if it runs u -> v along the chain
            out = "v" if start == "u" else "u"
            if (link, out) not in nxt:
                break
            link, start = nxt[(link, out)]
        if len(chain) >= 2:
            strokes.append(chain)
    strokes.sort(key=lambda c: (min(RANK[links[i].cls] for i, _f in c),
                                -sum(shapely.LineString(links[i].pts).length for i, _f in c)))
    routed = moved = split = 0                    # `paths` is the readout: links on a route,
                                                  # counted in one run rather than per pass
    for chain in strokes:
        if tick:
            tick(min(len(paths), len(live)), len(live))
        nodes_on = []                                 # the chain's nodes in order
        for i, fwd in chain:
            l = links[i]
            a, b = (l.u, l.v) if fwd else (l.v, l.u)
            if not nodes_on:
                nodes_on.append(a)
            nodes_on.append(b)
        # Cut where a junction is already fixed: route fixed to fixed.
        cuts = [0] + [k for k in range(1, len(nodes_on) - 1) if merged[nodes_on[k]] in fixed] + [len(nodes_on) - 1]
        split += len(cuts) - 2
        for c0, c1 in zip(cuts, cuts[1:]):
            part = chain[c0:c1]
            pts = []
            for i, fwd in part:
                p_ = links[i].pts if fwd else links[i].pts[::-1]
                pts += p_ if not pts else p_[1:]
            l0 = links[part[0][0]]
            width = max(links[i].width for i, _f in part)
            s_node, g_node = nodes_on[c0], nodes_on[c1]
            run = min_run(width)
            smooth = SMOOTH_TILES.get(l0.cls, 0.0)
            target = list(shapely.LineString(pts).simplify(smooth).coords) if smooth else pts
            hs = _pin_heading(pins, s_node, pts) if s_node in pins else None
            hg = _pin_heading(pins, g_node, pts[::-1]) if g_node in pins else None
            path = _route(target, corner[s_node], corner[g_node], hs, None if hg is None else _opposite(hg),
                          1, run, taken, part[0][0], 0, town, BETA_MAIN, STROKE_BAND, STROKE_ALPHA, FREE_MAIN,
                          near=near, road_width=width, stops=[corner[n] for n in nodes_on[c0 + 1:c1]])
            if path is None:
                continue                              # its links are routed one by one later
            # Each inner junction onto the route: the route's corner nearest it,
            # near where it lies along the road (in proportion).
            line_r = shapely.LineString(pts)
            cum = np.concatenate([[0.0], np.cumsum([math.dist(a, b) for a, b in zip(path, path[1:])])])
            k_scale = cum[-1] / max(line_r.length, 1e-9)
            at = [0]
            ok = True
            for k in range(c0 + 1, c1):
                n = nodes_on[k]
                along = line_r.project(shapely.Point(corner[n])) * k_scale
                lo = at[-1] + 1
                window = [j for j in range(lo, len(path) - 1) if abs(cum[j] - along) <= STROKE_MOVE * 2]
                if not window:
                    ok = False
                    break
                j = min(window, key=lambda j: math.dist(path[j], corner[n]))
                if math.dist(path[j], corner[n]) > STROKE_MOVE:
                    ok = False
                    break
                at.append(j)
            if not ok:
                continue
            at.append(len(path) - 1)
            for k, j in zip(range(c0, c1 + 1), at):
                root = merged[nodes_on[k]]
                if corner[nodes_on[k]] != path[j]:
                    moved += 1
                for m in groups[root]:
                    corner[m] = path[j]
                fixed.add(root)
            for (i, fwd), j0, j1 in zip(part, at, at[1:]):
                sub = path[j0:j1 + 1]
                paths[i] = sub if fwd else sub[::-1]
                p_ = paths[i]
                heading[(i, "u")] = _step_heading(p_[0], p_[1])
                heading[(i, "v")] = _step_heading(p_[-1], p_[-2])
            for p_ in path[1:-1]:
                taken[p_] = part[0][0]
            _mark(near, path, width)
            routed += 1
        if tick:
            tick(min(len(paths), len(live)), len(live))
    return (f"main roads routed whole: {len(strokes)} strokes in {routed} pieces ({split} cuts at fixed junctions), "
            f"{moved} junctions moved onto them")


def _square_straights(links, live, merged, groups, corner, fixed, paths, heading, ends=frozenset()):
    """Junctions moved (corner) so the streets straight in OSM run exactly on
    their nearest direction; returns ({link: heading}, a line for the log).
    Held: the junctions in `fixed`. A street whose squaring would move a
    junction more than STRAIGHT_MOVE is let go, the worst first."""
    cand = []
    for i in live:
        if i in paths:
            continue
        l = links[i]
        chord = shapely.LineString([l.pts[0], l.pts[-1]])
        tol = max(STRAIGHT_TOL, 0.02 * chord.length)
        if chord.length < STRAIGHT_MIN or max(chord.distance(shapely.Point(p)) for p in l.pts) > tol:
            continue
        t = _bearing(l.pts[-1][0] - l.pts[0][0], l.pts[-1][1] - l.pts[0][1])
        h = (_nearest_grid(t) if _prefers_grid(l.pts) else _nearest(t))[0]
        if _adiff(ANGLE[h], t) > STRAIGHT_MAX_DEG:
            continue
        if (i, "u") in heading and heading[(i, "u")] != h:
            continue
        cand.append((i, h))
    if not cand:
        return {}, "streets squared: 0"
    roots = sorted({merged[links[i].u] for i, _h in cand} | {merged[links[i].v] for i, _h in cand})
    at = {r: k for k, r in enumerate(roots)}
    p0 = np.array([corner[groups[r][0]] for r in roots], float)
    active = list(cand)
    dropped = 0
    for _ in range(60):
        rows, cols, vals, rhs = [], [], [], []
        eq = 0
        for r, k in at.items():                      # stay put, the held ones hard
            w = 1000.0 if r in fixed else 1.0
            for c in (0, 1):
                rows.append(eq); cols.append(2 * k + c); vals.append(w); rhs.append(w * p0[k, c]); eq += 1
        for i, h in active:                          # each squared street on its direction
            dx, dy = STEP[h]
            n = np.array([-dy, dx], float) / math.hypot(dx, dy)
            ku, kv = at[merged[links[i].u]], at[merged[links[i].v]]
            for c in (0, 1):
                rows += [eq, eq]; cols += [2 * kv + c, 2 * ku + c]; vals += [30.0 * n[c], -30.0 * n[c]]
            rhs.append(0.0); eq += 1
        sol = _least_squares(rows, cols, vals, rhs, 2 * len(roots), p0.ravel()).reshape(-1, 2)
        cap = np.array([STRAIGHT_MOVE_END if r in ends else STRAIGHT_MOVE for r in roots])
        move = np.abs(sol - p0).max(axis=1) / cap
        worst = int(np.argmax(move))
        if move[worst] <= 1.0:
            break
        # Let go the street at the worst junction that is furthest off its direction.
        r = roots[worst]
        touching = [(i, h) for i, h in active if r in (merged[links[i].u], merged[links[i].v])]
        if not touching:
            break
        def off(ih):
            i, h = ih
            dx, dy = STEP[h]
            n = np.array([-dy, dx], float) / math.hypot(dx, dy)
            return abs(n @ (p0[at[merged[links[i].v]]] - p0[at[merged[links[i].u]]]))
        active.remove(max(touching, key=off))
        dropped += 1
    # Rounded to tiles a group at a time: the junctions a squared street along
    # the grid joins share one row (or column), a held one's if it has one,
    # so rounding leaves no street a tile out of line.
    new_xy = {r: [sol[at[r], 0], sol[at[r], 1]] for r in roots}
    for axis, hs in ((1, (0, 8)), (0, (4, 12))):          # rows for east-west streets, columns for north-south
        parent = {r: r for r in roots}

        def find(r):
            while parent[r] != r:
                parent[r] = parent[parent[r]]
                r = parent[r]
            return r
        for i, h in active:
            if h in hs:
                parent[find(merged[links[i].u])] = find(merged[links[i].v])
        members: dict = {}
        for r in roots:
            members.setdefault(find(r), []).append(r)
        for group in members.values():
            held = [r for r in group if r in fixed]
            value = p0[at[held[0]], axis] if held else round(float(np.mean([new_xy[r][axis] for r in group])))
            for r in group:
                new_xy[r][axis] = value
    new = {r: (int(round(new_xy[r][0])), int(round(new_xy[r][1]))) for r in roots if r not in fixed}
    for r, c in new.items():
        for m in groups[r]:
            corner[m] = c
    straight = {}
    for i, h in active:
        l = links[i]
        if _lateral(corner[l.u], corner[l.v], h) == 0 and corner[l.u] != corner[l.v]:
            straight[i] = h
            heading[(i, "u")] = h
            heading[(i, "v")] = _opposite(h)
    moved = sum(1 for r, c in new.items() if c != tuple(int(v) for v in p0[at[r]]))
    return straight, f"streets squared: {len(straight)} of {len(cand)} ({dropped} let go), {moved} junctions moved"


def _least_squares(rows, cols, vals, rhs, n: int, x0) -> np.ndarray:
    """x minimising |A x - b| for the sparse A given as (rows, cols, vals): conjugate
    gradients on the normal equations, scaled by their diagonal (a held junction's rows
    weigh a thousand times the rest), from x0."""
    rows, cols, vals = np.asarray(rows), np.asarray(cols), np.asarray(vals, float)
    b = np.asarray(rhs, float)
    m = len(b)

    def AtA(x):
        y = np.bincount(rows, vals * x[cols], minlength=m)
        return np.bincount(cols, vals * y[rows], minlength=n)
    diag = np.bincount(cols, vals * vals, minlength=n)
    diag[diag == 0] = 1.0
    x = np.array(x0, float)
    r = np.bincount(cols, vals * b[rows], minlength=n) - AtA(x)
    z = r / diag
    p = z.copy()
    rz = r @ z
    scale = max(np.abs(r).max(), 1e-30)
    for _ in range(20 * n):
        if np.abs(r).max() <= 1e-10 * scale:
            break
        q = AtA(p)
        alpha = rz / (p @ q)
        x += alpha * p
        r -= alpha * q
        z = r / diag
        rz_new = r @ z
        p = z + (rz_new / rz) * p
        rz = rz_new
    return x


def _pin_heading(pins, node, pts) -> int:
    """The heading into the map nearest the road's way from a pin."""
    q = _point_along(pts, ARM_LOOK)
    t = _bearing(q[0] - pts[0][0], q[1] - pts[0][1])
    return min((h for h in range(N) if _inward(h, pins[node])), key=lambda h: _adiff(ANGLE[h], t))


def _lateral(s, g, h: int) -> int:
    """How far g is off the line from s on heading h: the cross product with
    the step, so 0 exactly when g is on that line of corners."""
    dx, dy = STEP[h]
    return dx * (g[1] - s[1]) - dy * (g[0] - s[0])


def _shift(p, h: int, amount: int):
    """p moved straight along the grid so its _lateral (as the far end g)
    changes by `amount` - across x or y, whichever the step crosses by one."""
    dx, dy = STEP[h]
    if abs(dx) == 1:
        return (p[0], p[1] + amount * dx)
    return (p[0] - amount * dy, p[1])


STATES = {"searched": 0}     # states searched, for the slow-link log


# Which engine runs the search: "rust" (the same search in rust/knoxroute - see
# rustsearch.py) or "python" (the loop in _search). Python works out the ground
# either way; this only picks who searches it. Rust is the default and the
# interpreter's own search the fallback: no binary built, a trace wanted, or a
# turn rule the port does not carry, and it runs here instead.
BACKEND = "rust"
TRACE_TO = None            # a list: the equivalence harness's window on the rust search's pops
_UNAVAILABLE = object()    # the rust search could not run: use the python one
_ROUTER = None


def _close_router() -> None:
    global _ROUTER
    if _ROUTER is not None:
        try:
            _ROUTER.close()
        except OSError:
            pass
        _ROUTER = None


def close_router() -> None:
    """Let the rust search process go: the next map starts a fresh one."""
    _close_router()


def _rust_search(**kw):
    """(path, states) from rust/knoxroute, or _UNAVAILABLE if it cannot run."""
    global _ROUTER
    from . import rustsearch
    if not rustsearch.available():
        return _UNAVAILABLE
    try:
        if _ROUTER is None:
            _ROUTER = rustsearch.Router()
        if TRACE_TO is not None:            # the harness comparing the two searches
            got, _ = _ROUTER.search(**kw, trace=400)
            TRACE_TO.extend(got)
        return _ROUTER.search(**kw)
    except (OSError, RuntimeError):
        # A binary that will not start, or one that died mid-pipe, is no reason to
        # fail the map: the search below takes over, and the next call tries a
        # fresh process.
        _close_router()
        return _UNAVAILABLE


def _route(pts, s, g, h_start, h_arrive, wide, run_min, taken, me, reach=0, town=None, beta=BETA,
           band_town=BAND, alpha_town=ALPHA, free_town=0.0, near=None, limit=None, road_width=None, stops=()):
    """Corners from s to g, or None. A heading of None is free. Distance is
    from the real line with its ends moved to the snapped corners (a merged
    junction can sit some way off the line); how far a corner may stray and
    what straying costs are BAND and ALPHA in town, BAND_OPEN and ALPHA_OPEN
    out of it (the town mask at that corner), the bands times wide. With
    reach, the road may stop anywhere within reach of g, each tile short of
    it costing END_SHORT.

    State (x, y, heading, run, last turn): the run counts to twice the
    minimum, and while it is short of that a turn back the other way from
    the last costs REVERSE more. Searched exactly (EXACT_STATES at most),
    then leaning on the estimate GREEDY times (MAX_STATES); `limit` for
    both instead, if given."""
    tries = LADDER if limit is None else ((1.0, limit), (GREEDY, limit))
    for lean, cap in tries:
        path = _search(pts, s, g, h_start, h_arrive, wide, run_min, taken, me, reach, town, beta,
                       band_town, alpha_town, free_town, lean, cap, near, road_width, stops)
        if path is not None:
            return path
    return None


def _dist_field(line, gx, gy, far):
    """Distance from `line` at every corner of the window, and infinite past the
    band. Measured corner by corner over the whole window, this was most of the
    cost of every search on a long road - a diagonal road's window is the whole
    map, while the band it may run in is a thin corridor through it, and the
    distance to a long line is not cheap. The corridor found first, only the
    corners in it are measured; outside it the cost is infinite either way."""
    corridor = shapely.buffer(line, far + 2, quad_segs=8)
    shapely.prepare(corridor)
    rows, cols = np.nonzero(shapely.contains_xy(corridor, gx, gy))
    out = np.full(gx.shape, np.inf)
    if rows.size:
        out[rows, cols] = shapely.distance(
            shapely.points(gx[rows, cols].astype(float), gy[rows, cols].astype(float)), line)
    return out


def _search(pts, s, g, h_start, h_arrive, wide, run_min, taken, me, reach, town, beta,
            band_town, alpha_town, free_town, lean, limit, near=None, road_width=None, stops=(),
            trace=None):
    """One A* search for _route: the estimate times `lean`, `limit` states.

    With `trace` (a list), the first five hundred states it pops are appended to
    it - (estimate, cost, x, y, heading, run, last turn) - so another engine's
    search can be compared with it step for step. See rust/knoxroute."""
    width = run_min                                  # min_run is the road's width (4 at least)
    road_w = road_width or run_min                   # the jog rule's width (its gap is from the edge)
    if s == g:
        return None
    pts = [s] + list(pts[1:-1]) + [g]
    line = shapely.LineString(pts)
    far = (BAND_OPEN if town is not None else band_town) * wide
    x0 = int(math.floor(min(p[0] for p in pts) - far - 2))
    y0 = int(math.floor(min(p[1] for p in pts) - far - 2))
    x1 = int(math.ceil(max(p[0] for p in pts) + far + 2))
    y1 = int(math.ceil(max(p[1] for p in pts) + far + 2))
    gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
    dist = _dist_field(line, gx, gy, far)
    if town is None:
        band, alpha, free = band_town * wide, alpha_town, free_town
    else:
        H, W = town.shape
        inside = town[np.clip(gy, 0, H - 1), np.clip(gx, 0, W - 1)]
        band = np.where(inside, band_town * wide, BAND_OPEN * wide)
        alpha = np.where(inside, alpha_town, ALPHA_OPEN)
        free = np.where(inside, free_town, FREE_OPEN)
    # What a corner costs to step on (times the step's length): nothing for
    # straying within `free` of the line, then the square of the rest; inf
    # beyond the band.
    over = np.maximum(dist - free, 0.0)
    weight = np.where(dist <= band, 1 + alpha * over * over + TIE * dist * dist, np.inf)
    if near is not None:
        # Near another road (CLEAR_PAD of its edge) costs more - but not by
        # this road's own ends, where it joins the others.
        H, W = near.shape
        close = near[np.clip(gy, 0, H - 1), np.clip(gx, 0, W - 1)].copy()
        close &= (np.hypot(gx - s[0], gy - s[1]) > run_min + 6) & (np.hypot(gx - g[0], gy - g[1]) > run_min + 6)
        weight = weight + CLEAR_COST * close
    # Out of town a run between bends must be longer (min_run's open-country
    # rule), read at the corner where the bend would be.
    if town is None:
        run_here = np.full(dist.shape, run_min)
    else:
        run_here = np.where(inside, run_min, 2 * run_min)
    # Frontage density (mode "cost"): its cost a step, and long runs where it is dense.
    cdens = None
    if COST is not None:
        CH, CW = COST.shape
        cdens = COST[np.clip(gy, 0, CH - 1), np.clip(gx, 0, CW - 1)]
        if JOG is not None:
            run_here = np.where(cdens >= JOG_DENSITY, JOG_RUN * run_here, run_here)
    jog_on = JOG is not None and COST is not None
    # Near its own ends a road may cross what is taken (it joins it there).
    end_r = run_min + 4
    # Occupancy: building squares under the carriageway, per tile of road.
    occw = None
    if OCC is not None and OCC_WEIGHT > 0:
        f = occ_field(road_w)
        FH, FW = f.shape
        occw = OCC_WEIGHT * f[np.clip(gy, 0, FH - 1), np.clip(gx, 0, FW - 1)]
    # May a road turn at a corner here (mode "cost")? A dense corner with a
    # frontage on it may only do so at a junction (or where the frontage has a
    # gap): worked out once for the window, so the search reads a corner
    # rather than calling turn_ok for every state.
    turnable = None
    if jog_on and JOG.get("plots") is None:
        CH, CW = JOG["dist"].shape
        gap = JOG["dist"][np.clip(gy, 0, CH - 1), np.clip(gx, 0, CW - 1)] > road_w / 2 + JOG_GAP
        turnable = ((cdens < JOG_DENSITY) | gap).tolist()

    turn_pts = (s, g, *stops)
    turn_reach = max(JOG_END, road_w)

    def may_turn(x, y, hd):
        """turn_ok, read off that field."""
        if turnable is None:
            return turn_ok(x, y, hd, road_w, s, g, stops)
        if turnable[y - y0][x - x0]:
            return True
        return min(math.dist((x, y), q) for q in turn_pts) <= turn_reach
    # The way the real line runs (degrees) at the point of it nearest each
    # corner: a step may not go more than 90 degrees from it, so a road never
    # doubles back on itself (with room to wander it would rather loop round
    # than arrive on its heading with a jog).
    # Only the corners within the band can be stepped on (past it the cost is
    # inf, and nothing reads those), and on a long road they are a fraction of
    # the window: read the line's way for those corners alone.
    way = np.zeros(gx.shape)
    flat = np.nonzero(dist <= band)
    if flat[0].size:
        px, py = gx[flat], gy[flat]
        along = shapely.line_locate_point(line, shapely.points(px, py))
        p0 = shapely.line_interpolate_point(line, np.maximum(along - 2.0, 0.0))
        p1 = shapely.line_interpolate_point(line, np.minimum(along + 2.0, line.length))
        way[flat] = np.degrees(np.arctan2(shapely.get_y(p1) - shapely.get_y(p0),
                                          shapely.get_x(p1) - shapely.get_x(p0))) % 360

    notch = beta * TURN_SHARE                # a turn of one notch
    # Read per corner, often, in the search below: plain lists are quicker
    # than a numpy array, and this is a few seconds' work even on the widest
    # window.
    weight_l, way_l, run_l = weight.tolist(), way.tolist(), run_here.tolist()
    dens_l = None if cdens is None else cdens.tolist()
    occ_l = None if occw is None else occw.tolist()
    taken_get = taken.get
    INF = math.inf
    reach_short = reach * math.sqrt(2)
    reach_near = reach + 2

    hcache: dict = {}                     # (corner, heading) -> the bound: one search's, and
                                          # the same state is reached again and again

    def h(x, y, hd=None):
        """A lower bound on the cost to the goal: the straight distance, and a
        notch's cost for each notch the heading must still swing - to head
        less than 90 degrees off the goal, and to arrive on the heading
        wanted."""
        key = (x, y, hd)
        got = hcache.get(key)
        if got is not None:
            return got
        dx, dy = g[0] - x, g[1] - y
        dist = math.hypot(dx, dy) - reach_short
        if dist < 0.0:
            dist = 0.0
        if hd is None or hd == DONE:
            hcache[key] = dist
            return dist
        turns = 0
        if max(abs(dx), abs(dy)) > reach_near:
            a = _bearing(dx, dy)
            if a in SWING_SET:
                # Exactly on a boundary - square to the goal, as a grid town's
                # streets are - the sector either side cannot hold both
                # headings' strictness, so the walk is taken after all.
                turns = min(_notches(hd, b) for b in range(N) if _adiff(ANGLE[b], a) < 90)
            else:
                k = bisect.bisect_right(SWING_BOUNDS, a)
                turns = SWING_TABLE[k - 1 if k else len(SWING_BOUNDS) - 1][hd]
        if h_arrive is not None:
            back = _notches(hd, h_arrive)
            if back > turns:
                turns = back
        out = lean * (dist + notch * turns)
        hcache[key] = out
        return out
    # The first and last runs need half the minimum: the junction's own
    # width stands in for the rest.
    end_run = (run_min + 1) // 2
    cap = int(run_here.max()) * 2 if np.size(run_here) else 2 * run_min

    # A test at the ends before searching: a road leaves s on h_start and
    # reaches g on h_arrive with a straight run of end_run, so those corners
    # must be ones a step may land on (in the band, not doubling back on the
    # line). If not, no path exists at these headings, and the search would
    # only run to its limit to find out (a few squares here, not a band).
    def steppable(cx, cy, hd):
        return (x0 <= cx <= x1 and y0 <= cy <= y1 and weight[cy - y0, cx - x0] != math.inf
                and _adiff(ANGLE[hd], way[cy - y0, cx - x0]) <= BACK_LIMIT)
    if h_start is not None:
        dx, dy = STEP[h_start]
        if not all(steppable(s[0] + dx * j, s[1] + dy * j, h_start)
                   for j in range(1, -(-end_run // SPAN[h_start]) + 1)):
            return None
    if h_arrive is not None and reach == 0:
        dx, dy = STEP[h_arrive]
        if not all(steppable(g[0] - dx * j, g[1] - dy * j, h_arrive)
                   for j in range(-(-end_run // SPAN[h_arrive]))):
            return None
    if BACKEND == "rust" and trace is None and turnable is not None:
        # The same search, out of process: all the ground work above is done, so
        # only the pops move. It keeps the mask's turn rule, which is the cost
        # mode's - any other mode stays in the loop below rather than guess at
        # turn_ok. Tracing stays here, where the analysis is.
        win_w, win_h = x1 - x0 + 1, y1 - y0 + 1
        got = _rust_search(
            x0=x0, y0=y0, w=win_w, h=win_h, s=s, g=g, h_start=h_start, h_arrive=h_arrive,
            reach=reach, run_min=run_min, cap=cap, end_run=end_run, end_r=end_r,
            road_width=road_w, beta=beta, lean=lean, limit=limit, weight=weight, way=way,
            dens=cdens, occ=occw, turnable=turnable, run_here=run_here,
            taken_idx=np.fromiter(((q[1] - y0) * win_w + (q[0] - x0) for q in taken),
                                  "<i4", len(taken)),
            taken_owner=np.fromiter(taken.values(), "<i4", len(taken)), me=me, stops=stops)
        if got is not _UNAVAILABLE:
            path, states = got
            STATES["searched"] += states
            return path
    starts = [(s[0], s[1], hd, run_min - end_run, 0) for hd in (range(N) if h_start is None else [h_start])]
    best = {st: 0.0 for st in starts}
    best_get = best.get
    came = {}
    via: dict = {}                                   # a state reached by a curve: the corners on the way
    tick = itertools.count()
    heap = [(h(s[0], s[1], st[2]), -0.0, next(tick), st) for st in starts]   # equal f: the deeper first
    heapq.heapify(heap)          # a list is not a heap: without this the first pops are of
                                 # whatever sits at the front, whichever heading that is
    seen = 0
    while heap:
        _f, neg, _t, st = heapq.heappop(heap)
        cost = -neg
        if cost > best_get(st, INF):
            continue
        if trace is not None and len(trace) < 500:
            trace.append((_f, cost) + st)
        x, y, hd, run, last = st
        if hd == DONE:
            STATES["searched"] += seen
            out = [(x, y)]
            st = came[st]                   # the same corner, arrived at
            while st in came:
                out += via.get(st, [])[::-1]
                st = came[st]
                out.append((st[0], st[1]))
            return out[::-1]
        if max(abs(x - g[0]), abs(y - g[1])) <= reach and h_arrive in (None, hd) and run >= end_run                 and (x, y) != s:                     # at least one step
            done = (x, y, DONE, 0, 0)
            dc = cost + END_SHORT * math.dist((x, y), g)
            if dc < best_get(done, INF):
                best[done] = dc
                came[done] = st
                heapq.heappush(heap, (dc, -dc, next(tick), done))
        seen += 1
        if seen > limit:
            STATES["searched"] += seen
            return None
        need = run_l[y - y0][x - x0]
        # Moves: (steps [(heading, count)], new heading, run after, last turn,
        # turn cost) - the straight run, then vanilla's sharp turns and its
        # curves, taken from the heading's own list rather than built here.
        nrun = run + SPAN[hd]
        if nrun > cap:
            nrun = cap
        moves = [([(hd, 1)], hd, nrun, 0 if nrun >= cap else last, 0.0)]
        if run >= need and (not jog_on or may_turn(x, y, hd)):
            short = run < 2 * need
            for steps, nh, nr, sign, turn_cost in _sharp_moves(hd, beta):
                back = REVERSE if short and last * sign < 0 else 0.0
                moves.append((steps, nh, nr, sign, turn_cost + back))
            scale = 1.0 if need <= run_min else 2.0      # out of town, gentler
            for steps, nh, nr, sign, turn_cost in _curved_moves(hd, width, scale, beta):
                back = REVERSE if short and last * sign < 0 else 0.0
                moves.append((steps, nh, nr, sign, turn_cost + back))
        for steps, nh, nr, nl, extra in moves:
            cx, cy = x, y
            nc = cost + extra
            corners = []
            ok = True
            for sh, count in steps:
                dx, dy = STEP[sh]
                ang = ANGLE[sh]
                slope = SLOPE[sh]
                for _ in range(count):
                    cx += dx
                    cy += dy
                    if cx < x0 or cx > x1 or cy < y0 or cy > y1:
                        ok = False
                        break
                    row = cy - y0
                    col = cx - x0
                    wgt = weight_l[row][col]
                    if wgt == INF:
                        ok = False
                        break
                    d = ang - way_l[row][col]
                    d %= 360.0
                    if d > BACK_LIMIT and 360.0 - d > BACK_LIMIT:
                        ok = False
                        break
                    owner = taken_get((cx, cy))
                    if owner is not None and owner != me and \
                            min(abs(cx - s[0]) + abs(cy - s[1]), abs(cx - g[0]) + abs(cy - g[1])) > end_r:
                        ok = False
                        break
                    nc += LENGTH[sh] * SLOPE_COST[slope] * wgt
                    if dens_l is not None:
                        nc += LENGTH[sh] * COST_SCALE * dens_l[row][col] * DIR_PENALTY[slope]
                    if occ_l is not None:
                        nc += LENGTH[sh] * occ_l[row][col]
                    corners.append((cx, cy))
                if not ok:
                    break
            if not ok:
                continue
            ns = (cx, cy, nh, nr, nl)
            if nc < best_get(ns, INF):
                best[ns] = nc
                came[ns] = st
                if len(corners) > 1:
                    via[ns] = corners[:-1]
                else:
                    via.pop(ns, None)
                heapq.heappush(heap, (nc + h(cx, cy, nh), -nc, next(tick), ns))
    STATES["searched"] += seen
    return None
