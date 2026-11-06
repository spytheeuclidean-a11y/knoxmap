"""Woodland pixels must stay identical across the native and Python paths."""
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import struct
import subprocess
import unittest
from unittest import mock

import numpy as np
from PIL import Image

import knoxstop
from generator import pz_colors as C
from generator.osm import OSMFeature
from generator.rendering import vegetation, woodland
from generator.roadgraph import rustsearch


def inputs(size=(257, 259)):
    w, h = size
    palette = np.array([C.WATER, C.MEDIUM_GRASS, C.LIGHT_GRASS, C.DARK_GRASS,
                        C.MEDIUM_ASPHALT, C.DIRT, (19, 51, 83)], dtype=np.uint8)
    ground = Image.fromarray(palette[np.arange(w*h).reshape(h, w) % len(palette)])
    return Image.new('RGB', size, C.FLOWERS), ground


def features():
    return [OSMFeature(1, 'way', {'landuse': 'forest'},
                       [(3, 3), (3, 250), (255, 250), (255, 3), (3, 3)]),
            OSMFeature(2, 'way', {'natural': 'scrub'},
                       [(0, 0), (0, 150), (220, 150), (220, 0), (0, 0)]),
            OSMFeature(3, 'node', {'natural': 'tree'}, [(258, 256)])]


PROJ = SimpleNamespace(meters_per_tile=1, to_px=lambda lat, lon: (lon, lat))


class Fallback(unittest.TestCase):
    def test_invalid_reply_and_failed_worker_leave_images_unchanged(self):
        for reply, code in ((b'', 0), (b'KWD1'+b'x'*35, 0), (b'wrong'+b'x'*35, 0), (b'', 2)):
            proc = mock.MagicMock()
            proc.__enter__.return_value = proc
            proc.poll.return_value = code
            proc.returncode = code
            proc.stdin.write.side_effect = lambda data: len(data)
            proc.stdout.read.return_value = reply
            veg, land = inputs((3, 2))
            mask = Image.new('L', veg.size, 255)
            before = veg.tobytes(), land.tobytes()
            with mock.patch.object(woodland, 'exe', return_value='worker'), \
                    mock.patch.object(woodland.subprocess, 'Popen', return_value=proc), \
                    self.assertLogs(woodland.__name__, level='WARNING'):
                self.assertFalse(woodland.paint(veg, land, mask, mask, mask,
                                                C.TREES_DARK_GRASS, C.TREES))
            self.assertEqual((veg.tobytes(), land.tobytes()), before)

    def test_timeout_and_stop_kill_the_worker(self):
        for stopped in (False, True):
            proc = mock.MagicMock()
            proc.__enter__.return_value = proc
            proc.poll.return_value = None
            veg, land = inputs((3, 2))
            mask = Image.new('L', veg.size, 255)
            with mock.patch.object(woodland, 'exe', return_value='worker'), \
                    mock.patch.object(woodland.subprocess, 'Popen', return_value=proc), \
                    mock.patch.object(woodland, '_exchange', return_value=b'x'*36), \
                    mock.patch.object(woodland, 'TIMEOUT_S', 0 if not stopped else 30):
                if stopped:
                    with self.assertRaises(knoxstop.Stopped):
                        woodland.paint(veg, land, mask, mask, mask, C.TREES, C.TREES,
                                       should_stop=lambda: True)
                else:
                    with self.assertLogs(woodland.__name__, level='WARNING'):
                        self.assertFalse(woodland.paint(veg, land, mask, mask, mask, C.TREES, C.TREES))
            proc.kill.assert_called_once()

    def test_missing_worker_leaves_images_for_python(self):
        veg, land = inputs((3, 2))
        mask = Image.new('L', veg.size, 255)
        before = veg.tobytes(), land.tobytes()
        with mock.patch.object(woodland, 'exe', return_value=None):
            self.assertFalse(woodland.paint(veg, land, mask, mask, mask,
                                            C.TREES_DARK_GRASS, C.TREES))
        self.assertEqual((veg.tobytes(), land.tobytes()), before)

    def test_stop_does_not_fall_back(self):
        veg, land = inputs()
        with self.assertRaises(knoxstop.Stopped):
            vegetation._paint_woodland(veg, land, features(), PROJ, should_stop=lambda: True)


