# knoxbuild/worldmap_bin.py

- _features · function · L43-L63 — def _features(xml_path: str)
- _polygons · function · L70-L78 — def _polygons(shape)
- _ring · function · L81-L90 — def _ring(points) -> list | None
- _clean · function · L93-L127 — def _clean(rings) -> list[list]
- _pieces · function · L130-L144 — def _pieces(rings, cell_x, cell_y)
- _points · function · L156-L157 — def _points(piece) -> int
- _within_budget · function · L160-L194 — def _within_budget(features: list) -> list
- rank · function · L180-L186 — def rank(item)
- write_bin · function · L197-L262 — def write_bin(xml_path: str, bin_path: str) -> int
- index · function · L222-L225 — def index(text: str) -> int
- read_bin · function · L265-L305 — def read_bin(bin_path: str) -> dict
- take · function · L271-L275 — def take(fmt)
