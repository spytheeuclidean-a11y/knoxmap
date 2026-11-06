"""The rotation threshold must not reject a town with more than one phase."""
import unittest

from generator.rendering.gridangle import ALIGN_MIN_STRENGTH


class Threshold(unittest.TestCase):
    def test_a_multi_phase_town_still_qualifies(self):
        # Strength is the winning district's share of all road in the box, so
        # a second phase or rural lanes dilute it. Measured towns that were
        # left staircased scored 0.135, 0.223 and 0.234.
        self.assertLessEqual(ALIGN_MIN_STRENGTH, 0.135)


if __name__ == "__main__":
    unittest.main()
