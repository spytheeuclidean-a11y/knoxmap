"""Sharing a map's ceiling out: by kind of building, and by town.

`max_buildings` on its own keeps whatever the spacing rule keeps, which is
the map's own mix and the map's own distribution. Two things are asked for
instead (knoxbuild/mixer.py):

  - "of 3000 buildings, 40% houses and 15% shops"
  - "two cities and ten villages: share them out, not all into the cities"

Neither can be a promise - a map can only keep buildings that are on it -
so what a kind or a town cannot use goes to one that can. Without that,
asking for 3000 on a map whose mix is nothing like the one asked for
quietly builds 800, and the setting looks broken rather than bounded.
"""
import unittest

from knoxbuild import mixer
from knoxbuild.procedural import cap
from knoxbuild.settings import Settings


class ReadingAMix(unittest.TestCase):
    def test_percentages_become_shares(self):
        mix = mixer.parse("house=40,shop=15,industrial=10")
        self.assertAlmostEqual(sum(mix.values()), 1.0)
        self.assertAlmostEqual(mix["house"], 0.4 / 0.65, places=6)

    def test_they_need_not_add_to_a_hundred(self):
        # Half the people writing one of these will not make them add up,
        # and refusing the map over arithmetic helps nobody.
        rough = mixer.parse("house=2,shop=1")
        tidy = mixer.parse("house=66.7,shop=33.3")
        for kind in ("house", "shop"):
            self.assertAlmostEqual(rough[kind], tidy[kind], places=3)

    def test_the_words_people_use(self):
        mix = mixer.parse("farm=50,warehouse=50")
        self.assertEqual(sorted(mix), ["barn", "industrial"])

    def test_percent_signs_and_spacing_are_tolerated(self):
        self.assertEqual(sorted(mixer.parse(" House = 40% ; shop=60 ")),
                         ["house", "shop"])

    def test_junk_is_no_mix_at_all_rather_than_a_crash(self):
        for spec in ("", "   ", "nonsense", "house", "house=0", "house=-5",
                     "house=nan", None, 7):
            with self.subTest(spec=spec):
                self.assertEqual(mixer.parse(spec), {})

    def test_the_preset_is_a_real_mix(self):
        mix = mixer.parse("preset")
        self.assertAlmostEqual(sum(mix.values()), 1.0)
        self.assertGreater(mix["house"], mix["shop"])

    def test_every_kind_the_build_makes_lands_in_a_share(self):
        # A kind with no line falls in "other", which is why "other" has a
        # share: a map with no hotels should not lose what it was promised.
        from knoxbuild.build import SPECIAL_BY_VALUE
        for kind in set(SPECIAL_BY_VALUE.values()) | {None, "house"}:
            with self.subTest(kind=kind):
                self.assertTrue(mixer.category_of(kind))


class SharingOut(unittest.TestCase):
    def test_evenly_when_everybody_can_take_it(self):
        counts = {f"town{i}": 500 for i in range(12)}
        got = mixer.share_out(counts, 3000)
        self.assertEqual(sum(got.values()), 3000)
        self.assertEqual(set(got.values()), {250})

    def test_what_one_cannot_use_goes_to_one_that_can(self):
        got = mixer.share_out({"city": 2000, "village": 40}, 1000)
        self.assertEqual(got["village"], 40)
        self.assertEqual(sum(got.values()), 1000)

    def test_a_ceiling_bigger_than_the_map_keeps_everything(self):
        got = mixer.share_out({"a": 10, "b": 5}, 1000)
        self.assertEqual(got, {"a": 10, "b": 5})

    def test_shares_are_honoured_where_they_can_be(self):
        counts = {"house": 10000, "shop": 10000}
        got = mixer.share_out(counts, 1000, {"house": 0.8, "shop": 0.2})
        self.assertEqual(got["house"], 800)
        self.assertEqual(got["shop"], 200)

    def test_a_ceiling_smaller_than_the_number_of_groups(self):
        # Rounding puts everybody at zero; somebody still has to be built.
        got = mixer.share_out({f"g{i}": 50 for i in range(20)}, 5)
        self.assertEqual(sum(got.values()), 5)

    def test_nothing_to_share(self):
        self.assertEqual(mixer.share_out({}, 100), {})
        self.assertEqual(mixer.share_out({"a": 5}, 0), {})


