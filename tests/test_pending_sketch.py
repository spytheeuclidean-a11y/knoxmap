import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from flask import Flask
from web import common, generation


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


if __name__ == '__main__':
    unittest.main()
