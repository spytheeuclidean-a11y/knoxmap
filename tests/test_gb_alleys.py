"""Back alleys between back-to-back British terraces (docs/REGIONAL_PROFILES.md,
GB step 6)."""
import unittest

from shapely.geometry import LineString

from generator.osm import OSMFeature
from generator.rendering.alleys import back_alleys
from generator.rendering.projection import Projector

PROJ = Projector.build(53.80, -1.52, 53.81, -1.50, 1.0)
X0, Y0 = 300, 300           # where the block stands, in tiles (= metres)


def way(points, tags, ident):
    return OSMFeature(osm_id=ident, kind="way", tags=tags,
                      geometry=[PROJ.to_latlon(X0 + x, Y0 + y) for x, y in points])


def house(x, y, w=5, d=8, ident=1):
    return way([(x, y), (x + w, y), (x + w, y + d), (x, y + d), (x, y)],
               {"building": "terrace"}, ident)


def street(points, ident, highway="residential"):
    return way(points, {"highway": highway}, ident)


def block(back_row=True, facing_away=True):
    """Two rows of six terraced houses: row A fronts the street at y=0, row B
    the street at y=32; 5 m yards behind each and a 2 m strip between them.
    Side streets close the block at x=-4 and x=34."""
    feats = [street([(-10, 0), (40, 0)], 9001), street([(-10, 32), (40, 32)], 9002),
             street([(-4, -10), (-4, 42)], 9003), street([(34, -10), (34, 42)], 9004)]
    for i in range(6):
        feats.append(house(i * 5, 2, ident=100 + i))
        if back_row:
            # facing_away: its front is on the y=32 street, so the backs meet.
            y = 22 if facing_away else 12
            feats.append(house(i * 5, y, ident=200 + i))
    return feats


def local(feat):
    pts = [PROJ.to_px(lat, lon) for lat, lon in feat.geometry]
    return LineString([(x - X0, y - Y0) for x, y in pts])


class BackAlleys(unittest.TestCase):
    def test_an_alley_runs_between_back_to_back_rows(self):
        alleys = back_alleys(block(), PROJ)
        self.assertEqual(len(alleys), 1)
        a = alleys[0]
        self.assertEqual(a.tags.get("highway"), "service")
        self.assertEqual(a.tags.get("service"), "alley")
        line = local(a)
        # Down the middle of the strip between the rear walls (y 10 and 22).
        for x, y in line.coords:
            self.assertAlmostEqual(y, 16, delta=1.5)
        # Joined to both side streets.
        xs = [x for x, _ in line.coords]
        self.assertLessEqual(min(xs), -3)
        self.assertGreaterEqual(max(xs), 33)

    def test_no_alley_where_one_is_already_mapped(self):
        feats = block() + [street([(-4, 16), (34, 16)], 9005, highway="footway")]
        self.assertEqual(back_alleys(feats, PROJ), [])

    def test_no_alley_behind_a_single_row(self):
        self.assertEqual(back_alleys(block(back_row=False), PROJ), [])

    def test_no_alley_between_rows_facing_the_same_way(self):
        self.assertEqual(back_alleys(block(facing_away=False), PROJ), [])

    def test_an_alley_never_runs_through_a_building(self):
        feats = block() + [way([(12, 13), (18, 13), (18, 19), (12, 19), (12, 13)],
                               {"building": "shed"}, 300)]
        for a in back_alleys(feats, PROJ):
            self.assertFalse(local(a).buffer(0.5).intersects(
                LineString([(12, 13), (18, 13), (18, 19), (12, 19), (12, 13)]).convex_hull))


if __name__ == "__main__":
    unittest.main()
