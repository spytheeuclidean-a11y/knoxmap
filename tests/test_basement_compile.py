"""Levels below ground through the .pzw, the cell sources and knoxlots."""
import glob
import os
import re
import shutil
import struct
import tempfile
import unittest

import numpy as np

from knoxbuild.kcell import SIDE, cell_source
from knoxbuild.layout import build_plan
from knoxbuild.settings import Settings
from knoxbuild.tbx import render_tbx
from knoxbuild.world import Placement, render_pzw
from tools.building_stats import read_header
from tools.compile_map import compile_rust, knoxlots_exe
from tools.map_source import project_origin, read_lots

from tests.basement_town import build_town

SOURCE_CELL = 300   # the .pzw's cells; the game's are 256 (SIDE)


def _add_lot(project: str, name: str, tx: int, ty: int, w: int, h: int, level: int) -> None:
    """Put a lot into the project's .pzw by hand, in the source cell of its corner."""
    stem = os.path.basename(os.path.normpath(project))
    pzw = os.path.join(project, f"{stem}.pzw")
    text = open(pzw, encoding="utf-8").read()
    cx, cy = tx // SOURCE_CELL, ty // SOURCE_CELL
    line = (f'  <lot x="{tx % SOURCE_CELL}" y="{ty % SOURCE_CELL}" level="{level}"'
            f' width="{w}" height="{h}" map="buildings/{name}"/>\n')
    m = re.search(rf'<cell x="{cx}" y="{cy}"[^>]*>\n', text)
    open(pzw, "w", encoding="utf-8").write(text[:m.end()] + line + text[m.end():])


def _levels(project: str) -> dict[str, tuple[int, int]]:
    return {os.path.basename(p): read_header(p)[1:3]
            for p in glob.glob(os.path.join(project, "lots", "*.lotheader"))}


class SignedLevels(unittest.TestCase):
    def test_a_lot_at_level_minus_2_is_read_back(self):
        with tempfile.TemporaryDirectory() as work:
            project = os.path.join(work, "t")
            os.makedirs(project)
            text = render_pzw(1, 1, "t.bmp", [Placement("buildings/a.tbx", 5, 6, 3, 3,
                                                        base_level=-2)], "t", project)
            self.assertIn('level="-2"', text)
            open(os.path.join(project, "t.pzw"), "w", encoding="utf-8").write(text)
            self.assertEqual(read_lots(project), [("a", 5, 6, -2, 3, 3)])

    def test_cell_source_below_ground_is_version_2_and_signed(self):
        layer = np.zeros((SIDE, SIDE), np.int64)
        layer[1, 1] = 1
        data = cell_source(0, 0, ["floors_a_01_0"], [[layer], [layer]], min_z=-1,
                           rooms=[("storage", -1, [(1, 1, 2, 2)], [])])
        version, _cx, _cy, min_z, levels = struct.unpack_from("<3IiI", data, 4)
        self.assertEqual((version, min_z, levels), (2, -1, 2))
        self.assertIn(b"storage" + struct.pack("<iI", -1, 1), data)

    def test_cell_source_above_ground_is_unchanged(self):
        layer = np.zeros((SIDE, SIDE), np.int64)
        self.assertEqual(cell_source(0, 0, [], [[layer]], min_z=0)[4:8], struct.pack("<I", 1))


@unittest.skipIf(knoxlots_exe() is None, "knoxlots is not built")
class BasementLotsCompile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="bsmt-compile-")
        cls.base = build_town(os.path.join(cls.work, "town"), Settings(seed=1),
                              compile_lots=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def _copy(self, name):
        project = os.path.join(self.work, name)
        shutil.copytree(self.base, project)
        os.rename(os.path.join(project, "town.pzw"), os.path.join(project, f"{name}.pzw"))
        for f in glob.glob(os.path.join(project, "town*")):
            os.rename(f, os.path.join(project, name + os.path.basename(f)[4:]))
        return project

    def test_a_basement_lot_compiles_to_level_minus_1(self):
        project = self._copy("one")
        name, tx, ty, _lv, w, h = read_lots(project)[0]
        shutil.copy(os.path.join(project, "buildings", f"{name}.tbx"),
                    os.path.join(project, "buildings", f"{name}_bsmt.tbx"))
        _add_lot(project, f"{name}_bsmt.tbx", tx, ty, w, h, -1)
        compile_rust(project)
        ox, oy = project_origin(project)
        cell = f"{(ox + tx) // SIDE}_{(oy + ty) // SIDE}.lotheader"
        levels = _levels(project)
        self.assertEqual(levels[cell][0], -1)
        others = [lv for c, lv in levels.items() if c != cell]
        self.assertTrue(others and all(lo == 0 for lo, _hi in others))
        # One building, its rooms on both levels, in the house's own cell.
        rooms, buildings = read_header(os.path.join(project, "lots", cell))[3:5]
        joined = [b for b in buildings if {-1, 0} <= {rooms[i][1] for i in b}]
        self.assertEqual(len(joined), 1)
        self.assertFalse(any(all(rooms[i][1] == -1 for i in b) for b in buildings))

    def test_an_installation_across_a_cell_edge_gives_both_cells_min_z(self):
        project = self._copy("wide")
        ox, oy = project_origin(project)
        _name, _tx, ty, *_ = read_lots(project)[0]
        tx = (ox // SIDE + 1) * SIDE - ox - 20          # 20 tiles west of a cell edge
        plan = build_plan(40, 10, kind="military", ground=False, seed=2)
        open(os.path.join(project, "buildings", "wide_bsmt.tbx"), "w",
             encoding="utf-8").write(render_tbx(plan, "wide"))
        _add_lot(project, "wide_bsmt.tbx", tx, ty, 40, 10, -2)
        compile_rust(project)
        cy = (oy + ty) // SIDE
        west, east = f"{(ox + tx) // SIDE}_{cy}.lotheader", f"{(ox + tx + 39) // SIDE}_{cy}.lotheader"
        self.assertNotEqual(west, east)
        levels = _levels(project)
        self.assertEqual((levels[west][0], levels[east][0]), (-2, -2))


if __name__ == "__main__":
    unittest.main()
