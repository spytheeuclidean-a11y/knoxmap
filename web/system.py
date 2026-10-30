"""The window's own housekeeping: error and problem reports, language files, setup
and health checks, the settings the page reads, Steam libraries and installing a map.
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

import knoxlog
from generator import osm
from knoxbuild import mapstate
from knoxbuild.settings import PRESETS, Settings

from web import common
from web.checks import (BASE_BYTES, BUILD_BASE_BYTES, BUILD_BYTES_PER_TILE,
                        BYTES_PER_TILE, RENDER_SETTINGS)
from web.common import BASE_DIR, SAFE_NAME, _json_body, _map_dir, failed, log
from web.mapfiles import _load_settings

bp = Blueprint("system", __name__)

# Room to keep free on the drive after an install, beyond the map's own files.
INSTALL_MARGIN_BYTES = 100 * 2**20


@bp.route("/api/client-error", methods=["POST"])
def api_client_error():
    """Errors in the page itself, sent by the script in static/js/app.js."""
    data = _json_body()
    if not (str(data.get("message") or "").strip()
            or str(data.get("stack") or "").strip()):
        return jsonify({"errorId": None})  # nothing to report, nothing to log
    eid = knoxlog.error_id()
    log.error("%s page error: %s\n  at %s\n%s", eid,
              str(data.get("message", ""))[:500], str(data.get("where", ""))[:300],
              str(data.get("stack", ""))[:4000])
    return jsonify({"errorId": eid})


@bp.route("/api/report")
def api_report():
    """A zip of the logs and a description of the PC, for #bug-reports."""
    log.info("problem report downloaded")
    stamp = time.strftime("%Y%m%d-%H%M")
    return send_file(io.BytesIO(knoxlog.report_zip(common.OUTPUT_DIR)), mimetype="application/zip",
                     as_attachment=True, download_name=f"KnoxMap-report-{stamp}.zip")


@bp.route("/api/report-save", methods=["POST"])
def api_report_save():
    """The same zip, saved into logs/ and shown in Explorer: the app window is
    not a browser, and has nowhere to put a download."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = knoxlog.LOG_DIR / f"KnoxMap-report-{stamp}.zip"
    knoxlog.LOG_DIR.mkdir(exist_ok=True)
    path.write_bytes(knoxlog.report_zip(common.OUTPUT_DIR))
    log.info("problem report saved: %s", path.name)
    knoxlog.open_folder(path)
    return jsonify({"name": path.name, "path": str(path)})


# ---- the window in another language ---------------------------------------------
#
# lang/english.txt lists every line the window says. Copy it to lang/<language>
# .txt, translate the right of each "=", and the language appears in the menu at
# the top - no code, no rebuild. tools/make_lang_template.py writes the English
# one from the page itself.

LANG_DIR = BASE_DIR / "lang"


def _language_strings(path: Path) -> dict:
    """The translated lines of one language file, English -> theirs."""
    out = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        english, _, theirs = line.partition("=")
        english, theirs = english.strip(), theirs.strip()
        # A line left as the English is simply not translated.
        if english and theirs and english != theirs:
            out[english] = theirs
    return out


@bp.route("/api/languages")
def api_languages():
    files = sorted(LANG_DIR.glob("*.txt")) if LANG_DIR.is_dir() else []
    import knoxpaths
    return jsonify({
        "languages": [{"file": f.stem, "name": f.stem[:1].upper() + f.stem[1:],
                       "lines": len(_language_strings(f))} for f in files],
        "current": knoxpaths.load_config().get("language", "english"),
        "folder": str(LANG_DIR),
    })


@bp.route("/api/language/<name>", methods=["GET", "POST"])
def api_language(name: str):
    """One language's lines, and - on POST - the one to open with next time."""
    import knoxpaths

    safe = SAFE_NAME.sub("_", name).strip("_").lower()
    path = (LANG_DIR / f"{safe}.txt")
    if safe != "english" and not path.is_file():
        return failed(f"No lang/{safe}.txt. Copy lang/english.txt and translate it.", 404)
    if request.method == "POST":
        knoxpaths.update_config({"language": safe})
        log.info("language set to %s", safe)
    return jsonify({"file": safe, "strings": _language_strings(path) if path.is_file() else {}})


