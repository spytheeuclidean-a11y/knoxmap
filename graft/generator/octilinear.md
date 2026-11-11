# generator/octilinear.py

- _key · function · L43-L44 — def _key(lat: float, lon: float) -> tuple[int, int]
- _simplify_idx · function · L47-L64 — def _simplify_idx(pts: list[tuple[float, float]], tol: float) -> list[int]
- _dist_to_line · function · L67-L73 — def _dist_to_line(p, a, b) -> float
- _legs · function · L76-L85 — def _legs(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]
- _tidy · function · L88-L101 — def _tidy(path: list[tuple[int, int]]) -> list[tuple[int, int]]
- _solve · function · L104-L134 — def _solve(p0: np.ndarray, segs: np.ndarray, normals: np.ndarray, weights: np.ndarray, iterations: int = 400, hold: float | None = None) -> np.ndarray
- apply · function · L112-L117 — def apply(x)
- _blur · function · L137-L147 — def _blur(a: np.ndarray, radius: int) -> np.ndarray
- _round_together · function · L150-L207 — def _round_together(moved: np.ndarray, segs: np.ndarray, normals: np.ndarray) -> list
- find · function · L158-L163 — def find(kind, a)
- shared · function · L178-L184 — def shared(kind, values)
- straighten_roads · function · L210-L329 — def straighten_roads(features: list, proj, classify, is_polygon) -> int
- vertex · function · L230-L236 — def vertex(xy, key=None)
- move · function · L312-L316 — def move(lat, lon)
