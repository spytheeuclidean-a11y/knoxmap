import math
import unittest
from types import SimpleNamespace
from shapely.geometry import LineString,Point
from generator import octilinear,osm,renderer


class CleanRoadRuns(unittest.TestCase):
    def road(self,number,points):
        return osm.OSMFeature(number,'way',{'highway':'residential'},[(y,x) for x,y in points])

    def straighten(self,roads):
        projection=SimpleNamespace(width=400,height=400,to_px=lambda lat,lon:(lon,lat),
                                   to_latlon=lambda x,y:(y,x))
        octilinear.straighten_roads(roads,projection,osm.classify,renderer._is_polygon)
        return [[(x,y) for y,x in r.geometry] for r in roads]

    def test_small_sideways_kink_becomes_one_straight_run(self):
        road=self.road(1,[(10,50),(110,50),(120,60),(230,60)])
        points=self.straighten([road])[0]
        self.assertEqual(len(points),2,points)
        self.assertEqual(points[0][1],points[1][1])

    def test_short_bevel_becomes_square_corner_and_branch_stays_connected(self):
        main=self.road(1,[(10,50),(110,50),(120,60),(120,200)])
        side=self.road(2,[(120,60),(230,60)])
        main_points,side_points=self.straighten([main,side])
        for a,b in zip(main_points,main_points[1:]):
            self.assertTrue(a[0]==b[0] or a[1]==b[1],main_points)
        self.assertLess(Point(side_points[0]).distance(LineString(main_points)),1e-8)

    def test_major_diagonal_is_retained(self):
        road=self.road(1,[(10,50),(110,50),(180,120),(300,120)])
        points=self.straighten([road])[0]
        self.assertTrue(any(abs(a[0]-b[0])>30 and abs(a[1]-b[1])>30
                            for a,b in zip(points,points[1:])),points)

    def test_all_native_rail_markers_clear_vegetation_but_keep_adjacent_grass(self):
        import numpy as np
        from PIL import Image
        from generator import pz_colors as C
        from generator.rail_tiles import RAIL_RULES
        from generator.rendering.vegetation import _clear_road_vegetation
        colours = [colour for _, colour, _ in RAIL_RULES] + [C.DARK_GRASS]
        ground = Image.fromarray(np.array([colours], dtype=np.uint8))
        vegetation = Image.new("RGB", ground.size, (0, 255, 0))
        _clear_road_vegetation(vegetation, ground)
        result = np.array(vegetation)
        self.assertTrue(np.all(result[0, :-1] == C.VEG_NOTHING))
        self.assertEqual(tuple(result[0, -1]), (0, 255, 0))

    def test_shared_junctions_move_within_the_existing_cap(self):
        roads=[self.road(1,[(10,50),(110,55),(230,60)]),
               self.road(2,[(110,55),(113,180)]),
               self.road(3,[(10,180),(113,180),(230,185)])]
        before=[(r.geometry[0],r.geometry[-1]) for r in roads]
        self.straighten(roads)
        for r,ends in zip(roads,before):
            for a,b in zip(ends,(r.geometry[0],r.geometry[-1])):
                self.assertLessEqual(math.dist(a,b),octilinear.MAX_MOVE_TILES)
        self.assertLess(Point(roads[1].geometry[0]).distance(LineString(roads[0].geometry)),1e-8)
        self.assertLess(Point(roads[1].geometry[-1]).distance(LineString(roads[2].geometry)),1e-8)

    def test_vertical_to_diagonal_corner_has_no_mid_diagonal_shift(self):
        # North-south road bending 45 degrees into a diagonal road with an
        # intermediate node must stay on one exact diagonal without a 1-tile step.
        road = self.road(1, [(100, 20), (100, 80), (130, 111), (160, 141)])
        projection = SimpleNamespace(width=400, height=400, to_px=lambda lat, lon: (lon, lat),
                                     to_latlon=lambda x, y: (y, x))
        octilinear.straighten_roads([road], projection, osm.classify, renderer._is_polygon, clean=True)
        points = [(x, y) for y, x in road.geometry]
        self.assertEqual(len(points), 3, points)
        (x0, y0), (x1, y1), (x2, y2) = points
        self.assertEqual(x0, x1)
        self.assertEqual(abs(x2 - x1), abs(y2 - y1))


if __name__=='__main__':unittest.main()
