"""A worker that dies in native code must not lose the whole compile.

concurrent.futures.BrokenProcessPool was raised out of the row pool and ended
the run: with an access violation in one worker (0xC0000005 on Windows) the map
could not be compiled at all, and the rows already paid for were only kept if
the caller passed resume=True. The rows a broken pool leaves unfinished are now
made again one at a time.
"""
import os
import tempfile
import unittest
from concurrent import futures
from unittest import mock

from tools import map_source


class _Pool:
    def __init__(self, *a, **k):
        pass

    def submit(self, *a, **k):
        return object()

    def shutdown(self, *a, **k):
        pass


class BrokenPool(unittest.TestCase):
    def test_the_rows_a_broken_pool_lost_are_made_one_at_a_time(self):
        made = []

        def row(project, out, cy, band, placed, seed, seams, size):
            made.append(cy)
            return 1

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(map_source.bitmaps, "_bmp_header", return_value=(600, 600)), \
                mock.patch.object(map_source, "project_origin", return_value=(0, 0)), \
                mock.patch.object(map_source, "read_lots", return_value=[]), \
                mock.patch.object(map_source, "read_buildings", return_value=[]), \
                mock.patch.object(map_source, "_row", row), \
                mock.patch.object(futures, "ProcessPoolExecutor", _Pool), \
                mock.patch.object(map_source, "_gather",
                                  side_effect=futures.process.BrokenProcessPool("worker died")):
            written = map_source.make_map_source(tmp, os.path.join(tmp, "src"), workers=2)

        self.assertGreater(len(made), 1, "the pool path was taken")
        self.assertEqual(written, len(made))
        self.assertEqual(sorted(made), list(range(len(made))), "every row was made once")


if __name__ == "__main__":
    unittest.main()
