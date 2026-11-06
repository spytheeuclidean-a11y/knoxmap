"""Files that belong to one map folder: its settings, edits, sketch and design."""
from __future__ import annotations

import json
import os
from pathlib import Path

import knoxfiles
import knoxlog
from generator import edits as mapedits
from generator import osm, renderer
from knoxbuild import mapstate
from knoxbuild.settings import Settings


SETTINGS_FILE = "settings.json"


def _settings_path(map_dir: Path) -> Path:
    return map_dir / SETTINGS_FILE


def _load_settings(map_dir: Path) -> Settings:
    """This map's saved settings, or the defaults."""
    try:
        with open(_settings_path(map_dir), encoding="utf-8") as f:
            return Settings.from_dict(json.load(f))
    except (OSError, ValueError):
        return Settings()


def _save_settings(map_dir: Path, settings: Settings) -> None:
    try:
        # Written beside itself and moved into place: half a settings.json is
        # read as no settings at all, so the next build of that map quietly
        # used the defaults instead of what the mapper had set.
        knoxfiles.write(str(_settings_path(map_dir)), settings.to_dict(), indent=2)
    except OSError:
        pass          # a map whose settings cannot be saved still builds


# ---- editing what a map was built from ------------------------------------------
#
# The download stays the download: what the mapper changed about it is kept
# beside the map as a short list of changes, keyed by each feature's own OSM
# id (generator/edits.py). A town is a hundred thousand features and nearly
# all of them are untouched, so this is a few lines where a copy would be
# megabytes - and a re-download does not throw the editing away.
def _osm_cache_for(map_dir: Path, bbox, meters_per_tile: float,
                   settings: Settings) -> tuple[str, tuple]:
    """Where this map's download lives, and the box it covers.

    A map turned to its street grid reaches past the drawn box at its corners
    and is fetched as the circle round it, under its own name. The editor and
    the generator both ask here, so they cannot look in different files.
    """
    south, west, north, east = bbox
    if bool(settings.align_streets) or bool(settings.rotate_degrees):
        return (osm.cache_path(str(map_dir), f"{map_dir.name}_turned"),
                renderer.cover_bbox(south, west, north, east, meters_per_tile))
    return osm.cache_path(str(map_dir), map_dir.name), tuple(bbox)


def _edits_path(map_dir: Path) -> Path:
    return map_dir / f"{map_dir.name}_edits.json"


def _load_edits(map_dir: Path) -> dict:
    try:
        with open(_edits_path(map_dir), encoding="utf-8") as f:
            return mapedits.clean(json.load(f))
    except (OSError, ValueError):
        return mapedits.empty()


def _save_edits(map_dir: Path, changes: dict) -> None:
    path = _edits_path(map_dir)
    try:
        map_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.part")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mapedits.clean(changes), f)
        os.replace(tmp, path)
    except OSError:
        pass          # a map whose edits cannot be saved still renders


# ---- the drawn map --------------------------------------------------------------
#
# What was drawn by hand for a map, as GeoJSON, next to the map it belongs to.
# It is kept rather than converted and thrown away because it is the only copy:
# the features it becomes go into the render and are gone, so without this a
# map could never be opened and its drawing changed.
def _sketch_path(map_dir: Path) -> Path:
    return map_dir / f"{map_dir.name}_sketch.geojson"


def _load_sketch(map_dir: Path) -> dict:
    try:
        with open(_sketch_path(map_dir), encoding="utf-8") as f:
            drawn = json.load(f)
    except (OSError, ValueError):
        return {"type": "FeatureCollection", "features": []}
    return drawn if isinstance(drawn, dict) else {
        "type": "FeatureCollection", "features": []}


def _save_sketch(map_dir: Path, drawn: dict | None) -> None:
    """Written whole through a temporary file, so a crash part way cannot
    leave a half-written drawing where the drawing was."""
    if not isinstance(drawn, dict):
        return
    path = _sketch_path(map_dir)
    try:
        map_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".geojson.part")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(drawn, f)
        os.replace(tmp, path)
    except OSError:
        pass          # a map whose drawing cannot be saved still renders


