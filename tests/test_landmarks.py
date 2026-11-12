import os
import re
import tempfile
import unittest

import numpy as np
from PIL import Image
from shapely.geometry import box

from generator import pz_colors as C
from generator.structures import PLINTH, Plan, _tower, tower_kind
from knoxbuild import landmarks


def read_tbx(path):
    """(x, y, level, layer, tile) from a tile-only lot, as the editor reads it."""
    text = open(path, encoding="utf-8").read()
    names = re.findall(r'<tile tile="([^"]+)"',
                       text.split("<user_tiles>")[1].split("</user_tiles>")[0])
    out = []
    for z, floor in enumerate(re.findall(r"<floor>(.*?)</floor>", text, re.S)):
        for layer, body in re.findall(r'<tiles layer="([^"]+)">(.*?)</tiles>', floor, re.S):
            for y, row in enumerate(body.strip().splitlines()):
                for x, value in enumerate(row.strip().rstrip(",").split(",")):
                    if value.strip() not in ("", "0"):
                        out.append((x, y, z, layer, names[int(value) - 1]))
    return out


def silhouette(tags, size=(6, 6)):
    plan = Plan()
    _tower(plan, box(0, 0, size[0], size[1]), tags)
    return plan.tiles


class Kinds(unittest.TestCase):
    def test_a_silo_is_a_silo_however_it_is_mapped(self):
        self.assertEqual(tower_kind({"man_made": "silo"}), "silo")
        self.assertEqual(tower_kind({"building": "silo"}), "silo")
        self.assertEqual(tower_kind({"building": "grain_elevator"}), "silo")

    def test_a_transmission_tower_is_not_a_building(self):
        self.assertEqual(tower_kind({"power": "tower"}), "pylon")
        self.assertIsNone(tower_kind({"power": "pole"}))

    def test_a_bell_tower_is_a_steeple(self):
        self.assertEqual(tower_kind({"man_made": "tower",
                                     "tower:type": "bell_tower"}), "steeple")
        self.assertEqual(tower_kind({"man_made": "tower",
                                     "tower:type": "campanile"}), "steeple")
        self.assertEqual(tower_kind({"man_made": "tower",
                                     "tower:type": "clock"}), "tower")

    def test_a_phone_mast_is_still_not_a_landmark(self):
        self.assertIsNone(tower_kind({"man_made": "tower",
                                      "tower:type": "communication"}))


class Silhouettes(unittest.TestCase):
    def test_a_silo_is_a_drum_with_a_domed_cap(self):
        tiles = silhouette({"man_made": "silo"})
        top = max(z for _x, _y, z, _layer in tiles)
        body = {(x, y) for x, y, z, _layer in tiles if z == top - 1}
        cap = {(x, y) for x, y, z, _layer in tiles if z == top}
        self.assertEqual(len(cap), 1, "the cap of a silo is one square")
        self.assertEqual(len(body), 36, "the body is the whole footprint, all the way up")
        self.assertEqual(tiles[(next(iter(cap))[0], next(iter(cap))[1], top, "Floor")],
                         PLINTH)

    def test_a_steeple_comes_to_a_point(self):
        tiles = silhouette({"man_made": "tower", "tower:type": "bell_tower"}, (3, 3))
        top = max(z for _x, _y, z, _layer in tiles)
        base = {(x, y) for x, y, z, _layer in tiles if z == 0}
        shaft = {(x, y) for x, y, z, _layer in tiles if z == top - 1}
        point = {(x, y) for x, y, z, _layer in tiles if z == top}
        self.assertEqual(len(base), 9, "the shaft stands on the whole footprint")
        self.assertEqual(len(shaft), 1, "and narrows to a needle under the point")
        self.assertEqual(len(point), 1)
        self.assertEqual(tiles[(next(iter(point))[0], next(iter(point))[1], top, "Floor")],
                         PLINTH)

    def test_a_transmission_tower_is_a_mast_with_arms(self):
        tiles = silhouette({"power": "tower"}, (3, 3))
        column = {(x, y) for x, y, z, layer in tiles if layer == "Floor"}
        arms = {z for _x, _y, z, layer in tiles if layer == "Furniture"}
        self.assertEqual(column, {(1, 1)}, "one square from the ground to the top")
        self.assertEqual(len(arms), 2, "two pairs of arms")
        top = max(z for _x, _y, z, _layer in tiles)
        self.assertTrue(all(z >= top - 2 for z in arms))

    def test_a_water_tower_keeps_its_legs(self):
        tiles = silhouette({"man_made": "water_tower"}, (6, 6))
        base = {(x, y) for x, y, z, _layer in tiles if z == 0}
        top = max(z for _x, _y, z, _layer in tiles)
        tank = {(x, y) for x, y, z, _layer in tiles if z == top}
        self.assertLess(len(base), len(tank), "the tank is wider than the legs")
        self.assertEqual(len(base), 9, "the legs are narrow, not the whole footprint")


