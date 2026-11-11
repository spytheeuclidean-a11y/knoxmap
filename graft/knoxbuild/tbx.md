# knoxbuild/tbx.py

- _stable_seed · function · L22-L26 — def _stable_seed(*parts) -> int
- _attrs · function · L35-L40 — def _attrs(pairs: list[tuple[str, object]]) -> str: # Nearly every value is a coordinate or an index. Quoting those through # quoteattr, nine million calls for a town, was 40% of the time spent # writing buildings; numbers never need escaping.
- _peak_depth · function · L56-L58 — def _peak_depth(across: int) -> str
- _roof_pieces · function · L61-L111 — def _roof_pieces(rects, peaked: bool, roof30: bool = True)
- _rooftop · function · L122-L144 — def _rooftop(grid: list[list[int]], width: int, height: int, seed: str | int = 0) -> list[tuple[str, int, int, str]]
- _storefront_runs · function · L147-L186 — def _storefront_runs(storey, doors) -> list[tuple[str, int, int, int]]
- cell · function · L155-L156 — def cell(x, y)
- outside · function · L158-L161 — def outside(d, fixed, t)
- _add · function · L189-L198 — def _add(entries: list[dict], entry: dict | None) -> int
- render_tbx · function · L219-L688 — def render_tbx(plan: Plan | Building, name: str, style: dict | None = None) -> str
- user_tile_layer · function · L473-L483 — def user_tile_layer(level: int) -> str | None
