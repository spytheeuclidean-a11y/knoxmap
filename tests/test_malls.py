"""A mall is one enclosed mall, laid out as a mall (knoxbuild.build, layout).

Run from the KnoxMap folder:  python -m unittest discover tests
No network, no files: footprints placed straight into an empty grid, and
buildings laid out directly.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from knoxbuild import layout  # noqa: E402
from knoxbuild.build import mall_by_name, row_units  # noqa: E402
from knoxbuild.footprint import place  # noqa: E402

GRID = np.zeros((600, 600), dtype=bool)


def mall(w=160, h=90, levels=1, seed=0, mask=None):
    return layout.build_building(w, h, levels=levels, kind="mall",
                                 commercial=True, seed=seed, mask=mask)


def _tiles(p, i):
    return sum(row.count(i) for row in p.grid)


def _anchor_rooms(p):
    return [p.grid[(y0 + y1) // 2][(x0 + x1) // 2] for x0, y0, x1, y1 in p.anchors]


def _touches_rect(p, i, rect):
    x0, y0, x1, y1 = rect
    for y, row in enumerate(p.grid):
        for x, v in enumerate(row):
            if v == i and any(x0 <= nx <= x1 and y0 <= ny <= y1
                              for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))):
                return True
    return False


def _door_rooms(p, door):
    """The two grid values a door joins; 0 is outside."""
    x, y, d = door
    def at(cx, cy):
        return p.grid[cy][cx] if 0 <= cx < p.width and 0 <= cy < p.height else 0
    return at(x, y), (at(x - 1, y) if d == "W" else at(x, y - 1))


def _links(p):
    out = {}
    for door in p.doors:
        a, b = _door_rooms(p, door)
        out.setdefault(a, set()).add(b)
        out.setdefault(b, set()).add(a)
    return out


def _service_components(p):
    halls = {i for i, r in enumerate(p.rooms, 1) if r.kind == "hall" and not r.is_core}
    links = _links(p)
    comps, seen = [], set()
    for h in halls:
        if h in seen:
            continue
        comp, stack = {h}, [h]
        while stack:
            for n in links.get(stack.pop(), ()):
                if n in halls and n not in comp:
                    comp.add(n)
                    stack.append(n)
        seen |= comp
        comps.append(comp)
    return comps


def _concourse_id(p):
    return next(i for i, r in enumerate(p.rooms, 1) if r.kind == "concourse")


def footprint(w: int, h: int):
    ring = [(10.0, 10.0), (10.0 + w, 10.0), (10.0 + w, 10.0 + h),
            (10.0, 10.0 + h), (10.0, 10.0)]
    fp, reason = place(ring, GRID.copy(), max_side=1e9)
    assert fp is not None, reason
    return fp


# Three different shops, as uses_of returns them (one per kind), and the
# floor area of a real mall.
SHOPS = [("clothingstore", "storage"), ("toystore", "storage"), ("bookstore", "storage")]
BIG = 20000.0


class MallsKeptWhole(unittest.TestCase):
    def test_tagged_mall_over_6000_m2_is_one_unit(self):
        units = row_units(footprint(150, 100), "mall", "retail", 0, 1.0)
        self.assertEqual(len(units), 1)

    def test_mall_over_max_m2_is_still_cut(self):
        # 260 x 240 = 62,400 m2 at a metre a tile.
        units = row_units(footprint(260, 240), "mall", "retail", 0, 1.0)
        self.assertGreater(len(units), 1)

    def test_mall_past_max_size_is_still_cut(self):
        units = row_units(footprint(150, 100), "mall", "retail", 0, 1.0,
                          max_side=100)
        self.assertGreater(len(units), 1)

    def test_center_with_three_shops_is_a_mall(self):
        self.assertEqual(mall_by_name("shop", {"name": "Piqua Center"}, SHOPS, BIG), "mall")
        self.assertEqual(mall_by_name(None, {"name": "Miami Valley Centre"}, SHOPS, BIG), "mall")
        self.assertEqual(mall_by_name(None, {"name": "Towne Plaza"}, SHOPS, BIG), "mall")

    def test_plaza_with_two_shops_is_not_a_mall(self):
        uses = [("clothesstore", "storage"), ("office", "office"), ("office", "office")]
        self.assertEqual(mall_by_name("civic", {"name": "Main Plaza"}, uses, BIG), "civic")

    def test_center_not_at_end_of_name_is_not_a_mall(self):
        self.assertEqual(mall_by_name("shop", {"name": "Center Street Shops"}, SHOPS, BIG), "shop")

    def test_medical_or_civic_center_is_not_a_mall(self):
        clinic = [("dentist", "medicaloffice"), ("medicaloffice", "medicaloffice"),
                  ("pharmacy", "storage")]
        self.assertEqual(mall_by_name(None, {"name": "Riverside Medical Center"}, clinic, BIG), None)
        civic = [("library", "storage"), ("policeoffice", "office"), ("post", "storage")]
        self.assertEqual(mall_by_name("civic", {"name": "Government Center"}, civic, BIG), "civic")

    def test_office_tower_plaza_is_not_a_mall(self):
        uses = SHOPS + [("office", "office")]
        self.assertEqual(mall_by_name("civic", {"name": "Commerce Plaza"}, uses, BIG), "civic")
        tall = {"name": "Commerce Plaza", "building:levels": "12"}
        self.assertEqual(mall_by_name("shop", tall, SHOPS, BIG), "shop")

    def test_strip_plaza_stays_a_row_of_shops(self):
        # 150 x 25 m: a strip mall, under a real mall's 10,000 m2.
        self.assertEqual(mall_by_name("shop", {"name": "Towne Plaza"}, SHOPS, 3750.0), "shop")


class FloorPlan(unittest.TestCase):
    def assert_mall_plan(self, p, msg):
        conc = [i for i, r in enumerate(p.rooms, 1) if r.kind == "concourse"]
        self.assertEqual(len(conc), 1, msg)
        adj = layout._neighbours(p)
        anchors = set(_anchor_rooms(p))
        self.assertEqual(len(anchors), len(p.anchors), msg)
        for i, r in enumerate(p.rooms, 1):
            if r.kind in layout.MALL_SHOP_KINDS or i in anchors:
                self.assertIn(conc[0], adj[i], (msg, i, r.kind))
            if r.kind in layout.MALL_SHOP_KINDS:
                self.assertTrue(40 <= _tiles(p, i) <= 150, (msg, r.kind, _tiles(p, i)))
        for i in anchors:
            self.assertTrue(800 <= _tiles(p, i) <= 2500, (msg, _tiles(p, i)))

    def test_one_concourse_reaches_every_shop_and_anchor(self):
        for seed in range(6):
            self.assert_mall_plan(mall(seed=seed).storeys[0], seed)

    def test_arms_reach_the_wall_and_storerooms_are_and_cut_the_storerooms(self):
        for w, h in ((160, 90), (240, 130), (245, 245)):
            p = mall(w, h).storeys[0]
            total = sum(map(sum, p.mask)) if p.mask is not None else w * h
            store = sum(_tiles(p, i) for i, r in enumerate(p.rooms, 1)
                        if r.kind == "storage")
            if (w, h) == (160, 90):   # was 35% before the arms ran through
                self.assertLess(store / total, 0.25, store / total)
            c = _concourse_id(p)
            edge = [(x, y) for y in range(p.height) for x in range(p.width)
                    if p.grid[y][x] == c and (x in (0, p.width - 1) or y in (0, p.height - 1))]
            self.assertTrue(edge, (w, h))

    def test_two_anchors_on_a_small_mall(self):
        p = mall().storeys[0]   # 14,400 tiles
        self.assertEqual(len(p.anchors), 2)
        self.assert_mall_plan(p, "small")

    def test_three_or_four_anchors_on_a_big_mall(self):
        p = mall(240, 130).storeys[0]   # 31,200 tiles
        self.assertIn(len(p.anchors), (3, 4))
        self.assert_mall_plan(p, "big")

    def test_inline_units_are_mall_sized(self):
        for seed in range(6):
            p = mall(seed=seed).storeys[0]
            shops = [i for i, r in enumerate(p.rooms, 1) if r.kind in layout.MALL_SHOP_KINDS]
            self.assertGreaterEqual(len(shops), 20, seed)
            for i in shops:
                self.assertTrue(40 <= _tiles(p, i) <= 150, (seed, _tiles(p, i)))

    def test_small_multi_storey_mall_gets_no_lift(self):
        # The old layout's hole runs the length of the spine and only the
        # stair core is taken out of it: a lift there stood in the hole
        # with the railing across its doors.
        for w, h in ((32, 28), (60, 50), (50, 40)):
            for seed in range(4):
                b = layout.build_building(w, h, levels=2, kind="mall",
                                          commercial=True, seed=seed)
                self.assertIsNone(b.storeys[0].court, (w, h))
                self.assertIsNone(b.storeys[0].shaft, (w, h, seed))

    def test_small_mall_keeps_old_layout(self):
        # 32x28 is below MALL_PLAN_MIN_TILES: the old spine-and-split layout.
        p = layout.build_building(32, 28, kind="mall", commercial=True, seed=0).storeys[0]
        self.assertIsNone(p.court)
        self.assertIn("concourse", {r.kind for r in p.rooms})

    def test_l_shaped_mall_has_no_room_outside_mask(self):
        w, h = 160, 90
        mask = [[not (x >= 100 and y < 40) for x in range(w)] for y in range(h)]
        for seed in range(3):
            p = mall(w, h, seed=seed, mask=mask).storeys[0]
            for y in range(h):
                for x in range(w):
                    if not mask[y][x]:
                        self.assertEqual(p.grid[y][x], 0, (seed, x, y))
            for i, r in enumerate(p.rooms, 1):
                if r.kind in layout.MALL_SHOP_KINDS:
                    self.assertTrue(40 <= _tiles(p, i) <= 150, (seed, _tiles(p, i)))

    def test_food_court_off_the_court_on_ground_only(self):
        for seed in range(6):
            b = mall(levels=2, seed=seed)
            g, up = b.storeys
            seats = [i for i, r in enumerate(g.rooms, 1) if r.kind == "foodcourt"]
            self.assertEqual(len(seats), 1, seed)
            self.assertTrue(_touches_rect(g, seats[0], g.court), seed)
            counters = [i for i, r in enumerate(g.rooms, 1) if r.kind in layout.FOOD_COUNTERS]
            self.assertTrue(3 <= len(counters) <= 5, (seed, len(counters)))
            adj = layout._neighbours(g)
            for c in counters:
                self.assertTrue(20 <= _tiles(g, c) <= 40, (seed, _tiles(g, c)))
                self.assertIn(seats[0], adj[c], seed)
            self.assertFalse({"foodcourt", *layout.FOOD_COUNTERS} & {r.kind for r in up.rooms}, seed)

    def test_tall_mall_same_rules(self):
        p = mall(90, 160).storeys[0]
        self.assertEqual(len(p.anchors), 2)
        self.assert_mall_plan(p, "tall")


def _in_rect(cell, rect, grow=0):
    x, y = cell
    x0, y0, x1, y1 = rect
    return x0 - grow <= x <= x1 + grow and y0 - grow <= y <= y1 + grow


def _cells(rect):
    x0, y0, x1, y1 = rect
    return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


class Atrium(unittest.TestCase):
    def test_escalators_and_lift_in_the_centre_court(self):
        for seed in range(4):
            b = mall(levels=2, seed=seed)
            g = b.storeys[0]
            self.assertTrue(b.escalators, seed)
            for cell in b.escalators:
                self.assertTrue(_in_rect(cell, g.court, grow=1), (seed, cell, g.court))
            self.assertIsNotNone(g.shaft, seed)
            self.assertTrue(any(_in_rect(c, g.court, grow=1) for c in _cells(g.shaft)), seed)

    def test_core_and_lift_keep_floor_upstairs(self):
        for seed in range(4):
            up = mall(levels=2, seed=seed).storeys[1]
            for rect in (up.core, up.shaft):
                for cell in _cells(rect):
                    self.assertNotIn(cell, up.void, seed)
                    self.assertTrue(up.grid[cell[1]][cell[0]], (seed, cell))

    def test_upper_hole_is_the_court_only(self):
        up = mall(levels=2).storeys[1]
        self.assertTrue(up.void)
        self.assertTrue(all(_in_rect(c, up.court) for c in up.void))
        self.assertTrue(all(up.grid[y][x] == 0 for x, y in up.void))


class Kiosks(unittest.TestCase):
    def kiosks(self, p):
        conc = _concourse_id(p)
        return [(x, y) for role, x, y, d in p.furniture
                if role == "shop_counter" and p.grid[y][x] == conc]

    def test_kiosks_on_a_wide_spine_clear_of_court_and_doors(self):
        p = mall(200, 110).storeys[0]          # band = round(110 * 0.16) = 18
        ks = self.kiosks(p)
        self.assertTrue(ks)
        for x, y in ks:
            self.assertFalse(_in_rect((x, y), p.court), (x, y))
            for dx, dy, _d in p.doors:
                self.assertGreater(abs(dx - x) + abs(dy - y), layout.MALL_KIOSK_DOOR_CLEAR)

    def test_no_kiosks_on_a_narrow_spine(self):
        p = mall(160, 70).storeys[0]           # band = 11
        self.assertEqual(self.kiosks(p), [])

    def test_no_kiosks_upstairs(self):
        up = mall(200, 110, levels=2).storeys[1]
        self.assertEqual(self.kiosks(up), [])


class Doors(unittest.TestCase):
    def test_service_corridor_reaches_restrooms_office_and_exit(self):
        for size in ((160, 90), (240, 130), (90, 160)):
            p = mall(*size).storeys[0]
            comps = _service_components(p)
            self.assertTrue(comps, size)
            links = _links(p)
            reached = set()
            for comp in comps:
                self.assertTrue(any(0 in links.get(h, ()) for h in comp), (size, comp))
                for h in comp:
                    reached |= links.get(h, set())
            kinds = [p.rooms[i - 1].kind for i in reached if i]
            self.assertGreaterEqual(kinds.count("bathroom"), 2, size)
            self.assertIn("office", kinds, size)

    def test_every_inline_shop_with_a_service_hall_behind_has_a_back_door(self):
        for seed in range(4):
            p = mall(seed=seed).storeys[0]
            adj, links = layout._neighbours(p), _links(p)
            halls = {i for i, r in enumerate(p.rooms, 1) if r.kind == "hall" and not r.is_core}
            for i, r in enumerate(p.rooms, 1):
                if r.kind in layout.MALL_SHOP_KINDS and halls & set(adj[i]):
                    self.assertTrue(halls & links.get(i, set()), (seed, i, r.kind))

    def test_food_counters_open_onto_the_seating(self):
        for seed in range(4):
            p = mall(seed=seed).storeys[0]
            links = _links(p)
            seat = next(i for i, r in enumerate(p.rooms, 1) if r.kind == "foodcourt")
            for i, r in enumerate(p.rooms, 1):
                if r.kind in layout.FOOD_COUNTERS:
                    self.assertIn(seat, links.get(i, set()), (seed, r.kind))

    def test_each_anchor_has_an_outside_door(self):
        for size in ((160, 90), (240, 130)):
            p = mall(*size).storeys[0]
            links = _links(p)
            for a in _anchor_rooms(p):
                self.assertIn(0, links.get(a, set()), (size, a))


# The biggest mall kept whole, two storeys, laid out in this many seconds.
# It takes about 40 s on a quiet machine and 70 s on a loaded one - a full suite
# running beside it was enough to fail the 60 s budget twice. This is a guard
# against a layout going quadratic, not a benchmark, so it is set where a busy
# CI box still passes and a real slowdown still trips it.
MALL_LAYOUT_BUDGET_S = 120.0


class Budget(unittest.TestCase):
    def test_biggest_allowed_mall_lays_out_in_budget(self):
        t = time.perf_counter()
        mall(245, 245, levels=2)               # 60,025 tiles: MALL_MAX_M2 at 1 m a tile
        self.assertLess(time.perf_counter() - t, MALL_LAYOUT_BUDGET_S)


if __name__ == "__main__":
    unittest.main()
