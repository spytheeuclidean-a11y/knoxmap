"""Fixed-size rail pieces must be able to end near fractional map coordinates."""
import math
import unittest

from generator.rail_tiles import ASSEMBLIES
from generator.rendering.rails import continuous_tracks, rail_sections


class RailEndpoints(unittest.TestCase):
    def test_fractional_endpoints_and_fitted_diagonal_fragments(self):
        cases = [[(0, .1), (4, .1)], [(0, .5), (4, .5)],
                 [(.5, 0), (.5, 4)], [(.5, 1.5), (3.5, 4.5)],
                 [(.5, 0), (3.5, -3)]]
        cases += [track for points in cases[:] for track in continuous_tracks([points])]
        for points in cases:
            with self.subTest(points=points):
                sections = list(rail_sections(points))
                self.assertTrue(sections)
                self.assertEqual(list(rail_sections(list(reversed(points)))), sections)
                previous = None
                for x, y, index in sections:
                    ports = {(2*x+px, 2*y+py) for px, py in ASSEMBLIES[index][:2]}
                    if previous is not None:
                        self.assertEqual(len(previous & ports), 1)
                    previous = ports
                endpoint = max(points[0], points[-1])
                self.assertLessEqual(min(math.dist((px/2, py/2), endpoint)
                                         for px, py in previous), math.sqrt(2.5)+1e-8)

    def test_integer_straight_keeps_its_existing_assembly(self):
        self.assertEqual(list(rail_sections([(0, 0), (4, 0)])), [(0, -1, 0)])
