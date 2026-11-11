# knoxbuild/picture.py

- map_size · function · L45-L50 — def map_size(map_dir: str | Path) -> tuple[int, int]
- compiled · function · L53-L55 — def compiled(map_dir: str | Path) -> bool
- _pixels · function · L58-L61 — def _pixels(w: int, h: int, scale: float) -> int
- _within_budget · function · L64-L76 — def _within_budget(x: int, y: int, w: int, h: int, scale: float) -> tuple[int, int, int, int]
- _scale_for · function · L79-L88 — def _scale_for(w: int, h: int, size: tuple[int, int]) -> float
- _trim · function · L91-L96 — def _trim(picture: Image.Image) -> Image.Image
- _on_background · function · L99-L109 — def _on_background(picture: Image.Image, size: tuple[int, int]) -> Image.Image
- picture · function · L112-L150 — def picture(map_dir: str | Path, out_png: str | Path | None = None, box: tuple[int, int, int, int] | None = None, roofs: bool = True, size: tuple[int, int] = SIZE, scale: float | None = None) -> Image.Image
- pictures_of · function · L153-L178 — def pictures_of(map_dir: str | Path, into: str | Path | None = None, size: tuple[int, int] = SIZE) -> list[Path]
