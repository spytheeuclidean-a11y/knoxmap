"""The road pass: the road-class image, kerbs and edges, road details, paving under dense
building and weathering."""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .. import pz_colors as C
from ..osm import OSMFeature, ROAD_HIERARCHY_CODES, road_hierarchy
from .crossings import paint_crossings
from .geometry import _draw_roads, _feature_coords_px, _is_polygon, _pixel_width
from .landcover import DENSE_COVERAGE, GREEN_CATEGORIES, MAX_PAVED_BLOCK
from .projection import Projector
from .widths import (ROAD_WIDTHS_M, _road_markings, _sidewalk_width_m,
                     _way_width_m)


def _road_hierarchy_image(buckets: dict[str, list[OSMFeature]], proj: Projector) -> Image.Image:
    """Rasterize road class over the right-of-way for downstream map passes."""
    image = Image.new("L", (proj.width, proj.height), 0)
    road_buckets = ("road_service", "road_minor", "road_medium", "road_major",
                    "paved_path", "dirt_path")
    for hierarchy, code in sorted(ROAD_HIERARCHY_CODES.items(), key=lambda item: item[1]):
        strokes = []
        for cat in road_buckets:
            for feat in buckets.get(cat, []):
                if _is_polygon(feat) or road_hierarchy(feat.tags) != hierarchy:
                    continue
                width = _way_width_m(feat, cat)
                if cat in ROAD_WIDTHS_M:
                    width += 2 * _sidewalk_width_m(feat, cat)
                strokes.append((_pixel_width(width, proj.meters_per_tile), _feature_coords_px(feat, proj)))
        _draw_roads(image, strokes, code)
    return image


def _real_kerbs(sides):
    """Keep kerbs that run along a straight edge; drop the steps of a staircase.

    Where a road crosses the tile grid at an angle its edge steps one tile
    every row, and a corner kerb on every step drew the edge as a row of
    teeth. A straight kerb stays when it is part of a run of at least three
    along the same edge (a corner may end the run); a corner stays only where straight
    kerbs lead into it on both arms. Staircase edges are left to the ground
    blends, which soften them.
    """
    import numpy as np

    W, N, S, E = 1, 2, 4, 8
    NW, SW, NE, SE = W | N, S | W, N | E, S | E
    padded = np.pad(sides, 2)
    core = (slice(2, -2), slice(2, -2))
    left, right = padded[2:-2, 1:-3], padded[2:-2, 3:-1]
    left2, right2 = padded[2:-2, :-4], padded[2:-2, 4:]
    up, down = padded[1:-3, 2:-2], padded[3:-1, 2:-2]
    up2, down2 = padded[:-4, 2:-2], padded[4:, 2:-2]
    del core

    def run3(here, a, a2, b, b2, allowed):
        # At least three in a row along the edge, this tile included.
        ia, ia2, ib, ib2 = (np.isin(x, allowed) for x in (a, a2, b, b2))
        return here & ((ia & ib) | (ia & ia2) | (ib & ib2))

    keep = np.zeros(sides.shape, dtype=bool)
    keep |= run3(sides == N, left, left2, right, right2, (N, NW, NE))
    keep |= run3(sides == S, left, left2, right, right2, (S, SW, SE))
    keep |= run3(sides == W, up, up2, down, down2, (W, NW, SW))
    keep |= run3(sides == E, up, up2, down, down2, (E, NE, SE))
    keep |= (sides == NW) & (right == N) & (down == W)
    keep |= (sides == NE) & (left == N) & (down == E)
    keep |= (sides == SW) & (right == S) & (up == W)
    keep |= (sides == SE) & (left == S) & (up == E)
    return np.where(keep, sides, 0).astype(sides.dtype)


def _shifted(mask, dy, dx) -> "object":
    """`mask` moved by (dy, dx), zero-filled at the edge."""
    out = mask.copy()
    out[:] = False
    ys = slice(max(0, dy), mask.shape[0] + min(0, dy))
    xs = slice(max(0, dx), mask.shape[1] + min(0, dx))
    yt = slice(max(0, -dy), mask.shape[0] + min(0, -dy))
    xt = slice(max(0, -dx), mask.shape[1] + min(0, -dx))
    out[ys, xs] = mask[yt, xt]
    return out


