import os
import re
import unittest
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

from generator import pz_colors as C
from knoxbuild.props import (BARRICADE_X, BARRICADE_Y, CRATES, DRUMS,
                             place_vignettes)


def _map(directory, name="town", width=200, height=200, roads=()):
    """A ground bitmap with the given (x0, y0, x1, y1) rectangles of tarmac."""
    ground = Image.new("RGB", (width, height), C.MEDIUM_GRASS)
    pixels = ground.load()
    for x0, y0, x1, y1 in roads:
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                pixels[x, y] = C.MEDIUM_ASPHALT
    ground.save(os.path.join(directory, f"{name}.bmp"))
    return ground


def _lots(bdir):
    """(x, y, tile) from every vignette lot, and the lot file names."""
    names = sorted(n for n in os.listdir(bdir) if "_vignettes_" in n)
    out = []
    for name in names:
        text = open(os.path.join(bdir, name), encoding="utf-8").read()
        tiles = re.findall(r'<tile tile="([^"]+)"',
                           text.split("<user_tiles>")[1].split("</user_tiles>")[0])
        for floor in re.findall(r"<floor>(.*?)</floor>", text, re.S):
            for layer, body in re.findall(r'<tiles layer="([^"]+)">(.*?)</tiles>',
                                          floor, re.S):
                for y, row in enumerate(body.strip().splitlines()):
                    for x, value in enumerate(row.strip().rstrip(",").split(",")):
                        if value.strip() not in ("", "0"):
                            out.append((x, y, tiles[int(value) - 1], layer))
    return out, names


class Vignettes(unittest.TestCase):
    def _place(self, directory, roads, rows=(), hierarchy=None, width=200, height=200):
        bdir = os.path.join(directory, "buildings")
        os.mkdir(bdir)
        _map(directory, roads=roads, width=width, height=height)
        occupied = np.zeros((height, width), dtype=bool)
        placements, counts = place_vignettes(
            directory, "town", bdir, occupied, list(rows),
            road_hierarchy=hierarchy, seed=7)
        return occupied, placements, counts, bdir

    def test_a_road_out_of_town_is_blocked_across_it(self):
        with TemporaryDirectory() as directory:
            occupied, _p, counts, bdir = self._place(directory, [(100, 0, 103, 199)])
            tiles, names = _lots(bdir)

            self.assertEqual(counts["checkpoints"], 2)
            self.assertTrue(names)
            barricades = [(x, y, t) for x, y, t, _l in tiles if t in BARRICADE_X]
            # Across a road that runs north-south: each checkpoint is one row of
            # segments four squares wide.
            rows: dict = {}
            for x, y, _t in barricades:
                rows.setdefault(y, set()).add(x)
            self.assertEqual(sorted(len(r) for r in rows.values()), [4, 4])
            # And on the tarmac, which is what a roadblock is for.
            self.assertTrue(occupied[:, 100:104].sum() >= 8)
            self.assertEqual(int(occupied[:, :100].sum()), 0)
            self.assertEqual(int(occupied[:, 104:].sum()), 0)

    def test_a_narrow_carriageway_gets_crates_not_half_a_barricade(self):
        with TemporaryDirectory() as directory:
            _o, _p, counts, bdir = self._place(directory, [(100, 0, 101, 199)])
            tiles, _names = _lots(bdir)

            self.assertEqual(counts["checkpoints"], 2)
            self.assertFalse([t for _x, _y, t, _l in tiles if t in BARRICADE_X + BARRICADE_Y])
            self.assertTrue([t for _x, _y, t, _l in tiles if t in CRATES])

    def test_a_main_road_is_stopped_away_from_the_edge(self):
        with TemporaryDirectory() as directory:
            hierarchy = np.zeros((200, 200), dtype=np.uint8)
            hierarchy[90:94, 40:161] = 6
            _o, _p, counts, bdir = self._place(
                directory, [(40, 90, 160, 93)], hierarchy=hierarchy)
            tiles, _names = _lots(bdir)

            # Blocks every ROAD_BLOCK_SPACING tiles along the road, and one
            # checkpoint where the road runs out - the way out of town.
            self.assertGreaterEqual(counts["road_blocks"], 2)
            self.assertEqual(counts["checkpoints"], 1)
            barricades = [(x, y, t) for x, y, t, _l in tiles if t in BARRICADE_Y]
            # The road runs east-west, so every barrier is a column four deep.
            columns: dict = {}
            for x, y, _t in barricades:
                columns.setdefault(x, set()).add(y)
            self.assertGreaterEqual(len(columns), 3)
            self.assertTrue(all(len(c) == 4 for c in columns.values()))

    def test_a_side_street_is_not_a_roadblock(self):
        with TemporaryDirectory() as directory:
            hierarchy = np.zeros((200, 200), dtype=np.uint8)
            hierarchy[90:94, 20:181] = 3          # residential: not a main road
            _o, _p, counts, _b = self._place(
                directory, [(20, 90, 180, 93)], hierarchy=hierarchy)

            self.assertEqual(counts["road_blocks"], 0)

    def test_a_road_that_stops_short_of_the_border_is_still_the_way_out(self):
        # A map padded past the town: the roads end well inside the bitmap, and
        # the outermost end is the last tarmac before the trees.
        with TemporaryDirectory() as directory:
            _o, _p, counts, bdir = self._place(directory, [(60, 90, 140, 93)])
            tiles, _names = _lots(bdir)

            self.assertEqual(counts["checkpoints"], 1)
            self.assertTrue([t for _x, _y, t, _l in tiles if t in BARRICADE_Y])

    def test_a_school_yard_becomes_an_evacuation_centre(self):
        school = {"kind": "school", "tile_x": 80, "tile_y": 80, "width": 10, "height": 8}
        with TemporaryDirectory() as directory:
            _o, placements, counts, bdir = self._place(directory, [], rows=[school])
            tiles, _names = _lots(bdir)

            self.assertEqual(counts["evac_centres"], 1)
            self.assertEqual(counts["vignette_props"], 4)
            self.assertTrue(placements)
            self.assertTrue(all(t in CRATES + DRUMS for _x, _y, t, _l in tiles))
            # Around the building, never inside its outline.
            self.assertTrue(tiles)

    def test_a_house_is_not_a_scene(self):
        house = {"kind": "house", "tile_x": 80, "tile_y": 80, "width": 10, "height": 8}
        with TemporaryDirectory() as directory:
            _o, placements, counts, _b = self._place(directory, [], rows=[house])

            self.assertEqual(placements, [])
            self.assertEqual(counts["vignette_props"], 0)

    def test_nothing_is_put_where_something_stands(self):
        school = {"kind": "school", "tile_x": 80, "tile_y": 80, "width": 10, "height": 8}
        with TemporaryDirectory() as directory:
            bdir = os.path.join(directory, "buildings")
            os.mkdir(bdir)
            _map(directory)
            occupied = np.ones((200, 200), dtype=bool)
            placements, counts = place_vignettes(
                directory, "town", bdir, occupied, [school], seed=7)

            self.assertEqual(placements, [])
            self.assertEqual(counts["vignette_props"], 0)
