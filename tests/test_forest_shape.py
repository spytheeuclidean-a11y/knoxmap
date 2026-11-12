"""Forests with stands, thin patches and clearings, thinning to their edge."""
import hashlib
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator.rendering import forest_shape as F
from generator.rendering.forest_params import ForestParams

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
            with patch.object(F, "UNDERGROWTH_SHARE", 0.0):   # bushes are not a grade
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


# What shape_forest drew for forest(edge=40) at density 1, stand 60 m, edge
# 20 m before any of its constants were knobs. The defaults have to keep it.
TODAY = "c07f5ea5a5c98cf9d708f69c6a91ee9ba393fc83fc835c8b27f38e79a07ee589"


def fingerprint(veg, land):
    return hashlib.sha256(np.asarray(veg).tobytes() + np.asarray(land).tobytes()).hexdigest()


class Knobs(unittest.TestCase):
    def shaped(self, **params):
        land, veg, mask = forest(edge=40)
        p = ForestParams(**{"keep_meadows": 1.0, **params})
        # Undergrowth (Task 4) is new on purpose; the fingerprint predates it.
        with patch.object(F, "UNDERGROWTH_SHARE", 0.0, create=True):
            F.shape_forest(veg, land, mask, 1.0, 60, 20, 1.0, p)
        return land, veg, mask

    def test_defaults_reproduce_todays_woods(self):
        land, veg, _ = self.shaped()
        self.assertEqual(fingerprint(veg, land), TODAY)

    def test_no_params_is_the_defaults(self):
        land, veg, mask = forest(edge=40)
        with patch.object(F, "UNDERGROWTH_SHARE", 0.0, create=True):
            F.shape_forest(veg, land, mask, 1.0, 60, 20, 1.0)
        a = fingerprint(veg, land)
        land, veg, mask = forest(edge=40)
        with patch.object(F, "UNDERGROWTH_SHARE", 0.0, create=True):
            F.shape_forest(veg, land, mask, 1.0, 60, 20, 1.0, ForestParams())
        self.assertEqual(a, fingerprint(veg, land))

    def test_thickets_scale_the_dense_share(self):
        self.assertEqual(F.shares(1, 1.0), F.shares(1))
        self.assertEqual(F.shares(1, 2.0), (0.0, 0.28, 0.52, 0.20))
        self.assertEqual(F.shares(1, 0.0), (0.0, 0.28, 0.72, 0.0))
        self.assertEqual(F.shares(3, 3.0), (0.0, 0.05, 0.05, 0.9))
        for d in (0.5, 1, 2, 3):
            for t in (0, 0.5, 1, 2, 3):
                self.assertAlmostEqual(sum(F.shares(d, t)), 1.0)

    def test_thickets_reach_the_wood(self):
        _, veg, mask = self.shaped(thickets=2.0)
        self.assertAlmostEqual((grade_of(veg)[mask] == 3).mean(), 0.20, delta=0.02)

    def test_stand_variety_mixes_stand_sizes(self):
        def spread(variety):
            land, veg, mask = forest()
            F.shape_forest(veg, land, mask, 1.0, 30, 0, 1.0,
                           ForestParams(stand_variety=variety, keep_meadows=1.0))
            dense = (grade_of(veg) == 3).astype(float)
            # Dense share in 40-tile blocks: big stands make some blocks
            # mostly dense and others empty.
            blocks = dense.reshape(10, 40, 10, 40).mean(axis=(1, 3))
            return blocks.std()
        self.assertGreater(spread(1.0), spread(0.0) * 1.3)

    def test_the_other_knobs_change_the_woods(self):
        land, veg, _ = self.shaped()
        base = fingerprint(veg, land)
        for knob, value in (("raggedness", 0.8), ("edge_wobble", 0.0),
                            ("spill_thick", 0.9), ("seed", 1)):
            with self.subTest(knob=knob):
                land, veg, _ = self.shaped(**{knob: value})
                self.assertNotEqual(fingerprint(veg, land), base)

    def test_no_spill_thickness_means_single_trees(self):
        land, veg, mask = forest(edge=60)
        F.shape_forest(veg, land, mask, 1.0, 20, 12, 1.0,
                       ForestParams(spill_thick=0.0, keep_meadows=1.0))
        self.assertFalse((~mask & (grade_of(veg) >= 2)).any())


