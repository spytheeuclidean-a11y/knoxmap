"""What a basement needs from the .tbx writer: holes, a top flight, no roof."""
import unittest

from knoxbuild.buildtiles import level_layers, parse_tbx
from knoxbuild.layout import Building, build_plan
from knoxbuild.tbx import render_tbx


def _small(levels=1):
    storeys = [build_plan(9, 8, seed=4, ground=(i == 0), level=i, levels=levels)
               for i in range(levels)]
    return Building(width=9, height=8, storeys=storeys)


class BasementTbx(unittest.TestCase):
    def test_holes_are_written_and_leave_no_floor(self):
        plan = build_plan(9, 8, seed=4)
        self.assertTrue(plan.grid[3][2])            # a room square, so it has a floor
        plan.holes = {(2, 2), (2, 3), (2, 4)}
        b = parse_tbx(render_tbx(plan, "t"))
        self.assertIn({"type": "hole", "x": "2", "y": "3"},
                      [{k: o.get(k) for k in ("type", "x", "y")} for o in b.floors[0].objects])
        floor_tiles = [t for t in level_layers(b, 0).get((2, 3), []) if t[0] == "Floor"]
        self.assertEqual(floor_tiles, [])

    def test_no_roof_floor_when_asked(self):
        self.assertGreater(len(parse_tbx(render_tbx(_small(2), "t")).floors), 2)
        b = parse_tbx(render_tbx(_small(2), "t", roof=False))
        self.assertEqual(len(b.floors), 2)
        self.assertFalse(any(o.get("type") == "roof" for f in b.floors for o in f.objects))

    def test_a_flight_on_the_top_storey(self):
        bld = _small(1)
        bld.stairs = [(2, 1, "N")]
        b = parse_tbx(render_tbx(bld, "t", roof=False))
        self.assertTrue(any(o.get("type") == "stairs" for o in b.floors[0].objects))


    def test_no_roof_even_when_the_style_has_one(self):
        from knoxbuild.catalog import HOUSE_STYLES
        style = next(s for s in HOUSE_STYLES if s.get("roof"))
        b = parse_tbx(render_tbx(_small(1), "t", style, roof=False))
        self.assertEqual(len(b.floors), 1)
        self.assertFalse(any(o.get("type") == "roof" for f in b.floors for o in f.objects))


if __name__ == "__main__":
    unittest.main()
