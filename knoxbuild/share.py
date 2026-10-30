"""A hand-built building in one file, to send to somebody else.

A preset lives in two or three files beside the app - the .tbx, the drawing it
was made from, and a line in presets.json saying what kind of building it
stands in for (knoxbuild/presets.py). That is fine for a building that stays
where it was made and no use at all for one somebody wants to show another
player, which is how the asking began: people build a house they are proud of
and there is nowhere for it to go.

So: one JSON file holding all of it, named `<building>.knoxbuilding.json`,
which can be sent over Discord and dropped back into any copy of KnoxMap.
Beyond passing it round, it is also how a building reaches the library that
ships with KnoxMap - somebody sends one in, and `tools/add_shared_building.py`
puts it in `presets/library/`, where every later release carries it and every
map can be built from it.

Everything here treats what it is given as untrusted. A share file arrives
from a stranger over a chat program; `read` is the one door it comes through,
and nothing past that door has to wonder whether the name is a path, whether
the .tbx is a building at all, or whether the thing is a hundred megabytes of
XML entities pointed at themselves.
"""
from __future__ import annotations

import json
import os
import re
import time

from . import presets as P

FORMAT = "knoxmap-building"
VERSION = 1
SUFFIX = ".knoxbuilding.json"

# Caps. A hand-built building of 150x150 over 8 storeys writes about a
# megabyte of .tbx, so four is room for anything the editor can make and far
# less than a file meant to tie the parser in knots.
MAX_TBX_CHARS = 4_000_000
MAX_DESIGN_CHARS = 1_000_000
MAX_SIDE = 300              # a cell; nothing that does not fit on the map
MAX_STOREYS = 32
MAX_AUTHOR = 60
MAX_NOTES = 500

# A document type declaration is the one piece of XML a .tbx never needs and
# the one an attack is written with: a few nested entities expand into
# gigabytes in the parser (knoxbuild/buildtiles.py reads these with
# ElementTree, which expands them). A building that has one is refused rather
# than parsed, here at the door, so nothing downstream has to defend itself.
_DANGEROUS = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.I)


