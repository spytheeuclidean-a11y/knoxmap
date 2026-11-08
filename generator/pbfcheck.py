"""Is this OpenStreetMap extract usable for a KnoxMap map?

A regional `.osm.pbf` can be the wrong region, a half-finished download, a
file renamed from something else, or an area so thinly mapped that the map
would come out as fields with no roads in them. All of those look the same from
the generator: a map that comes out wrong, minutes later. This reads the file
and says what is in it before any map is built.

Read it with `knoxmap pbf <file>` (tools/verify_pbf.py), from the Tools panel in
the app, or `python -c "from generator import pbfcheck; print(pbfcheck.report_text(pbfcheck.check('x.osm.pbf')))"`.
"""
from __future__ import annotations

import os
import time

# Tags a map needs to be worth reading. The first group is fatal when absent -
# a file with no roads or no buildings makes a map of empty fields - and the
# rest are what the renderer decorates with.
NEEDED = {
    "highway": "roads",
    "building": "buildings",
}
NICE = ("landuse", "natural", "waterway", "amenity", "railway", "barrier",
        "leisure", "place", "addr:housenumber")
# An extract older than this is worth mentioning: Geofabrik rebuilds daily.
STALE_S = 30 * 86400.0
# Reading a whole state to count its fuel stations costs minutes. Past this many
# objects the counts are a sample, and the report says so.
SAMPLE_LIMIT = 3_000_000


def _header(path: str) -> dict:
    """Bounds and timestamp from the file header, without reading the bodies."""
    import osmium

    reader = osmium.io.Reader(path)
    try:
        header = reader.header()
        box = header.box()
        out = {"objects": header.get("osmosis_replication_timestamp") or "",
               "generator": header.get("generator") or "",
               "bbox": None, "has_multiple_object_versions": bool(
                   header.get("multiple_object_versions"))}
        valid = box.valid()
        if valid:
            out["bbox"] = [box.bottom_left.lat, box.bottom_left.lon,
                           box.top_right.lat, box.top_right.lon]
        return out
    finally:
        reader.close()


