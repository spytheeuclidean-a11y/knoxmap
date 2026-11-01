"""Three things seen in game in a thin office and a house (Piqua, 2026-10-31).

- A whiteboard is three tiles of wall; windows kept off its first tile only and
  went through the other two.
- An office desk against a wall had its chair two tiles off, or across the room.
- A kitchen's one-tile tail took counters and a sink, a bathroom's one-square
  nub the toilet: nowhere to stand to use them.
"""
import random
import unittest

from knoxbuild import layout as L

SHAPES = [(8, 26), (3, 20), (6, 16), (5, 12), (10, 14), (4, 9), (12, 30), (7, 7)]


def buildings(count=60):
    rng = random.Random(7)
    for i in range(count):
        w, h = rng.choice(SHAPES)
        if rng.random() < 0.5:
            w, h = h, w
        kind = rng.choice([None, "civic", "civic", "police", "school", "medical"])
        yield L.build_building(w, h, levels=rng.choice((1, 2, 3)), seed=i, kind=kind,
                               commercial=kind is not None)


class OfficeSeating(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.built = list(buildings())

    def test_no_window_through_a_wall_piece(self):
        for b in self.built:
            for storey in b.storeys:
                windows = set(storey.windows)
                for role, x, y, o in storey.furniture:
                    if not L._is_wall_piece(role):
                        continue
                    for cx, cy in L._cells_for(role, x, y, o):
                        self.assertNotIn(L._wall_edge(cx, cy, o), windows, (role, x, y, o))

    def test_a_chair_at_every_desk_that_has_one_in_its_room(self):
        seated = total = 0
        for b in self.built:
            for storey in b.storeys:
                furn, grid = storey.furniture, storey.grid
                chairs = {(x, y) for role, x, y, _o in furn if role == "office_chair"}
                for role, x, y, o in furn:
                    if role not in L.DESK_ROLES:
                        continue
                    here = grid[y][x]
                    if not any(grid[cy][cx] == here for cx, cy in chairs):
                        continue        # no chair in its room to give it
                    sx, sy = L._STEP[L._OPPOSITE[o]]
                    front = {(cx + sx, cy + sy) for cx, cy in L._tiles_under(role, x, y, o)}
                    total += 1
                    seated += bool(front & chairs)
        # A desk can have no free tile in front of it; nearly all have one.
        self.assertGreater(total, 20)
        self.assertGreaterEqual(seated / total, 0.9, (seated, total))

    def test_nothing_stands_on_a_one_tile_wide_spot(self):
        for b in self.built:
            for storey in b.storeys:
                g, w, h = storey.grid, storey.width, storey.height
                for role, x, y, o in storey.furniture:
                    if not L._blocks(role) or role.startswith("elevator"):
                        continue
                    for cx, cy in L._tiles_under(role, x, y, o):
                        if 0 <= cx < w and 0 <= cy < h and g[cy][cx]:
                            self.assertFalse(L._narrow(g, cx, cy), (role, cx, cy))


if __name__ == "__main__":
    unittest.main()
