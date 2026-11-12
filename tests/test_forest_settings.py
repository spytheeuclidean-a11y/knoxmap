"""The forest knobs: settings, limits, and the params the renderer gets."""
import dataclasses
import inspect
import unittest

import app
from generator import renderer
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


if __name__ == "__main__":
    unittest.main()
