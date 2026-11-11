# knoxbuild/props.py

- lattice_on_map · function · L73-L83 — def lattice_on_map(first: int, stop: int, step: int, limit: int) -> range
- _blocked_mask · function · L86-L90 — def _blocked_mask(ground: np.ndarray) -> np.ndarray
- _polygons · function · L93-L96 — def _polygons(areas, category: str) -> list
- place_props · function · L99-L249 — def place_props(out_dir: str, map_name: str, bdir: str, occupied: np.ndarray, areas, metres_per_tile: float, seed: int = 0x6FADE) -> tuple[list, dict]
- put · function · L131-L139 — def put(x: int, y: int, tile: str) -> bool
- step · function · L141-L142 — def step(metres: float) -> int
