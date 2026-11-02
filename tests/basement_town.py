"""A small town for the basement tests: two streets of houses, built and compiled.

`extra` adds OpenStreetMap features (a military base, a school) to the same
ground. `digest` is what a build put in the game's files: the buildings and the
compiled lots, which carry no paths, so two folders can be compared.
"""
from __future__ import annotations

import contextlib
import glob
import hashlib
import io
import os

from tools.selftest import EAST, NORTH, SOUTH, WEST, box, way


def features(extra=()) -> list:
    feats = [way({"highway": "residential", "name": "First Street"}, [(40, 100), (400, 100)]),
             way({"highway": "residential", "name": "Second Street"}, [(40, 220), (400, 220)])]
    for n in range(8):
        x = 60 + n * 40
        feats.append(way({"building": "house"}, box(x, 110, x + 11, 122)))
        feats.append(way({"building": "house"}, box(x, 196, x + 11, 208)))
    return feats + list(extra)


def build_town(out: str, settings, extra=(), compile_lots: bool = True) -> str:
    """Terrain, buildings and (when knoxlots is there) lots for the town, in `out`."""
    from generator import renderer
    from knoxbuild.build import build
    from knoxbuild.world import origin, set_origin
    from tools.compile_map import compile_rust, knoxlots_exe

    was = origin()
    try:
        name = os.path.basename(os.path.normpath(out))
        with contextlib.redirect_stdout(io.StringIO()):
            renderer.render(features(extra), SOUTH, WEST, NORTH, EAST, meters_per_tile=1.0,
                            output_dir=out, map_name=name)
            build(out, settings=settings)
            if compile_lots and knoxlots_exe():
                compile_rust(out)
    finally:
        set_origin(was)
    return out


def digest(out: str) -> dict[str, str]:
    """SHA-1 of every .tbx and every lot file, by name."""
    files = sorted(glob.glob(os.path.join(out, "buildings", "*.tbx"))
                   + glob.glob(os.path.join(out, "lots", "*.lot*"))
                   + glob.glob(os.path.join(out, "lots", "chunkdata_*.bin")))
    return {os.path.relpath(f, out).replace("\\", "/"):
            hashlib.sha1(open(f, "rb").read()).hexdigest() for f in files}
