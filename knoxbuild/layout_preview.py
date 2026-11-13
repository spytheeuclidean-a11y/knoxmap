"""A picture of what the building step decided, to look at before compiling.

Compiling a big map takes the best part of an hour, and the settings that shape
it (spawn density, apartment share, street scale) are only judged by looking at
the result. This draws the ground, every building coloured by what it is, and
optionally how many zombies each part of the map will start with, from files
the build already wrote - so it takes a second and needs no WorldEd.
"""
from __future__ import annotations

import csv
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .bitmaps import read_rgb

MAX_SIDE = 2400

# Kinds the build makes, with fixed colours so a colour means the same thing on
# every map. Anything else gets the grey at the end.
KIND_COLOURS = {
    "house": (240, 200, 80), "apartment": (230, 120, 60), "shop": (70, 140, 230),
    "restaurant": (230, 80, 160), "shed": (170, 170, 170), "school": (90, 200, 120),
    "civic": (150, 110, 220), "church": (250, 250, 250), "medical": (230, 60, 60),
    "industrial": (110, 90, 70), "fire": (255, 120, 0), "police": (40, 70, 200),
    "fire_police": (180, 90, 140),
    "library": (120, 220, 220), "stadium": (60, 160, 90), "mall": (200, 60, 200),
}
OTHER = (200, 200, 200)

LAYERS = ("kinds", "zombies")


def _info(map_dir: str) -> tuple[str, dict]:
    name = os.path.basename(os.path.normpath(map_dir))
    with open(os.path.join(map_dir, f"{name}_info.json"), encoding="utf-8") as f:
        return name, json.load(f)


def _step(width: int, height: int) -> int:
    return max(1, -(-max(width, height) // MAX_SIDE))


def draw(map_dir: str, layer: str = "kinds") -> Image.Image:
    """The preview as a PIL image. `layer` is "kinds" (buildings by use) or
    "zombies" (buildings in outline over a heat map of the spawn map)."""
    name, info = _info(map_dir)
    width, height = info["width_tiles"], info["height_tiles"]
    step = _step(width, height)
    base = Image.fromarray(read_rgb(os.path.join(map_dir, f"{name}.bmp"), step=step))
    # Washed out: the colours drawn on top are what is being looked at.
    base = Image.blend(base, Image.new("RGB", base.size, (235, 235, 235)), 0.55)

    rows = []
    csv_path = os.path.join(map_dir, f"{name}_placements.csv")
    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    if layer == "zombies":
        spawn_path = os.path.join(map_dir, f"{name}_ZombieSpawnMap.bmp")
        if os.path.exists(spawn_path):
            # Written as a grey picture the size of the map in tenths, but
            # stored as 24-bit, so the red channel is the level.
            spawn = read_rgb(spawn_path)[:, :, 0]
            top = max(1, int(spawn.max()))
            heat = Image.fromarray((spawn.astype(np.float32) / top * 255).astype(np.uint8))
            heat = heat.resize(base.size, Image.BILINEAR)
            h = np.asarray(heat).astype(np.float32) / 255.0
            arr = np.asarray(base).astype(np.float32)
            red = np.array([220, 30, 30], dtype=np.float32)
            arr = arr * (1 - 0.8 * h[..., None]) + red * (0.8 * h[..., None])
            base = Image.fromarray(arr.astype(np.uint8))

    pen = ImageDraw.Draw(base)
    used: dict[str, int] = {}
    for r in rows:
        kind = r.get("kind") or "house"
        used[kind] = used.get(kind, 0) + 1
        x0, y0 = int(r["tile_x"]) // step, int(r["tile_y"]) // step
        x1 = max(x0 + 1, (int(r["tile_x"]) + int(r["width"])) // step)
        y1 = max(y0 + 1, (int(r["tile_y"]) + int(r["height"])) // step)
        if layer == "zombies":
            pen.rectangle([x0, y0, x1, y1], outline=(30, 30, 30))
        else:
            pen.rectangle([x0, y0, x1, y1], fill=KIND_COLOURS.get(kind, OTHER),
                          outline=(40, 40, 40))
    _legend(pen, base.size, used, layer)
    return base


def _legend(pen: ImageDraw.ImageDraw, size: tuple[int, int], used: dict,
            layer: str) -> None:
    try:
        font = ImageFont.load_default(size=max(12, size[0] // 90))
    except TypeError:                      # an older Pillow has one size only
        font = ImageFont.load_default()
    if layer == "zombies":
        items = [("more zombies = redder", (220, 30, 30), None)]
    else:
        items = [(k, KIND_COLOURS.get(k, OTHER), n)
                 for k, n in sorted(used.items(), key=lambda kv: -kv[1])]
    line = max(14, size[0] // 80)
    pad = line // 2
    pen.rectangle([pad, pad, pad + line * 12, pad * 2 + line * len(items) + pad],
                  fill=(255, 255, 255), outline=(60, 60, 60))
    for i, (label, colour, n) in enumerate(items):
        y = pad * 2 + i * line
        pen.rectangle([pad * 2, y, pad * 2 + line - 4, y + line - 4], fill=colour,
                      outline=(40, 40, 40))
        pen.text((pad * 2 + line, y - 1), label if n is None else f"{label} {n}",
                 fill=(20, 20, 20), font=font)


def render_to(map_dir: str, layer: str = "kinds") -> str:
    """Write the preview next to the map and return its path. It is drawn again
    only when something it is made from is newer."""
    if layer not in LAYERS:
        raise ValueError(f"unknown layer {layer!r}")
    name, _info_ = _info(map_dir)
    out = os.path.join(map_dir, f"{name}_layout_{layer}.png")
    sources = [os.path.join(map_dir, f"{name}{s}") for s in
               (".bmp", "_placements.csv", "_ZombieSpawnMap.bmp", "_info.json")]
    newest = max((os.path.getmtime(p) for p in sources if os.path.exists(p)),
                 default=0)
    if not os.path.exists(out) or os.path.getmtime(out) < newest:
        draw(map_dir, layer).save(out, format="PNG")
    return out
