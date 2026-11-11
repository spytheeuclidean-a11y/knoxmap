# tools/make_catalog.py

- parse_tile_entries · function · L23-L33 — def parse_tile_entries(path: str) -> list[dict]
- parse_furniture · function · L36-L60 — def parse_furniture(path: str) -> dict[str, list[dict]]
- parse_room_names · function · L63-L71 — def parse_room_names(path: str) -> dict[str, str]
- _tile_props · function · L111-L113 — def _tile_props(body: str) -> dict: # [ \t], not \s: a property with no value would swallow the next line.
- _blank · function · L125-L155 — def _blank(tile: str) -> bool
- erika_roles · function · L158-L250 — def erika_roles(furniture: dict, layers: dict) -> dict
- main · function · L253-L914 — def main(argv: list[str]) -> int
- tile_keys · function · L265-L274 — def tile_keys(e: dict) -> dict
- pick · function · L276-L287 — def pick(category: str, anchor: str) -> dict
- bt_entry · function · L295-L308 — def bt_entry(category: str, anchor: str | None) -> dict | None
- bt_lookup · function · L320-L325 — def bt_lookup(category: str, anchor: str) -> dict | None
- with_cutouts · function · L327-L349 — def with_cutouts(entry: dict | None) -> dict | None
- wall_entry · function · L351-L359 — def wall_entry(anchor: str) -> dict
- caps_for · function · L361-L371 — def caps_for(wall: str, fallback: str | None) -> dict | None
- curtains · function · L373-L383 — def curtains(anchor: str | None) -> dict | None
- roof · function · L385-L395 — def roof(slopes: str | None, top: str, peaked: bool) -> dict
- window · function · L397-L401 — def window(anchor: str) -> dict
- find_furniture · function · L582-L602 — def find_furniture(anchor: str) -> dict
