"""Print what WorldEd put on each square of a hand-made building, level by level.

    bxshow.py <case> [x0 y0 w h]       region in tiles of the first 300 x 300 cell
"""
import os
import struct
import sys

H = os.path.dirname(os.path.abspath(__file__))
NONE = 0xFFFFFFFF
ORIGIN = 21000
SHORT = [("walls_exterior_house_01_", "WX"), ("walls_exterior_roofs_01_", "RF"), ("walls_interior_house_01_", "WI"),
         ("floors_interior_tilesandwood_01_", "FT"), ("floors_interior_carpet_01_", "FC"), ("floors_", "F"),
         ("fixtures_doors_01_", "DR"), ("fixtures_doors_frames_01_", "DF"), ("walls_exterior_", "WE"),
         ("walls_interior_", "WN"), ("fixtures_windows_01_", "WD"), ("fixtures_stairs_01_", "ST"),
         ("blends_natural_01_", "g"), ("carpentry_02_", "cp"), ("furniture_", "fu"), ("lighting_", "li")]


def short(n):
    for p, s in SHORT:
        if n.startswith(p):
            return s + n[len(p):].lstrip("0") if n[len(p):].strip("0") else s + "0"
    return n


def load(lots, cx, cy):
    head = open(f"{lots}/{cx}_{cy}.lotheader", "rb").read()
    n = struct.unpack_from("<I", head, 8)[0]
    o = 12
    names = []
    for _ in range(n):
        e = head.index(b"\n", o)
        names.append(head[o:e].decode())
        o = e + 1
    minz, maxz = struct.unpack_from("<II", head, o + 8)
    d = open(f"{lots}/world_{cx}_{cy}.lotpack", "rb").read()
    offs = [struct.unpack_from("<Q", d, 12 + 8 * i)[0] for i in range(1024)] + [len(d)]
    sq = {}
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
                sq[(i // 32 * 8 + a, i % 32 * 8 + b, z)] = [names[t] for t in struct.unpack_from(f"<{m}I", ch, o)[1:]]
                o += 4 * m
                k += 1
    return sq, maxz - minz + 1


if __name__ == "__main__":
    case = sys.argv[1]
    x0, y0, w, h = (int(a) for a in sys.argv[2:6]) if len(sys.argv) > 5 else (38, 38, 10, 9)
    lots = f"{H}/bx/{case}/lots"
    cx = (ORIGIN + x0) // 256
    sq, levels = load(lots, cx, 0)
    print(f"{case}: {levels} levels in cell {cx}_0")
    legend = {}
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    for z in range(levels):
        print(f"-- level {z}   (x {x0}..{x0 + w - 1} across, y {y0}..{y0 + h - 1} down)")
        for y in range(y0, y0 + h):
            row = []
            for x in range(x0, x0 + w):
                st = sq.get(((ORIGIN + x) - cx * 256, y, z), [])
                if z == 0 and st and st[0].startswith("blends_natural"):
                    st = st[1:]
                key = tuple(st)
                if not key:
                    row.append(".")
                else:
                    if key not in legend:
                        legend[key] = letters[len(legend)] if len(legend) < len(letters) else "?"
                    row.append(legend[key])
            print(f"{y:3} " + " ".join(row))
    print("legend (bottom tile first):")
    for key, ch in legend.items():
        print(f"  {ch} = " + " + ".join(key))
