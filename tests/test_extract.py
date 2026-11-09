"""Map data from a downloaded regional extract instead of live Overpass queries."""
import os
import shutil
import struct
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import extract, osm  # noqa: E402

try:
    import osmium
except ImportError:          # the reading tests need it; the rest do not
    osmium = None


def square(lat, lon, size):
    return [(lat, lon), (lat, lon + size), (lat + size, lon + size), (lat + size, lon)]


def write_extract(path):
    """A tiny extract: a building, a bakery, a road far away, and a lake that is
    a relation of one untagged way."""
    w = osmium.SimpleWriter(path)

    def node(i, lat, lon, tags=None):
        w.add_node(osmium.osm.mutable.Node(id=i, location=(lon, lat), tags=tags or {}))

    for i, (la, lo) in enumerate(square(10.0, 20.0, 0.001), 1):
        node(i, la, lo)
    node(5, 10.0005, 20.0005, {"shop": "bakery"})
    node(6, 50.0, 50.0)
    node(7, 50.001, 50.001)
    for i, (la, lo) in enumerate(square(10.01, 20.01, 0.01), 10):
        node(i, la, lo)
    # A lake of four ways, three of them (one by one) beyond a small box.
    for i, (la, lo) in zip((30, 31, 32, 33), ((10.5, 20.5), (10.5, 20.51), (10.9, 20.51), (10.9, 20.5))):
        node(i, la, lo)
    for wid, (a, b) in zip((110, 111, 112, 113), ((30, 31), (31, 32), (32, 33), (33, 30))):
        w.add_way(osmium.osm.mutable.Way(id=wid, nodes=[a, b], tags={}))
    w.add_relation(osmium.osm.mutable.Relation(
        id=201, members=[("w", i, "outer") for i in (110, 111, 112, 113)],
        tags={"type": "multipolygon", "natural": "water"}))
    w.add_way(osmium.osm.mutable.Way(id=100, nodes=[1, 2, 3, 4, 1], tags={"building": "yes"}))
    w.add_way(osmium.osm.mutable.Way(id=101, nodes=[6, 7], tags={"highway": "residential"}))
    w.add_way(osmium.osm.mutable.Way(id=102, nodes=[10, 11, 12, 13, 10], tags={}))
    w.add_relation(osmium.osm.mutable.Relation(
        id=200, members=[("w", 102, "outer")], tags={"type": "multipolygon", "natural": "water"}))
    w.close()


class FilterReading(unittest.TestCase):
    def test_every_overpass_filter_is_understood(self):
        filters = extract.parse_filters(osm.OVERPASS_FILTERS)
        self.assertEqual(len(filters), len(osm.OVERPASS_FILTERS))

    def test_equality_regex_and_presence(self):
        f = extract.Filter('way["natural"="water"]')
        self.assertTrue(f.matches("way", {"natural": "water"}))
        self.assertFalse(f.matches("way", {"natural": "wood"}))
        self.assertFalse(f.matches("node", {"natural": "water"}))
        f = extract.Filter('way["landuse"~"^(forest|grass)$"]')
        self.assertTrue(f.matches("way", {"landuse": "forest"}))
        self.assertFalse(f.matches("way", {"landuse": "forestry"}))
        f = extract.Filter('way["highway"]')
        self.assertTrue(f.matches("way", {"highway": "x"}))
        self.assertFalse(f.matches("way", {}))

    def test_nwr_is_all_three_and_two_tests_both_hold(self):
        f = extract.Filter('nwr["amenity"="fountain"]')
        for kind in ("node", "way", "relation"):
            self.assertTrue(f.matches(kind, {"amenity": "fountain"}))
        f = extract.Filter('node["place"~"^(city|town)$"]["population"]')
        self.assertTrue(f.matches("node", {"place": "town", "population": "9"}))
        self.assertFalse(f.matches("node", {"place": "town"}))


class GeometryBounds(unittest.TestCase):
    def test_short_and_long_lines_in_either_byte_order(self):
        for count in (2, 64, 65, 1000):
            for endian, marker in (("<", 1), (">", 0)):
                points = [(float(i - 20), float(10 - i)) for i in range(count)]
                wkb = struct.pack(endian + "BII", marker, 2, count)
                wkb += struct.pack(endian + f"{count * 2}d", *[v for p in points for v in p])
                with self.subTest(count=count, endian=endian):
                    self.assertEqual(extract._line_bounds(wkb.hex()),
                                     (-20., float(11 - count), float(count - 21), 10.))

    def test_invalid_or_different_geometries_are_rejected(self):
        for wkb in (b'', b'\x01', struct.pack('<BII', 1, 2, 0),
                    struct.pack('<BII', 1, 3, 1)):
            with self.subTest(wkb=wkb), self.assertRaises(ValueError):
                extract._line_bounds(wkb.hex())


