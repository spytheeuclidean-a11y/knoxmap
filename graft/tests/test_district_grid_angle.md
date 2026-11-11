# tests/test_district_grid_angle.py

- ll · function · L29-L37 — def ll(x_m: float, y_m: float, deg: float = 0.0) -> tuple[float, float]
- seg · function · L40-L43 — def seg(x0: float, y0: float, x1: float, y1: float, deg: float = 0.0) -> OSMFeature
- grid · function · L46-L59 — def grid(deg: float, spacing: int = 80, half: int = 280) -> list[OSMFeature]
- district_a · function · L62-L78 — def district_a() -> list[OSMFeature]
- district_b · function · L81-L94 — def district_b() -> list[OSMFeature]
- Uniform · class · L97-L108 — class Uniform(unittest.TestCase)
- test_finds_the_single_grid · method · L98-L102 — def test_finds_the_single_grid(self)
- test_flat_grid_reads_zero · method · L104-L108 — def test_flat_grid_reads_zero(self)
- TwoDistricts · class · L111-L125 — class TwoDistricts(unittest.TestCase)
- test_dominant_district_wins_not_the_average · method · L112-L118 — def test_dominant_district_wins_not_the_average(self): # Averaging the two phases lands near -6.5 degrees - straightens # neither grid. The larger district's own angle must win instead.
- test_smaller_phase_alone_still_found · method · L120-L125 — def test_smaller_phase_alone_still_found(self): # The losing district is measured correctly when it is all there is.
