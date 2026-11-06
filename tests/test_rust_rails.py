"""The native rail search must emit the same connected assemblies as Python."""
import random
import hashlib
import math
from pathlib import Path
import struct
import subprocess
import unittest
from tempfile import TemporaryDirectory
from unittest import mock

from PIL import Image, ImageDraw

import knoxstop
from generator.rail_tiles import ASSEMBLIES, RAIL_END_RADIUS
from generator.rendering.rails import rail_sections, paint_track
from generator.roadgraph import rustsearch


class Fallback(unittest.TestCase):
    def test_an_unfittable_path_is_logged_and_not_silently_dropped(self):
        points = [(0, 0), (2, 0), (2, 2)]
        with mock.patch("generator.rendering.rails.rail_sections", side_effect=ValueError("no route")), \
                self.assertLogs("generator.rendering.rails", level="ERROR") as log:
            with self.assertRaises(ValueError):
                paint_track(ImageDraw.Draw(Image.new("RGB", (10, 10))), points)
        self.assertIn(repr(points), log.output[0])

    def test_missing_or_old_worker_keeps_the_python_result(self):
        points = [(5, 10), (50, 17)]
        expected = list(rail_sections(points, backend="python"))
        with mock.patch.object(rustsearch, "exe", return_value=None):
            self.assertEqual(list(rail_sections(points)), expected)
        with mock.patch.object(rustsearch, "exe", return_value="knoxroute"), \
                mock.patch.object(rustsearch.subprocess, "Popen", side_effect=OSError("old worker")), \
                self.assertLogs(rustsearch.__name__, level="WARNING"):
            self.assertEqual(list(rail_sections(points)), expected)

    def test_stop_is_not_retried_in_python(self):
        proc = mock.MagicMock()
        proc.poll.return_value = None
        proc.communicate.side_effect = [subprocess.TimeoutExpired("rails", .1), (b"", b"")]
        proc.__enter__.return_value = proc
        calls = iter([False, False, True])
        with mock.patch.object(rustsearch, "exe", return_value="knoxroute"), \
                mock.patch.object(rustsearch.subprocess, "Popen", return_value=proc):
            with self.assertRaises(knoxstop.Stopped):
                rustsearch.rail_search(Image.new("L", (10, 10)), 0, 0,
                                      (0, 0, 1, 0), (10, 0), (1, 0), ASSEMBLIES,
                                      should_stop=lambda: next(calls))
        proc.kill.assert_called_once()

    def test_truncated_or_invalid_result_falls_back(self):
        for reply in (b"", b"KRL1"+struct.pack("<4i", 1, 0, 0, 0),
                      b"KRL2"+struct.pack("<i", 0), b"KRL2"+struct.pack("<i", 12),
                      b"KRL2"+struct.pack("<4i", 1, 0, 0, 10000)):
            proc = mock.MagicMock()
            proc.poll.return_value = 0
            proc.returncode = 0
            proc.communicate.return_value = (reply, b"")
            proc.__enter__.return_value = proc
            with mock.patch.object(rustsearch, "exe", return_value="knoxroute"), \
                    mock.patch.object(rustsearch.subprocess, "Popen", return_value=proc), \
                    self.assertLogs(rustsearch.__name__, level="WARNING"):
                self.assertIsNone(rustsearch.rail_search(Image.new("L", (10, 10)),
                    0, 0, (0, 0, 1, 0), (10, 0), (1, 0), ASSEMBLIES))

    def test_timeout_kills_worker_before_falling_back(self):
        proc = mock.MagicMock()
        proc.poll.return_value = None
        proc.__enter__.return_value = proc
        with mock.patch.object(rustsearch, "exe", return_value="knoxroute"), \
                mock.patch.object(rustsearch.subprocess, "Popen", return_value=proc), \
                mock.patch.object(rustsearch.Router, "SEARCH_TIMEOUT_S", 0), \
                self.assertLogs(rustsearch.__name__, level="WARNING"):
            self.assertIsNone(rustsearch.rail_search(Image.new("L", (10, 10)),
                0, 0, (0, 0, 1, 0), (10, 0), (1, 0), ASSEMBLIES))
        proc.kill.assert_called_once()


