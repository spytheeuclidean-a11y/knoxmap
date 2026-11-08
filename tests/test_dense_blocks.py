"""Which city blocks get paved wall to wall (generator/rendering/roads.py).

A paved block is a slab of pale concrete, so the two things that keep it from
swallowing open country are how built-up a block has to be and how big a block
may be. Both are exercised here on synthetic streets, through the real
function rather than a copy of its arithmetic.
"""
import unittest
from types import SimpleNamespace

from PIL import Image

from generator.osm import OSMFeature
from generator.pz_colors import MEDIUM_GRASS, PALE_CONCRETE
from generator.rendering import roads

W = H = 900


def proj():
    # Geometry is written as (y, x) tile pairs, so projects straight through.
    return SimpleNamespace(width=W, height=H, meters_per_tile=1.0,
                           to_px=lambda la, lo: (lo, la))


def street(ring):
    return OSMFeature(osm_id=1, kind="way", tags={"highway": "residential"},
                      geometry=[(y, x) for x, y in ring])


def building(x, y, w, h):
    ring = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    return OSMFeature(osm_id=2, kind="way", tags={"building": "yes"},
                      geometry=[(yy, xx) for xx, yy in ring])


def square(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def paved_fraction(im, box):
    a = im.crop(box).convert("RGB")
    px = a.load()
    hit = sum(1 for x in range(a.width) for y in range(a.height)
              if px[x, y] == PALE_CONCRETE)
    return hit / (a.width * a.height)


def run(blocks, houses):
    landscape = Image.new("RGB", (W, H), MEDIUM_GRASS)
    buckets = {"road_minor": [street(ring) for ring in blocks]}
    roads._pave_dense_ground(landscape, houses, buckets, proj())
    return landscape


class DenseBlocks(unittest.TestCase):
    def test_a_dense_block_is_paved(self):
        # Two streets make one block, and two thirds of it is under buildings.
        im = run([square(100, 100, 300, 100), square(300, 100, 300, 300),
                  square(300, 300, 100, 300), square(100, 300, 100, 100)],
                 [building(110, 110, 160, 160)])
        self.assertGreater(paved_fraction(im, (110, 110, 290, 290)), 0.5)

    def test_an_ordinary_street_is_left_alone(self):
        # A third under buildings: a suburb, a village high street. It cleared
        # the old 0.28 line and got paved; the downtown line leaves it grass.
        im = run([square(100, 100, 300, 100), square(300, 100, 300, 300),
                  square(300, 300, 100, 300), square(100, 300, 100, 100)],
                 [building(130, 130, 115, 115)])
        self.assertEqual(paved_fraction(im, (110, 110, 290, 290)), 0.0)

    def test_a_block_the_size_of_a_field_is_never_paved(self):
        # 500 x 500: a farm and a works clear the coverage line, and paving
        # the whole thing is the concrete field the map grew instead of trees.
        im = run([square(50, 50, 600, 50), square(600, 50, 600, 600),
                  square(600, 600, 50, 600), square(50, 600, 50, 50)],
                 [building(100, 100, 300, 250), building(150, 400, 250, 150)])
        self.assertEqual(paved_fraction(im, (60, 60, 590, 590)), 0.0)


if __name__ == "__main__":
    unittest.main()
