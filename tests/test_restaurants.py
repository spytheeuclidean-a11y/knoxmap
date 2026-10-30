import unittest
from unittest import mock

from knoxbuild import layout

COUNTERS = ("diner_counter", "pizza_counter", "counter_2")
SEATING = ("diner_table", "pizza_table", "dining_table")
HOME_PIECES = ("sidetable", "dresser", "dresser_alt", "wardrobe", "lamp")


def dining_rooms(uses, seeds=range(20)):
    for seed in seeds:
        plan = layout.build_building(
            width=26, height=12, kind="restaurant", seed=seed, levels=1,
            street="S", uses=uses).storeys[0]
        for idx, room in enumerate(plan.rooms, 1):
            if room.kind == "restaurantdining":
                yield plan, idx, [f[0] for f in plan.furniture
                                  if plan.grid[f[2]][f[1]] == idx]


class RestaurantsAreFull(unittest.TestCase):
    def test_a_dining_room_holds_many_booths(self):
        # 6 sets a room before the sets were packed with a shared aisle.
        for kitchen in ("dinerkitchen", "pizzakitchen"):
            rooms = list(dining_rooms([("restaurantdining", kitchen)]))
            sets = sum(sum(r.count(s) for s in SEATING) for _p, _i, r in rooms)
            with self.subTest(kitchen=kitchen):
                self.assertGreaterEqual(sets / len(rooms), 10)

    def test_most_have_a_counter_at_the_back(self):
        rooms = list(dining_rooms([("restaurantdining", "dinerkitchen")]))
        with_counter = sum(any(c in r for c in COUNTERS) for _p, _i, r in rooms)
        self.assertGreaterEqual(with_counter / len(rooms), 0.5)

    def test_no_bedroom_furniture_in_a_dining_room(self):
        for _p, _i, roles in dining_rooms([("restaurantdining", "dinerkitchen")]):
            self.assertFalse([r for r in roles if r in HOME_PIECES], roles)


    def test_no_chest_under_a_plant_with_erikas_tiles(self):
        # Erika's plants are tabletop pieces, so each stood on a chest of
        # drawers; a dining room's plants stand on the floor.
        with mock.patch.object(layout, "_erika_ready", lambda: True):
            for _p, _i, roles in dining_rooms([("restaurantdining", "dinerkitchen")],
                                              range(8)):
                self.assertFalse([r for r in roles if r in HOME_PIECES], roles)


if __name__ == "__main__":
    unittest.main()
