"""ESA WorldCover 10 m land cover, for ground OSM leaves blank.

OSM polygons always win; this only fills tiles nothing else claimed. The
class -> behaviour table is data (data/worldcover_classes.json), not code.
Needs rasterio + numpy; without them the layer reports why and is skipped.
"""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path

from . import DatasetSource, Layer
from . import cache

log = logging.getLogger("knoxdata.worldcover")

TILE_DEG = 3
VERSION = "2021_v200"
BASE = os.environ.get(
    "KNOXMAP_WORLDCOVER_URL",
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map")
TTL_DAYS = 3650            # a published year does not change

_DATA = Path(__file__).with_name("data") / "worldcover_classes.json"


def classes() -> dict:
    with open(_DATA, encoding="utf-8") as fh:
        return json.load(fh)


def _corner(deg: float) -> str:
    deg = int(math.floor(deg / TILE_DEG) * TILE_DEG)
    return (f"N{deg:02d}" if deg >= 0 else f"S{-deg:02d}")


def _lon(deg: float) -> str:
    deg = int(math.floor(deg / TILE_DEG) * TILE_DEG)
    return (f"E{deg:03d}" if deg >= 0 else f"W{-deg:03d}")


def tile_names(bbox) -> list[str]:
    """The 3-degree WorldCover tiles a box touches, by their SW corner."""
    s, w, n, e = bbox
    names = []
    lat = math.floor(s / TILE_DEG) * TILE_DEG
    while lat <= math.floor(n / TILE_DEG) * TILE_DEG:
        lon = math.floor(w / TILE_DEG) * TILE_DEG
        while lon <= math.floor(e / TILE_DEG) * TILE_DEG:
            names.append(f"ESA_WorldCover_10m_{VERSION}_{_corner(lat)}{_lon(lon)}_Map.tif")
            lon += TILE_DEG
        lat += TILE_DEG
    return names


def _rasterio():
    try:
        import rasterio  # noqa: F401
        return True
    except Exception:           # noqa: BLE001
        return False


def _majority3(grid):
    """3x3 majority filter, to take the speckle out of a resampled 10 m grid."""
    import numpy as np

    if grid.size > 4_000_000:
        # ponytail: O(classes * pixels) is minutes on a 100 km map; skip the
        # filter there. Add a windowed/GPU pass if big maps need it.
        return grid
    padded = np.pad(grid, 1, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, (3, 3))
    codes = np.unique(grid)
    counts = np.stack([(windows == code).sum(axis=(-1, -2)) for code in codes])
    return codes[np.argmax(counts, axis=0)].astype(grid.dtype)


def suggest_preset(fractions: dict) -> str:
    """Rural/Town/Suburb/City from how much of the area is built up."""
    built = float(fractions.get("Built-up", 0.0) or 0.0)
    if built > 0.35:
        return "city"
    if built > 0.18:
        return "suburb"
    if built > 0.07:
        return "town"
    return "rural"


class WorldCover(DatasetSource):
    name = "worldcover"
    license = "CC-BY 4.0"
    attribution = "Contains modified Copernicus/ESA WorldCover data 2021"
    setting = "landcover"
    # "OpenStreetMap only" is off too: the ground OSM leaves blank stays grass
    # with KnoxMap's own scattered woods, as before WorldCover.
    off_values = ("off", "", "osm", None, False)

    def available(self, bbox) -> bool:
        s, w, n, e = bbox
        return (_rasterio() and -90 <= s < n <= 90 and -180 <= w < e <= 180)

    def why_unavailable(self) -> str:
        if not _rasterio():
            return "rasterio is not installed (pip install rasterio)"
        return "the area is outside WorldCover coverage."

    def cached(self, bbox) -> bool:
        root = cache.DATASET_DIR / "worldcover" / VERSION
        return all((root / name).exists() for name in tile_names(bbox))

    def rasterise(self, bbox, width: int, height: int):
        """WorldCover class at one sample per map tile.

        Read at WorldCover's own 10 m, 3x3-majority filtered there to take the
        speckle out, then sampled per tile: filtered after the stretch to map
        tiles, a 10 m pixel is ten tiles across and the filter changed nothing.
        Only tiles already on disk are read - this is the build path, and the
        generate step fetched what it needs."""
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.windows import from_bounds

        root = self.tile_dir()
        s, w, n, e = bbox
        native = None
        for name in tile_names(bbox):
            path = root / name
            if not path.exists():
                continue
            with rasterio.open(path) as src:
                if native is None:
                    rx, ry = abs(src.transform.a), abs(src.transform.e)
                    native = np.zeros((max(1, round((n - s) / ry)),
                                       max(1, round((e - w) / rx))), dtype="uint8")
                data = src.read(1, window=from_bounds(w, s, e, n, src.transform),
                                out_shape=native.shape,
                                resampling=Resampling.nearest,
                                boundless=True, fill_value=0)
            native[data > 0] = data[data > 0]   # OSM still paints over this
        if native is None:
            return np.zeros((height, width), dtype="uint8")
        native = _majority3(native)
        rows = np.minimum((np.arange(height) + 0.5) * native.shape[0] / height,
                          native.shape[0] - 1).astype(np.int64)
        cols = np.minimum((np.arange(width) + 0.5) * native.shape[1] / width,
                          native.shape[1] - 1).astype(np.int64)
        return native[rows[:, None], cols[None, :]]

    def tile_dir(self):
        """Where the downloaded tiles are kept."""
        return cache.DATASET_DIR / "worldcover" / VERSION

    def fetch(self, bbox, cache_dir=None, progress_cb=None):
        root = self.tile_dir()
        for name in tile_names(bbox):
            path = root / name
            if not cache.fresh(path, TTL_DAYS):
                cache.download(f"{BASE}/{name}", path, progress_cb=progress_cb)
        return root

    def build_layer(self, ctx) -> Layer:
        """Fraction of the AOI in each class, for the preset suggestion."""
        import numpy as np
        import rasterio
        from rasterio.windows import from_bounds

        root = self.fetch(ctx.bbox)
        table = classes()
        counts: dict[int, int] = {}
        for name in tile_names(ctx.bbox):
            with rasterio.open(root / name) as src:
                s, w, n, e = ctx.bbox
                window = from_bounds(w, s, e, n, src.transform)
                data = src.read(1, window=window)
            values, nvs = np.unique(data, return_counts=True)
            for value, count in zip(values.tolist(), nvs.tolist()):
                counts[int(value)] = counts.get(int(value), 0) + int(count)
        total = sum(counts.values()) or 1
        fractions = {table[str(k)]["name"]: round(v / total, 4)
                     for k, v in counts.items() if str(k) in table}
        return Layer(fractions=fractions, counts=counts, table=table)

    def apply(self, ctx, layer) -> None:
        ctx.report.setdefault("worldcover", {})["fractions"] = layer.data.get("fractions", {})
