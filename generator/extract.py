"""Map data from a downloaded regional extract, not live Overpass queries.

OpenStreetMap is published as flat files. Geofabrik cuts the planet into
extracts by continent, country and state or province, and updates each one
every day. Reading a map's worth of data out of one of those, on this PC, costs
the shared Overpass servers nothing - which is what the people who run them
ask of anything that fetches a whole town, a few hundred tiles at a time.

The extract is downloaded once and kept (cache/extracts), checked for a newer
copy at most every two weeks, and read with pyosmium using the same tag filters
the Overpass query uses (generator.osm.OVERPASS_FILTERS). What comes out is the
JSON Overpass would have answered with, so it goes through the same parser and
nothing downstream can tell the difference.
"""
from __future__ import annotations

import json
import os
import re
import struct
import tempfile
import time

import requests
from shapely import from_wkb

import knoxpaths
import knoxstop

GEOFABRIK_INDEX = "https://download.geofabrik.de/index-v1.json"
INDEX_MAX_AGE_S = 30 * 86400.0
# How long an extract is used without asking Geofabrik whether it has a newer
# one. They are rebuilt daily and nobody's map needs yesterday's changes.
EXTRACT_MAX_AGE_S = 14 * 86400.0
# More extracts than this for one map means a box over half a continent.
MAX_REGIONS = 6
# Above this a node-location table in memory would not fit; it goes to disk.
BIG_EXTRACT_BYTES = 1_500_000_000
CHUNK = 1 << 20
CONNECT_TIMEOUT_S = 15
READ_TIMEOUT_S = 60
HEADERS = {"User-Agent": "KnoxMap/1.0 (+https://github.com/spytheeuclidean-a11y/knoxmap) "
                         "local map generator (downloads regional extracts, cached)"}


class ExtractUnavailable(RuntimeError):
    """The extract route cannot be taken here (no pyosmium, no extract covers
    the place, no way to download one). The caller may use Overpass instead."""


def cache_dir() -> str:
    return os.path.join(str(knoxpaths.BASE_DIR), "cache", "extracts")


def available() -> bool:
    try:
        import osmium  # noqa: F401
    except ImportError:
        return False
    return True


# ---- the Overpass filters, read back ---------------------------------------------

_FILTER = re.compile(r'^(node|way|relation|nwr)((?:\[[^\]]+\])*)$')
_COND = re.compile(r'\["([^"]+)"(?:(=|~)"((?:[^"\\]|\\.)*)")?\]')


class Filter:
    """One line of OVERPASS_FILTERS: which kinds, and the tag tests."""

    def __init__(self, line: str):
        m = _FILTER.match(line.strip())
        if not m:
            raise ValueError(f"unreadable filter: {line!r}")
        head = m.group(1)
        self.kinds = {"node", "way", "relation"} if head == "nwr" else {head}
        self.tests = []
        for key, op, value in _COND.findall(m.group(2)):
            if op == "~":
                self.tests.append((key, re.compile(value)))
            elif op == "=":
                self.tests.append((key, value))
            else:
                self.tests.append((key, None))

    def matches(self, kind: str, tags) -> bool:
        if kind not in self.kinds:
            return False
        for key, want in self.tests:
            have = tags.get(key)
            if have is None:
                return False
            if want is None:
                continue
            if isinstance(want, str):
                if have != want:
                    return False
            elif not want.search(have):
                return False
        return True


def parse_filters(lines) -> list[Filter]:
    return [Filter(line) for line in lines]


def wanted(filters: list[Filter], kind: str, tags) -> bool:
    return any(f.matches(kind, tags) for f in filters)


# ---- which extract covers a box ----------------------------------------------------

