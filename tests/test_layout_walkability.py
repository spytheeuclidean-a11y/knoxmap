import unittest

from knoxbuild import layout


class FurnishedRoomWalkability(unittest.TestCase):
    def test_furniture_is_moved_off_the_window_approach(self):
        room = layout.Room(0, 0, 4, 4, kind="livingroom")
        plan = layout.Plan(
            5, 5, rooms=[room], grid=[[1] * 5 for _ in range(5)],
            doors=[(2, 0, "N")], windows=[(0, 2, "W")],
            furniture=[("bookshelf", 0, 2, "N")])
        building = layout.Building(5, 5, storeys=[plan])

        removed = layout._clear_the_way(building)

        self.assertEqual(removed, 0)
        shelves = [f for f in plan.furniture if f[0] == "bookshelf"]
        self.assertEqual(len(shelves), 1)
        self.assertNotEqual(shelves[0][1:3], (0, 2))

    def test_window_square_is_cleared_when_nothing_can_move(self):
        # Boxed in by fridges: a dresser may stand at a window now (it is
        # low), so one beside the bookshelf would simply trade places with it.
        room = layout.Room(0, 0, 2, 2, kind="livingroom")
        furniture = [("bookshelf", 0, 1, "W")]
        furniture += [("fridge", x, y, "N")
                      for x, y in ((0, 0), (2, 0), (2, 1), (0, 2), (1, 2), (2, 2))]
        plan = layout.Plan(
            3, 3, rooms=[room], grid=[[1] * 3 for _ in range(3)],
            doors=[(1, 0, "N")], windows=[(0, 1, "W")], furniture=furniture)
        building = layout.Building(3, 3, storeys=[plan])

        removed = layout._clear_the_way(building)

        self.assertEqual(removed, 1)
        self.assertFalse([f for f in plan.furniture if f[0] == "bookshelf"])

    def test_a_wall_cabinet_keeps_its_counter(self):
        # Nowhere free to stand the dresser: the bare counter could trade
        # places with it, but would leave the cabinet over a dresser.
        room = layout.Room(0, 0, 2, 2, kind="kitchen")
        furniture = [("dresser", 0, 1, "W"), ("counter", 2, 1, "E"),
                     ("wall_cabinet", 2, 1, "E")]
        furniture += [("dresser", x, y, "N")
                      for x, y in ((0, 0), (2, 0), (0, 2), (1, 2), (2, 2))]
        plan = layout.Plan(
            3, 3, rooms=[room], grid=[[1] * 3 for _ in range(3)],
            doors=[(1, 0, "N")], windows=[(0, 1, "W")], furniture=furniture)

        layout._make_way_for_windows(plan, None)

        self.assertIn(("counter", 2, 1, "E"), plan.furniture)

    def test_furniture_partition_is_opened_for_room_walkability(self):
        room = layout.Room(0, 0, 4, 4, kind="livingroom")
        furniture = [("bookshelf", 2, y, "N") for y in range(5)]
        plan = layout.Plan(
            5, 5, rooms=[room], grid=[[1] * 5 for _ in range(5)],
            doors=[(0, 2, "W")], furniture=furniture)
        building = layout.Building(5, 5, storeys=[plan])

        removed = layout._clear_the_way(building)

        self.assertGreater(removed, 0)
        self.assertLess(len(plan.furniture), len(furniture))


class NothingIsWalledOffByTheLift(unittest.TestCase):
    """A lift shaft is sealed, so what it stands across is a wall.

    A tall building with a narrow arm - an L or a T whose neck is a couple of
    tiles wide - had the shaft land in the neck, and every room up the arm
    then had nothing beside it but the shaft: no door anywhere, loot nobody
    could reach. The arm is taken out of that storey instead, which is what
    it is from the outside: roof.
    """

    def a_building_with_a_narrow_arm(self):
        # The shape the layout audit found it on: 16 x 39, a 16-wide body
        # with a 6-wide arm up the middle - four rooms wide once the arm has
        # its walls, and the shaft is two of them.
        mask = [[(y >= 14 or 5 <= x <= 10) for x in range(16)]
                for y in range(39)]
        return layout.build_building(16, 39, levels=12, seed=2464, kind="fire",
                                     mask=mask, commercial=True)

    def test_every_room_has_a_way_in(self):
        building = self.a_building_with_a_narrow_arm()
        for level, storey in enumerate(building.storeys):
            rooms = range(1, len(storey.rooms) + 1)
            shafts = {i for i in rooms if storey.rooms[i - 1].is_shaft}
            beside = {}
            for a, b in layout._boundary_edges(storey):
                if a in shafts or b in shafts:
                    continue
                beside.setdefault(a, set()).add(b)
                beside.setdefault(b, set()).add(a)
            for i in rooms:
                if i in shafts:
                    continue
                with self.subTest(level=level, room=storey.rooms[i - 1].kind):
                    self.assertTrue(beside.get(i),
                                    "nothing beside it but the lift shaft")


if __name__ == "__main__":
    unittest.main()