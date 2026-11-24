import random
import unittest

from knoxbuild import catalog as C
from knoxbuild import personas as P

WHO = {"household": "family", "plan_kind": "house", "wealth": 0.6, "wear": 0.3,
       "setting": "suburban", "age": 20}


class Personas(unittest.TestCase):
    def test_every_role_a_persona_asks_for_exists(self):
        for name, spec in P.PERSONAS.items():
            parts = list(spec.get("rooms", {}).values()) + [spec.get("spare", {})]
            for part in parts:
                for role, chance in part.get("add", ()):
                    self.assertIn(role, C.FURNITURE, (name, role))
                    self.assertTrue(0 < chance <= 1, (name, role))
                for role in list(part.get("swap", {}).values()):
                    self.assertIn(role, C.FURNITURE, (name, role))

    def test_no_persona_puts_warehouse_racking_in_a_home(self):
        industrial = {"metal_rack", "crate", "shop_shelf", "shop_aisle"}
        for name, spec in P.PERSONAS.items():
            parts = list(spec.get("rooms", {}).values()) + [spec.get("spare", {})]
            for part in parts:
                asked = {r for r, _c in part.get("add", ())} | set(part.get("swap", {}).values())
                self.assertFalse(asked & industrial, (name, asked & industrial))

    def test_a_pick_is_the_same_each_time_and_varies_between_homes(self):
        again = [P.pick(random.Random(i), WHO) for i in range(50)]
        self.assertEqual(again, [P.pick(random.Random(i), WHO) for i in range(50)])
        self.assertGreater(len(set(again)), 8)

    def test_a_persona_can_only_be_a_home_that_could_be_it(self):
        retired = dict(WHO, household="retired", plan_kind="apartment")
        picked = {P.pick(random.Random(i), retired) for i in range(400)}
        self.assertNotIn("students", picked)         # adults only
        self.assertNotIn("big_family", picked)       # families only
        self.assertIn("widow", picked)

    def test_apply_adds_drops_and_swaps_and_leaves_other_rooms(self):
        rng = random.Random(1)
        got = P.apply(["sofa", "plant", "painting"], "livingroom", "pianist_elder", rng)
        self.assertEqual(got[:3], ["sofa", "plant", "painting"])
        self.assertEqual(P.apply(["bed"], "bathroom", "pianist_elder", rng), ["bed"])
        self.assertEqual(P.apply(["a"], "livingroom", None, rng), ["a"])
        mini = P.apply(["sofa", "plant", "painting"], "livingroom", "minimalist", rng)
        self.assertEqual(mini, ["sofa"])
        stud = P.apply(["double_bed"], "bedroom", "students", random.Random(2))
        self.assertEqual(stud[0], "bed_plain")

    def test_a_spare_room_takes_the_spare_list(self):
        got = P.apply([], "office", "runner", random.Random(0))
        self.assertTrue(set(got) <= {"treadmill", "mirror", "plant"})
        self.assertEqual(P.apply([], "bathroom", "runner", random.Random(0)), [])


if __name__ == "__main__":
    unittest.main()
