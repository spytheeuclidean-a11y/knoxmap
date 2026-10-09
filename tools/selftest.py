"""Run the whole generator on a made-up town, offline, and check the result.

    python tools/selftest.py [--keep]

No internet, no game and no map tools needed: the town is invented here - a
street grid turned 30 degrees, a main road, a coast with the sea beyond, a
river and its bridge, a park, a multipolygon lake with an island, a school,
a church, flats of seven storeys (tall enough for a lift) and a row of
houses. It goes through the same steps as the app - terrain, buildings, the
paper map, the installed mod - and each step's output is checked for the
things that have broken before. Exits non-zero on any failure, so it can
gate a change (see .github/workflows/checks.yml).
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from generator import pz_colors as C  # noqa: E402
from generator.osm import OSMFeature  # noqa: E402

# A town near 40N, about 600 m across.
SOUTH, WEST = 40.0000, 20.0000
NORTH, EAST = 40.0054, 20.0070
ANGLE = math.radians(30)
_ids = iter(range(1, 10 ** 6))


def _ll(x_m: float, y_m: float) -> tuple[float, float]:
    """Metres east/north of the south-west corner, turned by ANGLE, to (lat, lon)."""
    cx, cy = 300.0, 300.0
    dx, dy = x_m - cx, y_m - cy
    rx = cx + dx * math.cos(ANGLE) - dy * math.sin(ANGLE)
    ry = cy + dx * math.sin(ANGLE) + dy * math.cos(ANGLE)
    return SOUTH + ry / 111320.0, WEST + rx / (111320.0 * math.cos(math.radians(SOUTH)))


def way(tags: dict, pts_m: list[tuple[float, float]]) -> OSMFeature:
    return OSMFeature(next(_ids), "way", tags, [_ll(x, y) for x, y in pts_m])


def box(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def town() -> list[OSMFeature]:
    feats = []
    # Street grid, 80 m blocks, and one main road through the middle.
    for i in range(1, 7):
        feats.append(way({"highway": "residential", "name": f"Street {i}"},
                         [(i * 80, 60), (i * 80, 540)]))
        feats.append(way({"highway": "residential", "name": f"Avenue {i}"},
                         [(60, i * 80), (540, i * 80)]))
    feats.append(way({"highway": "primary", "name": "High Street", "lanes": "2"},
                     [(0, 300), (600, 300)]))
    # Buildings in the blocks: houses, flats tall enough for a lift, a school, a church.
    for bx in range(0, 5):
        for by in range(0, 5):
            x0, y0 = 90 + bx * 80, 90 + by * 80
            if (bx, by) == (2, 2):
                feats.append(way({"building": "apartments", "building:levels": "7"},
                                 box(x0, y0, x0 + 45, y0 + 30)))
            elif (bx, by) == (1, 3):
                feats.append(way({"building": "school", "name": "Selftest School"},
                                 box(x0, y0, x0 + 55, y0 + 40)))
            elif (bx, by) == (3, 1):
                feats.append(way({"building": "church", "name": "Selftest Church"},
                                 box(x0, y0, x0 + 30, y0 + 50)))
            elif (bx, by) == (4, 0):
                # A petrol station with room for a forecourt, and a car park.
                feats.append(way({"building": "retail", "amenity": "fuel", "name": "Selftest Gas"},
                                 box(x0 + 10, y0 + 5, x0 + 24, y0 + 15)))
                feats.append(way({"amenity": "parking"}, box(x0, y0 + 30, x0 + 60, y0 + 62)))
                # And its canopy, a roof over the forecourt, where the pumps go.
                feats.append(way({"building": "roof", "amenity": "fuel"},
                                 box(x0 + 34, y0 + 4, x0 + 54, y0 + 16)))
            elif (bx, by) == (0, 4):
                # A pizza place and a supermarket, to be fitted out as such.
                feats.append(way({"building": "yes", "amenity": "restaurant", "cuisine": "pizza",
                                  "name": "Selftest Pizza"}, box(x0, y0, x0 + 16, y0 + 12)))
                feats.append(way({"building": "retail", "shop": "supermarket",
                                  "name": "Selftest Market"}, box(x0 + 22, y0, x0 + 50, y0 + 24)))
            else:
                for k in range(3):
                    feats.append(way({"building": "house"},
                                     box(x0 + k * 20, y0, x0 + k * 20 + 12, y0 + 10)))
    feats.append(way({"leisure": "park", "name": "Selftest Park"}, box(410, 410, 470, 470)))
    # A churchyard beside the church, an army base, a parade of shops, a police
    # station and a library - the land uses and buildings 1.3.6 added.
    feats.append(way({"landuse": "cemetery", "name": "Selftest Cemetery"},
                     box(250, 410, 330, 470)))
    feats.append(way({"landuse": "military", "name": "Selftest Camp"},
                     box(100, 410, 200, 480)))
    feats.append(way({"military": "barracks", "building": "yes", "name": "Selftest Barracks"},
                     box(120, 430, 150, 450)))
    feats.append(way({"building": "retail", "name": "Selftest Parade"},
                     box(170, 92, 290, 114)))
    feats.append(way({"building": "yes", "amenity": "police", "name": "Selftest Police"},
                     box(330, 250, 366, 278)))
    feats.append(way({"building": "yes", "amenity": "library", "name": "Selftest Library"},
                     box(330, 200, 360, 226)))
    # A street where the homes were never drawn - only their numbers.
    for k in range(8):
        feats.append(OSMFeature(next(_ids), "node",
                                {"addr:housenumber": str(k * 2 + 1),
                                 "addr:street": "Avenue 6"},
                                [_ll(120 + k * 14, 500)]))
    # A river with a bridge carrying High Street over it.
    feats.append(way({"waterway": "river", "name": "Selftest River"}, [(560, 30), (560, 600)]))
    feats.append(way({"natural": "water", "water": "river"}, box(550, 0, 572, 600)))
    # A lane over the river on a bridge a little off square, to be laid square.
    feats.append(way({"highway": "residential"}, [(500, 452), (540, 452)]))
    feats.append(way({"highway": "residential", "bridge": "yes", "layer": "1",
                      "name": "Selftest Bridge"}, [(540, 452), (582, 458)]))
    feats.append(way({"highway": "residential"}, [(582, 458), (600, 458)]))
    # A flyover: a main road on a bridge over Avenue 5, with room for ramps.
    feats.append(way({"highway": "primary"}, [(510, 250), (510, 330)]))
    feats.append(way({"highway": "primary", "bridge": "yes", "layer": "1",
                      "name": "Selftest Flyover"}, [(510, 330), (510, 470)]))
    feats.append(way({"highway": "primary"}, [(510, 470), (510, 540)]))
    # A statue and a triumphal arch in the park.
    statue = OSMFeature(next(_ids), "node", {"historic": "memorial", "memorial": "statue",
                                             "name": "Selftest Statue"}, [_ll(450, 450)])
    feats.append(statue)
    feats.append(way({"building": "triumphal_arch", "historic": "monument", "height": "12",
                      "name": "Selftest Arch"}, box(420, 420, 432, 425)))
    # A water tower on the edge of town, mapped as a building the way a
    # surveyor maps one. classify_building has no kind for it, so it used to
    # come out as a bungalow with a sofa in it.
    feats.append(way({"man_made": "water_tower", "building": "yes",
                      "name": "Selftest Water Tower"}, box(392, 420, 400, 428)))
    # A coast along the south: land on the left of the line, sea to the right.
    # Deliberately short: a real download often holds only part of a shore.
    feats.append(way({"natural": "coastline"}, [(0, 30), (600, 30)]))
    # A lake as a multipolygon of two outer ways and an island.
    lake = OSMFeature(next(_ids), "relation", {"natural": "water", "name": "Selftest Lake"},
                      [])
    a = [(20, 420), (20, 500), (60, 500)]
    b = [(60, 500), (60, 420), (20, 420)]
    island = box(32, 450, 44, 466)
    lake.role_geoms = [("outer", [_ll(*p) for p in a]), ("outer", [_ll(*p) for p in b]),
                       ("inner", [_ll(*p) for p in island])]
    from generator.osm import assemble_rings
    lake.role_geoms = assemble_rings(lake.role_geoms)
    lake.geometry = [ring for _r, ring in lake.role_geoms]
    feats.append(lake)
    return feats


class Checks:
    def __init__(self):
        self.failed = 0

    def __call__(self, ok: bool, what: str) -> None:
        print(("  ok    " if ok else "  FAIL  ") + what)
        if not ok:
            self.failed += 1


def check_1_3_6(check, out: str, tbx: list[str], pzw_text: str, log: str) -> None:
    """What 1.3.6 added: rows cut into units, rooms the game can fill, police
    stations and libraries, graves, army bases, and a place in the world of
    this map's own."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from audit_layouts import door_pair

    from knoxbuild import layout
    from knoxbuild.world import WORLD_ORIGIN_CELLS, choose_origin

    texts = {os.path.basename(p): open(p, encoding="utf-8").read() for p in tbx}

    # The 120 m parade of shops is several buildings, not one shed.
    units = [n for n in texts if re.fullmatch(r"selftest_\d+_\d+\.tbx", n)]
    check(len(units) >= 4, f"a row of shops is cut into its units ({len(units)})")

    # Every room small enough that the game fills every container in it. The
    # game caps filled containers per room, so one room the size of a factory
    # floor has loot at one end and bare shelves at the other.
    from knoxbuild.settings import Settings as _S
    # The cap is by what the building is: Knox County's own churches, gyms,
    # libraries and warehouses are far bigger than a house's rooms, and held
    # to one size they came out as a grid of cubicles.
    over = []
    for kind, w, h in (("industrial", 140, 110), ("civic", 200, 200),
                       ("apartment", 60, 40), (None, 30, 24),
                       ("church", 40, 60), ("library", 40, 30),
                       ("school", 60, 45)):
        plan = layout.build_building(w, h, commercial=True, seed=3, kind=kind,
                                     levels=1, settings=_S()).storeys[0]
        # Bar the landing of a block of flats, which is a corridor by
        # design and holds nothing worth filling.
        biggest = max((r.x1 - r.x0 + 1) * (r.y1 - r.y0 + 1)
                      for r in plan.rooms if not r.is_core)
        # The cap is where the splitter stops cutting, not a hard ceiling:
        # a region it cannot halve again without making a room narrower than
        # three tiles comes out over. A quarter over is the slack that allows.
        allowed = layout._room_cap(kind) * 1.25
        if not 0 < biggest <= allowed:
            over.append(f"{kind}:{biggest}>{allowed:.0f}")
    check(not over,
          f"no room is bigger than the game will fill for its kind "
          f"({'; '.join(over) or 'none over'})")

    rooms = {m for t in texts.values() for m in re.findall(r'InternalName="(\w+)"', t)}
    check("policeoffice" in rooms and "policelocker" in rooms,
          "the police station is a police station inside")
    check("library" in rooms, "the library has reading rooms")
    check("armystorage" in rooms, "the barracks holds army stores")

    props = [n for n in texts if n.startswith("selftest_props_")]
    graves = sum(t.count("location_community_cemetary_01_") for n, t in texts.items()
                 if n.startswith("selftest_props_"))
    stores = sum(t.count("location_military_generic_01_") for n, t in texts.items()
                 if n.startswith("selftest_props_"))
    check(props and graves >= 20 and any("selftest_props_" in line
                                         for line in pzw_text.splitlines()),
          f"the churchyard has headstones in it ({graves})")
    check(stores >= 2, f"the army base has stores on it ({stores})")

    # The base is fenced whether or not anyone drew the fence.
    wire = sum(t.count("fencing_01_059") + t.count("fencing_01_056")
               for n, t in texts.items() if "_fences_" in n)
    check(wire >= 20, f"the army base is fenced off ({wire} tiles of wire)")

    # Homes that the map only had an address for.
    geo = json.load(open(os.path.join(out, "selftest_buildings.geojson"), encoding="utf-8"))
    addressed = [f for f in geo["features"]
                 if (f.get("properties") or {}).get("addr:street") == "Avenue 6"]
    check(len(addressed) >= 6,
          f"a street of addresses with no buildings gets houses ({len(addressed)})")

    # Trees and scrub on ground nobody mapped, and none on the farmland.
    from generator import pz_colors as _C
    from generator import renderer as _r

    class _P:
        meters_per_tile = 1.0
    land = Image.new("RGB", (400, 300), _C.DARK_GRASS)
    pen = land.load()
    for x in range(200, 400):
        for y in range(300):
            pen[x, y] = _C.LIGHT_GRASS          # a field
    veg = Image.new("RGB", (400, 300), _C.VEG_NOTHING)
    grown = _r._paint_wild_growth(veg, land, _P(), density=1.0)
    grid = veg.load()
    field = sum(1 for x in range(210, 390) for y in range(10, 290)
                if grid[x, y] != _C.VEG_NOTHING)
    check(grown >= 30 and field == 0,
          f"open country grows trees and scrub, farmland stays a field ({grown})")

    # A building big enough to walk round has more than one way in. One door
    # on a hundred metres of wall was "some buildings generate without any
    # door": whichever side you arrived from, there was none.
    from knoxbuild.settings import Settings as _S2

    def ways_in(kind, w, h):
        plan = layout.build_building(w, h, commercial=True, seed=6, kind=kind,
                                     levels=1, settings=_S2()).storeys[0]
        return len([d for d in plan.doors
                    if door_pair(plan, d) is None or 0 in (door_pair(plan, d) or (0,))])

    check(ways_in("church", 30, 50) >= 3 and ways_in("industrial", 70, 50) >= 3,
          "a big building has more than one way in")
    check(ways_in(None, 12, 9) <= 2, "a house still has its front and back door")

    # A big room is lit at both ends: the game hangs one ceiling light per
    # switch, and one switch left a sales floor dark.
    mall = layout.build_building(46, 34, commercial=True, seed=11, kind="shop",
                                 levels=1, settings=_S2(), street="S",
                                 uses=[("departmentstore", "storage")]).storeys[0]
    per_room = {}
    for role, x, y, _o in mall.furniture:
        if role == "switch":
            per_room[mall.grid[y][x]] = per_room.get(mall.grid[y][x], 0) + 1
    check(max(per_room.values(), default=0) >= 4,
          f"a big room has several light switches ({max(per_room.values(), default=0)})")

    # And its aisles are not forty copies of one shelf.
    from collections import Counter as _Counter
    aisle = _Counter(role for role, _x, _y, _o in mall.furniture
                     if role in ("clothes_rack", "clothes_rack_small",
                                 "shop_shelf_wood", "shop_display"))
    check(len(aisle) >= 3,
          f"a mall's rows are a mix, not one piece repeated ({dict(aisle)})")

    # The first map on a PC keeps the old origin, and so does the next one:
    # generating makes a new folder every time, and those used to claim their
    # cells for good, so each map started further east than the last until the
    # town drew as a speck in the corner of the paper map.
    origin = re.search(r'<worldOrigin origin="(\d+),(\d+)"', pzw_text)
    check(origin and (int(origin.group(1)), int(origin.group(2))) == WORLD_ORIGIN_CELLS,
          "the first map is built where every map used to be")
    beside = os.path.join(os.path.dirname(out), "elsewhere")
    os.makedirs(beside, exist_ok=True)
    # On a PC with nothing installed, whatever is sitting in output/.
    empty = tempfile.mkdtemp(prefix="knoxmap-zomboid-")
    was = os.environ.get("ZOMBOID_DIR")
    os.environ["ZOMBOID_DIR"] = empty
    try:
        picked = choose_origin(beside, 3, 3)
        check(picked == WORLD_ORIGIN_CELLS,
              f"a map built beside one nobody installed lands there too "
              f"(cell {picked[0]},{picked[1]})")

        # What does stand clear is a map already installed, which is the only
        # thing that can be in the same world at the same time.
        cells = (Path(empty) / "mods" / "SomeOtherMap" / "common" / "media"
                 / "maps" / "Some Other Map")
        cells.mkdir(parents=True, exist_ok=True)
        for cx in range(82, 86):
            (cells / f"world_{cx}_0.lotheader").write_text("")
        picked = choose_origin(beside, 3, 3)
        check(picked[0] >= WORLD_ORIGIN_CELLS[0] + 3,
              f"a map is built clear of one already installed "
              f"(cell {picked[0]},{picked[1]})")
    finally:
        if was is None:
            os.environ.pop("ZOMBOID_DIR", None)
        else:
            os.environ["ZOMBOID_DIR"] = was
        shutil.rmtree(empty, ignore_errors=True)
    shutil.rmtree(beside, ignore_errors=True)


def check_dwellings(check) -> None:
    """A big building is homes, not one enormous house.

    A floor count of two used to settle it whatever the footprint, so a
    1200-tile terraced row came out as a single dwelling with 43 rooms, 24
    bedrooms and one kitchen. Two storeys says nothing on its own - a terrace
    is two and so is a bungalow with an attic - so the footprint decides.
    """
    import random as _random
    from collections import Counter as _Counter

    from knoxbuild.build import looks_like_apartment
    from knoxbuild.layout import build_building
    from knoxbuild.settings import Settings

    settings = Settings()
    big, small = 4 * settings.apartment_footprint, settings.apartment_footprint // 2

    def share(tags, area):
        return sum(looks_like_apartment(tags, area, _random.Random(k), settings)
                   for k in range(200)) / 200.0

    check(share({"building": "yes", "building:levels": "2"}, big) > 0.3,
          "a big two-storey building can be flats")
    check(share({"building": "yes", "building:levels": "2"}, small) == 0,
          "a small one is still somebody's house")
    check(share({"building": "yes", "building:levels": "1"}, big) == 0,
          "and a single storey is a house whatever its footprint")
    check(share({"building": "yes", "building:levels": "6"}, small) == 1,
          "six storeys is flats however small the footprint")
    check(share({"building": "house", "building:levels": "2"}, big) == 0,
          "a mapper who wrote building=house is believed")

    # And what it turns into has to read as homes: a kitchen and a bathroom
    # each, not two dozen bedrooms sharing one.
    kinds = _Counter()
    for seed in range(12):
        b = build_building(23, 19, levels=2, seed=seed, kind="apartment")
        for storey in b.storeys:
            for room in storey.rooms:
                kinds[room.kind] += 1
    beds = kinds["bedroom"] + kinds["kidsbedroom"]
    check(kinds["kitchen"] >= 4 and kinds["bathroom"] >= 4
          and beds <= 4 * kinds["kitchen"],
          f"and it comes out as flats with their own rooms "
          f"({kinds['kitchen'] / 12:.0f} kitchens, {kinds['bathroom'] / 12:.0f} "
          f"bathrooms, {beds / 12:.0f} bedrooms per building)")


def check_split_large(check) -> None:
    """A building past max_size is cut into units that fit, not dropped.

    footprint.place refuses on the real polygon's long side before claiming
    a single tile; build.py answers "large" by placing again without that
    one gate and cutting the footprint down in row_units. The factory and
    the hangar are the landmarks a place is known by, and dropping them
    left a hole exactly where the eye looks.
    """
    import numpy as np

    from knoxbuild.build import row_units
    from knoxbuild.footprint import place

    ring = [(10.0, 10.0), (510.0, 10.0), (510.0, 90.0), (10.0, 90.0),
            (10.0, 10.0)]
    fp, why = place(ring, np.zeros((600, 600), dtype=bool), max_side=200)
    whole, why2 = place(ring, np.zeros((600, 600), dtype=bool), max_side=1e9)
    # A quarter-metre a tile: the area rule stops before 200 tiles here, so
    # only the cap can bring this footprint in (tests/test_split_large_buildings).
    units = row_units(whole, "industrial", "industrial", 0, 0.25,
                      max_side=200) if whole else []
    longest = max((max(u.width, u.height) for u in units), default=0)
    check(fp is None and why == "large" and whole is not None and why2 == "ok"
          and len(units) > 1 and longest <= 200
          and sum(u.tiles for u in units) == whole.tiles,
          f"a building past max_size is cut into units that fit, not dropped "
          f"({len(units)} units, longest side {longest})")


def check_mapped_rooms(check) -> None:
    """Rooms the mapper drew are the rooms the floor is cut into.

    OSM indoor=room ways are attached to their building when the map is
    rendered, moved with the placed footprint, and cut into the ground floor
    (renderer._buildings_geojson, knoxbuild.build, layout._mapped_rooms) -
    so a school surveyed room by room keeps its classrooms instead of the
    BSP guessing. The rest of the floor and every floor above is cut as ever.
    """
    from knoxbuild.layout import build_plan

    mapped = [([(2, 2), (9, 2), (9, 7), (2, 7), (2, 2)], "classroom"),
              ([(13, 3), (18, 3), (18, 7), (13, 7), (13, 3)], "bathroom")]
    plan = build_plan(40, 24, kind="civic", seed=5, mapped=mapped)
    found = {(r.x0, r.y0, r.x1, r.y1): r.kind for r in plan.rooms}
    covered = all(all(row) for row in plan.grid)
    upper = build_plan(40, 24, kind="civic", seed=5, ground=False,
                       mapped=mapped)
    plain = build_plan(40, 24, kind="civic", seed=5, ground=False)
    one_floor = ([(r.x0, r.y0, r.x1, r.y1, r.kind) for r in upper.rooms]
                 == [(r.x0, r.y0, r.x1, r.y1, r.kind) for r in plain.rooms])
    from knoxbuild.layout import MIN_ROOM

    def drawn(rect, kind):
        """A room of this kind that is the drawn one: it holds the rectangle, and
        any more of it is a sliver too thin to be a room, merged in as every
        such leftover is (two rows above the classroom here)."""
        x0, y0, x1, y1 = rect
        return any(r.kind == kind and r.x0 <= x0 and r.y0 <= y0 and r.x1 >= x1 and r.y1 >= y1
                   and x0 - r.x0 < MIN_ROOM and y0 - r.y0 < MIN_ROOM
                   and r.x1 - x1 < MIN_ROOM and r.y1 - y1 < MIN_ROOM for r in plan.rooms)

    check(drawn((2, 2, 9, 7), "classroom") and drawn((13, 3, 18, 7), "bathroom")
          and len(plan.rooms) > len(mapped) and covered and one_floor,
          f"rooms the mapper drew are the floor's own rooms "
          f"({len(plan.rooms)} rooms, kinds kept, upper floor untouched)")


def check_giant_outline(check, work: str) -> None:
    """A building past max_size is kept, and does not cost the buildings inside it.

    Placed first (largest first), the giant outline claimed every tile in it and
    the house standing inside came out "taken"; where 1.5.2 left the outline out
    and kept the house. Outlines past max_size are placed after the rest."""
    import csv

    from generator import renderer
    from knoxbuild.build import MAX_OVERSIZE_TILES, build
    from knoxbuild.settings import Settings

    def box(s, w, n, e):
        return [(s, w), (s, e), (n, e), (n, w), (s, w)]

    giant = box(SOUTH + 0.0004, WEST + 0.0004, SOUTH + 0.0044, WEST + 0.0064)    # ~440 x 480 m
    house = box(SOUTH + 0.0022, WEST + 0.0030, SOUTH + 0.00245, WEST + 0.00335)  # ~28 x 21 m
    feats = [OSMFeature(next(_ids), "way", {"building": "yes"}, giant),
             OSMFeature(next(_ids), "way", {"building": "house"}, house)]
    out = os.path.join(work, "giant")
    renderer.render(feats, SOUTH, WEST, NORTH, EAST, meters_per_tile=1.0,
                    output_dir=out, map_name="giant")
    with contextlib.redirect_stdout(io.StringIO()):
        build(out, settings=Settings(seed=1, true_map=1))
    rows = list(csv.DictReader(open(os.path.join(out, "giant_placements.csv"), encoding="utf-8")))
    proj = renderer.Projector.build(SOUTH, WEST, NORTH, EAST, 1.0)
    hx, hy = proj.to_px(SOUTH + 0.002325, WEST + 0.003175)

    def holds(r):
        x, y, w, h = (int(r[k]) for k in ("tile_x", "tile_y", "width", "height"))
        return x <= hx < x + w and y <= hy < y + h

    inside = [r for r in rows if holds(r)]
    check(len(rows) > 4, f"a building past max_size is kept, cut into units ({len(rows)} buildings)")
    check(any(int(r["width"]) <= 40 and int(r["height"]) <= 40 for r in inside),
          "and the house standing inside it is kept as well")
    check(MAX_OVERSIZE_TILES > 0, "and there is a limit to how large an outline is kept")


