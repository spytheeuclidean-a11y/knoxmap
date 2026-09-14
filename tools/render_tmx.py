"""Draw part of a compiled cell the way the game shows it, from the real tiles.

    python tools/render_tmx.py output/<map>/tmx/<cell>.tmx out.png [x y w h] [--no-trees]

The .tmx files BMP to TMX writes hold the ground of each cell - floor, the
blend overlays, kerbs and vegetation - as tile ids into the Tilesets. This
decodes them and stacks the tile images isometrically, at the game's 1x size,
so road and ground rules can be judged by eye without starting the game.
Buildings are not in the .tmx (they are placed as lots), so they are absent.
"""
from __future__ import annotations

import base64
import os
import struct
import sys
import xml.etree.ElementTree as ET
import zlib

from PIL import Image

GROUND_LAYERS = ("Floor", "FloorOverlay", "FloorOverlay2", "FloorOverlay3",
                 "FloorOverlay4", "FloorOverlay5", "FloorOverlay6", "Curbs")
FLIP_MASK = 0x1FFFFFFF


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 2
    tmx_path, out_path = args[0], args[1]
    x0, y0, w, h = (int(v) for v in args[2:6]) if len(args) >= 6 else (0, 0, 300, 300)
    trees = "--no-trees" not in argv

    root = ET.parse(tmx_path).getroot()
    tiles_dir = _tiles_dir(root, tmx_path)
    sets = []
    for ts in root.findall("tileset"):
        img = ts.find("image")
        cols = max(1, int(img.get("width")) // 64) if img is not None else 1
        sets.append((int(ts.get("firstgid")), ts.get("name"), cols))
    sets.sort()

    layers = GROUND_LAYERS + (("Vegetation",) if trees else ())
    grids = {}
    width = int(root.get("width"))
    for layer in root.findall("layer"):
        if layer.get("name") in layers:
            raw = zlib.decompress(base64.b64decode(layer.find("data").text.strip()))
            grids[layer.get("name")] = struct.unpack(f"<{len(raw) // 4}I", raw)

    sheets: dict[str, Image.Image | None] = {}
    cache: dict[int, Image.Image | None] = {}

    def tile(gid: int):
        gid &= FLIP_MASK
        if gid == 0:
            return None
        if gid in cache:
            return cache[gid]
        ts = max((s for s in sets if s[0] <= gid), default=None)
        img = None
        if ts:
            first, name, cols = ts
            if name not in sheets:
                path = os.path.join(tiles_dir, "2x", f"{name}.png")
                sheets[name] = Image.open(path).convert("RGBA") if os.path.exists(path) else None
            sheet = sheets[name]
            if sheet is not None:
                idx = gid - first
                cx, cy = (idx % cols) * 128, (idx // cols) * 256
                if cy + 256 <= sheet.height:
                    img = sheet.crop((cx, cy, cx + 128, cy + 256)).resize((64, 128), Image.LANCZOS)
        cache[gid] = img
        return img

    canvas = Image.new("RGBA", ((w + h) * 32 + 64, (w + h) * 16 + 128), (20, 22, 24, 255))
    for name in layers:
        grid = grids.get(name)
        if grid is None:
            continue
        # Back to front: rows of constant x + y.
        for s in range(w + h - 1):
            for dx in range(max(0, s - h + 1), min(w, s + 1)):
                dy = s - dx
                gid = grid[(y0 + dy) * width + (x0 + dx)]
                img = tile(gid)
                if img is None:
                    continue
                sx = (dx - dy) * 32 + h * 32
                sy = (dx + dy) * 16
                canvas.alpha_composite(img, (sx - 32 + 32, sy - 96 + 96))
    canvas.convert("RGB").save(out_path)
    print(f"wrote {out_path} ({canvas.width}x{canvas.height})")
    return 0


def _tiles_dir(root, tmx_path: str) -> str:
    img = root.find("tileset/image")
    if img is not None:
        src = os.path.normpath(os.path.join(os.path.dirname(tmx_path), img.get("source")))
        return os.path.dirname(src)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import knoxpaths
    return str(knoxpaths.mapping_tools_dir() / "Tiles")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
