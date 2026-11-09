"""The window and the server must agree about where a map stops being easy.

`static/js/app.js` repeats a handful of numbers from `web/checks.py` so the
page can say what a big map costs before anything is sent - a browser cannot
import a Python module. The copy is a promise, and until now nothing checked
it: if one side moved, the note under the size readout would describe a limit
the server does not enforce (or the server would enforce one the page never
mentions) and every test would still pass.

This reads both files and compares them. It is a plain parse of the `const`
lines rather than a browser run, so it needs no Node, no server and no map.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from web import checks

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "js" / "app.js"

# The numbers the page mirrors on purpose, and the only ones compared. Anything
# else the page declares is the page's own business: SLOW_ABOVE_KM2, for one,
# has no server twin - it decides when to add a word to the note, not whether
# the server will accept a map.
SHARED = (
    "BIG_AREA_KM2",
    "BIG_TILES_PER_SIDE",
    "BIG_LANDMARK_KM2",
    "OVERPASS_TILE_KM2",
    "BUILD_BYTES_PER_TILE",
    "BUILD_BASE_BYTES",
)

CONSTANT = re.compile(r"^const\s+([A-Z][A-Z0-9_]*)\s*=\s*(-?[0-9.]+(?:e[0-9]+)?)\s*;")


def page_constants() -> dict[str, float]:
    """Every numeric `const NAME = value;` in app.js, by name."""
    out = {}
    for line in APP_JS.read_text(encoding="utf-8").splitlines():
        match = CONSTANT.match(line.strip())
        if match:
            out[match.group(1)] = float(match.group(2))
    return out


class ThePageMirrorsTheServer(unittest.TestCase):
    def setUp(self):
        self.page = page_constants()

    def test_every_shared_limit_is_declared_on_both_sides(self):
        for name in SHARED:
            with self.subTest(name=name):
                self.assertIn(name, self.page, f"{name} is gone from app.js")
                self.assertTrue(hasattr(checks, name), f"{name} is gone from web/checks.py")

    def test_the_values_are_the_same(self):
        for name in SHARED:
            with self.subTest(name=name):
                self.assertEqual(self.page[name], getattr(checks, name),
                                 f"app.js and web/checks.py disagree about {name}")

    def test_the_page_does_not_restate_another_server_limit(self):
        # The other direction: a number the page copies under a name nobody
        # listed above would drift just as silently. Anything numeric in both
        # files is compared, whether or not it is in SHARED.
        for name, value in self.page.items():
            server = getattr(checks, name, None)
            if isinstance(server, (int, float)):
                with self.subTest(name=name):
                    self.assertEqual(value, float(server),
                                     f"app.js and web/checks.py disagree about {name}")

    def test_every_mirrored_limit_is_actually_used(self):
        # A constant that is declared and never read is the other half of the
        # same mistake: the copy would look maintained while the note ignored
        # it. Each name outside the shared list is the page's own, so only the
        # shared ones are required to be referenced.
        source = APP_JS.read_text(encoding="utf-8")
        for name in SHARED:
            with self.subTest(name=name):
                self.assertGreater(source.count(name), 1,
                                   f"{name} is declared but never used in app.js")


if __name__ == "__main__":
    unittest.main()