def meadow_in_a_wood(width=30, size=400):
    """A wood with a meadow `width` tiles wide across its middle, and a
    300-tile field east of it."""
    land, veg, mask = forest(size=size)
    mask[:, 100:] = False                   # the field
    mid = 50
    mask[:, mid - width // 2:mid + width - width // 2] = False   # the meadow
    v = np.array(veg); g = np.array(land)
    v[~mask] = C.VEG_NOTHING; g[~mask] = C.MEDIUM_GRASS
    return Image.fromarray(g, "RGB"), Image.fromarray(v, "RGB"), mask, mid


class KeepMeadowsOpen(unittest.TestCase):
    def grown(self, keep):
        land, veg, mask, mid = meadow_in_a_wood()
        F.shape_forest(veg, land, mask, 1.0, 20, 30, 1.0, ForestParams(keep_meadows=keep))
        return grade_of(veg) > 0, mask, mid

    def test_a_small_meadow_keeps_its_middle(self):
        trees, _, mid = self.grown(0.33)
        self.assertLess(trees[:, mid - 3:mid + 3].mean(), 0.05)

    def test_off_fills_it(self):
        trees, _, mid = self.grown(1.0)
        self.assertGreater(trees[:, mid - 3:mid + 3].mean(), 0.15)

    def test_a_big_field_gets_the_full_spill(self):
        a, _, _ = self.grown(0.33)
        b, _, _ = self.grown(1.0)
        # 8-12 tiles into the 300-tile field east of the wood.
        self.assertAlmostEqual(a[:, 108:112].mean(), b[:, 108:112].mean(), delta=0.03)

    def test_zero_grows_no_spill(self):
        trees, mask, _ = self.grown(0.0)
        self.assertFalse((trees & ~mask).any())


TREE_GRADES = (C.SPARSE_TREES, C.TREES_DARK_GRASS, C.TREES)


def is_colour(veg, *colours):
    arr = np.asarray(veg)
    out = np.zeros(arr.shape[:2], dtype=bool)
    for c in colours:
        out |= np.all(arr == c, axis=2)
    return out


class YoungGrowthAndUndergrowth(unittest.TestCase):
    def grown(self, young_trees=True):
        land, veg, mask = forest(edge=40)
        counts = F.shape_forest(veg, land, mask, 1.0, 60, 20, 1.0, young_trees=young_trees)
        return veg, mask, counts

    def test_young_trees_are_a_share_of_the_trees(self):
        veg, mask, counts = self.grown()
        young = is_colour(veg, C.TREE_SMALL)
        trees = is_colour(veg, C.TREE_SMALL, C.BUSHES_TREES_DARK_GRASS, *TREE_GRADES)
        self.assertAlmostEqual(young[mask].sum() / trees[mask].sum(), F.YOUNG_SHARE, delta=0.02)
        self.assertEqual(counts["young"], int(young.sum()))

    def test_undergrowth_is_a_share_of_the_thin_wood(self):
        veg, mask, counts = self.grown()
        under = is_colour(veg, C.BUSHES_TREES_DARK_GRASS)
        thin = is_colour(veg, C.BUSHES_TREES_DARK_GRASS, C.SPARSE_TREES, C.TREES_DARK_GRASS)
        self.assertAlmostEqual(under[mask].sum() / thin[mask].sum(), F.UNDERGROWTH_SHARE, delta=0.02)
        self.assertEqual(counts["undergrowth"], int(under.sum()))

    def test_only_inside_the_wood(self):
        veg, mask, _ = self.grown()
        self.assertFalse((is_colour(veg, C.TREE_SMALL, C.BUSHES_TREES_DARK_GRASS) & ~mask).any())

    def test_young_growth_keeps_the_tiles_with_a_tree(self):
        def with_a_tree(young):
            veg, mask, _ = self.grown(young)
            return is_colour(veg, C.TREE_SMALL, C.BUSHES_TREES_DARK_GRASS, *TREE_GRADES)[mask].sum()
        self.assertEqual(with_a_tree(True), with_a_tree(False))

    def test_no_young_trees_without_their_rules(self):
        veg, _, counts = self.grown(young_trees=False)
        self.assertFalse(is_colour(veg, C.TREE_SMALL).any())
        self.assertEqual(counts["young"], 0)


if __name__ == "__main__":
    unittest.main()
