"""NOAA U.S. Climate Normals: region-correct flavour (US only).

The tabular 1991-2020 collection is a GeoParquet of ~15k stations; the nearest
station (with inverse-distance weighting over the nearest three) gives a
compact profile. Needs pyarrow; without it the map keeps its default look and
one line says so.
"""
from __future__ import annotations

import logging
import math
import os

from . import DatasetSource, Layer
from . import cache

log = logging.getLogger("knoxdata.climate_normals")

BASE = os.environ.get(
    "KNOXMAP_NOAA_URL",
    "https://www.ncei.noaa.gov/data/oceans/archive/arc0216/0253808/2.2/data"
    "/0-data/parquet/normals-monthly-1991-2020.parquet")
VERSION = "1991-2020"
TTL_DAYS = 3650


def _pyarrow():
    try:
        import pyarrow.parquet  # noqa: F401
        return True
    except Exception:           # noqa: BLE001
        return False


def in_coverage(bbox) -> bool:
    s, w, n, e = bbox
    return w <= -65 and e >= -180 and s <= 72 and n >= 17


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def classify(precip_mm: float, jan_c: float) -> str:
    if precip_mm < 400:
        return "arid"
    if jan_c < -3:
        return "cold continental"
    if precip_mm > 1000:
        return "humid"
    return "temperate"


class ClimateNormals(DatasetSource):
    name = "climate_normals"
    license = "NOAA (public domain)"
    attribution = "NOAA U.S. Climate Normals 1991-2020 (public domain)"
    setting = "climate_flavor"
    off_values = ("off", "", 0, None, False)

    def available(self, bbox) -> bool:
        return _pyarrow() and in_coverage(bbox)

    def why_unavailable(self) -> str:
        if not _pyarrow():
            return "pyarrow is not installed (pip install pyarrow)"
        return "NOAA normals cover the United States only; default look kept."

    def cached(self, bbox) -> bool:
        return self._file().exists()

    def _file(self):
        return cache.DATASET_DIR / "noaa" / f"normals-monthly-{VERSION}.parquet"

    def fetch(self, bbox, cache_dir=None, progress_cb=None):
        path = self._file()
        if not cache.fresh(path, TTL_DAYS):
            cache.download(BASE, path, progress_cb=progress_cb)
        return path

    def build_layer(self, ctx) -> Layer:
        import pyarrow.parquet as pq

        path = self.fetch(ctx.bbox)
        table = pq.read_table(path)
        rows = table.to_pylist()
        s, w, n, e = ctx.bbox
        lat, lon = (s + n) / 2.0, (w + e) / 2.0
        def coord(row, *keys):
            for key in keys:
                if row.get(key) is not None:
                    try:
                        return float(row[key])
                    except (TypeError, ValueError):
                        continue
            return None

        by_station: dict[tuple[float, float], dict] = {}
        for row in rows:
            la = coord(row, "LATITUDE", "latitude", "lat")
            lo = coord(row, "LONGITUDE", "longitude", "lon")
            if la is None or lo is None:
                continue
            key = (round(la, 5), round(lo, 5))
            st = by_station.get(key)
            if st is None:
                st = dict(row)
                st["_precip_sum"] = 0.0
                st["_has_months"] = False
                by_station[key] = st
            month = coord(row, "month", "MONTH")
            if month is not None:
                st["_has_months"] = True
                m = int(round(month))
                tavg = coord(row, "MLY-TAVG-NORMAL", "tavg", "TAVG")
                if m == 1 and tavg is not None and st.get("JAN_MEAN_TMP") is None:
                    st["JAN_MEAN_TMP"] = tavg
                elif m == 7 and tavg is not None and st.get("JUL_MEAN_TMP") is None:
                    st["JUL_MEAN_TMP"] = tavg
                prcp = coord(row, "MLY-PRCP-NORMAL", "precip", "PRCP")
                if prcp is not None:
                    st["_precip_sum"] += prcp

        ranked = []
        for (la, lo), st in by_station.items():
            if st.get("_has_months") and st["_precip_sum"] > 0:
                st["MLY-PRCP-NORMAL"] = st["_precip_sum"]
            ranked.append((_haversine_m(lat, lon, la, lo), st))
        ranked.sort(key=lambda t: t[0])
        nearest = ranked[:3]
        if not nearest:
            return Layer(profile=None)
        weights = [1.0 / max(d, 1.0) for d, _ in nearest]
        total = sum(weights)

        def avg(*keys):
            value = 0.0
            for weight, (_d, row) in zip(weights, nearest):
                value += weight * float(coord(row, *keys) or 0.0)
            return value / total

        jan = avg("JAN_MEAN_TMP", "jan_mean_tmp", "MLY-TAVG-NORMAL")
        jul = avg("JUL_MEAN_TMP", "jul_mean_tmp", "MLY-TAVG-NORMAL")
        precip = avg("MLY-PRCP-NORMAL", "precip", "PRCP")
        profile = {"jan_c": round(jan, 1), "jul_c": round(jul, 1),
                   "precip_mm": round(precip, 0),
                   "class": classify(precip, jan), "version": VERSION}
        return Layer(profile=profile)

    def apply(self, ctx, layer) -> None:
        profile = layer.data.get("profile")
        if profile:
            ctx.climate = profile
            ctx.report.setdefault("climate_normals", {})["profile"] = profile
