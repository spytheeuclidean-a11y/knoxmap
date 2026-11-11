"""How long a map will take, and how long is left of the one running.

Every step stamps the seconds it took, so the forecast is measured: seconds a
tile, the median over the maps this PC has made. A step with no history behind
it says nothing at all, which is the point - a forecast wrong by an hour is
worse than none, because somebody plans an evening around it.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from knoxbuild import mapstate
from web import forecast, jobs

SOUTH, WEST, NORTH, EAST = 40.1440, -84.2420, 40.1700, -84.2070


class DurationsAreKept(unittest.TestCase):
    def test_a_stamped_duration_is_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapstate.stamp(tmp, "build", version="1.0", took=123.44)
            self.assertEqual(mapstate.took(tmp, "build"), 123.4)

    def test_a_stage_stamped_without_a_duration_is_unknown(self):
        # Every map made before this has only "at", and reads as unknown rather
        # than as instant.
        with tempfile.TemporaryDirectory() as tmp:
            mapstate.stamp(tmp, "build", version="1.0")
            self.assertIsNone(mapstate.took(tmp, "build"))

    def test_a_stage_never_run_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(mapstate.took(tmp, "compile"))

    def test_a_stamp_takes_the_duration_of_a_step_that_invalidates_later_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapstate.stamp(tmp, "generate", version="1.0", took=10)
            mapstate.stamp(tmp, "build", version="1.0", took=20)
            self.assertEqual(mapstate.took(tmp, "build"), 20)
            # Building again forgets what was made from it.
            mapstate.stamp(tmp, "build", version="1.0", took=30)
            self.assertEqual(mapstate.took(tmp, "build"), 30)
            self.assertEqual(mapstate.took(tmp, "generate"), 10)


class TheSizeIsTheSizeTheRendererPads(unittest.TestCase):
    def test_tiles_are_whole_cells(self):
        width, height = forecast.size_of(SOUTH, WEST, NORTH, EAST, 1.0)
        self.assertEqual(width % 300, 0)
        self.assertEqual(height % 300, 0)
        # Worked out here from the degrees, not from the function's own sum.
        import math
        h_m = (NORTH - SOUTH) * 111320.0
        w_m = (EAST - WEST) * 111320.0 * math.cos(math.radians((SOUTH + NORTH) / 2))
        self.assertEqual(width, math.ceil(w_m / 300) * 300)
        self.assertEqual(height, math.ceil(h_m / 300) * 300)

    def test_a_larger_scale_is_a_smaller_map(self):
        small = forecast.size_of(SOUTH, WEST, NORTH, EAST, 1.0)
        big = forecast.size_of(SOUTH, WEST, NORTH, EAST, 4.0)
        self.assertLess(big[0], small[0])
        self.assertLess(big[1], small[1])

    def test_a_tiny_box_is_still_one_cell(self):
        width, height = forecast.size_of(40.144, -84.242, 40.1441, -84.2419, 8.0)
        self.assertEqual((width, height), (300, 300))


class TheRatesComeFromTheMapsAlreadyMade(unittest.TestCase):
    def town(self, where: Path, name: str, tiles: int, took: dict):
        folder = where / name
        folder.mkdir()
        (folder / f"{name}_info.json").write_text(json.dumps(
            {"width_tiles": tiles, "height_tiles": 1}), encoding="utf-8")
        for stage, seconds in took.items():
            mapstate.stamp(str(folder), stage, version="1.0", took=seconds)

    def test_the_median_of_the_maps_that_were_timed(self):
        with tempfile.TemporaryDirectory() as tmp:
            where = Path(tmp)
            # 1 s a tile, 3 s a tile, and 100 s a tile: the middle one wins.
            self.town(where, "one", 100, {"build": 100})
            self.town(where, "two", 100, {"build": 300})
            self.town(where, "three", 100, {"build": 10000})
            self.assertAlmostEqual(forecast.rates(where)["build"], 3.0)

    def test_a_map_with_no_tiles_is_left_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            where = Path(tmp)
            self.town(where, "empty", 0, {"build": 999})
            self.town(where, "real", 100, {"build": 100})
            self.assertAlmostEqual(forecast.rates(where)["build"], 1.0)

    def test_no_history_is_no_rates(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(forecast.rates(Path(tmp)), {})


class TheForecastSaysWhatItKnows(unittest.TestCase):
    def test_a_step_with_no_history_is_null_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = forecast.forecast(tmp, SOUTH, WEST, NORTH, EAST, 1.0)
            self.assertEqual(got["steps"], {"generate": None, "build": None,
                                            "compile": None})
            self.assertEqual(got["measured"], [])
            # The size is always known, history or not.
            self.assertGreater(got["tiles"]["width"], 0)
            self.assertGreater(got["cells"]["x"], 0)

    def test_a_measured_step_is_scaled_to_this_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            where = Path(tmp)
            TheRatesComeFromTheMapsAlreadyMade.town(self, where, "last", 100,
                                                    {"compile": 200})
            got = forecast.forecast(where, SOUTH, WEST, NORTH, EAST, 1.0)
            tiles = got["tiles"]["width"] * got["tiles"]["height"]
            self.assertEqual(got["steps"]["compile"], round(2.0 * tiles))
            self.assertEqual(got["measured"], ["compile"])
            self.assertIsNone(got["steps"]["build"])

    def test_the_bitmaps_are_three_of_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = forecast.forecast(tmp, SOUTH, WEST, NORTH, EAST, 1.0)
            tiles = got["tiles"]["width"] * got["tiles"]["height"]
            self.assertAlmostEqual(got["bitmapsMB"], tiles * 9 / 1e6, places=1)


class TheTimeLeftOfTheStepRunning(unittest.TestCase):
    def test_nothing_until_the_stage_has_a_pace(self):
        with mock.patch.object(jobs.time, "time", return_value=1000.0):
            self.assertIsNone(jobs._eta({"done": 1, "total": 100,
                                         "started": 998.0}))
            self.assertIsNone(jobs._eta({"done": 0, "total": 100,
                                         "started": 900.0}))
            self.assertIsNone(jobs._eta({"done": 5, "total": 100}))

    def test_a_quarter_done_in_a_hundred_seconds_has_three_hundred_left(self):
        with mock.patch.object(jobs.time, "time", return_value=1000.0):
            self.assertEqual(jobs._eta({"done": 25, "total": 100,
                                        "started": 900.0}), 300)

    def test_a_fraction_counts_as_well_as_a_count(self):
        # Build reports a fraction, generate a tile count.
        with mock.patch.object(jobs.time, "time", return_value=1000.0):
            self.assertEqual(jobs._eta({"fraction": 0.5, "started": 940.0}), 60)

    def test_the_stage_clock_starts_again_with_the_next_stage(self):
        with mock.patch.object(jobs.time, "time", return_value=1000.0):
            jobs._set_progress("eta-map", stage="buildings", fraction=0.1)
        with mock.patch.object(jobs.time, "time", return_value=1010.0):
            jobs._set_progress("eta-map", stage="buildings", fraction=0.2)
        self.assertEqual(jobs._PROGRESS["eta-map"]["etaSeconds"], 40)
        # The next stage is a new clock: no reading off the old pace.
        with mock.patch.object(jobs.time, "time", return_value=1011.0):
            jobs._set_progress("eta-map", stage="fences", fraction=0.9)
        self.assertNotIn("etaSeconds", jobs._PROGRESS["eta-map"])


if __name__ == "__main__":
    unittest.main()
