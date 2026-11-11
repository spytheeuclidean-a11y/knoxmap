# tests/test_blends.py

- blend · function · L21-L31 — def blend(layer, tile, d, exclude="")
- run · function · L42-L57 — def run(picture, text=ALL, seam=None, x0=0, y0=0)
- BlendTests · class · L60-L110 — class BlendTests(unittest.TestCase)
- test_parse · method · L61-L64 — def test_parse(self)
- test_cardinal_neighbour · method · L66-L68 — def test_cardinal_neighbour(self)
- test_two_opposite_neighbours · method · L70-L71 — def test_two_opposite_neighbours(self)
- test_corner_replaces_the_two_cardinals · method · L73-L77 — def test_corner_replaces_the_two_cardinals(self)
- test_a_lone_diagonal_gives_nothing · method · L79-L80 — def test_a_lone_diagonal_gives_nothing(self)
- test_main_ground_and_empty_squares_get_nothing · method · L82-L84 — def test_main_ground_and_empty_squares_get_nothing(self)
- test_excluded_ground_gets_nothing · method · L86-L90 — def test_excluded_ground_gets_nothing(self)
- test_later_rule_wins_a_shared_layer · method · L92-L94 — def test_later_rule_wins_a_shared_layer(self)
- test_seams · method · L96-L100 — def test_seams(self)
- test_a_cut_out_window_blends_the_same_inside · method · L102-L110 — def test_a_cut_out_window_blends_the_same_inside(self): # the picks follow the position, and a margin of one square gives the same neighbours
