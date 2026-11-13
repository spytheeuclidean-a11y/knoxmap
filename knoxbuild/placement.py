"""Where a map stands in the game's world, chosen rather than guessed.

Project Zomboid's world is one grid shared by every map installed. Knox County
sits in the corner of it, and KnoxMap has always dropped a generated map east
of the vanilla map and east again of any other KnoxMap map already installed
(knoxbuild/world.py, choose_origin), which keeps maps from landing on top of
each other and is the one thing nobody gets to decide: whether the new town is
north of Louisville or two counties west of it, whether two of your own maps
sit side by side as one sprawl or at opposite ends of the world.

This is that decision, handed over. A place chosen here is remembered beside
the map (`placement.json`) and the build uses it instead of packing the map in
automatically.

Moving one that is already built is three small rewrites, because everything
in the project is written relative to its own corner and the world origin is
added at the end:

    the .pzw    <worldOrigin origin="x,y"/>, in 300-tile cells
    worldmap.xml   <cell x= y=>, the same cells; its points are cell-relative
    streets.xml and worldmap-annotations.lua   world tiles

and then the map has to be compiled again, because the compiled files are
named for the 256-tile cells they land in and 300 does not divide into 256.
With the Rust compiler that is a minute on a map that took an hour to build,
which is why choosing the place afterwards is worth doing at all.
"""
from __future__ import annotations

import json
import os
import re

import knoxfiles

from .world import CELL_SIZE, _installed_boxes, _project_box

# Knox County, in 300-tile cells. The vanilla map is 78 x 63 compiled cells of
# 256 tiles - 19968 x 16128 tiles - which is 67 x 54 cells of 300.
VANILLA_BOX = (0, 0, 67, 54)
VANILLA_NAME = "Knox County (the vanilla map)"
# How far out a map may be put. The game holds a grid covering every cell any
# map uses, so a map parked at cell 10,000 is a world almost entirely of
# nothing, and the paper map draws the town as a speck in the corner of it.
MAX_CELL = 400

PLACEMENT_FILE = "placement.json"
LOT_NAME = re.compile(r"^(?:world_)?(?:.*?_)?(\d+)_(\d+)\.(lotheader|lotpack)$")


def saved(out_dir: str) -> tuple[int, int] | None:
    """The place chosen for this map, or None while it is packed in for you."""
    try:
        with open(os.path.join(out_dir, PLACEMENT_FILE), encoding="utf-8") as f:
            data = json.load(f)
        return int(data["cell_x"]), int(data["cell_y"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def standalone(out_dir: str) -> bool:
    """Whether this map is built to be played without Knox County."""
    try:
        with open(os.path.join(out_dir, PLACEMENT_FILE), encoding="utf-8") as f:
            return json.load(f).get("standalone") is True
    except (OSError, ValueError, AttributeError):
        return False


def save(out_dir: str, cells, standalone_flag: bool | None = None) -> tuple[int, int]:
    """Remember the place chosen; the standalone choice is kept unless one is given."""
    x, y = clamp(cells)
    keep = standalone(out_dir) if standalone_flag is None else bool(standalone_flag)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, PLACEMENT_FILE)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"cell_x": x, "cell_y": y, "standalone": keep}, f)
    os.replace(tmp, path)
    return x, y


def set_standalone(out_dir: str, map_name: str, on: bool) -> dict:
    """Make the map standalone, or take it back to sharing the world.

    A standalone map is the only one in its world, so it goes to the corner,
    cell 0,0, where the world is smallest. Taking it back leaves it where it
    stands: the player picks a new place, or has one picked for them."""
    if on:
        save(out_dir, (0, 0), standalone_flag=True)
        return move(out_dir, map_name, (0, 0), remember=False)
    here = where_is(out_dir, map_name, automatic=False)
    where, was = here["cell"] or (0, 0), here["built"]
    save(out_dir, where, standalone_flag=False)
    # Standing it back down leaves it parked where standalone put it, but the
    # lots in `lots/` are named for wherever it was last compiled - cell 0,0 is
    # not where they are - so this is the same question `move` asks, and not a
    # "no" written down here. Install refuses a map whose lots name another
    # place as "moved since it was last compiled", and said so however often it
    # was compiled again.
    return {"origin": list(where), "was": list(was) if was else None, "rewrote": [],
            "needsBuild": False, "needsCompile": not lots_match(out_dir, where)}


def forget(out_dir: str) -> bool:
    """Back to being packed in beside whatever else is installed."""
    try:
        os.remove(os.path.join(out_dir, PLACEMENT_FILE))
        return True
    except OSError:
        return False


