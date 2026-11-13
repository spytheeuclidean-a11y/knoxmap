"""The Forest card: its table in settings.js, its labels and their translations."""
import re
import unittest
from pathlib import Path

from dataclasses import fields

from knoxbuild.settings import LIMITS, Settings

ROOT = Path(__file__).resolve().parent.parent
# The page's scripts, split across static/js/ (the settings tables are in
# settings.js), read as one.
APP = "\n".join(p.read_text(encoding="utf-8")
                for p in sorted((ROOT / "static" / "js").glob("*.js")))
MAIN = ["forest_density", "forest_thickets", "forest_stand_m", "forest_stand_variety",
        "forest_edge_m"]
ADVANCED = [
    ("Shape", ["forest_raggedness", "forest_edge_wobble", "forest_spill_thick",
               "forest_keep_meadows", "forest_seed"]),
    ("Around the woods", ["forest_house_clearing_m", "forest_big_trees", "forest_groves",
                          "forest_wild_growth", "forest_shrubland"]),
    ("Everywhere", ["tree_density", "landcover", "winter_look"]),
]
UI_LINES = ["Forest", "Reset", "Advanced", "Shape", "Around the woods", "Everywhere",
            "Not shown in the picture.", "About {setting}"]


def block(name):
    m = re.search(rf"const {name} = \{{(.*?)\n\}};", APP, re.S)
    assert m, f"{name} not found in static/js/"
    return m.group(1)


class ForestCard(unittest.TestCase):
    def test_the_table(self):
        groups = block("SETTING_GROUPS")
        main = re.search(r"main: \[(.*?)\]", groups, re.S).group(1)
        self.assertEqual(re.findall(r"'(\w+)'", main), MAIN)
        for title, keys in ADVANCED:
            m = re.search(rf"\['{title}', \[(.*?)\]\]", groups, re.S)
            self.assertIsNotNone(m, title)
            self.assertEqual(re.findall(r"'(\w+)'", m.group(1)), keys)

    def test_every_key_is_a_labelled_setting(self):
        labels = block("SETTING_LABELS")
        known = Settings().to_dict()
        for key in MAIN + [k for _, ks in ADVANCED for k in ks]:
            with self.subTest(key=key):
                self.assertIn(key, known)
                self.assertRegex(labels, rf"\n  {key}:\s+\[")

    def test_translated(self):
        labels = block("SETTING_LABELS")
        wanted = list(UI_LINES)
        for key in [k for k in Settings().to_dict() if k.startswith("forest_")]:
            m = re.search(rf"\n  {key}:\s+\['((?:[^'\\]|\\.)*)', '((?:[^'\\]|\\.)*)'\]", labels)
            self.assertIsNotNone(m, key)
            wanted += [m.group(1).replace("\\'", "'"), m.group(2).replace("\\'", "'")]
        for lang in ("english", "espanol", "portugues_brasil", "russian"):
            text = (ROOT / "lang" / f"{lang}.txt").read_text(encoding="utf-8")
            keys = {line.split(" = ", 1)[0] for line in text.splitlines() if " = " in line}
            for line in wanted:
                with self.subTest(lang=lang, line=line):
                    self.assertIn(line, keys)

    def test_old_preview_wiring_gone(self):
        self.assertNotIn("FOREST_PREVIEW_KEYS", APP)
        self.assertNotIn("addForestPreview", APP)


class SliderSteps(unittest.TestCase):
    def test_every_float_default_is_a_position_the_slider_can_hold(self):
        # The same rule as floatStep in settingElement: a browser snaps a value
        # to the nearest step, so a default off the grid is changed on load.
        defaults = Settings()
        for f in fields(Settings):
            value = getattr(defaults, f.name)
            if f.name not in LIMITS or isinstance(value, (bool, int, str)):
                continue
            lo, hi = LIMITS[f.name]
            step = 0.01 if hi - lo <= 1 else 0.05
            with self.subTest(setting=f.name):
                n = (value - lo) / step
                self.assertLess(abs(n - round(n)) * step, 1e-9)
        self.assertIn("hi - lo <= 1 ? 0.01 : 0.05", APP)
