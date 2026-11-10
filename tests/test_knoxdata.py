"""Offline tests for the optional enrichment layers (knoxdata/).

No network: fetchers are mocked or the layer is gated out. The point is the
contract — a disabled, unavailable or failing layer is skipped with a line,
never a lost map, and OSM data is never overwritten.
"""
import io
import logging
import os
import tempfile
import unittest
from pathlib import Path

import knoxdata
from knoxbuild.settings import Settings


class TheCacheHasACeiling(unittest.TestCase):
    """knoxdata/cache.py caps the whole dataset cache, not just one download.

    The per-download ceiling stops one wrong URL filling the disk. Nothing
    stopped ten right ones: a few national extracts and a world raster and the
    cache was as big as the last month of maps made it.
    """

    def ages(self, folder, *sizes):
        """Files of the given sizes, oldest first."""
        made = []
        for i, size in enumerate(sizes):
            p = Path(folder) / f"set{i}.bin"
            p.write_bytes(b"x" * size)
            os.utime(p, (1000 + i, 1000 + i))
            made.append(p)
        return made

    def test_the_oldest_datasets_go_when_it_is_full(self):
        from knoxdata import cache
        with tempfile.TemporaryDirectory() as folder:
            made = self.ages(folder, 600, 600, 600)
            self.assertEqual(cache.prune(keep_bytes=1000, folder=folder), 2)
            self.assertFalse(made[0].exists())
            self.assertTrue(made[2].exists(), "the newest dataset must survive")

    def test_the_file_just_downloaded_is_never_the_one_deleted(self):
        from knoxdata import cache
        with tempfile.TemporaryDirectory() as folder:
            old, fresh = self.ages(folder, 600, 600)
            self.assertEqual(cache.prune(keep_bytes=600, folder=folder, keep=fresh), 1)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())

    def test_a_cache_under_its_ceiling_is_left_alone(self):
        from knoxdata import cache
        with tempfile.TemporaryDirectory() as folder:
            made = self.ages(folder, 10)
            self.assertEqual(cache.prune(keep_bytes=1000, folder=folder), 0)
            self.assertTrue(made[0].exists())

    def test_an_empty_or_missing_cache_is_not_an_error(self):
        from knoxdata import cache
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(cache.prune(folder=Path(folder) / "nothing-here"), 0)


class FakeFeature:
    def __init__(self, tags, ring):
        self.tags = dict(tags)
        self.geometry = ring


class _Source(knoxdata.DatasetSource):
    name = "elevation_3dep"
    license = "x"
    attribution = "x"
    setting = "elevation"
    off_values = ("flat", "off", "", None, False)

    def __init__(self, up=True, boom=False):
        self._up, self._boom = up, boom

    def available(self, bbox):
        return self._up

    def why_unavailable(self):
        return "not here"

    def fetch(self, bbox, cache_dir=None, progress_cb=None):
        return None

    def build_layer(self, ctx):
        if self._boom:
            raise RuntimeError("boom")
        return knoxdata.Layer()

    def apply(self, ctx, layer):
        ctx.report["applied"] = True


