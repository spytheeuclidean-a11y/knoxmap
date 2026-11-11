"""Why a footprint did not become a building, in words.

The build keeps a row per footprint it left out (`<map>_left_out.csv`, written
by knoxbuild/build.py). This turns one of those rows into something a person
can read, and is the one place the wording lives: the window shows it when a
building is clicked (web/zones.py), and tools/why_no_building.py prints it.
Two copies of these sentences would drift apart.
"""
from __future__ import annotations

import csv
import os

# What each reason means, in the words somebody would use about their own map.
WHY = {
    "small": "smaller than the smallest building that can be furnished",
    "large": "too big to lay out, even cut into units",
    "outside": "its footprint falls off the edge of the map",
    "taken": "the ground was already taken by a building placed before it",
    "road": "mostly road: more of its footprint is tarmac than ground",
    "not a building": "tagged as something that is not a building "
                      "(a roof, a ruin, a tank)",
    "over the limit": "the map was held to a set number of buildings, and "
                      "this one was outside it",
    "thinned": "the town was laid out for the game rather than copied from "
               "the survey, and this house stood too close to one kept",
}
# What to try about it.
FIX = {
    "small": "lower 'Smallest building' in Fine tuning, or leave it: "
             "a 3x4 shed has nowhere to put a door.",
    "large": "raise 'Largest building'; past that it is cut into units.",
    "outside": "draw the area a little wider and generate again.",
    "taken": "two footprints overlap in OpenStreetMap - often a building "
             "mapped twice. The bigger one wins.",
    "road": "the road is drawn over the building in OpenStreetMap, or the "
            "road is laid wider than it really is at this scale.",
    "not a building": "nothing to do: these are not buildings.",
    "over the limit": "raise 'Most buildings' in Fine tuning, or set it to 0 "
                      "for no ceiling at all. Landmarks are never the ones "
                      "dropped.",
    "thinned": "turn on 'Build every address' to keep every house the survey "
               "has, at the density the place really has.",
}


# The same reasons said in half a line, for counting them up: "250 off the
# edge of the map" reads where "250 outside" has to be looked up.
SHORT = {
    "small": "too small to furnish",
    "large": "too big to lay out",
    "outside": "off the edge of the map",
    "taken": "mapped twice over, one on top of the other",
    "road": "under a road",
    "not a building": "not buildings at all (roofs, ruins, tanks)",
    "over the limit": "over the limit you set",
    "thinned": "thinned out to leave room around the rest",
}


def read_rows(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def left_out_path(folder: str) -> str:
    folder = str(folder).rstrip("/\\")
    return os.path.join(folder, f"{os.path.basename(folder)}_left_out.csv")


def placements_path(folder: str) -> str:
    folder = str(folder).rstrip("/\\")
    return os.path.join(folder, f"{os.path.basename(folder)}_placements.csv")


def describe(row: dict) -> str:
    """The building itself: what it is called, how big, where."""
    what = row.get("name") or row.get("building") or "a building"
    size = ""
    if row.get("tiles_wide"):
        size = f" ({row['tiles_wide']}x{row['tiles_tall']} tiles)"
    where = f"at {row.get('tile_x')},{row.get('tile_y')}"
    osm = f"  osm {row['osm_id']}" if row.get("osm_id") else ""
    return f"{what}{size} {where}{osm}"


def for_id(folder: str, osm_id) -> dict:
    """What happened to one footprint, by its OpenStreetMap id.

    `left out` with the reason when the build recorded one, `built` when it
    recorded nothing against a footprint it saw, and `no records` when the
    buildings were never generated for this map at all - every footprint
    would otherwise read as built.
    """
    wanted = str(osm_id).strip().rsplit("/", 1)[-1]
    # On the file being there rather than on it having rows: a map whose
    # buildings came out perfectly has an empty one, and a map built by a
    # version older than this has none - and in that one every footprint
    # would otherwise read as built.
    if not os.path.exists(left_out_path(folder)):
        return {"state": "no records"}
    rows = read_rows(left_out_path(folder))
    for row in rows:
        if str(row.get("osm_id") or "") == wanted:
            reason = row.get("reason") or ""
            return {
                "state": "left out",
                "reason": reason,
                "why": WHY.get(reason, ""),
                "fix": FIX.get(reason, ""),
                "name": row.get("name") or "",
                "building": row.get("building") or "",
                "tiles_wide": row.get("tiles_wide") or "",
                "tiles_tall": row.get("tiles_tall") or "",
                "tile_x": row.get("tile_x") or "",
                "tile_y": row.get("tile_y") or "",
                "osm_id": wanted,
            }
    return {"state": "built", "osm_id": wanted}


def counts(folder: str) -> dict:
    """How many footprints went each way, by reason. {} if never recorded."""
    path = left_out_path(folder)
    if not os.path.exists(path):
        return {}
    tally: dict[str, int] = {}
    for row in read_rows(path):
        reason = row.get("reason") or "?"
        tally[reason] = tally.get(reason, 0) + 1
    return tally


def summary(folder: str) -> dict:
    """The counts in words, biggest first, for the window to show as it is.

    Worded here rather than in the page so that the reasons are named the
    same way everywhere, and so a reason added to the build does not have to
    be added to the javascript as well.
    """
    tally = counts(folder)
    return {
        "total": sum(tally.values()),
        "lines": [{"n": n, "reason": reason,
                   "text": SHORT.get(reason, reason)}
                  for reason, n in sorted(tally.items(), key=lambda kv: -kv[1])],
    }