def clamp(cells) -> tuple[int, int]:
    # A string is a sequence too, and "70,0" read as a pair of items is cell
    # 7,0 - a map quietly put somewhere nobody asked for, on top of Knox
    # County. Only a real pair of numbers is a place.
    if isinstance(cells, (str, bytes)) or not isinstance(cells, (list, tuple))             or len(cells) != 2:
        raise ValueError("A place is two whole numbers: the cell across and down.")
    try:
        x, y = int(cells[0]), int(cells[1])
    except (TypeError, ValueError):
        raise ValueError("A place is two whole numbers: the cell across and down.")
    if not (0 <= x <= MAX_CELL and 0 <= y <= MAX_CELL):
        raise ValueError(f"A map goes between cell 0 and cell {MAX_CELL}; "
                         f"further out is a world of empty grid.")
    return x, y


def project_origin(out_dir: str, map_name: str) -> tuple[int, int] | None:
    """Where the project on disk was last built, from its .pzw."""
    box = _project_box(os.path.join(out_dir, f"{map_name}.pzw"))
    return (box[0], box[1]) if box else None


def project_size(out_dir: str, map_name: str) -> tuple[int, int]:
    """How many cells across and down this map is."""
    box = _project_box(os.path.join(out_dir, f"{map_name}.pzw"))
    if box:
        return box[2], box[3]
    try:
        with open(os.path.join(out_dir, f"{map_name}_info.json"),
                  encoding="utf-8") as f:
            info = json.load(f)
        return int(info.get("cells_x") or 0), int(info.get("cells_y") or 0)
    except (OSError, ValueError, TypeError):
        return 0, 0


def compiled_corner(out_dir: str) -> tuple[int, int] | None:
    """The north-west compiled cell on disk, or None if nothing is compiled.

    Compiled files are named for the 256-tile cell they hold, so this is what
    says where the lots in `lots/` actually are - whatever the project now
    says about where the map should be.
    """
    lots = os.path.join(out_dir, "lots")
    found = []
    try:
        entries = os.listdir(lots)
    except OSError:
        return None
    for entry in entries:
        m = LOT_NAME.match(entry)
        if m:
            found.append((int(m.group(1)), int(m.group(2))))
    if not found:
        return None
    return min(c[0] for c in found), min(c[1] for c in found)


