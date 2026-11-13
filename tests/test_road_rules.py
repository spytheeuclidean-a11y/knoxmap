"""Tests for road detail rules patching, curb catalogues, and B42 compatibility."""
import re
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image

import knoxpaths
from worlded import patch_rules_roads
import knoxmap_setup


class RoadRulesTests(unittest.TestCase):
    def test_patch_rules_roads_b42_soil_resilience(self):
        """Build 42 lacks floors_exterior_natural_01_18; ensure Yard bed_soil rule survives."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            cfg.mkdir()
            rules_file = cfg / "Rules.txt"
            # Start with CRLF and older litter rule containing trash_01_13
            rules_file.write_text(
                "rule\r\n{\r\n    label = KnoxMap road Litter\r\n    bitmap = 1\r\n"
                "    color = 12 36 208\r\n    tiles = [\r\n        trash_01_0\r\n"
                "        trash_01_13\r\n    ]\r\n    layer = 0_FloorOverlay6\r\n}\r\n",
                encoding="utf-8",
            )

            two_x = root / "Tiles" / "2x"
            two_x.mkdir(parents=True)
            # Simulate B42 floors_exterior_natural_01.png where 18 is blank
            img = Image.new("RGBA", (8 * 128, 7 * 256), (0, 0, 0, 0))
            arr = np.array(img)
            for idx in [8, 9, 10, 11, 16, 17]:
                r, c = divmod(idx, 8)
                arr[r * 256 : (r + 1) * 256, c * 128 : (c + 1) * 128, 3] = 255
            Image.fromarray(arr).save(two_x / "floors_exterior_natural_01.png")

            ret = patch_rules_roads.main(["patch_rules_roads.py", str(root)])
            self.assertEqual(ret, 0)

            txt = rules_file.read_text(encoding="utf-8")
            self.assertNotIn("trash_01_13", txt)
            self.assertIn("KnoxMap road Yard bed_soil", txt)
            self.assertIn("floors_exterior_natural_01_016", txt)
            # And never the short form: Build 42 has no tile called _18.
            self.assertNotIn("floors_exterior_natural_01_18 ", txt)
            self.assertTrue(knoxpaths.road_rules_ok(root))

    def parse_rules(self, text):
        """label -> (colour, tile, layer, bitmap) for every rule block."""
        rules = {}
        for body in re.findall(r"rule\s*\{(.*?)\}", text, re.S):
            label = re.search(r"label = (.+)", body).group(1).strip()
            colour = re.search(r"color = ([^\n]+)", body).group(1).strip()
            tile = re.search(r"tiles = ([^\n\[]+)", body)
            layer = re.search(r"layer = (.+)", body).group(1).strip()
            bitmap = re.search(r"bitmap = (\d)", body).group(1)
            self.assertNotIn(label, rules, f"{label} is written twice")
            rules[label] = (colour, tile.group(1).strip() if tile else "", layer, bitmap)
        return rules

    def test_the_prop_rules_are_written_once_each_and_cleanly(self):
        """Every street and yard prop reaches Rules.txt once, with its own
        colour and the layer it belongs on - including a rule an older install
        already has, which must be rewritten in place rather than duplicated."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            cfg.mkdir()
            rules_file = cfg / "Rules.txt"
            # An install set up by an older build: the bench rule still names
            # the concrete wheel-stop tile it was first written with.
            rules_file.write_text(
                "rule\r\n{\r\n    label = KnoxMap road Bench Y0\r\n    bitmap = 1\r\n"
                "    color = 12 41 200\r\n    tiles = street_decoration_032\r\n"
                "    layer = 0_Furniture\r\n}\r\n",
                encoding="utf-8",
            )
            (root / "Tiles" / "2x").mkdir(parents=True)

            self.assertEqual(patch_rules_roads.main(["patch_rules_roads.py", str(root)]), 0)
            text = rules_file.read_text(encoding="utf-8")
            rules = self.parse_rules(text)

            expected = {
                "KnoxMap road Bench Y0": ("furniture_seating_outdoor_01_023", "0_Furniture"),
                "KnoxMap road Bench Y1": ("furniture_seating_outdoor_01_022", "0_Furniture"),
                "KnoxMap road Bench X1": ("furniture_seating_outdoor_01_021", "0_Furniture"),
                "KnoxMap road Kiosk W": ("street_decoration_01_080", "0_Furniture"),
                "KnoxMap road Postbox N": ("street_decoration_01_008", "0_Furniture"),
                "KnoxMap road Parking block X0": ("street_decoration_01_032", "0_Furniture"),
                "KnoxMap road Parking block Y2": ("street_decoration_01_035", "0_Furniture"),
                "KnoxMap road Utility pole": ("street_decoration_01_024", "0_Furniture"),
                "KnoxMap road Dog house": ("constructedobjects_01_004", "0_Furniture"),
                # Ground detail, not furniture: it goes on the overlay layer.
                "KnoxMap road Manhole cover": ("street_decoration_01_015", "0_FloorOverlay6"),
            }
            for label, (tile, layer) in expected.items():
                with self.subTest(rule=label):
                    self.assertIn(label, rules)
                    self.assertEqual(rules[label][1], tile)
                    self.assertEqual(rules[label][2], layer)

            # Our props are keyed by colour, so no two of them may share one:
            # the tools would paint whichever rule came last everywhere.
            prop_prefixes = ("Bench", "Kiosk", "Postbox", "Parking block",
                             "Manhole cover", "Utility pole", "Dog house")
            prop_colours = [values[0].split()[0:3] for label, values in rules.items()
                            if label.removeprefix("KnoxMap road ").startswith(prop_prefixes)]
            self.assertGreater(len(prop_colours), 20, "the prop rules are missing")
            self.assertEqual(len(prop_colours), len({tuple(c) for c in prop_colours}),
                             "two props share a colour")
            layers = {values[2] for values in rules.values()}
            self.assertTrue(all(layer.startswith("0_") for layer in layers),
                            f"a rule went onto a layer the tools do not use: {layers}")

            # Running Setup again must not grow the file or reorder it.
            self.assertEqual(patch_rules_roads.main(["patch_rules_roads.py", str(root)]), 0)
            self.assertEqual(rules_file.read_text(encoding="utf-8"), text)

    def test_each_rail_colour_lays_a_bed_and_a_track(self):
        """One colour, two rules, two layers - on purpose.

        The tools match every rule against the pixel and place its tile on that
        rule's layer, so a rail's colour lays the lightgravel bed on 0_Floor and
        the track piece on 0_FloorOverlay6. One square of a bitmap holds one
        colour, so giving the two rules different colours would mean one of the
        tiles is never painted at all.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config"
            cfg.mkdir()
            (cfg / "Rules.txt").write_text("version = 1\n", encoding="utf-8")
            (root / "Tiles" / "2x").mkdir(parents=True)
            self.assertEqual(patch_rules_roads.main(["patch_rules_roads.py", str(root)]), 0)
            rules = self.parse_rules((cfg / "Rules.txt").read_text(encoding="utf-8"))

        rails: dict[str, list[tuple[str, str, str]]] = {}
        for label, (colour, tile, layer, bitmap) in rules.items():
            if " Rail " in label:
                rails.setdefault(colour, []).append((tile, layer, bitmap))
        self.assertTrue(rails, "no rail rules were written")
        for colour, uses in rails.items():
            with self.subTest(colour=colour):
                self.assertEqual(len(uses), 2,
                                 "a rail colour must lay its bed and its track")
                self.assertEqual({layer for _t, layer, _b in uses},
                                 {"0_Floor", "0_FloorOverlay6"})
                self.assertEqual({bitmap for _t, _l, bitmap in uses}, {"0"})
                bed = [tile for tile, layer, _b in uses if layer == "0_Floor"]
                track = [tile for tile, layer, _b in uses if layer == "0_FloorOverlay6"]
                self.assertEqual(bed, ["lightgravel"])
                self.assertTrue(track[0].startswith("industry_railroad_"))

        # No two different rails may share a colour, or one would lay the other's
        # track, and no prop may collide with a rail either.
        self.assertEqual(len(rails), len({label for label in rules if " Rail " in label}) // 2)
        prop_colours = {values[0] for label, values in rules.items()
                        if not label.removeprefix("KnoxMap road ").startswith("Rail ")}
        self.assertEqual(set(rails) & prop_colours, set())

    def test_ensure_road_catalogue(self):
        """Verify ensure_road_catalogue adds curb and marking sheets to empty catalogue."""
        with tempfile.TemporaryDirectory() as tmp:
            tilesets = Path(tmp) / "Tilesets.txt"
            tilesets.write_text("version = 1\n", encoding="utf-8")
            knoxmap_setup.ensure_road_catalogue(tilesets)

            content = tilesets.read_text(encoding="utf-8")
            self.assertIn("street_curbs_01", content)
            self.assertIn("street_trafficlines_01", content)
            self.assertIn("floors_exterior_natural_01", content)


if __name__ == "__main__":
    unittest.main()
