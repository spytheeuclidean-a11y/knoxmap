"""The game's own interior wall styles must be walls with a door and a window in them."""
import unittest

from knoxbuild import catalog


class GameWallStyles(unittest.TestCase):
    def test_see_through_partitions_are_not_wall_styles(self):
        # walls_commercial_02 at 16 and 32 are WallWTrans/WallNTrans partitions with
        # no door piece: used as a wall they came out as half walls and missing walls.
        for style in (("walls_commercial_02", 16), ("walls_commercial_02", 32)):
            self.assertNotIn(style, catalog.GAME_WALL_STYLES)

    def test_no_building_is_offered_those_tiles(self):
        offered = {tile for entry in catalog.INTERIOR_WALLS
                   for tile in entry["tiles"].values()}
        self.assertFalse({t for t in offered
                          if t.startswith(("walls_commercial_02_016", "walls_commercial_02_032"))})


if __name__ == "__main__":
    unittest.main()
