"""Build the town the way the town is actually built.

KnoxMap's materials and storey counts come from the game's own Knox County -
weatherboard houses one and two storeys tall, mostly. That is right for the
map's native Kentucky and wrong for most of the world the survey can name. A
Chinese city is not clapboard and shutters: it is masonry and render, flat
roofs with air-conditioners on them, self-built houses of three and four
storeys and walk-up blocks behind compound walls.

This module answers two questions without touching anything else in the
pipeline: *where in the world is this map*, read from the script its own
buildings' names are written in (and from the bounding box when the survey
names nothing), and *what that place builds with* - a pool of house styles
composed from the catalog's own verified entries, plus the storey tables the
region's housing actually runs to.

The style composition is deliberately conservative. Rather than inventing
tile references, a regional style is the catalog's own entry with its peaked
roof laid flat and its shutters left off; every tile in it is a tile the
catalog already shipped. Detection never guesses a region from an ambiguous
place: a town whose names are in Han script is Chinese-built, one with kana
or hangul in them is Japanese or Korean, and one written in anything else
builds the way the game does. `arch_style` in the settings forces the issue
either way.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Where in the world this map is
# ---------------------------------------------------------------------------

# Script ranges, so a town is read by its own names rather than by which
# country claims the rectangle they stand in. Han ideographs alone cover
# written Chinese (including Hong Kong, Taiwan and Singapore); kana marks
# Japanese even though most of a Japanese name is Han; hangul marks Korean.
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff]")
_HANGUL = re.compile(r"[\uac00-\ud7af\u1100-\u11ff]")

# How many names to read before deciding, and how much of the sample must
# agree. A handful of Chinese restaurants on an American main street must not
# turn it flat-roofed; a town whose names are mostly Han script is a Han
# town, whatever the odd transliterated shopfront.
SAMPLE_MAX = 800
SAMPLE_MIN = 6
SHARE = 0.30

# Rough boxes, used only when the survey named nothing at all - a rural
# rectangle in China often carries no building names, and it should still be
# built the Chinese way. Good to a country's width, no finer: (west, south,
# east, north). Korea and Japan are tested first because they sit inside the
# Chinese longitudes.
_BOXES = (
    ("jp", (129.5, 30.5, 146.0, 45.9)),
    ("kr", (124.5, 33.0, 130.6, 38.7)),
    ("cn", (73.5, 17.5, 135.5, 53.8)),
)

# Countries built their own way that the names cannot tell apart from the
# default (Latin script), by the ISO code Natural Earth gives the map's centre
# (`region` in <map>_knoxdata.json, written when the map is generated).
COUNTRY_REGIONS = {"GB": "gb"}
# The same, for a map with no country on record (made before it was recorded,
# or with Natural Earth unreachable). Great Britain east of Dublin: Northern
# Ireland and the Outer Hebrides fall outside and build the default way.
_COUNTRY_BOXES = (
    ("gb", (-6.0, 49.8, 1.8, 60.9)),
)


@dataclass(frozen=True)
class Profile:
    """How a region builds. Today's values are the "us" defaults; a field is
    added only when a region's step needs it (docs/REGIONAL_PROFILES.md)."""
    code: str = "us"


PROFILES = {"us": Profile(), "cn": Profile(code="cn"), "gb": Profile(code="gb")}


def profile(region: str | None) -> Profile:
    """The profile for detect_region's answer; anything without one is "us"."""
    return PROFILES.get(region or "us", PROFILES["us"])


def map_country(out_dir: str, map_name: str) -> str | None:
    """The ISO country recorded for the map when it was generated, or None."""
    try:
        with open(os.path.join(out_dir, f"{map_name}_knoxdata.json"),
                  encoding="utf-8") as f:
            iso = json.load(f).get("region")
    except (OSError, ValueError, AttributeError):
        return None
    return str(iso).upper() if iso else None


def _centre(bbox: dict | None) -> tuple[float, float] | None:
    try:
        return ((float(bbox["west"]) + float(bbox["east"])) / 2,
                (float(bbox["south"]) + float(bbox["north"])) / 2)
    except (KeyError, TypeError, ValueError):
        return None


