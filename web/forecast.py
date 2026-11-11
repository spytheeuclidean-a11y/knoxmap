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


def rates(output_dir) -> dict[str, float]:
    """Seconds per tile each step has taken here, median over the timed maps."""
    found: dict[str, list[float]] = {stage: [] for stage in STEPS}
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
        for stage in STEPS:
            seconds = mapstate.took(str(map_dir), stage)
            if seconds:
                found[stage].append(seconds / tiles)
    return {stage: statistics.median(values)
            for stage, values in found.items() if values}


def forecast(output_dir, south: float, west: float, north: float, east: float,
             meters_per_tile: float) -> dict:
    """What this map will cost: its size, and the time each step takes at the
    pace of the maps already made on this PC."""
    tiles_w, tiles_h = size_of(south, west, north, east, meters_per_tile)
    tiles = tiles_w * tiles_h
    measured = rates(output_dir)
    return {
        "tiles": {"width": tiles_w, "height": tiles_h},
        "cells": {"x": tiles_w // C.CELL_SIZE, "y": tiles_h // C.CELL_SIZE},
        # Ground, greenery and the zombie spawn map, 24 bits a tile.
        "bitmapsMB": round(tiles * 3 * 3 / 1e6, 1),
        "steps": {stage: (int(round(measured[stage] * tiles)) if stage in measured
                          else None) for stage in STEPS},
        "measured": [stage for stage in STEPS if stage in measured],
    }
