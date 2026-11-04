"""HIFLD hospital profile and its effect on the spawn map (offline)."""
import unittest

from knoxbuild import hospitals, population


class Profile(unittest.TestCase):
    def test_profile_from_tags(self):
        prof = hospitals.profile({"healthcare": "hospital", "hifld_beds": "200",
                                  "hifld_staff": "500",
                                  "hifld_type": "PSYCHIATRIC",
                                  "hifld_status": "CLOSED", "helipad": "yes"})
        self.assertEqual(prof["beds"], 200)
        self.assertEqual(prof["mix"], "psychiatric")
        self.assertTrue(prof["closed"])
        self.assertTrue(prof["helipad"])
        self.assertGreater(prof["occupancy"], 1.0)

    def test_not_a_hospital_is_none(self):
        self.assertIsNone(hospitals.profile({"building": "house"}))

    def test_unknown_type_falls_back(self):
        prof = hospitals.profile({"amenity": "hospital", "hifld_type": "WEIRD"})
        self.assertEqual(prof["mix"], "generalacute")


class Occupancy(unittest.TestCase):
    def test_scaled_medical(self):
        base = population.occupants("medical", 100, 2, 1.0, 50)
        big = population.occupants("medical:3.0", 100, 2, 1.0, 50)
        self.assertAlmostEqual(big[1], base[1] * 3.0, places=3)

    def test_closed_reduces(self):
        base = population.occupants("medical", 100, 2, 1.0, 50)
        closed = population.occupants("medical:closed", 100, 2, 1.0, 50)
        self.assertLess(closed[1], base[1])

    def test_other_kinds_untouched(self):
        self.assertEqual(population.occupants("shop", 100, 2, 1.0, 50),
                         population.occupants("shop", 100, 2, 1.0, 50))


if __name__ == "__main__":
    unittest.main()