def check_street_zombies(check) -> None:
    """Zombies where the streets are, not only inside the buildings: a town
    mapped without its houses used to come out empty."""
    import numpy as np

    from knoxbuild.population import CHUNK, build_spawn_map
    from knoxbuild.settings import Settings

    work = tempfile.mkdtemp(prefix="knoxmap-streets-")
    try:
        w = h = CHUNK * 30
        ground = Image.new("RGB", (w, h), C.DARK_GRASS)
        pen = ground.load()
        for y in range(h // 2 - 4, h // 2 + 4):      # one road across
            for x in range(w):
                pen[x, y] = C.MEDIUM_ASPHALT
        path = os.path.join(work, "ground.bmp")
        ground.save(path, format="BMP")
        img, summary = build_spawn_map([], w, h, 1.0, path, Settings())
        value = np.array(img)[:, :, 0]
        on_road = value[h // 2 // CHUNK]
        check(summary["on_the_street"] > 0 and int((value > 0).sum()) > 0,
              f"a town with no buildings still has zombies on its streets "
              f"({summary['on_the_street']} people)")
        check(int(on_road.sum()) > int(value[0].sum()),
              "the zombies are on the road, not out in the fields")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def check_stop(check) -> None:
    """Stopping a long job: it gives up where it is asked to, and nothing it
    was working on is thrown away (knoxstop.py)."""
    import knoxstop

    stop = {"now": False}
    asked = lambda: stop["now"]          # noqa: E731 - what the jobs are given

    knoxstop.check(asked, "the download")    # not asked yet: no exception
    check(True, "a job that has not been stopped carries on")

    stop["now"] = True
    try:
        knoxstop.check(asked, "the download")
        stopped = False
    except knoxstop.Stopped as exc:
        stopped = "download" in str(exc)
    check(stopped, "a job that has been stopped raises Stopped, saying which")

    # The compile stops between batches and kills the batch it is in.
    import inspect

    from tools import compile_map as compiler
    src = inspect.getsource(compiler.compile_map)
    check("should_stop" in inspect.signature(compiler.compile_map).parameters
          and "_run_batch" in src,
          "the compile watches for a stop inside a batch, not only between them")
    batch = inspect.getsource(compiler._run_batch)
    check("terminate" in inspect.getsource(compiler._end_batch),
          "and closes WorldEd down rather than waiting it out")
    # Under Wine the tools' pipes are inherited by wineserver, which outlives
    # them: reading those to the end never ended, so a dead WorldEd left the
    # window compiling for ever and Stop could not get out of it either.
    check("PIPE" not in batch and "communicate" not in batch
          and "proc.wait(" in batch,
          "a batch is waited for by the process, never by its pipes")
    check("killpg" in inspect.getsource(compiler._end_batch)
          and "start_new_session" in batch,
          "and off Windows the whole group goes, since `wine` is only a launcher")
    for source in (batch, inspect.getsource(compiler._end_batch)):
        waits = re.findall(r"\.wait\(([^)]*)\)", source)
        check(waits and all("timeout" in w for w in waits),
              "nothing in a batch waits without a deadline")


def check_portable(check) -> None:
    """Running off Windows: the map tools through Wine, the private Python in
    bin/ rather than Scripts/, Steam where this system keeps it, and a window
    that falls back to the browser. On the Linux CI these run for real."""
    import knoxmap
    import knoxpaths

    windows = os.name == "nt"

    # The map tools are Windows programs. Off Windows they go through Wine;
    # a build made for this system (no .exe) is run directly either way.
    wine_cmd = knoxpaths.command_for("/tools/bin/PZWorldEd_cli.exe")
    native = knoxpaths.command_for("/tools/bin/PZWorldEd_cli")
    check(len(native) == 1 and native[0].endswith("PZWorldEd_cli"),
          "a build of the map tools for this system is run directly")
    check(wine_cmd == ["/tools/bin/PZWorldEd_cli.exe"] if windows
          else (len(wine_cmd) == 2 and wine_cmd[0].endswith("wine")),
          "a .exe is run through Wine off Windows, and directly on it")
    os.environ["KNOXMAP_WINE"] = "/opt/wine/bin/wine"
    try:
        chosen = knoxpaths.command_for("/tools/bin/PZWorldEd_cli.exe")
        check(chosen[0] == "/opt/wine/bin/wine" if not windows else True,
              "KNOXMAP_WINE picks which Wine runs them")
    finally:
        del os.environ["KNOXMAP_WINE"]

    # Which compiler is in use decides what the paths in a project have to
    # look like. A build for this system reads the machine's own names; the
    # Windows one under Wine cannot, and needs the Z: form.
    check(not knoxpaths.through_wine("/tools/bin/PZWorldEd_cli"),
          "a build for this system is not going through Wine")
    check(knoxpaths.through_wine("/tools/bin/PZWorldEd_cli.exe") != windows,
          "a .exe is, off Windows")
    here = os.path.abspath(os.path.join(tempfile.gettempdir(), "knoxmap-paths"))
    if knoxpaths.through_wine():
        check(knoxpaths.tool_path(here).startswith(("Z:", "z:")) or ":" in knoxpaths.tool_path(here),
              "compiling through Wine hands the tools a Wine path")
    else:
        check(knoxpaths.tool_path(here) == here,
              "compiling with a native build hands the tools the real path")
    # Qt will not start without a platform plugin, and a compile draws
    # nothing, so a native build is asked for the offscreen one.
    env = knoxpaths.tool_env("/tools/bin/PZWorldEd_cli")
    check(windows or env.get("QT_QPA_PLATFORM") == "offscreen",
          "a native build is run headless, so no window opens mid-compile")
    check(knoxpaths.tool_env("/tools/bin/PZWorldEd_cli.exe").get("QT_QPA_PLATFORM")
          == os.environ.get("QT_QPA_PLATFORM"),
          "and the Windows build is left alone")

    # Setup fetches the compiler built for this system on Linux rather than
    # leaning on Wine, and checks what it downloaded.
    import inspect

    import knoxmap_setup
    check(len(knoxmap_setup.CLI_LINUX_SHA256) == 64
          and knoxmap_setup.CLI_LINUX_URL.endswith(".tar.gz"),
          "the Linux compiler is pinned by fingerprint, not just by name")
    source = inspect.getsource(knoxmap_setup.ensure_patched_cli)
    check("_install_linux_cli" in source and "linux" in source,
          "and Setup reaches for it before it reaches for Wine")

    # Setup puts the private Python in Scripts/ on Windows and bin/ elsewhere.
    python = str(knoxpaths.venv_python())
    wanted = "Scripts" if windows else "bin"
    check(python.endswith((".exe", "python", "python3"))
          and (wanted in python or python == sys.executable),
          f"the private Python is looked for in {wanted}/ ({os.path.basename(python)})")
    check(str(knoxpaths.venv_python(windowless=True)).endswith(
        "pythonw.exe" if windows else ("python", "python3")),
        "and the windowless one only where there is one")

    # Steam, where this system keeps it.
    roots = [str(p) for p in knoxpaths._steam_roots()]
    check(bool(roots) and all(("Steam" in r or "steam" in r) for r in roots),
          f"Steam is looked for where this system keeps it ({len(roots)} places)")
    check(all("\\" not in name for name in knoxpaths._LIBRARY_NAMES) if not windows
          else True,
          "and library folder names use this system's separator")
    check(knoxpaths.setup_command() == ("Setup.bat" if windows else "./setup.sh"),
          f"the window names the right setup script ({knoxpaths.setup_command()})")

    # macOS keeps the game inside an application bundle, so <game>/media is
    # not there and a Mac install was found and then turned away for having no
    # artwork in it. Every way somebody might name that install has to work.
    mac = Path(tempfile.mkdtemp()) / "Steam"
    bundle = mac / "steamapps/common/ProjectZomboid/ProjectZomboid.app"
    packs = bundle / "Contents/Java/media/texturepacks"
    packs.mkdir(parents=True)
    (packs / "Tiles2x.floor.pack").write_bytes(b"")
    game = mac / "steamapps/common/ProjectZomboid"
    ways = {
        "the Steam library": mac,
        "the game folder": game,
        "the .app": bundle,
        "inside the bundle": bundle / "Contents/Java",
        "the media folder": bundle / "Contents/Java/media",
    }
    missed = [what for what, path in ways.items()
              if (knoxpaths.pz_media_dir(knoxpaths.pz_install_from(path) or "") or Path("x"))
              != packs.parent]
    check(not missed,
          "the game inside a Mac .app is found however its folder is named"
          + (f" (missed: {missed})" if missed else ""))
    check(knoxpaths.is_build42(knoxpaths.pz_install_from(game)),
          "and Build 42 is recognised through the bundle")
    real = Path(tempfile.mkdtemp()) / "ProjectZomboid"
    (real / "media" / "texturepacks").mkdir(parents=True)
    check(knoxpaths.pz_media_dir(real) == real / "media",
          "while Windows and Linux still find <game>/media")
    linux_nested = Path(tempfile.mkdtemp()) / "ProjectZomboid"
    (linux_nested / "projectzomboid" / "media" / "texturepacks").mkdir(parents=True)
    check(knoxpaths.pz_media_dir(linux_nested) == linux_nested / "projectzomboid" / "media",
          "and Linux finds <game>/projectzomboid/media when nested")
    check(knoxpaths.pz_install_from(Path(tempfile.mkdtemp())) is None,
          "and a folder with no game in it is still refused")

    # A machine with no desktop toolkit still gets the whole app, in a browser.
    os.environ["KNOXMAP_BROWSER"] = "1"
    try:
        check(knoxmap.in_a_browser(), "KNOXMAP_BROWSER opens it in a browser instead")
    finally:
        del os.environ["KNOXMAP_BROWSER"]
    check(windows or not knoxpaths.wine() or knoxpaths.tools_runnable(),
          "with Wine on the path, the map tools count as runnable")

    # The project file the map tools read. Off Windows they are Windows
    # programs under Wine, which shows the filesystem as drive Z:, so what
    # is written in the .pzw is not what Python opens.
    import compile_map as compiler
    from knoxbuild.world import Placement, render_pzw

    work = tempfile.mkdtemp(prefix="knoxmap-tools-")
    try:
        project = Path(work) / "town"
        (project / "tmx").mkdir(parents=True)
        (project / "town.bmp").write_bytes(b"")
        pzw = project / "town.pzw"
        pzw.write_text(render_pzw(1, 1, "town.bmp", [Placement("buildings/a.tbx", 0, 0, 4, 4)],
                                  "town", project_dir=str(project)), encoding="utf-8")
        told = re.search(r'<tmxexportdir path="([^"]+)"', pzw.read_text(encoding="utf-8"))
        check(bool(told) and (told.group(1).startswith(("Z:", "/")) if not windows
                              else ":" in told.group(1)),
              f"the export folder is written as the tools read it ({told.group(1)[:24]}…)")
        # The cell is empty until the bitmap has been converted; once the
        # .tmx is there it is matched by its real name, whatever the .pzw
        # calls the folder it is in.
        check('map=""' in pzw.read_text(encoding="utf-8"),
              "a cell with nothing converted for it yet is left empty")
        (project / "tmx" / "town_70_0.tmx").write_text("<map/>", encoding="utf-8")
        assigned = compiler.assign_converted_maps(pzw)
        after = pzw.read_text(encoding="utf-8")
        check(assigned == 1 and 'map=""' not in after,
              "a converted cell is found on disk and written into the project")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # A release carries one file per system; the updater takes the right one.
    import updater
    three = {"assets": [{"name": "KnoxMap-v9.9-windows.zip"},
                        {"name": "KnoxMap-v9.9-linux.tar.gz"},
                        {"name": "KnoxMap-v9.9-macos.tar.gz"}]}
    want = "windows" if windows else ("macos" if sys.platform == "darwin" else "linux")
    picked = (updater._asset(three) or {}).get("name", "")
    check(want in picked, f"the updater takes the release built for this system ({picked})")
    named = {"assets": [{"name": "KnoxMap-v9.9-rnd-windows.zip"},
                        {"name": "KnoxMap-v9.9-rnd-linux.tar.gz"},
                        {"name": "KnoxMap-v9.9-rnd-macos.tar.gz"}]}
    # A named release puts the name in the filename too, and the name must not
    # be mistaken for the system - a Linux PC handed the Windows zip is worse
    # than no update at all.
    got = (updater._asset(named) or {}).get("name", "")
    check(want in got and got.endswith(".zip" if windows else ".tar.gz"),
          f"and from a named release too ({got})")

    # The map compiler is published from this repository too, and its tags are
    # dates: "worlded-cli-linux-20260909f" read as a version is 20260909, far
    # newer than any KnoxMap, and GitHub had made it the "latest" release. The
    # updater would have offered a player 30 MB of Qt as an upgrade.
    check(not updater._is_knoxmap({"tag_name": "worlded-cli-linux-20260909f"})
          and not updater._is_knoxmap({"tag_name": "worlded-cli-20260909f"}),
          "a release that is not KnoxMap is not an update")
    check(updater._is_knoxmap({"tag_name": "v1.3.9"})
          and not updater._is_knoxmap({"tag_name": "v1.3.9", "prerelease": True})
          and not updater._is_knoxmap({"tag_name": "v1.4.0", "draft": True}),
          "a released version of KnoxMap is, and a draft or a pre-release is not")

    # 1.4.1 was tagged without the v, so release.yml - which listened for
    # "v*" alone - never ran, and the release went out with no files on it.
    # Both ends of that are worth holding down.
    check(updater._is_knoxmap({"tag_name": "1.4.1"}),
          "a tag with no v in front of it is still a KnoxMap release")
    check(not updater._for_this_system({"tag_name": "v9.9", "assets": []})
          and updater._for_this_system(dict(three, tag_name="v9.9")),
          "and a release with nothing on it to download is not an update")

    # A release can be named on top of a version - "1.3.9 mc1" was the macOS
    # fix, "1.3.9 rnd" the pictures - and has to come out newer than the
    # version it sits on, or nobody is ever offered it.
    order = [("1.3.9 rnd", "1.3.9"), ("1.3.9 mc1", "1.3.9"),
             ("1.3.9 rnd", "1.3.9 mc1"), ("1.3.10", "1.3.9 rnd")]
    check(all(updater.is_newer(a, b) for a, b in order)
          and not updater.is_newer("1.3.9", "1.3.9 rnd")
          and not updater.is_newer("1.3.9", "1.3.9"),
          "a named release is newer than the version it is named after")
    check(updater._is_knoxmap({"tag_name": "v1.3.9-rnd"}),
          "and its tag is recognised as one of ours")
    check((updater._asset({"assets": [{"name": "KnoxMap-v1.3.6.zip"}]}) or {}).get("name")
          == "KnoxMap-v1.3.6.zip",
          "and a release from before they were split is still for everybody")

    # The launchers must keep LF, or /bin/sh chokes on the carriage returns.
    root = Path(__file__).resolve().parent.parent
    flow = root / ".github" / "workflows" / "release.yml"
    if flow.exists():
        # Whichever way a release is made - pushing the tag or drafting the
        # release on GitHub - the files have to get built, or the updater has
        # nothing to offer.
        text = flow.read_text(encoding="utf-8")
        check('tags: ["v*", "[0-9]*"]' in text and "types: [published]" in text,
              "release.yml builds for a tag either way, and for a release "
              "drafted by hand")

    for name in ("setup.sh", "knoxmap.sh"):
        path = root / name
        if path.exists():
            check(b"\r\n" not in path.read_bytes(), f"{name} has no carriage returns in it")


def check_lots_apart(check, out: str, name: str = "selftest") -> None:
    """No two buildings' lots cover the same square.

    A lot reaches WorldEd as a rectangle - <lot x y width height> - and every
    square of that rectangle is written into the cell's layers, so where two
    lots overlap one building's wall is laid over the other's and a wall goes
    missing. It went unnoticed because the tiles are checked and the
    rectangles were not: a footprint off the grid owns a staircase of tiles
    inside a rectangle half again as big, and the next building along took the
    empty part quite legitimately. Brugge came out as 4202 buildings in 5004
    overlapping pairs of lots, some of them a whole row deep.

    Buildings that really do stand wall to wall - a terrace, a parade of shops
    - share an edge and not a square: one lot ends on the column the next one
    starts on, and the wall between them is the one both of them draw.
    """
    import csv as _csv
    with open(os.path.join(out, f"{name}_placements.csv"), encoding="utf-8") as f:
        lots = [(r["file"], int(r["tile_x"]), int(r["tile_y"]),
                 int(r["width"]), int(r["height"])) for r in _csv.DictReader(f)]
    # Only lots meeting in the same 64-tile square of the map can touch, which
    # keeps this a few thousand comparisons on a real town instead of millions.
    near: dict[tuple[int, int], list] = {}
    for lot in lots:
        _, x, y, w, h = lot
        for gx in range(x // 64, (x + w - 1) // 64 + 1):
            for gy in range(y // 64, (y + h - 1) // 64 + 1):
                near.setdefault((gx, gy), []).append(lot)
    clash = set()
    for group in near.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if (min(a[1] + a[3], b[1] + b[3]) > max(a[1], b[1])
                        and min(a[2] + a[4], b[2] + b[4]) > max(a[2], b[2])):
                    clash.add(tuple(sorted((a[0], b[0]))))
    worst = f", e.g. {' and '.join(sorted(clash)[0])}" if clash else ""
    check(not clash, f"no two lots stand on the same square "
                     f"({len(lots)} lots, {len(clash)} overlapping{worst})")


def dense_town() -> list:
    """A town as OpenStreetMap really draws one: terraces of seven-metre
    houses shoulder to shoulder, and the places a player actually goes -
    the police station, the school, the supermarket - traced at the size of
    the building somebody surveyed, which is to say tiny."""
    feats = []
    for i in range(1, 8):
        feats.append(way({"highway": "residential", "name": f"Street {i}"},
                         [(i * 70, 40), (i * 70, 560)]))
        feats.append(way({"highway": "residential", "name": f"Avenue {i}"},
                         [(40, i * 70), (560, i * 70)]))
    for bx in range(1, 7):
        for by in range(1, 7):
            x0, y0 = bx * 70 + 6, by * 70 + 6
            for n in range(7):
                x = x0 + n * 7.5
                feats.append(way({"building": "house"}, box(x, y0, x + 7, y0 + 10)))
    for tags, corner in (({"amenity": "police", "name": "Town Police"}, (90, 300, 102, 309)),
                         ({"amenity": "fire_station", "name": "Fire Station"}, (120, 300, 133, 310)),
                         ({"amenity": "school", "name": "High School"}, (300, 430, 320, 448)),
                         ({"shop": "supermarket", "name": "Supermarket"}, (360, 300, 375, 312)),
                         ({"amenity": "hospital", "name": "Hospital"}, (430, 430, 448, 446))):
        feats.append(way({"building": "yes", **tags}, box(*corner)))
    return feats


def check_procedural(check, work: str) -> None:
    """True map generation off: the same town, laid out for the game.

    OSM's own density at 2 m a tile is a street of five-by-four boxes with
    one room in each, which is what the setting exists to fix. Built with it
    off, the same ground should carry fewer houses, each of them worth
    walking into, and every named place should still be there - and be the
    size the game gives that kind of building rather than the size the
    surveyor traced.
    """
    from generator import renderer
    from knoxbuild.build import build
    from knoxbuild.settings import Settings
    from knoxbuild.world import origin, set_origin

    # Every build picks where its map stands in the world and leaves that
    # choice in a module global, which the .pzw, the paper map and the zones
    # are all written from. These maps are scratch, so the one the selftest
    # is really checking has to be put back afterwards - without this the
    # cell the project names is looked for under the wrong number and the
    # whole install check fails somewhere else entirely.
    was = origin()
    try:
        _dense(check, work, renderer, build, Settings)
    finally:
        set_origin(was)


def _dense(check, work, renderer, build, Settings) -> None:
    import csv as _csv

    feats = dense_town()
    got = {}
    for name, true_map in (("true", 1), ("laid out", 0)):
        out = os.path.join(work, f"dense-{true_map}")
        renderer.render(feats, SOUTH, WEST, NORTH, EAST, meters_per_tile=2.0,
                        output_dir=out, map_name="dense")
        with contextlib.redirect_stdout(io.StringIO()):
            build(out, settings=Settings(seed=1, true_map=true_map))
        with open(os.path.join(out, "dense_placements.csv"), encoding="utf-8") as f:
            got[true_map] = (list(_csv.DictReader(f)), out)

    def houses(rows):
        return [r for r in rows if r["kind"] == "house"]

    def median_rooms(rows):
        got_rooms = sorted(int(r["rooms"]) for r in rows)
        return got_rooms[len(got_rooms) // 2] if got_rooms else 0

    true_rows, _ = got[1]
    laid_rows, laid_out = got[0]
    n_true, n_laid = len(houses(true_rows)), len(houses(laid_rows))
    check(0.25 <= n_laid / max(1, n_true) <= 0.75,
          f"about half the houses are left out ({n_laid} of {n_true} kept)")
    rooms_true, rooms_laid = median_rooms(houses(true_rows)), median_rooms(houses(laid_rows))
    check(rooms_laid >= rooms_true + 2,
          f"and the ones that stay are proper houses "
          f"({rooms_true} rooms each as mapped, {rooms_laid} laid out for the game)")

    # Every named place still there, and bigger than the footprint OSM had.
    for kind in ("police", "fire", "school", "shop", "medical"):
        was = [r for r in true_rows if r["kind"] == kind]
        now = [r for r in laid_rows if r["kind"] == kind]
        area = (lambda rows: max((int(r["width"]) * int(r["height"]) for r in rows),
                                 default=0))
        check(len(now) >= len(was) >= 1 and area(now) > area(was) * 2,
              f"the {kind} is force-generated and built at the game's size "
              f"({area(was)} tiles as mapped, {area(now)} laid out)")

    # Growing a footprint must not grow it over the building next door.
    check_lots_apart(check, laid_out, name="dense")

    with contextlib.redirect_stdout(io.StringIO()):
        build(laid_out, settings=Settings(seed=1, true_map=0))
    with open(os.path.join(laid_out, "dense_placements.csv"), encoding="utf-8") as f:
        again = list(_csv.DictReader(f))
    check([r["file"] for r in again] == [r["file"] for r in laid_rows],
          "the same town comes out of the same seed")


def check_rifle(check, out: str, mod_root: str) -> None:
    """One military rifle on the map, wherever this town could put it.

    The M16 spawns from army and police loot and almost nowhere else, so a
    map of a town with neither has no container anywhere that could roll one.
    knoxbuild/guns.py picks the best building the map has and the mod ships
    the Lua that fills it.
    """
    import json as _json

    cache = os.path.join(out, "selftest_guncache.json")
    box_ = _json.load(open(cache, encoding="utf-8")) if os.path.exists(cache) else {}
    from knoxbuild.world import CELL_SIZE, origin
    ox = origin()[0] * CELL_SIZE
    check(box_.get("kind") in ("military", "police", "gunshop", "house", "any")
          and box_.get("x", 0) >= ox and box_.get("w", 0) > 0,
          f"the rifle has somewhere to go ({box_.get('kind')}: "
          f"{box_.get('name') or box_.get('building')}, at world {box_.get('x')},{box_.get('y')})")
    check(box_.get("kind") == "military",
          "and it goes to the army before anywhere else when the map has a base")

    lua_dir = os.path.join(mod_root, "common", "media", "lua", "server", "KnoxMap")
    shipped = sorted(os.listdir(lua_dir)) if os.path.isdir(lua_dir) else []
    handler = os.path.join(lua_dir, "KnoxMapGunCache.lua")
    text = open(handler, encoding="utf-8").read() if os.path.exists(handler) else ""
    registrations = [f for f in shipped if f.startswith("KnoxMapGunCache_")]
    registered = (open(os.path.join(lua_dir, registrations[0]), encoding="utf-8").read()
                  if registrations else "")
    ok = ("OnFillContainer" in text and "ModData.getOrCreate" in text
          and "Base.AssaultRifle" in registered
          and str(box_.get("x")) in registered
          # Either file may load first, so both have to make the table.
          and text.count("KnoxMapGunCache or") >= 1
          and "KnoxMapGunCache or" in registered)
    try:                      # a real parse when a Lua runtime is installed
        import lupa
        lupa.LuaRuntime().compile(text)
        lupa.LuaRuntime().compile(registered)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - a syntax error in the shipped Lua
        ok = False
        print(f"        {exc}")
    check(ok, f"the rifle ships with the map ({len(shipped)} Lua files)")


def check_rpath(check) -> None:
    """The compiler's own Qt outranks whatever LD_LIBRARY_PATH names.

    patchelf writes DT_RUNPATH, which the loader searches *after*
    LD_LIBRARY_PATH, so Steam's or Proton's Qt was found first and Qt aborted
    on the spot. DT_RPATH is searched before it, and the change is one word:
    the tag number, in place.
    """
    import struct

    import knoxpaths

    def elf(tag: int) -> bytes:
        """A 64-bit ELF with one PT_DYNAMIC holding `tag` and DT_NULL."""
        dyn_at = 128
        head = bytearray(64)
        head[0:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<HHI", head, 0x10, 2, 0x3E, 1)     # EXEC, x86-64
        struct.pack_into("<Q", head, 0x20, 64)               # e_phoff
        struct.pack_into("<HH", head, 0x34, 64, 56)          # e_ehsize, phentsize
        struct.pack_into("<H", head, 0x38, 1)                # e_phnum
        ph = bytearray(56)
        struct.pack_into("<I", ph, 0, 2)                     # PT_DYNAMIC
        struct.pack_into("<Q", ph, 8, dyn_at)                # p_offset
        struct.pack_into("<Q", ph, 32, 32)                   # p_filesz
        body = struct.pack("<qQ", tag, 0x40) + struct.pack("<qQ", 0, 0)
        out = bytearray(dyn_at + 32)
        out[0:64] = head
        out[64:120] = ph
        out[dyn_at:dyn_at + 32] = body
        return bytes(out)

    def tag_of(raw: bytes) -> int:
        return struct.unpack_from("<q", raw, 128)[0]

    work = Path(tempfile.mkdtemp(prefix="knoxmap-rpath-"))
    runpath = work / "runpath.so"
    runpath.write_bytes(elf(29))                             # DT_RUNPATH
    size = runpath.stat().st_size
    check(knoxpaths._force_rpath(runpath) and tag_of(runpath.read_bytes()) == 15,
          "DT_RUNPATH becomes DT_RPATH, which the loader reads first")
    check(runpath.stat().st_size == size,
          "and the file is the same size, because only the tag changed")
    check(not knoxpaths._force_rpath(runpath),
          "one that already says DT_RPATH is left alone")

    for name, raw in (("nonsense.so", b"not an ELF at all"),
                      ("empty.so", b""),
                      ("32bit.so", b"\x7fELF\x01\x01\x01" + bytes(200))):
        path = work / name
        path.write_bytes(raw)
        before = path.read_bytes()
        check(not knoxpaths._force_rpath(path) and path.read_bytes() == before,
              f"and {name} is not touched")

    # Loading the right Qt is only half of it: Qt looks for its plugins under
    # the prefix it was compiled with, and on Ubuntu 24.04 that meant the
    # bundled Qt 5.15.3 reading the system's plugin tree and pulling 5.15.13
    # in behind it. qt.conf replaces the prefix.
    bin_dir = work / "bin"
    (bin_dir / "plugins" / "platforms").mkdir(parents=True)
    binary = bin_dir / "PZWorldEd_cli"
    binary.write_bytes(elf(29))
    check(knoxpaths.write_qt_conf(binary)
          and "Plugins=plugins" in (bin_dir / "qt.conf").read_text(encoding="utf-8"),
          "a qt.conf beside the compiler points Qt at the bundled plugins")
    check(not knoxpaths.write_qt_conf(binary),
          "and one that already says so is left alone")
    bare = work / "bare"
    bare.mkdir()
    check(not knoxpaths.write_qt_conf(bare / "PZWorldEd_cli")
          and not (bare / "qt.conf").exists(),
          "with no bundled plugins to point at, none is written")
    shutil.rmtree(work, ignore_errors=True)


def check_facing(check) -> None:
    """Nothing is drawn against a wall it has no sprite for.

    A piece with only north and west sprites, put against a south or east
    wall, is drawn with its north sprite on the far edge of the tile: a
    corkboard hangs a tile into the room, a rack faces its own back. The rule
    was a list kept by hand, so a role added later was quietly wrong - 1076
    pieces over 200 houses, mostly corkboards and bedside tables.
    """
    from knoxbuild import catalog as _C
    from knoxbuild import layout as _L

    no_se = {role for role, facings in _C.FURNITURE.items()
             if set(facings) <= {"N", "W"}} - _L._EITHER_WAY
    check(no_se <= set(_L.NORTH_WEST_ONLY),
          f"every piece with no south or east sprite is kept off those walls "
          f"({len(no_se)} of them)")

    sizes = [(10, 9), (12, 10), (9, 11), (13, 10)]
    wrong = shelves = pieces = 0
    for i in range(48):
        w, h = sizes[i % len(sizes)]
        building = _L.build_building(w, h, levels=1 if i % 3 else 2, seed=i,
                                     kind=None, commercial=False)
        for storey in building.storeys:
            for role, fx, fy, orient in storey.furniture:
                if role != "switch":
                    pieces += 1
                if role == "shelf":
                    shelves += 1
                if role not in no_se or orient not in ("N", "W"):
                    continue
                idx = (storey.grid[fy][fx]
                       if 0 <= fx < storey.width and 0 <= fy < storey.height else 0)
                if not idx:
                    continue
                walls = {d for d, nx, ny in (("N", fx, fy - 1), ("S", fx, fy + 1),
                                             ("W", fx - 1, fy), ("E", fx + 1, fy))
                         if _L._room_at(storey, nx, ny) != idx}
                if walls and not walls & {orient} and walls <= {"S", "E"}:
                    wrong += 1
    check(wrong == 0, f"and none of {pieces} pieces is facing the wrong way "
                      f"({wrong})")
    # One wooden shelf was on nearly every room's list and was the same sprite
    # in every home, so a whole town was made of it.
    check(shelves < pieces * 0.04,
          f"no one piece of furniture is everywhere "
          f"(the wooden shelf is {100.0 * shelves / max(1, pieces):.1f}%)")

    # And what replaced it has to belong in the room. Varying the shelf per
    # home put warehouse wire racking in people's bathrooms.
    from collections import Counter as _Counter

    # Every room a house has, not just the ones you sit in: the box room and
    # the laundry were left out of this, and that is exactly where the steel
    # racking and the packing crates were sitting.
    indoors = {"livingroom", "bedroom", "kidsbedroom", "kitchen", "bathroom",
               "dining", "diningroom", "hall", "storage", "laundry", "closet",
               "office", "openplan"}
    industrial = {"metal_rack", "crate", "shop_shelf", "shop_aisle"}
    strays = _Counter()
    for i in range(48):
        w, h = sizes[i % len(sizes)]
        building = _L.build_building(w, h, levels=1 if i % 3 else 2, seed=i,
                                     kind=None, commercial=False)
        for storey in building.storeys:
            for role, fx, fy, _o in storey.furniture:
                if role not in industrial:
                    continue
                idx = (storey.grid[fy][fx]
                       if 0 <= fx < storey.width and 0 <= fy < storey.height else 0)
                if idx and storey.rooms[idx - 1].kind in indoors:
                    strays[(storey.rooms[idx - 1].kind, role)] += 1
    check(not strays,
          f"and a house's rooms have household shelving, not warehouse racking "
          f"({dict(strays) if strays else 'none'})")

    # A wall cabinet is an upper cupboard on the roof layer: it draws over a
    # counter and belongs above one. Offered as a shelf, it stood on its own
    # on any wall with nothing underneath.
    loose = rooms_with = 0
    for i in range(48):
        w, h = sizes[i % len(sizes)]
        building = _L.build_building(w, h, levels=1 if i % 3 else 2, seed=i,
                                     kind=None, commercial=False)
        for storey in building.storeys:
            counters = {(x, y) for role, x, y, _o in storey.furniture
                        if role.startswith("counter")}
            for role, fx, fy, _o in storey.furniture:
                if role != "wall_cabinet":
                    continue
                rooms_with += 1
                if (fx, fy) not in counters:
                    loose += 1
    check(loose <= rooms_with * 0.02,
          f"and a wall cabinet hangs over a counter, not on a bare wall "
          f"({loose} of {rooms_with} do not)")

    # Every kitchen in a town had the same sink. The extra sets came off the
    # vanilla map, where each tile's facing was read from the wall it stands
    # against; a facing copied down wrong would turn a sink to face the room.
    kinds = _Counter()
    facing_wrong = 0
    for i in range(48):
        w, h = sizes[i % len(sizes)]
        building = _L.build_building(w, h, levels=1 if i % 3 else 2, seed=i,
                                     kind=None, commercial=False)
        for storey in building.storeys:
            for role, fx, fy, orient in storey.furniture:
                if "sink" not in role:
                    continue
                kinds[role] += 1
                idx = (storey.grid[fy][fx]
                       if 0 <= fx < storey.width and 0 <= fy < storey.height else 0)
                if not idx:
                    continue
                walls = {d for d, nx, ny in (("N", fx, fy - 1), ("S", fx, fy + 1),
                                             ("W", fx - 1, fy), ("E", fx + 1, fy))
                         if _L._room_at(storey, nx, ny) != idx}
                if walls and orient not in walls:
                    facing_wrong += 1
    check(len(kinds) >= 4,
          f"a town has more than one kind of sink in it ({len(kinds)})")
    check(facing_wrong == 0,
          f"and every one has its back to a wall it has a sprite for "
          f"({facing_wrong} do not)")


def check_qt_env(check) -> None:
    """The map compiler is made to find its own Qt, and a Qt that got away
    with it is explained rather than reported as a crash.

    The build for Linux carries the Qt it was compiled against in lib/ beside
    it, and records that folder as DT_RUNPATH - which the loader searches
    *after* LD_LIBRARY_PATH. Steam and Proton both export that, so on a
    machine with its own Qt 5 the compiler loaded the wrong one and Qt killed
    it mid-compile: "Cannot mix incompatible Qt library (5.15.13) with this
    library (5.15.3)", exit -6, reported from Linux Mint.
    """
    import knoxpaths

    windows = os.name == "nt"
    work = tempfile.mkdtemp(prefix="knoxmap-qt-")
    binary = Path(work) / "bin" / "PZWorldEd_cli"
    (binary.parent / "lib").mkdir(parents=True)
    (binary.parent / "plugins" / "platforms").mkdir(parents=True)
    binary.write_text("", encoding="utf-8")

    # One folder with a Qt of its own, as Steam and Proton put on the path,
    # and one with something else in it.
    theirs = Path(work) / "their-qt"
    theirs.mkdir()
    (theirs / "libQt5Core.so.5").write_bytes(b"not really Qt")
    plain = Path(work) / "their-other-libs"
    plain.mkdir()

    was = os.environ.get("LD_LIBRARY_PATH")
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join([str(theirs), str(plain)])
    try:
        env = knoxpaths.tool_env(binary)
    finally:
        if was is None:
            os.environ.pop("LD_LIBRARY_PATH", None)
        else:
            os.environ["LD_LIBRARY_PATH"] = was
    path = (env.get("LD_LIBRARY_PATH") or "").split(os.pathsep)
    check(windows or (path and path[0] == str(binary.parent / "lib")),
          "the compiler's own Qt goes ahead of the machine's on LD_LIBRARY_PATH")
    check(windows or str(plain) in path,
          "and what was already there is kept, not thrown away")
    check(windows or str(theirs) not in path,
          "except a folder carrying a Qt of its own, which is left off")
    check(windows or env.get("QT_QPA_PLATFORM_PLUGIN_PATH")
          == str(binary.parent / "plugins" / "platforms"),
          "and its own platform plugins are the ones it is pointed at")

    # Only offscreen and minimal are bundled, so an inherited platform could
    # only fail; a compile draws nothing whatever the desktop is.
    was = os.environ.get("QT_QPA_PLATFORM")
    os.environ["QT_QPA_PLATFORM"] = "wayland"
    try:
        forced = knoxpaths.tool_env(binary).get("QT_QPA_PLATFORM")
    finally:
        if was is None:
            os.environ.pop("QT_QPA_PLATFORM", None)
        else:
            os.environ["QT_QPA_PLATFORM"] = was
    check(windows or forced == "offscreen",
          "a desktop's own QT_QPA_PLATFORM does not follow the compiler in")

    real = ("QStandardPaths: XDG_RUNTIME_DIR not set\n"
            "Cannot mix incompatible Qt library (5.15.13) with this library (5.15.3)\n")
    said = knoxpaths.qt_trouble(real) or ""
    check("5.15.13" in said and "5.15.3" in said and "LD_LIBRARY_PATH" in said,
          "a Qt version clash is explained with both versions and what to do")
    check(knoxpaths.qt_trouble(
        "./PZWorldEd_cli: error while loading shared libraries: libQt5Core.so.5"),
        "so is a library the loader could not find at all")
    check(knoxpaths.qt_trouble("Generate Lots: batch 3 of 48, 12 cells") is None
          and knoxpaths.qt_trouble("") is None,
          "and an ordinary line is left alone - the check must not cry wolf")


def check_compile_failures(check, work: str) -> None:
    """A batch that fails is tried again, and then stepped over.

    Reported from a 14-hour compile: batch 23 of 48 exited 1 after 849
    seconds and the whole run was thrown away. Three attempts now, and what
    still will not go is written down and skipped so the other 47 batches
    are not lost with it - except for the failures that are about the machine
    rather than the batch, which would fail all 48 the same way.
    """
    import json as _json

    import knoxlog

    from tools import compile_map as compiler

    class Proc:
        def __init__(self, rc, out=""):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    keep = {name: getattr(compiler, name) for name in
            ("_run_batch", "clear_stale", "assign_converted_maps", "world_size")}
    keep_saved = knoxlog.save_tool_output
    import knoxbuild.repair as _repair
    keep_repair = _repair.repair_project

    made = [0]

    def harness(plan):
        made[0] += 1
        project = Path(work) / f"compile-{made[0]}"
        (project / "lots").mkdir(parents=True)
        (project / "tmx").mkdir()
        (project / f"{project.name}.pzw").write_text("<world/>", encoding="utf-8")
        exe = project / "PZWorldEd_cli"
        exe.write_text("", encoding="utf-8")
        tries: dict = {}

        def fake(cmd, should_stop, started):
            arg = [a for a in cmd if a.startswith("--cells=")][0]
            bx, by, x1, y1 = (int(v) for v in arg[len("--cells="):].split(","))
            n = tries.get((bx, by), 0)
            tries[(bx, by)] = n + 1
            codes = plan.get((bx, by), [0])
            rc = codes[n] if n < len(codes) else codes[-1]
            if rc == 0:
                for cx in range(bx, x1 + 1):
                    for cy in range(by, y1 + 1):
                        (project / "lots" / f"{cx}_{cy}.lotheader").write_text("x")
            return Proc(rc, "Cannot mix incompatible Qt library (5.15.13) with "
                            "this library (5.15.3)" if rc == -6 else "")

        compiler._run_batch = fake
        return project, exe, tries

    try:
        compiler.clear_stale = lambda p: None
        compiler.assign_converted_maps = lambda p: None
        compiler.world_size = lambda p: (4, 4)
        _repair.repair_project = lambda p: {"changed": False, "moved": 0, "dropped": []}
        knoxlog.save_tool_output = lambda *a, **k: Path("batch.log")

        # One bad batch out of four, good on the second attempt.
        project, exe, tries = harness({(2, 0): [1, 0]})
        cells = compiler.compile_map(str(project), batch=2, exe=str(exe))
        check(cells == 16 and tries[(2, 0)] == 2 and not compiler.failed_cells(project),
              f"a batch that fails once is tried again and the map is whole ({cells} cells)")

        # One that never works first time round: the other three batches still
        # compile, and it comes good when it is asked for again on its own.
        project, exe, tries = harness({(2, 0): [1, 1, 1, 0]})
        cells = compiler.compile_map(str(project), batch=2, exe=str(exe))
        failed = compiler.failed_cells(project)
        check(cells == 12 and tries[(2, 0)] == compiler.BATCH_ATTEMPTS
              and [f["cells"] for f in failed] == [[2, 0, 3, 1]],
              f"one that never works is stepped over, not thrown away ({cells} cells, "
              f"{len(failed)} recorded)")
        check(not (project / compiler.LOCK_FILE).exists(),
              "and the compile lock is let go afterwards")

        # ...and asking for just those cells again compiles them.
        again = compiler.compile_map(str(project), batch=2, exe=str(exe),
                                     only_cells=[f["cells"] for f in failed])
        check(again == 16 and not compiler.failed_cells(project),
              f"compiling only the failed cells finishes the map ({again} cells)")

        # A Qt that cannot start is not this batch's fault: 48 batches of it
        # is hours of the same abort, so it stops on the first.
        project, exe, tries = harness({(0, 0): [-6]})
        try:
            compiler.compile_map(str(project), batch=2, exe=str(exe))
            said = ""
        except RuntimeError as exc:
            said = str(exc)
        check(sum(tries.values()) == 1 and "5.15.13" in said,
              "a compiler that cannot start stops the run at once, with what is wrong")

        # Two at a time in one folder write the same lots and the same .pzw.
        project, exe, _tries = harness({})
        (project / compiler.LOCK_FILE).write_text(
            _json.dumps({"pid": os.getpid() + 1, "run": "other"}), encoding="utf-8")
        alive = compiler._pid_alive
        compiler._pid_alive = lambda pid: True
        try:
            compiler.compile_map(str(project), batch=2, exe=str(exe))
            refused = ""
        except RuntimeError as exc:
            refused = str(exc)
        finally:
            compiler._pid_alive = alive
        check("already being compiled" in refused,
              "a second compile of the same map is refused while one is running")

        # ...but a lock left by a compile that crashed is not forever.
        (project / compiler.LOCK_FILE).write_text(
            _json.dumps({"pid": 999999, "run": "crashed"}), encoding="utf-8")
        cells = compiler.compile_map(str(project), batch=2, exe=str(exe))
        check(cells == 16, "and a lock left behind by a crash is cleared, not fatal")
    finally:
        for name, value in keep.items():
            setattr(compiler, name, value)
        knoxlog.save_tool_output = keep_saved
        _repair.repair_project = keep_repair


def check_wall_corners(check) -> None:
    """No window, and no outside door, on a tile that carries two walls.

    BuildingEd draws a tile with both a west and a north wall as one corner
    piece. Put a window there and it becomes a window facing one way, and the
    other half of the corner is simply not drawn - a window with a hole beside
    it, hanging on nothing. Reported on a generated town as windows all along
    a wall with gaps you could see straight through.

    layout.py always blocked this, but it asked _facade_runs, which only knows
    the outside of the building - so the corner where a *room* wall reaches
    the facade went unblocked, and that is almost all of them. Counted over
    the two city maps in output/ at the time: 7,684 windows on such corners
    across 5,311 buildings, 37% of the buildings affected.
    """
    from knoxbuild.layout import _room_edges, build_building
    from knoxbuild.settings import Settings

    def walls_of(grid):
        h, w = len(grid), len(grid[0])

        def inside(x, y):
            return 0 <= x < w and 0 <= y < h and bool(grid[y][x])

        edges = set()
        for y in range(h):
            for x in range(w):
                if not inside(x, y):
                    continue
                # An east wall is the west edge of the tile past it, and a
                # south wall the north edge of the row below: that is how
                # BuildingEd names them.
                for there, edge in (((x - 1, y), (x, y, "W")),
                                    ((x, y - 1), (x, y, "N")),
                                    ((x + 1, y), (x + 1, y, "W")),
                                    ((x, y + 1), (x, y + 1, "N"))):
                    if not inside(*there):
                        edges.add(edge)
        return edges

    def stepped(w, h, step):
        """A footprint with a stepped diagonal side, as a turned building has
        - which is where every one of these corners comes from."""
        return [[x >= int(y / step) for x in range(w)] for y in range(h)]

    windows = doors = bad_windows = bad_doors = stuck = 0
    # A counter, not hash(): Python randomises string hashes per process, and
    # a check that builds different buildings every run cannot be compared
    # with the last one.
    seed = 0
    for kind in (None, "shop", "civic", "apartment", "school", "medical", "industrial"):
        for step in (1.0, 1.5, 2.0, 3.0):
            for levels in (1, 2, 3):
                seed += 1
                plan = build_building(26, 20, levels=levels, kind=kind,
                                      mask=stepped(26, 20, step), settings=Settings(),
                                      seed=seed, commercial=kind is not None)
                for storey in plan.storeys:
                    outside = walls_of(storey.grid)
                    every = outside | _room_edges(storey.grid)
                    corner = {(x, y) for x, y, d in every
                              if (x, y, "N" if d == "W" else "W") in every}
                    windows += len(storey.windows)
                    doors += len(storey.doors)
                    bad_windows += sum(1 for x, y, _d in storey.windows if (x, y) in corner)
                    for x, y, d in storey.doors:
                        if (x, y) not in corner:
                            continue
                        # A door has nowhere else to go when every tile of the
                        # boundary it stands in is a corner too. Leaving it is
                        # right: a broken corner beats a room nobody can enter.
                        pair = _sides_for(storey.grid, x, y, d)
                        elsewhere = [e for e in every
                                     if _sides_for(storey.grid, *e) == pair
                                     and (e[0], e[1]) not in corner]
                        if elsewhere:
                            bad_doors += 1
                        else:
                            stuck += 1

    check(bad_windows == 0,
          f"no window lands on a corner that carries two walls "
          f"({windows} windows over {7 * 4 * 3} stepped buildings, {bad_windows} bad)")
    check(bad_doors == 0,
          f"and a door on one moves along its own boundary ({doors} doors, "
          f"{bad_doors} that could have moved and did not, {stuck} with nowhere to go)")


def _sides_for(grid, x, y, d):
    """The room ids either side of a wall edge; 0 is outside."""
    h, w = len(grid), len(grid[0])

    def at(px, py):
        return grid[py][px] if 0 <= px < w and 0 <= py < h else 0

    return (at(x - 1, y), at(x, y)) if d == "W" else (at(x, y - 1), at(x, y))


def check_overture(check, work: str) -> None:
    """Buildings from Overture, where OpenStreetMap has none.

    OSM is drawn by people, so a town is on it as far as somebody traced it.
    Measured over the same size of box, Overture added 60 buildings to a
    German town and 761 to a Turkish one - nearly trebling it. None of this
    check needs the network or DuckDB: what is tested is the shape of the
    answer and the rule that decides what to keep, which is where the bugs
    would be.
    """
    import json as _json

    from generator import osm as _osm
    from generator import overture

    check(isinstance(overture.available(), bool),
          f"whether Overture can be reached is a plain yes or no "
          f"({'DuckDB is installed' if overture.available() else 'no DuckDB here'})")
    check("duckdb" in overture.why_unavailable().lower(),
          "and without it the window says what to install")

    def square(lat, lon, side_m, **row):
        """One Overture row: a square building of `side_m` metres."""
        d = side_m / 111320.0
        e = d / max(0.2, math.cos(math.radians(lat)))
        ring = [[lon, lat], [lon + e, lat], [lon + e, lat + d], [lon, lat + d],
                [lon, lat]]
        return {"id": row.get("id", "x"), "height": row.get("height"),
                "levels": row.get("levels"), "class": row.get("cls"),
                "geometry": {"type": "Polygon", "coordinates": [ring]}}

    rows = [
        square(38.60, 34.90, 12.0, id="a", cls="house"),
        square(38.61, 34.91, 20.0, id="b", cls=None, levels=3, height=9.5),
        square(38.62, 34.92, 1.5, id="c"),          # a sliver, not a building
        {"id": "d", "geometry": {"type": "MultiPolygon", "coordinates": [
            [[[34.93, 38.63], [34.9302, 38.63], [34.9302, 38.6302],
              [34.93, 38.6302], [34.93, 38.63]]]]},
         "height": None, "levels": None, "class": "barn"},
    ]
    feats = overture.to_features(rows)
    check(len(feats) == 3,
          f"a sliver is not a building and is left out ({len(rows)} rows, "
          f"{len(feats)} kept)")
    tags = {f.tags["building"] for f in feats}
    check("house" in tags and "barn" in tags and "yes" in tags,
          "Overture's class goes straight into the building tag, and a "
          "machine-found roof with no class becomes a plain footprint")
    levelled = [f for f in feats if f.tags.get("building:levels")]
    check(levelled and levelled[0].tags["building:levels"] == "3"
          and levelled[0].tags.get("height") == "9.5",
          "storeys and height come across where Overture has them")
    check(all(f.kind == "way" and f.osm_id < 0 for f in feats),
          "and they arrive as ways with ids no OSM way can have, so nothing "
          "downstream has to know where they came from")

    # The rule that decides what is new: a centre inside a mapped building.
    mapped = []
    for f in feats[:1]:
        mapped.append(_osm.OSMFeature(osm_id=1, kind="way",
                                      tags={"building": "house"},
                                      geometry=list(f.geometry)))
    kept = overture.only_missing(feats, mapped)
    check(len(kept) == len(feats) - 1,
          f"a roof standing on a building OSM already has is dropped "
          f"({len(feats)} offered, {len(kept)} kept)")
    check(overture.only_missing(feats, []) == feats,
          "and where OSM has nothing at all, all of them are kept")

    # What is cached is only reused for the same box and the same release.
    box = (38.60, 34.90, 38.64, 34.94)
    path = overture.cache_path(work, "ovtest")
    overture.save_cache(path, box, rows)
    check(overture.load_cache(path, box) is not None,
          "a fetch is kept beside the map, so the minutes are paid once")
    check(overture.load_cache(path, (38.60, 34.90, 38.64, 34.95)) is None,
          "a different area is not answered from it")
    was = os.environ.get("KNOXMAP_OVERTURE_RELEASE")
    os.environ["KNOXMAP_OVERTURE_RELEASE"] = "1999-01-01.0"
    try:
        stale = overture.load_cache(path, box)
    finally:
        if was is None:
            os.environ.pop("KNOXMAP_OVERTURE_RELEASE", None)
        else:
            os.environ["KNOXMAP_OVERTURE_RELEASE"] = was
    check(stale is None, "nor is a newer release answered from an older one")

    # Without DuckDB the map is still made, from OSM alone.
    out, stats = overture.add_missing([], box, work, "ovtest2")
    if overture.available():
        check(True, "DuckDB is here, so gap filling would run (not fetched in a check)")
    else:
        check(out == [] and stats["added"] == 0 and stats.get("why"),
              "without DuckDB the map is the one OSM alone makes, and says why")

    # ...but a map already fetched re-renders without it. Fetching is the one
    # thing DuckDB is for, and asking for it before looking in the cache meant
    # a folder handed to somebody else lost the buildings it had already paid
    # minutes for.
    seeded = os.path.join(work, "ovseed")
    os.makedirs(seeded, exist_ok=True)
    overture.save_cache(overture.cache_path(seeded, "m"), box, rows)
    out, stats = overture.add_missing([], box, seeded, "m")
    check(stats["cached"] and stats["added"] == len(feats)
          and len(out) == len(feats),
          f"a map already fetched fills its gaps again with no DuckDB at all "
          f"({stats['added']} buildings back out of the cache)")

    # The credit Overture's licence asks for, only on a map that used it.
    import make_map_mod as _mod

    proj = os.path.join(work, "ovattr-proj")
    mod = os.path.join(work, "ovattr-mod")
    os.makedirs(proj, exist_ok=True)
    os.makedirs(mod, exist_ok=True)
    with open(os.path.join(proj, "t_info.json"), "w", encoding="utf-8") as f:
        _json.dump({"osm_bbox": list(box)}, f)
    _mod.write_attribution(proj, mod, "Test Town")
    plain = open(os.path.join(mod, "ATTRIBUTION.txt"), encoding="utf-8").read()
    open(os.path.join(proj, "t_overture.json.gz"), "wb").write(b"x")
    _mod.write_attribution(proj, mod, "Test Town")
    filled = open(os.path.join(mod, "ATTRIBUTION.txt"), encoding="utf-8").read()
    check("Overture" not in plain and "Overture Maps Foundation" in filled
          and "OpenStreetMap" in filled,
          "a map that used Overture credits it, and one that did not does not")


def check_kitchen_fit(check) -> None:
    """A kitchen is fitted out the way Knox County fits one out.

    Measured over its 672 kitchens (median 21 m2): 1.0 sink, 1.0 fridge, 1.2
    cooking appliances and 3.9 pieces of the counter tileset, which includes
    the wall cupboards - they are fixtures_counters_01_024-027. Ours filled
    both long walls end to end and then hung cupboards above that, for 7.1,
    put a microwave over every one of them for 1.8 cooking appliances, and had
    a washing machine in 80% of kitchens against the game's 16%.
    """
    import collections as _collections
    import random as _random

    from knoxbuild import layout as _L
    from knoxbuild.settings import Settings as _Settings

    groups = {
        "sink": lambda r: "sink" in r,
        "cooking": lambda r: r.startswith(("stove", "oven", "microwave")),
        "fridge": lambda r: r.startswith("fridge"),
        "counter": lambda r: r.startswith("counter") or "cabinet" in r,
        "washer": lambda r: r.startswith(("washer", "dryer")),
    }
    # (at least, at most) per kitchen. The counter band is wide at the top
    # because a sink that does not land in a run gets one slid under it, on
    # the sink's own square - an extra piece but not an extra worktop.
    want = {"sink": (0.8, 1.3), "cooking": (0.9, 1.4), "fridge": (0.8, 1.2),
            "counter": (3.0, 5.6), "washer": (0.0, 0.35)}

    rng = _random.Random(7)
    seen = _collections.Counter()
    kitchens = 0
    for _ in range(200):
        w, h = rng.randrange(9, 20), rng.randrange(9, 20)
        b = _L.build_building(w, h, levels=1, seed=rng.randrange(1 << 20),
                              kind="house", commercial=False,
                              settings=_Settings())
        for storey in b.storeys:
            for room in storey.rooms:
                if room.kind != "kitchen":
                    continue
                kitchens += 1
                for role, x, y, _o in storey.furniture:
                    if not (room.x0 <= x <= room.x1
                            and room.y0 <= y <= room.y1):
                        continue
                    for name, test in groups.items():
                        if test(role):
                            seen[name] += 1
    check(kitchens > 50, f"{kitchens} kitchens to measure")
    for name, (lo, hi) in want.items():
        per = seen[name] / max(1, kitchens)
        check(lo <= per <= hi,
              f"a kitchen has {per:.1f} {name} per room, the game's is "
              f"{ {'sink': 1.0, 'cooking': 1.2, 'fridge': 1.0, 'counter': 3.9, 'washer': 0.2}[name] }")


def check_standing(check) -> None:
    """Nothing is drawn hanging in the air.

    A piece is drawn with its base part-way up its tile when it is meant to
    sit on something. The box was the stacking one, drawn a quarter of a tile
    up, and Knox County puts 336 of its 338 boxes on the one that sits on the
    ground. The sinks were a list of the two that existed when it was written,
    so the three added later hung.
    """
    from knoxbuild import catalog as C
    from knoxbuild import layout as L

    missed = [r for r in C.FURNITURE
              if "sink" in r and r != "sink_public"
              and C.FURNITURE_LAYERS.get(r, "Furniture") == "Furniture"
              and not L._needs_surface(r)]
    check(not missed, f"every sink knows it needs a worktop ({missed or 'all do'})")
    check(not L._needs_surface("sink_public"),
          "a public pedestal basin stands without a counter")

    # Every room name we write has to be one the game knows, or nothing
    # spawns in it. "cells" was the only one that was not: Knox County has 540
    # prisoncells and no cells at all.
    from knoxbuild import layout as _L
    names = set()
    for spec in _L.SPECIAL_MIXES.values():
        for part in spec:
            names.update(part)
    names.update(_L.COMMERCIAL, _L.COMMERCIAL_FILL, _L.RESIDENTIAL_FILL,
                 _L.HOUSE_SLEEPING, _L.UPSTAIRS)
    nostyle = sorted(n for n in names if n not in _L.ROOM_STYLE)
    check(not nostyle, f"every room a building can hold has furniture for it "
                       f"({'; '.join(nostyle) or 'all do'})")
    # BuildingEd wants a colour for every room name and throws without one,
    # which dropped the school and the police station out of a town silently.
    nocolour = sorted(n for n in _L.ROOM_STYLE if n not in C.ROOM_COLORS)
    check(not nocolour, f"and a colour, or the .tbx cannot be written "
                        f"({'; '.join(nocolour) or 'all do'})")
    school = set(_L.SPECIAL_MIXES["school"][0]) | set(_L.SPECIAL_MIXES["school"][1])
    check({"diningroom", "kitchen"} <= school,
          "a school has a canteen and a kitchen to serve it")
    check("prisoncells" in set(_L.SPECIAL_MIXES["police"][0]) and "cells" not in names,
          "a police station has prisoncells, the name the game knows")

    box = C.FURNITURE["crate"]["W"]["0,0"]
    check(box.endswith(("_016", "_017", "_018", "_019")),
          f"a box on the floor is the one drawn on the floor ({box})")

    # And a school is walked round, not through: only houses had circulation.
    from knoxbuild.settings import Settings as _S
    halls = 0
    plan = L.build_building(55, 40, levels=1, seed=3, kind="school",
                            commercial=True, settings=_S()).storeys[0]
    halls = sum(1 for r in plan.rooms if (r.kind or "") in L.CIRCULATION)
    check(halls >= 3, f"a school has corridors to reach its classrooms by "
                      f"({halls} of {len(plan.rooms)} rooms)")


def check_wall_styles(check) -> None:
    """No kind of building is built of one material only.

    Every church in a county was the same church: the special styles shipped
    one entry each for church, barn and industrial, and police, library, fire
    and barracks had none at all, so they fell through to the house styles and
    a police station could come out clapboard. Houses took one style per
    110-tile block, which built estates rather than streets.
    """
    import collections as _c
    import random as _r

    from knoxbuild import catalog as C
    from knoxbuild.build import BORROWED_STYLE, pick_style, wall_variants
    from knoxbuild.settings import Settings as _S

    thin = []
    for kind in sorted(set(C.SPECIAL_STYLES) | set(BORROWED_STYLE)):
        got = len(wall_variants(BORROWED_STYLE.get(kind, kind)))
        if got < 3:
            thin.append(f"{kind}:{got}")
    check(not thin, f"every kind of building has three walls to choose from "
                    f"({'; '.join(thin) or 'all do'})")

    # And inside as well: every variant of a kind used to share one interior
    # wall, so a county of schools was the same colour indoors.
    same = []
    for kind in sorted(set(C.SPECIAL_STYLES) | set(BORROWED_STYLE)):
        got = wall_variants(BORROWED_STYLE.get(kind, kind))
        inside = {v["interior"]["tiles"]["West"] for v in got}
        if len(inside) < 2:
            same.append(kind)
    check(not same, f"and more than one wall inside it "
                    f"({'; '.join(same) or 'all do'})")

    # And a street of houses is not one house repeated.
    rng, settings = _r.Random(1), _S()
    seen = _c.Counter()
    for i in range(120):
        style = pick_style(None, 100 + (i % 12) * 14, 100 + (i // 12) * 14,
                           rng, settings, 0.6)
        seen[style["name"]] += 1
    check(len(seen) >= 4 and max(seen.values()) < 0.6 * sum(seen.values()),
          f"and a block of houses is built of several ({len(seen)} over 120 "
          f"buildings, commonest {max(seen.values())})")

    # A police station is not built like a bungalow.
    civic = {s["name"] for s in wall_variants("civic")}
    house = {s["name"] for s in C.HOUSE_STYLES}
    got = pick_style("police", 500, 500, rng, settings, 0.6)
    check(got["name"] in civic and got["name"] not in house,
          f"a police station is built like a public building ({got['name']})")


def check_squares(check) -> None:
    """A public square is paved, not left as grass.

    Two ways a city square went missing. A pedestrian zone was read as a
    service alley and painted three and a half metres wide, so Madrid's Puerta
    del Sol - a mesh of pedestrian ways with no polygon anywhere - came out as
    stripes on a lawn. And an arcade, tagged as a passage through a building,
    was read as a tunnel and dropped, which took Plaza Mayor with it.
    """
    from generator.osm import classify
    from generator.renderer import ROAD_WIDTHS_M

    check(classify({"highway": "pedestrian"}, area=True) == "plaza"
          and classify({"highway": "pedestrian", "area": "yes"}) == "plaza"
          and classify({"place": "square"}) == "plaza",
          "a pedestrian way that closes on itself is a square")
    check(classify({"highway": "footway", "covered": "colonnade",
                    "tunnel": "building_passage"}, area=True) == "plaza",
          "and so is the colonnade round one, rather than a tunnel")
    check(classify({"highway": "pedestrian"}) == "pedestrian"
          and ROAD_WIDTHS_M["pedestrian"] > 2 * ROAD_WIDTHS_M["road_service"],
          f"a pedestrian street is paved wide, not as a service lane "
          f"({ROAD_WIDTHS_M['pedestrian']} m against "
          f"{ROAD_WIDTHS_M['road_service']} m)")
    check(classify({"highway": "service", "tunnel": "yes"}) is None
          and classify({"highway": "primary", "tunnel": "building_passage"}) is None,
          "and a road in a tunnel is still left off the surface")


def check_house_plan(check) -> None:
    """A house you walk round, not through.

    Every room opening onto every room it touches is a warren: the commonest
    door in a generated town was one bedroom into the next, and an upstairs
    had no landing at all because only a lift or stair core was ever made a
    hall. Rooms open onto circulation now, bar the pairs a real house has -
    a bathroom off a bedroom, and the kitchen, dining and living rooms.
    """
    import collections as _c

    from knoxbuild import layout as L
    from knoxbuild.settings import Settings as _S

    ok_pairs = [{"bedroom", "bathroom"}, {"kidsbedroom", "bathroom"},
                {"kitchen", "dining"}, {"kitchen", "livingroom"},
                {"dining", "livingroom"}]
    doors = through = 0
    floors = with_circulation = 0
    floating = 0
    for seed in range(60):
        b = L.build_building(10 + seed % 14, 9 + (seed * 7) % 12,
                             levels=1 + seed % 2, seed=seed, settings=_S())
        for storey in b.storeys:
            kinds = [r.kind or "?" for r in storey.rooms]
            if "kitchen" not in kinds and "bedroom" not in kinds:
                continue
            floors += 1
            with_circulation += any(k in L.CIRCULATION for k in kinds)
            for x, y, d in storey.doors:
                a = L._room_at(storey, x, y)
                o = L._room_at(storey, *((x, y - 1) if d == "N" else (x - 1, y)))
                if not a or not o or a == o:
                    continue
                ka, kb = kinds[a - 1], kinds[o - 1]
                doors += 1
                if ka in L.PRIVATE_ROOMS and kb in L.PRIVATE_ROOMS                         and {ka, kb} not in ok_pairs:
                    through += 1
            # And nothing standing on a piece too low to reach it: a lamp on a
            # coffee table hangs a quarter of a tile above it.
            under = {}
            for role, x, y, orient in storey.furniture:
                if L._is_wall_piece(role) or L._needs_surface(role):
                    continue
                for cell in L._cells_for(role, x, y, orient):
                    under[cell] = role
            for role, x, y, _o in storey.furniture:
                if not L._needs_surface(role):
                    continue
                beneath = under.get((x, y))
                if beneath is None or beneath in L.LOW_TABLES:
                    floating += 1
    share = 100.0 * through / max(doors, 1)
    check(floors and with_circulation == floors,
          f"every house floor has a hall, a landing or a living room "
          f"({with_circulation} of {floors})")
    check(share <= 20.0,
          f"and rooms open onto one rather than onto each other "
          f"({share:.0f}% of doors join two private rooms, was 56%)")
    check(not floating,
          f"nothing stands on a piece too low to hold it ({floating})")


def check_porch_lights(check, out: str) -> None:
    """A light by the front door of nearly every house.

    Knox County has one outside 92% of its houses and generated ones had 1%,
    which is most of why a street of them read as unfinished from outside.
    """
    import csv as _csv

    from knoxbuild.yards import PORCH_LIGHTS, _SIDE

    name = os.path.basename(out.rstrip(os.sep))
    bdir = os.path.join(out, "buildings")
    rows = list(_csv.DictReader(open(os.path.join(out, f"{name}_placements.csv"),
                                     encoding="utf-8")))
    houses = sum(1 for r in rows if r["kind"] == "house")

    lit = 0
    used = set()
    for fname in sorted(f for f in os.listdir(bdir) if "_lights_" in f):
        text = open(os.path.join(bdir, fname), encoding="utf-8").read()
        block = re.search(r"<user_tiles>(.*?)</user_tiles>", text, re.S)
        order = re.findall(r'<tile tile="([^"]+)"/>', block.group(1)) if block else []
        for grid in re.findall(r'<tiles layer="[^"]*">(.*?)</tiles>', text, re.S):
            for value in grid.split(","):
                value = value.strip()
                if value and value != "0":
                    lit += 1
                    if int(value) - 1 < len(order):
                        used.add(order[int(value) - 1])
    check(houses and lit >= houses * 0.8,
          f"a light by the front door of nearly every house ({lit} on {houses})")

    # The sprite carries the direction, so the table is the thing that can go
    # wrong: a side missing, or one tile answering two of them.
    from collections import Counter as _Counter
    seen = _Counter()
    shaped = all(set(style) == set(_SIDE.values()) for style in PORCH_LIGHTS)
    for style in PORCH_LIGHTS:
        seen.update(style.values())
    known = {t for style in PORCH_LIGHTS for t in style.values()}
    check(shaped and max(seen.values()) == 1 and used <= known,
          f"and each one has a sprite for the wall it hangs on "
          f"({len(PORCH_LIGHTS)} styles, {len(used)} used)")

    # The light shares its square with the house wall, and WorldEd lays a
    # cell's lots down in the order the project lists them. Sorted by position
    # the light went down first and the wall covered it: in the game there was
    # nothing on the wall at all.
    from knoxbuild.world import Placement, render_pzw
    order = re.findall(r'map="buildings/(\w+)\.tbx"', render_pzw(
        1, 1, "m.bmp", [Placement("buildings/lamp.tbx", 40, 10, 2, 2, on_top=True),
                        Placement("buildings/house.tbx", 8, 40, 12, 10)]))
    check(order == ["house", "lamp"],
          f"and is laid down after the wall it hangs on, not before it ({order})")


def check_repair(check, out: str) -> None:
    """A project broken at its edges, as older versions and hand edits leave
    them, is repaired before compiling instead of stopping it."""
    from knoxbuild.repair import repair_project

    source = os.path.join(out, "selftest.pzw")
    broken = os.path.join(out, "broken.pzw")
    text = open(source, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in text else "\n"
    first_lot = re.search(r'map="(buildings/selftest_\d+\.tbx)"', text).group(1)
    # Not among the buildings: the checks further on read every file there.
    os.makedirs(os.path.join(out, "broken"), exist_ok=True)
    with open(os.path.join(out, "broken", "broken.tbx"), "w", encoding="utf-8") as f:
        f.write("<building version=\"4\" width=\"0\" height=\"3\"></building>")
    extra = nl.join([
        ' <cell x="9" y="0" map="">',                       # a whole cell past the edge
        f'  <lot x="5" y="5" level="0" width="3" height="3" map="{first_lot}"/>',
        " </cell>",
        ' <cell x="0" y="0" map="">',
        f'  <lot x="310" y="20" level="0" width="3" height="3" map="{first_lot}"/>',  # in cell 1,0 really
        '  <lot x="20" y="20" level="0" width="3" height="3" map="buildings/missing.tbx"/>',
        '  <lot x="30" y="20" level="0" width="3" height="3" map="broken/broken.tbx"/>',
        '  <object name="" group="TownZone" type="TownZone" x="10" y="950" level="0" width="5" height="5"/>',
        " </cell>",
    ])
    text = text.replace("</world>", extra + nl + "</world>")
    with open(broken, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    report = repair_project(broken)
    fixed = open(broken, encoding="utf-8").read()
    cells = [(int(a), int(b)) for a, b in re.findall(r'<cell x="(-?\d+)" y="(-?\d+)"', fixed)]
    size = re.search(r'<world version="[^"]*" width="(\d+)" height="(\d+)"', fixed)
    w, h = int(size.group(1)), int(size.group(2))
    reasons = " ".join(why for _what, why in report["dropped"])
    check(report["changed"] and report["moved"] == 1 and len(report["dropped"]) == 4
          and all(0 <= x < w and 0 <= y < h for x, y in cells)
          and len(cells) == len(set(cells))
          and "missing.tbx" not in fixed and "broken.tbx" not in fixed
          and "missing" in reasons and "outside" in reasons
          and os.path.exists(broken + ".bak"),
          f"a project broken at its edges is repaired, not refused "
          f"(moved {report['moved']}, dropped {len(report['dropped'])})")
    check(not repair_project(broken)["changed"] and not repair_project(source)["changed"],
          "a sound project is left exactly as it is")


def check_memory_guard(check) -> None:
    """A map too big for the memory there is says so before it starts.

    It is a warning now, not a refusal: nothing about an area stops a map
    being built, because a big map can be built and what it costs is the
    mapper's to spend. What this still has to do is say the number, so
    somebody choosing an area knows, and so a run that does die of it has the
    figure in its log."""
    import app as knoxapp
    import knoxlog

    real = knoxlog.memory_status
    try:
        knoxlog.memory_status = lambda: (15_000_000_000, 5_300_000_000, 2_100_000_000)

        class Small:                      # a 32-bit Python
            maxsize = 2 ** 32 - 1

        was, knoxapp.sys = knoxapp.sys, Small
        try:
            big = knoxapp._too_big_for_memory(5400, 6000)
            small = knoxapp._too_big_for_memory(1200, 1200)
        finally:
            knoxapp.sys = was
        import knoxpaths as _kp
        check(big and "32-bit" in big and _kp.setup_command() in big and not small,
              "a map too big for a 32-bit Python is warned about, with a way out")
        knoxlog.memory_status = lambda: (15_000_000_000, 900_000_000, 140_000_000_000)
        tight = knoxapp._too_big_for_memory(5400, 6000)
        check(tight and "free" in tight,
              "and so is one too big for the memory that is free")
    finally:
        knoxlog.memory_status = real


def check_overpass_retry(check) -> None:
    """A busy Overpass server does not lose the map.

    The public instances are shared and go busy together. A tile that nothing
    answered used to fail the whole download: every tile that had arrived was
    thrown away uncached, so a town that fetched forty and missed one started
    again from nothing. Nothing here touches the network.
    """
    import requests

    from generator import osm as _osm

    was_split, was_ask, was_pause = (_osm._fetch_splitting, _osm._ask,
                                     _osm.RETRY_PAUSE_S)
    was_check, was_tiles = _osm.check_endpoints, _osm.TILE_CACHE_DIR
    tile_dir = tempfile.mkdtemp(prefix="knoxmap-tiles-")
    try:
        _osm.RETRY_PAUSE_S = 0
        # Two things here reach outside the test. check_endpoints asks the
        # real public instances whether they are up, which this must not do
        # and which the docstring above promises it does not. The tile cache
        # keeps what a tile "downloaded" under the project's own cache folder,
        # so the second run of this test was served sixteen tiles it had
        # written itself and never saw the failure it was checking for.
        _osm.check_endpoints = lambda *a, **k: None
        _osm.TILE_CACHE_DIR = tile_dir
        seen: dict = {}
        ids: dict = {}

        def once_then_works(south, west, north, east, timeout, depth=0, first=0):
            key = (round(south, 4), round(west, 4))
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 1:
                raise _osm.OverpassError("busy", timed_out=True)
            # One feature per tile, each with an id of its own: the tiles are
            # merged on (kind, id), so a shared id would hide a lost tile.
            return [_osm.OSMFeature(osm_id=ids.setdefault(key, len(ids) + 1),
                                    kind="way", tags={},
                                    geometry=[(west, south)])]

        _osm._fetch_splitting = once_then_works
        got = _osm.fetch_features_tiled(50.0, 5.0, 50.2, 5.3, max_tile_km2=30.0)
        check(len(got) == len(seen) and len(seen) > 1,
              f"a tile that fails once is asked for again, and the map still "
              f"arrives ({len(seen)} tiles)")

        def never_works(south, west, north, east, timeout, depth=0, first=0):
            raise _osm.OverpassError("every Overpass endpoint failed — busy",
                                     timed_out=True)

        # A fresh cache: the tiles the check above "downloaded" are kept for
        # a fortnight, and handing them back here would answer the very
        # question this is asking - whether a download that fails everywhere
        # says so.
        _osm.TILE_CACHE_DIR = tempfile.mkdtemp(prefix="knoxmap-tiles-")
        _osm._fetch_splitting = never_works
        try:
            _osm.fetch_features_tiled(50.0, 5.0, 50.2, 5.3, max_tile_km2=30.0)
            said = ""
        except _osm.OverpassError as exc:
            said = str(exc)
        check("tiles would not download" in said and "smaller area" in said,
              "and when they all fail it says how many and what to do")

        # A tile nothing answers is quartered like a refused one, but the
        # splitting has to stop: on a dropped connection every request times
        # out, and each one waits out the clock before it says so.
        _osm._fetch_splitting = was_split
        tries = []

        def dead(endpoint, query, timeout):
            tries.append(endpoint)
            raise requests.Timeout("no answer")

        _osm._ask = dead
        side = (30.0 ** 0.5) / 111.32
        for area, ceiling in ((side, 3), (side / 6, 2)):
            tries.clear()
            try:
                _osm._fetch_splitting(50.0, 5.0, 50.0 + area, 5.0 + area, 30)
            except _osm.OverpassError:
                pass
            check(len(tries) <= ceiling * len(_osm.OVERPASS_ENDPOINTS),
                  f"a tile nobody answers gives up after {len(tries)} requests")
    finally:
        _osm._fetch_splitting, _osm._ask = was_split, was_ask
        _osm.RETRY_PAUSE_S = was_pause
        used = _osm.TILE_CACHE_DIR
        _osm.check_endpoints, _osm.TILE_CACHE_DIR = was_check, was_tiles
        for d in {tile_dir, used}:
            shutil.rmtree(d, ignore_errors=True)


def check_flat_selection(check) -> None:
    """An outline with no area is refused, not built as an empty map.

    A lasso drawn as one stroke, or a traced outline whose points land on each
    other, gets through as a valid polygon that encloses nothing. The renderer
    clips the map to it, which turns everything outside - all of it - back
    into grass, and the generation finishes and hands over a meadow.
    """
    import app as knoxapp

    w, s, e, n = 19.20, 42.40, 19.32, 42.48

    def ask(ring):
        shape, problem = knoxapp._clean_shape(
            {"type": "Polygon", "coordinates": [ring]})
        return shape, problem

    shape, problem = ask([[w, s], [e, s], [e, n], [w, n], [w, s]])
    check(shape is not None and not problem,
          "an outline drawn round a town is taken")

    # Small, but a real selection: roughly 220 m across. Nothing here may
    # refuse a genuinely small map.
    shape, problem = ask([[w, s], [w + 0.002, s], [w + 0.002, s + 0.002],
                          [w, s + 0.002], [w, s]])
    check(shape is not None and not problem,
          "and so is a small one, a couple of hundred metres across")

    for label, ring in (
        ("one stroke", [[w, s], [(w + e) / 2, (s + n) / 2], [e, n], [w, s]]),
        ("all one point", [[w, s]] * 4),
    ):
        shape, problem = ask(ring)
        check(shape is None and problem and "no area" in problem,
              f"an outline that is {label} is refused with a reason, not "
              f"generated as empty ground")


def check_overpass_blank(check) -> None:
    """A server that answers with nothing does not empty the map.

    Two ways a download used to succeed and bring back no town. Overpass
    reports a query it could not finish as HTTP 200 with the reason in
    "remark" and whatever it had managed in "elements"; and one of the public
    instances answers every query at all with 200 and an empty list. Either
    read as a tile of open farmland, so a city came out a meadow with its
    river still in it - the river was in the tiles that did arrive. Nothing
    here touches the network.
    """
    from generator import osm as _osm

    class Reply:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    ONE = {"elements": [{"type": "node", "id": 1, "lat": 50.0, "lon": 5.0,
                         "tags": {"natural": "tree"}}]}
    EMPTY: dict = {"elements": []}

    was_post, was_sleep = _osm.requests.post, _osm.time.sleep
    try:
        _osm.time.sleep = lambda _s: None
        replies: dict = {}
        asked: list = []

        def post(endpoint, data=None, headers=None, timeout=None):
            asked.append(endpoint.split("/")[2])
            return replies.get(asked[-1], Reply(EMPTY))

        _osm.requests.post = post
        first_host = _osm.OVERPASS_ENDPOINTS[0].split("/")[2]

        # A part-finished query is a failure, not an empty tile.
        replies = {first_host: Reply({**EMPTY, "remark":
                   'runtime error: Query timed out in "query" after 90 s.'})}
        try:
            _osm._ask(_osm.OVERPASS_ENDPOINTS[0], "", 60)
            said, big = "", False
        except _osm.OverpassError as exc:
            said, big = str(exc), exc.too_big
        check("timed out" in said and big,
              "a 200 that says the query timed out counts as too big, not as "
              "an empty tile")

        # The instance whose turn it is answers with nothing; another has the
        # data. The tile is the data.
        _osm._cooling.clear()
        second_host = _osm.ANSWERING_ENDPOINTS[1].split("/")[2]
        replies = {second_host: Reply(ONE)}
        asked.clear()
        got = _osm.fetch_features(50.0, 5.0, 50.1, 5.1, timeout=10, first=0)
        check(len(got) == 1 and asked[1] == second_host,
              f"a blank answer is not the tile; the next instance is asked "
              f"and its {len(got)} feature kept")

        # The instance that answers an ordinary query with nothing is asked
        # last, never first. Rotating over all three put every third tile on
        # it to begin with, which spent a round trip and a second's wait
        # before the tile had asked anything that could answer it.
        blank_host = _osm.OVERPASS_ENDPOINTS[-1].split("/")[2]
        firsts = set()
        _osm._cooling.clear()
        for turn in range(len(_osm.OVERPASS_ENDPOINTS) * 2):
            replies = {}
            asked.clear()
            _osm._cooling.clear()
            _osm.fetch_features(50.0, 5.0, 50.1, 5.1, timeout=10, first=turn)
            firsts.add(asked[0])
        check(blank_host not in firsts,
              f"{blank_host} answers with nothing, so no tile starts on it "
              f"(tiles started on {len(firsts)} of the others)")

        # ...but real open country is empty, and has to stay downloadable.
        _osm._cooling.clear()
        replies = {}
        got = _osm.fetch_features(50.0, 5.0, 50.1, 5.1, timeout=10)
        check(got == [],
              "a tile every instance agrees is empty is still an empty tile")

        # One instance saying nothing while the rest never answer is not
        # agreement. The tile goes back round the retry rather than into the
        # map as a field.
        _osm._cooling.clear()
        replies = {h.split("/")[2]: Reply({}, status=504)
                   for h in _osm.OVERPASS_ENDPOINTS[1:]}
        try:
            got = _osm.fetch_features(50.0, 5.0, 50.1, 5.1, timeout=10)
            said = f"returned {len(got)} features"
        except _osm.OverpassError:
            said = "raised"
        check(said == "raised",
              "one blank answer and no other answer at all is a failed tile, "
              f"not an empty one ({said})")

        # An instance that stopped answering is left out until it has had a
        # rest, so the tiles behind the first one do not each wait the whole
        # timeout to learn the same thing.
        _osm._cooling.clear()
        down = _osm.ANSWERING_ENDPOINTS[0]
        replies = {down.split("/")[2]: Reply({}, status=504)}
        asked.clear()
        _osm.fetch_features(50.0, 5.0, 50.1, 5.1, timeout=10, first=0)
        paid = list(asked)
        asked.clear()
        _osm.fetch_features(50.0, 5.0, 50.1, 5.1, timeout=10, first=0)
        check(asked[0] != down.split("/")[2] and down.split("/")[2] in asked,
              "an instance that answered 504 goes to the back of the queue "
              f"for the tiles behind it, but is still asked ({asked})")

        # ...but when every instance is resting there is nothing else to do.
        _osm._cooling.clear()
        for e in _osm.ANSWERING_ENDPOINTS:
            _osm._note_down(e)
        order = _osm._endpoint_order(0)
        check(all(e in order for e in _osm.ANSWERING_ENDPOINTS),
              "with every instance resting the tile asks them all anyway: a "
              "rest is a guess and may not be the reason a town fails")
        _osm._cooling.clear()

        # The wait between passes outlasts a busy spell instead of landing
        # back inside it.
        pauses = [_osm._retry_pause(a) for a in range(1, _osm.TILE_ATTEMPTS)]
        check(pauses == sorted(pauses) and pauses[-1] >= 90 and len(pauses) >= 2,
              f"the retry backs off over minutes, not seconds ({pauses})")

        # A map small enough to be a single tile still gets every pass: it is
        # what the failure message tells people to try, so it must not be the
        # path that tries least.
        _osm._cooling.clear()
        passes = [0]
        real_split = _osm._fetch_splitting

        def counting(*a, **k):
            passes[0] += 1
            raise _osm.OverpassError("nope", timed_out=True)

        _osm._fetch_splitting = counting
        pause, _osm.RETRY_PAUSE_S = _osm.RETRY_PAUSE_S, 0
        try:
            _osm.fetch_features_tiled(50.0, 5.0, 50.01, 5.01, max_tile_km2=30.0)
        except Exception:
            pass
        finally:
            _osm._fetch_splitting = real_split
            _osm.RETRY_PAUSE_S = pause
        check(passes[0] == _osm.TILE_ATTEMPTS,
              f"a one-tile map is asked for on every pass, not just the first "
              f"({passes[0]} of {_osm.TILE_ATTEMPTS})")

        check("openstreetmap.fr" not in " ".join(_osm.OVERPASS_ENDPOINTS),
              "the endpoint that 403s every request is not asked")
    finally:
        _osm.requests.post, _osm.time.sleep = was_post, was_sleep


def check_no_size_wall(check, work: str) -> None:
    """An area bigger than the comfortable one is still built.

    Every size check used to answer 400 and the window greyed the button out,
    so somebody who wanted a whole city could not have one at all. They are
    warnings now: the window says what it will cost and the button stays lit.
    What is still refused is a scale that is not a scale, because dividing the
    world by zero is not a map anybody asked for.

    Nothing here touches the network. The OpenStreetMap fetch is replaced with
    something that fails at once, so a request that reaches it has been past
    every size gate there is - which is the thing being tested.
    """
    import app as knoxapp

    class Reached(RuntimeError):
        """Raised where the download would start."""

    def no_download(*_a, **_k):
        raise Reached("got as far as the download")

    client = knoxapp.app.test_client()
    was_fetch = knoxapp.osm.fetch_features_tiled
    was_out = knoxapp.OUTPUT_DIR
    knoxapp.osm.fetch_features_tiled = no_download
    knoxapp.OUTPUT_DIR = Path(work) / "huge-maps"
    knoxapp.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # Past every old limit but the one WorldEd has: 25 km x 10 km at a metre a
        # tile, 25,000 tiles a side and 250 million tiles. (A map past 268
        # million is refused: see check_worlded_size.)
        huge = {"south": 51.2, "west": -0.6, "north": 51.29, "east": -0.24,
                "metersPerTile": 1, "mapName": "selftest-huge"}
        said = client.post("/api/generate", json=huge)
        body = (said.get_json() or {}).get("error", "")
        check("got as far as the download" in body,
              f"a map past every old limit but WorldEd's is built, not refused "
              f"({said.status_code}: {body[:60]})")

        for scale, what in ((0, "zero"), (-1, "a negative"), (1e9, "a silly")):
            bad = client.post("/api/generate", json={**huge, "metersPerTile": scale})
            if bad.status_code != 400:
                check(False, f"{what} scale should still be refused")
                break
        else:
            check(True, "but a scale of zero, a negative one or a silly one is not")
    finally:
        knoxapp.osm.fetch_features_tiled = was_fetch
        knoxapp.OUTPUT_DIR = was_out

    check(knoxapp.BIG_AREA_KM2 > 0 and knoxapp.BIG_TILES_PER_SIDE > 0
          and knoxapp.BIG_LANDMARK_KM2 > 0,
          "and the numbers behind the warnings are still there to warn with")


def check_repeatable_seeds(check) -> None:
    """Two processes must pick the same floors and trims for one building: the
    seeds were hash() of a string, which Python randomises per process."""
    import subprocess

    code = ("from knoxbuild.tbx import _stable_seed; "
            "print(_stable_seed('Selftest House', 7, 9, 'trim'), "
            "_stable_seed('Selftest House', 12, 7, 9))")
    seen = set()
    for hashseed in ("1", "2", "random"):
        env = {**os.environ, "PYTHONHASHSEED": hashseed}
        got = subprocess.run([sys.executable, "-c", code], env=env,
                             cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             capture_output=True, text=True).stdout.strip()
        seen.add(got)
    check(len(seen) == 1 and "" not in seen,
          "a building's floor and trim seeds are the same in every process")


def check_compile_records(check, work: str) -> None:
    """The compile's record of what it compiled is only kept while it is true."""
    import numpy as np

    import knoxlog
    import knoxstop
    import knoxbuild.repair as repair
    from tools import compile_map as compiler
    from tools import compile_state as cs

    project = Path(work) / "records"
    (project / "lots").mkdir(parents=True)
    (project / "tmx").mkdir()
    (project / "buildings").mkdir()
    Image.fromarray(np.zeros((600, 600, 3), dtype=np.uint8)).save(
        project / "records.bmp", format="BMP")
    (project / "buildings" / "a.tbx").write_text("one")
    cell = '<cell x="{x}" y="{y}" map="">\n <lot x="1" y="1" level="0" width="2" height="2" map="buildings/a.tbx"/>\n</cell>\n'
    (project / "records.pzw").write_text(
        '<world version="1.0" width="2" height="2">\n<worldOrigin origin="70,0"/>\n'
        '<bmp path="records.bmp" x="0" y="0" width="2" height="2"/>\n'
        + "".join(cell.format(x=x, y=y) for x in range(2) for y in range(2))
        + "</world>", encoding="utf-8")
    exe = project / "PZWorldEd_cli"
    exe.write_text("", encoding="utf-8")

    ran: list = []
    explode = [False]

    class Done:
        returncode, stdout, stderr = 0, "", ""

    def fake(cmd, should_stop, started):
        arg = [a for a in cmd if a.startswith("--cells=")][0]
        box = tuple(int(v) for v in arg[len("--cells="):].split(","))
        ran.append(box)
        if explode[0]:
            raise knoxstop.Stopped("the compile")
        cells = {(x, y) for x in range(box[0], box[2] + 1) for y in range(box[1], box[3] + 1)}
        for lx, ly in cs.lot_files_of(cells, (70, 0)):
            (project / "lots" / f"{lx}_{ly}.lotheader").write_text("new")
        return Done()

    keep = {n: getattr(compiler, n) for n in ("_run_batch",)}
    keep_saved, keep_repair = knoxlog.save_tool_output, repair.repair_project
    compiler._run_batch = fake
    knoxlog.save_tool_output = lambda *a, **k: None
    repair.repair_project = lambda pzw: {"changed": 0, "moved": 0, "dropped": []}
    try:
        compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1)
        check(cs.load(project) is not None and len(ran) == 4,
              "a compile that finishes leaves a record, having run every batch")

        ran.clear()
        compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1)
        check(not ran, "and with nothing changed the next one starts no batch at all")

        (project / "lots" / "84_2.lotheader").write_text("old")
        compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1,
                             only_cells=[[0, 0, 0, 0]], fresh=True)
        check((project / "lots" / "84_2.lotheader").read_text() == "old",
              "starting from scratch does not apply to a retry of just some cells")

        (project / "buildings" / "a.tbx").write_text("two")
        ran.clear()
        explode[0] = True
        try:
            compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1)
        except knoxstop.Stopped:
            pass
        check(ran and cs.load(project) is None,
              "a compile that stops part way leaves no record of the lots it half changed")
        explode[0] = False
        compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1)
        check(cs.load(project) is not None, "and the next one that finishes writes it again")
    finally:
        compiler._run_batch = keep["_run_batch"]
        knoxlog.save_tool_output = keep_saved
        repair.repair_project = keep_repair


def check_odd_requests(check, work: str) -> None:
    """Requests with the wrong kind of value in them are answered, not crashed on,
    and a download that fails leaves no folder behind."""
    import app as knoxapp

    def no_download(*_a, **_k):
        raise RuntimeError("the network is off in this test")

    was_fetch, was_out = knoxapp.osm.fetch_features_tiled, knoxapp.OUTPUT_DIR
    knoxapp.osm.fetch_features_tiled = no_download
    knoxapp.OUTPUT_DIR = Path(work) / "odd_output"
    knoxapp.OUTPUT_DIR.mkdir()
    try:
        client = knoxapp.app.test_client()
        box = {"south": 40.0, "west": 20.0, "north": 40.01, "east": 20.01}
        statuses = [client.post("/api/generate", json={**box, "mapName": what}).status_code
                    for what in (7, ["x"], {"a": 1}, True)]
        check(set(statuses) == {502},
              f"a map name that is not text is replaced by one, not a crash ({statuses})")
        check(not any(knoxapp.OUTPUT_DIR.iterdir()),
              "and a download that fails leaves no folder in output/")
        check(all(client.post("/api/client-error", json=v).status_code == 200
                  for v in ("x", 5, [], None)),
              "the page's error report is taken whatever it sends")
    finally:
        knoxapp.osm.fetch_features_tiled = was_fetch
        knoxapp.OUTPUT_DIR = was_out


def check_osm_parse_tolerant(check) -> None:
    """One bad element in an Overpass answer is skipped, not the end of the tile."""
    from generator import osm

    pt = {"lat": 1.0, "lon": 2.0}
    cases = {
        "a null point in a way": {"elements": [{"type": "way", "id": 1, "geometry": [pt, None, pt]}]},
        "a way with null geometry": {"elements": [{"type": "way", "id": 1, "geometry": None}]},
        "a null point in a relation": {"elements": [{"type": "relation", "id": 2, "members": [
            {"role": "outer", "geometry": [pt, None, {"lat": 1, "lon": 3}, pt]}]}]},
        "a point with no latitude": {"elements": [{"type": "way", "id": 1, "geometry": [{"lon": 2.0}]}]},
        "an element with no id": {"elements": [{"type": "way", "geometry": [pt, pt]}]},
        "null members": {"elements": [{"type": "relation", "id": 2, "members": None}]},
        "null elements": {"elements": None},
        "an answer that is not an object": [],
    }
    failed = []
    for what, payload in cases.items():
        try:
            osm._parse(payload)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{what}: {type(exc).__name__}")
    check(not failed, "an Overpass answer with nulls and gaps in it is still read"
                      + (f" (failed: {failed})" if failed else ""))
    good = osm._parse({"elements": [{"type": "way", "id": 1, "geometry": [pt, None, {"lat": 3, "lon": 4}]},
                                    "junk", {"type": "way", "id": 2, "geometry": [pt, pt]}]})
    check(len(good) == 2 and len(good[0].geometry) == 2,
          "and what is there is kept: the good points of a way, and the elements around it")


def check_osm_cache(check, work: str) -> None:
    """A cached download that is damaged is a miss, and a save cannot leave half a file."""
    import gzip
    import json as _json

    from generator import osm

    path = os.path.join(work, "osm_cache", "area.json.gz")
    bbox = (1.0, 2.0, 3.0, 4.0)
    feats = [osm.OSMFeature(i, "way", {"building": "yes"}, [(1, 2), (2, 3), (3, 4)])
             for i in range(500)]
    osm.save_cache(path, bbox, feats)
    check(len(osm.load_cache(path, bbox)) == 500 and not os.path.exists(path + ".part"),
          "a saved download comes back whole, with no half-written file beside it")
    whole = open(path, "rb").read()
    good_header = {"filters": osm.FILTERS_VERSION, "bbox": list(bbox)}
    damaged = {
        "cut short by a crash": whole[:len(whole) // 2],
        "not a gzip file at all": b"nope",
        "empty": b"",
        "a list rather than an object": gzip.compress(b"[1, 2]"),
        "an entry with a field missing": gzip.compress(_json.dumps(
            {**good_header, "features": [{"kind": "way"}]}).encode()),
        "a feature that is not an object": gzip.compress(_json.dumps(
            {**good_header, "features": ["x"]}).encode()),
    }
    worked = []
    for what, data in damaged.items():
        with open(path, "wb") as fh:
            fh.write(data)
        try:
            if osm.load_cache(path, bbox) is not None:
                worked.append(what)
        except Exception as exc:  # noqa: BLE001
            worked.append(f"{what} raised {type(exc).__name__}")
    check(not worked, "a damaged cache file is read as 'not cached', never as an error"
                      + (f" (not so: {worked})" if worked else ""))

    class Boom(Exception):
        pass

    good_before = os.path.join(work, "osm_cache", "keep.json.gz")
    osm.save_cache(good_before, bbox, feats[:3])
    was_dump = osm.json.dump
    osm.json.dump = lambda *a, **k: (_ for _ in ()).throw(Boom())
    try:
        osm.save_cache(good_before, bbox, feats)
    except Boom:
        pass
    finally:
        osm.json.dump = was_dump
    check(len(osm.load_cache(good_before, bbox)) == 3 and not os.path.exists(good_before + ".part"),
          "a save that fails part way leaves the earlier file as it was")


def check_config_file(check, work: str) -> None:
    """The settings file survives being damaged, and being written twice at once."""
    import json as _json
    import threading

    import knoxpaths

    was = knoxpaths.CONFIG_PATH
    knoxpaths.CONFIG_PATH = Path(work) / "config_test.json"
    try:
        for what, text in (("a list", "[1, 2]"), ("null", "null"), ("a string", '"x"'),
                           ("cut short", '{"pz_install": "C:/Games/Zomb'), ("empty", "")):
            knoxpaths.CONFIG_PATH.write_text(text, encoding="utf-8")
            if knoxpaths.load_config() != {}:
                check(False, f"{what} should read as no settings at all")
                break
        else:
            check(True, "a settings file that is not an object reads as no settings")
        knoxpaths.CONFIG_PATH.write_text(_json.dumps({"pz_install": "C:/Games/PZ"}), encoding="utf-8")
        knoxpaths.update_config({"language": "english"})
        knoxpaths.update_config({"auto_update": False})
        got = knoxpaths.load_config()
        check(got == {"pz_install": "C:/Games/PZ", "language": "english", "auto_update": False}
              and not Path(str(knoxpaths.CONFIG_PATH) + ".tmp").exists(),
              "changing one setting keeps the rest, and False is kept as False")
        threads = [threading.Thread(target=knoxpaths.update_config, args=({f"key{i}": i},))
                   for i in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        got = knoxpaths.load_config()
        check(all(got.get(f"key{i}") == i for i in range(40)),
              "forty changes made at once are all kept")
    finally:
        knoxpaths.CONFIG_PATH = was


def check_install_clears(check, work: str) -> None:
    """Installing over an old copy that cannot be removed stops, rather than mixing the two."""
    import shutil as _shutil

    from tools import make_map_mod

    old = Path(work) / "old_install"
    (old / "sub").mkdir(parents=True)
    (old / "sub" / "1_1.lotheader").write_text("old")
    make_map_mod._clear_folder(str(old))
    check(not old.exists(), "an old installed copy is removed before the new one goes in")

    stuck = Path(work) / "stuck_install"
    stuck.mkdir()
    (stuck / "5_5.lotheader").write_text("old")
    was = _shutil.rmtree
    make_map_mod.shutil.rmtree = lambda *a, **k: None       # a folder the game holds open
    try:
        try:
            make_map_mod._clear_folder(str(stuck), tries=1)
            said = ""
        except RuntimeError as exc:
            said = str(exc)
    finally:
        make_map_mod.shutil.rmtree = was
    check("could not be removed" in said and "Close Project Zomboid" in said and stuck.exists(),
          "and one that cannot be removed is reported, with what to do about it")


def check_odd_tags(check) -> None:
    """Heights and storeys come from free text on OpenStreetMap; none of it may stop a build."""
    from knoxbuild.build import levels_from_tags
    from knoxbuild.settings import Settings

    settings = Settings()
    worst = ["inf", "-inf", "Infinity", "nan", "1e999", "-1e999", "1e308", "9" * 400, "", " ",
             "-3", "0", "3;4", "3,5", "3 floors", "x", "40'", "12 ft", "0x10", "1_0"]
    bad = []
    for key in ("building:levels", "levels", "height", "building:height", "est_height"):
        for value in worst:
            try:
                got = levels_from_tags({key: value}, settings)
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{key}={value!r}: {type(exc).__name__}")
                continue
            if got is not None and not 1 <= got <= settings.max_levels:
                bad.append(f"{key}={value!r}: {got} storeys")
    for key in ("roof:levels", "min_height"):
        for value in worst:
            for base in ({"building:levels": "2"}, {"height": "20"}):
                try:
                    levels_from_tags({**base, key: value}, settings)
                except Exception as exc:  # noqa: BLE001
                    bad.append(f"{key}={value!r}: {type(exc).__name__}")
    from generator import renderer, structures
    from generator.osm import OSMFeature

    for value in worst:
        try:
            structures._storeys({"height": value}, 2)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"structures height={value!r}: {type(exc).__name__}")
        for key in ("width", "est_width", "lanes"):
            way = OSMFeature(1, "way", {"highway": "residential", key: value}, [(1, 2), (1, 3)])
            try:
                got = renderer._way_width_m(way, "road_minor")
            except Exception as exc:  # noqa: BLE001
                bad.append(f"road {key}={value!r}: {type(exc).__name__}")
                continue
            if value in ("nan", "inf", "-inf", "Infinity") and key != "lanes" \
                    and got != renderer._way_width_m(OSMFeature(1, "way", {"highway": "residential"}, []), "road_minor"):
                bad.append(f"road {key}={value!r} made a {got} m road")
    proj = renderer.Projector.build(SOUTH, WEST, NORTH, EAST, 1.0)
    for value in worst:
        try:
            structures.level_of({"layer": value, "highway": "residential"})
        except Exception as exc:  # noqa: BLE001
            bad.append(f"layer={value!r}: {type(exc).__name__}")
        try:
            renderer._places([OSMFeature(1, "node", {"place": "town", "population": value},
                                         [(SOUTH, WEST)])], proj)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"population={value!r}: {type(exc).__name__}")
    check(not bad, "no height or storey tag, however odd, raises" + (f" ({bad[:4]})" if bad else ""))
    check(levels_from_tags({"building:levels": "3;4"}, settings) == 3
          and levels_from_tags({"height": "12"}, settings) == 4
          and levels_from_tags({"building:levels": "inf", "height": "12"}, settings) == 4,
          "and a tag that is not a number falls through to the next one that is")


def check_degenerate_footprints(check) -> None:
    """A footprint with too few points is too small, not an error."""
    import numpy as np

    from knoxbuild.footprint import place

    occupied = np.zeros((40, 40), dtype=bool)
    said = []
    for points in ([], [(5, 5)], [(5, 5), (9, 9)], [(5, 5), (5, 5), (5, 5)]):
        try:
            said.append(place(points, occupied, min_side=3)[1])
        except Exception as exc:  # noqa: BLE001
            said.append(type(exc).__name__)
    check(said == ["small"] * 4, f"a footprint of no, one, two or repeated points is 'small' ({said})")


def check_car_park_stalls(check) -> None:
    """Walking only the part of a car park that is on the map tries the same stalls."""
    import random as _random

    from knoxbuild.build import CAR_PARK_LANE, STALL_H, STALL_W, car_park_stalls

    def original(bounds, w, h):
        x0, y0, x1, y1 = bounds
        across = (x1 - x0) >= (y1 - y0)
        sw, sh = (STALL_W, STALL_H) if across else (STALL_H, STALL_W)
        for a in range(0, (y1 - y0 if across else x1 - x0), CAR_PARK_LANE):
            for row in (0, STALL_H):
                for b in range(0, (x1 - x0 if across else y1 - y0), STALL_W):
                    x, y = (x0 + b, y0 + a + row) if across else (x0 + a + row, y0 + b)
                    if not (0 <= x and x + sw <= w and 0 <= y and y + sh <= h):
                        continue
                    yield x, y, sw, sh

    rng = _random.Random(5)
    differ = 0
    for _ in range(3000):
        w, h = rng.randint(8, 400), rng.randint(8, 400)
        x0, y0 = rng.randint(-300, 450), rng.randint(-300, 450)
        bounds = (x0, y0, x0 + rng.randint(1, 500), y0 + rng.randint(1, 500))
        if list(original(bounds, w, h)) != list(car_park_stalls(bounds, w, h)):
            differ += 1
    check(differ == 0, f"a car park is tried at the same stalls, in the same order, as before ({differ} of 3000 differ)")
    import time as _time
    t0 = _time.time()
    n = sum(1 for _ in car_park_stalls((-10 ** 6, -10 ** 6, 10 ** 6, 10 ** 6), 300, 300))
    check(_time.time() - t0 < 2 and n > 0,
          f"and one the size of a continent is walked in no time ({_time.time() - t0:.2f} s)")


def check_prop_lattice(check) -> None:
    """Props are laid on the part of a polygon that is on the map, on the same lattice."""
    import random as _random
    import time as _time

    from knoxbuild.props import lattice_on_map

    rng = _random.Random(9)
    differ = 0
    for _ in range(5000):
        step = rng.randint(1, 40)
        first = rng.randint(-900, 600)
        stop = first + rng.randint(0, 1200)
        limit = rng.randint(1, 700)
        naive = [v for v in range(first, stop, step) if 0 <= v < limit]
        if list(lattice_on_map(first, stop, step, limit)) != naive:
            differ += 1
    check(differ == 0, f"the lattice of a polygon is walked only where it is on the map, "
                       f"at the same points ({differ} of 5000 differ)")
    t0 = _time.time()
    n = len(lattice_on_map(-10 ** 9, 10 ** 9, 3, 500))
    check(_time.time() - t0 < 1 and n == len(range((-10 ** 9) % 3, 500, 3)),
          f"and a polygon a thousand kilometres across costs nothing ({n} points)")


def check_ground_shares(check, work: str) -> None:
    """The street and water shares of the ground come out as they did, read a strip at a time."""
    import numpy as np

    from generator import pz_colors as _C
    from knoxbuild import bitmaps, population

    rng = np.random.default_rng(3)
    palette = np.array([_C.WATER, _C.MEDIUM_ASPHALT, _C.PALE_CONCRETE, _C.DARK_GRASS,
                        _C.PAVING, _C.DARK_POTHOLE], dtype=np.uint8)
    chunk = population.CHUNK
    gw, gh = 9, 7
    ground = palette[rng.integers(0, len(palette), (gh * chunk + 3, gw * chunk + 5))]
    path = os.path.join(work, "ground_shares.bmp")
    Image.fromarray(ground).save(path, format="BMP")

    def whole(path: str):
        """The way it was done: the whole picture converted, then cut."""
        paved = np.zeros((gh, gw))
        water = np.zeros((gh, gw))
        with Image.open(path) as img:
            full = np.asarray(img.convert("RGB"))
        for y in range(gh):
            for x in range(gw):
                cell = full[y * chunk:(y + 1) * chunk, x * chunk:(x + 1) * chunk]
                paved[y, x] = np.logical_or.reduce(
                    [np.all(cell == c, axis=2) for c in population.STREET_COLOURS]).mean()
                water[y, x] = np.all(cell == np.array(_C.WATER), axis=2).mean()
        return paved, water

    was = population.GROUND_STRIP_CHUNKS
    population.GROUND_STRIP_CHUNKS = 3          # several strips, the last one short
    try:
        got = population._ground_shares(path, gw, gh)
    finally:
        population.GROUND_STRIP_CHUNKS = was
    expected = whole(path)
    check(np.allclose(got[0], expected[0]) and np.allclose(got[1], expected[1]),
          "the share of each chunk that is street or water is the same read a strip at a time")
    rows = bitmaps.read_rgb_rows(path, 10, 40, 50)
    check(np.array_equal(rows, ground[10:40, :50]),
          "and a strip of rows read from a bitmap is those rows of the picture")


def check_street_angle(check) -> None:
    """The angle a map is turned to is the grid on the map, found to a fraction of a degree."""
    from generator import renderer

    south, west, north, east = 40.0, 20.0, 40.02, 20.026
    proj = renderer.Projector.build(south, west, north, east, 1.0)
    ids = iter(range(1, 10 ** 6))

    def street(p0, p1):
        return renderer.OSMFeature(next(ids), "way", {"highway": "residential"},
                                   [proj.to_latlon(*p0), proj.to_latlon(*p1)])

    def clip(p0, p1, x0, y0, x1, y1):
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        t0, t1 = 0.0, 1.0
        for p, q in ((-dx, p0[0] - x0), (dx, x1 - p0[0]), (-dy, p0[1] - y0), (dy, y1 - p0[1])):
            if p == 0:
                if q < 0:
                    return None
            else:
                t = q / p
                t0, t1 = (max(t0, t), t1) if p < 0 else (t0, min(t1, t))
        return None if t0 >= t1 else ((p0[0] + t0 * dx, p0[1] + t0 * dy), (p0[0] + t1 * dx, p0[1] + t1 * dy))

    def grid(angle, x0, y0, x1, y1, spacing=60):
        a = math.radians(angle)
        u, v = (math.cos(a), -math.sin(a)), (math.sin(a), math.cos(a))
        cx, cy, reach = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0)
        out = []
        for k in range(-int(reach / spacing), int(reach / spacing) + 1):
            for d, e in ((u, v), (v, u)):
                o = (cx + e[0] * k * spacing, cy + e[1] * k * spacing)
                seg = clip((o[0] - d[0] * reach, o[1] - d[1] * reach),
                           (o[0] + d[0] * reach, o[1] + d[1] * reach), x0, y0, x1, y1)
                if seg:
                    out.append(street(*seg))
        return out

    def turned(feats):
        return renderer.dominant_road_angle(feats, south, west, north, east)

    w, h = proj.width, proj.height
    errs = []
    for ang in (3, 22.5, 44, -30):
        got, strength = turned(grid(ang, 0, 0, w, h))
        errs.append(abs(got - ang) < 0.5 and strength > 0.9)
    check(all(errs), "a street grid is found to within half a degree, whichever way it runs")
    two, _s = turned(grid(30, 0, 0, w * 0.65, h) + grid(0, w * 0.7, 0, w, h))
    check(abs(two - 30) < 0.5, "and where two districts meet, the one with more street decides")
    inside = grid(20, 0, 0, w, h)
    both, _s = turned(inside + grid(0, -3000, -3000, -50, h + 3000))
    check(abs(both - 20) < 0.5,
          "a bigger grid in the margin beyond the map does not turn the map to its own angle")
    from generator import osm as _osm
    check(len(_osm._points([{"lat": float("nan"), "lon": 20.0}, {"lat": 1.0, "lon": 2.0}])) == 1,
          "and a point with no real coordinates is dropped on the way in")
    check(turned([]) == (0.0, 0.0), "a map with no streets has no angle")


def check_throttle(check) -> None:
    """The compile eases off when WorldEd fails under load, and only so far."""
    import threading
    import time as _time

    from tools.compile_map import Throttle

    t = Throttle(4)
    check(t.limit == 4 and t.ease() == 3, "the compile gives up a slot after a failure")
    check(t.ease() is None and t.limit == 3,
          "a burst of failures from one overload counts once")
    t._eased_at = 0.0
    check(t.ease() == 2, "and again if it still fails a while later")
    one = Throttle(1)
    check(one.ease() is None and one.limit == 1, "but never below one")

    # A slot held by a batch keeps the next one waiting, and the limit it waits
    # under is whatever it is by then.
    t = Throttle(2)
    t.acquire()
    t.acquire()
    got = []
    waiter = threading.Thread(target=lambda: (t.acquire(), got.append(1)), daemon=True)
    waiter.start()
    _time.sleep(0.3)
    check(not got, "a third batch waits while two are running")
    t.release()
    waiter.join(3)
    check(got == [1], "and starts as soon as one ends")


def check_saved_areas(check, work: str) -> None:
    """Saved areas: kept by name, checked on the way in, gone when deleted."""
    import app as knoxapp

    was = knoxapp.PRESETS_FILE
    knoxapp.PRESETS_FILE = Path(work) / "presets_test.json"
    try:
        client = knoxapp.app.test_client()
        body = {"name": "Old town", "south": 40.0, "west": 20.0, "north": 40.01,
                "east": 20.01, "metersPerTile": 2, "shape": None,
                "settings": {"preset": "default", "seed": 7, "tree_density": 0.5}}
        check(client.get("/api/presets").get_json()["presets"] == [],
              "no saved areas to begin with")
        saved = client.post("/api/presets", json=body)
        check(saved.status_code == 200, "an area is saved under a name")
        got = client.get("/api/presets").get_json()["presets"]
        check(len(got) == 1 and got[0]["name"] == "Old town"
              and got[0]["metersPerTile"] == 2 and got[0]["settings"]["seed"] == 7,
              "and comes back with its scale and settings")
        client.post("/api/presets", json={**body, "metersPerTile": 4})
        got = client.get("/api/presets").get_json()["presets"]
        check(len(got) == 1 and got[0]["metersPerTile"] == 4,
              "saving under the same name replaces it")
        poly = {"type": "Polygon", "coordinates": [[[20, 40], [20.01, 40], [20.01, 40.01], [20, 40]]]}
        check(client.post("/api/presets", json={**body, "name": "Shape", "shape": poly})
              .status_code == 200, "an outline can be saved")
        for bad, why in (({**body, "name": " "}, "a blank name"),
                         ({**body, "north": 39.0}, "an area upside down"),
                         ({**body, "south": 95.0, "north": 96.0}, "an area off the map"),
                         ({**body, "shape": {"type": "Point", "coordinates": [1, 2]}},
                          "an outline that is not a polygon"),
                         ({"name": "x"}, "no area at all")):
            if client.post("/api/presets", json=bad).status_code != 400:
                check(False, f"{why} should be refused")
                break
        else:
            check(True, "a blank name, a bad area and a bad outline are refused")
        check(client.delete("/api/presets/Old%20town").status_code == 200
              and [p["name"] for p in client.get("/api/presets").get_json()["presets"]] == ["Shape"],
              "a saved area can be deleted")
        check(client.delete("/api/presets/Old%20town").status_code == 404,
              "and deleting it again says it is not there")
    finally:
        knoxapp.PRESETS_FILE = was


def check_health(check) -> None:
    """The health check answers without the network, and says what the PC holds."""
    import app as knoxapp

    data = knoxapp.app.test_client().get("/api/health").get_json()
    res = data.get("resources", {})
    check(isinstance(data.get("checks"), list) and "compileWorkers" in res
          and res["compileWorkers"] >= 1 and "overpass" not in data,
          "the health check lists the setup and the PC's room, and leaves the network alone by default")


def check_worlded_size(check) -> None:
    """A map WorldEd cannot compile is refused before it is made, and told how to fit."""
    import app as knoxapp
    from tools.compile_map import WORLDED_MAX_PIXELS, bitmap_pixels, scale_that_fits

    box = {"south": 34.84560, "west": -120.76103, "north": 35.18564, "east": -120.38612}
    r = knoxapp.app.test_client().post("/api/generate", json={**box, "metersPerTile": 2})
    said = (r.get_json() or {}).get("error", "")
    check(r.status_code == 400 and "WorldEd cannot compile" in said and "At 3 m a tile" in said,
          f"a 345 million tile map is refused, with the scale that fits ({said[:60]!r})")
    check(bitmap_pixels(13800, 18600) <= WORLDED_MAX_PIXELS < bitmap_pixels(16500, 16500)
          and bitmap_pixels(1, 1) == 300 * 300
          and scale_that_fits(17700, 19500, 2.0) == 3 and scale_that_fits(10 ** 6, 10 ** 6, 100.0) is None,
          "the size limit sits between a map that compiled and one that did not")


def check_other_websites(check) -> None:
    """A page on another website cannot make KnoxMap do things by posting to it."""
    import app as knoxapp

    client = knoxapp.app.test_client()

    def post(**headers):
        # /api/stop with no map name answers 400 and does nothing: a refusal is 403.
        return client.post("/api/stop", json={}, headers=headers).status_code

    check(post() == 400 and post(Origin="http://127.0.0.1:5000") == 400
          and post(Origin="http://localhost:5000") == 400 and post(Origin="http://[::1]:5000") == 400,
          "posts from KnoxMap's own page, and from tools with no Origin, are answered")
    check(post(Origin="http://evil.example") == 403 and post(Origin="null") == 403
          and post(Origin="http://127.0.0.1.evil.example") == 403,
          "posts from other websites are refused")
    check(post(**{"Sec-Fetch-Site": "cross-site"}) == 403
          and client.get("/api/health", headers={"Origin": "http://evil.example"}).status_code == 200,
          "and so is a cross-site post that sends no Origin, while reading stays open")


def check_overpass_setting(check, work: str) -> None:
    """The map data servers can be named in the window and are used at once."""
    from pathlib import Path

    import app as knoxapp
    import knoxpaths
    from generator import osm

    was_path, was_urls = knoxpaths.CONFIG_PATH, list(osm.OVERPASS_ENDPOINTS)
    knoxpaths.CONFIG_PATH = Path(work) / "config_overpass.json"
    try:
        client = knoxapp.app.test_client()
        mine = "http://localhost:12345/api/interpreter"
        r = client.post("/api/overpass", json={"endpoints": f"  {mine}\n{mine} "})
        d = r.get_json()
        check(r.status_code == 200 and d["endpoints"] == [mine] and d["using"] == [mine]
              and osm.OVERPASS_ENDPOINTS == [mine],
              "a server of your own is saved and used at once (duplicates and spaces dropped)")
        check(client.get("/api/overpass").get_json()["endpoints"] == [mine],
              "and read back from the config")
        for bad in ("ftp://x/y", "not a url", {"a": 1}, ["javascript:alert(1)"]):
            check(client.post("/api/overpass", json={"endpoints": bad}).status_code == 400,
                  f"{str(bad)[:24]!r} is refused")
        check(client.post("/api/overpass", json=[1]).get_json()["using"] == osm.OVERPASS_ENDPOINTS
              and osm.OVERPASS_ENDPOINTS == list(osm._DEFAULT_ENDPOINTS),
              "an empty answer goes back to the public servers")
    finally:
        knoxpaths.CONFIG_PATH = was_path
        osm.set_endpoints(was_urls if was_urls != list(osm._DEFAULT_ENDPOINTS) else None)


def check_workshop(check, work: str) -> None:
    """The pre-upload check finds a missing credit, a bad id and a missing picture."""
    import shutil

    from tools import workshop_check as wc

    root = os.path.join(work, "wmod", "My_Map")
    shutil.rmtree(os.path.dirname(root), ignore_errors=True)
    for where in ("", "common", "42"):
        os.makedirs(os.path.join(root, where), exist_ok=True)
        with open(os.path.join(root, where, "mod.info"), "w", encoding="utf-8") as f:
            f.write("name=My Map\nid=My_Map\ndescription=A map. Map data (c) OpenStreetMap contributors (ODbL).\n")
    maps = os.path.join(root, "common", "media", "maps", "My_Map")
    os.makedirs(maps)
    open(os.path.join(maps, "0_0.lotheader"), "wb").close()
    open(os.path.join(maps, "map.info"), "w").close()
    with open(os.path.join(root, "ATTRIBUTION.txt"), "w", encoding="utf-8") as f:
        f.write("Map data (c) OpenStreetMap contributors, available under the Open Database License (ODbL)")

    def levels():
        res = wc.check(root)
        return {r["level"] for r in res}, wc.summary(res)

    lv, s = levels()
    check("bad" not in lv and s["ready"] and s["warn"] == 1,
          "a complete mod is ready, with only the missing preview picture to warn about")
    Image.new("RGB", (300, 300)).save(os.path.join(root, "preview.png"))
    lv, s = levels()
    check(lv == {"ok"} and s["warn"] == 0, "and with a square preview it has nothing to say")
    Image.new("RGB", (300, 200)).save(os.path.join(root, "preview.png"))
    check(levels()[1]["warn"] == 1, "a preview that is not square is warned about")
    with open(os.path.join(root, "preview.png"), "wb") as f:
        f.write(b"not a png")
    check(not levels()[1]["ready"], "a preview that is not a PNG stops it")
    os.remove(os.path.join(root, "preview.png"))
    with open(os.path.join(root, "ATTRIBUTION.txt"), "w", encoding="utf-8") as f:
        f.write("made with KnoxMap")
    check(not levels()[1]["ready"], "an attribution without the OpenStreetMap credit stops it")
    os.remove(os.path.join(root, "ATTRIBUTION.txt"))
    check(not levels()[1]["ready"], "no attribution file stops it")
    with open(os.path.join(root, "mod.info"), "w", encoding="utf-8") as f:
        f.write("name=x\nid=bad id!\ndescription=nothing\n")
    check(not levels()[1]["ready"], "a mod id with odd characters and a copy that differs stop it")
    check(not wc.summary(wc.check(os.path.join(work, "nowhere")))["ready"],
          "a mod that is not installed is not ready")


def check_compile_state(check, work: str) -> None:
    """Working out which cells of a compiled map are out of date."""
    import numpy as np

    from knoxbuild import bitmaps
    from tools import compile_state as cs

    rng = np.random.default_rng(11)
    rgb = rng.integers(0, 256, (130, 205, 3), dtype=np.uint8)
    a_path, b_path = os.path.join(work, "cells_a.bmp"), os.path.join(work, "cells_b.bmp")
    Image.fromarray(rgb).save(a_path, format="BMP")
    changed = rgb.copy()
    changed[75, 160] = 255 - changed[75, 160]            # one pixel, in cell (2, 1)
    Image.fromarray(changed).save(b_path, format="BMP")
    ha, hb = bitmaps.cell_hashes(a_path, 60), bitmaps.cell_hashes(b_path, 60)
    check(len(ha) == 4 * 3 and bitmaps.cell_hashes(a_path, 60) == ha
          and [k for k in ha if ha[k] != hb[k]] == [(2, 1)],
          "one changed pixel changes the fingerprint of its own square and no other")
    grey = rng.integers(0, 256, (70, 90), dtype=np.uint8)
    g_path = os.path.join(work, "cells_g.bmp")
    Image.fromarray(grey, "L").save(g_path, format="BMP")
    check(len(bitmaps.cell_hashes(g_path, 30)) == 3 * 3, "and it reads a grey picture too")
    step3 = bitmaps.read_rgb(a_path, step=3)
    check(np.array_equal(step3, rgb[::3, ::3]), "a smaller picture of a bitmap is every third pixel")

    check(cs.lot_files_of({(0, 0)}, (70, 0)) == {(82, 0), (82, 1), (83, 0), (83, 1)},
          "a cell names the lot files that overlap it")

    def record(terrain_edit=None, content_edit=None) -> dict:
        t = {f"{x},{y}": f"t{x}{y}" for x in range(5) for y in range(5)}
        c = {f"{x},{y}": f"c{x}{y}" for x in range(5) for y in range(5)}
        t.update(terrain_edit or {})
        c.update(content_edit or {})
        return {"version": cs.VERSION, "global": "g", "origin": [70, 0],
                "size": [5, 5], "terrain": t, "content": c}

    base = record()
    check(cs.plan(None, base, True) is None and cs.plan(base, base, False) is None,
          "with no record, or nothing compiled, nothing is trusted")
    check(cs.plan(base, {**base, "global": "other"}, True) is None,
          "and a change to the rules or the compiler redoes everything")
    same = cs.plan(base, record(), True)
    check(same["changed"] == 0 and not same["lots"], "an unchanged map has nothing to redo")
    one = cs.plan(base, record(content_edit={"0,0": "new"}), True)
    check(one["changed"] == 1 and one["lots"] == {(0, 0), (1, 0), (0, 1), (1, 1)}
          and not one["terrain"],
          "a changed building in a corner redoes that cell and its neighbours, not the maps")
    mid = cs.plan(base, record(terrain_edit={"2,2": "new"}), True)
    check(len(mid["terrain"]) == 9 and len(mid["lots"]) == 9,
          "changed ground redoes its map and its neighbours' too")

    project = Path(work) / "statemap"
    (project / "lots").mkdir(parents=True)
    (project / "tmx").mkdir()
    pzw = project / "statemap.pzw"
    cell = '<cell x="{x}" y="{y}" map="C:/m/tmx/statemap_{tx}_{y}.tmx">\n</cell>\n'
    pzw.write_text('<world version="1.0" width="2" height="2">\n'
                   '<worldOrigin origin="70,0"/>\n<bmp path="statemap.bmp" x="0" y="0"/>\n'
                   + "".join(cell.format(x=x, y=y, tx=70 + x)
                             for x in range(2) for y in range(2)) + "</world>",
                   encoding="utf-8")
    for lx in range(82, 86):
        for ly in range(0, 4):
            for name in (f"{lx}_{ly}.lotheader", f"chunkdata_{lx}_{ly}.bin",
                         f"world_{lx}_{ly}.lotpack"):
                (project / "lots" / name).write_text("x")

    def make_maps() -> None:
        for x in range(2):
            for y in range(2):
                (project / "tmx" / f"statemap_{70 + x}_{y}.tmx").write_text("x")

    make_maps()
    # Ground changed somewhere: every map goes, because WorldEd does not make
    # up a partial set (its log said 375 of 384), but only the changed cell's
    # lot files.
    gone = cs.discard(project, {"lots": {(0, 0)}, "terrain": {(0, 0)}}, (70, 0))
    left = pzw.read_text(encoding="utf-8")
    check(gone == {"lots": 12, "tmx": 4}
          and not (project / "lots" / "82_0.lotheader").exists()
          and (project / "lots" / "85_3.lotheader").exists()
          and left.count('map=""') == 4 and ".tmx" not in left
          and not list((project / "tmx").glob("*.tmx")),
          "discarding takes just those cells' lot files, and every map when ground changed")
    make_maps()
    pzw.write_text(left.replace('map=""', 'map="C:/m/tmx/statemap_70_0.tmx"', 1),
                   encoding="utf-8")
    kept = cs.discard(project, {"lots": {(1, 1)}, "terrain": set()}, (70, 0))
    check(kept["tmx"] == 0 and len(list((project / "tmx").glob("*.tmx"))) == 4
          and "statemap_70_0.tmx" in pzw.read_text(encoding="utf-8"),
          "and changes that are not to the ground leave the maps alone")
    for lx in range(82, 86):
        for ly in range(0, 4):
            (project / "lots" / f"{lx}_{ly}.lotheader").write_text("x")
    (project / "lots" / "84_1.lotheader").unlink()
    check(cs.batch_needs_work(project, (1, 1, 1, 1), (70, 0), (2, 2))
          and not cs.batch_needs_work(project, (0, 0, 0, 0), (70, 0), (2, 2)),
          "a batch is run only when a lot file it would write is missing")
    cs.wipe(project)
    check(not any((project / "lots").iterdir()) and not any((project / "tmx").iterdir()),
          "starting from scratch empties lots and maps")


def check_big_bitmaps(check, work: str) -> None:
    """A map past Pillow's 179 Mpx bomb guard still opens, and the strip reader
    gives back exactly what Pillow does, at any width (BMP rows are padded)."""
    import numpy as np

    import generator  # noqa: F401 - lifts the pixel limit
    import knoxbuild  # noqa: F401
    from knoxbuild import bitmaps

    # 20000 x 20000 is 400 Mpx, twice the limit where Pillow stops warning and
    # starts refusing; 1-bit keeps the file at 50 MB.
    big = os.path.join(work, "big.bmp")
    Image.new("1", (20000, 20000)).save(big, format="BMP")
    try:
        with Image.open(big) as img:
            check(img.size == (20000, 20000),
                  "a bitmap past Pillow's decompression-bomb limit still opens")
    except Image.DecompressionBombError:
        check(False, "a bitmap past Pillow's decompression-bomb limit still opens")
    os.remove(big)

    rng = np.random.default_rng(5)
    same = True
    for w, h in ((1, 1), (5, 3), (7, 600), (301, 257)):      # widths off a 4-byte row
        rgb = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        path = os.path.join(work, f"rgb_{w}x{h}.bmp")
        Image.fromarray(rgb).save(path, format="BMP")
        same &= np.array_equal(bitmaps.read_rgb(path), rgb)
        crop = (max(1, h // 2), max(1, w // 2))
        same &= np.array_equal(bitmaps.read_rgb(path, crop=crop), rgb[:crop[0], :crop[1]])
        grey = rng.integers(0, 256, (h, w), dtype=np.uint8)
        gpath = os.path.join(work, f"grey_{w}x{h}.bmp")
        Image.fromarray(grey, "L").save(gpath, format="BMP")
        same &= np.array_equal(bitmaps.read_gray(gpath), grey)
        colour = tuple(int(v) for v in rgb[0, 0])
        same &= np.array_equal(bitmaps.same_colour(rgb, colour),
                               np.all(rgb == colour, axis=2))
    check(bool(same), "the strip reader returns the same pixels as Pillow, "
                      "whole or cropped, in colour and grey")


def check_box_any(check) -> None:
    """The reach test the gardens use works a strip at a time, to keep a town's
    summed-area table out of memory; it must still answer the same."""
    import numpy as np

    from generator.renderer import _box_any
    import generator.renderer as renderer

    def whole_map(mask, radius):
        h, w = mask.shape
        pad = np.pad(mask.astype(np.int32), radius + 1)
        ii = pad.cumsum(0).cumsum(1)
        k = 2 * radius + 1
        return (ii[k:k + h, k:k + w] - ii[0:h, k:k + w]
                - ii[k:k + h, 0:w] + ii[0:h, 0:w]) > 0

    rng = np.random.default_rng(3)
    was = renderer.BOX_STRIP_ROWS
    same = True
    try:
        for shape, radius, strip in (((300, 200), 3, 64), ((97, 61), 0, 7),
                                     ((512, 300), 12, 512), ((200, 200), 1, 3)):
            renderer.BOX_STRIP_ROWS = strip
            mask = rng.random(shape) < 0.02
            same = same and np.array_equal(_box_any(mask, radius), whole_map(mask, radius))
    finally:
        renderer.BOX_STRIP_ROWS = was
    check(same, "the gardens' reach test gives the same answer strip by strip")


def check_mapstate(check, out: str) -> None:
    """What a newer KnoxMap needs redone on an older map, and what it leaves
    alone (knoxbuild/mapstate.py)."""
    import knoxlog
    from knoxbuild import mapstate

    # The map the selftest just made: built, compiled and installed by this
    # version, so there is nothing to redo.
    for stage in mapstate.STAGES:
        mapstate.stamp(out, stage)
    check(mapstate.needs(out) == [] and mapstate.made_with(out) == knoxlog.version(),
          "a map this KnoxMap made needs nothing redone")

    def with_stages(versions: dict) -> list[str]:
        state = {"stages": {k: {"version": v} for k, v in versions.items()}}
        with open(os.path.join(out, mapstate.STATE_FILE), "w", encoding="utf-8") as f:
            json.dump(state, f)
        return mapstate.needs(out)

    # A map older than every step: all four, in order.
    old = {k: "1.0" for k in mapstate.STAGES}
    check(with_stages(old) == list(mapstate.STAGES) and mapstate.made_with(out) == "1.0",
          "a map older than everything is redone from the start")

    # One whose terrain is current but whose buildings are not: build again,
    # and everything after it - but not the terrain.
    current = {k: knoxlog.version() for k in mapstate.STAGES}
    check(with_stages({**current, "build": "1.0", "compile": "1.0", "install": "1.0"})
          == ["build", "compile", "install"],
          "a map with older buildings is built, compiled and installed again")

    # And one that only has to go in again.
    check(with_stages({**current, "install": "1.0"}) == ["install"],
          "a map that only needs installing again is only installed again")

    # A step redone makes what came after it stale.
    mapstate.stamp(out, "build")
    done = mapstate.done(out)
    check("compile" not in done and "install" not in done,
          "building again clears the compile and install it made stale")


def check_straight_roads(check) -> None:
    """Knox County roads: every road in grid or 45-degree runs, roads that met
    still meeting, and the buildings beside them moved with them."""
    from generator.octilinear import straighten_roads
    from generator.renderer import Projector, _is_polygon, classify

    proj = Projector.build(SOUTH, WEST, SOUTH + 0.0054, WEST + 0.0068, 1.0)
    # A long road at 12 degrees, a side street off it at 70, a crescent, and a
    # house beside the first.
    main = way({"highway": "primary"}, [(20, 100), (560, 215)])
    side = way({"highway": "residential"}, [(20, 100), (80, 265), (140, 430)])
    crescent = way({"highway": "residential"},
                   [(300, 400 + 60 * math.sin(t / 10)) for t in range(0, 32)])
    house = way({"building": "house"}, box(300, 170, 312, 180))
    before = proj.to_px(*house.geometry[0])
    feats = [main, side, crescent, house]
    straighten_roads(feats, proj, classify, _is_polygon)

    def runs_ok(f):
        pts = [proj.to_px(*p) for p in f.geometry]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            dx, dy = round(x1 - x0), round(y1 - y0)
            if not (dx == 0 or dy == 0 or abs(dx) == abs(dy)):
                return False
        return True

    check(all(runs_ok(f) for f in (main, side, crescent)),
          "Knox County roads run only along the tiles or on 45-degree diagonals")
    check(main.geometry[0] == side.geometry[0],
          "roads that met still meet once straightened")
    check(len({round(proj.to_px(*p)[1]) for p in main.geometry}) <= 2,
          "a long road at 12 degrees becomes straight, not a staircase")
    after = proj.to_px(*house.geometry[0])
    check(math.dist(before, after) > 0.5, "the houses beside a road move with it")


def check_missing_drive(check) -> None:
    """A Steam library on a drive that is gone (Windows raises for it rather
    than saying it is not there) is skipped, not a crash in Setup."""
    import knoxpaths

    class Gone(type(Path())):
        def stat(self, *a, **k):
            raise OSError(433, "A device which does not exist was specified", str(self))

    gone = Gone("F:/SteamLibrary")
    check(not knoxpaths._is_dir(gone / "steamapps") and not knoxpaths._exists(gone),
          "a Steam library on a missing drive is skipped")

    # A drive or folder the player names finds the library in it or above it.
    import tempfile
    with tempfile.TemporaryDirectory() as drive:
        lib = Path(drive) / "SteamLibrary"
        game = lib / "steamapps" / "common" / "ProjectZomboid"
        game.mkdir(parents=True)
        check(knoxpaths.library_of(drive) == [lib] and knoxpaths.library_of(game) == [lib]
              and knoxpaths.library_of(Path(drive) / "nothing") == [],
              "a chosen drive or folder finds its Steam library")
        old = os.environ.get("KNOXMAP_STEAM_FOLDERS")
        os.environ["KNOXMAP_STEAM_FOLDERS"] = drive
        try:
            found = knoxpaths.steam_libraries_found()
            check(found and found[0]["path"] == str(lib) and found[0]["chosen"],
                  "a chosen Steam library is looked in first")
        finally:
            if old is None:
                os.environ.pop("KNOXMAP_STEAM_FOLDERS")
            else:
                os.environ["KNOXMAP_STEAM_FOLDERS"] = old


def check_updater(check, work: str) -> None:
    """An update applied to a pretend install: new and changed files go in,
    dropped files go, and maps, logs and the Python environment are left alone."""
    import zipfile

    import updater

    base = Path(work) / "install"
    (base / "output" / "mytown").mkdir(parents=True)
    (base / "output" / "mytown" / "mytown.bmp").write_text("map")
    (base / ".venv").mkdir()
    (base / ".venv" / "keep.txt").write_text("env")
    (base / "knoxmap.py").write_text("old")
    (base / "dropped.py").write_text("gone in the new version")
    (base / "requirements.txt").write_text("flask")
    (base / "knoxmap_setup.py").write_text("setup")
    (base / updater.MANIFEST.name).write_text(json.dumps(
        {"version": "1.0", "files": ["knoxmap.py", "dropped.py", "requirements.txt",
                                     "knoxmap_setup.py"]}))
    update_dir = base / "update"
    update_dir.mkdir()
    zip_path = update_dir / "KnoxMap-v9.9.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("KnoxMap/knoxmap.py", "new")
        z.writestr("KnoxMap/requirements.txt", "flask")
        z.writestr("KnoxMap/knoxmap_setup.py", "setup")
        z.writestr("KnoxMap/added/module.py", "added")
        z.writestr("KnoxMap/output/mytown/mytown.bmp", "a release must not overwrite maps")
        z.writestr("KnoxMap/../escape.txt", "outside the folder")
    saved = {k: getattr(updater, k) for k in ("BASE_DIR", "UPDATE_DIR", "STAGED", "MANIFEST",
                                              "ASIDE_DIR", "FILE_TRIES", "FILE_GAP_S",
                                              "current_version", "enabled")}
    try:
        updater.BASE_DIR, updater.UPDATE_DIR = base, update_dir
        updater.STAGED, updater.MANIFEST = update_dir / "staged.json", base / saved["MANIFEST"].name
        updater.ASIDE_DIR = update_dir / "replaced"
        updater.FILE_TRIES, updater.FILE_GAP_S = 2, 0.01
        updater.current_version = lambda: "1.0"
        updater.enabled = lambda: True
        updater.STAGED.write_text(json.dumps({"version": "9.9", "zip": str(zip_path)}))
        applied = updater.apply_staged()
        check(applied and (base / "knoxmap.py").read_text() == "new"
              and (base / "added" / "module.py").exists() and not (base / "dropped.py").exists(),
              "an update puts in the new files and takes out the dropped ones")
        check((base / "output" / "mytown" / "mytown.bmp").read_text() == "map"
              and (base / ".venv" / "keep.txt").exists()
              and not (Path(work) / "escape.txt").exists(),
              "an update leaves maps and the Python environment alone and stays in its folder")
        check(not updater.STAGED.exists() and not zip_path.exists() and not updater.apply_staged(),
              "an update is applied once")
        # An older version goes in only when it was chosen in the version menu.
        old_zip = update_dir / "KnoxMap-v0.5.zip"
        with zipfile.ZipFile(old_zip, "w") as z:
            z.writestr("KnoxMap/knoxmap.py", "old release")
        updater.STAGED.write_text(json.dumps({"version": "0.5", "zip": str(old_zip)}))
        check(not updater.apply_staged() and (base / "knoxmap.py").read_text() == "new",
              "an automatic update never goes back to an older version")
        updater.STAGED.write_text(json.dumps({"version": "0.5", "zip": str(old_zip), "chosen": True}))
        updater.enabled = lambda: False       # choosing an older one turns them off
        check(updater.apply_staged() and (base / "knoxmap.py").read_text() == "old release",
              "a version chosen in the menu goes in, older ones too")
        check(updater.is_newer("1.10", "1.9") and not updater.is_newer("1.2", "1.2.0")
              and updater.is_newer("1.2.1", "1.2"), "versions compare as numbers")

        # One file that will not go in must not lose the whole update. Windows
        # refuses to overwrite a file another program has open - a virus
        # scanner reading KnoxMap.exe was enough - and the run used to stop
        # there with half the release in place, CHANGELOG.md among it, so
        # KnoxMap read as the new version and never looked again.
        updater.enabled = lambda: True
        (base / updater.VERSION_FILE).write_text("## 1.0\n")
        # A folder where the release has a file cannot be overwritten on any
        # system, which is the same dead end: the old one is moved aside.
        stuck = base / "stuck"
        stuck.mkdir()
        (stuck / "in the way").write_text("not something a file can replace")
        aside_zip = update_dir / "KnoxMap-v9.9.zip"
        with zipfile.ZipFile(aside_zip, "w") as z:
            z.writestr(f"KnoxMap/{updater.VERSION_FILE}", "## 9.9\n")
            z.writestr("KnoxMap/stuck", "a file where the install has a folder")
        updater.STAGED.write_text(json.dumps({"version": "9.9", "zip": str(aside_zip)}))
        check(updater.apply_staged() and (base / "stuck").is_file()
              and (updater.ASIDE_DIR / "stuck" / "in the way").exists(),
              "a file that will not be overwritten is moved aside and the update goes in")

        # And when it cannot even be moved: the version stays as it was and
        # the download waits for the next start rather than being thrown away.
        (base / updater.VERSION_FILE).write_text("## 1.0\n")
        (base / "locked").write_text("a file where the release has a folder")
        half_zip = update_dir / "KnoxMap-v9.9b.zip"
        with zipfile.ZipFile(half_zip, "w") as z:
            z.writestr(f"KnoxMap/{updater.VERSION_FILE}", "## 9.9\n")
            z.writestr("KnoxMap/locked/module.py", "cannot be unpacked over a file")
        updater.STAGED.write_text(json.dumps({"version": "9.9", "zip": str(half_zip)}))
        blocked = updater.apply_staged()
        left = json.loads(updater.STAGED.read_text()) if updater.STAGED.exists() else {}
        check(not blocked and (base / updater.VERSION_FILE).read_text().startswith("## 1.0")
              and left.get("tries") == 1 and half_zip.exists(),
              "an update that will not go in keeps the version it had and stays staged")
        (base / "locked").unlink()
        check(updater.apply_staged()
              and (base / "locked" / "module.py").exists()
              and (base / updater.VERSION_FILE).read_text().startswith("## 9.9"),
              "and the next start puts that update in")

        # A failure part way through moving files in: whatever was already
        # replaced goes back, so the install is not left half old and half new.
        for name in ("one.py", "two.py", "three.py"):
            (base / name).write_text(f"old {name}")
        (base / updater.VERSION_FILE).write_text("## 1.0\n")
        updater.MANIFEST.write_text(json.dumps({"version": "1.0", "files": []}))
        mid_zip = update_dir / "KnoxMap-v9.9c.zip"
        with zipfile.ZipFile(mid_zip, "w") as z:
            for name in ("one.py", "two.py", "three.py", "four.py"):
                z.writestr(f"KnoxMap/{name}", f"new {name}")
            z.writestr(f"KnoxMap/{updater.VERSION_FILE}", "## 9.9\n")
        updater.STAGED.write_text(json.dumps({"version": "9.9", "zip": str(mid_zip)}))
        real_put = updater._put_in_place
        calls = [0]

        def breaks_on_third(src, dest, rel, budget):
            calls[0] += 1
            if calls[0] == 3:
                raise OSError("a scanner has this one open")
            return real_put(src, dest, rel, budget)

        updater._put_in_place = breaks_on_third
        try:
            failed = not updater.apply_staged()
        finally:
            updater._put_in_place = real_put
        check(failed
              and all((base / n).read_text() == f"old {n}" for n in ("one.py", "two.py", "three.py"))
              and not (base / "four.py").exists()
              and (base / updater.VERSION_FILE).read_text().startswith("## 1.0")
              and mid_zip.exists(),
              "an update that fails part way through puts back the files it had replaced")
    finally:
        for k, v in saved.items():
            setattr(updater, k, v)


def main(argv: list[str]) -> int:
    # The compile checks drive a stand-in for WorldEd; they are about WorldEd's failures.
    os.environ["KNOXMAP_BACKEND"] = "worlded"
    keep = "--keep" in argv
    check = Checks()
    work = tempfile.mkdtemp(prefix="knoxmap-selftest-")
    os.environ["KNOXMAP_LOG_DIR"] = os.path.join(work, "logs")
    try:
        from generator import renderer
        from knoxbuild.build import build
        from knoxbuild.settings import Settings

        feats = town()
        angle, strength = renderer.dominant_road_angle(feats, SOUTH, WEST, NORTH, EAST)
        print(f"street grid: {angle:.1f} degrees, strength {strength:.2f}")
        check(abs(abs(angle) - 30) < 2 and strength > 0.8, "finds the 30-degree street grid")

        out = os.path.join(work, "selftest")
        print("terrain")
        renderer.render(feats, SOUTH, WEST, NORTH, EAST, meters_per_tile=1.0,
                        output_dir=out, map_name="selftest", rotation=-angle)
        ground = Image.open(os.path.join(out, "selftest.bmp")).convert("RGB")
        colours = {}
        for c in ground.get_flattened_data() if hasattr(ground, "get_flattened_data") else ground.getdata():
            colours[c] = colours.get(c, 0) + 1
        total = ground.width * ground.height
        check(colours.get(C.WATER, 0) / total > 0.03, "sea, river and lake are water")
        check(colours.get(C.MEDIUM_ASPHALT, 0) > 0 and colours.get(C.DARKEST_ASPHALT, 0) > 0,
              "streets and the main road are tarmac")
        check(colours.get(C.PALE_CONCRETE, 0) > 0, "streets have pavements")
        print("bridges and monuments")
        import json as _json
        from generator import structures
        raised = _json.load(open(os.path.join(out, "selftest_structures.json"), encoding="utf-8"))
        tiles = raised["tiles"]
        check(any(t[3] == "Floor" and t[4].startswith("ramps_01") and t[2] == 0 for t in tiles)
              and any(t[3] == "Floor" and t[2] == 1 for t in tiles),
              "the flyover climbs on ramps to a deck a storey up")
        proj = renderer.Projector.build(SOUTH, WEST, NORTH, EAST, 1.0, -angle)
        ax, ay = proj.to_px(*_ll(510, 400))
        under = {ground.getpixel((int(ax) + dx, int(ay) + dy)) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        check(C.DARKEST_ASPHALT not in under,
              "the avenue runs on under the flyover instead of meeting it")
        bx, by = proj.to_px(*_ll(556, 455))
        cx, _ = proj.to_px(*_ll(567, 455))

        def tarmac_rows(x):
            return [y for y in range(int(by) - 15, int(by) + 15)
                    if ground.getpixel((int(x), y)) == C.MEDIUM_ASPHALT]
        check(tarmac_rows(bx) and tarmac_rows(bx) == tarmac_rows(cx),
              "the bridge over the river is laid square")
        names = open(os.path.join(out, "selftest_buildings.geojson"), encoding="utf-8").read()
        check(any("cemetary_01" in t[4] for t in tiles) and "Selftest Arch" not in names
              and any(t[4] == "ramps_01_19" and t[2] >= 2 for t in tiles),
              "a statue stands in the park and the arch is an arch, not a house")
        # A tower is legs with a tank on top, and never a floor plan. Counted
        # around the tower itself: every structure on the map is in this list
        # and the arch's span would pass a count taken over all of them.
        tx, ty = proj.to_px(*_ll(396, 424))
        by_level: dict = {}
        for x, y, z, layer, tile in tiles:
            if layer == "Floor" and abs(x - tx) < 15 and abs(y - ty) < 15:
                by_level.setdefault(z, set()).add((x, y))
        top = max(by_level) if by_level else 0
        check(top >= 4 and len(by_level.get(top, ())) > len(by_level.get(top - 2, set()))
              and "Selftest Water Tower" not in names,
              f"the water tower is a tank on legs, not a house ({top + 1} storeys, "
              f"{len(by_level.get(top, ()))} tiles on top over {len(by_level.get(0, ()))})")
        veg = Image.open(os.path.join(out, "selftest_veg.bmp")).convert("RGB")
        pixels = veg.get_flattened_data() if hasattr(veg, "get_flattened_data") else veg.getdata()
        kerbs = sum(1 for c in pixels if c[0] == 12 and c[1] == 34)
        check(kerbs > 100, f"kerbs laid ({kerbs})")
        trees = sum(1 for c in pixels if c == C.TREES)
        shrubs = sum(1 for c in pixels if c == C.BUSHES)
        check(trees > 20 and shrubs > 20, f"gardens planted ({trees} trees, {shrubs} shrubs)")

        print("buildings")
        said: list = []
        with contextlib.redirect_stdout(io.StringIO()) as log:
            build(out, settings=Settings(seed=1),
                  progress=lambda text, fraction: said.append((text, fraction)))
        from knoxbuild import layout_preview
        for layer in layout_preview.LAYERS:
            png = layout_preview.render_to(out, layer)
            with Image.open(png) as shown:
                check(shown.size[0] > 100 and shown.size[1] > 100,
                      f"the layout preview ({layer}) is drawn ({shown.size[0]}x{shown.size[1]})")
        fractions = [f for _t, f in said if f is not None]
        check(len(said) >= 5 and fractions == sorted(fractions) and fractions[-1] >= 0.9,
              f"the building step reports its stages, in order ({len(said)} reports)")
        rows = open(os.path.join(out, "selftest_placements.csv"), encoding="utf-8").read().splitlines()
        check(len(rows) - 1 >= 60, f"buildings placed ({len(rows) - 1})")
        # Building again reuses what is unchanged, and what it lays out afresh
        # comes out the same: the cache is only worth having if it cannot
        # change the map.
        bdir = os.path.join(out, "buildings")

        def tbx_bytes() -> dict:
            return {n: open(os.path.join(bdir, n), "rb").read()
                    for n in sorted(os.listdir(bdir)) if n.endswith(".tbx")}

        first_tbx = tbx_bytes()
        with contextlib.redirect_stdout(io.StringIO()) as again:
            build(out, settings=Settings(seed=1))
        check("reused" in again.getvalue() and tbx_bytes() == first_tbx,
              "building again reuses every building and changes nothing")
        gone = sorted(n for n in first_tbx if n.startswith("selftest_0"))[:3]
        for n in gone:
            os.remove(os.path.join(bdir, n))
        with contextlib.redirect_stdout(io.StringIO()):
            build(out, settings=Settings(seed=1))
        check(tbx_bytes() == first_tbx,
              f"a building laid out again comes out as it did ({len(gone)} deleted)")
        with contextlib.redirect_stdout(io.StringIO()) as other:
            build(out, settings=Settings(seed=2))
        check("reused" not in other.getvalue(),
              "a different seed reuses nothing")
        with contextlib.redirect_stdout(io.StringIO()):
            build(out, settings=Settings(seed=1))
        pzw_text = open(os.path.join(out, "selftest.pzw"), encoding="utf-8").read()
        size = re.search(r'<world version="[^"]*" width="(\d+)" height="(\d+)"', pzw_text)
        cells = [(int(a), int(b)) for a, b in re.findall(r'<cell x="(\d+)" y="(\d+)"', pzw_text)]
        check(size and all(x < int(size.group(1)) and y < int(size.group(2)) for x, y in cells),
              "every cell in the WorldEd project is inside the world")
        check_lots_apart(check, out)
        check_procedural(check, work)
        check_qt_env(check)
        check_rpath(check)
        check_facing(check)
        check_compile_failures(check, work)
        check_wall_corners(check)
        check_overture(check, work)
        check_standing(check)
        check_kitchen_fit(check)
        check_wall_styles(check)
        check_squares(check)
        check_house_plan(check)
        check_porch_lights(check, out)
        check_repair(check, out)
        from knoxbuild.world import Placement, Zone, render_pzw
        edge = render_pzw(2, 2, "m.bmp", [Placement("a.tbx", 10, 599, 3, 3),
                                          Placement("b.tbx", 10, 600, 3, 3)], "m",
                          zones=[Zone("TownZone", 5, 650, 4, 4)])
        check(set(re.findall(r'<cell x="(\d+)" y="(\d+)"', edge)) ==
              {("0", "0"), ("0", "1"), ("1", "0"), ("1", "1")} and edge.count("<lot ") == 1,
              "a lot or zone past the map's edge never names a cell outside the world")
        tbx = [os.path.join(out, "buildings", f) for f in os.listdir(os.path.join(out, "buildings"))]
        import validate_tbx
        bad = [p for p in tbx if validate_tbx.check(p)]
        check(not bad, f"every building passes the editor's rules ({len(tbx)} files)")
        tall = [p for p in tbx if "fixtures_escalators_01_49" in open(p, encoding="utf-8").read()]
        check(len(tall) >= 1, "the seven-storey flats have a lift")
        school = [p for p in tbx if 'InternalName="classroom"' in open(p, encoding="utf-8").read()]
        pumps = [p for p in tbx if os.path.basename(p).startswith("selftest_pumps_")]
        check(pumps and any("_01_14" in open(p, encoding="utf-8").read() or
                            "_01_12" in open(p, encoding="utf-8").read() for p in pumps)
              and any("selftest_pumps_" in line for line in pzw_text.splitlines()),
              "the petrol station has pumps")
        stalls = len(re.findall(r'group="ParkingStall"', pzw_text))
        check(stalls >= 40, f"car parks and drives have parking stalls ({stalls})")
        check(len(school) >= 1, "the school has classrooms")
        check_1_3_6(check, out, tbx, pzw_text, log.getvalue())
        check_street_zombies(check)
        check_dwellings(check)
        check_split_large(check)
        check_mapped_rooms(check)
        check_giant_outline(check, work)
        check_stop(check)
        check_portable(check)
        texts = [open(p, encoding="utf-8").read() for p in tbx]
        windows = {m for t in texts for m in re.findall(r'category="windows">\s*<tile enum="West" tile="(\w+)"', t)}
        check(len(windows) >= 3, f"window styles vary ({len(windows)})")

        def gaps_match(t: str) -> bool:
            blocks = re.findall(r"<tile_entry[^>]*>(.*?)</tile_entry>", t, re.S)
            head = re.search(r"<building[^>]*>", t).group(0)
            ext = int(re.search(r'ExteriorWall="(\d+)"', head).group(1))
            cap = int(re.search(r'RoofCap="(\d+)"', head).group(1))
            west = re.search(r'enum="West" tile="(\w+)"', blocks[ext - 1])
            gap = re.search(r'enum="CapGapE3" tile="(\w+)"', blocks[cap - 1])
            return bool(west and gap and west.group(1) == gap.group(1))
        # The buildings, by their numbered names. Everything else in the
        # folder - fences, structures, pumps, props, porch lights - is loose
        # tiles with no rooms and none of a building's tile entries, and the
        # list of those to leave out kept going stale as kinds were added.
        houses_tbx = [t for p, t in zip(tbx, texts)
                      if re.search(r"_\d{4}(_\d{2})?\.tbx$", os.path.basename(p))]
        check(all(gaps_match(t) for t in houses_tbx), "flat roofs wall in the top floor with its own material")
        check(any("_fences_" in p for p in tbx), "back yards are fenced")
        yard = Image.open(os.path.join(out, "selftest.bmp")).convert("RGB")
        stone = sum(1 for c in (yard.get_flattened_data() if hasattr(yard, "get_flattened_data") else yard.getdata())
                    if c == C.PAVING_STONE)
        check(stone > 50, f"front paths laid ({stone} stone tiles)")
        check(any('RoofType="Peak' in t for t in texts), "houses have pitched roofs")
        check(any('InternalName="pizzakitchen"' in t and 'InternalName="restaurantdining"' in t
                  for t in texts), "the pizza place has a dining room and a pizza kitchen")
        check(any('InternalName="grocery"' in t and "location_shop_generic_01_015" in t for t in texts),
              "the supermarket has aisles of shelving")
        check(not any("fixtures_bathroom_01_026" in t and 'InternalName="grocery"' in t for t in texts),
              "no bath in a shop")
        from knoxbuild.layout import _erika_ready
        if _erika_ready():
            # The town has no shops; lay one out on a street to the south.
            from knoxbuild.layout import build_building
            from knoxbuild import catalog as KC
            from knoxbuild.tbx import render_tbx
            shop_path = os.path.join(out, "buildings", "selftest_shop.tbx")
            shop = render_tbx(build_building(18, 12, levels=2, commercial=True, kind="shop",
                                             seed=3, street="S"),
                              "selftest_shop", KC.SPECIAL_STYLES["shop"])
            open(shop_path, "w", encoding="utf-8").write(shop)
            check('type="wall"' in shop and "walls_commercial_erika" in shop,
                  "a shop gets Erika's glass shop front")
            check('<tiles layer="WallFurniture">' in shop, "a sign hangs over it")
            check(not validate_tbx.check(shop_path), "and still passes the editor's rules")
            speed = sum(1 for c in pixels if c in C.SPEED_SIGNS.values())
            check(speed > 0, f"speed limit signs on the streets ({speed})")
        else:
            check(not any("_erika_" in t for t in texts), "no mod tiles without Erika's Tiles")

        # A window is a frame and glass with nothing behind it: the hole is a
        # tile of the wall's own, one per window style. A wall entry that
        # names only the first leaves every other window with no wall at all.
        from knoxbuild import catalog as KC2
        walls = []

        def _walls(node):
            if isinstance(node, dict):
                if str(node.get("category", "")).endswith("_walls"):
                    walls.append(node)
                for v in node.values():
                    _walls(v)
            elif isinstance(node, (list, tuple)):
                for v in node:
                    _walls(v)

        _walls([KC2.TILE_ENTRIES, KC2.HOUSE_STYLES, KC2.SPECIAL_STYLES,
                getattr(KC2, "SPECIAL_STYLE_VARIANTS", {}),
                getattr(KC2, "ERIKA_STOREFRONTS", [])])
        holes = [next(iter(w["tiles"].values()), "?") for w in walls
                 if "WestWindow1" not in w["tiles"] or "NorthWindow1" not in w["tiles"]]
        check(walls and not holes,
              f"every wall has a cut-out for every window style ({len(walls)} walls"
              + (f", {len(holes)} without: {holes[:3]}" if holes else "") + ")")

        print("pictures")
        # Drawing needs compiled cells, which need WorldEd, which is not here.
        # What can be checked is everything around that: the framing, the
        # scale it picks, and that it says so rather than drawing nothing.
        from knoxbuild import picture as pictures
        import json as _json
        info = _json.loads(Path(out, "selftest_info.json").read_text(encoding="utf-8"))
        check(pictures.map_size(out) == (info["width_tiles"], info["height_tiles"]),
              "a picture knows how big the map is")
        check(not pictures.compiled(out), "and that this one is not compiled yet")
        try:
            pictures.picture(out)
            asked = False
        except FileNotFoundError as exc:
            asked = "Compile" in str(exc)
        check(asked, "so it asks for a compile instead of drawing nothing")
        # The scale has to fall as the area grows, and never ask for a canvas
        # bigger than the budget - a town at 1x is gigabytes.
        scales = [pictures._scale_for(n, n, (1920, 1080)) for n in (40, 120, 320, 1200, 6000)]
        check(scales == sorted(scales, reverse=True) and scales[0] <= 1.0
              and scales[-1] >= pictures.MIN_SCALE,
              f"the scale comes down as the area grows ({scales})")
        biggest, shrunk = 0, None
        for n in (40, 120, 320, 1200, 6000, 20000):
            scale = pictures._scale_for(n, n, (1920, 1080))
            _x, _y, w, h = pictures._within_budget(0, 0, n, n, scale)
            if (w, h) != (n, n):
                shrunk = n
            biggest = max(biggest, pictures._pixels(w, h, scale))
        check(biggest <= pictures.MAX_PIXELS,
              f"and never asks for a canvas over the budget ({biggest / 1e6:.0f}M pixels)")
        check(shrunk is not None,
              "a map too big to draw at once is drawn from the middle out")
        # An isometric view is a diamond, so the corners are empty and get cut
        # off; what is left is centred, and never blown up past its own size.
        from PIL import Image as _Image
        diamond = _Image.new("RGBA", (400, 200), (0, 0, 0, 0))
        diamond.paste(_Image.new("RGBA", (100, 50), (255, 0, 0, 255)), (150, 75))
        framed = pictures._on_background(pictures._trim(diamond), (640, 360))
        check(framed.size == (640, 360) and framed.getpixel((0, 0)) == pictures.BACKGROUND
              and framed.getpixel((320, 180)) == (255, 0, 0),
              "the empty corners are cropped and the rest is centred")
        print("compile")
        from compile_map import clear_stale
        stale = os.path.join(out, "lots")
        os.makedirs(stale, exist_ok=True)
        old_lot = os.path.join(stale, "0_0.lotheader")
        open(old_lot, "wb").write(b"old")
        os.utime(old_lot, (1, 1))
        clear_stale(Path(out))
        check(not os.path.exists(old_lot), "a rebuilt map's old lots are cleared")
        open(old_lot, "wb").write(b"new")
        clear_stale(Path(out))
        check(os.path.exists(old_lot), "lots newer than the map are kept, so compiles resume")
        os.remove(old_lot)

        print("paper map")
        root = ET.parse(os.path.join(out, "worldmap.xml")).getroot()
        props = {p.get("value") for p in root.iter("property")}
        check("Residential" in props and "CommunityServices" in props,
              "buildings on the paper map, by kind")
        ET.parse(os.path.join(out, "streets.xml"))
        notes = open(os.path.join(out, "worldmap-annotations.lua"), encoding="utf-8").read()
        check("OpenStreetMap contributors" in notes, "OpenStreetMap credit on the in-game map")
        check("Selftest School" in notes or "Selftest Church" in notes, "landmarks labelled")

        print("spawn map")
        pop = json.load(open(os.path.join(out, "selftest_population.json"), encoding="utf-8"))
        check(pop.get("residents", 0) > 0, f"people counted ({pop.get('residents')} residents)")

        print("app page")

        import app as knoxmap_app
        client = knoxmap_app.app.test_client()
        page = client.get("/")
        assets = re.findall(r'(?:href|src)="(/static/[^"]+)"', page.get_data(as_text=True))
        missing = [a for a in assets if client.get(a).status_code != 200]
        check(page.status_code == 200 and len(assets) >= 8 and not missing,
              f"page and all {len(assets)} of its files are served" + (f" - missing {missing}" if missing else ""))
        # Scripts, images and stylesheets only; a plain <a> link loads nothing.
        import knoxlog as _kl
        check(f"v{_kl.version()}" in page.get_data(as_text=True) and _kl.version() != "unknown",
              f"the window shows the version ({_kl.version()})")

        # In the app window a download link does nothing - there is no browser
        # to put a file anywhere - so the page is told, and saves through the
        # server instead. See /api/save.
        was_window = os.environ.get("KNOXMAP_WINDOW")
        os.environ["KNOXMAP_WINDOW"] = "1"
        try:
            in_window = client.get("/").get_data(as_text=True)
        finally:
            if was_window is None:
                os.environ.pop("KNOXMAP_WINDOW")
            else:
                os.environ["KNOXMAP_WINDOW"] = was_window
        check('data-in-window="1"' in in_window
              and 'data-in-window="0"' in page.get_data(as_text=True),
              "the page knows whether it is in the app window or a browser")

        # The window in another language: lang/<language>.txt, translated by
        # whoever wants it, with no code to change (tools/make_lang_template.py).
        lang_dir = Path(work) / "lang"
        lang_dir.mkdir(exist_ok=True)
        (lang_dir / "english.txt").write_text(
            "# template\nGenerate map = Generate map\n", encoding="utf-8")
        (lang_dir / "testish.txt").write_text(
            "# a translation\n"
            "Generate map = Haritayi olustur\n"
            "1. Area = 1. Bolge\n"
            "Map name = Map name\n"            # left in English: not translated
            "a line with no separator\n",
            encoding="utf-8")
        was_lang = knoxmap_app.LANG_DIR
        knoxmap_app.LANG_DIR = lang_dir
        try:
            listed = client.get("/api/languages").get_json()
            words = client.get("/api/language/testish").get_json()
            missing = client.get("/api/language/klingon")
        finally:
            knoxmap_app.LANG_DIR = was_lang
        names = [x["name"] for x in listed["languages"]]
        check(names == ["English", "Testish"]
              and words["strings"] == {"Generate map": "Haritayi olustur", "1. Area": "1. Bolge"}
              and missing.status_code == 404,
              "a language file in lang/ is offered and read")

        import zipfile as _zip

        revealed = []
        was_open = _kl.open_folder
        was_output = knoxmap_app.OUTPUT_DIR
        _kl.open_folder = lambda p=None: revealed.append(str(p)) or True
        knoxmap_app.OUTPUT_DIR = Path(out).parent      # where this map really is
        try:
            saved = client.post("/api/save", json={"mapName": "selftest", "name": "zip"}).get_json()
            one = client.post("/api/save", json={"mapName": "selftest",
                                                 "name": "selftest_preview.png"}).get_json()
            escape = client.post("/api/save", json={"mapName": "selftest",
                                                    "name": "../../secrets.txt"})
        finally:
            _kl.open_folder = was_open
            knoxmap_app.OUTPUT_DIR = was_output
        zip_path = Path(out) / "selftest.zip"
        check(saved and zip_path.exists() and _zip.ZipFile(zip_path).namelist()
              and one and one.get("name") == "selftest_preview.png"
              and escape.status_code == 400 and len(revealed) == 2,
              "saving a map's files writes them and shows them in Explorer")
        check(not re.search(r'(?:src="|<link[^>]*href=")https?://', page.get_data(as_text=True)),
              "page loads nothing from other sites")

        print("updates")
        check_updater(check, work)
        check_missing_drive(check)
        check_straight_roads(check)
        check_mapstate(check, out)
        check_no_size_wall(check, work)
        check_overpass_retry(check)
        check_overpass_blank(check)
        check_flat_selection(check)
        check_memory_guard(check)
        check_box_any(check)
        check_big_bitmaps(check, work)
        check_repeatable_seeds(check)
        check_throttle(check)
        check_osm_parse_tolerant(check)
        check_osm_cache(check, work)
        check_config_file(check, work)
        check_install_clears(check, work)
        check_odd_tags(check)
        check_degenerate_footprints(check)
        check_car_park_stalls(check)
        check_prop_lattice(check)
        check_ground_shares(check, work)
        check_street_angle(check)
        check_odd_requests(check, work)
        check_saved_areas(check, work)
        check_health(check)
        check_worlded_size(check)
        check_other_websites(check)
        check_overpass_setting(check, work)
        check_workshop(check, work)
        check_compile_state(check, work)
        check_compile_records(check, work)

        print("error log")
        import zipfile

        import knoxlog

        def _boom():
            raise ValueError("selftest boom")
        real = knoxmap_app.app.view_functions["api_lots"]
        knoxmap_app.app.view_functions["api_lots"] = _boom
        try:
            reply = client.get("/api/lots?map=x")
        finally:
            knoxmap_app.app.view_functions["api_lots"] = real
        body = reply.get_json(silent=True) or {}
        logged = open(knoxlog.MAIN_LOG, encoding="utf-8").read() if knoxlog.MAIN_LOG.exists() else ""
        check(reply.status_code == 500 and reply.is_json and str(body.get("errorId", "")).startswith("E-")
              and body["errorId"] in logged and "ValueError: selftest boom" in logged,
              "a crash comes back as JSON with an id that finds its traceback in the log")
        refused = client.post("/api/buildings", json={"mapName": "no such map"}).get_json() or {}
        logged = open(knoxlog.MAIN_LOG, encoding="utf-8").read()
        check(refused.get("errorId", "-") in logged, "refusals are logged with their id too")
        client.post("/api/client-error", json={"message": "selftest page error", "where": "x.js:1:1"})
        check("selftest page error" in open(knoxlog.MAIN_LOG, encoding="utf-8").read(),
              "errors in the page reach the log")
        report = client.get("/api/report")
        names = zipfile.ZipFile(io.BytesIO(report.data)).namelist() if report.status_code == 200 else []
        check("system.txt" in names and "logs/knoxmap.log" in names,
              f"the problem report holds the log and a description of the PC ({len(names)} files)")
        home = str(Path.home())
        check(home not in knoxlog.redact(os.path.join(home, "KnoxMap", "x.log"))
              and "<home>" in knoxlog.redact(home),
              "the report leaves the user's name out of paths")

        print("install")
        lots = os.path.join(out, "lots")
        os.makedirs(lots, exist_ok=True)
        open(os.path.join(lots, "0_0.lotheader"), "wb").write(b"stand-in")
        from make_map_mod import package
        mods = os.path.join(work, "mods")
        with contextlib.redirect_stdout(io.StringIO()):
            mod_root, cells, extras = package(out, "Selftest: Town", "selftest", mods_dir=mods)
        check(os.path.exists(os.path.join(mod_root, "ATTRIBUTION.txt")), "ATTRIBUTION.txt in the mod")
        # A server needs three things the mod folder cannot tell it: the mod
        # id, the map folder ahead of the vanilla one, and a spawn region
        # naming this map's spawnpoints. And the warning that matters most -
        # a world keeps the cells it has already made, so a map added to one
        # that exists fails in ways nobody can trace back.
        from make_map_mod import folder_name, write_server_setup
        map_folder = folder_name("Selftest: Town", "selftest")
        setup = os.path.join(mod_root, "SERVER SETUP.txt")
        regions = os.path.join(mod_root, "server",
                               f"{map_folder}_spawnregions.lua")
        said = open(setup, encoding="utf-8").read() if os.path.exists(setup) else ""
        lua = open(regions, encoding="utf-8").read() if os.path.exists(regions) else ""
        check(f"Mods=selftest" in said and f"Map={map_folder};Muldraugh, KY" in said,
              "the server's Mods= and Map= lines are written out with real names")
        check("BEFORE anyone joins" in said and "new world" in said,
              "and it says to add the map before the world exists")
        check("every player" in said and "Workshop" in said,
              "and that every player needs the mod too, it not being on the "
              "Workshop")
        erika = write_server_setup(os.path.join(work, "erika-notes"), "m",
                                   "M", "M", needs_erika=True)
        with_erika = open(os.path.join(work, "erika-notes", "SERVER SETUP.txt"),
                          encoding="utf-8").read()
        check("Erikas_Tiles" in with_erika and "WorkshopItems=" in with_erika
              and "Erikas_Tiles" not in said,
              f"a map built with Erika's Tiles says the server needs them, and "
              f"one without does not ({erika})")
        check("function SpawnRegions()" in lua
              and f'media/maps/{map_folder}/spawnpoints.lua' in lua
              and "Muldraugh, KY" in lua,
              "a spawn region file is written, this map's and the vanilla one")
        try:
            import lupa
            lupa.LuaRuntime().compile(lua)
            check(True, "and it is Lua the game can read")
        except ImportError:
            pass
        except Exception as exc:    # noqa: BLE001
            check(False, f"and it is Lua the game can read ({exc})")
        play = open(os.path.join(mod_root, "HOW TO PLAY.txt"), encoding="utf-8").read()
        check("before you start the world" in play.lower()
              and "SERVER SETUP.txt" in play,
              "and a single player is told the same, and where the server notes are")
        info = open(os.path.join(mod_root, "mod.info"), encoding="utf-8").read()
        check("OpenStreetMap" in info, "OpenStreetMap credit in the mod description")
        check("require=" not in info, "a map without mod tiles requires no mods")
        from knoxbuild.worldmap_bin import read_bin
        bin_map = os.path.join(mod_root, "common", "media", "maps", "Selftest Town", "worldmap.xml.bin")
        try:
            paper = read_bin(bin_map)
        except (OSError, ValueError) as exc:
            paper = {}
            print(f"        {exc}")
        kinds = {k for feats in paper.values() for _t, _r, props in feats for k in props}
        check(paper and "building" in kinds
              and all(x >= 82 for x, _y in paper)
              and all(-32768 <= px <= 32767 for feats in paper.values()
                      for _t, rings, _p in feats for ring in rings for px, _ in ring),
              f"the paper map is written as Build 42's worldmap.xml.bin ({len(paper)} cells)")
        # Build 42's XML reader throws on every outline of its own format, so
        # the XML only ever goes in beside a binary the game reads instead.
        map_folder = os.path.dirname(bin_map)
        check(not os.path.exists(os.path.join(map_folder, "worldmap.xml"))
              or os.path.exists(bin_map),
              "the paper map's XML never ships without its binary")
        # Walk it the way the game does - one point buffer per cell, each
        # outline remembering where it starts as a signed 16-bit number - and
        # make sure nothing reads past the end. Reading past it is what broke
        # the in-game map from worldmap.xml: hundreds of
        # "IndexOutOfBoundsException at WorldMapRenderer.fillPolygon".
        def buffer_safe(data) -> bool:
            for feats in data.values():
                pos = 0
                for _kind, rings, _props in feats:
                    for ring in rings:
                        first = pos
                        pos += 2 * len(ring)
                        if first > 32767 or first + 2 * (len(ring) - 1) + 1 >= pos:
                            return False
            return True

        check(buffer_safe(paper), "every outline on the paper map is inside its cell's buffer")

        # Rounding to whole tiles is what makes an outline the game cannot
        # draw. Reported from a Madrid map: 259 invalid and 39 zero-area
        # polygons, one of them [(244, 162), (244, 153), (244, 162)].
        from shapely.geometry import Polygon as _Poly

        from knoxbuild.worldmap_bin import read_bin as _read, write_bin as _write
        shapes = [("thin", [(244.2, 162.4), (244.4, 153.1), (244.1, 162.2)]),
                  ("collapse", [(50.1, 50.1), (50.4, 50.2), (50.2, 50.4), (50.3, 50.1)]),
                  ("bowtie", [(100, 100), (120, 120), (120, 100), (100, 120)]),
                  ("wide", [(200, 40), (900, 44), (895, 300), (205, 296)]),
                  ("ok", [(10, 10), (30, 10), (30, 30), (10, 30)])]
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<world version="1.0">',
                 ' <cell x="0" y="0">']
        for label, ring in shapes:
            pts = "".join(f'<point x="{px}" y="{py}"/>' for px, py in ring)
            lines += ['  <feature>', '   <geometry type="Polygon">',
                      f'    <coordinates>{pts}</coordinates>', '   </geometry>',
                      '   <properties>'
                      f'<property name="building" value="{label}"/></properties>',
                      '  </feature>']
        lines += [' </cell>', '</world>']
        nasty = os.path.join(work, "nasty.xml")
        with open(nasty, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        _write(nasty, nasty + ".bin")
        drawn = _read(nasty + ".bin")
        broken = 0
        for feats in drawn.values():
            for _t, rings, _props in feats:
                if any(len(set(map(tuple, r))) < 3 for r in rings):
                    broken += 1
                    continue
                shape = _Poly(rings[0], rings[1:])
                if not shape.is_valid or shape.area <= 0:
                    broken += 1
        labels = {v for feats in drawn.values() for _t, _r, props in feats
                  for v in props.values()}
        check(broken == 0 and {"ok", "wide", "bowtie"} <= labels
              and "thin" not in labels and "collapse" not in labels,
              f"a collapsed or crossed outline never reaches the paper map "
              f"({broken} bad, kept {sorted(labels)})")
        # A cell packed with more outlines than the game can index (it holds
        # each cell's points in one buffer, addressed by a 16-bit number).
        from knoxbuild.worldmap_bin import CELL_POINT_BUDGET, write_bin
        crowded = os.path.join(work, "crowded.xml")
        with open(crowded, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<world version="1.0">\n'
                    ' <cell x="0" y="0">\n')
            for i in range(3000):
                ring = "".join(f'<point x="{(i * 7) % 200 + dx}" y="{(i * 13) % 200 + dy}"/>'
                               for dx, dy in ((0, 0), (9, 1), (10, 9), (1, 10), (0, 5), (5, 0)))
                f.write('  <feature>\n   <geometry type="Polygon">\n'
                        f'    <coordinates>{ring}</coordinates>\n   </geometry>\n'
                        '   <properties><property name="building" value="yes"/></properties>\n'
                        '  </feature>\n')
            f.write(" </cell>\n</world>\n")
        write_bin(crowded, crowded + ".bin")
        packed = read_bin(crowded + ".bin")
        worst = max((sum(len(r) for _t, rings, _p in feats for r in rings)
                     for feats in packed.values()), default=0)
        check(packed and worst <= CELL_POINT_BUDGET,
              f"a cell too full for the game's map is thinned to fit ({worst} points)")
        objects = os.path.join(mod_root, "common", "media", "maps", "Selftest Town", "objects.lua")
        text = open(objects, encoding="utf-8").read() if os.path.exists(objects) else ""
        check(text.startswith("objects = {") and text.count('type = "ParkingStall"') == stalls
              and re.search(r'x = 2\d{4}, y = \d+, z = 0', text),
              "the parking stalls reach the game in objects.lua, at world tiles")
        open(os.path.join(lots, "0_0.lotheader"), "wb").write(b"LOTH\x01\x00\x00\x00signs_erika_01_000\n")
        with contextlib.redirect_stdout(io.StringIO()):
            mod_root, cells, extras = package(out, "Selftest: Town", "selftest", mods_dir=mods)
        info_erika = open(os.path.join(mod_root, "mod.info"), encoding="utf-8").read()
        check("require=Erikas_Tiles" in info_erika and "require=\\" not in info_erika,
              "a map using Erika's tiles requires the mod by its own id")
        check(os.path.isdir(os.path.join(mod_root, "common", "media", "maps", "Selftest Town")),
              "map folder name is safe for Windows")
        lua_dir = os.path.join(mod_root, "common", "media", "lua", "shared", "KnoxMap")
        selector = [open(os.path.join(lua_dir, f), encoding="utf-8").read()
                    for f in os.listdir(lua_dir)] if os.path.isdir(lua_dir) else []
        check(selector and "Selftest School" in selector[0] and "OnGameBoot" in selector[0]
              and selector[0].count("{") == selector[0].count("}"),
              "Spawn Selector gets the town and its landmarks")
        loot = os.path.join(mod_root, "common", "media", "lua", "client", "KnoxMap",
                            "KnoxMapResetLoot.lua")
        text = open(loot, encoding="utf-8").read() if os.path.exists(loot) else ""
        ok = ("OnFillWorldObjectContextMenu" in text and "ItemPicker.fillContainer" in text
              and "isClient()" in text)
        try:                      # a real parse when a Lua runtime is installed
            import lupa
            lupa.LuaRuntime().compile(text)
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001 - a syntax error in the shipped Lua
            ok = False
            print(f"        {exc}")
        check(ok, "the Reset loot menu is installed with the map")
        check_rifle(check, out, mod_root)
    except Exception:
        import traceback
        traceback.print_exc()
        check(False, "ran to the end without an error")
    finally:
        if keep:
            print(f"kept in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    print("selftest " + ("passed" if not check.failed else f"FAILED ({check.failed})"))
    return 1 if check.failed else 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(main(sys.argv))
