"""Windows upstairs stand above the windows downstairs.

A block of flats repeats its floor plan, so its windows always lined up. A
house does not: every storey is laid out room by room, the rooms upstairs are
not the rooms downstairs, and the windows went wherever each floor's rooms
wanted them. Looking up at a generated house from the street, 27 of every 100
upstairs windows stood above a window - which is what gives a town away,
because a real facade is built in columns.

Reported in #bug-reports by Zombaxx: "window alignment with the windows above
not properly lining up".
"""
import unittest

from knoxbuild.layout import Building, Plan, Room, _facade_runs, _place_windows, build_building

# Measured over the buildings below. Houses were at 0.27 before the floor
# below's columns were taken first; the rest were already repeating their
# plan and must not get worse.
WANTED = {"house": 0.60, "apartment": 0.85, "civic": 0.85, "shop": 0.85}


def lined_up(kind, levels=3, size=(24, 18), seeds=range(8)):
    """How much of each upper floor's glazing stands above the floor below."""
    above = same = 0
    for seed in seeds:
        built = build_building(size[0], size[1], levels=levels, seed=seed,
                               kind=None if kind == "house" else kind,
                               commercial=kind not in ("house", "apartment"))
        for level in range(1, len(built.storeys)):
            under = set(built.storeys[level - 1].windows)
            here = set(built.storeys[level].windows)
            above += len(here)
            same += len(here & under)
    return same / max(1, above), above


class WindowsInColumns(unittest.TestCase):
    def test_most_of_an_upper_floor_sits_above_the_one_below(self):
        for kind, wanted in WANTED.items():
            with self.subTest(kind=kind):
                share, counted = lined_up(kind)
                self.assertGreater(counted, 20, "nothing to measure")
                self.assertGreaterEqual(
                    share, wanted,
                    f"{kind}: only {share:.0%} of upstairs windows are above one")

    def test_a_tall_house_keeps_its_columns_all_the_way_up(self):
        share, _counted = lined_up("house", levels=5)
        self.assertGreaterEqual(share, 0.60)

    def test_the_windows_are_still_there_to_line_up(self):
        # Lining them up must not be done by having fewer of them: a house of
        # this size has windows on every storey.
        built = build_building(24, 18, levels=3, seed=3)
        for level, storey in enumerate(built.storeys):
            with self.subTest(level=level):
                self.assertGreater(len(storey.windows), 4)

    def test_apartment_windows_share_the_facade_despite_a_moved_partition(self):
        floors = []
        for split in (6, 4, 7):
            floors.append(Plan(12, 8, private_flats=True,
                               rooms=[Room(0, 0, split - 1, 7, kind="bedroom", unit=1),
                                      Room(split, 0, 11, 7, kind="openplan", unit=1)],
                               grid=[[1] * split + [2] * (12 - split) for _ in range(8)]))
        floors[1].wall_pieces.add((2, 0, "N"))
        _place_windows(Building(12, 8, floors), "apartment")

        columns = set(floors[1].windows)
        self.assertGreater(len(columns), 5)
        self.assertEqual(columns, set(floors[2].windows))
        for floor in floors[1:]:
            facade = {e[:3]: floor.grid[e[4]][e[3]]
                      for _, run in _facade_runs(floor.grid) for e in run}
            self.assertEqual({facade[edge] for edge in columns}, {1, 2})

    def test_apartment_setback_gets_its_own_columns(self):
        def floor(inset):
            grid = [[int(inset <= x < 14 - inset and inset <= y < 10 - inset)
                     for x in range(14)] for y in range(10)]
            return Plan(14, 10, private_flats=True, grid=grid,
                        rooms=[Room(inset, inset, 13 - inset, 9 - inset, kind="openplan", unit=1)])

        floors = [floor(inset) for inset in (0, 0, 2, 2)]
        _place_windows(Building(14, 10, floors), "apartment")
        self.assertTrue(floors[2].windows)
        self.assertEqual(floors[2].windows, floors[3].windows)
        self.assertTrue(set(floors[1].windows).isdisjoint(floors[2].windows))


if __name__ == "__main__":
    unittest.main()