class WhichExtract(unittest.TestCase):
    INDEX = {"features": [
        {"properties": {"id": "world", "name": "World", "urls": {"pbf": "https://x/world.pbf"}},
         "geometry": {"type": "Polygon", "coordinates": [[[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]]]}},
        {"properties": {"id": "land", "name": "Land", "parent": "world", "urls": {"pbf": "https://x/land.pbf"}},
         "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}},
        {"properties": {"id": "east", "name": "East", "parent": "land", "urls": {"pbf": "https://x/east.pbf"}},
         "geometry": {"type": "Polygon", "coordinates": [[[5, 0], [10, 0], [10, 10], [5, 10], [5, 0]]]}},
        {"properties": {"id": "west", "name": "West", "parent": "land", "urls": {"pbf": "https://x/west.pbf"}},
         "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [5, 0], [5, 10], [0, 10], [0, 0]]]}},
    ]}

    def test_the_smallest_extract_that_holds_the_box(self):
        got = extract.regions_for(1, 6, 2, 7, self.INDEX)
        self.assertEqual([r["id"] for r in got], ["east"])

    def test_a_box_across_two_halves_takes_the_parent_that_holds_it(self):
        got = extract.regions_for(1, 4, 2, 6, self.INDEX)
        self.assertEqual([r["id"] for r in got], ["land"])

    def test_a_box_across_two_extracts_with_no_parent_takes_both(self):
        halves = {"features": [f for f in self.INDEX["features"] if f["properties"]["id"] in ("east", "west")]}
        got = extract.regions_for(1, 4, 2, 6, halves)
        self.assertEqual({r["id"] for r in got}, {"east", "west"})

    def test_a_box_across_two_states_takes_the_states_not_the_country(self):
        # Geofabrik's United States polygon is 3,516 against Indiana's 10 and
        # Kentucky's 11: a box over the Ohio River is held by no single state
        # and by the country, and the two states are the cheaper read. The
        # country used to win this one, which is a 12 GB download.
        index = {"features": [
            {"properties": {"id": "country", "name": "Country", "urls": {"pbf": "https://x/country.pbf"}},
             "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]]}},
            {"properties": {"id": "a", "name": "A", "parent": "country", "urls": {"pbf": "https://x/a.pbf"}},
             "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [5, 0], [5, 10], [0, 10], [0, 0]]]}},
            {"properties": {"id": "b", "name": "B", "parent": "country", "urls": {"pbf": "https://x/b.pbf"}},
             "geometry": {"type": "Polygon", "coordinates": [[[5, 0], [10, 0], [10, 10], [5, 10], [5, 0]]]}},
        ]}
        got = extract.regions_for(1, 4, 2, 6, index)
        self.assertEqual([r["id"] for r in got], ["a", "b"])

    def test_a_box_in_the_sea_takes_the_widest_that_holds_it(self):
        got = extract.regions_for(-50, 100, -49, 101, self.INDEX)
        self.assertEqual([r["id"] for r in got], ["world"])


class Download(unittest.TestCase):
    REGION = {"id": "land", "name": "Land", "url": "https://x/land.pbf"}

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.patch = mock.patch.object(extract, "cache_dir", lambda: self.dir)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def response(self, status=200, body=b"data"):
        r = mock.Mock()
        r.status_code = status
        r.headers = {"Content-Length": str(len(body))}
        r.iter_content = lambda n: iter([body])
        r.raise_for_status = lambda: None if status < 400 else (_ for _ in ()).throw(
            extract.requests.HTTPError(str(status)))
        return r

    def test_a_fresh_copy_is_used_without_asking(self):
        path = os.path.join(self.dir, "land.osm.pbf")
        with open(path, "wb") as f:
            f.write(b"x")
        with mock.patch.object(extract.requests, "get", side_effect=AssertionError("asked")):
            self.assertEqual(extract._download(self.REGION, lambda *a: None, None), path)

    def test_a_missing_one_is_downloaded_and_kept(self):
        with mock.patch.object(extract.requests, "get", lambda *a, **k: self.response()):
            path = extract._download(self.REGION, lambda *a: None, None)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"data")
        self.assertFalse(os.path.exists(path + ".part"))

    def test_an_old_one_is_asked_about_and_kept_on_304(self):
        path = os.path.join(self.dir, "land.osm.pbf")
        with open(path, "wb") as f:
            f.write(b"old")
        old = time.time() - 40 * 86400
        os.utime(path, (old, old))
        seen = {}

        def get(url, headers=None, **k):
            seen.update(headers or {})
            return self.response(304)

        with mock.patch.object(extract.requests, "get", get):
            extract._download(self.REGION, lambda *a: None, None)
        self.assertIn("If-Modified-Since", seen)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"old")
        self.assertLess(time.time() - os.path.getmtime(path), 100)

    def test_an_old_one_is_used_when_the_server_cannot_be_reached(self):
        path = os.path.join(self.dir, "land.osm.pbf")
        with open(path, "wb") as f:
            f.write(b"old")
        old = time.time() - 40 * 86400
        os.utime(path, (old, old))
        with mock.patch.object(extract.requests, "get",
                               side_effect=extract.requests.ConnectionError("down")):
            self.assertEqual(extract._download(self.REGION, lambda *a: None, None), path)

    def test_none_and_no_server_is_unavailable(self):
        with mock.patch.object(extract.requests, "get",
                               side_effect=extract.requests.ConnectionError("down")):
            with self.assertRaises(extract.ExtractUnavailable):
                extract._download(self.REGION, lambda *a: None, None)


@unittest.skipUnless(osmium, "pyosmium is not installed")
class ReadingAnExtract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "t.osm.pbf")
        write_extract(cls.path)
        cls.filters = extract.parse_filters(osm.OVERPASS_FILTERS)

    def read(self, bbox):
        with mock.patch.object(extract, "cache_dir", lambda: self.dir):
            return extract._read(self.path, self.filters, bbox, lambda *a: None, None)

    @unittest.skipUnless(os.name == "nt", "Windows native paths")
    def test_unicode_directory_with_disk_index(self):
        directory = tempfile.mkdtemp(dir=self.dir, prefix="\u00c1rea-\u65e5\u672c-")
        path = os.path.join(directory, "test.osm.pbf")
        shutil.copyfile(self.path, path)
        try:
            extract._native_path(path)
        except extract.ExtractUnavailable:
            self.skipTest("Windows short paths are unavailable on this volume")
        with mock.patch.object(extract, "cache_dir", return_value=directory), \
             mock.patch.object(extract, "BIG_EXTRACT_BYTES", 0):
            got = extract._read(path, self.filters, (9.99, 19.99, 10.03, 20.03),
                                lambda *a: None, None)
        self.assertEqual({(e["type"], e["id"]) for e in got},
                         {("node", 5), ("way", 100), ("relation", 200)})

    @unittest.skipUnless(os.name == "nt", "Windows native paths")
    def test_unavailable_short_path_falls_back(self):
        with mock.patch("ctypes.windll.kernel32.GetShortPathNameW", return_value=0):
            with self.assertRaisesRegex(extract.ExtractUnavailable, "Overpass"):
                extract._native_path("C:/\u65e5\u672c/test.osm.pbf")

    def test_what_is_wanted_and_inside_comes_out(self):
        got = {(e["type"], e["id"]) for e in self.read((9.99, 19.99, 10.03, 20.03))}
        self.assertEqual(got, {("node", 5), ("way", 100), ("relation", 200)})

    def test_a_file_scan_reports_activity_without_a_guessed_percentage(self):
        reports = []
        with mock.patch.object(extract, "_download", return_value=self.path):
            extract.elements(9.99, 19.99, 10.03, 20.03,
                             regions=[{"name": "test"}],
                             progress=lambda done, total, note: reports.append((done, total, note)))
        self.assertTrue(any(total == 0 and "reading the map data" in note
                            for _done, total, note in reports))

    def test_what_is_far_away_is_left_out(self):
        got = {(e["type"], e["id"]) for e in self.read((9.99, 19.99, 10.002, 20.002))}
        self.assertEqual(got, {("node", 5), ("way", 100)})

    def test_the_relation_carries_its_member_ways_geometry(self):
        rel = next(e for e in self.read((9.99, 19.99, 10.03, 20.03)) if e["type"] == "relation")
        self.assertEqual(rel["members"][0]["role"], "outer")
        self.assertEqual(len(rel["members"][0]["geometry"]), 5)

    def test_it_parses_like_an_overpass_answer(self):
        feats = osm._parse({"elements": self.read((9.99, 19.99, 10.03, 20.03))})
        kinds = sorted(f.kind for f in feats)
        self.assertEqual(kinds, ["node", "relation", "way"])
        building = next(f for f in feats if f.kind == "way")
        self.assertEqual(building.tags, {"building": "yes"})
        self.assertEqual(building.geometry[0], building.geometry[-1])

    def test_a_lake_with_members_outside_the_box_comes_back_whole(self):
        els = self.read((10.49, 20.49, 10.51, 20.52))
        lake = next(e for e in els if e["type"] == "relation" and e["id"] == 201)
        self.assertEqual(sorted(m["ref"] for m in lake["members"]), [110, 111, 112, 113])
        self.assertTrue(all(len(m["geometry"]) == 2 for m in lake["members"]))

    def test_a_relation_touching_the_box_only_by_one_member_is_whole(self):
        # The lake reaches the box with its corner; its far corners are outside,
        # and the ring still comes back complete.
        rel = next(e for e in self.read((10.0, 20.0, 10.011, 20.011)) if e["type"] == "relation")
        self.assertEqual(len(rel["members"][0]["geometry"]), 5)


@unittest.skipUnless(osmium, "pyosmium is not installed")
class ExtractEncoding(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def write_names(self, invalid=None):
        path = os.path.join(self.folder.name, str(invalid)+'.osm.pbf')
        name = 'İstanbul 東京 Łódź'

        def tags(kind, values):
            return dict(values, name=b'x'*143+b'\xfd' if kind == invalid else name)

        with osmium.SimpleWriter(path) as writer:
            for i, location in enumerate(((20, 10), (20.001, 10), (20, 10.001)), 1):
                writer.add_node(osmium.osm.mutable.Node(id=i, location=location))
            writer.add_node(osmium.osm.mutable.Node(id=10, location=(20, 10),
                            tags=tags('node', {'shop': 'bakery'})))
            writer.add_way(osmium.osm.mutable.Way(id=20, nodes=[1, 2, 3, 1],
                           tags=tags('way', {'building': 'yes'})))
            writer.add_relation(osmium.osm.mutable.Relation(id=30, members=[('w', 20, 'outer')],
                                tags=tags('relation', {'type': 'multipolygon', 'natural': 'water'})))
        return path

    def test_non_english_names_survive_reading_and_cache(self):
        path = self.write_names()
        with mock.patch.object(extract, '_download', return_value=path):
            elements = extract.elements(9.99, 19.99, 10.01, 20.01, regions=[{'name': 'test'}])
        self.assertEqual({el['type'] for el in elements}, {'node', 'way', 'relation'})
        features = osm._parse({'elements': elements})
        cache = os.path.join(self.folder.name, 'names.json.gz')
        bbox = (9.99, 19.99, 10.01, 20.01)
        osm.save_cache(cache, bbox, features)
        self.assertEqual([f.tags['name'] for f in osm.load_cache(cache, bbox)],
                         ['İstanbul 東京 Łódź'] * 3)

    def test_invalid_tag_text_marks_each_extract_unavailable_without_changing_it(self):
        for kind in ('node', 'way', 'relation'):
            with self.subTest(kind=kind):
                path = self.write_names(kind)
                with open(path, 'rb') as stream:
                    before = stream.read()
                with mock.patch.object(extract, '_download', return_value=path), \
                        self.assertLogs(extract.knoxlog.log, level='WARNING') as log:
                    with self.assertRaises(extract.ExtractUnavailable) as ctx:
                        extract.elements(9.99, 19.99, 10.01, 20.01, regions=[{'name': 'test'}])
                self.assertIn('UTF-8', str(ctx.exception))
                self.assertIsInstance(ctx.exception.__cause__, UnicodeDecodeError)
                self.assertIn(path, log.output[0])
                self.assertIn('0xfd', log.output[0])
                with open(path, 'rb') as stream:
                    self.assertEqual(stream.read(), before)

    def test_auto_uses_overpass_without_returning_partial_extract_data(self):
        paths = [self.write_names(), self.write_names('way')]
        expected = [osm.OSMFeature(99, 'node', {'name': '東京'}, [(10, 20)])]
        with mock.patch.dict(os.environ, {'KNOXMAP_OSM_SOURCE': 'auto'}), \
                mock.patch.object(extract, '_index', return_value={}), \
                mock.patch.object(extract, 'regions_for', return_value=[{'name': 'first'}, {'name': 'second'}]), \
                mock.patch.object(extract, '_download', side_effect=paths), \
                mock.patch.object(osm, 'check_endpoints'), \
                mock.patch.object(osm, '_tile_cache_get', return_value=None), \
                mock.patch.object(osm, '_tile_cache_put'), \
                mock.patch.object(osm, '_fetch_splitting', return_value=expected) as fetch, \
                self.assertLogs(extract.knoxlog.log, level='WARNING'):
            result = osm.fetch_features_tiled(10, 20, 10.001, 20.001)
        self.assertEqual(result, expected)
        fetch.assert_called_once()

    def test_extract_only_explains_the_bad_file_without_contacting_overpass(self):
        path = self.write_names('relation')
        with mock.patch.dict(os.environ, {'KNOXMAP_OSM_SOURCE': 'extract'}), \
                mock.patch.object(extract, '_index', return_value={}), \
                mock.patch.object(extract, 'regions_for', return_value=[{'name': 'test'}]), \
                mock.patch.object(extract, '_download', return_value=path), \
                mock.patch.object(osm, '_fetch_splitting', side_effect=AssertionError('asked Overpass')), \
                self.assertLogs(extract.knoxlog.log, level='WARNING'):
            with self.assertRaises(osm.OverpassError) as ctx:
                osm.fetch_features_tiled(10, 20, 10.001, 20.001)
        self.assertIn('relation.osm.pbf', str(ctx.exception))
        self.assertIn('UTF-8', str(ctx.exception))
        self.assertIn('fresh copy', str(ctx.exception))


class WhichSource(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.pop("KNOXMAP_OSM_SOURCE", None)

    def tearDown(self):
        os.environ.pop("KNOXMAP_OSM_SOURCE", None)
        if self.old is not None:
            os.environ["KNOXMAP_OSM_SOURCE"] = self.old

    def test_the_default_is_auto(self):
        with mock.patch.object(osm.knoxpaths, "load_config", lambda: {}):
            self.assertEqual(osm.osm_source(), "auto")

    def test_config_and_environment_choose(self):
        with mock.patch.object(osm.knoxpaths, "load_config", lambda: {"osm_source": "overpass"}):
            self.assertEqual(osm.osm_source(), "overpass")
            os.environ["KNOXMAP_OSM_SOURCE"] = "extract"
            self.assertEqual(osm.osm_source(), "extract")

    def test_auto_takes_the_extract_and_never_asks_overpass(self):
        os.environ["KNOXMAP_OSM_SOURCE"] = "auto"
        sentinel = [osm.OSMFeature(1, "way", {}, [(0.0, 0.0)])]
        with mock.patch.object(extract, "available", lambda: True), \
                mock.patch.object(extract, "features", lambda *a, **k: sentinel), \
                mock.patch.object(osm.requests, "post", side_effect=AssertionError("asked Overpass")):
            self.assertEqual(osm.fetch_features_tiled(50.0, 5.0, 50.2, 5.3), sentinel)

    def test_auto_falls_back_to_overpass_when_no_extract_can_be_used(self):
        os.environ["KNOXMAP_OSM_SOURCE"] = "auto"
        asked = []
        with mock.patch.object(extract, "available", lambda: False), \
                mock.patch.object(osm, "check_endpoints", lambda *a: None),                 mock.patch.object(osm, "_tile_cache_get", lambda *a, **k: None),                 mock.patch.object(osm, "_tile_cache_put", lambda *a, **k: None), \
                mock.patch.object(osm, "_fetch_splitting",
                                  lambda *a, **k: asked.append(a) or []):
            osm.fetch_features_tiled(50.0, 5.0, 50.01, 5.01)
        self.assertTrue(asked)

    def test_extract_only_says_so_instead_of_asking_overpass(self):
        os.environ["KNOXMAP_OSM_SOURCE"] = "extract"
        with mock.patch.object(extract, "available", lambda: False), \
                mock.patch.object(osm.requests, "post", side_effect=AssertionError("asked Overpass")):
            with self.assertRaises(osm.OverpassError) as ctx:
                osm.fetch_features_tiled(50.0, 5.0, 50.2, 5.3)
        self.assertIn("extract", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
