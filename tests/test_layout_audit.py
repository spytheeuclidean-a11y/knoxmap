"""What Build reports about the buildings it has just made.

knoxbuild/audit.py holds the checks - a room with no way in, a door onto the
stairs, a flat with no front door. Build runs them over every building it lays
out and writes the totals beside the map, where the census shows them: the last
moment a bad town is cheap to put right, because compiling it takes hours and
finding out afterwards means walking it in game.
"""
import json
import tempfile
import unittest
from pathlib import Path

from knoxbuild.audit import audit
from knoxbuild.build import _audit_report, _layout_problems
from knoxbuild.layout import build_building
from web import mapfiles


def house(seed=1, w=12, h=10, levels=2):
    return build_building(w, h, levels=levels, seed=seed)


class TheChecksFindWhatTheyLookFor(unittest.TestCase):
    def test_a_room_with_no_way_in_is_reported(self):
        plan = house()
        self.assertGreater(len(plan.rooms), 1)
        # Every door taken out: the rooms are sealed off from each other and
        # from outside, which is the thing a player meets first.
        for storey in plan.storeys:
            storey.doors.clear()
        found = audit(plan, None)
        self.assertGreater(found["room with no way in"], 0, dict(found))

    def test_a_house_comes_out_clean(self):
        for seed in range(5):
            found = {k: v for k, v in audit(house(seed), None).items()
                     if v and not k.startswith("stat:")}
            with self.subTest(seed=seed):
                self.assertEqual(found, {})


class BuildReportsThem(unittest.TestCase):
    def test_a_clean_building_is_checked_and_empty(self):
        # {} is "checked and clean", which is not the same as None below.
        self.assertEqual(_layout_problems(house(), None, None), {})

    def test_a_check_that_breaks_does_not_cost_a_building(self):
        # Whatever the checks do, the building is kept: a diagnostic must never
        # turn a good house into a failed one.
        self.assertIsNone(_layout_problems(object(), None, None))

    def test_the_report_counts_buildings_and_problems(self):
        clean = (1, 4, 0, None, [], None, {})
        dirty = (1, 4, 0, None, [], None, {"room with no way in": 2})
        also = (1, 4, 0, None, [], None, {"room with no way in": 1,
                                          "door onto the stairs": 1})
        unchecked = (1, 4, 0, None, [], None, None)
        failed = (0, 0, 0, "could not be laid out", [], None, None)
        report = _audit_report([clean, dirty, also, unchecked, failed])
        self.assertEqual(report["buildings"], 3)
        self.assertEqual(report["flagged"], 2)
        self.assertEqual(report["problems"],
                         {"room with no way in": 3, "door onto the stairs": 1})

    def test_nothing_checked_says_so_rather_than_perfect(self):
        # A cache from before the audit, or checks that could not run, must not
        # read as a town with nothing wrong with it.
        report = _audit_report([(1, 4, 0, None, [], None, None)])
        self.assertEqual(report["buildings"], 0)
        self.assertEqual(report["flagged"], 0)
        self.assertEqual(report["problems"], {})


class TheWindowIsTold(unittest.TestCase):
    def test_no_report_means_nothing_is_said(self):
        with tempfile.TemporaryDirectory() as tmp:
            where = Path(tmp)
            self.assertIsNone(mapfiles._layout_audit(where))
            self.assertIsNone(mapfiles._audited(where, None))

    def test_the_report_rides_with_the_population(self):
        with tempfile.TemporaryDirectory() as tmp:
            where = Path(tmp) / "town"
            where.mkdir()
            report = {"buildings": 5, "flagged": 1,
                      "problems": {"room with no way in": 2}}
            (where / "town_layout.json").write_text(json.dumps(report),
                                                   encoding="utf-8")
            population = mapfiles._audited(where, {"residents": 10})
            self.assertEqual(population["residents"], 10)
            self.assertEqual(population["audit"], report)

    def test_a_recount_keeps_the_audit(self):
        # The audit is its own file, so redrawing the zombies cannot drop it.
        with tempfile.TemporaryDirectory() as tmp:
            where = Path(tmp) / "town"
            where.mkdir()
            (where / "town_layout.json").write_text(
                json.dumps({"buildings": 5, "flagged": 0, "problems": {}}),
                encoding="utf-8")
            (where / "town_population.json").write_text(
                json.dumps({"residents": 3}), encoding="utf-8")
            population = mapfiles._audited(where, mapfiles._population(where))
            self.assertEqual(population["residents"], 3)
            self.assertEqual(population["audit"]["buildings"], 5)


if __name__ == "__main__":
    unittest.main()
