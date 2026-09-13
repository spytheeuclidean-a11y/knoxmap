"""Query OpenStreetMap via the Overpass API.

We only pull tags that map cleanly onto PZ terrain categories — everything
else is ignored. The query asks for a single bbox and returns ways/relations
with their full geometry so we can rasterize without a second roundtrip.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import re
import threading
import time
from concurrent import futures
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import requests

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

# OSM's usage policy requires a real identifying User-Agent; the mirrors return
# 403 for the default "python-requests/x.y" string.
HEADERS = {"User-Agent": "KnoxMap/1.0 (+https://github.com/spytheeuclidean-a11y/knoxify) local map generator"}

# Tag filters — each line becomes one part of the Overpass union query.
# Order doesn't matter here; the rasterizer picks priority at paint time.
OVERPASS_FILTERS: Sequence[str] = (
    # water
    'way["natural"="water"]',
    'way["waterway"]',
    'relation["natural"="water"]',
    'way["landuse"="reservoir"]',
    'way["landuse"="basin"]',
    # forest / trees
    'way["landuse"="forest"]',
    'way["natural"="wood"]',
    'relation["landuse"="forest"]',
    'relation["natural"="wood"]',
    'way["natural"="scrub"]',
    'way["natural"="heath"]',
    'node["natural"="tree"]',
    # grass / parks / farms
    'way["landuse"="grass"]',
    'way["landuse"="meadow"]',
    'way["landuse"="farmland"]',
    'way["landuse"="farmyard"]',
    'way["leisure"="park"]',
    'way["leisure"="garden"]',
    'way["leisure"="pitch"]',
    # sand / beach
    'way["natural"="beach"]',
    'way["natural"="sand"]',
    # dirt
    'way["landuse"="brownfield"]',
    'way["landuse"="construction"]',
    'way["landuse"="quarry"]',
    # roads
    'way["highway"]',
    'way["area:highway"]',
    'way["place"="square"]',
    # buildings
    'way["building"]',
    'relation["building"]',
    # What the ground between buildings is used for. Without these a factory
    # yard, a schoolyard and a back garden all came out as the same wild grass,
    # which is most of why a generated town looked like nowhere in particular.
    'way["landuse"~"^(residential|commercial|retail|industrial|railway|garages|'
    'military|cemetery|orchard|vineyard|allotments)$"]',
    'relation["landuse"~"^(residential|commercial|retail|industrial|railway|'
    'military|cemetery|orchard|vineyard)$"]',
    'way["amenity"~"^(parking|school|university|college|kindergarten|hospital|'
    'clinic|bus_station|grave_yard|marketplace|place_of_worship)$"]',
    'relation["amenity"~"^(parking|school|university|college|hospital|'
    'grave_yard|marketplace)$"]',
    'way["leisure"~"^(playground|swimming_pool|sports_centre|stadium|track)$"]',
    'way["natural"~"^(grassland|wetland)$"]',
    # Property lines. Fences and walls become real fences in game; hedges
    # become rows of bushes.
    'way["barrier"~"^(fence|wall|hedge|retaining_wall|city_wall)$"]',
    # Official head counts, where mappers recorded one, to check the
    # population estimate against.
    'node["place"~"^(city|town|village|suburb|quarter|neighbourhood|hamlet)$"]'
    '["population"]',
)

# Bumped whenever the filters above change, so a cached download made with
# the old list is fetched again instead of silently lacking the new features.
FILTERS_VERSION = 3


@dataclass
class OSMFeature:
    osm_id: int
    kind: str             # "way" or "relation" or "node"
    tags: dict
    geometry: list        # for way: list of (lat, lon); relation: list of ring lists
    role_geoms: list = field(default_factory=list)  # relation members with roles


def _build_query(south: float, west: float, north: float, east: float,
                 timeout: int = 60) -> str:
    # Catch an out-of-range bbox here rather than letting Overpass answer with
    # a static error, which arrives as an XHTML page and costs a round trip to
    # all three servers to learn the same thing.
    for name, value, limit in (("south", south, 90.0), ("north", north, 90.0),
                               ("west", west, 180.0), ("east", east, 180.0)):
        if not -limit <= value <= limit:
            raise OverpassError(
                f"{name}={value:g} is outside ±{limit:g}. The map widget "
                f"reports coordinates unwrapped after panning across a world "
                f"copy; they need folding back before use.")
    bbox = f"{south},{west},{north},{east}"
    parts = [f"{f}({bbox});" for f in OVERPASS_FILTERS]
    body = "\n  ".join(parts)
    return (
        f"[out:json][timeout:{timeout}];\n"
        f"(\n  {body}\n);\n"
        f"out geom;\n"
    )


class OverpassError(RuntimeError):
    """A failed query, with whether a smaller bbox would plausibly succeed."""

    def __init__(self, message: str, too_big: bool = False):
        super().__init__(message)
        self.too_big = too_big


# Overpass says "query timed out" and "out of memory" with HTTP 400, the same
# status it uses for a syntax error. Reading the status alone turns "your area
# is too big for this server" into "Bad Request", which sends you looking for a
# bug in a query that is perfectly valid. The reason is in the body.
_TOO_BIG = ("timed out", "out of memory", "runtime error")
# ...except when the query really is malformed. Splitting the bbox cannot fix
# a syntax error, it just asks four times and fails four times.
_MY_FAULT = ("parse error", "unknown type", "static error")

_TAGS = re.compile(r"<[^>]+>")
_PARAS = re.compile(r"<p>(.*?)</p>", re.S | re.I)


def _error_text(body: str) -> str:
    """The human-readable complaint out of an Overpass error response.

    Errors come back as a full XHTML page whose first few hundred characters
    are a DOCTYPE and a namespace declaration. Truncating that to make it fit
    in a message shows the reader the doctype and nothing else, which is
    exactly what a failed town looked like: three endpoints, three identical
    walls of XHTML boilerplate, no reason among them.
    """
    if "<html" not in body[:400].lower():
        return " ".join(body.split())[:400]
    paragraphs = []
    for raw in _PARAS.findall(body):
        text = " ".join(_TAGS.sub(" ", raw).split())
        # The copyright notice is on every page, error or not.
        if not text or "openstreetmap.org" in text.lower():
            continue
        paragraphs.append(text)
    said = [p for p in paragraphs if "error" in p.lower()] or paragraphs
    return " | ".join(said)[:400] or " ".join(body.split())[:400]


def _ask(endpoint: str, query: str, timeout: int) -> list[OSMFeature]:
    r = requests.post(endpoint, data={"data": query}, headers=HEADERS,
                      timeout=timeout + 10)
    if r.status_code == 200:
        return _parse(r.json())
    # Classify on the whole body, report a trimmed version of it. Doing both
    # from the trimmed text is what stopped over-large areas re-splitting: the
    # markers sit well past the doctype, so nothing ever looked too big.
    whole = r.text.lower()
    message = _error_text(r.text)
    too_big = (any(s in whole for s in _TOO_BIG)
               and not any(s in whole for s in _MY_FAULT))
    raise OverpassError(f"HTTP {r.status_code}"
                        + (f" — {message}" if message else ""),
                        too_big=too_big)


def fetch_features(south: float, west: float, north: float, east: float,
                   timeout: int = 60, first: int = 0) -> list[OSMFeature]:
    """Run the Overpass query against the first endpoint that answers.

    `first` rotates which endpoint is tried first, so concurrent tiles spread
    themselves over the public instances instead of queueing on one.

    Every endpoint's complaint is kept, not just the last one. The instances
    fail in different ways at the same moment - one 504s, one stops answering,
    one says the query was too heavy - and reporting only the last of those
    describes the least interesting failure as though it were the whole story.
    """
    query = _build_query(south, west, north, east, timeout=timeout)
    errors: list[str] = []
    too_big = False
    order = OVERPASS_ENDPOINTS[first % len(OVERPASS_ENDPOINTS):]         + OVERPASS_ENDPOINTS[:first % len(OVERPASS_ENDPOINTS)]
    for endpoint in order:
        host = endpoint.split("/")[2]
        try:
            return _ask(endpoint, query, timeout)
        except OverpassError as exc:
            errors.append(f"{host}: {exc}")
            too_big = too_big or exc.too_big
        except requests.Timeout:
            errors.append(f"{host}: no answer within {timeout + 10}s")
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{host}: {exc}")
        time.sleep(1)
    raise OverpassError("every Overpass endpoint failed — "
                        + "; ".join(errors), too_big=too_big)


def _area_km2(south: float, west: float, north: float, east: float) -> float:
    lat_mid = math.radians((south + north) / 2)
    return abs((north - south) * 111.32 *
               (east - west) * 111.32 * math.cos(lat_mid))


def fetch_features_tiled(south: float, west: float, north: float, east: float,
                         max_tile_km2: float = 30.0, timeout: int = 90,
                         progress=None) -> list[OSMFeature]:
    """Fetch a large bbox as a grid of smaller Overpass queries.

    One query over a big area either times out or gets refused - that, not the
    renderer, is what used to cap map size. Splitting into tiles of at most
    `max_tile_km2` keeps every individual query the size Overpass is happy
    with.

    The tiles are deliberately large. They used to be 12 km2, sized so that no
    tile could ever be refused, which meant a town was fetched as dozens of
    small requests when three or four big ones would have done. Now that a
    refused tile quarters itself and retries, guessing high costs one wasted
    request on the rare tile that overshoots and saves many on every tile that
    does not.

    A way crossing a tile boundary is returned in full by every tile it touches
    (`out geom` gives complete geometry regardless of clipping), so features are
    de-duplicated on (kind, osm_id) and keep their whole shape.
    """
    area = _area_km2(south, west, north, east)
    steps = max(1, math.ceil(math.sqrt(area / max_tile_km2)))
    if steps == 1:
        return _fetch_splitting(south, west, north, east, timeout)

    d_lat = (north - south) / steps
    d_lon = (east - west) / steps
    merged: dict[tuple[str, int], OSMFeature] = {}
    total = steps * steps

    tiles = []
    for i in range(steps):
        for j in range(steps):
            s0 = south + i * d_lat
            n0 = north if i == steps - 1 else s0 + d_lat
            w0 = west + j * d_lon
            e0 = east if j == steps - 1 else w0 + d_lon
            tiles.append((s0, w0, n0, e0))

    # One tile at a time meant the whole map waited on whichever instance was
    # busiest, one request after another, with a courtesy second between each.
    # There are three independent servers; a tile is handed to each in turn and
    # they work at the same time, so the download takes about as long as the
    # slowest tile rather than the sum of all of them.
    done = 0
    lock = threading.Lock()

    def run(args) -> list[OSMFeature]:
        nonlocal done
        index, (s0, w0, n0, e0) = args
        try:
            return _fetch_splitting(s0, w0, n0, e0, timeout, first=index)
        finally:
            with lock:
                done += 1
                if progress:
                    progress(done, total)

    workers = min(len(OVERPASS_ENDPOINTS), total)
    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for feats in pool.map(run, enumerate(tiles)):
            for feat in feats:
                merged[(feat.kind, feat.osm_id)] = feat

    return list(merged.values())


# Below this, a tile is small enough that a refusal is the server's problem
# rather than the area's, and splitting further only multiplies the requests.
MIN_SPLIT_KM2 = 0.5


def _fetch_splitting(south: float, west: float, north: float, east: float,
                     timeout: int, depth: int = 0,
                     first: int = 0) -> list[OSMFeature]:
    """Fetch one tile, quartering it if the servers say it is too heavy.

    How much a bbox costs depends on what is inside it, not its size, so a
    fixed tile grid is always wrong somewhere: the tile holding a dense town
    centre can blow the server's limit while its neighbours over farmland
    return instantly. Giving up there loses the whole map. Splitting only the
    tile that failed costs three extra requests and keeps everything else.
    """
    try:
        return fetch_features(south, west, north, east, timeout=timeout,
                              first=first)
    except OverpassError as exc:
        if not exc.too_big or depth >= 3                 or _area_km2(south, west, north, east) <= MIN_SPLIT_KM2:
            raise
    mid_lat = (south + north) / 2
    mid_lon = (west + east) / 2
    out: list[OSMFeature] = []
    for s0, n0 in ((south, mid_lat), (mid_lat, north)):
        for w0, e0 in ((west, mid_lon), (mid_lon, east)):
            out += _fetch_splitting(s0, w0, n0, e0, timeout, depth + 1, first)
            time.sleep(1)
    return out


def cache_path(output_dir: str, map_name: str) -> str:
    return os.path.join(output_dir, f"{map_name}_osm.json.gz")


def save_cache(path: str, bbox: tuple[float, float, float, float],
               feats: list[OSMFeature]) -> None:
    """Keep the Overpass result next to the map it produced.

    Re-rendering is otherwise gated on a fresh download of the whole town,
    which for a real one is a few hundred tiled queries with a second of
    courtesy between each. Every change to how roads or ground are painted
    then costs that download again, for data that has not moved.
    """
    payload = {
        "filters": FILTERS_VERSION,
        "bbox": list(bbox),
        "features": [
            {"osm_id": f.osm_id, "kind": f.kind, "tags": f.tags,
             "geometry": f.geometry, "role_geoms": f.role_geoms}
            for f in feats
        ],
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)


def load_cache(path: str,
               bbox: tuple[float, float, float, float]) -> list[OSMFeature] | None:
    """Cached features for exactly this bbox, or None."""
    if not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    if payload.get("filters") != FILTERS_VERSION:
        return None
    cached = payload.get("bbox") or []
    if len(cached) != 4 or any(abs(a - b) > 1e-9 for a, b in zip(cached, bbox)):
        return None
    out = []
    for d in payload.get("features", []):
        out.append(OSMFeature(
            d["osm_id"], d["kind"], d.get("tags") or {},
            [tuple(c) for c in d.get("geometry") or []],
            [(role, [tuple(c) for c in ring])
             for role, ring in d.get("role_geoms") or []],
        ))
    return out


def _parse(payload: dict) -> list[OSMFeature]:
    elements = payload.get("elements", [])
    out: list[OSMFeature] = []
    for el in elements:
        kind = el.get("type")
        tags = el.get("tags", {}) or {}
        if kind == "way":
            coords = [(p["lat"], p["lon"]) for p in el.get("geometry", [])]
            if coords:
                out.append(OSMFeature(el["id"], "way", tags, coords))
        elif kind == "relation":
            rings: list[list[tuple[float, float]]] = []
            role_geoms: list[tuple[str, list[tuple[float, float]]]] = []
            for m in el.get("members", []):
                geom = m.get("geometry")
                if not geom:
                    continue
                ring = [(p["lat"], p["lon"]) for p in geom]
                role_geoms.append((m.get("role", ""), ring))
                rings.append(ring)
            if rings:
                feat = OSMFeature(el["id"], "relation", tags, rings)
                feat.role_geoms = role_geoms
                out.append(feat)
        elif kind == "node":
            lat, lon = el.get("lat"), el.get("lon")
            if lat is not None and lon is not None:
                out.append(OSMFeature(el["id"], "node", tags, [(lat, lon)]))
    return out


# Barrier kinds that become fences in game, as opposed to hedges.
FENCE_BARRIERS = {"fence", "wall", "retaining_wall", "city_wall"}

SCHOOL_AMENITIES = {"school", "university", "college", "kindergarten"}


def classify(tags: dict) -> str | None:
    """Map OSM tags to a PZ feature category string. None = ignore."""
    if "building" in tags:
        return "building"

    amenity = tags.get("amenity")
    landuse = tags.get("landuse")
    leisure = tags.get("leisure")

    # Paved areas before the linear road classes: a pedestrian square and a
    # car park are tagged highway/amenity too, but they are polygons and want
    # a surface, not a stripe down their middle.
    if amenity == "parking" or landuse == "garages":
        return "parking"
    if amenity == "bus_station":
        return "parking"
    if tags.get("place") == "square" or "area:highway" in tags or (
            tags.get("highway") == "pedestrian" and tags.get("area") == "yes"):
        return "plaza"

    h = tags.get("highway")
    if h:
        if h in {"motorway", "trunk", "primary", "motorway_link", "trunk_link",
                 "primary_link"}:
            return "road_major"
        if h in {"secondary", "tertiary", "secondary_link", "tertiary_link"}:
            return "road_medium"
        if h in {"residential", "unclassified", "living_street"}:
            return "road_minor"
        # Alleys, driveways and back lanes. Lumping these in with residential
        # streets paved every yard and car park aisle at full street width.
        if h in {"service", "pedestrian"}:
            return "road_service"
        if h in {"track", "path", "footway", "cycleway", "bridleway", "steps"}:
            return "dirt_path"
        return "road_minor"

    if leisure == "swimming_pool" and tags.get("indoor") not in ("yes", "covered"):
        return "pool"
    if tags.get("natural") == "water" or tags.get("waterway") in {
            "river", "riverbank", "canal", "stream"}:
        return "water"
    if landuse in {"reservoir", "basin"}:
        return "water"
    if landuse in {"forest"} or tags.get("natural") == "wood":
        return "forest"
    if tags.get("natural") in {"scrub", "heath"}:
        return "scrub"
    if tags.get("natural") == "wetland":
        return "wetland"
    if tags.get("natural") == "tree":
        return "tree_single"

    if leisure == "playground":
        return "playground"
    if leisure == "track":
        return "track"
    if leisure in {"sports_centre", "stadium"}:
        return "sports"
    if leisure == "park":
        return "park"
    if leisure in {"garden", "pitch"}:
        return "grass"
    if landuse in {"grass", "meadow", "recreation_ground"} \
            or tags.get("natural") == "grassland":
        return "grass"
    if landuse in {"farmland", "farmyard", "allotments"}:
        return "farmland"
    if landuse in {"orchard", "vineyard"}:
        return "orchard"
    if landuse == "cemetery" or amenity == "grave_yard":
        return "cemetery"
    if tags.get("natural") in {"beach", "sand"}:
        return "sand"
    if landuse in {"brownfield", "construction", "quarry"}:
        return "dirt"

    if amenity in SCHOOL_AMENITIES:
        return "schoolyard"
    if amenity in {"hospital", "clinic"}:
        return "hospital_grounds"
    if amenity == "marketplace" or landuse in {"commercial", "retail"}:
        return "commercial"
    if landuse in {"industrial", "railway"}:
        return "industrial"
    if landuse == "military":
        return "military"
    if landuse == "residential":
        return "residential"
    if amenity == "place_of_worship":
        return "worship_grounds"
    # A barrier only counts as one when the outline is nothing else. Here a
    # school's grounds, a barracks or a government compound is commonly one
    # closed way tagged amenity=school and barrier=fence together; checking
    # the barrier first lost every one of those areas to "just a fence". The
    # renderer takes the fence off any outline carrying one, whatever it is.
    barrier = tags.get("barrier")
    if barrier in FENCE_BARRIERS:
        return "fence"
    if barrier == "hedge":
        return "hedge"
    return None
