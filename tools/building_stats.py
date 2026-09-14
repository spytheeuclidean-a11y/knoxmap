"""Measure the houses in compiled map files, to compare ours with the game's.

    python tools/building_stats.py vanilla            # Knox County towns
    python tools/building_stats.py output/<map>        # a generated map

Reads .lotheader/.lotpack files - the rooms and buildings list in the header,
the tiles on every square in the pack - and reports, for houses (a building
with a kitchen and a bedroom, three storeys or fewer), the numbers that make a
house look and feel like one: size, storeys, rooms, how glazed the walls are,
how furnished the rooms are, what the roof and the outside walls are dressed
with. The same code measures both sides, so the comparison is like for like.

Header layout (LotFilesWorker256::generateHeaderAux): after the tile names,
chunk size twice, min and max level; rooms (name, level, rects in cell
coordinates, objects); buildings (room ids).
"""
from __future__ import annotations

import collections
import os
import statistics
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CELL = 256
CHUNKS = 32
CHUNK = 8
GAME_MAPS = "D:/SteamLibrary/steamapps/common/ProjectZomboid/media/maps/Muldraugh, KY"
# Residential parts of Knox County, as 256-tile cell ranges (x0, y0, x1, y1).
VANILLA_TOWNS = {
    "Muldraugh": (40, 36, 42, 40),
    "West Point": (45, 26, 47, 28),
    "Riverside": (22, 20, 25, 21),
    "Rosewood": (31, 44, 33, 46),
}

FURNITURE_PREFIXES = ("furniture_", "appliances_", "fixtures_bathroom", "fixtures_sinks",
                      "fixtures_counters", "location_", "recreational_", "floors_rugs",
                      "d_plants", "lighting_indoor", "walls_decoration", "trash_",
                      "carpentry_", "vegetation_indoor")


def _string(data: bytes, pos: int) -> tuple[str, int]:
    end = data.index(b"\n", pos)
    return data[pos:end].decode("latin-1"), end + 1


def read_header(path: str):
    data = open(path, "rb").read()
    pos = 8 if data[:4] == b"LOTH" else 4
    (count,) = struct.unpack_from("<i", data, pos); pos += 4
    names = []
    for _ in range(count):
        n, pos = _string(data, pos)
        names.append(n)
    _cw, _ch, lo, hi = struct.unpack_from("<4i", data, pos); pos += 16
    (nrooms,) = struct.unpack_from("<i", data, pos); pos += 4
    rooms = []
    for _ in range(nrooms):
        name, pos = _string(data, pos)
        level, nrects = struct.unpack_from("<2i", data, pos); pos += 8
        rects = []
        for _ in range(nrects):
            rects.append(struct.unpack_from("<4i", data, pos)); pos += 16
        (nobj,) = struct.unpack_from("<i", data, pos); pos += 4
        pos += 12 * nobj
        rooms.append((name, level, rects))
    (nb,) = struct.unpack_from("<i", data, pos); pos += 4
    buildings = []
    for _ in range(nb):
        (nr,) = struct.unpack_from("<i", data, pos); pos += 4
        ids = struct.unpack_from(f"<{nr}i", data, pos); pos += 4 * nr
        buildings.append(list(ids))
    return names, lo, hi, rooms, buildings


def read_squares(path: str, names: list[str], lo: int, hi: int) -> dict:
    """{(x, y, z): [tile names]} for the whole cell."""
    data = open(path, "rb").read()
    pos = 8 if data[:4] == b"LOTP" else 4
    (n,) = struct.unpack_from("<i", data, pos); pos += 4
    offsets = struct.unpack_from(f"<{n}q", data, pos)
    out = {}
    for cx in range(CHUNKS):
        for cy in range(CHUNKS):
            p = offsets[cx * CHUNKS + cy]
            if p < 0:
                continue
            skip = 0
            for z in range(lo, hi + 1):
                for x in range(CHUNK):
                    for y in range(CHUNK):
                        if skip > 0:
                            skip -= 1
                            continue
                        (count,) = struct.unpack_from("<i", data, p); p += 4
                        if count == -1:
                            (skip,) = struct.unpack_from("<i", data, p); p += 4
                            skip -= 1
                            continue
                        p += 4
                        ids = struct.unpack_from(f"<{count - 1}i", data, p); p += 4 * (count - 1)
                        out[(cx * CHUNK + x, cy * CHUNK + y, z)] = [names[i] for i in ids]
    return out


