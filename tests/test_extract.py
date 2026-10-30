"""Map data from a downloaded regional extract instead of live Overpass queries."""
import os
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
        open(path, "wb").write(b"x")
        with mock.patch.object(extract.requests, "get", side_effect=AssertionError("asked")):
            self.assertEqual(extract._download(self.REGION, lambda *a: None, None), path)

    def test_a_missing_one_is_downloaded_and_kept(self):
        with mock.patch.object(extract.requests, "get", lambda *a, **k: self.response()):
            path = extract._download(self.REGION, lambda *a: None, None)
        self.assertEqual(open(path, "rb").read(), b"data")
        self.assertFalse(os.path.exists(path + ".part"))

    def test_an_old_one_is_asked_about_and_kept_on_304(self):
        path = os.path.join(self.dir, "land.osm.pbf")
        open(path, "wb").write(b"old")
        old = time.time() - 40 * 86400
        os.utime(path, (old, old))
        seen = {}

        def get(url, headers=None, **k):
            seen.update(headers or {})
            return self.response(304)

        with mock.patch.object(extract.requests, "get", get):
            extract._download(self.REGION, lambda *a: None, None)
        self.assertIn("If-Modified-Since", seen)
        self.assertEqual(open(path, "rb").read(), b"old")
        self.assertLess(time.time() - os.path.getmtime(path), 100)

    def test_an_old_one_is_used_when_the_server_cannot_be_reached(self):
        path = os.path.join(self.dir, "land.osm.pbf")
        open(path, "wb").write(b"old")
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

    def test_what_is_wanted_and_inside_comes_out(self):
        got = {(e["type"], e["id"]) for e in self.read((9.99, 19.99, 10.03, 20.03))}
        self.assertEqual(got, {("node", 5), ("way", 100), ("relation", 200)})

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
