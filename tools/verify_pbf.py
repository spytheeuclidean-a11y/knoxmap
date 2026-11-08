"""Check an OpenStreetMap extract before building a map from it.

    python tools/verify_pbf.py tennessee-latest.osm.pbf
    python tools/verify_pbf.py tn.osm.pbf --bbox 37.33,-84.37,37.41,-84.32
    python tools/verify_pbf.py tn.osm.pbf --use      # make KnoxMap read it

Exit code is 0 when the file is usable, 1 when it is not, so a script can gate
on it. The app has the same check in its Tools panel (web/geo.py).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="the .osm.pbf to check")
    parser.add_argument("--bbox", metavar="S,W,N,E",
                        help="the area the map will be drawn for")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop counting after this many objects")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="the report as JSON")
    parser.add_argument("--use", action="store_true",
                        help="save it in knoxmap_config.json as pbf_file, so maps read it")
    parser.add_argument("--forget", action="store_true",
                        help="stop using any picked file")
    args = parser.parse_args(argv)

    import knoxpaths
    from generator import pbfcheck

    if args.forget:
        knoxpaths.update_config({"pbf_file": ""})
        print("KnoxMap goes back to choosing an extract by area.")
        return 0
    if args.use:
        if not os.path.isfile(args.path):
            print(f"there is no file at {args.path}", file=sys.stderr)
            return 1
        knoxpaths.update_config({"pbf_file": os.path.abspath(args.path)})
        print(f"KnoxMap reads {os.path.abspath(args.path)} from now on.")

    bbox = None
    if args.bbox:
        try:
            south, west, north, east = (float(v) for v in args.bbox.split(","))
        except ValueError:
            parser.error("--bbox takes four numbers: south,west,north,east")
        bbox = (south, west, north, east)

    kwargs = {} if args.limit is None else {"limit": args.limit}
    result = pbfcheck.check(args.path, bbox=bbox, **kwargs)
    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(pbfcheck.report_text(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
