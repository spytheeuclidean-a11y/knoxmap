"""End-to-end parity between knoxlots source workers and the Python reference."""
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from knoxbuild.layout import build_plan
from knoxbuild.tbx import render_tbx
from tools import map_source, native_source
from tools.compile_cells import lot_hashes
from tools.compile_map import knoxlots_exe


class NativeSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = knoxlots_exe()
        if not cls.exe or not native_source.supported(cls.exe):
            raise unittest.SkipTest("requires knoxlots with source-worker support")

    def test_overlapping_lots_basement_and_terrain_across_a_cell_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "town"
            buildings = project / "buildings"
            buildings.mkdir(parents=True)
            for name, kind in (("house", "house"), ("shop", "shop")):
                plan = build_plan(14, 12, kind=kind, ground=False, seed=4)
                (buildings / f"{name}.tbx").write_text(render_tbx(plan, name), encoding="utf-8")
            (project / "town.pzw").write_text(
                '<world>\n<worldOrigin origin="0,0"/>\n<cell x="0" y="0">\n'
                '<lot x="250" y="249" level="0" width="14" height="12" map="buildings/house.tbx"/>\n'
                '<lot x="260" y="249" level="0" width="14" height="12" map="buildings/shop.tbx"/>\n'
                '<lot x="250" y="249" level="-1" width="14" height="12" map="buildings/house.tbx"/>\n'
                '</cell>\n</world>', encoding="utf-8")
            ground = Image.new("RGB", (300, 300), (10, 20, 30))
            ground.paste((40, 50, 60), (255, 200, 280, 285))
            ground.save(project / "town.bmp")
            Image.new("RGB", ground.size).save(project / "town_veg.bmp")
            Image.new("L", (30, 30), 41).save(project / "town_ZombieSpawnMap.bmp")
            rules = root / "Rules.txt"
            rules.write_text(
                "alias\n{\nname = grass\ntiles = [\nfloor_001\nfloor_002\n]\n}\n"
                "rule\n{\nbitmap = 0\ncolor = 10 20 30\ntiles = grass\nlayer = 0_Floor\n}\n"
                "rule\n{\nbitmap = 0\ncolor = 40 50 60\ntiles = floor_003\nlayer = 0_Floor\n}\n",
                encoding="utf-8")
            (root / "Blends.txt").write_text(
                "blend\n{\nlayer = 0_FloorOverlay\nmainTile = grass\nblendTile = edge_001\ndir = w\n}\n",
                encoding="utf-8")
            outputs = []
            for label, exe in (("python", None), ("rust", self.exe)):
                src, lots = root / label, root / (label + "-lots")
                with patch.object(map_source, "rules_path", return_value=str(rules)):
                    count = map_source.make_map_source(
                        str(project), str(src), seed=37, seams=True, workers=2 if exe else 1,
                        track=True, native_exe=exe)
                self.assertEqual(count, 4)
                subprocess.run([self.exe, "compile", src, lots, "--threads", "2"],
                               capture_output=True, check=True)
                outputs.append((lot_hashes(lots), {
                    f.name: json.loads(f.read_text()) for f in src.glob("footprints_*.json")}))
            self.assertEqual(len(outputs[0][0]), 12)
            self.assertEqual(outputs[0], outputs[1])
