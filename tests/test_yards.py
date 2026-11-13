import os
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from generator import pz_colors as C
from knoxbuild import yards as yards_module
from knoxbuild.bitmaps import read_rgb
from knoxbuild.yards import YARD_MIN_DEPTH, _pave_patio, paint_paths, yard_plan


class YardPlacement(unittest.TestCase):
    def test_patio_paving_preserves_tiles_claimed_by_neighbor_paths(self):
        ground = np.full((3, 4, 3), C.MEDIUM_GRASS, dtype=np.uint8)
        vegetation = np.full((3, 4, 3), C.TREES, dtype=np.uint8)
        crossable = np.ones((3, 4), dtype=bool)
        claimed = np.zeros((3, 4), dtype=bool)
        claimed[1, 1] = True

        paved = _pave_patio(ground, vegetation, crossable, claimed,
                            [(1, 1), (2, 1), (-1, 1)])

        self.assertEqual(paved, [(2, 1)])
        self.assertEqual(tuple(ground[1, 1]), C.MEDIUM_GRASS)
        self.assertEqual(tuple(ground[1, 2]), C.PAVING_STONE)
        self.assertEqual(tuple(vegetation[1, 1]), C.TREES)
        self.assertEqual(tuple(vegetation[1, 2]), C.VEG_NOTHING)


SIZE = 6   # every test building is 6 x 6 with its door in the north wall


def _building(folder, name, door=(3, 0, "N")):
    """A one-room ground floor with an outside door, at (3, 0) facing north
    unless `door` says otherwise."""
    rows = "\n".join(",".join(["1"] * SIZE) for _ in range(SIZE))
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        f.write(f'<building><floor><rooms>\n{rows}\n</rooms>'
                f'<object type="door" x="{door[0]}" y="{door[1]}" dir="{door[2]}"/></floor></building>')


def _paint(width, height, buildings, water=(), veg=False, tarmac=()):
    """Lawn with a pavement along the top two rows; return the painted ground,
    or the vegetation layer when `veg`.

    `buildings` is (kind, tile_x, tile_y[, door]) per building, `water` (x, y) tiles."""
    with tempfile.TemporaryDirectory() as out:
        os.mkdir(os.path.join(out, "buildings"))
        ground = np.zeros((height, width, 3), dtype=np.uint8)
        ground[:, :] = C.MEDIUM_GRASS
        ground[:2, :] = C.PALE_CONCRETE
        for x, y in water:
            ground[y, x] = C.WATER
        for x, y in tarmac:
            ground[y, x] = C.DARK_ASPHALT
        Image.fromarray(ground).save(os.path.join(out, "t.bmp"), format="BMP")
        Image.fromarray(np.zeros_like(ground)).save(os.path.join(out, "t_veg.bmp"),
                                                   format="BMP")
        occupied = np.zeros((height, width), dtype=bool)
        rows = []
        for n, (kind, x, y, *door) in enumerate(buildings):
            _building(os.path.join(out, "buildings"), f"b{n}.tbx", *door)
            occupied[y:y + SIZE, x:x + SIZE] = True
            rows.append({"file": f"b{n}.tbx", "kind": kind, "building": "yes",
                         "tile_x": x, "tile_y": y, "width": SIZE, "height": SIZE})
        paint_paths(out, "t", rows, occupied)
        return read_rgb(os.path.join(out, "t_veg.bmp" if veg else "t.bmp"))


def _stone(ground, x, y):
    return tuple(ground[y, x]) == C.PAVING_STONE


