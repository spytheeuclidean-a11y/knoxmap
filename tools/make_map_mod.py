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
               "worldmap.xml", "streets.xml", "worldmap-annotations.lua")


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


def _spawn_tiles(project_dir: str, limit: int) -> list[tuple[int, int]]:
    """Map tiles to start on: inside homes, as far apart as the town allows.

    These used to be the middle of each building's bounding box, taken from
    every n-th row of the placements file. For an L-shaped or turned building
    that middle is often outside it - a start in the yard or inside a wall -
    and the rows are in file order, so the picks could bunch up in one street
    or land in a church. Now they come from the real footprints: homes first,
    each pick the building furthest from those already chosen, and within it
    a tile with floor on every side, away from the walls the furniture lines.
    """
    import numpy as np

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from knoxbuild.population import load_footprints

    saved = [os.path.join(project_dir, e) for e in os.listdir(project_dir)
             if e.endswith("_footprints.npz")]
    if not saved:
        return []
    buildings = load_footprints(saved[0])
    homes = [b for b in buildings if b[4] in ("house", "apartment")]
    pool = homes or [b for b in buildings if b[4] != "shed"] or buildings
    if not pool:
        return []

    def inner_tile(x0, y0, mask):
        # Tiles whose eight neighbours are all floor, nearest the middle.
        m = mask.astype(bool)
        core = m.copy()
        core[1:, :] &= m[:-1, :]
        core[:-1, :] &= m[1:, :]
        core[:, 1:] &= m[:, :-1]
        core[:, :-1] &= m[:, 1:]
        core[1:, 1:] &= m[:-1, :-1]
        core[:-1, :-1] &= m[1:, 1:]
        core[1:, :-1] &= m[:-1, 1:]
        core[:-1, 1:] &= m[1:, :-1]
        ys, xs = np.nonzero(core if core.any() else m)
        if len(xs) == 0:
            return None
        cy, cx = ys.mean(), xs.mean()
        i = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))
        return x0 + int(xs[i]), y0 + int(ys[i])

    spots = [s for s in (inner_tile(x0, y0, m) for x0, y0, m, _l, _k in pool) if s]
    if not spots:
        return []
    arr = np.array(spots, dtype=float)
    centre = arr.mean(axis=0)
    chosen = [int(np.argmin(((arr - centre) ** 2).sum(axis=1)))]
    nearest = ((arr - arr[chosen[0]]) ** 2).sum(axis=1)
    while len(chosen) < min(limit, len(spots)):
        nxt = int(np.argmax(nearest))
        if nearest[nxt] == 0:
            break
        chosen.append(nxt)
        nearest = np.minimum(nearest, ((arr - arr[nxt]) ** 2).sum(axis=1))
    return [spots[i] for i in chosen]


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

    Spawns go inside homes, spread across the town - see _spawn_tiles.
    """
    points = _spawn_tiles(project_dir, limit)

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


SPAWN_SELECTOR_MAX_POIS = 80
# Paper-map label styles that name somewhere a player might want to start.
SPAWN_SELECTOR_STYLES = {"text-building": "landmark", "text-place": "landmark"}


def write_spawn_selector(project_dir: str, mod_root: str, mod_id: str,
                         name: str) -> int:
    """Put this map into Spawn Selector, if the player has that mod.

    Spawn Selector (workshop 3772052709) lets a new character pick a starting
    spot on the world map, but its regions and points of interest are a fixed
    list for Knox County, so a generated town elsewhere in the world could not
    be picked. This adds a Lua file that, only when Spawn Selector is loaded,
    adds the map's area to its random-start regions and its named buildings and
    places - the same ones labelled on the paper map - to its points of
    interest. Without the mod the file does nothing, so it adds no dependency.

    The tables are filled at OnGameBoot, after every mod's Lua has run:
    Spawn Selector assigns its lists outright, so adding to them any earlier
    could be wiped out by load order. Returns how many points were added.
    """
    import json as _json
    import re as _re

    annotations = os.path.join(project_dir, "worldmap-annotations.lua")
    pois, town = [], name
    if os.path.exists(annotations):
        text = open(annotations, encoding="utf-8").read()
        found = _re.findall(r'addUntranslatedText\("((?:[^"\\]|\\.)*)", "([a-z-]+)", '
                            r'(-?[\d.]+), (-?[\d.]+)\)', text)
        for label, style, x, y in found:
            label = label.replace('\\"', '"').replace("\\\\", "\\")
            if style == "text-town":
                town = label
            elif style in SPAWN_SELECTOR_STYLES and len(pois) < SPAWN_SELECTOR_MAX_POIS:
                pois.append((label, SPAWN_SELECTOR_STYLES[style], float(x), float(y)))

    width = height = 0
    for entry in os.listdir(project_dir):
        if entry.endswith("_info.json"):
            with open(os.path.join(project_dir, entry), encoding="utf-8") as f:
                meta = _json.load(f)
            width, height = meta.get("width_tiles", 0), meta.get("height_tiles", 0)
    if not width or not height:
        return 0
    ox, oy = _world_origin_tiles(project_dir)

    def lua_str(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'

    entries = "\n".join(
        f'        {{ type = "custom_poi", group = {lua_str(group)}, name = {lua_str(label)}, '
        f'location = {lua_str(town)}, x = {x:.1f}, y = {y:.1f}, z = 0, placement = "building" }},'
        for label, group, x, y in pois)
    guard = _re.sub(r"\W", "_", mod_id)
    lua = f"""-- Written by KnoxMap for {name}.
