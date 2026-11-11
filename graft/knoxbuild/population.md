# knoxbuild/population.py

- _ground_shares · function · L79-L101 — def _ground_shares(path: str, gw: int, gh: int) -> tuple[np.ndarray, np.ndarray]
- occupants · function · L104-L112 — def occupants(kind: str, tiles: int, levels: int, metres_per_tile: float, m2_per_person: float) -> tuple[float, float]
- _soften · function · L115-L122 — def _soften(grid: np.ndarray) -> np.ndarray
- build_spawn_map · function · L125-L205 — def build_spawn_map(buildings: list[tuple[int, int, np.ndarray, int, str]], map_w: int, map_h: int, metres_per_tile: float, landscape_path: str | None, settings, zoning=None) -> tuple[Image.Image, dict]
- save_footprints · function · L208-L221 — def save_footprints(path: str, buildings: list[tuple[int, int, np.ndarray, int, str]]) -> None
- load_footprints · function · L224-L234 — def load_footprints(path: str) -> list[tuple[int, int, np.ndarray, int, str]]
- recount · function · L237-L257 — def recount(out_dir: str, settings) -> dict
- official_population · function · L260-L270 — def official_population(out_dir: str, map_name: str) -> list[dict]
