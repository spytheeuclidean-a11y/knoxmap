"""Buildings invented for gaps along a street (generator/rendering/infill.py)."""
import unittest

from shapely.geometry import Polygon

from generator.osm import OSMFeature
from generator.rendering.infill import _infill_frontage
from generator.rendering.projection import Projector

PROJ = Projector.build(35.90, -84.00, 35.92, -83.97, 1.0)
Y = 150.0                      # the street runs along y = 150 tiles


def way(ident, pts, **tags):
    return OSMFeature(osm_id=ident, kind="way", tags=tags,
                      geometry=[PROJ.to_latlon(x, y) for x, y in pts])


def box(ident, x0, x1, y0, y1, **tags):
    tags.setdefault("building", "house")
    return way(ident, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], **tags)


def street(x0=20, x1=300, y=Y, ident=1):
    return way(ident, [(x0, y), (x1, y)], highway="residential")


def row(start, count, pitch, width, y0, y1, skip=(), **tags):
    return [box(100 + i, start + i * pitch, start + i * pitch + width, y0, y1, **tags)
            for i in range(count) if i not in skip]


def polys(feats):
    return [Polygon([PROJ.to_px(la, lo) for la, lo in f.geometry]) for f in feats]


def fill(buildings, roads=(), **buckets):
    roads = list(roads) or [street()]
    return _infill_frontage({"road_minor": roads, **buckets}, [], buildings, PROJ)


class Houses(unittest.TestCase):
    # 15 m houses on an 18 m pitch, 12 m deep, standing 4 m off the pavement,
    # with the fifth to the eighth missing: a 70 m hole in a row of houses.
    def scene(self):
        return row(40, 14, 18, 15, 130, 142, skip=(4, 5, 6, 7))

    def test_a_hole_in_a_row_is_filled(self):
        made = fill(self.scene())
        self.assertGreaterEqual(len(made), 3)
        for p in polys(made):
            self.assertTrue(112 <= p.bounds[0] and p.bounds[2] <= 192)
            self.assertAlmostEqual(p.bounds[3] - p.bounds[1], 12, delta=2)

    def test_they_are_built_like_the_neighbours(self):
        made = fill(self.scene())
        self.assertTrue(all(f.tags["building"] == "house" for f in made))
        # standing as far back as the houses either side
        for p in polys(made):
            self.assertAlmostEqual(p.bounds[3], 142, delta=1.5)

    def test_nothing_overlaps_anything(self):
        existing = self.scene()
        made = fill(existing)
        every = polys(existing) + polys(made)
        for i, a in enumerate(every):
            for b in every[i + 1:]:
                self.assertLess(a.intersection(b).area, 1.0)

    def test_the_other_side_of_the_street_is_left_empty(self):
        for p in polys(fill(self.scene())):
            self.assertLess(p.bounds[3], Y)

    def test_a_lone_house_does_not_start_a_street(self):
        self.assertEqual(fill([box(1, 100, 115, 130, 142)]), [])

    def test_a_row_is_carried_on_only_a_little(self):
        one_end = row(40, 4, 18, 15, 130, 142)
        made = fill(one_end)
        self.assertLessEqual(len(made), 3)

    def test_a_church_beside_the_gap_says_nothing(self):
        scene = self.scene()
        scene[3] = box(103, 94, 111, 130, 142, building="church")
        self.assertEqual([f for f in fill(scene)
                          if polys([f])[0].bounds[0] < 120], [])

    def test_filling_is_repeatable(self):
        a = [(f.osm_id, f.geometry) for f in fill(self.scene())]
        b = [(f.osm_id, f.geometry) for f in fill(self.scene())]
        self.assertEqual(a, b)


class Downtown(unittest.TestCase):
    def test_a_street_wall_is_filled_wall_to_wall(self):
        # shops standing 0.5 tile off the pavement edge (y = 150 - 6.3)
        shops = [box(i, 40 + 14 * i, 54 + 14 * i, 128, 143.2, building="retail")
                 for i in range(12) if i not in (4, 5, 6)]
        made = fill(shops)
        self.assertGreaterEqual(len(made), 2)
        self.assertTrue(all(f.tags["building"] == "retail" for f in made))
        covered = sum(p.area for p in polys(made))
        self.assertGreater(covered, 0.8 * 3 * 14 * 14)     # almost the whole gap


class Blocked(unittest.TestCase):
    def test_water_in_the_gap_is_not_built_on(self):
        lake = way(50, [(112, 100), (190, 100), (190, 146), (112, 146), (112, 100)],
                   natural="water")
        made = fill(Houses().scene(), water=[lake])
        self.assertEqual(made, [])

    def test_a_side_street_is_not_built_across(self):
        cross = way(60, [(150, 40), (150, 150)], highway="residential")
        made = fill(Houses().scene(), roads=[street(), cross])
        for p in polys(made):
            self.assertFalse(p.intersects(
                Polygon([(144, 40), (156, 40), (156, 144), (144, 144)])))

    def test_nothing_outside_the_map(self):
        edge = row(0, 3, 18, 15, 130, 142) + row(70, 3, 18, 15, 130, 142)
        for p in polys(fill(edge)):
            self.assertGreaterEqual(p.bounds[0], 0)


if __name__ == "__main__":
    unittest.main()