class Spine(unittest.TestCase):
    def setUp(self):
        self._saved = knoxdata._SOURCES

    def tearDown(self):
        knoxdata._SOURCES = self._saved

    def test_registry_has_the_five_layers(self):
        names = set(knoxdata.sources())
        self.assertEqual(names, {"worldcover", "elevation_3dep", "natural_earth",
                                 "hifld_hospitals", "climate_normals"})

    def test_all_off_does_nothing(self):
        knoxdata._SOURCES = {}
        report = knoxdata.run_layers(
            Settings.from_dict({"landcover": "off", "elevation": "flat",
                                "ne_context": 0, "hospitals": "off",
                                "climate_flavor": 0}),
            (0, 0, 1, 1), ".")
        self.assertEqual(report["used"], [])

    def test_what_a_layer_reports_is_kept(self):
        # WorldCover's apply() reports its class fractions under its own name
        # for the preset suggestion; marking it used must not wipe them.
        class Reporting(_Source):
            def apply(self, ctx, layer):
                ctx.report.setdefault(self.name, {})["fractions"] = {"Tree cover": 0.9}
        knoxdata._SOURCES = {"elevation_3dep": Reporting()}
        report = knoxdata.run_layers(Settings(elevation="3dep"), (0, 0, 1, 1), ".")
        self.assertEqual(report["elevation_3dep"],
                         {"fractions": {"Tree cover": 0.9}, "used": True})

    def test_openstreetmap_only_turns_worldcover_off(self):
        wc = knoxdata.sources()["worldcover"]
        self.assertFalse(wc.enabled(Settings.from_dict({"landcover": "osm"})))
        self.assertFalse(wc.enabled(Settings.from_dict({"landcover": "off"})))
        self.assertTrue(wc.enabled(Settings()))
        self.assertIsNone(knoxdata.landcover_for(Settings.from_dict({"landcover": "osm"}),
                                                 (45.0, -69.0, 45.01, -68.99)))

    def test_disabled_layer_is_not_run(self):
        src = _Source(up=True)
        knoxdata._SOURCES = {"elevation_3dep": src}
        report = knoxdata.run_layers(Settings(elevation="flat"), (0, 0, 1, 1), ".")
        self.assertEqual(report["used"], [])
        self.assertNotIn("applied", report)

    def test_unavailable_layer_logs_one_line_and_degrades(self):
        src = _Source(up=False)
        knoxdata._SOURCES = {"elevation_3dep": src}
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        knoxdata.log.addHandler(handler)
        try:
            report = knoxdata.run_layers(Settings(elevation="3dep"), (0, 0, 1, 1), ".")
        finally:
            knoxdata.log.removeHandler(handler)
        self.assertEqual(report["used"], [])
        self.assertIn("elevation_3dep skipped - not here", stream.getvalue())

    def test_failing_layer_never_raises(self):
        src = _Source(up=True, boom=True)
        knoxdata._SOURCES = {"elevation_3dep": src}
        report = knoxdata.run_layers(Settings(elevation="3dep"), (0, 0, 1, 1), ".")
        self.assertEqual(report["used"], [])
        self.assertIn("boom", report["elevation_3dep"]["why"])

    def test_require_cache_skips_without_data(self):
        src = _Source(up=True)
        src.cached = lambda bbox: False
        knoxdata._SOURCES = {"elevation_3dep": src}
        report = knoxdata.run_layers(Settings(elevation="3dep"), (0, 0, 1, 1), ".",
                                     require_cache=True)
        self.assertEqual(report["used"], [])
        self.assertEqual(report["elevation_3dep"]["why"], "not cached")

    def test_refresh_fetches_enabled_layers(self):
        src = _Source(up=True)
        src.fetch = lambda bbox, cache_dir=None, progress_cb=None: "done"
        knoxdata._SOURCES = {"elevation_3dep": src}
        out = knoxdata.refresh(Settings(elevation="3dep"), (0, 0, 1, 1))
        self.assertTrue(out["elevation_3dep"]["fetched"])

    def test_attribution_names_the_sources(self):
        lines = knoxdata.attribution_lines(["worldcover", "hifld_hospitals"])
        self.assertTrue(any("Copernicus" in line for line in lines))
        self.assertTrue(any("HIFLD" in line for line in lines))


class PresetSuggestion(unittest.TestCase):
    def test_built_up_fraction_picks_the_preset(self):
        from knoxdata.worldcover import suggest_preset
        self.assertEqual(suggest_preset({"Built-up": 0.40}), "city")
        self.assertEqual(suggest_preset({"Built-up": 0.20}), "suburb")
        self.assertEqual(suggest_preset({"Built-up": 0.10}), "town")
        self.assertEqual(suggest_preset({"Built-up": 0.01}), "rural")


class SettingsKnobs(unittest.TestCase):
    def test_new_knobs_parse_and_clamp(self):
        s = Settings.from_dict({"landcover": "osm", "elevation": "flat",
                                "region_override": "gb", "max_relief": "99",
                                "ne_context": "1", "climate_flavor": "0"})
        self.assertEqual(s.landcover, "osm")
        self.assertEqual(s.elevation, "flat")
        self.assertEqual(s.region_override, "GB")
        self.assertEqual(s.max_relief, 12)          # clamped
        self.assertEqual(s.ne_context, 1)
        self.assertEqual(s.climate_flavor, 0)

    def test_bad_values_keep_defaults(self):
        s = Settings.from_dict({"landcover": "moon", "region_override": "!!",
                                "winter_look": "maybe"})
        self.assertEqual(s.landcover, "worldcover")
        self.assertEqual(s.region_override, "auto")
        self.assertEqual(s.winter_look, "auto")


class WorldCoverTiles(unittest.TestCase):
    def test_tile_name_is_the_three_degree_sw_corner(self):
        from knoxdata import worldcover
        self.assertEqual(worldcover.tile_names((32.0, -87.0, 32.5, -86.5)),
                         ["ESA_WorldCover_10m_2021_v200_N30W087_Map.tif"])
        self.assertEqual(worldcover.tile_names((-1.0, -1.0, -0.5, -0.5)),
                         ["ESA_WorldCover_10m_2021_v200_S03W003_Map.tif"])


