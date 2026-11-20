"""Parked aircraft on the map's own aprons, for the Wingsmith aircraft mods.

[RKC]WINGSMITH Aircraft is a framework; each aircraft mod on it declares the
places one is found, as a list of world tiles:

    spawns = { { id = "louisville_gate", dir = "S", cond = { 90, 100 },
                 fuel = { 0.9, 1.0 },
                 spots = { { 15400, 2824 }, { 15524, 2824 } } } }

Every one of those places is on the game's own map, so an airfield this tool
generated had its aprons stand empty however many aircraft mods were
installed. What is written here is the same thing for this map's aprons, so
whatever aircraft the player has is found standing on them.

The mod decides for itself whether a spot is clear, and tries the next one
when it is not, so these are candidates rather than promises: the useful
thing is to offer several, well apart, on real concrete.
"""
from __future__ import annotations

import json
import os

# How far apart two parked aircraft are put, in metres. A 737 is a little
# over 30 m long and 28 m across; this leaves room for that and the next one.
SPOT_SPACING_M = 60.0
# Nothing is offered on an apron smaller than this, in square metres: a
# corner of hardstanding by a flying club's hut is not a stand.
MIN_APRON_M2 = 2500.0
# At most this many spots offered per apron. They are candidates, not
# aircraft: the mod walks them until it finds one that is clear.
MAX_SPOTS = 6
# ...and at most this many aprons per airfield. Wingsmith puts one aircraft
# on each place it is given and marks that place done for every aircraft
# mod, so this is the number of aircraft an airfield ends up with: eleven
# aprons at a cargo hub would otherwise be eleven 737s. The biggest aprons
# on each field win, and a map with two airfields gets this many at each.
MAX_PER_AIRFIELD = 2
# Clear of any building by this much, in metres, before it is offered at all.
CLEAR_OF_BUILDINGS_M = 20.0


def _rings(geometry) -> list:
    """Every ring of coordinates in a geojson geometry, however nested."""
    out = []

    def walk(node, depth=0):
        if (isinstance(node, list) and node
                and isinstance(node[0], (int, float))):
            return
        if (isinstance(node, list) and node and isinstance(node[0], list)
                and node[0] and isinstance(node[0][0], (int, float))):
            out.append(node)
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(geometry.get("coordinates") if isinstance(geometry, dict) else geometry)
    return out


def _area_of(points) -> float:
    """Shoelace area of a ring of (x, y), in whatever units it is given."""
    total = 0.0
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        total += ax * by - bx * ay
    return abs(total) / 2.0


def _inside(points, x: float, y: float) -> bool:
    """Even-odd test, so a point in a hole is outside."""
    inside = False
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        if (ay > y) != (by > y):
            cross = ax + (y - ay) / (by - ay) * (bx - ax)
            if cross > x:
                inside = not inside
    return inside


def _airfield_of(ring, fields) -> int:
    """Which mapped aerodrome this apron sits in, or -1 for none."""
    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    for i, field in enumerate(fields):
        if _inside(field, cx, cy):
            return i
    return -1


def apron_spots(aprons, buildings, metres_per_tile: float,
                spacing_m: float = SPOT_SPACING_M,
                limit: int = MAX_SPOTS, fields=()) -> list[dict]:
    """Candidate stands on each apron, in tiles.

    `aprons` is a list of rings of (tile x, tile y); `buildings` a list of
    (x, y, w, h) footprints to keep clear of; `fields` the aerodrome
    outlines, so the cap below is per airfield rather than per map - a map
    with two airfields should not have to share two aircraft between them.
    Aprons outside every mapped aerodrome are counted as one field between
    them, since nothing says which strip they belong to.
    """
    spacing = max(4.0, spacing_m / max(0.05, metres_per_tile))
    clear = CLEAR_OF_BUILDINGS_M / max(0.05, metres_per_tile)
    least = MIN_APRON_M2 / (metres_per_tile * metres_per_tile)
    out = []
    for ring in aprons:
        if len(ring) < 4 or _area_of(ring) < least:
            continue
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        # An aircraft stands along the apron, so the long way round is the
        # way it points. The mod only knows the four compass directions.
        facing = "E" if (x1 - x0) >= (y1 - y0) else "S"
        spots = []
        step = spacing
        y = y0 + step / 2
        while y < y1 and len(spots) < limit:
            x = x0 + step / 2
            while x < x1 and len(spots) < limit:
                if _inside(ring, x, y) and not any(
                        bx - clear <= x <= bx + bw + clear
                        and by - clear <= y <= by + bh + clear
                        for bx, by, bw, bh in buildings):
                    spots.append((int(round(x)), int(round(y))))
                x += step
            y += step
        if spots:
            out.append({"dir": facing, "spots": spots,
                        "area_tiles": int(_area_of(ring)),
                        "field": _airfield_of(ring, fields)})
    out.sort(key=lambda site: -site["area_tiles"])
    kept, per_field = [], {}
    for site in out:
        field = site["field"]
        if per_field.get(field, 0) >= MAX_PER_AIRFIELD:
            continue
        per_field[field] = per_field.get(field, 0) + 1
        kept.append(site)
    return kept


def map_name_of(project_dir: str) -> str | None:
    """What this project's files are named after, from the ones it has."""
    try:
        entries = sorted(os.listdir(project_dir))
    except OSError:
        return None
    for entry in entries:
        if entry.endswith("_areas.geojson"):
            return entry[: -len("_areas.geojson")]
    return None


