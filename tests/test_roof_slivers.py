import random
import unittest

from knoxbuild.layout.assemble import roof_rects


def covered(rects, w, h):
    seen = [[0] * w for _ in range(h)]
    for x0, y0, rw, rh, _caps in rects:
        for y in range(y0, y0 + rh):
            for x in range(x0, x0 + rw):
                seen[y][x] += 1
    return seen


class RoofSlivers(unittest.TestCase):
    def test_an_l_is_two_blocks_not_a_block_and_a_strip(self):
        grid = [[1] * 20 for _ in range(7)] + [[0] * 10 + [1] * 10]
        rects = roof_rects(grid)
        self.assertEqual(len(rects), 2)
        self.assertTrue(all(min(r[2], r[3]) >= 7 for r in rects))

    def test_every_footprint_is_covered_exactly_once(self):
        rng = random.Random(3)
        for _ in range(200):
            w, h = rng.randint(3, 14), rng.randint(3, 14)
            grid = [[1 if rng.random() < 0.8 else 0 for _ in range(w)] for _ in range(h)]
            seen = covered(roof_rects(grid), w, h)
            for y in range(h):
                for x in range(w):
                    self.assertEqual(seen[y][x], 1 if grid[y][x] else 0)


if __name__ == "__main__":
    unittest.main()