@bp.route("/api/open-logs", methods=["POST"])
def api_open_logs():
    return jsonify({"opened": knoxlog.open_folder(), "folder": str(knoxlog.LOG_DIR)})


@bp.route("/api/setup-status")
def api_setup_status():
    return jsonify(_setup_report())


def _setup_report() -> dict:
    """What is installed, so the page can say exactly what is missing.

    Drawing terrain needs nothing but this app. Buildings need nothing more.
    Compiling needs the map tools and the patched compiler, and the tools need
    tile artwork extracted from the player's own game. Each gap says how to
    close it, instead of a compile failing later with a message about a
    missing executable.
    """
    import knoxpaths

    tools = knoxpaths.mapping_tools_dir()
    cli = knoxpaths.worlded_cli()
    game = knoxpaths.pz_install_dir()
    setup = knoxpaths.setup_command()
    tiles = 0
    if tools and (tools / "Tiles" / "2x").is_dir():
        tiles = sum(1 for _ in (tools / "Tiles" / "2x").glob("*.png"))
    checks = [
        {"id": "tools", "ok": bool(tools), "label": "PZ Mapping Tools",
         "fix": f"Run {setup} to download them."},
        {"id": "compiler", "ok": bool(cli), "label": "Patched map compiler",
         "fix": f"Run {setup}, or compile by hand with Open in WorldEd."},
        {"id": "game", "ok": bool(game), "label": "Project Zomboid install",
         "fix": ("Put the folder your Steam games are in under Steam libraries "
                 f"above - the game's own folder works too - or run {setup} and "
                 "paste the path when it asks."
                 + (" On a Mac the game lives inside ProjectZomboid.app; that "
                    "path is fine, and so is anything above it."
                    if sys.platform == "darwin" else "")
                 + f" If it is not installed yet, install it and run {setup} again.")},
        {"id": "build42", "ok": knoxpaths.is_build42(game),
         "label": "Project Zomboid Build 42",
         "fix": "Your game looks like Build 41. In Steam choose the Build 42 "
                "(unstable) branch under Properties > Betas."},
        # A 32-bit Python can only use about 2 GB, and a town-sized map needs
        # more: it fails part-way through with "MemoryError".
        {"id": "python64", "ok": sys.maxsize > 2 ** 32, "label": "64-bit Python",
         "fix": "KnoxMap is running 32-bit Python, which can only use about 2 GB of "
                "memory, so anything past a few square kilometres fails. Close KnoxMap "
                f"and run {setup} again: it fetches a 64-bit Python."},
        {"id": "python_library", "ok": not _missing_from_python(),
         "label": "Python's own library",
         "fix": ("This Python is missing "
                 + ", ".join(_missing_from_python()[:3])
                 + ", which comes with Python itself and cannot be installed "
                 "with pip - something has trimmed or removed part of it, "
                 "which antivirus software sometimes does. Close KnoxMap, "
                 "delete the .venv folder beside it (and .python if there is "
                 f"one), then run {setup} again to build a fresh one. If it "
                 "keeps happening, install Python from python.org and run "
                 "Setup once more.")},
        {"id": "tiles", "ok": tiles >= 400, "label": "Tile artwork from your game",
         "fix": f"Run {setup} to extract it from your install."},
        # Added to the tools after KnoxMap 1.0's first setups: without them a
        # compile still works but lays no kerbs or road markings, silently.
        {"id": "road_rules", "ok": _has_road_rules(tools), "label": "Kerbs and road markings",
         "fix": f"Run {setup} again to add them to the map tools."},
        # Likewise the big trees, and the tree sizes beside them: without
        # these rules a map still builds, and its woods are undergrowth.
        {"id": "tree_rules", "ok": _has_tree_rules(tools), "label": "Big trees",
         "fix": f"Run {setup} again to add them to the map tools."},
    ]
    # Off Windows the compiler is either one built for this system - what
    # Setup fetches on Linux, and nothing else is needed for it - or the
    # Windows build through Wine, which a PC playing Project Zomboid through
    # Proton already has, though not always on the path. Everything but
    # Compile works either way.
    if os.name != "nt":
        checks.append(
            {"id": "wine", "ok": knoxpaths.tools_runnable(),
             "label": "A map compiler that runs here",
             "fix": f"Run {setup} again to fetch the compiler built for this system. "
                    "If there is none for it, the map tools' Windows build needs Wine: "
                    "install it with your package manager (apt install wine, pacman -S "
                    "wine, dnf install wine), or set KNOXMAP_WINE to the build you want "
                    "used. Everything except Compile works without either."})
    optional = [
        {"id": "elevators", "ok": knoxpaths.elevators_mod_installed(),
         "label": "Elevators mod (optional)",
         "fix": "Subscribe to it on the Steam Workshop for working lifts in tall buildings."},
        {"id": "spawn_selector", "ok": knoxpaths.spawn_selector_installed(),
         "label": "Spawn Selector mod (optional)",
         "fix": "Subscribe to it on the Steam Workshop to start at any landmark of your map."},
        {"id": "overture", "ok": _overture_ready(),
         "label": "Overture Maps data (optional)",
         "fix": "Needed only for Fill gaps from Overture, which adds the buildings "
                "OpenStreetMap has not got. Install DuckDB into the Python inside "
                "KnoxMap's own .venv folder: python -m pip install duckdb. Worth it "
                "where your town is half missing from OSM; nothing else needs it."},
        {"id": "room_solver", "ok": _ortools_ready(),
         "label": "OR-Tools (optional)",
         "fix": "Needed only for Planned house rooms, which lays each house out whole "
                "with a constraint solver. Install it into the Python inside KnoxMap's "
                "own .venv folder: python -m pip install ortools. Nothing else needs it."},
        {"id": "erikas_tiles", "ok": knoxpaths.erikas_tiles_ready(),
         "label": "Erika's Tiles (optional)",
         "fix": f"Subscribe to it on the Steam Workshop and run {setup} again for glass shop "
                "fronts and signs, street signs, and far more varied pictures, posters and "
                "plants. Maps made with it require it."},
    ]
    return {"ready": all(c["ok"] for c in checks), "checks": checks,
            "optional": optional, "setupCommand": setup,
            "mods_dir": str(knoxpaths.zomboid_user_dir() / "mods")}