def from_project(project_dir: str, map_name: str | None = None) -> list[dict]:
    """Read this map's aprons and work out where an aircraft would stand."""
    map_name = map_name or map_name_of(project_dir)
    if not map_name:
        return []
    areas = os.path.join(project_dir, f"{map_name}_areas.geojson")
    info = os.path.join(project_dir, f"{map_name}_info.json")
    if not (os.path.isfile(areas) and os.path.isfile(info)):
        return []
    with open(info, encoding="utf-8") as fh:
        meta = json.load(fh)
    bbox = meta.get("bbox") or {}
    if not bbox:
        return []
    from generator.rendering.projection import Projector

    proj = Projector.build(bbox["south"], bbox["west"], bbox["north"],
                           bbox["east"], float(meta.get("meters_per_tile") or 1.0),
                           float(meta.get("rotation") or 0.0))
    with open(areas, encoding="utf-8") as fh:
        blob = json.load(fh)
    aprons, fields = [], []
    for feature in blob.get("features", []):
        category = (feature.get("properties") or {}).get("category")
        if category not in ("apron", "airfield"):
            continue
        where = aprons if category == "apron" else fields
        for ring in _rings(feature.get("geometry") or {}):
            where.append([proj.to_px(lat, lon) for lon, lat in ring])
    if not aprons:
        return []
    buildings = []
    placements = os.path.join(project_dir, f"{map_name}_placements.csv")
    if os.path.isfile(placements):
        import csv

        with open(placements, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    buildings.append((int(row["tile_x"]), int(row["tile_y"]),
                                      int(row["width"]), int(row["height"])))
                except (KeyError, ValueError):
                    continue
    return apron_spots(aprons, buildings,
                       float(meta.get("meters_per_tile") or 1.0),
                       fields=fields)


def lua(sites: list[dict], origin_tiles: tuple[int, int], mod_id: str,
        map_folder: str = "") -> str:
    """The Lua the map mod ships, which hands the stands to every aircraft.

    It is added to each registered aircraft rather than to one by name, so a
    player with any of them - or one written next year - finds it parked
    here. `Wingsmith.Spawn.sites()` keeps what it read the first time, so
    this goes in before the game starts rather than on a tick.
    """
    ox, oy = origin_tiles
    world = (map_folder or mod_id).replace("\\", "\\\\").replace('"', '\\"')
    rows = []
    for n, site in enumerate(sites, 1):
        spots = ", ".join(f"{{ {x + ox}, {y + oy} }}" for x, y in site["spots"])
        rows.append(
            f'\t{{ id = "{mod_id}_apron_{n}", name = "{mod_id} apron {n}", '
            f'dir = "{site["dir"]}", cond = {{ 65, 95 }}, fuel = {{ 0.2, 0.8 }},\n'
            f'\t  spots = {{ {spots} }} }},')
    body = "\n".join(rows)
    return f'''-- Aircraft parked on this map's aprons, for [RKC]WINGSMITH Aircraft.
-- Written by KnoxMap (knoxbuild/aircraft.py). Without Wingsmith installed
-- this does nothing at all.
--
-- Every aircraft mod on Wingsmith lists the places one is found, and every
-- one of those is on the game's own map, so this map's aprons stood empty.
-- These are the same thing for the aprons here. The mod checks each spot is
-- clear before it puts anything on it, and moves to the next when it is not.

local STANDS = {{
{body}
}}

local function addStands()
\tlocal W = Wingsmith
\tif not (W and W.aircraft) then return end
\tfor _, cfg in pairs(W.aircraft) do
\t\tif type(rawget(cfg, "spawns")) == "table" then
\t\t\tfor _, stand in ipairs(STANDS) do
\t\t\t\tlocal already = false
\t\t\t\tfor _, had in ipairs(cfg.spawns) do
\t\t\t\t\tif had.id == stand.id then already = true break end
\t\t\t\tend
\t\t\t\tif not already then table.insert(cfg.spawns, stand) end
\t\t\tend
\t\tend
\tend
\tif W.Spawn then W.Spawn.list = nil end
end

local function spawningOn()
	-- Wingsmith switches spawning off for the whole world unless the map it
	-- is playing names "Muldraugh, KY" - every place it knows is on the
	-- game's own map, so anywhere else there would be nothing to put down.
	-- A standalone map does not name Muldraugh at all, so the stands above
	-- were never reached. They are on this map, so when this map is the one
	-- being played it is told to carry on. It reads the field on every pass
	-- and only works it out when it is nil, so setting it is enough.
	local W = Wingsmith
	if not (W and W.Spawn) then return end
	local map = ""
	pcall(function() map = getWorld():getMap() or "" end)
	if map == "" then return end
	if string.find(map, "{world}", 1, true) and W.Spawn.mapOn ~= true then
		W.Spawn.mapOn = true
	end
end

Events.OnGameBoot.Add(addStands)
-- The world has to exist before it can be asked what map it is.
if Events.OnGameStart then Events.OnGameStart.Add(spawningOn) end
if Events.OnInitGlobalModData then Events.OnInitGlobalModData.Add(spawningOn) end
'''


def write(project_dir: str, mod_root: str, mod_id: str,
          origin_tiles: tuple[int, int], map_folder: str = "") -> int:
    """Write the Lua into the mod. Returns how many stands were written."""
    sites = from_project(project_dir)
    if not sites:
        return 0
    folder = os.path.join(mod_root, "common", "media", "lua", "shared", "KnoxMap")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{mod_id}_Aircraft.lua")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(lua(sites, origin_tiles, mod_id, map_folder))
    return sum(len(site["spots"]) for site in sites)


def describe(sites: list[dict]) -> str:
    spots = sum(len(site["spots"]) for site in sites)
    if not spots:
        return "no apron big enough to park an aircraft on"
    return (f"{spots} aircraft stand{'s' if spots != 1 else ''} "
            f"on {len(sites)} apron{'s' if len(sites) != 1 else ''}")

