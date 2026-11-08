"""Thinning a building's rooms so the map fits the game's save buffer.

The game writes every room and building in the world through one 10 MB
buffer (tools/make_map_mod.py). A map past it keeps nothing: the write throws
and no save stores which buildings are explored, alarmed or lit. Rather than
tell the player to generate a smaller map, the rooms are merged down to what
fits - walls, doors, furniture and the buildings themselves stay as they are.
"""
import csv
import glob
import os
import tempfile
import unittest
from unittest import mock

from knoxbuild import layout, placement, presets
from knoxbuild.build import _rooms_that_fit
from knoxbuild.layout import build_building
from knoxbuild.settings import Settings
from tests.basement_town import build_town
from tools import make_map_mod


def tiled(plan):
    """The squares this storey gave to a room, as {(x, y)}."""
    return {(x, y) for y, row in enumerate(plan.grid)
            for x, v in enumerate(row) if v}


class ThinningOneStorey(unittest.TestCase):
    def house(self):
        return build_building(22, 18, levels=2, seed=5, kind="house").storeys[0]

    def test_it_merges_down_to_the_limit(self):
        plan = self.house()
        was = len(plan.rooms)
        self.assertGreater(was, 8)
        merged = layout.thin_plan(plan, was // 2)
        self.assertGreater(merged, 0)
        self.assertEqual(len(plan.rooms), was - merged)
        self.assertLessEqual(len(plan.rooms), was // 2)

    def test_not_one_square_of_the_plan_is_lost(self):
        plan = self.house()
        before = tiled(plan)
        layout.thin_plan(plan, 6)
        self.assertEqual(tiled(plan), before)

    def test_every_room_left_owns_squares_and_is_numbered_in_order(self):
        plan = self.house()
        layout.thin_plan(plan, 6)
        owned = {v for row in plan.grid for v in row if v}
        self.assertEqual(owned, set(range(1, len(plan.rooms) + 1)))

    def test_the_walls_doors_and_windows_stay_where_they_were(self):
        plan = self.house()
        doors, windows = list(plan.doors), list(plan.windows)
        furniture = list(plan.furniture)
        layout.thin_plan(plan, 6)
        self.assertEqual(plan.doors, doors)
        self.assertEqual(plan.windows, windows)
        self.assertEqual(plan.furniture, furniture)

    def test_a_plan_drawn_by_hand_is_left_alone(self):
        plan = self.house()
        plan.drawn = True
        was = len(plan.rooms)
        self.assertEqual(layout.thin_plan(plan, 3), 0)
        self.assertEqual(len(plan.rooms), was)

    def test_the_stair_core_is_never_merged_away(self):
        plan = self.house()
        layout.thin_plan(plan, layout.THIN_MIN_ROOMS)
        self.assertTrue(any(room.is_core for room in plan.rooms))

    def test_two_flats_are_never_joined(self):
        flats = build_building(30, 26, levels=2, seed=3, kind="apartment").storeys[0]
        unit_by_tile = {(x, y): flats.rooms[v - 1].unit
                        for y, row in enumerate(flats.grid)
                        for x, v in enumerate(row) if v}
        layout.thin_plan(flats, 6)
        dwellings = {}
        for y, row in enumerate(flats.grid):
            for x, v in enumerate(row):
                if v:
                    dwellings.setdefault(v, set()).add(unit_by_tile[(x, y)])
        for units in dwellings.values():
            self.assertEqual(len(units), 1, "one room spans two dwellings")


class ThinningAWholeBuilding(unittest.TestCase):
    def test_no_storey_is_emptied_to_pay_for_the_one_below(self):
        building = build_building(26, 22, levels=3, seed=11, kind="house")
        was = len(building.rooms)
        merged = layout.thin_building(building, was // 3)
        self.assertGreater(merged, 0)
        self.assertLess(len(building.rooms), was)
        for storey in building.storeys:
            self.assertGreaterEqual(len(storey.rooms), layout.THIN_MIN_ROOMS)

    def test_a_building_already_thin_enough_is_untouched(self):
        building = build_building(10, 9, levels=1, seed=2, kind="house")
        was = len(building.rooms)
        self.assertEqual(layout.thin_building(building, was + 5), 0)
        self.assertEqual(len(building.rooms), was)


class WhatTheBufferHolds(unittest.TestCase):
    def test_knox_county_is_given_up_when_the_map_stands_alone(self):
        from tools.make_map_mod import (KNOX_COUNTY_META, META_BUDGET, META_BUILDING,
                                        META_CELL, META_ROOM)
        info = {"cells_x": 10, "cells_y": 10}
        left = META_BUDGET - META_BUILDING * 1000 - META_CELL * 100
        with mock.patch("knoxbuild.placement.standalone", return_value=True):
            alone = _rooms_that_fit(1000, info, ".")
        with mock.patch("knoxbuild.placement.standalone", return_value=False):
            shared = _rooms_that_fit(1000, info, ".")
        self.assertEqual(alone, left // META_ROOM)
        self.assertEqual(shared, (left - KNOX_COUNTY_META) // META_ROOM)

    def test_it_is_what_is_left_of_the_buffer_after_cells_and_buildings(self):
        from tools.make_map_mod import (META_BUDGET, META_BUILDING, META_CELL,
                                        META_ROOM)
        with mock.patch("knoxbuild.placement.standalone", return_value=True):
            rooms = _rooms_that_fit(500, {"cells_x": 20, "cells_y": 8}, ".")
        expect = (META_BUDGET - META_BUILDING * 500 - META_CELL * 160) // META_ROOM
        self.assertEqual(rooms, expect)


class AWholeTownFitsTheBuffer(unittest.TestCase):
    """The pass that runs once every building is laid out: a town that would
    not fit is thinned, and what reaches the game fits (knoxbuild/build.py)."""

    def town(self, folder: str, budget: int | None = None) -> dict:
        settings = Settings(seed=7)
        name = os.path.basename(folder)
        if budget is None:
            build_town(folder, settings, compile_lots=False)
        else:
            with mock.patch.object(make_map_mod, "META_BUDGET", budget):
                build_town(folder, settings, compile_lots=False)
        files = sorted(glob.glob(os.path.join(folder, "buildings", "*.tbx")))
        rooms = {}
        for path in files:
            with open(path, encoding="utf-8", errors="replace") as f:
                rooms[os.path.basename(path)] = presets.measure(f.read())["rooms"]
        with open(os.path.join(folder, f"{name}_placements.csv"), encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        cells = placement.project_size(folder, name)
        return {"rooms": rooms, "files": set(rooms), "rows": len(rows),
                "cells": cells[0] * cells[1],
                "total": sum(rooms.values()),
                "cellars": sum(1 for n in rooms if n.endswith("_bsmt.tbx"))}

    def test_a_town_past_the_buffer_comes_out_thin_and_whole(self):
        with tempfile.TemporaryDirectory() as work:
            plain = self.town(os.path.join(work, "plain", "town"))
            self.assertGreater(plain["total"], 200)

            # A buffer that leaves room for three quarters of the town's rooms, basements
            # included - the same sum the game's map_meta.bin holds.
            allowed = plain["total"] * 3 // 4
            budget = (10 * allowed
                      + 23 * (plain["rows"] + plain["cellars"])
                      + 8 * plain["cells"] + make_map_mod.KNOX_COUNTY_META)
            thin = self.town(os.path.join(work, "thin", "town"), budget)

            self.assertLess(thin["total"], plain["total"], "nothing was thinned")
            self.assertLessEqual(thin["total"], allowed,
                                 "more rooms than the buffer holds")
            self.assertEqual(thin["files"], plain["files"], "a building was lost")
            self.assertEqual(thin["rows"], plain["rows"], "a placement was lost")
            self.assertEqual(thin["cellars"], plain["cellars"], "a basement was lost")


if __name__ == "__main__":
    unittest.main()