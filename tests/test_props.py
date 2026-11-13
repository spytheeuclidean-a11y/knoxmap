import os
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np
from PIL import Image
from shapely.geometry import Point, Polygon

from generator import osm, pz_colors as C, renderer
from knoxbuild.props import _blocked_mask, place_props


class OutdoorProps(unittest.TestCase):
    def test_park_polygons_are_exported_for_outdoor_furnishing(self):
        park = osm.OSMFeature(
            1, "way", {"leisure": "park", "name": "Town Green"},
            [(5, 5), (5, 25), (25, 25), (25, 5), (5, 5)])

        exported = renderer._areas_geojson({"park": [park]})

        self.assertEqual(len(exported["features"]), 1)
        self.assertEqual(exported["features"][0]["properties"]["category"], "park")

    def test_road_and_sidewalk_colors_are_blocked_for_props(self):
        colors = (C.DARK_ASPHALT, C.MEDIUM_ASPHALT, C.LIGHT_ASPHALT,
                  C.DARKEST_ASPHALT, C.PALE_CONCRETE, C.DARK_POTHOLE,
                  C.LIGHT_POTHOLE, C.DARK_GRASS)
        ground = np.array([[color for color in colors]], dtype=np.uint8)

        blocked = _blocked_mask(ground)

        np.testing.assert_array_equal(blocked[0],
                                      [True] * (len(colors) - 1) + [False])

    def test_picnic_tables_stay_inside_parks_and_off_buildings_and_roads(self):
        with TemporaryDirectory() as directory:
            bdir = os.path.join(directory, "buildings")
            os.mkdir(bdir)
            ground = Image.new("RGB", (200, 200), C.MEDIUM_GRASS)
            pixels = ground.load()
            for y in range(200):
                pixels[100, y] = C.MEDIUM_ASPHALT
            ground.save(os.path.join(directory, "park.bmp"))
            Image.new("RGB", ground.size, C.TREES).save(
                os.path.join(directory, "park_veg.bmp"))
            occupied = np.zeros((200, 200), dtype=bool)
            occupied[90:98, 90:98] = True
            before = occupied.copy()
            park = Polygon([(2, 2), (198, 2), (198, 198), (2, 198)])
            areas = SimpleNamespace(_items=[(park, {"category": "park"})])

            placements, counts = place_props(
                directory, "park", bdir, occupied, areas, metres_per_tile=1.0,
                seed=42)

            self.assertGreater(counts["picnic_tables"], 0)
            self.assertTrue(placements)
            added = occupied & ~before
            self.assertEqual(int(added.sum()), counts["picnic_tables"] * 4)
            self.assertFalse(added[:, 100].any())
            self.assertFalse(added[90:98, 90:98].any())
            for y, x in zip(*np.nonzero(added)):
                self.assertTrue(park.contains(Point(x + 0.5, y + 0.5)))

    def test_cemetery_places_neat_rows_floors_and_statues(self):
        with TemporaryDirectory() as directory:
            bdir = os.path.join(directory, "buildings")
            os.mkdir(bdir)
            ground = Image.new("RGB", (60, 60), C.LIGHT_GRASS)
            ground.save(os.path.join(directory, "graveyard.bmp"))
            Image.new("RGB", ground.size, C.VEG_NOTHING).save(
                os.path.join(directory, "graveyard_veg.bmp"))
            occupied = np.zeros((60, 60), dtype=bool)
            cemetery = Polygon([(4, 4), (44, 4), (44, 34), (4, 34)])
            areas = SimpleNamespace(_items=[(cemetery, {"category": "cemetery"})])

            placements, counts = place_props(
                directory, "graveyard", bdir, occupied, areas,
                metres_per_tile=1.0, seed=7)

            self.assertGreater(counts["graves"], 20)
            self.assertTrue(placements)
            tbx_name = next(n for n in os.listdir(bdir) if n.endswith(".tbx"))
            with open(os.path.join(bdir, tbx_name), encoding="utf-8") as handle:
                tbx = handle.read()
            self.assertIn('layer="Floor"', tbx)
            self.assertIn('layer="FloorFurniture"', tbx)
            self.assertIn('layer="Furniture"', tbx)
            # No open grave pits, rock cairns, or rope posts from the old broken list.
            for bad in ("_016", "_017", "_019", "_020", "_021", "_030", "_031"):
                self.assertNotIn(f"location_community_cemetary_01{bad}", tbx)
            # Contains actual headstones and a focal angel statue.
            self.assertTrue(
                any(f"location_community_cemetary_01_00{n}" in tbx for n in (0, 2, 4, 8)))
            self.assertTrue(
                any(f"location_community_cemetary_01_0{n}" in tbx for n in (11, 12, 13, 14)))


if __name__ == "__main__":
    unittest.main()

class TileNames(unittest.TestCase):
    """The tile names the prop lists carry have to be the names the game has.

    `location_military_generic_01_8` and `..._008` are two different strings,
    and a tbx that names a tile the pack does not have loses it without a
    word - a cemetery of empty grass. BuildingFurniture.txt is the editor's own
    list of what can be placed, and it spells every one of these sheets with
    three digits, so that is how ours are spelled and how they are checked.
    """

    @staticmethod
    def _names() -> list[str]:
        from knoxbuild import props

        return sorted(set(props.HEADSTONES) | set(props.CROSSES) | set(props.ANGELS)
                      | set(props.CRATES) | set(props.DRUMS)
                      | set(props.BARRICADE_X) | set(props.BARRICADE_Y))

    def test_three_digit_names(self):
        names = self._names()
        self.assertTrue(names)
        for name in names:
            self.assertRegex(name, r"^[a-z0-9_]+_[0-9]{3}$")

    def test_and_the_editor_lists_every_one_of_them(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "vendor", "PZMappingTools", "config",
                            "BuildingFurniture.txt")
        if not os.path.exists(path):
            self.skipTest("no tile definitions on this machine")
        with open(path, encoding="utf-8", errors="ignore") as handle:
            defined = handle.read()
        missing = [name for name in self._names() if f"= {name}" not in defined]
        self.assertEqual(missing, [], f"not a piece the editor can place: {missing}")
