"""Visual check: building placement over the map, and a floor plan close-up.

    python tools/preview_buildings.py output/<map> [tbx_index]

Writes <map>_buildings_overlay.png and <map>_floorplan.png.
"""
from __future__ import annotations

import csv
import json
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knoxbuild import catalog as C  # noqa: E402
from knoxbuild.layout import build_building  # noqa: E402

ROOM_FILL = {
    "livingroom": (196, 92, 92), "kitchen": (92, 140, 196),
    "bedroom": (150, 120, 190), "bathroom": (96, 176, 168),
    "dining": (196, 152, 84), "hall": (150, 150, 150),
    "storage": (130, 130, 100), "office": (110, 160, 110),
}


def overlay(out_dir: str, map_name: str) -> str:
    src = os.path.join(out_dir, f"{map_name}_preview.png")
    img = Image.open(src).convert("RGB")
    base = Image.open(os.path.join(out_dir, f"{map_name}.bmp"))
    sx = img.width / base.width
    sy = img.height / base.height

    d = ImageDraw.Draw(img)
    with open(os.path.join(out_dir, f"{map_name}_placements.csv"),
              encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        x0 = int(r["tile_x"]) * sx
        y0 = int(r["tile_y"]) * sy
        x1 = (int(r["tile_x"]) + int(r["width"])) * sx
        y1 = (int(r["tile_y"]) + int(r["height"])) * sy
        color = (255, 170, 40) if r["commercial"] == "1" else (255, 70, 70)
        d.rectangle([x0, y0, x1, y1], outline=color, width=1)

    dst = os.path.join(out_dir, f"{map_name}_buildings_overlay.png")
    img.save(dst)
    return dst


def floorplan(out_dir: str, map_name: str, index: int, level: int = 0,
              scale: int = 18) -> str:
    with open(os.path.join(out_dir, f"{map_name}_placements.csv"),
              encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    row = rows[index]
    w, h = int(row["width"]), int(row["height"])
    # Rebuild the same plan: seed is 1 + the feature index in the filename.
    # Pass the recorded kind too, or the preview shows a generic house where
    # the map actually holds a school - which made it useless for judging how
    # the special buildings turned out.
    feat_i = int(row["file"].rsplit("_", 1)[1].split(".")[0])
    kind = row.get("kind") or "house"
    building = build_building(
        w, h, levels=int(row.get("levels") or 1),
        commercial=row["commercial"] == "1", seed=1 + feat_i,
        kind=None if kind == "house" else kind)
    plan = building.storeys[min(level, len(building.storeys) - 1)]

    pad = scale
    img = Image.new("RGB", (w * scale + pad * 2, h * scale + pad * 2),
                    (28, 28, 32))
    d = ImageDraw.Draw(img)

    def px(x: int, y: int) -> tuple[float, float]:
        return pad + x * scale, pad + y * scale

    for y in range(h):
        for x in range(w):
            idx = plan.grid[y][x]
            kind = plan.rooms[idx - 1].kind if idx else "hall"
            x0, y0 = px(x, y)
            d.rectangle([x0, y0, x0 + scale, y0 + scale],
                        fill=ROOM_FILL.get(kind, (90, 90, 90)))

    # Walls: every tile edge where the room index changes, plus the perimeter.
    def room_at(x: int, y: int) -> int:
        if 0 <= x < w and 0 <= y < h:
            return plan.grid[y][x]
        return 0

    for y in range(h + 1):
        for x in range(w + 1):
            if room_at(x, y) != room_at(x - 1, y):   # west edge
                x0, y0 = px(x, y)
                d.line([x0, y0, x0, y0 + scale], fill=(20, 20, 20), width=3)
            if room_at(x, y) != room_at(x, y - 1):   # north edge
                x0, y0 = px(x, y)
                d.line([x0, y0, x0 + scale, y0], fill=(20, 20, 20), width=3)

    for x, y, direction in plan.windows:
        x0, y0 = px(x, y)
        if direction == "W":
            d.line([x0, y0 + 3, x0, y0 + scale - 3], fill=(120, 220, 255), width=3)
        else:
            d.line([x0 + 3, y0, x0 + scale - 3, y0], fill=(120, 220, 255), width=3)

    for x, y, direction in plan.doors:
        x0, y0 = px(x, y)
        if direction == "W":
            d.line([x0, y0 + 2, x0, y0 + scale - 2], fill=(255, 220, 60), width=4)
        else:
            d.line([x0 + 2, y0, x0 + scale - 2, y0], fill=(255, 220, 60), width=4)

    for role, x, y, orient in plan.furniture:
        for key in C.FURNITURE[role][orient]:
            dx, dy = (int(v) for v in key.split(","))
            x0, y0 = px(x + dx, y + dy)
            d.rectangle([x0 + 4, y0 + 4, x0 + scale - 4, y0 + scale - 4],
                        fill=(245, 245, 235))

    suffix = f"_L{level}" if level else ""
    dst = os.path.join(out_dir, f"{map_name}_floorplan{suffix}.png")
    img.save(dst)
    return dst, row, plan


def main(argv: list[str]) -> int:
    out_dir = argv[1]
    idx = int(argv[2]) if len(argv) > 2 else 0
    level = int(argv[3]) if len(argv) > 3 else 0
    name = [f for f in os.listdir(out_dir) if f.endswith("_info.json")][0]
    map_name = name[: -len("_info.json")]
    a = overlay(out_dir, map_name)
    b, row, plan = floorplan(out_dir, map_name, idx, level)
    print("wrote", a)
    print("wrote", b)
    print(f"floor plan: {row['name']} {row['width']}x{row['height']} "
          f"{row.get('kind', '?')}, storey {level} of {row.get('levels', 1)}, "
          f"{len(plan.rooms)} rooms, {len(plan.furniture)} furniture, "
          f"{len(plan.windows)} windows")
    print("rooms:", [(r.kind, f"{r.w}x{r.h}") for r in plan.rooms])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