def _resources() -> dict:
    """What this PC can hold, in the units the window plans maps in.

    The areas are what fits at 1 m a tile with 80% of the memory that is free
    right now, using the same per-tile figures the warnings do; the real limit
    moves with whatever else is open.
    """
    import shutil

    from tools.compile_map import default_workers

    out: dict = {"cores": os.cpu_count() or 0, "python64": sys.maxsize > 2 ** 32,
                 "compileWorkers": default_workers()}
    status = knoxlog.memory_status()
    if status:
        total, free, room = status
        usable = min(free, room) * 0.8
        out.update(ramTotalGB=round(total / 1e9, 1), ramFreeGB=round(free / 1e9, 1),
                   drawKm2=max(0, round((usable - BASE_BYTES) / BYTES_PER_TILE / 1e6)),
                   buildKm2=max(0, round((usable - BUILD_BASE_BYTES)
                                         / BUILD_BYTES_PER_TILE / 1e6)))
    try:
        out["diskFreeGB"] = round(shutil.disk_usage(common.OUTPUT_DIR).free / 1e9, 1)
    except OSError:
        pass
    return out


@bp.route("/api/health")
def api_health():
    """The setup checks, what the PC can hold, and (when asked) whether the
    OpenStreetMap servers are answering. The last is a network round trip, so
    only `?network=1` makes it."""
    report = _setup_report()
    report["resources"] = _resources()
    if request.args.get("network") == "1":
        from concurrent import futures

        def one(endpoint: str) -> dict:
            t0 = time.time()
            ok = osm._probe(endpoint, 40.0, -74.0)
            return {"host": endpoint.split("/")[2], "ok": ok,
                    "seconds": round(time.time() - t0, 1)}

        with futures.ThreadPoolExecutor(max_workers=len(osm.OVERPASS_ENDPOINTS)) as pool:
            report["overpass"] = list(pool.map(one, osm.OVERPASS_ENDPOINTS))
    return jsonify(report)


