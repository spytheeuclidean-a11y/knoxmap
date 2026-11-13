"""Why a building is missing, asked by clicking it rather than by a command.

tools/why_no_building.py answers this at a command line, which rules it out
for most of the people who ask. The window asks /api/why about the building
that was clicked (web/zones.py), and shows the tally under the Buildings step
after a build. Both read the rows the build writes, through knoxbuild/why.py.
"""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as A
from knoxbuild import why
from web import common

FIELDS = ["reason", "tile_x", "tile_y", "lat", "lon", "tiles_wide",
          "tiles_tall", "building", "name", "osm_id"]
ROWS = [
    ("road", "320", "310", "39.2", "27.2", "8", "9", "yes", "On The Road", "3"),
    ("outside", "-20", "-30", "39.1", "27.1", "10", "12", "yes", "Off Map", "1"),
    ("outside", "-25", "-31", "39.1", "27.1", "9", "9", "yes", "", "7"),
]


def write_rows(folder: Path, rows=ROWS) -> None:
    with open(folder / f"{folder.name}_left_out.csv", "w", newline="",
              encoding="utf-8") as f:
        wtr = csv.writer(f)
        wtr.writerow(FIELDS)
        wtr.writerows(rows)


class OneBuilding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "Town"
        self.folder.mkdir()

    def test_the_reason_comes_back_with_the_words_for_it(self):
        write_rows(self.folder)
        answer = why.for_id(str(self.folder), 3)
        self.assertEqual(answer["state"], "left out")
        self.assertEqual(answer["reason"], "road")
        self.assertEqual(answer["why"], why.WHY["road"])
        self.assertEqual(answer["fix"], why.FIX["road"])

    def test_a_footprint_nothing_was_recorded_against_was_built(self):
        write_rows(self.folder)
        self.assertEqual(why.for_id(str(self.folder), 999)["state"], "built")

    def test_a_map_built_before_any_of_this_does_not_claim_they_were_built(self):
        # The file is missing rather than empty, and every footprint on the
        # map would otherwise read as built.
        self.assertEqual(why.for_id(str(self.folder), 3)["state"], "no records")

    def test_a_map_that_left_nothing_out_answers_built(self):
        write_rows(self.folder, [])
        self.assertEqual(why.for_id(str(self.folder), 3)["state"], "built")

    def test_an_id_pasted_as_an_openstreetmap_link_still_finds_it(self):
        write_rows(self.folder)
        answer = why.for_id(str(self.folder),
                            "https://www.openstreetmap.org/way/3")
        self.assertEqual(answer["reason"], "road")

    def test_the_tally_is_biggest_first_and_worded(self):
        write_rows(self.folder)
        report = why.summary(str(self.folder))
        self.assertEqual(report["total"], 3)
        self.assertEqual([line["reason"] for line in report["lines"]],
                         ["outside", "road"])
        self.assertEqual(report["lines"][0]["n"], 2)
        self.assertEqual(report["lines"][0]["text"], why.SHORT["outside"])

    def test_every_reason_the_tally_can_name_has_a_short_form(self):
        # Without one the window would print the bare label - "250 outside".
        for reason in why.WHY:
            with self.subTest(reason=reason):
                self.assertTrue(why.SHORT.get(reason))


class ThroughTheWindow(unittest.TestCase):
    def setUp(self):
        A.app.config["TESTING"] = True
        self.client = A.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        out = Path(self.tmp.name)
        (out / "Town").mkdir()
        write_rows(out / "Town")
        patcher = mock.patch.object(common, "OUTPUT_DIR", out)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_asking_about_the_clicked_building(self):
        res = self.client.get("/api/why/Town?osm=3")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["state"], "left out")
        self.assertIn("tarmac", body["why"])

    def test_asking_about_the_whole_map(self):
        body = self.client.get("/api/why/Town").get_json()
        self.assertEqual(body["total"], 3)

    def test_a_map_that_is_not_there(self):
        res = self.client.get("/api/why/nope?osm=3")
        self.assertEqual(res.status_code, 400)


class ThePageAsks(unittest.TestCase):
    """The wording is in Python; the page must be showing what it is sent."""

    def setUp(self):
        root = Path(__file__).resolve().parent.parent
        self.js = "\n".join(
            p.read_text(encoding="utf-8")
            for p in sorted((root / "static" / "js").glob("*.js"))
        )
        self.html = (root / "templates" / "index.html").read_text(encoding="utf-8")

    def test_the_building_that_was_clicked_is_asked_about(self):
        self.assertIn("/api/why/", self.js)
        self.assertIn("osm=", self.js)

    def test_the_reasons_are_not_written_out_a_second_time_in_the_page(self):
        for sentence in (why.WHY["road"], why.FIX["road"],
                         why.SHORT["outside"]):
            with self.subTest(sentence=sentence):
                self.assertNotIn(sentence, self.js)

    def test_there_is_somewhere_to_show_both(self):
        self.assertIn('id="leftOut"', self.html)
        self.assertIn("editWhy", self.js)


if __name__ == "__main__":
    unittest.main()
