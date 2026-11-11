# tests/test_room_furniture_layouts.py

- RoomFurnitureLayouts · class · L9-L181 — class RoomFurnitureLayouts(unittest.TestCase)
- setUp · method · L10-L16 — def setUp(self): # The game's own art only, whatever is installed on the machine running # the tests: with Erika's Tiles present a bathroom mirror is swapped for # one of the mod's prints, so these pass on a bare PC and fail on a # player's.
- tearDown · method · L18-L20 — def tearDown(self)
- test_bathroom_fixture_plan_does_not_mix_bath_and_shower · method · L22-L38 — def test_bathroom_fixture_plan_does_not_mix_bath_and_shower(self): # A bathroom the size this generator cuts gets a bath; one smaller than # it ever cuts for a house - a flat's or a motel's - gets the shower. # Either way, never both: the room is 6.5 m2.
- test_public_bathroom_fixtures_scale_with_room_area · method · L40-L44 — def test_public_bathroom_fixtures_scale_with_room_area(self)
- test_multitile_furniture_anchors_inside_east_and_south_walls · method · L46-L54 — def test_multitile_furniture_anchors_inside_east_and_south_walls(self)
- test_bathroom_fixtures_use_shared_plumbing_wall · method · L56-L78 — def test_bathroom_fixtures_use_shared_plumbing_wall(self)
- test_bath_mat_is_next_to_the_tub · method · L80-L94 — def test_bath_mat_is_next_to_the_tub(self)
- test_open_plan_merges_only_full_aligned_living_and_kitchen_rooms · method · L96-L108 — def test_open_plan_merges_only_full_aligned_living_and_kitchen_rooms(self)
- test_home_profile_varies_open_plan_dining_and_study_chances · method · L110-L123 — def test_home_profile_varies_open_plan_dining_and_study_chances(self)
- test_modern_home_can_be_open_plan_without_making_old_homes_uniform · method · L125-L138 — def test_modern_home_can_be_open_plan_without_making_old_homes_uniform(self)
- test_extra_hall_bridges_unserved_room_clusters · method · L140-L157 — def test_extra_hall_bridges_unserved_room_clusters(self)
- test_tied_hall_candidates_extend_existing_circulation · method · L159-L168 — def test_tied_hall_candidates_extend_existing_circulation(self)
- test_corridor_does_not_replace_a_stations_only_police_office · method · L170-L181 — def test_corridor_does_not_replace_a_stations_only_police_office(self)
