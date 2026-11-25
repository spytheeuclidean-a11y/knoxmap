"""Tests for Melos Tiles for Miles (workshop 2879745353) integration."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import knoxpaths
from knoxbuild import build, catalog as C, furnish_rules, layout, tbx
from knoxbuild.layout import furnishing
from tools import make_map_mod, make_map_workshop


class MelosCatalogTests(unittest.TestCase):
    def test_catalog_has_melos_roles_and_layers(self):
        self.assertGreater(len(C.MELOS_WALL_ART), 100)
        self.assertGreater(len(C.MELOS_PLANTS), 10)
        self.assertGreater(len(C.MELOS_SHELVES), 5)
        self.assertGreater(len(C.MELOS_STOREFRONTS), 10)
        self.assertTrue(C.MELOS_SIGNS["N"])
        self.assertTrue(C.MELOS_SIGNS["W"])
        for role in C.MELOS_WALL_ART:
            self.assertIn(role, C.FURNITURE)
            self.assertEqual(C.FURNITURE_LAYERS[role], "WallFurniture")
            self.assertIn(role, furnishing.NORTH_WEST_ONLY)
        for role in C.MELOS_PLANTS + C.MELOS_SHELVES:
            self.assertIn(role, C.FURNITURE)
            self.assertEqual(C.FURNITURE_LAYERS[role], "Furniture")
        self.assertGreater(sum(len(v) for v in C.MELOS_EXTERIOR_WALLS.values()), 100)
        self.assertGreater(len(C.MELOS_INTERIOR_WALLS), 50)

    def test_melos_building_styles_in_pick_style_and_wall_variants(self):
        with mock.patch("knoxbuild.layout._melos_ready", return_value=True), \
                mock.patch("knoxbuild.layout._erika_ready", return_value=True):
            variants = build.wall_variants("shop")
            self.assertTrue(any("melos_tiles_walls_" in v["name"] for v in variants))
            self.assertTrue(any("erika_" in v["name"] for v in variants))
            counts = {"melos": 0, "erika": 0, "vanilla": 0}
            for x in range(200):
                name = build.pick_style(
                    None, x * 17 + 3, x * 29 + 5, build.random.Random(x), build.Settings()
                ).get("name", "")
                if name.startswith("melos_tiles_walls_"):
                    counts["melos"] += 1
                elif "erika_" in name:
                    counts["erika"] += 1
                else:
                    counts["vanilla"] += 1
            # ~18% Melos, ~15% Erika, ~67% Vanilla
            self.assertTrue(20 <= counts["melos"] <= 55, counts)
            self.assertTrue(15 <= counts["erika"] <= 48, counts)
            self.assertGreater(counts["vanilla"], 110, counts)

    def test_melos_houses_use_hipped_or_flat_roofs_without_gables(self):
        with mock.patch("knoxbuild.layout._melos_ready", return_value=True):
            melos_style = next(s for s in build._melos_house_styles()
                               if "brick_02_blue" in s["name"])
            small = layout.build_building(10, 7, levels=1, kind="house", seed=1, street="S")
            xml_small = tbx.render_tbx(small, "melos-hip", melos_style)
            self.assertIn('RoofType="Peak30Quad"', xml_small)
            for gabled in ('PeakWE', 'PeakNS', 'Peak30WE', 'Peak30NS'):
                self.assertNotIn(f'RoofType="{gabled}"', xml_small)

            wide = layout.build_building(16, 14, levels=1, kind="house", seed=2, street="S")
            xml_wide = tbx.render_tbx(wide, "melos-flat", melos_style)
            self.assertIn('RoofType="FlatTop"', xml_wide)
            for gabled in ('PeakWE', 'PeakNS', 'Peak30WE', 'Peak30NS'):
                self.assertNotIn(f'RoofType="{gabled}"', xml_wide)

    def test_melos_plants_are_floor_standing(self):
        self.assertFalse(furnishing._needs_surface(C.MELOS_PLANTS[0]))
        self.assertTrue(furnishing._needs_surface("erika_plant_0"))

    def test_decoration_roles_and_concourse_keep(self):
        self.assertIn("melos_plant", furnish_rules.DECORATION_ROLES)
        self.assertIn("melos_shelves", furnish_rules.DECORATION_ROLES)
        self.assertIn("melos_art", furnish_rules.DECORATION_ROLES)
        self.assertIn("melos_plant", layout.malls.CONCOURSE_KEEP)


class MelosFurnishingAndStorefrontTests(unittest.TestCase):
    def setUp(self):
        self._erika = list(furnishing._ERIKA_ALLOWED)
        self._melos = list(furnishing._MELOS_ALLOWED)

    def tearDown(self):
        furnishing._ERIKA_ALLOWED[:] = self._erika
        furnishing._ERIKA.clear()
        furnishing._MELOS_ALLOWED[:] = self._melos
        furnishing._MELOS.clear()

    def test_use_mod_tiles_controls_both_erika_and_melos(self):
        furnishing.use_mod_tiles(False)
        self.assertFalse(furnishing._erika_ready())
        self.assertFalse(furnishing._melos_ready())

    def test_livingroom_and_shop_with_melos_only(self):
        with mock.patch.object(furnishing, "_erika_ready", lambda: False), \
                mock.patch.object(furnishing, "_melos_ready", lambda: True), \
                mock.patch.object(tbx, "_erika_ready", lambda: False), \
                mock.patch.object(tbx, "_melos_ready", lambda: True):
            plan = layout.build_plan(12, 10, kind="house", seed="melos-house", levels=1)
            roles = {f[0] for f in plan.furniture}
            self.assertTrue(any(r.startswith("melos_") for r in roles), roles)

            shop = layout.build_building(18, 12, levels=2, commercial=True,
                                         kind="shop", seed=3, street="S")
            xml_text = tbx.render_tbx(shop, "melos-shop", C.SPECIAL_STYLES["shop"])
            self.assertIn("melos_tiles_walls_commercial_", xml_text)

    def test_storefront_works_alongside_erika(self):
        with mock.patch.object(furnishing, "_erika_ready", lambda: True), \
                mock.patch.object(furnishing, "_melos_ready", lambda: True), \
                mock.patch.object(tbx, "_erika_ready", lambda: True), \
                mock.patch.object(tbx, "_melos_ready", lambda: True):
            # Across several seeds, both Erika and Melos storefronts should be selectable
            fronts = []
            for i in range(25):
                shop = layout.build_building(18, 12, levels=2, commercial=True,
                                             kind="shop", seed=i, street="S")
                xml_text = tbx.render_tbx(shop, f"combo-{i}", C.SPECIAL_STYLES["shop"])
                if "melos_tiles_walls_commercial_" in xml_text:
                    fronts.append("melos")
                if "walls_commercial_erika_" in xml_text:
                    fronts.append("erika")
            self.assertIn("melos", fronts)
            self.assertIn("erika", fronts)


class MelosPackagingAndCacheTests(unittest.TestCase):
    def test_server_setup_with_melos_and_erika(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_map_mod.write_server_setup(
                tmp, "mymap", "My Map", "My Map",
                needs_erika=True, needs_melos=True,
            )
            txt = (Path(tmp) / "SERVER SETUP.txt").read_text(encoding="utf-8")
            self.assertIn(knoxpaths.ERIKAS_TILES_MOD_ID, txt)
            self.assertIn(knoxpaths.MELOS_TILES_MOD_ID, txt)
            self.assertIn(knoxpaths.ERIKAS_TILES_WORKSHOP_ID, txt)
            self.assertIn(knoxpaths.MELOS_TILES_WORKSHOP_ID, txt)

    def test_cache_fingerprint_changes_with_melos_ready(self):
        with mock.patch("knoxbuild.layout._erika_ready", return_value=False), \
                mock.patch("knoxbuild.layout._melos_ready", return_value=False):
            fp_off = build._code_fingerprint()
        with mock.patch("knoxbuild.layout._erika_ready", return_value=False), \
                mock.patch("knoxbuild.layout._melos_ready", return_value=True):
            fp_on = build._code_fingerprint()
        self.assertNotEqual(fp_off, fp_on)

    def test_workshop_description_mentions_melos(self):
        with tempfile.TemporaryDirectory() as tmp:
            mods_dir = Path(tmp) / "mods"
            ws_dir = Path(tmp) / "workshop"
            mod_root = mods_dir / "mymap"
            mod_root.mkdir(parents=True)
            (mod_root / "mod.info").write_text(
                "name=My Map\nid=mymap\nrequire=Erikas_Tiles,melos_tiles_for_miles_pack\n",
                encoding="utf-8",
            )
            target = make_map_workshop.build("mymap", mods_dir, ws_dir)
            ws_txt = (target / "workshop.txt").read_text(encoding="utf-8")
            self.assertIn("Erika's Tiles", ws_txt)
            self.assertIn("Melos Tiles", ws_txt)


if __name__ == "__main__":
    unittest.main()
