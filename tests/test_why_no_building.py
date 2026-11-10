"""Why a footprint did not become a building, kept per building.

The build counts what it left out - so many too small, so many off the edge -
which says nothing to somebody looking at the gap where their own house
should be. A row per footprint is written beside the map
(`<map>_left_out.csv`) and tools/why_no_building.py reads it back for one
place.
"""
import csv
import os
import tempfile
import unittest

from tools import why_no_building as W

ROWS = [
    # reason, tile_x, tile_y, lat, lon, w, h, building, name, osm_id
    ("outside", "-20", "-30", "39.1", "27.1", "10", "12", "yes", "Off Map", "1"),
    ("taken", "300", "300", "39.2", "27.2", "6", "6", "shed", "", "2"),
    ("road", "320", "310", "39.2", "27.2", "8", "9", "yes", "On The Road", "3"),
    ("small", "900", "900", "39.3", "27.3", "2", "2", "shed", "Kızıl Avlu", "4"),
]
FIELDS = ["reason", "tile_x", "tile_y", "lat", "lon", "tiles_wide",
          "tiles_tall", "building", "name", "osm_id"]


class AMapWithHolesInIt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "town")
        os.makedirs(self.folder)
        with open(os.path.join(self.folder, "town_left_out.csv"), "w",
                  newline="", encoding="utf-8") as f:
            wtr = csv.writer(f)
            wtr.writerow(FIELDS)
            wtr.writerows(ROWS)
        with open(os.path.join(self.folder, "town_placements.csv"), "w",
                  newline="", encoding="utf-8") as f:
            wtr = csv.DictWriter(f, fieldnames=["file", "tile_x", "tile_y"])
            wtr.writeheader()
            wtr.writerow({"file": "a.tbx", "tile_x": "305", "tile_y": "305"})

    def run_tool(self, *args) -> str:
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = W.main(["why_no_building.py", self.folder, *args])
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_the_whole_map_is_summed_up_by_reason(self):
        text = self.run_tool()
        self.assertIn("left out  : 4", text)
        for reason in ("outside", "taken", "road", "small"):
            with self.subTest(reason=reason):
                self.assertIn(reason, text)

    def test_every_reason_says_what_it_means_and_what_to_do(self):
        # A reason with no words for it would print a bare label, which is
        # what the counts already did.
        for reason in ("small", "large", "outside", "taken", "road",
                       "not a building"):
            with self.subTest(reason=reason):
                self.assertTrue(W.WHY.get(reason), f"{reason} has no meaning")
                self.assertTrue(W.FIX.get(reason), f"{reason} has no remedy")

    def test_asking_about_one_place_leaves_the_rest_of_the_map_out(self):
        text = self.run_tool("--tiles", "300,300", "--radius", "40")
        self.assertIn("taken", text)
        self.assertIn("On The Road", text)       # 20x10 tiles away, inside 40
        self.assertNotIn("Off Map", text)        # the far side of the map
        self.assertNotIn("Kızıl Avlu", text)

    def test_and_counts_the_buildings_that_were_built_there(self):
        self.assertIn("built     : 1", self.run_tool("--tiles", "300,300",
                                                     "--radius", "40"))

    def test_one_reason_at_a_time(self):
        text = self.run_tool("--reason", "road")
        self.assertIn("On The Road", text)
        self.assertNotIn("Off Map", text)

    def test_a_place_where_everything_was_built_says_so(self):
        text = self.run_tool("--tiles", "500,500", "--radius", "5")
        self.assertIn("Every footprint here became a building", text)

    def test_a_folder_with_no_records_explains_itself(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = W.main(["why_no_building.py", self.tmp.name])
        self.assertEqual(code, 2)
        self.assertIn("generate the buildings first", out.getvalue())

    def test_a_name_in_another_alphabet_survives(self):
        self.assertIn("Kızıl Avlu", self.run_tool("--reason", "small"))


class TheBuildWritesThem(unittest.TestCase):
    def test_every_reason_the_build_can_give_has_words(self):
        # The build's own list of reasons, so a new one cannot be added there
        # and come out of the tool as a bare label.
        from knoxbuild import footprint
        import inspect
        import re
        source = inspect.getsource(footprint)
        given = set(re.findall(r'return None, "(\w[\w ]*)"', source))
        given.add("not a building")        # knoxbuild/build.py gives this one
        missing = sorted(given - set(W.WHY))
        self.assertFalse(missing, f"no words for: {missing}")


if __name__ == "__main__":
    unittest.main()
