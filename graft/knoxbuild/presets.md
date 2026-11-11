# knoxbuild/presets.py

- folder · function · L62-L63 — def folder(base_dir) -> str
- safe_name · function · L66-L70 — def safe_name(name: str) -> str
- measure · function · L73-L88 — def measure(text: str) -> dict | None
- kinds · function · L91-L114 — def kinds() -> list[dict]
- manifest · function · L117-L132 — def manifest(base_dir) -> dict
- _write_manifest · function · L135-L143 — def _write_manifest(base_dir, data: dict) -> None
- set_kind · function · L146-L159 — def set_kind(base_dir, name: str, kind: str) -> str
- set_use · function · L162-L174 — def set_use(base_dir, kind: str, on: bool) -> bool
- using · function · L177-L179 — def using(base_dir) -> set
- library · function · L182-L210 — def library(base_dir) -> list[dict]
- read · function · L213-L219 — def read(base_dir, name: str) -> str | None
- save · function · L222-L244 — def save(base_dir, name: str, text: str, kind: str | None = None) -> dict
- remove · function · L247-L263 — def remove(base_dir, name: str) -> bool
- fitting · function · L266-L275 — def fitting(entries: list[dict], width: int, height: int) -> list[dict]
- choose · function · L278-L290 — def choose(entries: list[dict], width: int, height: int, seed: int) -> dict | None
- for_kind · function · L293-L296 — def for_kind(entries: list[dict], kind: str | None) -> list[dict]
- choose_for_kind · function · L299-L312 — def choose_for_kind(entries: list[dict], kind: str | None, width: int, height: int, seed: int) -> dict | None
