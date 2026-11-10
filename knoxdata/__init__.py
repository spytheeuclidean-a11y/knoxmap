"""Optional enrichment layers from data outside OpenStreetMap.

Each dataset is a module implementing DatasetSource: it says whether it can
run here, downloads to a cache, builds a layer and applies it. A layer that
cannot run is logged and skipped; a map is never lost to a dataset. OSM and
hand-authored data always win. See docs/DATASETS.md.

Heavy dependencies (rasterio, pyarrow) are imported inside the modules that
need them, never here, so the package imports on a bare install.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

try:                                  # the app's logger, so lines land in the log
    import knoxlog
    log = knoxlog.setup("knoxdata")
except Exception:                     # noqa: BLE001 - a missing logger is not fatal
    import logging
    log = logging.getLogger("knoxdata")


# The order layers apply in: terrain first, then what stands on it.
ORDER = ("elevation_3dep", "worldcover", "natural_earth",
         "hifld_hospitals", "climate_normals")


@dataclass
class MapContext:
    """The little the pipeline has to hand a layer, and what it hands back."""
    bbox: tuple[float, float, float, float]   # south, west, north, east
    settings: object
    map_dir: Path
    map_name: str = ""
    features: list = field(default_factory=list)   # OSMFeature (mutable .tags)
    labels: dict = field(default_factory=dict)     # paper-map labels to add
    report: dict = field(default_factory=dict)     # per-layer result
    region: str = ""                                # ISO-2 country, from NE
    climate: dict = field(default_factory=dict)     # from NOAA normals
    landcover: object = None                        # per-tile class raster
    elevation: object = None                        # per-tile metres
    proj: object = None                             # renderer Projector, when known


class Layer:
    """What build_layer returns: a plain bag the source understands."""
    def __init__(self, data=None, **extra):
        # Layer({"rows": ...}) and Layer(rows=...) are both a data dict.
        self.data = dict(extra) if data is None else data
        self.extra = extra


class DatasetSource(ABC):
    """One optional dataset. Subclasses gate themselves out when they cannot run."""

    name: str = ""
    license: str = ""
    attribution: str = ""        # the line a map carries when this applied
    setting: str = ""            # Settings field that turns it on
    off_values: tuple = ("off", "", 0, None, False)

    def enabled(self, settings) -> bool:
        return getattr(settings, self.setting, None) not in self.off_values

    def cached(self, bbox) -> bool:
        """Is what this layer needs already on disk, so applying it costs no
        download? The pipeline calls run_layers(require_cache=True): a map is
        never slowed or failed by a dataset fetch."""
        return True

    @abstractmethod
    def available(self, bbox) -> bool:
        """Can this layer run here (dependency present, bbox in coverage)?"""

    @abstractmethod
    def why_unavailable(self) -> str:
        """One sentence for the log when available() is false."""

    @abstractmethod
    def fetch(self, bbox, cache_dir, progress_cb=None):
        """Download to cache_dir and return a Path (or raise)."""

    @abstractmethod
    def build_layer(self, map_ctx):
        """Read the cache into a Layer."""

    @abstractmethod
    def apply(self, map_ctx, layer) -> None:
        """Fold the layer into the map."""


def _build_registry() -> dict:
    from . import (climate_normals, elevation_3dep, hifld_hospitals,
                   natural_earth, worldcover)
    sources = [worldcover.WorldCover(), elevation_3dep.Elevation3DEP(),
               natural_earth.NaturalEarth(), hifld_hospitals.HIFLDHospitals(),
               climate_normals.ClimateNormals()]
    return {s.name: s for s in sources}


_SOURCES: dict | None = None


def sources() -> dict:
    global _SOURCES
    if _SOURCES is None:
        _SOURCES = _build_registry()
    return _SOURCES


def run_layers(settings, bbox, map_dir, map_name="", features=None,
               progress=None, ctx=None, require_cache=False):
    """Apply every enabled layer in ORDER; never raise for want of a dataset.

    Pass `ctx` to have the caller's MapContext filled in (region, labels,
    climate). With `require_cache` a layer is skipped unless its data is
    already on disk, so the build path never waits on a download; call
    refresh() first to populate the cache. Returns the report.
    """
    if ctx is None:
        ctx = MapContext(bbox=tuple(bbox), settings=settings, map_dir=Path(map_dir),
                         map_name=map_name,
                         features=features if features is not None else [])
    elif features is not None:
        ctx.features = features
    used: list[str] = []
    for name in ORDER:
        source = sources().get(name)
        if source is None or not source.enabled(settings):
            continue
        if not source.available(bbox):
            why = source.why_unavailable()
            log.info("knoxdata: %s skipped - %s", name, why)
            ctx.report[name] = {"used": False, "why": why}
            continue
        if require_cache and not source.cached(bbox):
            log.info("knoxdata: %s skipped - not cached; run refresh to fetch it", name)
            ctx.report[name] = {"used": False, "why": "not cached"}
            continue
        try:
            layer = source.build_layer(ctx)
            source.apply(ctx, layer)
            used.append(name)
            # Kept beside what apply() reported (WorldCover's class fractions).
            ctx.report[name] = {**ctx.report.get(name, {}), "used": True}
        except Exception as exc:            # noqa: BLE001 - one layer never sinks a map
            log.warning("knoxdata: %s failed - %s: %s; continuing without it",
                        name, type(exc).__name__, exc)
            ctx.report[name] = {"used": False, "why": str(exc)}
    ctx.report["used"] = used
    return ctx.report


def refresh(settings, bbox, progress=None) -> dict:
    """Download the enabled layers into the cache. The explicit fetch step:
    the generate path only ever reads what this put on disk."""
    out = {}
    for name in ORDER:
        source = sources().get(name)
        if source is None or not source.enabled(settings):
            continue
        if not source.available(bbox):
            out[name] = {"fetched": False, "why": source.why_unavailable()}
            continue
        try:
            source.fetch(tuple(bbox), cache_dir=None, progress_cb=progress)
            out[name] = {"fetched": True}
        except Exception as exc:            # noqa: BLE001
            log.info("knoxdata: %s refresh failed - %s", name, exc)
            out[name] = {"fetched": False, "why": str(exc)}
    return out


def landcover_for(settings, bbox):
    """A callable the renderer uses to lay WorldCover ground, or None.

    Only when the worldcover layer is on, in coverage, and already cached: the
    build path never downloads.
    """
    source = sources().get("worldcover")
    if (source is None or not source.enabled(settings)
            or not source.available(bbox) or not source.cached(bbox)):
        return None
    box = tuple(bbox)

    def grid(width, height, bounds=None):
        # `bounds` is what the map image covers, which is padded to whole
        # cells past the bbox; without it the bbox is stretched over the image.
        return source.rasterise(tuple(bounds) if bounds else box, width, height)
    return grid


def attribution_lines(names, retrieved: str | None = None) -> list[str]:
    """What a map built with `names` carries in ATTRIBUTION.txt."""
    when = retrieved or time.strftime("%Y-%m-%d")
    out = []
    for name in names:
        source = sources().get(name)
        if source and source.attribution:
            out.append(f"{source.attribution} (retrieved {when})")
    return out


def status(settings=None, bbox=None) -> dict:
    """Which layers are on, and which cannot run here. For Setup and the UI."""
    rows = {}
    for name in ORDER:
        source = sources().get(name)
        if source is None:
            continue
        on = bool(settings is None or source.enabled(settings))
        # Coverage only means something for a real bbox; without one report
        # what can be known from this machine (a missing dependency).
        can = source.available(bbox) if bbox is not None else not _needs_missing_source(source)
        rows[name] = {"enabled": on, "available": can, "license": source.license,
                      "why": "" if can else source.why_unavailable()}
    return rows


def _needs_missing_source(source) -> bool:
    """True when the layer is blocked by a dependency this machine lacks."""
    try:
        return "not installed" in source.why_unavailable()
    except Exception:                   # noqa: BLE001
        return False
