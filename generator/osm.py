"""Query OpenStreetMap via the Overpass API.

We only pull tags that map cleanly onto PZ terrain categories — everything
else is ignored. The query asks for a single bbox and returns ways/relations
with their full geometry so we can rasterize without a second roundtrip.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import threading
import time
import zlib
from concurrent import futures
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import requests

import knoxlog
import knoxpaths
import knoxstop

# Both lists can be replaced from knoxmap_config.json, which updates leave
# alone, so a dead public instance can be swapped without editing the source:
#   "overpass_endpoints": ["https://.../api/interpreter", ...]
#   "overpass_blank_only": ["overpass.osm.ch"]
def _config_list(key: str) -> list:
    try:
        value = knoxpaths.load_config().get(key)
    except Exception:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


_DEFAULT_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    # kumi.systems stops answering for long stretches; this one was answering
    # real data when it did.
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    # kumi.systems' successor, listed on the OSM wiki as a global instance
    # with no rate limit and no key.
    "https://overpass.private.coffee/api/interpreter",
    # A third, because the other two go busy together: when one instance
    # is queueing the people it turned away are queueing on the next.
    # It is last because it is the one that answers an ordinary query with an
    # empty result - see EMPTY_NEEDS_SECOND below.
    "https://overpass.osm.ch/api/interpreter",
    # More regional instances. Like osm.ch they answer blank outside their own
    # area, so they are blank-only too (BLANK_ONLY_HOSTS).
    "https://overpass.maprva.org/api/interpreter",
    "https://ethiopia.overpass.openplaceguide.org/api/interpreter",
]
OVERPASS_ENDPOINTS = _config_list("overpass_endpoints") or _DEFAULT_ENDPOINTS
# overpass.openstreetmap.fr answers every query with 403 "This service is only
# available to white-listed usages". It was tried once per tile, and on the
# tiles whose turn it was it pushed the work onto whatever came next.

# The instances that answer an ordinary query with real data. osm.ch is left
# out: it is still asked, and its blank still counts towards BLANKS_TO_BELIEVE,
# but it is not capacity and must not be counted as a download slot.
BLANK_ONLY_HOSTS = tuple(_config_list("overpass_blank_only")
                         or ["overpass.osm.ch",
                              "overpass.maprva.org",
                              "ethiopia.overpass.openplaceguide.org"])
ANSWERING_ENDPOINTS = [e for e in OVERPASS_ENDPOINTS
                       if not any(h in e for h in BLANK_ONLY_HOSTS)]


def osm_source() -> str:
    """Where a map's OpenStreetMap data comes from: "extract" (a downloaded
    regional file), "overpass" (the live servers) or "auto", the default - the
    extract, and Overpass only where no extract can be used. Set osm_source in
    knoxmap_config.json, or KNOXMAP_OSM_SOURCE in the environment."""
    value = os.environ.get("KNOXMAP_OSM_SOURCE", "").strip().lower()
    if not value:
        try:
            value = str(knoxpaths.load_config().get("osm_source") or "").strip().lower()
        except Exception:  # noqa: BLE001
            value = ""
    return value if value in ("extract", "overpass") else "auto"


def set_endpoints(urls: Sequence[str] | None) -> list:
    """Use these Overpass servers from now on, without a restart; none (or an
    empty list) goes back to the public ones. Returns the list in use.

    The settings window saves the same list to knoxmap_config.json, which is
    what the next start reads."""
    global OVERPASS_ENDPOINTS, ANSWERING_ENDPOINTS
    OVERPASS_ENDPOINTS = [u for u in (urls or []) if u] or list(_DEFAULT_ENDPOINTS)
    ANSWERING_ENDPOINTS = [e for e in OVERPASS_ENDPOINTS
                           if not any(h in e for h in BLANK_ONLY_HOSTS)]
    try:
        from generator import places
        places.OVERPASS_ENDPOINTS = list(ANSWERING_ENDPOINTS)
    except Exception:  # noqa: BLE001 - the place search is optional here
        pass
    return list(OVERPASS_ENDPOINTS)

# How long an instance that turned us away or stopped answering is left out of
# the rotation. Without this every tile found out the same thing for itself:
# nine tiles against a busy server each waited the full timeout to learn what
# the first one already knew, so a download spent ten minutes discovering one
# fact. The tile that finds it pays once and the rest go straight to an
# instance that is answering.
ENDPOINT_COOLDOWN_S = 120.0
# Each failure in a row doubles the rest, up to this. A server that is down or
# turning people away is not helped by being asked again every two minutes: one
# operator counted 22,515 requests in a day, 14,608 of them answered with a 504.
ENDPOINT_COOLDOWN_MAX_S = 3600.0
# A server that refuses us outright (401, 403, 451 - "white-listed use only",
# or told to go away) is left alone for this long, and across restarts.
REFUSED_FOR_S = 7 * 86400.0
# One request at a time to a host, and at least this long between the end of one
# and the start of the next. The public instances have a few slots each and
# many people sharing them.
HOST_MIN_GAP_S = 2.0
_cooling: dict = {}
_fails: dict = {}
_cooling_lock = threading.Lock()


def _refused_file() -> str:
    return os.path.join(str(knoxpaths.BASE_DIR), "cache", "overpass_refused.json")


def _load_refused() -> dict:
    try:
        with open(_refused_file(), encoding="utf-8") as f:
            data = json.load(f)
        now = time.time()
        return {k: float(v) for k, v in data.items() if float(v) > now}
    except (OSError, ValueError, AttributeError):
        return {}


_refused: dict = _load_refused()


def _refuse(endpoint: str) -> None:
    """This server said no. Leave it alone for a week, even after a restart."""
    with _cooling_lock:
        _refused[endpoint] = time.time() + REFUSED_FOR_S
        snapshot = dict(_refused)
    try:
        os.makedirs(os.path.dirname(_refused_file()), exist_ok=True)
        with open(_refused_file(), "w", encoding="utf-8") as f:
            json.dump(snapshot, f)
    except OSError:
        pass


def _is_refused(endpoint: str) -> bool:
    with _cooling_lock:
        until = _refused.get(endpoint, 0.0)
        if until and until <= time.time():
            del _refused[endpoint]
            return False
        return bool(until)


def _note_down(endpoint: str, retry_after: float | None = None) -> None:
    with _cooling_lock:
        n = _fails.get(endpoint, 0) + 1
        _fails[endpoint] = n
        wait = min(ENDPOINT_COOLDOWN_MAX_S, ENDPOINT_COOLDOWN_S * 2 ** (n - 1))
        if retry_after:
            wait = max(wait, min(float(retry_after), ENDPOINT_COOLDOWN_MAX_S))
        _cooling[endpoint] = time.time() + wait


def _note_up(endpoint: str) -> None:
    with _cooling_lock:
        _cooling.pop(endpoint, None)
        _fails.pop(endpoint, None)


def _is_cooling(endpoint: str) -> bool:
    with _cooling_lock:
        until = _cooling.get(endpoint, 0.0)
        if until and until <= time.time():
            del _cooling[endpoint]
            return False
        return bool(until)


def _rest_left() -> float:
    """Seconds until the first resting server may be asked again (0 if none rest)."""
    with _cooling_lock:
        times = [t - time.time() for t in _cooling.values()]
    return max(0.0, min(times)) if times else 0.0


_host_gate: dict = {}
_host_last: dict = {}
_gate_lock = threading.Lock()


class _one_at_a_time:
    """Hold a host for one request, after waiting out HOST_MIN_GAP_S since the
    last one finished."""

    def __init__(self, endpoint: str):
        self.host = endpoint.split("/")[2] if "//" in endpoint else endpoint

    def __enter__(self):
        with _gate_lock:
            gate = _host_gate.setdefault(self.host, threading.Lock())
        gate.acquire()
        pause = _host_last.get(self.host, 0.0) + HOST_MIN_GAP_S - time.time()
        if pause > 0:
            time.sleep(pause)
        return self

    def __exit__(self, *exc):
        _host_last[self.host] = time.time()
        _host_gate[self.host].release()
        return False


def _retry_after(r) -> float | None:
    """Seconds a server asked us to wait, from its Retry-After header."""
    try:
        return float(r.headers.get("Retry-After", ""))
    except (TypeError, ValueError, AttributeError):
        return None


def endpoint_ready(endpoint: str) -> bool:
    """Whether this server may be asked at all right now."""
    return not (_is_refused(endpoint) or _is_cooling(endpoint))


CONNECT_TIMEOUT_S = 10
PROBE_TIMEOUT_S = 8


def _status_url(endpoint: str) -> str:
    return endpoint.replace("/interpreter", "/status")


def _probe(endpoint: str, lat: float, lon: float) -> bool:
    """Does this instance answer? Asked of its status page, which is what that
    page is for and which costs the server no query - the probe used to be a
    real query sent to every instance at the start of every download."""
    if _is_refused(endpoint):
        return False
    try:
        with _one_at_a_time(endpoint):
            r = requests.get(_status_url(endpoint), headers=HEADERS,
                             timeout=(CONNECT_TIMEOUT_S, PROBE_TIMEOUT_S))
        if r.status_code in (401, 403, 451):
            _refuse(endpoint)
        return r.status_code == 200
    except (requests.RequestException, ValueError):
        return False


def check_endpoints(south: float, west: float, north: float, east: float) -> None:
    """Ask every instance a trivial question before the real download.

    The ones that do not answer go on cooldown, so tiles ask them last instead
    of each paying a full timeout to find out. The probes run together, so this
    costs a few seconds, not a few seconds per instance.
    """
    lat, lon = (south + north) / 2, (west + east) / 2
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return

    def one(endpoint):
        ok = _probe(endpoint, lat, lon)
        (_note_up if ok else _note_down)(endpoint)

    with futures.ThreadPoolExecutor(max_workers=len(OVERPASS_ENDPOINTS)) as pool:
        list(pool.map(one, OVERPASS_ENDPOINTS))


def _endpoint_order(first: int) -> list:
    """Which instances to ask, best first.

    The ones answering come first, rotated so concurrent tiles spread out. An
    instance on cooldown is left out entirely - unless they all are, when there
    is nothing to do but ask anyway. The blank-only instance is always last.
    """
    spin = first % max(1, len(ANSWERING_ENDPOINTS))
    spun = ANSWERING_ENDPOINTS[spin:] + ANSWERING_ENDPOINTS[:spin]
    # Resting moves an instance to the back of the queue; it does not take it
    # out. Dropping it altogether cost a player a town: one instance was
    # resting after a timeout, the other stopped answering too, and the tile
    # gave up having never asked the first. A rest is a guess about a server
    # we cannot see, so it may reorder the asking and must not end it. When
    # anything is answering the resting one is never reached anyway.
    ready = [e for e in spun if endpoint_ready(e)]
    return (ready + [e for e in OVERPASS_ENDPOINTS
                     if e not in ANSWERING_ENDPOINTS and endpoint_ready(e)])


# Whether an empty answer has to be confirmed by another instance before the
# tile is taken as empty ground (fetch_features), and how many have to agree.
# The flag is off only for tests, which would otherwise ask the real servers.
EMPTY_NEEDS_SECOND = True
BLANKS_TO_BELIEVE = 2

# OSM's usage policy requires a real identifying User-Agent; the mirrors return
# 403 for the default "python-requests/x.y" string.
HEADERS = {"User-Agent": "KnoxMap/1.0 (+https://github.com/spytheeuclidean-a11y/knoxmap) local map generator"}

# Tag filters — each line becomes one part of the Overpass union query.
# Order doesn't matter here; the rasterizer picks priority at paint time.
OVERPASS_FILTERS: Sequence[str] = (
    # water
    # The sea has no polygon in OSM, only the line of the shore, drawn with the
    # land on its left. Without it every coastal town was a meadow to the
    # horizon - see renderer.sea_polygons.
    'way["natural"="coastline"]',
    # Piers and breakwaters stand on the water; without them a marina's
    # jetties vanish and anything built on one floats.
    'way["man_made"~"^(pier|breakwater|groyne)$"]',
    # Railways: the lines a town grew along, and on the paper map. Trams run
    # in the street and are left to the road under them.
    'way["railway"~"^(rail|light_rail|narrow_gauge|disused|preserved)$"]',
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
    # Lone trees are not fetched. Every tree mapped as its own node was 9,300
    # of the 93,907 features in a New York download - a tenth of the payload,
    # and a third of all the nodes - for a 2 m dot each in the vegetation mask.
    # Woods, forest, scrub and parks are polygons and still come down in full;
    # what fills them is tree_density, so only a tree standing on its own in a
    # street is lost. The public instances were timing out on these tiles.
    # 'node["natural"="tree"]',
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
    # Monuments, statues and fountains: generator/structures.py
    'node["historic"~"^(monument|memorial)$"]',
    'way["historic"~"^(monument|memorial)$"]',
    'nwr["man_made"="obelisk"]',
    'node["tourism"="artwork"]',
    'nwr["amenity"="fountain"]',
    # Towers: a water tower, a lighthouse, a windmill or a clock tower is a
    # landmark somebody navigates by, not a house. Without this they arrive
    # only when the mapper also tagged building=*, and then as a bungalow.
    'nwr["man_made"~"^(water_tower|lighthouse|windmill|tower)$"]',
    # buildings
    'way["building"]',
    'relation["building"]',
    # Real interiors. Where a mapper drew the rooms inside a building, the
    # generated floor plan follows those walls instead of guessing (renderer
    # attaches them to the building, knoxbuild/layout cuts along them).
    # Rooms are only drawn in public and commercial buildings - schools,
    # hospitals, offices - so the payload is small next to the buildings.
    'way["indoor"~"^(room|corridor)$"]',
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
    # What the ground floors are: the pizza place, the bank, the pharmacy.
    # Mapped as points inside the building far more often than as the
    # building's own tags (knoxbuild/uses.py).
    'node["shop"]',
    'node["amenity"~"^(restaurant|fast_food|food_court|cafe|ice_cream|bar|pub|nightclub|'
    'biergarten|bank|bureau_de_change|post_office|pharmacy|dentist|doctors|clinic|'
    'veterinary|library|cinema|theatre|arts_centre|police|childcare|kindergarten|fuel|car_repair)$"]',
    'node["office"]',
    'node["craft"]',
    'node["healthcare"]',
    'node["leisure"~"^(fitness_centre|sports_centre|dance|bowling_alley)$"]',
    'node["tourism"~"^(hotel|motel|hostel|guest_house|museum|gallery)$"]',
    # Mapped building doors: carried into knoxbuild so the generated footprint
    # can put its exterior doors where people actually enter.
    'node["entrance"]',
    # The way through a fence. A mapper draws the fence as one unbroken line
    # and puts the gate in as a node on it, so a fence built from the line
    # alone walls off the drive it was never meant to cross.
    'node["barrier"~"^(gate|lift_gate|swing_gate|kissing_gate|cattle_grid|'
    'stile|entrance|bollard)$"]',
    # Bases, armouries, barracks: mapped with military=* as often as with
    # landuse=military, and without these an armoury was somebody's house.
    'way["military"]',
    'relation["military"]',
    # Homes that were surveyed but never drawn. In whole countries, and in
    # most American suburbs, a house is one node with its number on it and
    # nothing else; those streets came out as roads through empty grass
    # (generator/rendering/buildings.py _houses_from_addresses).
    'node["addr:housenumber"]',
)

# Bumped whenever the filters above change, so a cached download made with
# the old list is fetched again instead of silently lacking the new features.
FILTERS_VERSION = 14


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

    def __init__(self, message: str, too_big: bool = False,
                 timed_out: bool = False, busy: bool = False,
                 retry_after: float | None = None, refused: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        # The server said no, not "later": 401, 403 or 451.
        self.refused = refused
        self.too_big = too_big
        # Nothing answered at all, as opposed to answering with a refusal.
        self.timed_out = timed_out
        # The instance turned us away rather than disagreeing with the query:
        # 429 out of slots, or a gateway that is not coping. Worth going
        # somewhere else, and worth other tiles not finding out the hard way.
        self.busy = busy


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
    # A host that is down never completes the connection; waiting the whole
    # query timeout to learn that cost 100 s per dead instance per tile.
    with _one_at_a_time(endpoint):
        r = requests.post(endpoint, data={"data": query}, headers=HEADERS,
                          timeout=(CONNECT_TIMEOUT_S, timeout + 10))
    if r.status_code == 200:
        payload = r.json()
        # A query that runs out of time or memory part way through does not
        # fail: Overpass sends HTTP 200 with whatever it had gathered and puts
        # the reason in "remark". Reading only the status took that for a
        # finished tile, so a town downloaded "successfully" with half its
        # streets missing and nothing anywhere said so.
        remark = str(payload.get("remark") or "")
        if any(s in remark.lower() for s in _TOO_BIG):
            raise OverpassError(f"partial answer — {' '.join(remark.split())}",
                                too_big=True)
        return _parse(payload)
    # Classify on the whole body, report a trimmed version of it. Doing both
    # from the trimmed text is what stopped over-large areas re-splitting: the
    # markers sit well past the doctype, so nothing ever looked too big.
    whole = r.text.lower()
    message = _error_text(r.text)
    too_big = (any(s in whole for s in _TOO_BIG)
               and not any(s in whole for s in _MY_FAULT))
    raise OverpassError(f"HTTP {r.status_code}"
                        + (f" — {message}" if message else ""),
                        too_big=too_big,
                        busy=r.status_code == 429 or 500 <= r.status_code < 600,
                        retry_after=_retry_after(r),
                        refused=r.status_code in (401, 403, 451))


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
    timed_out = False
    blank = 0
    real_blank = 0
    order = _endpoint_order(first)
    for endpoint in order:
        host = endpoint.split("/")[2]
        try:
            feats = _ask(endpoint, query, timeout)
        except OverpassError as exc:
            errors.append(f"{host}: {exc}")
            too_big = too_big or exc.too_big
            if exc.refused:
                _refuse(endpoint)
            elif exc.busy:
                _note_down(endpoint, exc.retry_after)
        except requests.Timeout:
            errors.append(f"{host}: no answer within {timeout + 10}s")
            timed_out = True
            _note_down(endpoint)
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{host}: {exc}")
            _note_down(endpoint)
        else:
            _note_up(endpoint)
            if feats or not EMPTY_NEEDS_SECOND:
                return feats
            # An instance that answers 200 with nothing in it looks exactly
            # like open farmland, and the tiles it was handed went into the map
            # as empty ground. A city came out a meadow with its river still
            # in it, because the tiles that did download held the river.
            # Nothing is only believed when a second instance agrees.
            blank += 1
            real_blank += endpoint in ANSWERING_ENDPOINTS
            errors.append(f"{host}: answered with nothing")
        time.sleep(1)
    # Two instances have to say the tile is empty before it is. One saying so
    # while the others never answered at all is not agreement, it is the one
    # broken instance again - and taking it at its word is what quietly
    # emptied the map in the first place. Raising sends the tile back round
    # fetch_features_tiled's retry, and if it really will not download the
    # download says so instead of handing back a meadow.
    # Regional instances are blank everywhere but home, so their agreement
    # alone proves nothing: one of the instances that answer with data has to
    # be among them.
    if blank >= BLANKS_TO_BELIEVE and real_blank:
        return []
    if not errors:
        wait = int(_rest_left())
        raise OverpassError(
            "the Overpass servers are resting after refusing or failing to answer"
            + (f" - asking again in about {wait}s" if wait else ""),
            busy=True)
    raise OverpassError("every Overpass endpoint failed — "
                        + "; ".join(errors), too_big=too_big,
                        timed_out=timed_out)


def explain(exc: BaseException) -> str:
    """What went wrong and what to do about it, for someone who is not reading
    Overpass logs. The technical reason follows, for anyone who is."""
    if isinstance(exc, OverpassError):
        if exc.too_big:
            head = ("That area has more map data than the public servers will "
                    "send in one go. Pick a smaller area and try again.")
        else:
            head = ("The free OpenStreetMap servers are busy or not answering "
                    "right now. KnoxMap already retried. Wait a few minutes "
                    "and press Generate again; anything that did download is "
                    "kept, so the next try is faster. A smaller area also helps.")
    elif isinstance(exc, requests.RequestException):
        head = ("KnoxMap could not reach the OpenStreetMap servers. Check your "
                "internet connection, then try again.")
    else:
        return f"OSM query failed: {exc}"
    return f"{head}\n\nDetails: {exc}"


def _area_km2(south: float, west: float, north: float, east: float) -> float:
    lat_mid = math.radians((south + north) / 2)
    return abs((north - south) * 111.32 *
               (east - west) * 111.32 * math.cos(lat_mid))


def _say(progress, done: int, total: int, note: str) -> None:
    """Tell the window what is happening, if it asked and if it can hear it.

    The callback took two arguments before there was anything to say, and a
    caller may still pass one of those.
    """
    if progress is None:
        return
    try:
        progress(done, total, note)
    except TypeError:
        progress(done, total)


# Tiles that downloaded are kept on disk, so a download that fails part way, or
# is cancelled, does not fetch them again next time. They go stale: the map
# moves, and the filters change (FILTERS_VERSION is checked by load_cache).
TILE_CACHE_DIR = os.path.join(str(knoxpaths.BASE_DIR), "cache", "overpass_tiles")
TILE_CACHE_MAX_AGE_S = 14 * 86400
# How many tiles each download had to take from the cache past their age, for
# the tests and the log; the download itself says so through `progress`.
STALE_TILES_USED: list = []


def _tile_cache_file(box: tuple) -> str:
    key = ",".join(f"{v:.7f}" for v in box)
    name = hashlib.sha1(key.encode("ascii")).hexdigest()[:20]
    return os.path.join(TILE_CACHE_DIR, f"{name}.json.gz")


def _tile_cache_get(box: tuple, stale_ok: bool = False) -> list | None:
    """A kept tile; one past its age only when `stale_ok` (the servers are down)."""
    path = _tile_cache_file(box)
    try:
        if not stale_ok and time.time() - os.path.getmtime(path) > TILE_CACHE_MAX_AGE_S:
            return None
    except OSError:
        return None
    return load_cache(path, box)


def _tile_cache_put(box: tuple, feats: list) -> None:
    try:
        save_cache(_tile_cache_file(box), box, feats)
    except OSError:
        pass  # a tile that cannot be kept is still a tile


def _local_features(south: float, west: float, north: float, east: float) -> list:
    """Features from the player's own Overpass-JSON file, if one is set.

    "osm_json_file" in knoxmap_config.json names a file saved from
    overpass-turbo (Export -> raw OSM data, with geometry) or any Overpass
    `[out:json]` query using `out geom`. It is only read when the public
    servers have failed, and only what lies inside the map is kept.
    """
    try:
        path = knoxpaths.load_config().get("osm_json_file")
    except Exception:
        return []
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            feats = _parse(json.load(fh))
    except (OSError, ValueError):
        return []

    def inside(f: OSMFeature) -> bool:
        pts = f.geometry or [p for _role, ring in f.role_geoms for p in ring]
        return any(south <= lat <= north and west <= lon <= east
                   for lat, lon in (_flat(pts)))

    return [f for f in feats if inside(f)]


def _flat(points):
    for p in points:
        if p and isinstance(p[0], (int, float)):
            yield p[0], p[1]
        elif p:
            yield from _flat(p)


def fetch_features_tiled(south: float, west: float, north: float, east: float,
                         max_tile_km2: float = 30.0, timeout: int = 90,
                         progress=None, should_stop=None) -> list[OSMFeature]:
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
    source = osm_source()
    if source != "overpass":
        # A town is hundreds of queries against servers other people run and
        # pay for. OpenStreetMap is also published as files, and reading one on
        # this PC asks nobody for anything (generator/extract.py).
        from . import extract
        try:
            if not extract.available():
                raise extract.ExtractUnavailable(
                    "pyosmium is not installed (run Setup again, or pip install osmium)")
            return extract.features(south, west, north, east, progress=progress,
                                    should_stop=should_stop)
        except extract.ExtractUnavailable as exc:
            if source == "extract":
                raise OverpassError(f"The OpenStreetMap extract could not be used: {exc}") from None
            _say(progress, 1, 1, f"no extract ({exc}) - asking the Overpass servers instead")
            knoxlog.log.warning("osm: no extract (%s); using Overpass", exc)

    area = _area_km2(south, west, north, east)
    steps = max(1, math.ceil(math.sqrt(area / max_tile_km2)))
    # A map small enough to be one tile goes the same way as any other. It
    # used to return straight from here, which meant it never reached the
    # retry below: the smaller the area the less it tried, and "a smaller area
    # always works" is what the failure tells people to do. A 6.8 km2 town
    # failed after one pass while a city got three.

    check_endpoints(south, west, north, east)

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
    done = [0]
    lock = threading.Lock()

    def run(args):
        index, (s0, w0, n0, e0) = args
        # Between tiles is the one place a download can be dropped without
        # leaving a half-written cache behind; the tiles already in flight
        # finish and are thrown away with the rest.
        knoxstop.check(should_stop, "the download")
        try:
            box = (s0, w0, n0, e0)
            kept = _tile_cache_get(box)
            if kept is not None:
                return index, kept, None
            got = _fetch_splitting(s0, w0, n0, e0, timeout, first=index)
            _tile_cache_put(box, got)
            return index, got, None
        except OverpassError as exc:
            return index, None, exc
        finally:
            with lock:
                done[0] += 1
                if progress:
                    progress(min(done[0], total), total)

    # One tile failing used to lose the map: the whole download was thrown
    # away and nothing was cached, so a town that had fetched forty tiles and
    # missed one started again from nothing. The tiles that arrived are kept
    # and only the ones that did not are asked for again - a public instance
    # that was busy a moment ago usually is not a minute later.
    # Only the instances that answer with data are capacity. osm.ch replies 200
    # with nothing (EMPTY_NEEDS_SECOND), and a blank needs a second instance to
    # agree before it is believed, so it can never finish a tile on its own -
    # counting it ran three tiles at once against the two that answer, which
    # queued us behind ourselves on servers that were already busy.
    workers = min(max(1, len(ANSWERING_ENDPOINTS)), total)
    left = list(enumerate(tiles))
    problems: dict[int, OverpassError] = {}
    for attempt in range(TILE_ATTEMPTS):
        if attempt:
            # Say what the wait is for. Three passes with a minute or two
            # between them is a long time to sit on "Querying OpenStreetMap"
            # with nothing moving, and a player who thinks it has hung kills
            # it just before the pass that would have worked.
            wait = _retry_pause(attempt)
            for left_s in range(wait, 0, -1):
                knoxstop.check(should_stop, "the download")
                _say(progress, total - len(left), total,
                     f"the Overpass servers are busy — waiting {left_s}s, "
                     f"then trying again ({attempt + 1} of {TILE_ATTEMPTS})")
                time.sleep(1.0)
            _say(progress, total - len(left), total, "")
        done[0] = total - len(left)
        problems = {}
        again = []
        with futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for index, feats, exc in pool.map(run, left):
                if exc is not None:
                    problems[index] = exc
                    again.append((index, tiles[index]))
                    continue
                for feat in feats:
                    merged[(feat.kind, feat.osm_id)] = feat
        left = again
        if not left:
            break

    if left:
        # Next to last: the same tiles as kept from an earlier download, however
        # old. Only all of them will do - a map with holes where the tiles were
        # missing would come out with empty ground there.
        old_tiles = [_tile_cache_get(tiles[i], stale_ok=True) for i, _ in left]
        if all(t is not None for t in old_tiles):
            for feats in old_tiles:
                for feat in feats:
                    merged.setdefault((feat.kind, feat.osm_id), feat)
            STALE_TILES_USED.append(len(left))
            _say(progress, total, total,
                 f"the Overpass servers did not answer — {len(left)} of {total} "
                 f"tiles come from an earlier download and may be out of date")
            return list(merged.values())
        # Last resort: an Overpass-JSON export the player supplied.
        local = _local_features(south, west, north, east)
        if local:
            for feat in local:
                merged.setdefault((feat.kind, feat.osm_id), feat)
            return list(merged.values())
        worst = problems[left[0][0]]
        # A map that is one tile has already been asked for on every pass and
        # cannot be cut up any further, so telling its owner to pick a smaller
        # area is advice they have already taken.
        how_many = ("The map would not download"
                    if total == 1 else
                    f"{len(left)} of {total} map tiles would not download")
        smaller = "" if total == 1 else ", and a smaller area always does"
        raise OverpassError(
            f"{how_many}. The public Overpass servers are shared and go busy; "
            f"waiting a few minutes and generating again usually works"
            f"{smaller}. {worst}",
            too_big=any(e.too_big for e in problems.values()),
            timed_out=all(e.timed_out for e in problems.values()))

    return list(merged.values())


# Below this, a tile is small enough that a refusal is the server's problem
# rather than the area's, and splitting further only multiplies the requests.
MIN_SPLIT_KM2 = 0.5
# A tile nothing answered in time is usually a tile too heavy to answer, so it
# is quartered like a refused one - but only while it is big enough for that to
# be the reason, and only one level down. Past that it is the network rather
# than the area, and splitting only takes four times as long to say so.
TIMEOUT_SPLIT_KM2 = 4.0
TIMEOUT_SPLIT_DEPTH = 1
# How many passes over the tiles a map gets, and how long to leave the servers
# alone between them. The pause doubles: a public instance that is turning
# people away is busy for minutes, and twenty seconds put the next pass back
# inside the same busy spell, so the retry mostly failed the way the first try
# had. The error people saw told them to wait a few minutes and try again,
# which worked - this is the program doing that itself.
TILE_ATTEMPTS = 4
RETRY_PAUSE_S = 45
RETRY_PAUSE_MAX_S = 180


def _retry_pause(attempt: int) -> int:
    """Seconds to wait before pass `attempt` (1 is the first retry)."""
    return min(RETRY_PAUSE_MAX_S, RETRY_PAUSE_S * 2 ** (attempt - 1))


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
        area = _area_km2(south, west, north, east)
        heavy = exc.too_big or (exc.timed_out and depth < TIMEOUT_SPLIT_DEPTH
                                and area > TIMEOUT_SPLIT_KM2)
        if not heavy or depth >= 3 or area <= MIN_SPLIT_KM2:
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
    # Written beside the file and moved over it, so a crash or a full disk part
    # way through leaves the old file (or none), never half of a new one.
    partial = path + ".part"
    try:
        with gzip.open(partial, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(partial, path)
    except BaseException:
        try:
            os.remove(partial)
        except OSError:
            pass
        raise


def load_cache(path: str, bbox: tuple[float, float, float, float],
               filters: int | None = FILTERS_VERSION) -> list[OSMFeature] | None:
    """Cached features for exactly this bbox, or None.

    `filters` is the filter list the caller insists on: the current one by
    default, so a download made before the list grew is fetched again rather
    than quietly lacking what was added to it. Pass None to take whatever is
    there, which is what the steps after the map was drawn want - the build
    and the paper map read this download, they never fetch one, and refusing
    an older file there does not get the new tags, it loses every road, river
    and wood the map already has.
    """
    if not os.path.exists(path):
        return None
    # A cache is only ever a shortcut: whatever is wrong with the file - cut
    # short by a crash (EOFError, not an OSError), not what it should be, an
    # entry with a field missing - the answer is "not cached" and the area is
    # downloaded again, not a failed map.
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        if filters is not None and payload.get("filters") != filters:
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
    except (OSError, EOFError, ValueError, KeyError, TypeError, AttributeError, zlib.error):
        return None


def assemble_rings(role_geoms: list[tuple[str, list[tuple[float, float]]]]
                   ) -> list[tuple[str, list[tuple[float, float]]]]:
    """Join a multipolygon's member ways into closed rings.

    A relation's outline is rarely one way: a lake shore, a harbour or a
    forest edge is split into dozens of ways that only close into a ring end
    to end. Painted one way at a time, each way became a polygon of its own -
    a sliver from one end to the other - so Sydney Harbour came out as 6%
    water in scattered wedges. Ways are merged per role (outer, inner) and
    closed into rings; whatever does not close is kept as it was.
    """
    from shapely.geometry import LineString
    from shapely.ops import linemerge, polygonize, unary_union

    out: list[tuple[str, list[tuple[float, float]]]] = []
    for role in ("outer", "inner"):
        lines = [LineString([(lon, lat) for lat, lon in ring])
                 for r, ring in role_geoms
                 if (r or "outer") == role and len(ring) >= 2]
        if not lines:
            continue
        try:
            faces = list(polygonize(linemerge(unary_union(lines))))
        except Exception:  # noqa: BLE001 - malformed geometry: keep the ways
            faces = []
        if faces:
            out += [(role, [(lat, lon) for lon, lat in face.exterior.coords])
                    for face in faces]
        else:
            out += [(r, ring) for r, ring in role_geoms if (r or "outer") == role]
    return out or role_geoms


def _points(geometry) -> list[tuple[float, float]]:
    """The (lat, lon) points of an Overpass geometry list.

    A point that is null or has no coordinates is dropped, not fatal: Overpass
    leaves a null where a node is not in the data (clipped output, a relation
    member whose way is missing), and a file saved from overpass-turbo can have
    them too. One of those used to fail the whole answer - and with it the
    whole tile, on every server, since they all send the same thing."""
    out = []
    for p in geometry or []:
        try:
            lat, lon = float(p["lat"]), float(p["lon"])
        except (TypeError, KeyError, ValueError):
            continue
        if math.isfinite(lat) and math.isfinite(lon):     # "nan" is a float to float()
            out.append((lat, lon))
    return out


def _parse(payload: dict) -> list[OSMFeature]:
    if not isinstance(payload, dict):
        return []
    out: list[OSMFeature] = []
    for el in payload.get("elements") or []:
        if not isinstance(el, dict):
            continue
        kind = el.get("type")
        tags = el.get("tags") or {}
        ident = el.get("id", 0)
        if kind == "way":
            coords = _points(el.get("geometry"))
            if coords:
                out.append(OSMFeature(ident, "way", tags, coords))
        elif kind == "relation":
            rings: list[list[tuple[float, float]]] = []
            role_geoms: list[tuple[str, list[tuple[float, float]]]] = []
            for m in el.get("members") or []:
                if not isinstance(m, dict):
                    continue
                ring = _points(m.get("geometry"))
                if not ring:
                    continue
                role_geoms.append((m.get("role") or "", ring))
                rings.append(ring)
            if rings:
                role_geoms = assemble_rings(role_geoms)
                feat = OSMFeature(ident, "relation", tags,
                                  [ring for _role, ring in role_geoms] or rings)
                feat.role_geoms = role_geoms
                out.append(feat)
        elif kind == "node":
            lat, lon = el.get("lat"), el.get("lon")
            if lat is not None and lon is not None:
                out.append(OSMFeature(ident, "node", tags, [(lat, lon)]))
    return out


# Barrier kinds that become fences in game, as opposed to hedges.
FENCE_BARRIERS = {"fence", "wall", "retaining_wall", "city_wall"}
# What a mapper puts on a fence where people get through it. The fence line
# runs straight past the node, so the fence is built with a hole or a gate
# here instead of across the way in.
GATE_BARRIERS = {"gate", "lift_gate", "swing_gate", "kissing_gate",
                 "cattle_grid", "stile", "entrance"}

SCHOOL_AMENITIES = {"school", "university", "college", "kindergarten"}


PAVED_SURFACES = {"paved", "asphalt", "concrete", "concrete:plates",
                  "concrete:lanes", "paving_stones", "sett", "cobblestone",
                  "unhewn_cobblestone", "bricks", "metal", "wood", "tiles"}
UNPAVED_SURFACES = {"unpaved", "dirt", "earth", "ground", "grass", "gravel",
                    "fine_gravel", "compacted", "sand", "mud", "pebblestone",
                    "woodchips", "grass_paver"}


# Underground things. A road in a tunnel painted on the surface cut a street
# through whole blocks; a car park under a square covered the square in tarmac.
TUNNEL_VALUES = {"yes", "building_passage", "culvert", "avalanche_protector", "flooded"}


HIGHWAY_HIERARCHY = {
    "motorway": "motorway", "motorway_link": "motorway",
    "trunk": "trunk", "trunk_link": "trunk",
    "primary": "primary", "primary_link": "primary",
    "secondary": "secondary", "secondary_link": "secondary",
    "tertiary": "tertiary", "tertiary_link": "tertiary",
    "residential": "residential", "unclassified": "residential",
    "living_street": "residential", "road": "residential",
    "service": "service", "footway": "footway", "cycleway": "footway",
    "bridleway": "footway", "path": "footway", "steps": "footway",
}

ROAD_HIERARCHY_CODES = {
    "footway": 1, "service": 2, "residential": 3, "tertiary": 4,
    "secondary": 5, "primary": 6, "trunk": 7, "motorway": 8,
}
ROAD_HIERARCHY_BY_CODE = {code: name for name, code in ROAD_HIERARCHY_CODES.items()}


def road_hierarchy(tags: dict) -> str | None:
    """Detailed street function from the OSM highway tag, if any."""
    return HIGHWAY_HIERARCHY.get(str(tags.get("highway") or "").lower())


def classify(tags: dict, area: bool = False) -> str | None:
    """Map OSM tags to a PZ feature category string. None = ignore.

    `area` says the feature is a closed way or a relation - something with an
    inside - which changes two answers. An arcade is not a tunnel, and a
    pedestrian way that closes on itself is a square rather than a street.
    """
    if "building" in tags:
        return "building"
    # A building passage is a way through a building at ground level, not
    # under it - a colonnade or an archway. Read as a tunnel it took Madrid's
    # Plaza Mayor, 11,437 m2 of it, off the map altogether and left grass.
    underground = tags.get("tunnel") in TUNNEL_VALUES
    if area and tags.get("tunnel") == "building_passage":
        underground = False
    if (underground or tags.get("location") == "underground"
            or tags.get("parking") == "underground"):
        return None

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
    # A pedestrian street is drawn as a line and a pedestrian square as a fill.
    # Which it is, is whether the way closes on itself: area=yes says so when
    # the mapper remembered it, and the shape says so either way. The same for
    # the colonnade round a square, which is a footway that comes back to
    # where it started.
    if tags.get("place") == "square" or "area:highway" in tags or (
            tags.get("highway") == "pedestrian"
            and (area or tags.get("area") == "yes")) or (
            area and tags.get("highway") == "footway"
            and tags.get("covered") in ("colonnade", "arcade", "yes")):
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
        # A pedestrian zone is a square people stand in, not a lane. Lumped
        # in with service alleys it was painted three and a half metres wide,
        # so Madrid's Puerta del Sol - mapped as a mesh of pedestrian ways and
        # no polygon at all - came out as a few paved stripes on grass.
        if h == "pedestrian":
            return "pedestrian"
        # Alleys, driveways and back lanes. Lumping these in with residential
        # streets paved every yard and car park aisle at full street width.
        if h == "service":
            return "road_service"
        if h in {"track", "path", "footway", "cycleway", "bridleway", "steps"}:
            # A city's pavements are mapped as footways alongside each street,
            # and painting them as dirt put a brown strip down every kerb in
            # Paris. Footways, cycleways and steps are paved unless the mapper
            # says otherwise; tracks and paths are dirt unless they say paved.
            surface = (tags.get("surface") or "").lower()
            if surface in PAVED_SURFACES:
                return "paved_path"
            if surface in UNPAVED_SURFACES:
                return "dirt_path"
            if h in {"footway", "cycleway", "steps"}:
                return "paved_path"
            return "dirt_path"
        return "road_minor"

    if leisure == "swimming_pool" and tags.get("indoor") not in ("yes", "covered"):
        return "pool"
    if tags.get("natural") == "coastline":
        return "coastline"
    if tags.get("man_made") in {"pier", "breakwater", "groyne"}:
        return "pier"
    if tags.get("railway") in {"rail", "light_rail", "narrow_gauge", "disused", "preserved"}:
        return "railway"
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
    # A base is as often drawn with military=* alone - airfield, barracks,
    # range, training_area, naval_base - as with landuse=military.
    if landuse == "military" or (tags.get("military") or "no") != "no":
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
