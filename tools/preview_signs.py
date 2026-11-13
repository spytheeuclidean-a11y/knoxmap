"""A motel's board and a drive-in's, drawn as they stand in the world.

A roadside sign is a post of solid blocks with one of the game's shop signboards
hung on the WallFurniture layer at the top of it (knoxbuild/landmarks.py). There
is no wall behind the board, and the board is four tiles wide, so the only way
to judge how it reads is to put the sprites together and look:

    python tools/preview_signs.py out.png

The tiles are cut from the game's own 2x sheets, the same ones the map names, so
what this draws is what a compiled map lays down. Nothing here is scaled up -
the sheets are already at the 2x size a player sees.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import knoxpaths  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from knoxbuild.landmarks import BOARD_STRIPS, SIGN_POLE, SIGN_POST  # noqa: E402

BG = (30, 31, 35)
INK = (225, 225, 225)
TITLE = (255, 210, 120)
GROUND = (70, 72, 78)
CELL_W, CELL_H = 128, 256          # one tile on a 2x sheet
PAD = 24


def two_x_dir() -> str:
    return os.path.join(str(knoxpaths.mapping_tools_dir()), "Tiles", "2x")


def sprite(sheet: str, index: int) -> Image.Image | None:
    """One tile's picture from its 2x sheet, or None if the artwork is absent."""
    path = os.path.join(two_x_dir(), f"{sheet}.png")
    if not os.path.exists(path):
        return None
    with Image.open(path) as sheet_img:
        img = sheet_img.convert("RGBA")
        cols = max(1, img.width // CELL_W)
        row, col = divmod(index, cols)
        return img.crop((col * CELL_W, row * CELL_H, col * CELL_W + CELL_W,
                         row * CELL_H + CELL_H))


def tile(name: str) -> Image.Image | None:
    sheet, _, index = name.rpartition("_")
    return sprite(sheet, int(index))


def panel(name: str, what: str, strip_index: int = 0) -> Image.Image:
    """One sign seen from the street: post below, board on top, no wall."""
    strip = BOARD_STRIPS["N"][strip_index]
    posts = SIGN_POST[what]
    wide, high = len(strip) * CELL_W, (posts + 1) * CELL_H
    img = Image.new("RGBA", (wide + PAD * 2, high + PAD * 3), BG)
    d = ImageDraw.Draw(img)
    d.text((PAD, 8), f"{name}  -  a {posts}-storey post, a {len(strip)}-tile board",
           fill=TITLE)
    d.text((PAD, 20), "  ".join(strip), fill=(120, 124, 132))

    top = PAD * 2
    # The ground the post stands on, so the heights read as heights.
    d.rectangle([PAD - 8, top + high - 6, PAD + wide + 8, top + high + 2], fill=GROUND)

    post = tile(SIGN_POLE)
    board = [tile(t) for t in strip]
    centre = len(strip) // 2
    # The pole runs to the top of the board's storey and the board is drawn
    # over it, the way the map lays them down.
    for z in range(posts + 1):
        y = top + high - (z + 1) * CELL_H
        if post is not None:
            img.alpha_composite(post, (PAD + centre * CELL_W, y))
        d.rectangle([PAD + centre * CELL_W, y, PAD + (centre + 1) * CELL_W - 1,
                     y + CELL_H - 1], outline=(90, 92, 100))
    y = top
    for j, piece in enumerate(board):
        x = PAD + j * CELL_W
        if piece is not None:
            img.alpha_composite(piece, (x, y))
        else:
            d.rectangle([x, y, x + CELL_W - 1, y + CELL_H - 1], outline=(120, 60, 60))
    d.text((PAD, top + high + 10),
           "no wall behind it: the board is furniture on the WallFurniture layer",
           fill=INK)
    return img


def main(argv: list[str]) -> int:
    out = argv[1] if len(argv) > 1 else "signs.png"
    # The two boards the map draws from: both are one picture across their
    # four tiles, which is what makes them read as a billboard.
    panels = [panel("motel sign", "motel", 0),
              panel("motel sign, the other board", "motel", 1),
              panel("drive-in sign", "drive-in", 0)]
    sheet = Image.new("RGB", (max(p.width for p in panels),
                              sum(p.height for p in panels)), BG)
    y = 0
    for p in panels:
        sheet.paste(p, (0, y), p)
        y += p.height
    sheet.save(out)
    print(f"wrote {out}")
    if not os.path.isdir(two_x_dir()):
        print("no tile artwork on this machine: the boards are drawn as outlines",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
