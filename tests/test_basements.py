"""Basements: who gets one, how deep, and where it may go (knoxbuild/basements.py)."""
import random
import unittest
from types import SimpleNamespace

import numpy as np
from shapely.geometry import box as shape_box

from knoxbuild.basements import (BasementSpec, Underground, _inside, levels_for,
                                 plan_basement, render_basement, reserve, tier)
from knoxbuild.buildtiles import parse_tbx
from knoxbuild.layout import build_building
from knoxbuild.buildheader import placed_rooms
from knoxbuild.settings import Settings


def row(kind, x0, y0, w, h):
    return {"kind": kind, "x0": x0, "y0": y0, "w": w, "h": h,
            "mask": np.ones((h, w), dtype=bool)}


class Sites:
    """A stand-in for areas.AreaIndex: these boxes, the first holding the point."""

    def __init__(self, *boxes):
        self.shapes = [shape_box(*b) for b in boxes]

    def shape_around(self, x, y):
        from shapely.geometry import Point
        return next((s for s in self.shapes if s.contains(Point(x, y))), None)


def as_building(mask, name):
    grid = [[1 if v else 0 for v in r] for r in mask.tolist()]
    return SimpleNamespace(floors=[SimpleNamespace(rooms=grid, objects=[])],
                           rooms=[{"Name": name}])


class BasementSettings(unittest.TestCase):
    def test_defaults(self):
        s = Settings()
        self.assertEqual((s.basement_share, s.max_basement_depth), (0.4, 8))

    def test_depth_stops_at_the_game_s_bottom_level(self):
        self.assertEqual(Settings.from_dict({"max_basement_depth": 40}).max_basement_depth, 32)
        self.assertEqual(Settings.from_dict({"max_basement_depth": 0}).max_basement_depth, 1)

    def test_share_is_a_fraction(self):
        self.assertEqual(Settings.from_dict({"basement_share": 3}).basement_share, 1.0)


