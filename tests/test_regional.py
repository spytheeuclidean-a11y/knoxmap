"""The regional architecture pack: detection, styles, storeys.

A Chinese map must come out Chinese-built without a single tile the catalog
did not already ship, an American one must come out exactly as it did before
the knob existed, and a mapper's own height tags must beat both.
"""
import random
import unittest

from knoxbuild import catalog
from knoxbuild.build import (DEFAULT_LEVELS, building_levels, is_notable,
                             pick_style)
from knoxbuild.profile import BuildingProfile
from knoxbuild.regional import (AREA_LEVEL_TABLE, CN_BASES, area_level_pool,
                                cn_house_styles, detect_region, gb_house_styles,
                                map_country,
                                profile)
from knoxbuild.settings import Settings


def geo(names):
    """A buildings geojson whose footprints carry these names."""
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature",
                          "properties": {"name": name, "building": "yes"},
                          "geometry": {"type": "Polygon",
                                       "coordinates": [[[0, 0], [1, 0],
                                                        [1, 1], [0, 0]]]}}
                         for name in names]}


BBOX = {"south": 30.0, "west": 120.0, "north": 30.1, "east": 120.1}


class DetectRegion(unittest.TestCase):
    def test_han_names_read_as_chinese(self):
        self.assertEqual(detect_region(geo(["新华书店", "王记小吃", "人民公园",
                                            "第一中学", "红旗照相馆", "东风商场",
                                            "李家面馆"]), BBOX), "cn")

    def test_kana_marks_japanese_even_with_han(self):
        self.assertEqual(detect_region(geo(["東京都庁", "きたく図書館",
                                            "すずき薬局", "ヤマザキ商店",
                                            "さくら小学校", "ローソン",
                                            "コーヒー店"]), BBOX), "jp")

    def test_hangul_marks_korean(self):
        self.assertEqual(detect_region(geo(["서울시청", "강남구청",
                                            "미래약국", "행복슈퍼",
                                            "청솔초등학교", "한빛도서관",
                                            "가족식당"]), BBOX), "kr")

    def test_english_stays_default(self):
        self.assertIsNone(detect_region(geo(["Town Hall", "Ruby's Diner",
                                              "First National Bank",
                                              "Greenfield School",
                                              "Motel 6", "The Elm",
                                              "County Jail"]), BBOX))

    def test_a_chinatown_does_not_turn_the_town_chinese(self):
        names = ["Town Hall", "Ruby's Diner", "First National Bank"] * 4 \
            + ["金龙酒家", "新华书店"]
        self.assertIsNone(detect_region(geo(names), BBOX))

    def test_unnamed_map_falls_back_to_the_bounding_box(self):
        self.assertEqual(detect_region(geo(["", "", ""]), BBOX), "cn")
        self.assertEqual(detect_region(geo(["", "", ""]),
                                       {"south": 35.6, "west": 139.7,
                                        "north": 35.7, "east": 139.8}), "jp")
        self.assertEqual(detect_region(geo(["", "", ""]), LONDON), "gb")

    def test_seoul_is_not_read_as_china(self):
        self.assertEqual(detect_region(geo(["", "", ""]),
                                       {"south": 37.4, "west": 126.9,
                                        "north": 37.6, "east": 127.1}), "kr")


LONDON = {"south": 51.0, "west": -0.2, "north": 51.1, "east": 0.2}
DUBLIN = {"south": 53.3, "west": -6.35, "north": 53.4, "east": -6.2}
ENGLISH = ["Town Hall", "The Red Lion", "St Mary's Church", "Co-op",
           "Village Hall", "The Crown", "Primary School"]


