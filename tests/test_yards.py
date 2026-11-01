import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from generator import pz_colors as C
from knoxbuild.bitmaps import read_rgb
from knoxbuild.yards import _pave_patio, paint_paths


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


def _building(folder, name):
    """A one-room ground floor with an outside door at (3, 0), facing north."""
    rows = "\n".join(",".join(["1"] * SIZE) for _ in range(SIZE))
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        f.write(f'<building><floor><rooms>\n{rows}\n</rooms>'
                f'<object type="door" x="3" y="0" dir="N"/></floor></building>')


def _paint(width, height, buildings):
    """Lawn with a pavement along the top two rows; return the painted ground.

    `buildings` is (kind, tile_x, tile_y) per building."""
    with tempfile.TemporaryDirectory() as out:
        os.mkdir(os.path.join(out, "buildings"))
        ground = np.zeros((height, width, 3), dtype=np.uint8)
        ground[:, :] = C.MEDIUM_GRASS
        ground[:2, :] = C.PALE_CONCRETE
        Image.fromarray(ground).save(os.path.join(out, "t.bmp"), format="BMP")
        Image.fromarray(np.zeros_like(ground)).save(os.path.join(out, "t_veg.bmp"),
                                                   format="BMP")
        occupied = np.zeros((height, width), dtype=bool)
        rows = []
        for n, (kind, x, y) in enumerate(buildings):
            _building(os.path.join(out, "buildings"), f"b{n}.tbx")
            occupied[y:y + SIZE, x:x + SIZE] = True
            rows.append({"file": f"b{n}.tbx", "kind": kind, "building": "yes",
                         "tile_x": x, "tile_y": y, "width": SIZE, "height": SIZE})
        paint_paths(out, "t", rows, occupied)
        return read_rgb(os.path.join(out, "t.bmp"))


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

    def test_a_path_goes_around_the_neighbours_back_yard(self):
        alone = _paint(40, 40, [("house", 10, 4)])
        both = _paint(40, 40, [("house", 10, 4), ("house", 10, 24)])
        yard = (slice(10, 19), slice(8, 18))   # behind the first house
        self.assertTrue((alone[yard] == both[yard]).all(),
                        "the second house's path was painted over the first one's yard")


if __name__ == "__main__":
    unittest.main()
