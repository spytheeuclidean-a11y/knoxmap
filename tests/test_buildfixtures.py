"""Optional regression checks against local WorldEd output, never generated predictions."""
import os
import importlib.util
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

from knoxbuild.buildtiles import compose_lots, level_tiles, parse_tbx

FIXTURES = Path(os.environ.get("KNOXLOTS_FIXTURES", Path(__file__).resolve().parents[1] / "rust/knoxlots/fixtures"))
TERRAIN = ("blends_", "vegetation_foliage", "e_", "d_", "lighting_outdoor")


@unittest.skipUnless(FIXTURES.is_dir(), "local WorldEd fixtures are not installed")
class WorldEdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(FIXTURES))
        from bxshow import load
        sys.path.pop(0)
        cls.load = staticmethod(load)

    def check_building(self, folder, name, tx, ty, region=None):
        b = parse_tbx((folder / "buildings" / (name + ".tbx")).read_text(encoding="utf-8"))
        cache = {}
        for z in range(len(b.floors)):
            pred = level_tiles(b, z)
            for y in range(-2, b.height + 3):
                for x in range(-2, b.width + 3):
                    if region and not region(z, x, y):
                        continue
                    cx, cy = (21000 + tx + x) // 256, (ty + y) // 256
                    if (cx, cy) not in cache:
                        cache[cx, cy] = self.load(str(folder / "lots"), cx, cy)[0]
                    actual = cache[cx, cy].get(((21000 + tx + x) % 256, (ty + y) % 256, z), [])
                    actual = [t for t in actual if not t.startswith(TERRAIN)]
                    self.assertEqual(pred.get((x, y), []), actual, f"{name}: level {z}, ({x},{y})")

    def test_all_handmade_cases(self):
        for folder in sorted((FIXTURES / "bx").iterdir()):
            if folder.is_dir():
                with self.subTest(case=folder.name):
                    self.check_building(folder, folder.name, 40, 40)

    def test_four_level_house(self):
        self.check_building(FIXTURES / "exp/house", "house_0000", 269, 592)

    def test_fresh_custom_walls_and_unusual_windows(self):
        extra = Path(os.environ.get("KNOXLOTS_EXTRA", FIXTURES / "extra"))
        if not extra.is_dir():
            self.skipTest("additional WorldEd fixtures are not installed")
        for name in ("wallW", "wallN", "windows"):
            with self.subTest(case=name):
                self.check_building(extra / name, "building", 40, 40)

    def test_fresh_overlaps(self):
        extra = Path(os.environ.get("KNOXLOTS_EXTRA", FIXTURES / "extra"))
        if not extra.is_dir():
            self.skipTest("additional WorldEd fixtures are not installed")
        for name in ("overlap", "overlap-small", "overlap-trim"):
            with self.subTest(case=name):
                folder = extra / name
                a, b = [parse_tbx((folder / "buildings" / (n + ".tbx")).read_text())
                        for n in ("building", "second")]
                want = compose_lots([(a, 40, 40, 0), (b, 43, 42, 0)])
                actual = self.load(str(folder / "lots"), 82, 0)[0]
                for y in range(38, 51):
                    for x in range(38, 53):
                        tiles = [t for t in actual.get(((21000 + x) % 256, y, 0), []) if not t.startswith(TERRAIN)]
                        self.assertEqual(want.get((x, y, 0), []), tiles, f"{name}: ({x},{y})")

    def test_composed_project_checker(self):
        extra = Path(os.environ.get("KNOXLOTS_EXTRA", FIXTURES / "extra"))
        script = Path(os.environ.get("KNOXLOTS_COMPOSECHECK", FIXTURES / "composecheck.py"))
        if not extra.is_dir() or not script.is_file():
            self.skipTest("composed checker and additional fixtures are not installed")
        spec = importlib.util.spec_from_file_location("composecheck", script)
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(FIXTURES))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        result = module.compare_project(extra / "overlap-small")
        self.assertEqual(result["buildings"], 2)
        self.assertGreater(result["overlaps"], 0)
        self.assertGreater(result["total"], 0)
        self.assertEqual(result["misses"], [])

    def test_real_roofs_shutters_curtains_and_walls_furniture(self):
        folder = FIXTURES / "real/real1"
        regions = {
            "real1_0013": lambda z, x, y: (z == 2 and 6 <= x <= 19 and 7 <= y <= 19)
                                             or (z == 0 and (x, y) in ((1, 14), (6, 19))),
            "real1_0063": lambda z, x, y: z == 2 and 0 <= x <= 13 and 7 <= y <= 20,
            "real1_0012": lambda z, x, y: (z < 5 and x in (31, 32) and y == 23)
                                             or (z == 5 and (x, y) == (38, 4)),
            "real1_0031": lambda z, x, y: z == 1 and (x, y) == (5, 7),
        }
        project = ET.parse(folder / "real1.pzw")
        for name, region in regions.items():
            with self.subTest(building=name):
                placements = [(int(cell.get("x")) * 300 + int(lot.get("x")),
                               int(cell.get("y")) * 300 + int(lot.get("y")))
                              for cell in project.iter("cell") for lot in cell.findall("lot")
                              if lot.get("map") == "buildings/" + name + ".tbx"]
                self.assertEqual(len(placements), 1)
                self.check_building(folder, name, *placements[0], region=region)


if __name__ == "__main__":
    unittest.main()
