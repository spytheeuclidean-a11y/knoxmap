"""Overpass endpoint rotation, cooldown, tile cache and error text.

Run from the KnoxMap folder:  python -m unittest discover tests
No network: every request is replaced.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

# These tests are about the Overpass route; the default would take the extract.
os.environ["KNOXMAP_OSM_SOURCE"] = "overpass"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from generator import osm  # noqa: E402

A, B, C = osm.ANSWERING_ENDPOINTS[:3]
BLANK = [e for e in osm.OVERPASS_ENDPOINTS if e not in osm.ANSWERING_ENDPOINTS]
BOX = (37.0, -83.0, 37.01, -82.99)


def feat(i=1):
    return osm.OSMFeature(i, "way", {"highway": "residential"},
                          [(37.001, -82.999), (37.002, -82.998)])


class Base(unittest.TestCase):
    def setUp(self):
        osm._cooling.clear()
        p = mock.patch.object(osm.time, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(osm._cooling.clear)


class Order(Base):
    def test_ready_first_blank_last(self):
        order = osm._endpoint_order(0)
        self.assertEqual(order[:len(osm.ANSWERING_ENDPOINTS)],
                         osm.ANSWERING_ENDPOINTS)
        self.assertEqual(order[len(osm.ANSWERING_ENDPOINTS):], BLANK)

    # A resting server used to be asked last, "not dropped", on the grounds that
    # a rest is a guess. One operator counted 22,515 requests in a day, 14,608 of
    # them 504s, from exactly that. A resting server is not asked; the download
    # waits and tries again (fetch_features_tiled) when the rest is over.
    def test_resting_is_not_asked(self):
        osm._note_down(A)
        order = osm._endpoint_order(0)
        self.assertNotIn(A, order)
        self.assertIn(B, order)

    def test_all_resting_asks_none(self):
        for e in osm.ANSWERING_ENDPOINTS:
            osm._note_down(e)
        order = osm._endpoint_order(0)
        for e in osm.ANSWERING_ENDPOINTS:
            self.assertNotIn(e, order)

    def test_rotation_spreads_tiles(self):
        firsts = {osm._endpoint_order(i)[0] for i in range(len(osm.ANSWERING_ENDPOINTS))}
        self.assertEqual(firsts, set(osm.ANSWERING_ENDPOINTS))


class Fetch(Base):
    def test_falls_through_dead_instance(self):
        def ask(endpoint, query, timeout):
            if endpoint == A:
                raise requests.Timeout()
            return [feat()]
        with mock.patch.object(osm, "_ask", ask):
            got = osm.fetch_features(*BOX, first=0)
        self.assertEqual(len(got), 1)
        self.assertTrue(osm._is_cooling(A))

    def test_busy_instance_goes_on_cooldown(self):
        def ask(endpoint, query, timeout):
            if endpoint == A:
                raise osm.OverpassError("HTTP 429", busy=True)
            return [feat()]
        with mock.patch.object(osm, "_ask", ask):
            osm.fetch_features(*BOX, first=0)
        self.assertTrue(osm._is_cooling(A))

    def test_one_blank_is_not_believed(self):
        def ask(endpoint, query, timeout):
            if endpoint in BLANK:
                return []
            raise requests.Timeout()
        with mock.patch.object(osm, "_ask", ask):
            with self.assertRaises(osm.OverpassError):
                osm.fetch_features(*BOX)

    def test_two_blanks_are_believed(self):
        def ask(endpoint, query, timeout):
            return []
        with mock.patch.object(osm, "_ask", ask):
            self.assertEqual(osm.fetch_features(*BOX), [])

    def test_error_names_every_instance_asked(self):
        def ask(endpoint, query, timeout):
            raise requests.Timeout()
        with mock.patch.object(osm, "_ask", ask):
            with self.assertRaises(osm.OverpassError) as cm:
                osm.fetch_features(*BOX)
        for e in osm.OVERPASS_ENDPOINTS:
            self.assertIn(e.split("/")[2], str(cm.exception))


class TileCache(Base):
    def test_roundtrip_and_miss(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(osm, "TILE_CACHE_DIR", d):
            self.assertIsNone(osm._tile_cache_get(BOX))
            osm._tile_cache_put(BOX, [feat(7)])
            got = osm._tile_cache_get(BOX)
            self.assertEqual([f.osm_id for f in got], [7])
            self.assertIsNone(osm._tile_cache_get((37.0, -83.0, 37.02, -82.99)))

    def test_stale_tile_is_ignored(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(osm, "TILE_CACHE_DIR", d):
            osm._tile_cache_put(BOX, [feat()])
            old = osm.time.time() - osm.TILE_CACHE_MAX_AGE_S - 10
            os.utime(osm._tile_cache_file(BOX), (old, old))
            self.assertIsNone(osm._tile_cache_get(BOX))

    def test_cached_tile_skips_network(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(osm, "TILE_CACHE_DIR", d), \
                mock.patch.object(osm, "check_endpoints", lambda *a: None):
            osm._tile_cache_put(BOX, [feat(3)])
            with mock.patch.object(osm, "_ask", side_effect=AssertionError):
                got = osm.fetch_features_tiled(*BOX, max_tile_km2=100)
            self.assertEqual([f.osm_id for f in got], [3])

    def _expired(self, box):
        osm._tile_cache_put(box, [feat(5)])
        old = osm.time.time() - osm.TILE_CACHE_MAX_AGE_S - 10
        os.utime(osm._tile_cache_file(box), (old, old))

    def test_old_tile_is_used_when_every_server_is_down(self):
        with tempfile.TemporaryDirectory() as d,                 mock.patch.object(osm, "TILE_CACHE_DIR", d),                 mock.patch.object(osm, "check_endpoints", lambda *a: None),                 mock.patch.object(osm, "_retry_pause", lambda a: 0),                 mock.patch.object(osm, "_local_features", lambda *a: []),                 mock.patch.object(osm, "_ask", side_effect=requests.ConnectionError("down")):
            self._expired(BOX)
            osm.STALE_TILES_USED.clear()
            notes = []
            got = osm.fetch_features_tiled(*BOX, max_tile_km2=100,
                                           progress=lambda *a: notes.append(a[-1] if len(a) > 2 else ""))
            self.assertEqual([f.osm_id for f in got], [5])
            self.assertEqual(osm.STALE_TILES_USED, [1])
            self.assertTrue(any("earlier download" in n for n in notes))

    def test_a_map_with_a_missing_tile_is_not_patched_up_from_old_ones(self):
        # Four tiles, only one of them kept: a hole would come out as empty ground.
        with tempfile.TemporaryDirectory() as d,                 mock.patch.object(osm, "TILE_CACHE_DIR", d),                 mock.patch.object(osm, "check_endpoints", lambda *a: None),                 mock.patch.object(osm, "_retry_pause", lambda a: 0),                 mock.patch.object(osm, "_local_features", lambda *a: []),                 mock.patch.object(osm, "_ask", side_effect=requests.ConnectionError("down")):
            d_lat, d_lon = (37.01 - 37.0) / 2, (-82.99 + 83.0) / 2
            self._expired((37.0, -83.0, 37.0 + d_lat, -83.0 + d_lon))  # one of the four
            with self.assertRaises(osm.OverpassError):
                osm.fetch_features_tiled(37.0, -83.0, 37.01, -82.99, max_tile_km2=0.3)


class Explain(unittest.TestCase):
    def test_busy_message_is_plain(self):
        text = osm.explain(osm.OverpassError("every Overpass endpoint failed"))
        self.assertIn("Wait a few minutes", text)
        self.assertIn("Details:", text)

    def test_too_big_message(self):
        self.assertIn("smaller area",
                      osm.explain(osm.OverpassError("x", too_big=True)))

    def test_network_message(self):
        self.assertIn("internet", osm.explain(requests.ConnectionError("x")))


class QueryFilters(unittest.TestCase):
    def test_fetches_entrance_nodes(self):
        self.assertIn('node["entrance"]', osm.OVERPASS_FILTERS)
        self.assertIn('node["entrance"]', osm._build_query(*BOX))
        # 14: gate nodes, so a fence has a way through it.
        self.assertEqual(osm.FILTERS_VERSION, 14)

    def test_fetches_the_gates_on_a_fence(self):
        # A fence is drawn as one line with the gate as a node on it, so
        # without these every drive and footpath through a fence was walled.
        self.assertIn('node["barrier"~"^(gate|lift_gate|swing_gate|kissing_gate|'
                      'cattle_grid|stile|entrance|bollard)$"]', osm.OVERPASS_FILTERS)
        self.assertIn('"barrier"~', osm._build_query(*BOX))

    def test_fetches_mapped_rooms(self):
        self.assertIn('way["indoor"~"^(room|corridor)$"]', osm.OVERPASS_FILTERS)
        self.assertIn('"indoor"~', osm._build_query(*BOX))


if __name__ == "__main__":
    unittest.main()
