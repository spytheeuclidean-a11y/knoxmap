"""Shared by every route module: paths, the logger, error replies and small request helpers."""
from __future__ import annotations

import re
from pathlib import Path

from flask import jsonify, request

import knoxlog


BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR = BASE_DIR / "cache"

log = knoxlog.setup("app")


def _request_context() -> dict:
    """What the page asked for, for the log: the map, the area and the
    settings, never more than a few hundred characters."""
    body = request.get_json(silent=True) if request.is_json else None
    if not isinstance(body, dict):
        return {}
    keep = ("mapName", "south", "west", "north", "east", "metersPerTile", "title", "modId")
    ctx = {k: body[k] for k in keep if k in body}
    if isinstance(body.get("settings"), dict):
        ctx["settings"] = body["settings"]
    if body.get("shape"):
        ctx["shape"] = "drawn"
    return ctx


def failed(message: str, status: int = 500, exc: BaseException | None = None):
    """An error reply the page shows, logged with an id the user can quote."""
    eid = knoxlog.record(exc, f"{request.method} {request.path} -> {status}: {message}",
                         **_request_context())
    return jsonify({"error": message, "errorId": eid}), status


SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def _json_body() -> dict:
    """The request's JSON object, or {} for anything else - a bare number, a
    list, broken JSON. Endpoints then report what is missing instead of
    failing with a server error."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _worlded_exe(cli: bool = False) -> Path | None:
    """Find PZWorldEd. `cli` prefers the patched build with --generate-map."""
    import knoxpaths

    return knoxpaths.worlded_cli() if cli else knoxpaths.worlded_gui()


def _map_dir(map_name: str) -> Path | None:
    # A page sends null here before any map exists; that is "no such map",
    # not a crash.
    if not isinstance(map_name, str) or not map_name.strip():
        return None
    safe = SAFE_NAME.sub("_", map_name)
    d = (OUTPUT_DIR / safe).resolve()
    if not d.is_relative_to(OUTPUT_DIR.resolve()) or not d.is_dir():
        return None
    return d


def _bbox_area_km2(south: float, west: float, north: float, east: float) -> float:
    lat_mid = (south + north) / 2
    h_km = (north - south) * 111.32
    w_km = (east - west) * 111.32 * _cos_lat(lat_mid)
    return h_km * w_km


def _cos_lat(lat_deg: float) -> float:
    import math
    return math.cos(math.radians(lat_deg))
