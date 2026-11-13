"""The street props' tiles, checked against the map tools' own catalogue.

The colours (generator/pz_colors.py) and rules (worlded/patch_rules_roads.py)
were written by hand, and a wrong guess about which sprite faces which way
puts a bench across the pavement instead of along it - or a kiosk with its
newspaper window in a wall. BuildingFurniture.txt records the tile the game
uses for every orientation, so that is what these tests read: the mapping is
checked against the catalogue rather than against memory.
"""
import re
import unittest
from pathlib import Path

from generator import pz_colors as C
from generator.rendering import furniture
from worlded import patch_rules_roads

ROOT = Path(__file__).resolve().parent.parent
CATALOGUE = ROOT / "vendor" / "PZMappingTools" / "config" / "BuildingFurniture.txt"


def catalogue() -> dict[str, set[tuple[str, str]]]:
    """(orient, offset) pairs the tools list for each tile."""
    text = CATALOGUE.read_text(encoding="utf-8", errors="replace")
    places: dict[str, set[tuple[str, str]]] = {}
    for block in re.split(r"\n\s*furniture\s*\n\s*\{", text)[1:]:
        for orient, body in re.findall(
                r"orient = (\w)\s*\n((?:\s*\d+,\d+\s*=\s*\S+\s*\n)+)", block):
            for offset, tile in re.findall(r"(\d+,\d+) = (\S+)", body):
                places.setdefault(tile, set()).add((orient, offset))
    return places


def rule_tile(label: str) -> str:
    for name, _colour, tile, _layer in patch_rules_roads.RULES:
        if name == label:
            return tile
    raise AssertionError(f"no rule called {label!r}")


@unittest.skipUnless(CATALOGUE.exists(),
                     "the tool list is made from an installed game, so a "
                     "checkout without one has nothing to read")
class CatalogueOrientation(unittest.TestCase):
    def test_the_bench_pairs_run_the_way_their_names_say(self):
        """Orient W is a bench two squares along y, orient N two along x; a
        backless bench has no other orientations, so these four tiles are all
        there is to be right or wrong about."""
        places = catalogue()
        self.assertIn(("W", "0,0"), places[rule_tile("Bench Y0")])
        self.assertIn(("W", "0,1"), places[rule_tile("Bench Y1")])
        self.assertIn(("N", "0,0"), places[rule_tile("Bench X0")])
        self.assertIn(("N", "1,0"), places[rule_tile("Bench X1")])

    def test_each_kiosk_and_collection_box_has_the_orientation_in_its_name(self):
        places = catalogue()
        for kind in ("Kiosk", "Postbox"):
            for facing in "NESW":
                label = f"{kind} {facing}"
                with self.subTest(rule=label):
                    self.assertIn((facing, "0,0"), places[rule_tile(label)])

    def test_the_yard_props_are_the_sprites_their_rules_name(self):
        places = catalogue()
        self.assertIn(("N", "0,0"), places[rule_tile("Dog house")])
        # The swing is a single hanging seat, which the catalogue does not list
        # on its own; it is the middle seat of the park set.
        self.assertTrue(rule_tile("Swing").startswith("location_community_park_01_"))

    def test_every_prop_colour_is_unique(self):
        seen = set()
        for name, colour, _tile, _layer in patch_rules_roads.RULES:
            with self.subTest(rule=name):
                self.assertNotIn(colour, seen, f"{name} reuses a colour")
                seen.add(colour)


class FacingTheRoad(unittest.TestCase):
    def test_a_prop_faces_across_the_road_it_stands_beside(self):
        """The tools' orient is the direction the object points. roads.py
        paints KERB_W on the strip whose road lies to its west, and that kerb's
        face looks west over it; tools/make_catalog.py has to invert a tile's
        Facing only for wall objects, which stand against the opposite wall.
        So a prop on the east side of a north-south road, with the road to its
        west, takes the west-facing sprite."""
        self.assertEqual(furniture.FACES_THE_ROAD[C.EDGE_LINE_E], "W")
        self.assertEqual(furniture.FACES_THE_ROAD[C.EDGE_LINE_W], "E")
        self.assertEqual(furniture.FACES_THE_ROAD[C.EDGE_LINE_N], "S")
        self.assertEqual(furniture.FACES_THE_ROAD[C.EDGE_LINE_S], "N")

    def test_a_bench_lies_along_its_kerb(self):
        """The catalogue's W bench runs along y and its N bench along x, so a
        road running north-south (kerb along y) takes the y pair."""
        self.assertEqual(furniture.BENCH_RUNS[C.EDGE_LINE_E], (C.BENCH_Y, True))
        self.assertEqual(furniture.BENCH_RUNS[C.EDGE_LINE_W], (C.BENCH_Y, True))
        self.assertEqual(furniture.BENCH_RUNS[C.EDGE_LINE_N], (C.BENCH_X, False))
        self.assertEqual(furniture.BENCH_RUNS[C.EDGE_LINE_S], (C.BENCH_X, False))

    def test_the_facings_the_props_use_are_colours_the_rules_carry(self):
        rules = {colour for _name, colour, _tile, _layer in patch_rules_roads.RULES}
        for edge, facing in furniture.FACES_THE_ROAD.items():
            with self.subTest(edge=edge):
                self.assertIn(getattr(C, f"KIOSK_{facing}"), rules)
                self.assertIn(getattr(C, f"POSTBOX_{facing}"), rules)


if __name__ == "__main__":
    unittest.main()
