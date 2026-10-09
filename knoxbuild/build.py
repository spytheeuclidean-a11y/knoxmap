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
import math
import random
import re
import os
import sys

import numpy as np
from shapely.geometry import Polygon

from generator.renderer import Projector

import knoxstop

from .areas import AreaIndex
from .bitmaps import read_gray, read_rgb, same_colour
from .fences import build_fences
from . import footprint
from .footprint import place
from .layout import build_building
from .uses import USE_KEYS, is_hotel, uses_of
from .context import Context, style_fits
from .population import build_spawn_map, official_population, save_footprints
from .profile import BuildingProfile
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
            or tags.get("heritage") not in (None, "", "no")
            or tags.get("building") in ("government", "public", "civic", "townhall")
            or "wikidata" in tags or "wikipedia" in tags)


# Theatres are a hall a few storeys high.
THEATRE_MAX_LEVELS = 3

# OSM values that identify a building as something other than a house. Checked
# against the building/amenity/shop/leisure/tourism/healthcare tags in turn.
SPECIAL_BY_VALUE = {
    "school": "school", "kindergarten": "school", "college": "school",
    "university": "school", "childcare": "school", "library": "library",
    "church": "church", "chapel": "church", "cathedral": "church",
    "mosque": "church", "synagogue": "church", "temple": "church",
    "place_of_worship": "church",
    "restaurant": "restaurant", "fast_food": "restaurant", "cafe": "restaurant",
    "bar": "restaurant", "pub": "restaurant", "food_court": "restaurant",
    "retail": "shop", "commercial": "shop", "supermarket": "shop",
    "convenience": "shop", "kiosk": "shop",
    "shop": "shop", "marketplace": "shop",
    # A shopping centre is not a big corner shop. As "shop" it took the shop
    # recipe - one sales floor the width of the front, stockrooms behind -
    # and a 92x72 one came out as a single room of 5,670 tiles with an
    # office block on top. Knox County's mall is a concourse with units off
    # it: Muldraugh 54_22 is 33.6% hall by floor, and the rest clothes,
    # department, furniture, gift, toy and book stores of 150 to 400 tiles.
    "mall": "mall", "department_store": "mall",
    "industrial": "industrial", "warehouse": "industrial",
    "factory": "industrial", "works": "industrial", "manufacture": "industrial",
    "garage": "garage", "garages": "garage", "car_repair": "garage",
    "barn": "barn", "farm": "barn", "farm_auxiliary": "barn",
    "greenhouse": "barn", "stable": "barn", "cowshed": "barn",
    "hospital": "medical", "clinic": "medical", "doctors": "medical",
    "dentist": "medical", "pharmacy": "medical", "veterinary": "medical",
    "apartments": "apartment", "residential": "apartment",
    "dormitory": "apartment", "terrace": "apartment",
    "civic": "civic", "public": "civic", "government": "civic",
    "townhall": "civic",
    # A police station, a library and a fire station have rooms of their own
    # in the game, with the loot that goes in them. As "civic" they came out
    # as an office block with a storeroom, which is what players reported
    # when a station they knew had nothing in it.
    "police": "police", "prison": "police", "fire_station": "fire",
    "hotel": "civic", "office": "civic", "courthouse": "civic",
    "museum": "civic", "bank": "civic", "post_office": "civic",
    "theatre": "civic", "cinema": "civic", "arts_centre": "civic",
    # Bases: barracks, armouries, the offices and stores of a military site.
    "military": "military", "barracks": "military", "bunker": "military",
    "armory": "military", "armoury": "military",
    # The buildings a town is known by, which had no kind at all and so were
    # ordinary housing: thinned like a house, grown like a house and given a
    # sofa and two bedrooms. A castle keeps its great hall and its chapel; a
    # ground is a concourse, changing rooms and a kit store.
    "castle": "castle", "fort": "castle", "fortress": "castle",
    "citadel": "castle", "manor": "castle", "palace": "castle",
    "city_gate": "castle",
    "stadium": "stadium", "sports_centre": "stadium", "sports_hall": "stadium",
    "grandstand": "stadium", "pavilion": "stadium", "arena": "stadium",
}

# Last resort when the tags say nothing useful but the name is obvious.
SPECIAL_BY_NAME = [
    ("school", "school"), ("academy", "school"), ("college", "school"),
    ("university", "school"), ("church", "church"), ("chapel", "church"),
    ("cathedral", "church"), ("hospital", "medical"), ("clinic", "medical"),
    ("pharmacy", "medical"), ("warehouse", "industrial"),
    ("factory", "industrial"), ("mill", "industrial"), ("plant", "industrial"),
    ("market", "shop"), ("mall", "mall"), ("store", "shop"), ("shop", "shop"),
    ("diner", "restaurant"), ("restaurant", "restaurant"), ("grill", "restaurant"),
    ("cafe", "restaurant"), ("bar ", "restaurant"), ("barn", "barn"),
    ("library", "library"), ("bibliot", "library"), ("kütüphane", "library"),
    ("police", "police"), ("polizei", "police"), ("polic", "police"),
    ("karakol", "police"), ("politie", "police"), ("gendarm", "police"),
    ("fire station", "fire"), ("feuerwehr", "fire"), ("itfaiye", "fire"),
    ("caserne de pompiers", "fire"), ("brandweer", "fire"),
    ("bank", "civic"), ("city hall", "civic"),
    ("apartment", "apartment"), ("apartmani", "apartment"),
    ("residence", "apartment"), ("towers", "apartment"), ("blok", "apartment"),
]

# Storeys, when OSM does not say and the area tables in regional.py do not
# cover the kind either. A town of nothing but bungalows reads as a film set
# - the skyline is what tells you whether you are downtown or in the suburbs.
DEFAULT_LEVELS = {
    "industrial": (1, 1),
    "garage": (1, 1),
    "barn": (1, 1),
    "shed": (1, 1),
    "church": (1, 1),
    "apartment": (3, 5),
    "civic": (2, 3),
    "school": (2, 3),
    "medical": (2, 4),
    "shop": (1, 2),
    "restaurant": (1, 2),
    "military": (1, 2),
    "police": (1, 2),
    "library": (1, 2),
    "fire": (1, 1),
    # A keep is tall and a stand is not. Kept short because the mix is dealt
    # again on every storey: at four levels a castle had four chapels.
    "castle": (2, 3),
    "stadium": (1, 2),
    # Knox County's mall runs to five storeys; two is the common one.
    "mall": (1, 2),
}

# Rows of units under one outline.
#
# OpenStreetMap maps a parade of shops, a strip mall or a terrace of houses as
# one polygon more often than not - the mapper drew the block, not the seven
# front doors in it - and built as one building it came out as a single shed
# with one door and one enormous room, whatever country the map was of. A
# footprint this much longer than it is deep, and no deeper than a shop unit
# is, is cut into units instead (footprint.split_row).
#
# Everything here is in metres, not tiles, so a map drawn at 2 m a tile splits
# the same row the same way as one drawn at half a metre.
ROW_KINDS = {None, "house", "apartment", "shop", "restaurant"}
ROW_RATIO = 2.2          # long side over short side
ROW_MIN_DEPTH_M = 5.0    # any shallower and a unit has no room in it
ROW_MAX_DEPTH_M = 32.0   # any deeper and it is a big shop, not a row
ROW_MIN_LENGTH_M = 22.0
# Frontages: a terraced house is narrower than a shop unit.
UNIT_FRONTAGE_M = {"house": 9.0, "apartment": 9.0}
SHOP_FRONTAGE_M = 13.0
# building=* values that say "row of houses" outright, in the countries whose
# mappers use them.
TERRACE_TAGS = {"terrace", "terraced", "semidetached_house", "row_house"}

# OpenStreetMap room= and amenity= values the game furnishes under a name of
# their own. Rooms a mapper drew inside a building (indoor=room) arrive with
# their tags, and where the tag names something Knox County knows, the room is
# built as that instead of guessed from its size (layout._mapped_rooms).
MAPPED_ROOM_KINDS = {
    "bedroom": "bedroom",
    "bathroom": "bathroom",
    "toilet": "bathroom",
    "kitchen": "kitchen",
    "living_room": "livingroom",
    "corridor": "hall",
    "hallway": "hall",
    "hall": "hall",
    "lobby": "lobby",
    "classroom": "classroom",
    "office": "office",
    "storage": "storage",
    "utility": "storage",
    "laundry": "laundry",
    "closet": "closet",
    "wardrobe": "closet",
    "library": "library",
    "laboratory": "schoollab",
    "stairs": "hall",
}


