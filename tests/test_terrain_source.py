import os
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(ROOT, "vendor", "PZMappingTools", "config", "Rules.txt")


@unittest.skipUnless(os.path.exists(RULES), "the mapping tools' Rules.txt is not installed")
class TerrainSourceTests(unittest.TestCase):
    def make_project(self, d):
        proj = os.path.join(d, "tiny")
        os.makedirs(proj)
        h, w = 520, 600
        land = np.zeros((h, w, 3), np.uint8)
        land[:] = (90, 100, 35)                 # dark grass
        land[200:230, :] = (150, 150, 150)      # a road across the map
        land[:, 300:310] = (0, 138, 255)        # and a river down it
        veg = np.zeros((h, w, 3), np.uint8)
        veg[40:60, 40:60] = (255, 0, 0)         # some trees
        Image.fromarray(land).save(os.path.join(proj, "tiny.bmp"), format="BMP")
        Image.fromarray(veg).save(os.path.join(proj, "tiny_veg.bmp"), format="BMP")
        return proj

    def read_all(self, folder):
        return {f: open(os.path.join(folder, f), "rb").read() for f in sorted(os.listdir(folder))}

    def test_one_worker_and_several_make_the_same_files(self):
        from tools.terrain_source import make_sources

        with tempfile.TemporaryDirectory() as d:
            proj = self.make_project(d)
            a, b = os.path.join(d, "a"), os.path.join(d, "b")
            n1 = make_sources(proj, a, seed=3, workers=1)
            n2 = make_sources(proj, b, seed=3, workers=2)
            self.assertEqual(n1, n2)
            self.assertGreater(n1, 4)
            fa, fb = self.read_all(a), self.read_all(b)
            self.assertEqual(sorted(fa), sorted(fb))
            self.assertTrue(all(fa[k] == fb[k] for k in fa))
            self.assertIn("source.txt", fa)

    def test_another_seed_makes_other_tiles(self):
        from tools.terrain_source import make_sources

        with tempfile.TemporaryDirectory() as d:
            proj = self.make_project(d)
            a, b = os.path.join(d, "a"), os.path.join(d, "b")
            make_sources(proj, a, seed=1, workers=1)
            make_sources(proj, b, seed=2, workers=1)
            fa, fb = self.read_all(a), self.read_all(b)
            self.assertTrue(any(fa[k] != fb[k] for k in fa if k.endswith(".kcell")))


if __name__ == "__main__":
    unittest.main()
