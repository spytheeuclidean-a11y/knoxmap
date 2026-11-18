"""Saved areas and the building builder: presets.json and the builder's design routes."""
from __future__ import annotations

import io
import json
import os
import re
import threading
import time

from flask import Blueprint, jsonify, request, send_file

import knoxlog
from knoxbuild.settings import PRESETS, Settings

from web.checks import (MAX_METERS_PER_TILE, MIN_METERS_PER_TILE, _clean_shape,
                        _shape_rings, tidy_scale)
from web.common import BASE_DIR, _json_body, _map_dir, failed

bp = Blueprint("presets", __name__)


@bp.route("/api/presets/buildings", methods=["GET"])
def api_building_presets():
    """Every hand-built building, and which kinds are built from them."""
    from knoxbuild import presets as P

    return jsonify({"presets": [{k: v for k, v in entry.items() if k != "file"}
                                for entry in P.library(BASE_DIR)],
                    "kinds": P.kinds(), "use": sorted(P.using(BASE_DIR))})


@bp.route("/api/presets/buildings/<name>", methods=["POST", "DELETE"])
def api_building_preset(name: str):
    """Keep a building as a preset, or throw one away.

    A preset is a .tbx - the same file the generator writes and BuildingEd
    reads - so it is kept exactly as it came: the point of a hand-built
    building is that nothing happens to it.
    """
    from knoxbuild import presets as P

    if request.method == "DELETE":
        return jsonify({"removed": P.remove(BASE_DIR, name)})
    body = _json_body()
    text = body.get("tbx") if isinstance(body, dict) else None
    if not isinstance(text, str) and isinstance(body, dict):
        # Or by pointing at a building of a map that came out well.
        map_dir = _map_dir(body.get("mapName") or "")
        wanted = str(body.get("file") or "")
        if map_dir is not None and wanted and "/" not in wanted                 and "\\" not in wanted and wanted.endswith(".tbx"):
            try:
                with open(map_dir / "buildings" / wanted, encoding="utf-8",
                          errors="replace") as f:
                    text = f.read()
            except OSError:
                text = None
    if not isinstance(text, str):
        return jsonify({"error": "Send the building as 'tbx', or name a map "
                                 "and one of its .tbx files."}), 400
    try:
        about = P.save(BASE_DIR, name, text, kind=body.get("kind") or "")
    except (ValueError, OSError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({k: v for k, v in about.items() if k != "file"})


# ---- buildings passed from one person to another ----------------------------
#
# One file holds a whole hand-built building - the .tbx, the drawing it was
# made from and what it stands in for - so it can be sent over Discord and
# dropped into anybody's KnoxMap (knoxbuild/share.py). It is also how a
# building gets into the library that ships with KnoxMap: send one in, and
# tools/add_shared_building.py puts it in presets/library/.

def _library_reply() -> list[dict]:
    from knoxbuild import presets as P

    return [{k: v for k, v in e.items() if k != "file"} for e in P.library(BASE_DIR)]


@bp.route("/api/presets/buildings/<name>/share", methods=["POST"])
def api_building_share(name: str):
    """Write out a building as a file to send to somebody."""
    from knoxbuild import share as S

    body = _json_body()
    body = body if isinstance(body, dict) else {}
    try:
        entry = S.of_preset(BASE_DIR, name, author=body.get("author") or "",
                            notes=body.get("notes") or "")
    except (ValueError, OSError) as exc:
        return jsonify({"error": str(exc)}), 400
    payload = (json.dumps(entry, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    filename = S.file_name(entry["name"])
    if os.environ.get("KNOXMAP_WINDOW") == "1":
        folder = BASE_DIR / "preset_exports"
        try:
            folder.mkdir(exist_ok=True)
            target = folder / filename
            if target.exists():
                target = folder / f"{time.time_ns()}_{filename}"
            target.write_bytes(payload)
        except OSError as exc:
            return failed(f"Could not write that building out: {exc}", 500, exc)
        knoxlog.open_folder(target)
        return jsonify({"name": target.name, "folder": str(folder)})
    return send_file(io.BytesIO(payload), mimetype="application/json",
                     as_attachment=True, download_name=filename)


@bp.route("/api/presets/buildings/import", methods=["POST"])
def api_building_import():
    """Take in a building somebody else built and shared."""
    from knoxbuild import share as S

    entry, problem = S.read(_json_body())
    if problem:
        return jsonify({"error": problem}), 400
    try:
        about = S.install(BASE_DIR, entry)
    except (ValueError, OSError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"saved": {k: v for k, v in about.items() if k != "file"},
                    "author": entry.get("author") or "",
                    "presets": _library_reply()})


# ---- the building editor ----------------------------------------------------
#
# Rooms drawn on a sheet, built into a real .tbx by the generator's own passes
# (knoxbuild/designer.py). The window holds the drawing and sends it back
# whole for each change: the geometry - rooms that may not overlap - is worked
# out in one place, and the picture that comes back is drawn from the finished
# building rather than from the drawing, so what is on screen is what will be
# saved.

def _builder_reply(design: dict, level: int = 0) -> dict:
    import base64

    from knoxbuild import designer as D

    design = D.clean(design)
    level = min(max(level, 0), design["storeys"] - 1)
    # A big building takes seconds to lay out whole, which is too long to wait
    # for after every drag, so only the storey being drawn is built for the
    # picture. The whole stack is built when it is saved.
    alone = D.one_storey_at_a_time(design)
    built = D.stack(design, only=level if alone else None)
    image = ""
    if built.storeys:
        shot = io.BytesIO()
        D.preview(design, 0 if alone else level,
                  building=built).save(shot, format="PNG")
        image = ("data:image/png;base64,"
                 + base64.b64encode(shot.getvalue()).decode("ascii"))
    storey = built.storeys[0 if alone else min(level, len(built.storeys) - 1)] \
        if built.storeys else None
    return {"design": design, "level": level, "scale": D.scale_for(design),
            "image": image, "oneStoreyAtATime": alone,
            "storeys": design["storeys"] if alone else len(built.storeys),
            "tiles": D.tiles_used(design),
            "tally": [{"kind": kind, "label": D.room_label(kind),
                       "tiles": area,
                       "colour": "#%02x%02x%02x" % D.room_colour(kind)}
                      for kind, area in D.tally(design, level)],
            "built": {"rooms": len(storey.rooms) if storey else 0,
                      "doors": len(storey.doors) if storey else 0,
                      "windows": len(storey.windows) if storey else 0,
                      "furniture": len(storey.furniture) if storey else 0},
            "painted": D.painted(design, level)}


@bp.route("/api/builder")
def api_builder():
    """What can be drawn: the rooms, the kinds of building, the wall styles.

    The rooms are ordered by what is being built, so asking for a police
    station gets its cells and its gun store first, which is why the kind is
    a query rather than part of one fixed list.
    """
    from knoxbuild import designer as D
    from knoxbuild import presets as P

    kind = (request.args.get("kind") or "").strip().lower()
    return jsonify({"kinds": P.kinds(), "rooms": D.room_kinds(kind or None),
                    "styles": D.style_choices(kind or None),
                    "use": sorted(P.using(BASE_DIR)),
                    "limits": {"minSide": D.MIN_SIDE, "maxSide": D.MAX_SIDE,
                               "maxStoreys": D.MAX_STOREYS},
                    "presets": [{k: v for k, v in entry.items() if k != "file"}
                                for entry in P.library(BASE_DIR)]})


@bp.route("/api/builder/preview", methods=["POST"])
def api_builder_preview():
    body = _json_body()
    try:
        return jsonify(_builder_reply(body.get("design"),
                                      int(body.get("level") or 0)))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"That design could not be drawn: {exc}"}), 400
    except Exception as exc:                      # noqa: BLE001 - reported
        return failed(f"That design could not be built: {exc}", 500, exc)


