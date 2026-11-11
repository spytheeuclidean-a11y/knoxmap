# generator/places.py

- _throttle · function · L43-L50 — def _throttle() -> None
- search · function · L53-L99 — def search(query: str, viewbox: tuple[float, float, float, float] | None = None, bounded: bool = False, limit: int = 8) -> list[dict]
- _outline · function · L102-L110 — def _outline(geojson: dict | None) -> dict | None
- _build_query · function · L124-L132 — def _build_query(south: float, west: float, north: float, east: float, timeout: int = 30) -> str
- landmarks · function · L135-L153 — def landmarks(south: float, west: float, north: float, east: float, limit: int = 300) -> list[dict]
- _parse · function · L156-L205 — def _parse(payload: dict, limit: int) -> list[dict]
- _notability · function · L225-L229 — def _notability(kind: str, value: str, tags: dict) -> int
