"""The forest knobs: settings, limits, and the params the renderer gets."""
import dataclasses
import inspect
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import app
from generator import renderer
from generator.osm import OSMFeature
from generator.rendering.forest_params import FIELD_FOR_SETTING, ForestParams
from knoxbuild.settings import LIMITS, Settings

NEW = {
    "forest_thickets": (1.0, (0.0, 3.0)),
    "forest_stand_variety": (0.0, (0.0, 1.0)),
    "forest_raggedness": (0.25, (0.0, 1.0)),
    "forest_edge_wobble": (0.4, (0.0, 1.0)),
    "forest_spill_thick": (0.4, (0.0, 1.0)),
    "forest_keep_meadows": (0.33, (0.0, 1.0)),
    "forest_seed": (2207, (0, 999999)),
    "forest_house_clearing_m": (20, (0, 40)),
    "forest_big_trees": (1.0, (0.0, 3.0)),
    "forest_groves": (1.0, (0.0, 3.0)),
    "forest_wild_growth": (1.0, (0.0, 3.0)),
    "forest_shrubland": (1.0, (0.0, 3.0)),
}


class ForestSettings(unittest.TestCase):
    def test_defaults_and_limits(self):
        for key, (default, limits) in NEW.items():
            with self.subTest(key=key):
                self.assertEqual(getattr(Settings(), key), default)
                self.assertEqual(LIMITS[key], limits)

    def test_clamped(self):
        high = Settings.from_dict({k: 1e9 for k in NEW})
        low = Settings.from_dict({k: -1e9 for k in NEW})
        for key in NEW:
            with self.subTest(key=key):
                self.assertEqual(getattr(high, key), LIMITS[key][1])
                self.assertEqual(getattr(low, key), LIMITS[key][0])

    def test_all_redraw_the_map(self):
        for key in NEW:
            self.assertIn(key, app.RENDER_SETTINGS)

    def test_params_cover_every_forest_setting(self):
        fields = {f.name for f in dataclasses.fields(ForestParams)}
        self.assertEqual(set(FIELD_FOR_SETTING.values()), fields)
        self.assertEqual(set(FIELD_FOR_SETTING), set(NEW) | {"forest_stand_m", "forest_edge_m"})

    def test_param_defaults_are_the_setting_defaults(self):
        s, p = Settings(), ForestParams()
        for key, field in FIELD_FOR_SETTING.items():
            with self.subTest(key=key):
                self.assertEqual(getattr(p, field), getattr(s, key))

    def test_params_are_hashable(self):
        # The preview caches by them.
        self.assertEqual(hash(ForestParams()), hash(ForestParams()))

    def test_render_takes_them(self):
        self.assertIn("forest_params", inspect.signature(renderer.render).parameters)


class AroundTheWoods(unittest.TestCase):
    """render() hands each pass its knob."""

    def test_each_pass_gets_its_knob(self):
        seen = {}

        def spy(name, real):
            def call(*args, **kwargs):
                seen[name] = kwargs
                return real(*args, **kwargs)
            return call

        lat0, lon0, m = 40.0, 20.0, 1 / 111320
        house = [(lat0 + y * m, lon0 + x * m * 1.31) for x, y in
                 ((60, 60), (75, 60), (75, 72), (60, 72), (60, 60))]
        feats = [OSMFeature(1, "way", {"building": "house"}, house)]
        grid = lambda w, h, bounds=None: np.full((h, w), 10, np.uint8)
        fp = ForestParams(house_clearing_m=31, big_trees=2.5, groves=0.5,
                          wild_growth=1.5, shrubland=2.0)
        names = ("clear_homesteads", "_plant_big_trees", "_paint_groves",
                 "_paint_wild_growth", "plant_landcover")
        patches = [patch.object(renderer, n, spy(n, getattr(renderer, n))) for n in names]
        for p in patches:
            p.start()
        try:
            with tempfile.TemporaryDirectory() as out:
                renderer.render(feats, lat0, lon0, lat0 + 150 * m, lon0 + 150 * m * 1.31,
                                1.0, out, "t", tree_density=1.0, forest_density=1.0,
                                forest_params=fp, landcover_for=grid)
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(seen["clear_homesteads"]["clear_max_m"], 31)
        self.assertEqual(seen["_plant_big_trees"]["wood_mult"], 2.5)
        self.assertAlmostEqual(seen["_paint_groves"]["density"], 0.5)
        self.assertAlmostEqual(seen["_paint_wild_growth"]["density"], 1.5)
        self.assertAlmostEqual(seen["plant_landcover"]["density"], 2.0)


if __name__ == "__main__":
    unittest.main()
