"""Contact sheet of every tile knoxbuild picks, so the choices can be eyeballed.

The catalogue anchors were chosen by NAME out of a text file. Nothing there
proves `fixtures_bathroom_01_001` is a toilet rather than a bathtub, and a
mislabelled anchor would furnish every bathroom wrongly. This crops each chosen
tile out of the extracted sheets and lays them out with labels.

    python tools/preview_catalog.py <Tiles/2x dir> <Tilesets.txt> <out.png>
"""
from __future__ import annotations

import os
import re
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knoxbuild import catalog as C  # noqa: E402
from tools.extract_tiles import read_tilesets_txt  # noqa: E402

CELL_W, CELL_H = 240, 300


def crop_tile(tiles_dir: str, catalog: dict[str, tuple[int, int]],
              tile_name: str) -> Image.Image | None:
    m = re.match(r"^(.*)_(\d+)$", tile_name)
    if not m:
        return None
    sheet_name, idx = m.group(1), int(m.group(2))
    path = os.path.join(tiles_dir, f"{sheet_name}.png")
    if not os.path.exists(path) or sheet_name not in catalog:
        return None
    cols, _rows = catalog[sheet_name]
    sheet = Image.open(path).convert("RGBA")
    cw, ch = sheet.width // cols, None
    # Rows come from the sheet height and the declared row count.
    rows = catalog[sheet_name][1]
    ch = sheet.height // rows
    col, row = idx % cols, idx // cols
    if row >= rows:
        return None
    return sheet.crop((col * cw, row * ch, (col + 1) * cw, (row + 1) * ch))


def main(argv: list[str]) -> int:
    tiles_dir, tilesets_txt, out_path = argv[1], argv[2], argv[3]
    catalog = read_tilesets_txt(tilesets_txt)

    items: list[tuple[str, str]] = []
    for role in C.FURNITURE:
        north = C.FURNITURE[role].get("N", {})
        tile = north.get("0,0")
        if tile:
            items.append((role, tile))
    for entry, label in (
        (C.TILE_ENTRIES[C.EXTERIOR_WALL - 1], "exterior wall"),
        (C.TILE_ENTRIES[C.INTERIOR_WALL - 1], "interior wall"),
        (C.TILE_ENTRIES[C.DOOR - 1], "door"),
        (C.TILE_ENTRIES[C.WINDOW - 1], "window"),
        (C.TILE_ENTRIES[C.FLOOR_CARPET_RED - 1], "floor: livingroom"),
        (C.TILE_ENTRIES[C.FLOOR_CARPET_BLUE - 1], "floor: bedroom"),
        (C.TILE_ENTRIES[C.FLOOR_WOOD - 1], "floor: wood"),
        (C.TILE_ENTRIES[C.FLOOR_TILE_PALE - 1], "floor: bathroom"),
        (C.TILE_ENTRIES[C.FLOOR_TILE_CHECK - 1], "floor: kitchen"),
        (C.TILE_ENTRIES[C.FLOOR_LINO - 1], "floor: storage"),
    ):
        tile = list(entry["tiles"].values())[0]
        items.append((label, tile))

    cols = 6
    rows = (len(items) + cols - 1) // cols
    img = Image.new("RGBA", (cols * CELL_W, rows * CELL_H), (32, 32, 36, 255))
    d = ImageDraw.Draw(img)

    for i, (label, tile_name) in enumerate(items):
        cx, cy = (i % cols) * CELL_W, (i // cols) * CELL_H
        sprite = crop_tile(tiles_dir, catalog, tile_name)
        if sprite is not None:
            sprite.thumbnail((CELL_W - 16, CELL_H - 60))
            img.paste(sprite,
                      (cx + (CELL_W - sprite.width) // 2, cy + 8),
                      sprite)
        d.text((cx + 8, cy + CELL_H - 42), label, fill=(255, 255, 255, 255))
        d.text((cx + 8, cy + CELL_H - 26), tile_name, fill=(150, 150, 160, 255))

    img.convert("RGB").save(out_path)
    print(f"wrote {out_path}: {len(items)} tiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
