"""Why is there nothing here? What a map did with the buildings in one place.

    python tools/why_no_building.py <map folder>
    python tools/why_no_building.py <map folder> --at 39.1155,27.1884 --radius 120
    python tools/why_no_building.py <map folder> --tiles 300,420 --radius 60
    python tools/why_no_building.py <map folder> --reason road --list 40
    python tools/why_no_building.py <map folder> --name "Attalos"
    python tools/why_no_building.py <map folder> --osm 24992409

A map is never all of OpenStreetMap: footprints are left out for being too
small to furnish, too large to lay out, off the edge of the map, already
covered by another building, or mostly road. The build says how many went
each way, which is no help at all to somebody looking at the gap where their
own house should be. Build writes a row per footprint it left out
(`<map>_left_out.csv`), and this reads those back for one place and says, in
order, what happened to every building near it - the ones that were built as
well as the ones that were not.

`--at` takes latitude,longitude, `--tiles` takes a position on the map as the
in-game coordinates do; `--radius` is in tiles (about a metre each at the
usual scale). With neither, the whole map is summed up.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from knoxbuild import why  # noqa: E402  (after the path is set up)

# The wording lives in knoxbuild/why.py so that the window and this tool
# cannot answer the same question two different ways.
WHY = why.WHY
FIX = why.FIX
read_rows = why.read_rows
describe = why.describe


def number(row: dict, *names, default=0.0) -> float:
    for name in names:
        try:
            return float(row[name])
        except (KeyError, TypeError, ValueError):
            continue
    return default


def near(row: dict, centre, radius: float, latlon: bool) -> bool:
    if centre is None:
        return True
    if latlon:
        lat, lon = number(row, "lat"), number(row, "lon")
        if not lat and not lon:
            return False
        # Degrees are not tiles; compare in metres, roughly.
        dy = (lat - centre[0]) * 111320.0
        dx = (lon - centre[1]) * 111320.0 * math.cos(math.radians(centre[0]))
    else:
        dx = number(row, "tile_x") - centre[0]
        dy = number(row, "tile_y") - centre[1]
    return math.hypot(dx, dy) <= radius


def main(argv: list[str]) -> int:
    # Building names are whatever the place calls them, and a Windows console
    # is not UTF-8: without this, "Kızıl Avlu" comes out as mojibake or stops
    # the tool with a UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(
        description="What a map did with the buildings in one place.")
    ap.add_argument("map_folder")
    ap.add_argument("--at", help="latitude,longitude to look around")
    ap.add_argument("--tiles", help="x,y on the map to look around")
    ap.add_argument("--radius", type=float, default=100.0,
                    help="how far to look, in tiles (default 100)")
    ap.add_argument("--reason", help="only this reason")
    ap.add_argument("--name", help="only buildings whose name holds this")
    ap.add_argument("--osm", help="one building, by its OpenStreetMap id")
    ap.add_argument("--list", type=int, default=20,
                    help="how many to name (default 20)")
    args = ap.parse_args(argv[1:])

    folder = args.map_folder.rstrip("/\\")
    name = os.path.basename(folder)
    left = read_rows(why.left_out_path(folder))
    placed = read_rows(why.placements_path(folder))
    if not left and not placed:
        print(f"No building records in {folder}.\n"
              f"Looked for {name}_left_out.csv and {name}_placements.csv - "
              f"generate the buildings first, or check the folder.")
        return 2

    centre = latlon = None
    if args.at:
        centre = tuple(float(v) for v in args.at.split(","))
        latlon = True
    elif args.tiles:
        centre = tuple(float(v) for v in args.tiles.split(","))
        latlon = False

    # One building, asked for by what is known about it rather than where it
    # is: its OpenStreetMap id, or part of its name. An id is the only handle
    # that is certain - plenty of buildings have no name at all - and it is
    # what openstreetmap.org/way/<id> opens.
    if args.osm:
        wanted = args.osm.strip().rsplit("/", 1)[-1]
        one = [r for r in left if r.get("osm_id") == wanted]
        if not one:
            built_here = any(r for r in placed if wanted and wanted in str(r))
            print(f"Nothing was left out with the id {wanted}."
                  + ("  It looks like it was built." if built_here else
                     "  It is not among this map's footprints at all - check"
                     " the id, or whether it is inside the area you drew."))
            return 0
        for r in one:
            print(f"{describe(r)}\n  left out: {r['reason']} - "
                  f"{WHY.get(r['reason'], '')}\n  -> {FIX.get(r['reason'], '')}")
        return 0

    here = [r for r in left if near(r, centre, args.radius, bool(latlon))]
    if args.reason:
        here = [r for r in here if r["reason"] == args.reason]
    if args.name:
        want = args.name.casefold()
        here = [r for r in here if want in (r.get("name") or "").casefold()]
    # A placement row has no lat/lon, so a lat/lon search counts only tiles.
    built = [r for r in placed
             if near({"tile_x": r.get("tile_x"), "tile_y": r.get("tile_y")},
                     centre if not latlon else None, args.radius, False)]

    where = (f"within {args.radius:.0f} tiles of "
             + (f"{centre[0]}, {centre[1]}" if centre else "")) if centre \
        else "on the whole map"
    print(f"{name}: {where}")
    print(f"  built     : {len(built)}")
    print(f"  left out  : {len(here)}")
    if not here:
        print("\nEvery footprint here became a building.")
        return 0

    counts: dict[str, int] = {}
    for r in here:
        counts[r["reason"]] = counts.get(r["reason"], 0) + 1
    print()
    for reason, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5}  {reason}: {WHY.get(reason, '')}")
        print(f"         -> {FIX.get(reason, '')}")

    print(f"\nThe nearest {min(args.list, len(here))}:")
    if centre:
        here.sort(key=lambda r: math.hypot(
            number(r, "tile_x") - (centre[0] if not latlon else number(r, "tile_x")),
            number(r, "tile_y") - (centre[1] if not latlon else number(r, "tile_y"))))
    for r in here[:args.list]:
        print(f"  {r['reason']:16} {describe(r)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
