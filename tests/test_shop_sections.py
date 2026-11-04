"""Regression for the shop floor dropped from a generated map.

logs/knoxmap.log.1, 2026-11-03 (1.8.4): "building left out ... IndexError:
list index out of range" in _fit_out_sections. _shop_rooms recorded 1-based
room numbers before _paint; _paint drops, splits and renumbers rooms, so the
numbers were stale by the time _fit_out_sections indexed plan.rooms with them.
"""
import unittest

from knoxbuild import layout


def _band(w, h, y0, y1):
    """A footprint mask that leaves most of the shop outside the building."""
    return [[y0 <= y < y1 for _ in range(w)] for y in range(h)]


class ShopSections(unittest.TestCase):
    def test_renumbered_shop_floor_lays_out(self):
        mask = _band(96, 71, 60, 71)
        for street in (None, "S", "N", "E", "W"):
            for seed in (1, 2, 3):
                with self.subTest(street=street, seed=seed):
                    building = layout.build_building(
                        96, 71, levels=2, seed=seed, kind="shop",
                        street=street, mask=mask)
                    self.assertIsNotNone(building)


class PathGuards(unittest.TestCase):
    def test_save_refuses_a_sibling_prefix(self):
        """output/foo is not output/foo2: str.startswith used to say it was."""
        import tempfile
        from pathlib import Path

        from web import common

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "foo").mkdir()
            (root / "foo2").mkdir()
            (root / "foo2" / "secret.txt").write_text("x", encoding="utf-8")
            old = common.OUTPUT_DIR
            common.OUTPUT_DIR = root
            try:
                map_dir = common._map_dir("foo")
                self.assertIsNotNone(map_dir)
                target = (map_dir / ".." / "foo2" / "secret.txt").resolve()
                self.assertTrue(str(target).startswith(str(map_dir)))  # old bug
                self.assertFalse(target.is_relative_to(map_dir))       # now refused
            finally:
                common.OUTPUT_DIR = old


if __name__ == "__main__":
    unittest.main()
