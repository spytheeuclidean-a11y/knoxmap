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

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

import knoxfiles
import knoxstop

CELL = 300

_WORLD = re.compile(r'<world\b[^>]*\bwidth="(\d+)"[^>]*\bheight="(\d+)"')
_CELL = re.compile(r'^(\s*)<cell x="(-?\d+)" y="(-?\d+)"(.*)>\s*$')
_ENTRY = re.compile(r'^(\s*)<(lot|object)\b(.*?)/>\s*$')
_ATTR = re.compile(r'(\w+)="([^"]*)"')


def _check_building(path: Path, knoxlots: bool | None = None) -> list[str]:
    """Why a compile could not take this building file, or []. What only
    looks wrong (validate_tbx's `flaws`) is not a reason to drop it."""
    tools = Path(__file__).resolve().parent.parent / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import validate_tbx
    try:
        return validate_tbx.check(str(path), knoxlots, flaws=False)
    except Exception as exc:  # noqa: BLE001 - unreadable counts as broken
        return [f"could not be read: {exc}"]


def _check_batch(paths: list[str], knoxlots: bool) -> list[list[str]]:
    return [_check_building(Path(p), knoxlots) for p in paths]


# Each building file is read and checked before every compile: about 12 ms a
# file, so 54 minutes for a city of 270,000 on one core, with nothing on the
# screen and no way to stop it. So they are checked across every core, a few
# hundred at a time, and what was found is kept beside the map: the next
# compile reads again only the files that changed since.
CHECKED_FILE = ".buildings_checked.json"
CHECK_BATCH = 500
PARALLEL_CHECK_FROM = 300


def _checker(knoxlots: bool) -> str:
    """What the kept answers were given by: the rules and the catalogue they
    read. A change to either asks every file again."""
    h = hashlib.sha1(repr(knoxlots).encode())
    root = Path(__file__).resolve().parent.parent
    for rel in ("tools/validate_tbx.py", "knoxbuild/catalog.py"):
        try:
            h.update((root / rel).read_bytes())
        except OSError:
            pass
    return h.hexdigest()


def check_lot_files(base: Path, refs: list[str], knoxlots: bool | None = None,
                    should_stop=None, on_progress=None) -> dict[str, list[str]]:
    """{ref: why the compile cannot take it, or []} for the files a project's
    lots name, relative to `base`. `on_progress(done, total)` is told as it
    goes; a stop asked for (`should_stop`) raises knoxstop.Stopped, keeping
    what was checked by then for the next time."""
    if knoxlots is None:
        try:
            from tools.compile_map import default_backend
            knoxlots = default_backend() == "rust"
        except Exception:  # noqa: BLE001 - as validate_tbx would decide
            knoxlots = False
    key = _checker(knoxlots)
    kept_path = base / CHECKED_FILE
    try:
        with open(kept_path, encoding="utf-8") as f:
            kept = json.load(f)
        files = kept["files"] if kept.get("checker") == key else {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        files = {}

    # Size and time of every file, from one listing of each folder: asked one
    # file at a time, a city's 270,000 took nearly three minutes before the
    # first was checked.
    listed: dict[str, dict[str, list]] = {}
    for folder in {os.path.dirname(ref) for ref in refs if ref}:
        found = listed[folder] = {}
        try:
            with os.scandir(base / folder) as it:
                for entry in it:
                    if entry.is_file():
                        st = entry.stat()
                        found[entry.name] = [st.st_size, st.st_mtime_ns]
        except OSError:
            pass

    out: dict[str, list[str]] = {}
    todo: list[tuple[str, list]] = []           # (ref, [size, mtime_ns])
    for ref in refs:
        seen = listed.get(os.path.dirname(ref), {}).get(os.path.basename(ref)) if ref else None
        if seen is None and ref:
            try:                    # named in another case, say: asked directly
                st = (base / ref).stat()
                if (base / ref).is_file():
                    seen = [st.st_size, st.st_mtime_ns]
            except OSError:
                pass
        if seen is None:
            out[ref] = ["the file is missing"]
        elif not ref.lower().endswith(".tbx"):
            out[ref] = []
        else:
            was = files.get(ref)
            if isinstance(was, list) and len(was) == 3 and was[:2] == seen:
                out[ref] = was[2]
            else:
                todo.append((ref, seen))
    total = len(refs)
    done = total - len(todo)
    if on_progress:
        on_progress(done, total)

    def keep(part: list[tuple[str, list]], found: list[list[str]]) -> None:
        nonlocal done
        for (ref, seen), why in zip(part, found):
            out[ref] = why
            files[ref] = seen + [why]
        done += len(part)
        if on_progress:
            on_progress(done, total)

    try:
        if len(todo) < PARALLEL_CHECK_FROM or (os.cpu_count() or 1) < 2:
            for s in range(0, len(todo), 50):
                knoxstop.check(should_stop, "the compile")
                part = todo[s:s + 50]
                keep(part, _check_batch([str(base / r) for r, _ in part], knoxlots))
        else:
            from concurrent.futures import ProcessPoolExecutor
            pool = ProcessPoolExecutor(max_workers=os.cpu_count())
            parts = [todo[s:s + CHECK_BATCH] for s in range(0, len(todo), CHECK_BATCH)]
            pending = {pool.submit(_check_batch, [str(base / r) for r, _ in part],
                                   knoxlots): part for part in parts}
            knoxstop.gather(pool, pending, should_stop,
                            lambda fut, part: keep(part, fut.result()), "the compile")
    finally:
        if todo:
            try:
                knoxfiles.write(str(kept_path), {"checker": key, "files": {
                    r: files[r] for r in refs if r in files}})
            except OSError:
                pass            # checked again next time, that is all
    return out


def repair_project(pzw: str | os.PathLike, check_buildings: bool = True,
                   knoxlots: bool | None = None, should_stop=None,
                   on_progress=None) -> dict:
    """Repair the project in place. Returns what was done:
    {"moved": n, "dropped": [(what, why), ...], "changed": bool}.

    `should_stop` and `on_progress(done, total)` are for checking the building
    files, which is most of the time on a big map (check_lot_files)."""
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
    if check_buildings:
        refs = list(dict.fromkeys(
            dict(_ATTR.findall(body)).get("map", "")
            for key in order for _ind, kind, body in cells[key]["entries"] if kind == "lot"))
        checked = check_lot_files(base, refs, knoxlots, should_stop, on_progress)
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
                if ref not in checked:          # not checking the buildings
                    target = (base / ref) if ref else None
                    checked[ref] = [] if ref and target.is_file() else ["the file is missing"]
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
