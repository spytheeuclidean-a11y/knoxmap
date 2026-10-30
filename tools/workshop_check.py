"""Is an installed map ready to be put on the Steam Workshop?

Nothing here uploads anything. It reads the mod folder that Install wrote and
says what would be wrong with publishing it as it stands: the credit
OpenStreetMap's licence asks for, a mod id the game can use, and the preview
picture the Workshop wants. Each problem comes with what to do about it.

    check(mod_root) -> [{"level": "ok" | "warn" | "bad", "what": ..., "fix": ...}]

"bad" is something that makes the mod wrong or breaks the licence; "warn" is
something the Workshop page will want but the game does not.
"""
from __future__ import annotations

import os
import re
import struct

# The Workshop shows the preview at a small size and rejects a big file.
PREVIEW_MAX_BYTES = 1_000_000
PREVIEW_MIN_SIDE = 256

_PNG = b"\x89PNG\r\n\x1a\n"
_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,60}$")


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _mod_info(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip().lower()] = value.strip()
    return out


def _png_size(path: str):
    """(width, height) of a PNG, or None if the file is not one."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != _PNG or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def check(mod_root: str, project_dir: str | None = None) -> list[dict]:
    results: list[dict] = []

    def add(level: str, what: str, fix: str = "") -> None:
        results.append({"level": level, "what": what, "fix": fix})

    if not os.path.isdir(mod_root):
        add("bad", "The mod is not installed.", "Press Install first.")
        return results
    folder_id = os.path.basename(os.path.normpath(mod_root))

    # ---- the credit OpenStreetMap's licence (ODbL) asks for -------------------
    attribution = _read(os.path.join(mod_root, "ATTRIBUTION.txt"))
    if attribution is None:
        add("bad", "ATTRIBUTION.txt is missing.",
            "Install again: it writes the file, and the map may not be published without it.")
    else:
        # The file wraps its lines, and "Open Database" / "License" are on two.
        low = " ".join(attribution.lower().split())
        if "openstreetmap contributors" in low and "open database license" in low:
            add("ok", "ATTRIBUTION.txt credits OpenStreetMap under the ODbL.")
        else:
            add("bad", "ATTRIBUTION.txt does not credit OpenStreetMap under the ODbL.",
                "Install again to rewrite it, and keep the credit in whatever you publish.")
        overture = project_dir and os.path.isdir(project_dir) and any(
            e.endswith("_overture.json.gz") for e in os.listdir(project_dir))
        if overture:
            if "overture" in low:
                add("ok", "The Overture Maps buildings are credited.")
            else:
                add("bad", "The map uses Overture Maps buildings and the credit is missing.",
                    "Install again to rewrite ATTRIBUTION.txt.")

    # ---- mod.info: the id and what the Workshop page will say -----------------
    # The game reads it from the root, from common/ and from 42/; one that is
    # missing or different leaves the mod out of the Mods menu on that build.
    infos = {}
    for where in ("", "common", "42"):
        text = _read(os.path.join(mod_root, where, "mod.info"))
        label = f"{where}/mod.info" if where else "mod.info"
        if text is None:
            add("bad", f"{label} is missing.", "Install again.")
        else:
            infos[where] = _mod_info(text)
    if infos:
        first = next(iter(infos.values()))
        if any(i != first for i in infos.values()):
            add("bad", "The copies of mod.info differ.", "Install again so they match.")
        mod_id = first.get("id", "")
        if not mod_id:
            add("bad", "mod.info has no id.", "Fill in the Mod id and install again.")
        elif not _ID_OK.match(mod_id):
            add("bad", f"The mod id \"{mod_id}\" has characters the game does not accept.",
                "Use letters, digits, - and _ only.")
        elif mod_id != folder_id:
            add("warn", f"The mod id \"{mod_id}\" is not the folder name \"{folder_id}\".",
                "Install again so they agree.")
        else:
            add("ok", f"Mod id \"{mod_id}\" is fine.")
        if not first.get("name"):
            add("bad", "mod.info has no name.", "Fill in the Name in game and install again.")
        description = first.get("description", "")
        if "openstreetmap" in description.lower():
            add("ok", "The mod description credits OpenStreetMap.")
        else:
            add("bad", "The mod description does not credit OpenStreetMap.",
                "Install again: the credit goes into the description players see.")

    # ---- the map itself --------------------------------------------------------
    maps = os.path.join(mod_root, "common", "media", "maps")
    cells = 0
    has_info = False
    if os.path.isdir(maps):
        for folder in os.listdir(maps):
            path = os.path.join(maps, folder)
            if os.path.isdir(path):
                cells += sum(1 for f in os.listdir(path) if f.endswith(".lotheader"))
                has_info = has_info or os.path.exists(os.path.join(path, "map.info"))
    if not cells:
        add("bad", "The mod has no compiled cells.", "Compile the map, then install it.")
    elif not has_info:
        add("bad", "The map has no map.info.", "Install again.")
    else:
        add("ok", f"{cells} compiled cell{'s' if cells != 1 else ''} are in the mod.")

    # ---- the picture the Workshop page shows -----------------------------------
    preview = os.path.join(mod_root, "preview.png")
    if not os.path.exists(preview):
        add("warn", "There is no preview.png in the mod folder.",
            "Put a square PNG, 256 pixels or more a side and under 1 MB, named preview.png "
            "in the mod folder. The Workshop page uses it.")
    else:
        size = _png_size(preview)
        if size is None:
            add("bad", "preview.png is not a PNG.", "Save it again as a PNG.")
        elif min(size) < PREVIEW_MIN_SIDE:
            add("warn", f"preview.png is only {size[0]} x {size[1]}.",
                f"Use at least {PREVIEW_MIN_SIDE} pixels on the short side.")
        elif size[0] != size[1]:
            add("warn", f"preview.png is {size[0]} x {size[1]}, not square.",
                "The Workshop crops it; a square picture shows what you chose.")
        elif os.path.getsize(preview) > PREVIEW_MAX_BYTES:
            add("warn", "preview.png is over 1 MB.", "Save it smaller; the Workshop may refuse it.")
        else:
            add("ok", f"preview.png is {size[0]} x {size[1]}.")
    return results


def summary(results: list[dict]) -> dict:
    bad = sum(r["level"] == "bad" for r in results)
    warn = sum(r["level"] == "warn" for r in results)
    return {"ready": bad == 0, "bad": bad, "warn": warn}
