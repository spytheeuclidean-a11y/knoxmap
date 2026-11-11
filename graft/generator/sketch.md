# generator/sketch.py

- palette · function · L166-L178 — def palette() -> list[dict]
- _ring_is_closed · function · L181-L182 — def _ring_is_closed(points: list) -> bool
- _tags_for · function · L185-L193 — def _tags_for(entry_id: str, extra: dict | None) -> dict | None
- features · function · L196-L247 — def features(drawn: dict | list | None) -> list[OSMFeature]
- category_of · function · L250-L262 — def category_of(entry_id: str) -> str | None
- _sheet_size · function · L288-L296 — def _sheet_size(design: dict) -> tuple[float, float]
- _anchor · function · L299-L311 — def _anchor(design: dict) -> tuple[float, float]
- _utm_extent · function · L314-L330 — def _utm_extent(south: float, west: float, north: float, east: float)
- design_bbox · function · L333-L360 — def design_bbox(design: dict) -> tuple[float, float, float, float]
- design_to_drawn · function · L363-L413 — def design_to_drawn(design: dict | None) -> dict
- to_lonlat · function · L374-L380 — def to_lonlat(point): # By proportion of the sheet rather than by metres again: the box was # already fitted to the sheet, so a thing at the right-hand edge lands # on the right-hand edge and the two cannot disagree.
