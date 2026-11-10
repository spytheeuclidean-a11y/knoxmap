"""Forests with stands, thin patches and clearings, thinning to their edge."""
import unittest

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator.rendering import forest_shape as F

N = 400


def forest(edge=0, size=N):
    """A square forest painted the woodland pass's way, `edge` tiles of meadow
    round it, and its mask."""
    land = Image.new("RGB", (size, size), C.MEDIUM_GRASS)
    veg = Image.new("RGB", (size, size), C.VEG_NOTHING)
    mask = np.zeros((size, size), dtype=bool)
    mask[edge:size - edge, edge:size - edge] = True
    v = np.array(veg)
    v[mask] = C.TREES
    g = np.array(land)
    g[mask] = C.DARK_GRASS
    return Image.fromarray(g, "RGB"), Image.fromarray(v, "RGB"), mask


def grade_of(veg):
    arr = np.asarray(veg)
    out = np.full(arr.shape[:2], -1)
    for i, c in enumerate(F.GRADES):
        out[np.all(arr == c, axis=2)] = i
    return out


class Shares(unittest.TestCase):
    def test_table(self):
        self.assertEqual(F.shares(0), (1.0, 0.0, 0.0, 0.0))
        self.assertEqual(F.shares(1), (0.10, 0.15, 0.25, 0.50))
        self.assertEqual(F.shares(3), (0.0, 0.0, 0.10, 0.90))
        for a, b in zip(F.shares(0.75), (0.25, 0.20, 0.225, 0.325)):
            self.assertAlmostEqual(a, b)
        self.assertEqual(F.shares(9), F.shares(3))
        self.assertEqual(F.shares(-1), F.shares(0))


class ShapeForest(unittest.TestCase):
    def test_shares_come_out_as_asked(self):
        for density in (0.5, 1.0, 2.0):
            land, veg, mask = forest()
            F.shape_forest(veg, land, mask, density, 60, 0, 1.0)
            g = grade_of(veg)[mask]
            want = F.shares(density)
            for i in range(4):
                with self.subTest(density=density, grade=i):
                    self.assertAlmostEqual((g == i).mean(), want[i], delta=0.02)

    def test_density_zero_leaves_no_trees(self):
        land, veg, mask = forest()
        F.shape_forest(veg, land, mask, 0.0, 60, 6, 1.0)
        self.assertTrue((grade_of(veg)[mask] == 0).all())

    def test_outside_the_forest_and_scrub_untouched(self):
        land, veg, mask = forest(edge=20)
        v = np.array(veg)
        v[100, 100] = C.BUSHES_TREES_DARK_GRASS
        v[5, 5] = C.BUSHES
        veg = Image.fromarray(v, "RGB")
        before_land = np.asarray(land).copy()
        F.shape_forest(veg, land, mask, 1.0, 60, 6, 1.0)
        after = np.asarray(veg)
        self.assertEqual(tuple(after[100, 100]), C.BUSHES_TREES_DARK_GRASS)
        self.assertEqual(tuple(after[5, 5]), C.BUSHES)
        self.assertTrue((np.asarray(land)[~mask] == before_land[~mask]).all())

    def test_trees_stand_on_dark_grass(self):
        land, veg, mask = forest()
        g = np.array(land)
        g[mask] = C.MEDIUM_GRASS
        land = Image.fromarray(g, "RGB")
        F.shape_forest(veg, land, mask, 1.0, 60, 6, 1.0)
        trees = grade_of(veg) > 0
        self.assertTrue(np.all(np.asarray(land)[trees] == C.DARK_GRASS))

    def test_water_in_a_forest_stays_water(self):
        land, veg, mask = forest()
        g = np.array(land)
        g[50:60, 50:60] = C.WATER
        land = Image.fromarray(g, "RGB")
        v = np.array(veg)
        v[50:60, 50:60] = C.VEG_NOTHING
        veg = Image.fromarray(v, "RGB")
        F.shape_forest(veg, land, mask, 3.0, 60, 6, 1.0)
        self.assertTrue((grade_of(veg)[50:60, 50:60] == 0).all())
        self.assertTrue(np.all(np.asarray(land)[50:60, 50:60] == C.WATER))

    def test_bigger_stands_make_bigger_clumps(self):
        def clump(stand):
            land, veg, mask = forest()
            F.shape_forest(veg, land, mask, 1.0, stand, 0, 1.0)
            dense = grade_of(veg) == 3
            # Mean length of runs of dense along rows.
            runs = []
            for row in dense[::10]:
                edges = np.diff(np.concatenate(([0], row.astype(int), [0])))
                starts, ends = np.nonzero(edges == 1)[0], np.nonzero(edges == -1)[0]
                runs += list(ends - starts)
            return np.mean(runs)
        self.assertGreater(clump(160), 1.5 * clump(30))

    def test_edges_are_thinner_than_the_middle(self):
        land, veg, mask = forest()
        F.shape_forest(veg, land, mask, 1.0, 20, 20, 1.0)
        g = grade_of(veg)
        # The map's own border is not a forest edge: the forest runs on past it.
        land, veg2, mask2 = forest(edge=40)
        F.shape_forest(veg2, land, mask2, 1.0, 20, 20, 1.0)
        g2 = grade_of(veg2)
        band = np.zeros_like(mask2)
        band[40:50, 40:360] = True
        middle = np.zeros_like(mask2)
        middle[150:250, 150:250] = True
        self.assertLess(g2[band].mean(), g2[middle].mean() - 0.3)
        self.assertGreaterEqual(g[:10].mean(), g[150:250, 150:250].mean() - 0.3)

    def test_no_edge_effect_at_zero(self):
        land, veg, mask = forest(edge=40)
        # Small stands, so a ten-tile strip spans many of them.
        F.shape_forest(veg, land, mask, 1.0, 20, 0, 1.0)
        g = grade_of(veg)
        band = g[40:50, 40:360]
        middle = g[150:250, 150:250]
        self.assertLess(abs(band.mean() - middle.mean()), 0.3)

    def test_deterministic(self):
        a = forest()
        b = forest()
        F.shape_forest(a[1], a[0], a[2], 1.0, 60, 6, 1.0)
        F.shape_forest(b[1], b[0], b[2], 1.0, 60, 6, 1.0)
        self.assertEqual(a[1].tobytes(), b[1].tobytes())


if __name__ == "__main__":
    unittest.main()
