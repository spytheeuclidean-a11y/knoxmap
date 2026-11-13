"""A checkpoint and a roadblock drawn as they stand in the world.

A barricade is four tiles of one object (knoxbuild/props.py BARRICADE_X/Y),
laid across a carriageway with crates in whatever lane is left; a lane too
narrow for the barrier gets crates instead of half a fence over the pavement.
The only way to see whether that reads is to put the sprites on a road:

    python tools/preview_barricade.py out.png

The tiles are cut from the game's own 2x sheets by tools/preview_signs.py and
laid out on the game's isometric grid: a cell is 128 px wide and 64 tall, so
one cell east is 64 right and 32 down, and the road the barrier crosses runs
away to the lower left.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw  # noqa: E402

from knoxbuild.props import BARRICADE_X, CRATES  # noqa: E402
from preview_signs import BG, CELL_H, CELL_W, INK, PAD, TITLE, tile  # noqa: E402

ROAD = (150, 150, 150)             # MEDIUM_ASPHALT: the street the barrier holds
MAIN = (80, 80, 80)                # DARKEST_ASPHALT: the avenue a roadblock is on
PAVEMENT = (188, 188, 188)
HALF_W, HALF_H = CELL_W // 2, CELL_H // 8     # one cell east: 64 right, 32 down
BASE = CELL_H - HALF_H             # where a sprite's ground diamond sits
NEAR, FAR = 1.6, -1.4              # how much road to draw past the barrier line


def iso(x: float, y: float) -> tuple[float, float]:
    """Screen point of a cell centre, x east and y south."""
    return (x - y) * HALF_W, (x + y) * HALF_H


def panel(title: str, lanes: int, barrier: list[str], crates: list[str],
          note: str, avenue: bool = False) -> Image.Image:
    """One street from above: barrier across it, crates in the lanes left over."""
    corners = [iso(-0.5, FAR), iso(lanes + 0.5, FAR),
               iso(lanes + 0.5, NEAR), iso(-0.5, NEAR)]
    left = min(cx for cx, _cy in corners)
    right = max(cx for cx, _cy in corners)
    top = min(cy for _cx, cy in corners)
    bottom = max(cy for _cx, cy in corners)
    width = int(right - left) + PAD * 2
    height = int(bottom - top) + 150
    img = Image.new("RGBA", (max(width, 700), height), BG)
    d = ImageDraw.Draw(img)

    origin = (PAD - left, 70 - top)

    def at(x: float, y: float) -> tuple[float, float]:
        sx, sy = iso(x, y)
        return origin[0] + sx, origin[1] + sy

    d.text((PAD, 8), title, fill=TITLE)
    d.text((PAD, 22), "  ".join(barrier + crates), fill=(120, 124, 132))

    # Pavement either side, then the carriageway, both running north to south.
    for shift, colour in ((-0.5, PAVEMENT), (0.0, MAIN if avenue else ROAD)):
        wide = lanes + (0.0 if shift == 0.0 else 1.0)
        band = [at(shift, FAR), at(wide, FAR), at(wide, NEAR), at(shift, NEAR)]
        d.polygon(band, fill=colour)

    # The barrier stands across the road at the barrier line, one segment per
    # lane; the lanes it leaves are where the crates go.
    for i, name in enumerate(barrier):
        cx, cy = at(i + 0.5, 0.5)
        piece = tile(name)
        if piece is not None:
            img.alpha_composite(piece, (int(cx - HALF_W), int(cy - BASE)))

    for i, name in enumerate(crates, start=len(barrier)):
        cx, cy = at(i + 0.5, 0.5)
        piece = tile(name)
        if piece is not None:
            img.alpha_composite(piece, (int(cx - HALF_W), int(cy - BASE)))

    d.text((PAD, img.height - 24), note, fill=INK)
    return img


def main(argv: list[str]) -> int:
    out = argv[1] if len(argv) > 1 else "barricade.png"
    barrier = list(BARRICADE_X)                       # 044 045 046 047
    panels = [
        panel("checkpoint: the barrier across a four-lane street",
              4, barrier, [], "one segment per lane, kerb to kerb"),
        panel("a main road: the barrier and the lanes it leaves",
              6, barrier, [CRATES[0], CRATES[3]],
              "BARRIER then crates - spare[:2] fills what is left", avenue=True),
        panel("a lane too narrow for half a barrier",
              3, [], [CRATES[0], CRATES[3], CRATES[1]],
              "no barricade: a segment over the pavement is not a scene"),
    ]
    sheet = Image.new("RGB", (max(p.width for p in panels),
                              sum(p.height for p in panels)), BG)
    y = 0
    for p in panels:
        sheet.paste(p, (0, y), p)
        y += p.height
    sheet.save(out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
