# knoxbuild/areas.py

- AreaIndex · class · L38-L96 — class AreaIndex
- __init__ · method · L39-L41 — def __init__(self, polygons: list[tuple[Polygon, dict]])
- load · method · L44-L66 — def load(cls, out_dir: str, map_name: str, proj) -> "AreaIndex"
- around · method · L68-L82 — def around(self, x: float, y: float) -> dict | None
- kind_for · method · L84-L92 — def kind_for(self, x: float, y: float, tiles: int) -> str | None
- category_at · method · L94-L96 — def category_at(self, x: float, y: float) -> str | None
