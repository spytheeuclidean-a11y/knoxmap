"""WorldCover through the whole renderer: OSM wins, the rest grows by class."""
import contextlib
import io
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator import renderer
from generator.osm import OSMFeature
from generator.rendering import landcover as L
from generator.rendering.projection import Projector

SOUTH, WEST, NORTH, EAST = 40.0, -85.0, 40.0040, -84.9948


def latlon(proj, fx, fy):
    """The lat/lon of a fraction of the way across and down the map."""
    lat = NORTH - (NORTH - SOUTH) * fy
    lon = WEST + (EAST - WEST) * fx
    return lat, lon


def box(proj, x0, y0, x1, y1):
    pts = [latlon(proj, x0, y0), latlon(proj, x1, y0), latlon(proj, x1, y1),
           latlon(proj, x0, y1)]
    return pts + [pts[0]]


def features(proj):
    return [
        OSMFeature(1, "way", {"highway": "residential"},
                   [latlon(proj, 0.0, 0.5), latlon(proj, 1.0, 0.5)]),
        OSMFeature(2, "way", {"landuse": "residential"}, box(proj, 0.05, 0.05, 0.4, 0.4)),
        OSMFeature(3, "way", {"landuse": "farmland"}, box(proj, 0.6, 0.05, 0.95, 0.4)),
    ]


def grid_for(width, height):
    grid = np.full((height, width), 30, dtype="uint8")
    grid[:, : width // 2] = 10
    grid[height // 2:, width // 2:] = 40
    return grid


def render(landcover_for):
    proj = Projector.build(SOUTH, WEST, NORTH, EAST, 1.0, 0.0)
    out = tempfile.mkdtemp()
    with contextlib.redirect_stdout(io.StringIO()):
        renderer.render(features(proj), SOUTH, WEST, NORTH, EAST, meters_per_tile=1.0,
                        output_dir=out, map_name="wc", landcover_for=landcover_for)
    land = np.asarray(Image.open(os.path.join(out, "wc.bmp")).convert("RGB"))
    veg = np.asarray(Image.open(os.path.join(out, "wc_veg.bmp")).convert("RGB"))
    return proj, land, veg


def is_(arr, *colours):
    out = np.zeros(arr.shape[:2], dtype=bool)
    for colour in colours:
        out |= np.all(arr == colour, axis=2)
    return out


def region(proj, x0, y0, x1, y1):
    (la0, lo0), (la1, lo1) = latlon(proj, x0, y0), latlon(proj, x1, y1)
    px0, py0 = proj.to_px(la0, lo0)
    px1, py1 = proj.to_px(la1, lo1)
    return slice(int(py0), int(py1)), slice(int(px0), int(px1))


class RenderWorldCoverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proj, cls.land, cls.veg = render(grid_for)

    def test_no_marker_left(self):
        self.assertFalse(is_(self.land, *L.MARKER.values()).any())

    def test_tree_cover_is_a_wood(self):
        ys, xs = region(self.proj, 0.05, 0.6, 0.45, 0.95)
        trees = is_(self.veg[ys, xs], C.TREES, C.TREES_DARK_GRASS, C.SPARSE_TREES,
                    C.TREE_BIG, C.TREE_HUGE, C.TREE_GIANT, C.TREE_SMALL)
        self.assertGreater(trees.mean(), 0.5)

    def test_osm_residential_is_not_a_wood(self):
        ys, xs = region(self.proj, 0.1, 0.1, 0.35, 0.35)
        trees = is_(self.veg[ys, xs], C.TREES, C.TREES_DARK_GRASS)
        self.assertLess(trees.mean(), 0.2)
        self.assertTrue(is_(self.land[ys, xs], C.MEDIUM_GRASS).mean() > 0.5)

    def test_cropland_and_osm_farmland_are_fields(self):
        for area in ((0.6, 0.6, 0.95, 0.95), (0.65, 0.1, 0.9, 0.35)):
            ys, xs = region(self.proj, *area)
            furrow = is_(self.land[ys, xs], C.DIRT_ROWS_H, C.DIRT_ROWS_V)
            self.assertGreater(furrow.mean(), 0.3, area)

    def test_road_stays_clear(self):
        road = is_(self.land, C.MEDIUM_ASPHALT, C.DARKEST_ASPHALT,
                   C.DARK_POTHOLE, C.LIGHT_POTHOLE)
        # The road runs edge to edge of the bbox (the map is padded to whole
        # cells past it): no field or wood cut it.
        self.assertGreater(road.mean(axis=1).max(), 0.7)
        grown = is_(self.veg, C.CORN_1, C.CORN_2, C.TREES, C.TREES_DARK_GRASS,
                    C.SPARSE_TREES, C.BUSHES, C.ROCKS, C.BOULDERS)
        self.assertFalse((grown & road).any())

    def test_broken_landcover_still_renders(self):
        def broken(w, h):
            raise RuntimeError("no data")
        _, land, _ = render(broken)
        self.assertFalse(is_(land, *L.MARKER.values()).any())


if __name__ == "__main__":
    unittest.main()