def _in_box(boxes, bbox: dict | None) -> str | None:
    centre = _centre(bbox)
    if centre is None:
        return None
    lon, lat = centre
    for name, (w, s, e, n) in boxes:
        if w <= lon <= e and s <= lat <= n:
            return name
    return None


def _by_country(country: str | None, bbox: dict | None) -> str | None:
    if country:
        return COUNTRY_REGIONS.get(country.upper())
    return _in_box(_COUNTRY_BOXES, bbox)


def detect_region(geo: dict, bbox: dict | None = None,
                  country: str | None = None) -> str | None:
    """"cn", "jp" or "kr" when the map's own names say so, "gb" when its
    `country` (ISO, see map_country) or else its box is Great Britain, else None.

    The names come first because they are the place speaking for itself: a
    Chinatown inside an English city stays English-built at SHARE, and a
    Japanese quarter of a Chinese one stays Chinese. The bounding box is the
    fallback for a map that names nothing, which in practice means rural
    China - the one place this matters most.
    """
    scripts = {"han": 0, "kana": 0, "hangul": 0, "other": 0}
    sampled = 0
    for feat in geo.get("features", ()):
        name = (feat.get("properties") or {}).get("name") or ""
        if not name:
            continue
        sampled += 1
        if sampled > SAMPLE_MAX:
            break
        if _KANA.search(name):
            scripts["kana"] += 1
        elif _HANGUL.search(name):
            scripts["hangul"] += 1
        elif _HAN.search(name):
            scripts["han"] += 1
        else:
            scripts["other"] += 1
    if sampled >= SAMPLE_MIN:
        if scripts["kana"] / sampled > SHARE:
            return "jp"
        if scripts["hangul"] / sampled > SHARE:
            return "kr"
        if scripts["han"] / sampled > SHARE:
            return "cn"
        return _by_country(country, bbox)
    # Nothing named: fall back to where the rectangle sits.
    return _in_box(_BOXES, bbox) or _by_country(country, bbox)


# ---------------------------------------------------------------------------
# What that place builds with
# ---------------------------------------------------------------------------

# The masonry-and-render end of the catalog's house styles, rebuilt flat.
# Deliberately not clapboard, logs, timber, trailer or the coloured sidings:
# those are American wood, and the whole point of a regional pool is that a
# Chinese street does not wear them.
CN_BASES = ("render", "painted", "stucco", "panel", "brick")

_CN_STYLES: list | None = None


def _flat_roofed(base: dict) -> dict:
    """One catalog house style, rebuilt the masonry-city way.

    The pitched roof comes off (a flat cap keeps the weather out, and the
    rooftop machinery - already in the game - takes its place on top), and
    the wooden shutters go with it. Everything else - walls, windows, doors,
    trim, grime - is the catalog's own verified entry, tiles untouched.
    """
    style = dict(base)
    style["name"] = f"cn_{base['name']}"
    roof = dict(base.get("roof") or {})
    roof["peaked"] = False
    style["roof"] = roof
    style.pop("shutters", None)
    return style


def cn_house_styles() -> list[dict]:
    """The house styles a Chinese town is built from, composed once."""
    global _CN_STYLES
    if _CN_STYLES is None:
        from . import catalog as C
        by_name = {s["name"]: s for s in C.HOUSE_STYLES}
        _CN_STYLES = [_flat_roofed(by_name[name]) for name in CN_BASES
                      if name in by_name]
    return _CN_STYLES


# A British street: brick most of all, then render, pebble-dash-like stucco and
# painted brick, under the catalog's own pitched roofs. No clapboard, sidings,
# timber or logs (American wood), no panel, and no shutters, which British
# houses don't have. Brick is listed three times so it is half the pool.
GB_BASES = ("brick", "brick", "brick", "render", "stucco", "painted")

_GB_STYLES: list | None = None


