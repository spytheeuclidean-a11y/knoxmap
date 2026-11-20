"""Runway markings: the piano keys at each end, and the bars beyond them.

A runway with nothing on it but a centre line is a very wide road, and
standing on one you cannot tell an airfield from a dual carriageway. The
threshold bars settle it: a block of thick stripes across the full width at
each end, the one marking an airfield has that nothing else does.

They are not laid as line tiles. The game ships painted lines for the north
and west edge of a square and none on the diagonal, so a runway at 45
degrees - which is where half of them land once the grid has them - would
get a dashed zigzag or nothing at all. These are painted into the ground
itself as the pale concrete the shoulders use, which rasterises at any angle
the way a road does, and reads from the ground as paint on the strip.

Real dimensions, to scale: a threshold stripe is 1.75 m wide and 30 m long
with a 1.75 m gap, set back 6 m from the end; the aiming point is a pair of
bars 300 m in. They are in metres and divided by the map's scale at the last
moment, so a 1 m map gets the real thing and a coarse one gets the widest
stripe that is still a stripe.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from .. import pz_colors as C
from ..osm import OSMFeature
from .geometry import _feature_coords_px, _is_polygon
from .projection import Projector
from .widths import road_width_tiles

# Wider than the real thing, on purpose. A real threshold stripe is 1.75 m,
# which at 2 m a tile is one tile and reads from above as a fine hatch and
# from the ground as nothing much. The game's own world is not to real scale
# either - its streets are half as wide again as the ones they stand for -
# so these are scaled to match: four on, four off, which lands on whole
# tiles at 1 m and at 2 m and is legible at both.
THRESHOLD_STRIPE_M = 4.0        # wide
THRESHOLD_LENGTH_M = 45.0       # along the runway
THRESHOLD_GAP_M = 4.0           # between stripes
THRESHOLD_SET_BACK_M = 6.0      # from the very end of the strip
# The pair of bars a pilot aims at, well down the strip. A short field has
# none: they would be painted over the threshold they are measured from.
AIM_FROM_THRESHOLD_M = 300.0
AIM_LENGTH_M = 60.0
AIM_STRIPE_M = 8.0
AIM_OFFSET_M = 10.5             # each bar, from the centre line
MIN_RUNWAY_FOR_AIM_M = 900.0
# Two runway ends this close together are one runway split into two ways, not
# two thresholds: OpenStreetMap breaks a way wherever a tag changes.
JOIN_TOLERANCE_M = 40.0
# What the markings are painted on. The strip is asphalt; its shoulder is
# already this colour, so a bar that ran onto it would be invisible anyway.
STRIP_COLOURS = (C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT)
MARKING_COLOUR = C.PALE_CONCRETE


def _runway_ends(feats, proj) -> list:
    """(feature, tip, inward unit vector, span) for every real runway end."""
    ends = []
    for feat in feats:
        rings = _feature_coords_px(feat, proj)
        if not rings or len(rings[0]) < 2:
            continue
        pts = rings[0]
        span = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
        for tip, inward in ((pts[0], pts[1]), (pts[-1], pts[-2])):
            dx, dy = inward[0] - tip[0], inward[1] - tip[1]
            length = math.hypot(dx, dy)
            if length < 0.5:
                continue
            ends.append((feat, tip, (dx / length, dy / length), span))
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


def paint_runway_markings(landscape: Image.Image,
                          buckets: dict[str, list[OSMFeature]],
                          proj: Projector) -> int:
    """Paint the threshold bars and aiming points. Returns the tiles painted."""
    feats = [f for f in buckets.get("runway", []) if not _is_polygon(f)]
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

    for feat, tip, along, span in _runway_ends(feats, proj):
        across = (-along[1], along[0])
        width_tiles = road_width_tiles(feat, "runway", mpt)
        thick = tiles(THRESHOLD_STRIPE_M)
        step_m = THRESHOLD_STRIPE_M + THRESHOLD_GAP_M
        half_m = (width_tiles * mpt) / 2.0 - THRESHOLD_STRIPE_M
        out_m = -half_m
        while out_m <= half_m + 0.01:
            stripe(tip, along, across, out_m, THRESHOLD_SET_BACK_M,
                   THRESHOLD_LENGTH_M, thick)
            out_m += step_m
        if span * mpt < MIN_RUNWAY_FOR_AIM_M:
            continue
        for side in (-1, 1):
            stripe(tip, along, across, side * AIM_OFFSET_M,
                   AIM_FROM_THRESHOLD_M, AIM_LENGTH_M, tiles(AIM_STRIPE_M, 2))

    painted = (np.asarray(marks) > 0) & on_strip
    count = int(painted.sum())
    if count:
        out = ground.copy()
        out[painted] = MARKING_COLOUR
        landscape.paste(Image.fromarray(out))
    return count
