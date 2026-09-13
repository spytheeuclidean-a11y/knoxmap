"""Package a compiled map into a Project Zomboid map mod.

Run this AFTER WorldEd's Generate Lots. It collects the compiled cell data and
the Lua files WorldEd wrote, and lays them out the way Build 42 map mods do:

    <mods>/<id>/
        mod.info
        common/media/maps/<Map Name>/
            *.lotheader  *.lotpack  chunkdata_*.bin
            map.info
            spawnpoints.lua  objects.lua

Layout and map.info fields follow an installed B42 workshop map (New Hartburg).

    python tools/make_map_mod.py output/mytown --name "My Town, KY" --id mytown
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

LOT_PATTERNS = (".lotheader", ".lotpack")
EXTRA_FILES = ("spawnpoints.lua", "objects.lua", "roomtones.lua",
               "worldmap.xml", "streets.xml")


def default_mods_dir() -> str:
    # knoxpaths knows about a Zomboid folder moved elsewhere (ZOMBOID_DIR or
    # the setup config); ~/Zomboid otherwise.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import knoxpaths
    return str(knoxpaths.zomboid_user_dir() / "mods")


def collect(project_dir: str, lots_dir: str) -> tuple[list[str], list[str]]:
    """Compiled cell files, and the loose Lua/XML files WorldEd wrote."""
    cells = []
    if os.path.isdir(lots_dir):
        for f in sorted(os.listdir(lots_dir)):
            if f.endswith(LOT_PATTERNS) or f.startswith("chunkdata"):
                cells.append(os.path.join(lots_dir, f))
    extras = []
    for folder in (lots_dir, project_dir):
        if not os.path.isdir(folder):
            continue
        for name in EXTRA_FILES:
            p = os.path.join(folder, name)
            if os.path.exists(p) and not any(
                    os.path.basename(e) == name for e in extras):
                extras.append(p)
    return cells, extras


def _world_origin_tiles(project_dir: str) -> tuple[int, int]:
    """The map's world origin in tiles, read back from the .pzw it came from."""
    import re

    for entry in os.listdir(project_dir):
        if not entry.endswith(".pzw"):
            continue
        text = open(os.path.join(project_dir, entry),
                    encoding="utf-8", errors="replace").read()
        m = re.search(r'<worldOrigin origin="(\d+),(\d+)"', text)
        if m:
            return int(m.group(1)) * 300, int(m.group(2)) * 300
    return 0, 0