def measure_cell(folder: str, cx: int, cy: int) -> list[dict]:
    head = os.path.join(folder, f"{cx}_{cy}.lotheader")
    pack = os.path.join(folder, f"world_{cx}_{cy}.lotpack")
    if not (os.path.exists(head) and os.path.exists(pack)):
        return []
    names, lo, hi, rooms, buildings = read_header(head)
    squares = read_squares(pack, names, lo, hi)
    houses = []
    for ids in buildings:
        brooms = [rooms[i] for i in ids if 0 <= i < len(rooms)]
        kinds = {r[0] for r in brooms}
        # Porches, balconies and yards are rooms too ("emptyoutside"); a
        # storey or a footprint is only what is indoors.
        indoor = [r for r in brooms if not r[0].startswith("emptyoutside")]
        levels = sorted({r[1] for r in indoor if r[1] >= 0})
        if not levels or "kitchen" not in kinds or "bedroom" not in kinds or len(levels) > 3:
            continue
        tiles_by_level: dict[int, set] = collections.defaultdict(set)
        room_areas = []
        room_tiles: dict[int, list] = {}
        for i, (name, level, rects) in enumerate(brooms):
            if level < 0 or name.startswith("emptyoutside"):
                continue
            cells = {(x + dx, y + dy) for x, y, w, h in rects
                     for dx in range(w) for dy in range(h)}
            tiles_by_level[level] |= cells
            room_areas.append((name, len(cells)))
            room_tiles[i] = (name, level, cells)
        ground = tiles_by_level[levels[0]]
        if not ground or len(ground) > 600:
            continue
        xs = [x for x, _ in ground]
        ys = [y for _, y in ground]
        # Walls between the house and outside, per level; windows and doors
        # sit on a tile of the house or the tile just outside its edge.
        edges = windows = doors = 0
        for level, cells in tiles_by_level.items():
            for x, y in cells:
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if (nx, ny) not in cells:
                        edges += 1
            ring = cells | {(x + 1, y) for x, y in cells} | {(x, y + 1) for x, y in cells}
            for x, y in ring:
                for name in squares.get((x, y, level), ()):
                    if name.startswith("fixtures_windows_") and "curtain" not in name \
                            and "detailing" not in name:
                        windows += 1
                        break
            for x, y in ring:
                if (x, y) in cells and all(n in cells for n in ((x - 1, y), (x, y - 1))):
                    continue
                if any(n.startswith("fixtures_doors_0") for n in squares.get((x, y, level), ())):
                    doors += 1
        furniture = collections.Counter()
        area_by_kind = collections.Counter()
        for name, level, cells in room_tiles.values():
            area_by_kind[name] += len(cells)
            for x, y in cells:
                furniture[name] += sum(1 for n in squares.get((x, y, level), ())
                                       if n.startswith(FURNITURE_PREFIXES))
        roof = collections.Counter()
        dressing = collections.Counter()
        top = levels[-1]
        bound = {(x + dx, y + dy) for x, y in ground for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        for z in range(levels[0], top + 3):
            for x, y in bound:
                for n in squares.get((x, y, z), ()):
                    if n.startswith("roofs_30"):
                        roof["30"] += 1
                    elif n.startswith("roofs_"):
                        roof["45/flat"] += 1
                    if n.startswith("fixtures_windows_detailing"):
                        dressing["shutters"] += 1
                    elif n.startswith("walls_detailing"):
                        dressing["trim"] += 1
                    elif n.startswith("overlay_grime_wall"):
                        dressing["grime"] += 1
                    elif n.startswith(("lighting_outdoor", "fixtures_railings")):
                        dressing["porch"] += 1
        houses.append({
            "area": len(ground), "w": max(xs) - min(xs) + 1, "h": max(ys) - min(ys) + 1,
            "storeys": len(levels), "rooms": len(room_areas),
            "room_area": statistics.mean(a for _, a in room_areas),
            "windows_per_10_wall": 10 * windows / max(1, edges),
            "outside_doors": doors,
            "furniture_per_10m2": {k: 10 * furniture[k] / area_by_kind[k]
                                   for k in area_by_kind if area_by_kind[k]},
            "kinds": collections.Counter(n for n, _ in room_areas),
            "roof30": roof["30"] > roof["45/flat"],
            "shutters": dressing["shutters"] > 0, "trim": dressing["trim"] > 0,
            "grime": dressing["grime"] > 0, "porch": dressing["porch"] > 0,
        })
    return houses


def summary(houses: list[dict]) -> dict:
    if not houses:
        return {}

    def med(key):
        return statistics.median(h[key] for h in houses)

    per_room = collections.defaultdict(list)
    kinds = collections.Counter()
    for h in houses:
        for k, v in h["furniture_per_10m2"].items():
            per_room[k].append(v)
        kinds.update(h["kinds"])
    return {
        "houses": len(houses),
        "footprint m2 (median)": med("area"),
        "width x depth (median)": f"{med('w')} x {med('h')}",
        "one storey %": round(100 * sum(h["storeys"] == 1 for h in houses) / len(houses)),
        "rooms per house (median)": med("rooms"),
        "room size m2 (median)": round(med("room_area"), 1),
        "windows per 10 m wall": round(statistics.mean(h["windows_per_10_wall"] for h in houses), 2),
        "outside doors (median)": med("outside_doors"),
        "30-degree roof %": round(100 * sum(h["roof30"] for h in houses) / len(houses)),
        "shutters %": round(100 * sum(h["shutters"] for h in houses) / len(houses)),
        "trim %": round(100 * sum(h["trim"] for h in houses) / len(houses)),
        "grime %": round(100 * sum(h["grime"] for h in houses) / len(houses)),
        "porch/rail/light %": round(100 * sum(h["porch"] for h in houses) / len(houses)),
        "furniture per 10 m2": {k: round(statistics.median(v), 1)
                                for k, v in sorted(per_room.items()) if len(v) >= 5},
        "rooms by kind per house": {k: round(v / len(houses), 2)
                                    for k, v in kinds.most_common(10)},
    }


def main(argv: list[str]) -> int:
    import json

    target = argv[1] if len(argv) > 1 else "vanilla"
    houses = []
    if target == "vanilla":
        for x0, y0, x1, y1 in VANILLA_TOWNS.values():
            for cx in range(x0, x1 + 1):
                for cy in range(y0, y1 + 1):
                    houses += measure_cell(GAME_MAPS, cx, cy)
    else:
        lots = os.path.join(target, "lots")
        for f in os.listdir(lots):
            if f.endswith(".lotheader"):
                cx, cy = (int(v) for v in f[:-10].split("_"))
                houses += measure_cell(lots, cx, cy)
    print(json.dumps(summary(houses), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
