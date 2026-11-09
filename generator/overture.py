"""Buildings from Overture Maps, where OpenStreetMap has none.

OpenStreetMap is drawn by people, so how much of a town is on it depends on
who lives there and whether anyone has traced it. In a German town it is all
of it; in plenty of the world it is the high street and not much else, and a
map generated from it comes out as a few streets of buildings with empty land
where the rest of the town is.

Overture Maps publishes a buildings theme that is OpenStreetMap first and
machine-detected roofprints (Microsoft's and Google's) second, under the same
ODbL licence. Where OSM has the building, the two agree and this adds
nothing; where OSM is blank and somebody's model found a roof, it fills in.
Measured on two towns, the same size of box:

    Gifhorn, Germany   OSM 1,962 buildings   Overture adds    60  (3%)
    Urgup, Turkey      OSM   473 buildings   Overture adds   761 (62%)

The German ones are mostly sheds and garages, 38 m2 at the median. The
Turkish ones are houses, 87 m2 at the median, and they nearly treble the
town. So this is off by default and worth turning on exactly where a mapper
can see their town is half missing - which they can, from the preview.

`_houses_from_addresses` in the renderer already does a smaller version of
this from OSM's own address points, and keeps doing it: it catches the houses
somebody numbered but never drew. That was 22 houses in Gifhorn and 20 in
Urgup, so it is not an alternative to this, and the two do not collide -
addresses are filled in after, and only where nothing stands yet.

The data is GeoParquet on S3 and there is no HTTP API for a bounding box, so
this needs DuckDB, which is not a small install and is therefore optional.
Without it everything else works and the setting says why. One fetch of a
town takes two to three minutes, nearly all of it DuckDB reading the metadata
of every file in the theme to find the handful that cover the box, so the
answer is cached beside the map like the Overpass one.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import threading

from .osm import OSMFeature

# The release this was written against. Overture publishes monthly and keeps
# the old ones, so pinning means a map built today is the same map next year;
# KNOXMAP_OVERTURE_RELEASE moves it without a new KnoxMap.
RELEASE = "2026-08-19.0"
REGION = "us-west-2"
BUCKET = "overturemaps-us-west-2"

# Overture's ids are strings and OSM's are numbers, so a building from here
# gets a number of its own that no OSM way can have.
FIRST_ID = -1_000_000_000

# Smaller than this is a sliver, a bin store or an artefact of whatever traced
# it, not something worth standing on a map. The generator turns anything up
# to 30 m2 into a shed already; this is only about what is not a building at
# all. In Urgup 71 of the 761 new ones were under 20 m2.
MIN_AREA_M2 = 10.0

# How long to let one query run before giving up on it.
TIMEOUT_S = 15 * 60


def available() -> bool:
    """Whether this PC can fetch from Overture at all."""
    try:
        import duckdb  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure means "not available"
        return False
    return True


def why_unavailable() -> str:
    """What to tell somebody who asked for it and has not got it."""
    return ("Filling gaps from Overture Maps needs DuckDB, which reads the "
            "map data where Overture publishes it. Install it with "
            "'.venv/bin/python -m pip install duckdb' (or "
            '".venv\\Scripts\\python -m pip install duckdb" on Windows) and '
            "start KnoxMap again. Everything else works without it.")


def release() -> str:
    return os.environ.get("KNOXMAP_OVERTURE_RELEASE") or RELEASE


def cache_path(output_dir: str, map_name: str) -> str:
    return os.path.join(output_dir, f"{map_name}_overture.json.gz")


def save_cache(path: str, bbox: tuple[float, float, float, float],
               rows: list[dict]) -> None:
    payload = {"release": release(), "bbox": list(bbox), "buildings": rows}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)


def load_cache(path: str,
               bbox: tuple[float, float, float, float]) -> list[dict] | None:
    """What was fetched for exactly this box and release, or None."""
    if not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    if payload.get("release") != release():
        return None
    kept = payload.get("bbox")
    if not (isinstance(kept, list) and len(kept) == 4
            and all(abs(a - b) < 1e-9 for a, b in zip(kept, bbox))):
        return None
    found = payload.get("buildings")
    return found if isinstance(found, list) else None


def _query(south: float, west: float, north: float, east: float) -> str:
    # Overlapping, not contained: a building on the edge of the box is half
    # inside the map and has to be built, or the map has a bite out of it.
    url = (f"s3://{BUCKET}/release/{release()}"
           f"/theme=buildings/type=building/*")
    return f"""
        SELECT id, height, num_floors, class, ST_AsGeoJSON(geometry) AS gj
        FROM read_parquet('{url}')
        WHERE bbox.xmin <= {east} AND bbox.xmax >= {west}
          AND bbox.ymin <= {north} AND bbox.ymax >= {south}
    """


def fetch(south: float, west: float, north: float, east: float,
          should_stop=None) -> list[dict]:
    """Every Overture building touching this box.

    Runs on a thread of its own so the window's Stop button still works: a
    query is minutes long and DuckDB will not come back in the middle of one
    unless it is interrupted.
    """
    import duckdb

    con = duckdb.connect()
    try:
        con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
        con.execute(f"SET s3_region='{REGION}';")

        out: dict = {}

        def run() -> None:
            try:
                out["rows"] = con.execute(_query(south, west, north, east)).fetchall()
            except Exception as exc:  # noqa: BLE001 - reported on the main thread
                out["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        waited = 0.0
        while worker.is_alive():
            worker.join(0.5)
            waited += 0.5
            if waited > TIMEOUT_S:
                con.interrupt()
                worker.join(30)
                raise TimeoutError(
                    f"Overture did not answer within {TIMEOUT_S // 60} minutes.")
            if should_stop is not None and should_stop():
                con.interrupt()
                worker.join(30)
                import knoxstop
                raise knoxstop.Stopped("the Overture download")
        if "error" in out:
            raise RuntimeError(f"Overture query failed: {out['error']}")
    finally:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass

    rows = []
    for ident, height, floors, cls, gj in out.get("rows", []):
        try:
            shape = json.loads(gj)
        except (TypeError, ValueError):
            continue
        rows.append({"id": ident, "height": height, "levels": floors,
                     "class": cls, "geometry": shape})
    return rows


def _rings(shape: dict) -> list[list[tuple[float, float]]]:
    """The outer ring of a polygon, or of each part of a multipolygon, as
    (lat, lon) the way an OSM way carries it."""
    kind = shape.get("type")
    if kind == "Polygon":
        parts = [shape.get("coordinates") or []]
    elif kind == "MultiPolygon":
        parts = shape.get("coordinates") or []
    else:
        return []
    out = []
    for part in parts:
        if not part:
            continue
        ring = [(float(lat), float(lon)) for lon, lat in part[0]
                if lon is not None and lat is not None]
        if len(ring) >= 3:
            out.append(ring)
    return out


def _area_m2(ring: list[tuple[float, float]]) -> float:
    """The shoelace area of a small ring of (lat, lon), in square metres."""
    if len(ring) < 3:
        return 0.0
    lat0 = sum(p[0] for p in ring) / len(ring)
    mx = 111320.0 * math.cos(math.radians(lat0))
    xy = [(lon * mx, lat * 111320.0) for lat, lon in ring]
    total = 0.0
    for i in range(len(xy)):
        x1, y1 = xy[i]
        x2, y2 = xy[(i + 1) % len(xy)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def to_features(rows: list[dict]) -> list[OSMFeature]:
    """Overture buildings as the features the rest of KnoxMap already reads.

    `class` carries OpenStreetMap's own building values - house, apartments,
    barn, church, detached - so it goes straight into the building tag and
    everything downstream classifies it exactly as it would a mapped one.
    The machine-detected ones have no class at all, and arrive as a plain
    building=yes: a footprint, which is what they are.
    """
    feats = []
    ident = FIRST_ID
    for row in rows:
        for ring in _rings(row.get("geometry") or {}):
            if _area_m2(ring) < MIN_AREA_M2:
                continue
            tags = {"building": (row.get("class") or "yes")}
            levels = row.get("levels")
            if isinstance(levels, (int, float)) and 0 < levels < 100:
                tags["building:levels"] = str(int(levels))
            height = row.get("height")
            if isinstance(height, (int, float)) and 0 < height < 500:
                tags["height"] = f"{float(height):g}"
            feats.append(OSMFeature(osm_id=ident, kind="way", tags=tags,
                                    geometry=ring))
            ident -= 1
    return feats


def only_missing(candidates: list[OSMFeature],
                 features: list[OSMFeature]) -> list[OSMFeature]:
    """The candidates that do not stand where a building already stands.

    A centre inside an existing outline is the test, not an overlap: Overture
    and OSM trace the same building slightly differently, and anything that
    asks how much two outlines share has to be told how much counts. A roof
    whose middle is inside a mapped building is that building.
    """
    from shapely.geometry import Polygon
    from shapely.strtree import STRtree

    existing = []
    for f in features:
        if not (f.tags.get("building") or "").strip():
            continue
        rings = ([f.geometry] if f.kind == "way"
                 else [r for r in (f.geometry or []) if isinstance(r, list)])
        for ring in rings:
            if not ring or len(ring) < 3:
                continue
            try:
                poly = Polygon([(lon, lat) for lat, lon in ring])
                if not poly.is_valid:
                    poly = poly.buffer(0)
            except Exception:  # noqa: BLE001 - a ring shapely rejects is no test
                continue
            if not poly.is_empty and poly.area > 0:
                existing.append(poly)
    if not existing:
        return list(candidates)

    tree = STRtree(existing)
    kept = []
    for cand in candidates:
        try:
            here = Polygon([(lon, lat) for lat, lon in cand.geometry])
            middle = here.centroid
            if middle.is_empty:
                here = here.buffer(0)
                middle = here.centroid
        except Exception:  # noqa: BLE001
            continue
        if middle.is_empty:
            continue
        if len(tree.query(middle, predicate="within")) > 0:
            continue
        kept.append(cand)
    return kept


def add_missing(features: list[OSMFeature],
                bbox: tuple[float, float, float, float],
                output_dir: str, map_name: str,
                should_stop=None) -> tuple[list[OSMFeature], dict]:
    """`features`, plus a building wherever Overture has one and OSM does not.

    Returns the new list and what happened, for the window to report. Never
    raises for want of Overture: a map that cannot reach it is the map OSM
    alone makes, which is the map every earlier KnoxMap made.
    """
    south, west, north, east = bbox
    stats = {"available": available(), "fetched": 0, "added": 0, "cached": False}

    # The cache first, and only then DuckDB. Fetching is the one thing that
    # needs it: a map already fetched re-renders on any PC, and a map folder
    # handed to somebody else carries its buildings with it.
    path = cache_path(output_dir, map_name)
    rows = load_cache(path, bbox)
    if rows is not None:
        stats["cached"] = True
    else:
        if not stats["available"]:
            stats["why"] = why_unavailable()
            return features, stats
        rows = fetch(south, west, north, east, should_stop=should_stop)
        try:
            save_cache(path, bbox, rows)
        except OSError:
            pass          # a fetch that cannot be cached is still a fetch
    stats["fetched"] = len(rows)

    extra = only_missing(to_features(rows), features)
    stats["added"] = len(extra)
    return (features + extra) if extra else features, stats
