import unittest

from knoxbuild import catalog as C
from knoxbuild.layout import build_plan
from knoxbuild.tbx import render_tbx



class GarageGable(unittest.TestCase):
    def test_the_gable_ends_are_the_walls_own_style_not_white_clapboard(self):
        brick = next(s for s in C.HOUSE_STYLES if s["name"] == "brick")
        clap = next(s for s in C.HOUSE_STYLES if s["name"] == "clapboard")
        doc = render_tbx(build_plan(8, 6, kind="garage", seed=1), "g", style=brick)
        self.assertIn(brick["roof"]["caps"]["tiles"]["CapRiseE1"], doc)
        self.assertNotIn(clap["roof"]["caps"]["tiles"]["CapRiseE1"], doc)


if __name__ == "__main__":
    unittest.main()
