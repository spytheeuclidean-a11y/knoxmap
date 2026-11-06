import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator.rail_tiles import ASSEMBLIES, RAIL_RULES
from generator.rendering.rails import continuous_tracks, rail_sections
from knoxbuild.build import _road_weight


class ContinuousRails(unittest.TestCase):
    def test_minor_drift_becomes_one_run_without_sideways_bends(self):
        tracks = list(continuous_tracks([[(0, 0), (40, 4), (80, 8), (120, 12)]]))
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0][0][1], tracks[0][-1][1])
        self.assertTrue(all(index == 0 for x, y, index in rail_sections(tracks[0])))

    def test_parallel_tracks_stay_two_aligned_continuous_runs(self):
        rings = [[(0, 0), (100, 10), (200, 20)],
                 [(0, 5), (100, 15), (140, 14)]]
        tracks = list(continuous_tracks(rings))
        self.assertEqual(len(tracks), 2)
        self.assertEqual([p[0] for p in tracks[0]], [p[0] for p in tracks[1]])
        self.assertGreaterEqual(abs(tracks[0][0][1] - tracks[1][0][1]), 5)
        seen = set()
        for track in tracks:
            for ox, oy, index in rail_sections(track):
                self.assertEqual(index, 0)
                for x, y, sheet, tile in ASSEMBLIES[index][4]:
                    pos = (ox + x, oy + y)
                    self.assertNotIn(pos, seen)
                    seen.add(pos)

    def test_major_turn_is_kept_as_a_single_corner(self):
        tracks = list(continuous_tracks([[(0, 0), (80, 0), (80, 80)]]))
        self.assertEqual(len(tracks), 1)
        self.assertEqual(len(tracks[0]), 3)
        sections = list(rail_sections(tracks[0]))
        self.assertTrue(any(index >= 4 for x, y, index in sections))
        self.assertLessEqual(sum(index >= 4 for x, y, index in sections), 4)

    def test_fragment_order_and_direction_do_not_change_two_track_geometry(self):
        rings = [[(0, 0), (50, 5)], [(50, 5), (100, 10)],
                 [(0, 5), (100, 15)]]
        first = sorted(tuple(t) for t in continuous_tracks(rings))
        second = sorted(tuple(t) for t in continuous_tracks([list(reversed(r)) for r in reversed(rings)]))
        self.assertEqual(first, second)

    def test_buildings_keep_off_rail_even_in_industrial_yards(self):
        with tempfile.TemporaryDirectory() as folder:
            colours = [colour for label, colour, tile in RAIL_RULES]
            ground = np.array([colours + [C.DIRT] * 3], dtype=np.uint8)
            Image.fromarray(ground).save(Path(folder) / 'map_ground_base.bmp')
            areas = mock.Mock()
            areas.mask.return_value = np.ones(ground.shape[:2], dtype=bool)
            weight = _road_weight(folder, 'map', SimpleNamespace(width=ground.shape[1], height=1), areas=areas)
            self.assertTrue(np.all(weight[0, :-3] >= 2))
            self.assertGreaterEqual(weight[0, -3], 2)
            self.assertEqual(weight[0, -1], 0)


if __name__ == '__main__':
    unittest.main()
