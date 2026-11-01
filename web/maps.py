"""Maps already made: the list, the files they serve, lots and placement, saving and downloading."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file, send_from_directory

import knoxlog

from web import common
from web.common import CACHE_DIR, SAFE_NAME, _json_body, _map_dir, failed, log
from web.mapfiles import _load_settings, _map_summary, _population

bp = Blueprint("maps", __name__)


@bp.route("/api/maps")
def api_maps():
    """Every map in output/, newest first, and whether an older KnoxMap made
    it - so one can be opened again instead of drawn from scratch."""
    maps = []
    for entry in common.OUTPUT_DIR.iterdir():
        if not entry.is_dir() or not (entry / f"{entry.name}_info.json").exists():
            continue
        maps.append(_map_summary(entry))
    maps.sort(key=lambda m: -m["updated"])
    return jsonify({"maps": maps, "current": knoxlog.version()})


@bp.route("/api/maps/<map_name>")
def api_map(map_name: str):
    """One map, in the shape the page shows a freshly generated one in."""
    map_dir = _map_dir(map_name)
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    summary = _map_summary(map_dir)
    summary["settings"] = _load_settings(map_dir).to_dict()
    summary["population"] = _population(map_dir)
    return jsonify(summary)


@bp.route("/output/<path:relpath>")
def serve_output(relpath: str):
    return send_from_directory(common.OUTPUT_DIR, relpath)


@bp.route("/api/lots")
def api_lots():
    """Has WorldEd's Generate Lots produced anything yet?"""
    map_dir = _map_dir(request.args.get("map", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    lots = map_dir / "lots"
    cells = sorted(lots.glob("*.lotheader")) if lots.is_dir() else []
    return jsonify({"compiled": bool(cells), "cells": len(cells)})


@bp.route("/api/placement/<name>", methods=["GET", "POST", "DELETE"])
def api_placement(name: str):
    """Where this map stands in the game's world, and where to put it.

    GET is the world as the window draws it: Knox County, the maps already
    installed, and this one. POST moves this one, which rewrites the few files
    that carry the world origin and says whether the map has to be compiled
    again (knoxbuild/placement.py). DELETE goes back to having a place picked
    automatically.
    """
    from knoxbuild import placement as P

    map_dir = _map_dir(name)
    if map_dir is None:
        return jsonify({"error": "Bad map name."}), 400
    if request.method == "GET":
        return jsonify(P.layout(str(map_dir), map_dir.name, str(CACHE_DIR)))
    # A compile reads the map's place once, when it starts: moving the map under
    # it leaves lots named for the old place, refused at install as "moved".
    from web.jobs import _COMPILE, _PROGRESS_LOCK
    with _PROGRESS_LOCK:
        compiling = _COMPILE.get(map_dir.name, {}).get("state") in ("running", "stopping")
    if compiling:
        return jsonify({"error": "The map is compiling. Move it, or change Standalone, "
                                 "once the compile has finished."}), 409
    if request.method == "DELETE":
        done = P.unplace(str(map_dir), map_dir.name)
        log.info("placement %s: automatic, now cell %s (was %s)",
                 map_dir.name, done["origin"], done["was"])
        out = P.layout(str(map_dir), map_dir.name)
        out["moved"] = done
        return jsonify(out)
    body = _json_body()
    try:
        if "standalone" in body and body.get("cell_x") is None:
            done = P.set_standalone(str(map_dir), map_dir.name,
                                    body.get("standalone") is True)
            log.info("placement %s: standalone %s, now cell %s (was %s)", map_dir.name,
                     body.get("standalone") is True, done["origin"], done["was"])
            out = P.layout(str(map_dir), map_dir.name)
            out["moved"] = done
            return jsonify(out)
        done = P.move(str(map_dir), map_dir.name,
                      (body.get("cell_x"), body.get("cell_y")))
        log.info("placement %s: now cell %s (was %s)", map_dir.name, done["origin"], done["was"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except OSError as exc:
        return failed(f"The map could not be moved: {exc}", 500, exc)
    out = P.layout(str(map_dir), map_dir.name)
    out["moved"] = done
    return jsonify(out)


@bp.route("/api/placement/<name>/link", methods=["POST"])
def api_placement_link(name: str):
    """The sheet for a road drawn between this map and another.

    The window sends where the road was drawn, in world tiles; what comes back
    is a map to build (generator/sketch.py): the strip of country it runs
    through, at the same scale as the map it joins so the road is the same
    width in tiles as the streets it meets.
    """
    from knoxbuild import placement as P

    map_dir = _map_dir(name)
    if map_dir is None:
        return jsonify({"error": "Bad map name."}), 400
    body = _json_body()
    try:
        out = P.link_design(str(map_dir), map_dir.name, body.get("points"),
                            str(body.get("kind") or "primary"),
                            scenery=body.get("scenery", True) is not False)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:                  # noqa: BLE001 - reported
        return failed(f"That road could not be laid out: {exc}", 500, exc)
    out["name"] = f"{map_dir.name}_link"
    return jsonify(out)


@bp.route("/api/world-picture/<name>")
def api_world_picture(name: str):
    """The picture of a map already in the game, for the world view.

    Assembled from that map's own tile pyramid in the player's install and
    kept in the cache. It is their copy of the game, read on their own PC and
    shown in their own window; nothing is copied into a map or shipped.
    """
    from knoxbuild import placement as P

    where = P.picture_for(name, str(CACHE_DIR))
    if not where:
        return jsonify({"error": "No picture of that map."}), 404
    return send_file(where["file"], mimetype="image/png",
                     max_age=86400, conditional=True)


@bp.route("/api/save", methods=["POST"])
def api_save():
    """Save a map's file where the player can find it and show it in Explorer.

    A download link does nothing in the app window: it is a WebView, not a
    browser, with nowhere to put a file. Everything is already on disk in the
    map's own folder, so "downloading" here means making the zip when that is
    what was asked for, and opening Explorer with the file selected.
    """
    data = _json_body()
    map_dir = _map_dir(data.get("mapName", ""))
    if map_dir is None:
        return failed("Unknown map.", 404)
    name = str(data.get("name", "")).strip()
    if name in ("", "zip"):
        target = map_dir / f"{map_dir.name}.zip"
        try:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                for path in sorted(map_dir.rglob("*")):
                    if not path.is_file() or path.suffix.lower() == ".zip":
                        continue
                    zf.write(path, arcname=str(Path(map_dir.name) / path.relative_to(map_dir)))
        except OSError as exc:
            return failed(f"Could not write the zip: {exc}", 500, exc)
    else:
        target = (map_dir / name).resolve()
        if not str(target).startswith(str(map_dir.resolve())) or not target.is_file():
            return failed("That file is not in this map's folder.", 400)
    knoxlog.open_folder(target)
    log.info("saved %s for %s", target.name, map_dir.name)
    return jsonify({"path": str(target), "name": target.name,
                    "folder": str(target.parent)})


@bp.route("/download/<map_name>.zip")
def download_all(map_name: str):
    """Everything for one map, zipped on demand.

    Built when asked for rather than at generation time, so it also picks up
    anything produced later - the .tbx buildings, the .pzw project and the
    placement CSV that `python -m knoxbuild` writes into the same folder.
    """
    safe = SAFE_NAME.sub("_", map_name)
    map_dir = (common.OUTPUT_DIR / safe).resolve()
    if not str(map_dir).startswith(str(common.OUTPUT_DIR.resolve())):
        return jsonify({"error": "Bad map name."}), 400
    if not map_dir.is_dir():
        return jsonify({"error": f"No output for {safe!r}."}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(map_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() == ".zip":
                continue
            zf.write(path, arcname=str(Path(safe) / path.relative_to(map_dir)))
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"{safe}.zip")
