# tests/test_mapped_rooms.py

- rooms_property · function · L37-L39 — def rooms_property(indoor=(CLASSROOM, STRAY))
- Attach · class · L42-L56 — class Attach(unittest.TestCase)
- test_a_room_lands_on_its_building_with_its_tags · method · L43-L47 — def test_a_room_lands_on_its_building_with_its_tags(self)
- test_a_room_in_no_building_is_dropped · method · L49-L52 — def test_a_room_in_no_building_is_dropped(self): # Only the classroom is inside the school; the stray is not attached # to anything and never reaches the build.
- test_buildings_without_rooms_have_no_property · method · L54-L56 — def test_buildings_without_rooms_have_no_property(self)
- room_covering · function · L66-L73 — def room_covering(plan, x, y)
- Cut · class · L76-L121 — class Cut(unittest.TestCase)
- test_the_mapped_rooms_are_cut_as_drawn_with_their_kind · method · L77-L89 — def test_the_mapped_rooms_are_cut_as_drawn_with_their_kind(self)
- test_the_rest_of_the_floor_is_still_cut_and_tiled · method · L91-L95 — def test_the_rest_of_the_floor_is_still_cut_and_tiled(self)
- test_untagged_rooms_are_still_placed · method · L97-L106 — def test_untagged_rooms_are_still_placed(self): # A room the game has no name for keeps its walls; the usual rules # furnish it afterwards.
- test_upper_floors_are_laid_out_as_ever · method · L108-L116 — def test_upper_floors_are_laid_out_as_ever(self): # The mapper drew one floor; an upper storey is the ordinary plan.
- test_a_building_without_mapped_rooms_is_cut_as_ever · method · L118-L121 — def test_a_building_without_mapped_rooms_is_cut_as_ever(self)