def write_spawnpoints(project_dir: str, map_dir: str, limit: int = 8) -> int:
    """Write spawnpoints.lua, without which the map is not a startable region.

    Build 42's own maps use absolute world tile coordinates and a single
    `unemployed` list:

        function SpawnPoints()
          return {
            unemployed = {
              { posX = 2152, posY = 6089, posZ = 0 },
            }
          }
        end

    (Older community maps use worldX/worldY cell coordinates plus an in-cell
    offset; that form still loads but is not what the shipped maps do.)

    Knoxify projects sit at world origin 0,0, so a building's map tile position
    is already its world position. Spawns are placed at the middle of generated
    buildings, spread across the map, so you start indoors rather than in a wall
    or a lake.
    """
    import csv as _csv

    placements = None
    for entry in os.listdir(project_dir):
        if entry.endswith("_placements.csv"):
            placements = os.path.join(project_dir, entry)
            break

    points: list[tuple[int, int]] = []
    if placements:
        with open(placements, newline="", encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))
        # Spread the picks across the file so spawns aren't all in one corner.
        step = max(1, len(rows) // limit) if rows else 1
        for row in rows[::step][:limit]:
            x = int(row["tile_x"]) + int(row["width"]) // 2
            y = int(row["tile_y"]) + int(row["height"]) // 2
            points.append((x, y))

    if not points:
        # No buildings: fall back to the centre of the map.
        info = None
        for entry in os.listdir(project_dir):
            if entry.endswith("_info.json"):
                info = os.path.join(project_dir, entry)
                break
        if info:
            import json as _json
            with open(info) as f:
                meta = _json.load(f)
            points = [(meta["width_tiles"] // 2, meta["height_tiles"] // 2)]
        else:
            points = [(150, 150)]

    # Spawn points are absolute world tiles, so they must carry the same world
    # origin the lots were generated with. Without this they point at wherever
    # the map would have sat at origin 0,0 — on top of vanilla Knox County.
    ox, oy = _world_origin_tiles(project_dir)
    points = [(x + ox, y + oy) for x, y in points]

    body = ",\n".join(f"      {{ posX = {x}, posY = {y}, posZ = 0 }}"
                      for x, y in points)
    lua = ("function SpawnPoints()\n"
           "  return {\n"
           "    unemployed = {\n"
           f"{body}\n"
           "    }\n"
           "  }\n"
           "end\n")
    with open(os.path.join(map_dir, "spawnpoints.lua"), "w",
              encoding="utf-8") as f:
        f.write(lua)
    return len(points)


def package(project_dir: str, name: str, mod_id: str,
            lots_dir: str | None = None, mods_dir: str | None = None,
            description: str = "") -> tuple[str, int, list[str]]:
    """Write the mod folder. Returns (mod_root, cell file count, extras)."""
    lots_dir = lots_dir or os.path.join(project_dir, "lots")
    mods_dir = mods_dir or default_mods_dir()

    cells, extras = collect(project_dir, lots_dir)
    if not cells:
        raise FileNotFoundError(
            f"No compiled cell data in {lots_dir}. Run WorldEd's Generate Lots "
            f"first.")

    mod_root = os.path.join(mods_dir, mod_id)
    map_dir = os.path.join(mod_root, "common", "media", "maps", name)
    os.makedirs(map_dir, exist_ok=True)

    for src in cells + extras:
        shutil.copy2(src, os.path.join(map_dir, os.path.basename(src)))

    desc = description or f"{name}, generated from real-world map data."

    # lots=Muldraugh, KY tells the game which vanilla lot set to inherit room
    # and tile definitions from; every community map sets it.
    with open(os.path.join(map_dir, "map.info"), "w", encoding="utf-8") as f:
        f.write(f"title={name}\n")
        f.write("lots=Muldraugh, KY\n")
        f.write("fixed2x=true\n")
        f.write(f"description={desc}\n")

    # A map with no spawn points is not offered as a starting region, so the
    # mod appears in the Mods menu but the map is nowhere on the new-game map.
    n_spawns = 0
    if not any(os.path.basename(e) == "spawnpoints.lua" for e in extras):
        n_spawns = write_spawnpoints(project_dir, map_dir)

    # Build 42 scans version folders, and each needs its own copy of mod.info —
    # a root-only one leaves the mod invisible in the in-game Mods menu. An
    # installed workshop map (New Hartburg) ships three identical copies: at the
    # root, in common/ next to the media, and in 42/ as the "works on B42"
    # marker. Match that exactly.
    info = (f"name={name}\n"
            f"id={mod_id}\n"
            f"description={desc}\n")
    os.makedirs(os.path.join(mod_root, "42"), exist_ok=True)
    for where in ("", "common", "42"):
        with open(os.path.join(mod_root, where, "mod.info"), "w",
                  encoding="utf-8") as f:
            f.write(info)

    extra_names = [os.path.basename(e) for e in extras]
    if n_spawns:
        extra_names.append(f"spawnpoints.lua ({n_spawns} spawn points)")
    return mod_root, sum(1 for c in cells if c.endswith(".lotheader")), extra_names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir", help="the Knoxify output/<mapname> folder")
    ap.add_argument("--name", required=True,
                    help='in-game map name, e.g. "My Town, KY"')
    ap.add_argument("--id", required=True, help="mod id, e.g. mytown")
    ap.add_argument("--lots", default=None,
                    help="Generate Lots output (default <project>/lots)")
    ap.add_argument("--mods-dir", default=None,
                    help=f"default {default_mods_dir()}")
    ap.add_argument("--description", default="")
    args = ap.parse_args(argv)

    try:
        mod_root, n_cells, extras = package(
            args.project_dir, args.name, args.id,
            lots_dir=args.lots, mods_dir=args.mods_dir,
            description=args.description)
    except FileNotFoundError as exc:
        print(f"{exc}\nRun WorldEd's Generate Lots first.", file=sys.stderr)
        return 2

    print(f"cells installed   : {n_cells}")
    print(f"extra files       : {extras}")
    print(f"mod written to    : {mod_root}")
    print()
    print("Enable it in the game's Mods menu, then start a new save - the map "
          "appears as a spawn region.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