class Tiers(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(tier("house", 80, 0), "house")
        self.assertIsNone(tier("church", 599, 0))
        self.assertEqual(tier("church", 600, 0), "large")
        self.assertEqual(tier("school", 300, 0), "large")
        self.assertEqual(tier("industrial", 900, 49_999), "large")
        self.assertEqual(tier("industrial", 900, 50_000), "installation")
        self.assertEqual(tier("military", 50, 0), "installation")
        self.assertIsNone(tier("shed", 40, 0))
        self.assertIsNone(tier("apartment", 400, 0))

    def test_levels(self):
        self.assertEqual(levels_for("house", 90, 0, 8), 1)
        self.assertEqual(levels_for("large", 2_999, 0, 8), 1)
        self.assertEqual(levels_for("large", 3_000, 0, 8), 2)
        self.assertEqual(levels_for("installation", 500, 0, 8), 2)
        self.assertEqual(levels_for("installation", 500, 130_000, 8), 7)
        self.assertEqual(levels_for("installation", 500, 10 ** 7, 8), 8)
        self.assertEqual(levels_for("installation", 500, 10 ** 7, 40), 32)


class Reserving(unittest.TestCase):
    def test_underground_squares_are_taken_once(self):
        u = Underground()
        m = np.ones((4, 4), dtype=bool)
        self.assertTrue(u.fits(30, 30, m, 2))
        u.take(30, 30, m, 2)
        self.assertFalse(u.fits(33, 33, m, 1))
        self.assertTrue(u.fits(34, 30, m, 2))

    def test_a_house_basement_stays_a_tile_inside_its_walls(self):
        spec = reserve([row("house", 10, 10, 6, 5)], Settings(basement_share=1.0),
                       None, None, random.Random(1), (100, 100))[0]
        self.assertEqual((spec.tier, spec.kind, spec.levels, spec.dx, spec.dy), ("house", "house", 1, 0, 0))
        self.assertEqual(int(spec.mask.sum()), 4 * 3)
        self.assertFalse(spec.mask[0].any() or spec.mask[:, 0].any())

    def test_basements_never_join_buildings_that_stand_apart(self):
        a, b = row("house", 10, 10, 6, 6), row("house", 17, 10, 6, 6)   # a tile apart
        specs = reserve([a, b], Settings(basement_share=1.0), None, None, random.Random(1),
                        (100, 100))
        lots = [(as_building(a["mask"], "hall"), 10, 10, 0), (as_building(b["mask"], "hall"), 17, 10, 0),
                (as_building(specs[0].mask, "storage"), 10 + specs[0].dx, 10 + specs[0].dy, -1),
                (as_building(specs[1].mask, "storage"), 17 + specs[1].dx, 10 + specs[1].dy, -1)]
        self.assertEqual(len(placed_rooms(lots[:2])), 2)
        self.assertEqual(len(placed_rooms(lots, joins={2: 0, 3: 1})), 2)

    def test_an_installation_spreads_over_its_site_but_not_past_it(self):
        base = row("military", 40, 40, 10, 8)
        spec = reserve([base], Settings(), None, Sites((20, 30, 120, 90)), random.Random(1),
                       (300, 300))[0]
        self.assertEqual(spec.tier, "installation")
        self.assertGreater(int(spec.mask.sum()), 80)
        ys, xs = np.nonzero(spec.mask)
        x0, y0 = 40 + spec.dx, 40 + spec.dy
        self.assertTrue(x0 + xs.min() >= 20 and x0 + xs.max() < 120)
        self.assertTrue(y0 + ys.min() >= 30 and y0 + ys.max() < 90)
        self.assertEqual(spec.levels, 2 + 0)   # 100 x 60 = 6,000 m2: the fewest levels

    def test_an_installation_is_cropped_to_its_ceiling(self):
        spec = reserve([row("military", 900, 900, 10, 10)], Settings(), None,
                       Sites((0, 0, 2000, 2000)), random.Random(1), (2000, 2000))[0]
        self.assertLessEqual(int(spec.mask.sum()), 40_000)
        self.assertEqual(spec.levels, 8)

    def test_a_second_installation_on_the_same_squares_shrinks_then_drops(self):
        sites = Sites((0, 0, 100, 100), (50, 0, 150, 100))
        rows = [row("military", 20, 40, 10, 10),     # takes the whole first site
                row("military", 120, 40, 10, 10),    # its site overlaps: shrinks to its footprint
                row("military", 60, 40, 10, 10)]     # inside the first site: nowhere to go
        specs = reserve(rows, Settings(), None, sites, random.Random(1), (300, 300))
        self.assertGreater(int(specs[0].mask.sum()), 1000)
        self.assertEqual(int(specs[1].mask.sum()), 8 * 8)
        self.assertIsNone(specs[2])

    def test_share_zero_reserves_no_house_basement(self):
        rows = [row("house", 10 * i, 10, 6, 6) for i in range(20)]
        self.assertEqual(reserve(rows, Settings(basement_share=0.0), None, None,
                                 random.Random(1), (300, 300)), [None] * 20)

    def test_east_asian_region_quarters_the_house_share(self):
        rows = [row("house", 4 * (i % 500), 4 * (i // 500), 3, 3) for i in range(4000)]
        got = reserve(rows, Settings(basement_share=0.4), "jp", None, random.Random(1),
                      (2000, 40))
        self.assertTrue(300 <= sum(s is not None for s in got) <= 500)


class SiteShapes(unittest.TestCase):
    def test_shape_around_is_the_smallest_area_holding_the_point(self):
        from knoxbuild.areas import AreaIndex
        town, base = shape_box(0, 0, 500, 500), shape_box(100, 100, 200, 180)
        index = AreaIndex([(town, {"category": "residential"}), (base, {"category": "military"})])
        self.assertTrue(index.shape_around(150, 150).equals(base))
        self.assertTrue(index.shape_around(10, 10).equals(town))
        self.assertIsNone(index.shape_around(900, 900))
        self.assertIsNone(AreaIndex([]).shape_around(1, 1))


def house_spec(parent):
    mask = np.ones((parent.height, parent.width), dtype=bool)
    return BasementSpec("house", "house", 1, 0, 0, _inside(mask))


def steps(x, y, d):
    return {(x, y + 1 + i) for i in range(3)} if d == "N" else {(x + 1 + i, y) for i in range(3)}


class Planning(unittest.TestCase):
    def test_a_house_basement_stairs_land_in_a_ground_floor_room(self):
        parent = build_building(12, 10, seed=3)
        b = plan_basement(parent, house_spec(parent), 3, Settings())
        self.assertIsNotNone(b)
        sx, sy, d = b.building.stairs[-1]
        px, py = sx + b.dx, sy + b.dy
        self.assertNotEqual(parent.storeys[0].grid[py][px], 0)
        self.assertTrue(steps(px, py, d) <= parent.storeys[0].holes)
        kinds = {r.kind for r in b.building.rooms}
        self.assertTrue(kinds <= {"laundry", "storage", "garage", "livingroom", "hall"}, kinds)

    def test_no_spot_no_basement(self):
        parent = build_building(4, 4, seed=1)
        self.assertIsNone(plan_basement(parent, house_spec(parent), 1, Settings()))
        self.assertEqual(parent.storeys[0].holes, set())

    def test_a_basement_has_no_windows_or_outside_doors(self):
        parent = build_building(12, 10, seed=3)
        b = plan_basement(parent, house_spec(parent), 3, Settings())
        for st in b.building.storeys:
            self.assertEqual(st.windows, [])
            for x, y, d in st.doors:
                ox, oy = (x, y - 1) if d == "N" else (x - 1, y)
                inside = [0 <= yy < len(st.grid) and 0 <= xx < len(st.grid[0]) and st.grid[yy][xx] != 0
                          for xx, yy in ((x, y), (ox, oy))]
                self.assertTrue(all(inside), (x, y, d))

    def test_an_installation_has_one_stair_core_through_every_level(self):
        parent = build_building(20, 14, kind="military", seed=5)
        spec = BasementSpec("installation", "military", 4, -10, -8,
                            np.ones((30, 40), dtype=bool))
        b = plan_basement(parent, spec, 5, Settings())
        self.assertEqual(len(b.building.storeys), 4)
        self.assertEqual(len(b.building.stairs), 4)
        self.assertEqual(len(set(b.building.stairs)), 1)

    def test_the_rendered_basement_has_no_roof_floor(self):
        parent = build_building(12, 10, seed=3)
        b = plan_basement(parent, house_spec(parent), 3, Settings())
        tbx = parse_tbx(render_basement(b, "t", None))
        self.assertEqual(len(tbx.floors), 1)
        self.assertTrue(any(o.get("type") == "stairs" for o in tbx.floors[0].objects))


if __name__ == "__main__":
    unittest.main()