def _design_path(map_dir: Path) -> Path:
    return map_dir / f"{map_dir.name}_design.json"


def _load_design(map_dir: Path) -> dict | None:
    try:
        with open(_design_path(map_dir), encoding="utf-8") as f:
            design = json.load(f)
    except (OSError, ValueError):
        return None
    return design if isinstance(design, dict) else None


def _save_design(map_dir: Path, design: dict) -> None:
    path = _design_path(map_dir)
    try:
        map_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.part")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(design, f)
        os.replace(tmp, path)
    except OSError:
        pass          # a map whose sheet cannot be saved still renders


def _map_summary(map_dir: Path) -> dict:
    """What the window shows for a map it did not just make."""
    info = {}
    try:
        with open(map_dir / f"{map_dir.name}_info.json", encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        pass
    needs = mapstate.needs(str(map_dir))
    stages = mapstate.done(str(map_dir))
    inst = mapstate.installed(str(map_dir))
    compiled_at = (stages.get("compile") or {}).get("at")
    # The build as stamped, not guessed from a .pzw: a new Generate forgets it.
    built = (mapstate.read(str(map_dir)).get("stages") or {}).get("build")
    return {
        "mapName": map_dir.name,
        "width": info.get("width_tiles", 0),
        "height": info.get("height_tiles", 0),
        "cellsX": info.get("cells_x", 0),
        "cellsY": info.get("cells_y", 0),
        "featureCount": info.get("feature_count") or info.get("building_count", 0),
        "rotation": round(info.get("rotation", 0.0), 1),
        "updated": int(map_dir.stat().st_mtime),
        # What it was made from, so the window can run the steps again
        # over the same area without asking for it to be drawn afresh.
        "bbox": info.get("bbox"),
        "metersPerTile": info.get("meters_per_tile", 1.0),
        "shape": info.get("shape"),
        # The settings this map was made with. Upgrading it sent none at all,
        # so a map drawn with Knox County roads or a tree density of its own
        # came back with the defaults and looked like a different town.
        "settings": _load_settings(map_dir).to_dict(),
        "madeWith": mapstate.made_with(str(map_dir)),
        "current": knoxlog.version(),
        "stages": {k: v.get("version") for k, v in stages.items()},
        # Its buildings were built and not drawn over since (a new Generate
        # forgets the build stamp), so it can be compiled as it stands. The
        # window only offered Compile straight after a build, so after a
        # restart a built city had to be built again - hours - to compile it.
        "buildingsReady": bool(built) and (map_dir / f"{map_dir.name}.pzw").exists(),
        "builtAt": (built or {}).get("at"),
        "needs": needs,
        "needsLabels": [mapstate.LABELS[s] for s in needs],
        # Where it is installed, and whether that copy came after the last
        # compile - an install from before a recompile is out of date.
        "installed": None if inst is None else {
            "modRoot": inst["modRoot"],
            "at": inst.get("at"),
            "upToDate": not compiled_at or (inst.get("at") or "") >= compiled_at,
        },
        "files": {
            "landscape": f"/output/{map_dir.name}/{map_dir.name}.bmp",
            "vegetation": f"/output/{map_dir.name}/{map_dir.name}_veg.bmp",
            "spawn": f"/output/{map_dir.name}/{map_dir.name}_ZombieSpawnMap.bmp",
            "preview": f"/output/{map_dir.name}/{map_dir.name}_preview.png",
            "buildings": f"/output/{map_dir.name}/{map_dir.name}_buildings.geojson",
            "meta": f"/output/{map_dir.name}/{map_dir.name}_info.json",
            "zip": f"/download/{map_dir.name}.zip",
            "readme": f"/output/{map_dir.name}/README.txt",
        },
    }


def _population(map_dir: Path) -> dict | None:
    try:
        with open(map_dir / f"{map_dir.name}_population.json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
