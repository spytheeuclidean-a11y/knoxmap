"""Basements: who gets one, how deep, and where it may go (knoxbuild/basements.py)."""
import unittest

from knoxbuild.settings import Settings


class BasementSettings(unittest.TestCase):
    def test_defaults(self):
        s = Settings()
        self.assertEqual((s.basement_share, s.max_basement_depth), (0.4, 8))

    def test_depth_stops_at_the_game_s_bottom_level(self):
        self.assertEqual(Settings.from_dict({"max_basement_depth": 40}).max_basement_depth, 32)
        self.assertEqual(Settings.from_dict({"max_basement_depth": 0}).max_basement_depth, 1)

    def test_share_is_a_fraction(self):
        self.assertEqual(Settings.from_dict({"basement_share": 3}).basement_share, 1.0)


if __name__ == "__main__":
    unittest.main()
