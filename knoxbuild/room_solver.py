"""House rooms by constraint solver (OR-Tools CP-SAT): the room_solver setting.

Off by default (Settings.room_solver = 0): every building is laid out as before.
On, each house of up to four storeys is laid out as a whole by a constraint model
and a building it cannot fit, or anything that is not a house, keeps Build's own
layout. Without OR-Tools installed it does nothing. A house's programme (which
rooms, at what sizes: room_solver.json) is chosen by its storeys and floor area.
The programmes and room kinds came from English houses (KnoxMap UK, where the
regional data also gives each house its age and type - the `uk_rooms` record the
house_from_job path below reads when a map has one).

A house's storeys are laid out together in one model: each room is a
rectangle, or an L of two, of its kind's sizes (room_solver.json "kinds"); the
rooms fill each storey's mask exactly; the stairs are a 1 x 5 strip in the
same place on every storey, belonging to the hall below and the landing above.
The hall and landing are the stairs plus as little passage as the doors need
(their passage is the dearest square in the house).

Windows are planned with the rooms: each outside wall has its window columns
(every 3 squares front and back, 5 on the ends, from the outline), a room that
needs a window must hold a column with its own wall either side of it, and a
column kept on one storey is kept on the others where it can be, so windows
stack.

    python -m knoxbuild.room_solver --demo [out_dir]

writes plan pictures of a few made-up houses. Without OR-Tools, or when no
variant of a programme fits, solve() returns None and Build keeps its own
layout.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
TABLES = json.load(open(os.path.join(HERE, "room_solver.json"), encoding="utf-8"))
KINDS = TABLES["kinds"]
RULES = TABLES["rules"]
WEIGHTS = TABLES["weights"]
PROGRAMMES = TABLES["programmes"]
SHOPS = TABLES["shops"]

STAIR_RUN = 5          # as layout.STAIR_RUN: the flight's squares, from Stairs::bounds
ROOT_KINDS = ("hall", "landing")
SHOP_ONLY = "shop_only"     # a business with no homes: shop_only@class (room_solver.json "shops")
_COMPOSED = {}


def use_class(use) -> str:
    """A business's class (room_solver.json shops.classes) by its rooms ("front|back":
    a guest house's lobby and office) or its front room: food, bank, surgery,
    office, pub, guest; anything else is retail."""
    if not use:
        return "retail"
    classes = SHOPS["classes"]
    return classes.get(f"{use[0]}|{use[1]}", classes.get(use[0], "retail"))


def conversion(info: dict, use) -> str | None:
    """A business in a house (option C, room_solver.json shops.converted): its class
    when it is an office, surgery or guest house and the building's look is a
    house's; None otherwise."""
    cls = use_class(use)
    if cls not in SHOPS["converted"]["rename"]:
        return None
    look = (info or {}).get("look") or ""
    house = RULES["look_programmes"].get(look) is not None or look in SHOPS["converted"]["looks"]
    return cls if house else None


def is_programme(name: str) -> bool:
    if name in PROGRAMMES:
        return True
    base, _, cls = (name or "").partition("@")
    return cls in SHOPS["grounds"] and (base == SHOP_ONLY or base in PROGRAMMES)


def _composed(name: str) -> dict:
    """base@class: a commercial programme. shop_only@class
    is a business with no homes - the class's ground floor, a stair hall behind
    it opening off the back rooms when there is an upper floor, and the class's
    upper floors (store rooms and a break room; a pub's function room); one
    variant for each of 1-4 storeys. Any other base (shop_house, shop_flats...)
    keeps its own variants, the homes' lobby on the ground floor and the floors
    above, with the shop's rooms swapped for the class's."""
    if name in _COMPOSED:
        return _COMPOSED[name]
    base, _, cls = name.partition("@")
    ground = SHOPS["grounds"][cls]
    if base == SHOP_ONLY:
        upper = SHOPS["uppers"].get(cls, SHOPS["uppers"]["store"])
        hall = dict(SHOPS["stair_hall"], **{"from": SHOPS["stair_from"]})
        prog = {"weights": dict(SHOPS["weights"]),
                "variants": [[ground + ([hall] if n > 1 else [])] + [upper] * (n - 1) for n in range(1, 5)]}
    else:
        own = PROGRAMMES[base]
        prog = dict(own) if isinstance(own, dict) else {"variants": own}
        prog["weights"] = dict(prog.get("weights", {}), **SHOPS["weights"])
        prog["variants"] = [[ground + [r for r in v[0] if r["kind"] in ("hall", "cupboard")]]
                            + [floor + SHOPS["upper_extra"] for floor in v[1:]]
                            for v in prog["variants"]]
    _COMPOSED[name] = prog
    return prog


def programme_tables(name: str):
    """A programme's variants, weights and room kinds: a programme is a list
    of variants, or {"variants": [...], "weights": {...}, "kinds": {kind: {...}}}
    whose weights and kind fields replace the shared ones for its houses
    (a large house's bigger rooms, and a hall and landing allowed to be
    corridors)."""
    prog = _composed(name) if "@" in name else PROGRAMMES[name]
    if isinstance(prog, list):
        return prog, WEIGHTS, KINDS
    wt = dict(WEIGHTS, **prog.get("weights", {}))
    kd = dict(KINDS)
    for kind, over in prog.get("kinds", {}).items():
        kd[kind] = dict(KINDS[kind], **over)
    return prog["variants"], wt, kd


def _from(spec: dict) -> list:
    """The rooms a programme room may open from: its own list, else its kind's."""
    return spec.get("from", KINDS[spec["kind"]]["from"])


def _is_root(spec: dict) -> bool:
    """Where a storey's doors start: the hall or landing, or a programme's own
    root (a cottage's front door straight into its living room). A hall with
    root false opens off another room (the stairs behind a shop with no homes)."""
    return bool(spec.get("root", spec["kind"] in ROOT_KINDS))
STAIRS_OFF_STREET = False  # True: no square of the flight on the street wall (too strict for terraces)
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
STEP = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}


@dataclass
class House:
    """What the solver is given. masks[level][y][x] is True on the house's
    squares; party holds (x, y, side) for each square edge on a party wall;
    garage is a fixed (x0, y0, x1, y1) on the ground floor."""
    width: int
    height: int
    masks: list
    street: str = "S"
    party: set = field(default_factory=set)
    garage: tuple | None = None
    epc_rooms: int | None = None     # habitable rooms its EPCs say it has (a soft target)
    homes: int | None = None         # a block of flats: how many (shops.py's knox_homes)
    entry: tuple | None = None       # a flat: the square its front door opens onto
    inner: bool = False              # a flat inside a block: no outside doors of its own

    def inside(self, lvl, x, y):
        return 0 <= x < self.width and 0 <= y < self.height and self.masks[lvl][y][x]

    def outside_edge(self, lvl, x, y, side):
        """Whether square (x, y)'s edge on `side` is an outside wall (not party)."""
        dx, dy = STEP[side]
        return (self.inside(lvl, x, y) and not self.inside(lvl, x + dx, y + dy)
                and (x, y, side) not in self.party)


@dataclass
class Layout:
    """The answer, one entry per storey: rooms [{kind, build, rects, squares}],
    grid[y][x] (room number from 1, 0 = not house), doors and windows as
    Build's wall edges (x, y, "W"|"N"); stairs (x, y, "N"|"W") as Build's."""
    house: House
    programme: str
    variant: int
    storeys: list
    stairs: tuple | None
    seconds: float
    front_door: tuple | None = None
    back_door: tuple | None = None


# ---- the model's pieces -------------------------------------------------------

class Rect:
    """A rectangle of squares x0..x1, y0..y1 (inclusive), each a linear
    expression; `on` is its presence literal (True for a rectangle every
    layout has)."""

    def __init__(self, x0, y0, wx, hy, on=True, area=None):
        self.x0, self.y0, self.wx, self.hy, self.on, self.area = x0, y0, wx, hy, on, area
        self.x1 = x0 + wx - 1
        self.y1 = y0 + hy - 1


def _iv(m, start, size, hi, on=None):
    """An interval start..start+size (CP-SAT wants its end as one variable)."""
    end = m.new_int_var(0, hi, "")
    if on is None:
        return m.new_interval_var(start, size, end, "")
    return m.new_optional_interval_var(start, size, end, on, "")


def _lits(*bs):
    return [b for b in bs if b is not True]


def _when(m, c, *conds):
    """Add constraint c only when every literal in conds holds."""
    lits = _lits(*conds)
    ct = m.add(c)
    if lits:
        ct.only_enforce_if(lits)


def _contact(m, a: Rect, b: Rect, k: int):
    """A literal that, when true, makes a and b share k or more squares of wall."""
    c = m.new_bool_var("")
    dirs = []
    for (lo, hi, p0, p1, q0, q1) in (
            (a.x0, b.x1, a.y0, a.y1, b.y0, b.y1),   # a east of b
            (b.x0, a.x1, a.y0, a.y1, b.y0, b.y1),   # a west of b
            (a.y0, b.y1, a.x0, a.x1, b.x0, b.x1),   # a south of b
            (b.y0, a.y1, a.x0, a.x1, b.x0, b.x1)):  # a north of b
        d = m.new_bool_var("")
        dirs.append(d)
        _when(m, lo == hi + 1, d)
        _when(m, p1 >= q0 + k - 1, d)
        _when(m, q1 >= p0 + k - 1, d)
        _when(m, p1 >= p0 + k - 1, d)
        _when(m, q1 >= q0 + k - 1, d)
    m.add_bool_or(dirs).only_enforce_if(c)
    for lit in _lits(a.on, b.on):
        m.add_implication(c, lit)
    return c


def _need(m, lits, pres) -> bool:
    """One of lits must hold when the room is there; False when a room that
    must be there never can (an optional one is then left out)."""
    if not lits:
        if pres is True:
            return False
        m.add(pres == 0)
        return True
    ct = m.add_bool_or(lits)
    if pres is not True:
        ct.only_enforce_if(pres)
    return True


def _contains(m, r: Rect, x, y):
    s = m.new_bool_var("")
    _when(m, r.x0 <= x, s)
    _when(m, r.x1 >= x, s)
    _when(m, r.y0 <= y, s)
    _when(m, r.y1 >= y, s)
    for lit in _lits(r.on):
        m.add_implication(s, lit)
    return s


def _segments(house: House, lvl: int, side: str):
    """The storey's outside walls facing `side` as straight runs:
    (line, a, b) = squares a..b along the wall, at row/column `line`."""
    w, h = house.width, house.height
    runs = []
    horizontal = side in ("N", "S")
    for line in range(h if horizontal else w):
        run = []
        for t in range(w if horizontal else h):
            x, y = (t, line) if horizontal else (line, t)
            if house.outside_edge(lvl, x, y, side):
                run.append(t)
            elif run:
                runs.append((line, run[0], run[-1]))
                run = []
        if run:
            runs.append((line, run[0], run[-1]))
    return runs


def _wall_of(house: House, lvl: int, side: str, k: int) -> list:
    """The outside walls facing `side` at least k long, as (side, segment); when
    that side has none (all party wall: a terrace house whose street side was
    taken from a side road), the two walls at right angles stand in."""
    segs = [(side, g) for g in _segments(house, lvl, side) if g[2] - g[1] + 1 >= k]
    if segs:
        return segs
    turn = ("E", "W") if side in ("N", "S") else ("N", "S")
    return [(sd, g) for sd in turn for g in _segments(house, lvl, sd) if g[2] - g[1] + 1 >= k]


def _touch(m, rect: Rect, side: str, seg, k: int):
    """A literal that, when true, puts k or more squares of rect on segment seg."""
    line, a, b = seg
    if b - a + 1 < k:
        return None
    t = m.new_bool_var("")
    edge = {"N": rect.y0, "S": rect.y1, "W": rect.x0, "E": rect.x1}[side]
    lo, hi = (rect.x0, rect.x1) if side in ("N", "S") else (rect.y0, rect.y1)
    _when(m, edge == line, t)
    _when(m, hi >= a + k - 1, t)
    _when(m, lo <= b - k + 1, t)
    _when(m, hi >= lo + k - 1, t)
    for lit in _lits(rect.on):
        m.add_implication(t, lit)
    return t


