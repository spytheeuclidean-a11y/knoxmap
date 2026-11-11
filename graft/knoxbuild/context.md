# knoxbuild/context.py

- Context · class · L43-L99 — class Context
- __init__ · method · L44-L83 — def __init__(self, width: int, height: int, buildings: list[tuple[float, float, float, int | None]], metres_per_tile: float = 1.0, road_hierarchy: np.ndarray | None = None)
- density · method · L85-L89 — def density(self, x: float, y: float) -> float
- neighbour_levels · method · L91-L99 — def neighbour_levels(self, x: float, y: float) -> float | None
- style_fits · function · L102-L107 — def style_fits(style_name: str, density: float) -> bool
