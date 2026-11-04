"""Natural Earth 1:110m context: country, coastline fallback, place labels.

Public domain (CC0), so the small themes ship cached on demand. This is the
one layer that needs no dependency beyond shapely, so it is the reference
implementation of the DatasetSource contract.

OSM is the source of truth wherever it has the feature; this only fills gaps:
a country/region for regional defaults, a coastline where Overpass truncated
it at the bbox edge, and names for the paper map where OSM has no place tag.
"""
from __future__ import annotations

import json
import logging

from . import DatasetSource, Layer
from . import cache

log = logging.getLogger("knoxdata.natural_earth")

BASE = ("https://raw.githubusercontent.com/martynafford/"
        "natural-earth-geojson/master")
VERSION = "110m-2024"
TTL_DAYS = 30

# theme -> path under BASE. Only what a map actually reads.
THEMES = {
    "countries": "110m/cultural/ne_110m_admin_0_countries.json",
    "places": "110m/cultural/ne_110m_populated_places.json",
    "coastline": "110m/physical/ne_110m_coastline.json",
}

# Parsed geometry, kept for the process's life: a rebuild is one load.
_LOADED: dict = {}


def _url(theme: str) -> str:
    return f"{BASE}/{THEMES[theme]}"


def _file(theme: str):
    return cache.DATASET_DIR / "natural_earth" / f"ne_{VERSION.split('-')[0]}_{theme}.json"


def _load(theme: str):
    """The theme's GeoJSON, from cache or download, parsed once per process."""
    if theme in _LOADED:
        return _LOADED[theme]
    path = _file(theme)
    if not cache.fresh(path, TTL_DAYS):
        try:
            cache.download(_url(theme), path)
        except Exception as exc:            # noqa: BLE001 - caller degrades
            log.info("knoxdata: Natural Earth %s unavailable - %s", theme, exc)
            if not path.exists():
                return None
    payload = cache.read_json(path)
    _LOADED[theme] = payload
    return payload


def _geoms(theme: str):
    """[(shapely geometry, properties)] for a theme, or []."""
    from shapely.geometry import shape

    payload = _load(theme)
    out = []
    for feat in (payload or {}).get("features", []):
        try:
            geom = shape(feat["geometry"])
        except Exception:                   # noqa: BLE001 - a broken feature is skipped
            continue
        if not geom.is_empty:
            out.append((geom, feat.get("properties") or {}))
    return out


def country_at(lat: float, lon: float) -> dict | None:
    """The country containing a point, as {iso, name}, or None."""
    from shapely.geometry import Point

    here = Point(lon, lat)
    for geom, props in _geoms("countries"):
        if geom.contains(here):
            iso = props.get("ISO_A2") or props.get("WB_A2") or ""
            return {"iso": str(iso).upper() if iso else "",
                    "name": str(props.get("NAME") or props.get("ADMIN") or "")}
    return None


def places_in(bbox, limit: int = 200) -> list[dict]:
    """Populated places inside the box, biggest first."""
    from shapely.geometry import Point, box

    s, w, n, e = bbox
    area = box(w, s, e, n)
    found = []
    for geom, props in _geoms("places"):
        if not isinstance(geom, Point) or geom.is_empty:
            continue
        if area.contains(geom):
            found.append({"name": str(props.get("NAME") or ""),
                          "lat": float(props.get("LATITUDE") or geom.y),
                          "lon": float(props.get("LONGITUDE") or geom.x),
                          "pop": int(props.get("POP_MAX") or 0)})
    found.sort(key=lambda p: -p["pop"])
    return [p for p in found if p["name"]][:limit]


def coastline_in(bbox) -> list:
    """Coastline clipped to the box, as shapely geometries."""
    from shapely.geometry import box

    s, w, n, e = bbox
    clip = box(w, s, e, n)
    out = []
    for geom, _props in _geoms("coastline"):
        try:
            piece = geom.intersection(clip)
        except Exception:                   # noqa: BLE001
            continue
        if not piece.is_empty:
            out.append(piece)
    return out


class NaturalEarth(DatasetSource):
    name = "natural_earth"
    license = "CC0 1.0 (public domain)"
    attribution = "Natural Earth (public domain)"
    setting = "ne_context"
    off_values = ("off", "", 0, None, False)

    def available(self, bbox) -> bool:
        return True          # bounded, public, cached; download failures degrade

    def cached(self, bbox) -> bool:
        return all(_file(theme).exists() for theme in THEMES)

    def why_unavailable(self) -> str:
        return "Natural Earth themes could not be read."

    def fetch(self, bbox, cache_dir=None, progress_cb=None):
        for theme in THEMES:
            _load(theme)
        return cache.DATASET_DIR / "natural_earth"

    def build_layer(self, ctx) -> Layer:
        s, w, n, e = ctx.bbox
        center = ((s + n) / 2.0, (w + e) / 2.0)
        return Layer(country=country_at(*center),
                     places=places_in(ctx.bbox),
                     coastline=coastline_in(ctx.bbox))

    def apply(self, ctx, layer) -> None:
        country = layer.data.get("country") if layer.data else None
        if country and country.get("iso"):
            ctx.region = country["iso"]
            ctx.report.setdefault("natural_earth", {})["country"] = country
        places = layer.data.get("places") or []
        # Labels only where OSM left a name blank; the caller decides that.
        for i, place in enumerate(places):
            ctx.labels[f"ne-place-{i}"] = place
        coast = layer.data.get("coastline") or []
        ctx.report.setdefault("natural_earth", {})["coastline_km"] = round(
            sum(getattr(g, "length", 0.0) for g in coast) * 111.0, 1)
