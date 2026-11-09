"""Data layer status and fetching (knoxdata/).

The generate path only reads the cache, so the window needs one place to ask
what is available and one to fill the cache. Both are local-only, like every
other route (app.py's _only_local).
"""
from __future__ import annotations

import threading

from flask import Blueprint, jsonify, request

from web.common import _json_body, _map_dir, failed, log

bp = Blueprint("datasets", __name__)

# One refresh at a time; the fetch is minutes on a first run and the button
# may be pressed twice.
_REFRESH = {"state": "idle", "report": {}}
_REFRESH_LOCK = threading.Lock()


def _bbox(values) -> tuple[float, float, float, float] | None:
    try:
        south, west, north, east = (float(values[k]) for k in
                                    ("south", "west", "north", "east"))
    except (KeyError, TypeError, ValueError):
        return None
    if not (south < north and west < east):
        return None
    return south, west, north, east


@bp.route("/api/datasets/status")
def api_datasets_status():
    """What each layer is, whether it is on, and what it needs here."""
    import knoxdata
    from knoxbuild.settings import Settings

    args = request.args
    bbox = _bbox(args) if {"south", "west", "north", "east"} <= set(args) else None
    return jsonify({"layers": knoxdata.status(Settings(), bbox),
                    "refresh": _REFRESH["state"],
                    "report": _REFRESH["report"]})


@bp.route("/api/datasets/refresh", methods=["POST"])
def api_datasets_refresh():
    """Fill the cache for this area. Runs off the request thread."""
    body = _json_body()
    bbox = _bbox(body)
    if bbox is None:
        return failed("Refresh needs south, west, north and east.", 400)
    with _REFRESH_LOCK:
        if _REFRESH["state"] == "running":
            return jsonify({"state": "running"}), 202
        _REFRESH["state"] = "running"

    from knoxbuild.settings import Settings

    settings = Settings.from_dict(body.get("settings") or {})

    def worker():
        try:
            import knoxdata
            _REFRESH["report"] = knoxdata.refresh(settings, bbox)
        except Exception as exc:        # noqa: BLE001 - a fetch never crashes the app
            log.warning("datasets refresh failed - %s", exc)
            _REFRESH["report"] = {"error": str(exc)}
        finally:
            with _REFRESH_LOCK:
                _REFRESH["state"] = "idle"

    threading.Thread(target=worker, daemon=True, name="knoxdata-refresh").start()
    return jsonify({"state": "running"}), 202


@bp.route("/api/datasets/layers")
def api_datasets_layers():
    """What the layers did for a finished map (written at generate time)."""
    import knoxdata.cache as layer_cache

    map_dir = _map_dir(request.args.get("map", ""))
    if map_dir is None:
        return failed("Unknown map.", 404)
    return jsonify(layer_cache.read_json(map_dir / f"{map_dir.name}_knoxdata.json") or {})
