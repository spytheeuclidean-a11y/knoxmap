"""Editing the features a map was built from.

The download stays the download and the changes are kept beside it, so the
things worth checking are that a change really reaches the features, that it
cannot reach anything it should not, and that the original is left alone - a
map whose cached download has been quietly rewritten cannot be un-edited.
"""
import unittest

from generator import edits
from generator.osm import OSMFeature, classify

HOUSE = [(0.0, 0.0), (0.0, 0.001), (0.001, 0.001), (0.001, 0.0), (0.0, 0.0)]
ROAD = [(0.0, 0.0), (0.002, 0.002)]


def town():
    return [
        OSMFeature(1, "way", {"building": "house"}, list(HOUSE)),
        OSMFeature(2, "way", {"highway": "residential"}, list(ROAD)),
        OSMFeature(3, "way", {"natural": "wood"}, list(HOUSE)),
    ]


class Cleaning(unittest.TestCase):
    def test_nothing_is_an_empty_edit_list(self):
        self.assertEqual(edits.clean(None), edits.empty())
        self.assertEqual(edits.count(edits.empty()), 0)

    def test_ids_arrive_as_numbers_however_they_were_sent(self):
        # JSON object keys are strings, so a moved feature's id always is.
        cleaned = edits.clean({"removed": ["7", 8], "moved": {"9": ROAD}})
        self.assertEqual(cleaned["removed"], [7, 8])
        self.assertIn(9, cleaned["moved"])

    def test_rubbish_is_dropped_rather_than_guessed_at(self):
        cleaned = edits.clean({"removed": ["x", None], "moved": {"a": ROAD},
                               "tags": {"1": {"amenity": None}}})
        self.assertEqual(edits.count(cleaned), 0)

    def test_a_shape_of_one_point_is_not_a_shape(self):
        self.assertEqual(edits.clean({"moved": {"1": [[0.0, 0.0]]}})["moved"], {})

    def test_only_the_listed_tags_are_taken(self):
        # These tags reach classify and the renderer; a page cannot be allowed
        # to set whatever it likes on a feature.
        cleaned = edits.clean({"tags": {"1": {"building": "retail",
                                              "note": "hello",
                                              "population": "9999"}}})
        self.assertEqual(cleaned["tags"][1], {"building": "retail"})


class Applying(unittest.TestCase):
    def test_a_removed_feature_is_gone(self):
        out, used = edits.apply(town(), {"removed": [1]})
        self.assertEqual([f.osm_id for f in out], [2, 3])
        self.assertEqual(used["removed"], 1)

    def test_a_moved_feature_keeps_its_tags_and_takes_the_new_shape(self):
        out, used = edits.apply(town(), {"moved": {"2": [[5.0, 5.0], [6.0, 6.0]]}})
        road = next(f for f in out if f.osm_id == 2)
        self.assertEqual(road.geometry, [(5.0, 5.0), (6.0, 6.0)])
        self.assertEqual(road.tags, {"highway": "residential"})
        self.assertEqual(used["moved"], 1)

    def test_an_area_that_was_closed_stays_closed(self):
        # An open ring is a line, not an area: the house would be painted as a
        # stripe rather than built.
        ring = [[9.0, 9.0], [9.0, 9.001], [9.001, 9.001]]
        out, _used = edits.apply(town(), {"moved": {"1": ring}})
        house = next(f for f in out if f.osm_id == 1)
        self.assertEqual(house.geometry[0], house.geometry[-1])

    def test_retagging_a_house_as_a_shop_changes_what_is_built(self):
        out, used = edits.apply(town(), {"tags": {"1": {"building": "retail",
                                                        "shop": "yes"}}})
        house = next(f for f in out if f.osm_id == 1)
        self.assertEqual(house.tags["building"], "retail")
        self.assertEqual(classify(house.tags, area=True), "building")
        self.assertEqual(used["tags"], 1)

    def test_the_download_is_never_touched(self):
        original = town()
        before = [(f.osm_id, list(f.geometry), dict(f.tags)) for f in original]
        edits.apply(original, {"removed": [1], "moved": {"2": ROAD},
                               "tags": {"3": {"natural": "sand"}}})
        after = [(f.osm_id, list(f.geometry), dict(f.tags)) for f in original]
        self.assertEqual(before, after)

    def test_no_edits_is_the_same_list_of_features(self):
        out, used = edits.apply(town(), None)
        self.assertEqual([f.osm_id for f in out], [1, 2, 3])
        self.assertEqual(used, {"removed": 0, "moved": 0, "tags": 0})

    def test_an_id_that_is_not_there_changes_nothing(self):
        out, _used = edits.apply(town(), {"removed": [999]})
        self.assertEqual(len(out), 3)


class ForTheWindow(unittest.TestCase):
    def test_each_feature_carries_its_own_id_back(self):
        out = edits.as_geojson(town())
        self.assertEqual([f["properties"]["osm_id"] for f in out["features"]],
                         [1, 2, 3])

    def test_a_closed_way_is_a_polygon_and_an_open_one_a_line(self):
        out = edits.as_geojson(town())
        kinds = {f["id"]: f["geometry"]["type"] for f in out["features"]}
        self.assertEqual(kinds[1], "Polygon")
        self.assertEqual(kinds[2], "LineString")

    def test_coordinates_go_back_the_way_geojson_wants_them(self):
        out = edits.as_geojson([town()[1]])
        self.assertEqual(out["features"][0]["geometry"]["coordinates"],
                         [[0.0, 0.0], [0.002, 0.002]])

    def test_only_what_is_being_looked_at_comes_back(self):
        far = OSMFeature(4, "way", {"building": "house"},
                         [(50.0, 50.0), (50.0, 50.001), (50.001, 50.001),
                          (50.0, 50.0)])
        out = edits.as_geojson(town() + [far], bbox=(-1.0, -1.0, 1.0, 1.0))
        self.assertEqual([f["id"] for f in out["features"]], [1, 2, 3])

    def test_a_town_too_big_to_edit_sends_the_biggest_and_says_so(self):
        many = [OSMFeature(i, "way", {"building": "house"},
                           [(0.0, 0.0), (0.0, i / 1000), (i / 1000, i / 1000),
                            (0.0, 0.0)])
                for i in range(1, 51)]
        out = edits.as_geojson(many, limit=10)
        self.assertEqual(out["total"], 50)
        self.assertEqual(out["shown"], 10)
        self.assertEqual(len(out["features"]), 10)
        # Largest first, so what arrives is what is worth editing.
        self.assertEqual(out["features"][0]["id"], 50)

    def test_a_node_is_not_offered_for_editing(self):
        trees = [OSMFeature(9, "node", {"natural": "tree"}, [(0.0, 0.0)])]
        self.assertEqual(edits.as_geojson(trees)["features"], [])


if __name__ == "__main__":
    unittest.main()
