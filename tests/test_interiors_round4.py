import random
import unittest

from knoxbuild import interiors, layout
from knoxbuild.audit import audit


def _single_room_plan(w: int, h: int, room_kind: str, *,
                      plan_kind: str | None = None,
                      door: tuple[int, int, str] | None = None,
                      is_core: bool = False,
                      garage_door_tiles: set[tuple[int, int, str]] | None = None) -> layout.Plan:
    room = layout.Room(0, 0, w - 1, h - 1, kind=room_kind, is_core=is_core)
    grid = [[1] * w for _ in range(h)]
    if door is None:
        door = (w // 2, 0, "N")
    plan = layout.Plan(
        w, h,
        rooms=[room],
        grid=grid,
        doors=[door],
        kind=plan_kind or room_kind,
    )
    if garage_door_tiles:
        plan.garage_door_tiles = set(garage_door_tiles)
    return plan


def _roles(plan: layout.Plan) -> set[str]:
    return {role for role, *_ in plan.furniture}


class Round4CivicAndServiceLayouts(unittest.TestCase):
    def setUp(self):
        self._erika = list(layout._ERIKA_ALLOWED)
        layout.use_mod_tiles(False)

    def tearDown(self):
        layout._ERIKA_ALLOWED[:] = self._erika
        layout._ERIKA.clear()

    def test_library_has_circulation_desk_reading_and_stacks(self):
        plan = _single_room_plan(12, 12, "library", door=(5, 0, "N"))
        layout._furnish(plan, random.Random(7), street="N")
        roles = _roles(plan)
        self.assertTrue(roles & {"shop_counter", "counter", "counter_2"})
        self.assertIn("register", roles)
        self.assertIn("bookshelf", roles)
        self.assertIn("office_chair", roles)

    def test_theatre_has_seating_rows_and_screen_or_stage(self):
        plan = _single_room_plan(12, 14, "theatre", plan_kind="shop", door=(5, 0, "N"))
        layout._furnish(plan, random.Random(11), street="N")
        roles = _roles(plan)
        chairs = [f for f in plan.furniture if f[0] in ("chair", "armchair")]
        self.assertGreaterEqual(len(chairs), 6)
        self.assertTrue(roles & {"television", "shop_counter", "counter", "display", "vending", "bin"})

    def test_clinic_aliases_have_reception_waiting_and_medical_gear(self):
        for kind in ("clinic", "medical", "medicaloffice", "dentist"):
            with self.subTest(kind=kind):
                plan = _single_room_plan(10, 10, kind, plan_kind="medical", door=(4, 0, "N"))
                layout._furnish(plan, random.Random(13), street="N")
                roles = _roles(plan)
                self.assertTrue(roles & {"counter_2", "shop_counter", "counter", "desk"})
                self.assertTrue(roles & {"bed_plain", "exam_table", "cabinet_med", "dresser_med", "filing_cabinet"})
                self.assertTrue(roles & {"chair", "armchair", "office_chair", "sofa"})

    def test_bank_and_post_have_teller_line_and_security_or_counters(self):
        for kind in ("bank", "post"):
            with self.subTest(kind=kind):
                plan = _single_room_plan(10, 10, kind, plan_kind="shop", door=(4, 0, "N"))
                layout._furnish(plan, random.Random(17), street="N")
                roles = _roles(plan)
                self.assertTrue(roles & {"shop_counter", "counter", "counter_2"})
                self.assertIn("register", roles)
                self.assertTrue(roles & {"safe", "filing_cabinet", "desk_dark", "desk", "metal_rack"})

    def test_police_and_security_have_duty_desks_and_lockers(self):
        for kind in ("policeoffice", "policehall", "security"):
            with self.subTest(kind=kind):
                plan = _single_room_plan(10, 10, kind, plan_kind="police", door=(4, 0, "N"))
                layout._furnish(plan, random.Random(19), street="N")
                roles = _roles(plan)
                self.assertTrue(roles & {"office_chair", "chair"})
                self.assertTrue(roles & {"gun_locker", "wardrobe", "filing_cabinet"})
                self.assertTrue(roles & {"desk", "desk_dark", "shop_counter", "counter"})

    def test_daycare_has_play_tables_shelves_and_es_cribs(self):
        plan = _single_room_plan(10, 10, "daycare", plan_kind="shop", door=(4, 0, "N"))
        layout._furnish(plan, random.Random(23), street="N")
        roles = _roles(plan)
        self.assertTrue(roles & {"bookshelf", "shelf_2"})
        self.assertTrue(roles & {"round_table", "table", "table_small", "shop_counter", "counter"})
        cribs = [f for f in plan.furniture if f[0] == "crib"]
        self.assertGreaterEqual(len(cribs), 1)
        for _role, _x, _y, orient in cribs:
            self.assertIn(orient, ("E", "S"))


class Round4ZoningBaysCoresAndDressing(unittest.TestCase):
    def setUp(self):
        self._erika = list(layout._ERIKA_ALLOWED)
        layout.use_mod_tiles(False)

    def tearDown(self):
        layout._ERIKA_ALLOWED[:] = self._erika
        layout._ERIKA.clear()

    def test_lobby_has_reception_desk_and_waiting_zone(self):
        plan = _single_room_plan(10, 10, "lobby", plan_kind="offices", door=(4, 0, "N"))
        layout._furnish(plan, random.Random(29), street="N", is_ground=True)
        roles = _roles(plan)
        self.assertTrue(roles & {"shop_counter", "counter", "desk", "desk_dark"})
        self.assertTrue(roles & {"sofa", "armchair", "chair"})

    def test_cafeteria_diningroom_has_service_line_and_tables(self):
        plan = _single_room_plan(12, 10, "diningroom", plan_kind="school", door=(5, 0, "N"))
        layout._furnish(plan, random.Random(31), street="N")
        roles = _roles(plan)
        self.assertTrue(roles & {"hot_counter", "counter_2", "shop_counter", "counter"})
        self.assertTrue(roles & {"dining_table", "table"})
        self.assertIn("chair", roles)

    def test_industrial_floor_keeps_bay_lane_and_wall_clear(self):
        gdoors = {(4, 0, "N"), (5, 0, "N")}
        for kind in ("warehouse", "garage", "firegarage"):
            with self.subTest(kind=kind):
                plan = _single_room_plan(
                    10, 10, kind,
                    plan_kind="industrial" if kind == "warehouse" else "fire",
                    door=(1, 0, "N"),
                    garage_door_tiles=gdoors,
                )
                layout._furnish(plan, random.Random(37), street="N")
                lane = interiors._bay_lane_cells(plan, 1, {(x, y) for x in range(10) for y in range(10)})
                self.assertTrue(lane)
                occupied = {(x, y) for _role, x, y, _o in plan.furniture}
                self.assertEqual(lane & occupied, set())
                self.assertEqual(plan.wall_pieces & gdoors, set())

    def test_ground_core_gets_entry_polish_without_blocking_stairs(self):
        for is_ground in (True, False):
            with self.subTest(is_ground=is_ground):
                plan = _single_room_plan(6, 6, "hall", plan_kind="offices", door=(2, 0, "N"), is_core=True)
                layout._furnish(plan, random.Random(41), stairs=(1, 4, "N"), street="N", is_ground=is_ground)
                roles = _roles(plan)
                if is_ground:
                    self.assertIn("door_mat", roles)
                else:
                    self.assertNotIn("door_mat", roles)
                # Stair cell and landing stay clear.
                occupied = {(x, y) for _role, x, y, _o in plan.furniture}
                self.assertNotIn((1, 4), occupied)
                self.assertNotIn((1, 3), occupied)

    def test_non_residential_dressing_uses_commercial_accents(self):
        plan = _single_room_plan(8, 8, "generalstore", plan_kind="shop", door=(3, 0, "N"))
        layout._furnish(plan, random.Random(43), street="N")
        roles = _roles(plan)
        self.assertTrue(
            roles & {"register", "sale_sign", "coffee_maker", "phone", "mirror_small",
                     "clock", "corkboard", "wall_vent", "bin", "box", "box_battered", "door_mat"}
        )

    def test_full_building_archetypes_audit_clean_and_respect_nw_and_wall_edges(self):
        cases = [
            ("library", 16, 14, 1, False, True, None),
            ("shop", 16, 14, 1, True, False, [("theatre", "storage")]),
            ("shop", 16, 14, 1, True, False, [("bank", "office")]),
            ("shop", 16, 14, 1, True, False, [("daycare", "storage")]),
            ("medical", 18, 16, 2, True, False, None),
            ("police", 18, 16, 2, True, False, None),
            ("industrial", 20, 16, 1, True, False, None),
            ("school", 22, 18, 2, True, False, None),
            ("offices", 16, 16, 2, True, False, None),
        ]
        for kind, w, h, levels, commercial, retail, uses in cases:
            with self.subTest(kind=kind, uses=uses):
                b = layout.build_building(
                    w, h, levels=levels, commercial=commercial, seed=42,
                    kind=kind, street="S", retail=retail, uses=uses,
                    garage_door=(kind == "industrial"),
                )
                problems = {
                    msg: n for msg, n in audit(b, kind).items()
                    if not msg.startswith("stat:") and n
                }
                self.assertEqual(problems, {})
                for lvl, floor in enumerate(b.storeys):
                    openings = (
                        set(floor.doors)
                        | set(floor.windows)
                        | set(floor.open_edge)
                        | set(getattr(floor, "garage_door_tiles", ()))
                    )
                    self.assertEqual(
                        floor.wall_pieces & openings, set(),
                        f"{kind} L{lvl} wall_pieces overlapped openings: {floor.wall_pieces & openings}",
                    )
                    for role, x, y, orient in floor.furniture:
                        if role in layout.NORTH_WEST_ONLY:
                            self.assertIn(
                                orient, ("N", "W"),
                                f"{kind} L{lvl} NORTH_WEST_ONLY {role}@{x},{y} has orient={orient}",
                            )
