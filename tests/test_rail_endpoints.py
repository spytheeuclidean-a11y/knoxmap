"""Fixed-size rail pieces must be able to end near fractional map coordinates."""
import math
import unittest

from generator.rail_tiles import ASSEMBLIES
from generator.rendering.rails import continuous_tracks, rail_sections


class RailEndpoints(unittest.TestCase):
    def test_short_straight_fragment_uses_one_piece_instead_of_a_loop(self):
        for delta in ((1, 0), (0, 1), (1, 1), (1, -1)):
            for phase in (0, .2, .5, .8):
                points = [(10+phase, 20), (10+phase+1.2*delta[0], 20+1.2*delta[1])]
                for track in continuous_tracks([points]):
                    with self.subTest(delta=delta, phase=phase):
                        sections = list(rail_sections(track, backend="python"))
                        self.assertEqual(len(sections), 1)
                        self.assertLess(sections[0][2], 4)
                        x, y, index = sections[0]
                        ports = [(x+px/2, y+py/2) for px, py in ASSEMBLIES[index][:2]]
                        for endpoint in track:
                            self.assertLessEqual(min(math.dist(p, endpoint) for p in ports),
                                                 math.sqrt(2.5)+1e-8)

    def test_scaled_real_fragment_fits_with_connected_ports(self):
        # A clipped Cookeville diagonal; at 2m/tile its last port overhangs the line.
        source = [(2185.1667290805053, 1125.3332709194947),
                  (2189.4088189004106, 1121.0911810995894)]
        for scale in (1, 2, 3):
            points = [(x / scale, y / scale) for x, y in source]
            for track in continuous_tracks([points]):
                with self.subTest(scale=scale):
                    sections = list(rail_sections(track, backend="python"))
                    self.assertTrue(sections)
                    previous = None
                    for x, y, index in sections:
                        ports = {(2*x+px, 2*y+py) for px, py in ASSEMBLIES[index][:2]}
                        if previous is not None:
                            self.assertEqual(len(previous & ports), 1)
                        previous = ports
                    target = max(track[0], track[-1])
                    self.assertLessEqual(min(math.dist((px/2, py/2), target)
                                             for px, py in previous), math.sqrt(2.5)+1e-8)

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
