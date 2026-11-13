"""The settings' tabs: SETTING_GROUPS in settings.js places every setting once."""
import re
import unittest
from pathlib import Path

from knoxbuild.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
APP = "\n".join(p.read_text(encoding="utf-8")
                for p in sorted((ROOT / "static" / "js").glob("*.js")))
TABS = ["map", "gameplay", "roads", "buildings", "land", "forest"]
UI_LINES = ["Map", "Gameplay", "Roads", "Buildings", "Land", "Forest", "Other", "Settings",
            "Advanced", "Reset", "Changed from the defaults for this kind of place"]
LANGS = ("english", "espanol", "portugues_brasil", "russian")


def block(name):
    m = re.search(rf"const {name} = \{{(.*?)\n\}};", APP, re.S)
    assert m, f"{name} not found in static/js/"
    return m.group(1)


def tabs():
    """{name: (title, [keys in order], [subheads])} as the table writes them."""
    out = {}
    for m in re.finditer(r"\n  (\w+): \{(.*?)\n  \},", block("SETTING_GROUPS"), re.S):
        body = m.group(2)
        title = re.search(r"title: '([^']+)'", body).group(1)
        subheads = re.findall(r"\['([^']+)', \[", body)
        keys = [k for k in re.findall(r"'(\w+)'", re.sub(r"part: '\w+'", "", body))
                if k not in (title,) and k not in subheads]
        out[m.group(1)] = (title, keys, subheads)
    return out


def translations(lang):
    text = (ROOT / "lang" / f"{lang}.txt").read_text(encoding="utf-8")
    return {line.split(" = ", 1)[0] for line in text.splitlines() if " = " in line}


class SettingTabs(unittest.TestCase):
    def test_the_tabs_in_order(self):
        self.assertEqual(list(tabs()), TABS)

    def test_every_labelled_setting_is_in_exactly_one_tab(self):
        labelled = re.findall(r"\n  (\w+):\s*\[", block("SETTING_LABELS"))
        placed = [k for _, keys, _ in tabs().values() for k in keys]
        self.assertEqual(sorted(placed), sorted(set(placed)), "a setting is in two places")
        known = Settings().to_dict()
        live = [k for k in labelled if k in known]
        self.assertEqual(sorted(set(live) - set(placed)), [],
                         "these would fall into the Other tab")
        self.assertEqual(sorted(set(placed) - set(labelled)), [], "unlabelled setting in a tab")

    def test_tab_names_and_subheads_are_translated(self):
        wanted = set(UI_LINES)
        for title, _, subheads in tabs().values():
            wanted |= {title, *subheads}
        for lang in LANGS:
            with self.subTest(lang=lang):
                self.assertEqual(sorted(wanted - translations(lang)), [])

    def test_the_page_fields_are_parts_of_tabs(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        parts = re.findall(r'class="tab-part" data-part="(\w+)"', html)
        self.assertEqual(parts, ["map"])
        named = re.findall(r"part: '(\w+)'", block("SETTING_GROUPS"))
        self.assertEqual(named, parts)
        # No collapser left around the settings, and no second terrain switch.
        self.assertNotIn('<details id="advanced"', html)
        self.assertNotIn("terrainOnlyToggle", html + APP)

    def test_search_reaches_the_tabs(self):
        self.assertIn("new CustomEvent('listsearch'", APP)
        self.assertIn("addEventListener('listsearch'", APP)


if __name__ == "__main__":
    unittest.main()