@bp.route("/api/steam-libraries", methods=["GET", "POST"])
def api_steam_libraries():
    """The Steam libraries KnoxMap looks in for the game and Workshop mods:
    found on their own, plus the drives or folders the player chose."""
    import knoxpaths

    if request.method == "POST":
        sent = _json_body().get("folders")
        folders = [str(f).strip().strip('"')
                   for f in (sent if isinstance(sent, (list, tuple)) else [])
                   if str(f).strip()]
        bad = [f for f in folders if not knoxpaths.library_of(f)]
        if bad:
            return jsonify({"error": f"No Steam library found in {', '.join(bad)}. Name the drive "
                                     "(E:) or the folder that holds steamapps."}), 400
        knoxpaths.save_steam_folders(folders)
        log.info("steam folders chosen: %s", folders)
    return jsonify({"libraries": knoxpaths.steam_libraries_found(),
                    "chosen": knoxpaths.load_config().get("steam_folders", []),
                    "game": str(knoxpaths.pz_install_dir() or "")})


@bp.route("/api/zomboid-folder", methods=["GET", "POST"])
def api_zomboid_folder():
    """The Zomboid folder maps are installed into (its mods folder). An empty
    folder in a POST goes back to the default, ~/Zomboid."""
    import knoxpaths

    if request.method == "POST":
        folder = str(_json_body().get("folder") or "").strip().strip('"')
        if folder:
            try:
                (Path(folder).expanduser() / "mods").mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return jsonify({"error": f"Cannot use {folder}: {e}"}), 400
        knoxpaths.update_config({"zomboid_dir": folder})
        log.info("zomboid folder chosen: %s", folder or "(default)")
    return jsonify({"folder": str(knoxpaths.zomboid_user_dir()),
                    "mods": str(knoxpaths.zomboid_user_dir() / "mods"),
                    "chosen": bool(knoxpaths.load_config().get("zomboid_dir"))})


# Parts of Python itself that KnoxMap cannot do without: the .tbx and paper
# map readers (xml), the compressed download beside each map (zlib), the
# release downloads (ssl, zipfile, tarfile, hashlib) and the Windows folder
# lookups (ctypes). pip cannot put any of them back - they come with Python -
# so a copy that is missing one has to be mended or replaced, and saying
# which one it is turns "No module named 'xml.etree.ElementTree'" halfway
# through a build into something a person can act on.
NEEDED_FROM_PYTHON = ("xml.etree.ElementTree", "xml.sax.saxutils", "zlib",
                      "hashlib", "zipfile", "tarfile", "struct", "socket",
                      "ssl", "ctypes", "unicodedata")


def _missing_from_python() -> list[str]:
    """Which of them this Python cannot import, in the order above."""
    import importlib.util

    missing = []
    for name in NEEDED_FROM_PYTHON:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            missing.append(name)
    return missing


def _has_road_rules(tools) -> bool:
    if not tools:
        return False
    rules = tools / "config" / "Rules.txt"
    try:
        text = rules.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    # The newest rule, so tools patched before street furniture existed are
    # sent back through Setup - and no blank litter tile, so are the ones
    # patched while the litter rule still named trash_01_13 and 14, which the
    # game draws as a question mark.
    return "KnoxMap road Yard bed_soil" in text and "trash_01_13" not in text


