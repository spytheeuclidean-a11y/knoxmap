# tools/extract_tiles.py

- PackReader · class · L49-L103 — class PackReader
- __init__ · method · L50-L59 — def __init__(self, path: str)
- _int · method · L61-L65 — def _int(self) -> int
- _string · method · L67-L71 — def _string(self) -> str
- pages · method · L73-L103 — def pages(self)
- read_png · function · L90-L101 — def read_png() -> bytes
- split_name · function · L106-L111 — def split_name(entry: str) -> tuple[str, int] | None
- read_tilesets_txt · function · L114-L136 — def read_tilesets_txt(path: str) -> tuple[dict[str, tuple[int, int]], dict[str, str]]
- extract_pack · function · L139-L224 — def extract_pack(pack_path: str, catalog: dict, wanted: set, out_dir: str, merge: bool = False) -> set
- flush · function · L171-L178 — def flush(tname: str) -> None
- main · function · L227-L292 — def main(argv: list[str]) -> int
