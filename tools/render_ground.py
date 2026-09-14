"""Draw a map's ground the way the game will show it, from the real tiles.

    python tools/render_ground.py output/<map> out.png X Y W H [--no-trees] [--top]

Build 42's BMP to TMX leaves the .tmx layers empty; WorldEd turns the bitmap
into tiles while it generates the lots, using Rules.txt (colour -> tiles) and
Blends.txt (edge overlays between ground types). This repeats that - the same
rules, the same neighbour tests as BmpBlender::getBlendRule in WorldEd - and
stacks the tile images isometrically at the game's 1x size, so roads and
ground can be judged by eye without starting the game. Buildings are not
drawn. --top draws a flat top-down view instead of isometric.
"""
from __future__ import annotations

import os
import re
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _blocks(text: str, kind: str) -> list[dict]:
    out = []
    for m in re.finditer(kind + r"\s*\{(.*?)\n\}", text, re.S):
        body, fields = m.group(1), {}
        for fm in re.finditer(r"(\w+)\s*=\s*(\[.*?\]|[^\n]*)", body, re.S):
            fields[fm.group(1)] = fm.group(2).strip().strip("[]").split() \
                if fm.group(2).strip().startswith("[") else fm.group(2).strip()
        out.append(fields)
    return out


def load_rules(config: str):
    rules_txt = open(os.path.join(config, "Rules.txt"), encoding="utf-8", errors="replace").read()
    blends_txt = open(os.path.join(config, "Blends.txt"), encoding="utf-8", errors="replace").read()
    aliases = {}
    for a in _blocks(rules_txt, "alias"):
        tiles = a.get("tiles", [])
        aliases[a["name"]] = tiles if isinstance(tiles, list) else tiles.split()

    def expand(names) -> list[str]:
        names = names if isinstance(names, list) else str(names).split()
        out = []
        for n in names:
            out += aliases.get(n, [n])
        return out

    rules = []
    for r in _blocks(rules_txt, "rule"):
        colour = tuple(int(v) for v in str(r.get("color", "0 0 0")).split()[:3])
        cond = r.get("condition")
        rules.append({"bitmap": int(r.get("bitmap", 0)), "color": colour,
                      "tiles": [t for t in expand(r.get("tiles", [])) if t != "null"],
                      "layer": r.get("layer", "0_Floor"),
                      "condition": tuple(int(v) for v in cond.split()[:3]) if cond else None})
    blends = []
    for b in _blocks(blends_txt, "blend"):
        blends.append({"layer": b["layer"], "main": set(expand(b["mainTile"])),
                       "tiles": expand(b["blendTile"]), "dir": b["dir"],
                       "exclude": set(expand(b.get("exclude", [])))})
    return rules, blends


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) < 6:
        print(__doc__)
        return 2
    import numpy as np

    import knoxpaths

    out_dir, out_png = args[0], args[1]
    X, Y, W, H = (int(v) for v in args[2:6])
    name = [f for f in os.listdir(out_dir) if f.endswith("_info.json")][0][:-len("_info.json")]
    tools = knoxpaths.mapping_tools_dir()
    rules, blends = load_rules(str(tools / "config"))
    main_px = np.asarray(Image.open(os.path.join(out_dir, f"{name}.bmp")).convert("RGB"))
    veg_path = os.path.join(out_dir, f"{name}_veg.bmp")
    veg_px = np.asarray(Image.open(veg_path).convert("RGB")) if os.path.exists(veg_path) \
        and "--no-trees" not in argv else None

    by_colour: dict[tuple, list] = {}
    for r in rules:
        by_colour.setdefault(r["color"], []).append(r)

    def rand(x, y, salt=0):
        return ((x * 73856093) ^ (y * 19349663) ^ (salt * 83492791)) & 0x7FFFFFFF

    # Rules, with one tile of margin so edge blends see their neighbours.
    grids: dict[str, dict] = {}
    for y in range(Y - 1, Y + H + 1):
        for x in range(X - 1, X + W + 1):
            if not (0 <= x < main_px.shape[1] and 0 <= y < main_px.shape[0]):
                continue
            col = tuple(int(v) for v in main_px[y, x])
            for r in by_colour.get(col, []):
                if r["bitmap"] == 0 and r["tiles"]:
                    grids.setdefault(r["layer"], {})[(x, y)] = r["tiles"][rand(x, y) % len(r["tiles"])]
            if veg_px is not None:
                vcol = tuple(int(v) for v in veg_px[y, x])
                if vcol != (0, 0, 0):
                    for r in by_colour.get(vcol, []):
                        if r["bitmap"] == 1 and r["tiles"] and r["condition"] in (None, col, (0, 0, 0)):
                            grids.setdefault(r["layer"], {})[(x, y)] = \
                                r["tiles"][rand(x, y, 1) % len(r["tiles"])]

    floor = grids.get("0_Floor", {})
    layer_order = ["0_Floor"]
    for b in blends:
        if b["layer"] not in layer_order:
            layer_order.append(b["layer"])
    for x_y in [(x, y) for y in range(Y, Y + H) for x in range(X, X + W)]:
        x, y = x_y
        tile = floor.get(x_y)
        if tile is None:
            continue
        n = lambda dx, dy: floor.get((x + dx, y + dy))  # noqa: E731
        last = {}
        for b in blends:
            main = b["main"]
            if tile in main or tile in b["exclude"]:
                continue
            d = b["dir"]
            ok = {
                "n": n(0, -1) in main and n(-1, 0) not in main and n(1, 0) not in main,
                "s": n(0, 1) in main and n(-1, 0) not in main and n(1, 0) not in main,
                "e": n(1, 0) in main and n(0, -1) not in main and n(0, 1) not in main,
                "w": n(-1, 0) in main and n(0, -1) not in main and n(0, 1) not in main,
                "ne": n(0, -1) in main and n(1, 0) in main,
                "se": n(0, 1) in main and n(1, 0) in main,
                "nw": n(0, -1) in main and n(-1, 0) in main,
                "sw": n(0, 1) in main and n(-1, 0) in main,
            }.get(d, False)
            if ok:
                last[b["layer"]] = b
        for layer, b in last.items():
            grids.setdefault(layer, {})[x_y] = b["tiles"][rand(x, y, 2) % len(b["tiles"])]

    extra_layers = sorted({l for l in grids if l not in layer_order},
                          key=lambda l: (not l.startswith("0_Floor"), l))
    order = layer_order + extra_layers

    sheets: dict[str, Image.Image | None] = {}
    cache: dict[str, Image.Image | None] = {}

    def tile_image(tname: str):
        if tname in cache:
            return cache[tname]
        m = re.match(r"^(.*)_(\d+)$", tname)
        img = None
        if m:
            sheet_name, idx = m.group(1), int(m.group(2))
            if sheet_name not in sheets:
                p = tools / "Tiles" / "2x" / f"{sheet_name}.png"
                sheets[sheet_name] = Image.open(p).convert("RGBA") if p.exists() else None
            sheet = sheets[sheet_name]
            if sheet is not None:
                cx, cy = (idx % 8) * 128, (idx // 8) * 256
                if cy + 256 <= sheet.height:
                    img = sheet.crop((cx, cy, cx + 128, cy + 256)).resize((64, 128), Image.LANCZOS)
        cache[tname] = img
        return img

    top = "--top" in argv
    if top:
        canvas = Image.new("RGBA", (W * 16, H * 16), (20, 22, 24, 255))
    else:
        canvas = Image.new("RGBA", ((W + H) * 32 + 64, (W + H) * 16 + 128), (20, 22, 24, 255))
    for layer in order:
        grid = grids.get(layer, {})
        is_tall = not layer.startswith("0_Floor")
        for s in range(W + H - 1):
            for dx in range(max(0, s - H + 1), min(W, s + 1)):
                dy = s - dx
                tname = grid.get((X + dx, Y + dy))
                if not tname:
                    continue
                img = tile_image(tname)
                if img is None:
                    continue
                if top:
                    if is_tall:
                        continue
                    # The floor diamond, squashed flat into a square.
                    flat = img.crop((0, 96, 64, 128)).transform(
                        (16, 16), Image.QUAD, (0, 16, 32, 0, 64, 16, 32, 32))
                    canvas.alpha_composite(flat, (dx * 16, dy * 16))
                else:
                    sx = (dx - dy) * 32 + H * 32
                    sy = (dx + dy) * 16
                    canvas.alpha_composite(img, (sx, sy))
    canvas.convert("RGB").save(out_png)
    print(f"wrote {out_png} {canvas.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
