"""Regression coverage for solid tracks, linked garage panels and low roofs."""
import contextlib
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw

from generator import pz_colors as C
from generator.osm import OSMFeature
from generator.rendering import roads
from generator.rendering import rails
from knoxbuild import catalog, layout, tbx
from knoxbuild.buildtiles import parse_tbx, level_tiles
from knoxbuild.rules import load_rules
from knoxbuild.terrain import ground_layers, Palette
from worlded import patch_rules_roads


ROOT = Path(catalog.__file__).resolve().parents[1]
TOOLS_RULES = ROOT / "vendor/PZMappingTools/config/Rules.txt"


def _rules_for(folder: str) -> Path:
    """A config folder holding the rules KnoxMap writes, without the tools.

    These tests used to copy the PZMappingTools `Rules.txt` in, which is not in
    the repository - CI has no vendor folder, so they errored there and only
    ever ran on a machine with the tools installed. The rules they care about
    are the ones KnoxMap adds itself, written into an empty file by the same
    code Setup runs.
    """
    config = Path(folder) / "config"
    config.mkdir(exist_ok=True)
    (config / "Rules.txt").write_text("", encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        patch_rules_roads.main(["patch_rules_roads", folder])
    return config / "Rules.txt"


class RailGarageFixes(unittest.TestCase):
    def test_rail_tiles_survive_matching_street_detail_overlays(self):
        from generator.rail_tiles import RAIL_RULES
        with TemporaryDirectory() as folder:
            rules = load_rules(str(_rules_for(folder)))
        for label, colour, expected in RAIL_RULES:
            with self.subTest(tile=expected):
                pal = Palette()
                layers = ground_layers(np.array([[colour]], dtype=np.uint8),
                                       np.array([[(12, 36, 201)]], dtype=np.uint8),
                                       rules, pal, 1)
                self.assertEqual(pal.names[layers["0_FloorOverlay6"][0, 0]], expected)

    def test_compiler_does_not_reintroduce_legacy_rail_rules(self):
        from tools.compile_map import ensure_rail_rules
        with TemporaryDirectory() as folder:
            config = Path(folder) / "config"
            config.mkdir()
            path = config / "Rules.txt"
            path.write_text("rule\n{\n    label = Railroad NE-SW\n"
                            "    bitmap = 0\n    color = 200 30 200\n"
                            "    tiles = industry_railroad_01_6\n    layer = 0_Floor\n}\n",
                            encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(ensure_rail_rules(Path(folder)))
                self.assertFalse(ensure_rail_rules(Path(folder)))
            rules = load_rules(str(path))
            self.assertFalse(any(r.label.startswith("Railroad ") for r in rules.rules))
            self.assertFalse(any(r.entries == ["industry_railroad_01_6"]
                                 for r in rules.rules))

    def test_garage_opening_has_no_house_jambs_or_hanging_switches(self):
        for side in "NSEW":
            with self.subTest(side=side):
                building = layout.build_building(8, 8, kind="garage", street=side,
                                                 garage_door=True, seed=8)
                plan = building.storeys[0]
                opening = set(plan.garage_door_tiles)
                self.assertTrue(any(role == layout.SWITCH for role, *_ in plan.furniture))
                self.assertTrue(all(layout._hangs_on_wall(plan, role, x, y, facing, opening)
                                    for role, x, y, facing in plan.furniture
                                    if layout._is_wall_piece(role)))
                compiled = level_tiles(parse_tbx(tbx.render_tbx(building, "garage")), 0)
                for x, y, d in opening:
                    jambs = [name for name in compiled[(x, y)]
                             if name.startswith(("walls_interior_", "walls_exterior_"))]
                    self.assertEqual(jambs, [])

    def test_native_rail_sections_join_without_conflicting_tiles(self):
        from generator.rendering.rails import rail_sections
        from generator.rail_tiles import ASSEMBLIES
        for points in ([(5, 10), (90, 17)], [(5, 30), (90, 23)],
                       [(5, 5), (30, 5), (60, 20), (100, 5)],
                       [(10, 10), (40, 40)], [(10, 40), (40, 10)],
                       [(5, 10), (35, 10), (40, 40)]):
            with self.subTest(points=points):
                sections = list(rail_sections(points))
                self.assertTrue(sections)
                self.assertEqual(list(rail_sections(list(reversed(points)))), sections)
                tiles = {}
                previous_ports = None
                for ox, oy, index in sections:
                    ports = {(ox * 2 + x, oy * 2 + y) for x, y in ASSEMBLIES[index][:2]}
                    if previous_ports is not None:
                        self.assertEqual(len(ports & previous_ports), 1)
                    previous_ports = ports
                    for x, y, sheet, tile in ASSEMBLIES[index][4]:
                        previous = tiles.setdefault((ox + x, oy + y), (sheet, tile))
                        self.assertEqual(previous, (sheet, tile))
                # A bend must use curved art, rather than a shifted straight strip.
                if points[0][1] == 10 and points[-1][1] == 17:
                    self.assertTrue(any(index >= 4 for x, y, index in sections))

    def test_split_osm_ways_are_routed_as_one_track(self):
        from generator.rendering.rails import joined_tracks, rail_sections
        points = [(5, 10), (35, 12), (70, 20), (100, 20)]
        joined = list(joined_tracks([points[:2], list(reversed(points[1:3])), points[2:]]))
        self.assertEqual(len(joined), 1)
        self.assertEqual(list(rail_sections(joined[0])), list(rail_sections(points)))

    @unittest.skipUnless(TOOLS_RULES.exists(),
                         "needs the mapping tools' own Rules.txt, from which the "
                         "ground blends come; a checkout has no vendor folder")
    def test_track_has_both_rails_and_sleepers_over_solid_ground(self):
        with TemporaryDirectory() as folder:
            config = Path(folder) / "config"
            config.mkdir()
            path = config / "Rules.txt"
            path.write_text(TOOLS_RULES.read_text(encoding="utf-8"), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                patch_rules_roads.main(["patch_rules_roads", folder])
                once = path.read_text(encoding="utf-8")
                patch_rules_roads.main(["patch_rules_roads", folder])
            self.assertEqual(path.read_text(encoding="utf-8"), once)
            rules = load_rules(str(path))
            for ring, coords, tiles in (
                    ([(2, 10), (18, 10)], [(10, 9), (10, 10), (10, 11)], [5, 4, 3]),
                    ([(10, 2), (10, 18)], [(9, 10), (10, 10), (11, 10)], [0, 1, 2])):
                for points in (ring, list(reversed(ring))):
                    with self.subTest(points=points):
                        img = Image.new("RGB", (22, 22), C.DIRT)
                        feat = OSMFeature(1, "way", {"railway": "rail"}, [[0, 0], [0, 1]])
                        with mock.patch.object(rails, "_feature_coords_px", return_value=[points]):
                            roads.paint_rails(ImageDraw.Draw(img), {"railway": [feat]},
                                              mock.Mock(meters_per_tile=1.0, width=22, height=22))
                        pal = Palette()
                        layers = ground_layers(np.asarray(img), np.zeros((22, 22, 3),
                                               dtype=np.uint8), rules, pal, 1)
                        for (x, y), tile in zip(coords, tiles):
                            self.assertTrue(pal.names[layers["0_Floor"][y, x]].startswith("blends_"))
                            self.assertEqual(pal.names[layers["0_FloorOverlay6"][y, x]],
                                             f"industry_railroad_01_{tile}")

    def test_panels_follow_the_games_linking_order_on_all_four_sides(self):
        for side in "NSEW":
            for position in (0, 3, 7):
                with self.subTest(side=side, position=position):
                    plan = layout.build_plan(8, 8, kind="garage", commercial=True, seed=8)
                    wall = next(wall for face, wall in layout._outside_runs(plan, 1) if face == side)
                    plan.doors = [wall[position]]
                    layout._widen_vehicle_entry(plan, side)
                    building = parse_tbx(tbx.render_tbx(plan, "garage"))
                    panels = [o for o in building.floors[0].objects if o["type"] == "door"]
                    panels.sort(key=lambda o: int(o["x"]) if o["dir"] == "N" else -int(o["y"]))
                    self.assertEqual(len(panels), 3)
                    compiled = level_tiles(building, 0)
                    for slot, obj in enumerate(panels):
                        d = "North" if obj["dir"] == "N" else "West"
                        expected = f"walls_garage_02_{slot + (3 if d == 'North' else 0)}"
                        self.assertEqual(building.entries[int(obj["Tile"]) - 1][d], expected)
                        self.assertIn(expected, compiled[(int(obj["x"]), int(obj["y"]))])

    def test_narrow_walls_keep_a_regular_door(self):
        plan = layout.build_plan(8, 8, kind="garage", commercial=True, seed=8)
        wall = [(0, 0, "N"), (1, 0, "N")]
        plan.doors = [wall[0]]
        with mock.patch.object(layout, "_outside_runs", return_value=[("N", wall)]):
            layout._widen_vehicle_entry(plan, "N")
        self.assertEqual(plan.doors, [wall[0]])
        self.assertFalse(getattr(plan, "garage_door_tiles", ()))

    def test_small_garages_keep_gables_in_both_orientations(self):
        for width, height in ((3, 6), (6, 3), (4, 6), (6, 4), (8, 12), (12, 8), (15, 23), (23, 15)):
            with self.subTest(width=width, height=height):
                plan = layout.build_plan(width, height, kind="garage", commercial=True, seed=8)
                model = parse_tbx(tbx.render_tbx(plan, "garage"))
                roofs = [o for f in model.floors for o in f.objects if o["type"] == "roof"]
                pitched = [o for o in roofs if o["RoofType"] != "FlatTop"]
                self.assertTrue(pitched)
                expected = "Peak30WE" if width >= height else "Peak30NS"
                self.assertEqual({o["RoofType"] for o in pitched}, {expected})
                self.assertTrue(all(o["Depth"] == "Zero" for o in pitched))
                covered = level_tiles(model, 1)
                for y in range(height):
                    for x in range(width):
                        if plan.grid[y][x]:
                            self.assertTrue(any(t.startswith("roofs_") for t in covered[(x, y)]))

    def test_garages_have_stock_shingled_gables_with_every_style(self):
        plan = layout.build_plan(12, 10, kind="garage", commercial=True, seed=8)
        for style in [None] + catalog.HOUSE_STYLES:
            with self.subTest(style=(style or {}).get("name")):
                document = tbx.render_tbx(plan, "garage", style)
                roofs = ET.fromstring(document).findall("./floor/object[@type='roof']")
                self.assertTrue(roofs)
                self.assertEqual({o.get("RoofType") for o in roofs}, {"FlatTop", "Peak30WE"})
                gable = next(o for o in roofs if o.get("RoofType") == "Peak30WE")
                self.assertEqual(gable.get("Depth"), "Zero")
                self.assertEqual(gable.get("cappedW"), "true")
                self.assertEqual(gable.get("cappedE"), "true")
                model = parse_tbx(document)
                slope = model.entries[int(gable.get("SlopeTiles")) - 1]
                self.assertTrue(slope["Slope30S1"].startswith("roofs_30_02_"))
                compiled = level_tiles(parse_tbx(document), 1)
                for y in range(plan.height):
                    for x in range(plan.width):
                        if plan.grid[y][x]:
                            self.assertTrue(any(t.startswith("roofs_") for t in compiled[(x, y)]))


if __name__ == "__main__":
    unittest.main()