# White curtains drawn across, as British net curtains are. The catalog's
# brick houses hang brown ones, drawn shut, which from the street read as
# wooden shutters (Anfield: 12,930 windows); its stucco ones pull blinds down.
GB_CURTAINS = {"category": "curtains",
               "tiles": {"West": "fixtures_windows_curtains_01_008",
                         "East": "fixtures_windows_curtains_01_009",
                         "North": "fixtures_windows_curtains_01_010",
                         "South": "fixtures_windows_curtains_01_011"}}


def _british(base: dict) -> dict:
    """One catalog house style without its shutters and with white curtains;
    every other tile untouched."""
    style = dict(base)
    style["name"] = f"gb_{base['name']}"
    style.pop("shutters", None)
    style["curtains"] = GB_CURTAINS
    if style.get("windows_by_levels"):
        style["windows_by_levels"] = [(levels, entry, GB_CURTAINS if curtains else curtains)
                                      for levels, entry, curtains in style["windows_by_levels"]]
    return style


def gb_house_styles() -> list[dict]:
    """The house styles a British town is built from, composed once."""
    global _GB_STYLES
    if _GB_STYLES is None:
        from . import catalog as C
        by_name = {s["name"]: s for s in C.HOUSE_STYLES}
        _GB_STYLES = [_british(by_name[name]) for name in GB_BASES
                      if name in by_name]
    return _GB_STYLES


# ---------------------------------------------------------------------------
# Storeys
# ---------------------------------------------------------------------------

# Storey counts for buildings OSM says nothing about, built the Chinese way.
# A tagged building is never touched: the mapper counted the floors and that
# beats any table here. Clamped by the map's own max_levels, as everywhere.
#
# The housing these describe: the self-built house (zijianfang) is three or
# four storeys on a small footprint, often with the family's shop on the
# ground floor; the danwei and xiaoqu walk-up blocks run five to eight; a
# Chinese school or hospital is a big flat block, not a couple of storeys.
CN_DEFAULT_LEVELS = {
    "apartment": (5, 8),
    "civic": (2, 4),
    "school": (3, 5),
    "medical": (2, 5),
    "shop": (1, 2),
    "restaurant": (1, 2),
    "industrial": (1, 2),
    "military": (1, 2),
    "police": (1, 3),
    "library": (1, 3),
    "church": (1, 2),
}

# Area-weighted storey pools for untagged buildings, any region: the same
# idea Arnis (github.com/louis-e/arnis) uses for Minecraft - a kind says
# little on its own, a kind and a footprint say a lot. Entries are
# (up to this many square metres, pool of storeys, repeats are weights);
# the first band whose limit covers the footprint decides. Bands and pools
# were tuned against the ranges Arnis ships, re-based to one storey per
# level and the sizes PZ rooms want, and they degrade to the old flat ranges
# for any kind not listed.
AREA_LEVEL_TABLE = {
    None: ((120, (1, 1, 1, 2)), (300, (1, 2, 2, 3)),
           (800, (2, 2, 3, 3)), (None, (2, 3, 3, 4))),
    "apartment": ((300, (2, 3, 3, 4)), (900, (3, 4, 4, 5)),
                  (2500, (4, 5, 6, 8)), (None, (5, 7, 9, 12))),
    "shop": ((100, (1, 1, 1, 2)), (350, (1, 2, 2)), (None, (2, 2, 3))),
    "civic": ((300, (1, 2, 2)), (1200, (2, 3, 3, 4)), (None, (3, 4, 5))),
    "medical": ((600, (2, 2, 3)), (2000, (3, 4, 5)), (None, (4, 6, 8))),
    "school": ((800, (2, 2, 3)), (2500, (2, 3, 3, 4)), (None, (3, 4, 5))),
    "industrial": ((800, (1, 1)), (None, (1, 2))),
    "restaurant": ((150, (1, 1)), (400, (1, 2)), (None, (2, 2, 3))),
    "military": ((400, (1, 1)), (None, (1, 2))),
    "police": ((300, (1, 2)), (None, (2, 3))),
    "library": ((400, (1, 1, 2)), (None, (2, 2, 3))),
    "church": ((None, (1, 1)),),
    "barn": ((None, (1, 1)),),
    "shed": ((None, (1, 1)),),
    "fire": ((None, (1, 2)),),
    "fire_police": ((None, (1, 2)),),
    "stadium": ((None, (1, 2)),),
    "mall": ((None, (1, 2)),),
    "castle": ((None, (2, 3)),),
}
# Chinese housing overrides the plain-house pool: a small untagged footprint
# is a self-built house, not a bungalow - though the odd single-storey one
# survives in the older villages, so a few stay in at the bottom band.
CN_AREA_OVERRIDES = {
    None: ((150, (1, 2, 3, 3, 4)), (400, (3, 3, 4, 4)), (None, (3, 4, 4, 5))),
    "apartment": ((600, (4, 5, 6, 6)), (2000, (5, 6, 7, 8)), (None, (6, 8, 10, 12))),
    "church": ((None, (1, 2)),),
}
# British housing: a terrace or semi stands on 40-60 m2 and is two storeys,
# where the default reads a footprint that small as a bungalow. Up to 60 m2
# it is a terraced or semi-detached house (the odd three-storey town house);
# bungalows stand on the larger footprints, about one house in six there.
GB_AREA_OVERRIDES = {
    None: ((60, (2, 2, 2, 2, 2, 2, 2, 3)), (120, (1, 2, 2, 2, 2, 2)),
           (300, (2, 2, 2, 3)), (None, (2, 2, 3))),
}
_AREA_OVERRIDES = {"cn": CN_AREA_OVERRIDES, "gb": GB_AREA_OVERRIDES}


