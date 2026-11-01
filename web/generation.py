"""Making a map: generate, the pictures, buildings and zombies steps, the layout preview
and handing a map to WorldEd.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

import knoxfiles
import knoxlog
import knoxstop
from generator import edits as mapedits
from generator import osm, renderer, sketch
from knoxbuild import mapstate
from knoxbuild.settings import Settings

from web import common
from web.checks import (BASE_BYTES, BIG_AREA_KM2, BIG_TILES_PER_SIDE,
                        BUILD_BASE_BYTES, BUILD_BYTES_PER_TILE, BYTES_PER_TILE,
                        MAX_METERS_PER_TILE, MIN_METERS_PER_TILE,
                        OVERPASS_TILE_KM2, USUAL_METERS_PER_TILE,
                        _beyond_this_pc, _clean_shape, _normalise_bbox,
                        _shape_rings, _too_big_for_memory, tidy_scale)
from web.common import (SAFE_NAME, _bbox_area_km2, _cos_lat, _json_body,
                        _map_dir, _worlded_exe, failed, log)
from web.jobs import _PROGRESS_LOCK, _set_progress, _stopped, _stopper
from web.mapfiles import (_load_edits, _load_settings, _load_sketch,
                          _map_summary, _osm_cache_for, _population,
                          _save_design, _save_settings, _save_sketch)

bp = Blueprint("generation", __name__)


@bp.route("/api/generate", methods=["POST"])
def generate():
    data = _json_body()
    # A map drawn on the editor's own sheet brings its own size and its own
    # corner of the world; the box and the features both come out of it, so
    # there is nothing to draw on the world map and nothing to download.
    design = data.get("design")
    if isinstance(design, dict):
        south, west, north, east = sketch.design_bbox(design)
        data = {**data, "south": south, "west": west, "north": north,
                "east": east, "shape": None, "drawnOnly": True,
                "sketch": sketch.design_to_drawn(design)}
    shape, problem = _clean_shape(data.get("shape"))
    if problem:
        return jsonify({"error": problem}), 400
    if shape:
        # A drawn shape decides the box: its own bounds, whatever the page sent.
        lons = [p[0] for ring in _shape_rings(shape) for p in ring]
        lats = [p[1] for ring in _shape_rings(shape) for p in ring]
        data = {**data, "south": min(lats), "north": max(lats),
                "west": min(lons), "east": max(lons)}
    try:
        south = float(data["south"])
        west = float(data["west"])
        north = float(data["north"])
        east = float(data["east"])
        meters_per_tile = float(data.get("metersPerTile", 1.0))
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Missing or invalid bbox / scale."}), 400

    import math
    if not all(math.isfinite(v) for v in (south, west, north, east, meters_per_tile)):
        return jsonify({"error": "Missing or invalid bbox / scale."}), 400
    (south, west, north, east), problem = _normalise_bbox(
        south, west, north, east)
    if problem:
        return jsonify({"error": problem}), 400
    if not (MIN_METERS_PER_TILE <= meters_per_tile <= MAX_METERS_PER_TILE):
        return jsonify({"error": f"Metres per tile has to be a whole number "
                                 f"between {MIN_METERS_PER_TILE:g} and "
                                 f"{MAX_METERS_PER_TILE:g}."}), 400
    # Whole metres only: 1.5 would put every building, road and lot on a grid
    # that is not a multiple of the survey's own.
    meters_per_tile = tidy_scale(meters_per_tile)

    # Nothing below refuses the map. These are what the window has already
    # warned about; they are logged here so a report from somebody whose map
    # died halfway says how big it was.
    heavy: list[str] = []
    area_km2 = _bbox_area_km2(south, west, north, east)
    if area_km2 > BIG_AREA_KM2:
        heavy.append(f"{area_km2:.0f} km2, over the {BIG_AREA_KM2:g} km2 a map "
                     f"usually is")
    if not (USUAL_METERS_PER_TILE[0] <= meters_per_tile <= USUAL_METERS_PER_TILE[1]):
        heavy.append(f"{meters_per_tile:g} m a tile, outside the "
                     f"{USUAL_METERS_PER_TILE[0]:g}-{USUAL_METERS_PER_TILE[1]:g} "
                     f"the window offers")

    raw_name = data.get("mapName")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raw_name = f"knoxify_{int(time.time())}"
    map_name = SAFE_NAME.sub("_", raw_name).strip("_") or f"knoxify_{int(time.time())}"

    # Upper bound on the final bitmap size before we even hit Overpass.
    approx_w = ((east - west) * 111320 * _cos_lat((south + north) / 2)) / meters_per_tile
    approx_h = ((north - south) * 111320) / meters_per_tile
    if max(approx_w, approx_h) > BIG_TILES_PER_SIDE:
        heavy.append(f"{int(approx_w)}x{int(approx_h)} tiles, over the "
                     f"{BIG_TILES_PER_SIDE} a side that is comfortable")
    # The one size that is refused: WorldEd cannot compile it, so a map this big
    # would be made over most of an hour and then fail at the compile.
    from tools.compile_map import WORLDED_MAX_PIXELS, bitmap_pixels, default_backend, scale_that_fits
    pixels = bitmap_pixels(int(approx_w), int(approx_h))
    if pixels > WORLDED_MAX_PIXELS and default_backend() != "rust":
        fits = scale_that_fits(int(approx_w), int(approx_h), meters_per_tile)
        return jsonify({"error": (
            f"That map would be about {int(approx_w)} x {int(approx_h)} tiles "
            f"({pixels / 1e6:.0f} million), and WorldEd cannot compile a map past "
            f"{WORLDED_MAX_PIXELS / 1e6:.0f} million. "
            + (f"At {fits} m a tile it fits, or draw a smaller area."
               if fits else "Draw a smaller area."))}), 400
    tight = _too_big_for_memory(approx_w, approx_h)
    if tight:
        heavy.append(tight)
    impossible = _beyond_this_pc(approx_w, approx_h)
    if impossible:
        return jsonify({"error": impossible}), 400
    if heavy:
        log.warning("generate %s: going ahead with a heavy map - %s",
                    map_name, "; ".join(heavy))

    t0 = time.time()
    log.info("generate %s: %.5f,%.5f,%.5f,%.5f at %s m/tile, %.2f km2", map_name,
             south, west, north, east, meters_per_tile, area_km2)
    map_dir = common.OUTPUT_DIR / map_name
    # A folder this request makes is taken away again if the download fails: it
    # holds nothing but the settings, and every failed attempt left one behind.
    made_here = not map_dir.exists()
    map_dir.mkdir(parents=True, exist_ok=True)

    def forget_empty_folder() -> None:
        if made_here and not (map_dir / f"{map_name}_info.json").exists():
            shutil.rmtree(map_dir, ignore_errors=True)

    bbox = (south, west, north, east)
    # Remembered next to the map, so Generate buildings and any later rebuild
    # use the same ones without the page having to send them again - and so a
    # map from last week can be reproduced exactly.
    settings = Settings.from_dict(data.get("settings"))
    _save_settings(map_dir, settings)

    # The drawn map, kept beside the real one. The page sends it when there is
    # one; when there is not, whatever was drawn for this map last time is used
    # again, so Generate map twice over does not quietly lose it.
    if isinstance(design, dict):
        _save_design(map_dir, design)
    drawn = data.get("sketch")
    if drawn is None:
        drawn = _load_sketch(map_dir)
    else:
        _save_sketch(map_dir, drawn)
    drawn_only = bool(data.get("drawnOnly"))

    # What to download. A map turned to its street grid (see
    # renderer.dominant_road_angle) reaches past the drawn box at its corners,
    # and the angle is only known once the streets are in. This used to fetch
    # the box, measure the angle, then fetch the turned map's bounds as well -
    # the same town twice over, about 2.4 times the data. Now one download
    # covers the map at any angle: the circle round it, as a box.
    cache, fetch_box = _osm_cache_for(map_dir, bbox, meters_per_tile, settings)

    # Regenerating the same area is the common case - it is how a map gets
    # re-rendered after the ground or road rules change - and a town's worth of
    # Overpass tiles takes minutes to download every time. The reply is kept on
    # disk and reused whenever the bbox matches to the metre.
    # A map drawn by hand has no town behind it to download. Overpass is not
    # asked at all, which is also the only way to make a map of a place that
    # is not on OpenStreetMap - one never surveyed, or one that does not exist.
    features = [] if drawn_only else osm.load_cache(cache, fetch_box)
    if features is None:
        _set_progress(map_name, stage="osm", done=0, total=1)
        def _progress(i, total, note=""):
            _set_progress(map_name, stage="osm", done=max(0, i - 1), total=total,
                          note=note)

        try:
            # Always through the tiled path, even for a small area: with one
            # tile it is the same single request, and it brings the retry that
            # quarters a bbox the servers call too heavy.
            features = osm.fetch_features_tiled(
                *fetch_box, max_tile_km2=OVERPASS_TILE_KM2, progress=_progress,
                should_stop=_stopper(map_name))
        except knoxstop.Stopped:
            forget_empty_folder()
            return _stopped(map_name, "generate")
        except Exception as exc:  # Overpass can be flaky — surface that clearly
            message = osm.explain(exc)
            _set_progress(map_name, stage="error", message=message)
            forget_empty_folder()
            return failed(message, 502, exc)
        try:
            osm.save_cache(cache, fetch_box, features)
        except OSError:
            pass  # a map that cannot be cached still renders

    # Buildings Overture has and OpenStreetMap has not, before anything is
    # measured from them: they are ordinary building features from here on,
    # so the street angle, the ground, the gardens and the .tbx all see them
    # exactly as they see a mapped one (generator/overture.py).
    gaps = {"added": 0}
    if settings.fill_gaps:
        from generator import msbuildings, overture
        _set_progress(map_name, stage="overture", done=0, total=1)
        # Microsoft's files first: plain downloads, nothing to install. Overture
        # (DuckDB) only if they cannot be reached.
        try:
            try:
                features, gaps = msbuildings.add_missing(
                    features, fetch_box, str(map_dir), map_name,
                    should_stop=_stopper(map_name))
            except knoxstop.Stopped:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("microsoft buildings %s: %s", map_name, exc)
                features, gaps = overture.add_missing(
                    features, fetch_box, str(map_dir), map_name,
                    should_stop=_stopper(map_name))
        except knoxstop.Stopped:
            return _stopped(map_name, "generate")
        except Exception as exc:  # noqa: BLE001 - OSM alone still makes a map
            log.warning("overture %s: %s", map_name, exc)
            gaps = {"added": 0, "error": str(exc)}
        if gaps.get("added"):
            log.info("overture %s: %d buildings OSM had not got, from %d fetched",
                     map_name, gaps["added"], gaps.get("fetched", 0))

    # What the mapper drew, on top of whatever came down. It goes in here, with
    # the real features and before a single thing is measured from them, so the
    # street angle, the ground, the gardens, the buildings and the compiled
    # cells all see a drawn street exactly as they see a surveyed one.
    # What the mapper changed about the features themselves - a building
    # removed, a road dragged straight, a house retagged as a shop. Applied
    # here so nothing downstream ever sees the version that was rejected.
    changes = _load_edits(map_dir)
    if mapedits.count(changes):
        features, used = mapedits.apply(features, changes)
        log.info("generate %s: %d removed, %d moved, %d retagged by hand",
                 map_name, used["removed"], used["moved"], used["tags"])

    drawn_features = sketch.features(drawn)
    if drawn_features:
        features = list(features) + drawn_features
        log.info("generate %s: %d drawn features%s", map_name,
                 len(drawn_features), " (drawn map)" if drawn_only else "")

    rotation = 0.0
    if settings.align_streets:
        angle, strength = renderer.dominant_road_angle(features, *bbox)
        if strength >= renderer.ALIGN_MIN_STRENGTH and abs(angle) >= 0.5:
            rotation = -angle
    # And whatever turn the mapper asked for on top of that.
    rotation += float(settings.rotate_degrees)
    osm_cache_name = Path(cache).name
    osm_bbox = fetch_box

    osm_time = time.time() - t0
    _set_progress(map_name, stage="render", features=len(features))

    try:
        result = renderer.render(
            features, south, west, north, east,
            meters_per_tile=meters_per_tile,
            output_dir=str(map_dir),
            map_name=map_name,
            spawn_density=settings.spawn_density,
            tree_density=settings.tree_density,
            forest_density=settings.forest_density,
            rotation=rotation,
            osm_cache=osm_cache_name,
            osm_bbox=osm_bbox,
            shape=shape,
            straight_roads=int(settings.straight_roads),
            fill_frontage=int(settings.fill_frontage),
            should_stop=_stopper(map_name),
            progress=lambda done, total: _set_progress(map_name, stage="roads", done=done, total=total),
        )
    except knoxstop.Stopped:
        return _stopped(map_name, "generate")
    except MemoryError:
        # Nothing refuses a big map any more, so this is where one that really
        # was too big lands. Say what it would have taken rather than a
        # traceback: the numbers are the ones the window already showed.
        need = approx_w * approx_h * BYTES_PER_TILE + BASE_BYTES
        _set_progress(map_name, stage="error", message="ran out of memory")
        return failed(
            f"The map ran out of memory while it was being drawn. It needs about "
            f"{need / 1e9:.1f} GB for the ground and the greenery alone, at "
            f"{int(approx_w)}x{int(approx_h)} tiles. Close a few things and try "
            f"again, or draw it at a larger scale - 2 m a tile is a quarter of "
            f"the memory of 1 m. Everything downloaded is kept, so a second run "
            f"starts from the OpenStreetMap data already on disk.", 507)

    _write_readme(map_dir, map_name, result)
    _set_progress(map_name, stage="done")
    mapstate.stamp(str(map_dir), "generate")
    from_addresses = 0
    try:
        with open(map_dir / f"{map_name}_info.json", encoding="utf-8") as f:
            from_addresses = json.load(f).get("houses_from_addresses", 0)
    except (OSError, ValueError):
        pass
    log.info("generate %s: done, %d features, %dx%d tiles, rotation %.1f, "
             "%d houses from addresses, %d from Overture, %.1fs (download %.1fs)",
             map_name, len(features), result.width, result.height, rotation,
             from_addresses, gaps.get("added", 0), time.time() - t0, osm_time)

    return jsonify({
        "mapName": map_name,
        "width": result.width,
        "height": result.height,
        "cellsX": result.cells_x,
        "cellsY": result.cells_y,
        "featureCount": len(features),
        "rotation": round(rotation, 1),
        "osmSeconds": round(osm_time, 2),
        # What Overture put in that OpenStreetMap had not got, so the window
        # can say whether turning it on was worth it here.
        # What the window warned about and the mapper went ahead with anyway,
        # so it can say so beside the finished map too.
        "heavy": heavy,
        # As they were taken, clamped and saved - not as the page sent them -
        # so it can tell afterwards which knobs have really been moved since.
        "settings": settings.to_dict(),
        "fromOverture": gaps.get("added", 0),
        "overtureError": gaps.get("error") or gaps.get("why") or "",
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


@bp.route("/api/pictures", methods=["POST"])
def api_pictures():
    """Draw the map, the way the game would."""
    data = _json_body()
    map_dir = _map_dir(data.get("mapName", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    from knoxbuild import picture as pictures

    if not pictures.compiled(map_dir):
        return jsonify({"error": "Compile the map first - there is nothing to "
                                 "draw until then."}), 400
    name = map_dir.name
    with _PROGRESS_LOCK:
        if _PICTURES.get(name, {}).get("state") == "running":
            return jsonify({"started": False, "state": "running"})
        _PICTURES[name] = {"state": "running", "error": None, "files": []}

    def worker() -> None:
        log.info("pictures %s: started", name)
        t0 = time.time()
        try:
            made = pictures.pictures_of(map_dir)
            files = [f"/output/{map_dir.name}/pictures/{p.name}" for p in made]
            log.info("pictures %s: %d in %.0fs", name, len(files), time.time() - t0)
            with _PROGRESS_LOCK:
                _PICTURES[name] = {"state": "done" if files else "error",
                                   "files": files,
                                   "error": None if files else "Nothing was drawn."}
        except Exception as exc:  # noqa: BLE001 - reported to the window
            eid = knoxlog.record(exc, f"pictures {name}: failed")
            with _PROGRESS_LOCK:
                _PICTURES[name] = {"state": "error", "errorId": eid,
                                   "error": str(exc), "files": []}

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"started": True})


@bp.route("/api/pictures-status")
def api_pictures_status():
    map_dir = _map_dir(request.args.get("map", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    with _PROGRESS_LOCK:
        return jsonify(dict(_PICTURES.get(map_dir.name, {"state": "idle", "files": []})))


# ---- the rest of the pipeline, so the whole thing lives in one window ----

@bp.route("/api/buildings", methods=["POST"])
def api_buildings():
    """Run knoxbuild over a generated map."""
    from knoxbuild.build import build as build_buildings

    data = _json_body()
    map_dir = _map_dir(data.get("mapName", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    settings = Settings.from_dict(data.get("settings"))         if data.get("settings") else _load_settings(map_dir)
    _save_settings(map_dir, settings)
    log.info("buildings %s: started", map_dir.name)
    # Say so now if this PC cannot hold the map's bitmaps, rather than after
    # minutes of work. Free memory moves, so only a 32-bit Python's hard 2 GB
    # ceiling refuses outright; anything else is let through and caught below.
    info = _map_summary(map_dir)
    tight = _too_big_for_memory(info["width"], info["height"],
                                BUILD_BYTES_PER_TILE, BUILD_BASE_BYTES)
    if tight and sys.maxsize <= 2 ** 32:
        return jsonify({"error": tight}), 507
    if tight:
        log.warning("buildings %s: going ahead with a heavy map - %s",
                    map_dir.name, tight)
    t0 = time.time()
    out = io.StringIO()
    try:
        from contextlib import redirect_stdout
        def say(text: str, fraction: float | None) -> None:
            _set_progress(map_dir.name, stage="buildings", note=text,
                          fraction=fraction)

        say("Starting", 0.0)
        with redirect_stdout(out):
            build_buildings(str(map_dir), settings=settings,
                            should_stop=_stopper(map_dir.name), progress=say)
        _set_progress(map_dir.name, stage="buildings-done", note="", fraction=1.0)
    except knoxstop.Stopped:
        return _stopped(map_dir.name, "buildings")
    except knoxfiles.Damaged as exc:
        # One of the map's own files was left half written. That is the
        # mapper's to put right by generating the map again, and the message
        # says so, so it is not dressed up as a failure of the build.
        return failed(str(exc), 400, exc)
    except MemoryError as exc:
        need = info["width"] * info["height"] * BUILD_BYTES_PER_TILE + BUILD_BASE_BYTES
        return failed(
            f"Generate buildings ran out of memory. A map of "
            f"{info['width']}x{info['height']} tiles needs about "
            f"{need / 1e9:.1f} GB for this step. Close a few things and try "
            f"again, or draw the map at a larger scale: 2 m a tile is a quarter "
            f"of the memory of 1 m. Nothing is lost: the map itself is saved, "
            f"so Generate buildings can simply be run again.", 507, exc)
    except Exception as exc:
        log.info("buildings %s output before the error:\n%s", map_dir.name,
                 out.getvalue()[-4000:])
        return failed(f"Building generation failed: {exc}", 500, exc)
    tbx = sorted((map_dir / "buildings").glob("*.tbx"))
    mapstate.stamp(str(map_dir), "build")
    log.info("buildings %s: %d files in %.1fs\n%s", map_dir.name, len(tbx),
             time.time() - t0, out.getvalue()[-3000:])
    return jsonify({"count": len(tbx),
                    "pzw": f"{map_dir.name}.pzw",
                    "settings": settings.to_dict(),
                    "population": _population(map_dir)})


@bp.route("/api/layout-preview")
def api_layout_preview():
    """A picture of what the building step decided - buildings by use, or the
    zombie heat map - to judge the settings before a long compile."""
    from knoxbuild import layout_preview

    map_dir = _map_dir(request.args.get("map", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    layer = request.args.get("layer", "kinds")
    if layer not in layout_preview.LAYERS:
        return jsonify({"error": f"Unknown layer {layer!r}."}), 400
    if not (map_dir / f"{map_dir.name}_placements.csv").exists():
        return jsonify({"error": "Build the buildings first - there is nothing "
                                 "to show until then."}), 400
    path = layout_preview.render_to(str(map_dir), layer)
    return send_file(path, mimetype="image/png", max_age=0)


@bp.route("/api/zombies", methods=["POST"])
def api_zombies():
    """Recount a built map's zombies with new settings, without rebuilding.

    The spawn map only depends on the buildings' footprints, heights and
    kinds, which the build saved. Redrawing it takes a second or two against
    the minutes a full building pass takes, so the zombie dials can be tried
    freely. The map still needs compiling again for the game to see it.
    """
    from knoxbuild.population import recount

    data = _json_body()
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
        return failed(f"Cannot recount zombies: {exc}.", 400, exc)
    _save_settings(map_dir, settings)
    return jsonify({"population": summary})


@bp.route("/api/worlded", methods=["POST"])
def api_worlded():
    """Open the generated project in PZWorldEd."""
    import subprocess

    data = _json_body()
    map_dir = _map_dir(data.get("mapName", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    import knoxpaths

    exe = _worlded_exe()
    if exe is None:
        return jsonify({"error": "PZWorldEd not found. Set the PZWORLDED "
                                 "environment variable to its full path."}), 400
    pzw = map_dir / f"{map_dir.name}.pzw"
    if not pzw.exists():
        return jsonify({"error": "No .pzw yet — generate the buildings first."}), 400
    subprocess.Popen(knoxpaths.command_for(exe) + [str(pzw)])
    return jsonify({"launched": str(pzw)})


# Pictures of a finished map: drawn from the compiled cells the game itself
# loads, so they are the map rather than an impression of it. A town takes the
# best part of a minute, so it runs on its own thread and the page asks.
_PICTURES: dict[str, dict] = {}


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
    # UTF-8 whatever the PC's code page: the text has dashes that a Korean or
    # Japanese Windows cannot write in its own, and the whole generate request
    # failed on them after the map was already drawn.
    (map_dir / "README.txt").write_text(text, encoding="utf-8")
