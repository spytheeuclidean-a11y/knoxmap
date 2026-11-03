"""Basements: who gets one, how deep, and where it may go (knoxbuild/basements.py)."""
import os
import random
import unittest
from types import SimpleNamespace

import numpy as np
from shapely.geometry import box as shape_box

from knoxbuild.basements import (BasementSpec, Underground, _inside, levels_for,
                                 plan_basement, render_basement, reserve, tier)
from knoxbuild.buildtiles import parse_tbx
from knoxbuild.layout import _blocks as layout_blocks, build_building
from knoxbuild.buildheader import placed_rooms
from knoxbuild.settings import Settings
from tools.compile_map import knoxlots_exe

# Only knoxlots compiles basements; without it a build makes none.
NEEDS_KNOXLOTS = unittest.skipIf(knoxlots_exe() is None, "knoxlots is not built")


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
        self.assertEqual(Settings.from_dict({"max_basement_depth": -3}).max_basement_depth, 0)

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
        self.assertEqual(tier("apartment", 400, 0), "house")    # flats: a cellar too

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
        # Nor the house above: in the game's maps a basement is always a
        # building of its own, and joined the house lost its roof.
        self.assertEqual(len(placed_rooms(lots)), 4)

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
        # Under its own footprint it is a building's basement, not the base's bunker.
        self.assertEqual((specs[0].tier, specs[1].tier), ("installation", "large"))
        self.assertEqual(specs[1].levels, levels_for("large", 100, 0, 8))

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

    def test_a_house_cellar_laundry_is_a_home_s_not_a_laundromat(self):
        """A house cellar's laundry once got coin washers down one wall and
        coin dryers down the other; a home has one washer."""
        found = 0
        for seed in range(40):
            parent = build_building(16, 14, seed=seed)
            b = plan_basement(parent, house_spec(parent), seed, Settings())
            if b is None or not any(r.kind == "laundry" for r in b.building.rooms):
                continue
            found += 1
            roles = [f[0] for st in b.building.storeys for f in st.furniture]
            self.assertFalse([r for r in roles if r.startswith("coin_")], seed)
            self.assertLessEqual(roles.count("washer"), 1, seed)
        self.assertGreater(found, 0)

    def stair_room(self, parent, b):
        """The ground floor's room holding the flight's top squares, its
        squares, and the doors on its edges."""
        g = parent.storeys[0]
        sx, sy, d = b.building.stairs[-1]
        top = [(sx + b.dx + (0 if d == "N" else i), sy + b.dy + (i if d == "N" else 0))
               for i in range(4)]
        n = g.grid[top[0][1]][top[0][0]]
        cells = {(x, y) for y, row in enumerate(g.grid) for x, v in enumerate(row) if v == n}
        doors = [(x, y, e) for x, y, e in g.doors
                 if {(x, y), (x, y - 1) if e == "N" else (x - 1, y)} & cells]
        return g, n, set(top), cells, doors

    def test_a_house_basement_is_reached_through_a_door_at_the_top(self):
        """A house too small to wall a flight off in (a 4 x 4 dining room
        cut in two by it) keeps open stairs; most are behind a door."""
        walled = 0
        for seed in range(12):
            parent = build_building(12, 10, seed=seed)
            b = plan_basement(parent, house_spec(parent), seed, Settings())
            if b is None:
                continue
            g, n, top, cells, doors = self.stair_room(parent, b)
            if cells != top:
                continue
            walled += 1
            with self.subTest(seed=seed):
                self.assertEqual(g.rooms[n - 1].kind, "hall")
                self.assertEqual(cells, top)            # a stairwell one wide
                self.assertEqual(len(doors), 1)
                self.assertFalse([f for f in g.furniture if (f[1], f[2]) in cells
                                  and layout_blocks(f[0])])
        self.assertGreaterEqual(walled, 10)

    def test_open_stairs_have_a_room_of_their_own(self):
        """A school's stairs come up in a stair hall: the flight and a lane
        beside it, walled off with a door, so nothing stands in the way."""
        found = 0
        for seed in range(12):
            parent = build_building(22, 16, kind="school", seed=seed, commercial=True)
            ground = np.array([[bool(v) for v in row] for row in parent.storeys[0].grid])
            spec = BasementSpec("large", "school", 1, 0, 0, _inside(ground))
            b = plan_basement(parent, spec, seed, Settings())
            if b is None:
                continue
            g, n, top, cells, doors = self.stair_room(parent, b)
            found += 1
            with self.subTest(seed=seed):
                self.assertTrue(top < cells)
                self.assertEqual(len(cells), 8)         # the flight and a lane
                self.assertEqual(len(doors), 1)
                self.assertFalse([f for f in g.furniture if (f[1], f[2]) in cells
                                  and layout_blocks(f[0])])
        self.assertGreater(found, 0)

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


