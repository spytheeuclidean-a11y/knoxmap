import tempfile
import unittest
from pathlib import Path

from generator import osm
from knoxbuild.settings import Settings
from web.checks import RENDER_SETTINGS

try:
    import osmium
except ImportError:
    osmium = None


class ProposedRoads(unittest.TestCase):
    def test_switch_selects_and_types_proposed_roads_without_mutating_cache(self):
        features = [
            osm.OSMFeature(1, 'way', {'highway': 'residential'}, [(1, 1), (2, 2)]),
            osm.OSMFeature(2, 'way', {'highway': 'proposed', 'proposed': 'primary'}, [(1, 1), (2, 2)]),
            osm.OSMFeature(3, 'way', {'proposed:highway': 'footway'}, [(1, 1), (2, 2)]),
            osm.OSMFeature(4, 'way', {'highway': 'proposed'}, [(1, 1), (2, 2)]),
        ]
        with tempfile.TemporaryDirectory() as directory:
            cache = str(Path(directory) / 'map.json.gz')
            box = (0, 0, 3, 3)
            osm.save_cache(cache, box, features)
            loaded = osm.load_cache(cache, box)
            self.assertEqual([f.osm_id for f in osm.proposed_roads(loaded, False)], [1])
            selected = osm.proposed_roads(loaded, True)
            self.assertEqual([osm.classify(f.tags) for f in selected],
                             ['road_minor', 'road_major', 'paved_path', 'road_minor'])
            self.assertEqual(loaded[1].tags['highway'], 'proposed')
            self.assertEqual(osm.load_cache(cache, box)[1].tags['highway'], 'proposed')

    def test_queries_and_settings_include_option(self):
        self.assertIn('way["proposed:highway"]', osm._build_query(0, 0, 1, 1))
        self.assertEqual(Settings().include_proposed_roads, 0)
        self.assertEqual(Settings.from_dict({'include_proposed_roads': 1}).include_proposed_roads, 1)
        self.assertIn('include_proposed_roads', RENDER_SETTINGS)
        self.assertIsNone(osm.classify({'highway': 'proposed'}))

    @unittest.skipUnless(osmium, 'pyosmium is not installed')
    def test_extract_finds_prefixed_proposal(self):
        from generator import extract
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'map.osm.pbf')
            with osmium.SimpleWriter(path) as writer:
                writer.add_node(osmium.osm.mutable.Node(id=1, location=(1, 1)))
                writer.add_node(osmium.osm.mutable.Node(id=2, location=(1.001, 1.001)))
                writer.add_way(osmium.osm.mutable.Way(id=3, nodes=[1, 2],
                                                     tags={'proposed:highway': 'primary'}))
            found = extract._read(path, extract.parse_filters(osm.OVERPASS_FILTERS),
                                  (0, 0, 2, 2), lambda *args: None, None)
            features = osm.proposed_roads(osm._parse({'elements': found}), True)
            self.assertEqual([(f.osm_id, osm.classify(f.tags)) for f in features],
                             [(3, 'road_major')])