class DetectBritain(unittest.TestCase):
    def test_the_country_on_record_makes_a_british_map_gb(self):
        self.assertEqual(detect_region(geo(ENGLISH), BBOX, country="GB"), "gb")

    def test_a_country_without_a_profile_builds_the_default_way(self):
        self.assertIsNone(detect_region(geo(ENGLISH), LONDON, country="FR"))
        self.assertIsNone(detect_region(geo(ENGLISH), DUBLIN, country="IE"))

    def test_names_still_come_first(self):
        names = ["新华书店", "王记小吃", "人民公园", "第一中学", "红旗照相馆", "东风商场"]
        self.assertEqual(detect_region(geo(names), LONDON, country="GB"), "cn")

    def test_without_a_country_the_box_decides(self):
        # A map made before the country was recorded, or with no Natural Earth.
        self.assertEqual(detect_region(geo(ENGLISH), LONDON), "gb")
        self.assertIsNone(detect_region(geo(ENGLISH), DUBLIN))
        self.assertIsNone(detect_region(geo(ENGLISH), BBOX))

    def test_the_country_is_read_from_the_maps_data_layers(self):
        import json
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(map_country(d, "Town"))
            with open(os.path.join(d, "Town_knoxdata.json"), "w") as f:
                json.dump({"region": "GB"}, f)
            self.assertEqual(map_country(d, "Town"), "GB")


class Profiles(unittest.TestCase):
    def test_every_map_has_a_profile_and_the_us_is_the_default(self):
        self.assertEqual(profile(None).code, "us")
        self.assertEqual(profile("jp").code, "us")
        self.assertEqual(profile("gb").code, "gb")
        self.assertEqual(profile("cn").code, "cn")


