"""Every tower drawn level by level, with the silhouette beside it.

A water tower, a lighthouse, a windmill and a clock tower are not buildings
with floor plans - generator/structures.py stacks them out of solid blocks -
so plan_sheet.py cannot draw them and there was no way to look at one without
compiling a map. Each level's footprint is laid out left to right and the
elevation on the end is what the tower reads as from across a town: legs with
a tank on them, a shaft, a shaft on a wide base.

    python tools/preview_towers.py out.png

The tiles come from _tower() itself, so what this draws is what a map gets.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw  # noqa: E402
from shapely.geometry import box  # noqa: E402

from generator import structures as S  # noqa: E402

BG = (30, 31, 35)
INK = (225, 225, 225)
TITLE = (255, 210, 120)
BLOCK = (150, 160, 175)          # a full-height block
PLINTH = (110, 115, 125)         # the low base a shaft rises from
CELL = 14
PAD = 30

# Footprints a surveyor would draw for each, in tiles. A node-mapped tower
# comes through as a 3x3 box; these are the ones traced as an outline.
TOWERS = [
    ("water tower", {"man_made": "water_tower"}, (6, 6)),
    ("lighthouse", {"man_made": "lighthouse"}, (3, 3)),
    ("windmill", {"man_made": "windmill", "height": "15"}, (5, 5)),
    ("clock tower", {"man_made": "tower", "tower:type": "clock"}, (4, 4)),
    ("steeple", {"man_made": "tower", "tower:type": "bell_tower"}, (3, 3)),
    ("silo", {"man_made": "silo"}, (4, 4)),
    ("transmission tower", {"power": "tower"}, (3, 3)),
]


def _tiles(tags: dict, size: tuple[int, int]) -> dict:
    plan = S.Plan()
    S._tower(plan, box(0, 0, size[0], size[1]), tags)
    return plan.tiles


def panel(name: str, tags: dict, size: tuple[int, int]) -> Image.Image:
    tiles = _tiles(tags, size)
    xs = [k[0] for k in tiles]
    ys = [k[1] for k in tiles]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    top = max(k[2] for k in tiles)
    wide, high = x1 - x0 + 1, y1 - y0 + 1
    step = wide * CELL + PAD
    # One panel per level, and the elevation after them. The elevation is as
    # tall as the tower, which is what decides the height of the strip.
    img = Image.new("RGB", (step * (top + 2) + PAD,
                            max(high, top + 1) * CELL + PAD * 3), BG)
    d = ImageDraw.Draw(img)
    d.text((PAD, 8), f"{name}  -  {top + 1} storeys, {len(tiles)} tiles", fill=TITLE)

    def cell(px: int, py: int, tile: str) -> None:
        d.rectangle([px, py, px + CELL - 2, py + CELL - 2],
                    fill=PLINTH if tile == S.PLINTH else BLOCK,
                    outline=(20, 20, 24))

    for z in range(top + 1):
        ox = PAD + z * step
        d.text((ox, PAD - 4), f"level {z}", fill=INK)
        for (x, y, lz, _layer), tile in tiles.items():
            if lz == z:
                cell(ox + (x - x0) * CELL, PAD + 12 + (y - y0) * CELL, tile)

    ox = PAD + (top + 1) * step
    d.text((ox, PAD - 4), "from the side", fill=INK)
    for (x, y, z, _layer), tile in tiles.items():
        cell(ox + (x - x0) * CELL, PAD + 12 + (top - z) * CELL, tile)
    return img


def main(argv: list[str]) -> int:
    out = argv[1] if len(argv) > 1 else "towers.png"
    panels = [panel(*t) for t in TOWERS]
    sheet = Image.new("RGB", (max(p.width for p in panels),
                              sum(p.height for p in panels)), BG)
    y = 0
    for p in panels:
        sheet.paste(p, (0, y))
        y += p.height
    sheet.save(out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