class FrontPaths(unittest.TestCase):
    def test_a_block_of_flats_gets_a_path_to_the_pavement(self):
        ground = _paint(30, 30, [("apartment", 10, 10)])
        # Straight out of the door at (13, 9) up to the pavement at row 1.
        for y in range(2, 10):
            self.assertTrue(_stone(ground, 13, y), f"no path at (13, {y})")

    def test_a_house_far_back_from_the_street_walks_to_its_drive(self):
        ground = _paint(30, 80, [("house", 10, 62)])
        drive = np.all(ground == C.DARK_ASPHALT, axis=2)
        self.assertTrue(drive[2:62].any(axis=1).all(),
                        "the drive does not reach the pavement")
        self.assertTrue(_stone(ground, 13, 61), "no path from the door")

    def test_a_house_with_a_drive_from_the_terrain_gets_no_second(self):
        # A drive the woods' clearing laid (generator/rendering/homesteads.py):
        # down the west side from the pavement, then in to the house's wall.
        laid = ([(x, y) for x in range(2, 5) for y in range(2, 66)]
                + [(x, y) for x in range(5, 10) for y in range(63, 66)])
        ground = _paint(30, 80, [("house", 10, 62)], tarmac=laid)
        drive = np.all(ground == C.DARK_ASPHALT, axis=2)
        extra = drive.copy()
        for x, y in laid:
            extra[y, x] = False
        self.assertFalse(extra.any(), "a second drive was laid beside the first")
        self.assertTrue(_stone(ground, 13, 61), "no path from the door")

    def test_a_house_within_walk_limit_with_no_drive_gets_a_path(self):
        # A stream with one footbridge-wide gap: no straight drive gets across.
        stream = [(x, 8) for x in range(30) if x != 13]
        ground = _paint(30, 30, [("house", 10, 16)], water=stream)
        for y in range(2, 16):
            self.assertTrue(_stone(ground, 13, y), f"no path at (13, {y})")

    def test_an_extremely_long_front_path_is_omitted(self):
        # Beyond WALK_MAX_TILES, no concrete path is drawn across open ground.
        stream = [(x, 30) for x in range(30) if x != 13]
        ground = _paint(30, 80, [("house", 10, 62)], water=stream)
        self.assertFalse(any(_stone(ground, 13, y) for y in range(2, 62)),
                         "extremely long path should not be painted")

    def test_a_path_goes_around_the_neighbours_back_yard(self):
        alone = _paint(40, 40, [("house", 10, 4)])
        both = _paint(40, 40, [("house", 10, 4), ("house", 10, 24)])
        # The house and the minimum yard every house gets (the yard behind it
        # starts at row 10); a deeper yard may extend further, but this part is
        # claimed whatever the depth chosen.
        yard = (slice(10, 10 + YARD_MIN_DEPTH), slice(8, 18))
        self.assertTrue((alone[yard] == both[yard]).all(),
                        "the second house's path was painted over the first one's yard")



