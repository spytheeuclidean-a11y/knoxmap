"""Controlled WorldEd experiments: change one map feature, compile, compare the lot files.

    exp.py <variant> [...]      variants: base water forest road house park
Output goes to scratchpad/exp/<variant>/ ; the lot files are decoded and summarised.
"""
import collections
import contextlib
import io
import os
import shutil
import sys

sys.path.insert(0, "C:/KnoxMap")
from generator import renderer
from generator.osm import OSMFeature
from knoxbuild.build import build
from knoxbuild.settings import Settings
from tools import compile_map as cm

S, W, N, E = 40.0000, 20.0000, 40.0054, 20.0070
HERE = os.path.dirname(os.path.abspath(__file__))  # experiments write to ./exp/<variant>
ids = iter(range(1, 10 ** 6))


def box(s, w, n, e, tags):
    """A rectangle given as fractions of the area (0..1), south-west origin."""
    la, lo = N - S, E - W
    pts = [(S + s * la, W + w * lo), (S + s * la, W + e * lo), (S + n * la, W + e * lo),
           (S + n * la, W + w * lo), (S + s * la, W + w * lo)]
    return OSMFeature(next(ids), "way", tags, pts)


def line(a, b, tags):
    la, lo = N - S, E - W
    pts = [(S + a[0] * la, W + a[1] * lo), (S + b[0] * la, W + b[1] * lo)]
    return OSMFeature(next(ids), "way", tags, pts)


VARIANTS = {
    "base": [],
    "water": [box(0.55, 0.55, 0.8, 0.8, {"natural": "water"})],
    "forest": [box(0.55, 0.55, 0.8, 0.8, {"natural": "wood"})],
    "road": [line((0.1, 0.05), (0.9, 0.95), {"highway": "residential"})],
    "house": [box(0.2, 0.2, 0.26, 0.27, {"building": "house"})],
    "park": [box(0.55, 0.55, 0.8, 0.8, {"leisure": "park"})],
}


def make(name):
    out = f"{HERE}/exp/{name}"
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    feats = VARIANTS[name]
    renderer.render(feats, S, W, N, E, meters_per_tile=1.0, output_dir=out, map_name=name)
    with contextlib.redirect_stdout(io.StringIO()):
        build(out, settings=Settings(seed=1, true_map=1))
        cm.compile_map(out, batch=2, incremental=False)
    return out


def summarise(out):
    lots = f"{out}/lots"
    res = {}
    for f in sorted(os.listdir(lots)):
        if f.startswith("chunkdata_"):
            c = open(f"{lots}/{f}", "rb").read()
            res[f] = (collections.Counter(c[2:1026]), (len(c) - 1026) // 64)
        elif f.endswith(".lotheader"):
            h = open(f"{lots}/{f}", "rb").read()[-1024:]
            res[f] = (collections.Counter(h), 0)
    return res


if __name__ == "__main__":
    for v in sys.argv[1:]:
        out = make(v)
        print("==", v, out)
        tot = collections.Counter()
        blocks = 0
        hdr = collections.Counter()
        for f, (cnt, nb) in summarise(out).items():
            if f.startswith("chunkdata_"):
                tot.update(cnt)
                blocks += nb
            else:
                hdr.update(cnt)
        print("   chunkdata values", dict(sorted(tot.items())), "blocks", blocks)
        print("   header bytes", dict(sorted(hdr.items())))
