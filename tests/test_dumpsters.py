import random
import unittest

from knoxbuild.works import _dumpster

X0, Y0, BW, BH = 10, 10, 10, 8


def ring_around():
    return [(x, y) for x in range(X0 - 1, X0 + BW + 1) for y in range(Y0 - 1, Y0 + BH + 1)
            if max(X0 - x, x - (X0 + BW - 1), Y0 - y, y - (Y0 + BH - 1), 0) == 1]


def stood(occ=None, seed=1, doors=()):
    got = {}

    def stand(x, y, colour):
        got[(x, y)] = colour
        return True
    ok = _dumpster(ring_around(), X0, Y0, BW, BH, list(doors), lambda x, y: (x, y) not in got,
                   stand, random.Random(seed), occ)
    return ok, got


class DumpsterClearance(unittest.TestCase):
    def test_stands_wholly_against_the_south_or_east_wall(self):
        for seed in range(20):
            ok, got = stood(seed=seed)
            self.assertTrue(ok)
            (a, b) = sorted(got)
            south = a[1] == b[1] == Y0 + BH and X0 <= a[0] and b[0] <= X0 + BW - 1
            east = a[0] == b[0] == X0 + BW and Y0 <= a[1] and b[1] <= Y0 + BH - 1
            self.assertTrue(south or east, (seed, a, b))

    def test_not_squeezed_into_an_alley_between_two_buildings(self):
        # A building two tiles off the east wall: the east wall has no room for one.
        neighbour = lambda x, y: x >= X0 + BW + 1 and Y0 - 3 <= y <= Y0 + BH + 3
        for seed in range(20):
            ok, got = stood(neighbour, seed)
            self.assertTrue(ok)
            self.assertTrue(all(y == Y0 + BH for _x, y in got), (seed, got))

    def test_none_when_a_neighbour_hems_every_wall(self):
        everywhere = lambda x, y: not (X0 <= x < X0 + BW and Y0 <= y < Y0 + BH) and \
            (x < X0 - 1 or x > X0 + BW or y < Y0 - 1 or y > Y0 + BH)
        ok, got = stood(everywhere)
        self.assertFalse(ok)
        self.assertFalse(got)


if __name__ == "__main__":
    unittest.main()
