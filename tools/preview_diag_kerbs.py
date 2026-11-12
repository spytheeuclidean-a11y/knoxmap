"""Catalogue of the game's diagonal kerb tiles, straight out of its own packs.

    python tools/preview_diag_kerbs.py [out.png] [sheet-prefix]

Every piece is drawn at the size the game draws it, labelled with its index, so
the piece for a diagonal kerb can be picked by looking instead of guessed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PACK = "media/texturepacks/Tiles2x.floor.pack"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "diag_kerbs.png")
PREFIX = sys.argv[2] if len(sys.argv) > 2 else "street_curbs_01_diag"


def install_dir() -> Path:
    """The install KnoxMap is configured to build for."""
    config = Path("knoxmap_config.json")
    if not config.exists():
        raise SystemExit("run me from the KnoxMap folder")
    install = Path(json.loads(config.read_text("utf-8"))["pz_install"])
    if not (install / PACK).exists():
        raise SystemExit(f"{install / PACK} is not there - Build 42 has no 2x packs")
    return install


def main() -> int:
    from tools.pzpk import read_pack

    tiles, images = read_pack(install_dir() / PACK)
    pieces = []
    for tile in tiles:
        if not tile.name.startswith(PREFIX) or tile.w < 3 or tile.h < 3:
            continue
        art = images[tile.atlas].crop((tile.x, tile.y, tile.x + tile.w, tile.y + tile.h))
        if art.getbbox():
            pieces.append((tile, art))
    print(f"{len(pieces)} pieces under {PREFIX}")

    cell_w = max(p[1].width for p in pieces) + 10
    cell_h = max(p[1].height for p in pieces) + 22
    cols = 8
    rows = (len(pieces) + cols - 1) // cols
    out = Image.new("RGB", (cols * cell_w + 8, rows * cell_h + 8), (18, 20, 24))
    draw = ImageDraw.Draw(out)
    for n, (tile, art) in enumerate(pieces):
        x = 4 + (n % cols) * cell_w
        y = 4 + (n // cols) * cell_h
        draw.text((x, y), "#" + tile.name.rsplit("_", 1)[-1], fill=(250, 230, 140))
        bg = Image.new("RGBA", art.size, (60, 90, 60, 255))
        bg.alpha_composite(art)
        out.paste(bg.convert("RGB"), (x, y + 12))
    out.save(OUT)
    print("wrote", OUT, out.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
