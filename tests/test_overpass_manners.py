"""The Overpass client is a guest on shared servers: it rests a server that fails,
leaves one that refuses it alone, honours Retry-After and asks one at a time."""
import os
import tempfile
import time
import unittest
from unittest import mock

from generator import osm

A, B = "https://a.example/api/interpreter", "https://b.example/api/interpreter"


def reply(status, headers=None, text="", payload=None):
    r = mock.Mock()
    r.status_code = status
    r.headers = headers or {}
    r.text = text
    r.json.return_value = payload if payload is not None else {"elements": []}
    return r


class Manners(unittest.TestCase):
    def setUp(self):
        self._saved = (osm.OVERPASS_ENDPOINTS, osm.ANSWERING_ENDPOINTS, dict(osm._cooling),
                       dict(osm._fails), dict(osm._refused), osm.HOST_MIN_GAP_S,
                       osm.EMPTY_NEEDS_SECOND)
        osm.OVERPASS_ENDPOINTS = osm.ANSWERING_ENDPOINTS = [A, B]
        osm._cooling.clear()
        osm._fails.clear()
        osm._refused.clear()
        osm.HOST_MIN_GAP_S = 0
        osm.EMPTY_NEEDS_SECOND = False
        self.tmp = tempfile.mkdtemp()
        self.save = mock.patch.object(osm, "_refused_file",
                                      lambda: os.path.join(self.tmp, "refused.json"))
        self.save.start()
        self.sleep = mock.patch.object(osm.time, "sleep", lambda s: None)
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.save.stop()
        (osm.OVERPASS_ENDPOINTS, osm.ANSWERING_ENDPOINTS, cooling, fails, refused,
         osm.HOST_MIN_GAP_S, osm.EMPTY_NEEDS_SECOND) = self._saved
        osm._cooling.clear(); osm._cooling.update(cooling)
        osm._fails.clear(); osm._fails.update(fails)
        osm._refused.clear(); osm._refused.update(refused)

    def test_a_server_that_504s_is_not_asked_again_while_it_rests(self):
        calls = []

        def post(url, **kw):
            calls.append(url)
            return reply(504) if url == A else reply(200, payload={"elements": [
                {"type": "node", "id": 1, "lat": 1.0, "lon": 1.0, "tags": {"a": "b"}}]})

        with mock.patch.object(osm.requests, "post", post):
            for _ in range(5):
                osm.fetch_features(0.0, 0.0, 0.01, 0.01, first=0)
        self.assertEqual(calls.count(A), 1)

    def test_the_rest_grows_with_each_failure_and_follows_retry_after(self):
        osm._note_down(A)
        first = osm._cooling[A] - time.time()
        osm._note_down(A)
        second = osm._cooling[A] - time.time()
        self.assertGreater(second, first * 1.5)
        osm._note_down(B, retry_after=1800)
        self.assertGreater(osm._cooling[B] - time.time(), 1700)
        osm._note_up(A)
        osm._note_down(A)
        self.assertLess(osm._cooling[A] - time.time(), 130)

    def test_a_refusal_takes_the_server_out_for_good(self):
        def post(url, **kw):
            return reply(403, text="This service is only available to white-listed usages") \
                if url == A else reply(200)

        with mock.patch.object(osm.requests, "post", post):
            osm.fetch_features(0.0, 0.0, 0.01, 0.01, first=0)
        self.assertTrue(osm._is_refused(A))
        self.assertFalse(osm.endpoint_ready(A))
        self.assertNotIn(A, osm._endpoint_order(0))

    def test_when_every_server_rests_nothing_is_asked(self):
        osm._note_down(A)
        osm._note_down(B)
        with mock.patch.object(osm.requests, "post", side_effect=AssertionError("asked")):
            with self.assertRaises(osm.OverpassError) as ctx:
                osm.fetch_features(0.0, 0.0, 0.01, 0.01)
        self.assertTrue(ctx.exception.busy)

    def test_the_probe_reads_the_status_page_not_a_query(self):
        seen = []
        with mock.patch.object(osm.requests, "get",
                               lambda url, **kw: (seen.append(url), reply(200, text="Connected as: 123\nRate limit: 2"))[1]), \
                mock.patch.object(osm.requests, "post", side_effect=AssertionError("query")):
            self.assertTrue(osm._probe(A, 40.0, -74.0))
        self.assertEqual(seen, ["https://a.example/api/status"])

    def test_one_request_at_a_time_to_a_host(self):
        import threading
        osm.HOST_MIN_GAP_S = 0
        inside, worst = [0], [0]
        lock = threading.Lock()

        def post(url, **kw):
            with lock:
                inside[0] += 1
                worst[0] = max(worst[0], inside[0])
            with lock:
                inside[0] -= 1
            return reply(200)

        def go():
            with osm._one_at_a_time(A):
                post(A)

        ts = [threading.Thread(target=go) for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(worst[0], 1)

    def test_the_regional_server_that_asked_us_to_stop_is_gone_from_the_defaults(self):
        self.assertFalse(any("atownsend" in e for e in osm._DEFAULT_ENDPOINTS))


if __name__ == "__main__":
    unittest.main()
