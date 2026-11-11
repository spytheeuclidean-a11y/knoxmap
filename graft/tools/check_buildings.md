# tools/check_buildings.py

- Lots · class · L45-L59 — class Lots
- __init__ · method · L48-L49 — def __init__(self, lots_dir: str, keep: int = 12)
- at · method · L51-L59 — def at(self, x: int, y: int, z: int) -> list[str]
- wall_tiles · function · L66-L71 — def wall_tiles(b) -> set[str]
- is_wall · function · L74-L75 — def is_wall(tile: str, own: set[str] = frozenset()) -> bool
- ground_blockers · function · L78-L85 — def ground_blockers() -> set[str]
- furniture_tiles · function · L88-L90 — def furniture_tiles(b) -> set[str]
- blank_tiles · function · L93-L132 — def blank_tiles(lots_dir: str) -> list[str]
- check · function · L135-L219 — def check(project: str, show: int = 8, only_level: int | None = None) -> dict
- blocks · function · L163-L166 — def blocks(tile: str) -> bool
- room · function · L172-L173 — def room(x: int, y: int) -> int
- main · function · L222-L250 — def main(argv: list[str]) -> int
