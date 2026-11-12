import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from flask import Flask
from web import generation, zones


EMPTY = {"type": "FeatureCollection", "features": []}
HOUSE = {"type": "Feature", "properties": {"kind": "house"},
         "geometry": {"type": "Polygon", "coordinates": [[
             [-84.1208, 9.9802], [-84.1206, 9.9802],
             [-84.1206, 9.9804], [-84.1208, 9.9804], [-84.1208, 9.9802]]]}}


class PendingSketch(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        for target, options in (
                ('web.common.OUTPUT_DIR', {'new': self.folder}),
                ('web.generation._too_big_for_memory', {'return_value': None}),
                ('web.generation._population', {'return_value': {}}),
                ('knoxdata.run_layers', {'return_value': {'used': []}})):
            p = patch(target, **options)
            p.start(); self.addCleanup(p.stop)
        app = Flask(__name__)
        app.register_blueprint(generation.bp)
        app.register_blueprint(zones.bp)
        self.client = app.test_client()
        self.settings = {'align_streets': False, 'straight_roads': 0,
                         'fill_frontage': 0, 'tree_density': 0, 'forest_density': 0}
        self.initial = {'mapName': 'test', 'south': 9.9800, 'north': 9.9810,
                        'west': -84.1210, 'east': -84.1200, 'metersPerTile': 1,
                        'settings': self.settings, 'sketch': EMPTY, 'drawnOnly': True}
        response = self.client.post('/api/generate', json=self.initial)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.map = self.folder / 'test'
        self.seen = []

        def build(folder, **kwargs):
            geo = json.loads((Path(folder) / 'test_buildings.geojson').read_text())
            self.seen = geo['features']
            return 0
        p = patch('knoxbuild.build.build', side_effect=build)
        self.build_patch = p
        p.start(); self.addCleanup(p.stop)

    def build(self, sketch):
        return self.client.post('/api/buildings', json={
            'mapName': 'test', 'settings': self.settings,
            'sketch': sketch, 'drawnOnly': True})

    def test_build_applies_a_building_drawn_after_terrain_generation(self):
        response = self.build({'type': 'FeatureCollection', 'features': [HOUSE]})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(len(self.seen), 1)
        self.assertEqual(self.seen[0]['properties']['building'], 'house')
        self.assertIsNotNone(response.get_json().get('terrain'))

    def test_unchanged_drawing_does_not_regenerate_terrain(self):
        with patch.object(generation.renderer, 'render', wraps=generation.renderer.render) as render:
            response = self.build(EMPTY)
        self.assertEqual(response.status_code, 200, response.get_json())
        render.assert_not_called()

    def test_removing_a_drawing_removes_its_old_footprint(self):
        self.assertEqual(self.build({'type': 'FeatureCollection', 'features': [HOUSE]}).status_code, 200)
        self.assertEqual(len(self.seen), 1)
        self.assertEqual(self.build(EMPTY).status_code, 200)
        self.assertEqual(self.seen, [])

    def test_failed_refresh_does_not_start_build_or_forget_pending_drawing(self):
        drawn = {'type': 'FeatureCollection', 'features': [HOUSE]}
        with patch.object(generation.renderer, 'render', side_effect=MemoryError):
            response = self.build(drawn)
        self.assertEqual(response.status_code, 507)
        self.assertEqual(self.seen, [])
        self.assertEqual(self.build(drawn).status_code, 200)
        self.assertEqual(len(self.seen), 1)

    def test_requests_without_a_sketch_preserve_existing_behavior(self):
        with patch.object(generation.renderer, 'render') as render:
            response = self.client.post('/api/buildings', json={'mapName': 'test'})
        self.assertEqual(response.status_code, 200)
        render.assert_not_called()

    def test_pending_drawing_produces_a_real_building_file(self):
        self.build_patch.stop()
        response = self.build({'type': 'FeatureCollection', 'features': [HOUSE]})
        self.assertEqual(response.status_code, 200, response.get_json())
        buildings = list((self.map / 'buildings').glob('*.tbx'))
        self.assertTrue(buildings)
        placements = (self.map / 'test_placements.csv').read_text()
        self.assertIn(',house,', placements)

    def test_settings_write_failure_stops_generation_build_and_recount(self):
        saved = (self.map / 'settings.json').read_bytes()
        with patch('web.mapfiles.knoxfiles.write', side_effect=PermissionError('read only')):
            with patch.object(generation.renderer, 'render') as render:
                response = self.client.post('/api/generate', json=self.initial)
                self.assertEqual(response.status_code, 500)
                self.assertIn('Could not save', response.get_json()['error'])
                render.assert_not_called()
            response = self.build(EMPTY)
            self.assertEqual(response.status_code, 500)
            self.assertEqual(self.seen, [])
            with patch('knoxbuild.population.recount') as recount:
                response = self.client.post('/api/zombies', json={
                    'mapName': 'test', 'settings': self.settings})
                self.assertEqual(response.status_code, 500)
                recount.assert_not_called()
        self.assertEqual((self.map / 'settings.json').read_bytes(), saved)

    def test_failed_drawing_and_edit_saves_report_errors(self):
        with patch('knoxfiles.os.replace', side_effect=PermissionError('read only')):
            for url, data in (('/api/edits/test', {}), ('/api/design/test', {}),
                              ('/api/sketch/test', EMPTY)):
                with self.subTest(url=url):
                    response = self.client.post(url, json=data)
                    self.assertEqual(response.status_code, 500)
                    self.assertIn('could not be saved', response.get_json()['error'])

    def test_failed_drawing_save_stops_generation(self):
        import os
        replace = os.replace

        def fail_sketch(src, dst):
            if str(dst).endswith('_sketch.geojson'):
                raise PermissionError('read only')
            return replace(src, dst)

        with patch('knoxfiles.os.replace', side_effect=fail_sketch):
            with patch.object(generation.renderer, 'render') as render:
                response = self.client.post('/api/generate', json=self.initial)
        self.assertEqual(response.status_code, 500)
        self.assertIn('Could not save', response.get_json()['error'])
        render.assert_not_called()

    def test_failed_osm_download_keeps_a_new_maps_drawing(self):
        drawn = {'type': 'FeatureCollection', 'features': [HOUSE]}
        request = {**self.initial, 'mapName': 'newmap', 'sketch': drawn,
                   'drawnOnly': False}
        with patch.object(generation.osm, 'load_cache', return_value=None), \
                patch.object(generation.osm, 'fetch_features_tiled', side_effect=OSError('offline')):
            response = self.client.post('/api/generate', json=request)
        self.assertEqual(response.status_code, 502)
        saved = self.folder / 'newmap' / 'newmap_sketch.geojson'
        self.assertEqual(json.loads(saved.read_text(encoding='utf-8')), drawn)

    def test_failed_replace_preserves_existing_drawings(self):
        from web import mapfiles

        for save, path, payload in (
                (mapfiles._save_edits, mapfiles._edits_path(self.map), {}),
                (mapfiles._save_design, mapfiles._design_path(self.map), {}),
                (mapfiles._save_sketch, mapfiles._sketch_path(self.map), EMPTY)):
            with self.subTest(path=path):
                path.write_text('{"original": true}', encoding='utf-8')
                with patch('knoxfiles.os.replace', side_effect=PermissionError('read only')):
                    with self.assertRaises(PermissionError):
                        save(self.map, payload)
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'original': True})
                self.assertFalse(Path(str(path) + '.part').exists())


if __name__ == '__main__':
    unittest.main()