@bp.route("/api/builder/autofill", methods=["POST"])
def api_builder_autofill():
    """The rooms the generator would have cut, to start from or to change."""
    from knoxbuild import designer as D

    body = _json_body()
    try:
        filled = D.autofill(body.get("design"))
        return jsonify(_builder_reply(filled, int(body.get("level") or 0)))
    except Exception as exc:                      # noqa: BLE001 - reported
        return failed(f"Nothing could be laid out there: {exc}", 500, exc)


@bp.route("/api/builder/save", methods=["POST"])
def api_builder_save():
    """Keep a drawing as a preset: the .tbx, and the drawing beside it."""
    from knoxbuild import designer as D
    from knoxbuild import presets as P

    body = _json_body()
    design = body.get("design")
    design = design if isinstance(design, dict) else {}
    name = body.get("name") or design.get("name") or ""
    try:
        about = D.keep(BASE_DIR, name, design)
    except (ValueError, OSError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:                      # noqa: BLE001 - reported
        return failed(f"That design could not be saved: {exc}", 500, exc)
    return jsonify({"saved": {k: v for k, v in about.items() if k != "file"},
                    "presets": [{k: v for k, v in e.items() if k != "file"}
                                for e in P.library(BASE_DIR)]})


@bp.route("/api/builder/design/<name>")
def api_builder_design(name: str):
    """A saved drawing, to open and change again."""
    from knoxbuild import designer as D

    design = D.load_design(BASE_DIR, name)
    if design is None:
        return jsonify({"error": "There is no drawing saved for that preset. "
                                 "It can still be used as it is."}), 404
    return jsonify(_builder_reply(design, 0))


@bp.route("/api/builder/use", methods=["POST"])
def api_builder_use():
    """Switch hand-built buildings on or off for one kind of building."""
    from knoxbuild import presets as P

    body = _json_body()
    try:
        P.set_use(BASE_DIR, body.get("kind") or "", bool(body.get("on")))
    except (ValueError, OSError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"use": sorted(P.using(BASE_DIR))})


