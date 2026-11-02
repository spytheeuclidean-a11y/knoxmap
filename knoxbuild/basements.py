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
