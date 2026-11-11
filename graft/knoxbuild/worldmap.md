# knoxbuild/worldmap.py

- write · function · L84-L199 — def write(out_dir: str, map_name: str, proj, info: dict, buildings: list[tuple[list[tuple[float, float]], str, str]]) -> dict
- _lua_string · function · L201-L204 — def _lua_string(text: str) -> str
- _write_annotations · function · L207-L235 — def _write_annotations(path: str, labels: list[tuple[str, str, float, float, float]], width: int, height: int) -> None
- _clean · function · L238-L244 — def _clean(poly) -> Polygon | None
- _line · function · L247-L249 — def _line(feat, proj) -> LineString | None
- _outer_rings · function · L252-L257 — def _outer_rings(feat, proj) -> list[list[tuple[float, float]]]
- _parts · function · L260-L265 — def _parts(geom) -> list[Polygon]
- _write_worldmap · function · L268-L299 — def _write_worldmap(path: str, features: list[tuple[Polygon, str, str]], width: int, height: int) -> int
- _write_streets · function · L302-L325 — def _write_streets(path: str, streets: dict[str, list[tuple[LineString, float]]]) -> int
