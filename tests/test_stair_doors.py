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

    def test_irregular_civic_keeps_doors_off_stairs(self):
        import random
        import tools.audit_layouts as al

        rng = random.Random(4242)
        for i in range(45):
            kind = al.KINDS[i % len(al.KINDS)]
            w, h = rng.randint(9, 40), rng.randint(9, 40)
            roll = rng.random()
            mask = None
            if roll < 0.3:
                mask = al.irregular_mask(w, h, rng)
            elif roll < 0.65:
                fp = al.rotated_mask(rng)
                if fp is not None:
                    w, h, mask = fp.width, fp.height, fp.mask_list()
            levels = rng.choice((1, 2, 3, 4, 5, 6, 8, 12))
            if i == 44:
                b = build_building(w, h, levels=levels, seed=i, kind=kind,
                                   mask=mask, commercial=True)
                found = audit(b, kind)
                self.assertFalse(found.get(BAD), (kind, w, h, levels, i))
                self.assertFalse(found.get("room with no way in"), (kind, i))

    def test_houses_and_flats(self):
        for seed in range(40):
            self.check(12 + seed % 20, 14 + seed % 17, 2 + seed % 3, seed,
                       "apartment" if seed % 2 else None)


if __name__ == "__main__":
    unittest.main()
