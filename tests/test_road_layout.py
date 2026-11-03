"""The Road layout setting's vanilla choices (generator/roadgraph): every routed road on
vanilla's sixteen directions with its junctions shared; the frontage-density mode (a
sparse street keeps its 2:1, a dense one goes on the grid, a terraced street's jog moves
to the gap in its frontage, a road keeps off a building on its line); the numpy stand-ins
for scipy; the routed roads saved by Generate and read back the same by Build."""
import json
import math
import os
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np

from generator import octilinear, osm, renderer
from generator.roadgraph import modes, network, raster, route, snap
from knoxbuild.settings import Settings

H = W = 200


def plain_projection(size=400):
    """1 tile = 1 degree, y down as lat: to_px(lat, lon) = (lon, lat)."""
    return SimpleNamespace(width=size, height=size, meters_per_tile=1.0,
                           to_px=lambda lat, lon: (lon, lat), to_latlon=lambda x, y: (y, x))


def a_route(s, g, pts, h=None, width=4):
    return snap._route(pts, s, g, h, h, 2, snap.min_run(width), {}, 0, road_width=width)


def share_2to1(path) -> float:
    vs = raster.vertices(path)
    seg = [(math.hypot(b[0] - a[0], b[1] - a[1]), a, b) for a, b in zip(vs, vs[1:])]
    two = sum(L for L, a, b in seg if a[0] != b[0] and a[1] != b[1] and abs(b[0] - a[0]) != abs(b[1] - a[1]))
    return two / sum(L for L, _a, _b in seg)


def town():
    """A main road on a gentle curve, a side road off it at an angle, a lane off that."""
    main = osm.OSMFeature(1, "way", {"highway": "primary", "name": "High Street"},
                          [(200, 20), (190, 100), (175, 180), (170, 260), (172, 380)])
    side = osm.OSMFeature(2, "way", {"highway": "residential", "name": "Mill Lane"},
                          [(175, 180), (130, 200), (90, 230), (40, 250)])
    lane = osm.OSMFeature(3, "way", {"highway": "residential"},
                          [(90, 230), (60, 200), (40, 160)])
    house = osm.OSMFeature(4, "way", {"building": "house"},
                           [(150, 140), (150, 150), (160, 150), (160, 140), (150, 140)])
    return [main, side, lane, house]


