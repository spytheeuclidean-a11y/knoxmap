"""Tests for carports, front porches, back decks, and exterior house props."""
import random
import tempfile
import unittest
from pathlib import Path

from knoxbuild import structures, yards
from tools import validate_tbx


class LivedInHouseStructuresTests(unittest.TestCase):
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
            for p in placements:
                tbx_path = Path(tmp) / Path(p.tbx_path).name
                self.assertEqual(validate_tbx.check(str(tbx_path)), [], p.tbx_path)

    def test_back_deck_places_floor_and_railings(self):
        lights = []
        claimed = bytearray(40 * 40)
        paved = bytearray(40 * 40)
        yards._add_back_deck(
            0, 6, 5, lambda u, v: (10 + u, 10 - v),
            lambda x, y: True, lambda x, y, c: None, claimed, paved, 40, 40, 1, 0, -1,
            random.Random(1), lights,
        )
        floors = [t for t in lights if t[3] == "Floor"]
        rails = [t for t in lights if t[3] == "WallOverlay"]
        self.assertEqual(len(floors), 15)  # 5x3 wood deck
        self.assertTrue(rails)

    def test_exterior_house_props_add_lights_electric_and_ac_clear_of_windows(self):
        import numpy as np
        occ = np.zeros((30, 30), dtype=np.uint8)
        occ[5:13, 5:15] = 1
        occ_bytes = bytearray(occ.tobytes())
        lights = []
        doors = [(4, 8, 4, 7), (10, 3, 9, 3)]
        windows = {(8, 13)}
        # Try a few seeds to ensure all prop types appear cleanly
        for seed in range(10):
            yards._add_exterior_house_props(
                5, 5, 10, 8, doors, windows, occ_bytes, 30, 30,
                random.Random(seed), lights,
            )
        tiles_used = {t[4] for t in lights}
        self.assertTrue(any(t.startswith("lighting_outdoor_01_") for t in tiles_used))
        self.assertIn("industry_01_014", tiles_used)
        self.assertIn("industry_01_004", tiles_used)
        self.assertFalse(any((t[0], t[1]) in {(7, 13), (8, 13), (9, 13)} for t in lights))


if __name__ == "__main__":
    unittest.main()
