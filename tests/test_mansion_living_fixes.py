import random
import unittest
from unittest import mock

from knoxbuild import catalog, layout


class MansionLivingFixes(unittest.TestCase):
    def test_small_living_rooms_pair_tv_with_sofa(self):
        for width, height in ((3, 3), (3, 4), (4, 4), (5, 4), (6, 5)):
            with self.subTest(size=(width, height)):
                room = layout.Room(0, 0, width - 1, height - 1, kind='livingroom')
                plan = layout.Plan(width, height, rooms=[room],
                                   grid=[[1] * width for _ in range(height)], kind='house')
                self.assertTrue(layout._furnish_living(plan, 1, room, set(), set(), {}))
                tv = next(item for item in plan.furniture if item[0] == 'tv')
                sofa = next(item for item in plan.furniture if item[0] == 'sofa')
                self.assertEqual(sofa[3], layout._OPPOSITE_SIDE[tv[3]])
                dx, dy = layout._STEP[tv[3]]
                self.assertTrue(any((sx - tv[1]) * -dy == (sy - tv[2]) * -dx
                                    and (sx - tv[1]) * dx + (sy - tv[2]) * dy < 0
                                    for sx, sy in layout._cells_for(*sofa)))

    def test_full_arrangement_is_tried_before_pair_only_fallback(self):
        room = layout.Room(0, 0, 6, 6, kind='livingroom')
        plan = layout.Plan(7, 7, rooms=[room], grid=[[1] * 7 for _ in range(7)],
                           kind='house')
        real_fits = layout._living_fits
        pair_seen = False

        def blocked_first_table(plan, idx, parts, cells, taken, gap, keeps_open):
            nonlocal pair_seen
            if len(parts) == 2:
                pair_seen = True
            elif not pair_seen:
                return False
            return real_fits(plan, idx, parts, cells, taken, gap, keeps_open)

        with mock.patch.object(layout, '_living_fits', side_effect=blocked_first_table):
            self.assertTrue(layout._furnish_living(plan, 1, room, set(), set(), {}))
        self.assertTrue(pair_seen)
        self.assertIn('coffee_table', [role for role, *_ in plan.furniture])

    def test_generated_houses_and_basements_keep_tv_facing_seating(self):
        checked = 0
        for kind in ('house', 'basement_house_rec'):
            for seed in range(10):
                plan = layout.build_plan(12, 10, kind=kind, seed=seed)
                for room_id, room in enumerate(plan.rooms, 1):
                    if room.kind != 'livingroom':
                        continue
                    items = [f for f in plan.furniture
                             if layout._room_at(plan, f[1], f[2]) == room_id]
                    for tv in (f for f in items if f[0] == 'tv'):
                        checked += 1
                        dx, dy = layout._STEP[tv[3]]
                        self.assertTrue(any(
                            role.startswith('sofa') and orient == layout._OPPOSITE_SIDE[tv[3]]
                            and any((sx - tv[1]) * dy == (sy - tv[2]) * dx
                                    and (sx - tv[1]) * dx + (sy - tv[2]) * dy < 0
                                    for sx, sy in layout._cells_for(role, x, y, orient))
                            for role, x, y, orient in items), (kind, seed, items))
        self.assertGreater(checked, 0)


if __name__ == '__main__':
    unittest.main()
