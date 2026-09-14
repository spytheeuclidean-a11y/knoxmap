"""What a building's surroundings say about it.

OSM describes a few buildings well and the rest barely at all. The ones it does
describe say a lot about their neighbours: a street where every mapped block is
six storeys tall is not lined with bungalows in between, and a quarter packed
wall to wall with buildings is not the place for a log cabin. This looks at all
the footprints at once, before any building is placed, so each untagged one
can borrow what its neighbours make plain.
"""
from __future__ import annotations

import math

import numpy as np

# Coverage is measured on a coarse grid and averaged over a 3x3 window of it,
# so a building sees roughly the 120 m around it - a block or two. Distances
# here are real metres, whatever the map's scale: the question is what the
# street is like, not how many tiles it became.
DENSITY_CELL_M = 40
# Share of the ground under buildings. Measured on real places: central
# Paris, Kadikoy and a Tokyo neighbourhood put most buildings at 0.4-0.5;
# Levittown and a French village both sit around 0.16, so density cannot tell
# a suburb from a village - but it does pick out the farmstead or the house at
# the end of the lane, below SPARSE, which is where a log cabin belongs.
DENSE = 0.28
SPARSE = 0.06

# Wall styles that belong only in some places. A log cabin or a trailer in the
# middle of a city reads as a mistake at first glance, and clapboard or timber
# framing looks lost among blocks of flats.
RURAL_ONLY = {"logs", "trailer"}
NOT_DENSE = {"clapboard", "timber", "siding_blue", "siding_yellow", "siding_green",
             "siding_pink", "siding_grey"}

# Tagged heights count within this distance of a building, and only when
# enough of them agree to be a pattern rather than one tower.
NEIGHBOUR_RADIUS_M = 120
NEIGHBOUR_SAMPLES = 4


class Context:
    def __init__(self, width: int, height: int,
                 buildings: list[tuple[float, float, float, int | None]],
                 metres_per_tile: float = 1.0):
        """`buildings` holds (centre x, centre y, area in tiles, storeys or None)."""
        self.cell = max(1.0, DENSITY_CELL_M / metres_per_tile)
        self.radius = NEIGHBOUR_RADIUS_M / metres_per_tile
        gw = max(1, math.ceil(width / self.cell))
        gh = max(1, math.ceil(height / self.cell))
        covered = np.zeros((gh, gw), dtype=float)
        for x, y, area, _levels in buildings:
            gx = min(gw - 1, max(0, int(x // self.cell)))
            gy = min(gh - 1, max(0, int(y // self.cell)))
            covered[gy, gx] += area
        # 3x3 window sums, divided by the ground each window really spans so
        # the map's edges are not read as empty countryside.
        padded = np.pad(covered, 1)
        ground = np.pad(np.ones_like(covered), 1)
        sums = sum(padded[dy:dy + gh, dx:dx + gw] for dy in range(3) for dx in range(3))
        spans = sum(ground[dy:dy + gh, dx:dx + gw] for dy in range(3) for dx in range(3))
        self.coverage = np.clip(sums / (spans * self.cell * self.cell), 0, 1)

        tagged = [(x, y, lv) for x, y, _a, lv in buildings if lv is not None]
        self._tagged = np.array(tagged, dtype=float).reshape(-1, 3)

    def density(self, x: float, y: float) -> float:
        gh, gw = self.coverage.shape
        gx = min(gw - 1, max(0, int(x // self.cell)))
        gy = min(gh - 1, max(0, int(y // self.cell)))
        return float(self.coverage[gy, gx])

    def neighbour_levels(self, x: float, y: float) -> float | None:
        """Median tagged storey count nearby, or None when too few say."""
        if len(self._tagged) < NEIGHBOUR_SAMPLES:
            return None
        d2 = (self._tagged[:, 0] - x) ** 2 + (self._tagged[:, 1] - y) ** 2
        near = self._tagged[d2 <= self.radius ** 2, 2]
        if len(near) < NEIGHBOUR_SAMPLES:
            return None
        return float(np.median(near))


def style_fits(style_name: str, density: float) -> bool:
    if style_name in RURAL_ONLY:
        return density < SPARSE
    if style_name in NOT_DENSE:
        return density < DENSE
    return True
