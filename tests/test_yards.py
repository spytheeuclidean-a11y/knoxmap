import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from generator import pz_colors as C
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

    def test_a_house_far_back_with_no_drive_still_gets_a_path(self):
        # A stream with one footbridge-wide gap: no straight drive gets across.
        stream = [(x, 30) for x in range(30) if x != 13]
        ground = _paint(30, 80, [("house", 10, 62)], water=stream)
        for y in range(2, 62):
            self.assertTrue(_stone(ground, 13, y), f"no path at (13, {y})")

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


if __name__ == "__main__":
    unittest.main()
