"""Generate downloads the WorldCover tiles a map needs, and never fails on it."""
import unittest
from unittest import mock

from web import generation

BBOX = (45.16, -68.86, 45.19, -68.80)


class Source:
    def __init__(self, enabled=True, available=True, cached=False, fails=False):
        self._enabled, self._available, self._cached = enabled, available, cached
        self.fails = fails
        self.fetched = []

    def enabled(self, settings):
        return self._enabled

    def available(self, bbox):
        return self._available

    def cached(self, bbox):
        return self._cached

    def fetch(self, bbox, cache_dir=None, progress_cb=None):
        if self.fails:
            raise OSError("offline")
        progress_cb(5_000_000, 50_000_000)
        self.fetched.append(bbox)


def run(source):
    knoxdata = mock.Mock()
    knoxdata.sources.return_value = {"worldcover": source}
    with mock.patch.object(generation, "_set_progress") as progress:
        generation._fetch_landcover(knoxdata, object(), BBOX, "m")
    return progress


class FetchLandcoverTest(unittest.TestCase):
    def test_fetches_when_missing(self):
        source = Source()
        progress = run(source)
        self.assertEqual(source.fetched, [BBOX])
        notes = [c.kwargs.get("note", "") for c in progress.call_args_list]
        self.assertTrue(any("5 of 50 MB" in n for n in notes), notes)

    def test_skips_when_cached_off_or_out_of_coverage(self):
        for source in (Source(cached=True), Source(enabled=False), Source(available=False)):
            run(source)
            self.assertEqual(source.fetched, [])

    def test_failure_is_not_fatal(self):
        run(Source(fails=True))


if __name__ == "__main__":
    unittest.main()
