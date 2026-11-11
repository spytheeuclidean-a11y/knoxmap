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


@bp.route("/api/maps/<map_name>", methods=["GET", "DELETE"])
def api_map(map_name: str):
    """One map: GET shows its summary; DELETE removes its folder in output/
    and any installed mod in ~/Zomboid/mods."""
    map_dir = _map_dir(map_name)
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404

    if request.method == "DELETE":
        from web.jobs import _COMPILE, _PROGRESS_LOCK
        with _PROGRESS_LOCK:
            compiling = _COMPILE.get(map_dir.name, {}).get("state") in ("running", "stopping")
        if compiling:
            return jsonify({"error": "The map is busy. Stop it first."}), 409

        # If installed, also clean up the installed mod in ~/Zomboid/mods
        try:
            from knoxbuild import mapstate
            from tools import make_map_mod
            rec = mapstate.installed(str(map_dir))
            if rec and "modRoot" in rec:
                mod_root = Path(rec["modRoot"]).resolve()
                if mod_root.is_dir() and mod_root.parent.name == "mods":
                    info_file = mod_root / "mod.info"
                    if info_file.is_file() and "generated from real-world map data with KnoxMap" in info_file.read_text(encoding="utf-8", errors="replace"):
                        make_map_mod._clear_folder(str(mod_root))
        except Exception as exc:
            log.warning("Could not remove mod during map delete %s: %s", map_dir.name, exc)

        import shutil
        try:
            shutil.rmtree(map_dir)
            log.info("deleted map project: %s", map_dir.name)
        except OSError as exc:
            return failed(f"Could not delete map folder: {exc}", 500, exc)

        return jsonify({"deleted": map_dir.name})

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
        out = P.layout(str(map_dir), map_dir.name, str(CACHE_DIR))
        out["moved"] = done
        return jsonify(out)
    body = _json_body()
    try:
        if "standalone" in body and body.get("cell_x") is None:
            done = P.set_standalone(str(map_dir), map_dir.name,
                                    body.get("standalone") is True)
            log.info("placement %s: standalone %s, now cell %s (was %s)", map_dir.name,
                     body.get("standalone") is True, done["origin"], done["was"])
            out = P.layout(str(map_dir), map_dir.name, str(CACHE_DIR))
            out["moved"] = done
            return jsonify(out)
        done = P.move(str(map_dir), map_dir.name,
                      (body.get("cell_x"), body.get("cell_y")))
        log.info("placement %s: now cell %s (was %s)", map_dir.name, done["origin"], done["was"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except OSError as exc:
        return failed(f"The map could not be moved: {exc}", 500, exc)
    out = P.layout(str(map_dir), map_dir.name, str(CACHE_DIR))
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


@bp.route("/api/iso-info/<name>")
def api_iso_info(name: str):
    """Metadata about a map's compiled isometric views."""
    import json
    map_dir = _map_dir(name)
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    lots = map_dir / "lots"
    compiled = lots.is_dir() and any(lots.glob("*.lotheader"))

    info_path = map_dir / f"{map_dir.name}_info.json"
    info = {}
    if info_path.is_file():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    pics_dir = map_dir / "pictures"
    pictures = {}
    if pics_dir.is_dir():
        for p in ("town.png", "close.png", "inside_town.png", "inside.png"):
            target = pics_dir / p
            if target.is_file():
                pictures[p.replace(".png", "")] = f"/output/{map_dir.name}/pictures/{p}?t={int(target.stat().st_mtime)}"
        # If inside_town.png exists, use it for "inside" so the full town has all interiors visible
        if (pics_dir / "inside_town.png").is_file():
            pictures["inside"] = f"/output/{map_dir.name}/pictures/inside_town.png?t={int((pics_dir / 'inside_town.png').stat().st_mtime)}"

    cells_list = []
    if lots.is_dir():
        for lh in sorted(lots.glob("*.lotheader")):
            parts = lh.stem.split("_")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                cells_list.append([int(parts[0]), int(parts[1])])

    # Focus coordinates centered on the actual town buildings rather than arbitrary midpoint
    focus_x = None
    focus_y = None
    placements_csv = map_dir / f"{map_dir.name}_placements.csv"
    if placements_csv.is_file():
        try:
            import csv
            xs, ys = [], []
            with open(placements_csv, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "tile_x" in row and "tile_y" in row:
                        xs.append(int(row["tile_x"]))
                        ys.append(int(row["tile_y"]))
            if xs and ys:
                focus_x = round(sum(xs) / len(xs))
                focus_y = round(sum(ys) / len(ys))
        except Exception:
            pass

    return jsonify({
        "name": map_dir.name,
        "compiled": compiled,
        "width_tiles": int(info.get("width_tiles") or 0),
        "height_tiles": int(info.get("height_tiles") or 0),
        "cells_x": int(info.get("cells_x") or 0),
        "cells_y": int(info.get("cells_y") or 0),
        "building_count": int(info.get("building_count") or 0),
        "focus_x": focus_x,
        "focus_y": focus_y,
        "pictures": pictures,
        "cells": cells_list,
    })


@bp.route("/api/iso-render/<name>")
def api_iso_render(name: str):
    """Render an area of the compiled map in 2.5D isometric view."""
    map_dir = _map_dir(name)
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    lots = map_dir / "lots"
    if not (lots.is_dir() and any(lots.glob("*.lotheader"))):
        return jsonify({"error": "Map is not compiled yet."}), 400

    from tools import render_lots
    from knoxbuild.picture import _trim, picture as make_picture

    # Scale parameter (1.0 = native in-game zoom)
    try:
        scale = float(request.args.get("scale", 1.0))
    except ValueError:
        scale = 1.0
    scale = max(0.05, min(1.0, scale))

    roofs = request.args.get("roofs", "1") in ("1", "true", "yes", "on")
    floor_arg = request.args.get("floor")
    if floor_arg is not None and floor_arg != "":
        try:
            max_level = int(floor_arg)
        except ValueError:
            max_level = None if roofs else 0
    else:
        max_level = None if roofs else 0
    if max_level is not None:
        max_level = max(0, min(int(max_level), 64))

    box_arg = request.args.get("box")
    if box_arg:
        try:
            x, y, w, h = [int(float(v)) for v in box_arg.split(",")]
        except ValueError:
            return jsonify({"error": "box must be x,y,w,h"}), 400
        # A box is drawn whole, never cropped to the first 200 tiles of what
        # was asked for. The picture grows with the square of the box - 200x200
        # at 1:1 is already 12,864x6,624 - so anything larger is rendered at a
        # smaller scale instead: 528 * (w + h)^2 * scale^2 stays under 90 Mpx
        # while (w + h) * scale <= 412.
        w = max(10, w)
        h = max(10, h)
        span = w + h
        if span * scale > 412:
            scale = max(0.05, 412 / span)
    else:
        # Default: if full map requested without box, check existing pictures first
        pics_dir = map_dir / "pictures"
        if not roofs and (pics_dir / "inside_town.png").is_file():
            return send_file(pics_dir / "inside_town.png", mimetype="image/png")
        target_name = "town.png" if roofs else "inside_town.png"
        target_path = pics_dir / target_name
        if target_path.is_file():
            return send_file(target_path, mimetype="image/png")
        # Otherwise generate full picture
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            make_picture(map_dir, target_path, roofs=roofs)
            if target_path.is_file():
                return send_file(target_path, mimetype="image/png")
        except Exception as exc:
            return failed(f"Could not draw picture: {exc}", 500, exc)
        return jsonify({"error": "Could not render picture."}), 500

    # Cache key for box renders. The lot files are what the picture is drawn
    # from, so the newest of them belongs in the key: without it a map that was
    # compiled again kept showing the town it used to be.
    cache_dir = map_dir / "pictures" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    newest = max((p.stat().st_mtime_ns for p in lots.glob("*.lot*")), default=0)
    cache_file = (cache_dir / f"iso_{x}_{y}_{w}_{h}_s{scale:.2f}"
                                f"_r{1 if roofs else 0}_m{max_level}_t{newest}.png")

    if cache_file.is_file():
        return send_file(cache_file, mimetype="image/png")

    try:
        drawn = render_lots.render(str(map_dir), x, y, w, h, max_level=max_level, scale=scale)
    except Exception as exc:
        return failed(f"Render failed: {exc}", 500, exc)

    if drawn is None:
        # Return an empty ground canvas so the browser <img> element never breaks
        from PIL import Image
        TW = max(4, round(64 * scale))
        half, quarter = TW // 2, TW // 4
        width = (w + h) * half + TW
        height = (w + h) * quarter + 2 * TW
        drawn = Image.new("RGBA", (width, height), (24, 26, 28, 255))

    trimmed = _trim(drawn)
    try:
        trimmed.save(cache_file, "PNG")
        return send_file(cache_file, mimetype="image/png")
    except Exception as exc:
        return failed(f"Saving render failed: {exc}", 500, exc)


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
        if not target.is_relative_to(map_dir.resolve()) or not target.is_file():
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
    if not map_dir.is_relative_to(common.OUTPUT_DIR.resolve()):
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
