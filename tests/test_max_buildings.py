"""A ceiling on how many buildings a map may hold.

A big map paved with houses is a big map nobody wants to cross, and "about
half" - which is all `true_map` off offered - is not a number anybody can ask
for. `max_buildings` is the number itself: the landmarks stay, the housing is
spaced out until the count fits, and what goes is spread over the whole map
(knoxbuild/procedural.cap).
"""
import unittest

from knoxbuild.procedural import cap
from knoxbuild.settings import Settings


def town(across=30, down=30, step=20.0, width=10.0, every_landmark=0):
    """A grid town: (index, x, y, width, landmark) as the build hands them."""
    out = []
    i = 0
    for y in range(down):
        for x in range(across):
            land = bool(every_landmark) and i % every_landmark == 0
            out.append((i, x * step, y * step, width, land))
            i += 1
    return out


class TheNumberAsked(unittest.TestCase):
    def test_exactly_that_many_come_back(self):
        # A spacing rule alone cannot land on an arbitrary number - a street
        # goes from every house to every other one in one step - so the
        # search stops under the ceiling and the room left is filled back in.
        places = town()
        for limit in (1, 7, 50, 123, 400, 899):
            with self.subTest(limit=limit):
                self.assertEqual(len(cap(places, limit)), limit)

    def test_a_ceiling_above_the_town_changes_nothing(self):
        places = town(10, 10)
        self.assertEqual(len(cap(places, 500)), 100)
        self.assertEqual(len(cap(places, 100)), 100)

    def test_no_ceiling_at_all(self):
        places = town(10, 10)
        self.assertEqual(len(cap(places, 0)), 100)

    def test_the_same_map_twice_is_the_same_map(self):
        places = town(12, 12)
        self.assertEqual(cap(places, 40), cap(places, 40))

    def test_what_is_kept_is_spread_over_the_whole_map(self):
        # The point of the setting: a long drive with something at both ends,
        # not a full quarter and three empty ones.
        places = town(40, 40)
        kept = cap(places, 200)
        quarters = {}
        for i, x, y, _w, _l in places:
            if i in kept:
                quarters[(x < 400, y < 400)] = quarters.get((x < 400, y < 400), 0) + 1
        self.assertEqual(len(quarters), 4)
        self.assertGreater(min(quarters.values()), 200 // 4 * 0.6)

    def test_landmarks_are_never_the_ones_dropped(self):
        places = town(30, 30, every_landmark=97)
        landmarks = {i for i, _x, _y, _w, land in places if land}
        kept = cap(places, 120)
        self.assertTrue(landmarks)
        self.assertTrue(landmarks <= kept, "a landmark was dropped")

    def test_more_landmarks_than_the_ceiling_keeps_the_biggest_of_them(self):
        # Not a map of sheds: if the ceiling is below the number of places
        # worth going to, the ones that stay are the big ones.
        places = [(i, i * 20.0, 0.0, 5.0 + i, True) for i in range(20)]
        kept = cap(places, 5)
        self.assertEqual(len(kept), 5)
        self.assertEqual(kept, {15, 16, 17, 18, 19})

    def test_a_ceiling_of_one(self):
        self.assertEqual(len(cap(town(5, 5), 1)), 1)


class TheSetting(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(Settings().max_buildings, 0)

    def test_it_survives_a_round_trip(self):
        kept = Settings.from_dict({**Settings().to_dict(), "max_buildings": 800})
        self.assertEqual(kept.max_buildings, 800)

    def test_a_negative_ceiling_is_no_ceiling(self):
        self.assertEqual(Settings.from_dict({"max_buildings": -5}).max_buildings, 0)

    def test_the_reason_a_capped_building_gives_has_words(self):
        from knoxbuild import why
        for book in (why.WHY, why.FIX, why.SHORT):
            self.assertTrue(book.get("over the limit"))
            self.assertTrue(book.get("thinned"))


if __name__ == "__main__":
    unittest.main()