class Routing(unittest.TestCase):
    def test_every_road_runs_on_the_sixteen_directions_and_junctions_are_shared(self):
        feats = town()
        proj = plain_projection()
        graph = route.route(feats, proj, "graph", log=lambda *a: None)
        self.assertEqual(set(graph["ways"]), {"1", "2", "3"})
        for w, g in graph["ways"].items():
            pts = [proj.to_px(*p) for p in g["geometry"]]
            for a, b in zip(pts, pts[1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                k = math.gcd(int(round(dx)), int(round(dy))) or 1
                self.assertIn((round(dx) // k, round(dy) // k), snap.STEP, f"way {w}: {a} -> {b}")
        ends = {w: {tuple(g["geometry"][0]), tuple(g["geometry"][-1])} for w, g in graph["ways"].items()}
        on = {w: {tuple(p) for p in g["geometry"]} for w, g in graph["ways"].items()}
        self.assertTrue(ends["2"] & on["1"], "the side road meets the main road at one of its nodes")
        self.assertTrue(ends["3"] & on["2"], "the lane meets the side road at one of its nodes")
        self.assertTrue(graph["shift"])

    def test_the_graph_moves_the_rest_of_the_town_with_the_roads(self):
        feats = town()
        proj = plain_projection()
        graph = route.route(feats, proj, "graph", log=lambda *a: None)
        before = list(feats[3].geometry)
        n = octilinear.apply_road_graph(feats, graph, proj)
        self.assertEqual(n, 3)
        self.assertEqual([list(p) for p in feats[0].geometry], graph["ways"]["1"]["geometry"])
        self.assertNotEqual(feats[3].geometry, before)          # the house moved with its street

    def test_a_roundabout_stays_as_drawn_and_the_roads_meet_it(self):
        ring = [(200.3 + 12 * math.sin(a), 199.6 + 12 * math.cos(a)) for a in np.linspace(0, 2 * math.pi, 13)]
        ring[-1] = ring[0]
        rb = osm.OSMFeature(9, "way", {"highway": "primary", "junction": "roundabout"}, ring)
        west = osm.OSMFeature(10, "way", {"highway": "primary"}, [(190, 20), (195, 120), ring[9]])
        east = osm.OSMFeature(11, "way", {"highway": "primary"}, [ring[3], (205, 300), (215, 380)])
        proj = plain_projection()
        graph = route.route([rb, west, east], proj, "graph", log=lambda *a: None)
        self.assertEqual(graph["ways"]["9"]["geometry"], [list(p) for p in ring])
        self.assertEqual(tuple(graph["ways"]["10"]["geometry"][-1]), ring[9])   # off the tile corners
        self.assertEqual(tuple(graph["ways"]["11"]["geometry"][0]), ring[3])

    def test_a_roundabout_mapped_as_arcs_is_one_ring(self):
        # four quarter arcs; a road leaves straight out east from the eastern node (tile x
        # is lon here): it must be free to (an arc's own middle once pointed it elsewhere)
        ring = [(200 + 12 * math.sin(a), 200 + 12 * math.cos(a)) for a in np.linspace(0, 2 * math.pi, 17)]
        ring[-1] = ring[0]
        arcs = [osm.OSMFeature(20 + k, "way", {"highway": "primary", "junction": "roundabout"}, ring[4 * k:4 * k + 5])
                for k in range(4)]
        lat, lon = ring[0]
        out = osm.OSMFeature(30, "way", {"highway": "primary"}, [ring[0], (lat, lon + 40), (lat, lon + 90)])
        proj = plain_projection()
        nodes, links, pins = network.build(arcs + [out], proj)
        (n,) = [n for n in pins if n in (links[0].u, links[0].v)]
        self.assertGreater(pins[n][0], 0.9)                             # outwards: +x
        graph = route.route(arcs + [out], proj, "graph", log=lambda *a: None)
        pts = [proj.to_px(*q) for q in graph["ways"]["30"]["geometry"]]
        self.assertLessEqual(max(abs(y - pts[0][1]) for _x, y in pts), 2)    # straight out, no hook

    def test_a_dual_carriageway_is_one_road(self):
        a = osm.OSMFeature(1, "way", {"highway": "primary", "oneway": "yes"}, [(100, 20), (100, 380)])
        b = osm.OSMFeature(2, "way", {"highway": "primary", "oneway": "yes"}, [(110, 380), (110, 20)])
        nodes, links, _pins = network.build([a, b], plain_projection())
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].tags.get("dual_carriageway"), "yes")
        graph = route.route([a, b], plain_projection(), "graph", log=lambda *a: None)
        self.assertEqual(graph["ways"]["1"]["geometry"], graph["ways"]["2"]["geometry"][::-1])
        self.assertNotIn("width", graph["ways"]["1"]["tags"])     # drawn as one ordinary road

    def test_a_width_in_metres_is_tiles_at_the_maps_scale(self):
        f = osm.OSMFeature(1, "way", {"highway": "residential", "width": "8"}, [(100, 20), (100, 380)])
        proj = plain_projection()
        self.assertEqual(network.build([f], proj)[1][0].width, 8)
        proj.meters_per_tile = 2.0
        self.assertEqual(network.build([f], proj)[1][0].width, 4)


class Modes(unittest.TestCase):
    def tearDown(self):
        modes.reset()

    def test_density_is_high_by_a_frontage_and_nothing_far_off(self):
        edge = np.zeros((H, W), bool)
        edge[100, 20:180] = True                     # a long row of house fronts
        d = modes.density(edge)
        self.assertGreater(d[100, 100], 0.5)
        self.assertLess(d[100 - 40, 100], 0.01)
        self.assertLessEqual(d.max(), 1.0)

    def test_a_sparse_street_keeps_its_2to1(self):
        s, g = (20, 50), (140, 110)                  # a street at 2:1, nothing beside it
        snap.COST = np.zeros((H, W))
        self.assertGreater(share_2to1(a_route(s, g, [s, g], h=1)), 0.9)

    def test_a_dense_street_is_drawn_on_the_grid(self):
        s, g = (20, 50), (140, 110)
        free = a_route(s, g, [s, g])
        snap.COST = np.ones((H, W))                  # lined with buildings all along
        dense = a_route(s, g, [s, g])
        self.assertLess(share_2to1(dense), share_2to1(free) - 0.5)

    def test_a_terraced_streets_jog_moves_to_the_gap(self):
        # The real street steps 10 tiles south at x 40; terraces both sides all along but
        # for a gap at x 80-105 (no building within JOG_GAP of the road's edge there).
        s, g = (10, 50), (130, 60)
        line = [s, (40, 50), (40, 60), g]
        snap.COST = np.ones((H, W))
        dist = np.full((H, W), 3.0)
        dist[:, 80:106] = 20.0
        snap.JOG = {"dist": dist, "plots": None}
        inner = raster.vertices(a_route(s, g, line, h=0))[1:-1]
        self.assertTrue(inner)
        for x, _y in inner:
            self.assertTrue(78 <= x <= 107, f"a turn at x {x}, not in the gap: {inner}")
        snap.JOG = None                              # without the rule it jogs near the real step
        free = raster.vertices(a_route(s, g, line, h=0))[1:-1]
        self.assertTrue(any(x < 70 for x, _y in free), free)

    def test_occupancy_steers_a_road_off_a_building_on_its_line(self):
        s, g = (20, 100), (180, 100)
        fp = np.zeros((H, W), bool)
        fp[97:106, 85:115] = True                    # a building standing across the real line
        under = lambda path: snap.occ_field(4)[[y for _x, y in path], [x for x, _y in path]].sum()
        snap.OCC = fp
        straight = a_route(s, g, [s, g], h=0)        # OCC_WEIGHT 0: through it
        snap.OCC_WEIGHT = 4.0
        try:
            around = a_route(s, g, [s, g], h=0)
        finally:
            snap.OCC_WEIGHT = 0.0
        self.assertGreater(under(straight), 0)
        self.assertLess(under(around), under(straight) / 4)

    def test_a_modes_constants_are_put_back(self):
        before = (snap.OCC_WEIGHT, snap.DIR_PENALTY)
        info = modes.prepare("cost", [], H, W)
        self.assertEqual(info["mode"], "cost")
        self.assertEqual(snap.OCC_WEIGHT, 1.0)
        self.assertIsNotNone(snap.COST)
        modes.reset()
        self.assertEqual((snap.OCC_WEIGHT, snap.DIR_PENALTY), before)
        self.assertIsNone(snap.COST)
        self.assertIsNone(snap.JOG)


class WithoutScipy(unittest.TestCase):
    def test_distance_is_exact_up_to_its_cap(self):
        rng = np.random.default_rng(1)
        fill = rng.random((40, 50)) > 0.97
        d = modes.distance(fill, cap=8)
        ys, xs = np.nonzero(fill)
        for y in range(40):
            for x in range(50):
                want = min(math.hypot(x - xs[k], y - ys[k]) for k in range(len(xs)))
                self.assertAlmostEqual(d[y, x], min(want, 9.0), places=6)

    def test_least_squares_matches_numpy(self):
        rng = np.random.default_rng(2)
        A = rng.random((30, 12)) * (rng.random((30, 12)) > 0.6)
        A[np.arange(12), np.arange(12)] += 1.0
        b = rng.random(30)
        rows, cols = np.nonzero(A)
        got = snap._least_squares(rows, cols, A[rows, cols], b, 12, np.zeros(12))
        want = np.linalg.lstsq(A, b, rcond=None)[0]
        self.assertTrue(np.allclose(got, want, atol=1e-6))

    def test_convolve_is_the_same_size_and_centred(self):
        a = np.zeros((9, 9))
        a[4, 4] = 1.0
        k = np.arange(9, dtype=float).reshape(3, 3)
        out = snap.convolve(a, k)
        self.assertEqual(out.shape, a.shape)
        self.assertAlmostEqual(out[3:6, 3:6].sum(), k.sum())
        self.assertAlmostEqual(out[4, 4], k[1, 1])


class Setting(unittest.TestCase):
    def test_four_road_layouts(self):
        self.assertEqual(Settings().straight_roads, 1)
        self.assertEqual(Settings.from_dict({"straight_roads": 3}).straight_roads, 3)
        self.assertEqual(Settings.from_dict({"straight_roads": 9}).straight_roads, 3)
        self.assertEqual(set(renderer.ROAD_LAYOUTS.values()), set(modes.PRESETS))

    def test_build_reads_the_saved_roads_back(self):
        proj = plain_projection()
        graph = route.route(town(), proj, "graph", log=lambda *a: None)
        with tempfile.TemporaryDirectory() as d:
            with open(octilinear.graph_path(d, "m"), "w", encoding="utf-8") as f:
                json.dump(graph, f)
            feats = town()
            n = octilinear.replay(feats, proj, osm.classify, renderer._is_polygon,
                                  {"straight_roads": 2}, d, "m")
            self.assertEqual(n, 3)
            self.assertEqual([list(p) for p in feats[1].geometry], graph["ways"]["2"]["geometry"])
            with self.assertRaises(RuntimeError):
                octilinear.replay(town(), proj, osm.classify, renderer._is_polygon, {"straight_roads": 2}, d, "x")
        self.assertEqual(octilinear.replay(town(), proj, osm.classify, renderer._is_polygon,
                                           {"straight_roads": 0}, "", "m"), 0)


if __name__ == "__main__":
    unittest.main()