def _has_tree_rules(tools) -> bool:
    """Whether the tools place big trees, and trees the game grows.

    Two things, one answer, because one run of Setup writes both: the rules
    for the jumbo sheets, and ordinary trees moved off the sheet indices the
    game has no tile definition for - which drew, and were scenery.
    """
    if not tools:
        return False
    try:
        text = (tools / "config" / "Rules.txt").read_text(encoding="utf-8",
                                                          errors="replace")
    except OSError:
        return False
    import re
    return ("KnoxMap tree Giant tree" in text and "KnoxMap tree Small tree" in text
            and not re.search(r"\be_\w+_1_(?:[89]|1[0-5])\b", text))


def _overture_ready() -> bool:
    """Whether gap-filling from Overture can run here. Kept off the import
    path: the check is one import and the window asks for it on every poll."""
    try:
        from generator import overture
        return overture.available()
    except Exception:  # noqa: BLE001 - a broken optional extra is just absent
        return False


def _ortools_ready() -> bool:
    """Whether the room solver (Settings.room_solver) can run here."""
    import importlib.util
    try:
        return importlib.util.find_spec("ortools") is not None
    except (ImportError, ValueError):
        return False


@bp.route("/api/settings")
def api_settings():
    """The knobs, their limits, and the presets - so the page is not a
    hard-coded copy of them that drifts out of step."""
    from knoxbuild.settings import LIMITS, BUILDING_ALIGNMENT_OPTIONS

    map_dir = _map_dir(request.args.get("map", ""))
    current = _load_settings(map_dir) if map_dir else Settings()
    from dataclasses import fields

    return jsonify({
        "current": current.to_dict(),
        "defaults": Settings().to_dict(),
        # Which of them need the map drawing again, rather than only the
        # buildings laying out again.
        "renderKeys": RENDER_SETTINGS,
        # JSON writes 1.0 as 1, so the page cannot tell a float whose default
        # happens to be whole from an int - and a woodland slider built as an
        # integer can only reach 0, 1, 2 or 3. Say which is which.
        "types": {f.name: ("enum" if f.name in ("building_alignment", "arch_style",
                                                "height_mix")
                           else "int" if f.type in (int, "int") else "float")
                  for f in fields(Settings)},
        "options": {
            "building_alignment": [
                [value, value.capitalize()]
                for value in BUILDING_ALIGNMENT_OPTIONS],
            "arch_style": [["auto", "Auto"], ["cn", "Chinese"], ["off", "Default"]],
            "straight_roads": [[0, "As mapped"], [1, "Knox County straight"],
                               [2, "Vanilla curves"], [3, "Vanilla curves, built-up streets square"]],
            "height_mix": [["auto", "As the place is"],
                           ["low", "Mostly low, a few taller"],
                           ["middle", "Mostly middling"],
                           ["tall", "Mostly tall, a few smaller"],
                           ["even", "Every height equally"]],
        },
        "limits": {k: list(v) for k, v in LIMITS.items()},
        "presets": {name: s.to_dict() for name, s in PRESETS.items()},
    })


