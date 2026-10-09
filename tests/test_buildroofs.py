import unittest
from types import SimpleNamespace

from knoxbuild.buildroofs import band_squares, flat_squares, roof_squares, upper_level

NAMES = ["SlopeS1", "SlopeS2", "SlopeS3", "SlopeE1", "SlopeE2", "SlopeE3", "SlopePt5S", "SlopeOnePt5S",
         "SlopeTwoPt5S", "SlopePt5E", "SlopeOnePt5E", "SlopeTwoPt5E",
         "Slope30N1", "Slope30N2", "Slope30S1", "Slope30S2", "Peak30NS3", "Slope30W1", "Slope30W2",
         "Slope30E1", "Slope30E2", "Peak30WE3", "Peak30Quad3",
         "OuterSlope30NW1", "OuterSlope30NE1", "OuterSlope30SW1", "OuterSlope30SE1",
         "OuterSlope30NW2", "OuterSlope30NE2", "OuterSlope30SW2", "OuterSlope30SE2"]
CAPS = ["CapRiseE1", "CapRiseE2", "CapRiseE3", "CapFallE1", "CapFallE2", "CapFallE3", "CapGapE3",
        "CapRiseS1", "CapRiseS2", "CapRiseS3", "CapFallS1", "CapFallS2", "CapFallS3", "CapGapS3",
        "PeakPt5E", "PeakOnePt5E", "PeakTwoPt5E", "PeakPt5S", "PeakOnePt5S", "PeakTwoPt5S",
        "CapSlope30FallE1", "CapSlope30FallE2", "CapSlope30RiseE1", "CapSlope30RiseE2", "CapPeak30E3"]
TABLE = {1: {n: "s_" + n for n in NAMES}, 2: {n: "c_" + n for n in CAPS},
         3: {"West1": "top", "North1": "topN"}, 4: {"Ceiling": "ceil"}}


def entry(n):
    return TABLE.get(int(n), {})


def roof(kind, depth, x, y, w, h, caps=""):
    return dict(type="roof", RoofType=kind, Depth=depth, x=x, y=y, width=w, height=h,
                SlopeTiles=1, CapTiles=2, TopTiles=3,
                **{f"capped{d}": str(d in caps).lower() for d in "WNES"})


def squares(*a, **k):
    return roof_squares(entry, {}, roof(*a, **k))


class PeakTests(unittest.TestCase):
    def test_south_half_of_a_depth_two_roof(self):
        s = squares("PeakWE", "Two", 5, 5, 8, 4)
        self.assertEqual(s[(5, 8)], ["s_SlopeS1"])
        self.assertEqual(s[(9, 7)], ["s_SlopeS2"])
        self.assertNotIn((5, 5), s)                    # nothing on the north half
        self.assertEqual(len(s), 16)

    def test_odd_sizes_have_a_ridge_row(self):
        s = squares("PeakWE", "TwoPoint5", 0, 0, 3, 5)
        self.assertEqual([s[(0, y)] for y in (4, 3, 2)], [["s_SlopeS1"], ["s_SlopeS2"], ["s_SlopeTwoPt5S"]])
        self.assertEqual(squares("PeakWE", "Point5", 0, 0, 3, 1)[(1, 0)], ["s_SlopePt5S"])

    def test_depth_three_takes_the_depth_that_fits(self):
        s = squares("PeakWE", "Three", 0, 0, 3, 5)
        self.assertEqual(s[(0, 2)], ["s_SlopeTwoPt5S"])
        self.assertEqual(len(squares("PeakWE", "Three", 0, 0, 3, 12)), 9)    # three rows however tall

    def test_caps_stand_on_the_first_column_and_just_past_the_last(self):
        s = squares("PeakWE", "Two", 5, 5, 8, 4, caps="WE")
        self.assertEqual([s[(5, y)] for y in (5, 6, 7, 8)],
                         [["c_CapFallE1"], ["c_CapFallE2"], ["c_CapRiseE2", "s_SlopeS2"], ["c_CapRiseE1", "s_SlopeS1"]])
        self.assertEqual(s[(13, 5)], ["c_CapFallE1"])                         # outside the roof
        self.assertNotIn((13, 9), s)
        self.assertNotIn((6, 5), squares("PeakWE", "Two", 5, 5, 8, 4, caps="W"))

    def test_tall_depth_three_caps_fill_with_gap_tiles(self):
        s = squares("PeakWE", "Three", 0, 0, 4, 8, caps="W")
        self.assertEqual([s[(0, y)][0] for y in range(8)],
                         ["c_CapFallE1", "c_CapFallE2", "c_CapFallE3", "c_CapGapE3", "c_CapGapE3",
                          "c_CapRiseE3", "c_CapRiseE2", "c_CapRiseE1"])

    def test_north_south_roofs_slope_to_the_east(self):
        s = squares("PeakNS", "OnePoint5", 0, 0, 3, 4, caps="N")
        self.assertEqual(s[(2, 1)], ["s_SlopeE1"])
        self.assertEqual(s[(1, 1)], ["s_SlopeOnePt5E"])
        self.assertEqual([s[(x, 0)][0] for x in range(3)], ["c_CapRiseS1", "c_PeakOnePt5S", "c_CapFallS1"])