class BackYards(unittest.TestCase):
    def pieces(self, veg, colour):
        return {(int(x), int(y)) for y, x in zip(*np.nonzero(np.all(veg == colour, axis=2)))}

    def test_the_deck_chair_s_halves_lie_end_to_end(self):
        """Each half is half of one sprite: X0 west of X1, Y0 north of Y1.
        A yard beside the house once got its two halves side by side."""
        streets = {"N": [("house", 10, 10)],                      # yard behind, to the south
                   "W": [("house", 10, 10, (0, 3, "W"))],         # yard behind, to the east
                   "E": [("house", 20, 10, (SIZE, 3, "W"))]}      # yard behind, to the west
        for door, houses in streets.items():
            veg = _paint(40, 40, houses, veg=True)
            x0, x1 = self.pieces(veg, C.TABLE_X0), self.pieces(veg, C.TABLE_X1)
            y0, y1 = self.pieces(veg, C.TABLE_Y0), self.pieces(veg, C.TABLE_Y1)
            self.assertTrue(x0 or y0, door)
            self.assertEqual({(x + 1, y) for x, y in x0}, x1, door)
            self.assertEqual({(x, y + 1) for x, y in y0}, y1, door)

    def test_yards_get_a_dog_house_and_a_swing_with_the_rules(self):
        """Not every yard has them, but a street of them does: the props are
        gated on the rules carrying them, like the poles and the benches."""
        houses = [("house", 4 + 12 * n, 10) for n in range(6)]
        with mock.patch.object(yards_module, "_rule_ready", return_value=True):
            veg = _paint(80, 40, houses, veg=True)
        self.assertTrue(self.pieces(veg, C.DOG_HOUSE), "no dog house")

    def test_a_blocked_square_moves_the_dog_house_rather_than_dropping_it(self):
        """The props used to be tried on one fixed square each and silently
        skipped when the patio or a bed was there."""
        houses = [("house", 10, 10)]
        with mock.patch.object(yards_module, "_rule_ready", return_value=True), \
                mock.patch.object(yards_module, "DOG_HOUSE_SHARE", 1.0):
            plain = _paint(40, 40, houses, veg=True)
            dog = self.pieces(plain, C.DOG_HOUSE)
            self.assertTrue(dog, "no dog house at all")
            # Water on the square it took: it must find another, not vanish.
            blocked = _paint(40, 40, houses, water=[next(iter(dog))], veg=True)
        moved = self.pieces(blocked, C.DOG_HOUSE)
        self.assertTrue(moved, "the dog house was dropped, not moved")
        self.assertNotEqual(moved, dog)

    def test_without_the_rules_a_yard_gets_neither(self):
        houses = [("house", 4 + 12 * n, 10) for n in range(6)]
        with mock.patch.object(yards_module, "_rule_ready", return_value=False):
            veg = _paint(80, 40, houses, veg=True)
        self.assertEqual(self.pieces(veg, C.DOG_HOUSE), set())

    def test_a_blocked_half_takes_the_whole_deck_chair_with_it(self):
        """With water where the second half would go, the first half is not
        left standing alone."""
        houses = [("house", 10, 10)]
        veg = _paint(40, 40, houses, veg=True)
        x0, x1 = self.pieces(veg, C.TABLE_X0), self.pieces(veg, C.TABLE_X1)
        self.assertTrue(x0 and x1)
        veg = _paint(40, 40, houses, water=list(x1), veg=True)
        self.assertEqual(self.pieces(veg, C.TABLE_X0), set())
        self.assertEqual(self.pieces(veg, C.TABLE_X1), set())


class Variation(unittest.TestCase):
    def test_a_street_gets_more_than_one_kind_of_yard(self):
        plans = [yard_plan(6 + 10 * n, 6) for n in range(12)]
        self.assertGreaterEqual(len({p[2] for p in plans}), 3, "archetypes")
        self.assertGreaterEqual(len({p[0] for p in plans}), 2, "fence styles")
        self.assertTrue(any(not p[1] for p in plans), "some yards are open")

    def test_a_house_gets_the_same_yard_every_time(self):
        self.assertEqual(yard_plan(42, 17), yard_plan(42, 17))

    def test_terraced_edge_obstacle_still_gets_inset_back_yard_and_front_details(self):
        with tempfile.TemporaryDirectory() as out:
            os.mkdir(os.path.join(out, "buildings"))
            occupied = np.zeros((40, 60), dtype=bool)
            ground = np.full((40, 60, 3), C.MEDIUM_GRASS, dtype=np.uint8)
            ground[28:32, :] = C.PALE_CONCRETE
            ground[32:36, :] = C.MEDIUM_ASPHALT
            veg = np.full((40, 60, 3), C.VEG_NOTHING, dtype=np.uint8)
            Image.fromarray(ground, "RGB").save(os.path.join(out, "m.bmp"))
            Image.fromarray(veg, "RGB").save(os.path.join(out, "m_veg.bmp"))
            rows = []
            # Three closely spaced terraced houses with front doors facing south (y=20)
            # and a 1-tile obstacle along one side of the back yard.
            for idx, bx in enumerate((6, 16, 26)):
                _building(os.path.join(out, "buildings"), f"h{idx}.tbx", door=(3, 6, "N"))
                occupied[14:20, bx:bx + SIZE] = True
                occupied[10:14, bx] = True  # blocks side=0 on the west corner
                rows.append({"kind": "house", "file": f"h{idx}.tbx",
                             "tile_x": bx, "tile_y": 14, "width": SIZE, "height": SIZE})
            _paths, fences = paint_paths(out, "m", rows, occupied)
            # At least one house should get a fenced inset back yard despite the corner block.
            self.assertTrue(any(yard_plan(6 + 10 * n, 14)[1] for n in range(3)))
            self.assertGreater(len(fences), 0)
            veg_after = np.asarray(Image.open(os.path.join(out, "m_veg.bmp")))
            colours = {tuple(c) for c in veg_after.reshape(-1, 3)}
            self.assertIn(C.FLOWERS, colours)


