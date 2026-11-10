import random
import unittest
from collections import deque

from knoxbuild import buildtiles, layout, tbx
from knoxbuild.layout.furnishing import _blocks, _cells_for, _door_tiles, _furnish


class PublicStalls(unittest.TestCase):
    def test_school_bathrooms_have_reachable_stalls(self):
        for seed in range(12):
            plan = layout.build_building(40, 32, kind="school", commercial=True,
                                         seed=seed).storeys[0]
            self.assertTrue(plan.stalls, seed)
            for x, y, facing in plan.stalls:
                room = plan.grid[y][x]
                self.assertIn(("toilet", x, y, facing), plan.furniture)
                dx, dy = (0, 1) if facing == "N" else (1, 0)
                front = (x + dx, y + dy)
                blocked = {cell for role, fx, fy, orient in plan.furniture if _blocks(role)
                           for cell in _cells_for(role, fx, fy, orient)}
                self.assertNotIn(front, blocked)
                entrances = {cell for cell in _door_tiles(plan)
                             if 0 <= cell[0] < plan.width and 0 <= cell[1] < plan.height
                             and plan.grid[cell[1]][cell[0]] == room and cell not in blocked}
                reached = set(entrances)
                queue = deque(entrances)
                while queue:
                    px, py = queue.popleft()
                    for nx, ny in ((px-1, py), (px+1, py), (px, py-1), (px, py+1)):
                        if (0 <= nx < plan.width and 0 <= ny < plan.height
                                and plan.grid[ny][nx] == room and (nx, ny) not in blocked
                                and (nx, ny) not in reached):
                            reached.add((nx, ny))
                            queue.append((nx, ny))
                self.assertIn(front, reached, (seed, x, y, facing))

    def test_stall_walls_and_doors_compile_without_replacing_room_boundaries(self):
        for seed in range(6):
            building = layout.build_building(40, 32, kind="school", commercial=True,
                                             seed=seed)
            plan = building.storeys[0]
            parsed = buildtiles.parse_tbx(tbx.render_tbx(building, "school"))
            tiles = buildtiles.level_tiles(parsed, 0)
            for x, y, facing in plan.stalls:
                dx, dy = (0, 1) if facing == "N" else (1, 0)
                door = tiles[(x + dx, y + dy)]
                self.assertIn("fixtures_bathroom_01_49" if facing == "N"
                              else "fixtures_bathroom_01_48", door)
                self.assertIn("fixtures_bathroom_01_42" if facing == "N"
                              else "fixtures_bathroom_01_43", door)
            for obj in parsed.floors[0].objects:
                if obj.get("type") != "wall":
                    continue
                x, y = int(obj["x"]), int(obj["y"])
                ox, oy = (x - 1, y) if obj["dir"] == "N" else (x, y - 1)
                self.assertTrue(0 <= ox < plan.width and 0 <= oy < plan.height)
                self.assertEqual(plan.grid[y][x], plan.grid[oy][ox])

    def test_homes_keep_regular_bathrooms(self):
        room = layout.Room(0, 0, 7, 5, kind="bathroom")
        plan = layout.Plan(8, 6, rooms=[room], grid=[[1] * 8 for _ in range(6)],
                           kind="house", doors=[(4, 6, "N")])
        _furnish(plan, random.Random(1))
        self.assertFalse(plan.stalls)

    def test_large_public_bathroom_has_multiple_toilets_in_stalls(self):
        room = layout.Room(0, 0, 7, 5, kind="bathroom")
        plan = layout.Plan(8, 6, rooms=[room], grid=[[1] * 8 for _ in range(6)],
                           kind="school", doors=[(4, 6, "N")])
        _furnish(plan, random.Random(1))
        self.assertGreaterEqual(len(plan.stalls), 2)
        self.assertEqual({(x, y) for role, x, y, orient in plan.furniture if role == "toilet"},
                         {(x, y) for x, y, facing in plan.stalls})
        self.assertTrue(any(role == "sink_public" for role, *_ in plan.furniture))


if __name__ == "__main__":
    unittest.main()
