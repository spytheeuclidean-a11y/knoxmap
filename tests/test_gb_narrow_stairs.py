"""A British terraced house four or five tiles wide keeps its upper floor: its
stairs run against the party wall with a one-tile hall beside them
(knoxbuild/layout/furnishing.py NARROW_CORE_WIDE). Anfield had 2,396 such
houses built as bungalows."""
import unittest
from dataclasses import replace

from knoxbuild.layout.assemble import build_building
from knoxbuild.profile import BuildingProfile

BASE = BuildingProfile.infer({}, None, 0.3, 50.0, 2, 1)
GB = replace(BASE, narrow_stairs=True)


def houses(width, height, profile):
    return [build_building(width, height, levels=2, seed=seed, street="S", profile=profile)
            for seed in range(12)]


def kinds(b):
    return {r.kind for st in b.storeys for r in st.rooms}


class NarrowStairs(unittest.TestCase):
    def test_a_british_house_five_wide_has_two_storeys_and_a_whole_home(self):
        for height in (8, 10, 12):
            for b in houses(5, height, GB):
                self.assertEqual(len(b.storeys), 2)
                self.assertIn("bathroom", kinds(b))
                self.assertTrue({"kitchen", "livingroom"} <= kinds(b) or "openplan" in kinds(b),
                                kinds(b))
                self.assertTrue(kinds(b) & {"bedroom", "kidsbedroom"}, kinds(b))

    def test_four_wide_has_two_storeys_a_living_room_and_a_bedroom(self):
        # Too shallow for a bathroom as well, short ones go without, as many
        # did with the toilet out the back.
        for height in (9, 11, 12, 14):
            for b in houses(4, height, GB):
                self.assertEqual(len(b.storeys), 2)
                self.assertTrue({"kitchen", "livingroom"} <= kinds(b) or "openplan" in kinds(b),
                                kinds(b))
                self.assertTrue(kinds(b) & {"bedroom", "kidsbedroom"}, kinds(b))

    def test_elsewhere_nothing_changes(self):
        for width in (4, 5):
            for b in houses(width, 10, BASE) + houses(width, 10, None):
                self.assertEqual(len(b.storeys), 1)

    def test_wider_british_houses_are_built_as_before(self):
        for gb, base in zip(houses(7, 10, GB), houses(7, 10, BASE)):
            self.assertEqual([[r.kind for r in st.rooms] for st in gb.storeys],
                             [[r.kind for r in st.rooms] for st in base.storeys])


if __name__ == "__main__":
    unittest.main()
