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

    def test_shuttered_house_windows_keep_clear_of_wall_decor_and_strip_overlaps(self):
        room = layout.Room(0, 0, 5, 3, kind="livingroom")
        plan = layout.Plan(
            6, 4, rooms=[room], grid=[[1] * 6 for _ in range(4)],
            doors=[(0, 2, "W")],
            furniture=[("painting", 2, 0, "N"), ("switch", 1, 3, "N")],
        )
        building = layout.Building(6, 4, storeys=[plan])

        layout._place_windows(building, "house")
        # Shuttered house windows must not land on or immediately adjacent to
        # the painting at (2, 0, "N") -> (1, 0, "N"), (2, 0, "N"), (3, 0, "N").
        for wx, wy, wd in plan.windows:
            if wd == "N" and wy == 0:
                self.assertGreater(abs(wx - 2), 1)

        # If wall decor ever overlaps a placed window edge, _clear_the_way removes it
        # while preserving light switches.
        plan.windows.append((2, 0, "N"))
        plan.windows.append((1, 3, "N"))
        layout._clear_the_way(building)
        roles = [f[0] for f in plan.furniture]
        self.assertNotIn("painting", roles)
        self.assertIn("switch", roles)

    def test_wall_hugging_stairs_and_open_side_railing(self):
        core = (2, 1, 4, 6)
        self.assertEqual(layout._stairs_in_core(core, hug_wall=True), (2, 2, "N"))
        self.assertEqual(layout._stairs_in_core(core, hug_wall=False), (3, 2, "N"))

        # 2-storey house room with stairs at x=1 hugging West exterior wall (x=1, "W")
        r0 = layout.Room(0, 0, 3, 5, kind="hall")
        r1 = layout.Room(0, 0, 3, 5, kind="hall")
        g0 = [[1] * 4 for _ in range(6)]
        g1 = [[1] * 4 for _ in range(6)]
        # Make x=0 a separate room so (1, y, "W") is a wall and (2, y, "W") is open
        for y in range(6):
            g0[y][0] = 2
            g1[y][0] = 2
        p0 = layout.Plan(4, 6, rooms=[r0, layout.Room(0, 0, 0, 5, kind="livingroom")], grid=g0)
        p1 = layout.Plan(4, 6, rooms=[r1, layout.Room(0, 0, 0, 5, kind="bedroom")], grid=g1)
        b = layout.Building(4, 6, storeys=[p0, p1], stairs=[(1, 1, "N")])
        layout._add_stair_railings(b)
        # Open East side of the flight gets railings; West wall side does not
        for y in range(1, 1 + layout.STAIR_RUN - 1):
            self.assertIn((2, y, "W"), p0.railing)
            self.assertNotIn((1, y, "W"), p0.railing)
        for y in range(2, 1 + layout.STAIR_RUN):
            self.assertIn((2, y, "W"), p1.railing)

    def test_stairs_reject_roof_landing_and_one_tile_hallway(self):
        from knoxbuild import audit

        # 1) Top landing (1, 0) is outside upper storey -> roof / nowhere
        g0 = [[1] * 4 for _ in range(7)]
        g1 = [[1] * 4 for _ in range(7)]
        g1[0] = [0] * 4
        p0 = layout.Plan(4, 7, rooms=[layout.Room(0, 0, 3, 6, kind="hall")], grid=g0)
        p1 = layout.Plan(4, 7, rooms=[layout.Room(0, 1, 3, 6, kind="hall")], grid=g1)
        b_roof = layout.Building(4, 7, storeys=[p0, p1], stairs=[(1, 1, "N")])
        self.assertFalse(layout._valid_stairs_on_building(b_roof, (1, 1, "N")))
        self.assertGreater(audit.audit(b_roof, "house").get("stairs onto roof", 0), 0)

        # 2) 1-tile-wide hallway on a non-tower house -> rejected
        g_narrow0 = [[2, 1, 2, 2] for _ in range(7)]
        g_narrow1 = [[2, 1, 2, 2] for _ in range(7)]
        b_narrow = layout.Building(
            4, 7,
            storeys=[
                layout.Plan(4, 7, rooms=[layout.Room(1, 0, 1, 6, kind="hall"),
                                         layout.Room(0, 0, 3, 6, kind="livingroom")], grid=g_narrow0),
                layout.Plan(4, 7, rooms=[layout.Room(1, 0, 1, 6, kind="hall"),
                                         layout.Room(0, 0, 3, 6, kind="bedroom")], grid=g_narrow1),
            ],
            stairs=[(1, 1, "N")],
        )
        self.assertFalse(layout._valid_stairs_on_building(b_narrow, (1, 1, "N")))
        self.assertGreater(audit.audit(b_narrow, "house").get("stairs in 1-tile hallway", 0), 0)
        # Skyscraper stair cores are explicitly allowed to be 1 tile wide.
        self.assertTrue(layout._valid_stairs_on_building(
            b_narrow, (1, 1, "N"), allow_narrow_core=True))

        # 3) Valid 3-wide wall-hugging stairs pass both checks
        g_ok0 = [[1] * 4 for _ in range(7)]
        g_ok1 = [[1] * 4 for _ in range(7)]
        b_ok = layout.Building(
            4, 7,
            storeys=[
                layout.Plan(4, 7, rooms=[layout.Room(0, 0, 3, 6, kind="hall")], grid=g_ok0),
                layout.Plan(4, 7, rooms=[layout.Room(0, 0, 3, 6, kind="hall")], grid=g_ok1),
            ],
            stairs=[(0, 1, "N")],
        )
        self.assertTrue(layout._valid_stairs_on_building(b_ok, (0, 1, "N")))
        self.assertEqual(audit.audit(b_ok, "house").get("stairs onto roof", 0), 0)
        self.assertEqual(audit.audit(b_ok, "house").get("stairs in 1-tile hallway", 0), 0)

    def test_exterior_door_avoids_one_tile_deep_wall(self):
        from knoxbuild.layout.openings import _exterior_door, _has_door_depth

        # South facade has a 1-tile-deep strip of room 1 (y=3, x=1..4) with room 2
        # right behind it (y=0..2), while the West/East sides of room 1 (x=0, y=0..3)
        # have >= 2 tiles of depth. _exterior_door must not put the door on the
        # 1-tile-deep South wall facing room 2's wall.
        g = [
            [1, 1, 2, 2, 2, 1],
            [1, 1, 2, 2, 2, 1],
            [1, 1, 2, 2, 2, 1],
            [1, 1, 1, 1, 1, 1],
        ]
        plan = layout.Plan(
            6, 4,
            rooms=[layout.Room(0, 0, 5, 3, kind="hall"),
                   layout.Room(2, 0, 4, 2, kind="storage")],
            grid=g,
            kind="school",
        )
        _exterior_door(plan, layout.random.Random(1), street="S")
        self.assertTrue(plan.doors)
        door = plan.doors[0]
        # Must not land on the 1-tile-deep South strip at x in 2..4, y=4
        self.assertFalse(door[2] == "N" and door[1] == 4 and 2 <= door[0] <= 4)
        self.assertTrue(
            any(_has_door_depth(plan, side, door) for side in ("N", "S", "W", "E"))
        )


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