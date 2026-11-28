import os
import unittest
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

from generator import pz_colors as C
from knoxbuild import catalog, layout
from knoxbuild.layout import openings
from knoxbuild.yards import paint_paths

SIZES = ((12, 10, 1), (16, 12, 2), (20, 14, 2), (24, 16, 2))


def houses(**kw):
    for seed in range(60):
        for w, h, levels in SIZES:
            yield seed, w, h, layout.build_building(width=w, height=h, seed=seed, levels=levels,
                                                     street="S", **kw).storeys[0]


class Garages(unittest.TestCase):
    def test_about_a_third_of_houses_have_one(self):
        total = with_garage = 0
        for _seed, _w, _h, st in houses():
            total += 1
            with_garage += any(r.kind == "garage" for r in st.rooms)
        # The bay is kept before the floor is cut (openings._garage_bay):
        # waiting for a room big enough gave about one house in seven.
        self.assertGreater(with_garage / total, 0.3)
        self.assertLess(with_garage / total, 0.5)

    def test_the_garage_door_is_three_tiles_on_the_street_and_not_the_front_door(self):
        seen = 0
        for _seed, w, h, st in houses():
            garage = [i for i, r in enumerate(st.rooms, 1) if r.kind == "garage"]
            if not garage:
                self.assertFalse(getattr(st, "garage_door_tiles", ()))
                continue
            seen += 1
            tiles = list(st.garage_door_tiles)
            self.assertEqual(len(tiles), 3)
            # on the street (south) wall, in a row, all on the garage room
            self.assertTrue(all(d == "N" and y == h for _x, y, d in tiles) or
                            all(d == "N" and y == h for _x, y, d in tiles[:1]))
            xs = sorted(x for x, _y, _d in tiles)
            self.assertEqual(xs, list(range(xs[0], xs[0] + 3)))
            self.assertTrue(all(st.grid[y - 1][x] in garage for x, y, _d in tiles))
            g = garage[0]
            cells = [(x, y) for y in range(h) for x in range(w) if st.grid[y][x] == g]
            gxs = [x for x, _ in cells]
            gys = [y for _, y in cells]
            self.assertGreaterEqual(max(gxs) - min(gxs) + 1, 5)
            self.assertGreaterEqual(max(gys) - min(gys) + 1, 5)
            # the house still has a door that is not the garage's
            self.assertTrue([d for d in st.doors if d not in tiles])
        self.assertGreater(seen, 20)

    def test_detached_garages_are_at_least_5x5(self):
        for w, h in ((4, 4), (4, 5), (5, 4), (6, 4), (6, 6)):
            b = layout.build_building(width=w, height=h, seed=1, levels=1, kind="garage", street="S")
            st = b.storeys[0]
            self.assertGreaterEqual(len(st.grid[0]), 5)
            self.assertGreaterEqual(len(st.grid), 5)
            self.assertEqual(min(len(st.grid[0]), len(st.grid)) % 2, 1)

    def test_a_garage_is_not_a_way_through_and_the_house_joins_up(self):
        for _seed, _w, _h, st in houses():
            garage = [i for i, r in enumerate(st.rooms, 1) if r.kind == "garage"]
            for g in garage:
                class P:  # the plan as _rooms_joined_without reads it
                    rooms, doors, grid = st.rooms, st.doors, st.grid
                    width, height = len(st.grid[0]), len(st.grid)
                self.assertTrue(openings._rooms_joined_without(P, g))

    def test_no_garage_without_a_street_and_none_in_a_tiny_house(self):
        for seed in range(40):
            b = layout.build_building(width=12, height=10, seed=seed, levels=1, street=None)
            self.assertFalse(any(r.kind == "garage" for r in b.storeys[0].rooms))
            b = layout.build_building(width=7, height=7, seed=seed, levels=1, street="S")
            self.assertFalse(any(r.kind == "garage" for r in b.storeys[0].rooms))

    def test_shops_and_flats_get_none(self):
        for seed in range(30):
            for kind in ("shop", "apartment"):
                b = layout.build_building(width=20, height=14, seed=seed, levels=2, kind=kind,
                                          street="S", commercial=kind == "shop")
                self.assertFalse(any(r.kind == "garage" for r in b.storeys[0].rooms))

    def test_it_is_the_same_every_time(self):
        a = [(r.kind, r.x0, r.y0) for _s, _w, _h, st in houses() for r in st.rooms]
        b = [(r.kind, r.x0, r.y0) for _s, _w, _h, st in houses() for r in st.rooms]
        self.assertEqual(a, b)


class Drive(unittest.TestCase):
    def test_a_house_drive_starts_at_its_garage_door_not_its_front_door(self):
        with TemporaryDirectory() as directory:
            os.mkdir(os.path.join(directory, "buildings"))
            ground = Image.new("RGB", (40, 30), C.DARK_GRASS)
            for x in range(40):
                ground.putpixel((x, 15), C.MEDIUM_ASPHALT)
            ground.save(os.path.join(directory, "map.bmp"))
            grid = "\n".join(",".join(["1"] * 8) for _ in range(8))
            mid = catalog.GARAGE_DOOR[1]
            with open(os.path.join(directory, "buildings", "house.tbx"), "w", encoding="utf-8") as f:
                # the front door on the north wall; the garage door on the west
                f.write(f'<floor><rooms>{grid}</rooms>'
                        '<object type="door" FrameTile="3" x="4" y="0" dir="N" Tile="2"/>'
                        f'<object type="door" FrameTile="0" x="0" y="3" dir="W" Tile="{mid}"/>'
                        '</floor>')
            occupied = np.zeros((30, 40), dtype=bool)
            occupied[10:18, 10:18] = True
            rows = [{"file": "house.tbx", "building": "house", "kind": "house",
                     "tile_x": 10, "tile_y": 10, "width": 8, "height": 8}]
            paint_paths(directory, "map", rows, occupied)
            with Image.open(os.path.join(directory, "map.bmp")) as result:
                # tarmac in front of the garage door (west side), as for a garage
                self.assertEqual(result.getpixel((9, 13)), C.DARK_ASPHALT)

    def test_a_house_without_a_garage_door_gets_no_drive(self):
        with TemporaryDirectory() as directory:
            os.mkdir(os.path.join(directory, "buildings"))
            ground = Image.new("RGB", (40, 30), C.DARK_GRASS)
            for x in range(40):
                ground.putpixel((x, 15), C.MEDIUM_ASPHALT)
            ground.save(os.path.join(directory, "map.bmp"))
            grid = "\n".join(",".join(["1"] * 8) for _ in range(8))
            with open(os.path.join(directory, "buildings", "house.tbx"), "w", encoding="utf-8") as f:
                f.write(f'<floor><rooms>{grid}</rooms>'
                        '<object type="door" FrameTile="3" x="0" y="3" dir="W" Tile="2"/></floor>')
            occupied = np.zeros((30, 40), dtype=bool)
            occupied[10:18, 10:18] = True
            paint_paths(directory, "map", [{"file": "house.tbx", "building": "house", "kind": "house",
                                            "tile_x": 10, "tile_y": 10, "width": 8, "height": 8}], occupied)
            with Image.open(os.path.join(directory, "map.bmp")) as result:
                self.assertNotEqual(result.getpixel((9, 13)), C.DARK_ASPHALT)


if __name__ == "__main__":
    unittest.main()
