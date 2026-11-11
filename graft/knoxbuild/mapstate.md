# knoxbuild/mapstate.py

- _parse · function · L48-L51 — def _parse(version: str) -> tuple[int, ...]
- _path · function · L54-L55 — def _path(map_dir: str) -> str
- read · function · L58-L64 — def read(map_dir: str) -> dict
- stamp · function · L67-L82 — def stamp(map_dir: str, stage: str, version: str | None = None) -> None
- done · function · L85-L111 — def done(map_dir: str) -> dict
- needs · function · L114-L135 — def needs(map_dir: str) -> list[str]
- made_with · function · L138-L149 — def made_with(map_dir: str) -> str | None
