# generator/edits.py

- empty · function · L42-L43 — def empty() -> dict
- clean · function · L46-L81 — def clean(raw: dict | None) -> dict
- count · function · L84-L88 — def count(edits: dict | None) -> int
- apply · function · L91-L129 — def apply(features: list[OSMFeature], edits: dict | None) -> tuple[list, dict]
- as_geojson · function · L132-L168 — def as_geojson(features: list[OSMFeature], bbox=None, limit: int = 0) -> dict
