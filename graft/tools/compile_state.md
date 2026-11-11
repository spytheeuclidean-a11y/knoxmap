# tools/compile_state.py

- _sha · function · L40-L45 — def _sha(*parts: bytes) -> str
- _key · function · L48-L49 — def _key(x: int, y: int) -> str
- _unkey · function · L52-L54 — def _unkey(key: str) -> tuple[int, int]
- _pzw_facts · function · L57-L64 — def _pzw_facts(text: str) -> dict
- _global_fingerprint · function · L67-L87 — def _global_fingerprint(project: Path, pzw_text: str, facts: dict) -> str
- fingerprints · function · L90-L129 — def fingerprints(project: Path) -> dict
- tbx · function · L108-L112 — def tbx(rel: str) -> str
- load · function · L132-L138 — def load(project: Path) -> dict | None
- save · function · L141-L148 — def save(project: Path, fp: dict) -> None
- forget · function · L151-L155 — def forget(project: Path) -> None
- _grow · function · L158-L161 — def _grow(cells: set[tuple[int, int]], size: tuple[int, int]) -> set[tuple[int, int]]
- lot_files_of · function · L164-L173 — def lot_files_of(cells, origin: tuple[int, int]) -> set[tuple[int, int]]
- plan · function · L176-L196 — def plan(old: dict | None, new: dict, lots_present: bool) -> dict | None
- discard · function · L199-L235 — def discard(project: Path, plan_: dict, origin: tuple[int, int]) -> dict
- batch_needs_work · function · L238-L253 — def batch_needs_work(project: Path, box: tuple[int, int, int, int], origin: tuple[int, int], size: tuple[int, int]) -> bool
- origin_of · function · L256-L258 — def origin_of(pzw: Path) -> tuple[int, int]
- wipe · function · L261-L277 — def wipe(project: Path) -> None
