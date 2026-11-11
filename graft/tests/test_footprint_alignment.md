# tests/test_footprint_alignment.py

- BuildingAlignment · class · L11-L117 — class BuildingAlignment(unittest.TestCase)
- setUp · method · L12-L16 — def setUp(self)
- place · method · L18-L22 — def place(self, alignment)
- test_rectilinear_keeps_l_outline_and_removes_diagonal_steps · method · L24-L32 — def test_rectilinear_keeps_l_outline_and_removes_diagonal_steps(self)
- test_rectangle_fills_the_rotated_bounds · method · L34-L38 — def test_rectangle_fills_the_rotated_bounds(self)
- test_smart_rectifies_near_grid_l_but_keeps_strong_diagonal · method · L40-L54 — def test_smart_rectifies_near_grid_l_but_keeps_strong_diagonal(self)
- test_entrance_point_follows_rectilinearized_outline · method · L56-L61 — def test_entrance_point_follows_rectilinearized_outline(self)
- test_rectilinear_simplification_removes_small_jogs · method · L63-L68 — def test_rectilinear_simplification_removes_small_jogs(self)
- test_road_avoidance_moves_building_completely_clear · method · L70-L79 — def test_road_avoidance_moves_building_completely_clear(self)
- test_building_still_stands_where_nothing_is_clear_of_the_road · method · L81-L94 — def test_building_still_stands_where_nothing_is_clear_of_the_road(self): # A spot off the road is taken when there is one (the test above), but # where there is none the building stands on the least road it can # rather than being dropped. Dropping it emptied the towns: a footprint # that fronts a pavement cannot reach zero, and in a town most of them # do - the selftest's school, shop and medical building all came out # "0 laid out".
- test_legacy_angle_settings_migrate · method · L96-L107 — def test_legacy_angle_settings_migrate(self)
- test_settings_api_exposes_alignment_choices · method · L109-L117 — def test_settings_api_exposes_alignment_choices(self)
