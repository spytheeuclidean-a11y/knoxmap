"""Finding places: search by name, and list landmarks inside a bbox.

Two different services, for two different jobs:

* Nominatim answers "where is Lexington High School" - free-text geocoding,
  used to jump the map somewhere and pre-set the selection rectangle.
* Overpass answers "what is inside this rectangle" - the named schools, shops
  and civic buildings the area actually contains, which is what decides whether
  an area is worth turning into a map.

Both are public OSM services with usage policies. They require a real
User-Agent (the default python-requests string gets a 403), and Nominatim asks
for at most one request per second, which `_throttle` enforces process-wide.
"""
from __future__ import annotations

import threading
import time

import requests

from generator import osm

HEADERS = {
    "User-Agent": "KnoxMap/1.0 (+https://github.com/spytheeuclidean-a11y/knoxmap) local map generator",
    "Accept-Language": "en",
}

# Nominatim's public server is shared and has a usage policy every client must
# follow: https://operations.osmfoundation.org/policies/nominatim/
# One request a second (see _throttle), a real User-Agent (HEADERS), results
# cached (web/geo.py), no autocomplete (the page searches only on Enter), no bulk use.
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# The same instances, in the same order, as the map download (generator/osm.py,
# configurable in knoxmap_config.json).
OVERPASS_ENDPOINTS = list(osm.ANSWERING_ENDPOINTS)

_lock = threading.Lock()
_last_call = 0.0
MIN_INTERVAL = 1.0


def _throttle() -> None:
    """Nominatim's usage policy allows one request per second."""
    global _last_call
    with _lock:
        wait = MIN_INTERVAL - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()


def search(query: str, viewbox: tuple[float, float, float, float] | None = None,
           bounded: bool = False, limit: int = 8) -> list[dict]:
    """Geocode `query`. viewbox is (south, west, north, east) to bias results."""
    query = (query or "").strip()
    if not query:
        return []

    params = {
        "q": query,
        "format": "jsonv2",
        "limit": str(max(1, min(limit, 20))),
        "addressdetails": "1",
        # Real outlines for towns, districts and parks, simplified to about ten
        # metres so a city boundary does not arrive as megabytes of points.
        "polygon_geojson": "1",
        "polygon_threshold": "0.0001",
    }
    if viewbox:
        s, w, n, e = viewbox
        # Nominatim wants <left>,<top>,<right>,<bottom>.
        params["viewbox"] = f"{w},{n},{e},{s}"
        if bounded:
            params["bounded"] = "1"

    _throttle()
    r = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()

    out = []
    for item in r.json():
        bb = item.get("boundingbox") or []
        try:
            south, north, west, east = (float(bb[0]), float(bb[1]),
                                        float(bb[2]), float(bb[3]))
        except (ValueError, IndexError):
            continue
        out.append({
            "name": item.get("name") or item.get("display_name", "").split(",")[0],
            "display_name": item.get("display_name", ""),
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "bbox": [south, west, north, east],
            "category": item.get("category") or item.get("class") or "",
            "type": item.get("type") or "",
            "outline": _outline(item.get("geojson")),
        })
    return out


def _outline(geojson: dict | None) -> dict | None:
    """The place's own boundary, when it has one worth drawing a map in."""
    if not geojson or geojson.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    rings = geojson["coordinates"] if geojson["type"] == "Polygon" else \
        [r for poly in geojson["coordinates"] for r in poly]
    if sum(len(r) for r in rings) > 20000:
        return None
    return geojson


# Tags worth listing as landmarks. Anything named under these keys is something
# a mapper would recognise on the ground.
LANDMARK_KEYS = ("amenity", "shop", "leisure", "tourism", "historic",
                 "office", "healthcare", "building")

# Buildings are tagged building=yes in bulk, so only list named ones whose
# value says something.
BORING_BUILDING_VALUES = {"yes", "residential", "house", "detached", "garage",
                          "shed", "hut", "roof", "apartments"}


def _build_query(south: float, west: float, north: float, east: float,
                 timeout: int = 30) -> str:
    bbox = f"{south},{west},{north},{east}"
    parts = []
    for key in LANDMARK_KEYS:
        for kind in ("node", "way", "relation"):
            parts.append(f'{kind}["{key}"]["name"]({bbox});')
    body = "\n  ".join(parts)
    return f"[out:json][timeout:{timeout}];\n(\n  {body}\n);\nout center tags;\n"


# How many landmarks a list holds, and how much of it any one kind of place
# may take. A town with forty churches in it used to spend a quarter of the
# list on them - they are ranked highly and there are a lot of them - and the
# one theatre, the one market and the one graveyard were pushed out by the
# cut. Each kind gets at most this share before anything is allowed seconds.
LANDMARK_LIMIT = 600
VALUE_SHARE = 0.08
VALUE_MIN = 4


