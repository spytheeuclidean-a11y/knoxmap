"""Petrol station forecourts: pumps on islands, set well back from the shop."""
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from generator import pz_colors as C
from knoxbuild import pumps
from knoxbuild.bitmaps import read_rgb


def forecourt(mpt, side="S", w=18, h=8, size=(120, 90), at=(50, 20)):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "buildings"))
    ground = np.zeros((size[1], size[0], 3), np.uint8)
    ground[:] = C.MEDIUM_GRASS
    ground[size[1] - 6:] = C.MEDIUM_ASPHALT          # a street along the bottom
    Image.fromarray(ground).save(os.path.join(d, "m.bmp"), format="BMP")
    occupied = np.zeros((size[1], size[0]), bool)
    x0, y0 = at
    occupied[y0:y0 + h, x0:x0 + w] = True
    placements, count = pumps.place_pumps(
        d, "m", os.path.join(d, "buildings"), occupied, [(x0, y0, w, h, side)], [],
        metres_per_tile=mpt)
    return read_rgb(os.path.join(d, "m.bmp")), count, placements, (x0, y0, w, h)


class Forecourt(unittest.TestCase):
    def test_islands_stand_off_the_shop(self):
        for mpt in (1.0, 2.0):
            ground, count, placements, (x0, y0, w, h) = forecourt(mpt)
            self.assertGreaterEqual(count, 2)
            rows = np.where((ground == np.array(C.PALE_CONCRETE)).all(axis=2).any(axis=1))[0]
            front = y0 + h + 1                        # the shop's pavement row
            island_rows = [r for r in rows if r > front + 1 and r < 80]
            self.assertTrue(island_rows, "no island was drawn")
            nearest = (min(island_rows) - (y0 + h)) * mpt
            self.assertGreaterEqual(nearest, pumps.PUMP_SETBACK_M - mpt, f"mpt {mpt}")

    def test_the_shop_front_is_paved(self):
        ground, _count, _p, (x0, y0, w, h) = forecourt(2.0)
        row = ground[y0 + h + 1, x0:x0 + w]
        self.assertTrue((row == np.array(C.PALE_CONCRETE)).all(axis=1).sum() >= w // 2)

    def test_each_island_has_a_roof_on_posts(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "buildings"))
        ground = np.zeros((90, 120, 3), np.uint8)
        ground[:] = C.MEDIUM_GRASS
        Image.fromarray(ground).save(os.path.join(d, "m.bmp"), format="BMP")
        occupied = np.zeros((90, 120), bool)
        occupied[20:28, 50:68] = True
        pumps.place_pumps(d, "m", os.path.join(d, "buildings"), occupied,
                          [(50, 20, 18, 8, "S")], [], metres_per_tile=2.0)
        text = "".join(open(os.path.join(d, "buildings", f), encoding="utf-8").read()
                       for f in os.listdir(os.path.join(d, "buildings")))
        kit = [pumps.CANOPY[b] for b in pumps.CANOPY if pumps.CANOPY[b]["pillar"][0] in text][0]
        self.assertIn(kit["edge"], text)
        self.assertIn(kit["fascia_n"], text)
        self.assertEqual(text.count("<floor>"), 3)        # the roof is two floors up

    def test_a_mapped_canopy_gets_its_roof(self):
        # A canopy OpenStreetMap draws, a little askew on a turned map: pumps
        # under it, a roof over them, and the forecourt one rectangle of
        # tarmac rather than the outline's jagged inside.
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "buildings"))
        ground = np.zeros((90, 120, 3), np.uint8)
        ground[:] = C.MEDIUM_GRASS
        Image.fromarray(ground).save(os.path.join(d, "m.bmp"), format="BMP")
        outline = [(40.0, 30.0), (64.0, 31.0), (63.6, 41.0), (39.6, 40.0)]
        _p, count = pumps.place_pumps(d, "m", os.path.join(d, "buildings"),
                                      np.zeros((90, 120), bool), [], [],
                                      canopies=[outline], metres_per_tile=1.0)
        self.assertGreaterEqual(count, 2)
        text = "".join(open(os.path.join(d, "buildings", f), encoding="utf-8").read()
                       for f in os.listdir(os.path.join(d, "buildings")))
        self.assertTrue(any(pumps.CANOPY[b]["pillar"][0] in text for b in pumps.CANOPY))
        self.assertEqual(text.count("<floor>"), 3)
        g = read_rgb(os.path.join(d, "m.bmp"))
        box = g[30:41, 40:64]
        paved = ((box == np.array(C.DARK_ASPHALT)).all(axis=2)
                 | (box == np.array(C.PALE_CONCRETE)).all(axis=2))
        self.assertTrue(paved.all())

    def test_canopy_is_built_as_the_muldraugh_station(self):
        # The game's own Fossoil station (Muldraugh, cell 41,38): islands at
        # x 117-125 on rows 32 and 39, read back from its lot files.
        tiles = pumps.canopy_tiles([(117, 32, 125, 32), (117, 39, 125, 39)], "fossoil",
                                   lambda x, y: True)
        at = {}
        for x, y, z, _layer, tile in tiles:
            at.setdefault((x, y, z), set()).add(tile)
        f = "location_shop_fossoil_01_"
        roof = {(x, y) for (x, y, z) in at if z == 2}
        self.assertEqual(roof, {(x, y) for x in range(116, 129) for y in range(30, 42)})
        self.assertEqual(at[(116, 30, 2)], {f + "38"})
        self.assertEqual(at[(120, 35, 2)], {f + "39"})
        for px, py in ((116, 32), (126, 32), (116, 39), (126, 39)):
            for z in (0, 1):
                self.assertEqual(at[(px, py, z)], {f + "4"})
                self.assertEqual(at[(px + 1, py, z)], {f + "6"})
                self.assertEqual(at[(px, py + 1, z)], {f + "5"})
                self.assertEqual(at[(px + 1, py + 1, z)], {f + "7"})
        self.assertEqual({(x, y) for (x, y, z), t in at.items() if z == 1 and f + "40" in t},
                         {(x, 42) for x in range(116, 129)})
        self.assertEqual({(x, y) for (x, y, z), t in at.items() if z == 1 and f + "41" in t},
                         {(129, y) for y in range(30, 42)})
        self.assertEqual(at[(129, 42, 1)], {f + "42"})

    def test_deep_forecourt_gets_two_islands(self):
        for mpt in (1.0, 2.0):
            rows = pumps.island_rows(pumps.full_depth(mpt), mpt)
            self.assertEqual(len(rows), 2)
            self.assertGreaterEqual(rows[1] - rows[0], pumps.MIN_LANE_TILES)
        self.assertEqual(len(pumps.island_rows(5, 2.0)), 1)


if __name__ == "__main__":
    unittest.main()
