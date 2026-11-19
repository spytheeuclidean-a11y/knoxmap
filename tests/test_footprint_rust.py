"""Parity tests between pure-Python footprint.place() and Rust knoxroute --footprints."""
from __future__ import annotations

import math
import os
import random
import unittest

import numpy as np

from knoxbuild.footprint import FootprintSession, place


def _rect_poly(cx: float, cy: float, w: float, h: float, deg: float = 0.0):
    rad = math.radians(deg)
    ca, sa = math.cos(rad), math.sin(rad)
    hw, hh = w / 2.0, h / 2.0
    pts = []
    for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        pts.append((cx + dx * ca - dy * sa, cy + dx * sa + dy * ca))
    return pts


def _l_poly(x0: float, y0: float, w: float, h: float, cut_w: float, cut_h: float):
    return [
        (x0, y0),
        (x0 + w, y0),
        (x0 + w, y0 + h - cut_h),
        (x0 + w - cut_w, y0 + h - cut_h),
        (x0 + w - cut_w, y0 + h),
        (x0, y0 + h),
    ]


class TestFootprintRustParity(unittest.TestCase):
    def _assert_sequence_parity(
        self,
        w: int,
        h: int,
        buildings: list[tuple[list[tuple[float, float]], dict]],
        avoid: np.ndarray | None = None,
        use_lots: bool = True,
        init_occ: np.ndarray | None = None,
        init_lots: np.ndarray | None = None,
    ):
        occ_py = init_occ.copy() if init_occ is not None else np.zeros((h, w), dtype=bool)
        occ_rs = occ_py.copy()
        lots_py = (
            (init_lots.copy() if init_lots is not None else np.zeros((h, w), dtype=bool))
            if use_lots
            else None
        )
        lots_rs = lots_py.copy() if lots_py is not None else None

        with FootprintSession(occ_rs, avoid=avoid, lots=lots_rs) as sess:
            self.assertTrue(sess.native, "knoxroute --footprints binary must be active")
            for idx, (px, kw) in enumerate(buildings):
                fp_py, r_py = place(px, occ_py, avoid=avoid, lots=lots_py, **kw)
                fp_rs, r_rs = sess.place(px, **kw)
                self.assertEqual(r_py, r_rs, f"building {idx}: reason mismatch")
                if fp_py is None:
                    self.assertIsNone(fp_rs, f"building {idx}: expected None")
                else:
                    self.assertIsNotNone(fp_rs, f"building {idx}: expected Footprint")
                    assert fp_rs is not None
                    self.assertEqual((fp_py.x0, fp_py.y0), (fp_rs.x0, fp_rs.y0), f"building {idx}: origin")
                    self.assertEqual(fp_py.point_offset, fp_rs.point_offset, f"building {idx}: offset")
                    self.assertTrue(
                        np.array_equal(fp_py.mask, fp_rs.mask),
                        f"building {idx}: mask mismatch",
                    )

        self.assertTrue(np.array_equal(occ_py, occ_rs), "final occupied mismatch")
        if use_lots:
            assert lots_py is not None and lots_rs is not None
            self.assertTrue(np.array_equal(lots_py, lots_rs), "final lots mismatch")

    def test_roads_nudges_wide_nudge_and_reject(self):
        h, w = 120, 120
        avoid = np.zeros((h, w), dtype=np.int8)
        # Main road with pavement
        avoid[48:56, :] = 2
        avoid[47, :] = 1
        avoid[56, :] = 1
        # Wide highway where building cannot escape even at WIDE_NUDGE_TILES
        avoid[80:115, 10:110] = 3

        buildings = [
            # Clean off-road rectangle
            (_rect_poly(25, 25, 10, 8), {"min_side": 4, "alignment": "smart"}),
            # Slightly on main road -> normal nudge within 5 tiles
            (_rect_poly(40, 50, 10, 8), {"min_side": 4, "alignment": "smart"}),
            # Deep in main road -> wide nudge
            (_rect_poly(60, 52, 10, 12), {"min_side": 4, "alignment": "smart"}),
            # Stuck in middle of wide highway -> "road"
            (_rect_poly(60, 97, 10, 10), {"min_side": 4, "alignment": "smart"}),
            # Outside map bounds -> "outside"
            (_rect_poly(-30, -30, 8, 8), {"min_side": 4, "alignment": "smart"}),
            # Too small -> "small"
            (_rect_poly(20, 20, 2, 2), {"min_side": 4, "alignment": "smart"}),
            # Too large -> "large"
            (_rect_poly(60, 25, 50, 10), {"min_side": 4, "max_side": 40, "alignment": "smart"}),
        ]
        self._assert_sequence_parity(w, h, buildings, avoid=avoid, use_lots=True)

    def test_lots_clear_box_and_prepopulated_state(self):
        h, w = 100, 100
        init_occ = np.zeros((h, w), dtype=bool)
        init_lots = np.zeros((h, w), dtype=bool)
        # Pre-existing lot in the middle
        init_lots[30:40, 30:40] = True
        init_occ[32:38, 32:38] = True

        buildings = [
            # Diagonal non-rectangular building overlapping init_lots
            (_rect_poly(35, 35, 24, 16, deg=25.0), {"min_side": 4, "alignment": "real"}),
            # L-shape overlapping a corner of the previous lot
            (_l_poly(20, 20, 20, 20, 8, 8), {"min_side": 4, "alignment": "real"}),
            # Exact duplicate -> "taken"
            (_l_poly(20, 20, 20, 20, 8, 8), {"min_side": 4, "alignment": "real"}),
        ]
        self._assert_sequence_parity(
            w, h, buildings, avoid=None, use_lots=True, init_occ=init_occ, init_lots=init_lots
        )

    def test_random_town_stress_parity(self):
        rng = random.Random(42)
        h, w = 220, 220
        avoid = np.zeros((h, w), dtype=np.int8)
        # Grid of streets
        for y in (50, 110, 170):
            avoid[y - 2:y + 3, :] = 2
            avoid[y - 3, :] = 1
            avoid[y + 3, :] = 1
        for x in (60, 140):
            avoid[:, x - 2:x + 3] = 2
            avoid[:, x - 3] = np.maximum(avoid[:, x - 3], 1)
            avoid[:, x + 3] = np.maximum(avoid[:, x + 3], 1)

        alignments = ("smart", "real", "rectilinear", "rectangle")
        buildings = []
        for _ in range(180):
            cx = rng.uniform(5, w - 5)
            cy = rng.uniform(5, h - 5)
            bw = rng.uniform(5, 22)
            bh = rng.uniform(5, 22)
            deg = rng.choice([0.0, 3.0, 15.0, 28.0, 42.0])
            if rng.random() < 0.35:
                px = _l_poly(cx - bw / 2, cy - bh / 2, bw, bh, bw * 0.4, bh * 0.4)
            else:
                px = _rect_poly(cx, cy, bw, bh, deg=deg)
            kw = {
                "min_side": 4.0,
                "max_side": 30.0,
                "snap_degrees": 8.0,
                "alignment": rng.choice(alignments),
            }
            buildings.append((px, kw))

        self._assert_sequence_parity(w, h, buildings, avoid=avoid, use_lots=True)

    def test_fallback_when_disabled_or_missing_binary(self):
        occ = np.zeros((60, 60), dtype=bool)
        lots = np.zeros((60, 60), dtype=bool)
        old = os.environ.get("KNOXMAP_FOOTPRINT_RUST")
        try:
            os.environ["KNOXMAP_FOOTPRINT_RUST"] = "0"
            with FootprintSession(occ, lots=lots) as sess:
                self.assertFalse(sess.native)
                fp, reason = sess.place(_rect_poly(30, 30, 10, 8), min_side=4)
                self.assertEqual(reason, "ok")
                self.assertIsNotNone(fp)
        finally:
            if old is None:
                os.environ.pop("KNOXMAP_FOOTPRINT_RUST", None)
            else:
                os.environ["KNOXMAP_FOOTPRINT_RUST"] = old

        occ2 = np.zeros((60, 60), dtype=bool)
        with self.assertLogs("knoxmap", level="WARNING"):
            with FootprintSession(occ2, binary="__nonexistent_knoxroute_bin__") as sess:
                self.assertFalse(sess.native)
                fp, reason = sess.place(_rect_poly(30, 30, 10, 8), min_side=4)
                self.assertEqual(reason, "ok")
                self.assertIsNotNone(fp)


if __name__ == "__main__":
    unittest.main()