@bp.route("/api/builder/kind", methods=["POST"])
def api_builder_kind():
    """Say what an existing preset stands in for."""
    from knoxbuild import presets as P

    body = _json_body()
    try:
        kind = P.set_kind(BASE_DIR, body.get("name") or "", body.get("kind") or "")
    except (ValueError, OSError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"kind": kind,
                    "presets": [{k: v for k, v in e.items() if k != "file"}
                                for e in P.library(BASE_DIR)]})


# ---- saved areas ----------------------------------------------------------------
#
# An area with the scale and settings it was made with, kept by name so a town
# can be come back to without drawing it and setting everything up again. One
# file next to the program, written whole each time through a temporary file so
# a crash cannot leave half of it.
PRESETS_FILE = BASE_DIR / "presets.json"
_PRESETS_LOCK = threading.Lock()
MAX_PRESETS = 200
MAX_PRESET_POINTS = 5000


class PresetsUnreadableError(Exception):
    """Raised when presets.json exists but cannot be read or parsed."""


def _backup_file():
    return PRESETS_FILE.with_suffix(".json.bak")


def _read_presets() -> dict:
    if not PRESETS_FILE.exists():
        return {}
    try:
        with open(PRESETS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        raise PresetsUnreadableError(
            "Saved areas file could not be read.") from exc
    if not isinstance(data, dict):
        raise PresetsUnreadableError("Saved areas file is not a JSON object.")
    return data


def _write_presets(presets: dict) -> None:
    bak = _backup_file()
    if PRESETS_FILE.exists():
        try:
            with open(PRESETS_FILE, encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                bak_tmp = bak.with_suffix(".bak.tmp")
                with open(bak_tmp, "w", encoding="utf-8") as bf:
                    json.dump(existing, bf, indent=2, ensure_ascii=False)
                os.replace(bak_tmp, bak)
        except (OSError, ValueError):
            pass
    tmp = PRESETS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PRESETS_FILE)
    if not bak.exists():
        bak_tmp = bak.with_suffix(".bak.tmp")
        with open(bak_tmp, "w", encoding="utf-8") as bf:
            json.dump(presets, bf, indent=2, ensure_ascii=False)
        os.replace(bak_tmp, bak)


def _unreadable_response():
    return jsonify({
        "error": "Saved areas file could not be read. Nothing was overwritten.",
        "corrupt": True,
        "hasBackup": _backup_file().exists(),
    }), 500


def _count_points(shape: dict) -> int:
    def walk(c):
        if c and isinstance(c[0], (int, float)):
            return 1
        return sum(walk(x) for x in c)
    return walk(shape.get("coordinates") or [])


def _validate_area(data: dict, *, default_scale: float | None = None,
                   require_settings: bool = True) -> tuple[dict | None, str | None]:
    """Shared validator for both local saved areas and exported presets."""
    import math
    if not isinstance(data, dict):
        return None, "Area data must be a JSON object."
    name = str(data.get("name") or "").strip()[:60]
    if not name:
        return None, "Give the area a name."
    try:
        south, west, north, east = (float(data[key]) for key in
                                   ("south", "west", "north", "east"))
        raw_scale = data.get("metersPerTile", default_scale)
        if raw_scale is None:
            return None, "The preset needs a valid area and scale."
        scale = float(raw_scale)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, "Draw a valid area and scale first."
    if not all(math.isfinite(n) for n in (south, west, north, east, scale)):
        return None, "The area coordinates or scale are not valid numbers."
    if not (-85.05 <= south < north <= 85.05) or not (-180 <= west < east <= 180):
        return None, ("The area must have non-zero width and height between "
                      "-85.05° and 85.05° latitude and -180° to 180° longitude.")
    if not MIN_METERS_PER_TILE <= scale <= MAX_METERS_PER_TILE:
        return None, (f"Scale must be between {MIN_METERS_PER_TILE} and "
                      f"{MAX_METERS_PER_TILE} m per tile.")
    shape = data.get("shape")
    if shape is not None:
        if not isinstance(shape, dict):
            return None, "The area outline is not a polygon."
        try:
            if _count_points(shape) > MAX_PRESET_POINTS:
                return None, f"An area outline can hold at most {MAX_PRESET_POINTS:,} points."
            shape, problem = _clean_shape(shape)
            if problem:
                return None, problem
            for ring in _shape_rings(shape):
                if any(not (math.isfinite(lon) and math.isfinite(lat)
                            and west - 1e-5 <= lon <= east + 1e-5
                            and south - 1e-5 <= lat <= north + 1e-5)
                       for lon, lat in ring):
                    return None, "The area outline falls outside its bounding box."
                # _wrap_lon can turn 20.01 into 20.00999999999999. Keep
                # share files stable across repeated imports and exports.
                for point in ring:
                    point[0], point[1] = round(point[0], 12), round(point[1], 12)
        except (TypeError, ValueError, OverflowError, RecursionError):
            return None, "The area outline could not be read."
    given = data.get("settings")
    if require_settings:
        if not isinstance(given, dict):
            return None, "The preset needs map settings."
    elif not isinstance(given, dict):
        given = {}
    kind = data.get("preset") or given.get("preset")
    if not isinstance(kind, str) or kind not in PRESETS:
        kind = None
    return {
        "name": name,
        "south": south, "west": west, "north": north, "east": east,
        "metersPerTile": tidy_scale(scale),
        "shape": shape, "preset": kind,
        "settings": Settings.from_dict({**given, **({"preset": kind} if kind else {})}).to_dict(),
    }, None


def _portable_preset(data: dict) -> tuple[dict | None, str | None]:
    """Check a shared area before it enters the map widget or leaves this PC."""
    if not isinstance(data, dict) or data.get("format") != "knoxmap-preset" or data.get("version") != 1:
        return None, "This is not a KnoxMap preset version 1."
    area, problem = _validate_area(data, require_settings=True)
    if problem:
        return None, problem
    return {"format": "knoxmap-preset", "version": 1, **area}, None


@bp.route("/api/presets/validate", methods=["POST"])
def api_preset_validate():
    preset, problem = _portable_preset(_json_body())
    return (jsonify({"error": problem}), 400) if problem else jsonify({"preset": preset})


@bp.route("/api/presets/export", methods=["POST"])
def api_preset_export():
    """Download JSON in a browser; save beside KnoxMap in the desktop window."""
    preset, problem = _portable_preset(_json_body())
    if problem:
        return jsonify({"error": problem}), 400
    payload = (json.dumps(preset, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", preset["name"]).strip("_") or "area"
    filename = f"{safe}.knoxmap.json"
    if os.environ.get("KNOXMAP_WINDOW") == "1":
        folder = BASE_DIR / "preset_exports"
        try:
            folder.mkdir(exist_ok=True)
            target = folder / filename
            if target.exists():
                target = folder / f"{safe}_{time.time_ns()}.knoxmap.json"
            target.write_bytes(payload)
        except OSError as exc:
            return failed(f"Could not export the preset: {exc}", 500, exc)
        knoxlog.open_folder(target)
        return jsonify({"name": target.name, "folder": str(folder)})
    return send_file(io.BytesIO(payload), mimetype="application/json", as_attachment=True,
                     download_name=filename)


@bp.route("/api/presets", methods=["GET", "POST"])
def api_presets():
    """GET lists the saved areas; POST saves one under a name, replacing any
    already called that."""
    if request.method == "GET":
        with _PRESETS_LOCK:
            try:
                presets = _read_presets()
            except PresetsUnreadableError:
                return _unreadable_response()
        return jsonify({"presets": sorted(presets.values(),
                                          key=lambda p: p["name"].lower())})
    area, problem = _validate_area(_json_body(), default_scale=1.0,
                                   require_settings=False)
    if problem:
        return jsonify({"error": problem}), 400
    entry = {**area, "saved": int(time.time())}
    with _PRESETS_LOCK:
        try:
            presets = _read_presets()
        except PresetsUnreadableError:
            return _unreadable_response()
        if area["name"] not in presets and len(presets) >= MAX_PRESETS:
            return jsonify({"error": f"That is {MAX_PRESETS} saved areas. Delete "
                                     f"one first."}), 400
        presets[area["name"]] = entry
        try:
            _write_presets(presets)
        except OSError as exc:
            return failed(f"Could not save the area: {exc}", 500, exc)
    return jsonify({"saved": entry})


@bp.route("/api/presets/restore", methods=["POST"])
def api_presets_restore():
    """Restore the last readable backup of saved areas when presets.json is damaged."""
    with _PRESETS_LOCK:
        bak = _backup_file()
        if not bak.exists():
            return jsonify({"error": "No backup of saved areas was found."}), 404
        try:
            with open(bak, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            return failed(f"Could not read backup: {exc}", 500, exc)
        if not isinstance(data, dict):
            return jsonify({"error": "The backup file is not a valid saved areas object."}), 500
        if PRESETS_FILE.exists():
            try:
                os.replace(PRESETS_FILE, PRESETS_FILE.with_suffix(".json.broken"))
            except OSError:
                pass
        try:
            _write_presets(data)
        except OSError as exc:
            return failed(f"Could not restore saved areas: {exc}", 500, exc)
    return jsonify({"presets": sorted(data.values(),
                                      key=lambda p: p["name"].lower())})


@bp.route("/api/presets/<path:name>", methods=["DELETE"])
def api_preset_delete(name: str):
    with _PRESETS_LOCK:
        try:
            presets = _read_presets()
        except PresetsUnreadableError:
            return _unreadable_response()
        if name not in presets:
            return jsonify({"error": "No saved area has that name."}), 404
        del presets[name]
        try:
            _write_presets(presets)
        except OSError as exc:
            return failed(f"Could not delete the area: {exc}", 500, exc)
    return jsonify({"deleted": name})