def landmarks(south: float, west: float, north: float, east: float,
              limit: int = LANDMARK_LIMIT) -> list[dict]:
    """Named landmarks inside the bbox, most specific category first."""
    query = _build_query(south, west, north, east)
    last_err: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        # The same manners as the map download: a server that is resting or
        # has refused us is not asked, and one request at a time to a host.
        if not osm.endpoint_ready(endpoint):
            last_err = RuntimeError(f"{endpoint} is resting")
            continue
        try:
            with osm._one_at_a_time(endpoint):
                r = requests.post(endpoint, data={"data": query},
                                  headers=HEADERS,
                                  timeout=(osm.CONNECT_TIMEOUT_S, 60))
            payload = osm.response_payload(r)
            osm._note_up(endpoint)
            return _parse(payload, limit)
        except osm.OverpassError as exc:
            if exc.refused:
                osm._refuse(endpoint)
            elif exc.busy:
                osm._note_down(endpoint, exc.retry_after)
            last_err = RuntimeError(f"{endpoint}: {exc}")
        except (requests.RequestException, ValueError) as exc:
            osm._note_down(endpoint)
            last_err = RuntimeError(f"{endpoint}: {exc}")
    raise RuntimeError(f"All Overpass endpoints failed: {last_err}")


def _parse(payload: dict, limit: int) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for el in payload.get("elements", []):
        tags = el.get("tags") or {}
        name = tags.get("name")
        if not name:
            continue
        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            centre = el.get("center") or {}
            lat, lon = centre.get("lat"), centre.get("lon")
        if lat is None or lon is None:
            continue

        kind = value = None
        for key in LANDMARK_KEYS:
            if key in tags:
                if key == "building" and tags[key] in BORING_BUILDING_VALUES:
                    continue
                kind, value = key, tags[key]
                break
        if not kind:
            continue

        dedupe = (name, value)
        if dedupe in seen:
            continue
        seen.add(dedupe)

        out.append({
            "name": name,
            "kind": kind,
            "value": value,
            "lat": float(lat),
            "lon": float(lon),
            "_rank": _notability(kind, value, tags),
        })

    # Most notable first, then cut. Sorting by name of category before the
    # cut meant a busy street's alcohol shops, bakeries and bars filled the
    # list and every museum, church and school - later in the alphabet - was
    # silently dropped.
    out.sort(key=lambda d: (-d["_rank"], d["value"], d["name"].lower()))
    kept = _share_out(out, limit)
    for d in kept:
        del d["_rank"]
    kept.sort(key=lambda d: (d["value"], d["name"].lower()))
    return kept


def _share_out(ranked: list[dict], limit: int) -> list[dict]:
    """The best `limit` landmarks, with no one kind of place taking the list.

    Two passes down the ranking. The first takes each kind up to its share, so
    the church, the school, the market and the theatre are all in before the
    fortieth church; the second fills whatever is left over from what was
    passed up, so a place that really is all churches still gets a full list
    rather than a short one.
    """
    if len(ranked) <= limit:
        return list(ranked)
    share = max(VALUE_MIN, int(limit * VALUE_SHARE))
    taken: dict[str, int] = {}
    kept, spare = [], []
    for item in ranked:
        value = item["value"]
        if len(kept) < limit and taken.get(value, 0) < share:
            taken[value] = taken.get(value, 0) + 1
            kept.append(item)
        else:
            spare.append(item)
    kept.extend(spare[:max(0, limit - len(kept))])
    return kept


# What a player would navigate by. Weighted by key, raised for the values that
# are landmarks in any town, and again when the place has its own Wikipedia or
# Wikidata entry - a fair sign that people outside the street have heard of it.
KEY_WEIGHT = {"historic": 6, "tourism": 5, "leisure": 3, "amenity": 3,
              "healthcare": 2, "building": 2, "office": 1, "shop": 1}
NOTABLE_VALUES = {
    "place_of_worship": 4, "church": 4, "mosque": 4, "cathedral": 5,
    "synagogue": 4, "temple": 4, "school": 3, "university": 4, "college": 3,
    "hospital": 4, "townhall": 4, "police": 3, "fire_station": 3,
    "library": 3, "museum": 5, "attraction": 4, "castle": 5, "monument": 4,
    "park": 3, "stadium": 4, "marketplace": 3, "theatre": 3, "cinema": 2,
    "train_station": 4, "bus_station": 2, "supermarket": 2, "mall": 3,
    "department_store": 2, "fuel": 2, "pharmacy": 1, "post_office": 2,
    "prison": 4, "courthouse": 3, "hotel": 2,
}


def _notability(kind: str, value: str, tags: dict) -> int:
    score = KEY_WEIGHT.get(kind, 0) + NOTABLE_VALUES.get(value, 0)
    if "wikidata" in tags or "wikipedia" in tags:
        score += 4
    return score
