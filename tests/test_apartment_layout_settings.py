import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import replace
from itertools import groupby
from math import cos, radians, sin
from statistics import median
from unittest.mock import patch

import numpy as np

from knoxbuild.apartment_sections import split_sections
from knoxbuild.audit import audit
from knoxbuild.buildtiles import level_tiles, parse_tbx
from knoxbuild.footprint import Footprint
from knoxbuild.layout import Plan, Room, build_building
from knoxbuild.layout.access import door_sides, shared_paths, stair_tiles
from knoxbuild.layout.dwellings import _paint, _unit_touches_corridor
from knoxbuild.layout.flat_planning import replan_flats
from knoxbuild.layout.furnishing import _blocks, _carve_shaft, _tiles_under
from knoxbuild.layout.mixed_ground import ApartmentSite, Section, build_site, site_from_osm
from knoxbuild.layout.openings import ApartmentAccessError, _room_at
from knoxbuild.pedestrian_access import PedestrianContext
from knoxbuild.profile import ApartmentAccessRules, BuildingProfile
from knoxbuild.settings import Settings
from knoxbuild.sizing import SIZES
from knoxbuild.street_context import _entrances_by_unit, mapped_rooms_by_floor
from knoxbuild.tbx import render_tbx
from knoxbuild.uses import GroundBusiness, ground_businesses