def _mark_two_tile_bumps(fg, bg, back):
    """Return a mask of 2-tile-wide, 1-tile-deep ``fg`` teeth jutting into ``bg``."""
    out = fg & False
    h, w = fg.shape
    if h >= 3 and w >= 4:
        pair = fg[1:-1, 1:-2] & fg[1:-1, 2:-1] & bg[1:-1, :-3] & bg[1:-1, 3:]
        n = pair & bg[:-2, 1:-2] & bg[:-2, 2:-1] & \
            back[2:, :-3] & back[2:, 1:-2] & back[2:, 2:-1] & back[2:, 3:]
        out[1:-1, 1:-2] |= n
        out[1:-1, 2:-1] |= n
        s = pair & bg[2:, 1:-2] & bg[2:, 2:-1] & \
            back[:-2, :-3] & back[:-2, 1:-2] & back[:-2, 2:-1] & back[:-2, 3:]
        out[1:-1, 1:-2] |= s
        out[1:-1, 2:-1] |= s
    if h >= 4 and w >= 3:
        pair = fg[1:-2, 1:-1] & fg[2:-1, 1:-1] & bg[:-3, 1:-1] & bg[3:, 1:-1]
        w_m = pair & bg[1:-2, :-2] & bg[2:-1, :-2] & \
            back[:-3, 2:] & back[1:-2, 2:] & back[2:-1, 2:] & back[3:, 2:]
        out[1:-2, 1:-1] |= w_m
        out[2:-1, 1:-1] |= w_m
        e_m = pair & bg[1:-2, 2:] & bg[2:-1, 2:] & \
            back[:-3, :-2] & back[1:-2, :-2] & back[2:-1, :-2] & back[3:, :-2]
        out[1:-2, 1:-1] |= e_m
        out[2:-1, 1:-1] |= e_m
    return out


def _mark_two_tile_notches(fg, bg):
    """Return a mask of 2-tile-wide, 1-tile-deep ``fg`` dents into ``bg``."""
    out = fg & False
    h, w = fg.shape
    if h >= 3 and w >= 4:
        pair = fg[1:-1, 1:-2] & fg[1:-1, 2:-1] & bg[1:-1, :-3] & bg[1:-1, 3:]
        n = pair & fg[:-2, 1:-2] & fg[:-2, 2:-1] & bg[2:, 1:-2] & bg[2:, 2:-1]
        out[1:-1, 1:-2] |= n
        out[1:-1, 2:-1] |= n
        s = pair & fg[2:, 1:-2] & fg[2:, 2:-1] & bg[:-2, 1:-2] & bg[:-2, 2:-1]
        out[1:-1, 1:-2] |= s
        out[1:-1, 2:-1] |= s
    if h >= 4 and w >= 3:
        pair = fg[1:-2, 1:-1] & fg[2:-1, 1:-1] & bg[:-3, 1:-1] & bg[3:, 1:-1]
        w_m = pair & fg[1:-2, :-2] & fg[2:-1, :-2] & bg[1:-2, 2:] & bg[2:-1, 2:]
        out[1:-2, 1:-1] |= w_m
        out[2:-1, 1:-1] |= w_m
        e_m = pair & fg[1:-2, 2:] & fg[2:-1, 2:] & bg[1:-2, :-2] & bg[2:-1, :-2]
        out[1:-2, 1:-1] |= e_m
        out[2:-1, 1:-1] |= e_m
    return out


