# tests/test_design.py

- cells · function · L16-L17 — def cells(metres: float) -> int
- sheet · function · L20-L23 — def sheet(width=900, height=900, lat=0.0, lon=0.0, features=None)
- SheetSize · class · L26-L68 — class SheetSize(unittest.TestCase)
- test_a_sheet_is_the_size_it_says · method · L27-L35 — def test_a_sheet_is_the_size_it_says(self)
- test_it_never_measures_over_and_so_never_costs_a_whole_cell · method · L37-L47 — def test_it_never_measures_over_and_so_never_costs_a_whole_cell(self): # The one that matters: at or just over a 300 m boundary.
- test_a_silly_size_is_brought_into_range · method · L49-L55 — def test_a_silly_size_is_brought_into_range(self)
- test_a_sheet_with_no_corner_still_lands_somewhere · method · L57-L62 — def test_a_sheet_with_no_corner_still_lands_somewhere(self)
- test_a_corner_off_the_world_is_not_used · method · L64-L68 — def test_a_corner_off_the_world_is_not_used(self)
- WhatIsOnIt · class · L71-L117 — class WhatIsOnIt(unittest.TestCase)
- test_metres_from_the_corner_land_in_the_right_corner · method · L72-L81 — def test_metres_from_the_corner_land_in_the_right_corner(self): # (0, 0) is the bottom left of the sheet and (w, h) the top right.
- test_an_area_comes_out_closed · method · L83-L87 — def test_an_area_comes_out_closed(self)
- test_the_palette_decides_the_shape · method · L89-L95 — def test_the_palette_decides_the_shape(self)
- test_what_cannot_be_drawn_is_left_out · method · L97-L104 — def test_what_cannot_be_drawn_is_left_out(self)
- test_a_sheet_becomes_features_the_generator_knows · method · L106-L113 — def test_a_sheet_becomes_features_the_generator_knows(self)
- test_nothing_drawn_is_nothing_built · method · L115-L117 — def test_nothing_drawn_is_nothing_built(self)
