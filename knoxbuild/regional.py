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

import re

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


def detect_region(geo: dict, bbox: dict | None = None) -> str | None:
    """"cn", "jp" or "kr" when the map's own names say so, else None.

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
        return None
    # Nothing named: fall back to where the rectangle sits.
    try:
        lon = (float(bbox["west"]) + float(bbox["east"])) / 2
        lat = (float(bbox["south"]) + float(bbox["north"])) / 2
    except (KeyError, TypeError, ValueError):
        return None
    for name, (w, s, e, n) in _BOXES:
        if w <= lon <= e and s <= lat <= n:
            return name
    return None


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


def area_level_pool(kind: str | None, area_m2: float,
                    region: str | None = None) -> tuple | None:
    """A weighted pool of storeys for this kind and footprint, or None.

    `kind` is classify_building's word (None for an ordinary house) and
    `area_m2` the real footprint - the mapper's metres, not tiles, so the
    answer holds at whatever scale the map was drawn.
    """
    if region == "cn":
        for limit, pool in CN_AREA_OVERRIDES.get(kind, ()):
            if limit is None or area_m2 <= limit:
                return pool
    for limit, pool in AREA_LEVEL_TABLE.get(kind, ()):
        if limit is None or area_m2 <= limit:
            return pool
    return None
