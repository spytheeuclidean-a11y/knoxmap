"""Do the room and building tables built from the .tbx files equal WorldEd's headers?

    headercheck.py <real/real1 | exp/house | bx/<case>> [--show]

Compares, cell by cell and in order, each room's name, level and rectangles, and the building
lists. Room objects are not compared (see knoxbuild/buildheader.py).
"""
import os
import re
import sys

sys.path.insert(0, os.environ.get("KNOXMAP_DIR", "."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "C:/Users/TheTaZe/AppData/Local/Temp/claude/C--KnoxMap/cf336669-7001-42fe-9302-983424f5daee/scratchpad")
from knoxbuild.buildheader import cell_tables, placed_rooms
from knoxbuild.buildtiles import parse_tbx

H = os.path.dirname(os.path.abspath(__file__))


def read_header(path):
    import struct
    d = open(path, "rb").read()
    n = struct.unpack_from("<I", d, 8)[0]
    o = 12
    for _ in range(n):
        o = d.index(b"\n", o) + 1
    u = lambda: struct.unpack_from("<I", d, u.o)[0]
    pos = o + 16
    nr = struct.unpack_from("<I", d, pos)[0]
    pos += 4
    rooms = []
    for _ in range(nr):
        e = d.index(b"\n", pos)
        name = d[pos:e].decode()
        pos = e + 1
        z, nrect = struct.unpack_from("<II", d, pos)
        pos += 8
        rects = [struct.unpack_from("<4I", d, pos + 16 * i) for i in range(nrect)]
        pos += 16 * nrect
        nobj = struct.unpack_from("<I", d, pos)[0]
        pos += 4 + 12 * nobj
        rooms.append({"name": name, "z": z, "rects": rects})
    nb = struct.unpack_from("<I", d, pos)[0]
    pos += 4
    buildings = []
    for _ in range(nb):
        k = struct.unpack_from("<I", d, pos)[0]
        buildings.append(list(struct.unpack_from(f"<{k}I", d, pos + 4)))
        pos += 4 + 4 * k
    return rooms, buildings


proj = f"{H}/{sys.argv[1]}"
name = os.path.basename(proj)
lots, cell = [], None
for line in open(f"{proj}/{name}.pzw", encoding="utf-8"):
    m = re.match(r'\s*<cell x="(\d+)" y="(\d+)"', line)
    if m:
        cell = (int(m[1]), int(m[2]))
    m = re.search(r'<lot x="(\d+)" y="(\d+)" level="(\d+)" width="(\d+)" height="(\d+)" map="buildings/([^"]+)\.tbx"', line)
    if m and cell and not any(k in m[6] for k in ("fences", "lights", "struct", "bridge", "monument")):
        lots.append((cell[0] * 300 + int(m[1]), cell[1] * 300 + int(m[2]), int(m[3]), m[6]))
if name != "real1":      # hand-made cases: the one building at (40, 40)
    lots = [(40, 40, 0, name)] if "bx" in sys.argv[1] else lots
placed = placed_rooms([(parse_tbx(open(f"{proj}/buildings/{t}.tbx", encoding="utf-8").read()), tx, ty, lv)
                       for tx, ty, lv, t in lots])
cells = sorted({tuple(int(t) for t in f[:-10].split("_")) for f in os.listdir(f"{proj}/lots") if f.endswith(".lotheader")})
ok_rooms = bad_rooms = ok_cells = 0
same_order = same_set = 0


def sig(r):
    return (r["name"], r["z"], tuple(sorted(map(tuple, r["rects"]))))


for cx, cy in cells:
    want_rooms, want_buildings = cell_tables(cx, cy, placed)
    got_rooms, got_buildings = read_header(f"{proj}/lots/{cx}_{cy}.lotheader")
    got_rooms = [{"name": r["name"], "z": r["z"], "rects": [tuple(x) for x in r["rects"]]} for r in got_rooms]
    in_order = [sig(r) for r in want_rooms] == [sig(r) for r in got_rooms]
    as_sets = sorted(sig(r) for r in want_rooms) == sorted(sig(r) for r in got_rooms)
    # a building is the set of its rooms, whatever order they are listed in
    part = lambda rooms, bl: sorted(tuple(sorted(sig(rooms[i]) for i in b)) for b in bl)
    same_bl = part(want_rooms, want_buildings) == part(got_rooms, got_buildings)
    same_order += in_order
    same_set += as_sets and same_bl
    if not (as_sets and same_bl) and "--show" in sys.argv:
        print(f"cell {cx}_{cy}: ours {len(want_rooms)} rooms / {len(want_buildings)} buildings, "
              f"WorldEd {len(got_rooms)} / {len(got_buildings)}; same rooms (any order): {as_sets}; same buildings: {same_bl}")
        ours = {sig(r) for r in want_rooms}
        theirs = {sig(r) for r in got_rooms}
        for r in sorted(ours - theirs)[:2]:
            print("   only ours   ", r)
        for r in sorted(theirs - ours)[:2]:
            print("   only WorldEd", r)
print(f"{name}: of {len(cells)} cell headers, {same_set} have the same rooms and the same buildings "
      f"(room order also identical in {same_order})")
