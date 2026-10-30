"""No door opens onto the steps of a flight of stairs: those squares cannot be
walked across, so the door and the rooms behind it are cut off."""
import os
import sys
import unittest

from knoxbuild.layout import build_building

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
from audit_layouts import audit  # noqa: E402

BAD = "door opening onto the stairs"


class DoorsClearOfStairs(unittest.TestCase):
    def check(self, w, h, levels, seed, kind):
        b = build_building(w, h, levels=levels, seed=seed, kind=kind,
                           commercial=kind not in (None, "apartment"))
        found = audit(b, kind)
        self.assertFalse(found.get(BAD), (kind, w, h, levels, seed))
        self.assertFalse(found.get("room with no way in"), (kind, seed))

    def test_cases_that_failed(self):
        self.check(21, 37, 2, 60, "apartment")
        self.check(36, 39, 5, 98, "apartment")
        self.check(28, 28, 8, 44, "civic")

    def test_houses_and_flats(self):
        for seed in range(40):
            self.check(12 + seed % 20, 14 + seed % 17, 2 + seed % 3, seed,
                       "apartment" if seed % 2 else None)


if __name__ == "__main__":
    unittest.main()
