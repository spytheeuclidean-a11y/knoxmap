"""Turn a Knoxify output folder into furnished .tbx buildings + a WorldEd project.

    python -m knoxbuild output/mytown

Reads <name>_info.json and <name>_buildings.geojson, reprojects every OSM
footprint with Knoxify's own Projector so the buildings line up with the
landscape BMP exactly, generates a floor plan for each, and writes:

    <dir>/buildings/<name>_NNN.tbx
    <dir>/<name>.pzw          WorldEd project with every building placed
    <dir>/<name>_placements.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

import numpy as np
from shapely.geometry import Polygon

from generator.renderer import Projector

from .areas import AreaIndex
from .fences import build_fences
from .footprint import place
from .layout import build_building
from .context import Context, style_fits
from .population import build_spawn_map, official_population, save_footprints
from .settings import PRESETS, Settings
from .tbx import render_tbx
from .world import Placement, render_pzw
from . import worldmap

# OSM building tags that should get a commercial room mix rather than a house.
COMMERCIAL_TAGS = {
    "retail", "commercial", "industrial", "warehouse", "office", "shop",
    "supermarket", "school", "hospital", "church", "civic", "public",
    "government", "hotel", "service", "garage", "garages", "kiosk",
}


# building=* values that are not walled buildings at all. A carport or a petrol
# station canopy is a roof on posts; ruins and tanks have no rooms. Built as
# houses they would be solid boxes standing where the real place is open.
NOT_BUILDINGS = {
    "roof", "carport", "canopy", "ruins", "collapsed", "demolished", "no",
    "bridge", "storage_tank", "tank", "silo", "transformer_tower", "chimney",
    "tower", "grandstand", "construction",
}
# Outbuildings: one room, one storey, nobody living there.
SHED_VALUES = {
    "shed", "garage", "garages", "hut", "service", "toilets", "boathouse",
    "allotment_house", "bunker", "garbage_shed", "guardhouse", "gatehouse",
}
# An untagged building this small is a shed, a garage or a kiosk, not a home:
# 30 square metres of house would be one living room with a sofa filling it.
# Mappers tag the small houses that do exist (building=house), and those
# stay houses. Real square metres, so a map drawn at 4 m a tile does not turn
# its houses into sheds.
SHED_MAX_M2 = 30
HOUSE_TAGS = ("house", "detached", "bungalow", "semidetached_house", "cabin")
# An untagged building among tagged blocks of flats is taken for one when it
# is at least this big, in square metres; smaller ones are the shops and
# garages between them.
NEIGHBOUR_FLATS_M2 = 60
# Kinds whose height follows the tagged buildings around them. A school or a
# church is its own shape whatever the street is like.
FOLLOWS_NEIGHBOURS = {"house", "apartment", "shop", "civic", "restaurant"}
HOUSE_MAX_LEVELS = 3


# Named buildings worth a label on the paper map: the public ones people give
# directions by. Hotels, banks and offices are "civic" for their room plan,
# but a label on each buries the map in brand names.
NOTABLE_AMENITY = {"townhall", "police", "fire_station", "library", "courthouse",
                   "post_office", "community_centre", "theatre", "hospital",
                   "school", "university", "college", "place_of_worship",
                   "marketplace", "prison", "arts_centre"}


def is_notable(tags: dict, kind: str | None) -> bool:
    if kind in ("school", "church", "medical"):
        return True
    return (tags.get("amenity") in NOTABLE_AMENITY
            or tags.get("tourism") in ("museum", "attraction")
            or tags.get("historic") not in (None, "", "no")
            or tags.get("building") in ("government", "public", "civic", "townhall")
            or "wikidata" in tags or "wikipedia" in tags)


# OSM values that identify a building as something other than a house. Checked
# against the building/amenity/shop/leisure/tourism/healthcare tags in turn.
SPECIAL_BY_VALUE = {
    "school": "school", "kindergarten": "school", "college": "school",
    "university": "school", "childcare": "school", "library": "civic",
    "church": "church", "chapel": "church", "cathedral": "church",
    "mosque": "church", "synagogue": "church", "temple": "church",
    "place_of_worship": "church",
    "restaurant": "restaurant", "fast_food": "restaurant", "cafe": "restaurant",
    "bar": "restaurant", "pub": "restaurant", "food_court": "restaurant",
    "retail": "shop", "commercial": "shop", "supermarket": "shop",
    "convenience": "shop", "mall": "shop", "kiosk": "shop",
    "department_store": "shop", "shop": "shop", "marketplace": "shop",
    "industrial": "industrial", "warehouse": "industrial",
    "factory": "industrial", "works": "industrial", "manufacture": "industrial",
    "barn": "barn", "farm": "barn", "farm_auxiliary": "barn",
    "greenhouse": "barn", "stable": "barn", "cowshed": "barn",
    "hospital": "medical", "clinic": "medical", "doctors": "medical",
    "dentist": "medical", "pharmacy": "medical", "veterinary": "medical",
    "apartments": "apartment", "residential": "apartment",
    "dormitory": "apartment", "terrace": "apartment",
    "civic": "civic", "public": "civic", "government": "civic",
    "townhall": "civic", "police": "civic", "fire_station": "civic",
    "hotel": "civic", "office": "civic", "courthouse": "civic",
    "museum": "civic", "bank": "civic", "post_office": "civic",
}

# Last resort when the tags say nothing useful but the name is obvious.
SPECIAL_BY_NAME = [
    ("school", "school"), ("academy", "school"), ("college", "school"),
    ("university", "school"), ("church", "church"), ("chapel", "church"),
    ("cathedral", "church"), ("hospital", "medical"), ("clinic", "medical"),
    ("pharmacy", "medical"), ("warehouse", "industrial"),
    ("factory", "industrial"), ("mill", "industrial"), ("plant", "industrial"),
    ("market", "shop"), ("mall", "shop"), ("store", "shop"), ("shop", "shop"),
    ("diner", "restaurant"), ("restaurant", "restaurant"), ("grill", "restaurant"),
    ("cafe", "restaurant"), ("bar ", "restaurant"), ("barn", "barn"),
    ("library", "civic"), ("bank", "civic"), ("city hall", "civic"),
    ("apartment", "apartment"), ("apartmani", "apartment"),
    ("residence", "apartment"), ("towers", "apartment"), ("blok", "apartment"),
]

# Storeys, when OSM does not say. A town of nothing but bungalows reads as a
# film set - the skyline is what tells you whether you are downtown or in the
# suburbs, and every building here was one floor tall.
DEFAULT_LEVELS = {
    "industrial": (1, 1),
    "barn": (1, 1),
    "shed": (1, 1),
    "church": (1, 1),
    "apartment": (3, 5),
    "civic": (2, 3),
    "school": (2, 3),
    "medical": (2, 4),
    "shop": (1, 2),
    "restaurant": (1, 2),
}


# A footprint this big, with nothing but building=yes on it, is a block of
# flats rather than somebody's house.
#
# This has to be a guess because the data gives nothing else to go on: of 3079
# buildings in a real Turkish town, 3015 were tagged building=yes and not one
# carried building:levels. Taking those at face value produced 2902 detached
# houses and two apartment blocks - a suburb where a town should be.
def looks_like_apartment(tags: dict, area_tiles: int, rng,
                         settings: Settings) -> bool:
    """Whether an untagged building should be treated as a block of flats."""
    # A mapper who recorded a height or a floor count has told us what this
    # is, whatever its footprint: three storeys up is a block of flats and one
    # storey is not, and neither needs guessing at.
    measured = levels_from_tags(tags, settings)
    if measured is not None:
        return measured >= 3
    if area_tiles < settings.apartment_footprint:
        return False
    if (tags.get("building") or "").lower() in ("house", "detached", "bungalow"):
        return False
    return rng.random() < settings.apartment_chance


# Metres of building per storey, for turning a height= into a floor count.
# OSM's own convention, and close enough to the game's floor spacing.
METRES_PER_LEVEL = 3.0


def _number(raw: str | None) -> float | None:
    """A leading number out of an OSM measurement, in metres.

    Values in the wild are "12", "12 m", "12.5", "12,5" and occasionally
    "40'" or "3;4" where two mappers disagreed. Feet are converted; a
    semicolon list takes the first entry.
    """
    if not raw:
        return None
    text = str(raw).strip().split(";")[0].strip().replace(",", ".")
    feet = text.endswith("'") or text.endswith("ft")
    text = text.rstrip("'").removesuffix("ft").removesuffix("m").strip()
    try:
        value = float(text)
    except ValueError:
        return None
    return value * 0.3048 if feet else value


def levels_from_tags(tags: dict, settings: Settings) -> int | None:
    """Storeys according to OSM, or None where it does not say.

    Preference order is how confident each source is. building:levels is a
    mapper counting floors, so it is taken as given. height is a measurement -
    of the roof ridge, not the top floor - so it is divided by a nominal storey
    and rounded down, which is why a 10 m building comes out as three floors
    rather than four.
    """
    for key in ("building:levels", "levels"):
        value = _number(tags.get(key))
        if value is not None and value >= 1:
            levels = int(value)
            # A roof level is habitable space in OSM's model, so an attic
            # conversion counts - but only when the mapper recorded one.
            roof = _number(tags.get("roof:levels"))
            if roof and roof >= 1:
                levels += int(roof)
            return max(1, min(settings.max_levels, levels))

    for key in ("height", "building:height", "est_height"):
        metres = _number(tags.get(key))
        if metres and metres > 0:
            # A building:part sitting on a podium starts partway up.
            base = _number(tags.get("min_height")) or 0.0
            usable = max(metres - base, metres * 0.5)
            return max(1, min(settings.max_levels,
                              int(usable // METRES_PER_LEVEL)))
    return None


def building_levels(tags: dict, kind: str | None, area_tiles: int,
                    rng, settings: Settings) -> tuple[int, bool]:
    """How many storeys this building gets, and whether OSM said so."""
    measured = levels_from_tags(tags, settings)
    if measured is not None:
        return measured, True
    lo, hi = DEFAULT_LEVELS.get(kind or "", (1, 2))
    return rng.randint(min(lo, settings.max_levels),
                       min(hi, settings.max_levels)), False


def classify_building(tags: dict) -> str | None:
    """The special kind for this building, or None for an ordinary one."""
    for key in ("amenity", "shop", "healthcare", "leisure", "tourism",
                "office", "industrial", "craft", "building"):
        value = (tags.get(key) or "").strip().lower()
        if not value:
            continue
        if value in SPECIAL_BY_VALUE:
            return SPECIAL_BY_VALUE[value]
        # shop=* with an unlisted value is still a shop.
        if key == "shop" and value not in ("no", "vacant"):
            return "shop"
        if key == "healthcare":
            return "medical"
    name = (tags.get("name") or "").lower()
    for needle, kind in SPECIAL_BY_NAME:
        if needle in name:
            return kind
    return None


def pick_style(kind: str | None, tile_x: int, tile_y: int, rng,
               settings: Settings, density: float = 0.0) -> dict:
    """Materials for one building: its own if special, else its block's.

    Only styles that suit how built-up the place is are in the running, so the
    old town gets render and brick and the log cabins stay in the countryside.
    """
    from . import catalog as C

    if kind and kind in C.SPECIAL_STYLES:
        return C.SPECIAL_STYLES[kind]

    styles = [s for s in C.HOUSE_STYLES if style_fits(s["name"], density)] \
        or C.HOUSE_STYLES
    size = settings.neighbourhood_tiles
    block = (tile_x // size, tile_y // size)
    # Deterministic per block, so re-running gives the same town.
    idx = (block[0] * 73856093 ^ block[1] * 19349663) % len(styles)
    if len(styles) > 1 and rng.random() < settings.style_oddity:
        idx = (idx + 1 + rng.randrange(len(styles) - 1)) % len(styles)
    return styles[idx]


def _detect_zones(landscape_path: str, placements, rng_seed: int = 7,
                  settings: Settings | None = None):
    """Parking stalls along the roads, town zones over built-up ground.

    Without these the streets are bare: vehicles only ever spawn inside
    ParkingStall zones, and TownZone is what marks ground as urban. Vanilla
    Knox County ships 9694 of the former and 2715 of the latter.

    Stalls are found by scanning the landscape bitmap for asphalt that sits on
    a road *edge* — a stall in the middle of a carriageway would block it.
    """
    import random

    from PIL import Image

    from generator import pz_colors as C

    from .world import Zone

    ASPHALT = {C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT,
               C.DARK_POTHOLE, C.LIGHT_POTHOLE}

    settings = settings or Settings()
    rng = random.Random(rng_seed)
    zones: list[Zone] = []

    img = Image.open(landscape_path).convert("RGB")
    w, h = img.size
    px = img.load()

    def is_asphalt(x: int, y: int) -> bool:
        """Carriageway or car park, as opposed to the pavement beside it."""
        if not (0 <= x < w and 0 <= y < h):
            return False
        # The three street shades plus the two pothole shades that weather
        # them. Kerbs and paving slabs are deliberately out: parking a car on
        # the pavement is where stalls ended up once roads grew kerbs, because
        # any grey pixel in a wide range counted as road.
        return px[x, y] in ASPHALT

    STALL_W, STALL_H = 3, 5
    step = 14           # how often to consider a spot
    taken: set[tuple[int, int]] = set()

    for y in range(4, h - STALL_H - 4, step):
        for x in range(4, w - STALL_W - 4, step):
            if not is_asphalt(x, y):
                continue
            kerbside = not (is_asphalt(x - 4, y) and is_asphalt(x + 4, y)
                            and is_asphalt(x, y - 4) and is_asphalt(x, y + 4))
            # Deep inside a wide expanse of tarmac: no carriageway is 16 tiles
            # across, so this is a car park, and its middle is exactly where
            # the cars go. The old rule skipped every interior spot to avoid
            # blocking a road, which left car parks themselves empty.
            car_park = (is_asphalt(x - 8, y) and is_asphalt(x + 8, y)
                        and is_asphalt(x, y - 8) and is_asphalt(x, y + 8))
            if not kerbside and not car_park:
                continue
            chance = (0.75 if car_park else 0.45) * settings.parking_density
            if rng.random() > chance:
                continue
            vertical = is_asphalt(x, y - 2) or is_asphalt(x, y + 2)
            sw, sh = (STALL_W, STALL_H) if vertical else (STALL_H, STALL_W)
            key = (x // 8, y // 8)
            if key in taken:
                continue
            taken.add(key)
            zones.append(Zone("ParkingStall", x, y, sw, sh))

    # One town zone per cell that holds buildings, covering their extent with a
    # margin so gardens and the street frontage count as town too.
    by_cell: dict[tuple[int, int], list] = {}
    for p in placements:
        by_cell.setdefault((p.cell_x, p.cell_y), []).append(p)
    for (cx, cy), group in by_cell.items():
        x0 = max(0, min(p.tile_x for p in group) - 8)
        y0 = max(0, min(p.tile_y for p in group) - 8)
        x1 = min(w, max(p.tile_x + p.width for p in group) + 8)
        y1 = min(h, max(p.tile_y + p.height for p in group) + 8)
        # Clamp into the owning cell so the rectangle stays where it is written.
        x0 = max(x0, cx * 300)
        y0 = max(y0, cy * 300)
        x1 = min(x1, (cx + 1) * 300)
        y1 = min(y1, (cy + 1) * 300)
        if x1 - x0 > 4 and y1 - y0 > 4:
            zones.append(Zone("TownZone", x0, y0, x1 - x0, y1 - y0))

    return zones


def _ring_points(geom: dict) -> list[list[float]]:
    """Every [lon, lat] in a Polygon or MultiPolygon outer ring."""
    if geom["type"] == "Polygon":
        return geom["coordinates"][0]
    pts: list[list[float]] = []
    for poly in geom["coordinates"]:
        pts.extend(poly[0])
    return pts


def _make_one(job: tuple) -> tuple[int, int, int]:
    """Lay out one building and write its .tbx. Returns (storeys, rooms, furniture)."""
    w, h, levels, commercial, seed, kind, mask, settings, style, label, path = job
    plan = build_building(w, h, levels=levels, commercial=commercial, seed=seed,
                          kind=kind, mask=mask, settings=settings)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_tbx(plan, label, style))
    return (len(plan.storeys), len(plan.rooms),
            sum(len(s.furniture) for s in plan.storeys))


# Below this many buildings, starting worker processes costs more than it saves.
PARALLEL_FROM = 60


def _make_all(jobs: list[tuple]) -> list[tuple[int, int, int]]:
    """Every building, in order, across processes when there are enough.

    KNOXBUILD_WORKERS=1 forces one process. If worker processes cannot start
    at all - some locked-down PCs refuse them - the work simply runs here.
    """
    workers = int(os.environ.get("KNOXBUILD_WORKERS") or
                  max(1, min(12, (os.cpu_count() or 2) - 2)))
    if workers <= 1 or len(jobs) < PARALLEL_FROM:
        return [_make_one(job) for job in jobs]
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool

    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(_make_one, jobs,
                                 chunksize=max(4, len(jobs) // (workers * 8))))
    except (BrokenProcessPool, OSError) as exc:
        print(f"  (worker processes unavailable: {exc}; building in one process)")
        return [_make_one(job) for job in jobs]


def build(out_dir: str, seed: int | None = None, min_size: int | None = None,
          max_size: int | None = None, settings: Settings | None = None) -> int:
    """Generate every building for a rendered map.

    The explicit seed/min_size/max_size arguments are kept so the command line
    can override one value without composing a whole Settings.
    """
    settings = settings or Settings()
    overrides = {k: v for k, v in (("seed", seed), ("min_size", min_size),
                                   ("max_size", max_size)) if v is not None}
    if overrides:
        settings = Settings.from_dict({**settings.to_dict(), **overrides})
    seed = settings.seed
    min_size = settings.min_size
    max_size = settings.max_size
    names = [f for f in os.listdir(out_dir) if f.endswith("_info.json")]
    if not names:
        print(f"no <name>_info.json in {out_dir}", file=sys.stderr)
        return 2
    map_name = names[0][: -len("_info.json")]

    with open(os.path.join(out_dir, f"{map_name}_info.json")) as f:
        info = json.load(f)
    with open(os.path.join(out_dir, f"{map_name}_buildings.geojson")) as f:
        geo = json.load(f)

    bbox = info["bbox"]
    proj = Projector.build(bbox["south"], bbox["west"], bbox["north"],
                           bbox["east"], info["meters_per_tile"])
    if (proj.width, proj.height) != (info["width_tiles"], info["height_tiles"]):
        print("projection does not match the rendered BMP - is this folder "
              "from a different Knoxify version?", file=sys.stderr)
        return 2

    # Record what this build actually used, whoever started it. Without this
    # a map generated from the command line cannot be reproduced, and the app
    # and the CLI disagree about what a folder was built with.
    try:
        with open(os.path.join(out_dir, "settings.json"), "w",
                  encoding="utf-8") as f:
            json.dump(settings.to_dict(), f, indent=2)
    except OSError:
        pass

    bdir = os.path.join(out_dir, "buildings")
    os.makedirs(bdir, exist_ok=True)
    # Clear out the previous build. Building numbers follow the footprints, so
    # a rebuild does not overwrite the same set of files, and leftovers from an
    # earlier run sit in the folder looking like part of the map.
    for stale in os.listdir(bdir):
        if stale.endswith(".tbx"):
            os.remove(os.path.join(bdir, stale))
    # WorldEd writes into these but will not create them: BMP to TMX fails with
    # "Could not open file for writing" if the export directory is absent.
    os.makedirs(os.path.join(out_dir, "tmx"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "lots"), exist_ok=True)

    import random as _random
    style_rng = _random.Random(seed ^ 0x5EED)

    placements: list[Placement] = []
    rows = []
    skipped = {"small": 0, "large": 0, "outside": 0, "taken": 0,
               "not a building": 0}
    sheds = 0        # outbuildings given a single storage room
    from_near = 0    # storeys borrowed from tagged neighbours
    from_osm = 0   # buildings whose storey count came from the data
    from_area = 0  # buildings whose kind came from the land around them
    squared = 0    # buildings close enough to the grid to square up

    areas = AreaIndex.load(out_dir, map_name, proj)
    # (x0, y0, mask, storeys, kind) for the population estimate.
    peopled: list[tuple[int, int, np.ndarray, int, str]] = []
    # Real outlines of the buildings placed, for the in-game paper map.
    outlines: list[tuple[list[tuple[float, float]], str, str]] = []
    occupied = np.zeros((proj.height, proj.width), dtype=bool)

    # Biggest footprints claim their tiles first. Where two real buildings
    # share a wall, one of them has to give up that row of tiles, and it should
    # not be the town hall giving way to the shed behind it.
    order = []
    jobs: list[tuple] = []       # what each building needs to lay itself out
    decided: list[tuple] = []    # and what the map needs to know about it
    surroundings: list[tuple[float, float, float, int | None]] = []
    for i, feat in enumerate(geo["features"]):
        pts = _ring_points(feat["geometry"])
        if len(pts) < 3:
            continue
        tags = feat.get("properties", {})
        if (tags.get("building") or "").strip().lower() in NOT_BUILDINGS:
            skipped["not a building"] += 1
            continue
        px = [proj.to_px(lat, lon) for lon, lat in pts]
        poly = Polygon(px)
        if not poly.is_valid:
            poly = poly.buffer(0)
        order.append((-poly.area, i, px))
        centre = poly.centroid
        if not centre.is_empty:
            surroundings.append((centre.x, centre.y, poly.area,
                                 levels_from_tags(tags, settings)))
    order.sort()
    metres_per_tile = info["meters_per_tile"]
    context = Context(proj.width, proj.height, surroundings, metres_per_tile)

    for _neg_area, i, px in order:
        feat = geo["features"][i]
        fp, reason = place(px, occupied, min_side=min_size, max_side=max_size)
        if fp is None:
            skipped[reason] += 1
            continue
        x0, y0, w, h = fp.x0, fp.y0, fp.width, fp.height
        mask = fp.mask_list()
        if fp.angle <= 8.0:
            squared += 1

        tags = feat.get("properties", {})
        btag = (tags.get("building") or "").strip().lower()
        cx = x0 + w / 2
        cy = y0 + h / 2
        real_m2 = fp.tiles * metres_per_tile * metres_per_tile
        special = classify_building(tags)
        if special is None and (btag in SHED_VALUES or (
                btag in ("", "yes") and real_m2 <= SHED_MAX_M2)):
            special = "shed"
            sheds += 1
        nearby = (context.neighbour_levels(cx, cy)
                  if levels_from_tags(tags, settings) is None else None)
        if special is None and nearby is not None and nearby >= 3 \
                and real_m2 >= NEIGHBOUR_FLATS_M2 and btag not in HOUSE_TAGS:
            # Among tagged blocks of flats, a big untagged building is one more.
            special = "apartment"
        if special is None:
            around = areas.kind_for(cx, cy, fp.tiles)
            # A tall building in a shopping street is flats over shops; the
            # mapper's height says so more reliably than the zoning does.
            if around == "shop" and (levels_from_tags(tags, settings) or 0) >= 3:
                around = None
            if around:
                special = around
                from_area += 1
        commercial = special is not None or tags.get("building") in COMMERCIAL_TAGS
        if special is None and looks_like_apartment(tags, fp.tiles, style_rng,
                                                    settings):
            special = "apartment"
            commercial = True
        levels, measured = building_levels(tags, special, fp.tiles,
                                           style_rng, settings)
        if measured:
            from_osm += 1
        elif nearby is not None and (special or "house") in FOLLOWS_NEIGHBOURS:
            top = settings.max_levels
            if special is None:
                top = min(top, HOUSE_MAX_LEVELS)
            levels = max(1, min(top, int(round(nearby)) +
                                style_rng.choice((-1, 0, 0, 1))))
            from_near += 1
        style = pick_style(special, x0, y0, style_rng, settings,
                           density=context.density(cx, cy))

        fname = f"{map_name}_{i:04d}.tbx"
        label = tags.get("name") or f"{map_name} building {i}"
        jobs.append((w, h, levels, commercial, seed + i, special, mask,
                     settings, style, label, os.path.join(bdir, fname)))
        decided.append((fname, label, x0, y0, w, h, fp, px, special, measured,
                        commercial, style, mask,
                        (tags.get("name") or "") if is_notable(tags, special) else ""))

    # Every decision above is made in order, from one random stream, so the
    # town comes out the same each time. What is left - laying out rooms and
    # writing the files - depends only on each building's own seed, so it runs
    # across processes: a 4,000-building district took three minutes on one.
    for (fname, label, x0, y0, w, h, fp, px, special, measured, commercial,
         style, mask, real_name), (storeys, rooms, furniture) in zip(decided, _make_all(jobs)):
        p = Placement(f"buildings/{fname}", x0, y0, w, h)
        placements.append(p)
        peopled.append((x0, y0, fp.mask, storeys, special or "house"))
        outlines.append((px, special or "house", real_name))
        rows.append({
            "file": fname, "name": label,
            "tile_x": x0, "tile_y": y0, "width": w, "height": h,
            "cell_x": p.cell_x, "cell_y": p.cell_y,
            "offset_x": p.offset_x, "offset_y": p.offset_y,
            "levels": storeys,
            "levels_from_osm": int(measured),
            "rooms": rooms,
            "furniture": furniture,
            "commercial": int(commercial),
            "kind": special or "house",
            "style": style["name"],
            "shaped": int(mask is not None),
            "angle": round(fp.angle, 1),
        })
    rows.sort(key=lambda r: r["file"])

    fence_placements, fence_tiles = build_fences(out_dir, map_name, proj,
                                                 occupied, areas, bdir)

    # The zombie spawn map, redrawn from the people in the buildings just
    # placed. It replaces the ground-colour one the renderer wrote, at the
    # same path and size, so the WorldEd project picks it up unchanged.
    spawn_img, population = build_spawn_map(
        peopled, proj.width, proj.height, info["meters_per_tile"],
        os.path.join(out_dir, f"{map_name}.bmp"), settings)
    spawn_img.save(os.path.join(out_dir, f"{map_name}_ZombieSpawnMap.bmp"), format="BMP")
    save_footprints(os.path.join(out_dir, f"{map_name}_footprints.npz"), peopled)
    population["official"] = [p for p in official_population(out_dir, map_name)
                              if p.get("inside")][:5]
    with open(os.path.join(out_dir, f"{map_name}_population.json"), "w",
              encoding="utf-8") as f:
        json.dump(population, f, indent=2, ensure_ascii=False)

    paper_map = worldmap.write(out_dir, map_name, proj, info, outlines)

    zones = _detect_zones(os.path.join(out_dir, f"{map_name}.bmp"),
                          placements, settings=settings)
    # Fences go into the project alongside the buildings, but not into the
    # town zones: a fence lot spans its whole cell and would mark it all town.
    placements = placements + fence_placements

    pzw_path = os.path.join(out_dir, f"{map_name}.pzw")
    with open(pzw_path, "w", encoding="utf-8") as f:
        f.write(render_pzw(info["cells_x"], info["cells_y"],
                           f"{map_name}.bmp", placements, map_name,
                           project_dir=out_dir, zones=zones))

    csv_path = os.path.join(out_dir, f"{map_name}_placements.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                             ["file"])
        wtr.writeheader()
        wtr.writerows(rows)

    total_rooms = sum(r["rooms"] for r in rows)
    total_furn = sum(r["furniture"] for r in rows)
    print(f"footprints in geojson : {len(geo['features'])}")
    print(f"  too small (<{min_size})     : {skipped['small']}")
    print(f"  too large (>{max_size})   : {skipped['large']}")
    print(f"  outside the map     : {skipped['outside']}")
    print(f"  swallowed by others : {skipped['taken']}")
    print(f"  not buildings       : {skipped['not a building']} (roofs, ruins, tanks)")
    import collections as _c
    kinds = _c.Counter(r["kind"] for r in rows)
    styles = _c.Counter(r["style"] for r in rows)
    print(f"buildings generated   : {len(rows)}")
    print(f"  kinds               : {dict(kinds)}")
    print(f"  styles              : {dict(styles)}")
    shaped = sum(r['shaped'] for r in rows)
    print(f"  on real footprint   : {len(rows) - squared} turned, "
          f"{squared} squared up ({shaped} with irregular outlines)")
    print(f"  kind from land use  : {from_area}")
    print(f"  sheds and garages   : {sheds}")
    print(f"  storeys from nearby : {from_near}")
    storeys = _c.Counter(r["levels"] for r in rows)
    print(f"  storeys             : {dict(sorted(storeys.items()))}")
    pct = 100.0 * from_osm / len(rows) if rows else 0.0
    print(f"  heights from OSM    : {from_osm} of {len(rows)} ({pct:.1f}%), "
          f"rest inferred from footprint")
    print(f"  rooms               : {total_rooms}")
    print(f"  furniture pieces    : {total_furn}")
    print(f"wrote {pzw_path}")
    print(f"wrote {csv_path}")
    n_park = sum(1 for z in zones if z.kind == "ParkingStall")
    n_town = sum(1 for z in zones if z.kind == "TownZone")
    print(f"zones                 : {n_park} parking, {n_town} town")
    print(f"fences                : {fence_tiles} fence tiles in "
          f"{len(fence_placements)} lots")
    print(f"paper map             : {paper_map['map_features']} features in "
          f"{paper_map['map_cells']} cells, {paper_map['streets']} named streets, "
          f"{paper_map['labels']} labels")
    print(f"population            : {population['residents']:,} residents, "
          f"{population['daytime_occupants']:,} at work or school")
    print(f"zombie spawn map      : {population['share_with_zombies']:.1%} of chunks "
          f"populated, peak {population['peak_value']} (cap {population['horde_cap']}), "
          f"{population['chunks_at_cap']} chunks at the cap")
    # Not "place": that name is the footprint placer imported above, and a
    # loop variable of the same name makes it local to all of build().
    for town in population["official"]:
        print(f"  OSM says {town['name'] or town['place']}: "
              f"population {town['population']:,} ({town['place']})")
    print(f"wrote {len(rows)} .tbx files in {bdir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Place names can be in any script, and a Windows console using a legacy
    # code page cannot print most of them - "OSM says Kadıköy" crashed a build
    # on cp1252. Print what it can and mark the rest, rather than dying.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("output_dir", help="a Knoxify output/<mapname> folder")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--min-size", type=int, default=None,
                    help="skip footprints smaller than this many tiles")
    ap.add_argument("--max-size", type=int, default=None,
                    help="skip footprints larger than this many tiles")
    ap.add_argument("--preset", choices=sorted(PRESETS),
                    help="suburb / town / city / rural")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override one setting, repeatable "
                         "(e.g. --set window_density=0.6)")
    args = ap.parse_args(argv)

    # A saved settings.json in the map folder is the starting point, so the
    # command line and the app agree on what a given map was built with.
    out = args.output_dir
    saved = os.path.join(out, "settings.json")
    base = {}
    if os.path.exists(saved):
        try:
            with open(saved, encoding="utf-8") as f:
                base = json.load(f)
        except (OSError, ValueError):
            pass
    if args.preset:
        # A preset named on the command line replaces what was saved rather
        # than sitting underneath it. Merged the other way, every saved value
        # outranked the preset and --preset town quietly rebuilt a suburb.
        base = {"preset": args.preset}
    for item in args.set:
        key, _, value = item.partition("=")
        if not _:
            ap.error(f"--set wants KEY=VALUE, got {item!r}")
        base[key.strip()] = value.strip()
    settings = Settings.from_dict(base)
    return build(args.output_dir, seed=args.seed,
                 min_size=args.min_size, max_size=args.max_size,
                 settings=settings)


if __name__ == "__main__":
    raise SystemExit(main())
