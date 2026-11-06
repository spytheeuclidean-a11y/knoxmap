import unittest
import numpy as np
from PIL import Image
from generator.rendering.geometry import _draw_roads


class RoadBevels(unittest.TestCase):
    def paint(self, paths, width=6):
        image=Image.new('L',(100,100),0)
        _draw_roads(image,[(width,paths)],255)
        return np.array(image)

    def test_even_width_has_no_one_tile_bulge_at_vertices(self):
        for width in (4,6,8,12):
            with self.subTest(width=width):
                road=self.paint([[(10,50),(40,50),(80,50)]],width)
                for x in (15,39,40,41,75):
                    self.assertEqual(np.count_nonzero(road[:,x]),width)

    def test_outer_corner_is_a_45_degree_bevel(self):
        road=self.paint([[(10,50),(50,50),(50,10)]],8)
        edges=[]
        for y in (51,52,53,54):
            xs=np.flatnonzero(road[y]);self.assertTrue(len(xs))
            edges.append(int(xs[-1]))
        self.assertEqual(np.diff(edges).tolist(),[-1,-1,-1],edges)

    def test_small_diagonal_retains_its_inside_45_degree_cut(self):
        road=self.paint([[(50,90),(50,53),(53,50),(90,50)]],6)
        self.assertEqual(road[54,54],255)
        self.assertEqual(road[55,54],0)
        self.assertEqual(road[54,55],0)

    def test_separate_map_ways_make_the_same_corner(self):
        whole=self.paint([[(10,50),(50,50),(50,10)]],8)
        split=self.paint([[(10,50),(50,50)],[(50,10),(50,50)]],8)
        np.testing.assert_array_equal(whole,split)

    def test_projection_roundoff_cannot_add_an_extra_edge_tile(self):
        path=[(10,50),(50,50),(50,10)]
        noisy=[(x+1e-10,y-1e-10) for x,y in path]
        np.testing.assert_array_equal(self.paint([path]),self.paint([noisy]))

    def test_closed_road_does_not_fill_its_centre(self):
        road=self.paint([[(20,20),(80,20),(80,80),(20,80),(20,20)]])
        self.assertEqual(road[50,50],0)
        self.assertEqual(road[20,50],255)

    def test_narrow_and_clipped_roads_still_draw(self):
        for width in (1,3,6):
            road=self.paint([[(-30,0),(40,0),(40,50)]],width)
            self.assertEqual(road[20,40],255)


if __name__=='__main__':unittest.main()
