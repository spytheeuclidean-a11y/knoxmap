"""What an installed map ships so the game's fixed buffers do not overflow."""
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import make_map_mod as M  # noqa: E402


class SpawnPicture(unittest.TestCase):
    def test_the_spawn_picker_gets_a_picture_of_the_map(self):
        project = tempfile.mkdtemp()
        name = os.path.basename(project)
        Image.new("RGB", (900, 600), (90, 120, 60)).save(os.path.join(project, f"{name}_preview.png"))
        with open(os.path.join(project, f"{name}.pzw"), "w", encoding="utf-8") as f:
            f.write('<world width="3" height="2">\n <worldOrigin origin="71,1"/>\n</world>\n')
        out = tempfile.mkdtemp()
        self.assertTrue(M.write_spawn_pyramid(project, out))
        z = zipfile.ZipFile(os.path.join(out, "spawnSelectImagePyramid.zip"))
        text = z.read("pyramid.txt").decode()
        self.assertIn("bounds=21300 300 22200 900", text)
        self.assertIn("imageSize=900 600", text)
        names = set(z.namelist())
        self.assertIn("0/tile3x2.png", names)          # 900 x 600 is 4 x 3 tiles of 256
        self.assertIn("1/tile1x1.png", names)          # halved: 2 x 2, three or fewer a side
        self.assertNotIn("2/", names)

    def test_no_preview_no_picture(self):
        self.assertFalse(M.write_spawn_pyramid(tempfile.mkdtemp(), tempfile.mkdtemp()))


class SaveBuffer(unittest.TestCase):
    def test_a_city_of_rooms_is_past_what_the_game_can_save(self):
        # Hamburg: 4087 cells, 1,577,797 rooms, 237,854 buildings.
        def header(path):
            return [], 0, 0, [None] * 386, [None] * 58
        cells = [f"{i}_0.lotheader" for i in range(4087)]
        with mock.patch("tools.building_stats.read_header", header):
            self.assertGreater(M.save_bytes(cells), M.META_BUDGET)

    def test_a_town_fits(self):
        def header(path):
            return [], 0, 0, [None] * 140, [None] * 8
        cells = [f"{i}_0.lotheader" for i in range(1760)] + ["world_0_0.lotpack"]
        with mock.patch("tools.building_stats.read_header", header):
            got = M.save_bytes(cells)
        self.assertEqual(got, 1760 * (8 + 140 * 10 + 8 * 23))
        self.assertLess(got, M.META_BUDGET)


if __name__ == "__main__":
    unittest.main()
