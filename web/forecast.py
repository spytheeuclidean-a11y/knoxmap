"""How long a map will take, worked out from how long the last ones did.

Every step now stamps the seconds it took (knoxbuild/mapstate.py), so the
forecast is measured rather than guessed: seconds a tile, the median over the
maps this PC has made. A step with no history behind it says nothing instead of
inventing a number - a forecast that is wrong by an hour is worse than none,
because somebody plans their evening around it.

What it is asked before Generate, when the map does not exist yet, so the area
comes in the request rather than out of a folder.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path

from generator import pz_colors as C
from knoxbuild import mapstate

# The steps worth waiting for, in the order they run. Install is a file copy and
# says how far along it is as it goes.
STEPS = ("generate", "build", "compile")


def size_of(south: float, west: float, north: float, east: float,
            meters_per_tile: float) -> tuple[int, int]:
    """The map's tiles across and down, padded to whole cells as the renderer
    does. The same estimate the pre-flight size checks use."""
    h_m = (north - south) * 111320.0
    w_m = (east - west) * 111320.0 * math.cos(math.radians((south + north) / 2))
    return (max(C.CELL_SIZE, int(math.ceil(w_m / meters_per_tile / C.CELL_SIZE) * C.CELL_SIZE)),
            max(C.CELL_SIZE, int(math.ceil(h_m / meters_per_tile / C.CELL_SIZE) * C.CELL_SIZE)))


def _building_counts(map_dir: Path) -> tuple[int, int]:
    """Return ``(buildings, floors)`` from a map's built CSV or GeoJSON."""
    csv_path = map_dir / f"{map_dir.name}_buildings.csv"
    if csv_path.is_file():
        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if rows:
                floors = sum(max(1, int(r.get("levels") or 1)) for r in rows)
                return len(rows), floors
        except (OSError, ValueError):
            pass
    geo_path = map_dir / f"{map_dir.name}_buildings.geojson"
    if geo_path.is_file():
        try:
            with open(geo_path, encoding="utf-8") as f:
                data = json.load(f)
            feats = data.get("features") or []
            if feats:
                return len(feats), 0
        except (OSError, ValueError):
            pass
    return 0, 0


def _collect_rates(output_dir) -> dict[str, dict[str, list[float]]]:
    found: dict[str, dict[str, list[float]]] = {
        "tiles": {stage: [] for stage in STEPS},
        "buildings": {stage: [] for stage in STEPS},
        "floors": {stage: [] for stage in STEPS},
    }
    for state in Path(output_dir).glob("*" + "/" + mapstate.STATE_FILE):
        map_dir = state.parent
        try:
            with open(map_dir / f"{map_dir.name}_info.json", encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            continue
        tiles = int(info.get("width_tiles") or 0) * int(info.get("height_tiles") or 0)
        if tiles <= 0:
            continue
        bldgs, floors = _building_counts(map_dir)
        for stage in STEPS:
            seconds = mapstate.took(str(map_dir), stage)
            if seconds:
                found["tiles"][stage].append(seconds / tiles)
                if bldgs > 0:
                    found["buildings"][stage].append(seconds / bldgs)
                if floors > 0:
                    found["floors"][stage].append(seconds / floors)
    return found


def rates(output_dir) -> dict[str, float]:
    """Seconds per tile each step has taken here, median over the timed maps."""
    found = _collect_rates(output_dir)["tiles"]
    return {stage: statistics.median(values)
            for stage, values in found.items() if values}


def forecast(output_dir, south: float, west: float, north: float, east: float,
             meters_per_tile: float, map_dir: Path | str | None = None) -> dict:
    """What this map will cost: its size, and the time each step takes at the
    pace of the maps already made on this PC.

    Before Generate, estimates use median seconds per tile. Once `map_dir` has
    building counts or floor counts, Build and Compile refine to those rates.
    """
    tiles_w, tiles_h = size_of(south, west, north, east, meters_per_tile)
    tiles = tiles_w * tiles_h
    collected = _collect_rates(output_dir)
    map_bldgs, map_floors = _building_counts(Path(map_dir)) if map_dir else (0, 0)

    steps: dict[str, int | None] = {}
    counts: dict[str, int] = {}
    basis: dict[str, str] = {}
    measured: list[str] = []

    for stage in STEPS:
        t_vals = collected["tiles"][stage]
        b_vals = collected["buildings"][stage]
        f_vals = collected["floors"][stage]
        if stage == "compile" and map_floors > 0 and f_vals:
            steps[stage] = int(round(statistics.median(f_vals) * map_floors))
            counts[stage] = len(f_vals)
            basis[stage] = "floors"
        elif stage in ("build", "compile") and map_bldgs > 0 and b_vals:
            steps[stage] = int(round(statistics.median(b_vals) * map_bldgs))
            counts[stage] = len(b_vals)
            basis[stage] = "buildings"
        elif t_vals:
            steps[stage] = int(round(statistics.median(t_vals) * tiles))
            counts[stage] = len(t_vals)
            basis[stage] = "tiles"
        else:
            steps[stage] = None
            counts[stage] = 0
        if steps[stage] is not None:
            measured.append(stage)

    return {
        "tiles": {"width": tiles_w, "height": tiles_h},
        "cells": {"x": tiles_w // C.CELL_SIZE, "y": tiles_h // C.CELL_SIZE},
        # Ground, greenery and the zombie spawn map, 24 bits a tile.
        "bitmapsMB": round(tiles * 3 * 3 / 1e6, 1),
        "steps": steps,
        "counts": counts,
        "basis": basis,
        "measured": measured,
    }
