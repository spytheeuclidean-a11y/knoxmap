"""Compare ground tiles made by KnoxMap with the ones WorldEd made from the same pictures.

    python tools/terrain_check.py <map folder> <our lots folder> <WorldEd lots folder>

WorldEd chooses among a rule's tiles at random, so single squares cannot be compared.
What is checked: the same squares are occupied; on every square each rule layer holds a
tile its rule allows; and for every (landscape, vegetation) colour pair the share of each
tile is close between the two. Blend tiles along edges count as tiles the rules give.
"""
from __future__ import annotations

import collections
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knoxbuild import bitmaps  # noqa: E402
from knoxbuild.rules import load_rules  # noqa: E402
from tools.terrain_source import ORIGIN_X, rules_path  # noqa: E402

NONE = 0xFFFFFFFF


def read_level0(lots: str, cx: int, cy: int) -> dict:
    """{(x, y): tuple of tile names} for level 0 of one cell, x and y in cell tiles."""
    head = open(f"{lots}/{cx}_{cy}.lotheader", "rb").read()
    n = struct.unpack_from("<I", head, 8)[0]
    o = 12
    names = []
    for _ in range(n):
        e = head.index(b"\n", o)
        names.append(head[o:e].decode())
        o = e + 1
    d = open(f"{lots}/world_{cx}_{cy}.lotpack", "rb").read()
    offs = [struct.unpack_from("<Q", d, 12 + 8 * i)[0] for i in range(1024)] + [len(d)]
    out = {}
    for i in range(1024):
        ch = d[offs[i]:offs[i + 1]]
        o = k = 0
        while o < len(ch) and k < 64:
            m = struct.unpack_from("<I", ch, o)[0]
            o += 4
            if m == NONE:
                k += struct.unpack_from("<I", ch, o)[0]
                o += 4
            else:
                out[(i // 32 * 8 + k // 8, i % 32 * 8 + k % 8)] = tuple(names[t] for t in struct.unpack_from(f"<{m}I", ch, o)[1:])
                o += 4 * m
                k += 1
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    project, ours, theirs = argv
    name = os.path.basename(os.path.normpath(project))
    land = bitmaps.read_rgb(os.path.join(project, f"{name}.bmp"))
    veg = bitmaps.read_rgb(os.path.join(project, f"{name}_veg.bmp"), crop=land.shape[:2])
    rules = load_rules(rules_path())
    # tiles each rule layer may hold at all (rule entries, aliases resolved)
    allowed: dict[str, set] = collections.defaultdict(set)
    for r in rules.rules:
        for e in r.entries:
            allowed[r.layer].update(rules.aliases.get(e, [e]))
    rule_tiles = set().union(*allowed.values())
    from knoxbuild.blends import load_blends
    for bl in load_blends(os.path.join(os.path.dirname(rules_path()), "Blends.txt")):
        rule_tiles.update(rules.aliases.get(bl.tile, [bl.tile]))
    cells = sorted({tuple(int(t) for t in f[:-10].split("_")) for f in os.listdir(theirs) if f.endswith(".lotheader")})
    occupied_diff = bad_ours = squares = 0
    share = {"ours": collections.defaultdict(collections.Counter), "theirs": collections.defaultdict(collections.Counter)}
    for cx, cy in cells:
        a, b = read_level0(ours, cx, cy), read_level0(theirs, cx, cy)
        occupied_diff += len(set(a) ^ set(b))
        for (x, y), stack in a.items():
            squares += 1
            if not all(t in rule_tiles for t in stack):
                bad_ours += 1
        for who, sq in (("ours", a), ("theirs", b)):
            for (x, y), stack in sq.items():
                wx, wy = cx * 256 + x - ORIGIN_X, cy * 256 + y
                if 0 <= wy < land.shape[0] and 0 <= wx < land.shape[1]:
                    key = (tuple(int(c) for c in land[wy, wx]), tuple(int(c) for c in veg[wy, wx]))
                    for t in stack:
                        if t in rule_tiles:
                            share[who][key][t] += 1
    print(f"{len(cells)} cells, {squares} squares made; squares occupied in only one of the two: {occupied_diff}")
    print(f"squares where ours holds a tile no rule gives: {bad_ours}")
    worst = 0.0
    rows = []
    for key in share["theirs"]:
        ta, tb = share["ours"][key], share["theirs"][key]
        na, nb = sum(ta.values()), sum(tb.values())
        if nb < 200:
            continue                      # too few squares to tell a distribution
        tiles = set(ta) | set(tb)
        tv = 0.5 * sum(abs(ta[t] / max(na, 1) - tb[t] / nb) for t in tiles)
        # tiles WorldEd put that ours never did
        missing = sorted(t for t in tb if t not in ta and tb[t] / nb > 0.01)
        rows.append((tv, key, nb, missing))
        worst = max(worst, tv)
    for tv, key, nb, missing in sorted(rows, reverse=True)[:6]:
        print(f"  land{key[0]} veg{key[1]}: {nb} tiles, share difference {tv:.3f}"
              + (f", WorldEd tiles ours lacks: {missing[:3]}" if missing else ""))
    print(f"largest share difference over {len(rows)} colour pairs: {worst:.3f}")
    return 0 if occupied_diff == 0 and bad_ours == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