@unittest.skipUnless(rustsearch.available(), 'build rust/knoxroute for native parity')
class Native(unittest.TestCase):
    def setUp(self):
        self.threshold = mock.patch.object(woodland, 'MIN_PIXELS', 0)
        self.threshold.start()
        self.addCleanup(self.threshold.stop)

    def test_terrain_files_match_the_python_woodland_path(self):
        from generator import renderer
        from tools.regression_maps import (scenario_features, SOUTH, WEST, LAT_PER_M, LON_PER_M)
        native = woodland.paint

        def checked(*args, **kwargs):
            result = native(*args, **kwargs)
            self.assertTrue(result, 'native woodland silently fell back')
            return result

        with TemporaryDirectory() as temp:
            for scale in (1, 2, 3):
                hashes = []
                for backend in ('python', 'rust'):
                    folder = Path(temp)/str(scale)/backend
                    with mock.patch.object(woodland, 'paint', return_value=False) if backend == 'python' else \
                            mock.patch.object(woodland, 'paint', side_effect=checked) as worker:
                        renderer.render(scenario_features('village'), SOUTH, WEST,
                                        SOUTH+260*LAT_PER_M, WEST+260*LON_PER_M,
                                        scale, str(folder), 'woods')
                        if backend == 'rust':
                            worker.assert_called_once()
                    hashes.append({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in folder.iterdir() if p.suffix in ('.bmp', '.png')
                                   or p.name.endswith('_structures.json')})
                self.assertGreaterEqual(len(hashes[0]), 7)
                self.assertEqual(*hashes)

    def test_python_can_finish_after_a_partial_native_failure(self):
        expected = inputs()
        with mock.patch.object(woodland, 'paint', return_value=False):
            vegetation._paint_woodland(*expected, features(), PROJ, .75)
        actual = inputs()
        exchange = woodland._exchange
        calls = []

        def interrupted(*args):
            calls.append(1)
            if len(calls) == 2:
                raise OSError('worker interrupted')
            return exchange(*args)

        with mock.patch.object(woodland, '_exchange', side_effect=interrupted), \
                self.assertLogs(woodland.__name__, level='WARNING'):
            vegetation._paint_woodland(*actual, features(), PROJ, .75)
        self.assertEqual(len(calls), 2)
        self.assertEqual([im.tobytes() for im in actual], [im.tobytes() for im in expected])

    def test_density_edges_scrub_water_and_existing_pixels_match_python(self):
        native = woodland.paint
        for density in (-1, 0, .25, .75, 1, 1.25, 1.75, 2, 3):
            with self.subTest(density=density):
                expected = inputs()
                with mock.patch.object(woodland, 'paint', return_value=False):
                    vegetation._paint_woodland(*expected, features(), PROJ, density)
                actual = inputs()

                def checked(*args, **kwargs):
                    result = native(*args, **kwargs)
                    self.assertTrue(result, 'native worker silently fell back')
                    return result

                with mock.patch.object(woodland, 'paint', side_effect=checked) as worker:
                    vegetation._paint_woodland(*actual, features(), PROJ, density)
                worker.assert_called_once()
                self.assertEqual([im.tobytes() for im in actual], [im.tobytes() for im in expected])

    def test_invalid_frames_exit_without_large_allocations(self):
        for payload in (b'bad!', b'KWD1'+struct.pack('<II', 0, 1),
                        b'KWD1'+struct.pack('<II', 2**31, 2**31), b'KWD1'):
            reply = subprocess.run([rustsearch.exe(), '--woodland'], input=payload,
                                   capture_output=True, timeout=10)
            self.assertNotEqual(reply.returncode, 0)