def write_map(tmp, width=40, height=40, road=None):
    """A small map with a building on it and, optionally, a road along a row."""
    ground = np.zeros((height, width, 3), np.uint8)
    ground[:] = C.SHORT_GRASS
    if road is not None:
        ground[road, :] = C.MEDIUM_ASPHALT
    Image.fromarray(ground).save(os.path.join(tmp, "t.bmp"), format="BMP")
    veg = np.zeros((height, width, 3), np.uint8)
    veg[:] = C.VEG_NOTHING
    Image.fromarray(veg).save(os.path.join(tmp, "t_veg.bmp"), format="BMP")
    occupied = np.zeros((height, width), bool)
    occupied[5:12, 5:15] = True
    return occupied


def tiles_of(tmp, placements):
    """The tiles of the landmark lots, in the map's own coordinates."""
    out = []
    for p in placements:
        for x, y, z, layer, tile in read_tbx(os.path.join(tmp, os.path.basename(p.tbx_path))):
            out.append((x + p.tile_x, y + p.tile_y, z, layer, tile))
    return out


class Placement(unittest.TestCase):
    def test_a_church_gets_a_steeple_beside_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            occupied = write_map(tmp)
            rows = [{"tile_x": 5, "tile_y": 5, "width": 10, "height": 7,
                     "levels": 1, "kind": "church"}]
            placements, counts = landmarks.place_landmarks(tmp, "t", tmp, occupied, rows, [])
            self.assertEqual(counts["steeples"], 1)
            tiles = tiles_of(tmp, placements)
            columns = {(x, y) for x, y, _z, _layer, _tile in tiles}
            self.assertEqual(len(columns), 1, "one square on the ground")
            levels = sorted(z for _x, _y, z, _layer, _tile in tiles)
            self.assertEqual(levels, list(range(len(levels))), "no storey missing")
            self.assertGreaterEqual(len(levels), 5)
            self.assertEqual(tiles[-1][4], PLINTH, "the finial")

    def test_a_sign_stands_runs_along_the_road(self):
        with tempfile.TemporaryDirectory() as tmp:
            occupied = write_map(tmp, road=13)
            businesses = [(6, 5, 14, 11, "motel")]
            placements, counts = landmarks.place_landmarks(tmp, "t", tmp, occupied,
                                                           [], businesses)
            self.assertEqual(counts["signs"], 1)
            self.assertEqual(counts["motel_signs"], 1)
            tiles = tiles_of(tmp, placements)
            panel = [t for t in tiles if t[3] == landmarks.PANEL_LAYER]
            post = [t for t in tiles if t[3] == landmarks.POST_LAYER]
            self.assertEqual(len(panel), 4, "a whole signboard, not a piece of one")
            self.assertEqual(len({(x, y) for x, y, _z, _layer, _t in post}), 1)
            self.assertEqual({z for _x, _y, z, _layer, _t in post},
                             set(range(landmarks.SIGN_POST["motel"] + 1)))
            self.assertEqual({t for _x, _y, _z, _layer, t in post}, {landmarks.SIGN_POLE},
                             "a post, not a pier of concrete")
            # Lying along the road, one row up from it, so the board is read
            # from the street and not from the back of the lot.
            self.assertEqual({y for _x, y, _z, _layer, _t in panel}, {12})

    def test_one_board_per_business_mapped_twice(self):
        # A motel is often an outline with a point inside it: two targets, one
        # motel, one board in front of it.
        with tempfile.TemporaryDirectory() as tmp:
            occupied = write_map(tmp, road=13)
            businesses = [(6, 5, 14, 11, "motel"), (8, 6, 12, 10, "motel")]
            _placements, counts = landmarks.place_landmarks(tmp, "t", tmp, occupied,
                                                            [], businesses)
            self.assertEqual(counts["signs"], 1)

    def test_two_motels_get_two_boards(self):
        with tempfile.TemporaryDirectory() as tmp:
            occupied = write_map(tmp, width=80, road=13)
            businesses = [(2, 5, 8, 11, "motel"), (30, 5, 36, 11, "motel")]
            _placements, counts = landmarks.place_landmarks(tmp, "t", tmp, occupied,
                                                            [], businesses,
                                                            metres_per_tile=2.0)
            self.assertEqual(counts["signs"], 2)

    def test_only_one_picture_signboards_are_used(self):
        # Four posters on one post read as a rack; a board that is one picture
        # across its four tiles reads as a billboard.
        poster_strips = {"walls_decoration_03_000", "walls_decoration_03_032",
                         "walls_decoration_03_128", "walls_decoration_03_160"}
        for direction, strips in landmarks.BOARD_STRIPS.items():
            self.assertTrue(strips)
            for strip in strips:
                with self.subTest(direction=direction, strip=strip[0]):
                    self.assertEqual(len(strip), 4)
                    self.assertTrue(all(t.startswith("walls_decoration_03_") for t in strip))
                    self.assertFalse(poster_strips & set(strip))
        self.assertEqual(landmarks.BOARD_STRIPS["N"][0][0], "walls_decoration_03_064")

    def test_an_ordinary_cinema_gets_no_board(self):
        self.assertIsNone(landmarks.sign_for({"amenity": "cinema"}))
        self.assertIsNone(landmarks.sign_for({"amenity": "cinema", "drive_in": "no"}))
        self.assertEqual(landmarks.sign_for({"amenity": "cinema", "drive_in": "yes"}),
                         "drive-in")
        self.assertEqual(landmarks.sign_for({"tourism": "motel"}), "motel")
        self.assertIsNone(landmarks.sign_for({"tourism": "hotel"}))

    def test_without_a_road_the_board_stays_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            occupied = write_map(tmp)          # no road anywhere
            businesses = [(16, 16, 24, 24, "motel")]
            placements, counts = landmarks.place_landmarks(tmp, "t", tmp, occupied,
                                                            [], businesses)
            self.assertEqual(counts["signs"], 1)
            cells = [(x, y) for x, y, _z, _layer, _t in tiles_of(tmp, placements)]
            # Against the edge of the business, not at the far end of the block.
            nearest = min(max(16 - x, x - 24, 16 - y, y - 24) for x, y in cells)
            self.assertLessEqual(nearest, 1)

    def test_a_drive_in_sign_stands_taller(self):
        with tempfile.TemporaryDirectory() as tmp:
            occupied = write_map(tmp, road=13)
            businesses = [(6, 5, 14, 11, "drive-in")]
            _placements, counts = landmarks.place_landmarks(tmp, "t", tmp, occupied,
                                                            [], businesses)
            self.assertEqual(counts["drive_in_signs"], 1)

    def test_no_room_no_landmark(self):
        with tempfile.TemporaryDirectory() as tmp:
            occupied = write_map(tmp)
            occupied[:] = True
            rows = [{"tile_x": 5, "tile_y": 5, "width": 10, "height": 7,
                     "levels": 1, "kind": "church"}]
            businesses = [(6, 5, 14, 11, "motel")]
            placements, counts = landmarks.place_landmarks(tmp, "t", tmp, occupied,
                                                           rows, businesses)
            self.assertEqual(placements, [])
            self.assertEqual(counts["steeples"], 0)
            self.assertEqual(counts["signs"], 0)

    def test_an_ordinary_house_gets_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            occupied = write_map(tmp)
            rows = [{"tile_x": 5, "tile_y": 5, "width": 10, "height": 7,
                     "levels": 1, "kind": "house"}]
            _placements, counts = landmarks.place_landmarks(tmp, "t", tmp, occupied,
                                                            rows, [])
            self.assertEqual(sum(counts.values()), 0)


if __name__ == "__main__":
    unittest.main()
