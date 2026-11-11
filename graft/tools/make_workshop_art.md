# tools/make_workshop_art.py

- _font · function · L68-L82 — def _font(px: int)
- thumbnail · function · L85-L127 — def thumbnail(render: Path) -> Image.Image
- fit · function · L130-L138 — def fit(image: Image.Image, size: tuple[int, int]) -> Image.Image
- letterbox · function · L141-L155 — def letterbox(image: Image.Image, size: tuple[int, int]) -> Image.Image
- render_lots · function · L158-L171 — def render_lots(project: Path, x: int, y: int, w: int, h: int, scale: float, where: Path, max_level: int | None = None) -> Path | None
- trim · function · L174-L179 — def trim(image: Image.Image) -> Image.Image
- main · function · L182-L262 — def main(argv: list[str] | None = None) -> int