@unittest.skipUnless(rustsearch.available(), "build rust/knoxroute for native parity")
class NativeRails(unittest.TestCase):
    def test_fractional_and_clipped_endpoints_fit_in_both_backends(self):
        from generator.rendering.rails import continuous_tracks
        cases = [[(0, .1), (4, .1)], [(.5, 1.5), (3.5, 4.5)],
                 [(.5, 0), (3.5, -3)], [(.49, 0), (.49, 4)],
                 [(0, .5), (4, .5)], [(.5, 0), (.5, 4)]]
        cases += [track for points in cases[:3] for track in continuous_tracks([points])]
        source = [(2185.1667290805053, 1125.3332709194947),
                  (2189.4088189004106, 1121.0911810995894)]
        cases += [track for scale in (1, 2, 3)
                  for track in continuous_tracks([[(x/scale, y/scale) for x, y in source]])]
        cases += [[(10.2, 20), (11.4, 20)]]
        for points in cases:
            with self.subTest(points=points):
                expected = list(rail_sections(points, backend="python"))
                self.assertTrue(expected)
                self.assertEqual(list(rail_sections(points)), expected)
                self.assertEqual(list(rail_sections(list(reversed(points)))), expected)
                x, y, index = expected[-1]
                end_ports = [(x+px/2, y+py/2) for px, py in ASSEMBLIES[index][:2]]
                target = max(points[0], points[-1])  # canonical route direction
                self.assertLessEqual(min(math.dist(p, target) for p in end_ports), RAIL_END_RADIUS)

    def test_no_route_is_reported_without_retrying_the_search(self):
        with self.assertRaises(ValueError):
            rustsearch.rail_search(Image.new("L", (10, 10), 255),
                                  0, 0, (0, 0, 1, 0), (10, 0), (1, 0), ASSEMBLIES)

    def test_terrain_bitmaps_match_the_python_renderer(self):
        from generator import osm, renderer
        from tools.regression_maps import (SOUTH, WEST, LAT_PER_M, LON_PER_M,
                                           scenario_features)

        def features():
            result = scenario_features("village")
            for i, offset in enumerate((0, 7)):
                points = [(x, y+offset) for x, y in ((0, 165), (80, 165), (125, 210), (260, 210))]
                result.append(osm.OSMFeature(-100-i, "way", {"railway": "rail"},
                    [(SOUTH+y*LAT_PER_M, WEST+x*LON_PER_M) for x, y in points]))
            return result

        hashes = []
        with TemporaryDirectory() as temp:
            for scale, backend in ((scale, backend) for scale in (1, 2, 3)
                                   for backend in ("python", "rust")):
                folder = Path(temp)/str(scale)/backend
                with mock.patch.object(rustsearch, "rail_search", return_value=None) if backend == "python" else \
                        mock.patch.object(rustsearch, "rail_search", wraps=rustsearch.rail_search) as native:
                    renderer.render(features(), SOUTH, WEST, SOUTH+260*LAT_PER_M,
                                    WEST+260*LON_PER_M, scale, str(folder), "rails")
                    if backend == "rust":
                        self.assertGreaterEqual(native.call_count, 2)
                hashes.append({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in folder.iterdir() if p.suffix in (".bmp", ".png")
                               or p.name.endswith("_structures.json")})
            for i in range(0, len(hashes), 2):
                self.assertGreaterEqual(len(hashes[i]), 7)
                self.assertEqual(hashes[i], hashes[i+1])

    def test_exact_sections_across_straights_curves_negative_and_half_tiles(self):
        cases = [[], [(0, 0)], [(0, 0), (.1, .1)], [(5, 10), (90, 17)],
                 [(5, 30), (90, 23)], [(5, 5), (30, 5), (60, 20), (100, 5)],
                 [(10, 10), (40, 40)], [(10, 40), (40, 10)],
                 [(5, 10), (35, 10), (40, 40)],
                 [(-40.5, -20.5), (0, -20.5), (20.5, 0.5)],
                 [(0, 0), (0, 0), (80, 0), (80, 80)]]
        rng = random.Random(7612)
        for _ in range(12):
            x, y = rng.randint(-30, 30)+.5, rng.randint(-30, 30)+.5
            cases.append([(x, y), (x+rng.randint(15, 60), y+rng.randint(-8, 8))])
        original = rustsearch.rail_search
        native_calls = []

        def checked(*args, **kwargs):
            result = original(*args, **kwargs)
            self.assertIsNotNone(result, "native worker failed and silently fell back")
            native_calls.append(1)
            return result

        with mock.patch.object(rustsearch, "rail_search", checked):
            for points in cases:
                with self.subTest(points=points):
                    expected = list(rail_sections(points, backend="python"))
                    self.assertEqual(list(rail_sections(points)), expected)
                    self.assertEqual(list(rail_sections(list(reversed(points)))), expected)
        self.assertGreaterEqual(len(native_calls), 30)

    def test_bad_input_exits_without_allocating_a_huge_guide(self):
        for payload in (b"bad!", b"KRL2"+struct.pack("<4i", 0, 0, 2**30, 2**30),
                        b"KRL2"+struct.pack("<8i3d3i", 0, 0, 10, 10, 0, 0, 1, 0,
                                           10, 0, float('nan'), 1, 0, len(ASSEMBLIES))):
            result = subprocess.run([rustsearch.exe(), "--rails"], input=payload,
                                    capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
