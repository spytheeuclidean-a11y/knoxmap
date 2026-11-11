# knoxbuild/procedural.py

- Candidate · class · L100-L119 — class Candidate
- landmark · method · L110-L113 — def landmark(self) -> bool
- width · method · L116-L119 — def width(self) -> float
- _centre · function · L122-L125 — def _centre(px: list) -> tuple[float, float]
- _grown · function · L128-L139 — def _grown(px: list, factor: float) -> list
- _long_side · function · L142-L153 — def _long_side(px: list) -> float
- _factor · function · L156-L173 — def _factor(cand: Candidate, max_size: float) -> float
- _clamped · function · L176-L187 — def _clamped(factor: float, cx: float, cy: float, width: float, nearby: list[tuple[float, float, float]]) -> float
- _Kept · class · L198-L225 — class _Kept
- __init__ · method · L201-L203 — def __init__(self) -> None
- add · method · L205-L208 — def add(self, cx: float, cy: float, width: float) -> None
- near · method · L210-L225 — def near(self, cx: float, cy: float, width: float) -> list
- plan · function · L228-L274 — def plan(cands: list[Candidate], max_size: float) -> tuple[list[Candidate], dict]
- take · function · L245-L252 — def take(c: Candidate, cx: float, cy: float, nearby: list) -> None
