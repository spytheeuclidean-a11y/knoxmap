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
        self.assertEqual(F.shares(1), (0.0, 0.28, 0.62, 0.10))
        self.assertEqual(F.shares(3), (0.0, 0.05, 0.55, 0.40))
        for a, b in zip(F.shares(0.75), (0.0, 0.465, 0.475, 0.06)):
            self.assertAlmostEqual(a, b)
        self.assertEqual(F.shares(9), F.shares(3))
        self.assertEqual(F.shares(-1), F.shares(0))


class Navigable(unittest.TestCase):
    def test_default_forest_is_mostly_passable(self):
        # Dense grade is a tree on every tile; at the default at least nine
        # tiles in ten of a forest stay passable, and never most of it at max.
        self.assertLessEqual(F.shares(1)[3], 0.10)
        self.assertLess(F.shares(3)[3], 0.5)


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
        # Past the fringe (Edge softness out, 6 tiles here) nothing changes.
        far = ~mask
        far[20 - 6:N - 20 + 6, 20 - 6:N - 20 + 6] = False
        self.assertTrue((np.asarray(land)[far] == before_land[far]).all())

    def test_trees_stand_on_dark_grass(self):
        land, veg, mask = forest()
        g = np.array(land)
        g[mask] = C.MEDIUM_GRASS
        land = Image.fromarray(g, "RGB")
        F.shape_forest(veg, land, mask, 1.0, 60, 6, 1.0)
        g = grade_of(veg)
        ground = np.asarray(land)
        # Every tree in the wood, sparse ones too, stands on its dark floor.
        self.assertTrue(np.all(ground[mask & (g >= 1)] == C.DARK_GRASS))
        # Thinned right down, the bare patches are meadow, not dark floor.
        land, veg, mask = forest()
        F.shape_forest(veg, land, mask, 0.25, 60, 6, 1.0)
        g = grade_of(veg)
        self.assertTrue((mask & (g == 0)).any())
        self.assertTrue(np.all(np.asarray(land)[mask & (g == 0)] == C.MEDIUM_GRASS))

    def test_no_clearings_are_invented(self):
        # From half density up, every tile of a wood keeps trees: lower density
        # thins it, it never opens it.
        for density in (0.5, 1.0, 2.0, 3.0):
            land, veg, mask = forest(edge=40)
            F.shape_forest(veg, land, mask, density, 60, 20, 1.0)
            with self.subTest(density=density):
                self.assertFalse((grade_of(veg)[mask] == 0).any())

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

    def test_the_edge_does_not_carve_into_the_wood(self):
        # Edge softness only spills the wood outwards: every tile inside it is
        # graded exactly as it would be with no edge at all.
        land, veg, mask = forest(edge=40)
        F.shape_forest(veg, land, mask, 1.0, 20, 20, 1.0)
        land0, veg0, mask0 = forest(edge=40)
        F.shape_forest(veg0, land0, mask0, 1.0, 20, 0, 1.0)
        self.assertTrue((grade_of(veg)[mask] == grade_of(veg0)[mask]).all())

    def test_no_bare_ring_inside_the_edge(self):
        # The wood thins steadily across its edge: the tiles just inside it are
        # never barer than the fringe just outside, and most of them not bare.
        land, veg, mask = forest(edge=60, size=600)
        F.shape_forest(veg, land, mask, 1.0, 60, 12, 1.0)
        g = grade_of(veg)
        din, dout = F.edge_depth(mask, 12), F.edge_depth(~mask, 12)
        bare = [(g[mask & (din >= a) & (din < b)] == 0).mean() for a, b in
                ((0, 3), (3, 6), (9, 12))]
        outside = (g[~mask & (dout < 3)] == 0).mean()
        self.assertLess(bare[0], 0.65)
        self.assertLess(bare[0], outside)
        self.assertGreaterEqual(bare[0] + 0.02, bare[1])
        self.assertGreaterEqual(bare[1] + 0.02, bare[2])

    def test_no_edge_effect_at_zero(self):
        land, veg, mask = forest(edge=40)
        # Small stands, so a ten-tile strip spans many of them.
        F.shape_forest(veg, land, mask, 1.0, 20, 0, 1.0)
        g = grade_of(veg)
        # The whole ten-tile ring against the whole inside: one strip against
        # one square is too little forest, and differs by a third of a grade
        # anywhere in it once the grades are spread evenly.
        inside = np.zeros_like(mask)
        inside[50:350, 50:350] = True
        ring = mask & ~inside
        self.assertLess(abs(g[ring].mean() - g[inside & mask].mean()), 0.15)

    def test_fringe_spills_out_and_fades(self):
        land, veg, mask = forest(edge=60)
        counts = F.shape_forest(veg, land, mask, 1.0, 20, 12, 1.0)
        v = np.asarray(veg)
        planted = ~mask & np.any(v != 0, axis=2)
        self.assertGreater(counts["fringe"], 0)
        self.assertEqual(int(planted.sum()), counts["fringe"])
        # Thick beside the wood, thinning out, and none past Edge softness.
        near = planted[60 - 3:60, 60:340].mean()
        mid = planted[60 - 9:60 - 6, 60:340].mean()
        self.assertGreater(near, mid)
        self.assertGreater(near, 0.3)
        self.assertFalse(planted[:60 - 12].any())
        # Thick fringe trees stand on dark grass, as the wood's do; outside the
        # wood it never closes into a wall.
        g = grade_of(veg)
        self.assertTrue(np.all(np.asarray(land)[planted & (g >= 2)] == C.DARK_GRASS))
        self.assertFalse((planted & (g == 3)).any())

    def test_fringe_keeps_off_fields_roads_and_edges_at_zero(self):
        land, veg, mask = forest(edge=60)
        g = np.array(land)
        g[:60, :200] = C.LIGHT_GRASS          # a field beside the wood
        g[:60, 260:264] = (100, 100, 100)     # a road running up to it
        land = Image.fromarray(g, "RGB")
        F.shape_forest(veg, land, mask, 1.0, 20, 12, 1.0)
        planted = ~mask & np.any(np.asarray(veg) != 0, axis=2)
        self.assertFalse(planted[:60, :200].any())
        self.assertFalse(planted[:60, 258:266].any())
        self.assertTrue(planted[:60, 280:340].any())
        land, veg, mask = forest(edge=60)
        self.assertEqual(F.shape_forest(veg, land, mask, 1.0, 20, 0, 1.0)["fringe"], 0)
        land, veg, mask = forest(edge=60)
        self.assertEqual(F.shape_forest(veg, land, mask, 0.0, 20, 12, 1.0)["fringe"], 0)

    def test_deterministic(self):
        a = forest()
        b = forest()
        F.shape_forest(a[1], a[0], a[2], 1.0, 60, 6, 1.0)
        F.shape_forest(b[1], b[0], b[2], 1.0, 60, 6, 1.0)
        self.assertEqual(a[1].tobytes(), b[1].tobytes())


if __name__ == "__main__":
    unittest.main()
