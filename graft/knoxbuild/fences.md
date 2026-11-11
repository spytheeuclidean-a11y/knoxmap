# knoxbuild/fences.py

- _tile · function · L47-L48 — def _tile(n: int) -> str
- _fenced_sites · function · L56-L65 — def _fenced_sites(areas) -> list
- style_for · function · L68-L91 — def style_for(tags: dict, area: str | None) -> str
- _grid_path · function · L94-L121 — def _grid_path(points: list[tuple[float, float]]) -> list[tuple[int, int]]
- _tarmac_mask · function · L124-L143 — def _tarmac_mask(bmp_path: str, width: int, height: int)
- build_fences · function · L146-L289 — def build_fences(out_dir: str, map_name: str, proj, occupied, areas, bdir: str, extra: list | None = None, keep_clear: set | None = None) -> tuple[list, int]
- building_at · function · L167-L168 — def building_at(x: int, y: int) -> bool
- crossing · function · L177-L182 — def crossing(ax: int, ay: int, bx: int, by: int) -> bool
- render_fence_tbx · function · L292-L334 — def render_fence_tbx(width: int, height: int, pieces: dict[tuple[int, int], str]) -> str
