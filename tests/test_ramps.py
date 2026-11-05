"""A ramp must land on the deck it climbs to, not stop short in mid-air."""
import unittest

from generator.structures import DECK_FLOOR, Plan, _cap_tops


class _Proj:
    width = 80
    height = 40


class CapTops(unittest.TestCase):
    def test_a_stranded_top_gets_the_deck_it_climbs_to(self):
        plan, deck = Plan(), {1: set()}
        _cap_tops(plan, [(10, 10, 0, "E")], deck, _Proj())
        self.assertEqual(plan.tiles[(11, 10, 1, "Floor")], DECK_FLOOR)
        self.assertIn((11, 10), deck[1])

    def test_a_top_that_already_meets_its_deck_is_left_alone(self):
        plan, deck = Plan(), {1: {(11, 10)}}
        _cap_tops(plan, [(10, 10, 0, "E")], deck, _Proj())
        self.assertEqual(plan.tiles, {})

    def test_a_top_at_the_map_edge_caps_in_place(self):
        plan, deck = Plan(), {1: set()}
        _cap_tops(plan, [(79, 10, 0, "E")], deck, _Proj())
        self.assertEqual(plan.tiles[(79, 10, 1, "Floor")], DECK_FLOOR)


if __name__ == "__main__":
    unittest.main()
