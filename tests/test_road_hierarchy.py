import unittest
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import mock

import numpy as np
from PIL import Image

from generator import osm, renderer, structures
from knoxbuild import build as building
from knoxbuild.context import Context


class RoadHierarchyTests(unittest.TestCase):
    def test_highway_tags_map_to_ordered_hierarchy(self):
        cases = {
            "motorway": "motorway", "motorway_link": "motorway",
            "trunk": "trunk", "trunk_link": "trunk",
            "primary": "primary", "primary_link": "primary",
            "secondary": "secondary", "secondary_link": "secondary",
            "tertiary": "tertiary", "tertiary_link": "tertiary",
            "residential": "residential", "unclassified": "residential",
            "living_street": "residential", "service": "service",
            "footway": "footway", "cycleway": "footway",
        }
        for highway, hierarchy in cases.items():
            with self.subTest(highway=highway):
                self.assertEqual(osm.road_hierarchy({"highway": highway}), hierarchy)

    def test_nonroad_features_have_no_hierarchy(self):
        self.assertIsNone(osm.road_hierarchy({"building": "yes"}))

    def test_render_road_classification_keeps_surface_categories(self):
        self.assertEqual(osm.classify({"highway": "motorway"}), "road_major")
        self.assertEqual(osm.classify({"highway": "residential"}), "road_minor")
        self.assertEqual(osm.classify({"highway": "footway"}), "paved_path")

    def test_default_widths_follow_hierarchy(self):
        expected = {"motorway": 24.0, "trunk": 16.0, "primary": 12.0,
                    "secondary": 9.0, "tertiary": 7.0,
                    "residential": 6.0, "service": 3.5}
        for highway, width in expected.items():
            with self.subTest(highway=highway):
                feat = SimpleNamespace(tags={"highway": highway})
                coarse = osm.classify(feat.tags)
                self.assertEqual(renderer._way_width_m(feat, coarse), width)

    def test_explicit_width_overrides_hierarchy_default(self):
        feat = SimpleNamespace(tags={"highway": "residential", "width": "8 m"})
        self.assertEqual(renderer._way_width_m(feat, "road_minor"), 8.0)

    def test_widths_round_to_the_nearest_bitmap_tile(self):
        self.assertEqual(renderer._pixel_width(3.5, 1.0), 4)
        self.assertEqual(renderer._pixel_width(4.0, 1.6), 3)

    def test_lane_markings_follow_direction_and_lane_count(self):
        two_way = SimpleNamespace(tags={"highway": "residential", "lanes": "2"})
        one_way = SimpleNamespace(tags={"highway": "residential", "lanes": "2",
                                        "oneway": "yes"})
        divided = SimpleNamespace(tags={"highway": "primary", "lanes": "4"})

        self.assertEqual(renderer._road_markings(two_way, "road_minor"),
                         [("yellow", 0.0)])
        self.assertEqual(renderer._road_markings(one_way, "road_minor"),
                         [("white", 0.0)])
        self.assertEqual(renderer._road_markings(divided, "road_major"),
                         [("yellow", 0.0), ("white", -3.45), ("white", 3.45)])

    def test_oneway_and_twoway_lane_colors_are_painted_on_the_road(self):
        def markings(oneway):
            ground = Image.new("RGB", (40, 30), renderer.C.DARK_GRASS)
            for y in range(11, 19):
                for x in range(40):
                    ground.putpixel((x, y), renderer.C.MEDIUM_ASPHALT)
            vegetation = Image.new("RGB", ground.size, renderer.C.VEG_NOTHING)
            tags = {"highway": "residential", "lanes": "2"}
            if oneway:
                tags["oneway"] = "yes"
            road = osm.OSMFeature(1, "way", tags, [(15, 2), (15, 38)])
            projection = SimpleNamespace(meters_per_tile=1.0,
                                         to_px=lambda lat, lon: (lon, lat))

            renderer._paint_road_details(vegetation, ground,
                                         {"road_minor": [road]}, projection)
            return {vegetation.getpixel((x, 15)) for x in range(40)}

        one_way_colors = markings(True)
        two_way_colors = markings(False)
        self.assertIn(renderer.C.LINE_WHITE_N, one_way_colors)
        self.assertNotIn(renderer.C.LINE_YELLOW_N, one_way_colors)
        self.assertIn(renderer.C.LINE_YELLOW_N, two_way_colors)

    def test_tunnels_are_not_surface_roads_and_bridges_keep_their_height(self):
        self.assertIsNone(osm.classify({"highway": "primary", "tunnel": "yes"}))
        self.assertEqual(structures.level_of({"bridge": "yes"}), 1)
        self.assertEqual(structures.level_of({"layer": "2"}), 2)

    def test_sidewalks_and_verges_follow_road_hierarchy(self):
        motorway = SimpleNamespace(tags={"highway": "motorway"})
        residential = SimpleNamespace(tags={"highway": "residential"})
        service = SimpleNamespace(tags={"highway": "service"})
        self.assertEqual(renderer._sidewalk_width_m(motorway, "road_major"), 0.0)
        self.assertEqual(renderer._sidewalk_width_m(residential, "road_minor"), 2.5)
        self.assertEqual(renderer._verge_width_m(residential, "road_minor"), 1.5)
        self.assertEqual(renderer._verge_width_m(service, "road_service"), 0.0)

    def test_explicitly_mapped_or_absent_sidewalks_are_not_generated(self):
        for tags in ({"sidewalk:both": "separate"},
                     {"sidewalk:left": "no", "sidewalk:right": "separate"},
                     {"sidewalk": "no"}):
            feat = SimpleNamespace(tags={"highway": "residential", **tags})
            self.assertEqual(renderer._sidewalk_width_m(feat, "road_minor"), 0)
        feat = SimpleNamespace(tags={"highway": "residential", "sidewalk:left": "separate"})
        self.assertGreater(renderer._sidewalk_width_m(feat, "road_minor"), 0)

    def test_map_distinguishes_paved_sidewalks_from_dirt_trails(self):
        from knoxbuild.worldmap import HIGHWAY_VALUE
        self.assertEqual(HIGHWAY_VALUE["dirt_path"], "trail")
        self.assertNotEqual(HIGHWAY_VALUE["paved_path"], "trail")

    def test_road_hierarchy_raster_covers_the_right_of_way(self):
        feat = osm.OSMFeature(1, "way", {"highway": "residential"},
                              [(20, 8), (20, 56)])
        proj = SimpleNamespace(width=64, height=64, meters_per_tile=1.0,
                                to_px=lambda lat, lon: (lon, lat))
        image = renderer._road_hierarchy_image({"road_minor": [feat]}, proj)

        self.assertEqual(image.getpixel((32, 20)), osm.ROAD_HIERARCHY_CODES["residential"])
        self.assertEqual(image.getpixel((32, 15)), osm.ROAD_HIERARCHY_CODES["residential"])

    def test_building_avoidance_weights_major_roads_more(self):
        with TemporaryDirectory() as directory:
            Image.new("RGB", (4, 2), renderer.C.DARK_GRASS).save(
                f"{directory}/map.bmp")
            classes = np.zeros((2, 4), dtype=np.uint8)
            classes[0, 0] = osm.ROAD_HIERARCHY_CODES["residential"]
            classes[0, 1] = osm.ROAD_HIERARCHY_CODES["motorway"]

            weight = building._road_weight(
                directory, "map", SimpleNamespace(width=4, height=2), classes)

        self.assertGreater(weight[0, 1], weight[0, 0])

    def test_building_avoidance_detects_road_surfaces_without_hierarchy(self):
        colours = (renderer.C.DARK_ASPHALT, renderer.C.MEDIUM_ASPHALT,
                   renderer.C.LIGHT_ASPHALT, renderer.C.DARKEST_ASPHALT)
        with TemporaryDirectory() as directory:
            ground = Image.new("RGB", (len(colours), 1), renderer.C.DARK_GRASS)
            for x, colour in enumerate(colours):
                ground.putpixel((x, 0), colour)
            ground.save(f"{directory}/map.bmp")

            weight = building._road_weight(
                directory, "map", SimpleNamespace(width=len(colours), height=1))

        self.assertTrue(np.all(weight[0] > 0))

    def test_trees_are_cleared_from_road_surfaces(self):
        ground = Image.new("RGB", (3, 1), renderer.C.DARK_GRASS)
        ground.putpixel((0, 0), renderer.C.DARK_ASPHALT)
        ground.putpixel((1, 0), renderer.C.MEDIUM_ASPHALT)
        vegetation = Image.new("RGB", ground.size, renderer.C.TREES)

        renderer._clear_road_vegetation(vegetation, ground)

        self.assertEqual(vegetation.getpixel((0, 0)), renderer.C.VEG_NOTHING)
        self.assertEqual(vegetation.getpixel((1, 0)), renderer.C.VEG_NOTHING)
        self.assertEqual(vegetation.getpixel((2, 0)), renderer.C.TREES)

    def test_higher_order_roads_raise_local_urban_density(self):
        classes = np.zeros((40, 40), dtype=np.uint8)
        classes[:, 19:21] = osm.ROAD_HIERARCHY_CODES["primary"]
        rural = Context(40, 40, [], metres_per_tile=1.0)
        urban = Context(40, 40, [], metres_per_tile=1.0,
                        road_hierarchy=classes)

        self.assertGreater(urban.density(20, 20), rural.density(20, 20))

    def test_vehicle_stalls_favor_residential_roads_over_motorways(self):
        with TemporaryDirectory() as directory:
            path = f"{directory}/ground.bmp"
            pixels = Image.new("RGB", (400, 80), renderer.C.DARK_GRASS)
            for y in range(16, 23):
                for x in range(400):
                    pixels.putpixel((x, y), renderer.C.MEDIUM_ASPHALT)
            pixels.save(path)
            residential = np.zeros((80, 400), dtype=np.uint8)
            motorway = np.zeros_like(residential)
            residential[16:23, :] = osm.ROAD_HIERARCHY_CODES["residential"]
            motorway[16:23, :] = osm.ROAD_HIERARCHY_CODES["motorway"]
            settings = SimpleNamespace(parking_density=1.0)
            local_zones = building._detect_zones(
                path, [], settings=settings, road_hierarchy=residential)
            motorway_zones = building._detect_zones(
                path, [], settings=settings, road_hierarchy=motorway)

        local_stalls = sum(zone.kind == "ParkingStall" for zone in local_zones)
        motorway_stalls = sum(zone.kind == "ParkingStall" for zone in motorway_zones)
        self.assertGreater(local_stalls, motorway_stalls)

    def test_kerbside_bays_get_a_wheel_stop_at_their_ends(self):
        """The concrete blocks that close a bay: painted into the vegetation
        bitmap across the mouth of the bay, on the tarmac only."""
        with TemporaryDirectory() as directory:
            ground_path = f"{directory}/map.bmp"
            veg_path = f"{directory}/map_veg.bmp"
            pixels = Image.new("RGB", (80, 60), renderer.C.DARK_GRASS)
            for y in range(16, 31):
                for x in range(80):
                    pixels.putpixel((x, y), renderer.C.MEDIUM_ASPHALT)
            pixels.save(ground_path)
            Image.new("RGB", (80, 60), renderer.C.VEG_NOTHING).save(veg_path)
            classes = np.zeros((60, 80), dtype=np.uint8)
            classes[16:31, :] = osm.ROAD_HIERARCHY_CODES["residential"]
            with mock.patch("knoxbuild.yards._rule_ready", return_value=True):
                zones = building._detect_zones(
                    ground_path, [], settings=SimpleNamespace(parking_density=1.0),
                    road_hierarchy=classes, veg_path=veg_path)
            veg = np.asarray(Image.open(veg_path).convert("RGB"))
            painted = {tuple(colour) for colour in veg.reshape(-1, 3)}

        self.assertTrue(any(zone.kind == "ParkingStall" for zone in zones), "no bays")
        stops = painted & (set(renderer.C.PARKING_BLOCK_X) | set(renderer.C.PARKING_BLOCK_Y))
        self.assertTrue(stops, "no wheel stop was laid")
        # A block is one sprite in three squares, so a whole one is all three
        # colours of its group: never a lone square of concrete.
        groups = (renderer.C.PARKING_BLOCK_X, renderer.C.PARKING_BLOCK_Y)
        self.assertTrue(any(set(group) <= painted for group in groups),
                        "every stop was laid half-finished")

    def test_commercial_frontage_prefers_higher_order_road_at_equal_distance(self):
        with TemporaryDirectory() as directory:
            ground = Image.new("RGB", (40, 40), renderer.C.DARK_GRASS)
            for x in range(10, 31):
                ground.putpixel((x, 12), renderer.C.PALE_CONCRETE)
                ground.putpixel((x, 27), renderer.C.PALE_CONCRETE)
            ground.save(f"{directory}/map_ground_base.bmp")
            classes = np.zeros((40, 40), dtype=np.uint8)
            classes[12, 10:31] = osm.ROAD_HIERARCHY_CODES["residential"]
            classes[27, 10:31] = osm.ROAD_HIERARCHY_CODES["primary"]

            side = building._street_finder(directory, "map", classes)(15, 15, 10, 10)

        self.assertEqual(side, "S")

    def test_residential_streets_get_more_lamps_than_motorways(self):
        def lamp_count(hierarchy):
            ground = Image.new("RGB", (60, 220), renderer.C.DARK_GRASS)
            pixels = ground.load()
            for y in range(220):
                for x in range(20, 26):
                    pixels[x, y] = renderer.C.MEDIUM_ASPHALT
                pixels[26, y] = renderer.C.PALE_CONCRETE
            vegetation = Image.new("RGB", ground.size, renderer.C.VEG_NOTHING)
            classes = Image.new("L", ground.size,
                                osm.ROAD_HIERARCHY_CODES[hierarchy])
            counts = renderer._paint_street_furniture(vegetation, ground, classes)
            return counts.get("lamp", 0)

        self.assertGreater(lamp_count("residential"), lamp_count("motorway"))


if __name__ == "__main__":
    unittest.main()
