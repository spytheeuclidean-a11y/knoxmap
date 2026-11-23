import unittest
from collections import Counter

from generator.rendering.infill import _infill_frontage, _report_lines
from tests.test_infill import PROJ, box, row, street


def run(buildings, roads=None, **kw):
    report = Counter()
    made = _infill_frontage({"road_minor": roads or [street()]}, [], buildings, PROJ,
                            report=report, **kw)
    return made, report


class Report(unittest.TestCase):
    def test_what_was_made_is_counted(self):
        houses = row(40, 14, 18, 15, 130, 142, skip=(4, 5, 6, 7))
        made, report = run(houses)
        self.assertEqual(report["lot: made"], len(made))
        self.assertGreater(len(made), 0)

    def test_a_gap_beside_a_school_says_so(self):
        school = [box(1, 40, 80, 120, 142, building="school"), box(2, 130, 170, 120, 142, building="school")]
        made, report = run(school)
        self.assertEqual(made, [])
        self.assertEqual(report["gap: beside a church, school, garage or the like"], 1)

    def test_a_lone_building_is_not_a_row(self):
        made, report = run([box(1, 40, 55, 130, 142)])
        self.assertEqual(made, [])
        self.assertFalse([r for r in report if r.startswith("lot:")])

    def test_a_row_end_that_is_not_extended_is_counted(self):
        houses = row(40, 4, 18, 15, 130, 142)
        made, report = run(houses, extend_ends=False)
        self.assertEqual(made, [])
        self.assertTrue(report["gap: too long to fill (row ends are not extended)"]
                        or report["gap: only one building beside it, so not a row"])

    def test_without_a_report_nothing_changes(self):
        houses = row(40, 14, 18, 15, 130, 142, skip=(4, 5, 6, 7))
        a = _infill_frontage({"road_minor": [street()]}, [], houses, PROJ)
        b, _ = run(houses)
        self.assertEqual([f.geometry for f in a], [f.geometry for f in b])

    def test_lines_list_what_was_made_first_then_reasons_by_count(self):
        lines = _report_lines(Counter({"gap: a": 2, "gap: b": 5, "lot: made": 3}))
        self.assertTrue(lines[0].endswith("lot: made"))
        self.assertTrue(lines[1].endswith("gap: b"))
        self.assertTrue(lines[2].endswith("gap: a"))


if __name__ == "__main__":
    unittest.main()
