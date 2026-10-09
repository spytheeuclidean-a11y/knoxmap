"""Walls and doors of a compiled map, as the game will see them.

    python tools/check_buildings.py <map folder> [--show N] [--level N]

Reads the lot files in <map folder>/lots together with the .tbx files in
<map folder>/buildings, and reports, per building:

- missing walls: a square on a building's edge (room next to outside, or next to a
  different room) where the wall belongs, and no wall tile is there. Corner squares
  count only when they have no wall tile at all.
- doors with no wall tile: a door in the plan with only a plain wall (or nothing) under it.
- doors that cannot be walked through: on either side of a door, a tile that blocks.
  Blocking is a tile of a furniture definition of that building, or a tile that Rules.txt
  puts on the vegetation or furniture layer of the ground (bushes, trees, benches), or a
  fence.

It checks the result of the compile, so it sees what the ground puts in front of a door as
well as what the plan does. Exits 1 when anything is found.
"""
from __future__ import annotations

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knoxbuild.buildtiles import parse_tbx  # noqa: E402
from knoxbuild.rules import load_rules  # noqa: E402
from tools.cell_check import read_cell  # noqa: E402
from tools.map_source import ORIGIN_X, read_lots  # noqa: E402
from tools.terrain_source import rules_path  # noqa: E402

UTILITY = ("_fences_", "_lights_", "_struct", "_bridge", "_monument")
NOT_A_WALL = ("walls_detailing", "walls_interior_detailing", "walls_exterior_roofs",
              "walls_decoration", "walls_exterior_detailing")
GROUND_BLOCKING_LAYERS = ("0_Vegetation", "0_Furniture")
BLOCKING_PREFIXES = ("fencing_", "vegetation_trees")
# Bushes and grass overlays are walked through (slowly); they are counted, not failed.
STAIR_PREFIXES = ("fixtures_escalators", "fixtures_stairs", "stairs_", "location_stairs")
SOFT_PREFIXES = ("vegetation_foliage", "blends_")


