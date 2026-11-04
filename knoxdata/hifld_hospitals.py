"""HIFLD hospitals: make generated hospitals match the real facilities (US).

The national file is small and updated weekly, so it is one dataset-wide
download on a 7-day TTL, indexed once per process. Matching prefers a name
match, then the nearest tagged hospital, then the nearest candidate building;
only the best tier is applied. See docs/DATASETS.md.
"""
from __future__ import annotations

import logging
import math
import os
import re

from . import DatasetSource, Layer
from . import cache

log = logging.getLogger("knoxdata.hifld")

# HIFLD publishes on ArcGIS Hub; the layer id can move, so this is overridable.
DEFAULT_URL = os.environ.get(
    "KNOXMAP_HIFLD_URL",
    "https://services1.arcgis.com/Hp6G80Pky0om7QvQ/arcgis/rest/services/"
    "Hospitals/FeatureServer/0/query"
    "?where=1%3D1&outFields=NAME,ADDRESS,CITY,STATE,TYPE,STATUS,BEDS,"
    "TTL_STAFF,HELIPAD,OWNER,LATITUDE,LONGITUDE&f=geojson&outSR=4326")

TTL_DAYS = 7
MATCH_M = 150.0
_VERSION = "hifld-2024"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()).strip()


def _tokens(text: str) -> set[str]:
    ignored = {"hospital", "medical", "center", "centre", "health", "the", "of"}
    return {w for w in _norm(text).split() if w and w not in ignored}


def name_score(a: str, b: str) -> float:
    """Jaccard overlap of the words that matter, 0..1."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _centroid(feature):
    """(lat, lon) centre of an OSM way's ring, or None."""
    ring = getattr(feature, "geometry", None) or []
    if not isinstance(ring, list) or len(ring) < 3:
        return None
    lat = sum(float(p[0]) for p in ring) / len(ring)
    lon = sum(float(p[1]) for p in ring) / len(ring)
    return lat, lon


def _passes(feature) -> bool:
    tags = getattr(feature, "tags", None) or {}
    return (tags.get("amenity") == "hospital"
            or tags.get("healthcare") == "hospital"
            or tags.get("building") == "hospital")


def _key(prop, *names):
    for name in names:
        if name in prop and prop[name] not in (None, ""):
            return prop[name]
    return None


class HIFLDHospitals(DatasetSource):
    name = "hifld_hospitals"
    license = "US Government Open Data (public domain)"
    attribution = "HIFLD Hospitals (US Government, public domain)"
    setting = "hospitals"
    off_values = ("off", "", "osm", None, False)

    def _file(self):
        return cache.DATASET_DIR / "hifld" / "hospitals.geojson"

    def available(self, bbox) -> bool:
        # US coverage only: CONUS, AK/HI/PR/VI are all in -180..-65, 17..72.
        s, w, n, e = bbox
        in_us = (w <= -65 and e >= -180 and s <= 72 and n >= 17)
        return in_us and (self._file().exists() or self._can_reach())

    @staticmethod
    def _can_reach() -> bool:
        return True          # fetch() degrades on its own; this only gates coverage

    def cached(self, bbox) -> bool:
        return self._file().exists()

    def why_unavailable(self) -> str:
        return "HIFLD covers the United States only, and the hospitals list is not cached."

    def fetch(self, bbox, cache_dir=None, progress_cb=None):
        path = self._file()
        if cache.fresh(path, TTL_DAYS):
            return path
        cache.download(DEFAULT_URL, path, progress_cb=progress_cb)
        return path

    def _rows(self):
        payload = cache.read_json(self._file())
        if payload is None:
            try:
                self.fetch(None)
            except Exception as exc:        # noqa: BLE001 - degrade, not die
                log.info("knoxdata: HIFLD fetch failed - %s", exc)
                return []
            payload = cache.read_json(self._file()) or {}
        rows = []
        for feat in payload.get("features", []):
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if geom.get("type") != "Point" or len(coords) < 2:
                lat = _key(props, "LATITUDE")
                lon = _key(props, "LONGITUDE")
            else:
                lon, lat = coords[0], coords[1]
            if lat is None or lon is None:
                continue
            rows.append({"name": str(_key(props, "NAME") or ""),
                         "lat": float(lat), "lon": float(lon),
                         "type": str(_key(props, "TYPE") or "").strip(),
                         "status": str(_key(props, "STATUS") or "").strip(),
                         "beds": int(float(_key(props, "BEDS") or 0)),
                         "staff": int(float(_key(props, "TTL_STAFF") or 0)),
                         "helipad": str(_key(props, "HELIPAD") or "").upper() == "Y"})
        return rows

    def build_layer(self, ctx) -> Layer:
        s, w, n, e = ctx.bbox
        inside = [r for r in self._rows()
                  if s <= r["lat"] <= n and w <= r["lon"] <= e]
        return Layer(rows=inside)

    def apply(self, ctx, layer) -> None:
        rows = layer.data.get("rows") or []
        candidates = [f for f in ctx.features
                      if getattr(f, "tags", None)
                      and (f.tags.get("building") or _passes(f))]
        matched = []
        for row in rows:
            best = None            # (tier, distance, feature)
            for feat in candidates:
                centre = _centroid(feat)
                if centre is None:
                    continue
                distance = _haversine_m(row["lat"], row["lon"], *centre)
                if distance > MATCH_M:
                    continue
                tags = getattr(feat, "tags", None) or {}
                score = name_score(row["name"], tags.get("name", ""))
                tier = 0 if score >= 0.5 else (1 if _passes(feat) else 2)
                if best is None or (tier, distance) < (best[0], best[1]):
                    best = (tier, distance, feat)
            if best is None:
                continue
            tier, _distance, feat = best
            feat.tags["name"] = row["name"] or feat.tags.get("name", "")
            feat.tags.setdefault("amenity", "hospital")
            feat.tags["healthcare"] = "hospital"
            # The numbers the building step reads (knoxbuild/hospitals.py).
            feat.tags["hifld_beds"] = str(row.get("beds", 0))
            feat.tags["hifld_staff"] = str(row.get("staff", 0))
            feat.tags["hifld_type"] = row.get("type", "")
            feat.tags["hifld_status"] = row.get("status", "")
            if row.get("helipad"):
                feat.tags["helipad"] = "yes"
            matched.append({"name": row["name"], "tier": tier,
                            "beds": row["beds"], "type": row["type"],
                            "status": row["status"]})
        ctx.report.setdefault("hifld_hospitals", {})["matched"] = matched
        ctx.report["hifld_hospitals"]["found"] = len(rows)
