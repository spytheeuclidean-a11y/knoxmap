"""Put a real building footprint onto the tile grid.

Project Zomboid buildings cannot be rotated. The first approach squared every
footprint up into an upright rectangle with the right side lengths, centred on
the real one. That is tidy, and wrong for most real towns: in the Turkish town
this was measured on, 61% of buildings stand more than 15 degrees off the
grid, and 37% of the squared-up rectangles covered less than 70% of the real
footprint. A street of houses running diagonally became a scatter of upright
boxes jutting into the road - buildings in the right places, but not a town
anyone would recognise.

So a building close to the grid is still squared up, because a wall with a
one-tile step every eight tiles looks like a mistake. Anything turned further
is rasterised as it really is: a tile belongs to the building when the middle
of that tile lies inside the real outline. The result has stepped walls along
its diagonal sides, and it stands exactly where the building stands.
"""
from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import Polygon

# Within this many degrees of the grid, square the building up.
SNAP_DEGREES = 8.0
# A footprint filling this share of its rotated rectangle is a rectangle.
RECTANGULAR_ENOUGH = 0.86
MIN_TILES = 16


def _polygon(px: list[tuple[float, float]]):
    poly = Polygon(px)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    return poly


def grid_angle(poly) -> float:
    """How far the building's long side is from the nearest grid axis, 0..45."""
    rect = poly.minimum_rotated_rectangle
    if not hasattr(rect, "exterior"):
        return 0.0
    c = list(rect.exterior.coords)
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    long_edge = e1 if math.hypot(*e1) >= math.hypot(*e2) else e2
    a = abs(math.degrees(math.atan2(long_edge[1], long_edge[0]))) % 90.0
    return min(a, 90.0 - a)


def _largest_component(mask: np.ndarray) -> np.ndarray:
    """Keep only the biggest 4-connected piece of a mask."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    best: list[tuple[int, int]] = []
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or seen[y, x]:
                continue
            piece = []
            stack = [(y, x)]
            seen[y, x] = True
            while stack:
                cy, cx = stack.pop()
                piece.append((cy, cx))
                for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(piece) > len(best):
                best = piece
    out = np.zeros_like(mask, dtype=bool)
    for y, x in best:
        out[y, x] = True
    return out


class Footprint:
    """Where one building goes: its bounding box and which tiles it owns."""

    def __init__(self, x0: int, y0: int, mask: np.ndarray, angle: float,
                 short_side: float, long_side: float):
        self.x0, self.y0 = x0, y0
        self.mask = mask
        self.angle = angle
        self.short_side = short_side
        self.long_side = long_side

    @property
    def width(self) -> int:
        return self.mask.shape[1]

    @property
    def height(self) -> int:
        return self.mask.shape[0]

    @property
    def tiles(self) -> int:
        return int(self.mask.sum())

    def mask_list(self) -> list[list[bool]] | None:
        """The mask as layout.py takes it, or None when it fills its box."""
        if self.mask.all():
            return None
        return self.mask.tolist()


def place(px: list[tuple[float, float]], occupied: np.ndarray,
          min_side: float = 0, max_side: float = 1e9,
          snap_degrees: float = SNAP_DEGREES
          ) -> tuple[Footprint | None, str]:
    """Rasterise a projected footprint, claiming its tiles in `occupied`.

    Returns the footprint and why not when there is none: "small", "large",
    "outside" or "taken". Size is judged on the real building's sides, before
    anything is claimed, so a rejected building never blocks its neighbours.

    Tiles another building already owns are left to it. Real neighbours share
    walls; two buildings claiming the same tile would put one wall inside the
    other.
    """
    map_h, map_w = occupied.shape
    poly = _polygon(px)
    if poly.is_empty or poly.area <= 0:
        return None, "small"
    rect = poly.minimum_rotated_rectangle
    c = list(rect.exterior.coords) if hasattr(rect, "exterior") else []
    if len(c) >= 4:
        sides = sorted((math.dist(c[0], c[1]), math.dist(c[1], c[2])))
    else:
        minx, miny, maxx, maxy = poly.bounds
        sides = sorted((maxx - minx, maxy - miny))
    if sides[0] < min_side:
        return None, "small"
    if sides[1] > max_side:
        return None, "large"
    angle = grid_angle(poly)
    rectangular = rect.area > 0 and poly.area / rect.area >= RECTANGULAR_ENOUGH

    # Past 30 degrees a turned outline squared up would stand far out of its
    # real footprint, so from there any shape is squared (the user asked for
    # every building on the grid), not just near-rectangles.
    if angle <= snap_degrees and (rectangular or snap_degrees >= 30):
        # Square it up: an upright rectangle of the true side lengths, centred.
        cx, cy = poly.centroid.x, poly.centroid.y
        horizontal = (angle == 0.0 and (poly.bounds[2] - poly.bounds[0])
                      >= (poly.bounds[3] - poly.bounds[1]))
        if len(c) >= 4:
            dx = abs(c[1][0] - c[0][0]) + abs(c[2][0] - c[1][0])
            dy = abs(c[1][1] - c[0][1]) + abs(c[2][1] - c[1][1])
            horizontal = dx >= dy
        w, h = (sides[1], sides[0]) if horizontal else (sides[0], sides[1])
        w, h = max(1, int(round(w))), max(1, int(round(h)))
        x0 = int(round(cx - w / 2))
        y0 = int(round(cy - h / 2))
        mask = np.ones((h, w), dtype=bool)
    else:
        minx, miny, maxx, maxy = poly.bounds
        x0, y0 = int(math.floor(minx)), int(math.floor(miny))
        x1, y1 = int(math.ceil(maxx)), int(math.ceil(maxy))
        xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        mask = shapely.contains_xy(poly, xs, ys)

    # Clip to the map, then give up tiles already owned by a neighbour.
    h, w = mask.shape
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1, cy1 = min(map_w, x0 + w), min(map_h, y0 + h)
    if cx1 <= cx0 or cy1 <= cy0:
        return None, "outside"
    mask = mask[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0].copy()
    mask &= ~occupied[cy0:cy1, cx0:cx1]
    if mask.sum() < MIN_TILES:
        return None, "taken"
    mask = _largest_component(mask)

    # Trim empty rows and columns so the box hugs what is left.
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    mask = mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    fx0, fy0 = cx0 + int(cols[0]), cy0 + int(rows[0])
    if mask.sum() < MIN_TILES:
        return None, "taken"
    occupied[fy0:fy0 + mask.shape[0], fx0:fx0 + mask.shape[1]] |= mask
    return Footprint(fx0, fy0, mask, angle, sides[0], sides[1]), "ok"
