# knoxbuild/terrain.py

- mix · function · L22-L28 — def mix(x: np.ndarray, y: np.ndarray, salt: int) -> np.ndarray
- Palette · class · L31-L43 — class Palette
- __init__ · method · L34-L36 — def __init__(self)
- of · method · L38-L43 — def of(self, name: str) -> int
- _pick · function · L46-L63 — def _pick(rule: Rule, rules: Ruleset, pal: Palette, xs: np.ndarray, ys: np.ndarray, seed: int, salt: int) -> np.ndarray
- colour_keys · function · L66-L68 — def colour_keys(img: np.ndarray) -> np.ndarray
- _key · function · L71-L72 — def _key(c) -> int
- ground_layers · function · L75-L107 — def ground_layers(land: np.ndarray, veg: np.ndarray, rules: Ruleset, pal: Palette, seed: int, x0: int = 0, y0: int = 0) -> dict[str, np.ndarray]
- paint · function · L87-L91 — def paint(rule: Rule, mask: np.ndarray, salt: int) -> None
- stack_order · function · L110-L112 — def stack_order(layer_names) -> list[str]
