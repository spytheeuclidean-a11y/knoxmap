"""Draw a compiled map the way the game draws it, from the files the game loads.

    python tools/render_lots.py output/<map> out.png X Y W H [--max-level N] [--scale S]
    python tools/render_lots.py "<game>/media/maps/Muldraugh, KY" out.png X Y W H --world

With --world, X Y are world tile coordinates and the folder holds the
.lotheader files itself - a vanilla map, for comparing against the real thing.

X Y W H is an area of the map in its own tile coordinates (the same as the
terrain bitmap). --max-level cuts the view off above a floor, the way the game
hides the storeys above you when you walk inside, so interiors show; without it
you see rooftops. --scale shrinks the picture (1 = the game at 1x zoom).

This reads the compiled .lotheader/.lotpack files - every floor, wall, window,
door, piece of furniture, roof, tree and lift door exactly as WorldEd wrote
them for the game - and stacks their tile images isometrically. What it leaves
out is what the game adds at run time: lighting and shadows, weather, zombies,
loot, vehicles, and the fading of walls in front of the player.

File layout (WorldEd's LotFilesWorker256, little-endian):

    X_Y.lotheader      "LOTH", version, tile count, tile names ("name\\n"),
                       chunk width, chunk height (8), min level, max level, ...
    world_X_Y.lotpack  "LOTP", version, 1024 chunk offsets (int64, chunk x*32+y),
                       then per chunk: for z, for x 0..7, for y 0..7 either
                       (-1, run of empty squares) or (count+1, room id, count tile ids)
Cells are 256 tiles; the map's tile 0,0 is world tile (world origin cell x 300).
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CELL = 256
CHUNKS = 32
CHUNK = 8
LEVEL_PX = 96          # screen height of one storey at 1x


def read_header(path: str) -> tuple[list[str], int, int]:
    data = open(path, "rb").read()
    pos = 4 if data[:4] == b"LOTH" else 0
    pos += 4                                   # version
    (count,) = struct.unpack_from("<i", data, pos); pos += 4
    names = []
    for _ in range(count):
        end = data.index(b"\n", pos)
        names.append(data[pos:end].decode("latin-1"))
        pos = end + 1
    _cw, _ch, lo, hi = struct.unpack_from("<4i", data, pos)
    return names, lo, hi


def read_squares(pack: str, names: list[str], lo: int, hi: int,
                 want: tuple[int, int, int, int]) -> dict:
    """{(cell-local x, y, z): [tile names]} for squares inside `want` (x0, y0, x1, y1)."""
    data = open(pack, "rb").read()
    pos = 4 if data[:4] == b"LOTP" else 0
    pos += 4
    (n,) = struct.unpack_from("<i", data, pos); pos += 4
    offsets = struct.unpack_from(f"<{n}q", data, pos)
    wx0, wy0, wx1, wy1 = want
    out = {}
    for cx in range(CHUNKS):
        for cy in range(CHUNKS):
            bx, by = cx * CHUNK, cy * CHUNK
            if bx + CHUNK <= wx0 or bx >= wx1 or by + CHUNK <= wy0 or by >= wy1:
                continue
            p = offsets[cx * CHUNKS + cy]
            if p < 0:
                continue
            skip = 0
            for z in range(lo, hi + 1):
                for x in range(CHUNK):
                    for y in range(CHUNK):
                        if skip > 0:
                            skip -= 1
                            continue
                        (count,) = struct.unpack_from("<i", data, p); p += 4
                        if count == -1:
                            (skip,) = struct.unpack_from("<i", data, p); p += 4
                            skip -= 1
                            continue
                        _room = struct.unpack_from("<i", data, p); p += 4
                        ids = struct.unpack_from(f"<{count - 1}i", data, p); p += 4 * (count - 1)
                        sx, sy = bx + x, by + y
                        if wx0 <= sx < wx1 and wy0 <= sy < wy1:
                            out[(sx, sy, z)] = [names[i] for i in ids]
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) < 6:
        print(__doc__)
        return 2
    opts = {a.split("=")[0]: a.split("=", 1)[1] for a in argv[1:] if a.startswith("--") and "=" in a}
    for i, a in enumerate(argv):
        if a in ("--max-level", "--scale") and i + 1 < len(argv):
            opts[a] = argv[i + 1]
    map_dir, out_png = args[0], args[1]
    X, Y, W, H = (int(v) for v in args[2:6])
    max_level = int(opts["--max-level"]) if "--max-level" in opts else None
    scale = float(opts.get("--scale", 1))

    import knoxpaths
    from knoxbuild.world import WORLD_ORIGIN_CELLS

    if "--world" in argv:
        ox = oy = 0
        lots = map_dir
    else:
        ox, oy = WORLD_ORIGIN_CELLS[0] * 300, WORLD_ORIGIN_CELLS[1] * 300
        lots = os.path.join(map_dir, "lots")
    squares: dict[tuple[int, int, int], list[str]] = {}
    top = 0
    wx0, wy0 = ox + X, oy + Y
    for cxw in range(wx0 // CELL, (wx0 + W - 1) // CELL + 1):
        for cyw in range(wy0 // CELL, (wy0 + H - 1) // CELL + 1):
            header = os.path.join(lots, f"{cxw}_{cyw}.lotheader")
            pack = os.path.join(lots, f"world_{cxw}_{cyw}.lotpack")
            if not (os.path.exists(header) and os.path.exists(pack)):
                continue
            names, lo, hi = read_header(header)
            base_x, base_y = cxw * CELL, cyw * CELL
            local = (wx0 - base_x, wy0 - base_y, wx0 + W - base_x, wy0 + H - base_y)
            for (sx, sy, z), tiles in read_squares(pack, names, lo, hi, local).items():
                squares[(base_x + sx - wx0, base_y + sy - wy0, z)] = tiles
                top = max(top, z)
    if not squares:
        print("nothing compiled in that area")
        return 1
    if max_level is not None:
        top = min(top, max_level)

    tiles_dir = knoxpaths.mapping_tools_dir() / "Tiles" / "2x"
    sheets: dict[str, Image.Image | None] = {}
    cache: dict[str, Image.Image | None] = {}

    def image(name: str):
        if name in cache:
            return cache[name]
        img = None
        m = re.match(r"^(.*)_(\d+)$", name)
        if m:
            sheet_name, idx = m.group(1), int(m.group(2))
            if sheet_name not in sheets:
                path = tiles_dir / f"{sheet_name}.png"
                sheets[sheet_name] = Image.open(path).convert("RGBA") if path.exists() else None
            sheet = sheets[sheet_name]
            if sheet is not None:
                cols = max(1, sheet.width // 128)
                cx, cy = (idx % cols) * 128, (idx // cols) * 256
                if cy + 256 <= sheet.height:
                    img = sheet.crop((cx, cy, cx + 128, cy + 256)).resize((TW, TW * 2), Image.LANCZOS)
        cache[name] = img
        return img

    # Sprites are shrunk before they are stacked, so a whole district can be
    # drawn: at full size two square kilometres is a 96,000-pixel-wide image.
    TW = max(4, round(64 * scale))
    half, quarter, level_px = TW // 2, TW // 4, round(LEVEL_PX * TW / 64)
    width = (W + H) * half + TW
    height = (W + H) * quarter + 2 * TW + (top + 1) * level_px
    canvas = Image.new("RGBA", (width, height), (24, 26, 28, 255))
    lift = (top + 1) * level_px
    # The game draws a storey at a time, bottom up, each back to front.
    for z in range(0, top + 1):
        for s in range(W + H - 1):
            for dx in range(max(0, s - H + 1), min(W, s + 1)):
                dy = s - dx
                for name in squares.get((dx, dy, z), ()):
                    img = image(name)
                    if img is not None:
                        canvas.alpha_composite(img, ((dx - dy) * half + H * half,
                                                     (dx + dy) * quarter + lift - z * level_px
                                                     - TW * 3 // 2))
    result = canvas.convert("RGB")
    result.save(out_png)
    print(f"wrote {out_png} {result.size}, levels 0-{top}, {len(squares)} squares")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