@bp.route("/api/install", methods=["POST"])
def api_install():
    """Package the compiled map into ~/Zomboid/mods."""
    from knoxbuild import placement as P
    from tools import make_map_mod

    data = _json_body()
    map_dir = _map_dir(data.get("mapName", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    # A map moved since it was compiled would ship cells named for where it
    # used to be and a paper map pointing where it is now, which is a map the
    # game loads as two halves of different places.
    where = P.saved(str(map_dir)) or P.project_origin(str(map_dir), map_dir.name)
    if not P.lots_match(str(map_dir), where):
        return jsonify({"error": "This map has been moved since it was last "
                                 "compiled. Compile it again, then install."}), 400
    # Both end up in folder names and mod.info, so they are text of a sane
    # length whatever the page sent.
    raw_title, raw_id = data.get("title"), data.get("modId")
    # An update names neither: it goes back in as what is installed now.
    before = mapstate.installed(str(map_dir)) or {}
    raw_title = raw_title or before.get("title")
    raw_id = raw_id or before.get("modId")
    title = (raw_title if isinstance(raw_title, str) and raw_title.strip()
             else map_dir.name).strip()[:80]
    mod_id = SAFE_NAME.sub("_", raw_id if isinstance(raw_id, str) and raw_id.strip()
                           else map_dir.name).strip("_")[:60] or map_dir.name[:60]
    # The mod takes about as much room as the cells it copies. Say so before
    # the copy starts, rather than fail part-way with the drive full. An old
    # copy being replaced is not counted: that is the conservative side.
    mods_dir = make_map_mod.default_mods_dir()
    need = make_map_mod.install_size(str(map_dir))
    free = make_map_mod.free_bytes(mods_dir)
    if free < need + INSTALL_MARGIN_BYTES:
        return jsonify({"error": f"Not enough room in {mods_dir} for this map: it needs about "
                                 f"{need // 2**20} MB and {free // 2**20} MB is free. Choose a "
                                 "folder with more room under Where maps are installed, or free "
                                 "some space."}), 400
    try:
        mod_root, n_cells, extras = make_map_mod.package(
            str(map_dir), title, mod_id)
    except FileNotFoundError as exc:
        return failed(str(exc), 400, exc)
    except Exception as exc:
        return failed(f"Install failed: {exc}", 500, exc)
    mapstate.stamp(str(map_dir), "install")
    mapstate.record_install(str(map_dir), str(mod_root), mod_id, title)
    log.info("install %s: %d cells as %s, extras %s", map_dir.name, n_cells, mod_id, extras)
    return jsonify({"modRoot": str(mod_root), "cells": n_cells,
                    "extras": extras, "modId": mod_id, "title": title})


@bp.route("/api/uninstall", methods=["POST"])
def api_uninstall():
    """Take an installed map out of the game's mods folder. Only the mod folder
    KnoxMap installed this map into is removed; the map's own files and the
    player's saves are left alone."""
    from tools import make_map_mod

    map_dir = _map_dir(_json_body().get("mapName", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    rec = mapstate.installed(str(map_dir))
    if rec is None:
        return jsonify({"error": "This map is not installed."}), 404
    mod_root = Path(rec["modRoot"]).resolve()
    # Checked again here, not just trusted from the record: a folder that is
    # not a KnoxMap mod is never deleted, whatever the record says.
    try:
        info = (mod_root / "mod.info").read_text(encoding="utf-8", errors="replace")
    except OSError:
        info = ""
    if mod_root.parent.name != "mods" or "generated from real-world map data with KnoxMap" not in info:
        return jsonify({"error": f"{mod_root} does not look like a KnoxMap map, so it was "
                                 "left alone."}), 400
    try:
        make_map_mod._clear_folder(str(mod_root))
    except RuntimeError as exc:
        return failed(str(exc), 500, exc)
    mapstate.forget_install(str(map_dir))
    log.info("uninstall %s: removed %s", map_dir.name, mod_root)
    return jsonify({"removed": str(mod_root)})


@bp.route("/api/workshop-check")
def api_workshop_check():
    """Is the installed map fit to publish? Reads the mod folder and uploads
    nothing; see tools/workshop_check.py."""
    from tools import make_map_mod, workshop_check

    mod_id = SAFE_NAME.sub("_", request.args.get("modId", "")).strip("_")[:60]
    if not mod_id:
        return jsonify({"error": "Give the mod id."}), 400
    map_dir = _map_dir(request.args.get("map", ""))
    results = workshop_check.check(os.path.join(make_map_mod.default_mods_dir(), mod_id),
                                   str(map_dir) if map_dir else None)
    return jsonify({"results": results, **workshop_check.summary(results)})
