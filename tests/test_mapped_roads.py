import math
import unittest
from types import SimpleNamespace

import numpy as np
from PIL import Image

from generator import mapped_roads, osm, pz_colors as C, renderer
from generator.rendering.geometry import _draw_roads
from generator.rendering.roads import _smooth_road_edges
from knoxbuild.settings import Settings


def _is_colour(ground, colours):
    mask = np.zeros(ground.shape[:2], dtype=bool)
    for colour in colours:
        mask |= np.all(ground == colour, axis=2)
    return mask


class MappedRoadsRevamp(unittest.TestCase):
    def setUp(self):
        self.proj = SimpleNamespace(
            width=128,
            height=128,
            to_px=lambda lat, lon: (lon, lat),
            to_latlon=lambda x, y: (y, x),
        )

    def test_default_road_layout_is_as_mapped(self):
        self.assertEqual(Settings().straight_roads, 0)
        self.assertEqual(Settings.from_dict({}).straight_roads, 0)

    def test_noisy_straight_road_is_cleaned_while_junctions_stay_pinned(self):
        # Straight east-west road with sub-tile digitization jitter, plus a side street at (30, 50).
        main = osm.OSMFeature(
            1, "way", {"highway": "residential"},
            [(50.0, 10.0), (50.35, 20.0), (50.0, 30.0), (49.7, 40.0), (50.0, 60.0)],
        )
        side = osm.OSMFeature(
            2, "way", {"highway": "residential"},
            [(50.0, 30.0), (70.0, 30.0)],
        )
        cleaned = mapped_roads.clean_mapped_roads(
            [main, side], self.proj, osm.classify, renderer._is_polygon
        )
        self.assertEqual(cleaned, 1)
        # Junction at (50.0, 30.0) and endpoints stay exact.
        self.assertEqual(main.geometry[0], (50.0, 10.0))
        self.assertIn((50.0, 30.0), main.geometry)
        self.assertEqual(main.geometry[-1], (50.0, 60.0))
        # Sub-tile jitter points are collapsed.
        self.assertEqual(len(main.geometry), 3)

    def test_small_roundabout_stays_round(self):
        ring = [
            (50.0 + 6.0 * math.sin(2 * math.pi * i / 12),
             50.0 + 6.0 * math.cos(2 * math.pi * i / 12))
            for i in range(12)
        ]
        ring.append(ring[0])
        rb = osm.OSMFeature(3, "way", {"highway": "residential", "junction": "roundabout"}, ring)
        mapped_roads.clean_mapped_roads([rb], self.proj, osm.classify, renderer._is_polygon)
        self.assertGreaterEqual(len(rb.geometry), 9)

    def test_angled_road_has_no_one_tile_asphalt_spurs(self):
        im = Image.new("RGB", (80, 80), C.MEDIUM_GRASS)
        pts = [(10.0, 20.0), (70.0, 42.0)]
        _draw_roads(im, [(10, [pts])], C.PALE_CONCRETE)
        _draw_roads(im, [(6, [pts])], C.MEDIUM_ASPHALT)
        asphalt = (C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT)
        _smooth_road_edges(im, asphalt, _is_colour)

        arr = np.asarray(im)
        road = _is_colour(arr, asphalt)
        # No asphalt pixel should have 3+ non-asphalt orthogonal neighbours (1-tile spur).
        spurs = 0
        for y in range(1, 79):
            for x in range(1, 79):
                if road[y, x]:
                    non_road = sum(
                        not road[y + dy, x + dx]
                        for dy, dx in ((0, -1), (0, 1), (-1, 0), (1, 0))
                    )
                    if non_road >= 3:
                        spurs += 1
        self.assertEqual(spurs, 0)

    def test_curved_road_is_smoothed_while_sharp_corner_stays_crisp(self):
        # Gentle bend with 20-tile segments gets rounded into more points,
        # while a sharp 90-degree corner stays unrounded.
        curve = osm.OSMFeature(
            4, "way", {"highway": "residential"},
            [(10.0, 10.0), (10.0, 30.0), (20.0, 50.0)],
        )
        corner = osm.OSMFeature(
            5, "way", {"highway": "residential"},
            [(80.0, 10.0), (80.0, 30.0), (100.0, 30.0)],
        )
        mapped_roads.clean_mapped_roads(
            [curve, corner], self.proj, osm.classify, renderer._is_polygon
        )
        self.assertGreater(len(curve.geometry), 3)
        self.assertEqual(curve.geometry[0], (10.0, 10.0))
        self.assertEqual(curve.geometry[-1], (20.0, 50.0))
        self.assertEqual(corner.geometry, [(80.0, 10.0), (80.0, 30.0), (100.0, 30.0)])

    def test_two_tile_bumps_and_notches_are_smoothed_on_road_and_sidewalk(self):
        im = Image.new("RGB", (24, 24), C.MEDIUM_GRASS)
        px = im.load()
        # Horizontal band: sidewalk y in 6..15, road y in 8..13.
        for y in range(6, 16):
            for x in range(2, 22):
                px[x, y] = C.PALE_CONCRETE
        for y in range(8, 14):
            for x in range(2, 22):
                px[x, y] = C.MEDIUM_ASPHALT
        # Inject a 2-tile-wide asphalt bump at (6..7, 7) and 2-tile notch at (12..13, 8).
        px[6, 7] = C.MEDIUM_ASPHALT
        px[7, 7] = C.MEDIUM_ASPHALT
        px[12, 8] = C.PALE_CONCRETE
        px[13, 8] = C.PALE_CONCRETE
        # Inject a 2-tile-wide sidewalk bump at (6..7, 5) and 2-tile notch at (12..13, 6).
        px[6, 5] = C.PALE_CONCRETE
        px[7, 5] = C.PALE_CONCRETE
        px[12, 6] = C.MEDIUM_GRASS
        px[13, 6] = C.MEDIUM_GRASS

        asphalt = (C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT)
        _smooth_road_edges(im, asphalt, _is_colour)

        self.assertEqual(px[6, 7], C.PALE_CONCRETE)
        self.assertEqual(px[7, 7], C.PALE_CONCRETE)
        self.assertEqual(px[12, 8], C.MEDIUM_ASPHALT)
        self.assertEqual(px[13, 8], C.MEDIUM_ASPHALT)
        self.assertEqual(px[6, 5], C.MEDIUM_GRASS)
        self.assertEqual(px[7, 5], C.MEDIUM_GRASS)
        self.assertEqual(px[12, 6], C.PALE_CONCRETE)
        self.assertEqual(px[13, 6], C.PALE_CONCRETE)


if __name__ == "__main__":
    unittest.main()
