"""Tests for clustered forest generation (issue #116)."""
import unittest
from types import SimpleNamespace

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator.osm import OSMFeature
from generator.rendering import vegetation
from knoxbuild.settings import Settings


PROJ = SimpleNamespace(meters_per_tile=1.0, to_px=lambda lat, lon: (lon, lat))


def _forest_feature(w: int = 120, h: int = 120) -> list[OSMFeature]:
    return [
        OSMFeature(
            1,
            "way",
            {"landuse": "forest"},
            [(0, 0), (0, w), (h, w), (h, 0), (0, 0)],
        )
    ]


class ForestClusteringTests(unittest.TestCase):
    def test_openness_creates_stands_sparse_patches_and_clearings(self):
        veg = Image.new("RGB", (120, 120), C.VEG_NOTHING)
        land = Image.new("RGB", (120, 120), C.MEDIUM_GRASS)
        vegetation._paint_woodland(
            veg, land, _forest_feature(), PROJ,
            density=1.0, clustering=24.0, openness=0.3, edge_softness=2, seed=7,
        )
        arr = np.asarray(veg)
        colours = {tuple(c) for c in arr.reshape(-1, 3)}
        self.assertIn(C.TREES, colours)
        self.assertIn(C.TREES_DARK_GRASS, colours)
        self.assertIn(C.SPARSE_TREES, colours)
        self.assertIn(C.VEG_NOTHING, colours)

    def test_zero_openness_keeps_interior_uniform(self):
        veg = Image.new("RGB", (80, 80), C.VEG_NOTHING)
        land = Image.new("RGB", (80, 80), C.MEDIUM_GRASS)
        vegetation._paint_woodland(
            veg, land, _forest_feature(80, 80), PROJ,
            density=1.0, openness=0.0, edge_softness=2, seed=7,
        )
        arr = np.asarray(veg)[10:70, 10:70]
        self.assertTrue(np.all(arr == C.TREES))

    def test_higher_openness_produces_more_open_and_sparse_tiles(self):
        counts = []
        for openness in (0.15, 0.55):
            veg = Image.new("RGB", (120, 120), C.VEG_NOTHING)
            land = Image.new("RGB", (120, 120), C.MEDIUM_GRASS)
            vegetation._paint_woodland(
                veg, land, _forest_feature(), PROJ,
                density=1.0, clustering=20.0, openness=openness, edge_softness=2, seed=11,
            )
            arr = np.asarray(veg)[10:110, 10:110]
            open_or_sparse = (
                np.all(arr == C.VEG_NOTHING, axis=2)
                | np.all(arr == C.SPARSE_TREES, axis=2)
            )
            counts.append(int(open_or_sparse.sum()))
        self.assertLess(counts[0], counts[1])

    def test_edge_softness_controls_border_band_width(self):
        inset = [OSMFeature(1, "way", {"landuse": "forest"},
                            [(5, 5), (5, 75), (75, 75), (75, 5), (5, 5)])]
        veg_sharp = Image.new("RGB", (80, 80), C.VEG_NOTHING)
        land_sharp = Image.new("RGB", (80, 80), C.MEDIUM_GRASS)
        vegetation._paint_woodland(
            veg_sharp, land_sharp, inset, PROJ,
            density=1.0, openness=0.0, edge_softness=0, seed=1,
        )
        veg_soft = Image.new("RGB", (80, 80), C.VEG_NOTHING)
        land_soft = Image.new("RGB", (80, 80), C.MEDIUM_GRASS)
        vegetation._paint_woodland(
            veg_soft, land_soft, inset, PROJ,
            density=1.0, openness=0.0, edge_softness=5, seed=1,
        )
        # Pixel (8, 40) is 3 tiles inside the (5..75) polygon: inside the 5-tile border band.
        self.assertEqual(veg_sharp.getpixel((8, 40)), C.TREES)
        self.assertEqual(veg_soft.getpixel((8, 40)), C.TREES_DARK_GRASS)

    def test_forest_pattern_is_seeded_deterministically(self):
        outputs = []
        for seed in (42, 42, 99):
            veg = Image.new("RGB", (100, 100), C.VEG_NOTHING)
            land = Image.new("RGB", (100, 100), C.MEDIUM_GRASS)
            vegetation._paint_woodland(
                veg, land, _forest_feature(100, 100), PROJ,
                density=1.0, clustering=24.0, openness=0.3, edge_softness=3, seed=seed,
            )
            outputs.append(veg.tobytes())
        self.assertEqual(outputs[0], outputs[1])
        self.assertNotEqual(outputs[0], outputs[2])

    def test_settings_clamp_new_forest_knobs(self):
        s = Settings.from_dict({
            "forest_clustering": 500,
            "forest_openness": 2.0,
            "forest_edge_softness": -3,
        })
        self.assertEqual(s.forest_clustering, 120.0)
        self.assertEqual(s.forest_openness, 0.9)
        self.assertEqual(s.forest_edge_softness, 0)