def _text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def file_name(name: str) -> str:
    """What a share file for this building is called."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", P.safe_name(name)).strip("_")
    return f"{safe or 'building'}{SUFFIX}"


def wrap(name: str, tbx: str, design: dict | None = None, kind: str = "",
         author: str = "", notes: str = "") -> dict:
    """The share file for a building, as data ready to be written out."""
    out = {
        "format": FORMAT,
        "version": VERSION,
        "name": P.safe_name(name),
        "kind": str(kind or ""),
        "author": _text(author, MAX_AUTHOR),
        "notes": _text(notes, MAX_NOTES),
        "made": int(time.time()),
        "tbx": tbx,
    }
    if design:
        out["design"] = design
    try:
        import knoxlog
        out["knoxmap"] = knoxlog.version()
    except Exception:          # noqa: BLE001 - the version is a courtesy
        pass
    return out


def of_preset(base_dir, name: str, author: str = "", notes: str = "") -> dict:
    """Wrap a preset that is already saved here. Raises if there is none."""
    from . import designer as D

    clean = P.safe_name(name)
    text = P.read(base_dir, clean)
    if text is None:
        raise ValueError(f'There is no hand-built building called "{name}".')
    entry = next((p for p in P.library(base_dir) if p["name"] == clean), {})
    # Whoever built it keeps their name on it when it is passed on again.
    return wrap(clean, text, D.load_design(base_dir, clean),
                kind=entry.get("kind") or "",
                author=author or entry.get("author") or "",
                notes=notes or entry.get("notes") or "")


def read(data) -> tuple[dict | None, str | None]:
    """Check a share file. Returns (building, None) or (None, what is wrong).

    What comes back is built from scratch out of what was in the file, so
    anything else it carried - a key we have never heard of, a kind this
    version does not have - is left outside rather than passed along.
    """
    from . import designer as D

    if not isinstance(data, dict):
        return None, "That file does not hold a building."
    if data.get("format") != FORMAT:
        return None, "That is not a building shared from KnoxMap."
    if data.get("version") != VERSION:
        return None, (f"That building was shared by another version of "
                      f"KnoxMap (version {data.get('version')!r}, this one "
                      f"reads {VERSION}).")
    name = P.safe_name(data.get("name") or "")
    if not name:
        return None, "The building in that file has no name."

    tbx = data.get("tbx")
    if not isinstance(tbx, str) or not tbx.strip():
        return None, "That file holds no building: there is no .tbx in it."
    if len(tbx) > MAX_TBX_CHARS:
        return None, (f"That building is {len(tbx):,} characters of .tbx, "
                      f"past the {MAX_TBX_CHARS:,} a shared one may be.")
    if _DANGEROUS.search(tbx):
        return None, ("That building carries an XML document type "
                      "declaration, which a building file never needs. It has "
                      "not been opened.")
    about = P.measure(tbx)
    if about is None:
        return None, ("That is not a building file: no <building> with a "
                      "width and a height in it.")
    if about["width"] > MAX_SIDE or about["height"] > MAX_SIDE:
        return None, (f"That building is {about['width']}x{about['height']} "
                      f"tiles, and a shared one may be {MAX_SIDE} a side.")
    if about["storeys"] > MAX_STOREYS:
        return None, f"That building has {about['storeys']} storeys."

    kind = str(data.get("kind") or "").strip().lower()
    if kind and kind not in {entry["id"] for entry in P.kinds()}:
        kind = P.ANY          # a kind this version does not know is no kind

    design = data.get("design")
    if design is not None:
        if not isinstance(design, dict):
            design = None
        elif len(json.dumps(design, default=str)) > MAX_DESIGN_CHARS:
            return None, "The drawing in that file is too big to read."
        else:
            try:
                design = D.clean(design)
            except Exception:  # noqa: BLE001 - a drawing we cannot read is
                design = None  # no reason to refuse the building itself

    return {"format": FORMAT, "version": VERSION, "name": name, "kind": kind,
            "author": _text(data.get("author"), MAX_AUTHOR),
            "notes": _text(data.get("notes"), MAX_NOTES),
            "made": data.get("made") if isinstance(data.get("made"), int) else None,
            "knoxmap": _text(data.get("knoxmap"), 20),
            "tbx": tbx, "design": design,
            "width": about["width"], "height": about["height"],
            "storeys": about["storeys"], "rooms": about["rooms"]}, None


def load(path) -> tuple[dict | None, str | None]:
    """Read and check a share file on disk."""
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return None, f"Could not open that file: {exc}"
    if size > MAX_TBX_CHARS + MAX_DESIGN_CHARS:
        return None, f"That file is {size:,} bytes, which is too big to be one."
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        return None, f"That file could not be read: {exc}"
    return read(data)


def install(base_dir, entry: dict, folder: str | None = None) -> dict:
    """Put a checked building into a preset folder. Returns what it is.

    `folder` is where it goes; the default is where somebody's own buildings
    live. `tools/add_shared_building.py` passes the library that ships with
    KnoxMap instead.
    """
    from . import designer as D

    if folder is None:
        about = P.save(base_dir, entry["name"], entry["tbx"],
                       kind=entry.get("kind") or P.ANY)
        if entry.get("design"):
            D.save_design(base_dir, entry["name"], entry["design"])
            about["editable"] = True
        return about

    os.makedirs(folder, exist_ok=True)
    name = P.safe_name(entry["name"])
    path = os.path.join(folder, f"{name}.tbx")
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(entry["tbx"])
    os.replace(tmp, path)
    if entry.get("design"):
        design_path = os.path.join(folder, f"{name}{P.DESIGN_SUFFIX}")
        tmp = design_path + ".part"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump({**entry["design"], "name": name}, f, indent=1)
        os.replace(tmp, design_path)
    return {"name": name, "file": path, "width": entry["width"],
            "height": entry["height"], "storeys": entry["storeys"],
            "rooms": entry["rooms"], "kind": entry.get("kind") or P.ANY}
