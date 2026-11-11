# knoxbuild/zones.py

- overridable · function · L65-L74 — def overridable() -> list[dict]
- clean · function · L77-L119 — def clean(raw) -> list[dict]
- load · function · L122-L128 — def load(out_dir: str, map_name: str) -> list[dict]
- save · function · L131-L137 — def save(out_dir: str, map_name: str, zones) -> None
- Zoning · class · L140-L249 — class Zoning
- __init__ · method · L148-L155 — def __init__(self, items: list[tuple[Polygon, dict]], settings: Settings)
- build · method · L158-L168 — def build(cls, zones, proj, settings: Settings) -> "Zoning"
- load · method · L171-L173 — def load(cls, out_dir: str, map_name: str, proj, settings: Settings) -> "Zoning"
- __len__ · method · L175-L176 — def __len__(self) -> int
- at · method · L178-L188 — def at(self, x: float, y: float) -> dict | None
- settings_at · method · L190-L201 — def settings_at(self, x: float, y: float) -> Settings
- style_at · method · L203-L206 — def style_at(self, x: float, y: float) -> str | None
- presets_at · method · L208-L211 — def presets_at(self, x: float, y: float) -> list[str]
- any_presets · method · L213-L215 — def any_presets(self) -> bool
- chunk_values · method · L217-L249 — def chunk_values(self, keys, gw: int, gh: int, tiles_per_chunk: int) -> dict