class WhichTown(unittest.TestCase):
    PLACES = [{"name": "Ayton", "tile_x": 0, "tile_y": 0},
              {"name": "Beeford", "tile_x": 1000, "tile_y": 0}]

    def test_a_building_belongs_to_the_nearest(self):
        self.assertEqual(mixer.nearest_place(10, 10, self.PLACES), "Ayton")
        self.assertEqual(mixer.nearest_place(900, 50, self.PLACES), "Beeford")

    def test_a_farm_miles_out_is_still_somebody_s_countryside(self):
        # A radius here would be a number nobody could guess the value of.
        self.assertEqual(mixer.nearest_place(-9000, -9000, self.PLACES), "Ayton")

    def test_a_place_with_no_position_is_skipped(self):
        places = [{"name": "Nowhere"}, *self.PLACES]
        self.assertEqual(mixer.nearest_place(5, 5, places), "Ayton")

    def test_no_places_at_all(self):
        self.assertEqual(mixer.nearest_place(5, 5, []), "")


class TheBudgets(unittest.TestCase):
    def items(self, kinds_and_places):
        return [(i, kind, place)
                for i, (kind, place) in enumerate(kinds_and_places)]

    def test_by_town_alone(self):
        items = self.items([(None, "A")] * 100 + [(None, "B")] * 100)
        budgets, group_of = mixer.budgets(items, 50, None, True)
        self.assertEqual(sum(budgets.values()), 50)
        self.assertEqual(sorted(budgets.values()), [25, 25])
        self.assertEqual(group_of[0], ("A",))

    def test_by_kind_alone(self):
        items = self.items([(None, "")] * 500 + [("shop", "")] * 500)
        budgets, group_of = mixer.budgets(
            items, 100, {"house": 0.9, "shop": 0.1}, False)
        self.assertEqual(budgets[("house",)], 90)
        self.assertEqual(budgets[("shop",)], 10)

    def test_by_both_at_once(self):
        items = self.items([(None, "A")] * 100 + [("shop", "A")] * 100
                           + [(None, "B")] * 100 + [("shop", "B")] * 100)
        budgets, _ = mixer.budgets(items, 80, {"house": 0.75, "shop": 0.25}, True)
        self.assertEqual(sum(budgets.values()), 80)
        self.assertEqual(budgets[("A", "house")], budgets[("B", "house")])
        self.assertGreater(budgets[("A", "house")], budgets[("A", "shop")])

    def test_with_neither_it_is_one_group(self):
        items = self.items([(None, "")] * 10)
        budgets, group_of = mixer.budgets(items, 5, None, False)
        self.assertEqual(list(budgets), [("all",)])
        self.assertEqual(set(group_of.values()), {("all",)})


class TheCeilingItself(unittest.TestCase):
    def grid(self, n=400):
        return [(i, (i % 40) * 25.0, (i // 40) * 25.0, 8.0, False)
                for i in range(n)]

    def test_each_group_is_held_to_its_own_number(self):
        items = self.grid()
        group_of = {i: ("odd",) if i % 2 else ("even",) for i in range(400)}
        kept = cap(items, 50, {("odd",): 30, ("even",): 20}, group_of)
        odd = sum(1 for i in kept if group_of[i] == ("odd",))
        self.assertEqual(len(kept), 50)
        self.assertEqual(odd, 30)

    def test_a_group_with_no_budget_is_dropped_entirely(self):
        items = self.grid()
        group_of = {i: ("keep",) if i < 200 else ("drop",) for i in range(400)}
        kept = cap(items, 10, {("keep",): 10}, group_of)
        self.assertTrue(all(i < 200 for i in kept))

    def test_without_budgets_it_behaves_as_it_always_did(self):
        self.assertEqual(len(cap(self.grid(), 50)), 50)


class TheSettings(unittest.TestCase):
    def test_a_map_takes_its_own_mix_by_default(self):
        self.assertEqual(Settings().building_mix, "")
        self.assertEqual(Settings().spread_buildings, 1)

    def test_a_usable_mix_is_kept(self):
        self.assertEqual(
            Settings.from_dict({"building_mix": "house=40,shop=60"}).building_mix,
            "house=40,shop=60")

    def test_junk_leaves_the_map_its_own_mix(self):
        for spec in ("nonsense", "house", 7, None):
            with self.subTest(spec=spec):
                self.assertEqual(
                    Settings.from_dict({"building_mix": spec}).building_mix, "")

    def test_it_survives_a_round_trip(self):
        one = Settings.from_dict({"building_mix": "preset", "spread_buildings": 0})
        two = Settings.from_dict(one.to_dict())
        self.assertEqual(two.building_mix, "preset")
        self.assertEqual(two.spread_buildings, 0)


if __name__ == "__main__":
    unittest.main()
