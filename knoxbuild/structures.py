"""Write the bridges, overpasses and monuments generator/structures.py planned.

The renderer leaves a list of tiles, each on a storey and a layer. They go into
buildings with no rooms, one per map cell, the way fences do (see fences.py),
drawn as the building's user tiles: BuildingEd keeps a grid of those per layer
name per floor, and WorldEd lays them over the ground when it compiles the lots.
"""
from __future__ import annotations

import json
import os
from xml.sax.saxutils import escape, quoteattr

import knoxfiles

from . import catalog as C

CELL = 300


def build_structures(out_dir: str, map_name: str, bdir: str) -> tuple[list, dict]:
    from .world import Placement

    path = os.path.join(out_dir, f"{map_name}_structures.json")
    data = knoxfiles.read(path, "the bridges and monuments")
    if not data:
        return [], {"bridges": 0, "monuments": 0, "tiles": 0}
    rows = data.get("tiles") or []
    try:
        with open(os.path.join(out_dir, f"{map_name}_info.json"), encoding="utf-8") as f:
            info = json.load(f)
        width, height = info["width_tiles"], info["height_tiles"]
    except (OSError, ValueError, KeyError):
        width = height = None

    by_cell: dict[tuple[int, int], list] = {}
    for x, y, z, layer, tile in rows:
        # Only what lies on the map. A railing along the far edge of a bridge
        # at the map's bottom row stood on the tile below it - in a cell the
        # map does not have, and WorldEd refused the whole project: "error
        # reading world, invalid cell coordinates".
        if x < 0 or y < 0 or z < 0:
            continue
        if width is not None and (x >= width or y >= height):
            continue
        by_cell.setdefault((x // CELL, y // CELL), []).append((x, y, z, layer, tile))

    placements = []
    for (cx, cy), tiles in sorted(by_cell.items()):
        x0 = min(t[0] for t in tiles)
        y0 = min(t[1] for t in tiles)
        w = max(t[0] for t in tiles) - x0 + 1
        h = max(t[1] for t in tiles) - y0 + 1
        fname = f"{map_name}_structures_{cx}_{cy}.tbx"
        with open(os.path.join(bdir, fname), "w", encoding="utf-8") as f:
            f.write(render_tiles_tbx(w, h, [(x - x0, y - y0, z, layer, tile)
                                            for x, y, z, layer, tile in tiles]))
        placements.append(Placement(f"buildings/{fname}", x0, y0, w, h))
    return placements, {"bridges": data.get("bridges", 0),
                        "monuments": data.get("monuments", 0), "tiles": len(rows)}


def pack_loose(bdir: str, map_name: str, tag: str, tiles: list,
               on_top: bool = False) -> list:
    """Loose (x, y, level, layer, tile) squares written as one .tbx per cell.

    A lot spanning cells is refused by WorldEd, so they are grouped by the
    cell they fall in and each group placed at its own corner.
    """
    from .world import Placement

    by_cell: dict[tuple[int, int], list] = {}
    for t in tiles:
        by_cell.setdefault((t[0] // CELL, t[1] // CELL), []).append(t)
    placements = []
    for (cx, cy), group in sorted(by_cell.items()):
        gx0 = min(t[0] for t in group)
        gy0 = min(t[1] for t in group)
        gw = max(t[0] for t in group) - gx0 + 1
        gh = max(t[1] for t in group) - gy0 + 1
        fname = f"{map_name}_{tag}_{cx}_{cy}.tbx"
        with open(os.path.join(bdir, fname), "w", encoding="utf-8") as f:
            f.write(render_tiles_tbx(gw, gh, [(x - gx0, y - gy0, z, layer, tile)
                                              for x, y, z, layer, tile in group]))
        placements.append(Placement(f"buildings/{fname}", gx0, gy0, gw, gh,
                                    on_top=on_top))
    return placements


def render_tiles_tbx(width: int, height: int, tiles: list) -> str:
    """A building with no rooms whose floors hold only user-drawn tiles."""
    from .tbx import _roomless_tbx_header

    names = sorted({t[4] for t in tiles})
    number = {n: i + 1 for i, n in enumerate(names)}
    levels = max(t[2] for t in tiles) + 1
    grids: dict[int, dict[str, dict]] = {}
    for x, y, z, layer, tile in tiles:
        grids.setdefault(z, {}).setdefault(layer, {})[(x, y)] = number[tile]

    out = _roomless_tbx_header(width, height)
    out.append(" <user_tiles>")
    out.extend(f"  <tile tile={quoteattr(n)}/>" for n in names)
    out.append(" </user_tiles>")
    out.append(" <used_tiles>" + " ".join(str(i) for i in range(1, len(C.TILE_ENTRIES) + 1))
               + "</used_tiles>")
    out.append(" <used_furniture></used_furniture>")

    rooms = "\n" + "\n".join(",".join("0" for _ in range(width)) + ("," if y < height - 1 else "")
                             for y in range(height)) + "\n"
    # BuildingFloor's tile layers include one extra row and column for edges.
    columns, rows = width + 1, height + 1
    blank_row = ["0"] * columns
    blank_text = ",".join(blank_row)
    for z in range(levels):
        out.append(" <floor>")
        out.append("  <rooms>" + rooms + "</rooms>")
        for layer, cells in sorted(grids.get(z, {}).items()):
            text = ["\n"]
            if len(cells) * 4 <= columns * rows:
                # Bridges and props often leave most of the layer empty.
                painted = {}
                for (x, y), tile_index in cells.items():
                    if not (0 <= x < columns and 0 <= y < rows):
                        continue
                    col, row = int(x), int(y)
                    if (col, row) != (x, y):
                        continue
                    values = painted.get(row)
                    if values is None:
                        values = painted[row] = blank_row.copy()
                    values[col] = str(tile_index)
                for y in range(rows):
                    row_text = ",".join(painted[y]) if y in painted else blank_text
                    text.append(row_text + (",\n" if y < height else "\n"))
            else:
                for y in range(rows):
                    row = [str(cells.get((x, y), 0)) for x in range(columns)]
                    text.append(",".join(row) + (",\n" if y < height else "\n"))
            out.append(f'  <tiles layer={quoteattr(layer)}>' + escape("".join(text)) + "</tiles>")
        out.append(" </floor>")
    out.append("</building>")
    return "\n".join(out) + "\n"
