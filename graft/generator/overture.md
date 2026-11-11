# generator/overture.py

- available · function · L67-L73 — def available() -> bool
- why_unavailable · function · L76-L82 — def why_unavailable() -> str
- release · function · L85-L86 — def release() -> str
- cache_path · function · L89-L90 — def cache_path(output_dir: str, map_name: str) -> str
- save_cache · function · L93-L98 — def save_cache(path: str, bbox: tuple[float, float, float, float], rows: list[dict]) -> None
- load_cache · function · L101-L118 — def load_cache(path: str, bbox: tuple[float, float, float, float]) -> list[dict] | None
- _query · function · L121-L131 — def _query(south: float, west: float, north: float, east: float) -> str: # Overlapping, not contained: a building on the edge of the box is half # inside the map and has to be built, or the map has a bite out of it.
- fetch · function · L134-L183 — def fetch(south: float, west: float, north: float, east: float, should_stop=None) -> list[dict]
- run · function · L150-L154 — def run() -> None
- _rings · function · L186-L204 — def _rings(shape: dict) -> list[list[tuple[float, float]]]
- _area_m2 · function · L207-L219 — def _area_m2(ring: list[tuple[float, float]]) -> float
- to_features · function · L222-L247 — def to_features(rows: list[dict]) -> list[OSMFeature]
- only_missing · function · L250-L297 — def only_missing(candidates: list[OSMFeature], features: list[OSMFeature]) -> list[OSMFeature]
- add_missing · function · L300-L333 — def add_missing(features: list[OSMFeature], bbox: tuple[float, float, float, float], output_dir: str, map_name: str, should_stop=None) -> tuple[list[OSMFeature], dict]
