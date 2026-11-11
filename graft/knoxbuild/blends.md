# knoxbuild/blends.py

- Blend · class · L34-L40 — class Blend
- parse_blends · function · L43-L70 — def parse_blends(text: str) -> list[Blend]
- load_blends · function · L73-L75 — def load_blends(path: str) -> list[Blend]
- _members · function · L78-L88 — def _members(rules: Ruleset, pal: Palette, kind: str) -> np.ndarray
- _neighbour · function · L91-L98 — def _neighbour(mask: np.ndarray, dx: int, dy: int) -> np.ndarray
- blend_layers · function · L101-L171 — def blend_layers(floor: np.ndarray, rules: Ruleset, blends: list[Blend], pal: Palette, seed: int, x0: int = 0, y0: int = 0, seam: int | None = None) -> dict[str, np.ndarray]
- look · function · L119-L127 — def look(mask: np.ndarray, dx: int, dy: int) -> np.ndarray
- see · function · L146-L150 — def see(dx, dy, main=b.main, mask=is_main)
