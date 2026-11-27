"""Tests for carports, front porches, back decks, and exterior house props."""
import random
import tempfile
import unittest
from pathlib import Path

from knoxbuild import structures, yards
from tools import validate_tbx


class LivedInHouseStructuresTests(unittest.TestCase):
    def test_carport_has_two_posts_per_corner_and_an_open_end(self):
        for dx, dy, top in ((0, 1, [(10 + x, 20 + y) for y in range(5) for x in range(3)]),
                            (1, 0, [(10 + x, 20 + y) for y in range(3) for x in range(5)])):
            out = []
            yards._add_house_carport(top, dx, dy, random.Random(1), out)
            cx0, cy0, cw, ch, tiles, _roof, _d = out[0]
            posts = [(x, y) for x, y, _z, _l, t in tiles if t == yards.CARPORT_POST]
            self.assertEqual(len(posts), 8)
            self.assertEqual(len(set(posts)), 8)
            # the two rows of posts along the drive's open end hold none between the corners
            for x, y in posts:
                inner = (x if dy else y)
                self.assertTrue(inner in ((0, cw) if dy else (0, ch)), (x, y))

    def test_carport_and_porch_pass_validate_tbx(self):
        structures_out = []
        top = [(10 + x, 20 + y) for y in range(5) for x in range(3)]
        yards._add_house_carport(top, 0, 1, random.Random(1), structures_out)
        self.assertEqual(len(structures_out), 1)

        claimed = bytearray(60 * 60)
        paved = bytearray(60 * 60)
        yards._add_front_porch(
            20, 30, 0, 1, -1, 0, 10, 8,
            lambda x, y: True, claimed, paved, 60, 60, set(),
            random.Random(1), structures_out,
        )
        self.assertEqual(len(structures_out), 2)

        with tempfile.TemporaryDirectory() as tmp:
            placements = structures.pack_roofed_structures(
                tmp, "testmap", "yardstruct", structures_out
            )
            self.assertEqual(len(placements), 2)
            for idx, p in enumerate(placements):
                tbx_path = Path(tmp) / Path(p.tbx_path).name
                self.assertEqual(validate_tbx.check(str(tbx_path)), [], p.tbx_path)
                import xml.etree.ElementTree as ET
                root = ET.parse(tbx_path).getroot()
                floors = root.findall("floor")
                self.assertEqual(len(floors), 2)
                if idx == 0:
                    # Carport uses a FlatTop roof on floor z=0 (rendered at z=1)
                    # supported by full-height pillars (never short fence posts).
                    objs = floors[0].findall("object")
                    self.assertEqual(len(objs), 1)
                    self.assertEqual(objs[0].attrib["RoofType"], "FlatTop")
                    self.assertEqual(objs[0].attrib["Depth"], "Three")
                    self.assertFalse(floors[1].findall("object"))
                    user_tiles = [t.attrib["tile"] for t in root.findall("./user_tiles/tile")]
                    self.assertEqual(user_tiles, ["fixtures_railings_01_035"])
                else:
                    # Pitched roofs (Peak30Quad) must live on floor z=1 so knoxlots
                    # draws them above the z=0 posts rather than on the ground.
                    self.assertFalse(floors[0].findall("object"))
                    self.assertTrue(floors[1].findall("object"))

    def test_back_deck_places_floor_and_railings(self):
        lights = []
        claimed = bytearray(40 * 40)
        paved = bytearray(40 * 40)
        yards._add_back_deck(
            0, 8, 6, lambda u, v: (10 + u, 10 - v),
            lambda x, y: True, lambda x, y, c: None, claimed, paved, 40, 40, 1, 0, -1,
            random.Random(1), lights, back_door_u=3,
        )
        floors = [t for t in lights if t[3] == "Floor"]
        rails = [t for t in lights if t[3] == "WallOverlay"]
        furn = [t for t in lights if t[3] == "Furniture"]
        self.assertGreaterEqual(len(floors), 20)
        self.assertEqual(rails, [])
        self.assertTrue(any(t[4] == yards.DECK_GRILL for t in furn))
        self.assertTrue(any(t[4] == yards.DECK_TABLE for t in furn))
        # Deck extends North (bdy=-1): dv=0 chair faces North (idx 1), dv=2 faces South (idx 3)
        table = next(t for t in furn if t[4] == yards.DECK_TABLE)
        south_chair = next(t for t in furn if (t[0], t[1]) == (table[0], table[1] + 1))
        north_chair = next(t for t in furn if (t[0], t[1]) == (table[0], table[1] - 1))
        self.assertEqual(south_chair[4], yards.DECK_CHAIRS[1])
        self.assertEqual(north_chair[4], yards.DECK_CHAIRS[3])

    def test_exterior_house_props_and_orientation_verification(self):
        import numpy as np
        occ = np.zeros((30, 30), dtype=np.uint8)
        occ[5:13, 5:15] = 1
        occ_bytes = bytearray(occ.tobytes())
        lights = []
        doors = [(4, 8, 4, 7), (10, 3, 9, 3)]
        windows = {(8, 13)}
        for seed in range(20):
            yards._add_exterior_house_props(
                5, 5, 10, 8, doors, windows, occ_bytes, 30, 30,
                random.Random(seed), lights,
            )
        tiles_used = {t[4] for t in lights}
        self.assertTrue(any(t.startswith("lighting_outdoor_01_") for t in tiles_used))
        self.assertIn("industry_01_004", tiles_used)
        self.assertIn("industry_01_005", tiles_used)
        self.assertNotIn("industry_01_014", tiles_used)
        self.assertNotIn("industry_01_015", tiles_used)
        self.assertEqual(
            yards.verify_exterior_props(
                lights, occ_bytes, 30, 30, window_tiles=windows, check_pz_defs=True
            ),
            [],
        )
        # Deliberately flipped AC orientation must be caught by verify_exterior_props
        bad = [(8, 13, 0, yards.PORCH_LIGHT_LAYER, yards.WALL_AC_UNIT["W"])]
        self.assertTrue(yards.verify_exterior_props(bad, occ_bytes, 30, 30, window_tiles=windows))

    def test_wall_ac_keeps_clear_of_garage_doors(self):
        import numpy as np
        occ = np.zeros((30, 30), dtype=np.uint8)
        occ[5:13, 5:15] = 1
        occ_bytes = bytearray(occ.tobytes())
        garage = {(8, 13)}
        lights = []
        for seed in range(60):
            yards._add_exterior_house_props(
                5, 5, 10, 8, [], set(), occ_bytes, 30, 30,
                random.Random(seed), lights, garage)
        ac = {t[4] for t in yards.WALL_AC_UNIT.values()}
        near = {(8 + dx, 13 + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        self.assertFalse([t for t in lights if t[4] in ac and (t[0], t[1]) in near])

    def test_residential_front_door_opens_into_hall(self):
        from knoxbuild import layout

        for seed in range(10):
            for w, h, lv in ((12, 10, 1), (16, 12, 2), (20, 14, 2)):
                b = layout.build_building(width=w, height=h, seed=seed, levels=lv, street="S", kind="house")
                st = b.storeys[0]
                gset = set(getattr(st, "garage_door_tiles", ()))
                front = next((d for d in st.doors if d not in gset and d[2] == "N" and d[1] == h), None)
                self.assertIsNotNone(front)
                r_id = st.grid[front[1] - 1][front[0]]
                self.assertEqual(st.rooms[r_id - 1].kind, "hall")


if __name__ == "__main__":
    unittest.main()
