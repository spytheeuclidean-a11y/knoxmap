"""Compare two sets of lot files square by square: ours and WorldEd's for the same map.

    python tools/cell_check.py <our lots folder> <WorldEd lots folder> [--show N]

WorldEd picks among a rule's tiles at random, so tiles are compared by what they are: a tile
that belongs to an alias of Rules.txt (a kind of grass, a kind of overlay) stands for that
alias, and a tree or bush from a vegetation rule for its layer. Everything else - walls,
floors, furniture, roofs - is compared by name.
"""
from __future__ import annotations

import collections
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knoxbuild.rules import load_rules  # noqa: E402
from tools.terrain_source import rules_path  # noqa: E402

NONE = 0xFFFFFFFF


def read_cell(lots: str, cx: int, cy: int) -> dict[tuple[int, int, int], list[str]]:
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
        while o < len(ch):
            m = struct.unpack_from("<I", ch, o)[0]
            o += 4
            if m == NONE:
                k += struct.unpack_from("<I", ch, o)[0]
                o += 4
            else:
                z, r = divmod(k, 64)
                a, b = divmod(r, 8)
                out[(i // 32 * 8 + a, i % 32 * 8 + b, z)] = [names[t] for t in struct.unpack_from(f"<{m}I", ch, o)[1:]]
                o += 4 * m
                k += 1
    return out


def canonicaliser():
    rules = load_rules(rules_path())
    alias_of: dict[str, str] = {}
    for name in sorted(rules.aliases):
        for t in rules.aliases[name]:
            alias_of.setdefault(t, "@" + name)
    layer_of: dict[str, str] = {}
    for r in rules.rules:
        for e in r.entries:
            if e not in rules.aliases:
                layer_of.setdefault(e, "#" + r.layer)

    def canon(t: str) -> str:
        return alias_of.get(t) or layer_of.get(t) or t
    return canon


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    show = int(argv[argv.index("--show") + 1]) if "--show" in argv else 0
    if show:
        args.remove(str(show))
    if len(args) != 2:
        print(__doc__)
        return 2
    ours, theirs = args
    canon = canonicaliser()
    cells = sorted({tuple(int(t) for t in f[:-10].split("_")) for f in os.listdir(theirs) if f.endswith(".lotheader")})
    total = same = 0
    kinds_missing = collections.Counter()
    kinds_extra = collections.Counter()
    examples = []
    only_one = 0
    for cx, cy in cells:
        if not os.path.exists(f"{ours}/{cx}_{cy}.lotheader"):
            only_one += 1
            continue
        a, b = read_cell(ours, cx, cy), read_cell(theirs, cx, cy)
        for pos in set(a) | set(b):
            sa, sb = [canon(t) for t in a.get(pos, [])], [canon(t) for t in b.get(pos, [])]
            if not sa and not sb:
                continue
            total += 1
            if sa == sb:
                same += 1
            else:
                for t in set(sb) - set(sa):
                    kinds_missing[t.rsplit("_", 1)[0]] += 1
                for t in set(sa) - set(sb):
                    kinds_extra[t.rsplit("_", 1)[0]] += 1
                if len(examples) < show:
                    examples.append(((cx, cy), pos, a.get(pos, []), b.get(pos, [])))
    print(f"{len(cells)} cells ({only_one} missing from ours); {total} squares with tiles in either; "
          f"{same} identical ({100 * same / max(total, 1):.2f}%)")
    print("  WorldEd has, ours lacks:", dict(kinds_missing.most_common(8)))
    print("  ours has, WorldEd lacks:", dict(kinds_extra.most_common(8)))
    for cell, pos, ours_s, theirs_s in examples:
        print(f"  cell {cell} square {pos}\n     ours    {ours_s}\n     WorldEd {theirs_s}")
    return 0 if same == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