# ---------------------------------------------------------------------------
# Terraces and semis
# ---------------------------------------------------------------------------

# A British terraced house is 5-6 m wide; the default cuts rows at 9 m.
GB_TERRACE_FRONTAGE_M = 5.5
# British mappers tag houses building=residential or =terrace, which the kind
# table reads as flats: in Cambourne the 1,246 residential outlines had a
# median of 57 m2 (houses: 54 m2) and only 7 were over 250 m2. Up to this, and
# with no tagged third storey, they are houses.
GB_HOUSE_TAGS = {"residential", "terrace", "terraced"}
GB_HOUSE_MAX_M2 = 250.0


def british_house(special: str | None, btag: str, real_m2: float,
                  levels: int | None) -> bool:
    """Whether a building the kind table made flats is a British house."""
    return (special == "apartment" and btag in GB_HOUSE_TAGS
            and real_m2 <= GB_HOUSE_MAX_M2 and (levels is None or levels < 3))


# ---------------------------------------------------------------------------
# Garages and parking
# ---------------------------------------------------------------------------

# A block of lock-up garages (building=garages) is cut into one garage per
# car. A real lock-up is about 3 m wide, but a footprint is never cut narrower
# than footprint.MIN_ROOM_SIDE (5) and the layout needs as much.
GB_LOCKUP_FRONTAGE_M = 5.0
# Terraced streets have no drives, so their cars stand at the kerb, along
# both sides of nearly every residential street. By road_hierarchy code
# (3 residential, 4 tertiary); the rest keep the default rates.
GB_KERBSIDE_RATES = {3: 0.85, 4: 0.5}
# An integral garage on a British house is a newer estate's detached house,
# not the street: the default puts one on 40% of houses that have room. A
# terraced or semi-detached house - any house with a party wall - has none.
GB_GARAGE_SHARE = 0.15


def area_level_pool(kind: str | None, area_m2: float,
                    region: str | None = None) -> tuple | None:
    """A weighted pool of storeys for this kind and footprint, or None.

    `kind` is classify_building's word (None for an ordinary house) and
    `area_m2` the real footprint - the mapper's metres, not tiles, so the
    answer holds at whatever scale the map was drawn.
    """
    for limit, pool in _AREA_OVERRIDES.get(region, {}).get(kind, ()):
        if limit is None or area_m2 <= limit:
            return pool
    for limit, pool in AREA_LEVEL_TABLE.get(kind, ()):
        if limit is None or area_m2 <= limit:
            return pool
    return None