def _smooth_road_edges(landscape: Image.Image, asphalt, is_colour) -> None:
    """Fill one-tile notches along the edge of the road, and shave one-tile bumps.

    A street a degree or two off the tile grid rasterises with its edge
    stepping back and forth by a tile; kerbs follow every step, and the edge
    came out as a row of teeth. A pavement tile with road on both sides of it
    along a line becomes road, and a road tile with pavement on both sides
    becomes pavement.
    """
    from . import native_pixels

    verge_pal = (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS)
    if native_pixels.smooth_road_edges(
        landscape, asphalt, C.PALE_CONCRETE, C.MEDIUM_GRASS, verge_pal
    ):
        return

    import numpy as np

    w, h = landscape.size
    strip = 1024
    for y0 in range(0, h, strip):
        y1 = min(h, y0 + strip)
        top, bottom = max(0, y0 - 1), min(h, y1 + 1)
        ground = np.asarray(landscape.crop((0, top, w, bottom))).copy()
        for _ in range(10):
            road = is_colour(ground, asphalt)
            pave = is_colour(ground, (C.PALE_CONCRETE,))
            verge = is_colour(ground, (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS))
            road_border = pave | verge
            notch = np.zeros_like(road)
            notch[1:-1, :] |= road[:-2, :] & road[2:, :]
            notch[:, 1:-1] |= road[:, :-2] & road[:, 2:]
            notch &= road_border
            notch |= _mark_two_tile_notches(road_border, road)
            border_count = np.zeros(road.shape, dtype=np.uint8)
            border_count[:, 1:] += road_border[:, :-1]
            border_count[:, :-1] += road_border[:, 1:]
            border_count[1:, :] += road_border[:-1, :]
            border_count[:-1, :] += road_border[1:, :]
            bump = np.zeros_like(road)
            bump[1:-1, :] |= road_border[:-2, :] & road_border[2:, :]
            bump[:, 1:-1] |= road_border[:, :-2] & road_border[:, 2:]
            bump |= border_count >= 3
            bump &= road
            bump |= _mark_two_tile_bumps(road, road_border, road)
            # A pavement tile with no pavement beside it orthogonally is one
            # step of a diagonal edge, and on its own it draws as a lip that
            # reads as a spike standing in the grass. It becomes the ground it
            # stands in, so a street that crosses the tile grid at an angle ends
            # with tarmac to grass, the way a road out of town does, instead of
            # a dotted line of slabs.
            ortho_count = np.zeros(pave.shape, dtype=np.uint8)
            ortho_count[:, 1:] += pave[:, :-1]
            ortho_count[:, :-1] += pave[:, 1:]
            ortho_count[1:, :] += pave[:-1, :]
            ortho_count[:-1, :] += pave[1:, :]
            near = ortho_count > 0
            diag_pave = np.zeros_like(pave)
            diag_pave[1:, 1:] |= pave[:-1, :-1]
            diag_pave[1:, :-1] |= pave[:-1, 1:]
            diag_pave[:-1, 1:] |= pave[1:, :-1]
            diag_pave[:-1, :-1] |= pave[1:, 1:]
            near_road = np.zeros_like(road)
            near_road[:, 1:] |= road[:, :-1]
            near_road[:, :-1] |= road[:, 1:]
            near_road[1:, :] |= road[:-1, :]
            near_road[:-1, :] |= road[1:, :]
            # Only a pavement tile with no pavement beside it at all is a lip
            # standing in the grass. A single step with a diagonal neighbour is
            # part of the band, and removing it is what stopped a sidewalk that
            # should have run on.
            lonep = pave & ~near & ~diag_pave
            # A break of a tile or two in a pavement run closes up, so a kerb
            # line reads as one line rather than stopping and starting. Only
            # beside a road: a gap out in the lawn is not a pavement.
            breaks_h = (_shifted(pave, 0, 1) | _shifted(pave, 0, 2)) & \
                       (_shifted(pave, 0, -1) | _shifted(pave, 0, -2))
            breaks_v = (_shifted(pave, 1, 0) | _shifted(pave, 2, 0)) & \
                       (_shifted(pave, -1, 0) | _shifted(pave, -2, 0))
            near_road2 = (_shifted(road, 1, 0) | _shifted(road, -1, 0) |
                          _shifted(road, 0, 1) | _shifted(road, 0, -1) |
                          _shifted(road, 2, 0) | _shifted(road, -2, 0) |
                          _shifted(road, 0, 2) | _shifted(road, 0, -2))
            mend = verge & (breaks_h | breaks_v) & near_road2
            # Shave 1-tile pavement spikes jutting into grass (3+ grass
            # neighbours) and fill 1-tile grass notches in a pavement edge
            # (3+ pavement neighbours).
            verge_count = np.zeros(pave.shape, dtype=np.uint8)
            verge_count[:, 1:] += verge[:, :-1]
            verge_count[:, :-1] += verge[:, 1:]
            verge_count[1:, :] += verge[:-1, :]
            verge_count[:-1, :] += verge[1:, :]
            pave_bump = (pave & (verge_count >= 3)) | _mark_two_tile_bumps(
                pave, verge, pave | road
            )
            pave_notch = (verge & (ortho_count >= 3)) | _mark_two_tile_notches(
                verge, pave
            )
            if not notch.any() and not bump.any() and not lonep.any() \
                    and not mend.any() and not pave_bump.any() \
                    and not pave_notch.any():
                break
            # A filled notch takes the tarmac of the road beside it.
            ys, xs = np.nonzero(notch)
            for y, x in zip(ys, xs):
                if y > 0 and road[y - 1, x]:
                    ground[y, x] = ground[y - 1, x]
                elif x > 0 and road[y, x - 1]:
                    ground[y, x] = ground[y, x - 1]
                elif y + 1 < road.shape[0] and road[y + 1, x]:
                    ground[y, x] = ground[y + 1, x]
                else:
                    ground[y, x] = ground[y, x + 1]
            bys, bxs = np.nonzero(bump)
            for y, x in zip(bys, bxs):
                ground[y, x] = C.PALE_CONCRETE
                for dy, dx in ((0, -1), (-1, 0), (0, 1), (1, 0)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < ground.shape[0] and 0 <= xx < ground.shape[1]:
                        if pave[yy, xx]:
                            ground[y, x] = C.PALE_CONCRETE
                            break
                        if verge[yy, xx]:
                            ground[y, x] = ground[yy, xx]
            if lonep.any():
                paved = {C.PALE_CONCRETE} | set(asphalt)
                lys, lxs = np.nonzero(lonep)
                for y, x in zip(lys, lxs):
                    ground[y, x] = C.MEDIUM_GRASS
                    for dy, dx in ((0, -1), (-1, 0), (0, 1), (1, 0)):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < ground.shape[0] and 0 <= xx < ground.shape[1]:
                            beside = tuple(ground[yy, xx])
                            if beside not in paved:
                                ground[y, x] = beside
                                break
            if mend.any() or pave_notch.any():
                mys, mxs = np.nonzero(mend | pave_notch)
                for y, x in zip(mys, mxs):
                    ground[y, x] = C.PALE_CONCRETE
            if pave_bump.any():
                pys, pxs = np.nonzero(pave_bump)
                for y, x in zip(pys, pxs):
                    ground[y, x] = C.MEDIUM_GRASS
                    for dy, dx in ((0, -1), (-1, 0), (0, 1), (1, 0)):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < ground.shape[0] and 0 <= xx < ground.shape[1] \
                                and verge[yy, xx]:
                            ground[y, x] = ground[yy, xx]
                            break
        rows = slice(y0 - top, y0 - top + (y1 - y0))
        landscape.paste(Image.fromarray(ground[rows]), (0, y0))






# --- railway ---------------------------------------------------------------

def paint_rails(draw, buckets: dict[str, list[OSMFeature]], proj: Projector, should_stop=None) -> None:
    """Lay connected vanilla straights, diagonals and bends along each track."""
    from .rails import rail_paths, paint_track

    for ring in rail_paths(buckets.get("railway", []), proj):
        paint_track(draw, ring, should_stop)


def _paint_kerbs(veg: Image.Image, landscape: Image.Image, asphalt, is_colour) -> None:
    """Paint straight and corner kerbs where pavement meets road."""
    from . import native_pixels

    kerb_for = {1: C.KERB_W, 2: C.KERB_N, 4: C.KERB_S, 8: C.KERB_E,
                3: C.KERB_NW, 5: C.KERB_SW, 10: C.KERB_NE, 12: C.KERB_SE}
    kerb_tuple = tuple(kerb_for[bits] for bits in (1, 2, 4, 8, 3, 5, 10, 12))
    if native_pixels.paint_kerbs(veg, landscape, asphalt, C.PALE_CONCRETE, kerb_tuple):
        return

    import numpy as np

    w, h = landscape.size
    strip = 1024
    for y0 in range(0, h, strip):
        y1 = min(h, y0 + strip)
        top, bottom = max(0, y0 - 1), min(h, y1 + 1)
        ground = np.asarray(landscape.crop((0, top, w, bottom)))
        road = is_colour(ground, asphalt)
        pave = is_colour(ground, (C.PALE_CONCRETE,))
        sides = np.zeros(road.shape, dtype=np.uint8)
        sides[:, 1:] |= road[:, :-1] * np.uint8(1)     # road to the west
        sides[1:, :] |= road[:-1, :] * np.uint8(2)     # road to the north
        sides[:-1, :] |= road[1:, :] * np.uint8(4)     # road to the south
        sides[:, :-1] |= road[:, 1:] * np.uint8(8)     # road to the east
        sides[~pave] = 0
        sides = _real_kerbs(sides)
        rows = slice(y0 - top, y0 - top + (y1 - y0))
        sides = sides[rows]
        existing = np.asarray(veg.crop((0, y0, w, y1)))
        free = (existing.reshape(-1, 3).max(axis=1) == 0).reshape(sides.shape)
        out = existing.copy()
        for bits, colour in kerb_for.items():
            out[(sides == bits) & free] = colour
        veg.paste(Image.fromarray(out), (0, y0))


def _paint_road_details(veg: Image.Image, landscape: Image.Image,
                        buckets: dict[str, list[OSMFeature]], proj: Projector) -> None:
    """Kerbs where pavement meets the road, and lines down two-lane roads.

    Asphalt ran straight into the pavement with nothing between them, and a
    road wider than a car had nothing painted on it. The vanilla map has both
    on every street - laid by hand - and without them a street reads as a grey
    patch rather than a road.
    """
    import numpy as np

    w, h = landscape.size
    asphalt = (C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT,
               C.DARK_POTHOLE, C.LIGHT_POTHOLE)

    def is_colour(ground, colours):
        mask = np.zeros(ground.shape[:2], dtype=bool)
        for colour in colours:
            same = ground[:, :, 0] == colour[0]
            same &= ground[:, :, 1] == colour[1]
            same &= ground[:, :, 2] == colour[2]
            mask |= same
        return mask

    _smooth_road_edges(landscape, asphalt, is_colour)
    _paint_kerbs(veg, landscape, asphalt, is_colour)

    # Crossings go down before the lane lines, which only paint on squares
    # nothing else has taken: a centre line drawn through a crossing is a line
    # nobody paints in a real street.
    paint_crossings(veg, landscape, buckets, proj)

    # Lane markings follow direction and lane count. Two-way traffic gets a
    # yellow separator; one-way and same-direction lanes use white dividers.
    # Diagonal segments are left plain because rasterizing their stripes would
    # make a tile-grid zigzag.
    mpt = proj.meters_per_tile
    marks = []
    for cat in ("road_major", "road_medium", "road_minor"):
        for feat in buckets.get(cat, []):
            if _is_polygon(feat):
                continue
            width = _way_width_m(feat, cat) / mpt
            markings = _road_markings(feat, cat)
            if not markings:
                continue
            for ring in _feature_coords_px(feat, proj):
                for (ax, ay), (bx, by) in zip(ring, ring[1:]):
                    dx, dy = bx - ax, by - ay
                    length = math.hypot(dx, dy)
                    if not length:
                        continue
                    nx, ny = -dy / length, dx / length
                    if abs(dy) <= 0.2 * abs(dx):
                        edge = "N"
                    elif abs(dx) <= 0.2 * abs(dy):
                        edge = "W"
                    else:
                        continue
                    for style, offset_m in markings:
                        ox, oy = nx * offset_m / mpt, ny * offset_m / mpt
                        marks.append((style, edge, ax + ox, ay + oy,
                                      bx + ox, by + oy, width))
    if not marks:
        return

    colour_for = {("yellow", "N"): C.LINE_YELLOW_N, ("yellow", "W"): C.LINE_YELLOW_W,
                  ("white", "N"): C.LINE_WHITE_N, ("white", "W"): C.LINE_WHITE_W}
    road = is_colour(np.asarray(landscape), asphalt)
    veg_arr = np.asarray(veg).copy()

    for style, edge, ax, ay, bx, by, width in marks:
        steps = int(max(abs(bx - ax), abs(by - ay)))
        t = np.linspace(0.0, 1.0, steps + 1) if steps else np.array([0.0])
        xs = np.rint(ax + (bx - ax) * t).astype(np.intp)
        ys = np.rint(ay + (by - ay) * t).astype(np.intp)
        keep = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        if style == "white":
            along = xs if edge == "N" else ys
            keep &= ((along // 3) % 2) == 0
        if not keep.any():
            continue
        xs, ys = xs[keep], ys[keep]
        if edge == "N":
            on_road = road[ys, xs] & (ys > 0) & road[np.maximum(0, ys - 1), xs]
        else:
            on_road = road[ys, xs] & (xs > 0) & road[ys, np.maximum(0, xs - 1)]
        if not on_road.any():
            continue
        xs, ys = xs[on_road], ys[on_road]
        run = np.zeros(len(xs), dtype=np.int32)
        for k in range(1, int(width) + 4):
            if edge == "N":
                run += np.where(ys >= k, road[np.maximum(0, ys - k), xs], 0)
                run += np.where(ys + k - 1 < h, road[np.minimum(h - 1, ys + k - 1), xs], 0)
            else:
                run += np.where(xs >= k, road[ys, np.maximum(0, xs - k)], 0)
                run += np.where(xs + k - 1 < w, road[ys, np.minimum(w - 1, xs + k - 1)], 0)
        ok = run <= width + 3
        if not ok.any():
            continue
        xs, ys = xs[ok], ys[ok]
        free = np.all(veg_arr[ys, xs] == C.VEG_NOTHING, axis=1)
        if free.any():
            veg_arr[ys[free], xs[free]] = colour_for[(style, edge)]
    veg.paste(Image.fromarray(veg_arr))


def _pave_dense_ground(landscape: Image.Image, building_feats: list[OSMFeature],
                       buckets: dict[str, list[OSMFeature]], proj: Projector) -> None:
    """Pave the unmapped ground of built-up city blocks.

    Land OSM says nothing about is painted as wild grass, which is right in the
    countryside and wrong in an old town, where it is courtyards, alleys and
    the gaps between blocks. Central Paris came out 77% meadow.

    The decision is made per city block - the ground the streets enclose - on
    how much of that block is under buildings. It used to be made per patch of
    ground on the density nearby, which near the threshold flickered between
    paved and grass across a single block and left it blotched like camouflage.
    A block is paved whole or not at all, as real ones are. Mapped parks,
    gardens and pitches keep their grass inside a paved block; a residential
    area's lawns do not, since between buildings packed this tight they are
    yards.
    """
    import numpy as np
    from shapely import STRtree
    from shapely.geometry import LineString, Polygon, box
    from shapely.ops import polygonize, unary_union

    w, h = landscape.size
    frame = box(0, 0, w, h)
    streets = []
    for cat in ("road_major", "road_medium", "road_minor", "road_service",
                "pedestrian"):
        for feat in buckets.get(cat, []):
            if feat.kind == "way" and not _is_polygon(feat):
                pts = [proj.to_px(la, lo) for la, lo in feat.geometry]
                if len(pts) >= 2:
                    streets.append(LineString(pts))
    if not streets:
        return
    blocks = [b.intersection(frame) for b in
              polygonize(unary_union(streets + [frame.exterior]))]
    blocks = [b for b in blocks if not b.is_empty and b.area > 50]

    footprints = []
    for feat in building_feats:
        for ring in _feature_coords_px(feat, proj):
            if len(ring) >= 3:
                poly = Polygon(ring)
                footprints.append(poly if poly.is_valid else poly.buffer(0))
    if not footprints:
        return
    tree = STRtree(footprints)

    paved = Image.new("L", (w, h), 0)
    pd = ImageDraw.Draw(paved)
    any_paved = False
    for block in blocks:
        covered = sum(footprints[i].intersection(block).area
                      for i in tree.query(block))
        if block.area > MAX_PAVED_BLOCK or covered / block.area < DENSE_COVERAGE:
            continue
        for part in getattr(block, "geoms", None) or [block]:
            if hasattr(part, "exterior"):
                pd.polygon(list(part.exterior.coords), fill=255)
                for hole in part.interiors:
                    pd.polygon(list(hole.coords), fill=0)
                any_paved = True
    if not any_paved:
        return

    keep = Image.new("L", (w, h), 0)
    kd = ImageDraw.Draw(keep)
    for cat in GREEN_CATEGORIES:
        for feat in buckets.get(cat, []):
            if _is_polygon(feat):
                for ring in _feature_coords_px(feat, proj):
                    if len(ring) >= 3:
                        kd.polygon(ring, fill=255)

    # Strip by strip, so the colour tests never hold the whole map at once.
    strip = 1024
    for y0 in range(0, h, strip):
        y1 = min(h, y0 + strip)
        mask = np.asarray(paved.crop((0, y0, w, y1))) > 0
        mask &= np.asarray(keep.crop((0, y0, w, y1))) == 0
        if not mask.any():
            continue
        ground = np.asarray(landscape.crop((0, y0, w, y1)))
        grass = np.zeros(mask.shape, dtype=bool)
        for colour in (C.DARK_GRASS, C.MEDIUM_GRASS):
            same = ground[:, :, 0] == colour[0]
            same &= ground[:, :, 1] == colour[1]
            same &= ground[:, :, 2] == colour[2]
            grass |= same
        mask &= grass
        if mask.any():
            paint = Image.new("RGB", (w, y1 - y0), C.PALE_CONCRETE)
            landscape.paste(paint, (0, y0), Image.fromarray(mask.astype(np.uint8) * 255))


def _weather_roads(landscape: Image.Image, proj: Projector) -> None:
    """Break up the tarmac with worn patches.

    Every road in a class is otherwise a single flat colour from kerb to kerb
    for its whole length, which is the main reason a generated town looks
    printed rather than driven on. Rules.txt has two pothole shades that blend
    into asphalt, so scattering small blots of them costs nothing in tiles and
    gives the surface some age.

    Patches go on asphalt only - they are skipped over grass, water, pavement
    and building footprints, so nothing outside the carriageway is touched.
    """
    import random

    asphalt = {C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT}
    px = landscape.load()
    rng = random.Random(20250913)
    # One patch per 1500 tiles of map. Denser than this and the roads read as
    # bombed rather than worn.
    attempts = max(1, (proj.width * proj.height) // 1500)
    for _ in range(attempts):
        cx = rng.randrange(proj.width)
        cy = rng.randrange(proj.height)
        if px[cx, cy] not in asphalt:
            continue
        shade = rng.choice((C.DARK_POTHOLE, C.LIGHT_POTHOLE))
        radius = rng.randint(1, 3)
        for y in range(max(0, cy - radius), min(proj.height, cy + radius + 1)):
            for x in range(max(0, cx - radius), min(proj.width, cx + radius + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 > radius * radius:
                    continue
                if px[x, y] in asphalt:
                    px[x, y] = shade