class ChineseStyles(unittest.TestCase):
    def test_pool_is_composed_from_the_catalogs_own_entries(self):
        by_name = {s["name"]: s for s in catalog.HOUSE_STYLES}
        for style in cn_house_styles():
            with self.subTest(style=style["name"]):
                donor = by_name[style["name"][len("cn_"):]]
                # Every tile table is the donor's own, unchanged.
                for key in ("exterior", "interior", "window", "curtains",
                            "trim", "grime"):
                    self.assertEqual(style.get(key), donor.get(key),
                                     f"{key} must be the catalog's own")

    def test_pool_is_flat_roofed_masonry_without_shutters(self):
        names = [s["name"] for s in cn_house_styles()]
        self.assertEqual(sorted(names),
                         sorted(f"cn_{base}" for base in CN_BASES))
        for style in cn_house_styles():
            self.assertFalse(style["roof"]["peaked"])
            self.assertNotIn("shutters", style)
            # And the wood-and-siding styles are not in the pool at all.
            self.assertFalse(any(base in style["name"] for base in
                                 ("clapboard", "logs", "trailer", "siding",
                                  "timber")))

    def test_cn_style_renders_a_tbx(self):
        from xml.etree import ElementTree

        from knoxbuild import layout
        from knoxbuild.tbx import render_tbx

        room = layout.Room(0, 0, 4, 5, kind="livingroom")
        plan = layout.Plan(5, 6, rooms=[room],
                           grid=[[1] * 5 for _ in range(6)],
                           windows=[(2, 0, "N")])
        style = cn_house_styles()[0]
        root = ElementTree.fromstring(render_tbx(plan, "cn-style-test", style))
        entries = [entry for entry in root.findall("tile_entry")
                   if entry.get("category") in ("exterior_walls",
                                                "interior_walls")]
        self.assertTrue(entries)

    def test_pick_style_uses_the_cn_pool_for_ordinary_houses(self):
        rng = random.Random(7)
        settings = Settings()
        seen = set()
        for i in range(40):
            style = pick_style(None, 10 + (i % 12) * 9, 10 + (i // 12) * 9,
                               rng, settings, density=0.3, region="cn")
            seen.add(style["name"])
        self.assertTrue(seen)
        self.assertTrue(all(name.startswith("cn_") for name in seen), seen)

    def test_dated_prewar_buildings_keep_their_pitched_roofs(self):
        profile = BuildingProfile.infer({"start_date": "1921"}, None,
                                        0.3, 120, 2, 11)
        self.assertTrue(profile.dated)
        self.assertEqual(profile.era, "prewar")
        style = pick_style(None, 40, 40, random.Random(1), Settings(),
                           density=0.3, profile=profile, region="cn")
        self.assertFalse(style["name"].startswith("cn_"))

    def test_undated_buildings_do_not_get_the_prewar_exemption(self):
        profile = BuildingProfile.infer({}, None, 0.3, 120, 2, 11)
        self.assertFalse(profile.dated)
        style = pick_style(None, 40, 40, random.Random(1), Settings(),
                           density=0.3, profile=profile, region="cn")
        self.assertTrue(style["name"].startswith("cn_"))

    def test_default_maps_are_unchanged(self):
        rng = random.Random(7)
        settings = Settings()
        for i in range(20):
            style = pick_style(None, 10 + (i % 8) * 9, 10 + (i // 8) * 9,
                               rng, settings, density=0.3)
            self.assertFalse(style["name"].startswith("cn_"))


class BritishStyles(unittest.TestCase):
    def test_pool_is_the_catalogs_own_masonry_with_pitched_roofs(self):
        by_name = {s["name"]: s for s in catalog.HOUSE_STYLES}
        pool = gb_house_styles()
        self.assertTrue(pool)
        for style in pool:
            with self.subTest(style=style["name"]):
                donor = by_name[style["name"][len("gb_"):]]
                for key in ("exterior", "interior", "window", "curtains",
                            "trim", "grime", "roof"):
                    self.assertEqual(style.get(key), donor.get(key),
                                     f"{key} must be the catalog's own")
                self.assertTrue(style["roof"]["peaked"])
                self.assertNotIn("shutters", style)
                self.assertFalse(any(base in style["name"] for base in
                                     ("clapboard", "logs", "trailer", "siding",
                                      "timber", "panel")))

    def test_most_british_houses_are_brick(self):
        names = [s["name"] for s in gb_house_styles()]
        self.assertGreater(names.count("gb_brick") / len(names), 0.4)

    def test_pick_style_uses_the_gb_pool_for_ordinary_houses(self):
        rng = random.Random(7)
        seen = {pick_style(None, 10 + (i % 12) * 9, 10 + (i // 12) * 9,
                           rng, Settings(), density=0.3, region="gb")["name"]
                for i in range(40)}
        self.assertTrue(seen)
        self.assertTrue(all(name.startswith("gb_") for name in seen), seen)

    def test_dated_buildings_stay_british(self):
        # A Victorian terrace is brick too: no prewar exemption as for cn's flat roofs.
        profile = BuildingProfile.infer({"start_date": "1890"}, None,
                                        0.3, 120, 2, 11)
        style = pick_style(None, 40, 40, random.Random(1), Settings(),
                           density=0.3, profile=profile, region="gb")
        self.assertTrue(style["name"].startswith("gb_"))


class RegionalStoreys(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.rng = random.Random(42)

    def test_cn_houses_run_taller_than_default_ones(self):
        default = [building_levels({}, None, 30, random.Random(i),
                                   self.settings, metres_per_tile=2.0)[0]
                   for i in range(200)]
        cn = [building_levels({}, None, 30, random.Random(i),
                              self.settings, metres_per_tile=2.0,
                              region="cn")[0]
              for i in range(200)]
        self.assertGreater(max(cn), max(default))
        self.assertGreater(sum(cn) / len(cn), sum(default) / len(default))

    def test_cn_houses_never_exceed_the_games_house_shape_by_much(self):
        for i in range(100):
            levels, measured = building_levels({}, None, 30, random.Random(i),
                                               self.settings,
                                               metres_per_tile=2.0,
                                               region="cn")
            self.assertFalse(measured)
            self.assertLessEqual(levels, 4)

    def test_cn_apartments_follow_their_own_table(self):
        got = {building_levels({}, "apartment", 500, random.Random(i),
                               self.settings, metres_per_tile=2.0,
                               region="cn")[0]
               for i in range(60)}
        self.assertTrue(got & {4, 5, 6}, got)

    def test_small_footprints_stay_low_everywhere(self):
        # The Arnis-style area table: a kiosk-sized footprint is not a tower.
        for region in (None, "cn"):
            for i in range(40):
                levels, _ = building_levels({}, "shop", 8, random.Random(i),
                                            self.settings,
                                            metres_per_tile=2.0,
                                            region=region)
                self.assertLessEqual(levels, 2, (region, levels))

    def test_large_houses_read_as_taller_than_small_ones(self):
        small = {building_levels({}, None, 20, random.Random(i),
                                 self.settings, metres_per_tile=2.0)[0]
                 for i in range(80)}
        large = {building_levels({}, None, 200, random.Random(i),
                                 self.settings, metres_per_tile=2.0)[0]
                 for i in range(80)}
        self.assertGreater(max(large), max(small))

    def test_osm_levels_beat_every_table(self):
        for region in (None, "cn"):
            levels, measured = building_levels(
                {"building:levels": "5"}, None, 30, self.rng, self.settings,
                metres_per_tile=2.0, region=region)
            self.assertTrue(measured)
            self.assertEqual(levels, 5)

    def test_levels_respect_max_levels(self):
        settings = Settings(max_levels=3)
        for i in range(40):
            levels, _ = building_levels({}, "apartment", 500, random.Random(i),
                                        settings, metres_per_tile=2.0,
                                        region="cn")
            self.assertLessEqual(levels, 3)

    def test_every_default_kind_still_has_a_pool_or_range(self):
        for kind in set(DEFAULT_LEVELS) | {None, "mall", "castle"}:
            pool = area_level_pool(kind, 1000.0)
            rng = random.Random(0)
            lo, hi = DEFAULT_LEVELS.get(kind or "", (1, 2))
            levels = building_levels({}, kind, 250, rng, self.settings,
                                     metres_per_tile=2.0)[0]
            self.assertGreaterEqual(levels, 1)
            self.assertLessEqual(levels, max(hi, 12))
            if pool is None:
                self.assertIn(kind, DEFAULT_LEVELS)

    def test_area_bands_are_ordered(self):
        for kind, bands in AREA_LEVEL_TABLE.items():
            with self.subTest(kind=kind):
                limits = [limit for limit, _pool in bands]
                self.assertEqual(limits[-1], None)
                self.assertEqual([l for l in limits if l is not None],
                                 sorted(l for l in limits if l is not None))


class NotableBuildings(unittest.TestCase):
    def test_heritage_listed_buildings_are_notable(self):
        self.assertTrue(is_notable({"heritage": "2"}, None))
        self.assertTrue(is_notable({"historic": "monument"}, None))
        self.assertFalse(is_notable({"heritage": "no"}, None))
        self.assertFalse(is_notable({}, None))


class SettingsArchStyle(unittest.TestCase):
    def test_arch_style_round_trips(self):
        self.assertEqual(Settings(arch_style="cn").arch_style, "cn")
        self.assertEqual(Settings.from_dict({"arch_style": "cn"}).arch_style,
                         "cn")
        self.assertEqual(Settings.from_dict({"arch_style": "AUTO"}).arch_style,
                         "auto")

    def test_unknown_arch_style_falls_back_to_auto(self):
        self.assertEqual(Settings.from_dict({"arch_style": "gothic"}).arch_style,
                         "auto")
        self.assertEqual(Settings.from_dict({"arch_style": None}).arch_style,
                         "auto")

    def test_arch_style_is_serialised(self):
        self.assertIn("arch_style", Settings().to_dict())
        self.assertEqual(Settings().to_dict()["arch_style"], "auto")

    def test_settings_api_exposes_arch_style(self):
        from app import app

        body = app.test_client().get("/api/settings").get_json()
        self.assertEqual(body["types"]["arch_style"], "enum")
        self.assertEqual([value for value, _label in body["options"]["arch_style"]],
                         ["auto", "cn", "off"])
        self.assertEqual(body["defaults"]["arch_style"], "auto")


if __name__ == "__main__":
    unittest.main()
