"""Living rooms, classrooms, clinics, shops and big houses laid out like real ones."""
import unittest

from knoxbuild import layout
from knoxbuild.uses import use_of


def pieces_in(plan, idx, prefix):
    return [(role, x, y, o) for role, x, y, o in plan.furniture
            if role.startswith(prefix) and plan.grid[y][x] == idx]


class LivingRooms(unittest.TestCase):
    def test_the_sofa_faces_the_television(self):
        faces = total = 0
        for seed in range(25):
            plan = layout.build_building(18, 14, kind="house", street="S", seed=seed).storeys[0]
            for idx, room in enumerate(plan.rooms, 1):
                if room.kind != "livingroom":
                    continue
                sofa, tv = pieces_in(plan, idx, "sofa"), pieces_in(plan, idx, "tv")
                if not (sofa and tv):
                    continue
                total += 1
                _r, sx, sy, so = sofa[0]
                _r, tx, ty, _o = tv[0]
                fx, fy = {"N": (0, 1), "S": (0, -1), "W": (1, 0), "E": (-1, 0)}[so]
                dx, dy = tx - sx, ty - sy
                faces += dx * fx + dy * fy > 0 and abs(dx * fy - dy * fx) <= 2
        self.assertGreater(total, 20)
        self.assertGreater(faces / total, 0.8)


class Schools(unittest.TestCase):
    def test_desks_stand_in_rows_not_round_the_walls(self):
        seen = 0
        for seed in range(10):
            plan = layout.build_building(40, 30, kind="school", street="S", seed=seed).storeys[0]
            for idx, room in enumerate(plan.rooms, 1):
                if room.kind != "classroom" or min(room.x1 - room.x0, room.y1 - room.y0) < 7:
                    continue
                tables = pieces_in(plan, idx, "dining_table")
                if not tables:
                    continue
                seen += 1
                inside = [t for t in tables
                          if room.x0 < t[1] < room.x1 and room.y0 < t[2] < room.y1]
                self.assertGreaterEqual(len(inside), len(tables) // 2)
        self.assertGreater(seen, 3)


class Clinics(unittest.TestCase):
    def test_the_couch_is_off_the_wall_in_a_roomy_exam_room(self):
        roomy = off = 0
        for seed in range(30):
            plan = layout.build_building(36, 28, kind="medical", street="S", seed=seed).storeys[0]
            for idx, room in enumerate(plan.rooms, 1):
                if room.kind != "clinic" or room.area < 24 or min(
                        room.x1 - room.x0, room.y1 - room.y0) + 1 < 5:
                    continue
                beds = pieces_in(plan, idx, "bed")
                if not beds:
                    continue
                roomy += 1
                off += any(room.x0 < cx < room.x1 and room.y0 < cy < room.y1
                           for role, x, y, o in beds
                           for cx, cy in layout._cells_for(role, x, y, o))
        self.assertGreater(roomy, 3)
        self.assertGreater(off / roomy, 0.6)


class Shops(unittest.TestCase):
    def test_a_wide_supermarket_has_two_tills(self):
        plan = layout.build_building(30, 18, kind="shop",
                                     uses=[use_of({"shop": "supermarket"})],
                                     street="S", seed=3).storeys[0]
        self.assertGreaterEqual(sum(role == "register" for role, *_ in plan.furniture), 2)

    def test_a_bookshop_has_somewhere_to_sit(self):
        seats = 0
        for seed in range(6):
            plan = layout.build_building(26, 18, kind="shop", uses=[use_of({"shop": "books"})],
                                         street="S", seed=seed).storeys[0]
            seats += sum(role == "round_table" for role, *_ in plan.furniture)
        self.assertGreater(seats, 0)


class BigHouses(unittest.TestCase):
    def test_most_big_floors_are_cut_by_the_programme(self):
        used = []
        orig = layout._house_by_kind

        def spy(plan, level, levels, rng):
            got = orig(plan, level, levels, rng)
            if plan.width >= 20 and plan.height >= 20:
                used.append(got is not None)
            return got
        layout._house_by_kind = spy
        try:
            for seed in range(12):
                layout.build_building(24, 22, kind="house", street="S", seed=seed, levels=1)
        finally:
            layout._house_by_kind = orig
        self.assertGreater(sum(used) / len(used), 0.4)


if __name__ == "__main__":
    unittest.main()
