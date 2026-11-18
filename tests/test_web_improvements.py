"""Tests for saved-area protection, shared area validation, refined forecasts,
oversized landmark summaries, and the repeatable in-game test map."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app import app
from knoxbuild import mapstate, why
from tools import make_ingame_test_map
from web import forecast as forecast_mod
from web import presets as web_presets


class SavedAreaProtectionAndValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pfile = Path(self.tmp.name) / "presets.json"
        self.patcher = mock.patch.object(web_presets, "PRESETS_FILE", self.pfile)
        self.patcher.start()
        self.client = app.test_client()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_corrupt_presets_file_is_preserved_and_restorable(self):
        payload = {
            "name": "HomeTown",
            "south": 40.0, "west": -80.0, "north": 40.01, "east": -79.99,
            "metersPerTile": 1.0,
        }
        r = self.client.post("/api/presets", json=payload)
        self.assertEqual(r.status_code, 200)
        # Write a second time so the first readable copy is also backed up.
        payload2 = {**payload, "name": "SecondTown"}
        r2 = self.client.post("/api/presets", json=payload2)
        self.assertEqual(r2.status_code, 200)

        # Corrupt presets.json
        self.pfile.write_text("{corrupt json", encoding="utf-8")

        get_r = self.client.get("/api/presets")
        self.assertEqual(get_r.status_code, 500)
        self.assertTrue(get_r.get_json()["corrupt"])
        self.assertTrue(get_r.get_json()["hasBackup"])

        # Saving must NOT overwrite the corrupt file
        post_r = self.client.post("/api/presets", json={**payload, "name": "Third"})
        self.assertEqual(post_r.status_code, 500)
        self.assertEqual(self.pfile.read_text(encoding="utf-8"), "{corrupt json")

        # Restore from backup
        res_r = self.client.post("/api/presets/restore")
        self.assertEqual(res_r.status_code, 200)
        names = [p["name"] for p in res_r.get_json()["presets"]]
        self.assertIn("HomeTown", names)

    def test_save_and_export_share_area_validation(self):
        # Zero-width rectangle (east == west) must be rejected on Save just like Export
        bad = {
            "name": "ZeroWidth",
            "south": 40.0, "west": -80.0, "north": 40.01, "east": -80.0,
            "metersPerTile": 1.0,
        }
        r_save = self.client.post("/api/presets", json=bad)
        self.assertEqual(r_save.status_code, 400)
        r_exp = self.client.post("/api/presets/validate", json={
            **bad, "format": "knoxmap-preset", "version": 1, "settings": {},
        })
        self.assertEqual(r_exp.status_code, 400)

        # Latitude > 85.05 must also be rejected on both
        bad_lat = {**bad, "east": -79.99, "north": 86.0}
        self.assertEqual(self.client.post("/api/presets", json=bad_lat).status_code, 400)


class ForecastRefinementTests(unittest.TestCase):
    def test_forecast_refines_build_and_compile_by_buildings_and_floors(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            # Past map 1: 10 buildings, 30 floors, 300x300 tiles
            m1 = out / "past_city"
            m1.mkdir()
            (m1 / "past_city_info.json").write_text(json.dumps({
                "width_tiles": 300, "height_tiles": 300,
            }), encoding="utf-8")
            with open(m1 / "past_city_buildings.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["file", "levels"])
                w.writeheader()
                for i in range(10):
                    w.writerow({"file": f"b{i}.tbx", "levels": "3"})
            mapstate.stamp(str(m1), "generate", took=90.0)
            mapstate.stamp(str(m1), "build", took=100.0)    # 10s per building
            mapstate.stamp(str(m1), "compile", took=150.0)  # 5s per floor

            # Target map with 2 buildings, 10 floors (much denser/taller or sparser)
            cur = out / "current"
            cur.mkdir()
            with open(cur / "current_buildings.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["file", "levels"])
                w.writeheader()
                w.writerow({"file": "t1.tbx", "levels": "5"})
                w.writerow({"file": "t2.tbx", "levels": "5"})

            # Without map_dir -> tile-based
            pre = forecast_mod.forecast(out, 40.0, 20.0, 40.002, 20.002, 1.0)
            self.assertEqual(pre["basis"]["build"], "tiles")
            self.assertEqual(pre["counts"]["build"], 1)

            # With map_dir -> building & floor refined
            post = forecast_mod.forecast(out, 40.0, 20.0, 40.002, 20.002, 1.0, map_dir=cur)
            self.assertEqual(post["basis"]["build"], "buildings")
            self.assertEqual(post["steps"]["build"], 20)     # 2 buildings * 10s
            self.assertEqual(post["basis"]["compile"], "floors")
            self.assertEqual(post["steps"]["compile"], 50)   # 10 floors * 5s
            self.assertEqual(post["counts"]["compile"], 1)


class OversizedLandmarkSummaryTests(unittest.TestCase):
    def test_why_summary_reports_split_and_skipped_oversized(self):
        with tempfile.TemporaryDirectory() as tmp:
            mdir = Path(tmp) / "hometown"
            mdir.mkdir()
            (mdir / "hometown_oversized.json").write_text(
                json.dumps({"split": 3, "skipped": 1}), encoding="utf-8"
            )
            with open(mdir / "hometown_left_out.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["reason", "tile_x", "tile_y", "lat", "lon",
                                                 "tiles_wide", "tiles_tall", "building", "name", "osm_id"])
                w.writeheader()
                w.writerow({"reason": "large", "tile_x": 10, "tile_y": 10, "lat": 0, "lon": 0,
                            "tiles_wide": 250, "tiles_tall": 250, "building": "industrial",
                            "name": "Big Plant", "osm_id": "123"})
            rep = why.summary(str(mdir))
            self.assertEqual(rep["oversized"], "3 oversized buildings split into units, 1 skipped")


class InGameTestMapTests(unittest.TestCase):
    def test_build_ingame_test_map_creates_route_and_all_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ingame_test_map"
            make_ingame_test_map.build_test_map(out)
            self.assertTrue((out / "ingame_test_map.bmp").is_file())
            self.assertTrue((out / "ingame_test_map.pzw").is_file())
            self.assertTrue((out / "ROUTE.txt").is_file())
            places = (out / "ingame_test_map_places.json").read_text(encoding="utf-8")
            self.assertIn("テスト駅", places)
            self.assertIn("الاختبار", places)
            self.assertIn("Тест", places)


if __name__ == "__main__":
    unittest.main()