class ThirtyDegreeTests(unittest.TestCase):
    def test_wide_roofs_keep_the_eleven_square_cross_section_at_the_origin(self):
        table = {1: {f"{stem}{i}": f"{stem}{i}" for stem in
                      ("Slope30W", "Slope30E", "Slope30N", "Slope30S", "Peak30WE", "Peak30NS")
                      for i in range(1, 7)},
                 2: {f"{stem}{i}": f"{stem}{i}" for stem in
                      ("CapSlope30RiseS", "CapSlope30FallS", "CapSlope30RiseE", "CapSlope30FallE", "CapPeak30S", "CapPeak30E")
                      for i in range(1, 7)}}
        for kind, w, h, caps, peak in (("Peak30WE", 4, 13, "WE", (3, 9)),
                                     ("Peak30NS", 13, 4, "NS", (8, 4))):
            with self.subTest(kind=kind):
                s = roof_squares(lambda n: table.get(int(n), {}), {}, roof(kind, "Zero", 3, 4, w, h, caps))
                self.assertTrue(any("Peak30" in t for t in s[peak]))
                self.assertNotIn((3, 15) if kind == "Peak30WE" else (14, 4), s)

    def test_slopes_both_sides_of_a_peak_row(self):
        s = squares("Peak30WE", "Zero", 0, 0, 2, 5)
        self.assertEqual([s[(0, y)] for y in range(5)],
                         [["s_Slope30N1"], ["s_Slope30N2"], ["s_Peak30NS3"], ["s_Slope30S2"], ["s_Slope30S1"]])

    def test_hip_rings(self):
        s = squares("Peak30Quad", "Zero", 0, 0, 5, 5)
        self.assertEqual(s[(0, 0)], ["s_OuterSlope30NW1"])
        self.assertEqual(s[(4, 0)], ["s_OuterSlope30NE1"])
        self.assertEqual(s[(1, 1)], ["s_OuterSlope30NW2"])
        self.assertEqual(s[(2, 2)], ["s_Peak30Quad3"])
        self.assertEqual(s[(0, 2)], ["s_Slope30W1"])
        self.assertEqual(len(s), 25)


class UpperLevelTests(unittest.TestCase):
    def floors(self, *grids_and_objects):
        return [SimpleNamespace(rooms=g, objects=o) for g, o in grids_and_objects]

    def test_ceilings_and_flat_roofs(self):
        rooms = [[1, 1, 0], [1, 1, 0]]
        empty = [[0, 0, 0], [0, 0, 0]]
        defs = [{"Ceiling": 4}]
        f = self.floors((rooms, [roof("FlatTop", "Three", 1, 0, 1, 2)]), (empty, []))
        up = upper_level(entry, {}, 3, 2, defs, f, 1)
        self.assertEqual(up[(0, 0)], ["ceil"])
        self.assertEqual(up[(1, 0)], ["top"])                    # the flat roof replaces the ceiling
        self.assertNotIn((2, 0), up)                             # no room, no ceiling

    def test_no_ceiling_under_a_room_above(self):
        rooms = [[1, 1]]
        f = self.floors((rooms, []), (rooms, []))
        self.assertEqual(upper_level(entry, {}, 2, 1, [{"Ceiling": 4}], f, 1), {})

    def test_the_flat_band_of_a_tall_roof(self):
        b = band_squares(entry, {}, roof("PeakWE", "Three", 2, 1, 3, 10))
        self.assertEqual(sorted({y for _, y in b}), [4, 5, 6, 7])
        self.assertEqual(band_squares(entry, {}, roof("PeakWE", "Three", 0, 0, 3, 6)), {})
        self.assertEqual(band_squares(entry, {}, roof("PeakWE", "Two", 0, 0, 3, 10)), {})

    def test_flat_top_covers_its_rectangle(self):
        self.assertEqual(len(flat_squares(entry, {}, roof("FlatTop", "Three", 0, 0, 4, 3))), 12)


if __name__ == "__main__":
    unittest.main()
