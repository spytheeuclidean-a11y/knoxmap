import unittest
from collections import Counter
from xml.etree import ElementTree

from knoxbuild import layout, tbx
from knoxbuild.uses import use_of


class MallShopVariety(unittest.TestCase):
    def test_farm_shop_tag_uses_the_games_garden_store(self):
        self.assertEqual(use_of({"shop": "farm"}), ("gardenstore", "storage"))

    def test_mall_can_fit_requested_and_additional_store_types(self):
        kinds = {"gardenstore", "gunstore", "jewelrystore", "armysurplus",
                 "hunting", "artstore", "petstore", "camerastore"}
        uses = [(kind, "storage") for kind in sorted(kinds)]
        building = layout.build_building(160, 90, kind="mall", commercial=True,
                                         uses=uses, seed=4)
        plan = building.storeys[0]
        found = {room.kind for room in plan.rooms}
        self.assertTrue(kinds <= found, kinds - found)
        for kind in kinds:
            rooms = {i for i, room in enumerate(plan.rooms, 1) if room.kind == kind}
            self.assertTrue(any(plan.grid[y][x] in rooms and role not in {"switch", "light"}
                                for role, x, y, _ in plan.furniture), kind)
            self.assertTrue(any(plan.grid[y][x] in rooms or
                                (x > 0 and plan.grid[y][x - 1] in rooms) or
                                (y > 0 and plan.grid[y - 1][x] in rooms)
                                for x, y, _ in plan.open_edge), kind)
        room_names = {room.get("InternalName") for room in
                      ElementTree.fromstring(tbx.render_tbx(building, "mall")).findall("room")}
        self.assertTrue(kinds <= room_names, kinds - room_names)

    def test_gun_and_jewelry_stores_are_more_frequent(self):
        counts = Counter()
        for seed in range(3):
            plan = layout.build_building(160, 90, kind="mall", commercial=True,
                                         seed=seed).storeys[0]
            counts.update(room.kind for room in plan.rooms)
        self.assertGreaterEqual(counts["gunstore"], 5)
        self.assertGreaterEqual(counts["jewelrystore"], 5)


if __name__ == "__main__":
    unittest.main()
