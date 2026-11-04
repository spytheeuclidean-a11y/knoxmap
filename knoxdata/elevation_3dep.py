"""USGS 3DEP elevation (US only): gentle real relief within the z budget.

Default path is the 10 m (1/3 arc-second) DEM; raw lidar point clouds are an
advanced mode this module does not attempt. The layer reports why when
rasterio is absent or the area is outside 3DEP coverage, and the map is built
flat as before. Grading is left to the pipeline: this supplies metres per tile.
"""
from __future__ import annotations

import logging
import os

from . import DatasetSource, Layer
from . import cache

log = logging.getLogger("knoxdata.elevation_3dep")

# The National Map staged-product layout; overridable because it moves.
BASE = os.environ.get(
    "KNOXMAP_3DEP_URL",
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current")
TTL_DAYS = 3650


def _rasterio():
    try:
        import rasterio  # noqa: F401
        return True
    except Exception:           # noqa: BLE001
        return False


def in_coverage(bbox) -> bool:
    """CONUS, Alaska, Hawaii, Puerto Rico and the US Virgin Islands."""
    s, w, n, e = bbox
    conus = (w <= -66 and e >= -125 and s <= 50 and n >= 24)
    alaska = (w <= -129 and e >= -170 and s <= 72 and n >= 51)
    islands = (w <= -64 and e >= -161 and s <= 23 and n >= 17)
    return conus or alaska or islands


def _cell(lat: float, lon: float) -> str:
    ns = "n" + str(int((51 - lat) // 1)).zfill(2)
    ew = "w" + str(int((lon + 180) // 1)).zfill(3)
    return ns + ew


def tile_name(lat: float, lon: float) -> str:
    return f"USGS_13_{_cell(lat, lon)}.tif"


class Elevation3DEP(DatasetSource):
    name = "elevation_3dep"
    license = "USGS 3DEP (public domain)"
    attribution = "USGS 3DEP elevation (public domain)"
    setting = "elevation"
    off_values = ("flat", "off", "", None, False)

    def available(self, bbox) -> bool:
        return _rasterio() and in_coverage(bbox)

    def why_unavailable(self) -> str:
        if not _rasterio():
            return "rasterio is not installed (pip install rasterio)"
        return "the area is outside USGS 3DEP coverage; terrain stays flat."

    def cached(self, bbox) -> bool:
        s, w, n, e = bbox
        return (cache.DATASET_DIR / "3dep"
                / tile_name((s + n) / 2.0, (w + e) / 2.0)).exists()

    def fetch(self, bbox, cache_dir=None, progress_cb=None):
        root = cache.DATASET_DIR / "3dep"
        s, w, n, e = bbox
        lat = (s + n) / 2.0
        lon = (w + e) / 2.0
        name = tile_name(lat, lon)
        path = root / name
        if not cache.fresh(path, TTL_DAYS):
            folder = _cell(lat, lon)
            cache.download(f"{BASE}/{folder}/{name}", path, progress_cb=progress_cb)
        return path

    def build_layer(self, ctx) -> Layer:
        """One elevation sample per map tile, normalised and clamped."""
        import numpy as np
        import rasterio
        from rasterio.windows import from_bounds

        path = self.fetch(ctx.bbox)
        proj = getattr(ctx, "proj", None)
        width = getattr(proj, "width", 256)
        height = getattr(proj, "height", 256)
        s, w, n, e = ctx.bbox
        with rasterio.open(path) as src:
            data = src.read(1, window=from_bounds(w, s, e, n, src.transform),
                            out_shape=(height, width), resampling=rasterio.enums.Resampling.average)
        metres = np.asarray(data, dtype="float32")
        finite = metres[np.isfinite(metres)]
        if finite.size == 0:
            return Layer(metres=None)
        lo, hi = float(finite.min()), float(finite.max())
        max_relief = int(getattr(ctx.settings, "max_relief", 4) or 4)
        if hi - lo > 0:
            metres = (metres - lo) / (hi - lo) * max_relief
        return Layer(metres=metres, span=(lo, hi))

    def apply(self, ctx, layer) -> None:
        ctx.elevation = layer.data.get("metres")
        ctx.report.setdefault("elevation_3dep", {})["span_m"] = layer.data.get("span")