def _counts(path: str, limit: int) -> dict:
    """Objects by kind and the tags a map is made of found on the way through."""
    import osmium

    seen = {"nodes": 0, "ways": 0, "relations": 0, "tagged": 0}
    tags: dict[str, int] = {}
    stop = {"hit": False}
    box = {"south": 90.0, "west": 180.0, "north": -90.0, "east": -180.0}

    class Counter(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.n = 0

        def _tally(self, obj):
            self.n += 1
            if self.n > limit:
                stop["hit"] = True
                raise osmium.InvalidLocationError("enough")
            if obj.tags:
                seen["tagged"] += 1
                for key, _value in obj.tags:
                    if key in NEEDED or key in NICE:
                        tags[key] = tags.get(key, 0) + 1

        def node(self, n):
            seen["nodes"] += 1
            if n.location.valid():
                box["south"] = min(box["south"], n.location.lat)
                box["north"] = max(box["north"], n.location.lat)
                box["west"] = min(box["west"], n.location.lon)
                box["east"] = max(box["east"], n.location.lon)
            self._tally(n)

        def way(self, w):
            seen["ways"] += 1
            self._tally(w)

        def relation(self, r):
            seen["relations"] += 1
            self._tally(r)

    handler = Counter()
    try:
        handler.apply_file(path)
    except Exception:  # noqa: BLE001 - the limit is raised as an error, and a
        pass           # malformed file is reported by the caller's try
    bounds = None
    if box["north"] >= box["south"] and box["east"] >= box["west"]:
        bounds = [box["south"], box["west"], box["north"], box["east"]]
    return {"counts": seen, "tags": tags, "sampled": stop["hit"], "bbox": bounds}


def check(path: str, bbox: tuple[float, float, float, float] | None = None,
          limit: int = SAMPLE_LIMIT) -> dict:
    """Everything wrong with this extract, and what is in it.

    `bbox` is (south, west, north, east) of the map about to be built; when
    given, the file has to cover it.
    """
    result = {"path": os.path.abspath(path) if path else "", "ok": False,
              "problems": [], "warnings": [], "stats": {}, "tags": {},
              "bbox": None, "version": 1}
    problems, warnings = result["problems"], result["warnings"]

    if not path:
        problems.append("No file given.")
        return result
    if not os.path.isfile(path):
        problems.append(f"There is no file at {path}.")
        return result
    size = os.path.getsize(path)
    if not size:
        problems.append("The file is empty (0 bytes): a download that never "
                        "finished, or a shortcut with nothing behind it.")
        return result
    try:
        import osmium  # noqa: F401
    except ImportError:
        problems.append("pyosmium is not installed, so no extract can be read "
                        "(run Setup again, or pip install osmium).")
        return result

    try:
        header = _header(path)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"The file header cannot be read ({type(exc).__name__}: "
                        f"{exc}). It is not an .osm.pbf, or it is truncated.")
        return result

    try:
        counted = _counts(path, limit)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"The file breaks off while being read ({type(exc).__name__}: "
                        f"{exc}). A download that stopped part way looks like this.")
        return result

    counts, tags = counted["counts"], counted["tags"]
    result["tags"] = tags
    result["stats"] = {**counts, "bytes": size,
                       "modified": time.strftime("%Y-%m-%d",
                                                 time.localtime(os.path.getmtime(path))),
                       "header": header,
                       "sampled": counted["sampled"]}
    # A hand-cut file often carries no bounding box in its header; the nodes
    # themselves say what it covers just as well.
    result["bbox"] = header["bbox"] or counted["bbox"]

    if not counts["nodes"] or not counts["ways"]:
        problems.append("The file holds no nodes or no ways: there is nothing "
                        "to draw a map from.")
    for key, what in NEEDED.items():
        if not tags.get(key):
            problems.append(f"No {what} in the file (nothing tagged {key}: {what}).")
    missing = [key for key in NICE if not tags.get(key)]
    if missing:
        warnings.append("Nothing tagged " + ", ".join(missing)
                        + ": those parts of the map will be plain.")

    if not result["bbox"]:
        warnings.append("The header gives no bounding box, so it cannot be "
                        "checked against the area being drawn.")
    elif bbox:
        south, west, north, east = bbox
        hb = result["bbox"]
        if hb[2] < south or hb[0] > north or hb[3] < west or hb[1] > east:
            problems.append(
                f"The file covers {hb[0]:.4f},{hb[1]:.4f} to {hb[2]:.4f},{hb[3]:.4f}, "
                f"which does not overlap the area being drawn "
                f"({south:.4f},{west:.4f} to {north:.4f},{east:.4f}).")
        elif (hb[0] > south + 1e-6 or hb[2] < north - 1e-6
              or hb[1] > west + 1e-6 or hb[3] < east - 1e-6):
            warnings.append("The area being drawn runs past the edge of this "
                            "file: the part outside it will have no data.")

    age = time.time() - os.path.getmtime(path)
    if age > STALE_S:
        warnings.append(f"The file was last written {int(age // 86400)} days ago; "
                        "Geofabrik rebuilds its extracts every day.")
    if size < 1 << 20:
        warnings.append(f"The file is only {size / 1024:.0f} KB, which is small "
                        "for a regional extract.")
    if counted["sampled"]:
        warnings.append(f"Counts are a sample of the first {limit:,} objects.")

    result["ok"] = not problems
    return result


def report_text(result: dict) -> str:
    """The check as lines for a console."""
    stats = result.get("stats") or {}
    lines = [f"{result['path']} — {'usable' if result['ok'] else 'NOT usable'}"]
    if stats:
        lines.append(f"  {stats['bytes'] / 1048576:.1f} MB, written {stats['modified']}, "
                     f"{stats['nodes']:,} nodes, {stats['ways']:,} ways, "
                     f"{stats['relations']:,} relations")
        if result["bbox"]:
            b = result["bbox"]
            lines.append(f"  covers {b[0]:.4f},{b[1]:.4f} to {b[2]:.4f},{b[3]:.4f}")
    for problem in result["problems"]:
        lines.append(f"  ✗ {problem}")
    for warning in result["warnings"]:
        lines.append(f"  ! {warning}")
    return "\n".join(lines)
