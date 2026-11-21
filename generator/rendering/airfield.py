"""Runway markings: threshold piano keys, edge stripes, dashed centerline, aiming
points, touchdown zone bars, and taxiway hold-short bars.

Painted directly into the ground bitmap in pale concrete so markings rasterise
cleanly at any heading (including diagonal runways such as 05/23) rather than
turning into stair-stepped line tiles. Dimensions follow FAA AC 150/5340-1M /
ICAO Annex 14 proportions scaled to metres-per-tile.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Polygon

from .. import pz_colors as C
from ..osm import OSMFeature
from .geometry import _feature_coords_px, _is_polygon
from .projection import Projector
from .widths import RUNWAY_SHOULDER_M, road_width_tiles

# FAA/ICAO threshold bars ("piano keys"), symmetrical left and right of the
# centerline with a clear central gap.
THRESHOLD_STRIPE_M = 2.0        # width of each bar
THRESHOLD_LENGTH_M = 30.0       # length along the runway
THRESHOLD_GAP_M = 2.0           # gap between adjacent bars
THRESHOLD_CENTER_GAP_M = 3.0    # clear gap straddling the centerline
THRESHOLD_SET_BACK_M = 6.0      # inset from the very end of the strip

# Continuous runway side/edge stripes inset slightly from the asphalt border.
SIDE_STRIPE_M = 1.5
SIDE_INSET_M = 1.5

# Dashed runway centerline between the two threshold zones.
CENTERLINE_STRIPE_M = 1.5
CENTERLINE_DASH_M = 36.0
CENTERLINE_GAP_M = 24.0
CENTERLINE_CLEAR_M = THRESHOLD_SET_BACK_M + THRESHOLD_LENGTH_M + 12.0

# Aiming point bars (two broad white rectangles). Long runways place them at
# 300 m from each threshold; shorter regional strips (500-900 m) place them at
# 150 m so they still read clearly as an airfield.
AIM_FROM_THRESHOLD_M = 300.0
AIM_SHORT_FROM_THRESHOLD_M = 150.0
AIM_LENGTH_M = 45.0
AIM_STRIPE_M = 5.0
MIN_RUNWAY_FOR_AIM_M = 900.0
MIN_RUNWAY_FOR_SHORT_AIM_M = 500.0

# Touchdown zone pairs on long commercial runways (>= 1200 m).
TDZ_LENGTH_M = 22.5
TDZ_STRIPE_M = 2.5
MIN_RUNWAY_FOR_TDZ_M = 1200.0

# Two runway ends this close together are one runway split into two OSM ways.
JOIN_TOLERANCE_M = 40.0

# Runway asphalt surfaces where markings may land.
STRIP_COLOURS = (C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT)
MARKING_COLOUR = C.PALE_CONCRETE


def _polygon_runway_span(pts: list[tuple[float, float]]) -> tuple[tuple[float, float], tuple[float, float], float] | None:
    """Extract (start_px, end_px, width_px) from a polygon-mapped runway."""
    if len(pts) < 4:
        return None
    poly = Polygon(pts)
    if poly.is_empty or poly.area <= 0:
        return None
    rect = poly.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)
    if len(coords) < 5:
        return None
    e0 = (coords[1][0] - coords[0][0], coords[1][1] - coords[0][1])
    e1 = (coords[2][0] - coords[1][0], coords[2][1] - coords[1][1])
    l0 = math.hypot(*e0)
    l1 = math.hypot(*e1)
    if min(l0, l1) < 2.0:
        return None
    if l0 >= l1:
        a = ((coords[0][0] + coords[3][0]) / 2.0, (coords[0][1] + coords[3][1]) / 2.0)
        b = ((coords[1][0] + coords[2][0]) / 2.0, (coords[1][1] + coords[2][1]) / 2.0)
        return a, b, l1
    a = ((coords[0][0] + coords[1][0]) / 2.0, (coords[0][1] + coords[1][1]) / 2.0)
    b = ((coords[2][0] + coords[3][0]) / 2.0, (coords[2][1] + coords[3][1]) / 2.0)
    return a, b, l0


def _runway_segments(feats, proj) -> list[tuple[OSMFeature, tuple[float, float], tuple[float, float], float]]:
    """Return (feature, start_px, end_px, width_tiles) for line and polygon runways."""
    mpt = proj.meters_per_tile
    segs = []
    for feat in feats:
        rings = _feature_coords_px(feat, proj)
        if not rings or len(rings[0]) < 2:
            continue
        pts = rings[0]
        if _is_polygon(feat):
            span = _polygon_runway_span(pts)
            if span is None:
                continue
            a, b, w_px = span
            segs.append((feat, a, b, max(4.0, w_px)))
        else:
            w_tiles = float(road_width_tiles(feat, "runway", mpt))
            segs.append((feat, pts[0], pts[-1], w_tiles))
    return segs


def _runway_ends(feats, proj) -> list:
    """(feature, tip, inward unit vector, span_px, width_tiles) for every real runway end."""
    ends = []
    for feat, a, b, w_tiles in _runway_segments(feats, proj):
        dx, dy = b[0] - a[0], b[1] - a[1]
        span = math.hypot(dx, dy)
        if span < 0.5:
            continue
        ux, uy = dx / span, dy / span
        ends.append((feat, a, (ux, uy), span, w_tiles))
        ends.append((feat, b, (-ux, -uy), span, w_tiles))
    near = (JOIN_TOLERANCE_M / proj.meters_per_tile) ** 2
    out = []
    for i, end in enumerate(ends):
        tip = end[1]
        joined = any(
            j != i and (tip[0] - other[1][0]) ** 2 + (tip[1] - other[1][1]) ** 2 <= near
            for j, other in enumerate(ends))
        if not joined:
            out.append(end)
    return out


def _paint_hold_short_bars(draw: ImageDraw.ImageDraw,
                           buckets: dict[str, list[OSMFeature]],
                           proj: Projector,
                           runway_segs: list) -> None:
    """Paint transverse hold-short bars on taxiways just outside each runway edge."""
    taxiways = [f for f in buckets.get("taxiway", []) if not _is_polygon(f)]
    if not taxiways or not runway_segs:
        return
    mpt = proj.meters_per_tile
    hold_thick = max(1, int(round(1.5 / mpt)))
    hold_gap = max(2.0, (RUNWAY_SHOULDER_M + 4.0) / mpt)
    for tw in taxiways:
        rings = _feature_coords_px(tw, proj)
        if not rings or len(rings[0]) < 2:
            continue
        pts = rings[0]
        tw_w = max(4.0, float(road_width_tiles(tw, "taxiway", mpt))) * 0.45
        for tip, nbr in ((pts[0], pts[1]), (pts[-1], pts[-2])):
            tdx, tdy = nbr[0] - tip[0], nbr[1] - tip[1]
            tlen = math.hypot(tdx, tdy)
            if tlen < 2.0:
                continue
            tux, tuy = tdx / tlen, tdy / tlen
            tpx, tpy = -tuy, tux
            for _feat, a, b, rw_w in runway_segs:
                rdx, rdy = b[0] - a[0], b[1] - a[1]
                rlen2 = rdx * rdx + rdy * rdy
                if rlen2 < 1.0:
                    continue
                t = ((tip[0] - a[0]) * rdx + (tip[1] - a[1]) * rdy) / rlen2
                if not (-0.02 <= t <= 1.02):
                    continue
                cx, cy = a[0] + t * rdx, a[1] + t * rdy
                dist = math.hypot(tip[0] - cx, tip[1] - cy)
                if dist <= rw_w * 0.5 + hold_gap:
                    # Step back along the taxiway just past the runway shoulder.
                    step = max(0.0, (rw_w * 0.5 + hold_gap) - dist)
                    hx = tip[0] + tux * step
                    hy = tip[1] + tuy * step
                    p0 = (hx - tpx * tw_w, hy - tpy * tw_w)
                    p1 = (hx + tpx * tw_w, hy + tpy * tw_w)
                    draw.line([p0, p1], fill=255, width=hold_thick)
                    break


def paint_runway_markings(landscape: Image.Image,
                          buckets: dict[str, list[OSMFeature]],
                          proj: Projector) -> int:
    """Paint threshold piano keys, side stripes, dashed centerline, aiming
    points, touchdown zones, and taxiway hold-short bars. Returns tiles painted."""
    feats = list(buckets.get("runway", []))
    if not feats:
        return 0
    mpt = proj.meters_per_tile
    w, h = landscape.size
    ground = np.asarray(landscape.convert("RGB"))
    on_strip = np.zeros(ground.shape[:2], dtype=bool)
    for colour in STRIP_COLOURS:
        on_strip |= np.all(ground == colour, axis=2)
    if not on_strip.any():
        return 0

    def tiles(metres: float, least: int = 1) -> int:
        return max(least, int(round(metres / mpt)))

    marks = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(marks)

    def stripe(tip, along, across, out_m: float, from_m: float, run_m: float,
               thick: int) -> None:
        """One bar: `out_m` to the side of the centre, `from_m` in from the end."""
        ox, oy = across[0] * out_m / mpt, across[1] * out_m / mpt
        a = (tip[0] + ox + along[0] * from_m / mpt,
             tip[1] + oy + along[1] * from_m / mpt)
        b = (a[0] + along[0] * run_m / mpt, a[1] + along[1] * run_m / mpt)
        draw.line([a, b], fill=255, width=thick)

    segs = _runway_segments(feats, proj)

    # 1. Full-length side/edge stripes and dashed centerline on each runway segment.
    side_thick = tiles(SIDE_STRIPE_M)
    cl_thick = tiles(CENTERLINE_STRIPE_M)
    for _feat, a, b, w_tiles in segs:
        dx, dy = b[0] - a[0], b[1] - a[1]
        span_px = math.hypot(dx, dy)
        if span_px < 1.0:
            continue
        along = (dx / span_px, dy / span_px)
        across = (-along[1], along[0])
        span_m = span_px * mpt
        half_w_m = (w_tiles * mpt) / 2.0

        # Side edge stripes inset inside the dark asphalt borders.
        edge_out_m = max(0.0, half_w_m - SIDE_INSET_M - SIDE_STRIPE_M / 2.0)
        if edge_out_m >= 3.0 and span_m > 2 * THRESHOLD_SET_BACK_M:
            for side in (-1, 1):
                stripe(a, along, across, side * edge_out_m,
                       THRESHOLD_SET_BACK_M,
                       span_m - 2 * THRESHOLD_SET_BACK_M, side_thick)

        # Dashed centerline between the two threshold zones.
        pos_m = CENTERLINE_CLEAR_M
        end_m = span_m - CENTERLINE_CLEAR_M
        while pos_m + CENTERLINE_DASH_M * 0.5 <= end_m:
            dash_len = min(CENTERLINE_DASH_M, end_m - pos_m)
            stripe(a, along, across, 0.0, pos_m, dash_len, cl_thick)
            pos_m += CENTERLINE_DASH_M + CENTERLINE_GAP_M

    # 2. Threshold piano keys, aiming point bars, and touchdown zone markers.
    key_thick = tiles(THRESHOLD_STRIPE_M)
    aim_thick = tiles(AIM_STRIPE_M, 2)
    tdz_thick = tiles(TDZ_STRIPE_M, 1)
    for _feat, tip, along, span_px, w_tiles in _runway_ends(feats, proj):
        across = (-along[1], along[0])
        width_m = w_tiles * mpt
        half_m = width_m / 2.0 - SIDE_INSET_M - SIDE_STRIPE_M - THRESHOLD_STRIPE_M * 0.5
        step_m = THRESHOLD_STRIPE_M + THRESHOLD_GAP_M
        # Symmetrical left/right piano keys leaving a clean central gap.
        start_out = (THRESHOLD_CENTER_GAP_M + THRESHOLD_STRIPE_M) / 2.0
        out_m = start_out
        while out_m <= half_m + 0.01:
            for side in (-1, 1):
                stripe(tip, along, across, side * out_m, THRESHOLD_SET_BACK_M,
                       THRESHOLD_LENGTH_M, key_thick)
            out_m += step_m

        span_m = span_px * mpt
        aim_offset_m = max(4.5, min(width_m * 0.27, half_m - AIM_STRIPE_M * 0.5))
        if span_m >= MIN_RUNWAY_FOR_AIM_M:
            for side in (-1, 1):
                stripe(tip, along, across, side * aim_offset_m,
                       AIM_FROM_THRESHOLD_M, AIM_LENGTH_M, aim_thick)
        elif span_m >= MIN_RUNWAY_FOR_SHORT_AIM_M:
            for side in (-1, 1):
                stripe(tip, along, across, side * aim_offset_m,
                       AIM_SHORT_FROM_THRESHOLD_M, AIM_LENGTH_M * 0.75, aim_thick)

        if span_m >= MIN_RUNWAY_FOR_TDZ_M:
            tdz_dists = [150.0] + ([450.0] if span_m >= 1500.0 else [])
            for dist_m in tdz_dists:
                for side in (-1, 1):
                    stripe(tip, along, across, side * aim_offset_m,
                           dist_m, TDZ_LENGTH_M, tdz_thick)

    # 3. Taxiway hold-short bars where taxiways meet runways.
    _paint_hold_short_bars(draw, buckets, proj, segs)

    painted = (np.asarray(marks) > 0) & on_strip
    count = int(painted.sum())
    if count:
        out = ground.copy()
        out[painted] = MARKING_COLOUR
        landscape.paste(Image.fromarray(out))
    return count