def _index(refresh_ok: bool = True) -> dict:
    path = os.path.join(cache_dir(), "geofabrik-index.json")
    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < INDEX_MAX_AGE_S
    if not fresh and refresh_ok:
        try:
            r = requests.get(GEOFABRIK_INDEX, headers=HEADERS,
                             timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S))
            r.raise_for_status()
            data = r.json()
            os.makedirs(cache_dir(), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return data
        except (requests.RequestException, ValueError, OSError):
            pass
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        raise ExtractUnavailable("could not read Geofabrik's list of extracts "
                                 f"({GEOFABRIK_INDEX}) and none is saved") from None


def regions_for(south: float, west: float, north: float, east: float,
                index: dict) -> list[dict]:
    """The smallest extract that holds the whole box, as {id, name, url}; or,
    where no one does (a box across a border no extract spans), the smallest
    ones that between them touch it."""
    from shapely.geometry import box, shape

    target = box(west, south, east, north)
    found = []
    for feat in index.get("features", []):
        props = feat.get("properties") or {}
        url = (props.get("urls") or {}).get("pbf")
        geom = feat.get("geometry")
        if not url or not geom:
            continue
        try:
            poly = shape(geom)
        except (ValueError, TypeError):
            continue
        if poly.intersects(target):
            found.append({"id": props.get("id", ""), "name": props.get("name", ""),
                          "parent": props.get("parent"), "url": url,
                          "area": poly.area, "covers": poly.buffer(0).covers(target)})
    if not found:
        return []
    covering = [r for r in found if r["covers"]]
    if covering:
        return [min(covering, key=lambda r: r["area"])]
    ids = {r["id"] for r in found}
    parents = {r["parent"] for r in found}
    leaves = [r for r in found if r["id"] not in parents]
    pick = leaves or found
    pick.sort(key=lambda r: r["area"])
    return pick[:MAX_REGIONS] if len(pick) <= MAX_REGIONS else []


# ---- the download -------------------------------------------------------------------

def _download(region: dict, say, should_stop) -> str:
    """The extract on disk, downloaded if there is none or it is two weeks old.
    A stale copy is used when Geofabrik cannot be reached."""
    os.makedirs(cache_dir(), exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", region["id"] or region["name"])
    path = os.path.join(cache_dir(), f"{safe}.osm.pbf")
    have = os.path.exists(path)
    if have and time.time() - os.path.getmtime(path) < EXTRACT_MAX_AGE_S:
        return path
    headers = dict(HEADERS)
    if have:
        headers["If-Modified-Since"] = time.strftime(
            "%a, %d %b %Y %H:%M:%S GMT", time.gmtime(os.path.getmtime(path)))
    try:
        r = requests.get(region["url"], headers=headers, stream=True,
                         timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S))
        if r.status_code == 304 and have:
            os.utime(path)               # checked: good for another two weeks
            return path
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        part = path + ".part"
        got = 0
        with open(part, "wb") as f:
            for block in r.iter_content(CHUNK):
                knoxstop.check(should_stop, "the download")
                f.write(block)
                got += len(block)
                mb = got // (1 << 20)
                say(min(99, int(100 * got / total)) if total else 0,
                    f"downloading the {region['name']} extract from Geofabrik, "
                    f"{mb} of {total // (1 << 20)} MB" if total else
                    f"downloading the {region['name']} extract from Geofabrik, {mb} MB")
        if total and got != total:
            raise OSError(f"the download stopped at {got} of {total} bytes")
        os.replace(part, path)
        return path
    except knoxstop.Stopped:
        raise
    except (requests.RequestException, OSError) as exc:
        if have:
            return path
        raise ExtractUnavailable(
            f"could not download the {region['name']} extract ({exc})") from None


# ---- reading it ---------------------------------------------------------------------

def _overlaps(b, south, west, north, east) -> bool:
    return not (b[2] < south or b[0] > north or b[3] < west or b[1] > east)


def _line_bounds(hex_wkb: str) -> tuple[float, float, float, float]:
    """Bounds of the 2D LineString produced by osmium's WKBFactory.

    GEOS decoding a hex string for every distant way dominated a regional
    scan. Decode hex in C first; short lines need only four extrema, while
    long ones are faster in GEOS's binary reader. Neither creates point dicts.
    """
    data = bytes.fromhex(hex_wkb)
    if len(data) < 9 or data[0] not in (0, 1):
        raise ValueError("invalid WKB LineString")
    order = "<" if data[0] else ">"
    kind, count = struct.unpack_from(order + "II", data, 1)
    if kind != 2 or not count or len(data) != 9 + count * 16:
        raise ValueError("expected a 2D WKB LineString")
    if count > 64:
        return from_wkb(data).bounds
    points = struct.unpack_from(f"{order}{count * 2}d", data, 9)
    xs, ys = points[::2], points[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def _read(path: str, filters: list[Filter], bbox, say, should_stop) -> list[dict]:
    """The elements of one extract that the filters want and that touch the box,
    as Overpass's `out geom` writes them."""
    import osmium

    south, west, north, east = bbox
    big = os.path.getsize(path) > BIG_EXTRACT_BYTES
    index_file = None
    if big:
        index_file = tempfile.NamedTemporaryFile(
            dir=cache_dir(), suffix=".nodes", delete=False)
        index_file.close()
        locations = f"sparse_file_array,{index_file.name}"
    else:
        locations = "flex_mem"

    elements: list[dict] = []
    try:
        keys = sorted({key for f in filters for key, _want in f.tests})
        factory = osmium.geom.WKBFactory()
        last_report = time.monotonic()

        def heartbeat(note):
            nonlocal last_report
            knoxstop.check(should_stop, "the download")
            now = time.monotonic()
            if now - last_report >= 1:
                # Object counts are not percentages of a compressed PBF.
                # The old estimate saturated at 70 (71 in the UI) and then
                # looked frozen for the rest of a hundred-million-node scan.
                say(None, note)
                last_report = now

        # 1. The relations, which come last in the file and are read on their
        # own: which ones the filters want, and which ways they are made of.
        say(None, "reading the relations")
        relations: dict[int, dict] = {}
        member_of: dict[int, list[int]] = {}
        for i, rel in enumerate(osmium.FileProcessor(path, osmium.osm.RELATION)
                                .with_filter(osmium.filter.KeyFilter(*keys))):
            if i % 20000 == 0:
                knoxstop.check(should_stop, "the download")
            tags = dict(rel.tags)
            if not wanted(filters, "relation", tags):
                continue
            ways = [(m.ref, m.role) for m in rel.members if m.type == "w"]
            if not ways:
                continue
            relations[rel.id] = {"tags": tags, "members": ways}
            for ref, _role in ways:
                member_of.setdefault(ref, []).append(rel.id)

        # 2. Nodes and ways, with their places. A way is kept when it is wanted
        # and touches the box; a way a wanted relation is made of is kept for
        # the relation when it touches the box (the rest are fetched below if
        # the relation turns out to).
        say(None, "reading the map data")
        geometry: dict[int, list] = {}
        touches: set[int] = set()
        for i, obj in enumerate(osmium.FileProcessor(path, osmium.osm.NODE | osmium.osm.WAY)
                                .with_locations(locations)
                                .with_filter(osmium.filter.KeyFilter(*keys).enable_for(osmium.osm.NODE))):
            if i % 1000 == 0:
                heartbeat(f"reading the map data: {i:,} tagged nodes and ways checked")
            if obj.is_node():
                if not obj.tags or not (south <= obj.location.lat <= north
                                        and west <= obj.location.lon <= east):
                    continue
                if wanted(filters, "node", obj.tags):
                    elements.append({"type": "node", "id": obj.id,
                                     "lat": obj.location.lat, "lon": obj.location.lon,
                                     "tags": {t.k: t.v for t in obj.tags}})
                continue
            in_relation = obj.id in member_of
            if not obj.tags and not in_relation:
                continue
            # Reject distant ways in native code. Building a Python dict for
            # every vertex of every road/forest in the entire region used to
            # dominate this pass, even for a map of a few streets.
            try:
                min_lon, min_lat, max_lon, max_lat = _line_bounds(factory.create_linestring(obj))
            except (RuntimeError, ValueError):
                pass  # incomplete node locations: preserve the old fallback
            else:
                if not _overlaps((min_lat, min_lon, max_lat, max_lon), south, west, north, east):
                    continue
            tags = dict(obj.tags)
            own = wanted(filters, "way", tags) if tags else False
            if not own and not in_relation:
                continue
            pts, lo_la, lo_lo, hi_la, hi_lo = [], 90.0, 180.0, -90.0, -180.0
            for n in obj.nodes:
                if not n.location.valid():
                    continue
                la, lo = n.location.lat, n.location.lon
                pts.append({"lat": la, "lon": lo})
                lo_la = min(lo_la, la)
                hi_la = max(hi_la, la)
                lo_lo = min(lo_lo, lo)
                hi_lo = max(hi_lo, lo)
            if not pts or not _overlaps((lo_la, lo_lo, hi_la, hi_lo), south, west, north, east):
                continue
            if own:
                elements.append({"type": "way", "id": obj.id,
                                 "tags": tags, "geometry": pts})
            if in_relation:
                touches.add(obj.id)
                geometry[obj.id] = pts

        # 3. The relations that touch the box, with every member way in full:
        # the ones outside the box were not kept above.
        chosen = {rid for ref in touches for rid in member_of[ref]}
        missing = {ref for rid in chosen for ref, _r in relations[rid]["members"]
                   if ref not in geometry}
        if missing:
            say(None, "reading the rest of the larger areas")
            # Nodes are read too, because the locations are built from them.
            for i, way in enumerate(osmium.FileProcessor(path, osmium.osm.NODE | osmium.osm.WAY)
                                    .with_locations(locations)
                                    .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
                                    .with_filter(osmium.filter.IdFilter(missing))):
                if i % 1000 == 0:
                    knoxstop.check(should_stop, "the download")
                geometry[way.id] = [{"lat": n.location.lat, "lon": n.location.lon}
                                    for n in way.nodes if n.location.valid()]
                missing.discard(way.id)
                if not missing:
                    break
        for rid in sorted(chosen):
            rel = relations[rid]
            members = [{"type": "way", "ref": ref, "role": role, "geometry": geometry[ref]}
                       for ref, role in rel["members"] if geometry.get(ref)]
            if members:
                elements.append({"type": "relation", "id": rid, "tags": rel["tags"],
                                 "members": members})
    finally:
        if index_file is not None:
            try:
                os.remove(index_file.name)
            except OSError:
                pass
    return elements


def elements(south: float, west: float, north: float, east: float, filters=None,
             progress=None, should_stop=None, regions=None) -> list[dict]:
    """Everything the filters want inside the box, from the extract(s) that cover
    it - what Overpass would have answered with, as its JSON elements."""
    from generator import osm

    if not available():
        raise ExtractUnavailable("pyosmium is not installed (pip install osmium)")
    for name, value, limit in (("south", south, 90.0), ("north", north, 90.0),
                               ("west", west, 180.0), ("east", east, 180.0)):
        if not -limit <= value <= limit:
            raise osm.OverpassError(f"{name}={value:g} is outside ±{limit:g}.")
    filters = parse_filters(filters if filters is not None else osm.OVERPASS_FILTERS)

    def say(pct: int | None, note: str) -> None:
        # File scans have no known object count; total=0 asks the UI for an
        # activity indicator instead of an invented completion percentage.
        osm._say(progress, pct + 1 if pct is not None else 0,
                 100 if pct is not None else 0, note)

    if regions is None:
        say(None, "finding the OpenStreetMap extract that covers this place")
        regions = regions_for(south, west, north, east, _index())
    if not regions:
        raise ExtractUnavailable("no Geofabrik extract covers this place")
    out: dict[tuple[str, int], dict] = {}
    for region in regions:
        path = _download(region, say, should_stop)
        say(None, f"reading the {region['name']} extract")
        for el in _read(path, filters, (south, west, north, east), say, should_stop):
            out[(el["type"], el["id"])] = el
    return list(out.values())


def features(south: float, west: float, north: float, east: float,
             progress=None, should_stop=None) -> list:
    """OSMFeatures for the box, read from an extract (see the module docstring)."""
    from generator import osm
    return osm._parse({"elements": elements(south, west, north, east,
                                            progress=progress, should_stop=should_stop)})
