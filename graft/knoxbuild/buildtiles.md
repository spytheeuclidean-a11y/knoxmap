# knoxbuild/buildtiles.py

- Floor · class · L23-L26 — class Floor
- Building · class · L30-L38 — class Building
- tile_name · function · L41-L45 — def tile_name(name: str) -> str
- _tile_grid · function · L48-L54 — def _tile_grid(text: str, user_tiles: list[str], w: int, h: int) -> list[list[str]]
- parse_tbx · function · L57-L79 — def parse_tbx(text: str) -> Building
- _window_variant · function · L86-L94 — def _window_variant(window_tile: str) -> int
- _stair_squares · function · L97-L104 — def _stair_squares(o: dict) -> list[tuple[int, int]]
- _entry · function · L107-L109 — def _entry(b: Building, number) -> dict
- level_layers · function · L112-L380 — def level_layers(b: Building, z: int) -> dict[tuple[int, int], list[tuple[str, str]]]
- room · function · L133-L134 — def room(x: int, y: int) -> int
- west · function · L153-L154 — def west(x, y)
- north · function · L156-L157 — def north(x, y)
- wall_tiles · function · L164-L181 — def wall_tiles(x: int, y: int, kind: str, fallback: str = "", end=False) -> list[str]
- add · function · L230-L231 — def add(x, y, tile)
- add_curtain · function · L237-L239 — def add_curtain(x, y, tile, before=False)
- preserve_corner · function · L257-L263 — def preserve_corner(tiles)
- level_tiles · function · L383-L385 — def level_tiles(b: Building, z: int) -> dict[tuple[int, int], list[str]]
- compose_lots · function · L388-L410 — def compose_lots(lots) -> dict[tuple[int, int, int], list[str]]
