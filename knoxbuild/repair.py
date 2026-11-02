"""Make a WorldEd project safe to compile, whatever wrote it.

WorldEd refuses a whole project over a single bad entry - "error reading
world, invalid cell coordinates" for one fence past the map's edge, or a
building file it cannot read - and a town that took half an hour to build
then cannot be compiled at all. Every such problem found so far was at a
boundary: something one tile past the edge of the map or of its cell.

So before each compile, repair_project() reads the .pzw and fixes what can be
fixed and drops what cannot, instead of letting one entry stop the map:

* a lot or zone whose offset runs past its cell moves to the cell it is really
  in;
* anything in a cell outside the world is moved in if its tiles are on the
  map, and dropped if they are not;
* a lot whose building file is missing, unreadable or breaks BuildingEd's
  rules is dropped;
* a lot or zone with no size is dropped.

It works on the text the project was written as, line by line, so what it
leaves alone is byte for byte what was there. What it changed is written to
the log, and the original is kept as <map>.pzw.bak.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

CELL = 300

_WORLD = re.compile(r'<world\b[^>]*\bwidth="(\d+)"[^>]*\bheight="(\d+)"')
_CELL = re.compile(r'^(\s*)<cell x="(-?\d+)" y="(-?\d+)"(.*)>\s*$')
_ENTRY = re.compile(r'^(\s*)<(lot|object)\b(.*?)/>\s*$')
_ATTR = re.compile(r'(\w+)="([^"]*)"')


def _check_building(path: Path, knoxlots: bool | None = None) -> list[str]:
    tools = Path(__file__).resolve().parent.parent / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import validate_tbx
    return validate_tbx.check(str(path), knoxlots)


def repair_project(pzw: str | os.PathLike, check_buildings: bool = True,
                   knoxlots: bool | None = None) -> dict:
    """Repair the project in place. Returns what was done:
    {"moved": n, "dropped": [(what, why), ...], "changed": bool}."""
    path = Path(pzw)
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        text = f.read()
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    size = _WORLD.search(text)
    report = {"moved": 0, "dropped": [], "changed": False}
    if not size:
        return report
    width, height = int(size.group(1)), int(size.group(2))

    head: list[str] = []
    tail: list[str] = []
    cells: dict[tuple[int, int], dict] = {}     # (cx, cy) -> {"open": line, "entries": [...]}
    order: list[tuple[int, int]] = []
    current = None
    seen_cell = False
    for line in lines:
        m = _CELL.match(line)
        if m:
            seen_cell = True
            key = (int(m.group(2)), int(m.group(3)))
            rest = m.group(4)
            empty = rest.rstrip().endswith("/")
            if empty:
                rest = rest.rstrip()[:-1].rstrip()
            if key not in cells:
                cells[key] = {"indent": m.group(1), "rest": rest, "entries": []}
                order.append(key)
            current = None if empty else key
            continue
        if current is not None:
            if line.strip() == "</cell>":
                current = None
                continue
            e = _ENTRY.match(line)
            if e:
                cells[current]["entries"].append((e.group(1), e.group(2), e.group(3)))
                continue
            cells[current]["entries"].append((None, None, line))   # anything else, kept
            continue
        (tail if seen_cell else head).append(line)

    base = path.parent
    checked: dict[str, list[str]] = {}
    placed: dict[tuple[int, int], list] = {k: [] for k in order}

    def on_map(cx, cy):
        return 0 <= cx < width and 0 <= cy < height

    for key in order:
        cx, cy = key
        for indent, kind, body in cells[key]["entries"]:
            if kind is None:
                if on_map(cx, cy):
                    placed[key].append((indent, kind, body))
                continue
            attrs = dict(_ATTR.findall(body))
            label = attrs.get("map") or attrs.get("group") or kind
            try:
                x, y = int(attrs.get("x", 0)), int(attrs.get("y", 0))
                w, h = int(attrs.get("width", 1)), int(attrs.get("height", 1))
            except ValueError:
                report["dropped"].append((label, "coordinates are not numbers"))
                continue
            if w <= 0 or h <= 0:
                report["dropped"].append((label, f"size {w}x{h}"))
                continue
            # Where it really is, in tiles of the whole map.
            tx, ty = cx * CELL + x, cy * CELL + y
            if not (0 <= tx < width * CELL and 0 <= ty < height * CELL):
                report["dropped"].append((label, f"at tile {tx},{ty}, outside the "
                                                 f"{width * CELL}x{height * CELL} map"))
                continue
            if kind == "lot":
                ref = attrs.get("map", "")
                if ref not in checked:
                    target = (base / ref) if ref else None
                    if not ref or not target.is_file():
                        checked[ref] = ["the file is missing"]
                    elif check_buildings and ref.lower().endswith(".tbx"):
                        try:
                            checked[ref] = _check_building(target, knoxlots)
                        except Exception as exc:  # noqa: BLE001 - unreadable counts as broken
                            checked[ref] = [f"could not be read: {exc}"]
                    else:
                        checked[ref] = []
                if checked[ref]:
                    report["dropped"].append((label, "; ".join(checked[ref][:2])))
                    continue
            ncx, ncy = tx // CELL, ty // CELL
            if (ncx, ncy) != key:
                report["moved"] += 1
                body = re.sub(r'\bx="-?\d+"', f'x="{tx - ncx * CELL}"', body, count=1)
                body = re.sub(r'\by="-?\d+"', f'y="{ty - ncy * CELL}"', body, count=1)
            placed.setdefault((ncx, ncy), []).append((indent, kind, body))

    if not report["moved"] and not report["dropped"] and all(on_map(*k) for k in order):
        return report

    out = list(head)
    indent = cells[order[0]]["indent"] if order else " "
    for key in sorted({k for k in placed if on_map(*k)} | {k for k in order if on_map(*k)}):
        info = cells.get(key, {"indent": indent, "rest": ' map=""'})
        out.append(f'{info["indent"]}<cell x="{key[0]}" y="{key[1]}"{info["rest"]}>')
        for ind, kind, body in placed.get(key, []):
            out.append(body if kind is None else f"{ind}<{kind}{body}/>")
        out.append(f'{info["indent"]}</cell>')
    out.extend(tail)

    shutil.copyfile(path, path.with_name(path.name + ".bak"))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(newline.join(out) + newline)
    report["changed"] = True
    return report
