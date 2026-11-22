import unittest

import numpy as np

from generator.osm import OSMFeature
from generator.rendering.infill import _drop_on_roads
from generator.rendering.projection import Projector

SOUTH, WEST = 40.0, 20.0
D = 400 / 111320.0
PROJ = Projector.build(SOUTH, WEST, SOUTH + D, WEST + D / np.cos(np.radians(SOUTH)), 1.0)


def at(x, y):
    return PROJ.to_latlon(x, y)


def box(ident, x0, y0, x1, y1):
    ring = [at(x0, y0), at(x1, y0), at(x1, y1), at(x0, y1), at(x0, y0)]
    return OSMFeature(osm_id=ident, kind="way", tags={"building": "house"}, geometry=ring)


def road():
    y = PROJ.height / 2
    return OSMFeature(osm_id=1, kind="way", tags={"highway": "residential"},
                      geometry=[at(10, y), at(PROJ.width - 10, y)])


class DropOnRoads(unittest.TestCase):
    def test_footprint_file_buildings_on_a_road_are_dropped(self):
        y = PROJ.height / 2
        across = box(-1_000_000_001, 100, y - 2, 112, y + 2)     # the road runs through it
        beside = box(-1_000_000_002, 130, y + 12, 142, y + 24)    # behind the pavement
        mapped = box(5, 150, y - 6, 162, y + 6)                   # OSM's own: never dropped
        infill = box(-2_000_000_001, 170, y - 6, 182, y + 6)      # infill checks itself
        feats = [across, beside, mapped, infill]
        kept, dropped = _drop_on_roads({"road_minor": [road()]}, feats, PROJ)
        self.assertEqual(dropped, 1)
        self.assertNotIn(across, kept)
        self.assertEqual(len(kept), 3)

    def test_nothing_changes_without_roads(self):
        feats = [box(-1_000_000_001, 100, 100, 112, 112)]
        kept, dropped = _drop_on_roads({}, feats, PROJ)
        self.assertEqual((dropped, kept), (0, feats))


if __name__ == "__main__":
    unittest.main()
