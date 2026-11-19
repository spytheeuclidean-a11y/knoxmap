"""End-to-end parity between knoxlots source workers and the Python reference."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import warnings

from PIL import Image

from generator import pz_colors as C
from knoxbuild import buildtiles, kcell, terrain, world
from knoxbuild.layout import build_building, build_plan
from knoxbuild.tbx import render_tbx
from tools import map_source, native_source
from tools.compile_cells import lot_hashes
from tools.compile_map import knoxlots_exe


ROOT = Path(__file__).resolve().parent.parent
WORKER_DIR = ROOT / "rust" / "knoxlots" / "src" / "worker"


class NativeConstantsSync(unittest.TestCase):
    """Fail immediately if shared constants drift between Python and Rust workers."""

    def test_terrain_constants_match_python(self):
        src = (WORKER_DIR / "terrain.rs").read_text(encoding="utf-8")
        self.assertIn(f"const WIN: usize = {kcell.SIDE + 2};", src)
        self.assertIn(f"div_euclid({world.CELL_SIZE})", src)

        order_m = re.search(r"const ORDER:\s*\[&str;\s*\d+\]\s*=\s*\[(.*?)\];", src, re.S)
        self.assertIsNotNone(order_m)
        rust_order = re.findall(r'"([^"]+)"', order_m.group(1))
        self.assertEqual(rust_order, terrain.LAYER_ORDER)

        # Vegetation-excluded ground RGB keys in terrain.rs must match terrain.py.
        py_keys = {
            (c[0] << 16) | (c[1] << 8) | c[2]
            for c in (
                C.DARK_ASPHALT, C.MEDIUM_ASPHALT, C.LIGHT_ASPHALT, C.DARKEST_ASPHALT,
                C.PALE_CONCRETE, C.DARK_POTHOLE, C.LIGHT_POTHOLE, C.WATER,
            )
        }
        rust_hex = {int(h, 16) for h in re.findall(r"0x([0-9a-fA-F]{6})", src)}
        self.assertTrue(py_keys <= rust_hex, f"missing no-veg keys in terrain.rs: {py_keys - rust_hex}")

    def test_building_structure_and_yielding_prefixes_match_python(self):
        src = (WORKER_DIR / "building.rs").read_text(encoding="utf-8")
        struct_m = re.search(r"fn structure\(t: &str\) -> bool \{\s*\[(.*?)\]", src, re.S)
        self.assertIsNotNone(struct_m)
        self.assertEqual(tuple(re.findall(r'"([^"]+)"', struct_m.group(1))),
                         buildtiles.STRUCTURE_PREFIXES)

        finish_m = re.search(r"pub fn finish\(.*?\!\[\s*(.*?)\s*\]", src, re.S)
        self.assertIsNotNone(finish_m)
        self.assertEqual(tuple(re.findall(r'"([^"]+)"', finish_m.group(1))),
                         buildtiles.YIELDING_PREFIXES)


class NativeSourceHardening(unittest.TestCase):
    def test_supported_handles_timeout_and_missing_binary(self):
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(["x"], 15)):
            self.assertFalse(native_source.supported("x"))
        with patch.object(subprocess, "run", side_effect=FileNotFoundError("no exe")):
            self.assertFalse(native_source.supported("missing"))

    def test_temp_dirs_are_created_outside_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            seen_dirs = []

            def fake_run(_exe, job, folder, _stop):
                seen_dirs.append((job.tag, Path(folder).resolve()))
                if job.tag == "tables":
                    Path(job.attrib["out"]).write_text("<tables/>", encoding="utf-8")

            with patch.object(native_source, "_run", side_effect=fake_run):
                native_source.tables("exe", tmp, str(out), [], (0, 0), None)
                native_source.row("exe", tmp, str(out), 0, [], {}, (0, 0),
                                  (256, 256), [0], 1, False, "Rules.txt", False, None)

            self.assertEqual(len(seen_dirs), 2)
            for tag, folder in seen_dirs:
                self.assertNotIn(out.resolve(), folder.parents, f"{tag} temp dir inside out")
                self.assertNotEqual(folder, out.resolve())


class NativeSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = knoxlots_exe()
        if not cls.exe or not native_source.supported(cls.exe):
            msg = "requires knoxlots with source-worker support"
            if os.environ.get("KNOXMAP_REQUIRE_NATIVE_TESTS") == "1":
                raise RuntimeError(msg)
            warnings.warn(f"Skipping NativeSource parity tests: {msg}", RuntimeWarning, stacklevel=2)
            raise unittest.SkipTest(msg)

    def _run_parity(self, root: Path, setup_fn, expected_cells: int):
        project = root / "town"
        (project / "buildings").mkdir(parents=True)
        setup_fn(project)
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
            self.assertEqual(count, expected_cells)
            subprocess.run([self.exe, "compile", src, lots, "--threads", "2"],
                           capture_output=True, check=True)
            outputs.append((lot_hashes(lots), {
                f.name: json.loads(f.read_text()) for f in src.glob("footprints_*.json")}))
        self.assertEqual(outputs[0], outputs[1])
        return outputs[0]

    def test_overlapping_lots_basement_and_terrain_across_a_cell_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            def setup(project: Path):
                for name, kind in (("house", "house"), ("shop", "shop")):
                    plan = build_plan(14, 12, kind=kind, ground=False, seed=4)
                    (project / "buildings" / f"{name}.tbx").write_text(
                        render_tbx(plan, name), encoding="utf-8")
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

            hashes, _ = self._run_parity(Path(tmp), setup, expected_cells=4)
            self.assertEqual(len(hashes), 12)

    def test_roof_variants_openings_stairs_and_multi_storey_parity(self):
        from knoxbuild import catalog as cat

        with tempfile.TemporaryDirectory() as tmp:
            def setup(project: Path):
                house_style = {
                    **cat.HOUSE_STYLES[0],
                    "peaked": True,
                    "roof30": True,
                }
                blds = [
                    ("house2", build_building(14, 12, levels=2, kind="house", seed=7), house_style),
                    ("shop2", build_building(16, 12, levels=2, commercial=True, kind="shop", seed=9), None),
                    ("apts", build_building(18, 14, levels=3, kind="apartment", seed=11), None),
                ]
                for name, bld, style in blds:
                    (project / "buildings" / f"{name}.tbx").write_text(
                        render_tbx(bld, name, style=style), encoding="utf-8")
                (project / "town.pzw").write_text(
                    '<world>\n<worldOrigin origin="0,0"/>\n<cell x="0" y="0">\n'
                    '<lot x="20" y="20" level="0" width="14" height="12" map="buildings/house2.tbx"/>\n'
                    '<lot x="60" y="20" level="0" width="16" height="12" map="buildings/shop2.tbx"/>\n'
                    '<lot x="110" y="20" level="0" width="18" height="14" map="buildings/apts.tbx"/>\n'
                    '</cell>\n</world>', encoding="utf-8")
                ground = Image.new("RGB", (300, 300), (10, 20, 30))
                ground.save(project / "town.bmp")
                Image.new("RGB", ground.size).save(project / "town_veg.bmp")
                Image.new("L", (30, 30), 41).save(project / "town_ZombieSpawnMap.bmp")

            self._run_parity(Path(tmp), setup, expected_cells=4)
