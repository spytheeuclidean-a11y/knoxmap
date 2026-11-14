"""Putting a map on a dedicated server, without anybody editing an .ini.

A map mod is enough for a player on their own. A server needs three more
things, none of them guessable from the mod folder:

    Mods=...;<the mod id>
    Map=<the map folder>;Muldraugh, KY
    Zomboid/Server/<the server's name>_spawnregions.lua

The mod already ships a SERVER SETUP.txt saying exactly that with this
map's real names in it, and people still get it wrong - because the editing
is the hard part, not the knowing. `Mods=` on a played-in server is a line
of forty mods; adding one by hand means finding the end of it without
dropping a semicolon. `Map=` has to gain an entry at the *front* and keep
Muldraugh at the back. The spawn regions file has to be named for the
server rather than the map, which is the single most common thing to get
wrong - players spawn in Muldraugh and nobody knows why.

So this does it: reads the server's own files, adds what is missing,
leaves what is already there, and says what it changed. The .ini is copied
to one side first, because it is the player's file and a map tool has no
business being the reason a server will not start.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

import knoxpaths

# The vanilla map every non-standalone map inherits its lot definitions
# from, and which has to stay at the end of Map=.
VANILLA_MAP = "Muldraugh, KY"


def server_dir() -> Path:
    """Zomboid/Server, wherever the Zomboid folder is."""
    return knoxpaths.zomboid_user_dir() / "Server"


def _ini_value(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}=(.*)$", text, re.M)
    return match.group(1).strip() if match else ""


def servers() -> list[dict]:
    """Every server on this PC, by the name its files are called.

    A server is a `<name>.ini` in Zomboid/Server. `save` is whether a world
    has already been played, because adding a map to one of those is the
    thing that cannot be undone: Project Zomboid writes a world cell by cell
    from whatever map was loaded at the time, so cells built before the map
    arrived do not agree with the ones built after.
    """
    found = []
    folder = server_dir()
    if not folder.is_dir():
        return found
    saves = knoxpaths.zomboid_user_dir() / "Saves" / "Multiplayer"
    for ini in sorted(folder.glob("*.ini")):
        name = ini.stem
        try:
            text = ini.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found.append({
            "name": name,
            "ini": str(ini),
            "map": _ini_value(text, "Map"),
            "mods": [m for m in _ini_value(text, "Mods").split(";") if m],
            "spawnregions": (folder / f"{name}_spawnregions.lua").exists(),
            "save": (saves / name).is_dir(),
        })
    return found


def merge_entries(current: str, wanted: list[str], first: bool = False) -> str:
    """A semicolon list with `wanted` in it, keeping what is already there.

    Order matters for Map= and not for Mods=, so `first` puts the new
    entries at the front. Nothing is ever removed: a server's mod list is
    the server owner's, and a map tool that tidies it is a map tool that
    breaks somebody's game.
    """
    have = [e.strip() for e in current.split(";") if e.strip()]
    missing = [w for w in wanted if w not in have]
    if not missing:
        return ";".join(have)
    return ";".join(missing + have if first else have + missing)


def _set_key(text: str, key: str, value: str) -> tuple[str, bool]:
    """The .ini with `key` set to `value`. Keeps the file's own line endings
    and leaves every other line exactly as it was."""
    pattern = re.compile(rf"^({re.escape(key)}=)(.*)$", re.M)
    match = pattern.search(text)
    if match is None:
        nl = "\r\n" if "\r\n" in text else "\n"
        return text.rstrip("\r\n") + nl + f"{key}={value}" + nl, True
    if match.group(2).strip() == value:
        return text, False
    return pattern.sub(lambda m: m.group(1) + value, text, count=1), True


def spawn_regions_lua(name: str, map_folder: str, standalone: bool) -> str:
    """The spawn regions file, named for the map inside and the server out."""
    rows = [f'        {{ name = "{name}", '
            f'file = "media/maps/{map_folder}/spawnpoints.lua" }},']
    if not standalone:
        rows.append(f'        {{ name = "{VANILLA_MAP}", '
                    f'file = "media/maps/{VANILLA_MAP}/spawnpoints.lua" }},')
    return ("-- Written by KnoxMap for this server.\n"
            "function SpawnRegions()\n    return {\n"
            + "\n".join(rows) + "\n    }\nend\n")


def apply(server: str, mod_id: str, map_folder: str, title: str = "",
          standalone: bool = False, extra_mods: list | None = None,
          workshop: list | None = None) -> dict:
    """Put this map on that server. Returns what was changed.

    Nothing here is clever: the point is that it is exactly right, every
    time, including the parts people get wrong - the map at the front of
    `Map=`, Muldraugh still at the back, the spawn regions file named for
    the server and not the map.
    """
    folder = server_dir()
    ini = folder / f"{server}.ini"
    if not ini.is_file():
        raise FileNotFoundError(f"No {server}.ini in {folder}")

    text = ini.read_text(encoding="utf-8", errors="replace")
    before = text
    changed: list[str] = []

    mods = merge_entries(_ini_value(text, "Mods"),
                         list(extra_mods or []) + [mod_id])
    text, hit = _set_key(text, "Mods", mods)
    if hit:
        changed.append(f"Mods= now ends with {mod_id}")

    if standalone:
        maps = map_folder
    else:
        maps = merge_entries(_ini_value(text, "Map"), [map_folder], first=True)
        if VANILLA_MAP not in maps.split(";"):
            maps = f"{maps};{VANILLA_MAP}"
    text, hit = _set_key(text, "Map", maps)
    if hit:
        changed.append(f"Map= is {maps}")

    if workshop:
        items = merge_entries(_ini_value(text, "WorkshopItems"),
                              [str(w) for w in workshop])
        text, hit = _set_key(text, "WorkshopItems", items)
        if hit:
            changed.append("WorkshopItems= has the tile mod's id")

    backup = ""
    if text != before:
        # The server owner's file. A map tool has no business being the
        # reason a server will not start, so the old one is kept.
        backup = str(ini) + time.strftime(".knoxmap-%Y%m%d-%H%M%S.bak")
        shutil.copy2(ini, backup)
        ini.write_text(text, encoding="utf-8", newline="")

    regions = folder / f"{server}_spawnregions.lua"
    wanted = spawn_regions_lua(title or map_folder, map_folder, standalone)
    existing = regions.read_text(encoding="utf-8", errors="replace") \
        if regions.is_file() else ""
    if existing != wanted:
        if existing:
            backup_lua = str(regions) + time.strftime(".knoxmap-%Y%m%d-%H%M%S.bak")
            shutil.copy2(regions, backup_lua)
        regions.write_text(wanted, encoding="utf-8", newline="")
        changed.append(f"{regions.name} points at this map")

    saves = knoxpaths.zomboid_user_dir() / "Saves" / "Multiplayer" / server
    return {
        "server": server,
        "changed": changed,
        "backup": backup,
        # Named as well as pathed: the window shows the name, and working a
        # basename out of a Windows path in javascript is three layers of
        # backslash escaping for no reason.
        "backupName": os.path.basename(backup) if backup else "",
        "ini": str(ini),
        "spawnregions": str(regions),
        # Not deleted here: wiping somebody's world is their decision, not a
        # side effect of setting a map up.
        "save": str(saves) if saves.is_dir() else "",
    }
