"""The window's menu bar (static/js/shell.js) and what the Tools menu opens.

A menu with no items is a dead button: `MENUS` builds the bar and a matching
`fillMenu` case fills it, and the two are separate lists that can drift. The
Tools menu is the map developer's way in to the extract picker and the check.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class MenuBar(unittest.TestCase):
    def setUp(self):
        self.shell = read("static", "js", "shell.js")

    def menus(self) -> list[str]:
        found = re.search(r"const MENUS = \[([^\]]+)\]", self.shell)
        self.assertIsNotNone(found, "the menu bar is built from MENUS")
        return re.findall(r"'([^']+)'", found.group(1))

    def test_tools_sits_between_build_and_help(self):
        menus = self.menus()
        self.assertEqual(menus[-3:], ["Build", "Tools", "Help"])

    def test_every_menu_has_items(self):
        for name in self.menus():
            with self.subTest(menu=name):
                self.assertRegex(self.shell, rf"\n\s+{name}: \(\) =>",
                                 f"no fillMenu case for {name}")

    def test_the_tools_menu_opens_the_extract_tool(self):
        self.assertIn("check an openstreetmap extract", self.shell.lower())
        self.assertIn("$('toolsBody')", self.shell)

    def test_the_panel_it_opens_is_in_the_page(self):
        for element in ("pbfFile", "pbfBrowse", "pbfUse", "pbfClear", "pbfCheck",
                        "pbfReport", "toolsBody"):
            with self.subTest(element=element):
                self.assertEqual(read("templates", "index.html").count(f'id="{element}"'), 1)

    def test_the_panel_hides_outside_the_dialog(self):
        css = read("static", "css", "app.css")
        self.assertIn("#toolsBody { display: none; }", css)
        self.assertIn(".ws-dialog #toolsBody { display: block; }", css)


if __name__ == "__main__":
    unittest.main()
