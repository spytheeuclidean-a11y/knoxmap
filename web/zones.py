"""Editing a map after it is drawn: its features, edits, sketch, design sheet, board and zones."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from generator import edits as mapedits
from generator import osm, sketch

from web.common import _json_body, _map_dir, failed
from web.mapfiles import (_load_design, _load_edits, _load_settings,
                          _load_sketch, _map_summary, _osm_cache_for,
                          _save_design, _save_edits, _save_sketch)

bp = Blueprint("zones", __name__)


# How many features one look at the map may bring back. A city has a hundred
# thousand; a page that is handed them all stops responding, and nobody edits
# a hundred thousand things by hand anyway. The biggest are sent first, so
# what arrives is what is worth editing.
EDIT_FEATURE_LIMIT = 1200


@bp.route("/api/features/<name>")
def api_features(name: str):
    """This map's own features, as GeoJSON, for editing.

    They come from the download that made the map, not from a fresh one, so
    what is edited is exactly what was built - and editing costs no requests
    to Overpass at all.
    """
    map_dir = _map_dir(name)
    if map_dir is None:
        return jsonify({"error": "Bad map name."}), 400
    info = _map_summary(map_dir)
    box = info.get("bbox") or {}
    if not box:
        return jsonify({"error": "That map has no area recorded, so there is "
                                 "nothing to read its features from."}), 400
    settings = _load_settings(map_dir)
    cache, fetch_box = _osm_cache_for(
        map_dir, (box["south"], box["west"], box["north"], box["east"]),
        float(info.get("metersPerTile") or 1.0), settings)
    features = osm.load_cache(cache, fetch_box)
    if features is None:
        return jsonify({"error": "This map's download is not beside it any "
                                 "more, or it was made by a version whose "
                                 "filters have changed. Generate it again and "
                                 "its features can be edited."}), 404
    features = osm.proposed_roads(features, settings.include_proposed_roads)
    # Only what is being looked at, which is what keeps a town editable.
    view = None
    try:
        view = (float(request.args["south"]), float(request.args["west"]),
                float(request.args["north"]), float(request.args["east"]))
    except (KeyError, TypeError, ValueError):
        view = None
    out = mapedits.as_geojson(features, view, EDIT_FEATURE_LIMIT)
    out["edits"] = _load_edits(map_dir)
    return jsonify(out)


@bp.route("/api/edits/<name>", methods=["GET", "POST"])
def api_edits(name: str):
    map_dir = _map_dir(name)
    if map_dir is None:
        return jsonify({"error": "Bad map name."}), 400
    if request.method == "GET":
        return jsonify(_load_edits(map_dir))
    changes = mapedits.clean(_json_body())
    try:
        _save_edits(map_dir, changes)
    except OSError as exc:
        return failed(f"The map edits could not be saved: {exc}", 500, exc)
    return jsonify({"changes": mapedits.count(changes), **changes})


@bp.route("/api/sketch")
def api_sketch_palette():
    """What can be drawn, and the OpenStreetMap tags each one carries.

    The page builds its palette from this rather than holding a second copy of
    the tags: a tag that is wrong here draws a shape that is missing from the
    finished map, and one list cannot disagree with itself."""
    return jsonify({"palette": sketch.palette(),
                    "categories": {e["id"]: sketch.category_of(e["id"])
                                   for e in sketch.palette()}})


@bp.route("/api/design/<name>", methods=["GET", "POST"])
def api_design(name: str):
    """The editor's own sheet: what was drawn, in metres, and how big it is.

    Kept as drawn rather than as the GeoJSON it becomes, because metres from
    a corner are what the editor works in and degrees are not - a sheet that
    came back as longitude could not be drawn on again without guessing at
    the conversion backwards.
    """
    map_dir = _map_dir(name)
    if map_dir is None:
        return jsonify({"error": "Bad map name."}), 400
    if request.method == "GET":
        design = _load_design(map_dir)
        if design is None:
            return jsonify({"error": "That map was not drawn on a sheet."}), 404
        return jsonify(design)
    design = _json_body()
    if not isinstance(design, dict):
        return jsonify({"error": "Expected a sheet."}), 400
    try:
        _save_design(map_dir, design)
    except OSError as exc:
        return failed(f"The drawing could not be saved: {exc}", 500, exc)
    south, west, north, east = sketch.design_bbox(design)
    made = sketch.features(sketch.design_to_drawn(design))
    drawn = design.get("features")
    return jsonify({"saved": len(drawn) if isinstance(drawn, (list, tuple)) else 0,
                    "usable": len(made),
                    "bbox": {"south": south, "west": west,
                             "north": north, "east": east}})


# ---- drawing a map that joins one already built ----------------------------
#
# The drawing board has no world under it, which is the point of it and also
# means a street drawn on it stops dead at the edge. These two give it the map
# next door: where that map's roads leave the side they share, so the drawing
# can be made to meet them, and the ground it stands on afterwards, so the two
# really are neighbours in the game.

@bp.route("/api/board/join/<name>")
def api_board_join(name: str):
    """A built map, as the drawing board needs to see it.

    `side` is where the new sheet goes - "E" means east of this map - and
    `w`/`h` are the sheet in metres, so the roads come back as points on it.
    """
    from knoxbuild import joins
    from knoxbuild import placement as P

    map_dir = _map_dir(name)
    if map_dir is None:
        return jsonify({"error": "Bad map name."}), 400
    side = (request.args.get("side") or "E").upper()
    try:
        sheet_w = float(request.args.get("w") or 900)
        sheet_h = float(request.args.get("h") or 900)
    except (TypeError, ValueError):
        return jsonify({"error": "The sheet is two numbers: how wide and how "
                                 "tall it is, in metres."}), 400
    try:
        out = joins.sheet_joins(str(map_dir), map_dir.name, side, sheet_w, sheet_h)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    where = P.saved(str(map_dir)) or P.project_origin(str(map_dir), map_dir.name)
    cells_w, cells_h = P.project_size(str(map_dir), map_dir.name)
    out["cells"] = ({"x": where[0], "y": where[1], "w": cells_w, "h": cells_h}
                    if where else None)
    out["cellTiles"] = P.CELL_SIZE
    preview = map_dir / f"{map_dir.name}_preview.png"
    out["preview"] = (f"/output/{map_dir.name}/{preview.name}"
                      if preview.exists() else None)
    return jsonify(out)


@bp.route("/api/board/place-beside", methods=["POST"])
def api_board_place_beside():
    """Put a map that has just been built next to the one it was drawn to
    join, so the street that meets its border meets it in the game too."""
    from knoxbuild import joins
    from knoxbuild import placement as P

    body = _json_body()
    mine = _map_dir(str(body.get("map") or ""))
    theirs = _map_dir(str(body.get("neighbour") or ""))
    side = str(body.get("side") or "E").upper()
    if mine is None or theirs is None:
        return jsonify({"error": "Bad map name."}), 400
    if side not in joins.SIDES:
        return jsonify({"error": f"A map has four sides, not {side}."}), 400
    where = P.saved(str(theirs)) or P.project_origin(str(theirs), theirs.name)
    if not where:
        return jsonify({"error": f"{theirs.name} has no place in the world "
                                 f"yet, so there is nothing to sit beside."}), 400
    their_w, their_h = P.project_size(str(theirs), theirs.name)
    my_w, my_h = P.project_size(str(mine), mine.name)
    # Corners line up on the side they share, which is what makes the streets
    # across the border line up too.
    cell = {"E": (where[0] + their_w, where[1]),
            "W": (where[0] - my_w, where[1]),
            "S": (where[0], where[1] + their_h),
            "N": (where[0], where[1] - my_h)}[side]
    try:
        done = P.move(str(mine), mine.name, cell)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except OSError as exc:
        return failed(f"The map could not be placed: {exc}", 500, exc)
    out = P.layout(str(mine), mine.name)
    out["moved"] = done
    out["beside"] = theirs.name
    return jsonify(out)


@bp.route("/api/zones")
def api_zone_settings():
    """What a zone may say about itself, and the wall styles it may pin to.

    Served rather than written into the page, for the same reason the settings
    are: a second copy drifts, and a zone setting the window offers that the
    generator does not read is a dial that does nothing.
    """
    from knoxbuild import zones as Z
    from knoxbuild.build import style_names

    return jsonify({"settings": Z.overridable(), "styles": style_names(),
                    "styleKey": Z.STYLE_KEY})


@bp.route("/api/zones/<name>", methods=["GET", "POST"])
def api_zones(name: str):
    from knoxbuild import zones as Z

    map_dir = _map_dir(name)
    if map_dir is None:
        return jsonify({"error": "Bad map name."}), 400
    if request.method == "GET":
        return jsonify({"zones": Z.load(str(map_dir), map_dir.name)})
    body = _json_body()
    drawn = body.get("zones") if isinstance(body, dict) else body
    if not isinstance(drawn, list):
        return jsonify({"error": "Expected a list of zones."}), 400
    try:
        Z.save(str(map_dir), map_dir.name, drawn)
    except OSError as exc:
        return failed(f"The zones could not be saved: {exc}", 500, exc)
    kept = Z.load(str(map_dir), map_dir.name)
    return jsonify({"zones": kept, "saved": len(kept)})


@bp.route("/api/sketch/<name>", methods=["GET", "POST"])
def api_sketch(name: str):
    map_dir = _map_dir(name)
    if map_dir is None:
        return jsonify({"error": "Bad map name."}), 400
    if request.method == "GET":
        return jsonify(_load_sketch(map_dir))
    drawn = _json_body()
    if not isinstance(drawn, dict):
        return jsonify({"error": "Expected a GeoJSON FeatureCollection."}), 400
    try:
        _save_sketch(map_dir, drawn)
    except OSError as exc:
        return failed(f"The drawing could not be saved: {exc}", 500, exc)
    made = sketch.features(drawn)
    sent = drawn.get("features")
    return jsonify({"saved": len(sent) if isinstance(sent, (list, tuple)) else 0,
                    "usable": len(made)})