class Lots:
    """Squares of the compiled map, read a cell at a time."""

    def __init__(self, lots_dir: str, keep: int = 12):
        self.dir, self.keep, self.cache = lots_dir, keep, collections.OrderedDict()

    def at(self, x: int, y: int, z: int) -> list[str]:
        X = x + ORIGIN_X
        key = (X // 256, y // 256)
        if key not in self.cache:
            if len(self.cache) >= self.keep:
                self.cache.popitem(last=False)
            path = os.path.join(self.dir, f"{key[0]}_{key[1]}.lotheader")
            self.cache[key] = read_cell(self.dir, *key) if os.path.exists(path) else {}
        return self.cache[key].get((X % 256, y % 256, z), [])


WALL_ENUMS = {"West", "North", "NorthWest", "SouthEast", "WestDoor", "NorthDoor",
              "WestWindow", "NorthWindow"}


def wall_tiles(b) -> set[str]:
    """The tiles a building uses for its walls: some styles (a shop, a trailer) are not
    called walls_*, so the names come from the building's own tile entries."""
    return {t for e in b.entries for enum, t in e.items()
            if (enum in WALL_ENUMS or enum.startswith(("WestWindow", "NorthWindow")))
            and t and not t.startswith(("fixtures_",) + NOT_A_WALL)}


def is_wall(tile: str, own: set[str] = frozenset()) -> bool:
    return (tile.startswith("walls_") and not tile.startswith(NOT_A_WALL)) or tile in own


def ground_blockers() -> set[str]:
    rules = load_rules(rules_path())
    out = set()
    for r in rules.rules:
        if r.layer in GROUND_BLOCKING_LAYERS:
            for e in r.entries:
                out.update(t for t in rules.aliases.get(e, [e]) if not t.startswith(SOFT_PREFIXES))
    return out


def furniture_tiles(b) -> set[str]:
    return {t for d in b.furniture if d["layer"] not in ("Walls", "WallFurniture", "Curtains")
            for tiles in d["orients"].values() for _x, _y, t in tiles}


def check(project: str, show: int = 8, only_level: int | None = None) -> dict:
    name = os.path.basename(os.path.normpath(project))
    lots = Lots(os.path.join(project, "lots"))
    blockers = ground_blockers()
    found = {"walls": [], "door_wall": [], "door_blocked": []}
    counts = collections.Counter()
    placed = [(t, tx, ty, lv) for t, tx, ty, lv, _w, _h in read_lots(project)
              if not any(k in t for k in UTILITY)]
    parsed = {t: parse_tbx(open(os.path.join(project, "buildings", f"{t}.tbx"), encoding="utf-8").read())
              for t, *_ in placed}
    # Which lot has a room on a square: two parts of one building meet with no wall between.
    owner: dict[tuple[int, int, int], str] = {}
    for t, tx, ty, lv in placed:
        for z, fl in enumerate(parsed[t].floors):
            for y, row in enumerate(fl.rooms):
                for x, v in enumerate(row):
                    if v > 0:
                        owner[(tx + x, ty + y, lv + z)] = t
    for t, tx, ty, lv in placed:
        if any(k in t for k in UTILITY):
            continue
        b = parsed[t]
        if not b.floors:
            continue
        counts["buildings"] += 1
        furn = furniture_tiles(b)
        own = wall_tiles(b)

        def blocks(tile: str) -> bool:
            return tile in furn or tile in blockers or tile.startswith(BLOCKING_PREFIXES)

        for z, fl in enumerate(b.floors):
            if only_level is not None and lv + z != only_level:
                continue

            def room(x: int, y: int) -> int:
                return fl.rooms[y][x] if 0 <= x < b.width and 0 <= y < b.height else 0

            # walls: the north and west edge of every square, ring included
            for y in range(b.height + 1):
                for x in range(b.width + 1):
                    for edge, other in (("north", (x, y - 1)), ("west", (x - 1, y))):
                        if room(x, y) == room(*other):
                            continue
                        if not (room(x, y) or room(*other)):
                            continue
                        # a neighbouring part of the same building: no wall between
                        far = owner.get((tx + other[0], ty + other[1], lv + z))
                        mine = owner.get((tx + x, ty + y, lv + z))
                        if (far and far != t) or (mine and mine != t):
                            continue
                        counts["edges"] += 1
                        tiles = lots.at(tx + x, ty + y, lv + z)
                        if not any(is_wall(tl, own) for tl in tiles):
                            if any(tl.startswith(STAIR_PREFIXES) for tl in tiles):
                                counts["walls_by_stairs"] += 1       # a stair or escalator takes the edge
                                continue
                            what = "roof" if any(tl.startswith(("roofs_", "ceilings")) or "roofs_" in tl
                                                 for tl in tiles) else "other"
                            counts["walls_missing"] += 1
                            counts["walls_missing_" + what] += 1
                            found["walls"].append((t, lv + z, tx + x, ty + y, edge + " (under a roof)" if what == "roof" else edge))
            for o in fl.objects:
                if o.get("type") != "door":
                    continue
                counts["doors"] += 1
                x, y = int(o["x"]), int(o["y"])
                side = [(x - 1, y), (x, y)] if o.get("dir", "N") == "W" else [(x, y - 1), (x, y)]
                if not any(is_wall(tl, own) for tl in lots.at(tx + x, ty + y, lv + z)):
                    counts["doors_without_wall"] += 1
                    found["door_wall"].append((t, lv + z, tx + x, ty + y, o.get("dir")))
                for sx, sy in side:
                    here = lots.at(tx + sx, ty + sy, lv + z)
                    if any(tl.startswith(SOFT_PREFIXES[:1]) for tl in here):
                        counts["doors_with_bushes"] += 1
                    bad = [tl for tl in here if blocks(tl)]
                    if bad:
                        counts["doors_blocked"] += 1
                        found["door_blocked"].append((t, lv + z, tx + sx, ty + sy, bad[0]))
                        break
    return {"name": name, "counts": counts, "found": found}


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    show = int(argv[argv.index("--show") + 1]) if "--show" in argv else 8
    level = int(argv[argv.index("--level") + 1]) if "--level" in argv else None
    for flag in ("--show", "--level"):
        if flag in argv:
            args.remove(argv[argv.index(flag) + 1])
    if len(args) != 1:
        print(__doc__)
        return 2
    r = check(args[0], show, level)
    c, f = r["counts"], r["found"]
    print(f"{r['name']}: {c['buildings']} buildings, {c['edges']} wall edges, {c['doors']} doors")
    print(f"  wall edges with no wall tile : {c['walls_missing']} "
          f"({c['walls_missing_roof']} where a roof tile stands instead, {c['walls_missing_other']} other; "
          f"{c['walls_by_stairs']} more beside stairs are not counted)")
    print(f"  doors with no wall under them: {c['doors_without_wall']}")
    print(f"  doors with a blocked side    : {c['doors_blocked']}")
    print(f"  doors with a bush at them    : {c['doors_with_bushes']} (walked through; not counted above)")
    for key, title in (("walls", "missing wall (file, level, x, y, edge)"),
                       ("door_wall", "door without wall"), ("door_blocked", "blocked door (side square, blocker)")):
        by_file = collections.Counter(x[0] for x in f[key])
        if by_file:
            print(f"  {title}; worst buildings: {by_file.most_common(5)}")
        for x in f[key][:show]:
            print("     ", x)
    return 1 if (c["walls_missing"] or c["doors_without_wall"] or c["doors_blocked"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
