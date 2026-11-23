"""Real interiors from OSM indoor=room data (renderer + knoxbuild.layout).

Run from the KnoxMap folder:  python -m unittest discover tests
No network, no files.

Two halves: renderer._buildings_geojson attaches each mapped room to the
building it stands in, and layout.build_plan cuts the ground floor along
those rooms instead of guessing. A building surveyed room by room - a
school's classrooms, an office's rooms round its core - keeps that plan.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import renderer  # noqa: E402
from generator.osm import OSMFeature  # noqa: E402
from knoxbuild.entrances import ground_entrance  # noqa: E402
from knoxbuild.layout import build_building, build_plan  # noqa: E402

# A school: a building wide enough to hold the rooms drawn inside it.
SCHOOL = OSMFeature(1, "way", {"building": "school", "name": "Test School"},
                    [(40.000, 20.000), (40.000, 20.0010),
                     (40.0016, 20.0010), (40.0016, 20.000),
                     (40.000, 20.000)])
CLASSROOM = OSMFeature(2, "way", {"indoor": "room", "room": "classroom"},
                       [(40.0002, 20.0002), (40.0002, 20.0008),
                        (40.0008, 20.0008), (40.0008, 20.0002),
                        (40.0002, 20.0002)])
# A room drawn off in the field, not in any building.
STRAY = OSMFeature(3, "way", {"indoor": "room"},
                   [(40.010, 20.010), (40.010, 20.011),
                    (40.011, 20.011), (40.011, 20.010),
                    (40.010, 20.010)])


def rooms_property(indoor=(CLASSROOM, STRAY)):
    g = renderer._buildings_geojson([SCHOOL], list(indoor))
    return g["features"][0]["properties"].get("rooms")


class Attach(unittest.TestCase):
    def test_a_room_lands_on_its_building_with_its_tags(self):
        rooms = rooms_property()
        self.assertEqual(len(rooms), 1)
        self.assertEqual(rooms[0]["room"], "classroom")
        self.assertEqual(len(rooms[0]["ring"]), 5)

    def test_a_room_in_no_building_is_dropped(self):
        # Only the classroom is inside the school; the stray is not attached
        # to anything and never reaches the build.
        self.assertEqual(len(rooms_property()), 1)

    def test_buildings_without_rooms_have_no_property(self):
        g = renderer._buildings_geojson([SCHOOL], [])
        self.assertNotIn("rooms", g["features"][0]["properties"])

    def test_apartment_lobby_import_retains_the_floor_and_building_facts(self):
        apartment = OSMFeature(4, "way", {"building": "apartments", "start_date": "2018",
                                         "building:flats": "36"}, SCHOOL.geometry)
        ground = OSMFeature(5, "way", {"indoor": "room", "room": "lobby", "level": "0"},
                            CLASSROOM.geometry)
        upper = OSMFeature(6, "way", {"indoor": "room", "room": "lobby", "level": "1"},
                           CLASSROOM.geometry)
        props = renderer._buildings_geojson([apartment], [ground, upper])["features"][0]["properties"]
        self.assertEqual(props["start_date"], "2018")
        self.assertEqual(props["building:flats"], "36")
        self.assertEqual([r["level"] for r in props["rooms"] if ground_entrance(r)], ["0"])


# Two rooms as the mapper drew them, in storey tiles: a 8x6 classroom and a
# 6x5 bathroom, both small enough that no kind cap cuts them back.
CLASSROOM_RING = [(2, 2), (9, 2), (9, 7), (2, 7), (2, 2)]
BATHROOM_RING = [(13, 3), (18, 3), (18, 7), (13, 7), (13, 3)]
MAPPED = [(CLASSROOM_RING, "classroom"), (BATHROOM_RING, "bathroom")]


def room_covering(plan, x, y):
    """The room holding (x, y); slivers beside a mapped room may be folded
    into it (layout._mend_fragments), so the drawn room can cover more than
    was drawn - never less."""
    for r in plan.rooms:
        if r.x0 <= x <= r.x1 and r.y0 <= y <= r.y1:
            return r
    return None


class Cut(unittest.TestCase):
    def test_the_mapped_rooms_are_cut_as_drawn_with_their_kind(self):
        plan = build_plan(40, 24, kind="civic", seed=5, mapped=MAPPED)
        cls = room_covering(plan, 5, 4)       # the middle of the classroom
        self.assertIsNotNone(cls)
        self.assertTrue(cls.x0 <= 2 and cls.y0 <= 2
                        and cls.x1 >= 9 and cls.y1 >= 7, vars(cls))
        self.assertEqual(cls.kind, "classroom")
        self.assertTrue(cls.fixed)
        # The bathroom has no sliver against it and lands exactly as drawn.
        cls2 = room_covering(plan, 15, 5)
        self.assertEqual((cls2.x0, cls2.y0, cls2.x1, cls2.y1),
                         (13, 3, 18, 7))
        self.assertEqual(cls2.kind, "bathroom")

    def test_the_rest_of_the_floor_is_still_cut_and_tiled(self):
        plan = build_plan(40, 24, kind="civic", seed=5, mapped=MAPPED)
        self.assertGreater(len(plan.rooms), len(MAPPED))
        self.assertTrue(all(all(row) for row in plan.grid),
                        "every tile of the floor belongs to some room")

    def test_untagged_rooms_are_still_placed(self):
        # A room the game has no name for keeps its walls; the usual rules
        # furnish it afterwards.
        bare = [([xy for xy in CLASSROOM_RING], None)]
        plan = build_plan(40, 24, kind="civic", seed=5, mapped=bare)
        r = room_covering(plan, 5, 4)
        self.assertIsNotNone(r)
        self.assertFalse(r.fixed)
        self.assertTrue(r.x0 <= 2 and r.y0 <= 2 and r.x1 >= 9 and r.y1 >= 7,
                        vars(r))

    def test_upper_floors_are_laid_out_as_ever(self):
        # The mapper drew one floor; an upper storey is the ordinary plan.
        with_mapped = build_plan(40, 24, kind="civic", seed=5,
                                 ground=False, mapped=MAPPED)
        without = build_plan(40, 24, kind="civic", seed=5, ground=False)
        self.assertEqual([(r.x0, r.y0, r.x1, r.y1, r.kind)
                          for r in with_mapped.rooms],
                         [(r.x0, r.y0, r.x1, r.y1, r.kind)
                          for r in without.rooms])

    def test_a_school_keeps_mapped_rooms_on_their_upper_floor(self):
        school = build_building(40, 24, 3, kind="school", seed=5, mapped={1: MAPPED})
        self.assertEqual(len(school.stairs), 2)
        for level, plan in enumerate(school.storeys):
            with self.subTest(level=level):
                fixed = [r.kind for r in plan.rooms if r.fixed]
                self.assertCountEqual(fixed, ["classroom", "bathroom"] if level == 1 else [])
        upper = school.storeys[1]
        for x, y, kind in ((5, 4, "classroom"), (15, 5, "bathroom")):
            r = upper.rooms[upper.grid[y][x] - 1]
            self.assertEqual(r.kind, kind)
            self.assertTrue(r.fixed)

    def test_a_building_without_mapped_rooms_is_cut_as_ever(self):
        plan = build_plan(40, 24, kind="civic", seed=5)
        self.assertGreater(len(plan.rooms), 1)
        self.assertTrue(all(all(row) for row in plan.grid))


if __name__ == "__main__":
    unittest.main()
