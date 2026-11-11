# tests/test_split_large_buildings.py

- placed · function · L29-L30 — def placed(max_side: float)
- Gate · class · L33-L44 — class Gate(unittest.TestCase)
- test_the_gate_still_refuses_on_the_real_side · method · L34-L37 — def test_the_gate_still_refuses_on_the_real_side(self)
- test_the_retry_places_it_whole · method · L39-L44 — def test_the_retry_places_it_whole(self): # What build.py does when place answers "large": try again without # the one gate that fired. place claimed nothing before refusing.
- Split · class · L47-L82 — class Split(unittest.TestCase)
- test_cut_units_fit_inside_the_cap · method · L48-L59 — def test_cut_units_fit_inside_the_cap(self)
- test_the_cuts_keep_every_tile · method · L61-L65 — def test_the_cuts_keep_every_tile(self)
- test_without_the_cap_the_area_rule_is_unchanged · method · L67-L70 — def test_without_the_cap_the_area_rule_is_unchanged(self)
- test_a_building_that_already_fits_is_cut_exactly_as_before · method · L72-L82 — def test_a_building_that_already_fits_is_cut_exactly_as_before(self)
