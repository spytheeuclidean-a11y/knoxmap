"""Clearings and drives for buildings in woods; no field or lake under a house."""
import math
import unittest
from collections import deque

import numpy as np
from PIL import Image

from generator import pz_colors as C
from generator.rendering import homesteads as H

W = HGT = 300
HOUSE = [(140, 140), (152, 140), (152, 150), (140, 150)]      # 12 x 10 m
ROAD = [(0, 260), (299, 260)]                                 # 110 m south


def woods(width=W, height=HGT):
    land = Image.new("RGB", (width, height), C.DARK_GRASS)
    veg = Image.new("RGB", (width, height), C.TREES)
    road = np.array(land)
    road[258:263, :] = C.MEDIUM_ASPHALT
    land = Image.fromarray(road, "RGB")
    return land, veg


def is_(arr, *colours):
    out = np.zeros(arr.shape[:2], dtype=bool)
    for c in colours:
        out |= np.all(arr == c, axis=2)
    return out


def distance_to_house(y, x):
    cx = min(max(x, 140), 152)
    cy = min(max(y, 140), 150)
    return math.hypot(x - cx, y - cy)


class ClearingTest(unittest.TestCase):
    def setUp(self):
        self.land, self.veg = woods()
        self.done, self.counts = H.clear_homesteads(self.veg, self.land, [HOUSE], [ROAD], 1.0)
        self.v = np.asarray(self.veg)
        self.g = np.asarray(self.land)

    def test_a_clearing_clear_m_out(self):
        self.assertEqual(self.counts["clearings"], 1)
        bare = ~is_(self.v, *H.WOODS)
        lo = H.CLEAR_M[0] * (1 - H.WOBBLE) - 1
        hi = H.CLEAR_M[1] * (1 + H.WOBBLE) + H.EDGE_M + 1
        for y in range(100, 200):
            for x in range(100, 200):
                d = distance_to_house(y, x)
                if d < lo:
                    self.assertTrue(bare[y, x], (x, y, d))
                if d > hi and not self.done[y, x]:
                    self.assertFalse(bare[y, x], (x, y, d))

    def test_not_a_ring(self):
        # The edge of the clearing is not the same distance all the way round.
        bare = ~is_(self.v, *H.WOODS)
        reach = []
        for angle in range(0, 360, 15):
            dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            r = 0
            while bare[int(145 + dy * (r + 1)), int(146 + dx * (r + 1))]:
                r += 1
                if r > 80:
                    break
            reach.append(r)
        self.assertGreater(max(reach) - min(reach), 4, reach)

    def test_lawn_in_the_clearing(self):
        # Inside the smallest the clearing ever is, west of the house.
        x = 140 - int(H.CLEAR_M[0] * (1 - H.WOBBLE)) + 1
        self.assertTrue(np.all(self.g[145, x] == C.MEDIUM_GRASS))

    def test_drive_reaches_the_road(self):
        self.assertEqual(self.counts["drives"], 1)
        tarmac = is_(self.g, C.DARK_ASPHALT)
        road = is_(self.g, C.MEDIUM_ASPHALT)
        self.assertTrue(tarmac.any())
        # From next to the house, along the drive, to the road.
        start = next((x, y) for y in range(138, 154) for x in range(138, 156)
                     if tarmac[y, x])
        seen, queue, reached = {start}, deque([start]), False
        while queue:
            x, y = queue.popleft()
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not (0 <= nx < W and 0 <= ny < HGT) or (nx, ny) in seen:
                    continue
                if road[ny, nx]:
                    reached = True
                    queue.clear()
                    break
                if tarmac[ny, nx]:
                    seen.add((nx, ny))
                    queue.append((nx, ny))
        self.assertTrue(reached)
        self.assertFalse(is_(self.v, *H.WOODS)[tarmac].any())

    def test_deterministic(self):
        land, veg = woods()
        H.clear_homesteads(veg, land, [HOUSE], [ROAD], 1.0)
        self.assertEqual(veg.tobytes(), self.veg.tobytes())
        self.assertEqual(land.tobytes(), self.land.tobytes())


