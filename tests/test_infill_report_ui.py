import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from web import mapfiles

APP = Path(__file__).resolve().parent.parent / "static" / "js" / "app.js"
REPORT = {"lot: made": 40, "lot: trimmed to fit": 5, "lot: outline copied from a neighbour": 3,
          "gap: no building on either side": 90, "gap: a yard between two houses, not a missing house": 12,
          "lot: would stand on a building": 7}


def render(report):
    """infillReportHtml, as app.js defines it, run under node."""
    text = APP.read_text(encoding="utf-8")
    start = text.index("const INFILL_KEPT")
    end = text.index("function renderResults(data)")
    script = ("const escapeHtml = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');\n"
              + text[start:end] + "\nprocess.stdout.write(infillReportHtml(" + json.dumps(report) + "));")
    return subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Panel(unittest.TestCase):
    def test_no_report_no_panel(self):
        self.assertEqual(render({}), "")
        self.assertEqual(render(None), "")

    def test_made_and_why_the_rest_stayed_empty(self):
        html = render(REPORT)
        self.assertIn("Street infill: 40 made", html)
        self.assertIn("<li>5 of them trimmed to fit", html)
        self.assertIn("<li>3 of them shaped like the houses beside them", html)
        # most common first, prefix dropped
        self.assertLess(html.index("90 no building on either side"),
                        html.index("12 a yard between two houses"))
        self.assertIn("<li>7 would stand on a building</li>", html)
        self.assertIn("Stretches of street left empty", html)
        self.assertIn("Lots given up", html)

    def test_reasons_are_escaped(self):
        self.assertNotIn("<script>", render({"gap: <script>": 1}))


class Passthrough(unittest.TestCase):
    def test_a_reopened_map_carries_its_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "m"
            d.mkdir()
            (d / "m_info.json").write_text(json.dumps(
                {"houses_infilled": 40, "street_infill_report": REPORT}), encoding="utf-8")
            summary = mapfiles._map_summary(d)
        self.assertEqual(summary["fromStreetInfill"], 40)
        self.assertEqual(summary["streetInfillReport"], REPORT)


if __name__ == "__main__":
    unittest.main()
