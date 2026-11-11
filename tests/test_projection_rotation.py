"""A turned map still holds everything that was drawn on it.

The bitmap is sized from the selection before it is turned, and to_px then
rotates every feature about the map's centre. A turned rectangle is wider than
the rectangle it came from, so its own corners used to land outside the bitmap -
and a feature outside the bitmap is not drawn small or moved, it is silently
dropped. A town turned onto its street grid, a few degrees, lost the corners of
its own selection; a map turned 45 degrees lost a fifth of every side.

The sizes are checked against the geometry worked out from scratch here, so a
map that grows by the wrong amount fails as loudly as one that does not grow.
"""
import math
import unittest

import pyproj

from generator import pz_colors as C
from generator.rendering.projection import Projector

# A square, a wide strip and a tall strip: the turn costs the strips far more
# than it costs the square, which is what makes the old sizing show up.
BOXES = {
    "square": (40.1440, -84.2420, 40.1700, -84.2070),
    "wide": (40.1440, -84.3000, 40.1550, -84.1000),
    "tall": (40.1000, -84.2500, 40.2500, -84.2300),
}
ANGLES = (-45.0, -30.0, -11.5, -3.0, 0.5, 3.0, 10.0, 30.0, 45.0)


def extent(south, west, north, east):
    """The selection's width and height in metres, worked out from scratch."""
    lon_c, lat_c = (west + east) / 2, (south + north) / 2
    epsg = (32600 if lat_c >= 0 else 32700) + int((lon_c + 180) / 6) + 1
    t = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    xs, ys = zip(*(t.transform(lo, la) for lo, la in
                   ((west, south), (east, south), (east, north), (west, north))))
    return max(xs) - min(xs), max(ys) - min(ys)


def side(metres, meters_per_tile):
    """Tiles for that many metres, padded up to whole cells as the map is."""
    return max(C.CELL_SIZE,
               math.ceil(metres / meters_per_tile / C.CELL_SIZE) * C.CELL_SIZE)


class TurnedSelectionTest(unittest.TestCase):
    def test_every_corner_of_the_selection_is_on_the_map(self):
        for name, box in BOXES.items():
            for mpt in (1.0, 2.0):
                for angle in ANGLES:
                    proj = Projector.build(*box, mpt, angle)
                    corners = ((box[0], box[1]), (box[0], box[3]),
                               (box[2], box[3]), (box[2], box[1]))
                    for corner in corners:
                        with self.subTest(box=name, mpt=mpt, angle=angle,
                                          corner=corner):
                            x, y = proj.to_px(*corner)
                            self.assertTrue(0 <= x <= proj.width,
                                            f"x={x:.1f} off a {proj.width} map")
                            self.assertTrue(0 <= y <= proj.height,
                                            f"y={y:.1f} off a {proj.height} map")

    def test_the_map_is_the_size_the_turn_needs_and_no_more(self):
        for name, box in BOXES.items():
            raw_w, raw_h = extent(*box)
            for mpt in (1.0, 2.0):
                for angle in ANGLES:
                    a = math.radians(angle)
                    cos_a, sin_a = abs(math.cos(a)), abs(math.sin(a))
                    proj = Projector.build(*box, mpt, angle)
                    with self.subTest(box=name, mpt=mpt, angle=angle):
                        self.assertEqual(
                            proj.width, side(raw_w * cos_a + raw_h * sin_a, mpt))
                        self.assertEqual(
                            proj.height, side(raw_w * sin_a + raw_h * cos_a, mpt))

    def test_an_upright_map_is_the_size_it_always_was(self):
        for name, box in BOXES.items():
            raw_w, raw_h = extent(*box)
            proj = Projector.build(*box, 1.0, 0.0)
            with self.subTest(box=name):
                self.assertEqual((proj.width, proj.height),
                                 (side(raw_w, 1.0), side(raw_h, 1.0)))

    def test_the_turn_does_not_shift_the_map(self):
        # The turn is about the map's centre, so it must not change how far a
        # feature sits from that centre - only which way it lies. Turning about
        # the corner of the bitmap, or about the bbox in degrees rather than the
        # projected one, moves the town instead of turning it.
        for name, box in BOXES.items():
            lat, lon = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            base = Projector.build(*box, 1.0, 0.0)
            x0, y0 = base.to_px(lat, lon)
            reach = math.hypot(x0 - base.width / 2, y0 - base.height / 2)
            for angle in ANGLES:
                proj = Projector.build(*box, 1.0, angle)
                x, y = proj.to_px(lat, lon)
                with self.subTest(box=name, angle=angle):
                    self.assertAlmostEqual(
                        math.hypot(x - proj.width / 2, y - proj.height / 2),
                        reach, places=6)

    def test_the_turn_does_not_move_a_tile_in_the_world(self):
        for angle in ANGLES:
            proj = Projector.build(*BOXES["square"], 1.0, angle)
            for px, py in ((0, 0), (proj.width, 0), (0, proj.height),
                           (proj.width / 2, proj.height / 2), (123.0, 456.0)):
                lat, lon = proj.to_latlon(px, py)
                bx, by = proj.to_px(lat, lon)
                with self.subTest(angle=angle, at=(px, py)):
                    self.assertAlmostEqual(bx, px, places=6)
                    self.assertAlmostEqual(by, py, places=6)


if __name__ == "__main__":
    unittest.main()
