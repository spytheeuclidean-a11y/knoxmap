"""A drawn feature has to be a real OSM feature, or it is drawn and then lost.

Everything after the drawing - the ground, the buildings, the paper map, the
compiled cells - reads tags and nothing else. A palette entry whose tags say
nothing to `classify` puts a shape on the page that is simply missing from the
finished map, with no error anywhere, so the table is checked against
`classify` itself rather than against the comment beside it.
"""
import unittest

from generator import sketch
from generator.osm import classify


def collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def drawn(kind, geometry, coordinates, **props):
    return {"type": "Feature",
            "properties": {"kind": kind, **props},
            "geometry": {"type": geometry, "coordinates": coordinates}}


SQUARE = [[[0.0, 0.0], [0.001, 0.0], [0.001, 0.001], [0.0, 0.001], [0.0, 0.0]]]
LINE = [[0.0, 0.0], [0.001, 0.001]]


class Palette(unittest.TestCase):
    def test_every_entry_reaches_the_map(self):
        lost = [e[0] for e in sketch.PALETTE if sketch.category_of(e[0]) is None]
        self.assertEqual(lost, [], "drawn, then missing from the finished map")

    def test_ids_are_unique(self):
        ids = [e[0] for e in sketch.PALETTE]
        self.assertEqual(len(ids), len(set(ids)))

    def test_geometry_is_one_the_window_can_draw(self):
        for entry_id, _label, geometry, _tags in sketch.PALETTE:
            with self.subTest(entry_id):
                self.assertIn(geometry, ("line", "area", "point"))

    def test_a_building_entry_is_a_building_to_the_generator(self):
        # The building generator looks for the tag, not for the category.
        for entry_id in ("house", "apartments", "school", "church", "shed"):
            with self.subTest(entry_id):
                self.assertIn("building", sketch.BY_ID[entry_id][3])
                self.assertEqual(sketch.category_of(entry_id), "building")

    def test_the_road_classes_come_out_in_their_own_classes(self):
        # A motorway and an alley must not land in the same bucket, or every
        # drawn road is painted the same width.
        self.assertEqual(sketch.category_of("motorway"), "road_major")
        self.assertEqual(sketch.category_of("residential"), "road_minor")
        self.assertEqual(sketch.category_of("service"), "road_service")


class Conversion(unittest.TestCase):
    def test_a_line_keeps_its_points_in_osm_order(self):
        feats = sketch.features(collection(drawn("residential", "LineString", LINE)))
        self.assertEqual(len(feats), 1)
        # GeoJSON is (lon, lat); OSMFeature is (lat, lon), as Overpass gives it.
        self.assertEqual(feats[0].geometry, [(0.0, 0.0), (0.001, 0.001)])
        self.assertEqual(feats[0].tags, {"highway": "residential"})
        self.assertEqual(feats[0].kind, "way")

    def test_an_area_is_a_closed_way(self):
        feats = sketch.features(collection(drawn("house", "Polygon", SQUARE)))
        self.assertEqual(feats[0].geometry[0], feats[0].geometry[-1])
        self.assertEqual(classify(feats[0].tags, area=True), "building")

    def test_an_unclosed_ring_is_closed(self):
        feats = sketch.features(collection(
            drawn("water", "Polygon", [SQUARE[0][:-1]])))
        self.assertEqual(feats[0].geometry[0], feats[0].geometry[-1])

    def test_ids_are_negative_and_do_not_repeat(self):
        feats = sketch.features(collection(
            drawn("residential", "LineString", LINE),
            drawn("water", "Polygon", SQUARE),
            drawn("tree", "Point", [0.0, 0.0])))
        ids = [f.osm_id for f in feats]
        self.assertTrue(all(i < 0 for i in ids), ids)
        self.assertEqual(len(set(ids)), len(ids))

    def test_a_point_is_a_node(self):
        feats = sketch.features(collection(drawn("tree", "Point", [1.5, 2.5])))
        self.assertEqual(feats[0].kind, "node")
        self.assertEqual(feats[0].geometry, [(2.5, 1.5)])

    def test_rubbish_is_left_out_rather_than_guessed_at(self):
        # None of these can be drawn through the window, but a hand-edited
        # file or an older release's save can hold them.
        self.assertEqual(sketch.features(None), [])
        self.assertEqual(sketch.features(collection()), [])
        for bad in (drawn("not_a_kind", "LineString", LINE),
                    drawn("residential", "LineString", [[0.0, 0.0]]),
                    drawn("water", "Polygon", [[[0.0, 0.0], [1.0, 1.0]]]),
                    drawn("residential", "Circle", LINE),
                    {"type": "Feature", "geometry": {"type": "LineString",
                                                     "coordinates": LINE}}):
            with self.subTest(bad=bad):
                self.assertEqual(sketch.features(collection(bad)), [])

    def test_only_the_listed_extra_tags_are_taken(self):
        # The tags reach classify and the renderer, so a page cannot be allowed
        # to set whatever it likes on a feature.
        feats = sketch.features(collection(drawn(
            "house", "Polygon", SQUARE,
            tags={"building:levels": 3, "name": "The Arms", "amenity": "bar"})))
        self.assertEqual(feats[0].tags["building:levels"], "3")
        self.assertEqual(feats[0].tags["name"], "The Arms")
        self.assertNotIn("amenity", feats[0].tags)

    def test_a_drawn_street_is_the_same_feature_as_a_surveyed_one(self):
        # The whole point: nothing downstream can tell them apart.
        from generator.osm import OSMFeature
        surveyed = OSMFeature(12345, "way", {"highway": "residential"},
                              [(0.0, 0.0), (0.001, 0.001)])
        made = sketch.features(collection(drawn("residential", "LineString", LINE)))[0]
        self.assertEqual(classify(made.tags), classify(surveyed.tags))
        self.assertEqual(made.geometry, surveyed.geometry)
        self.assertEqual(made.kind, surveyed.kind)


if __name__ == "__main__":
    unittest.main()