-- Adds this map to Spawn Selector (Steam workshop 3772052709) when it is
-- installed. Does nothing otherwise.
local function addToSpawnSelector()
    if not (SpawnSelector and SpawnSelector.RANDOM_REGIONS
            and SpawnSelectorPOIs and SpawnSelectorPOIs.entries) then
        return
    end
    if SpawnSelector.KnoxMapAdded_{guard} then return end
    SpawnSelector.KnoxMapAdded_{guard} = true
    table.insert(SpawnSelector.RANDOM_REGIONS,
        {{ minX = {ox}, minY = {oy}, maxX = {ox + width - 1}, maxY = {oy + height - 1} }})
    local pois = {{
{entries}
    }}
    for _, poi in ipairs(pois) do
        table.insert(SpawnSelectorPOIs.entries, poi)
    end
end

Events.OnGameBoot.Add(addToSpawnSelector)
"""
    folder = os.path.join(mod_root, "common", "media", "lua", "shared", "KnoxMap")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, f"{guard}_SpawnSelector.lua"), "w",
              encoding="utf-8") as f:
        f.write(lua)
    return len(pois)


KNOXMAP_URL = "https://github.com/spytheeuclidean-a11y/knoxify"


def write_attribution(project_dir: str, mod_root: str, name: str) -> None:
    """ATTRIBUTION.txt at the root of every mod: what the map is made from.

    - OpenStreetMap's ODbL requires crediting OpenStreetMap wherever a
      Produced Work (a map, an image, a game world) made from its data is
      used, and making the source data or the method of deriving it
      available (section 4.6). The method is KnoxMap itself, open source, and
      the area and date below are what it was run on.
    - The Indie Stone's terms ask fan productions to say what they are.
    """
    import datetime
    import json as _json

    info = {}
    for entry in os.listdir(project_dir):
        if entry.endswith("_info.json"):
            with open(os.path.join(project_dir, entry), encoding="utf-8") as f:
                info = _json.load(f)
            break
    bbox = info.get("osm_bbox") or [info.get("bbox", {}).get(k) for k in ("south", "west", "north", "east")]
    text = f"""{name}
{"=" * len(name)}

A Project Zomboid map generated with KnoxMap ({KNOXMAP_URL}).

MAP DATA
Map data (c) OpenStreetMap contributors, available under the Open Database
License (ODbL): https://www.openstreetmap.org/copyright

This map is a Produced Work made from OpenStreetMap data. It was derived from
the OpenStreetMap data inside this area (south, west, north, east):
    {bbox}
downloaded on or before {datetime.date.today().isoformat()}, using the open-source
method in KnoxMap at the address above. If you publish this map, keep this
file with it and credit "Map data (c) OpenStreetMap contributors".

Buildings' interiors, residents and zombies are invented by the generator and
do not describe the real places or anyone connected with them. Not for
navigation or any real-world use.

PROJECT ZOMBOID
Thanks to The Indie Stone for creating Project Zomboid (https://projectzomboid.com/),
which made this possible. This is an unofficial fan production for
non-commercial purposes made under the Indie Stone Terms
(https://projectzomboid.com/blog/support/terms-conditions/).
KnoxMap is not made, endorsed or supported by The Indie Stone.
"""
    with open(os.path.join(mod_root, "ATTRIBUTION.txt"), "w", encoding="utf-8") as f:
        f.write(text)


def folder_name(title: str, fallback: str) -> str:
    """A map folder name the game and Windows both accept, from a display title.

    The folder used to be the title itself, so "Paris: Le Marais" asked Windows
    for a path with a colon in it, and "Kadıköy" put non-ASCII characters into
    paths the game hands to Lua. Accents are folded ("Kadikoy"), anything else
    outside letters, digits, spaces, commas, dots and dashes is dropped. The
    title in map.info keeps its real spelling.
    """
    import re
    import unicodedata

    folded = unicodedata.normalize("NFKD", title)
    folded = folded.replace("ı", "i").replace("ß", "ss")
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^A-Za-z0-9 ,.\-_]+", " ", ascii_only)
    safe = re.sub(r"\s+", " ", safe).strip(" .")
    return safe or fallback


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
    map_dir = os.path.join(mod_root, "common", "media", "maps",
                           folder_name(name, mod_id))
    os.makedirs(map_dir, exist_ok=True)

    for src in cells + extras:
        shutil.copy2(src, os.path.join(map_dir, os.path.basename(src)))

    desc = description or f"{name}, generated from real-world map data."
    # OpenStreetMap's licence (ODbL) requires attribution wherever the map is
    # used, and a game map may carry it in its menus; the mod list is where
    # players see it. See write_attribution for the rest.
    desc = f"{desc} Map data (c) OpenStreetMap contributors (ODbL)."
    # Optional mods this map makes use of, so players know what they add.
    buildings = os.path.join(project_dir, "buildings")
    has_lifts = os.path.isdir(buildings) and any(
        "fixtures_escalators_01_4" in open(os.path.join(buildings, f), encoding="utf-8").read()
        for f in os.listdir(buildings) if f.endswith(".tbx"))
    works_with = (["Elevators (working lifts)"] if has_lifts else []) + \
        ["Spawn Selector (choose where to start)"]
    desc = f"{desc} Optional: {', '.join(works_with)}."

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

    write_attribution(project_dir, mod_root, name)
    n_pois = write_spawn_selector(project_dir, mod_root, mod_id, name)
    extra_names = [os.path.basename(e) for e in extras]
    if n_spawns:
        extra_names.append(f"spawnpoints.lua ({n_spawns} spawn points)")
    extra_names.append(f"Spawn Selector support ({n_pois} places)")
    return mod_root, sum(1 for c in cells if c.endswith(".lotheader")), extra_names


def main(argv: list[str] | None = None) -> int:
    # Place names can be in any script, and a Windows console using a legacy
    # code page cannot print most of them - "OSM says Kadıköy" crashed a build
    # on cp1252. Print what it can and mark the rest, rather than dying.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
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
