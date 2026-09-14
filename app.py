"""Knoxify — Flask entry point.

Real-world areas → Project Zomboid maps.

Run:
    source .venv/bin/activate
    python app.py

Then open http://127.0.0.1:5000/ in a browser.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import threading
import time
import zipfile
from pathlib import Path

from flask import (Flask, jsonify, render_template, request, send_file,
                   send_from_directory)

from generator import osm, places, renderer
from knoxbuild.settings import PRESETS, Settings

# Builds print place names in any script; a console on a legacy code page
# would raise mid-request on the first one it cannot show.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")

# Safety rails. The area cap used to be 20 km² because one Overpass query that
# size is about all the API will answer; osm.fetch_features_tiled lifts that by
# splitting a big request into a grid of small ones, so the real limits now are
# render memory and patience.
#
# MAX_TILES_PER_SIDE is the memory rail: the renderer holds a landscape and a
# vegetation image at full size, 3 bytes a tile each, so 9000 tiles a side is
# about 490 MB of pixels before anything else. Raise it only with RAM to match.
MAX_AREA_KM2 = 400.0
OVERPASS_TILE_KM2 = 30.0       # size of each sub-query; overshoot re-splits
MAX_TILES_PER_SIDE = 9000      # 30 cells at 300 tiles each
MIN_METERS_PER_TILE = 0.5
MAX_METERS_PER_TILE = 8.0

# Landmark lookup asks for far more tag keys than the terrain query, so it stays
# on a tighter leash.
MAX_LANDMARK_KM2 = 40.0

SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")

# Source cells per side handed to one WorldEd process. 4x4 keeps its peak
# memory around a gigabyte; larger batches are faster per cell but climb.
COMPILE_BATCH = 4

# Big maps take minutes, so generation reports where it has got to and the page
# polls /api/progress. Keyed by map name; the generate call owns its entry.
_PROGRESS: dict[str, dict] = {}
_COMPILE: dict[str, dict] = {}
_PROGRESS_LOCK = threading.Lock()


def _set_progress(map_name: str, **fields) -> None:
    with _PROGRESS_LOCK:
        _PROGRESS.setdefault(map_name, {}).update(fields)


@app.route("/api/progress")
def api_progress():
    with _PROGRESS_LOCK:
        return jsonify(_PROGRESS.get(request.args.get("map", ""), {}))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search")
def api_search():
    """Find a place by name, so the map can jump to it."""
    q = request.args.get("q", "")
    if not q.strip():
        return jsonify({"results": []})

    viewbox = None
    try:
        viewbox = (float(request.args["south"]), float(request.args["west"]),
                   float(request.args["north"]), float(request.args["east"]))
    except (KeyError, ValueError):
        pass
    bounded = request.args.get("bounded") == "1"

    try:
        results = places.search(q, viewbox=viewbox, bounded=bounded)
    except Exception as exc:  # network, rate limit, bad JSON
        return jsonify({"error": f"Search failed: {exc}"}), 502
    return jsonify({"results": results})


@app.route("/api/landmarks", methods=["POST"])
def api_landmarks():
    """List the named landmarks inside a bbox."""
    data = request.get_json(silent=True) or {}
    try:
        south = float(data["south"])
        west = float(data["west"])
        north = float(data["north"])
        east = float(data["east"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Need south, west, north and east."}), 400

    if _bbox_area_km2(south, west, north, east) > MAX_LANDMARK_KM2:
        return jsonify({"error": f"Landmark lookup is limited to {MAX_LANDMARK_KM2:g} km² — zoom in or draw a smaller box."}), 400

    try:
        found = places.landmarks(south, west, north, east)
    except Exception as exc:
        return jsonify({"error": f"Lookup failed: {exc}"}), 502
    return jsonify({"landmarks": found})


def _wrap_lon(lon: float) -> float:
    """Fold a longitude back into -180..180."""
    return (lon + 180.0) % 360.0 - 180.0


def _normalise_bbox(south: float, west: float, north: float,
                    east: float) -> tuple[tuple[float, float, float, float],
                                          str | None]:
    """Clean a bbox from the map widget, or say why it cannot be used.

    Leaflet hands back *unwrapped* coordinates once the map has been panned
    across a world copy: drag east past the date line twice and a rectangle
    over Bergama arrives as longitude 747.17 rather than 27.17. It passes
    west < east and it passes the area check, because the span is still small -
    and then every Overpass server rejects it with "the only allowed values are
    floats between -180.0 and 180.0", which reaches the page as three identical
    walls of XHTML and no clue that panning caused it.
    """
    south = max(-85.05, min(85.05, south))
    north = max(-85.05, min(85.05, north))
    west, east = _wrap_lon(west), _wrap_lon(east)
    if not south < north:
        return (south, west, north, east), "BBox is degenerate."
    if west == east:
        return (south, west, north, east), "BBox is degenerate."
    if west > east:
        # Wrapping put the two edges either side of the date line. Splitting
        # the query would work but every map built here would then straddle
        # the seam, so say so rather than quietly building half of it.
        return ((south, west, north, east),
                "That selection crosses the 180th meridian. Draw it on one "
                "side or the other.")
    return (south, west, north, east), None


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True) or {}
    try:
        south = float(data["south"])
        west = float(data["west"])
        north = float(data["north"])
        east = float(data["east"])
        meters_per_tile = float(data.get("metersPerTile", 1.0))
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Missing or invalid bbox / scale."}), 400

    (south, west, north, east), problem = _normalise_bbox(
        south, west, north, east)
    if problem:
        return jsonify({"error": problem}), 400
    if not (MIN_METERS_PER_TILE <= meters_per_tile <= MAX_METERS_PER_TILE):
        return jsonify({"error": "Scale out of allowed range."}), 400

    area_km2 = _bbox_area_km2(south, west, north, east)
    if area_km2 > MAX_AREA_KM2:
        return jsonify({
            "error": f"Area {area_km2:.2f} km² exceeds limit of "
                     f"{MAX_AREA_KM2} km². Select a smaller region."}), 400

    raw_name = data.get("mapName") or f"knoxify_{int(time.time())}"
    map_name = SAFE_NAME.sub("_", raw_name).strip("_") or f"knoxify_{int(time.time())}"

    # Upper bound on the final bitmap size before we even hit Overpass.
    approx_w = ((east - west) * 111320 * _cos_lat((south + north) / 2)) / meters_per_tile
    approx_h = ((north - south) * 111320) / meters_per_tile
    if max(approx_w, approx_h) > MAX_TILES_PER_SIDE:
        return jsonify({
            "error": f"Requested map is too large (~{int(approx_w)}×"
                     f"{int(approx_h)} tiles). Pick a smaller area or a larger "
                     f"meters-per-tile scale."}), 400

    t0 = time.time()
    map_dir = OUTPUT_DIR / map_name
    map_dir.mkdir(parents=True, exist_ok=True)
    bbox = (south, west, north, east)
    cache = osm.cache_path(str(map_dir), map_name)

    # Regenerating the same area is the common case - it is how a map gets
    # re-rendered after the ground or road rules change - and a town's worth of
    # Overpass tiles takes minutes to download every time. The reply is kept on
    # disk and reused whenever the bbox matches to the metre.
    features = osm.load_cache(cache, bbox)
    if features is None:
        _set_progress(map_name, stage="osm", done=0, total=1)
        def _progress(i, total):
            _set_progress(map_name, stage="osm", done=i - 1, total=total)

        try:
            # Always through the tiled path, even for a small area: with one
            # tile it is the same single request, and it brings the retry that
            # quarters a bbox the servers call too heavy.
            features = osm.fetch_features_tiled(
                south, west, north, east,
                max_tile_km2=OVERPASS_TILE_KM2, progress=_progress)
        except Exception as exc:  # Overpass can be flaky — surface that clearly
            _set_progress(map_name, stage="error", message=str(exc))
            return jsonify({"error": f"OSM query failed: {exc}"}), 502
        try:
            osm.save_cache(cache, bbox, features)
        except OSError:
            pass  # a map that cannot be cached still renders

    # Remembered next to the map, so Generate buildings and any later rebuild
    # use the same ones without the page having to send them again - and so a
    # map from last week can be reproduced exactly.
    settings = Settings.from_dict(data.get("settings"))
    _save_settings(map_dir, settings)

    # Turn the map to its street grid (see renderer.dominant_road_angle). A
    # turned map's corners reach past the drawn selection, so the ground for
    # them is fetched too - otherwise each corner would be an empty wedge.
    rotation = 0.0
    osm_cache_name = Path(cache).name
    osm_bbox = bbox
    if settings.align_streets:
        angle, strength = renderer.dominant_road_angle(features, *bbox)
        if strength >= renderer.ALIGN_MIN_STRENGTH and abs(angle) >= 2.0:
            rotation = -angle
            turned = renderer.Projector.build(*bbox, meters_per_tile, rotation)
            osm_bbox = turned.latlon_bbox()
            wide_cache = osm.cache_path(str(map_dir), f"{map_name}_turned")
            wider = osm.load_cache(wide_cache, osm_bbox)
            if wider is None:
                _set_progress(map_name, stage="osm", done=0, total=1)
                try:
                    wider = osm.fetch_features_tiled(
                        *osm_bbox, max_tile_km2=OVERPASS_TILE_KM2,
                        progress=lambda i, total: _set_progress(
                            map_name, stage="osm", done=i - 1, total=total))
                    osm.save_cache(wide_cache, osm_bbox, wider)
                except Exception:  # noqa: BLE001 - keep north up rather than fail
                    wider = None
            if wider is not None:
                features = wider
                osm_cache_name = Path(wide_cache).name
            else:
                rotation, osm_bbox = 0.0, bbox

    osm_time = time.time() - t0
    _set_progress(map_name, stage="render", features=len(features))

    result = renderer.render(
        features, south, west, north, east,
        meters_per_tile=meters_per_tile,
        output_dir=str(map_dir),
        map_name=map_name,
        spawn_density=settings.spawn_density,
        tree_density=settings.tree_density,
        rotation=rotation,
        osm_cache=osm_cache_name,
        osm_bbox=osm_bbox,
    )

    _write_readme(map_dir, map_name, result)
    _set_progress(map_name, stage="done")

    return jsonify({
        "mapName": map_name,
        "width": result.width,
        "height": result.height,
        "cellsX": result.cells_x,
        "cellsY": result.cells_y,
        "featureCount": len(features),
        "rotation": round(rotation, 1),
        "osmSeconds": round(osm_time, 2),
        "files": {
            "landscape": f"/output/{map_name}/{Path(result.landscape_path).name}",
            "vegetation": f"/output/{map_name}/{Path(result.vegetation_path).name}",
            "spawn": f"/output/{map_name}/{Path(result.spawn_map_path).name}",
            "preview": f"/output/{map_name}/{Path(result.preview_path).name}",
            "buildings": f"/output/{map_name}/{Path(result.buildings_geojson_path).name}",
            "meta": f"/output/{map_name}/{Path(result.meta_path).name}",
            "zip": f"/download/{map_name}.zip",
            "readme": f"/output/{map_name}/README.txt",
        },
    })


@app.route("/output/<path:relpath>")
def serve_output(relpath: str):
    return send_from_directory(OUTPUT_DIR, relpath)


# ---- the rest of the pipeline, so the whole thing lives in one window ----

def _worlded_exe(cli: bool = False) -> Path | None:
    """Find PZWorldEd. `cli` prefers the patched build with --generate-map."""
    import knoxpaths

    return knoxpaths.worlded_cli() if cli else knoxpaths.worlded_gui()


def _map_dir(map_name: str) -> Path | None:
    safe = SAFE_NAME.sub("_", map_name)
    d = (OUTPUT_DIR / safe).resolve()
    if not str(d).startswith(str(OUTPUT_DIR.resolve())) or not d.is_dir():
        return None
    return d


@app.route("/api/buildings", methods=["POST"])
def api_buildings():
    """Run knoxbuild over a generated map."""
    from knoxbuild.build import build as build_buildings

    data = request.get_json(silent=True) or {}
    map_dir = _map_dir(data.get("mapName", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    settings = Settings.from_dict(data.get("settings"))         if data.get("settings") else _load_settings(map_dir)
    _save_settings(map_dir, settings)
    try:
        build_buildings(str(map_dir), settings=settings)
    except Exception as exc:
        return jsonify({"error": f"Building generation failed: {exc}"}), 500
    tbx = sorted((map_dir / "buildings").glob("*.tbx"))
    return jsonify({"count": len(tbx),
                    "pzw": f"{map_dir.name}.pzw",
                    "settings": settings.to_dict(),
                    "population": _population(map_dir)})


def _population(map_dir: Path) -> dict | None:
    try:
        with open(map_dir / f"{map_dir.name}_population.json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


@app.route("/api/zombies", methods=["POST"])
def api_zombies():
    """Recount a built map's zombies with new settings, without rebuilding.

    The spawn map only depends on the buildings' footprints, heights and
    kinds, which the build saved. Redrawing it takes a second or two against
    the minutes a full building pass takes, so the zombie dials can be tried
    freely. The map still needs compiling again for the game to see it.
    """
    from knoxbuild.population import recount

    data = request.get_json(silent=True) or {}
    map_dir = _map_dir(data.get("mapName", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    # Same rule as Generate buildings: settings sent with the request stand on
    # their own. Layering them over the saved ones let a saved value outrank
    # the preset being asked for, so "town" after a recount at 1.5 stayed 1.5.
    settings = Settings.from_dict(data.get("settings"))         if data.get("settings") else _load_settings(map_dir)
    try:
        summary = recount(str(map_dir), settings)
    except FileNotFoundError as exc:
        return jsonify({"error": f"Cannot recount zombies: {exc}."}), 400
    _save_settings(map_dir, settings)
    return jsonify({"population": summary})


@app.route("/api/worlded", methods=["POST"])
def api_worlded():
    """Open the generated project in PZWorldEd."""
    import subprocess

    data = request.get_json(silent=True) or {}
    map_dir = _map_dir(data.get("mapName", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    exe = _worlded_exe()
    if exe is None:
        return jsonify({"error": "PZWorldEd.exe not found. Set the PZWORLDED "
                                 "environment variable to its full path."}), 400
    pzw = map_dir / f"{map_dir.name}.pzw"
    if not pzw.exists():
        return jsonify({"error": "No .pzw yet — generate the buildings first."}), 400
    subprocess.Popen([str(exe), str(pzw)])
    return jsonify({"launched": str(pzw)})


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
        with open(_settings_path(map_dir), "w", encoding="utf-8") as f:
            json.dump(settings.to_dict(), f, indent=2)
    except OSError:
        pass          # a map whose settings cannot be saved still builds


@app.route("/api/setup-status")
def api_setup_status():
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
    tiles = 0
    if tools and (tools / "Tiles" / "2x").is_dir():
        tiles = sum(1 for _ in (tools / "Tiles" / "2x").glob("*.png"))
    checks = [
        {"id": "tools", "ok": bool(tools), "label": "PZ Mapping Tools",
         "fix": "Run Setup.bat to download them."},
        {"id": "compiler", "ok": bool(cli), "label": "Patched map compiler",
         "fix": "Run Setup.bat, or compile by hand with Open in WorldEd."},
        {"id": "game", "ok": bool(game), "label": "Project Zomboid install",
         "fix": "Install the game, then run Setup.bat again."},
        {"id": "build42", "ok": knoxpaths.is_build42(game),
         "label": "Project Zomboid Build 42",
         "fix": "Your game looks like Build 41. In Steam choose the Build 42 "
                "(unstable) branch under Properties > Betas."},
        {"id": "tiles", "ok": tiles >= 400, "label": "Tile artwork from your game",
         "fix": "Run Setup.bat to extract it from your install."},
    ]
    return jsonify({"ready": all(c["ok"] for c in checks), "checks": checks,
                    "mods_dir": str(knoxpaths.zomboid_user_dir() / "mods")})


@app.route("/api/settings")
def api_settings():
    """The knobs, their limits, and the presets - so the page is not a
    hard-coded copy of them that drifts out of step."""
    from knoxbuild.settings import LIMITS

    map_dir = _map_dir(request.args.get("map", ""))
    current = _load_settings(map_dir) if map_dir else Settings()
    from dataclasses import fields

    return jsonify({
        "current": current.to_dict(),
        "defaults": Settings().to_dict(),
        # JSON writes 1.0 as 1, so the page cannot tell a float whose default
        # happens to be whole from an int - and a woodland slider built as an
        # integer can only reach 0, 1, 2 or 3. Say which is which.
        "types": {f.name: ("int" if f.type in (int, "int") else "float")
                  for f in fields(Settings)},
        "limits": {k: list(v) for k, v in LIMITS.items()},
        "presets": {name: s.to_dict() for name, s in PRESETS.items()},
    })


def _expected_cells(map_dir: Path) -> int:
    """How many 256-tile cells the compile should produce, for a progress bar."""
    try:
        with open(map_dir / f"{map_dir.name}_info.json") as f:
            info = json.load(f)
    except Exception:
        return 0
    from knoxbuild.world import CELL_SIZE, WORLD_ORIGIN_CELLS

    ox = WORLD_ORIGIN_CELLS[0] * CELL_SIZE
    oy = WORLD_ORIGIN_CELLS[1] * CELL_SIZE
    w = info.get("cells_x", 0) * CELL_SIZE
    h = info.get("cells_y", 0) * CELL_SIZE
    x0, x1 = ox // 256, (ox + w + 255) // 256
    y0, y1 = oy // 256, (oy + h + 255) // 256
    return max(0, (x1 - x0) * (y1 - y0))


@app.route("/api/compile-status")
def api_compile_status():
    """Progress of a running compile, so the page never has to block on one."""
    map_dir = _map_dir(request.args.get("map", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    with _PROGRESS_LOCK:
        state = dict(_COMPILE.get(map_dir.name, {"state": "idle"}))
    lots = map_dir / "lots"
    state["cells"] = len(list(lots.glob("*.lotheader"))) if lots.is_dir() else 0
    state["expected"] = _expected_cells(map_dir)
    state["tmx"] = len(list((map_dir / "tmx").glob("*.tmx"))) \
        if (map_dir / "tmx").is_dir() else 0
    return jsonify(state)


@app.route("/api/compile", methods=["POST"])
def api_compile():
    """Convert and compile the whole map without touching WorldEd's menus.

    Uses the patched PZWorldEd_cli.exe, which adds a --generate-map switch that
    runs BMP to TMX and Generate Lots in order. Stock WorldEd has no such
    switch, so without the patched build this falls back to /api/worlded.
    """
    import subprocess

    data = request.get_json(silent=True) or {}
    map_dir = _map_dir(data.get("mapName", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    exe = _worlded_exe(cli=True)
    if exe is None:
        return jsonify({"error": "Patched PZWorldEd_cli.exe not found — use "
                                 "Open in WorldEd and run the two menu "
                                 "commands instead."}), 400
    pzw = map_dir / f"{map_dir.name}.pzw"
    if not pzw.exists():
        return jsonify({"error": "No .pzw yet — generate the buildings first."}), 400

    (map_dir / "tmx").mkdir(exist_ok=True)
    (map_dir / "lots").mkdir(exist_ok=True)

    name = map_dir.name
    with _PROGRESS_LOCK:
        if _COMPILE.get(name, {}).get("state") == "running":
            return jsonify({"started": False, "state": "running"})
        _COMPILE[name] = {"state": "running", "error": None}

    def worker() -> None:
        """Compiling a town takes many minutes.

        Running it inside the request blocked the whole UI - the window simply
        froze until it finished. It runs on its own thread now and the page
        polls /api/compile-status, so the app stays usable and shows progress.

        The work goes out in batches of cells, one short-lived WorldEd
        process each: a single process compiling a whole town never gives
        its memory back and took the machine down at 13.7 GB. See
        tools/compile_map.py.
        """
        from tools import compile_map as compiler

        def note(done: int, total: int, cells: int) -> None:
            with _PROGRESS_LOCK:
                _COMPILE[name] = {"state": "running", "error": None,
                                  "batch": done, "batches": total}

        try:
            produced = compiler.compile_map(str(map_dir), batch=COMPILE_BATCH,
                                            exe=str(exe), on_progress=note)
            if not produced:
                with _PROGRESS_LOCK:
                    _COMPILE[name] = {"state": "error",
                                      "error": "Compile produced no cells."}
                return
            with _PROGRESS_LOCK:
                _COMPILE[name] = {"state": "done", "error": None}
        except subprocess.TimeoutExpired:
            with _PROGRESS_LOCK:
                _COMPILE[name] = {"state": "error", "error": "Compile timed out."}
        except Exception as exc:
            with _PROGRESS_LOCK:
                _COMPILE[name] = {"state": "error", "error": str(exc)}

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"started": True, "expected": _expected_cells(map_dir)})


@app.route("/api/lots")
def api_lots():
    """Has WorldEd's Generate Lots produced anything yet?"""
    map_dir = _map_dir(request.args.get("map", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    lots = map_dir / "lots"
    cells = sorted(lots.glob("*.lotheader")) if lots.is_dir() else []
    return jsonify({"compiled": bool(cells), "cells": len(cells)})


@app.route("/api/install", methods=["POST"])
def api_install():
    """Package the compiled map into ~/Zomboid/mods."""
    from tools import make_map_mod

    data = request.get_json(silent=True) or {}
    map_dir = _map_dir(data.get("mapName", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    title = (data.get("title") or map_dir.name).strip()
    mod_id = SAFE_NAME.sub("_", (data.get("modId") or map_dir.name)).strip("_")
    try:
        mod_root, n_cells, extras = make_map_mod.package(
            str(map_dir), title, mod_id)
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Install failed: {exc}"}), 500
    return jsonify({"modRoot": str(mod_root), "cells": n_cells,
                    "extras": extras, "modId": mod_id, "title": title})


def _bbox_area_km2(south: float, west: float, north: float, east: float) -> float:
    lat_mid = (south + north) / 2
    h_km = (north - south) * 111.32
    w_km = (east - west) * 111.32 * _cos_lat(lat_mid)
    return h_km * w_km


def _cos_lat(lat_deg: float) -> float:
    import math
    return math.cos(math.radians(lat_deg))


def _write_readme(map_dir: Path, map_name: str, result: renderer.RenderResult) -> None:
    text = f"""Project Zomboid map: {map_name}
Generated by KnoxMap.

Bitmap dimensions: {result.width}x{result.height} tiles
Cell grid:         {result.cells_x} x {result.cells_y} (cells are always 300 tiles)

Files
-----
{map_name}.bmp                  Landscape (base terrain — WorldEd's main input)
{map_name}_veg.bmp              Vegetation (trees, bushes, long grass)
{map_name}_ZombieSpawnMap.bmp   Zombie population (grayscale, 1/10 scale)
{map_name}_preview.png          Human-viewable preview of what you'll get
{map_name}_buildings.geojson    Building footprints from OSM (for reference)
{map_name}_info.json            Meta: bbox, scale, cell count
{map_name}.zip                  Everything in this folder, from the web UI

How to import (per Thuztor's Mapping Guide v0.2, chapter 2)
-----------------------------------------------------------
1. Open WorldEd (part of the Zomboid Mapping Tools).
2. File -> New, and choose a {result.cells_x} x {result.cells_y} cell grid.
3. From your file browser, drag {map_name}.bmp onto the empty grid.
   (WorldEd reads the matching {map_name}_veg.bmp automatically if it sits
   next to the landscape bitmap with the same base filename.)
4. File -> BMP to TMX -> All cells. Set an export folder for the .tmx output.
5. Open the resulting project in WorldEd / TileZed to place buildings
   (.tbx files) on top of the landscape. This tool does NOT place PZ
   buildings — OSM building footprints are exported as GeoJSON for
   reference only.
6. File -> Generate Lots. This produces .lotheader + .lotpack files.
7. Copy those into your game's media/maps folder (see chapter 9 of the
   guide for offset / world-origin details).

Notes
-----
* Roads render as asphalt (residential = light, secondary = medium,
  primary/motorway = dark). Paths and tracks render as dirt lines.
* Forests render as dense trees in the interior and a grass+tree blend
  at the edges so the transition isn't a hard rectangle.
* The spawn map is generated procedurally: higher density on asphalt,
  zero on water, slight randomness throughout.
* OSM building footprints CANNOT be converted directly to PZ buildings —
  PZ buildings are a separate thing you assemble in BuildingEd (.tbx).
  The GeoJSON file lets you see where buildings would sit in the real
  world and drop matching .tbx lots in the right tiles.
"""
    (map_dir / "README.txt").write_text(text)


@app.route("/download/<map_name>.zip")
def download_all(map_name: str):
    """Everything for one map, zipped on demand.

    Built when asked for rather than at generation time, so it also picks up
    anything produced later - the .tbx buildings, the .pzw project and the
    placement CSV that `python -m knoxbuild` writes into the same folder.
    """
    safe = SAFE_NAME.sub("_", map_name)
    map_dir = (OUTPUT_DIR / safe).resolve()
    if not str(map_dir).startswith(str(OUTPUT_DIR.resolve())):
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)
