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

HEADERS = {
    "User-Agent": "KnoxMap/1.0 (+https://github.com/spytheeuclidean-a11y/knoxify) local map generator",
    "Accept-Language": "en",
}

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

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
        })
    return out


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


def landmarks(south: float, west: float, north: float, east: float,
              limit: int = 300) -> list[dict]:
    """Named landmarks inside the bbox, most specific category first."""
    query = _build_query(south, west, north, east)
    last_err: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            r = requests.post(endpoint, data={"data": query},
                              headers=HEADERS, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                last_err = RuntimeError(f"{endpoint} -> {r.status_code}")
                continue
            r.raise_for_status()
            return _parse(r.json(), limit)
        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            continue
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
        })

    out.sort(key=lambda d: (d["value"], d["name"].lower()))
    return out[:limit]