def window_columns(house: House, lvl: int):
    """Each outside wall's window spots: (x, y, side). Every 3 squares on the
    front and back, 5 on the ends, never a run's end square."""
    out = []
    front = (house.street, OPPOSITE[house.street])
    for side in "NSEW":
        pitch = RULES["pitch_front"] if side in front else RULES["pitch_side"]
        for line, a, b in _segments(house, lvl, side):
            n = b - a + 1
            if n < 3:
                # a short wall (the back room's beside a back addition): the
                # square at its inside corner, the wall going on indoors
                dx, dy = _along(side)
                for t in range(a, b + 1):
                    x, y = (t, line) if side in ("N", "S") else (line, t)
                    if house.inside(lvl, x - dx, y - dy) and house.inside(lvl, x + dx, y + dy):
                        out.append((x, y, side))
                        break
                continue
            count = max(1, (n + 1) // pitch)
            for k in range(count):
                i = min(max(1, int((k + .5) * n / count)), n - 2)
                t = a + i
                spot = (t, line, side) if side in ("N", "S") else (line, t, side)
                if spot not in out:
                    out.append(spot)
    return out


def _one_piece(mask) -> bool:
    """Whether a storey's squares all join up, side to side."""
    cells = {(x, y) for y, row in enumerate(mask) for x, v in enumerate(row) if v}
    if not cells:
        return True
    seen, todo = set(), [next(iter(cells))]
    while todo:
        x, y = todo.pop()
        if (x, y) in seen:
            continue
        seen.add((x, y))
        todo += [q for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if q in cells and q not in seen]
    return len(seen) == len(cells)


def stair_places(house: House):
    """Every (x, y, vert) the stairs may take: the 5 squares in every storey,
    and one long side of the flight against the ground floor's outside or
    party wall (English stairs run along a wall, not across a room)."""
    out = []
    levels = len(house.masks)
    for vert in (1, 0):
        for y in range(house.height):
            for x in range(house.width):
                sq = [(x + i * (1 - vert), y + i * vert) for i in range(STAIR_RUN)]
                if not all(house.inside(l, *q) for l in range(levels) for q in sq):
                    continue
                if house.garage:
                    gx0, gy0, gx1, gy1 = house.garage
                    if any(gx0 <= qx <= gx1 and gy0 <= qy <= gy1 for qx, qy in sq):
                        continue
                if STAIRS_OFF_STREET and any(house.outside_edge(0, qx, qy, house.street) for qx, qy in sq):
                    continue        # the flight keeps off the street wall
                sides = ("E", "W") if vert else ("N", "S")
                for side in sides:
                    dx, dy = STEP[side]
                    if all(not house.inside(0, qx + dx, qy + dy) for qx, qy in sq):
                        out.append((x, y, vert))
                        break
    return out


def _along(side):
    return (1, 0) if side in ("N", "S") else (0, 1)


# ---- solving ------------------------------------------------------------------

def _check_variant(house: House, variant: list):
    """1990 rules a variant must keep before it is tried."""
    if len(variant) != len(house.masks):
        return False
    if len(variant) >= RULES["bedrooms_upstairs_from"]:
        if any(r["kind"] in RULES["bedroom_kinds"] for r in variant[0]):
            return False
    for storey in variant:
        kinds = {r["kind"] for r in storey}
        for r in storey:
            frm = _from(r)
            if not _is_root(r) and frm and not (kinds & set(frm)):
                return False
    return True


# Speed (2026-10-20, measured on Alton): small houses on one solver thread
# (4 only from SMALL_FLOOR_M2), and a solve stops within REL_GAP of the best
# possible rather than proving it (None: prove it, to the time limit).
SMALL_FLOOR_M2 = None
REL_GAP = None
# Patience: a solve stops when it has found no better layout for this long
# (seconds), rather than searching to its time limit (None: to the limit).
TIMED_OUT = [False]         # set when a solve ran out of time (solve_varied reads it)
PATIENCE = 1.0              # measured on 30 Alton houses: 38% faster, the same houses laid out, objective 3% worse
LAST_OBJECTIVE = [None]       # the last solve's objective (for measuring)
# Set by prepare, once it has tried every footprint: Build's workers (they
# inherit it) then only read the cache. A footprint that ran out of time in
# prepare is not cached, and a worker used to solve it again at the same budget,
# so the same building came out the solver's way one run and Build's own the next
# (a pub with 18 rooms: then 7).
PREPARED = "KNOXMAP_ROOMS_PREPARED"

SLACK = (1.0, 1.5, 2.5)     # the room maxima tried as given, then stretched
MAX_FLOOR_M2 = 260          # a storey bigger than this keeps Build's own layout (not one house: a row, a block)


def solve(house: House, programme: str, seconds: float = 3.0, workers: int = 4, seed: int = 0):
    """The first variant of the programme that fits, as a Layout; None if none
    does. Every variant is tried with the rooms' maxima as given before any is
    tried with them stretched (a 1 m grid has no wall thickness to take up)."""
    try:
        from ortools.sat.python import cp_model  # noqa: F401
    except ImportError:
        return None
    start = time.time()
    if programme == "flats_block":
        return solve_flats(house, seconds, workers, seed)
    if any(sum(v for row in mk for v in row) > MAX_FLOOR_M2 for mk in house.masks):
        return None
    if not all(_one_piece(mk) for mk in house.masks):
        return None             # a storey in pieces (an outbuilding in the outline): Build's layout
    # a big house's model is bigger: more time (3 s, and 1 s per 10 m2 of its
    # biggest floor past 60, at most 20 s)
    biggest = max(sum(v for row in mk for v in row) for mk in house.masks)
    seconds = min(20.0, seconds + max(0, biggest - 60) / 10)
    if SMALL_FLOOR_M2 and biggest < SMALL_FLOOR_M2:
        workers = 1
    variants, wt, kd = programme_tables(programme)
    tries = [(slack, i, v) for slack in SLACK for i, v in enumerate(variants)]
    for slack, i, variant in tries:
        if not _check_variant(house, variant):
            continue
        got = _solve_variant(house, variant, seconds, workers, slack, seed, wt, kd)
        if got is not None:
            storeys, stairs = got
            lay = Layout(house, programme, i, storeys, stairs, time.time() - start)
            _place_openings(lay)
            return lay
    return None


def _solve_patiently(solver, model, patience: float):
    """Solve, stopping the search once no better layout has turned up for
    `patience` seconds after the first (a watcher thread; CP-SAT has no such
    setting). Until a first layout is found it searches to its time limit."""
    import threading
    from ortools.sat.python import cp_model

    last = [None]

    class Better(cp_model.CpSolverSolutionCallback):
        def on_solution_callback(self):
            last[0] = time.time()

    done = threading.Event()

    def watch():
        while not done.wait(0.1):
            if last[0] is not None and time.time() - last[0] > patience:
                solver.stop_search()
                return

    t = threading.Thread(target=watch, daemon=True)
    t.start()
    try:
        return solver.solve(model, Better())
    finally:
        done.set()


def _solve_variant(house: House, variant: list, seconds: float, workers: int,
                   slack: float = 1.0, seed: int = 0, wt: dict | None = None, kd: dict | None = None):
    import random
    from ortools.sat.python import cp_model
    # seed > 0: another layout of the same house - each room's size aimed a
    # little off, and a small pull on where rooms and stairs sit
    jig = random.Random(seed) if seed else None
    wt, kd = wt or WEIGHTS, kd or KINDS
    m = cp_model.CpModel()
    W, H = house.width, house.height
    levels = len(house.masks)
    cost = []

    # The stairs: one strip for every storey, its top at (sx, sy), running
    # down the page (Build's "N": foot at the bottom) when vert, else across.
    stairs = None
    if levels > 1:
        sx = m.new_int_var(0, W - 1, "sx")
        sy = m.new_int_var(0, H - 1, "sy")
        vert = m.new_bool_var("vert")
        m.add(sx + (STAIR_RUN - 1) * (1 - vert) <= W - 1)
        m.add(sy + (STAIR_RUN - 1) * vert <= H - 1)
        stairs = (sx, sy, vert)
        places = stair_places(house)
        if not places:
            return None
        m.add_allowed_assignments([sx, sy, vert], places)
        if jig:
            cost.append(jig.choice((-3, 3)) * sx + jig.choice((-3, 3)) * sy)

        def stair_square(i):
            return Rect(sx + i * (1 - vert), sy + i * vert, 1, 1)

    layouts = []
    for lvl, storey in enumerate(variant):
        xs, ys, area_terms = [], [], []
        mask_area = sum(sum(1 for v in row if v) for row in house.masks[lvl])

        # squares not in this storey: fixed blocks, a row run at a time
        for y in range(H):
            x = 0
            while x < W:
                if house.masks[lvl][y][x]:
                    x += 1
                    continue
                x2 = x
                while x2 + 1 < W and not house.masks[lvl][y][x2 + 1]:
                    x2 += 1
                xs.append(m.new_fixed_size_interval_var(x, x2 - x + 1, ""))
                ys.append(m.new_fixed_size_interval_var(y, 1, ""))
                x = x2 + 1

        walk_stair = []
        if stairs:
            sx, sy, vert = stairs
            xs.append(_iv(m, sx, 1 + (STAIR_RUN - 1) * (1 - vert), W))
            ys.append(_iv(m, sy, 1 + (STAIR_RUN - 1) * vert, H))
            area_terms.append(STAIR_RUN)
            if lvl < levels - 1:
                walk_stair.append(stair_square(STAIR_RUN - 1))   # the foot
            if lvl > 0:
                walk_stair.append(stair_square(0))               # the head

        rooms = []
        for spec in storey:
            kind = spec["kind"]
            k = kd[kind]
            rects = []
            # an optional room (a third bedroom, a study) is there if it fits
            pres = m.new_bool_var("") if spec.get("optional") else True
            if pres is not True:
                cost.append(-spec.get("value", wt["optional_room"]) * pres)
            n_rects = 2 if k["l"] else 1
            for j in range(n_rects):
                optional = j > 0 or kind in ROOT_KINDS or pres is not True
                if j == 0 and pres is not True:
                    on = pres
                else:
                    on = m.new_bool_var("") if optional else True
                    if on is not True and pres is not True:
                        m.add_implication(on, pres)
                side = k["side"]
                x0 = m.new_int_var(0, W - 1, "")
                y0 = m.new_int_var(0, H - 1, "")
                wx = m.new_int_var(side, W, "")
                hy = m.new_int_var(side, H, "")
                a = m.new_int_var(0, W * H, "")
                m.add_multiplication_equality(a, [wx, hy])
                if optional:
                    xs.append(_iv(m, x0, wx, 2 * W, on))
                    ys.append(_iv(m, y0, hy, 2 * H, on))
                    eff = m.new_int_var(0, W * H, "")
                    m.add(eff == a).only_enforce_if(on)
                    m.add(eff == 0).only_enforce_if(~on)
                    m.add(x0 + wx <= W).only_enforce_if(on)
                    m.add(y0 + hy <= H).only_enforce_if(on)
                    per = m.new_int_var(0, W + H, "")
                    m.add(per == wx + hy).only_enforce_if(on)
                    m.add(per == 0).only_enforce_if(~on)
                else:
                    xs.append(_iv(m, x0, wx, W))
                    ys.append(_iv(m, y0, hy, H))
                    eff, per = a, wx + hy
                if j == 0 and kind not in ROOT_KINDS:
                    # aspect: long side at most `aspect` times the short
                    asp = int(round(k["aspect"] * 10))
                    _when(m, 10 * wx <= asp * hy, on)
                    _when(m, 10 * hy <= asp * wx, on)
                r = Rect(x0, y0, wx, hy, on, eff)
                rects.append(r)
                area_terms.append(eff)
                cost.append(wt["wall"] * per)
            # an L: the second rectangle against the first
            if len(rects) == 2:
                first = rects[0]
                if kind in ROOT_KINDS:
                    # passage pieces are free-standing but must be used in order
                    m.add_implication(rects[1].on, rects[0].on)
                else:
                    m.add_implication(rects[1].on, _contact(m, first, rects[1], k["side"]))
            area = sum(r.area for r in rects)
            lo, hi = spec.get("area", k["area"])
            if k.get("grow") and slack > 1:
                # stretched past its size: allowed, at a price per m2
                over = m.new_int_var(0, W * H, "")
                m.add(over >= sum(r.area for r in rects) - hi)
                cost.append(wt["stretch"] * over)
                hi = int(hi * slack)
            _when(m, area >= lo, pres)
            _when(m, area <= hi, pres)
            if kind in ROOT_KINDS:
                cost.append(wt["stair_room"] * area)
            elif kind == "store":
                cost.append(wt["store"] * area)
            else:
                target = spec.get("target", k["target"]) + (jig.randint(-3, 3) if jig else 0)
                dev = m.new_int_var(0, W * H, "")
                _when(m, dev >= area - target, pres)
                _when(m, dev >= target - area, pres)
                cost.append(wt["size"] * dev)
                if jig:
                    cost.append(jig.choice((-2, -1, 1, 2)) * rects[0].x0)
                    cost.append(jig.choice((-2, -1, 1, 2)) * rects[0].y0)
            walk = list(rects)
            if kind in ROOT_KINDS and len(walk_stair) == 2:
                # a middle floor: the flight up starts where the flight from
                # below arrives only through the landing - its passage must
                # join the foot of the next flight to the head of this one
                foot, head = walk_stair
                ways = []
                for a in rects:
                    w = m.new_bool_var("")
                    for c in (_contact(m, a, head, 1), _contact(m, a, foot, 1)):
                        m.add_implication(w, c)
                    ways.append(w)
                for a in rects:
                    for b in rects:
                        if a is b:
                            continue
                        w = m.new_bool_var("")
                        for c in (_contact(m, a, head, 1), _contact(m, b, foot, 1), _contact(m, a, b, 1)):
                            m.add_implication(w, c)
                        ways.append(w)
                m.add_bool_or(ways)
            if kind in ROOT_KINDS:
                walk = walk_stair + rects
                # passage pieces join the stairs' walkable square or each other
                for j, r in enumerate(rects):
                    links = [_contact(m, r, s, 1) for s in walk_stair]
                    links += [_contact(m, r, rects[i], 1) for i in range(j)]
                    if links:
                        m.add_bool_or(links).only_enforce_if(r.on)
            rooms.append({"spec": spec, "kind": kind, "rects": rects, "walk": walk, "area": area,
                          "pres": pres})

        if lvl == 0 and house.garage:
            gx0, gy0, gx1, gy1 = house.garage
            xs.append(m.new_fixed_size_interval_var(gx0, gx1 - gx0 + 1, ""))
            ys.append(m.new_fixed_size_interval_var(gy0, gy1 - gy0 + 1, ""))
            area_terms.append((gx1 - gx0 + 1) * (gy1 - gy0 + 1))
            g = Rect(gx0, gy0, gx1 - gx0 + 1, gy1 - gy0 + 1)
            rooms.append({"spec": {"kind": "garage"}, "kind": "garage", "rects": [g], "walk": [g],
                          "fixed": True, "pres": True})

        # the kitchen behind the front room, the double bigger than the single...
        def back_of(r):
            """Twice the middle of r's first rectangle, counted from the street."""
            a = r["rects"][0]
            return {"S": -(a.y0 + a.y1), "N": a.y0 + a.y1,
                    "E": -(a.x0 + a.x1), "W": a.x0 + a.x1}[house.street]
        def one_home(ra, rb):
            return ra["spec"].get("unit", 0) == rb["spec"].get("unit", 0)
        for ka, kb in ([] if house.inner else RULES["behind"]):
            for ra in rooms:
                for rb in rooms:
                    if not one_home(ra, rb):
                        continue
                    if ra["kind"] == ka and (rb["kind"] == kb or (kb == "main" and rb["spec"].get("main"))):
                        _when(m, back_of(ra) >= back_of(rb) + 1, ra["pres"], rb["pres"])
        for ka, kb in RULES.get("behind_wanted", []):
            for ra in rooms:
                for rb in rooms:
                    if ra["kind"] == ka and (rb["kind"] == kb or (kb == "main" and rb["spec"].get("main"))):
                        ok = m.new_bool_var("")
                        m.add(back_of(ra) >= back_of(rb) + 1).only_enforce_if(ok)
                        for lit in _lits(ra["pres"], rb["pres"]):
                            m.add_implication(ok, lit)
                        cost.append(-wt["behind_wanted"] * ok)
        for ka, kb in RULES["larger"]:
            for ra in rooms:
                for rb in rooms:
                    if ra["kind"] == ka and rb["kind"] == kb and one_home(ra, rb):
                        _when(m, ra["area"] >= rb["area"] + 1, ra["pres"], rb["pres"])
        mains = [r for r in rooms if r["spec"].get("main")]
        for r in rooms:
            if mains and r is not mains[0] and r["kind"] == mains[0]["kind"]:
                m.add(mains[0]["area"] >= r["area"])

        m.add_no_overlap_2d(xs, ys)
        m.add(sum(area_terms) == mask_area)

        # Doors: a tree from the hall (landing) - each room opens off one
        # room of a kind it may open from, nearer the root than itself.
        roots = [r for r in rooms if _is_root(r["spec"])]
        if not roots:
            return None
        depth = [m.new_int_var(0, len(rooms), "") for _ in rooms]
        parents = {}
        for i, r in enumerate(rooms):
            if _is_root(r["spec"]):
                m.add(depth[i] == 0)
                continue
            allowed = _from(r["spec"])
            choices = []
            mine = r["spec"].get("unit", 0)
            for j, p in enumerate(rooms):
                if j == i or p["kind"] not in allowed:
                    continue
                theirs = p["spec"].get("unit", 0)
                # a flat's way in (its hall, or in a block its zone) is off the shared hall
                if theirs != mine and not (theirs == 0 and r["kind"] in ("flat_hall", "flat_zone")):
                    continue
                if [r["kind"], p["kind"]] in RULES["no_door"] or [p["kind"], r["kind"]] in RULES["no_door"]:
                    continue
                s = m.new_bool_var("")
                m.add(depth[i] >= depth[j] + 1).only_enforce_if(s)
                if r["spec"].get("prefer", RULES.get("prefer_from", {}).get(r["kind"])) == p["kind"]:
                    cost.append(-wt["prefer_from"] * s)
                links = [_contact(m, a, b, 1) for a in r["walk"] for b in p["walk"]]
                m.add_bool_or(links).only_enforce_if(s)
                choices.append((j, s))
            if not choices:
                if r["pres"] is True:
                    return None
                m.add(r["pres"] == 0)
                continue
            if r["kind"] == "garage":
                # a door through to the house is wanted, not needed
                linked = m.new_bool_var("")
                m.add(sum(s for _, s in choices) == linked)
                cost.append(-wt["garage_door"] * linked)
            else:
                m.add(sum(s for _, s in choices) == (1 if r["pres"] is True else r["pres"]))
            parents[i] = choices

        # A flat's hall holds the square its front door opens onto
        if house.entry and lvl == 0:
            for r in rooms:
                if r["spec"].get("entry"):
                    ex, ey = house.entry
                    m.add_bool_or([_contains(m, rect, ex, ey) for rect in r["rects"]])
        # Walls the rooms must have: the front door's, the back door's
        for r in rooms:
            k_out = r["spec"].get("outside")
            if k_out:
                # outside wall enough for its windows, on any side
                lits = [t for rect in r["rects"] for sd in "NSEW" for seg in _segments(house, lvl, sd)
                        if (t := _touch(m, rect, sd, seg, k_out)) is not None]
                if not _need(m, lits, r["pres"]):
                    return None
            for key, side in (("front", house.street), ("back", OPPOSITE[house.street])):
                k = r["spec"].get(key)
                if not k:
                    continue
                # the hall's own passage, not the stairs, meets the front door
                lits = [t for rect in r["rects"] for sd, seg in _wall_of(house, lvl, side, k)
                        if (t := _touch(m, rect, sd, seg, k)) is not None]
                if not _need(m, lits, r["pres"]):
                    return None
            k = r["spec"].get("rear")
            if k:
                # a business's back rooms (the cellar, the kitchen, the toilets, the
                # stairs) on its back wall where it has one: wanted, not needed (a
                # unit with party walls all round has none)
                lits = [t for rect in r["rects"] for sd, seg in _wall_of(house, lvl, OPPOSITE[house.street], k)
                        if (t := _touch(m, rect, sd, seg, k)) is not None]
                if lits and r["spec"].get("rear_need"):
                    _need(m, lits, r["pres"])       # needed where there is a wall (a pub's drop door)
                elif lits:
                    at = m.new_bool_var("")
                    m.add_bool_or(lits).only_enforce_if(at)
                    cost.append(-wt.get("rear", 0) * at)
            if r["spec"].get("main"):
                # the main bedroom on the street wall
                lits = [t for rect in r["rects"] for sd, seg in _wall_of(house, lvl, house.street, 2)
                        if (t := _touch(m, rect, sd, seg, 2)) is not None]
                if not _need(m, lits, r["pres"]):
                    return None

        # Windows: a room holds a column when the column's square and the
        # squares either side along the wall are all its own.
        cols = window_columns(house, lvl)
        win = {}
        for wi, (x, y, side) in enumerate(cols):
            dx, dy = _along(side)
            owners = []
            for i, r in enumerate(rooms):
                if kd[r["kind"]]["window"] == "no":
                    continue
                o = m.new_bool_var("")
                reach = ((x, y),) if kd[r["kind"]].get("small_window") else                     ((x, y), (x - dx, y - dy), (x + dx, y + dy))
                for (qx, qy) in reach:
                    m.add_bool_or([_contains(m, rect, qx, qy) for rect in r["rects"]]).only_enforce_if(o)
                win[(i, wi)] = o
                owners.append(o)
            if owners:
                m.add(sum(owners) <= 1)
        for i, r in enumerate(rooms):
            mine = [win[(i, wi)] for wi in range(len(cols)) if (i, wi) in win]
            want = kd[r["kind"]]["window"]
            if want == "need":
                if not _need(m, mine, r["pres"]):
                    return None
            elif want == "want" and mine:
                has = m.new_bool_var("")
                m.add_bool_or(mine).only_enforce_if(has)
                cost.append(-wt["want_window"] * has)
            if mine:
                # the windows it holds are the windows it gets: no more than its cap
                m.add(sum(mine) <= kd[r["kind"]]["cap"])
                cost.append(-wt["window"] * sum(mine))
        alive = {}
        for wi, col in enumerate(cols):
            owned = [win[(i, wi)] for i in range(len(rooms)) if (i, wi) in win]
            if owned:
                a = m.new_bool_var("")
                m.add(a == sum(owned))
                alive[col] = a
        layouts.append({"rooms": rooms, "parents": parents, "alive": alive, "cols": cols, "win": win})

    # A block's zones stack: on a floor of the same outline as the ground, each
    # room (the shared hall or landing's passage, each flat's zone) as below.
    if variant[0][0].get("stack"):
        for lvl in range(1, levels):
            if house.masks[lvl] != house.masks[0]:
                continue
            for ra, rb in zip(layouts[lvl]["rooms"], layouts[0]["rooms"]):
                for a, b in zip(ra["rects"], rb["rects"]):
                    if a.on is not True and b.on is not True:
                        m.add(a.on == b.on)
                    for u, v in ((a.x0, b.x0), (a.y0, b.y0), (a.wx, b.wx), (a.hy, b.hy)):
                        _when(m, u == v, a.on, b.on)

    # The house's habitable rooms near what its EPCs say (soft).
    if house.epc_rooms:
        here = [r["pres"] for lay in layouts for r in lay["rooms"] if r["kind"] in RULES["habitable"]]
        if here:
            count = sum(1 if p is True else p for p in here)
            miss = m.new_int_var(0, 40, "")
            m.add(miss >= count - house.epc_rooms)
            m.add(miss >= house.epc_rooms - count)
            cost.append(wt["epc_rooms"] * miss)

    # Across storeys: windows stacked, the bathroom over the kitchen.
    for lvl in range(1, levels):
        below, here = layouts[lvl - 1]["alive"], layouts[lvl]["alive"]
        for col, a in here.items():
            if col in below:
                d = m.new_bool_var("")
                m.add(d >= a - below[col])
                m.add(d >= below[col] - a)
                cost.append((wt.get("window_stack_ground", wt["window_stack"]) if lvl == 1
                             else wt["window_stack"]) * d)
        baths = [r for r in layouts[lvl]["rooms"] if r["kind"] == "bathroom"]
        kitchens = [r for r in layouts[lvl - 1]["rooms"] if r["kind"] in ("kitchen", "kitchen_diner", "utility")]
        for b in baths:
            over = []
            for kroom in kitchens:
                a, c = b["rects"][0], kroom["rects"][0]
                o = m.new_bool_var("")
                for cond in (a.x0 <= c.x1, c.x0 <= a.x1, a.y0 <= c.y1, c.y0 <= a.y1):
                    m.add(cond).only_enforce_if(o)
                for lit in _lits(a.on, c.on):
                    m.add_implication(o, lit)
                over.append(o)
            if over:
                any_over = m.new_bool_var("")
                m.add_bool_or(over).only_enforce_if(any_over)
                cost.append(-wt["bath_over_kitchen"] * any_over)

    m.minimize(sum(cost))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = workers
    if REL_GAP:
        solver.parameters.relative_gap_limit = REL_GAP
    if PATIENCE:
        status = _solve_patiently(solver, m, PATIENCE)
    else:
        status = solver.solve(m)
    LAST_OBJECTIVE[0] = solver.objective_value if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.UNKNOWN:
            TIMED_OUT[0] = True     # out of time, not proven impossible
        return None

    v = solver.value
    out = []
    stair_sq = []
    st = None
    if stairs:
        sx, sy, vert = (v(stairs[0]), v(stairs[1]), v(stairs[2]))
        stair_sq = [(sx + i * (1 - vert), sy + i * vert) for i in range(STAIR_RUN)]
        st = (sx, sy, "N" if vert else "W")
    for lvl, lay in enumerate(layouts):
        grid = [[0] * W for _ in range(H)]
        rooms = []
        here = [i for i, r in enumerate(lay["rooms"])
                if r["pres"] is True or solver.boolean_value(r["pres"])]
        number = {i: n for n, i in enumerate(here)}
        for i in here:
            r = lay["rooms"][i]
            rects = []
            for rect in r["rects"]:
                if rect.on is not True and not solver.boolean_value(rect.on):
                    continue
                x0, y0 = v(rect.x0), v(rect.y0)
                x1, y1 = v(rect.x1), v(rect.y1)
                rects.append((x0, y0, x1, y1))
                for y in range(y0, y1 + 1):
                    for x in range(x0, x1 + 1):
                        grid[y][x] = number[i] + 1
            squares = {(x, y) for (x0, y0, x1, y1) in rects
                       for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)}
            if r["kind"] in ROOT_KINDS:
                for (x, y) in stair_sq:
                    grid[y][x] = number[i] + 1
                squares |= set(stair_sq)
            parent = None
            for j, s in lay["parents"].get(i, []):
                if solver.boolean_value(s):
                    parent = number[j]
            rooms.append({"kind": r["kind"], "unit": r["spec"].get("unit", 0),
                          "build": (kd or KINDS)[r["kind"]]["build"],
                          "rects": rects, "squares": squares, "parent": parent,
                          "spec": r["spec"]})
        # the window spots the solver gave each room (its own, already in the room)
        owned = [(number[i] + 1, lay["cols"][wi]) for (i, wi), o in lay["win"].items()
                 if i in number and solver.boolean_value(o)]
        out.append({"rooms": rooms, "grid": grid, "cols": lay["cols"], "owned": owned,
                    "doors": [], "windows": []})
    return out, st