# And a building too big to be one building whatever it is.
#
# A room may be no bigger than the game will fill (layout.MAX_ROOM_AREA), so a
# footprint of forty thousand tiles came out as five hundred rooms in one
# .tbx - more than any hand-made building in the game has, and slow to lay
# out. Past this it is cut into blocks that stand wall to wall, which is what
# a shopping centre or a works of that size is anyway.
BIG_BUILDING_M2 = 6000.0
# A footprint past settings.max_size is kept and cut into units instead of
# dropped, but not without limit: a polygon this many tiles in area (about a
# square kilometre at one metre a tile) comes to hundreds of units, each laid
# out as a building of its own, and is a campus or an airfield mapped as one
# building rather than a building. Past it the old answer stands: left out.
MAX_OVERSIZE_TILES = 1_200_000


def _cut_big(units: list, metres_per_tile: float,
             max_side: int | None = None) -> list:
    """Cut anything left that is still too big to be one building.

    `max_side`, passed only for a footprint placed past settings.max_size
    (build.py, the "large" retry), is a hard cap on either side: the gate
    that used to throw such a building away no longer ran, so it is cut down
    to what the gate would have allowed instead. split_row leaves a piece
    whole when round(length / unit) comes to 1, so the cut target is 2/3 of
    the cap - a side over the cap is then always over 1.5 targets, which
    always divides, and every piece lands inside the cap.
    """
    import math

    from .footprint import split_row

    side = max(8, int(math.sqrt(BIG_BUILDING_M2) / max(0.05, metres_per_tile)))
    limit = side * side
    cut = side if max_side is None else min(side, max(4, (2 * max_side) // 3))

    def needs_cut(u) -> bool:
        return (u.width * u.height > limit
                or (max_side is not None and max(u.width, u.height) > max_side))

    out = list(units)
    for _ in range(4):
        if all(not needs_cut(u) for u in out):
            break
        nxt = []
        for u in out:
            nxt.extend(split_row(u, cut) if needs_cut(u) else [u])
        if len(nxt) == len(out):
            break
        out = nxt
    return out


def row_units(fp, special: str | None, btag: str, n_uses: int,
              metres_per_tile: float, max_side: int | None = None):
    """One footprint per unit of a row, or the footprint as it stands.

    `max_side` (see _cut_big) is passed only for a footprint that was too
    wide for settings.max_size and placed anyway, to be cut into units that
    fit rather than dropped.
    """
    from .footprint import split_row

    if special not in ROW_KINDS and btag not in TERRACE_TAGS:
        return _cut_big([fp], metres_per_tile, max_side)
    long_side = max(fp.width, fp.height) * metres_per_tile
    short_side = min(fp.width, fp.height) * metres_per_tile
    if short_side < ROW_MIN_DEPTH_M or long_side < ROW_MIN_LENGTH_M:
        return _cut_big([fp], metres_per_tile, max_side)
    terrace = btag in TERRACE_TAGS
    if not terrace:
        if short_side > ROW_MAX_DEPTH_M or long_side < short_side * ROW_RATIO:
            return _cut_big([fp], metres_per_tile, max_side)
    frontage = UNIT_FRONTAGE_M.get(special or "house", SHOP_FRONTAGE_M)
    if n_uses > 1:
        # The shops mapped inside it say how many units there really are;
        # keep the frontage sane so two shops in a long parade do not become
        # two units of fifty metres.
        frontage = min(max(frontage, long_side / n_uses), frontage * 2)
    return _cut_big(split_row(fp, max(5, int(round(frontage / metres_per_tile)))),
                    metres_per_tile, max_side)


# Kinds with no walls and windows of their own (knoxbuild/catalog.py
# SPECIAL_STYLES), dressed as the nearest kind that has: an army base is
# built like a works, a station or a library like any other public building.
STYLE_AS = {"military": "industrial", "fire": "industrial",
            "garage": "industrial", "police": "civic", "library": "civic"}


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
    # A mapper who recorded a height or a floor count has told us something,
    # but not everything. Three storeys up is a block of flats and one storey
    # is not; two says nothing, because a terraced row is two storeys and so
    # is a bungalow with an attic, and the footprint is what separates them.
    #
    # Taking two at face value made every large 2-storey building one house,
    # at any size: a 1200-tile terrace came out as a single dwelling with 25
    # rooms, six bedrooms and five bathrooms.
    measured = levels_from_tags(tags, settings)
    if measured is not None and measured >= 3:
        return True
    if measured == 1:
        return False
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
    # float() reads "inf", "Infinity", "nan" and "1e999" as numbers. None of them
    # is a height, and each one raised in the int() a few lines on - outside the
    # per-building handling, so one such tag stopped the whole build.
    if not math.isfinite(value):
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
                    rng, settings: Settings,
                    metres_per_tile: float = 1.0,
                    region: str | None = None) -> tuple[int, bool]:
    """How many storeys this building gets, and whether OSM said so.

    OSM's own height and level tags come first, as ever. Where it says
    nothing, the guess is the Arnis way: the kind and the real footprint
    together (knoxbuild/regional.py) - a 90 m2 footprint is a shop unit or
    somebody's house whatever country it is in, and a 2,500 m2 one is not a
    bungalow - with the region's own housing tables where the map is of
    somewhere whose housing does not run to Knox County's shapes.
    """
    from .regional import area_level_pool

    measured = levels_from_tags(tags, settings)
    if measured is not None:
        return measured, True
    lo, hi = DEFAULT_LEVELS.get(kind or "", (1, 2))
    if region == "cn":
        from .regional import CN_DEFAULT_LEVELS
        lo, hi = CN_DEFAULT_LEVELS.get(kind or "", (lo, hi))
    real_m2 = area_tiles * metres_per_tile * metres_per_tile
    pool = area_level_pool(kind, real_m2, region)
    if pool:
        return max(1, min(settings.max_levels, rng.choice(pool))), False
    return rng.randint(min(lo, settings.max_levels),
                       min(hi, settings.max_levels)), False


def classify_building(tags: dict) -> str | None:
    """The special kind for this building, or None for an ordinary one."""
    for key in ("amenity", "shop", "healthcare", "leisure", "tourism",
                "office", "industrial", "craft", "military", "historic",
                "building"):
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
        # military=* is the key mappers use for everything on a base -
        # armory, barracks, checkpoint, office, hangar, depot - and it was
        # not read at all, so an armoury came out as somebody's house.
        if key == "military" and value != "no":
            return "military"
    name = (tags.get("name") or "").lower()
    for needle, kind in SPECIAL_BY_NAME:
        if needle in name:
            return kind
    return None


def _business_kind(special: str | None, uses: list[tuple[str, str]]) -> str | None:
    """Promote retail outlines containing a mapped car-repair business to a garage."""
    if special in (None, "shop") and ("mechanic", "storage") in uses:
        return "garage"
    return special


# A public building has no wall style of its own, so it fell through to the
# house styles and a police station could come out in clapboard. These borrow
# another kind's, which is what such a building is built of.
BORROWED_STYLE = {"police": "civic", "library": "civic", "fire": "civic",
                  "military": "civic",
                  # Stone, not clapboard: a castle has no style of its own and
                  # the house styles would have built one out of weatherboard.
                  "castle": "church", "stadium": "civic", "mall": "civic"}
# Kinds that shipped with a single style, so every church in a county was the
# same church. The exterior wall is taken from a house style instead, whole -
# the entry carries its own window and door tiles, so nothing is mixed.
MORE_WALLS = {
    "church": ("brick", "stucco", "render", "painted"),
    "industrial": ("brick", "panel", "stucco"),
    "barn": ("timber", "panel", "clapboard"),
}
# ...and the walls inside. Every variant of a kind shared one interior wall,
# so a whole county of schools was painted the same colour indoors however
# many materials the outside came in. The house styles carry nine different
# ones between them and each is taken whole, window and door tiles with it.
MORE_INSIDE = {
    "school": ("brick", "painted", "stucco"),
    "church": ("timber", "painted", "clapboard"),
    "civic": ("painted", "stucco", "panel"),
    "shop": ("painted", "panel"),
    "apartment": ("brick", "painted", "stucco", "render"),
    "industrial": ("panel", "stucco"),
    "barn": ("timber", "panel"),
    "medical": ("painted", "stucco"),
    "restaurant": ("painted", "panel"),
}
# Of the buildings in a block, how many keep the block's own style. A street
# built at one time is mostly one material with later infills between; every
# house in 110 tiles being identical is what read as an estate rather than a
# street.
BLOCK_SHARE = 55


def wall_variants(kind: str) -> list[dict]:
    """Every style a building of this kind may be built in."""
    from . import catalog as C

    base = C.SPECIAL_STYLES[kind]
    out = list(getattr(C, "SPECIAL_STYLE_VARIANTS", {}).get(kind) or [base])
    houses = {s["name"]: s for s in C.HOUSE_STYLES}
    for name in MORE_WALLS.get(kind, ()):
        donor = houses.get(name)
        if not donor:
            continue
        variant = dict(base)
        variant["exterior"] = donor["exterior"]
        variant["name"] = f"{base['name']}_{name}"
        out.append(variant)
    inside = [(n, houses[n]["interior"]) for n in MORE_INSIDE.get(kind, ())
              if n in houses]
    if inside:
        grown = []
        for variant in out:
            grown.append(variant)
            for name, entry in inside:
                other = dict(variant)
                other["interior"] = entry
                other["name"] = f"{variant['name']}~{name}"
                grown.append(other)
        out = grown
    return out


def pick_style(kind: str | None, tile_x: int, tile_y: int, rng,
               settings: Settings, density: float = 0.0,
               profile: BuildingProfile | None = None,
               region: str | None = None) -> dict:
    """Materials for one building: its own if special, else its block's.

    Only styles that suit how built-up the place is are in the running, so the
    old town gets render and brick and the log cabins stay in the countryside.
    A Chinese map (or one set to Chinese) builds its houses from the flat-roofed
    masonry pool instead - unless the building is a dated prewar one, which
    keeps its pitched roof and era materials: the temple and the 1920s shophouse
    are the last things a regional pool should flatten.
    """
    from . import catalog as C
    from . import regional

    kind = BORROWED_STYLE.get(kind or "", kind)
    if kind and kind in C.SPECIAL_STYLES:
        variants = wall_variants(kind)
        if profile:
            picker = random.Random(profile.seed ^ 0xA37E)
            weights = [profile.style_weight(variant["name"]) for variant in variants]
            return picker.choices(variants, weights=weights, k=1)[0]
        # By the building's own position, so neighbours differ and a rebuild
        # picks the same again.
        return variants[(tile_x * 73856093 ^ tile_y * 19349663) % len(variants)]

    if region == "cn" and not (profile and profile.dated
                               and profile.era == "prewar"):
        pool = regional.cn_house_styles()
        styles = [s for s in pool if style_fits(s["name"], density)] or pool
    else:
        styles = [s for s in C.HOUSE_STYLES if style_fits(s["name"], density)] \
            or C.HOUSE_STYLES
    size = settings.neighbourhood_tiles
    block = (tile_x // size, tile_y // size)
    # Deterministic per block, so re-running gives the same town.
    idx = (block[0] * 73856093 ^ block[1] * 19349663) % len(styles)
    # ...and then per building, so a block is a street rather than one house
    # built over and over.
    own = (tile_x * 83492791 ^ tile_y * 297121507) & 0x7FFFFFFF
    if len(styles) > 1 and own % 100 >= BLOCK_SHARE:
        idx = (own // 100) % len(styles)
    if len(styles) > 1 and rng.random() < settings.style_oddity:
        idx = (idx + 1 + rng.randrange(len(styles) - 1)) % len(styles)
    if profile:
        weights = [profile.style_weight(style["name"])
                   * (1.4 if i == idx else 1.0)
                   for i, style in enumerate(styles)]
        picker = random.Random(profile.seed ^ 0xA37E)
        return picker.choices(styles, weights=weights, k=1)[0]
    return styles[idx]


STALL_W, STALL_H = 3, 5
CAR_PARK_LANE = 17            # two rows of 5, and a 7-tile lane


def car_park_stalls(bounds: tuple[int, int, int, int], w: int, h: int):
    """Where a stall could go in a car park with these bounds, as (x, y, sw, sh),
    in the order they are tried - only the ones that lie on the map.

    This used to walk the whole bounding box of the car park and throw away what
    was off the map afterwards. A car park a few hundred metres past the edge
    costs nothing; a polygon of the whole country mapped as one (it happens) was
    hundreds of millions of steps. Starting each run at the first position that
    can be on the map visits the same stalls in the same order."""
    x0, y0, x1, y1 = bounds
    across = (x1 - x0) >= (y1 - y0)          # rows run along the long side
    sw, sh = (STALL_W, STALL_H) if across else (STALL_H, STALL_W)
    # b runs along the rows, a across them; a + row is the offset of a stall's row.
    b_origin, b_len, b_map = (x0, x1 - x0, w) if across else (y0, y1 - y0, h)
    a_origin, a_len, a_map = (y0, y1 - y0, h) if across else (x0, x1 - x0, w)
    lane = CAR_PARK_LANE
    a_lo = max(0, -a_origin - STALL_H)
    a_start = -(-a_lo // lane) * lane
    a_stop = min(a_len, a_map - STALL_H - a_origin + 1)
    b_lo = max(0, -b_origin)
    b_start = -(-b_lo // STALL_W) * STALL_W
    b_stop = min(b_len, b_map - STALL_W - b_origin + 1)
    for a in range(a_start, a_stop, lane):
        for row in (0, STALL_H):
            for b in range(b_start, b_stop, STALL_W):
                x, y = (x0 + b, y0 + a + row) if across else (x0 + a + row, y0 + b)
                if 0 <= x and x + sw <= w and 0 <= y and y + sh <= h:
                    yield x, y, sw, sh


def _detect_zones(landscape_path: str, placements, rng_seed: int = 7,
                  settings: Settings | None = None, areas=None, drives=(),
                  keep_clear=(), road_hierarchy: np.ndarray | None = None):
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
    if road_hierarchy is not None:
        road_hierarchy = road_hierarchy[:h, :w]

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

    # A car on most drives, as in Knox County.
    for x, y, sw, sh in drives:
        if rng.random() <= min(1.0, 0.6 * settings.parking_density):
            taken.add((x // 8, y // 8))
            zones.append(Zone("ParkingStall", x, y, sw, sh))

    # Car parks OpenStreetMap maps as such: rows of stalls across the whole of
    # each, two rows back to back and then a lane, the way a real one is laid
    # out. Sampling the tarmac every 14 tiles found at most a stall or two in
    # anything smaller than a supermarket's, so most car parks had no cars.
    if areas is not None:
        from shapely.geometry import box

        buildings = [box(p.tile_x, p.tile_y, p.tile_x + p.width, p.tile_y + p.height)
                     for p in placements]
        from shapely import STRtree
        built = STRtree(buildings) if buildings else None
        lots = [shape for shape, props in areas._items if props.get("category") == "parking"]
        hard = ASPHALT | {C.PALE_CONCRETE, C.PAVING}
        for lot in lots:
            bounds = tuple(int(v) for v in lot.bounds)
            for x, y, sw, sh in car_park_stalls(bounds, w, h):
                stall = box(x, y, x + sw, y + sh)
                if not lot.contains(stall):
                    continue
                if any(px[i, j] not in hard for i in (x, x + sw - 1)
                       for j in (y, y + sh - 1)):
                    continue
                if built is not None and any(buildings[int(i)].intersects(stall)
                                             for i in built.query(stall)):
                    continue
                if rng.random() > min(1.0, 0.55 * settings.parking_density):
                    continue
                taken.add((x // 8, y // 8))
                zones.append(Zone("ParkingStall", x, y, sw, sh))

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
            if car_park:
                rate = 0.75
            elif road_hierarchy is None or not road_hierarchy[y, x]:
                rate = 0.45
            else:
                rate = {
                    1: 0.0, 2: 0.18, 3: 0.55, 4: 0.38,
                    5: 0.28, 6: 0.16, 7: 0.08, 8: 0.02,
                }.get(int(road_hierarchy[y, x]), 0.45)
            chance = rate * settings.parking_density
            if rng.random() > chance:
                continue
            vertical = is_asphalt(x, y - 2) or is_asphalt(x, y + 2)
            sw, sh = (STALL_W, STALL_H) if vertical else (STALL_H, STALL_W)
            # Not on a petrol station's forecourt, where the pumps stand.
            if any(x < fx + fw and fx < x + sw and y < fy + fh and fy < y + sh
                   for fx, fy, fw, fh in keep_clear):
                continue
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


STREET_LOOK_TILES = 40
RETAIL_DENSITY = 0.28


def _street_finder(out_dir: str, map_name: str,
                   road_hierarchy: np.ndarray | None = None):
    """A function giving the side ("N", "S", "W" or "E") of a footprint that
    faces the nearest pavement or road, or None if none is near."""
    import numpy as np
    from PIL import Image

    from generator import pz_colors as PC

    path = os.path.join(out_dir, f"{map_name}_ground_base.bmp")
    if not os.path.exists(path):
        path = os.path.join(out_dir, f"{map_name}.bmp")
    if not os.path.exists(path):
        return lambda *a: None
    g = read_rgb(path)
    paved = np.zeros(g.shape[:2], dtype=bool)
    for c in (PC.PALE_CONCRETE, PC.MEDIUM_ASPHALT, PC.DARKEST_ASPHALT):
        paved |= same_colour(g, c)
    H, W = paved.shape

    def side(x0: int, y0: int, w: int, h: int) -> str | None:
        best, best_score = None, STREET_LOOK_TILES + 1
        for name, (dx, dy) in (("N", (0, -1)), ("S", (0, 1)), ("W", (-1, 0)), ("E", (1, 0))):
            if dx == 0:
                starts = [(x0 + w * f // 4, y0 if dy < 0 else y0 + h - 1) for f in (1, 2, 3)]
            else:
                starts = [(x0 if dx < 0 else x0 + w - 1, y0 + h * f // 4) for f in (1, 2, 3)]
            for sx, sy in starts:
                for d in range(1, STREET_LOOK_TILES + 1):
                    x, y = sx + dx * d, sy + dy * d
                    if not (0 <= x < W and 0 <= y < H):
                        break
                    if paved[y, x]:
                        rank = (int(road_hierarchy[y, x])
                                if road_hierarchy is not None else 0)
                        score = d - min(5.0, rank * 0.6)
                        if score < best_score:
                            best, best_score = name, score
                        break
        return best

    return side


def _load_road_hierarchy(out_dir: str, map_name: str, proj) -> np.ndarray | None:
    from PIL import Image

    path = os.path.join(out_dir, f"{map_name}_road_hierarchy.bmp")
    if not os.path.exists(path):
        return None
    return read_gray(path, crop=(proj.height, proj.width))


def _road_weight(out_dir: str, map_name: str, proj,
                 road_hierarchy: np.ndarray | None = None) -> np.ndarray | None:
    """2 on carriageway, 1 on pavement, 0 elsewhere, from the ground as the
    renderer drew it."""
    from PIL import Image

    from generator import pz_colors as C

    path = os.path.join(out_dir, f"{map_name}_ground_base.bmp")
    if not os.path.exists(path):
        path = os.path.join(out_dir, f"{map_name}.bmp")
    if not os.path.exists(path):
        return None
    ground = read_rgb(path, crop=(proj.height, proj.width))
    weight = np.zeros(ground.shape[:2], dtype=np.int8)
    for colour in (C.PALE_CONCRETE,):
        weight[same_colour(ground, colour)] = 1
    for colour in (C.DARK_ASPHALT, C.MEDIUM_ASPHALT, C.LIGHT_ASPHALT,
                   C.DARKEST_ASPHALT, C.DARK_POTHOLE, C.LIGHT_POTHOLE):
        weight[same_colour(ground, colour)] = 2
    if road_hierarchy is not None:
        # The mask includes each road's sidewalk width. Larger road classes
        # carry a stronger cost so footprints settle behind local streets.
        classified = road_hierarchy[:proj.height, :proj.width]
        weight[classified > 0] = classified[classified > 0]
    return weight


def _points_of_use(out_dir: str, info: dict, map_name: str, proj) -> dict:
    """Point features from OSM, bucketed by tile for nearby-footprint lookup."""
    from generator import osm
    bbox = info.get("bbox") or {}
    cache = os.path.join(out_dir, info["osm_cache"]) if info.get("osm_cache")         else osm.cache_path(out_dir, map_name)
    wanted = tuple(info["osm_bbox"]) if info.get("osm_bbox") else         (bbox.get("south"), bbox.get("west"), bbox.get("north"), bbox.get("east"))
    grid: dict = {}
    feats = osm.load_cache(cache, wanted) or []
    if info.get("straight_roads") and feats:
        # Where the renderer moved them to, with the roads straightened.
        from generator.octilinear import straighten_roads
        from generator.renderer import _is_polygon, classify
        straighten_roads(feats, proj, classify, _is_polygon)
    for feat in feats:
        if feat.kind != "node" or not (
            any(k in feat.tags for k in USE_KEYS) or "entrance" in feat.tags):
            continue
        lat, lon = feat.geometry[0]
        x, y = proj.to_px(lat, lon)
        grid.setdefault((int(x) // 16, int(y) // 16), []).append((x, y, feat.tags))
    return grid


def _points_inside(grid: dict, px: list, taken: set) -> list[dict]:
    """The tags of the points inside a footprint (or just outside its wall,
    where a mapper put the shop's entrance), each point used once."""
    if not grid:
        return []
    from shapely.geometry import Point
    poly = Polygon(px)
    if not poly.is_valid:
        poly = poly.buffer(0)
    zone = poly.buffer(1.0)
    minx, miny, maxx, maxy = zone.bounds
    out = []
    for gx in range(int(minx) // 16, int(maxx) // 16 + 1):
        for gy in range(int(miny) // 16, int(maxy) // 16 + 1):
            for x, y, tags in grid.get((gx, gy), ()):
                key = (x, y)
                if (any(k in tags for k in USE_KEYS) and key not in taken
                        and zone.contains(Point(x, y))):
                    taken.add(key)
                    out.append((x, y, tags))
    return [tags for _x, _y, tags in out]


def _entrances_inside(grid: dict, px: list) -> list[tuple[float, float, dict]]:
    """Entrance nodes on or just outside a building outline, in map tiles."""
    if not grid:
        return []
    from shapely.geometry import Point
    poly = Polygon(px)
    if not poly.is_valid:
        poly = poly.buffer(0)
    zone = poly.buffer(1.5)
    minx, miny, maxx, maxy = zone.bounds
    out = []
    for gx in range(int(minx) // 16, int(maxx) // 16 + 1):
        for gy in range(int(miny) // 16, int(maxy) // 16 + 1):
            for x, y, tags in grid.get((gx, gy), ()):
                if "entrance" in tags and zone.contains(Point(x, y)):
                    out.append((x, y, tags))
    return out


def _entrances_by_unit(entrances: list[tuple[float, float, dict]], units
                       ) -> list[list[tuple[float, float, dict]]]:
    """Assign each mapped entrance to its closest unit and make it local."""
    assigned = [[] for _ in units]
    for x, y, tags in entrances:
        closest = None
        for i, unit in enumerate(units):
            lx, ly = x - unit.x0, y - unit.y0
            ix0, iy0 = math.floor(lx), math.floor(ly)
            distance = float("inf")
            for iy in range(max(0, iy0 - 1), min(unit.height, iy0 + 2)):
                for ix in range(max(0, ix0 - 1), min(unit.width, ix0 + 2)):
                    if not unit.mask[iy, ix]:
                        continue
                    dx = max(ix - lx, 0.0, lx - ix - 1)
                    dy = max(iy - ly, 0.0, ly - iy - 1)
                    distance = min(distance, dx * dx + dy * dy)
            if closest is None or distance < closest[0]:
                closest = (distance, i, lx, ly)
        if closest is not None and closest[0] <= 2.25:
            _distance, i, lx, ly = closest
            assigned[i].append((lx, ly, tags))
    return assigned


def _rooms_by_unit(entries, fp, units, proj) -> list:
    """The building's mapped rooms (renderer._buildings_geojson), moved with
    the placed footprint and shared out between the units it was cut into.

    Returns one list per unit of (ring, kind): the ring in that unit's own
    tiles, kind from the OSM room tag where the game knows it (None = cut as
    drawn but furnished by the usual rules). A room whose centre falls in no
    unit - outside the footprint after squaring up - is left out.
    """
    out: list = [[] for _ in units]
    if not entries:
        return out
    turned = fp.point_rotation or fp.point_offset != (0.0, 0.0)
    for entry in entries:
        ring = entry.get("ring") or []
        if len(ring) < 3:
            continue
        pts = [proj.to_px(lat, lon) for lon, lat in ring]
        if turned:
            pts = [fp.transform_point(x, y) for x, y in pts]
        room = str(entry.get("room") or "").strip().lower()
        amenity = str(entry.get("amenity") or "").strip().lower()
        kind = MAPPED_ROOM_KINDS.get(room) or MAPPED_ROOM_KINDS.get(amenity)
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        for n, unit in enumerate(units):
            if unit.x0 <= cx < unit.x0 + unit.width \
                    and unit.y0 <= cy < unit.y0 + unit.height:
                local = [(int(round(x - unit.x0)), int(round(y - unit.y0)))
                         for x, y in pts]
                out[n].append((local, kind))
                break
    return out


def _party_walls(owner: np.ndarray, me: int, x0: int, y0: int, mask: np.ndarray,
                 levels: list[int]) -> dict:
    """{(x, y, "N" or "W"): storeys of the neighbour} for each outside wall
    of building `me` with another building's tile beyond it, in the
    building's own coordinates, as doors and windows name wall edges."""
    out: dict = {}
    h, w = mask.shape
    mh, mw = owner.shape
    for ly in range(h):
        for lx in range(w):
            if not mask[ly, lx]:
                continue
            for dx, dy, edge in ((0, -1, (lx, ly, "N")), (0, 1, (lx, ly + 1, "N")),
                                 (-1, 0, (lx, ly, "W")), (1, 0, (lx + 1, ly, "W"))):
                nx, ny = lx + dx, ly + dy
                if 0 <= nx < w and 0 <= ny < h and mask[ny, nx]:
                    continue
                wx, wy = x0 + nx, y0 + ny
                if 0 <= wx < mw and 0 <= wy < mh:
                    other = owner[wy, wx]
                    if other >= 0 and other != me:
                        out[edge] = max(out.get(edge, 0), levels[other])
    return out


def _make_one(job: tuple) -> tuple:
    """Lay out one building and write its .tbx. Returns (storeys, rooms,
    furniture, error): a building that cannot be laid out is left out with the
    reason, instead of stopping the other two thousand."""
    (w, h, levels, commercial, seed, kind, mask, settings, style, label, path, street, retail,
        uses, hotel, entrances, profile, mapped, garage_door, party) = job
    try:
        plan = build_building(w, h, levels=levels, commercial=commercial, seed=seed,
                              kind=kind, mask=mask, settings=settings, street=street,
                              retail=retail, uses=uses, hotel=hotel, party=party,
                              entrances=entrances, profile=profile,
                              mapped=mapped, garage_door=garage_door)
        text = render_tbx(plan, label, style)
    except Exception:  # noqa: BLE001
        import traceback
        return (0, 0, 0, f"{os.path.basename(path)} ({kind or 'house'}, {w}x{h}, "
                         f"{levels} storeys): {traceback.format_exc()}", [])
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return (len(plan.storeys), len(plan.rooms),
            sum(len(s.furniture) for s in plan.storeys), None,
            list(plan.escalators))


# Below this many buildings, starting worker processes costs more than it saves.
PARALLEL_FROM = 60

# What the last build made, kept beside its files so that building again - a new
# zombie setting, a few footprints moved - lays out only the buildings whose
# inputs changed. A building's .tbx depends on nothing but its own job (every
# random choice is seeded from it, see tbx._stable_seed) and on the code that
# lays it out, so the same job under the same code gives the same file.
CACHE_FILE = "build_cache.json"   # in the map folder, not buildings/: that is all .tbx


def _code_fingerprint() -> str:
    """Changes whenever the code that lays a building out does, or the tiles it
    may use. A cache from other code is not trusted: the same job would come
    out differently."""
    import hashlib

    from .layout import _erika_ready

    h = hashlib.sha1()
    here = os.path.dirname(os.path.abspath(__file__))
    for name in sorted(os.listdir(here)):
        if name.endswith(".py"):
            h.update(name.encode())
            with open(os.path.join(here, name), "rb") as f:
                h.update(f.read())
    h.update(b"erika" if _erika_ready() else b"vanilla")
    return h.hexdigest()


def _job_key(job: tuple) -> str:
    """A building's inputs as one string. The file name (index 10) is left out:
    numbers shift when a footprint is added, and the building does not change."""
    import hashlib
    import pickle

    return hashlib.sha1(pickle.dumps(job[:10] + job[11:], protocol=4)).hexdigest()


def _read_cache(out_dir: str, code: str) -> dict:
    try:
        with open(os.path.join(out_dir, CACHE_FILE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("code") != code:
        return {}
    return data.get("buildings") or {}


def _write_cache(out_dir: str, code: str, entries: dict) -> None:
    try:
        tmp = os.path.join(out_dir, CACHE_FILE + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"code": code, "buildings": entries}, f)
        os.replace(tmp, os.path.join(out_dir, CACHE_FILE))
    except OSError:
        pass          # no cache means the next build lays everything out again


def _make_all(jobs: list[tuple], tick=None) -> list[tuple[int, int, int]]:
    """Every building, in order, across processes when there are enough.

    KNOXBUILD_WORKERS=1 forces one process. If worker processes cannot start
    at all - some locked-down PCs refuse them - the work simply runs here.
    `tick(done, total)` is called as results come in, for a progress readout.
    """
    def run_here() -> list:
        out = []
        for job in jobs:
            out.append(_make_one(job))
            if tick and len(out) % 25 == 0:
                tick(len(out), len(jobs))
        return out

    workers = int(os.environ.get("KNOXBUILD_WORKERS") or
                  max(1, min(12, (os.cpu_count() or 2) - 2)))
    if workers <= 1 or len(jobs) < PARALLEL_FROM:
        return run_here()
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool

    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            out = []
            for result in pool.map(_make_one, jobs,
                                   chunksize=max(4, len(jobs) // (workers * 8))):
                out.append(result)
                if tick and len(out) % 25 == 0:
                    tick(len(out), len(jobs))
            return out
    except (BrokenProcessPool, OSError) as exc:
        print(f"  (worker processes unavailable: {exc}; building in one process)")
        return run_here()


def build(out_dir: str, seed: int | None = None, min_size: int | None = None,
          max_size: int | None = None, settings: Settings | None = None,
          should_stop=None, progress=None) -> int:
    """Generate every building for a rendered map.

    The explicit seed/min_size/max_size arguments are kept so the command line
    can override one value without composing a whole Settings.

    `progress(text, fraction)`, when given, is called as the work moves on:
    a short account of the stage, and how far through the whole run it is
    (0 to 1, or None when that is not known). The fractions are rough: where
    each stage starts, not a measured share of the time.
    """
    def say(text: str, fraction: float | None = None) -> None:
        if progress:
            progress(text, fraction)

    say("Reading the map", 0.0)
    settings = settings or Settings()
    overrides = {k: v for k, v in (("seed", seed), ("min_size", min_size),
                                   ("max_size", max_size)) if v is not None}
    if overrides:
        settings = Settings.from_dict({**settings.to_dict(), **overrides})
    # Before any building is laid out: the mod-tile check is asked once and
    # remembered, so saying this afterwards would be too late for the first.
    from .layout import use_mod_tiles
    use_mod_tiles(not settings.vanilla_tiles)
    seed = settings.seed
    min_size = settings.min_size
    max_size = settings.max_size
    names = [f for f in os.listdir(out_dir) if f.endswith("_info.json")]
    if not names:
        print(f"no <name>_info.json in {out_dir}", file=sys.stderr)
        return 2
    map_name = names[0][: -len("_info.json")]

    with open(os.path.join(out_dir, f"{map_name}_info.json"), encoding="utf-8") as f:
        info = json.load(f)
    with open(os.path.join(out_dir, f"{map_name}_buildings.geojson"), encoding="utf-8") as f:
        geo = json.load(f)

    bbox = info["bbox"]
    proj = Projector.build(bbox["south"], bbox["west"], bbox["north"],
                           bbox["east"], info["meters_per_tile"],
                           info.get("rotation") or 0.0)
    if (proj.width, proj.height) != (info["width_tiles"], info["height_tiles"]):
        print("projection does not match the rendered BMP - is this folder "
              "from a different Knoxify version?", file=sys.stderr)
        return 2
    road_hierarchy = _load_road_hierarchy(out_dir, map_name, proj)

    # What part of the world the survey is of, read from the names on its own
    # buildings (knoxbuild/regional.py). Only Chinese housing is built its own
    # way for now; anywhere else keeps the game's shapes, and `arch_style`
    # forces the question either way.
    from . import regional
    region = None
    if settings.arch_style == "cn":
        region = "cn"
    elif settings.arch_style != "off":
        region = regional.detect_region(geo, bbox)

    # Where this map stands in the world, beside any other KnoxMap map on
    # this PC rather than on top of it (knoxbuild/world.py). Everything
    # below - the paper map, the zones, the compiled cells - is written from
    # here on, so it is settled first.
    from .world import choose_origin, origin, set_origin
    set_origin(choose_origin(out_dir, info["cells_x"], info["cells_y"]))

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
    # What the last build left. Building numbers follow the footprints, so a
    # rebuild does not overwrite the same set of files, and leftovers from an
    # earlier run would sit in the folder looking like part of the map: the
    # ones this build does not write are removed once it has finished (below),
    # and the ones it can reuse are left alone until then.
    earlier_files = {f for f in os.listdir(bdir) if f.endswith(".tbx")}
    code = _code_fingerprint()
    earlier = _read_cache(out_dir, code)
    # Gone until this build has finished and written it again. A build that
    # stops half way leaves some files rewritten and some not, and a cache
    # that still described the old ones would vouch for the wrong files.
    try:
        os.remove(os.path.join(out_dir, CACHE_FILE))
    except OSError:
        pass
    # WorldEd writes into these but will not create them: BMP to TMX fails with
    # "Could not open file for writing" if the export directory is absent.
    os.makedirs(os.path.join(out_dir, "tmx"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "lots"), exist_ok=True)

    import random as _random
    style_rng = _random.Random(seed ^ 0x5EED)

    placements: list[Placement] = []
    rows = []
    skipped = {"small": 0, "large": 0, "outside": 0, "taken": 0, "road": 0,
               "not a building": 0}
    sheds = 0        # outbuildings given a single storage room
    from_near = 0    # storeys borrowed from tagged neighbours
    from_osm = 0   # buildings whose storey count came from the data
    from_area = 0  # buildings whose kind came from the land around them
    squared = 0    # buildings close enough to the grid to square up
    rows_split = 0   # rows of shops or terraces cut into their units
    units_made = 0   # and how many buildings those became
    split_large = 0  # and buildings past max_size kept by cutting them

    areas = AreaIndex.load(out_dir, map_name, proj)
    points = _points_of_use(out_dir, info, map_name, proj)
    points_taken: set = set()
    with_uses = 0
    # (x0, y0, mask, storeys, kind) for the population estimate.
    peopled: list[tuple[int, int, np.ndarray, int, str]] = []
    # Real outlines of the buildings placed, for the in-game paper map.
    outlines: list[tuple[list[tuple[float, float]], str, str]] = []
    occupied = np.zeros((proj.height, proj.width), dtype=bool)
    # ...and the ground covered by a lot rectangle rather than by a building's
    # own tiles, which is more ground whenever the footprint is not a rectangle
    # (footprint._clear_box). Lots may not overlap: WorldEd writes each of them
    # into the same cell layers, so where two cover a square only one survives.
    lots = np.zeros((proj.height, proj.width), dtype=bool)
    # Knox County roads: every building upright, and stood clear of the roads.
    road_weight = _road_weight(out_dir, map_name, proj, road_hierarchy)

    # Biggest footprints claim their tiles first. Where two real buildings
    # share a wall, one of them has to give up that row of tiles, and it should
    # not be the town hall giving way to the shed behind it.
    order = []
    jobs: list[tuple] = []       # what each building needs to lay itself out
    street_side = _street_finder(out_dir, map_name, road_hierarchy)
    stations: list[tuple] = []   # petrol stations, for their pumps
    gunshops: set[str] = set()   # and the buildings OSM says sell weapons
    canopies: list[list] = []    # and the canopies over their forecourts
    decided: list[tuple] = []    # and what the map needs to know about it
    surroundings: list[tuple[float, float, float, int | None]] = []
    centres: dict[int, tuple[float, float]] = {}   # each building's centroid
    for i, feat in enumerate(geo["features"]):
        pts = _ring_points(feat["geometry"])
        if len(pts) < 3:
            continue
        tags = feat.get("properties", {})
        if (tags.get("building") or "").strip().lower() in NOT_BUILDINGS:
            skipped["not a building"] += 1
            if tags.get("amenity") == "fuel":
                # A petrol station's canopy: its forecourt, pumps underneath.
                canopies.append([proj.to_px(lat, lon) for lon, lat in pts])
            continue
        px = [proj.to_px(lat, lon) for lon, lat in pts]
        poly = Polygon(px)
        if not poly.is_valid:
            poly = poly.buffer(0)
        order.append((-poly.area, i, px))
        centre = poly.centroid
        if not centre.is_empty:
            centres[i] = (centre.x, centre.y)
            surroundings.append((centre.x, centre.y, poly.area,
                                 levels_from_tags(tags, settings)))
    order.sort()
    # A town laid out for the game rather than copied from the survey: about
    # half the ordinary houses left out and what stays grown to a size worth
    # walking into, landmarks kept whatever and placed first so the ground a
    # police station needs is still free (knoxbuild/procedural.py). With
    # true_map on, nothing here runs and the order is the one it always was.
    thinning: dict = {}
    if not settings.true_map:
        from .procedural import HOUSING, Candidate, plan
        cands = []
        m2_per_tile = info["meters_per_tile"] ** 2
        for _neg_area, i, px in order:
            tags = geo["features"][i].get("properties", {})
            kind = classify_building(tags)
            if kind is None:
                # What the land around it says, as the placement loop asks
                # below. Without this the huts on an army base and the wings
                # of a hospital look like untagged houses here and are
                # thinned away, and the base loses the building the whole
                # map's rifles were going to spawn in. Sheds are left out of
                # it for the same reason the loop leaves them out: a garage
                # on an industrial estate is a garage, not a works.
                btag = (tags.get("building") or "").strip().lower()
                if (-_neg_area * m2_per_tile > SHED_MAX_M2
                        and btag not in SHED_VALUES):
                    # Already worked out above; building the polygon again
                    # for every candidate was Shapely done twice per building.
                    centre = centres.get(i)
                    if centre is not None:
                        kind = areas.kind_for(centre[0], centre[1], int(-_neg_area))
            notable = is_notable(tags, kind)
            # Only housing can be thinned, so only housing has to be checked
            # for the shop or surgery mapped inside it; anything else is a
            # landmark already. A throwaway `taken` set, because the real one
            # is filled below, as each building claims its points for good.
            has_use = (not notable and kind in HOUSING
                       and bool(_points_inside(points, px, set())))
            cands.append(Candidate(i, px, -_neg_area, kind, notable, has_use))
        kept, thinning = plan(cands, max_size)
        order = [(-c.area, c.index, c.px) for c in kept]
    metres_per_tile = info["meters_per_tile"]
    context = Context(proj.width, proj.height, surroundings, metres_per_tile,
                      road_hierarchy=road_hierarchy)

    # The buildings past max_size are not placed with the rest: they are kept
    # (below) but only after everything else has its ground. The order here is
    # largest first, and an outline that claims its whole area before the
    # buildings inside it are placed leaves them "taken" - a campus mapped as one
    # building would lose every house and hall standing in it, where before it
    # was simply left out and they all stayed. Placed last, it takes what is free.
    deferred_large: list = []

    def candidates():
        for neg_area, idx, points in order:
            yield neg_area, idx, points, False
        for neg_area, idx, points in deferred_large:
            yield neg_area, idx, points, True

    for placed_so_far, (_neg_area, i, px, retry) in enumerate(candidates()):
        # Between buildings: nothing is written to disk until the whole run
        # is laid out, so stopping here costs only the time spent.
        if placed_so_far % 64 == 0:
            knoxstop.check(should_stop, "the buildings")
        feat = geo["features"][i]
        oversize = False
        if retry:
            # A building past max_size is not thrown away any more: the
            # factory and the hangar are the landmarks a place is known by,
            # and dropping them left a hole exactly where the eye looks. The
            # gate measured the real building's long side, so it is tried
            # again without that one gate (place claimed nothing before
            # refusing) and cut into units that fit further down, in
            # row_units - which is what it is anyway, works of that size
            # being several blocks wall to wall.
            fp, reason = place(px, occupied, min_side=min_size, max_side=1e9,
                       snap_degrees=settings.square_buildings,
                       avoid=road_weight, lots=lots,
                       alignment=settings.building_alignment)
            oversize = fp is not None
        else:
            fp, reason = place(px, occupied, min_side=min_size, max_side=max_size,
                       snap_degrees=settings.square_buildings,
                       avoid=road_weight, lots=lots,
                       alignment=settings.building_alignment)
            if fp is None and reason == "large":
                if -_neg_area <= MAX_OVERSIZE_TILES:
                    deferred_large.append((_neg_area, i, px))
                else:
                    skipped["large"] += 1
                continue
        if fp is None:
            skipped[reason] += 1
            continue
        x0, y0, w, h = fp.x0, fp.y0, fp.width, fp.height
        if fp.angle <= 8.0:
            squared += 1

        tags = feat.get("properties", {})
        # Rooms the mapper drew inside it, if OSM has any for this building
        # (renderer._buildings_geojson attaches them to their building).
        mapped = feat.get("properties", {}).get("rooms") or []
        btag = (tags.get("building") or "").strip().lower()
        cx = x0 + w / 2
        cy = y0 + h / 2
        real_m2 = fp.tiles * metres_per_tile * metres_per_tile
        special = classify_building(tags)
        # What is really in it: its own tags and the shops, restaurants and
        # offices mapped as points inside it.
        inside = [tags] + _points_inside(points, px, points_taken)
        uses = uses_of(inside)
        special = _business_kind(special, uses)
        if special == "garage":
            sheds += 1
        entrance_points = _entrances_inside(points, px)
        hotel = is_hotel(inside)
        if ("gasstore", "storage") in uses:
            stations.append((x0, y0, w, h, street_side(x0, y0, w, h)))
        offices_only = bool(uses) and all(u == ("office", "office") for u in uses)
        if uses:
            with_uses += 1
        if offices_only and special in (None, "house"):
            special = "civic"          # an office building
        elif uses and not offices_only and special in (None, "house", "shed"):
            special = "shop"           # flats over it, below, if it is tall
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
                                           style_rng, settings,
                                           metres_per_tile=metres_per_tile,
                                           region=region)
        if measured:
            from_osm += 1
        elif nearby is not None and (special or "house") in FOLLOWS_NEIGHBOURS:
            top = settings.max_levels
            if special is None:
                # A Chinese self-built house runs a storey taller than the
                # game's houses before the neighbours' heights are heard.
                top = min(top, HOUSE_MAX_LEVELS + 1 if region == "cn"
                          else HOUSE_MAX_LEVELS)
            levels = max(1, min(top, int(round(nearby)) +
                                style_rng.choice((-1, 0, 0, 1))))
            from_near += 1
        if hotel:
            special = "apartment"      # its flats are guest rooms
        elif any(back == "theatre" for _front, back in uses):
            # A theatre is its auditorium behind a foyer on the street, and a
            # few storeys of hall, not a tower.
            special = "civic"
            levels = min(levels, THEATRE_MAX_LEVELS)
        elif special in ("shop", "restaurant") and uses and levels >= 3 and \
                btag not in ("retail", "commercial", "supermarket", "shop", "kiosk"):
            # A pizza place in a five-storey building is flats over a pizza
            # place, not a five-storey pizza place - unless the building is
            # offices: a company inside it, or a name like "Americas Tower".
            offices = ("office", "office") in uses or btag == "office" or re.search(
                r"\b(tower|building|plaza|center|centre|exchange)\b", tags.get("name") or "", re.I)
            special = "civic" if offices else "apartment"
        local_density = context.density(cx, cy)
        profile = BuildingProfile.infer(tags, special, local_density, real_m2,
                                        levels, seed + i * 31)
        # Hotels are dressed as the city's big buildings, army bases as works,
        # and the public buildings that have no walls of their own as civic.
        style = pick_style(STYLE_AS.get("civic" if hotel else special, special),
                           x0, y0, style_rng, settings,
                           density=local_density, profile=profile,
                           region=region)
        if profile.wear < 0.18 and style.get("grime"):
            style = dict(style)
            style.pop("grime", None)

        name = tags.get("name") or ""
        real_name = name if is_notable(tags, special) else ""
        # A row of shops or a terrace of houses is one polygon here; built as
        # one building it is the "uber building" players reported. Each unit
        # becomes its own building, standing wall to wall with the next.
        units = row_units(fp, special, btag, len(uses), metres_per_tile,
                          max_side=max_size if oversize else None)
        if oversize:
            split_large += 1
        unit_mapped = _rooms_by_unit(mapped, fp, units, proj)
        placed_entrances = [(x, y, tags) for x, y, tags in entrance_points]
        if fp.point_rotation or fp.point_offset != (0.0, 0.0):
            placed_entrances = [(*fp.transform_point(x, y), tags)
                                for x, y, tags in entrance_points]
        entrances_by_unit = _entrances_by_unit(placed_entrances, units)
        if len(units) > 1:
            rows_split += 1
            units_made += len(units)
        for n, unit in enumerate(units):
            ux0, uy0 = unit.x0, unit.y0
            uw, uh = unit.width, unit.height
            umask = unit.mask_list()
            # Each unit keeps one of the uses found in the whole row, in the
            # order they were found, so a parade of shops is a parade and not
            # seven copies of the same one.
            unit_uses = [uses[n % len(uses)]] if uses and len(units) > 1 else uses
            fname = f"{map_name}_{i:04d}.tbx" if len(units) == 1 else \
                f"{map_name}_{i:04d}_{n:02d}.tbx"
            label = (f"{name} {n + 1}" if name and len(units) > 1 else
                     name or f"{map_name} building {i}")
            if ("gunstore", "storage") in unit_uses:
                gunshops.add(fname)
            jobs.append((uw, uh, levels, commercial, seed + i * 31 + n, special, umask,
                         settings, style, label, os.path.join(bdir, fname),
                         street_side(ux0, uy0, uw, uh),
                         # Shops under flats where the town is built up.
                         context.density(cx, cy) >= RETAIL_DENSITY,
                         # What the ground floor really is, and a hotel's rooms.
                         unit_uses, hotel, entrances_by_unit[n], profile,
                         unit_mapped[n],
                         btag in ("garage", "garages")
                         or special in ("garage", "fire")))
            outline = px if len(units) == 1 else [
                (ux0, uy0), (ux0 + uw, uy0), (ux0 + uw, uy0 + uh), (ux0, uy0 + uh)]
            decided.append((fname, label, ux0, uy0, uw, uh, unit, outline, special,
                            measured, commercial, style, umask,
                            real_name if n == 0 else ""))

    # Walls shared with the building next door, now every building has its
    # tiles: no window, shop window or door goes in one, up to the height of
    # the neighbour. Laid out on its own footprint, a terrace of shops had
    # glass shop fronts and windows looking into the next shop.
    owner = np.full((proj.height, proj.width), -1, dtype=np.int32)
    for j, d in enumerate(decided):
        dx0, dy0, dw, dh, dfp = d[2], d[3], d[4], d[5], d[6]
        view = owner[dy0:dy0 + dh, dx0:dx0 + dw]
        view[dfp.mask[:view.shape[0], :view.shape[1]]] = j
    for j, d in enumerate(decided):
        jobs[j] = jobs[j] + (_party_walls(owner, j, d[2], d[3], d[6].mask,
                                          [job[2] for job in jobs]),)

    # Every decision above is made in order, from one random stream, so the
    # town comes out the same each time. What is left - laying out rooms and
    # writing the files - depends only on each building's own seed, so it runs
    # across processes: a 4,000-building district took three minutes on one.
    failed_buildings = []
    escalator_squares: list = []
    keys = [_job_key(job) for job in jobs]
    results: list = [None] * len(jobs)
    todo = []
    for j, d in enumerate(decided):
        old = earlier.get(d[0])
        if (old and old.get("key") == keys[j] and d[0] in earlier_files
                and os.path.exists(os.path.join(bdir, d[0]))):
            storeys, rooms, furniture, escalators = old["result"]
            results[j] = (storeys, rooms, furniture, None,
                          [tuple(e) for e in escalators])
        else:
            todo.append(j)
    reused = len(jobs) - len(todo)
    if reused:
        print(f"reused {reused} of {len(jobs)} buildings from the last build")
    say(f"Laying out {len(todo):,} buildings"
        + (f" ({reused:,} reused from the last build)" if reused else ""), 0.05)

    def laid_out(done: int, total: int) -> None:
        say(f"Laying out buildings: {done:,} of {total:,}", 0.05 + 0.55 * done / total)

    for j, result in zip(todo, _make_all([jobs[j] for j in todo], laid_out)):
        results[j] = result

    for (fname, label, x0, y0, w, h, fp, px, special, measured, commercial,
         style, mask, real_name), (storeys, rooms, furniture, error,
                                   escalators) in zip(decided, results):
        if error:
            failed_buildings.append(error)
            continue
        # A mall's escalators stand in its atrium and carry two tiles on some
        # squares, so they are packed as their own lot rather than written
        # into the building (knoxbuild/catalog.escalator_tiles).
        for ex, ey in escalators:
            from . import catalog as _C
            escalator_squares.extend(_C.escalator_tiles(x0 + ex, y0 + ey,
                                                          west=True))
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
            "building": btag,
            "style": style["name"],
            "shaped": int(mask is not None),
            "angle": round(fp.angle, 1),
        })
    rows.sort(key=lambda r: r["file"])
    knoxstop.check(should_stop, "the buildings")

    # Remember what was made, and clear out what was left from before and not
    # written this time.
    entries = {d[0]: {"key": keys[j], "result": [r_[0], r_[1], r_[2], r_[4]]}
               for j, (d, r_) in enumerate(zip(decided, results)) if not r_[3]}
    _write_cache(out_dir, code, entries)
    for stale in earlier_files - set(entries):
        try:
            os.remove(os.path.join(bdir, stale))
        except OSError:
            pass

    # One military rifle somewhere on the map, whatever this town turned out
    # to be: an army building, else the police station, else a gun shop, else
    # a house on the edge of town (knoxbuild/guns.py). A real place has no
    # checkpoints in it, so without this the game's rifles have nowhere at all
    # they could spawn.
    from . import guns
    from .world import CELL_SIZE
    gun_cache = guns.write(
        out_dir, map_name,
        guns.choose(rows, gunshops) if settings.guaranteed_rifle else None,
        origin(), CELL_SIZE)
    say("Front paths, yards and porch lights", 0.62)
    from .yards import paint_paths
    drives: list = []
    porch_lights: list = []
    paths, yard_fences = paint_paths(out_dir, map_name, rows, occupied, drives,
                                     porch_lights)
    # The lights stand outside the houses, past the edge of their own .tbx.
    from .structures import pack_loose
    light_placements = pack_loose(bdir, map_name, "lights", porch_lights,
                                  on_top=True)
    escalator_placements = pack_loose(bdir, map_name, "escalators",
                                      escalator_squares, on_top=True)

    say("Petrol pumps, graves and other props", 0.74)
    # Pumps on a forecourt at each petrol station, including those mapped as
    # a point with no building of their own.
    from .pumps import place_pumps
    loose_fuel = [(x, y) for group in points.values() for x, y, t in group
                  if t.get("amenity") == "fuel" and (x, y) not in points_taken]
    forecourts: list = []
    pump_placements, n_pumps = place_pumps(out_dir, map_name, bdir, occupied,
                                           stations, loose_fuel, forecourts, canopies)

    # Headstones in the churchyards, stores on the army bases: land uses that
    # are neither a building nor a colour of ground.
    from .props import place_props
    prop_placements, prop_counts = place_props(out_dir, map_name, bdir, occupied,
                                               areas, metres_per_tile,
                                               seed=seed + 5)

    # Five jobs that each read the finished ground and none of which changes
    # it or what another one reads: fences, the zombie spawn map, the paper
    # map, the parking/town zones and the bridges. Mostly numpy and shapely,
    # which let go of the interpreter lock, so threads overlap them.
    say("Fences, zombies, zones and the paper map", 0.82)
    from concurrent.futures import ThreadPoolExecutor
    from .structures import build_structures

    def make_spawn_map():
        # Redrawn from the people in the buildings just placed. It replaces the
        # ground-colour one the renderer wrote, at the same path and size, so
        # the WorldEd project picks it up unchanged.
        spawn_img, pop = build_spawn_map(
            peopled, proj.width, proj.height, info["meters_per_tile"],
            os.path.join(out_dir, f"{map_name}.bmp"), settings)
        spawn_img.save(os.path.join(out_dir, f"{map_name}_ZombieSpawnMap.bmp"),
                       format="BMP")
        save_footprints(os.path.join(out_dir, f"{map_name}_footprints.npz"), peopled)
        pop["official"] = [p for p in official_population(out_dir, map_name)
                           if p.get("inside")][:5]
        with open(os.path.join(out_dir, f"{map_name}_population.json"), "w",
                  encoding="utf-8") as f:
            json.dump(pop, f, indent=2, ensure_ascii=False)
        return pop

    with ThreadPoolExecutor(max_workers=5) as pool:
        job_fences = pool.submit(build_fences, out_dir, map_name, proj, occupied,
                                 areas, bdir, extra=yard_fences)
        job_spawn = pool.submit(make_spawn_map)
        job_paper = pool.submit(worldmap.write, out_dir, map_name, proj, info,
                                outlines)
        job_zones = pool.submit(
            _detect_zones, os.path.join(out_dir, f"{map_name}.bmp"), placements,
            settings=settings, areas=areas, drives=drives, keep_clear=forecourts,
            road_hierarchy=road_hierarchy)
        # Fences go into the project alongside the buildings, but not into the
        # town zones: a fence lot spans its whole cell and would mark it all town.
        job_structures = pool.submit(build_structures, out_dir, map_name, bdir)
        fence_placements, fence_tiles = job_fences.result()
        population = job_spawn.result()
        paper_map = job_paper.result()
        zones = job_zones.result()
        structure_placements, raised = job_structures.result()
    placements = (placements + fence_placements + structure_placements +
                  pump_placements + prop_placements + light_placements
                  + escalator_placements)

    say("Writing the WorldEd project", 0.95)
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
    print(f"  shops, food, offices: {with_uses} buildings from the map's points and tags")
    if region:
        print(f"  region style         : {region}"
              + (" (flat roofs, masonry blocks, taller housing)" if region == "cn"
                 else " (built the default way for now)"))
    print(f"  too small (<{min_size})     : {skipped['small']}")
    if split_large:
        print(f"  oversized (>{max_size})     : {split_large} kept, "
              f"cut into units that fit")
    else:
        print(f"  too large (>{max_size})   : {skipped['large']}")
    print(f"  outside the map     : {skipped['outside']}")
    print(f"  swallowed by others : {skipped['taken']}")
    print(f"  on the road         : {skipped['road']} (more than {round(100 * footprint.ROAD_SHARE_MAX)}% road)")
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
    print(f"  rows cut into units : {rows_split} rows -> {units_made} buildings")
    if thinning:
        print(f"  town laid out for PZ: {thinning['thinned']} houses left out, "
              f"{thinning['grown']} buildings grown, "
              f"{thinning['landmarks']} landmarks kept and placed first")
    print(f"  storeys from nearby : {from_near}")
    storeys = _c.Counter(r["levels"] for r in rows)
    print(f"  storeys             : {dict(sorted(storeys.items()))}")
    pct = 100.0 * from_osm / len(rows) if rows else 0.0
    print(f"  heights from OSM    : {from_osm} of {len(rows)} ({pct:.1f}%), "
          f"rest inferred from footprint")
    print(f"  rooms               : {total_rooms}")
    print(f"  furniture pieces    : {total_furn}")
    if gun_cache:
        print(f"guaranteed rifle      : {gun_cache['kind']} - "
              f"{gun_cache['name'] or gun_cache['building']}")
    print(f"world origin          : cell {origin()[0]},{origin()[1]}")
    print(f"wrote {pzw_path}")
    print(f"wrote {csv_path}")
    n_park = sum(1 for z in zones if z.kind == "ParkingStall")
    n_town = sum(1 for z in zones if z.kind == "TownZone")
    print(f"zones                 : {n_park} parking, {n_town} town")
    print(f"petrol stations       : {n_pumps} pumps at {len(stations)} stations"
          f", {len(canopies)} canopies and {len(loose_fuel)} points")
    print(f"front paths, yards    : {paths} houses, {len(yard_fences)} back yards")
    print(f"graves, army stores  : {prop_counts['graves']} graves, "
          f"{prop_counts['dumps']} stacks of stores")
    print(f"porch lights         : {len(porch_lights)} by front doors")
    print(f"fences                : {fence_tiles} fence tiles in "
          f"{len(fence_placements)} lots")
    print(f"bridges, monuments    : {raised['bridges']} bridges, "
          f"{raised['monuments']} monuments, {raised['tiles']} tiles in "
          f"{len(structure_placements)} lots")
    print(f"paper map             : {paper_map['map_features']} features in "
          f"{paper_map['map_cells']} cells, {paper_map['streets']} named streets, "
          f"{paper_map['labels']} labels")
    print(f"population            : {population['residents']:,} residents, "
          f"{population['daytime_occupants']:,} at work or school, "
          f"{population.get('on_the_street', 0):,} out on the street")
    print(f"zombie spawn map      : {population['share_with_zombies']:.1%} of chunks "
          f"populated, peak {population['peak_value']} (cap {population['horde_cap']}), "
          f"{population['chunks_at_cap']} chunks at the cap")
    # Not "place": that name is the footprint placer imported above, and a
    # loop variable of the same name makes it local to all of build().
    for town in population["official"]:
        print(f"  OSM says {town['name'] or town['place']}: "
              f"population {town['population']:,} ({town['place']})")
    print(f"wrote {len(rows)} .tbx files in {bdir}")
    if failed_buildings:
        print(f"left out {len(failed_buildings)} buildings that could not be laid out:")
        for error in failed_buildings[:20]:
            print(f"  {error}")
        try:
            import knoxlog
            for error in failed_buildings:
                knoxlog.log.warning("building left out: %s", error)
        except Exception:  # noqa: BLE001 - the printout is the record then
            pass
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
                         "(e.g. --set max_levels=12)")
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
