"""A picked extract, and the check that says whether it will work.

A regional file covers a place; a developer may have cut one by hand, or
downloaded a county rather than the state. Choosing it takes the guess out, and
checking it says what is in the file before a map is built from nothing.
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import osmium

from generator import extract, pbfcheck


def tiny_pbf(path, buildings=True, roads=True, extra=()):
    """A square of nodes, one building, one street, inside 10,20."""
    w = osmium.SimpleWriter(path)
    nodes = [(10.000, 20.000), (10.002, 20.000), (10.002, 20.002), (10.000, 20.002)]
    for i, (lat, lon) in enumerate(nodes, 1):
        w.add_node(osmium.osm.mutable.Node(id=i, location=(lon, lat)))
    if buildings:
        w.add_way(osmium.osm.mutable.Way(id=10, nodes=[1, 2, 3, 4, 1],
                                        tags={"building": "yes"}))
    if roads:
        w.add_node(osmium.osm.mutable.Node(id=5, location=(20.001, 10.001)))
        w.add_way(osmium.osm.mutable.Way(id=11, nodes=[1, 5],
                                        tags={"highway": "residential"}))
    for osm_id, tags in extra:
        w.add_node(osmium.osm.mutable.Node(id=osm_id, location=(20.0015, 10.0015),
                                          tags=tags))
    w.close()
    return path


class Temp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.old = os.environ.pop("KNOXMAP_PBF_FILE", None)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        os.environ.pop("KNOXMAP_PBF_FILE", None)
        if self.old is not None:
            os.environ["KNOXMAP_PBF_FILE"] = self.old

    def build(self, name="t.osm.pbf", **kw):
        return tiny_pbf(os.path.join(self.dir, name), **kw)


class TheCheck(Temp):
    def test_a_good_file_is_usable(self):
        result = pbfcheck.check(self.build())
        self.assertTrue(result["ok"], result["problems"])
        self.assertGreaterEqual(result["stats"]["nodes"], 4)
        self.assertEqual(result["tags"].get("building"), 1)
        self.assertIn("usable", pbfcheck.report_text(result))

    def test_a_file_with_no_buildings_is_refused(self):
        result = pbfcheck.check(self.build(buildings=False))
        self.assertFalse(result["ok"])
        self.assertTrue(any("buildings" in p for p in result["problems"]))

    def test_a_file_with_no_roads_is_refused(self):
        result = pbfcheck.check(self.build(roads=False))
        self.assertTrue(any("roads" in p for p in result["problems"]))

    def test_an_empty_file_is_refused(self):
        path = os.path.join(self.dir, "empty.osm.pbf")
        open(path, "wb").close()
        result = pbfcheck.check(path)
        self.assertFalse(result["ok"])
        self.assertTrue(any("empty" in p for p in result["problems"]))

    def test_something_that_is_not_an_extract_is_refused(self):
        path = os.path.join(self.dir, "notes.osm.pbf")
        with open(path, "wb") as fh:
            fh.write(b"this is not an extract, it is a text file\n" * 40)
        result = pbfcheck.check(path)
        self.assertFalse(result["ok"])
        self.assertTrue(any("header" in p for p in result["problems"]))

    def test_a_file_that_misses_the_area_is_refused(self):
        result = pbfcheck.check(self.build(), bbox=(40.0, 50.0, 40.1, 50.1))
        self.assertFalse(result["ok"])
        self.assertTrue(any("does not overlap" in p for p in result["problems"]))

    def test_a_file_that_covers_the_area_passes(self):
        result = pbfcheck.check(self.build(), bbox=(10.0005, 20.0005, 10.0015, 20.0015))
        self.assertTrue(result["ok"], result["problems"])


class ThePickedFile(Temp):
    def test_a_picked_file_becomes_the_region(self):
        path = self.build()
        os.environ["KNOXMAP_PBF_FILE"] = path
        self.assertTrue(extract.forced())
        region = extract.local_region()
        self.assertEqual(region["path"], os.path.abspath(path))
        self.assertTrue(region["local"])

    def test_nothing_picked_means_no_region(self):
        self.assertFalse(extract.forced())
        self.assertIsNone(extract.local_region())

    def test_the_picked_file_is_read_without_asking_geofabrik(self):
        path = self.build()
        os.environ["KNOXMAP_PBF_FILE"] = path
        with mock.patch.object(extract, "_index",
                               side_effect=AssertionError("asked Geofabrik")):
            elements = extract.elements(10.0, 20.0, 10.002, 20.002)
        self.assertTrue(elements)
        self.assertTrue(all(el["type"] in ("node", "way", "relation") for el in elements))

    def test_a_picked_file_that_is_gone_stops_the_map(self):
        os.environ["KNOXMAP_PBF_FILE"] = os.path.join(self.dir, "missing.osm.pbf")
        with self.assertRaises(extract.ExtractUnavailable) as caught:
            extract.elements(10.0, 20.0, 10.002, 20.002)
        self.assertIn("not there", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class TheRoutes(Temp):
    """The two endpoints the Tools panel talks to."""

    def setUp(self):
        super().setUp()
        import app as A
        self.client = A.app.test_client()

    def test_check_answers_with_the_report(self):
        res = self.client.post("/api/tools/pbf/check", json={"path": self.build()})
        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertTrue(data["ok"], data["problems"])
        self.assertIn("usable", data["report"])

    def test_check_defaults_to_the_saved_file(self):
        os.environ["KNOXMAP_PBF_FILE"] = self.build()
        data = self.client.post("/api/tools/pbf/check", json={}).get_json()
        self.assertTrue(data["ok"], data["problems"])

    def test_check_of_nothing_is_a_report_not_a_crash(self):
        data = self.client.post("/api/tools/pbf/check", json={"path": ""}).get_json()
        self.assertFalse(data["ok"])
        self.assertTrue(data["problems"])

    def test_saving_a_path_that_is_not_there_is_refused(self):
        import knoxpaths
        with mock.patch.object(knoxpaths, "update_config") as save:
            res = self.client.post("/api/overpass",
                                   json={"pbf_file": os.path.join(self.dir, "no.osm.pbf")})
        self.assertEqual(res.status_code, 400)
        save.assert_not_called()

    def test_saving_and_clearing_the_file(self):
        import knoxpaths
        path = self.build()
        with mock.patch.object(knoxpaths, "update_config") as save:
            self.client.post("/api/overpass", json={"pbf_file": path})
            save.assert_called_with({"pbf_file": os.path.abspath(path)})
            self.client.post("/api/overpass", json={"pbf_file": ""})
            save.assert_called_with({"pbf_file": ""})