class MultiDoorAndInfillFrontPaths(unittest.TestCase):
    @staticmethod
    def _write_doors_tbx(folder, name, doors):
        rows = "\n".join(",".join(["1"] * SIZE) for _ in range(SIZE))
        objs = "".join(
            f'<object type="door" x="{x}" y="{y}" dir="{d}"/>'
            for x, y, d in doors
        )
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(f"<building><floor><rooms>\n{rows}\n</rooms>{objs}</floor></building>")

    def test_blocked_first_door_falls_back_to_street_facing_door(self):
        with tempfile.TemporaryDirectory() as out:
            os.mkdir(os.path.join(out, "buildings"))
            occupied = np.zeros((30, 30), dtype=bool)
            ground = np.full((30, 30, 3), C.MEDIUM_GRASS, dtype=np.uint8)
            ground[22:25, :] = C.PALE_CONCRETE
            ground[25:28, :] = C.MEDIUM_ASPHALT
            veg = np.full((30, 30, 3), C.VEG_NOTHING, dtype=np.uint8)
            Image.fromarray(ground, "RGB").save(os.path.join(out, "m.bmp"))
            Image.fromarray(veg, "RGB").save(os.path.join(out, "m_veg.bmp"))

            # First door at north wall (blocked by occupied), second door at south wall facing street
            self._write_doors_tbx(os.path.join(out, "buildings"), "multi.tbx",
                                  [(3, 0, "N"), (3, 6, "N")])
            occupied[10:16, 10:16] = True
            occupied[9, 13] = True  # block the first door's outside tile
            rows = [{"kind": "house", "file": "multi.tbx",
                     "tile_x": 10, "tile_y": 10, "width": SIZE, "height": SIZE}]
            paths, _ = paint_paths(out, "m", rows, occupied)
            self.assertEqual(paths, 1)
            after = np.asarray(Image.open(os.path.join(out, "m.bmp")))
            # South door at (13, 16) should have a paved stoop and a paved route to y=21
            self.assertNotEqual(tuple(after[16, 13]), C.MEDIUM_GRASS)
            self.assertTrue(any(tuple(after[21, x]) != C.MEDIUM_GRASS for x in range(10, 20)))

    def test_infill_shop_with_two_front_doors_gets_paths_to_street(self):
        with tempfile.TemporaryDirectory() as out:
            os.mkdir(os.path.join(out, "buildings"))
            occupied = np.zeros((30, 30), dtype=bool)
            ground = np.full((30, 30, 3), C.MEDIUM_GRASS, dtype=np.uint8)
            ground[22:25, :] = C.PALE_CONCRETE
            ground[25:28, :] = C.MEDIUM_ASPHALT
            veg = np.full((30, 30, 3), C.VEG_NOTHING, dtype=np.uint8)
            Image.fromarray(ground, "RGB").save(os.path.join(out, "m.bmp"))
            Image.fromarray(veg, "RGB").save(os.path.join(out, "m_veg.bmp"))

            self._write_doors_tbx(os.path.join(out, "buildings"), "shop.tbx",
                                  [(1, 6, "N"), (4, 6, "N")])
            occupied[10:16, 10:16] = True
            rows = [{"kind": "shop", "file": "shop.tbx",
                     "tile_x": 10, "tile_y": 10, "width": SIZE, "height": SIZE}]
            paths, _ = paint_paths(out, "m", rows, occupied)
            self.assertEqual(paths, 1)
            after = np.asarray(Image.open(os.path.join(out, "m.bmp")))
            self.assertNotEqual(tuple(after[16, 11]), C.MEDIUM_GRASS)
            self.assertNotEqual(tuple(after[21, 11]), C.MEDIUM_GRASS)
            self.assertNotEqual(tuple(after[16, 14]), C.MEDIUM_GRASS)
            self.assertNotEqual(tuple(after[21, 14]), C.MEDIUM_GRASS)


if __name__ == "__main__":
    unittest.main()
