"""Dependency checks for a knoxlots recompile after editing building files."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import PIL
import numpy as np

import knoxfiles
import knoxlog
import knoxstop
from knoxbuild.buildtiles import compose_lots, parse_tbx
from tools import map_source

CACHE = ".knoxlots-cells.json"

# Ignore only WorldEd placement lines parsed by map_source.read_lots.
LOT_LINE = re.compile(
    rb'(?m)^[ \t]*<lot x="[0-9]+" y="[0-9]+" level="-?[0-9]+" width="[0-9]+" '
    rb'height="[0-9]+" map="buildings/[^"\r\n]+\.tbx"/>[ \t]*(?:\r?\n|$)'
)

# Code and data shared by all cells. Changes to these or to the project
# geometry/terrain take the full path.
COMPILER_FILES = (
    "tools/compile_map.py", "tools/compile_cells.py", "tools/map_source.py",
    "tools/terrain_source.py", "tools/native_source.py", "knoxbuild/bitmaps.py", "knoxbuild/blends.py",
    "knoxbuild/buildheader.py", "knoxbuild/buildtiles.py", "knoxbuild/buildroofs.py",
    "knoxbuild/kcell.py", "knoxbuild/rules.py", "knoxbuild/terrain.py",
    "generator/pz_colors.py",
)


def digest(p):
    try:
        with p.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()
    except FileNotFoundError:
        return None


def lot_paths(folder):
    return (p for p in folder.iterdir()
            if p.name.endswith(".lotheader") or
            (p.name.startswith("world_") and p.name.endswith(".lotpack")) or
            (p.name.startswith("chunkdata_") and p.name.endswith(".bin")))


def lot_hashes(folder):
    return {p.name: digest(p) for p in lot_paths(folder)}


def cells_from_sources(src):
    return {tuple(map(int, p.stem.split("_")[1:])) for p in src.glob("cell_*.kcell")}


def lot_names(cells):
    return {name for x, y in cells for name in
            (f"{x}_{y}.lotheader", f"world_{x}_{y}.lotpack", f"chunkdata_{x}_{y}.bin")}


def moved_buildings(before, after):
    old, new = Counter(before), Counter(after)
    moved = {lot[0] for lot in (old - new).keys() | (new - old).keys()}
    # Relative order can change the output when lots overlap.
    if ([lot for lot in before if lot[0] not in moved]
            != [lot for lot in after if lot[0] not in moved]):
        return None
    return moved


class CellCache:
    def __init__(self, project, exe, root, reuse, should_stop):
        self.native_exe = None
        self.project = project
        self.should_stop = should_stop
        self.extras = [exe, *(root / p for p in COMPILER_FILES)]
        rules = Path(map_source.rules_path())
        self.extras += [rules, rules.with_name("Blends.txt")]
        self.pzw = project / (project.name + ".pzw")
        layout = self.pzw.read_bytes()
        self.pzw_hash = hashlib.sha256(layout).hexdigest()
        self.guard = self._guard(layout)
        from tools.terrain_source import project_origin
        ox, oy = project_origin(str(project))
        bmp = project / (project.name + ".bmp")
        w, h = map_source.bitmaps._bmp_header(str(bmp))[:2]
        side = map_source.SIDE
        self.all_cells = {(x, y) for y in range(oy // side, (oy + h - 1) // side + 1)
                          for x in range(ox // side, (ox + w - 1) // side + 1)}
        self.all_rows = {str(y) for _, y in self.all_cells}
        self.lots = map_source.read_lots(str(project))
        self.inputs = self._building_hashes()
        self.state = None
        self.partial = False
        self.changed = set()
        if reuse:
            try:
                prior = json.loads((project / CACHE).read_text(encoding="utf-8"))
                if (prior["guard"] == self.guard and prior["inputs"].keys() == self.inputs.keys()
                        and lot_names(self.all_cells) == prior["outputs"].keys()
                        and lot_hashes(project / "lots") == prior["outputs"]
                        and isinstance(prior["rooms"], dict)
                        and self._valid_footprints(prior["footprints"])):
                    moved = moved_buildings([tuple(lot) for lot in prior["lots"]], self.lots)
                    if moved is not None:
                        self.state = prior
                        self.changed = moved | {t for t in self.inputs
                                                if self.inputs[t] != prior["inputs"][t]}
            except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
                pass

    def _guard(self, layout):
        name = self.project.name
        paths = [self.project / (name + suffix) for suffix in
                 (".bmp", "_veg.bmp", "_ZombieSpawnMap.bmp")]
        layout_hash = hashlib.sha256(LOT_LINE.sub(b"", layout)).hexdigest()
        return [knoxlog.version(), sys.version, np.__version__, PIL.__version__, layout_hash,
                *(digest(p) for p in paths + self.extras)]

    def _valid_footprints(self, footprints):
        return (footprints.keys() == self.all_rows
                and all(isinstance(row, dict) and all(
                    name in self.inputs and isinstance(cols, list) and all(
                        type(x) is int and (x, int(y)) in self.all_cells for x in cols)
                    for name, cols in row.items())
                    for y, row in footprints.items()))

    def _building_hashes(self):
        inputs = {}
        for t, *_ in self.lots:
            if t not in inputs:
                knoxstop.check(self.should_stop, "the compile")
                inputs[t] = digest(self.project / "buildings" / (t + ".tbx"))
        return inputs

    def verify_inputs(self):
        layout = self.pzw.read_bytes()
        if (hashlib.sha256(layout).hexdigest() != self.pzw_hash
                or self.guard != self._guard(layout) or self.inputs != self._building_hashes()):
            raise RuntimeError("The map changed during compilation. Compile it again.")

    def select(self, room_rows, origin, size):
        ox, oy = origin
        w, h = size
        side, margin = map_source.SIDE, map_source.MARGIN
        self.rooms = {str(cy): {str(cx): hashlib.sha256(
            json.dumps(placed, sort_keys=True).encode("utf-8")).hexdigest()
            for cx, placed in columns.items()} for cy, columns in room_rows.items()}
        if self.state is None:
            return None
        old_rooms = self.state["rooms"]
        dirty = set()
        for cy in old_rooms.keys() | self.rooms.keys():
            a, b = old_rooms.get(cy, {}), self.rooms.get(cy, {})
            dirty.update((int(cx), int(cy)) for cx in a.keys() | b.keys() if a.get(cx) != b.get(cx))
        for cy, row in self.state["footprints"].items():
            for name in self.changed:
                dirty.update((cx, int(cy)) for cx in row.get(name, ()))

        # Collect the new footprint using the same room and tile coordinates
        # as the compositor, including furniture outside the building rectangle.
        if self.native_exe:
            from tools.native_source import changed_cells
            dirty.update(changed_cells(self.native_exe, self.project,
                                       (lot for lot in self.lots if lot[0] in self.changed),
                                       origin, margin, self.should_stop))
        else:
            dirty.update(self._changed_cells(origin, side, margin))

        self.partial = True
        selection = {}
        for cx, cy in sorted(dirty):
            if ox // side <= cx <= (ox + w - 1) // side and oy // side <= cy <= (oy + h - 1) // side:
                selection.setdefault(cy, []).append(cx)
        self.selected = {(cx, cy) for cy, columns in selection.items() for cx in columns}
        return selection

    def _changed_cells(self, origin, side, margin):
        ox, oy = origin
        reach = {}
        for t, tx, ty, base, _w, _h in self.lots:
            if t not in self.changed:
                continue
            knoxstop.check(self.should_stop, "the compile")
            if t not in reach:
                b = parse_tbx((self.project / "buildings" / (t + ".tbx")).read_text(encoding="utf-8"))
                points = set()
                compose_lots([(b, 0, 0, 0)], lambda _, xy: points.update(xy))
                reach[t] = b.height, points
            height, points = reach[t]
            for x, y in points:
                cy = (ty + y + oy) // side
                wy0 = cy * side - oy
                if ty - margin < wy0 + side + margin and ty + height + margin > wy0 - margin:
                    yield (tx + x + ox) // side, cy

    def save(self, src, outputs):
        if not hasattr(self, "rooms"):
            return  # resumed after all rows were already finished
        footprints = dict(self.state["footprints"]) if self.partial else {}
        for path in src.glob("footprints_*.json"):
            footprints[path.stem.split("_")[1]] = json.loads(path.read_text(encoding="utf-8"))
        if not self._valid_footprints(footprints):
            return
        try:
            knoxfiles.write(str(self.project / CACHE), {
                "guard": self.guard, "inputs": self.inputs, "outputs": outputs,
                "lots": self.lots, "rooms": self.rooms, "footprints": footprints,
            })
        except OSError:
            pass  # compilation succeeded; no dependency cache means a full recompile
