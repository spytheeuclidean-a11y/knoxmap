"""The Forest card's live preview."""
import io
import time
import unittest

import numpy as np
from PIL import Image

from app import app
from generator import pz_colors as C
from generator.rendering import forest_preview as P
from generator.rendering.forest_params import ForestParams


class Preview(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def picture(self, query=""):
        res = self.client.get(f"/api/forest-preview{query}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "image/png")
        return Image.open(io.BytesIO(res.data))

    def test_a_picture(self):
        self.assertEqual(self.picture("?forest_density=1").size, (2 * P.SIZE, 2 * P.SIZE))

    def test_bad_and_missing_values_still_draw(self):
        self.picture()
        self.picture("?forest_density=banana&forest_stand_m=-5&forest_edge_m=nan"
                     "&tree_density=99&forest_seed=x&forest_keep_meadows=7")

    def test_every_knob_in_the_card_reaches_it(self):
        base = self.picture().tobytes()
        for query in ("forest_density=2", "forest_thickets=3", "forest_stand_m=150",
                      "forest_stand_variety=1", "forest_edge_m=0", "forest_raggedness=1",
                      "forest_edge_wobble=0", "forest_spill_thick=1", "forest_keep_meadows=1",
                      "forest_seed=5", "forest_house_clearing_m=40", "forest_shrubland=3",
                      "tree_density=0.5"):
            with self.subTest(query=query):
                self.assertNotEqual(self.picture(f"?{query}").tobytes(), base)

    def test_cached(self):
        p = ForestParams()
        self.assertIs(P.preview_png(1.0, 1.0, p), P.preview_png(1.0, 1.0, p))

    def test_quick(self):
        t = time.perf_counter()
        P.preview_png(1.0, 1.0, ForestParams(seed=12345))
        self.assertLess(time.perf_counter() - t, 1.0)


class SampleLand(unittest.TestCase):
    def setUp(self):
        self.land, self.veg, self.rings = P.preview_layers(1.0, 1.0, ForestParams())

    def test_the_house_in_the_wood_is_in_a_clearing(self):
        (x0, y0), (x1, y1) = P.WOOD_HOUSE
        ring = np.zeros(self.veg.shape[:2], dtype=bool)
        # Inside the smallest clearing: 8 m less its wobble is about 5 m.
        ring[y0 - 4:y1 + 4, x0 - 4:x1 + 4] = True
        ring[y0:y1, x0:x1] = False
        trees = np.any(self.veg != 0, axis=2)
        self.assertLess(trees[ring].mean(), 0.1)

    def test_no_tree_on_the_road(self):
        self.assertFalse(np.any(self.veg[P.ROAD[0]:P.ROAD[1]] != 0))

    def test_woods_with_young_trees_and_undergrowth(self):
        for colour in (C.TREE_SMALL, C.BUSHES_TREES_DARK_GRASS, C.TREES_DARK_GRASS):
            with self.subTest(colour=colour):
                self.assertTrue(np.all(self.veg == colour, axis=2).any())


class BigTreesAndDrives(unittest.TestCase):
    def layers(self, params):
        from unittest import mock
        # The game's tree rules are not installed everywhere; pretend they are.
        with mock.patch("generator.rendering.vegetation.tree_rules_ready",
                        return_value=True):
            return P.preview_layers(1.0, 1.0, params)

    def big(self, veg):
        return sum(int(np.all(veg == colour, axis=2).sum()) for colour in C.BIG_TREE_ROOM)

    def test_big_trees_appear_and_the_knob_turns_them_off(self):
        _, veg, _ = self.layers(ForestParams())
        self.assertGreater(self.big(veg), 0)
        _, veg, _ = self.layers(ForestParams(big_trees=0))
        self.assertEqual(self.big(veg), 0)

    def test_the_house_in_the_wood_gets_a_drive(self):
        land, _, _ = P.preview_layers(1.0, 1.0, ForestParams())
        (x0, y0), (x1, y1) = P.WOOD_HOUSE
        near = land[y0 - 12:y1 + 12, x0 - 12:x1 + 12]
        self.assertTrue(np.all(near == C.DARK_ASPHALT, axis=2).any())

    def test_young_trees_leave_dark_ground_between_them(self):
        land, veg, _ = P.preview_layers(1.0, 1.0, ForestParams())
        img = np.asarray(P._from_above(land, veg, []).convert("RGB"))[::2, ::2]
        young = np.all(veg == C.TREE_SMALL, axis=2)
        self.assertGreater(young.sum(), 50)
        share = np.all(img[young] == P.YOUNG_RGB, axis=1).mean()
        self.assertLess(share, 0.7)