class NaturalEarth(unittest.TestCase):
    def setUp(self):
        from shapely.geometry import Point, Polygon
        from knoxdata import natural_earth as ne
        self.ne = ne
        self._saved = ne._geoms

        def fake(theme):
            if theme == "countries":
                return [(Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
                         {"ISO_A2": "GB", "NAME": "Testland"})]
            if theme == "places":
                return [(Point(1, 1), {"NAME": "Town", "POP_MAX": 100})]
            return []
        ne._geoms = fake

    def tearDown(self):
        self.ne._geoms = self._saved

    def test_country_at_point(self):
        self.assertEqual(self.ne.country_at(1.0, 1.0)["iso"], "GB")

    def test_place_inside_bbox(self):
        places = self.ne.places_in((0.5, 0.5, 1.5, 1.5))
        self.assertEqual([p["name"] for p in places], ["Town"])


class HIFLDMatching(unittest.TestCase):
    def test_name_match_wins_and_sets_the_name(self):
        from knoxdata import hifld_hospitals as h
        ring = [(40.000, -75.000), (40.000, -74.998),
                (40.002, -74.998), (40.002, -75.000)]
        feat = FakeFeature({"building": "hospital", "name": "Mercy General Hospital"}, ring)
        ctx = knoxdata.MapContext(bbox=(40, -75, 40.1, -74.9),
                                  settings=Settings(), map_dir=".", features=[feat])
        src = h.HIFLDHospitals()
        rows = [{"name": "Mercy General", "lat": 40.001, "lon": -74.999,
                 "type": "GENERAL ACUTE CARE", "status": "OPEN", "beds": 200,
                 "staff": 500, "helipad": True}]
        src.apply(ctx, knoxdata.Layer(rows=rows))
        self.assertEqual(feat.tags["name"], "Mercy General")
        self.assertEqual(feat.tags["healthcare"], "hospital")
        self.assertEqual(feat.tags["helipad"], "yes")
        match = ctx.report["hifld_hospitals"]["matched"][0]
        self.assertEqual(match["tier"], 0)          # name match

    def test_road_is_not_a_candidate(self):
        from knoxdata import hifld_hospitals as h
        road = FakeFeature({"highway": "primary"}, [(40.000, -75.000)] * 4)
        ctx = knoxdata.MapContext(bbox=(40, -75, 40.1, -74.9),
                                  settings=Settings(), map_dir=".", features=[road])
        src = h.HIFLDHospitals()
        src.apply(ctx, knoxdata.Layer(rows=[
            {"name": "Far", "lat": 40.0, "lon": -75.0, "type": "", "status": "",
             "beds": 0, "staff": 0, "helipad": False}]))
        self.assertNotIn("healthcare", road.tags)


class CacheDownload(unittest.TestCase):
    class _Resp:
        def __init__(self, body=b"data"):
            self._body = body
            self.headers = {"Content-Length": str(len(body))}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _n):
            body, self._body = self._body, b""
            return body

    def test_retries_with_backoff_then_succeeds(self):
        import tempfile
        import unittest.mock as mock

        from knoxdata import cache

        calls = {"n": 0}

        def fake(*_a, **_k):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("busy")
            return self._Resp(b"data")

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("urllib.request.urlopen", side_effect=fake), \
                mock.patch("knoxdata.cache.time.sleep", lambda *_: None):
            out = cache.download("http://x", Path(tmp) / "f.bin")
            self.assertEqual(out.read_bytes(), b"data")
        self.assertEqual(calls["n"], 3)

    def test_size_cap_refuses_a_huge_file(self):
        import tempfile
        import unittest.mock as mock

        from knoxdata import cache

        resp = self._Resp(b"")
        resp.headers = {"Content-Length": str(10 ** 12)}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("urllib.request.urlopen", return_value=resp), \
                mock.patch("knoxdata.cache.time.sleep", lambda *_: None):
            with self.assertRaises(ValueError):
                cache.download("http://x", Path(tmp) / "f.bin", max_bytes=1000)


class Attribution(unittest.TestCase):
    def test_a_mod_carries_the_layers_it_used(self):
        import json
        import os
        import tempfile

        from tools import make_map_mod

        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "proj")
            mod = os.path.join(tmp, "mod")
            os.makedirs(project)
            os.makedirs(mod)
            with open(os.path.join(project, "m_knoxdata.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"used": ["natural_earth", "hifld_hospitals"]}, fh)
            make_map_mod.write_attribution(project, mod, "M")
            with open(os.path.join(mod, "ATTRIBUTION.txt"), encoding="utf-8") as fh:
                text = fh.read()
        self.assertIn("OPTIONAL DATA", text)
        self.assertIn("Natural Earth", text)
        self.assertIn("HIFLD", text)


if __name__ == "__main__":
    unittest.main()
