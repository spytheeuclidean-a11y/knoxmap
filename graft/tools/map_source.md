# tools/map_source.py

- read_lots · function · L35-L48 — def read_lots(project: str)
- merge_stack · function · L51-L53 — def merge_stack(ground: list[str], building: list[str], has_room: bool) -> list[str]
- _free_gb · function · L56-L61 — def _free_gb() -> float
- _row · function · L67-L154 — def _row(project: str, out: str, cy: int, band: list[tuple], placed, seed: int, seams: bool, size: tuple[int, int]) -> int
- make_map_source · function · L157-L216 — def make_map_source(project: str, out: str, seed: int = 1, seams: bool = False, workers: int | None = None, should_stop=None, on_row=None, on_start=None) -> int
- main · function · L219-L229 — def main(argv: list[str]) -> int