@NEEDS_KNOXLOTS
class BuildingWithBasements(unittest.TestCase):
    """The whole build: tests/basement_town.py, built and compiled."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.work = tempfile.mkdtemp(prefix="bsmt-build-")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.work, ignore_errors=True)

    def _build(self, name, compile_lots=True, **settings):
        import os
        from tests.basement_town import build_town
        return build_town(os.path.join(self.work, name), Settings(seed=1, **settings),
                          compile_lots=compile_lots)

    @staticmethod
    def _pzw(out):
        import glob
        return open(glob.glob(out + "/*.pzw")[0], encoding="utf-8").read()

    @staticmethod
    def _bsmt_files(out):
        import glob
        return glob.glob(out + "/buildings/*_bsmt.tbx")

    def test_a_town_with_basements_builds_and_compiles(self):
        import glob
        from tools.building_stats import read_header
        from tools.compile_map import knoxlots_exe
        out = self._build("all", basement_share=1.0)
        self.assertIn('level="-1"', self._pzw(out))
        self.assertTrue(self._bsmt_files(out))
        if knoxlots_exe():
            lows = [read_header(p)[1] for p in glob.glob(out + "/lots/*.lotheader")]
            self.assertEqual(min(lows), -1)

    def test_share_zero_leaves_no_basement_lots_behind(self):
        out = self._build("again", basement_share=1.0)
        self.assertTrue(self._bsmt_files(out))
        self._build("again", basement_share=0.0)
        self.assertNotIn("_bsmt", self._pzw(out))
        self.assertEqual(self._bsmt_files(out), [])

    def test_a_rebuild_keeps_its_basements(self):
        out = self._build("twice", basement_share=1.0)
        first = sorted(self._bsmt_files(out))
        self._build("twice", basement_share=1.0)
        self.assertEqual(sorted(self._bsmt_files(out)), first)
        self.assertEqual(self._pzw(out).count("_bsmt.tbx"), len(first))

    def test_a_cache_entry_from_before_basements_is_laid_out_again(self):
        import json
        import os
        out = self._build("oldcache", basement_share=1.0)
        path = os.path.join(out, "build_cache.json")
        data = json.load(open(path, encoding="utf-8"))
        for entry in data["buildings"].values():
            entry["result"] = entry["result"][:4]
        json.dump(data, open(path, "w", encoding="utf-8"))
        n = len(self._bsmt_files(out))
        self._build("oldcache", basement_share=1.0)
        self.assertEqual(len(self._bsmt_files(out)), n)
        self.assertEqual(self._pzw(out).count("_bsmt.tbx"), n)

    def test_no_basements_same_bytes(self):
        import json
        import os
        from tests.basement_town import digest
        out = self._build(os.path.join("none", "bsmttown"), basement_share=0.0)   # the baseline's name
        here = os.path.dirname(os.path.abspath(__file__))
        want = json.load(open(os.path.join(here, "fixtures", "basements_baseline.json")))
        self.assertEqual(digest(out), want)


class PresetsAndSolver(unittest.TestCase):
    def test_a_preset_building_gets_no_basement(self):
        self.assertIsNone(tier("preset", 120, 0))
        got = reserve([row("preset", 10, 10, 12, 10)], Settings(basement_share=1.0), None, None,
                      random.Random(1), (100, 100))
        self.assertEqual(got, [None])

    def test_the_room_solver_never_sees_the_basement(self):
        import os
        import tempfile
        from unittest import mock
        from knoxbuild import build as B, room_solver
        seen = []

        def plan_for_job(job, roof=None):
            seen.append(len(job))
            return None

        with tempfile.TemporaryDirectory() as d,                 mock.patch.object(room_solver, "wanted", lambda s: True),                 mock.patch.object(room_solver, "plan_for_job", plan_for_job):
            spec = BasementSpec("house", "house", 1, 0, 0, _inside(np.ones((10, 12), bool)))
            job = (12, 10, 1, False, 3, None, None, Settings(), None, "t",
                   os.path.join(d, "t.tbx"), None, False, None, False, None, None, None,
                   False, None, {}, spec)
            result = B._make_one(job)
        self.assertEqual(seen, [B.JOB_FIELDS])
        self.assertIsNone(result[3], result[3])
        self.assertEqual(result[5]["file"], "t_bsmt.tbx")


class OnlyKnoxlotsReadsThem(unittest.TestCase):
    """BuildingEd has no hole object and wants a flight's top in the same file;
    knoxlots reads both (knoxbuild/buildtiles.py). A basement is for knoxlots."""

    def _files(self, d):
        import os
        parent = build_building(12, 10, seed=3)
        b = plan_basement(parent, house_spec(parent), 3, Settings())
        from knoxbuild.tbx import render_tbx
        out = {}
        for name, text in (("t.tbx", render_tbx(parent, "t")),
                           ("t_bsmt.tbx", render_basement(b, "t", None))):
            out[name] = os.path.join(d, name)
            open(out[name], "w", encoding="utf-8").write(text)
        return out

    def test_the_validator_takes_basements_for_knoxlots_only(self):
        import sys
        import tempfile
        sys.path.insert(0, "tools")
        import validate_tbx
        with tempfile.TemporaryDirectory() as d:
            for path in self._files(d).values():
                self.assertTrue(validate_tbx.check(path, knoxlots=False), path)
                self.assertEqual(validate_tbx.check(path, knoxlots=True), [], path)

    @NEEDS_KNOXLOTS
    def test_worlded_refuses_a_map_with_basements(self):
        import os
        from tools.compile_map import compile_map
        out = BuildingWithBasements._build(self._town, "worlded", basement_share=1.0)
        with self.assertRaises(RuntimeError) as got:
            compile_map(out, backend="worlded")
        self.assertIn("basement", str(got.exception))

    def test_no_basements_when_worlded_would_compile(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"KNOXMAP_BACKEND": "worlded"}):
            out = BuildingWithBasements._build(self._town, "plain", basement_share=1.0,
                                               compile_lots=False)
        self.assertEqual(BuildingWithBasements._bsmt_files(out), [])

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._town = SimpleNamespace(work=tempfile.mkdtemp(prefix="bsmt-only-"))

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._town.work, ignore_errors=True)


class NoGhostRooms(unittest.TestCase):
    def test_every_basement_room_has_squares(self):
        """The audit's own buildings (tools/audit_layouts.py), as far as the
        police station whose basement once kept a room with no squares."""
        import sys
        from collections import Counter
        sys.path.insert(0, "tools")
        import audit_layouts as A
        rng = random.Random(4242)
        for i in range(88):
            kind = A.KINDS[i % len(A.KINDS)]
            w, h = rng.randint(9, 40), rng.randint(9, 40)
            roll, mask = rng.random(), None
            if roll < 0.3:
                mask = A.irregular_mask(w, h, rng)
            elif roll < 0.65:
                fp = A.rotated_mask(rng)
                if fp is not None:
                    w, h, mask = fp.width, fp.height, fp.mask_list()
            levels = rng.choice((1, 2, 3, 4, 5, 6, 8, 12))
            if i < 87:
                continue
            b = build_building(w, h, levels=levels, seed=i, kind=kind, mask=mask,
                               commercial=kind not in (None, "apartment"))
            ground = np.array([[bool(v) for v in row] for row in b.storeys[0].grid])
            spec = BasementSpec("large", kind, 1, 0, 0, _inside(ground))
            below = plan_basement(b, spec, i, Settings())
            for st in below.building.storeys:
                owned = Counter(v for row in st.grid for v in row if v)
                self.assertEqual([n for n in range(1, len(st.rooms) + 1) if not owned[n]], [])


class ReviewFixes(unittest.TestCase):
    def test_depth_zero_turns_every_basement_off(self):
        rows = [row("house", 10, 10, 12, 10), row("school", 40, 10, 20, 20),
                row("military", 80, 10, 20, 20)]
        got = reserve(rows, Settings(basement_share=1.0, max_basement_depth=0), None, None,
                      random.Random(1), (200, 200))
        self.assertEqual(got, [None, None, None])

    def test_an_industrial_estate_stays_shallow(self):
        self.assertEqual(levels_for("installation", 500, 130_000, 8, kind="industrial"), 2)
        self.assertEqual(levels_for("installation", 500, 130_000, 8, kind="military"), 7)

    def test_the_biggest_building_on_a_site_takes_the_bunker(self):
        sites = Sites((0, 0, 200, 200))
        rows = [row("military", 20, 20, 4, 4),      # a guard hut, first in build order
                row("military", 100, 100, 30, 20)]  # the barracks
        specs = reserve(rows, Settings(), None, sites, random.Random(1), (300, 300))
        self.assertEqual(specs[1].tier, "installation")
        self.assertNotEqual(getattr(specs[0], "tier", None), "installation")


if __name__ == "__main__":
    unittest.main()
