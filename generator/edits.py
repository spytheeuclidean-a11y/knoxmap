"""Changes to the features a map was built from, kept as a list of changes.

A generated map is a reading of OpenStreetMap, and a reading is sometimes
wrong: a shed the survey calls a house, a road that runs through where the
mapper wants a square, a lake drawn round the wrong side of an island. Until
now the only answer was to accept it, because the features came down from
Overpass and went straight into the render.

This holds what the mapper changed about them. Three kinds of change, each
keyed by the feature's own OSM id:

    removed  ids that are left out of the map altogether
    moved    ids whose shape is replaced, as [(lat, lon), ...]
    tags     ids whose tags are added to or overwritten

They are kept as changes rather than as a copy of the edited features because
a town is a hundred thousand features and almost all of them are untouched.
The download stays exactly as it came, so an edit can be undone by dropping
its line, and a re-download does not throw the editing away.

Applying them is ordinary list work, so it costs nothing on a map with no
edits and does not need the features to be in any particular order.
"""
from __future__ import annotations

from dataclasses import replace

from .osm import OSMFeature

# What a page may set on an edited feature. The same list as a drawn one, plus
# the tags that say what a building is: retagging a house as a shop is one of
# the things this is for. Anything else is dropped - these tags reach
# `classify` and the renderer, and a page should not be able to set whatever
# it likes.
EDITABLE_TAGS = {
    "building", "building:levels", "shop", "amenity", "leisure", "landuse",
    "natural", "highway", "railway", "waterway", "barrier", "name", "width",
    "bridge", "tunnel", "oneway", "layer", "surface", "area",
}


def empty() -> dict:
    return {"removed": [], "moved": {}, "tags": {}}


def clean(raw: dict | None) -> dict:
    """An edit list from untrusted input, with anything unusable left out."""
    raw = raw if isinstance(raw, dict) else {}
    out = empty()
    for value in raw.get("removed") or []:
        try:
            out["removed"].append(int(value))
        except (TypeError, ValueError):
            continue
    for key, ring in (raw.get("moved") or {}).items():
        try:
            osm_id = int(key)
        except (TypeError, ValueError):
            continue
        points = []
        for point in ring or []:
            try:
                lat, lon = float(point[0]), float(point[1])
            except (TypeError, ValueError, IndexError):
                points = []
                break
            points.append((lat, lon))
        # One point is not a way and two is not an area; either way there is
        # nothing to replace the original with.
        if len(points) >= 2:
            out["moved"][osm_id] = points
    for key, tags in (raw.get("tags") or {}).items():
        try:
            osm_id = int(key)
        except (TypeError, ValueError):
            continue
        kept = {str(k): str(v) for k, v in (tags or {}).items()
                if k in EDITABLE_TAGS and v not in (None, "")}
        if kept:
            out["tags"][osm_id] = kept
    return out


def count(edits: dict | None) -> int:
    edits = edits or {}
    return (len(edits.get("removed") or [])
            + len(edits.get("moved") or {})
            + len(edits.get("tags") or {}))


def apply(features: list[OSMFeature], edits: dict | None) -> tuple[list, dict]:
    """The features as the mapper wants them, and what was actually used.

    What comes back is a new list; the features passed in are not touched, so
    the cached download stays the download.
    """
    edits = clean(edits)
    removed = set(edits["removed"])
    moved, tags = edits["moved"], edits["tags"]
    if not removed and not moved and not tags:
        return list(features), {"removed": 0, "moved": 0, "tags": 0}

    used = {"removed": 0, "moved": 0, "tags": 0}
    out = []
    for feat in features:
        if feat.osm_id in removed:
            used["removed"] += 1
            continue
        ring = moved.get(feat.osm_id)
        new_tags = tags.get(feat.osm_id)
        if ring is None and new_tags is None:
            out.append(feat)
            continue
        changed = feat
        if ring is not None:
            # A way that was closed stays closed: an area whose ring is left
            # open is not an area any more, and would be painted as a line.
            points = list(ring)
            was_closed = (len(feat.geometry) > 2
                          and feat.geometry[0] == feat.geometry[-1])
            if was_closed and points[0] != points[-1]:
                points.append(points[0])
            changed = replace(changed, geometry=points)
            used["moved"] += 1
        if new_tags is not None:
            changed = replace(changed, tags={**feat.tags, **new_tags})
            used["tags"] += 1
        out.append(changed)
    return out, used


def as_geojson(features: list[OSMFeature], bbox=None, limit: int = 0) -> dict:
    """Features as GeoJSON for the window to edit, each carrying its own id.

    `bbox` is (south, west, north, east): only what touches it is sent, which
    is what keeps a town-sized map editable - a city is a hundred thousand
    features and a page cannot hold them. `limit` caps how many come back,
    largest first, so what arrives is what is worth editing.
    """
    out = []
    for feat in features:
        if feat.kind != "way" or len(feat.geometry) < 2:
            continue
        lats = [p[0] for p in feat.geometry]
        lons = [p[1] for p in feat.geometry]
        if bbox is not None:
            south, west, north, east = bbox
            if max(lats) < south or min(lats) > north:
                continue
            if max(lons) < west or min(lons) > east:
                continue
        closed = len(feat.geometry) > 2 and feat.geometry[0] == feat.geometry[-1]
        span = (max(lats) - min(lats)) * (max(lons) - min(lons))
        ring = [[lon, lat] for lat, lon in feat.geometry]
        out.append((span, {
            "type": "Feature",
            "id": feat.osm_id,
            "properties": {"osm_id": feat.osm_id, "tags": dict(feat.tags)},
            "geometry": ({"type": "Polygon", "coordinates": [ring]} if closed
                         else {"type": "LineString", "coordinates": ring}),
        }))
    total = len(out)
    if limit and total > limit:
        out.sort(key=lambda row: -row[0])
        out = out[:limit]
    return {"type": "FeatureCollection",
            "features": [row[1] for row in out],
            "total": total, "shown": len(out)}