class WhoGetsOneTest(unittest.TestCase):
    def test_house_in_the_open_untouched(self):
        land, _ = woods()
        veg = Image.new("RGB", (W, HGT), C.VEG_NOTHING)
        veg.putpixel((120, 120), C.TREES)   # one tree is not a wood
        before = land.tobytes()
        _, counts = H.clear_homesteads(veg, land, [HOUSE], [ROAD], 1.0)
        self.assertEqual(counts, {"clearings": 0, "drives": 0})
        self.assertEqual(land.tobytes(), before)
        self.assertEqual(veg.getpixel((120, 120)), C.TREES)

    def test_shed_gets_a_clearing_but_no_drive(self):
        land, veg = woods()
        shed = [(140, 140), (145, 140), (145, 144), (140, 144)]
        _, counts = H.clear_homesteads(veg, land, [shed], [ROAD], 1.0)
        self.assertEqual(counts, {"clearings": 1, "drives": 0})

    def test_no_drive_across_water(self):
        land, veg = woods()
        g = np.array(land)
        g[200:215, :] = C.WATER
        land = Image.fromarray(g, "RGB")
        _, counts = H.clear_homesteads(veg, land, [HOUSE], [ROAD], 1.0)
        self.assertEqual(counts["drives"], 0)
        self.assertFalse(is_(np.asarray(land), C.DARK_ASPHALT).any())

    def test_no_drive_through_another_building(self):
        land, veg = woods()
        barn = [(100, 200), (200, 200), (200, 230), (100, 230)]
        _, counts = H.clear_homesteads(veg, land, [HOUSE, barn], [ROAD], 1.0)
        g = np.asarray(land)
        self.assertFalse(is_(g[201:230, 101:200], C.DARK_ASPHALT).any())

    def test_road_running_off_the_map(self):
        land, veg = woods()
        # Nearest to the house past the map's edge; only its on-map part counts.
        road = [(-400, 145), (-50, 145), (-50, 262), (299, 262)]
        _, counts = H.clear_homesteads(veg, land, [HOUSE], [road], 1.0)
        self.assertEqual(counts["drives"], 1)

    def test_house_and_garage_share_one_drive(self):
        land, veg = woods()
        garage = [(156, 140), (163, 140), (163, 147), (156, 147)]   # 49 m2, 4 m off
        _, counts = H.clear_homesteads(veg, land, [garage, HOUSE], [ROAD], 1.0)
        self.assertEqual(counts["drives"], 1)
        # And it is the house's: it starts at the house, not the garage.
        g = np.asarray(land)
        self.assertTrue(is_(g[150:154, 139:154], C.DARK_ASPHALT).any())

    def test_houses_far_apart_get_one_each(self):
        land, veg = woods()
        other = [(40, 140), (52, 140), (52, 150), (40, 150)]
        _, counts = H.clear_homesteads(veg, land, [HOUSE, other], [ROAD], 1.0)
        self.assertEqual(counts["drives"], 2)

    def test_buildings_at_and_past_the_edge(self):
        land, veg = woods()
        edge_houses = [[(x, y) for x, y in ((290, 60), (305, 60), (305, 72), (290, 72))],
                       [(x, y) for x, y in ((310, 60), (322, 60), (322, 72), (310, 72))],
                       [(x, y) for x, y in ((-20, 60), (-8, 60), (-8, 72), (-20, 72))],
                       # Over ten tiles past the edge, and smaller than HOUSE so
                       # it comes after a drive is laid: its window's far end
                       # was a negative index, read from the other end.
                       [(x, y) for x, y in ((-40, 60), (-32, 60), (-32, 66), (-40, 66))],
                       [(x, y) for x, y in ((140, -18), (148, -18), (148, -12), (140, -12))],
                       [(x, y) for x, y in ((100, -15), (112, -15), (112, -5), (100, -5))]]
        _, counts = H.clear_homesteads(veg, land, [HOUSE] + edge_houses, [ROAD], 1.0)
        self.assertGreaterEqual(counts["drives"], 2)

    def test_road_close_by_needs_no_drive(self):
        land, veg = woods()
        _, counts = H.clear_homesteads(veg, land, [HOUSE], [[(0, 152), (299, 152)]], 1.0)
        self.assertEqual(counts["drives"], 0)


class YardTest(unittest.TestCase):
    def test_no_field_or_lake_under_a_building(self):
        land = Image.new("RGB", (100, 100), C.LIGHT_GRASS)
        g = np.array(land)
        g[:, 50:] = C.WATER
        land = Image.fromarray(g, "RGB")
        grid = np.full((100, 100), 40, dtype="uint8")
        grid[:, 50:] = 80
        owned = np.ones((100, 100), dtype=bool)
        house = [(45, 40), (58, 40), (58, 50), (45, 50)]
        yards = H.keep_yards_clear(land, grid, owned, [house], 1.0)
        g = np.asarray(land)
        self.assertTrue(np.all(g[45, 52] == C.MEDIUM_GRASS))     # was lake
        self.assertTrue(np.all(g[45, 47] == C.MEDIUM_GRASS))     # was cropland
        self.assertTrue(np.all(g[45, 90] == C.WATER))            # far off: still lake
        self.assertFalse(owned[45, 52])
        self.assertTrue(owned[5, 5])
        self.assertTrue(yards[45, 52] and yards[35, 50] and not yards[5, 5])

    def test_fields_stay_off_yards(self):
        from generator.rendering.fields import paint_fields

        class P:
            meters_per_tile = 1.0

        land = Image.new("RGB", (200, 200), C.LIGHT_GRASS)
        veg = Image.new("RGB", (200, 200), C.VEG_NOTHING)
        ring = [(0, 0), (199, 0), (199, 199), (0, 199)]
        blocked = np.zeros((200, 200), dtype=bool)
        blocked[80:120, 80:120] = True
        cropland = np.ones((200, 200), dtype=bool)
        paint_fields(land, veg, P(), [ring], cropland, blocked=blocked)
        g = np.asarray(land)
        self.assertTrue(np.all(g[80:120, 80:120] == C.LIGHT_GRASS))
        furrow = is_(g, C.DIRT_ROWS_H, C.DIRT_ROWS_V)
        self.assertGreater(furrow.mean(), 0.3)


class ClearingSize(unittest.TestCase):
    def bare(self, clear_max_m):
        land, veg = woods()
        done, counts = H.clear_homesteads(veg, land, [HOUSE], [ROAD], 1.0,
                                          clear_max_m=clear_max_m)
        return int((~is_(np.asarray(veg), *H.WOODS)).sum()), counts

    def test_the_default_is_today(self):
        land, veg = woods()
        H.clear_homesteads(veg, land, [HOUSE], [ROAD], 1.0)
        land2, veg2 = woods()
        H.clear_homesteads(veg2, land2, [HOUSE], [ROAD], 1.0, clear_max_m=20)
        self.assertEqual(np.asarray(veg).tobytes(), np.asarray(veg2).tobytes())

    def test_zero_is_no_clearing(self):
        _, counts = self.bare(0)
        self.assertEqual(counts["clearings"], 0)

    def test_bigger_is_bigger(self):
        self.assertGreater(self.bare(40)[0], self.bare(20)[0])


if __name__ == "__main__":
    unittest.main()
