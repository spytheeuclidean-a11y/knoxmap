"""British garden boundaries: close-board fences behind, a low front
boundary with the path and drive left open (docs/REGIONAL_PROFILES.md, GB
step 7)."""
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from generator import pz_colors as C
from knoxbuild.yards import GB_FRONT_STYLES, paint_paths, yard_plan

SIZE = 6


def _building(folder, name):
    """A 6 x 6 house with its front door in the south wall."""
    rows = "\n".join(",".join(["1"] * SIZE) for _ in range(SIZE))
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        f.write(f'<building><floor><rooms>\n{rows}\n</rooms>'
                f'<object type="door" x="3" y="6" dir="N"/></floor></building>')


def street(region, n_houses=8, alley=False):
    """Detached houses at y 14-19 fronting a pavement at y 28, with a back
    alley paved along y 4-5 behind their gardens when `alley`; return
    (fences, ground after painting, vegetation after painting)."""
    with tempfile.TemporaryDirectory() as out:
        os.mkdir(os.path.join(out, "buildings"))
        width = 13 * n_houses + 6
        occupied = np.zeros((40, width), dtype=bool)
        ground = np.full((40, width, 3), C.MEDIUM_GRASS, dtype=np.uint8)
        ground[28:32, :] = C.PALE_CONCRETE
        ground[32:36, :] = C.MEDIUM_ASPHALT
        if alley:
            ground[4:6, :] = C.DARK_ASPHALT
        veg = np.full((40, width, 3), C.VEG_NOTHING, dtype=np.uint8)
        Image.fromarray(ground, "RGB").save(os.path.join(out, "m.bmp"))
        Image.fromarray(veg, "RGB").save(os.path.join(out, "m_veg.bmp"))
        rows = []
        for n in range(n_houses):
            bx = 4 + 13 * n
            _building(os.path.join(out, "buildings"), f"h{n}.tbx")
            occupied[14:20, bx:bx + SIZE] = True
            rows.append({"kind": "house", "file": f"h{n}.tbx", "tile_x": bx,
                         "tile_y": 14, "width": SIZE, "height": SIZE})
        _paths, fences = paint_paths(out, "m", rows, occupied, region=region)
        painted = np.asarray(Image.open(os.path.join(out, "m.bmp")))[:, :, :3].copy()
        planted = np.asarray(Image.open(os.path.join(out, "m_veg.bmp")))[:, :, :3].copy()
    return fences, painted, planted


def longest_hedge(planted, row=27):
    """The longest unbroken stretch of bushes along the pavement edge: a
    shrub bed by the door is a tile or two, a hedge runs the garden's width."""
    best = cur = 0
    for bush in (planted[row] == C.BUSHES).all(axis=1):
        cur = cur + 1 if bush else 0
        best = max(best, cur)
    return best


def front_runs(fences):
    """Fence runs along the pavement edge (y = 28)."""
    return [f for f in fences if all(y == 28 for _x, y in f[0])]


class BackFences(unittest.TestCase):
    def test_british_back_gardens_are_wooden(self):
        plans = [yard_plan(6 + 10 * n, 6 + 7 * n, region="gb") for n in range(200)]
        styles = [p[0] for p in plans]
        self.assertTrue(set(styles) <= {"tall_wooden", "short_wooden"}, set(styles))
        self.assertGreater(styles.count("tall_wooden") / len(styles), 0.6)
        self.assertGreater(sum(p[1] for p in plans) / len(plans), 0.9)

    def test_default_back_gardens_are_unchanged(self):
        self.assertEqual(yard_plan(42, 17), yard_plan(42, 17, region=None))


def back_gates(fences):
    """Gates in back fences, past the back wall at y 13: (x, y) tiles."""
    return [g for f in fences for g in (f[2] if len(f) > 2 else ()) if g[1] < 13]


def gate_tiles_built(fences, width=110):
    """Tiles where build_fences put a gate, for these yard fences."""
    from types import SimpleNamespace
    from xml.etree import ElementTree

    from knoxbuild.fences import GATES, build_fences
    gate_names = {t for pair in GATES.values() for t in pair}
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, "buildings"))
        proj = SimpleNamespace(width=width, height=40, to_px=lambda lat, lon: (lon, lat))
        placements, _ = build_fences(d, "m", proj, np.zeros((40, width), dtype=bool),
                                     None, os.path.join(d, "buildings"), extra=fences)
        found = set()
        for p in placements:
            root = ElementTree.parse(os.path.join(d, p.tbx_path))
            names = [f.find("entry/tile").get("name") for f in root.findall(".//furniture")]
            for obj in root.findall(".//floor/object"):
                if names[int(obj.get("FurnitureTiles"))] in gate_names:
                    found.add((p.tile_x + int(obj.get("x")), p.tile_y + int(obj.get("y"))))
    return found


class AlleyGates(unittest.TestCase):
    def test_a_garden_on_a_back_alley_has_a_gate_onto_it(self):
        fences = street("gb", alley=True)[0]
        gates = back_gates(fences)
        self.assertTrue(gates)
        # In the fence along the alley's edge, the far side of row y = 6.
        self.assertEqual({y for _x, y in gates}, {6})
        # ...and the fence builder hangs a gate there, not a fence panel.
        self.assertEqual(gate_tiles_built(fences), set(gates))

    def test_no_gate_without_an_alley_or_outside_britain(self):
        self.assertEqual(back_gates(street("gb")[0]), [])
        self.assertEqual(back_gates(street(None, alley=True)[0]), [])


class FrontBoundaries(unittest.TestCase):
    def test_british_front_gardens_get_a_low_boundary(self):
        runs = front_runs(street("gb")[0])
        self.assertTrue(runs)
        self.assertTrue({r[1] for r in runs} <= set(GB_FRONT_STYLES))

    def test_the_path_and_the_drive_are_left_open(self):
        fences, painted, _planted = street("gb")
        open_row = painted[27]
        for pts, _style, *_ in front_runs(fences):
            xs = sorted(x for x, _ in pts)
            for x in range(xs[0], xs[-1]):
                self.assertTrue((open_row[x] == C.MEDIUM_GRASS).all(),
                                f"front fence across paving at x={x}")

    def test_some_front_gardens_are_hedged(self):
        _fences, painted, planted = street("gb", 20)
        self.assertGreaterEqual(longest_hedge(planted), 5)
        # Along the pavement edge on lawn, never across the path or the drive.
        hedge = (planted[27] == C.BUSHES).all(axis=1)
        self.assertTrue((painted[27][hedge] == C.MEDIUM_GRASS).all())

    def test_no_front_boundary_elsewhere(self):
        fences, _painted, planted = street(None)
        self.assertEqual(front_runs(fences), [])
        self.assertLess(longest_hedge(planted), 5)


if __name__ == "__main__":
    unittest.main()
