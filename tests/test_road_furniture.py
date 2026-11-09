import unittest
from unittest import mock

from PIL import Image

from generator import pz_colors as C
from generator import renderer
from generator.rendering import furniture


class RoadFurniturePlacement(unittest.TestCase):
    def make_road(self, roadside):
        ground = Image.new("RGB", (40, 40), C.DARK_GRASS)
        pixels = ground.load()
        for y in range(40):
            for x in range(8, 13):
                pixels[x, y] = C.MEDIUM_ASPHALT
            pixels[13, y] = C.PALE_CONCRETE
            pixels[14, y] = roadside
        vegetation = Image.new("RGB", ground.size, C.VEG_NOTHING)
        vegetation.putpixel((12, 20), C.EDGE_LINE_E)
        return vegetation, ground

    def test_signs_and_lamps_skip_asphalt_destination(self):
        for mod_tiles, prop in ((True, "speed"), (False, "lamp")):
            with self.subTest(prop=prop):
                vegetation, ground = self.make_road(C.DARK_ASPHALT)
                with mock.patch.object(furniture, "_mod_tiles_ready", return_value=mod_tiles):
                    renderer._paint_street_furniture(vegetation, ground)
                blocked_color = (C.SPEED_SIGNS[(25, "S")] if prop == "speed"
                                 else C.LAMP_W)
                self.assertNotEqual(vegetation.getpixel((14, 20)), blocked_color)

    def test_lamp_can_use_a_grass_verge(self):
        vegetation, ground = self.make_road(C.DARK_GRASS)
        with mock.patch.object(furniture, "_mod_tiles_ready", return_value=False):
            counts = renderer._paint_street_furniture(vegetation, ground)
        self.assertGreater(counts.get("lamp", 0), 0)


class RoadsideProps(unittest.TestCase):
    """Benches are gone, and hydrants, bins and mailboxes only stand beside a
    sidewalk where there is a building to serve."""

    def long_road(self, length=180):
        ground = Image.new("RGB", (length, 24), C.DARK_GRASS)
        pixels = ground.load()
        for y in range(24):
            for x in range(4, 12):
                pixels[x, y] = C.MEDIUM_ASPHALT
            pixels[12, y] = C.PALE_CONCRETE
            pixels[13, y] = C.DARK_GRASS
        vegetation = Image.new("RGB", ground.size, C.VEG_NOTHING)
        for y in range(24):
            vegetation.putpixel((11, y), C.EDGE_LINE_E)
        return vegetation, ground

    def buildings_near(self, size, box):
        mask = Image.new("L", size, 0)
        mask.paste(255, box)
        return mask

    def test_no_benches_on_the_roadside(self):
        vegetation, ground = self.long_road()
        with mock.patch.object(furniture, "_mod_tiles_ready", return_value=False):
            renderer._paint_street_furniture(
                vegetation, ground, None,
                self.buildings_near(ground.size, (10, 8, 60, 16)))
        colours = {vegetation.getpixel((x, y)) for x in range(ground.width)
                   for y in range(ground.height)}
        for tile in (C.TABLE_X0, C.TABLE_X1, C.TABLE_Y0, C.TABLE_Y1):
            self.assertNotIn(tile, colours, "a bench is still being laid")

    def test_props_only_stand_where_a_building_is(self):
        vegetation, ground = self.long_road()
        mask = self.buildings_near(ground.size, (10, 8, 60, 16))
        with mock.patch.object(furniture, "_mod_tiles_ready", return_value=False):
            counts = renderer._paint_street_furniture(vegetation, ground, None, mask)
        props = [C.HYDRANT, C.BIN, C.MAILBOX]
        xs = [x for x in range(ground.width) for y in range(ground.height)
              if vegetation.getpixel((x, y)) in props]
        self.assertTrue(counts.get("hydrant", 0) or counts.get("bin", 0) or
                        counts.get("mailbox", 0), "nothing was placed at all")
        self.assertTrue(xs)
        self.assertLessEqual(max(xs) - min(xs), 60 + 2 * furniture.NEAR_BUILDING_TILES,
                             f"props out on open road at {sorted(set(xs))}")

    def test_props_stand_beside_the_sidewalk_and_not_on_it(self):
        vegetation, ground = self.long_road()
        mask = self.buildings_near(ground.size, (10, 0, 60, 24))
        with mock.patch.object(furniture, "_mod_tiles_ready", return_value=False):
            renderer._paint_street_furniture(vegetation, ground, None, mask)
        props = [C.HYDRANT, C.BIN, C.MAILBOX]
        for x in range(ground.width):
            for y in range(ground.height):
                if vegetation.getpixel((x, y)) not in props:
                    continue
                with self.subTest(at=(x, y)):
                    self.assertNotEqual(ground.getpixel((x, y)), C.PALE_CONCRETE,
                                        "a prop is standing on the sidewalk")
                    neighbours = [ground.getpixel((x + dx, y + dy))
                                  for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                                  if 0 <= x + dx < ground.width and 0 <= y + dy < ground.height]
                    self.assertIn(C.PALE_CONCRETE, neighbours,
                                  "a prop is not beside a sidewalk")


if __name__ == "__main__":
    unittest.main()
