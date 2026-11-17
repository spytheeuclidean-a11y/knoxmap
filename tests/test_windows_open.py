"""A window on a house has to open.

Project Zomboid marks most of each window sheet WindowLocked: those sprites
can never be opened, only smashed, and once smashed never shut again. Five of
the fourteen house styles were built with them, and a school, a surgery and a
town hall too - so about a third of a town's houses had windows nobody could
climb through or close behind them.

A shop front and a factory's glazing keep theirs. Fixed panes are what those
are in the game as well.
"""
import unittest

from knoxbuild import catalog as C
from knoxbuild.buildtiles import LOCKED_WINDOWS, window_locked

# Buildings people live in or walk into. The ones left out are the shop
# fronts (restaurant, shop), a works (industrial) and a barn.
MUST_OPEN = {"civic", "medical", "school"}


def west(style):
    return (style.get("window") or {}).get("tiles", {}).get("West", "")


class WindowsPeopleCanOpen(unittest.TestCase):
    def test_every_house_style_has_windows_that_open(self):
        shut = [s["name"] for s in C.HOUSE_STYLES if window_locked(west(s))]
        self.assertEqual(shut, [], f"houses with windows that never open: {shut}")

    def test_so_does_every_building_people_walk_into(self):
        for kind in sorted(MUST_OPEN):
            with self.subTest(kind=kind):
                self.assertFalse(window_locked(west(C.SPECIAL_STYLES[kind])),
                                 west(C.SPECIAL_STYLES[kind]))
                for variant in C.SPECIAL_STYLE_VARIANTS.get(kind, ()):
                    self.assertFalse(window_locked(west(variant)), west(variant))

    def test_a_shop_front_is_still_a_fixed_pane(self):
        # Not every locked window is a mistake: a shop window is one sheet of
        # glass in the game too, and it is meant to be broken rather than
        # opened.
        self.assertTrue(window_locked(west(C.SPECIAL_STYLES["shop"])))

    def test_the_rule_reads_a_sprite_number_the_way_the_game_does(self):
        self.assertTrue(window_locked("fixtures_windows_wood_008"))
        self.assertTrue(window_locked("fixtures_windows_wood_8"))
        self.assertFalse(window_locked("fixtures_windows_wood_018"))
        self.assertFalse(window_locked("fixtures_windows_church_014"))
        # A sheet nobody recorded, and anything that is not a window at all.
        self.assertFalse(window_locked("fixtures_windows_curtains_01_040"))
        self.assertFalse(window_locked(""))
        self.assertFalse(window_locked("walls_exterior_house_01_032"))

    def test_the_table_covers_the_sheets_the_styles_are_built_from(self):
        used = set()
        for style in list(C.HOUSE_STYLES) + list(C.SPECIAL_STYLES.values()):
            tile = west(style)
            if tile:
                used.add(tile.rsplit("_", 1)[0])
        # church is the one sheet with nothing locked in it, so it is not in
        # the table; everything else a style uses has to be.
        self.assertTrue(used - set(LOCKED_WINDOWS) <= {"fixtures_windows_church"},
                        sorted(used - set(LOCKED_WINDOWS)))

    def test_mismatched_tall_or_wide_windows_omit_curtains(self):
        from xml.etree import ElementTree

        from knoxbuild import layout
        from knoxbuild.tbx import render_tbx

        built = layout.build_building(8, 8, levels=1, seed=1, kind="house")
        by_name = {s["name"]: s for s in C.HOUSE_STYLES}
        for name, want_curtains in (("clapboard", True), ("siding_green", False), ("siding_pink", False)):
            root = ElementTree.fromstring(render_tbx(built, name, style=by_name[name]))
            win_curtains = {
                int(obj.attrib["CurtainsTile"])
                for obj in root.iter("object")
                if obj.attrib.get("type") == "window"
            }
            self.assertTrue(win_curtains, name)
            if want_curtains:
                self.assertTrue(all(c > 0 for c in win_curtains), (name, win_curtains))
            else:
                self.assertEqual(win_curtains, {0}, (name, win_curtains))


if __name__ == "__main__":
    unittest.main()
