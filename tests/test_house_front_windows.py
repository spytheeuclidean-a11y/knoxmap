"""A house looks out at its street: every storey of a narrow house has a
window in its front wall, rather than spending its rooms' few windows on the
side walls first."""
import unittest

from knoxbuild.layout.assemble import build_building


def front_windows(width, height, seed):
    """Windows in the south (street) wall of each storey of a 2-storey house."""
    b = build_building(width, height, levels=2, seed=seed, street="S")
    return [sum(1 for _x, y, d in s.windows if d == "N" and y == height)
            for s in b.storeys]


class FrontWindows(unittest.TestCase):
    def test_every_storey_has_a_front_window(self):
        for width, height in ((6, 9), (7, 10)):
            for seed in range(12):
                per_storey = front_windows(width, height, seed)
                self.assertTrue(all(per_storey), (width, height, seed, per_storey))

    def test_the_upstairs_front_of_a_terrace_house_has_two(self):
        self.assertEqual({front_windows(7, 10, seed)[1] for seed in range(12)}, {2})


if __name__ == "__main__":
    unittest.main()