def lots_match(out_dir: str, cells: tuple[int, int] | None) -> bool:
    """Do the compiled lots sit where the map is now meant to be?

    False means the map has been moved since it was compiled, so installing it
    as it stands would ship cells under one set of names and a paper map and
    spawn points pointing somewhere else.
    """
    corner = compiled_corner(out_dir)
    if corner is None or cells is None:
        return True
    tx, ty = cells[0] * CELL_SIZE, cells[1] * CELL_SIZE
    return corner == (tx // 256, ty // 256)


def where_is(out_dir: str, map_name: str, automatic: bool = True) -> dict:
    """Where this map stands, and which record says so - the one answer.

    Three things know where a map is: the place chosen for it
    (`placement.json`), the world origin its own `.pzw` was last built with, and
    the names of the compiled lots in `lots/`. They disagree, by design - a map
    moved after it was compiled has lots naming the old place, and one that has
    never been compiled has none at all - but each caller used to read them
    itself, in its own order. That is how one of them could believe the map was
    at 70,0 while another read 0,0, and why install refused a map as "moved
    since it was last compiled" while the window said it was ready.

        chosen     what the player picked (standalone parks at 0,0)
        built      what the project itself was last built at
        automatic  a free cell, when neither of those says anything
        compiled   where the lots really are, in compiled cells
        matches    whether the lots are where the map is going

    Every caller asks this instead of reading the three, so there is one order
    of precedence rather than four.
    """
    from .world import choose_origin

    width, height = project_size(out_dir, map_name)
    chosen = saved(out_dir)
    built = project_origin(out_dir, map_name)
    cell = chosen or built
    if cell is None and automatic:
        cell = choose_origin(out_dir, width, height)
    return {
        "cell": cell,
        "chosen": chosen,
        "built": built,
        "source": "chosen" if chosen else "built" if built else "automatic",
        "size": (width, height),
        "compiled": compiled_corner(out_dir),
        "matches": lots_match(out_dir, cell),
    }


# ---- the world as it really is ----------------------------------------------
#
# Boxes are enough to put a map somewhere, and not enough to see what you are
# putting it next to: Knox County is not a rectangle, it is 4,065 cells with
# bites out of it, and the vanilla world is eight maps rather than one. These
# read the cells on disk - the game's own folders and every map installed -
# and hand the window their real shape.

COMPILED_CELL = 256
CELL_NAME = re.compile(r"^(\d+)_(\d+)\.lotheader$")
TILE_NAME = re.compile(r"(\d+)/tile(\d+)x(\d+)\.png")


def _cells_of(folder: str) -> list[tuple[int, int]]:
    """Every compiled cell in a map folder, from the names of its headers."""
    out = []
    try:
        entries = os.listdir(folder)
    except OSError:
        return out
    for entry in entries:
        m = CELL_NAME.match(entry)
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return out


def _runs(cells: list[tuple[int, int]]) -> list[list[int]]:
    """Cells as [row, first, last] runs: a map's shape without listing every
    one of its four thousand cells."""
    by_row: dict[int, list[int]] = {}
    for x, y in cells:
        by_row.setdefault(y, []).append(x)
    out = []
    for y in sorted(by_row):
        xs = sorted(by_row[y])
        start = last = xs[0]
        for x in xs[1:]:
            if x == last + 1:
                last = x
                continue
            out.append([y, start, last])
            start = last = x
        out.append([y, start, last])
    return out


def _map_folder(folder: str, kind: str, name: str) -> dict | None:
    cells = _cells_of(folder)
    if not cells:
        return None
    x0 = min(c[0] for c in cells)
    y0 = min(c[1] for c in cells)
    return {"name": name, "kind": kind, "cells": len(cells),
            "x": x0, "y": y0,
            "w": max(c[0] for c in cells) - x0 + 1,
            "h": max(c[1] for c in cells) - y0 + 1,
            "runs": _runs(cells)}


# The game draws its own map from a pyramid of tiles shipped beside it:
#
#     media/maps/<map>/pyramid.zip
#         pyramid.txt   VERSION=1 / bounds=0 0 19968 16128 / imageSize=...
#         <level>/tile<x>x<y>.png    256 px tiles, each level half the one
#                                    before it
#
# so the picture of Knox County - and of any installed map that ships one -
# can be put on the world exactly where it belongs, instead of a grey box the
# shape of its cells. It is the player's own copy of the game being read, and
# the picture never leaves their PC: it is assembled into the app's cache and
# shown in the window.
PYRAMID = "pyramid.zip"
PICTURE_MAX_PX = 1600          # a world picture bigger than this is wasted


def safe_file(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "map"


def _map_folders():
    """(folder, kind, name) for every map on this PC: the game's own first."""
    try:
        import knoxpaths
    except Exception:                       # noqa: BLE001 - no paths, no world
        return
    try:
        media = knoxpaths.pz_media_dir()
    except Exception:                       # noqa: BLE001
        media = None
    if media:
        maps = os.path.join(str(media), "maps")
        if os.path.isdir(maps):
            for entry in sorted(os.listdir(maps)):
                yield os.path.join(maps, entry), "vanilla", entry
    try:
        mods = knoxpaths.zomboid_user_dir() / "mods"
    except Exception:                       # noqa: BLE001
        return
    if mods.is_dir():
        for folder in sorted(mods.glob("*/common/media/maps/*")):
            yield str(folder), "installed", folder.name


def _pyramid_bounds(text: str) -> tuple[int, int, int, int] | None:
    """The world tiles a pyramid covers, from its own pyramid.txt."""
    for line in text.splitlines():
        if line.startswith("bounds="):
            parts = line.split("=", 1)[1].split()
            if len(parts) == 4:
                try:
                    return tuple(int(float(v)) for v in parts)   # type: ignore
                except ValueError:
                    return None
    return None


def build_picture(folder: str, into: str) -> dict | None:
    """Assemble a map's picture from the smallest level of its pyramid.

    Twenty tiles rather than the 4,914 of the full one, which is as much
    picture as a window the size of a postcard can show.
    """
    import io
    import zipfile

    from PIL import Image

    path = os.path.join(folder, PYRAMID)
    if not os.path.exists(path):
        return None
    try:
        with zipfile.ZipFile(path) as zf:
            bounds = _pyramid_bounds(zf.read("pyramid.txt").decode("utf-8", "replace"))
            if not bounds:
                return None
            x0, y0, x1, y1 = bounds
            levels: dict[int, list[tuple[int, int]]] = {}
            for name in zf.namelist():
                m = TILE_NAME.fullmatch(name)
                if m:
                    levels.setdefault(int(m.group(1)), []).append(
                        (int(m.group(2)), int(m.group(3))))
            if not levels or x1 <= x0 or y1 <= y0:
                return None
            # Each level is half the one before, so the highest number is the
            # smallest picture of the whole map.
            level = max(levels)
            step = 2 ** level
            width, height = max(1, (x1 - x0) // step), max(1, (y1 - y0) // step)
            canvas = Image.new("RGB", (width, height), (16, 18, 15))
            for tx, ty in levels[level]:
                with zf.open(f"{level}/tile{tx}x{ty}.png") as f:
                    with Image.open(io.BytesIO(f.read())) as page:
                        tile = page.convert("RGB")
                canvas.paste(tile, (tx * 256, ty * 256))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None
    os.makedirs(os.path.dirname(into), exist_ok=True)
    tmp = into + ".part"
    canvas.save(tmp, format="PNG")
    os.replace(tmp, into)
    return {"file": into, "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
            "px": [width, height]}


def picture_for(name: str, cache_dir: str) -> dict | None:
    """A map's picture by name, assembled on the first ask and kept."""
    for folder, _kind, found in _map_folders():
        if found != name:
            continue
        into = os.path.join(cache_dir, "world", f"{safe_file(found)}.png")
        source = os.path.join(folder, PYRAMID)
        try:
            if os.path.getmtime(into) >= os.path.getmtime(source):
                import zipfile

                from PIL import Image
                with zipfile.ZipFile(source) as zf:
                    bounds = _pyramid_bounds(
                        zf.read("pyramid.txt").decode("utf-8", "replace"))
                with Image.open(into) as im:
                    size = im.size
                if bounds:
                    return {"file": into, "x": bounds[0], "y": bounds[1],
                            "w": bounds[2] - bounds[0], "h": bounds[3] - bounds[1],
                            "px": list(size)}
        except Exception:                   # noqa: BLE001 - no cache, build it
            pass
        return build_picture(folder, into)
    return None


def _with_pictures(maps: list[dict], cache_dir: str | None) -> list[dict]:
    """Each map that has a picture, with the world tiles it covers.

    Done here rather than when the window asks for each one, because a picture
    is only worth drawing if the window knows where to put it, and that is the
    same answer every time.
    """
    if not cache_dir:
        for found in maps:
            found["picture"] = False
        return maps
    for found in maps:
        if not found.get("picture"):
            continue
        where = picture_for(found["name"], cache_dir)
        found["picture"] = bool(where)
        if where:
            found["pictureBox"] = {k: where[k] for k in ("x", "y", "w", "h")}
    return maps


def world_maps(own_mod: str | None = None) -> list[dict]:
    """Every map on this PC, in compiled cells: the game's own and the
    installed mods. What the window draws the world from.

    `own_mod` is the mod folder the map being placed was installed into: its
    own installed copy is not another map, and was drawn as one, a second
    square of the same town behind it."""
    own = os.path.normcase(os.path.abspath(own_mod)) + os.sep if own_mod else None
    out = []
    for folder, kind, name in _map_folders():
        if own and os.path.normcase(os.path.abspath(folder)).startswith(own):
            continue
        found = _map_folder(folder, kind, name)
        if found:
            # Whether the game ships a picture of it, which the window asks
            # for separately.
            found["picture"] = os.path.exists(os.path.join(folder, PYRAMID))
            out.append(found)
    return out


def installed_maps() -> list[dict]:
    """Every map already installed on this PC, in cells."""
    out = []
    for x, y, w, h in _installed_boxes():
        out.append({"x": x, "y": y, "w": w, "h": h})
    return out


def overlaps(box: dict, other: dict) -> bool:
    return (box["x"] < other["x"] + other["w"] and other["x"] < box["x"] + box["w"]
            and box["y"] < other["y"] + other["h"] and other["y"] < box["y"] + box["h"])


def layout(out_dir: str, map_name: str, cache_dir: str | None = None) -> dict:
    """Everything the window needs to show the world and this map in it.

    `cache_dir` is where the pictures of the maps are kept; without one the
    world is drawn as the shape of its cells and nothing else.
    """
    from . import mapstate

    here = where_is(out_dir, map_name)
    inst = mapstate.installed(out_dir)
    width, height = here["size"]
    chosen, built, where = here["chosen"], here["built"], here["cell"]
    vx, vy, vw, vh = VANILLA_BOX
    mine = {"x": where[0], "y": where[1], "w": width, "h": height}
    taken = [m for m in installed_maps()
             if not (built and m["x"] == built[0] and m["y"] == built[1])]
    alone = standalone(out_dir)
    return {
        "vanilla": {"x": vx, "y": vy, "w": vw, "h": vh, "name": VANILLA_NAME},
        # The world as it really is, in compiled cells, for the picture.
        "maps": _with_pictures(world_maps(inst and inst.get("modRoot")), cache_dir),
        "compiledCell": COMPILED_CELL,
        "installed": taken,
        "map": mine,
        "chosen": bool(chosen),
        "built": list(built) if built else None,
        "compiled": here["compiled"] is not None,
        "lotsMatch": here["matches"],
        "source": here["source"],
        "cellTiles": CELL_SIZE,
        "maxCell": MAX_CELL,
        "standalone": alone,
        # A standalone map is the only one in its world: nothing to clash with.
        "clash": [] if alone else (
            ([VANILLA_NAME] if width and height
             and overlaps(mine, {"x": vx, "y": vy, "w": vw, "h": vh}) else [])
            + [f"a map at cell {m['x']},{m['y']}" for m in taken
               if width and height and overlaps(mine, m)]),
    }


# ---- moving one that has already been built ---------------------------------

def _shift_pzw(path: str, cells: tuple[int, int]) -> bool:
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return False
    new, n = re.subn(r'<worldOrigin origin="-?\d+,-?\d+"/>',
                     f'<worldOrigin origin="{cells[0]},{cells[1]}"/>', text, count=1)
    if not n:
        return False
    knoxfiles.write_text(path, new)
    return True


def _shift_worldmap(path: str, delta: tuple[int, int]) -> bool:
    """The paper map's cells. Its points are relative to the cell they are in,
    so only the cell numbers move."""
    dx, dy = delta
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return False

    def one(m):
        return f'<cell x="{int(m.group(1)) + dx}" y="{int(m.group(2)) + dy}">'

    new, n = re.subn(r'<cell x="(-?\d+)" y="(-?\d+)">', one, text)
    if not n:
        return False
    knoxfiles.write_text(path, new)
    return True


def _shift_points(path: str, delta_tiles: tuple[int, int]) -> bool:
    """Street lines, which are world tiles to one decimal place."""
    dx, dy = delta_tiles
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return False

    def one(m):
        return (f'<point x="{float(m.group(1)) + dx:.1f}" '
                f'y="{float(m.group(2)) + dy:.1f}"/>')

    new, n = re.subn(r'<point x="(-?[\d.]+)" y="(-?[\d.]+)"/>', one, text)
    if not n:
        return False
    knoxfiles.write_text(path, new)
    return True


def _shift_annotations(path: str, delta_tiles: tuple[int, int]) -> bool:
    """The text on the paper map: addUntranslatedText(name, layer, x, y)."""
    dx, dy = delta_tiles
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return False

    def one(m):
        return f'{m.group(1)}{int(m.group(2)) + dx}, {int(m.group(3)) + dy})'

    new, n = re.subn(r'(addUntranslatedText\(.*?,\s*"[^"]*",\s*)(-?\d+),\s*(-?\d+)\)',
                     one, text)
    if not n:
        return False
    knoxfiles.write_text(path, new)
    return True


def automatic(out_dir: str, map_name: str) -> tuple[int, int]:
    """Where this map would be put if nobody had placed it: east of the
    vanilla map and of anything else installed (knoxbuild/world.py)."""
    from .world import choose_origin

    width, height = project_size(out_dir, map_name)
    return choose_origin(out_dir, width, height, keep_place=False)


def unplace(out_dir: str, map_name: str) -> dict:
    """Hand the choice back to the app, and put the map where it would go.

    Forgetting the choice alone would leave a map that had been moved sitting
    wherever it was moved to - the project itself says where it is - so the
    map goes back to the place it would have been packed into.
    """
    forget(out_dir)
    done = move(out_dir, map_name, automatic(out_dir, map_name), remember=False)
    done["automatic"] = True
    return done


def settled_origin(out_dir: str, map_name: str,
                   width: int, height: int) -> tuple[int, int]:
    """Where to build this map: the place picked for it, else where its own
    files already stand, else a free cell.

    A build used to pick a fresh place every time and ignore the choice, so a
    map the window had placed at 0,0 was built at 70,0: the compiled cells
    named for one origin and install refusing it against the other, for ever.
    """
    # Same answer as everywhere else: the choice, else where it was built,
    # else a free cell (see where_is).
    return where_is(out_dir, map_name)["cell"]


def move(out_dir: str, map_name: str, cells, remember: bool = True) -> dict:
    """Put a built map somewhere else. Says what was rewritten.

    Only the files that carry the world origin are touched; the buildings, the
    ground and the zombies are all relative to the map's own corner and do not
    know where in the world they are. The compiled lots do - they are named
    for it - so they have to be made again, which the window says.
    """
    want = save(out_dir, cells) if remember else clamp(cells)
    was = where_is(out_dir, map_name, automatic=False)["built"]
    done = {"origin": list(want), "was": list(was) if was else None,
            "rewrote": [], "needsBuild": was is None,
            "needsCompile": False}
    if was is None or was == want:
        done["needsCompile"] = not lots_match(out_dir, want)
        return done
    delta = (want[0] - was[0], want[1] - was[1])
    tiles = (delta[0] * CELL_SIZE, delta[1] * CELL_SIZE)

    if _shift_pzw(os.path.join(out_dir, f"{map_name}.pzw"), want):
        done["rewrote"].append(f"{map_name}.pzw")
    if _shift_worldmap(os.path.join(out_dir, "worldmap.xml"), delta):
        done["rewrote"].append("worldmap.xml")
    if _shift_points(os.path.join(out_dir, "streets.xml"), tiles):
        done["rewrote"].append("streets.xml")
    if _shift_annotations(os.path.join(out_dir, "worldmap-annotations.lua"), tiles):
        done["rewrote"].append("worldmap-annotations.lua")
    done["needsCompile"] = not lots_match(out_dir, want)
    return done


# ---- a road from one map to the next ----------------------------------------
#
# Two maps in one world have empty grid between them: no ground, no road,
# nothing to drive along. A road drawn across that gap becomes a map of its own
# - a strip of country with that road down it - built, compiled and installed
# by the same steps as any other map.
#
# Two things decide whether it looks like anywhere. It is built at the scale of
# the map it joins, so its road is the same width in tiles as the roads it
# meets - a road built at a metre a tile against a map built at two is twice as
# wide as the street it runs into. And it is not a road on bare grass: a road
# between two towns runs past woods, fields and hedges, which is what the land
# either side of it is made of here.

LINK_MARGIN_CELLS = 1          # cells of ground either side of the road
LINK_MAX_CELLS = 2500          # a link bigger than this is a map, not a road
VERGE_M = 14.0                 # grass between the road and whatever is beyond
SCENERY_STEP_M = 150.0         # how often the land either side changes
SCENERY_DEPTH_M = (60.0, 230.0)
# What the country between two towns is made of, and how much of each.
SCENERY = (("forest", 34), ("farmland", 26), ("scrub", 12), ("grass", 10),
           ("orchard", 6), ("forest", 12))


def _clip_to_box(points, width, height):
    """A line cut to the sheet, as however many runs of it are inside."""
    def inside(p):
        return 0 <= p[0] <= width and 0 <= p[1] <= height

    def cross(a, b):
        lo, hi = 0.0, 1.0
        for _ in range(24):
            mid = (lo + hi) / 2
            at = (a[0] + (b[0] - a[0]) * mid, a[1] + (b[1] - a[1]) * mid)
            if inside(at):
                lo = mid
            else:
                hi = mid
        return (a[0] + (b[0] - a[0]) * lo, a[1] + (b[1] - a[1]) * lo)

    out, run = [], []
    for i, here in enumerate(points):
        if inside(here):
            if not run and i:
                run.append(cross(here, points[i - 1]))
            run.append(here)
            continue
        if run:
            run.append(cross(run[-1], here))
            if len(run) > 1:
                out.append(run)
            run = []
    if len(run) > 1:
        out.append(run)
    return out


def _along(points, step):
    """Walk a line, giving (x, y, along, dx, dy) every `step` metres."""
    import math

    out = []
    walked = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        run = math.hypot(x1 - x0, y1 - y0)
        if run <= 0:
            continue
        ux, uy = (x1 - x0) / run, (y1 - y0) / run
        at = 0.0
        while at < run:
            out.append((x0 + ux * at, y0 + uy * at, walked + at, ux, uy))
            at += step
        walked += run
    return out


def _jitter(ring, rng, by):
    """Corners nudged about, so a field is not a stencil of the last one."""
    return [[round(x + rng.uniform(-by, by), 1), round(y + rng.uniform(-by, by), 1)]
            for x, y in ring]


def _scenery(points, width, height, seed: int) -> list[dict]:
    """Woods, fields, hedges, trees and the odd farm either side of the road.

    Laid along the road rather than scattered over the sheet: what a road
    between two towns runs past is a hedge, then a field, then a wood, in
    lengths of a hundred metres or two, with a farm standing back from it
    every so often. Bare grass with a road down the middle reads as a runway,
    which is what the first version of this looked like.
    """
    import random

    rng = random.Random(seed)
    out: list[dict] = []
    kinds = [kind for kind, _n in SCENERY]
    weights = [n for _kind, n in SCENERY]
    inside = lambda ring: all(0 <= px <= width and 0 <= py <= height
                              for px, py in ring)

    for x, y, _walked, ux, uy in _along(points, SCENERY_STEP_M):
        nx, ny = -uy, ux                   # square to the road
        for side in (1, -1):
            if rng.random() < 0.15:
                continue                   # a gap: a view across the fields
            kind = rng.choices(kinds, weights=weights, k=1)[0]
            near = VERGE_M + rng.uniform(0, 26)
            deep = rng.uniform(*SCENERY_DEPTH_M)
            run = SCENERY_STEP_M * rng.uniform(0.75, 1.15)
            a = (x + nx * side * near, y + ny * side * near)
            b = (a[0] + ux * run, a[1] + uy * run)
            c = (b[0] + nx * side * deep, b[1] + ny * side * deep)
            d = (a[0] + nx * side * deep, a[1] + ny * side * deep)
            ring = _jitter([a, b, c, d], rng, min(run, deep) * 0.12)
            if inside(ring):
                out.append({"kind": kind, "points": ring})

            # A farm, a barn or a house standing back from the road, with a
            # track up to it. A road with nothing on it for two miles is a
            # road nobody has any reason to drive down.
            if rng.random() < 0.22:
                building = rng.choices(("barn", "house", "shed"),
                                       weights=(5, 4, 3), k=1)[0]
                back = near + rng.uniform(30, 90)
                size = {"barn": (22, 14), "house": (12, 9), "shed": (7, 5)}[building]
                along = rng.uniform(20, max(21, run - size[0]))
                p0 = (x + ux * along + nx * side * back,
                      y + uy * along + ny * side * back)
                plot = [p0,
                        (p0[0] + ux * size[0], p0[1] + uy * size[0]),
                        (p0[0] + ux * size[0] + nx * side * size[1],
                         p0[1] + uy * size[0] + ny * side * size[1]),
                        (p0[0] + nx * side * size[1], p0[1] + ny * side * size[1])]
                drive = [[round(p0[0] + ux * size[0] / 2, 1),
                          round(p0[1] + uy * size[0] / 2, 1)],
                         [round(x + ux * along + ux * size[0] / 2, 1),
                          round(y + uy * along + uy * size[0] / 2, 1)]]
                if inside(plot) and inside(drive):
                    out.append({"kind": "track", "points": drive})
                    out.append({"kind": building,
                                "points": [[round(px, 1), round(py, 1)]
                                           for px, py in plot]})

        # A hedge along the verge, in runs, which is what a country road has
        # between it and the field beyond.
        if rng.random() < 0.55:
            side = rng.choice((1, -1))
            near = VERGE_M * rng.uniform(0.6, 0.9)
            a = (x + nx * side * near, y + ny * side * near)
            b = (a[0] + ux * SCENERY_STEP_M * 0.9, a[1] + uy * SCENERY_STEP_M * 0.9)
            if inside((a, b)):
                out.append({"kind": "hedge",
                            "points": [[round(a[0], 1), round(a[1], 1)],
                                       [round(b[0], 1), round(b[1], 1)]]})

    # Trees along the verge, thicker than the woods are even: a lane is lined
    # with them long after the wood it came out of has ended.
    for x, y, _walked, ux, uy in _along(points, 26.0):
        nx, ny = -uy, ux
        for side in (1, -1):
            if rng.random() > 0.38:
                continue
            at = (x + nx * side * (VERGE_M * rng.uniform(0.5, 1.4))
                  + ux * rng.uniform(-8, 8),
                  y + ny * side * (VERGE_M * rng.uniform(0.5, 1.4))
                  + uy * rng.uniform(-8, 8))
            if inside((at,)):
                out.append({"kind": "tree",
                            "points": [[round(at[0], 1), round(at[1], 1)]]})
    return out


def link_design(out_dir: str, map_name: str, points, kind: str = "primary",
                scenery: bool = True) -> dict:
    """The road drawn between two maps, as a map of its own.

    `points` are where it was drawn, in world tiles. What comes back is the
    sheet to build (generator/sketch.py), the cells it covers and the scale it
    is built at - the same as the map it joins, so its road is the same width
    in tiles as the streets it runs into.
    """
    import json

    kinds = {entry[0] for entry in __import__("generator.sketch",
                                              fromlist=["sketch"]).PALETTE}
    if kind not in kinds:
        raise ValueError(f"No such thing to draw: {kind}")
    line = []
    if not isinstance(points, (list, tuple)):
        raise ValueError("A road is a list of points in world tiles.")
    for point in points:
        try:
            line.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError, IndexError):
            raise ValueError("A road is a list of points in world tiles.")
    if len(line) < 2:
        raise ValueError("A road needs at least two points.")

    metres = 1.0
    try:
        with open(os.path.join(out_dir, f"{map_name}_info.json"),
                  encoding="utf-8") as f:
            metres = float(json.load(f).get("meters_per_tile") or 1.0)
    except (OSError, ValueError, TypeError):
        pass

    box = _link_box(line, out_dir, map_name)
    if box is None:
        raise ValueError("There is no room for a road there: every cell it "
                         "crosses belongs to a map already.")
    if box["w"] * box["h"] > LINK_MAX_CELLS:
        raise ValueError(f"{box['w']}x{box['h']} cells of ground is a map, not "
                         f"a road. Draw a straighter one.")

    # Onto the sheet: metres from its bottom-left corner, y north, which is
    # upside down from the world grid the road was drawn on.
    width = box["w"] * CELL_SIZE * metres
    height = box["h"] * CELL_SIZE * metres
    sheet = [((x - box["x"] * CELL_SIZE) * metres,
              ((box["y"] + box["h"]) * CELL_SIZE - y) * metres) for x, y in line]
    runs = _clip_to_box(sheet, width, height)
    if not runs:
        raise ValueError("None of that road is on ground that can be built.")

    features = []
    for run in runs:
        features.append({"kind": kind,
                         "points": [[round(x, 1), round(y, 1)] for x, y in run]})
        if scenery:
            features += _scenery(run, width, height,
                                 seed=int(abs(run[0][0]) + abs(run[0][1])) + box["x"])
    return {"design": {"width_m": round(width, 1), "height_m": round(height, 1),
                       "anchor": {"lat": 0.0, "lon": 0.0}, "features": features},
            "box": box, "metersPerTile": metres,
            "cells": box["w"] * box["h"],
            "roads": len(runs), "scenery": len(features) - len(runs)}


def _link_box(line, out_dir: str, map_name: str) -> dict | None:
    """The cells a road may be built on: round the road, out of every map.

    Two maps may not share a cell - whichever the game reads second wins and
    the other's ground is simply not there - so the strip is trimmed back out
    of everything already on the world, including the map it is joining.
    """
    import math

    xs = [p[0] for p in line]
    ys = [p[1] for p in line]
    x0 = max(0, int(math.floor(min(xs) / CELL_SIZE)) - LINK_MARGIN_CELLS)
    y0 = max(0, int(math.floor(min(ys) / CELL_SIZE)) - LINK_MARGIN_CELLS)
    x1 = int(math.ceil(max(xs) / CELL_SIZE)) + LINK_MARGIN_CELLS
    y1 = int(math.ceil(max(ys) / CELL_SIZE)) + LINK_MARGIN_CELLS
    box = {"x": x0, "y": y0, "w": max(1, x1 - x0), "h": max(1, y1 - y0)}

    taken = []
    for found in world_maps():
        c = COMPILED_CELL
        taken.append({"x": found["x"] * c, "y": found["y"] * c,
                      "w": found["w"] * c, "h": found["h"] * c})
    where = saved(out_dir) or project_origin(out_dir, map_name)
    width, height = project_size(out_dir, map_name)
    if where and width and height:
        taken.append({"x": where[0] * CELL_SIZE, "y": where[1] * CELL_SIZE,
                      "w": width * CELL_SIZE, "h": height * CELL_SIZE})

    for _pass in range(8):
        me = {"x": box["x"] * CELL_SIZE, "y": box["y"] * CELL_SIZE,
              "w": box["w"] * CELL_SIZE, "h": box["h"] * CELL_SIZE}
        hit = next((t for t in taken if overlaps(me, t)), None)
        if hit is None:
            return box
        sides = sorted(
            (by, side) for side, by in (
                ("left", -(-(hit["x"] + hit["w"] - me["x"]) // CELL_SIZE)),
                ("right", -(-(me["x"] + me["w"] - hit["x"]) // CELL_SIZE)),
                ("top", -(-(hit["y"] + hit["h"] - me["y"]) // CELL_SIZE)),
                ("bottom", -(-(me["y"] + me["h"] - hit["y"]) // CELL_SIZE)),
            ) if by > 0)
        if not sides:
            return None
        by, side = sides[0]
        if side == "left":
            box["x"] += by
            box["w"] -= by
        elif side == "right":
            box["w"] -= by
        elif side == "top":
            box["y"] += by
            box["h"] -= by
        else:
            box["h"] -= by
        if box["w"] <= 0 or box["h"] <= 0:
            return None
    return None
