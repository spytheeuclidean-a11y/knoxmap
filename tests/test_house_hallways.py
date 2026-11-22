import unittest

from knoxbuild import layout
from knoxbuild.layout import furnishing as F

SIZES = ((16, 12, 1), (20, 14, 2), (24, 16, 2))


def halls():
    for seed in range(40):
        for w, h, levels in SIZES:
            plan = layout.build_building(width=w, height=h, seed=seed, levels=levels, street="S")
            for st in plan.storeys:
                for idx, r in enumerate(st.rooms, 1):
                    if r.kind == "hall" and r.is_core:
                        yield st, idx


class HouseHallways(unittest.TestCase):
    def test_halls_are_furnished_and_still_walkable(self):
        total = furnished = 0
        for st, idx in halls():
            cells = {(x, y) for y, row in enumerate(st.grid) for x, v in enumerate(row) if v == idx}
            pieces = [f for f in st.furniture if f[0] in F.HALL_PIECES and (f[1], f[2]) in cells]
            blocked = {c for f in st.furniture if F._blocks(f[0]) and (f[1], f[2]) in cells
                       for c in F._cells_for(*f)}
            total += 1
            furnished += bool(pieces)
            # Whatever floor is left in the hall is one piece: a way through.
            free = cells - blocked
            if free:
                seen, todo = {next(iter(free))}, [next(iter(free))]
                while todo:
                    x, y = todo.pop()
                    for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if n in free and n not in seen:
                            seen.add(n)
                            todo.append(n)
                self.assertEqual(seen, free)
        self.assertGreater(total, 100)
        self.assertGreater(furnished / total, 0.6)


if __name__ == "__main__":
    unittest.main()
