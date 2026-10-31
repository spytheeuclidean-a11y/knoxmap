"""Failures seen in real map downloads, without depending on public servers."""
import unittest
from unittest import mock

from generator import osm
from generator import extract, places


class Endpoints(unittest.TestCase):
    def test_roots_and_backend_aliases_become_one_service(self):
        self.assertEqual(osm.normalise_endpoints([
            'https://overpass-api.de', 'https://z.overpass-api.de/api/interpreter',
            'https://lz4.overpass-api.de/api/interpreter',
            'https://maps.mail.ru', 'http://localhost:12345/api',
        ]), [
            'https://overpass-api.de/api/interpreter',
            'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
            'http://localhost:12345/api/interpreter',
        ])

    def test_custom_interpreter_paths_survive(self):
        self.assertEqual(osm.normalise_endpoints(['https://example.org/custom/api/interpreter/']),
                         ['https://example.org/custom/api/interpreter'])

    def test_bad_urls_are_rejected(self):
        for url in ['ftp://x', 'not a URL', 'https://user:password@example.org']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                osm.normalise_endpoints([url])


class Responses(unittest.TestCase):
    def test_html_with_status_200_is_a_server_error(self):
        r = mock.Mock(status_code=200, text='<html><p>gateway error</p></html>')
        r.json.side_effect = ValueError('Expecting value')
        with mock.patch.object(osm, 'endpoint_ready', return_value=True), \
                mock.patch.object(osm, '_one_at_a_time', return_value=mock.MagicMock()), \
                mock.patch.object(osm.requests, 'post', return_value=r):
            with self.assertRaises(osm.OverpassError) as ctx:
                osm._ask('https://x/api/interpreter', '', 5)
        self.assertTrue(ctx.exception.busy)
        self.assertIn('expected Overpass JSON', str(ctx.exception))

    def test_200_with_a_json_error_is_not_an_empty_map(self):
        r = mock.Mock(status_code=200)
        r.json.return_value = {'error': 'proxy failed'}
        with mock.patch.object(osm, 'endpoint_ready', return_value=True), \
                mock.patch.object(osm, '_one_at_a_time', return_value=mock.MagicMock()), \
                mock.patch.object(osm.requests, 'post', return_value=r):
            with self.assertRaises(osm.OverpassError):
                osm._ask('https://x/api/interpreter', '', 5)

    def test_busy_dispatcher_does_not_multiply_queries_by_splitting_the_area(self):
        r = mock.Mock(status_code=504, text='runtime error: The server is probably too busy')
        r.headers = {}
        with self.assertRaises(osm.OverpassError) as ctx:
            osm.response_payload(r)
        self.assertTrue(ctx.exception.busy)
        self.assertFalse(ctx.exception.too_big)

    def test_partial_json_with_an_unknown_runtime_error_is_rejected(self):
        r = mock.Mock(status_code=200)
        r.json.return_value = {'elements': [], 'remark': 'runtime error: query aborted'}
        with self.assertRaises(osm.OverpassError):
            osm.response_payload(r)

    def test_html_homepage_is_not_a_healthy_status_page(self):
        r = mock.Mock(status_code=200, text='<html>Welcome</html>')
        with mock.patch.object(osm, '_is_refused', return_value=False), \
                mock.patch.object(osm, '_one_at_a_time', return_value=mock.MagicMock()), \
                mock.patch.object(osm.requests, 'get', return_value=r):
            self.assertFalse(osm._probe('https://x/api/interpreter', 0, 0))

    def test_refused_servers_are_never_reintroduced_when_all_are_down(self):
        with mock.patch.object(osm, 'ANSWERING_ENDPOINTS', ['https://x/api/interpreter']), \
                mock.patch.object(osm, 'OVERPASS_ENDPOINTS', ['https://x/api/interpreter']), \
                mock.patch.object(osm, 'endpoint_ready', return_value=False):
            self.assertEqual(osm._endpoint_order(0), [])

    def test_stopping_prevents_the_next_server_request(self):
        with mock.patch.object(osm, '_endpoint_order', return_value=['https://x/api/interpreter']), \
                mock.patch.object(osm, '_ask', side_effect=AssertionError('asked')):
            with self.assertRaises(osm.knoxstop.Stopped):
                osm.fetch_features(0, 0, .01, .01, should_stop=lambda: True)

    def test_landmarks_try_the_next_server_after_an_html_response(self):
        bad = mock.Mock(status_code=200, text='<html>gateway</html>')
        bad.json.side_effect = ValueError('Expecting value')
        good = mock.Mock(status_code=200)
        good.json.return_value = {'elements': [
            {'type': 'node', 'id': 1, 'lat': 1, 'lon': 1,
             'tags': {'name': 'Museum', 'tourism': 'museum'}}]}
        with mock.patch.object(places, 'OVERPASS_ENDPOINTS', ['https://a/api/interpreter',
                                                            'https://b/api/interpreter']), \
                mock.patch.object(osm, 'endpoint_ready', return_value=True), \
                mock.patch.object(osm, '_one_at_a_time', return_value=mock.MagicMock()), \
                mock.patch.object(osm, '_note_down') as down, \
                mock.patch.object(osm, '_note_up'), \
                mock.patch.object(places.requests, 'post', side_effect=[bad, good]):
            self.assertEqual(places.landmarks(0, 0, 2, 2)[0]['name'], 'Museum')
            down.assert_called_once_with('https://a/api/interpreter', None)


if __name__ == '__main__':
    unittest.main()
