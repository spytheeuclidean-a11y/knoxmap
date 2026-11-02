"""Basements: a cellar under a house, a plant room under a school, levels of
bunker under a military base (docs/superpowers/specs/2026-11-01-basements-design.md).

A basement is its own lot, `<parent>_bsmt.tbx`, laid at a level below 0 with its
top floor at -1; the room tables count its rooms as the parent building's
(buildheader.placed_rooms). Where each one goes is settled here, in build order,
before the buildings are laid out across processes: one map of the squares
already taken underground, so no two basements share a square on any level.

Build 42's levels run from -32 to 31 (zombie.iso.IsoChunkMap, read for analysis).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np

BOTTOM_LEVEL = -32

LARGE_KINDS = {"school", "medical", "civic", "police", "mall", "industrial"}
CHURCH_MIN_M2 = 600
LARGE_TWO_LEVELS_M2 = 3_000
INSTALLATION_SITE_M2 = 50_000          # an industrial site this big goes deep
SITE_M2_PER_LEVEL = 20_000
# ponytail: a square crop centred on the parent; follow the site's own shape if
# a big base's basement looks cut off.
INSTALLATION_MAX_TILES = 40_000        # per level, so a base is not one building of thousands of rooms
EAST_ASIA = {"cn", "jp", "kr"}         # houses there rarely have a cellar
BLOCK = 32


def tier(kind: str | None, footprint_m2: float, site_m2: float) -> str | None:
    """"house", "large", "installation", or None for a building with no basement."""
    if kind is None or kind == "house":
        return "house"
    if kind == "military":
        return "installation"
    if kind == "industrial" and site_m2 >= INSTALLATION_SITE_M2:
        return "installation"
    if kind in LARGE_KINDS or (kind == "church" and footprint_m2 >= CHURCH_MIN_M2):
        return "large"
    return None


def levels_for(tier: str, footprint_m2: float, site_m2: float, max_depth: int) -> int:
    if tier == "house":
        return 1
    if tier == "large":
        return 2 if footprint_m2 >= LARGE_TWO_LEVELS_M2 else 1
    deepest = min(max_depth, -BOTTOM_LEVEL)
    return max(2, min(1 + int(site_m2 // SITE_M2_PER_LEVEL), deepest))


class Underground:
    """The squares basements have taken, level by level, in 32 x 32 blocks."""

    def __init__(self):
        self._levels: dict[int, dict[tuple[int, int], np.ndarray]] = {}

    def _blocks(self, x0: int, y0: int, mask: np.ndarray):
        """(block key, block slice, mask slice) for each block the mask covers."""
        h, w = mask.shape
        for by in range(y0 // BLOCK, (y0 + h - 1) // BLOCK + 1):
            for bx in range(x0 // BLOCK, (x0 + w - 1) // BLOCK + 1):
                ax, ay = max(x0, bx * BLOCK), max(y0, by * BLOCK)
                bx1, by1 = min(x0 + w, (bx + 1) * BLOCK), min(y0 + h, (by + 1) * BLOCK)
                yield ((bx, by), (slice(ay - by * BLOCK, by1 - by * BLOCK),
                                  slice(ax - bx * BLOCK, bx1 - bx * BLOCK)),
                       (slice(ay - y0, by1 - y0), slice(ax - x0, bx1 - x0)))

    def fits(self, x0: int, y0: int, mask: np.ndarray, levels: int) -> bool:
        for z in range(-1, -levels - 1, -1):
            taken = self._levels.get(z, {})
            for key, there, here in self._blocks(x0, y0, mask):
                block = taken.get(key)
                if block is not None and (block[there] & mask[here]).any():
                    return False
        return True

    def take(self, x0: int, y0: int, mask: np.ndarray, levels: int) -> None:
        for z in range(-1, -levels - 1, -1):
            taken = self._levels.setdefault(z, {})
            for key, there, here in self._blocks(x0, y0, mask):
                block = taken.setdefault(key, np.zeros((BLOCK, BLOCK), dtype=bool))
                block[there] |= mask[here]


@dataclass
class BasementSpec:
    tier: str
    kind: str
    levels: int
    dx: int               # the basement lot's corner, from the parent lot's corner
    dy: int
    mask: np.ndarray      # its squares, in its own lot


def _inside(mask: np.ndarray) -> np.ndarray:
    """The footprint less its outer ring: the walls of two units of one building
    stand side by side, and their basements must not touch."""
    m = np.asarray(mask, dtype=bool)
    out = m.copy()
    out[0, :] = out[-1, :] = False
    out[:, 0] = out[:, -1] = False
    out[1:, :] &= m[:-1, :]
    out[:-1, :] &= m[1:, :]
    out[:, 1:] &= m[:, :-1]
    out[:, :-1] &= m[:, 1:]
    return out


def _site_mask(shape, row: dict, inside: np.ndarray, size: tuple[int, int]):
    """(dx, dy, mask) of a site's squares around the parent, within the map and
    INSTALLATION_MAX_TILES, joined to the parent's own."""
    import shapely
    x0, y0, w, h = row["x0"], row["y0"], row["w"], row["h"]
    side = int(INSTALLATION_MAX_TILES ** 0.5)
    cx, cy = x0 + w // 2, y0 + h // 2
    a, b, c, d = shape.bounds
    lx = max(int(a), cx - side // 2, 0)
    ly = max(int(b), cy - side // 2, 0)
    hx = min(int(c) + 1, lx + side, size[0])
    hy = min(int(d) + 1, ly + side, size[1])
    xs, ys = np.meshgrid(np.arange(lx, hx) + 0.5, np.arange(ly, hy) + 0.5)
    mask = shapely.contains_xy(shape, xs, ys)
    # The parent's own squares, wherever the crop or the site's edge falls.
    ux0, uy0 = min(lx, x0), min(ly, y0)
    ux1, uy1 = max(hx, x0 + w), max(hy, y0 + h)
    out = np.zeros((uy1 - uy0, ux1 - ux0), dtype=bool)
    out[ly - uy0:hy - uy0, lx - ux0:hx - ux0] = mask
    out[y0 - uy0:y0 - uy0 + h, x0 - ux0:x0 - ux0 + w] |= inside
    return ux0 - x0, uy0 - y0, out


def reserve(rows: list[dict], settings, region: str | None, areas, rng: random.Random,
            size: tuple[int, int], m2_per_tile: float = 1.0,
            underground: Underground | None = None) -> list[BasementSpec | None]:
    """Where each building's basement goes, in build order, or None.

    A row is {"kind", "x0", "y0", "w", "h", "mask"}: the parent lot and its
    footprint. `areas` answers shape_around(x, y) with the site a building
    stands in (areas.AreaIndex), or is None. `size` is the map, in tiles."""
    underground = underground or Underground()
    share = settings.basement_share * (0.25 if region in EAST_ASIA else 1.0)
    out: list[BasementSpec | None] = []
    for row in rows:
        kind = row["kind"] or "house"
        footprint_m2 = float(np.count_nonzero(row["mask"])) * m2_per_tile
        site = None
        if areas is not None and kind in ("military", "industrial"):
            site = areas.shape_around(row["x0"] + row["w"] / 2, row["y0"] + row["h"] / 2)
        site_m2 = site.area * m2_per_tile if site is not None else 0.0
        t = tier(kind, footprint_m2, site_m2)
        if t is None or (t == "house" and rng.random() >= share):
            out.append(None)
            continue
        levels = levels_for(t, footprint_m2, site_m2, settings.max_basement_depth)
        inside = _inside(row["mask"])
        tries = [(0, 0, inside)]
        if t == "installation" and site is not None:
            tries.insert(0, _site_mask(site, row, inside, size))
        spec = None
        for dx, dy, mask in tries:
            if mask.any() and underground.fits(row["x0"] + dx, row["y0"] + dy, mask, levels):
                underground.take(row["x0"] + dx, row["y0"] + dy, mask, levels)
                spec = BasementSpec(t, kind, levels, dx, dy, mask)
                break
        out.append(spec)
    return out


# --- laying one out ----------------------------------------------------------

# Where the stairs down may start, best first: through a hall, past the
# laundry, and only then out of a kitchen. A big building also takes a stair in
# any room but a bathroom or a bedroom.
STAIR_ROOMS = ("hall", "corridor", "lobby", "laundry", "storage", "office", "kitchen",
               "dining", "livingroom")
NOT_STAIR_ROOMS = {"bathroom", "bedroom", "kidsbedroom"}


@dataclass
class Basement:
    building: object      # layout.Building, its storeys bottom first
    dx: int
    dy: int
    levels: int


def _run(x: int, y: int, d: str) -> list[tuple[int, int]]:
    """The squares a flight and its landings take (layout.STAIR_RUN)."""
    from .layout import STAIR_RUN
    return [(x, y + i) if d == "N" else (x + i, y) for i in range(STAIR_RUN)]


def _top(x: int, y: int, d: str) -> list[tuple[int, int]]:
    """What a flight from below takes of the floor it rises to: the square a
    player steps off at, then the three over the steps (buildtiles._stair_squares)."""
    return _run(x, y, d)[:4]


def _core(x: int, y: int, d: str) -> tuple[int, int, int, int]:
    """The shaft around a flight, as layout._stairs_in_core reads one back."""
    from .layout import STAIR_RUN
    if d == "N":
        return (x - 1, y - 1, x + 1, y + STAIR_RUN - 1)
    return (x - 1, y - 1, x + STAIR_RUN - 1, y + 1)


def find_stair_spot(ground, under: np.ndarray, kinds: tuple[str, ...] | None,
                    avoid: set) -> tuple[int, int, str] | None:
    """(x, y, dir) on the ground floor where a flight can come up from below.

    The square a player steps off at and the three left open over the steps
    (_top) lie in one room of `kinds` (None: any room but a bathroom or a
    bedroom), off every door and `avoid`; the shaft below lies inside `under`
    (the basement's squares, in the ground floor's tiles). The first spot that
    moves no furniture wins, rooms taken in the order of `kinds`."""
    from .layout import _cells_for, _is_wall_piece
    grid = ground.grid
    h, w = len(grid), len(grid[0]) if grid else 0
    blocked = set(avoid) | set(ground.void) | set(ground.holes)
    for x, y, d in ground.doors:
        blocked |= {(x, y), (x, y - 1) if d == "N" else (x - 1, y)}
    furnished = {c for f in ground.furniture if not _is_wall_piece(f[0])
                 for c in _cells_for(f[0], f[1], f[2], f[3])}

    def room_kind(x, y):
        v = grid[y][x]
        return ground.rooms[v - 1].kind if v else None

    def ok(x, y, d):
        run = _top(x, y, d)
        if any(not (0 <= a < w and 0 <= b < h) or (a, b) in blocked for a, b in run):
            return False
        first = grid[run[0][1]][run[0][0]]
        if first == 0 or any(grid[b][a] != first for a, b in run):
            return False
        x0, y0, x1, y1 = _core(x, y, d)
        uh, uw = under.shape
        return (0 <= x0 and 0 <= y0 and x1 < uw and y1 < uh
                and bool(under[y0:y1 + 1, x0:x1 + 1].all()))

    spots = [(x, y, d) for y in range(h) for x in range(w) for d in ("N", "W")
             if room_kind(x, y) and ok(x, y, d)]
    order = kinds or STAIR_ROOMS

    def rank(spot):
        kind = room_kind(spot[0], spot[1])
        if kinds is None and kind in NOT_STAIR_ROOMS:
            return None
        place = order.index(kind) if kind in order else (len(order) if kinds is None else None)
        if place is None:
            return None
        return (place, bool(set(_top(*spot)) & furnished))

    ranked = [(r, s) for s in spots if (r := rank(s)) is not None]
    return min(ranked)[1] if ranked else None


def plan_basement(parent, spec: BasementSpec, seed: int, settings) -> Basement | None:
    """Lay out `spec` under `parent` (a layout.Building), or None when the
    ground floor has nowhere for the stairs. On success the parent's ground
    floor is cleared over the flight and opened (Plan.holes)."""
    from .layout import Building, _cells_for, _clear_for_stairs, _is_wall_piece, build_plan
    ground = parent.storeys[0]
    h, w = spec.mask.shape
    # The basement's squares in the parent's tiles.
    under = np.zeros((parent.height, parent.width), dtype=bool)
    for y in range(parent.height):
        by = y - spec.dy
        if 0 <= by < h:
            for x in range(parent.width):
                bx = x - spec.dx
                if 0 <= bx < w:
                    under[y, x] = spec.mask[by, bx]
    avoid = {c for s in parent.stairs for c in _run(*s)}
    kinds = STAIR_ROOMS if spec.tier == "house" else None
    spot = find_stair_spot(ground, under, kinds, avoid)
    if spot is None:
        return None
    sx, sy, d = spot
    here = (sx - spec.dx, sy - spec.dy, d)
    core = _core(*here)
    mask = spec.mask.tolist()
    storeys = [build_plan(w, h, seed=seed + 977 * i, kind=f"basement_{spec.kind}",
                          mask=mask, ground=False, settings=settings, core=core,
                          level=i, levels=spec.levels + 1, stairs=here,
                          corridor=spec.tier == "installation")
               for i in range(spec.levels)]
    for st in storeys:
        st.windows = []
        _clear_for_stairs(st, *here)
    building = Building(width=w, height=h, storeys=storeys, stairs=[here] * spec.levels)
    top = set(_top(sx, sy, d))
    ground.furniture = [f for f in ground.furniture if _is_wall_piece(f[0])
                        or not (set(_cells_for(f[0], f[1], f[2], f[3])) & top)]
    ground.holes |= set(_top(sx, sy, d)[1:])
    return Basement(building, spec.dx, spec.dy, spec.levels)


def basement_style(style: dict | None) -> dict:
    """The building's style with concrete walls and floors: the industrial kit."""
    from . import catalog as C
    plant = C.SPECIAL_STYLES["industrial"]
    out = dict(style or {})
    out.update(exterior=plant["exterior"], interior=plant["interior"], floor=plant["floor"],
               roof=None, trim=None, shutters=None, grime=None, windows_by_levels=None)
    out.setdefault("name", "basement")
    return out


def render_basement(b: Basement, label: str, style: dict | None) -> str:
    from .tbx import render_tbx
    return render_tbx(b.building, label, basement_style(style), roof=False)