# ---- doors and windows from the solved rooms ---------------------------------

def _edge(x, y, side):
    """Build's wall edge for square (x, y)'s edge on side."""
    return {"N": (x, y, "N"), "W": (x, y, "W"), "S": (x, y + 1, "N"), "E": (x + 1, y, "W")}[side]


# ---- blocks of flats: two stages --------------------------------------------

ZONE_TRIES = 3          # stage 1 zonings tried before a flat a floor fewer
SHARED_HALL_M2 = 20     # a block's shared hall or landing: passage at most this (m2)
# a flat's zone at least this share of its floor's fair share (the hall and
# stores take the rest): the zoning attempts in turn, strict first
ZONE_SHARE = (0.85, 0.85, 0.6)


def flats_per_floor(house: House) -> int:
    """How many flats a floor: its homes over its storeys, at most
    rules.flats_per_floor_max, no flat under rules.flat_min_m2."""
    levels = len(house.masks)
    homes = house.homes or levels
    n = max(1, min(RULES["flats_per_floor_max"], -(-homes // levels)))
    least = min(sum(v for row in mk for v in row) for mk in house.masks)
    while n > 1 and (least - 9) / n < RULES["flat_min_m2"]:
        n -= 1
    return n


def _zone_variant(house: House, n: int, share: float = None) -> list:
    """Stage 1: each floor's shared hall (or landing) and n flat zones,
    stacked where the floors have the same outline."""
    levels = len(house.masks)
    out = []
    for lvl, mk in enumerate(house.masks):
        area = sum(v for row in mk for v in row) - (STAIR_RUN if levels > 1 else 0) - 4
        # a smaller floor (the top, under the roof) takes fewer flats
        n_here = max(1, min(n, area // RULES["flat_split_m2"]))
        t = max(RULES["flat_min_m2"], area // n_here)
        # the shared hall may be a corridor to the street door (the stairs can
        # rise from the back): up to SHARED_HALL_M2 of passage, still priced
        floor = [{"kind": "hall" if lvl == 0 else "landing", "stack": True, "area": [0, SHARED_HALL_M2],
                  **({"front": 1} if lvl == 0 else {})}]
        for i in range(n_here):
            floor.append({"kind": "flat_zone", "unit": lvl * n + i + 1, "target": t, "outside": 3,
                          "area": [max(RULES["flat_min_m2"], int(t * (share or ZONE_SHARE[0]))), int(t * 1.5) + 2]})
        # communal stores take the corners no flat can use (priced per m2)
        floor += [{"kind": "store", "optional": True, "value": 0}, {"kind": "store", "optional": True, "value": 0}]
        out.append(floor)
    return out


def _zone_house(house: House, lvl: int, squares: set, entry) -> House:
    """A flat's zone as a house of its own: its walls onto the stairwell or
    the next flat are party walls (no windows), its front door's square fixed."""
    W, H = house.width, house.height
    mask = [[(x, y) in squares for x in range(W)] for y in range(H)]
    party = set()
    for (x, y) in squares:
        for side in "NSEW":
            dx, dy = STEP[side]
            if (x + dx, y + dy) in squares:
                continue
            if not house.outside_edge(lvl, x, y, side):
                party.add((x, y, side))
    return House(W, H, [mask], house.street, party, None, None, None, entry, True)


def solve_flats(house: House, seconds: float = 3.0, workers: int = 4, seed: int = 0):
    """A block of flats in two stages: the floors' shared hall, stairs and a
    zone a flat (stage 1), then each zone as a flat (stage 2, flat_unit; a zone
    the same as one solved already is not solved again). Fewer flats a floor
    when they do not fit; None when not even one does."""
    start = time.time()
    if not all(_one_piece(mk) for mk in house.masks):
        return None
    if any(sum(v for row in mk for v in row) > 2 * MAX_FLOOR_M2 for mk in house.masks):
        return None
    for n in range(flats_per_floor(house), 0, -1):
        # a zone can come out a shape no flat fits: zone the floors again,
        # nudged and less strictly (ZONE_SHARE), before taking a flat a floor away
        for attempt in range(ZONE_TRIES):
            variant = _zone_variant(house, n, ZONE_SHARE[min(attempt, len(ZONE_SHARE) - 1)])
            got = None
            for slack in SLACK:
                got = _solve_variant(house, variant, seconds + 2, workers, slack, seed * 7 + attempt)
                if got:
                    break
            if not got:
                continue            # no zoning this strict: the next attempt is less so
            storeys, stairs = got
            block = Layout(house, "flats_block", n, storeys, stairs, 0.0)
            _place_openings(block)
            flats = _lay_flats(block, seconds, workers, seed)
            if flats is not None:
                flats.seconds = time.time() - start
                return flats
    return None


def _lay_flats(block: Layout, seconds, workers, seed):
    house = block.house
    done = {}
    out_storeys = []
    for lvl, st in enumerate(block.storeys):
        rooms, doors = [], []
        number = {}
        # the shared rooms first: the hall or landing (with the stairs)
        for i, r in enumerate(st["rooms"]):
            if r["kind"] != "flat_zone":
                number[i] = len(rooms)
                rooms.append(dict(r, unit=0, parent=None if r["parent"] is None else number.get(r["parent"])))
        windows = [w for w in st["windows"]
                   if st["grid"][_inside_of(w, st["grid"])[1]][_inside_of(w, st["grid"])[0]]
                   and st["rooms"][st["grid"][_inside_of(w, st["grid"])[1]][_inside_of(w, st["grid"])[0]] - 1][
                       "kind"] != "flat_zone"]
        grid = [[0] * house.width for _ in range(house.height)]
        for i, r in enumerate(st["rooms"]):
            if r["kind"] != "flat_zone":
                for (x, y) in r["squares"]:
                    grid[y][x] = number[i] + 1
        for d in st["doors"]:
            a, b = _door_squares(d)
            ra, rb = (_room_at(st["grid"], *a), _room_at(st["grid"], *b))
            kinds = {st["rooms"][q - 1]["kind"] for q in (ra, rb) if q}
            if "flat_zone" not in kinds or len(kinds) == 1:
                doors.append(d)             # the shared rooms' own doors (the street door)
        for i, r in enumerate(st["rooms"]):
            if r["kind"] != "flat_zone":
                continue
            # its front door: the door from the hall or landing into it
            entry, front = None, None
            for d in st["doors"]:
                a, b = _door_squares(d)
                if a in r["squares"] and b not in r["squares"]:
                    entry, front = a, d
                elif b in r["squares"] and a not in r["squares"]:
                    entry, front = b, d
            if entry is None:
                return None
            zone = _zone_house(house, lvl, r["squares"], entry)
            key = house_key(zone, "flat_unit")
            if key not in done:
                done[key] = solve(zone, "flat_unit", seconds, workers, seed)
            flat = done[key]
            if flat is None:
                return None
            unit = r.get("unit") or r["spec"].get("unit", 0)
            base = len(rooms)
            for fr in flat.storeys[0]["rooms"]:
                parent = fr["parent"]
                rooms.append(dict(fr, unit=unit,
                                  parent=(base + parent) if parent is not None else number.get(r["parent"])))
            for y, row in enumerate(flat.storeys[0]["grid"]):
                for x, v in enumerate(row):
                    if v:
                        grid[y][x] = base + v
            doors += [front] + list(flat.storeys[0]["doors"])
            windows += list(flat.storeys[0]["windows"])
        out_storeys.append({"rooms": rooms, "grid": grid, "cols": [], "doors": doors, "windows": windows})
    return Layout(house, "flats_block", block.variant, out_storeys, block.stairs, 0.0,
                  block.front_door, block.back_door)


def _door_squares(edge):
    x, y, d = edge
    return ((x - 1, y), (x, y)) if d == "W" else ((x, y - 1), (x, y))


def _room_at(grid, x, y):
    if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
        return grid[y][x]
    return 0


def _inside_of(edge, grid):
    """The square of a window edge that is in the building."""
    a, b = _door_squares(edge)
    return a if _room_at(grid, *a) else b


def _place_openings(lay: Layout):
    house = lay.house
    # the programme's own kinds (a studio's open-plan room may have a small window)
    kd = programme_tables(lay.programme)[2] if is_programme(lay.programme) and         lay.programme != "flats_block" else KINDS
    stair = set()
    walk_stair = {}
    if lay.stairs:
        x, y, d = lay.stairs
        dx, dy = (0, 1) if d == "N" else (1, 0)
        stair = [(x + dx * i, y + dy * i) for i in range(STAIR_RUN)]
    levels = len(lay.storeys)
    for lvl, st in enumerate(lay.storeys):
        grid, rooms = st["grid"], st["rooms"]
        blocked = set(stair)
        if stair:
            if lvl < levels - 1:
                blocked.discard(stair[-1])
            if lvl > 0:
                blocked.discard(stair[0])
        walk_stair[lvl] = blocked

        def room_at(x, y):
            if 0 <= x < house.width and 0 <= y < house.height:
                return grid[y][x]
            return 0

        # windows: the spots the solver gave each room
        per_room = {}
        for r, spot in st.get("owned", []):
            per_room.setdefault(r, []).append(tuple(spot))
        for r, spots in per_room.items():
            rooms[r - 1]["windows"] = spots
            st["windows"] += [_edge(*sp) for sp in spots]
        window_squares = {(x, y) for r in per_room.values() for (x, y, _) in r}

        # inside doors: across the middle of each room's wall with its parent
        for i, room in enumerate(rooms):
            p = room["parent"]
            if p is None:
                continue
            pairs = []
            for (x, y) in sorted(room["squares"]):
                if (x, y) in blocked:
                    continue
                for side in "NSEW":
                    dx, dy = STEP[side]
                    q = (x + dx, y + dy)
                    if room_at(*q) == p + 1 and q not in blocked:
                        pairs.append(_edge(x, y, side))
            if pairs:
                st["doors"].append(pairs[len(pairs) // 2])

        if lvl == 0 and not house.inner:
            # the stair hall behind a shop with no homes has no street door
            entries = [r for r in rooms if r["spec"].get("root", True) is not False]
            lay.front_door = _outside_door(house, lvl, entries, house.street, ROOT_KINDS + ("living",),
                                           set(stair), window_squares,
                                           near=stair[-1] if stair else None)
            if lay.front_door is None:
                # the hall's only front square is a window: the door wins
                lay.front_door = _outside_door(house, lvl, entries, house.street, ROOT_KINDS + ("living",),
                                               set(stair), set())
                if lay.front_door in st["windows"]:
                    st["windows"].remove(lay.front_door)
                    for room in rooms:
                        room["windows"] = [w for w in room.get("windows", [])
                                           if _edge(*w) != lay.front_door]
            if lay.front_door:
                st["doors"].append(lay.front_door)
            # a shop (each bar of a pub): its own door in the middle of its
            # frontage, the frontage glass
            business = []
            # the street wall, else (all party wall) the walls at right angles (_wall_of)
            faces = [house.street] + [sd for sd in ("E", "W", "N", "S") if sd not in (house.street, OPPOSITE[house.street])
                                      and not _segments(house, lvl, house.street)]
            for room in rooms:
                if not kd[room["kind"]].get("frontage"):
                    continue
                face, spots = next(((sd, s) for sd in faces
                                    if (s := [(x, y) for (x, y) in sorted(room["squares"])
                                              if house.outside_edge(lvl, x, y, sd)])), (None, []))
                if not spots:
                    continue
                front = [_edge(x, y, face) for (x, y) in spots]
                door = front[len(front) // 2]
                st["doors"].append(door)
                business.append(door)
                st["shop_front"] = st.get("shop_front", []) + front
                st["windows"] = [w for w in st["windows"] if w not in front] + \
                    [e for e in front if e != door]
                room["windows"] = [w for w in room.get("windows", []) if _edge(*w) not in front]
            # a surgery's waiting room: a door from the street in an ordinary wall
            for room in rooms:
                if not kd[room["kind"]].get("street_door"):
                    continue
                door = (_outside_door(house, lvl, [room], house.street, (room["kind"],), blocked, window_squares)
                        or _outside_door(house, lvl, [room], house.street, (room["kind"],), blocked, set()))
                if door:
                    st["doors"].append(door)
                    business.append(door)
                    st["windows"] = [w for w in st["windows"] if w != door]
                    room["windows"] = [w for w in room.get("windows", []) if _edge(*w) != door]
            if lay.front_door is None and business:
                lay.front_door = business[0]        # a business with no homes: its own door
            lay.back_door = _outside_door(house, lvl, rooms, OPPOSITE[house.street],
                                          ("kitchen", "kitchen_diner", "kitchen_breakfast", "utility",
                                           "scullery", "cellar", "stockroom", "shop_kitchen", "back_office",
                                           "family_room", "hall", "shop_floor"),
                                          blocked, window_squares)
            if lay.back_door:
                st["doors"].append(lay.back_door)


def _outside_door(house, lvl, rooms, side, kinds, blocked, windows, near=None):
    if not _segments(house, lvl, side):
        # all party wall that way: the walls at right angles (_wall_of)
        for sd in (("E", "W") if side in ("N", "S") else ("N", "S")):
            got = _outside_door(house, lvl, rooms, sd, kinds, blocked, windows, near)                 if _segments(house, lvl, sd) else None
            if got:
                return got
        return None
    for kind in kinds:
        for room in rooms:
            if room["kind"] != kind:
                continue
            spots = [(x, y) for (x, y) in sorted(room["squares"])
                     if house.outside_edge(lvl, x, y, side)
                     and (x, y) not in blocked and (x, y) not in windows]
            if not spots:
                continue
            if near:
                spots.sort(key=lambda s: abs(s[0] - near[0]) + abs(s[1] - near[1]))
                x, y = spots[0]
            else:
                x, y = spots[len(spots) // 2]
            return _edge(x, y, side)
    return None


# ---- the cache: layouts kept by footprint, with variety -----------------------
#
# Most houses on a map share their footprint with others (Alton: 2,784 houses,
# 1,401 footprints; 1,689 plain rectangles in 337 sizes), so a house is solved
# once for its footprint, street side, party walls and programme, a few ways
# (VARIETY), and kept on disk. A house takes one of its footprint's layouts by
# its own id, so a terrace of the same house is not all one plan. A layout
# mirrored along the street fits the mirror-image house (a semi's pair), when
# its stairs still climb a way the game has (N or W).

VARIETY = 2                 # layouts solved per footprint (its mirror image's add more)
CACHE_VERSION = 3           # bump when the solver changes what it makes


_PROG_HASH = {}
# the rules a layout depends on (the rest only choose a programme)
LAYOUT_RULES = ("behind", "behind_wanted", "larger", "no_door", "prefer_from", "pitch_front", "pitch_side",
                "habitable", "bedrooms_upstairs_from", "bedroom_kinds")
BLOCK_RULES = ("flat_min_m2", "flats_per_floor_max", "flat_split_m2")


def _rules_for(keys) -> dict:
    return {k: RULES.get(k) for k in keys}


def programme_hash(name: str) -> str:
    """What a programme's layouts depend on: its variants, weights and the
    kinds it names, the rules and the solver's version. Editing one kind re-solves only the programmes using it."""
    if name == "flats_block" and name not in _PROG_HASH:
        _PROG_HASH[name] = hashlib.sha1(json.dumps(
            [CACHE_VERSION, programme_hash("flat_unit"), KINDS["flat_zone"], KINDS["hall"], KINDS["landing"],
             _rules_for(LAYOUT_RULES + BLOCK_RULES), WEIGHTS, ZONE_TRIES, SHARED_HALL_M2, ZONE_SHARE], sort_keys=True).encode()).hexdigest()[:12]
    if name not in _PROG_HASH:
        variants, wt, kd = programme_tables(name)
        # the kinds it names (their from lists are in them): a kind it never
        # has cannot change its layouts
        used = {r["kind"] for v in variants for st in v for r in st} | set(ROOT_KINDS) | {"garage"}
        text = json.dumps([CACHE_VERSION, variants, wt, {k: kd[k] for k in sorted(used) if k in kd},
                           _rules_for(LAYOUT_RULES)], sort_keys=True)
        _PROG_HASH[name] = hashlib.sha1(text.encode()).hexdigest()[:12]
    return _PROG_HASH[name]


def house_key(house: House, programme: str) -> str:
    masks = ["/".join("".join("1" if v else "0" for v in row) for row in m) for m in house.masks]
    text = json.dumps([programme, programme_hash(programme), house.width, house.height, masks,
                       house.street, sorted(house.party), house.garage, house.epc_rooms,
                       house.homes, house.entry, house.inner])
    return hashlib.sha1(text.encode()).hexdigest()[:20]


def _flips_x(house: House) -> bool:
    """A mirror along the street flips x for a street N or S, else y."""
    return house.street in ("N", "S")


SWAP_X = {"E": "W", "W": "E"}
SWAP_Y = {"N": "S", "S": "N"}


def mirror_house(house: House) -> House:
    W, H = house.width, house.height
    g = house.garage
    if _flips_x(house):
        masks = [[list(row[::-1]) for row in m] for m in house.masks]
        party = {(W - 1 - x, y, SWAP_X.get(s, s)) for (x, y, s) in house.party}
        g = g and (W - 1 - g[2], g[1], W - 1 - g[0], g[3])
    else:
        masks = [[list(row) for row in m[::-1]] for m in house.masks]
        party = {(x, H - 1 - y, SWAP_Y.get(s, s)) for (x, y, s) in house.party}
        g = g and (g[0], H - 1 - g[3], g[2], H - 1 - g[1])
    return House(W, H, masks, house.street, party, tuple(g) if g else None, house.epc_rooms,
                 house.homes, None, house.inner)


def mirror(lay: Layout, house: House) -> Layout | None:
    """lay (solved for house's mirror image) mirrored onto house; None when its
    stairs would climb a way the game has no stairs for."""
    W, H = house.width, house.height
    fx = _flips_x(house)
    stairs = None
    if lay.stairs:
        x, y, d = lay.stairs
        # a flight along the flip would come out climbing E or S: no such stairs
        if (fx and d == "W") or (not fx and d == "N"):
            return None
        stairs = (W - 1 - x, y, d) if fx else (x, H - 1 - y, d)

    def sq(p):
        return (W - 1 - p[0], p[1]) if fx else (p[0], H - 1 - p[1])

    def edge(e):
        x, y, d = e
        if fx:
            return (W - x, y, "W") if d == "W" else (W - 1 - x, y, "N")
        return (x, H - 1 - y, "W") if d == "W" else (x, H - y, "N")

    def rect(r):
        x0, y0, x1, y1 = r
        return (W - 1 - x1, y0, W - 1 - x0, y1) if fx else (x0, H - 1 - y1, x1, H - 1 - y0)

    def spot(w):
        x, y, s = w
        return (*sq((x, y)), (SWAP_X if fx else SWAP_Y).get(s, s))

    storeys = []
    for st in lay.storeys:
        grid = [list(row[::-1]) for row in st["grid"]] if fx else [list(r) for r in st["grid"][::-1]]
        rooms = [dict(r, rects=[rect(t) for t in r["rects"]], squares={sq(p) for p in r["squares"]},
                      windows=[spot(w) for w in r.get("windows", [])])
                 for r in st["rooms"]]
        storeys.append({"rooms": rooms, "grid": grid, "cols": [],
                        "doors": [edge(e) for e in st["doors"]],
                        "windows": [edge(e) for e in st["windows"]],
                        "shop_front": [edge(e) for e in st.get("shop_front", [])]})
    return Layout(house, lay.programme, lay.variant, storeys, stairs, lay.seconds,
                  lay.front_door and edge(lay.front_door), lay.back_door and edge(lay.back_door))


def _to_json(lay: Layout) -> dict:
    return {"programme": lay.programme, "variant": lay.variant, "seconds": round(lay.seconds, 2),
            "stairs": lay.stairs, "front_door": lay.front_door, "back_door": lay.back_door,
            "storeys": [{"grid": st["grid"], "doors": st["doors"], "windows": st["windows"],
                         "shop_front": st.get("shop_front", []),
                         "rooms": [{"kind": r["kind"], "unit": r.get("unit", 0), "build": r["build"], "rects": r["rects"],
                                    "parent": r["parent"], "windows": r.get("windows", []),
                                    "spec": r["spec"]} for r in st["rooms"]]}
                        for st in lay.storeys]}


def _tup(v):
    return tuple(v) if v else None


def _from_json(d: dict, house: House) -> Layout:
    storeys = []
    for st in d["storeys"]:
        rooms = []
        for i, r in enumerate(st["rooms"]):
            squares = {(x, y) for y, row in enumerate(st["grid"]) for x, v in enumerate(row) if v == i + 1}
            rooms.append({"kind": r["kind"], "unit": r.get("unit", 0), "build": r["build"],
                          "rects": [tuple(t) for t in r["rects"]],
                          "squares": squares, "parent": r["parent"], "spec": r["spec"],
                          "windows": [tuple(w) for w in r["windows"]]})
        storeys.append({"rooms": rooms, "grid": st["grid"], "cols": [],
                        "doors": [tuple(e) for e in st["doors"]],
                        "windows": [tuple(e) for e in st["windows"]],
                        "shop_front": [tuple(e) for e in st.get("shop_front", [])]})
    return Layout(house, d["programme"], d["variant"], storeys, _tup(d["stairs"]), d["seconds"],
                  _tup(d["front_door"]), _tup(d["back_door"]))


def solve_varied(house: House, programme: str, n: int = VARIETY, seconds: float = 3.0,
                 workers: int = 4) -> list:
    """Up to n different layouts of one house (seed 0 is solve()'s own).
    TIMED_OUT[0] says afterwards whether a solve ran out of time: then an
    empty answer is not "no layout" (it is not cached as one)."""
    TIMED_OUT[0] = False
    out, seen = [], set()
    for seed in range(n + 1):
        lay = solve(house, programme, seconds, workers, seed)
        if lay is None:
            break           # no layout at all: another seed will not find one
        sig = json.dumps([st["grid"] for st in lay.storeys])
        if sig not in seen:
            seen.add(sig)
            out.append(lay)
        if len(out) >= n:
            break
    return out


class LayoutCache:
    """Layouts by house_key, on disk as JSON. The key holds its programme's
    hash, so a change to the tables or the solver leaves the old entries
    unused (`prune` drops them) and re-solves only what it touched."""

    def __init__(self, folder: str | None = None):
        self.folder = folder or os.path.join(HERE, "..", "cache", "room_solver")
        self.path = os.path.join(self.folder, "layouts.json")
        self.data = {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        self.dirty = False

    def options(self, house: House, programme: str) -> list:
        """Every cached layout that fits house: its own, and its mirror image's mirrored."""
        own = [_from_json(d, house) for d in self._layouts(house_key(house, programme))]
        twin = mirror_house(house)
        flipped = [mirror(_from_json(d, twin), house)
                   for d in self._layouts(house_key(twin, programme))]
        return own + [m for m in flipped if m is not None]

    def known(self, house: House, programme: str) -> bool:
        """Whether this footprint has been solved (layouts or none), or its
        mirror image has layouts that mirror onto it (stairs the game has)."""
        return house_key(house, programme) in self.data or bool(self.options(house, programme))

    def _layouts(self, key: str) -> list:
        return self.data.get(key, {}).get("layouts", [])

    def put(self, house: House, programme: str, lays: list) -> None:
        self.store(house_key(house, programme), programme, [_to_json(lay) for lay in lays])

    def store(self, key: str, programme: str, lays: list) -> None:
        self.data[key] = {"programme": programme, "hash": programme_hash(programme), "layouts": lays}
        self.dirty = True

    def prune(self) -> int:
        """Drop entries an older version of their programme made."""
        stale = [k for k, v in self.data.items()
                 if not is_programme(v.get("programme")) or v.get("hash") != programme_hash(v["programme"])]
        for k in stale:
            del self.data[k]
        self.dirty = self.dirty or bool(stale)
        return len(stale)

    def save(self, tries: int = 10) -> None:
        """Write the cache, merged with what is on disk now (another Build run
        may have saved since this one read it), through a file of this
        process's own; a moment's lock on Windows is waited out."""
        if not self.dirty:
            return
        os.makedirs(self.folder, exist_ok=True)
        tmp = f"{self.path}.{os.getpid()}.tmp"
        for i in range(tries):
            try:
                if os.path.exists(self.path):
                    with open(self.path, encoding="utf-8") as f:
                        disk = json.load(f)
                    disk.update(self.data)
                    self.data = disk
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, separators=(",", ":"))
                os.replace(tmp, self.path)
                self.dirty = False
                return
            except (OSError, ValueError):
                if i == tries - 1:
                    raise
                time.sleep(0.5 * (i + 1))


def pick(options: list, building_id) -> Layout:
    """One of a footprint's layouts, the same one for a building every run."""
    h = int(hashlib.sha1(str(building_id).encode()).hexdigest(), 16)
    return options[h % len(options)]


def layout_for(house: House, programme: str, building_id, cache: LayoutCache,
               seconds: float = 3.0, workers: int = 4, solve_missing: bool = True) -> Layout | None:
    """A layout for this house from the cache, solving its footprint first when
    the cache has none - unless solve_missing is False (Build's workers after
    prepare, which has tried every footprint: what it could not solve keeps
    Build's own layout, the same every run)."""
    options = cache.options(house, programme)
    if not options:
        if cache.known(house, programme) or not solve_missing:
            return None         # solved before: no layout fits (Build's own layout)
        lays = solve_varied(house, programme, seconds=seconds, workers=workers)
        if not lays:
            if not TIMED_OUT[0]:
                cache.put(house, programme, lays)      # proven: no layout
            return None
        cache.put(house, programme, lays)
        options = cache.options(house, programme)
    return pick(options, building_id)


def _prewarm_one(job):
    """Solve one footprint. None in place of the layouts: nothing to store
    (it ran out of time, or the solver failed - that house keeps Build's own)."""
    house, programme, seconds, workers, n = job
    t = time.time()
    try:
        lays = solve_varied(house, programme, n=n, seconds=seconds, workers=workers)
    except Exception:  # noqa: BLE001 - one house is not worth the Build run
        return house_key(house, programme), programme, None, time.time() - t
    if not lays and TIMED_OUT[0]:
        return house_key(house, programme), programme, None, time.time() - t
    return house_key(house, programme), programme, [_to_json(x) for x in lays], time.time() - t


def prewarm(jobs, cache: LayoutCache, processes: int = 2, seconds: float = 3.0,
            workers: int = 4, progress=None) -> dict:
    """Solve every footprint in jobs [(house, programme)] the cache lacks, in
    parallel. First each footprint once, a mirror image left to its twin; then
    any house whose twin's layouts do not mirror onto it (stairs that would
    climb a way the game has none) is solved itself. A solve that ran out of
    time or failed stores nothing: the next run tries it again."""
    from collections import Counter
    from multiprocessing import Pool
    # a footprint only one house has needs one layout; variety is for repeats
    uses = Counter()
    for house, programme in jobs:
        k, tk = house_key(house, programme), house_key(mirror_house(house), programme)
        uses[min(k, tk)] += 1
    start = time.time()
    got = {"solved": 0, "no_layout": 0, "not_stored": 0, "solve_seconds": 0.0}

    def run(todo):
        if not todo:
            return
        with Pool(processes) as pool:
            for i, (k, prog, lays, took) in enumerate(pool.imap_unordered(_prewarm_one, todo)):
                got["solved"] += 1
                got["solve_seconds"] += took
                if lays is None:
                    got["not_stored"] += 1
                else:
                    cache.store(k, prog, lays)
                    got["no_layout"] += not lays
                if progress and (i + 1) % 25 == 0:
                    progress(i + 1, len(todo), time.time() - start)
                    cache.save()
        cache.save()

    todo, keys = [], set()
    for house, programme in jobs:
        k = house_key(house, programme)
        tk = house_key(mirror_house(house), programme)
        if k in keys or tk in keys or cache.known(house, programme):
            continue
        keys.add(k)
        todo.append((house, programme, seconds, workers, VARIETY if uses[min(k, tk)] > 1 else 1))
    run(todo)
    again, keys = [], set()
    for house, programme in jobs:
        k = house_key(house, programme)
        if k not in keys and not cache.known(house, programme):
            keys.add(k)
            again.append((house, programme, seconds, workers, 1))
    run(again)
    got["solve_seconds"] = round(got["solve_seconds"], 1)
    return dict(got, jobs=len(jobs), seconds=round(time.time() - start, 1))


# ---- into Build ---------------------------------------------------------------

def to_building(lay: Layout, seed: int = 0, profile=None, party: dict | None = None,
                uses: list | None = None, converted: str | None = None, homes: bool = False):
    """The layout as Build's own Building: its rooms, doors and windows as
    solved, then Build's furnishing and walkways, as designer.stack does for
    a hand-drawn plan. converted: a house's layout for an office, surgery or
    guest house (conversion), its rooms renamed by that class - only the
    ground floor's when homes are over it."""
    import random
    from . import layout as L
    house = lay.house
    block = lay.programme == "flats_block"
    kd = KINDS if block else programme_tables(lay.programme)[2]
    shop = any(kd[r["kind"]].get("frontage") or kd[r["kind"]].get("street_door")
               for r in lay.storeys[0]["rooms"])
    use = shop_use_of(uses) if shop or converted else None
    conv = SHOPS["converted"]
    storeys = []
    for lvl, st in enumerate(lay.storeys):
        rooms = []
        # (with homes on its one storey a house stays a home: someone working from it)
        renamed = converted and (not homes or converted in conv["all_floors"]
                                 or (lvl == 0 and len(lay.storeys) > 1))
        for room in st["rooms"]:
            xs = [x for x, _ in room["squares"]]
            ys = [y for _, y in room["squares"]]
            # named after the business's own use (the pizza place's kitchen),
            # where the room's kind or the programme says so; in a converted
            # house, by its class's table (the front room the office's reception)
            which = room.get("spec", {}).get("use", kd[room["kind"]].get("use"))
            if renamed:
                which = conv["rename"][converted].get(room["kind"])
                if which in ("front", "back"):
                    kind = use[0 if which == "front" else 1] if use else room["build"]
                else:
                    kind = which or room["build"]
            else:
                kind = use[0 if which == "front" else 1] if use and which else room["build"]
            # a shop's lobby and stair hall: nothing standing in them (_furnish)
            rooms.append(L.Room(min(xs), min(ys), max(xs), max(ys), kind=kind, fixed=True,
                                unit=room.get("unit", 0),
                                is_core=shop and lvl == 0 and room["kind"] in ROOT_KINDS))
        # a wall is a party wall on this storey where the neighbour is as tall
        # (Build's party: {edge: the neighbour's storeys}), else every storey
        walls = ({e for e, n in party.items() if n > lvl} if party is not None
                 else {_edge(*e) for e in house.party})
        plan = L.Plan(width=house.width, height=house.height, rooms=rooms,
                      grid=[row[:] for row in st["grid"]], drawn=True, profile=profile,
                      mask=[row[:] for row in house.masks[lvl]], party=walls)
        plan.doors = list(st["doors"])
        plan.windows = list(st["windows"])
        if block:
            plan.kind = "apartment"
        if shop:
            # a floor of homes over the business is a flat's; its store rooms are the shop's
            home = any(kd[r["kind"]]["build"] in HOME_BUILDS for r in st["rooms"])
            plan.kind = "shop" if lvl == 0 or not home else "apartment"
            plan.shop_front = set(st.get("shop_front", ())) if lvl == 0 else set()
        elif renamed and converted != "guest":
            plan.kind = "shop"          # furnished as a business (an office's desks, a public WC)
        storeys.append(plan)
    building = L.Building(width=house.width, height=house.height, storeys=storeys, profile=profile)
    for lvl, plan in enumerate(storeys):
        L._furnish(plan, random.Random(seed + 977 * lvl), lay.stairs, house.street)
    pubs = _pubs() if lay.programme.endswith("@pub") else None
    if pubs:
        for plan in storeys:
            pubs.fit_bars(plan, house.street)       # the counter, the back bar, the tables
    if lay.stairs:
        for lvl in range(len(storeys) - 1):
            building.stairs.append(lay.stairs)
            L._clear_for_stairs(storeys[lvl], *lay.stairs)
            L._clear_for_stairs(storeys[lvl + 1], *lay.stairs)
    L._clear_the_way(building)
    from . import interiors
    interiors.one_wood(building, random.Random(f"{seed}:wood"))
    return building


# ---- checks -------------------------------------------------------------------

def check(lay: Layout) -> list[str]:
    """Rule breaks in a solved layout (empty when it keeps them all)."""
    out = []
    levels = len(lay.storeys)
    for lvl, st in enumerate(lay.storeys):
        for i, room in enumerate(st["rooms"]):
            k = room["kind"]
            flat = lay.programme == "flats_block" and room.get("unit")
            if levels >= RULES["bedrooms_upstairs_from"] and lvl == 0 and k in RULES["bedroom_kinds"]                     and not flat:
                out.append(f"L{lvl} {k}: a bedroom downstairs")
            need = programme_tables("flat_unit")[2][k]["window"] if flat else KINDS[k]["window"]
            if need == "need" and not room.get("windows"):
                out.append(f"L{lvl} {k}: no window")
            if not _is_root(room["spec"]) and k != "garage" and room["parent"] is None:
                out.append(f"L{lvl} {k}: no door")
            if room["parent"] is not None:
                pk = st["rooms"][room["parent"]]["kind"]
                if [k, pk] in RULES["no_door"] or [pk, k] in RULES["no_door"]:
                    out.append(f"L{lvl} {k}: door from {pk}")
        if lay.stairs and 0 < lvl < levels - 1:
            x, y, d = lay.stairs
            dx, dy = (0, 1) if d == "N" else (1, 0)
            flight = [(x + dx * i, y + dy * i) for i in range(STAIR_RUN)]
            hall = st["grid"][flight[0][1]][flight[0][0]]
            open_sq = {(cx, cy) for cy, row in enumerate(st["grid"]) for cx, v in enumerate(row)
                       if v == hall} - set(flight[1:-1])
            seen, todo = set(), [flight[0]]
            while todo:
                q = todo.pop()
                if q in seen or q not in open_sq:
                    continue
                seen.add(q)
                todo += [(q[0] + 1, q[1]), (q[0] - 1, q[1]), (q[0], q[1] + 1), (q[0], q[1] - 1)]
            if flight[-1] not in seen:
                out.append(f"L{lvl}: the landing does not join the stairs up to the stairs down")
        cells = sum(1 for row in st["grid"] for c in row if c)
        need = sum(1 for row in lay.house.masks[lvl] for c in row if c)
        if cells != need:
            out.append(f"L{lvl}: {need - cells} squares in no room")
    if lay.front_door is None and not lay.house.inner:
        out.append("no front door")
    pubs = _pubs() if lay.programme.endswith("@pub") else None
    if pubs:
        out += pubs.check(lay)
    return out


# ---- pictures -----------------------------------------------------------------

COLOURS = {
    "hall": (222, 210, 180), "landing": (222, 210, 180), "living": (164, 196, 140),
    "through": (150, 190, 130), "dining": (196, 214, 150), "kitchen": (240, 196, 120),
    "kitchen_diner": (240, 186, 110), "utility": (220, 180, 140), "wc": (150, 200, 225),
    "bathroom": (130, 186, 222), "ensuite": (150, 200, 230), "bed_double": (196, 160, 210),
    "bed_single": (214, 186, 222), "box": (226, 200, 230), "airing": (190, 190, 190),
    "garage": (170, 170, 170), "drawing_room": (140, 184, 120), "sitting_room": (176, 204, 150),
    "family_room": (170, 200, 140), "library": (186, 160, 120), "breakfast_room": (214, 222, 150),
    "kitchen_breakfast": (240, 190, 115), "scullery": (226, 196, 150), "pantry": (200, 180, 150),
    "dressing": (206, 180, 214), "bed_master": (180, 140, 200), "cupboard": (196, 196, 196),
    "study": (160, 190, 200), "shop_floor": (240, 220, 120), "stockroom": (200, 184, 140),
    "shop_kitchen": (240, 176, 100), "back_office": (170, 196, 210), "strongroom": (150, 150, 150),
    "waiting": (230, 216, 170), "consult": (176, 210, 200), "store_room": (200, 184, 140),
    "break_room": (214, 200, 160), "bar_room": (196, 150, 110), "cellar": (160, 140, 120),
    "function_room": (206, 166, 126),
}
LABEL = {"bed_master": "main bed", "kitchen_breakfast": "kitchen", "drawing_room": "drawing rm",
         "sitting_room": "sitting rm", "family_room": "family rm", "breakfast_room": "breakfast",
         "cupboard": "cpd", "bed_double": "double", "bed_single": "single", "kitchen_diner": "kit-diner",
         "living": "front room", "dining": "dining", "shop_floor": "shop", "shop_kitchen": "kitchen",
         "back_office": "office", "store_room": "store", "break_room": "break rm", "bar_room": "bar",
         "function_room": "function rm"}


def render(lay: Layout, path: str, title: str = "", px: int = 28):
    from PIL import Image, ImageDraw
    house = lay.house
    W, H = house.width, house.height
    pad = 30
    fw, fh = W * px + 2 * pad, H * px + 2 * pad + 20
    img = Image.new("RGB", (fw * len(lay.storeys), fh + 24), (250, 250, 247))
    d = ImageDraw.Draw(img)
    d.text((6, 4), f"{title}  [{lay.programme} v{lay.variant}, {lay.seconds:.1f}s]", fill=(0, 0, 0))
    stair = []
    if lay.stairs:
        x, y, dd = lay.stairs
        dx, dy = (0, 1) if dd == "N" else (1, 0)
        stair = [(x + dx * i, y + dy * i) for i in range(STAIR_RUN)]
    for lvl, st in enumerate(lay.storeys):
        ox, oy = lvl * fw + pad, pad + 24
        grid = st["grid"]
        d.text((ox, oy - 16), ["Ground", "First", "Second", "Third"][lvl] + f"  (street {house.street})",
               fill=(60, 60, 60))

        def P(x, y):
            return ox + x * px, oy + y * px
        for y in range(H):
            for x in range(W):
                r = grid[y][x]
                if not r:
                    continue
                c = COLOURS.get(st["rooms"][r - 1]["kind"], (200, 200, 200))
                d.rectangle([*P(x, y), P(x + 1, y + 1)[0] - 1, P(x + 1, y + 1)[1] - 1], fill=c)
                d.rectangle([*P(x, y), P(x + 1, y + 1)[0] - 1, P(x + 1, y + 1)[1] - 1], outline=(0, 0, 0, 30))
        # stairs: hatched, arrow up the flight
        for i, (x, y) in enumerate(stair):
            x0, y0 = P(x, y)
            for t in range(0, px, 5):
                if lay.stairs[2] == "N":
                    d.line([x0 + 3, y0 + t, x0 + px - 3, y0 + t], fill=(120, 100, 70))
                else:
                    d.line([x0 + t, y0 + 3, x0 + t, y0 + px - 3], fill=(120, 100, 70))
        if stair:
            a, b = P(*stair[-1]), P(*stair[0])
            d.line([a[0] + px // 2, a[1] + px // 2, b[0] + px // 2, b[1] + px // 2], fill=(200, 0, 0), width=2)
            d.text((b[0] + 4, b[1] + 2), "UP" if lvl < len(lay.storeys) - 1 else "dn", fill=(200, 0, 0))
        # walls
        for y in range(H + 1):
            for x in range(W + 1):
                here = grid[y][x] if y < H and x < W else 0
                west = grid[y][x - 1] if 0 < x <= W and y < H else 0
                north = grid[y - 1][x] if 0 < y <= H and x < W else 0
                if y < H and here != west:
                    party = (x, y, "W") in house.party or (x - 1, y, "E") in house.party
                    d.line([*P(x, y), *P(x, y + 1)], fill=(170, 30, 30) if party else (20, 20, 20),
                           width=4 if (here == 0 or west == 0) else 2)
                if x < W and here != north:
                    party = (x, y, "N") in house.party or (x, y - 1, "S") in house.party
                    d.line([*P(x, y), *P(x + 1, y)], fill=(170, 30, 30) if party else (20, 20, 20),
                           width=4 if (here == 0 or north == 0) else 2)
        for (x, y, s) in st["windows"]:
            a = P(x, y)
            if s == "W":
                d.line([a[0], a[1] + 5, a[0], a[1] + px - 5], fill=(40, 170, 240), width=5)
            else:
                d.line([a[0] + 5, a[1], a[0] + px - 5, a[1]], fill=(40, 170, 240), width=5)
        for (x, y, s) in st["doors"]:
            a = P(x, y)
            if s == "W":
                d.line([a[0], a[1] + 4, a[0], a[1] + px - 4], fill=(250, 250, 247), width=5)
                d.line([a[0] - 3, a[1] + 4, a[0] + 3, a[1] + 4], fill=(140, 80, 30), width=2)
            else:
                d.line([a[0] + 4, a[1], a[0] + px - 4, a[1]], fill=(250, 250, 247), width=5)
                d.line([a[0] + 4, a[1] - 3, a[0] + 4, a[1] + 3], fill=(140, 80, 30), width=2)
        for room in st["rooms"]:
            if not room["rects"]:
                continue
            x0, y0, x1, y1 = max(room["rects"], key=lambda r: (r[2] - r[0] + 1) * (r[3] - r[1] + 1))
            cx, cy = P((x0 + x1 + 1) / 2, (y0 + y1 + 1) / 2)
            name = LABEL.get(room["kind"], room["kind"])
            if room.get("unit"):
                name = f"{room['unit']}: {name}"        # which flat
            area = len(room["squares"])
            d.text((cx - 3 * len(name), cy - 10), name, fill=(0, 0, 0))
            d.text((cx - 8, cy + 1), f"{area}m2", fill=(60, 60, 60))
    _save(img, path)


def _save(img, path: str, tries: int = 5) -> None:
    """Save through a temporary file: on Windows an open preview of the old
    picture can refuse the write for a moment."""
    path = os.path.normpath(path)
    tmp = path + ".tmp.png"
    img.save(tmp)
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            time.sleep(0.3 * (i + 1))
    os.replace(tmp, path)


# ---- demo ---------------------------------------------------------------------

def _box(w, h, cut=()):
    """A w x h mask with (x0, y0, x1, y1) rectangles cut out."""
    m = [[True] * w for _ in range(h)]
    for (x0, y0, x1, y1) in cut:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                m[y][x] = False
    return m


def _party(w, h, sides, mask=None):
    out = set()
    for side in sides:
        if side == "E":
            out |= {(w - 1, y, "E") for y in range(h)}
        if side == "W":
            out |= {(0, y, "W") for y in range(h)}
    return out


def demo_houses():
    """Made-up houses (street at the bottom of the page, "S")."""
    out = []
    # Victorian mid terrace, 5 x 9 main range + 3 x 4 back addition (north = back)
    w, h = 5, 13
    m = _box(w, h, [(3, 0, 4, 3)])
    out.append(("vic_mid_terrace", House(w, h, [m, m], "S",
                                         _party(w, h, "EW") - {(4, y, "E") for y in range(4)}),
                "terrace_victorian"))
    # inter-war semi 7 x 8, party wall east
    w, h = 7, 8
    m = _box(w, h)
    out.append(("iw_semi", House(w, h, [m, m], "S", _party(w, h, "E")), "semi_interwar"))
    # 1970s council terrace end 6 x 8
    w, h = 6, 8
    m = _box(w, h)
    out.append(("council_end", House(w, h, [m, m], "S", _party(w, h, "W")), "council"))
    # 1980s starter home, mid terrace 5 x 7
    w, h = 5, 7
    m = _box(w, h)
    out.append(("starter_mid", House(w, h, [m, m], "S", _party(w, h, "EW")), "starter_80s"))
    # detached 1980s, 10 x 8 with an integral garage 3 x 6 at the front west
    w, h = 10, 8
    m = _box(w, h)
    up = _box(w, h)
    out.append(("detached_garage", House(w, h, [m, up], "S", set(), garage=(0, 2, 2, 7)), "detached_80s"))
    # bungalow 11 x 8
    w, h = 11, 8
    m = _box(w, h)
    out.append(("bungalow", House(w, h, [m], "S"), "bungalow"))
    # L-shaped detached 9 x 9 with the back corner out
    w, h = 9, 9
    m = _box(w, h, [(6, 0, 8, 2)])
    out.append(("l_detached", House(w, h, [m, m], "S"), "detached_80s"))
    # semi with street to the north, party wall west
    w, h = 7, 8
    m = _box(w, h)
    out.append(("semi_north", House(w, h, [m, m], "N", _party(w, h, "W")), "semi_interwar"))
    # homes over shops (street to the south; party walls both sides, as on a High Street)
    w, h = 6, 12
    m = _box(w, h)
    out.append(("shop_home", House(w, h, [m, m], "S", _party(w, h, "EW")), "shop_house"))
    w, h = 7, 12
    m = _box(w, h)
    out.append(("shop_flats_3", House(w, h, [m, m, m], "S", _party(w, h, "EW")), "shop_flats"))
    w, h = 11, 10
    m = _box(w, h)
    out.append(("shop_two_flats", House(w, h, [m, m], "S", _party(w, h, "W")), "shop_flats2"))
    # businesses by class: no homes over them, or a home
    w, h = 6, 10
    m = _box(w, h)
    out.append(("shop_one_storey", House(w, h, [m], "S", _party(w, h, "EW")), "shop_only@retail"))
    w, h = 6, 12
    m = _box(w, h)
    out.append(("shop_stores_over", House(w, h, [m, m], "S", _party(w, h, "EW")), "shop_only@retail"))
    out.append(("takeaway_home", House(w, h, [m, m], "S", _party(w, h, "EW")), "shop_house@food"))
    w, h = 9, 12
    m = _box(w, h)
    out.append(("bank", House(w, h, [m, m], "S", _party(w, h, "W")), "shop_only@bank"))
    w, h = 10, 10
    m = _box(w, h)
    out.append(("surgery", House(w, h, [m, m], "S"), "shop_only@surgery"))
    w, h = 5, 10
    m = _box(w, h)
    out.append(("estate_agent", House(w, h, [m, m], "S", _party(w, h, "EW")), "shop_only@office"))
    # pubs: a town pub with two bars and the landlord's flat; a village pub, nobody over it
    w, h = 13, 10
    m = _box(w, h)
    out.append(("pub_two_bars", House(w, h, [m, m], "S", _party(w, h, "W")), "shop_house@pub"))
    w, h = 9, 9
    m = _box(w, h)
    out.append(("pub_function_room", House(w, h, [m, m], "S"), "shop_only@pub"))
    # blocks of flats
    w, h = 10, 8
    m = _box(w, h)
    out.append(("flats_four_block", House(w, h, [m, m], "S", homes=4), "flats_block"))
    w, h = 14, 10
    m = _box(w, h)
    out.append(("flats_80s_block", House(w, h, [m, m, m], "S", homes=6), "flats_block"))
    w, h = 7, 11
    m = _box(w, h)
    out.append(("flats_conversion", House(w, h, [m, m, m], "S", _party(w, h, "E"), homes=3), "flats_block"))
    return out


def programme_by_area(storeys: int, ground_m2: int, style: str = "") -> str:
    """A programme when the sub-type gives none (rules.programme_by_area); a
    large house in a period style (rules.period_styles) is a period one."""
    period = style in RULES["period_styles"] or "__" in style
    if storeys == 1:
        return "bungalow_large" if ground_m2 >= RULES["programme_by_area"][-2][1] else "bungalow"
    if storeys >= 3:
        big = ground_m2 >= RULES["townhouse_large_m2"]
        return ("period_large" if big else "townhouse_period") if period else                ("executive_large" if big else "townhouse_modern")
    name = RULES["programme_by_area"][-1][0]
    for n, below in RULES["programme_by_area"]:
        if ground_m2 < below:
            name = n
            break
    if name == "executive_large" and period:
        return "period_large"
    return name


def choose_programme(look: str, storeys: int, ground_m2: int, style: str = "") -> str | None:
    """A house's programme: its 1993 look (rules.look_programmes), then its
    storeys and size; None for what the room solver leaves to Build (flats)."""
    looks = RULES["look_programmes"]
    if look in looks and looks[look] is None:
        return None
    period = look in RULES["period_looks"] or style in RULES["period_styles"] or "__" in style
    if storeys == 1:
        return "bungalow_large" if ground_m2 >= RULES["programme_by_area"][-2][1] else "bungalow"
    if storeys >= 3:
        big = ground_m2 >= RULES["townhouse_large_m2"]
        return ("period_large" if big else "townhouse_period") if period else \
               ("executive_large" if big else "townhouse_modern")
    if ground_m2 >= RULES["programme_by_area"][-2][1]:
        return "period_large" if period else "executive_large"
    if look in looks and any(len(v) == storeys for v in programme_tables(looks[look])[0]):
        return looks[look]
    # the look's programme has no variant of this many storeys (a bungalow
    # look with rooms in the roof: a chalet bungalow): by size
    return programme_by_area(storeys, ground_m2, style)


def _pubs():
    """KnoxMap UK's pub fittings (knoxbuild/pub_uk.py), or None where it is not installed."""
    try:
        from . import pub_uk
    except ImportError:
        return None
    return pub_uk


HOME_BUILDS = {"livingroom", "bedroom", "kitchen", "openplan"}     # a floor with these is a home's


def shop_use_of(uses) -> tuple | None:
    """The one business the solver lays a ground floor out for: a pub's bar
    when it has one (its food hygiene record or business rates are the same
    pub), else the building's only use; None for several (Build's own, for now)."""
    uses = list(uses or [])
    pubs = _pubs()
    pub = pubs.pub_use(uses) if pubs else None
    if pub:
        return pub
    return tuple(uses[0]) if len(uses) == 1 else None


def shop_programme(storeys: int, homes: int, cls: str = "retail") -> str | None:
    """A business by its homes: none (shop_only@class: store rooms and a break
    room upstairs), one (a house's rooms above, a maisonette over two floors),
    a flat a floor, or two flats a floor. The ground floor is its class's
    (room_solver.json shops); a retail one with homes keeps its first programmes'
    names (shop_house...)."""
    upper = storeys - 1
    if upper < 0 or upper > 3 or cls not in SHOPS["grounds"]:
        return None             # (a guest house not in a house: Build's)
    if not homes:
        return f"{SHOP_ONLY}@{cls}"
    if upper < 1:
        return None
    base = "shop_house" if homes <= 1 else "shop_flats" if homes <= upper else "shop_flats2"
    return base if cls == "retail" else f"{base}@{cls}"


def house_from_job(job: tuple, roof: dict | None = None):
    """Build's job for one building (build._make_one) as (House, programme,
    building id), or None when the room solver is not for it: not a house, a
    block of flats or a business with one use (or a pub) with or without homes
    over it (those three need KnoxMap UK's regional record); rooms mapped from
    OSM, a landmark, a hotel; the room_solver setting off."""
    (w, h, levels, commercial, seed, kind, mask, settings, style, label, path, street, retail,
        uses, hotel, entrances, profile, mapped, garage_door, preset_file, party, *planned) = job
    roof = roof if roof is not None else (planned[0] if planned else None)
    style = style or {}
    if not wanted(settings):
        return None
    # KnoxMap UK's regional record (age, dwelling, rooms); without one, a house is
    # laid out by its footprint and storeys alone
    info = style.get("uk_rooms") or {}
    if preset_file or style.get("landmark") or style.get("superstore"):
        return None
    # a business with or without homes over it (shops.py's shop_flats, shop):
    # one use, or a pub (a building tagged as one is Build's "restaurant")
    use = shop_use_of(uses) if info.get("dwelling") in ("shop_flats", "shop") else None
    shop = (info.get("dwelling") in ("shop_flats", "shop") and kind in ("apartment", "shop", "restaurant")
            and not hotel and use is not None)
    # a block of flats: shops.py's flats, no shop under it (a lift block, 5+ storeys, is Build's)
    block = info.get("dwelling") == "flats" and kind == "apartment" and not uses and not hotel
    if not shop and not block and (kind not in (None, "house") or commercial or uses):
        return None
    if any(k != "garage" for _, k in (mapped or [])):
        return None
    # no mask: a plain rectangle, every square
    base = [[bool(v) for v in row] for row in mask] if mask is not None else [[True] * w for _ in range(h)]
    if roof and roof.get("level_masks"):
        masks = [[[bool(v) and bool(base[y][x]) for x, v in enumerate(row)] for y, row in enumerate(lm)]
                 for lm in roof["level_masks"]]
    else:
        masks = [[row[:] for row in base] for _ in range(max(1, levels))]
    masks = [mk for mk in masks if any(any(r) for r in mk)]
    if not masks or len(masks) > 4:
        return None
    # Build's party edges (x, y, "N"|"W") as the square sides behind them
    sides = set()
    for (x, y, d) in (party or {}):
        a, b = ((x, y - 1), (x, y)) if d == "N" else ((x - 1, y), (x, y))
        inside = lambda q: 0 <= q[0] < w and 0 <= q[1] < h and base[q[1]][q[0]]  # noqa: E731
        if inside(b) and not inside(a):
            sides.add((b[0], b[1], d))
        elif inside(a) and not inside(b):
            sides.add((a[0], a[1], "S" if d == "N" else "E"))
    g = (style.get("garage") or {}).get("rect")
    if g and not all(0 <= x < w and 0 <= y < h and base[y][x]
                     for x in range(g[0], g[2] + 1) for y in range(g[1], g[3] + 1)):
        g = None            # a garage reaching past the footprint: the solver leaves it out
    house = House(w, h, masks, street or "S", sides, tuple(g) if g else None,
                  None if (shop or block) else info.get("epc_rooms"),
                  info.get("homes") if block else None)
    ground = sum(v for row in masks[0] for v in row)
    if block:
        prog = "flats_block"
    elif shop and conversion(info, use):
        # an office, surgery or guest house in a house: the house's own plan
        # (renamed in to_building); a period house cut into flats by its size
        prog = choose_programme(info.get("look", ""), len(masks), ground, style.get("name", "")) \
            or programme_by_area(len(masks), ground, style.get("name", ""))
    elif shop:
        # shops.py's "shop" has no homes; "shop_flats" at least one
        homes = (info.get("homes") or 1) if info.get("dwelling") == "shop_flats" else 0
        prog = shop_programme(len(masks), homes, use_class(use))
    else:
        prog = choose_programme(info.get("look", ""), len(masks), ground, style.get("name", ""))
    if prog is None:
        return None
    return house, prog, info.get("osm_id") or label


# ---- Build's hook: the room_solver setting ------------------------------------------

_CACHE = None

ENV = "KNOXMAP_ROOM_SOLVER"     # 1 / 0: on or off for every map, whatever its settings say
OFF = ("0", "off", "no", "false")


def wanted(settings) -> bool:
    """The room solver for this building's settings (Settings.room_solver; a zone may
    set it), unless KNOXMAP_ROOM_SOLVER says otherwise."""
    env = os.environ.get(ENV)
    if env is not None and env.strip():
        return env.strip().lower() not in OFF
    return bool(getattr(settings, "room_solver", 0))


def prepare(jobs: list, processes: int | None = None) -> dict | None:
    """Before Build's pool starts: every house's footprint the cache lacks,
    solved in parallel here, so the workers only read it."""
    if not any(wanted(job[7]) for job in jobs):
        return None
    try:
        from ortools.sat.python import cp_model  # noqa: F401
    except ImportError:
        print("room_solver: OR-Tools is not installed; Build's own layouts")
        return None
    todo = []
    for job in jobs:
        try:
            got = house_from_job(job)
        except Exception:  # noqa: BLE001 - that house keeps Build's layout
            got = None
        if got:
            todo.append((got[0], got[1]))
    cache = LayoutCache()
    dropped = cache.prune()
    processes = processes or max(1, (os.cpu_count() or 4) // 4)
    got = prewarm(todo, cache, processes=processes, workers=4,
                  progress=lambda i, n, t: print(f"  room_solver: {i}/{n} footprints solved, {t:.0f}s", flush=True))
    os.environ[PREPARED] = "1"      # Build's workers: the cache only (PREPARED)
    got["houses"] = len(todo)
    got["stale_dropped"] = dropped
    print("room_solver:", got)
    return got


def plan_for_job(job: tuple, roof: dict | None = None):
    """A house's Building from its cached layout (Build's _make_one), or None
    to leave it to Build's own layout."""
    global _CACHE
    got = house_from_job(job, roof)
    if got is None:
        return None
    house, prog, bid = got
    if _CACHE is None:
        _CACHE = LayoutCache()
    lay = layout_for(house, prog, bid, _CACHE, solve_missing=not os.environ.get(PREPARED))
    if lay is None:
        return None
    seed, profile, party, uses = job[4], job[16], job[20], job[13]
    info = (job[8] or {}).get("uk_rooms") or {}
    converted = conversion(info, shop_use_of(uses)) if info.get("dwelling") in ("shop", "shop_flats") else None
    return to_building(lay, seed=seed, profile=profile, party=party or {}, uses=uses,
                       converted=converted, homes=info.get("dwelling") == "shop_flats")


def dump_job(path: str, job: tuple, roof: dict | None = None) -> None:
    """One line of JSON for a house Build is about to lay out (KNOXMAP_ROOMS_DUMP):
    the room solver's input, for rooms_check. One file per process (path.<pid>)."""
    try:
        got = house_from_job(job, roof)
    except Exception as exc:  # noqa: BLE001 - a record is not worth a Build run
        with open(f"{path}.errors", "a", encoding="utf-8") as f:
            f.write(f"{job[9]}: {exc!r}\n")
        return
    if got is None:
        # why not (a diagnostic): <path>.skipped, one line a building
        style, kind, uses = job[8] or {}, job[5], job[13]
        info = style.get("uk_rooms") or {}
        why = ("no record" if not info else f"kind={kind} uses={len(uses or [])} "
               f"dwelling={info.get('dwelling')} look={info.get('look')} levels={job[2]}")
        with open(f"{path}.skipped", "a", encoding="utf-8") as f:
            f.write(f"{job[9]}\t{why}\n")
        return
    house, prog, bid = got
    style = job[8] or {}
    rec = {"id": bid, "label": job[9], "programme": prog, "style": style.get("name"),
           "rooms": style.get("uk_rooms"), "width": house.width, "height": house.height,
           "masks": ["/".join("".join("1" if v else "0" for v in row) for row in m) for m in house.masks],
           "street": house.street, "party": sorted(house.party), "garage": house.garage,
           "epc_rooms": house.epc_rooms, "homes": house.homes}
    with open(f"{path}.{os.getpid()}", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def load_dump(path: str) -> list:
    """The houses a Build run wrote with KNOXMAP_ROOMS_DUMP: [(House, programme, record)]."""
    import glob
    out = []
    for fn in sorted(glob.glob(path + ".*")):
        if not fn.rsplit(".", 1)[-1].isdigit():
            continue            # .skipped, .errors: not houses
        with open(fn, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                masks = [[[c == "1" for c in row] for row in m.split("/")] for m in r["masks"]]
                house = House(r["width"], r["height"], masks, r["street"],
                              {tuple(e) for e in r["party"]}, tuple(r["garage"]) if r["garage"] else None,
                              r.get("epc_rooms"), r.get("homes"))
                out.append((house, r["programme"], r))
    return out


def map_houses(map_dir: str, limit: int | None = None, seed: int = 1):
    """Real footprints from a built map's .tbx files, for timing: (house,
    programme, name). Approximate: the street is taken as S and there are no
    party walls (the .tbx keeps neither); the programme by storeys and size."""
    import csv
    import random
    from . import buildtiles
    name = os.path.basename(os.path.abspath(map_dir))
    with open(os.path.join(map_dir, f"{name}_placements.csv"), encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["kind"] == "house"]
    if limit:
        rows = random.Random(seed).sample(rows, min(limit, len(rows)))
    out = []
    for r in rows:
        path = os.path.join(map_dir, "buildings", r["file"])
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            b = buildtiles.parse_tbx(f.read())
        floors = [[[bool(v) for v in row] for row in fl.rooms] for fl in b.floors
                  if any(any(row) for row in fl.rooms)]
        if not floors or len(floors) > 4 or r["style"].startswith("uk_flats"):
            continue            # flats in a house's outline: a flats programme, later
        ys = [y for m in floors for y, row in enumerate(m) if any(row)]
        xs = [x for m in floors for row in m for x, v in enumerate(row) if v]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        masks = [[row[x0:x1 + 1] for row in m[y0:y1 + 1]] for m in floors]
        area = sum(v for row in masks[0] for v in row)
        prog = programme_by_area(len(masks), area, r.get("style", ""))
        out.append((House(x1 - x0 + 1, y1 - y0 + 1, masks, "S"), prog, r["name"]))
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", nargs="?", const=os.path.join(HERE, "..", "output", "rooms_demo"))
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--only")
    ap.add_argument("--bench", help="a built map: time solving its houses' footprints into the cache")
    ap.add_argument("--sample", type=int, default=None)
    ap.add_argument("--processes", type=int, default=4)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cache", help="cache folder (default cache/room_solver)")
    a = ap.parse_args(argv)
    if a.bench:
        houses = map_houses(a.bench, a.sample)
        cache = LayoutCache(a.cache)
        print("stale entries dropped:", cache.prune())
        jobs = [(h, p) for h, p, _ in houses]
        print(f"{len(jobs)} houses; {len({house_key(h, p) for h, p in jobs})} footprints")
        got = prewarm(jobs, cache, processes=a.processes, seconds=a.seconds, workers=a.workers,
                      progress=lambda i, n, t: print(f"  {i}/{n} footprints, {t:.0f}s", flush=True))
        print(got)
        t = time.time()
        found = sum(1 for i, (h, p) in enumerate(jobs) if layout_for(h, p, i, cache) is not None)
        print(f"from the cache: {found}/{len(jobs)} houses laid out in {time.time() - t:.1f}s")
        return 0
    if not a.demo:
        ap.print_help()
        return 1
    os.makedirs(a.demo, exist_ok=True)
    for name, house, prog in demo_houses():
        if a.only and a.only != name:
            continue
        lay = solve(house, prog, seconds=a.seconds, workers=8)
        if lay is None:
            print(f"{name}: no layout")
            continue
        broken = check(lay)
        render(lay, os.path.join(a.demo, f"{name}.png"), name)
        print(f"{name}: {prog} v{lay.variant} {lay.seconds:.1f}s stairs={lay.stairs} "
              f"{'OK' if not broken else broken}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
