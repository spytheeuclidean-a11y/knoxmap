import unittest
from types import SimpleNamespace

from knoxbuild.buildheader import cell_tables, placed_rooms, room_rects


def squares(pic):
    return {(x, y) for y, row in enumerate(pic) for x, c in enumerate(row) if c == "#"}


def covers(rects):
    return {(x + i, y + j) for x, y, w, h in rects for j in range(h) for i in range(w)}


class RectTests(unittest.TestCase):
    def test_a_rectangle_is_one_rect(self):
        self.assertEqual(room_rects(squares(["###", "###"])), [(0, 0, 3, 2)])

    def test_a_c_shape_cuts_the_way_worlded_does(self):
        pic = ["######", "######", "#.....", "#.....", "#.....", "######"]
        self.assertEqual(room_rects(squares(pic)), [(0, 0, 6, 2), (0, 2, 1, 3), (0, 5, 6, 1)])

    def test_a_row_wider_than_the_column_above_ends_the_column(self):
        pic = [".###", ".###", ".###", "####", "####"]
        self.assertEqual(room_rects(squares(pic)), [(1, 0, 3, 3), (0, 3, 4, 2)])

    def test_the_rects_always_cover_the_squares_exactly_once(self):
        import random
        rnd = random.Random(5)
        for _ in range(200):
            sq = {(x, y) for x in range(8) for y in range(8) if rnd.random() < 0.6}
            rects = room_rects(sq)
            self.assertEqual(covers(rects), sq)
            self.assertEqual(sum(w * h for _, _, w, h in rects), len(sq))


def building(rooms_by_floor, names=("hall", "kitchen")):
    floors = [SimpleNamespace(rooms=g, objects=[]) for g in rooms_by_floor]
    return SimpleNamespace(floors=floors, rooms=[{"Name": n} for n in names])


class TableTests(unittest.TestCase):
    def test_rooms_go_floor_by_floor_then_by_number(self):
        b = building([[[1, 1, 2]], [[2, 2, 2]]])
        (tx, ty, entries), = placed_rooms([(b, 10, 20, 0)])
        self.assertEqual([(e["name"], e["z"], e["rects"]) for e in entries],
                         [("hall", 0, [(10, 20, 2, 1)]), ("kitchen", 0, [(12, 20, 1, 1)]),
                          ("kitchen", 1, [(10, 20, 3, 1)])])

    def test_a_later_building_takes_the_squares_it_covers(self):
        first = building([[[1, 1, 1, 1]]])
        second = building([[[2, 2]]])
        out = placed_rooms([(first, 0, 0, 0), (second, 1, 0, 0)])
        self.assertEqual(len(out), 1)                       # they touch: one building
        by_name = {e["name"]: e["rects"] for e in out[0][2]}
        self.assertEqual(covers(by_name["hall"]), {(0, 0), (3, 0)})   # the first keeps its two ends
        self.assertEqual(covers(by_name["kitchen"]), {(1, 0), (2, 0)})

    def test_buildings_that_do_not_touch_stay_apart(self):
        b = building([[[1]]])
        out = placed_rooms([(b, 0, 0, 0), (b, 5, 0, 0)])
        self.assertEqual(len(out), 2)

    def test_a_building_is_listed_in_the_cell_of_its_north_west_corner_whole(self):
        b = building([[[1, 1, 1, 1]]])
        placed = placed_rooms([(b, 246, 3, 0)])                   # world x 246 is x = 254 of cell 82_0
        rooms, buildings = cell_tables(82, 0, placed)
        self.assertEqual(rooms[0]["rects"], [(254, 3, 4, 1)])          # runs on past the cell's edge
        self.assertEqual(buildings, [[0]])
        self.assertEqual(cell_tables(83, 0, placed), ([], []))

    def test_buildings_come_by_source_cell_row_by_row(self):
        b = building([[[1]]])
        # Cell 82_1 starts at world (-8, 256). The project lists the lot in source cell (0, 1)
        # first (it goes column by column); WorldEd goes across a row first, so the lot in
        # source cell (0, 0) comes first.
        lots = [(b, 10, 310, 0), (b, 150, 280, 0)]
        rooms, buildings = cell_tables(82, 1, placed_rooms(lots))
        self.assertEqual([r["rects"][0][:2] for r in rooms], [(158, 24), (18, 54)])
        self.assertEqual(buildings, [[0], [1]])


if __name__ == "__main__":
    unittest.main()