class ApartmentLayoutSettings(unittest.TestCase):
    def test_studio_can_fit_bathroom_when_the_threshold_is_a_narrow_nook(self):
        plan = Plan(10, 8, rooms=[Room(1, 1, 8, 7, kind="openplan", unit=1)],
                    doors=[(4, 1, "N")], private_flats=True)
        plan.grid = [[int((x == 4 and y == 1) or (1 <= x <= 8 and y >= 2))
                      for x in range(10)] for y in range(8)]
        replan_flats(plan, set())
        self.assertIn((4, 1, "N"), plan.doors)
        bath, = [r for r in plan.rooms if r.kind == "bathroom"]
        self.assertGreaterEqual(bath.area, 6)
        for door in plan.doors:
            first, second = (_room_at(plan, *p) for p in door_sides(door))
            if first and second and bath in [plan.rooms[first - 1], plan.rooms[second - 1]]:
                break
        else:
            self.fail("The bathroom has no usable door")

    def test_inferred_entrances_use_the_yard_only_with_a_way_in(self):
        w, h = 24, 18
        x, y = 20, 20
        mask = np.ones((h, w), dtype=bool)
        footprint = Footprint(x, y, mask, 0, h, w)
        occupied = np.zeros((64, 64), dtype=bool)
        occupied[y:y + h, x:x + w] = True
        street = np.zeros_like(occupied)
        street[10:14, :] = True
        pavement = np.zeros_like(occupied)
        pavement[14:19, :] = True
        pavement[17:45, 15:17] = True
        pavement[43:45, 15:44] = True
        pavement[38:45, 20:44] = True
        fences = {(u, 48, "N") for u in range(20, 44)}
        fences.update((u, v, "W") for u in (20, 44) for v in range(38, 48))
        shop = GroundBusiness("bakery", "bakerykitchen", (8, 1))
        section = Section(0, 0, w, h, None, "N", ())

        for gate_open in (False, True):
            with self.subTest(gate_open=gate_open):
                blocked = fences - {(20, 43, "W")} if gate_open else fences
                context = PedestrianContext(occupied, street, street, np.zeros_like(street),
                                            pavement, blocked)
                approaches = context.approaches(footprint)
                self.assertEqual(any(door.side == "S" for door in approaches), gate_open)
                building = build_site(ApartmentSite((section,), (shop,), approaches=approaches),
                                      w, h, 5, Settings(apartment_layout="auto"), None, {}, 19, "N")
                chosen = {item["kind"]: item for item in building.entrance_report}
                self.assertEqual(chosen["shop"]["facade"], "N")
                self.assertEqual(chosen["staircase"]["facade"] == "S", gate_open)
                self.assertTrue(all(r["source"] == "inferred" for r in chosen.values()))

    def test_two_mapped_stairwells_on_opposite_facades_keep_both_doors(self):
        w, h = 24, 18
        fp = Footprint(0, 0, np.ones((h, w), dtype=bool), 0, h, w)
        points = [(12, 0, {"entrance": "staircase", "ref": "A"}),
                  (12, h, {"entrance": "staircase", "ref": "B"})]
        parts = split_sections(fp, points, 5, "auto", "N")
        self.assertEqual([(p.x0, p.y0, p.width, p.height) for p in parts],
                         [(0, 0, 24, 9), (0, 9, 24, 9)])
        sections = tuple(Section(p.x0, p.y0, p.width, p.height, p.mask_list(), "N", tuple(ports))
                         for p, ports in zip(parts, _entrances_by_unit(points, parts)))
        built = build_site(ApartmentSite(sections, (), tuple(points)), w, h, 5,
                           Settings(apartment_layout="auto"), None, {}, 19, "N")
        self.assertEqual([len(built.stairs_at(z)) for z in range(4)], [2] * 4)
        self.assertEqual([(r["ref"], r["facade"], r["status"], r["door"])
                          for r in built.entrance_report],
                         [("A", "N", "placed", [12, 0, "N"]),
                          ("B", "S", "placed", [12, 18, "N"])])
        self.assert_public_entrance(built, (12, 0, "N"), (12, 0))

    def test_inferred_doors_do_not_reopen_closed_mapped_entrances(self):
        w, h = 24, 18
        points = ((12, 0, {"entrance": "staircase", "access": "no"}),
                  (13, 0, {"entrance": "no"}),
                  (14, 0, {"entrance": "staircase", "locked": "yes"}),
                  (15, 0, {"entrance": "yes", "foot": "no"}))
        site = ApartmentSite((Section(0, 0, w, h, None, "N", ()),),
                             (GroundBusiness("bakery", "bakerykitchen", (13, 1)),), points)
        built = build_site(site, w, h, 5, Settings(apartment_layout="auto"), None, {}, 19, "N")
        self.assertTrue({(x, 0, "N") for x, _, _ in points}.isdisjoint(built.storeys[0].doors))
        self.assertEqual([r["status"] for r in built.entrance_report], ["closed"] * len(points))
        self.assertEqual([r["reason"] for r in built.entrance_report],
                         ["mapped_entrance_closed"] * len(points))
        self.assertEqual(len(built.stairs_at(0)), 1)

    def test_mapped_shop_on_a_shared_wall_is_reported_with_no_facade_change(self):
        w, h = 24, 18
        section = Section(0, 0, w, h, None, "N", ((11, h, {"entrance": "staircase"}),))
        shop = GroundBusiness("bakery", "bakerykitchen", (7, 1), "Bakery", (7, 0))
        built = build_site(ApartmentSite((section,), (shop,)), w, h, 5,
                           Settings(apartment_layout="auto"), None,
                           {(x, 0, "N"): 5 for x in range(w)}, 19, "N")
        self.assertEqual(built.unplaced_businesses, ("Bakery",))
        self.assertFalse(any(r.business for r in built.storeys[0].rooms))
        report, = [r for r in built.entrance_report if r["kind"] == "shop"]
        self.assertEqual((report["facade"], report["status"], report["reason"], report["door"]),
                         ("N", "unplaced", "facade_is_shared_wall", None))

    def test_replans_a_merged_footprint_and_keeps_the_landing_door(self):
        # The second dwelling has no approach of its own. Its old large
        # room is part of the new plan, down to the wall and door positions.
        plan = Plan(15, 8, core=(0, 0, 1, 7), private_flats=True,
                    rooms=[Room(2, 0, 7, 7, kind="hall", unit=1),
                           Room(8, 0, 14, 7, kind="openplan", unit=2)])
        _paint(plan)
        merged = _unit_touches_corridor(plan)
        self.assertEqual(merged, {1})
        front = (2, 3, "W")
        plan.doors = [front, (8, 3, "W")]

        replan_flats(plan, merged)

        self.assertIn(front, plan.doors)
        self.assertEqual({r.unit for r in plan.rooms if r.unit}, {1})
        self.assertEqual(sum(bool(i) for row in plan.grid for i in row), 120)
        self.assert_flat_entries(plan)
        self.assert_bath_opens_to_entry(plan)
        self.assertLess(max(r.area for r in plan.rooms if r.unit), 56)

    def test_reconsiders_a_stretched_kitchen_with_an_indirect_bathroom_door(self):
        rooms = [Room(2, 0, 3, 1, kind="hall", unit=1, fixed=True, apartment_entry=True),
                 Room(4, 0, 11, 1, kind="kitchen", unit=1, fixed=True),
                 Room(12, 0, 14, 1, kind="bathroom", unit=1, fixed=True),
                 Room(2, 2, 9, 5, kind="livingroom", unit=1, fixed=True),
                 Room(10, 2, 14, 5, kind="bedroom", unit=1, fixed=True)]
        plan = Plan(15, 6, core=(0, 0, 1, 5), private_flats=True, rooms=rooms)
        _paint(plan)
        plan.doors = [(2, 0, "W"), (4, 0, "W"), (12, 0, "W"),
                      (3, 2, "N"), (10, 3, "W")]

        replan_flats(plan, set())

        self.assert_flat_entries(plan)
        self.assert_bath_opens_to_entry(plan)
        self.assertTrue(any(r.kind in ("kitchen", "openplan") for r in plan.rooms))
        for room in plan.rooms:
            if room.kind == "kitchen":
                self.assertLessEqual(max(room.w, room.h) / min(room.w, room.h),
                                     SIZES["kitchen"].aspect)

    def test_replans_a_cramped_foyer_with_an_open_passage_to_the_living_room(self):
        plan = Plan(11, 8, core=(0, 0, 1, 7), private_flats=True, rooms=[
            Room(2, 2, 3, 3, kind="hall", unit=1, apartment_entry=True),
            Room(2, 0, 3, 1, kind="bathroom", unit=1),
            Room(4, 0, 10, 3, kind="openplan", unit=1),
            Room(2, 4, 10, 7, kind="bedroom", unit=1),
        ])
        _paint(plan)
        front = (2, 2, "W")
        plan.doors = [front, (3, 2, "N"), (4, 3, "W"), (3, 4, "N")]

        replan_flats(plan, set())

        self.assertIn(front, plan.doors)
        self.assert_flat_entries(plan)
        entry, = [i for i, r in enumerate(plan.rooms, 1) if r.apartment_entry]
        self.assertEqual(plan.rooms[entry - 1].kind, "hall")
        self.assertGreaterEqual(sum(row.count(entry) for row in plan.grid), 6)
        passage, = plan.open_edge
        sides = {_room_at(plan, *p) for p in door_sides(passage)}
        self.assertIn(entry, sides)
        self.assertTrue({plan.rooms[i - 1].kind for i in sides} & {"openplan", "livingroom"})
        self.assert_bath_opens_to_entry(plan)

    def test_two_bedrooms_and_living_room_share_the_only_available_facade(self):
        width, height = 12, 10
        home = {(x, y) for x in range(2, width) for y in range(height)}
        hall = {(x, y) for x in (2, 3) for y in (4, 5)}
        bath = {(x, y) for x in (4, 5) for y in (4, 5, 6)}
        bedroom = {(x, y) for x in (6, 7, 8) for y in (4, 5, 6)}
        front = (2, 4, "W")
        plan = Plan(width, height, private_flats=True, rooms=[
            Room(0, 0, 1, 9, kind="hall", is_core=True),
            Room(2, 4, 3, 5, kind="hall", unit=1, apartment_entry=True),
            Room(4, 4, 5, 6, kind="bathroom", unit=1),
            Room(6, 4, 8, 6, kind="bedroom", unit=1),
            Room(2, 0, 11, 9, kind="openplan", unit=1),
        ], doors=[front, (4, 5, "W"), (6, 5, "W"), (3, 4, "N")])
        plan.party = {(x, y, "N") for x in range(width) for y in (0, height)}
        plan.grid = [[1, 1] + [5] * (width - 2) for _ in range(height)]
        for i, tiles in enumerate((hall, bath, bedroom), 2):
            for x, y in tiles:
                plan.grid[y][x] = i

        replan_flats(plan, set())

        self.assertIn(front, plan.doors)
        self.assertEqual({(x, y) for y, row in enumerate(plan.grid) for x, i in enumerate(row)
                          if plan.rooms[i - 1].unit}, home)
        beds = {i for i, r in enumerate(plan.rooms, 1) if r.kind == "bedroom"}
        living, = [i for i, r in enumerate(plan.rooms, 1) if r.kind == "openplan"]
        entry, = [i for i, r in enumerate(plan.rooms, 1) if r.apartment_entry]
        self.assertEqual(len(beds), 2)
        self.assertLessEqual(beds | {living}, {row[-1] for row in plan.grid})
        door_pairs = [{_room_at(plan, *p) for p in door_sides(door)} for door in plan.doors]
        self.assertTrue(all({entry, bed} in door_pairs for bed in beds))
        self.assert_bath_opens_to_entry(plan)

    def assert_bath_opens_to_entry(self, plan):
        entrance, = [i for i, r in enumerate(plan.rooms, 1) if r.apartment_entry]
        bath, = [i for i, r in enumerate(plan.rooms, 1) if r.kind == "bathroom"]
        pairs = [{_room_at(plan, *tile) for tile in door_sides(edge)} for edge in plan.doors]
        self.assertIn({entrance, bath}, pairs)

    def test_settings_are_opt_in_and_available_to_the_buildings_tab(self):
        from app import app

        payload = app.test_client().get("/api/settings").get_json()
        self.assertEqual(payload["current"]["apartment_layout"], "classic")
        self.assertEqual(payload["current"]["apartment_furnishing"], 0)
        self.assertEqual({value for value, _ in payload["options"]["apartment_layout"]},
                         {"classic", "auto", "landing", "corridor"})
        self.assertEqual(payload["limits"]["apartment_furnishing"], [0, 1])
        self.assertEqual({value for value, _ in payload["options"]["apartment_ground_floor"]},
                         {"auto", "residential", "mixed"})
        custom = Settings.from_dict({"apartment_layout": "landing", "apartment_furnishing": 1})
        self.assertEqual(Settings.from_dict(custom.to_dict()), custom)
        self.assertEqual(Settings.from_dict({"apartment_layout": "junk"}).apartment_layout,
                         "classic")

    def test_compact_landing_can_serve_four_flats_in_a_narrow_section(self):
        entrance = [(8.5, 14, {"entrance": "staircase"})]
        built = build_building(18, 14, levels=5, kind="apartment", seed=5,
                               settings=Settings(apartment_layout="auto"),
                               entrances=entrance)
        self.assertEqual(len(built.storeys), 5)
        self.assertEqual(len(built.stairs), 4)
        self.assert_public_entrance(built, (8, 14, "N"), (8, 13))
        for plan in built.storeys:
            self.assertFalse(plan.shafts)
            x0, y0, x1, y1 = plan.core
            self.assertEqual((x1 - x0 + 1, y1 - y0 + 1), (2, 7))
            self.assert_flat_entries(plan)
            units = {r.unit for r in plan.rooms if r.unit}
            self.assertEqual(len(units), 4)
            for unit in units:
                rooms = [r for r in plan.rooms if r.unit == unit]
                hall, = [r for r in rooms if r.kind == "hall" and not r.is_balcony]
                bath, = [r for r in rooms if r.kind == "bathroom"]
                bedroom, = [r for r in rooms if r.kind == "bedroom"]
                self.assertTrue(hall.apartment_entry)
                self.assertIn(bath.area, (6, 9))
                self.assertGreaterEqual(bedroom.area, 12)

    def test_long_sections_put_apartment_doors_along_the_length_of_the_building(self):
        for width, height, levels, portals, exterior in (
                (56, 14, 5, [(28.5, 0, {"entrance": "staircase"})],
                 [(28, 0, "N")]),
                (14, 56, 6, [(0, 12.5, {"entrance": "staircase", "ref": "A"}),
                             (14, 42.5, {"entrance": "staircase", "ref": "A"})],
                 [(0, 12, "W"), (14, 42, "W")]),
        ):
            with self.subTest(width=width, height=height):
                building = build_building(width, height, levels=levels, kind="apartment",
                                          seed=19, settings=Settings(apartment_layout="auto"),
                                          entrances=portals)
                self.assertEqual(len(building.storeys), levels)
                self.assertEqual(len(building.stairs), levels - 1)
                ground, upper = building.storeys[0], building.storeys[-1]
                for door in exterior:
                    self.assertIn(door, ground.doors)
                    inside, = [p for p in door_sides(door) if _room_at(ground, *p)]
                    self.assert_public_entrance(building, door, inside)
                    seen, pending = {inside}, [inside]
                    while pending:
                        x, y = pending.pop()
                        neighbours = {(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)}
                        frontier = neighbours & ground.public_path - seen
                        seen.update(frontier)
                        pending.extend(frontier)
                    self.assertIn(stair_tiles(building.stairs[0])[-1], seen)
                long_axis = int(height > width)
                hall = [(x, y) for y, row in enumerate(upper.grid) for x, i in enumerate(row)
                        if i and upper.rooms[i - 1].is_core and not upper.rooms[i - 1].access_role]
                cx0, cy0, cx1, cy1 = upper.core
                landing = range(cy0, cy1 + 1) if long_axis else range(cx0, cx1 + 1)
                sections = {p[long_axis] for p in hall if p[long_axis] not in landing}
                self.assertGreater(len(sections), 56 // 2)
                self.assertTrue(all(sum(p[long_axis] == t for p in hall) == 2 for t in sections))
                self.assertGreater(min(p[long_axis] for p in hall), 0)
                self.assertLess(max(p[long_axis] for p in hall), 55)
                for end in (0, 55):
                    for across in range(14):
                        p = (across, end) if long_axis else (end, across)
                        room = _room_at(upper, *p)
                        self.assertGreater(room, 0)
                        self.assertGreater(upper.rooms[room - 1].unit, 0)
                self.assertEqual(len(upper.shafts), int(levels == 6))
                self.assertGreater(len({r.unit for r in upper.rooms if r.unit}), 4)
                for p in building.storeys:
                    self.assert_flat_entries(p)

    def test_long_stairwells_separated_by_flats_on_both_sides_of_the_joint(self):
        sections = tuple(Section(x, 0, 32, 14, None, "N",
                                 ((16.5, 0, {"entrance": "staircase"}),))
                         for x in (0, 32))
        building = build_site(ApartmentSite(sections, ()), 64, 14, 5,
                              Settings(apartment_layout="auto"), None, {}, 13, "N")
        for plan in building.storeys:
            self.assertEqual(sum(room.is_core for room in plan.rooms), 2)
            end_units = set()
            for x in (0, 31, 32, 63):
                for y in range(14):
                    room = _room_at(plan, x, y)
                    self.assertGreater(room, 0)
                    self.assertGreater(plan.rooms[room - 1].unit, 0)
                    end_units.add(plan.rooms[room - 1].unit)
            areas = Counter(plan.rooms[i - 1].unit for row in plan.grid for i in row
                            if i and plan.rooms[i - 1].unit)
            self.assertGreaterEqual(min(areas[unit] for unit in end_units),
                                    2 * median(areas.values()) / 3)
            self.assert_flat_entries(plan)

    def test_ground_lobby_prefers_surveyed_geometry_to_building_age(self):
        footprint = (26, 18)
        entrance = ((13.5, 0, {"entrance": "staircase"}),)
        polygon = ((9, 0), (17, 0), (17, 4), (14, 4), (14, 6), (9, 6))
        counts = {}
        for variant, year, lobbies, load in (
                ("compact", 1960, (), None), ("recent", 2018, (), None),
                ("few_flats", 2018, (), 4), ("many_flats", 1960, (), 32),
                ("mapped", 1960, (polygon,), None)):
            profile = BuildingProfile.infer({"start_date": str(year)}, "apartment",
                                            .3, 468, 5, seed=5)
            section = Section(0, 0, *footprint, None, "N", entrance, lobbies, load)
            built = build_site(ApartmentSite((section,), ()), *footprint, 5,
                               Settings(apartment_layout="auto"), profile, {}, 13, "N")
            ground, upper = built.storeys[:2]

            def core_tiles(plan):
                return {(x, y) for y, row in enumerate(plan.grid) for x, i in enumerate(row)
                        if i and plan.rooms[i - 1].is_core}

            counts[variant] = len(core_tiles(ground))
            self.assertEqual(len(core_tiles(upper)), counts["compact"])
            self.assert_public_entrance(built, (13, 0, "N"), (13, 0))
            self.assert_flat_entries(ground)
            if lobbies:
                self.assertIn((9, 5), core_tiles(ground))
                self.assertNotIn((9, 5), core_tiles(upper))
                self.assertNotIn((16, 5), core_tiles(ground))
        self.assertEqual(counts["compact"], counts["few_flats"])
        self.assertLess(counts["compact"], counts["recent"])
        self.assertLess(counts["compact"], counts["many_flats"])
        self.assertLess(counts["recent"], counts["mapped"])

    def test_lift_is_reserved_before_apartments_are_painted(self):
        def verify_reserved(plan, shaft, door):
            x0, y0, x1, y1 = shaft
            self.assertTrue(all(plan.grid[y][x] == 0 for y in range(y0, y1 + 1)
                                for x in range(x0, x1 + 1)))
            _carve_shaft(plan, shaft, door)

        with patch("knoxbuild.layout.assemble._carve_shaft", side_effect=verify_reserved) as carve:
            built = build_building(28, 20, levels=6, kind="apartment", seed=9,
                                   settings=Settings(apartment_layout="auto"))
        self.assertGreaterEqual(carve.call_count, 6)
        for plan in built.storeys:
            ((x0, y0, x1, y1), door), = plan.shafts
            border = ([(x, y) for x in range(x0, x1 + 1) for y in (y0 - 1, y1 + 1)]
                      + [(x, y) for y in range(y0, y1 + 1) for x in (x0 - 1, x1 + 1)])
            rooms_at = [plan.rooms[i - 1] for tile in border if (i := _room_at(plan, *tile))]
            self.assertTrue(any(r.access_role == "stairs" for r in rooms_at))
            x, y, direction = door
            if direction == "N":
                rear = [(i, y1 + 1 if y == y0 else y0 - 1) for i in range(x0, x1 + 1)]
            else:
                rear = [(x1 + 1 if x == x0 else x0 - 1, i) for i in range(y0, y1 + 1)]
            self.assertTrue(set(rear).isdisjoint(plan.clear_access))
            rooms = [plan.rooms[_room_at(plan, *tile) - 1] for tile in door_sides(door)]
            self.assertEqual(sum(r.access_role == "lift_lobby" for r in rooms), 1)
            self.assertEqual(sum(r.is_shaft for r in rooms), 1)
            self.assertLessEqual(plan.clear_access, plan.public_path)
            self.assertTrue(all(not plan.clear_access.intersection(_tiles_under(*f))
                                for f in plan.furniture if _blocks(f[0])))
            stair_doors = [{plan.rooms[i - 1].access_role for p in door_sides(edge)
                            if (i := _room_at(plan, *p))} for edge in plan.doors]
            self.assertEqual([roles for roles in stair_doors if "stairs" in roles],
                             [{"lift_lobby", "stairs"}])

    def test_long_corridor_reaches_stairs_without_entering_the_lift_lobby(self):
        building = build_building(56, 14, 6, kind="apartment", seed=9,
                                  settings=Settings(apartment_layout="auto"))
        for level, plan in enumerate(building.storeys):
            with self.subTest(level=level):
                self.assertEqual(len(plan.shafts), 1)
                approaches = []
                for door in plan.doors:
                    rooms = [plan.rooms[i - 1] for p in door_sides(door)
                             if (i := _room_at(plan, *p))]
                    if any(r.access_role == "stairs" for r in rooms):
                        approaches.extend(r for r in rooms if r.access_role != "stairs")
                approach, = approaches
                self.assertTrue(approach.is_core)
                self.assertIsNone(approach.access_role)

    def test_building_profile_can_override_lift_height_and_keep_the_mapped_entrance(self):
        profile = BuildingProfile.infer({}, "apartment", 0.2, 280, 5, seed=5)
        settings = Settings(apartment_layout="auto")
        entrance = [(8.5, 14, {"entrance": "staircase"})]

        def build(profile, settings=settings):
            return build_building(20, 14, levels=5, kind="apartment", seed=5,
                                  settings=settings, profile=profile, entrances=entrance)

        default = build(profile)
        lifted = build(replace(profile, apartment_access=ApartmentAccessRules(lift_from_levels=4)))
        self.assertFalse(default.storeys[0].shafts)
        self.assertTrue(all(p.shafts for p in lifted.storeys))
        self.assert_public_entrance(default, (8, 14, "N"), (8, 13))
        self.assert_public_entrance(lifted, (8, 14, "N"), (8, 13))

        corridor = build(replace(profile, apartment_access=ApartmentAccessRules(
            compact_landing_max_levels=4)))
        self.assertNotEqual(corridor.storeys[0].core, default.storeys[0].core)
        self.assertFalse(corridor.storeys[0].shafts)
        classic = build(profile, Settings())
        self.assertTrue(all(p.shafts for p in classic.storeys))

    def test_balcony_routes_to_stairs_and_exports_a_walkable_deck(self):
        settings = Settings.from_dict({"apartment_layout": "auto", "apartment_stair_balcony": 1})
        building = build_building(56, 14, 6, kind="apartment", seed=19, settings=settings)
        self.assertFalse(any(r.access_role == "balcony" for r in building.storeys[0].rooms))
        parsed = parse_tbx(render_tbx(building, "Open stair passage"))
        for z, plan in enumerate(building.storeys[1:], 1):
            balcony, = [i for i, r in enumerate(plan.rooms, 1) if r.access_role == "balcony"]
            deck = {(x, y) for y, row in enumerate(plan.grid) for x, rid in enumerate(row)
                    if rid == balcony}
            stair_doors = [{plan.rooms[i - 1].access_role for p in door_sides(edge)
                            if (i := _room_at(plan, *p))} for edge in plan.doors]
            self.assertEqual([roles for roles in stair_doors if "stairs" in roles],
                             [{"balcony", "stairs"}])
            self.assertIn({"lift_lobby", "balcony"}, stair_doors)
            rails = [e for e in plan.railing if deck.intersection(door_sides(e))]
            self.assertGreaterEqual(len(rails), 2)
            tiles = level_tiles(parsed, z)
            for p in deck:
                self.assertIn("carpentry_02_56", tiles[p])
            for x, y, _ in rails:
                self.assertTrue(any(t.startswith("fencing_01_") for t in tiles[x, y]))

    def test_wide_ground_passage_behind_a_single_mapped_door(self):
        building = build_building(56, 14, 5, kind="apartment", seed=19,
                                  settings=Settings(apartment_layout="auto"),
                                  entrances=[(28.5, 0, {"entrance": "staircase"})])
        ground = building.storeys[0]
        self.assertIn((28, 0, "N"), ground.doors)
        for y in range(6):
            self.assertGreaterEqual(sum((x, y) in ground.public_path for x in range(27, 30)), 2)

    def test_open_stair_passage_can_be_inferred_or_disabled(self):
        profile = BuildingProfile.infer({"start_date": "2018"}, "apartment", .2, 56 * 14, 6, 19)
        for mode in (0, 2):
            with self.subTest(mode=mode):
                b = build_building(56, 14, 6, kind="apartment", seed=19, profile=profile,
                                   settings=Settings(apartment_layout="auto", apartment_stair_balcony=mode))
                self.assertEqual(sum(r.access_role == "balcony" for r in b.rooms), 5 if mode == 2 else 0)

    def test_private_balcony_has_one_same_flat_door_and_facade_rails(self):
        tags = {"balcony": "yes"}
        profile = BuildingProfile.infer(tags, "apartment", .2, 32 * 22, 3, 11)
        b = build_building(32, 22, 3, kind="apartment", seed=11, profile=profile,
                           settings=Settings(apartment_layout="auto"))
        upper = b.storeys[1]
        balconies = {i for i, r in enumerate(upper.rooms, 1) if r.access_role == "flat_balcony"}
        self.assertTrue(balconies)
        self.assertFalse(any(r.is_balcony for r in b.storeys[0].rooms))
        for i in balconies:
            (a, b), = [pair for pair in map(door_sides, upper.doors)
                       if i in {_room_at(upper, *p) for p in pair}]
            if _room_at(upper, *a) != i:
                a, b = b, a
            other = _room_at(upper, *b)
            self.assertIn(upper.rooms[other - 1].kind, ("livingroom", "openplan"))
            self.assertEqual(upper.rooms[other - 1].unit, upper.rooms[i - 1].unit)
            dx, dy = b[0] - a[0], b[1] - a[1]
            room = upper.rooms[i - 1]
            deck = {(x, y) for y, row in enumerate(upper.grid) for x, rid in enumerate(row) if rid == i}
            self.assertEqual(room.area, len(deck))
            self.assertGreaterEqual(room.h if dx else room.w, 3)
            for x, y in deck:
                land, outside = (x + dx, y + dy), (x - dx, y - dy)
                if land not in deck:
                    self.assertEqual(_room_at(upper, *land), other)
                if outside not in deck:
                    self.assertFalse(_room_at(upper, *outside))
                    railing = (max(x, outside[0]), max(y, outside[1]), "W" if dx else "N")
                    self.assertIn(railing, upper.railing)
        self.assert_flat_entries(upper)

    def test_rooms_do_not_wrap_around_other_rooms_in_a_generated_flat(self):
        building = build_building(24, 18, 5, kind="apartment", seed=9,
                                  settings=Settings(apartment_layout="auto"))
        plan = building.storeys[1]
        self.assertTrue(any(room.kind == "bathroom" for room in plan.rooms))
        for line in (*plan.grid, *zip(*plan.grid)):
            for unit, segment in groupby(line, lambda i: plan.rooms[i - 1].unit if i else 0):
                if unit:
                    run = [room for room, _ in groupby(segment)]
                    self.assertEqual(len(run), len(set(run)), run)

    def test_auto_preserves_stock_commerce_but_explicit_mixed_mode_keeps_flats(self):
        class TileProjection:
            def to_px(self, lat, lon):
                return lon, lat

        w, h, levels = 53, 15, 5
        footprint = Footprint(0, 0, np.ones((h, w), dtype=bool), 0, h, w)
        portals = [(22.5, h, {"entrance": "staircase"}),
                   (28.5, 0, {"entrance": "shop", "name": "Market"})]
        points = [(28.5, 2, {"shop": "supermarket", "name": "Market", "level": "0"})]
        for mode in ("auto", "mixed", "residential"):
            with self.subTest(mode=mode):
                site = site_from_osm(footprint, {}, points, portals, {}, levels, "auto", mode,
                                     TileProjection(), lambda *_: "N", None, stock_venues=True)
                building = build_site(site, w, h, levels, Settings(apartment_layout="auto"),
                                      None, {}, 11, "N")
                self.assertEqual(any(r.unit for r in building.storeys[0].rooms), mode != "auto")
                self.assertEqual(any(r.business for r in building.storeys[0].rooms), mode != "residential")
                self.assertTrue(any(r.unit for r in building.storeys[1].rooms))

    def test_three_stairwells_split_one_high_rise_without_gaps_or_extra_cores(self):
        fp = Footprint(100, 200, np.ones((20, 84), dtype=bool), 0, 20, 84)
        entrances = [(100 + x, 220, {"entrance": "staircase", "ref": str(i)})
                     for i, x in enumerate((12.5, 41.5, 69.5), 1)]
        service = (140, 200, {"entrance": "service"})
        units = split_sections(fp, entrances + [service], 7, "auto", "S")
        self.assertEqual([(unit.x0, unit.width, unit.tiles) for unit in units],
                         [(100, 28, 560), (128, 28, 560), (156, 28, 560)])
        for unit, portals in zip(units, _entrances_by_unit(entrances, units)):
            x, y, _ = portals[0]
            built = build_building(unit.width, unit.height, levels=7, kind="apartment", seed=9,
                                   settings=Settings(apartment_layout="auto"), entrances=portals)
            self.assertEqual(len(built.storeys), 7)
            self.assertTrue(all(len(p.shafts) == 1 for p in built.storeys))
            self.assert_public_entrance(built, (int(x), int(y), "N"), (int(x), int(y) - 1))

    def test_duplicate_doors_do_not_create_extra_sections(self):
        fp = Footprint(0, 0, np.ones((20, 60), dtype=bool), 0, 20, 60)
        entrances = [(15, 0, {"entrance": "staircase", "ref": "stair A"}),
                     (16, 20, {"entrance": "staircase", "ref": "stair A"}),
                     (40, 0, {"entrance": "staircase", "level": "1"}),
                     (45, 0, {"entrance": "shop"})]
        self.assertEqual(split_sections(fp, entrances, 6, "auto", "N"), [fp])

    def test_furnishing_option_can_vary_placement_independently_of_layout(self):
        def flats(variety):
            return build_building(30, 22, levels=5, seed=19, kind="apartment",
                                  settings=Settings(apartment_furnishing=variety))

        original, built, rebuilt = flats(0), flats(1), flats(1)
        classic, varied, repeat = original.storeys, built.storeys, rebuilt.storeys
        self.assertEqual([p.grid for p in classic], [p.grid for p in varied])
        self.assertEqual([p.doors for p in classic], [p.doors for p in varied])
        self.assertEqual([p.furniture for p in varied], [p.furniture for p in repeat])
        beds = [{(x, y, d) for role, x, y, d in p.furniture
                 if role.startswith(("bed", "double_bed", "bunk_bed", "crib"))}
                for p in varied[1:]]
        self.assertEqual(len(beds), 4)
        self.assertTrue(all(beds))
        self.assertTrue(all(a != b for a, b in zip(beds, beds[1:])))

        tbx = render_tbx(built, "Flats")
        self.assertEqual(tbx, render_tbx(rebuilt, "Flats"))
        rooms = ET.fromstring(tbx).findall("room")
        before = ET.fromstring(render_tbx(original, "Flats")).findall("room")
        self.assertEqual([r.get("InternalName") for r in before],
                         [r.get("InternalName") for r in rooms])
        self.assertGreater(len({r.get("Floor") for r in rooms
                                if r.get("InternalName") == "bedroom"}), 1)

    def assert_public_entrance(self, building, door, inside):
        ground = building.storeys[0]
        self.assertIn(door, ground.doors)
        x, y = inside
        self.assertTrue(ground.rooms[ground.grid[y][x] - 1].is_core)
        problems = {name: count for name, count in audit(building, "apartment").items()
                    if not name.startswith("stat:")}
        self.assertEqual(problems, {})

    def test_diagonal_apartment_corridor_and_rooms_follow_the_facades(self):
        for angle in (27, -45):
            with self.subTest(angle=angle):
                direction = radians(angle)
                dx, dy = cos(direction), sin(direction)

                def coordinates(x, y):
                    x, y = x - 23, y - 23
                    return x * dx + y * dy, y * dx - x * dy

                mask = [[abs(u) < 20 and abs(v) < 8
                         for x in range(47) for u, v in [coordinates(x, y)]]
                        for y in range(47)]
                house = build_building(47, 47, 4, kind="apartment", mask=mask, street="S",
                                       seed=37, settings=Settings(apartment_layout="auto"))
                self.assertEqual(len(house.storeys), 4)
                plan = house.storeys[1]
                hall, rooms = [], {}
                for y, row in enumerate(plan.grid):
                    for x, i in enumerate(row):
                        self.assertEqual(bool(i), mask[y][x])
                        if not i:
                            continue
                        room = plan.rooms[i - 1]
                        if room.is_core:
                            hall.append(coordinates(x, y))
                        elif room.kind in {"openplan", "bedroom", "livingroom"}:
                            rooms.setdefault(i, []).append((x, y))
                along, across = zip(*hall)
                self.assertGreater(max(along) - min(along), 2 * (max(across) - min(across)))

                def fitted_box(cells):
                    a, b = zip(*cells)
                    return (max(a) - min(a) + 1) * (max(b) - min(b) + 1)

                # Living rooms and bedrooms keep more usable area when
                # measured relative to the facade than on the map axes.
                self.assertLess(sum(fitted_box([coordinates(*p) for p in cells])
                                    for cells in rooms.values()),
                                .9 * sum(fitted_box(cells) for cells in rooms.values()))
                self.assert_flat_entries(plan)
                self.assertFalse([key for key in audit(house, "apartment") if not key.startswith("stat:")])

    def test_entry_and_private_rooms_preserve_reachability_in_an_irregular_section(self):
        width, height = 24, 17
        mask = [[not (x >= 19 and y >= 12) for x in range(width)] for y in range(height)]
        for mode in ("auto", "landing", "corridor"):
            with self.subTest(mode=mode):
                building = build_building(width, height, 5, kind="apartment", mask=mask,
                                          settings=Settings(apartment_layout=mode), seed=19)
                self.assertEqual(len(building.storeys), 5)
                for plan in building.storeys:
                    self.assert_flat_entries(plan)

    def test_compact_flat_enters_through_its_planned_room(self):
        for width, height in ((6, 6), (7, 8)):
            with self.subTest(size=(width, height)):
                plan = build_building(width, height, kind="apartment", seed=1,
                                      settings=Settings(apartment_layout="auto")).storeys[0]
                front, = [plan.rooms[(a or b) - 1] for door in plan.doors
                          for a, b in [tuple(_room_at(plan, *p) for p in door_sides(door))]
                          if bool(a) != bool(b)]
                self.assertTrue(front.apartment_entry)
                self.assertIn(front.kind, ("hall", "kitchen", "openplan"))

    def test_shared_route_cannot_cross_stair_steps_or_open_onto_a_hole(self):
        plan = Plan(1, 7, rooms=[Room(0, 0, 0, 6, is_core=True)],
                    grid=[[1] for _ in range(7)], doors=[(0, 0, "N")])
        with self.assertRaises(ApartmentAccessError):
            shared_paths(plan, to_above=[(0, 1, "N")], ground=True)
        plan.rooms.append(Room(1, 0, 1, 6, unit=1))
        plan.width = 2
        plan.grid = [[1, 2] for _ in range(7)]
        plan.doors.append((1, 1, "W"))
        plan.holes.add((0, 1))
        with self.assertRaises(ApartmentAccessError):
            shared_paths(plan, ground=True)

    def assert_flat_entries(self, plan):
        links = {i: set() for i in range(1, len(plan.rooms) + 1)}
        for door in [*plan.doors, *plan.open_edge]:
            a, b = (_room_at(plan, *tile) for tile in door_sides(door))
            if a and b and a != b:
                links[a].add(b)
                links[b].add(a)
        units = {r.unit for r in plan.rooms if r.unit}
        for unit in units:
            members = {i for i in links if plan.rooms[i - 1].unit == unit}
            self.assertLessEqual(sum(plan.rooms[i - 1].kind == "bathroom" for i in members), 1)
            approaches = [(i, j) for i in members for j in links[i] if j not in members]
            self.assertEqual(len(approaches), 1)
            first, hall = approaches[0]
            self.assertTrue(plan.rooms[hall - 1].is_core)
            self.assertTrue(plan.rooms[first - 1].apartment_entry)
            self.assertIn(plan.rooms[first - 1].kind, ("hall", "kitchen", "openplan"))
            seen, queue = {first}, [first]
            while queue:
                i = queue.pop()
                if plan.rooms[i - 1].kind in ("bedroom", "kidsbedroom", "bathroom"):
                    self.assertEqual(len(links[i]), 1)
                else:
                    next_rooms = links[i] & members - seen
                    seen.update(next_rooms)
                    queue.extend(next_rooms)
            self.assertEqual(seen, members)
        solid = {tile for role, x, y, d in plan.furniture if _blocks(role)
                 for tile in _tiles_under(role, x, y, d)}
        self.assertFalse(solid & plan.public_path)

    def test_a_wide_shop_can_span_sections_beside_two_separate_bakeries(self):
        sections = tuple(Section(x, 0, 23, 18, [[True] * 23 for _ in range(18)], "N",
                                 ((10, 18, {"entrance": "staircase"}),))
                         for x in (0, 23, 46))
        site = ApartmentSite(sections, (
            GroundBusiness("grocery", "grocerystorage", (22, 0)),
            GroundBusiness("bakery", "bakerykitchen", (36, 1)),
            GroundBusiness("bakery", "bakerykitchen", (58, 1)),
        ))
        building = build_site(site, 69, 18, 6, Settings(apartment_layout="auto"),
                              None, {}, 19, "N")
        ground = building.storeys[0]
        self.assertEqual(len(building.stairs_at(0)), 3)
        self.assertEqual(len(ground.shafts), 3)
        self.assertFalse(building.unplaced_businesses)
        grocery, = [r for r in ground.rooms if r.kind == "grocery"]
        self.assertLess(grocery.x0, 23)
        self.assertGreaterEqual(grocery.x1, 23)
        self.assertEqual(len({r.business for r in ground.rooms if r.kind == "bakery"}), 2)
        outside = [ground.rooms[(a or b) - 1] for door in ground.doors
                   for a, b in [tuple(_room_at(ground, *tile) for tile in door_sides(door))]
                   if bool(a) != bool(b)]
        self.assertEqual(sum(r.is_core for r in outside), 3)
        self.assertEqual({r.business for r in outside if r.business}, {1, 2, 3})
        self.assert_flat_entries(ground)
        for plan in building.storeys[1:]:
            self.assert_flat_entries(plan)
        parsed = parse_tbx(render_tbx(building, "Mixed block"))
        for z in range(len(building.storeys) - 1):
            here, above = level_tiles(parsed, z), level_tiles(parsed, z + 1)
            self.assertEqual(len([o for o in parsed.floors[z].objects if o["type"] == "stairs"]), 3)
            for flight in building.stairs_at(z):
                top, _landing, *steps, foot = stair_tiles(flight)
                self.assertTrue(any(t.startswith("floors_") for t in here[foot]))
                self.assertTrue(any(t.startswith("floors_") for t in above[top]))
                for step in steps:
                    self.assertTrue(any(t.startswith("fixtures_stairs_") for t in here[step]))

    def test_deep_mixed_block_keeps_wide_flats_and_uses_the_osm_count(self):
        class TileProjection:
            def to_px(self, lat, lon):
                return lon, lat

        w, h, levels = 43, 27, 12
        footprint = Footprint(0, 0, np.ones((h, w), dtype=bool), 0, h, w)
        settings = Settings(apartment_layout="auto")
        entrances = [(21.6, 27.1, {"entrance": "staircase", "ref": "A"}),
                     (32.6, .1, {"entrance": "shop", "name": "Market"})]
        points = [(32.6, 3.6, {"shop": "supermarket", "name": "Market", "level": "0"})]
        lobby = {"room": "lobby", "ring": [(15.1, 27.1), (27.1, 27.1), (27.1, 21.1),
                                          (23.1, 21.1), (23.1, 19.1), (15.1, 19.1)]}
        for declared, expected in ((96, 8), (72, 6), (None, 8)):
            with self.subTest(declared=declared):
                tags = {"building": "apartments", "start_date": "2018"}
                if declared is not None:
                    tags["building:flats"] = str(declared)
                profile = BuildingProfile.infer(tags, "apartment", .2, w * h, levels, seed=409)
                site = site_from_osm(footprint, tags, points, entrances, {0: [lobby]},
                                     levels, "auto", "auto", TileProjection(), lambda *_: "N", profile)
                built = build_site(site, w, h, levels, settings, profile, {}, 409, "N")
                upper = built.storeys[1]
                facade = {unit: sum(upper.rooms[i - 1].unit == unit for side in (0, h - 1)
                                    for i in upper.grid[side] if i)
                          for unit in {r.unit for r in upper.rooms if r.unit}}
                self.assertEqual(len(facade), expected)
                self.assertGreaterEqual(min(facade.values()), 8)
                self.assertFalse(built.unplaced_businesses)
                self.assertTrue(any(r.kind == "grocery" and r.business for r in built.storeys[0].rooms))
                self.assertEqual(len(upper.shafts), 1)
                self.assertEqual([len(built.stairs_at(z)) for z in range(levels - 1)], [1] * (levels - 1))
                self.assertFalse({key: count for key, count in audit(built, "apartment").items()
                                  if count and not key.startswith("stat:")})

    def test_same_apartment_footprint_with_full_partial_and_empty_osm(self):
        class TileProjection:
            def to_px(self, lat, lon):
                return lon, lat

        w, h, levels = 96, 16, 5
        footprint = Footprint(0, 0, np.ones((h, w), dtype=bool), 0, h, w)
        settings = Settings(apartment_layout="auto")
        entrances = [(x, 0, {"entrance": "staircase", "ref": str(x)}) for x in (16, 48, 80)]
        shop_door = (88, 0, {"entrance": "shop", "name": "Bakery"})
        bakery = {"shop": "bakery", "name": "Bakery"}
        upstairs = (20, 3, {"shop": "books", "level": "1"})
        kitchen = {"room": "kitchen", "level": "0",
                   "ring": [(2, 2), (8, 2), (8, 5), (5, 5), (5, 7), (2, 7)]}
        office = {"room": "office", "level": "1", "ring": [(36, 2), (42, 2), (42, 6), (36, 6)]}
        kitchen_tiles = {(x, y) for y in range(2, 7) for x in range(2, 8) if x < 5 or y < 5}
        office_tiles = {(x, y) for y in range(2, 6) for x in range(36, 42)}
        cases = (
            ("full", [*entrances, shop_door], [(88, 2, {**bakery, "level": "0"}), upstairs],
             [kitchen, office], {0: ("kitchen", kitchen_tiles), 1: ("office", office_tiles)}),
            ("partial", [entrances[0], shop_door], [(88, 2, bakery), upstairs],
             [kitchen], {0: ("kitchen", kitchen_tiles)}),
            ("empty", [], [], [], {}),
        )
        for name, doors, points, rooms, surveyed in cases:
            with self.subTest(osm=name):
                site = site_from_osm(footprint, {"building": "apartments", "start_date": "2014"},
                                     points, doors, mapped_rooms_by_floor(rooms, levels),
                                     levels, "auto", "auto", TileProjection(), lambda *_: "N", None)
                building = build_site(site, w, h, levels, settings, None, {}, 19, "N")
                self.assertEqual(len(building.storeys), levels)
                self.assertEqual([len(building.stairs_at(z)) for z in range(levels - 1)], [3] * 4)
                report = {tuple(item["position"]): item for item in building.entrance_report}
                self.assertEqual(set(report), {(x, y) for x, y, _ in doors})
                for x, y, tags in doors:
                    item = report[x, y]
                    self.assertIn(item["status"], ("placed", "snapped"))
                    self.assertEqual((item["facade"], item["door"][1:]), ("N", [y, "N"]))
                    self.assertLessEqual(abs(item["door"][0] - x), 2)
                    self.assertEqual(item["kind"], tags["entrance"])
                external = [floor.rooms[(a or b) - 1]
                            for floor in building.storeys[:1] for edge in floor.doors
                            for a, b in [tuple(_room_at(floor, *p) for p in door_sides(edge))]
                            if bool(a) != bool(b)]
                self.assertEqual(sum(r.is_core for r in external), 3)
                self.assertEqual([venue.name for venue in site.businesses], ["Bakery"] if doors else [])
                self.assertEqual(building.unplaced_businesses, ())
                self.assertEqual({r.kind for r in building.storeys[0].rooms if r.business},
                                 {"bakery", "bakerykitchen"} if doors else set())
                for z, floor in enumerate(building.storeys):
                    actual = [(r.kind, {(x, y) for y, row in enumerate(floor.grid)
                                        for x, room in enumerate(row) if room == i})
                              for i, r in enumerate(floor.rooms, 1) if r.surveyed]
                    self.assertEqual(actual, [surveyed[z]] if z in surveyed else [])
                self.assertFalse({key: count for key, count in audit(building, "apartment").items()
                                  if count and not key.startswith("stat:")})

    def test_ground_businesses_keep_separate_places_and_exclude_upper_floors(self):
        points = [
            (6.0, 2.0, {"shop": "bakery", "name": "First", "level": 0}),
            (6.5, 2.0, {"shop": "bakery", "name": "First", "_knox_area_poi": True}),
            (23.0, 2.0, {"shop": "bakery", "name": "Second", "level": 0}),
            (12.0, 12.0, {"shop": "books", "name": "Upstairs", "level": "1"}),
        ]
        venues = ground_businesses({}, points, [
            (6.0, 0.0, {"entrance": "shop", "name": "First"}),
            (8.0, 0.0, {"entrance": "staircase", "name": "First"}),
        ])
        self.assertEqual([(b.name, b.position, b.entrance) for b in venues],
                         [("First", (6.0, 2.0), (6.0, 0.0)), ("Second", (23.0, 2.0), None)])

    def test_mixed_floor_cannot_take_the_last_home(self):
        site = ApartmentSite((Section(0, 0, 6, 6, [[True] * 6 for _ in range(6)], "N", ()),),
                             (GroundBusiness("bakery", "bakerykitchen", (3, 1)),))
        building = build_site(site, 6, 6, 1, Settings(apartment_layout="auto"),
                              None, {}, 3, "N")
        self.assertTrue(any(r.unit for r in building.storeys[0].rooms))
        self.assertEqual(building.unplaced_businesses, ("bakery",))

    def test_nearby_distinct_shops_keep_their_own_mapped_entrances(self):
        venues = ground_businesses({}, [
            (6.0, 1.0, {"shop": "bakery", "name": "First", "ref": "1"}),
            (7.0, 1.0, {"shop": "bakery", "name": "Second", "ref": "1"}),
        ], [
            (6.5, 0, {"entrance": "shop", "name": "First"}),
            (9.5, 0, {"entrance": "shop", "name": "Second"}),
        ])
        self.assertEqual([(b.name, b.entrance) for b in venues],
                         [("First", (6.5, 0)), ("Second", (9.5, 0))])

    def test_anonymous_shop_entrance_matches_at_most_one_venue(self):
        venues = ground_businesses({}, [
            (6.0, 2.0, {"shop": "bakery", "level": 0}),
            (7.0, 2.0, {"shop": "bakery", "level": 0}),
        ], [(6.0, 0.0, {"entrance": "shop"})])
        self.assertEqual(len(venues), 2)
        self.assertEqual([b.entrance for b in venues], [(6.0, 0.0), None])

    def test_auto_needs_ground_commercial_evidence(self):
        recent = {"start_date": "2020", "building": "apartments"}
        points = [(4, 2, {"shop": "bakery"}),
                  (6, 2, {"shop": "books", "name": "Upstairs", "level": "1"}),
                  (6, 3, {"shop": "books", "name": "Upstairs", "_knox_area_poi": True})]
        self.assertEqual(ground_businesses(recent, points), ())
        self.assertEqual([b.front for b in ground_businesses(recent, points, commercial_area=True)],
                         ["bakery"])
        self.assertEqual([b.entrance for b in ground_businesses(recent, [], [(4, 0, {"entrance": "shop"})])],
                         [(4, 0)])
        self.assertEqual([b.front for b in ground_businesses(recent, [], mode="mixed")], ["generalstore"])
