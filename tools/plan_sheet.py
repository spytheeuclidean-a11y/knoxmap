"""Draw every storey of a generated building side by side, plus its roof.

    python tools/plan_sheet.py out.png [kind] [width] [height] [levels] [seed] [shape]

kind is house / apartment / shop / school ...; shape is rect or L. Flats are
outlined in orange so you can see where one dwelling ends and the next
begins, the staircase is hatched on every floor it touches, and the last panel
shows the roof rectangles laid over the footprint.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw  # noqa: E402

from knoxbuild import catalog as C  # noqa: E402
from knoxbuild.layout import STAIR_RUN, build_building, roof_rects  # noqa: E402

FILL = {
    "livingroom": (196, 92, 92), "kitchen": (92, 140, 196),
    "bedroom": (150, 120, 190), "bathroom": (96, 176, 168),
    "dining": (196, 152, 84), "hall": (150, 150, 150),
    "storage": (130, 130, 100), "office": (110, 160, 110),
}
S = 16
PAD = 26


def panel(storey, stairs, title, roofs=None):
    w, h = storey.width, storey.height
    img = Image.new("RGB", (w * S + PAD * 2, h * S + PAD * 2), (30, 31, 35))
    d = ImageDraw.Draw(img)
    d.text((PAD, 6), title, fill=(225, 225, 225))

    def at(x, y):
        return storey.grid[y][x] if 0 <= x < w and 0 <= y < h else 0

    def px(x, y):
        return PAD + x * S, PAD + y * S

    for y in range(h):
        for x in range(w):
            v = at(x, y)
            if not v:
                continue
            x0, y0 = px(x, y)
            colour = (70, 70, 74) if roofs is not None else \
                FILL.get(storey.rooms[v - 1].kind, (110, 110, 110))
            d.rectangle([x0, y0, x0 + S, y0 + S], fill=colour)

    if roofs is not None:
        tints = [(160, 90, 60), (90, 120, 160), (120, 150, 80), (160, 140, 70),
                 (130, 90, 150), (80, 150, 140)]
        for n, (rx, ry, rw, rh, caps) in enumerate(roofs):
            x0, y0 = px(rx, ry)
            x1, y1 = px(rx + rw, ry + rh)
            d.rectangle([x0 + 2, y0 + 2, x1 - 2, y1 - 2], fill=tints[n % len(tints)])
            for side, line in (("cappedN", [x0, y0, x1, y0]), ("cappedS", [x0, y1, x1, y1]),
                               ("cappedW", [x0, y0, x0, y1]), ("cappedE", [x1, y0, x1, y1])):
                if caps[side]:
                    d.line(line, fill=(240, 240, 240), width=3)
        return img

    for y in range(h + 1):
        for x in range(w + 1):
            for nx, ny, line in ((x - 1, y, (0, 0, 0, S)), (x, y - 1, (0, 0, S, 0))):
                a, b = at(x, y), at(nx, ny)
                if a == b:
                    continue
                ua = storey.rooms[a - 1].unit if a else -1
                ub = storey.rooms[b - 1].unit if b else -1
                between_flats = a and b and ua != ub and ua and ub
                colour = (255, 150, 40) if between_flats else (15, 15, 15)
                x0, y0 = px(x, y)
                d.line([x0 + line[0], y0 + line[1], x0 + line[2], y0 + line[3]],
                       fill=colour, width=4 if between_flats else 3)

    for role, fx, fy, orient in storey.furniture:
        for key in C.FURNITURE[role][orient]:
            dx, dy = (int(v) for v in key.split(","))
            x0, y0 = px(fx + dx, fy + dy)
            d.rectangle([x0 + 5, y0 + 5, x0 + S - 5, y0 + S - 5], fill=(238, 236, 226))

    if stairs is not None:
        sx, sy, sd = stairs
        dx, dy = (0, 1) if sd == "N" else (1, 0)
        for i in range(STAIR_RUN):
            x0, y0 = px(sx + dx * i, sy + dy * i)
            d.rectangle([x0 + 2, y0 + 2, x0 + S - 2, y0 + S - 2], outline=(250, 250, 250))
            if 1 <= i <= 3:
                for k in range(0, S, 4):
                    d.line([x0 + 2, y0 + k, x0 + S - 2, y0 + k], fill=(250, 250, 250))

    for x, y, dirn in storey.windows:
        x0, y0 = px(x, y)
        line = [x0, y0 + 3, x0, y0 + S - 3] if dirn == "W" else [x0 + 3, y0, x0 + S - 3, y0]
        d.line(line, fill=(110, 215, 255), width=4)
    for x, y, dirn in storey.doors:
        x0, y0 = px(x, y)
        line = [x0, y0 + 2, x0, y0 + S - 2] if dirn == "W" else [x0 + 2, y0, x0 + S - 2, y0]
        d.line(line, fill=(255, 215, 50), width=5)
    return img


def main(argv):
    out = argv[1]
    kind = argv[2] if len(argv) > 2 else "apartment"
    w = int(argv[3]) if len(argv) > 3 else 24
    h = int(argv[4]) if len(argv) > 4 else 18
    levels = int(argv[5]) if len(argv) > 5 else 3
    seed = int(argv[6]) if len(argv) > 6 else 7
    shape = argv[7] if len(argv) > 7 else "rect"
    mask = None
    if shape == "L":
        mask = [[not (y < h // 2 and x >= w - w // 2) for x in range(w)] for y in range(h)]
    b = build_building(w, h, levels=levels, seed=seed, mask=mask,
                       kind=None if kind == "house" else kind,
                       commercial=kind not in ("house", "apartment"))
    panels = []
    for lvl, storey in enumerate(b.storeys):
        flats = len({r.unit for r in storey.rooms if r.unit})
        stairs = b.stairs[lvl] if lvl < len(b.stairs) else \
            (b.stairs[lvl - 1] if lvl and lvl - 1 < len(b.stairs) else None)
        title = (f"floor {lvl}: {len(storey.rooms)} rooms, {len(storey.windows)} windows"
                 + (f", {flats} flats" if flats > 1 else ""))
        panels.append(panel(storey, stairs, title))
    top = b.storeys[-1]
    rects = roof_rects(top.grid)
    panels.append(panel(top, None, f"roof: {len(rects)} rectangle(s)", roofs=rects))

    width = sum(p.width for p in panels)
    height = max(p.height for p in panels) + 34
    sheet = Image.new("RGB", (width, height), (22, 23, 26))
    x = 0
    for p in panels:
        sheet.paste(p, (x, 0))
        x += p.width
    d = ImageDraw.Draw(sheet)
    legend = [("living", FILL["livingroom"]), ("kitchen", FILL["kitchen"]),
              ("bedroom", FILL["bedroom"]), ("bath", FILL["bathroom"]),
              ("dining", FILL["dining"]), ("hall", FILL["hall"]),
              ("door", (255, 215, 50)), ("window", (110, 215, 255)),
              ("wall between flats", (255, 150, 40))]
    lx = 10
    for label, colour in legend:
        d.rectangle([lx, height - 24, lx + 12, height - 12], fill=colour)
        d.text((lx + 16, height - 25), label, fill=(210, 210, 210))
        lx += 26 + 7 * len(label)
    sheet.save(out)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
