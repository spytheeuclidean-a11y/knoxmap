"""Selftest checks for buildings."""
from __future__ import annotations

if __package__ == "tools.selftest_suite":
    from ..selftest import (
        EAST, Image, NORTH, OSMFeature, Path, SOUTH, WEST,
        _dense, _ids, _sides_for, contextlib, io, json,
        os, re, shutil, sys, tempfile,
    )
else:
    from selftest import (
        EAST, Image, NORTH, OSMFeature, Path, SOUTH, WEST,
        _dense, _ids, _sides_for, contextlib, io, json,
        os, re, shutil, sys, tempfile,
    )


def check_1_3_6(check, out: str, tbx: list[str], pzw_text: str, log: str) -> None:
    """What 1.3.6 added: rows cut into units, rooms the game can fill, police
    stations and libraries, graves, army bases, and a place in the world of
    this map's own."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    check(props and graves >= 16 and any("selftest_props_" in line
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
    ranged = [f for f in geo["features"]
              if (f.get("properties") or {}).get("addr:street") == "Range Row"]
    check(not ranged,
          f"the ends of an address interpolation are not houses ({len(ranged)})")

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
    # A floor this big is cut into sections now, each its own shop; a section of
    # 200 tiles or more still gets a switch at each end.
    big = [i for i, r in enumerate(mall.rooms, 1) if r.area >= 200]
    check(big and all(per_room.get(i, 0) >= 2 for i in big),
          f"a big room has several light switches ({[per_room.get(i, 0) for i in big]})")

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


def check_basements(check, out: str) -> None:
    """Basements (knoxbuild/basements.py). Only knoxlots compiles them, so the
    town built for WorldEd above has none; built again for knoxlots, some of its
    houses and its school and barracks get one, compiled to levels below 0,
    each part of the building over it, its stairs coming up through that floor."""
    if check.fast:
        print("  skip  basements and the knoxlots compile (--fast)")
        return
    import glob
    import shutil
    from knoxbuild.build import build
    from knoxbuild.settings import Settings
    from tools.building_stats import read_header
    from tools.compile_map import compile_rust, knoxlots_exe

    name = os.path.basename(os.path.normpath(out))
    check(not glob.glob(os.path.join(out, "buildings", "*_bsmt.tbx")),
          "no basements in a map WorldEd will compile")
    if knoxlots_exe() is None:
        return
    work = tempfile.mkdtemp(prefix="knoxmap-basements-")
    was = os.environ.get("KNOXMAP_BACKEND")
    try:
        os.environ["KNOXMAP_BACKEND"] = "rust"
        copy = os.path.join(work, name)
        shutil.copytree(out, copy, ignore=shutil.ignore_patterns("lots", ".knoxlots"))
        with contextlib.redirect_stdout(io.StringIO()):
            build(copy, settings=Settings(seed=1))
            compile_rust(copy)
        below = sorted(glob.glob(os.path.join(copy, "buildings", "*_bsmt.tbx")))
        opened = all('type="hole"' in open(p[:-len("_bsmt.tbx")] + ".tbx", encoding="utf-8").read()
                     for p in below)
        lowest, joined, orphans = 0, 0, 0
        for header in glob.glob(os.path.join(copy, "lots", "*.lotheader")):
            _names, lo, _hi, rooms, buildings = read_header(header)
            lowest = min(lowest, lo)
            under = [{rooms[i][1] < 0 for i in b} for b in buildings]
            joined += sum(1 for u in under if u == {True, False})
            orphans += sum(1 for u in under if u == {True})
    finally:
        if was is None:
            os.environ.pop("KNOXMAP_BACKEND", None)
        else:
            os.environ["KNOXMAP_BACKEND"] = was
        shutil.rmtree(work, ignore_errors=True)
    # A basement is a building of its own, as in every map the game ships:
    # joined to the house above, the game took the house's roof off.
    check(below and opened and lowest <= -1 and orphans and not joined,
          f"a house basement compiles to level -1 and its stairs reach the house "
          f"({len(below)} basements, down to level {lowest}, {orphans} buildings of their own, "
          f"{joined} joined to the house)")


def check_build_audits(check, out: str) -> None:
    """The things the fixes from the field reports put right, checked on what
    the build just wrote: no glass walls inside, no fence lost to a lamp, no
    roof over open ground, no staircase with a wall across it."""
    from knoxbuild import buildtiles, catalog
    from tools import tbx_stats

    glass = catalog.GLASS_WALL_TILES
    walls = catalog._all_interior_walls()
    check(walls and not any(t in glass for e in walls for t in e["tiles"].values()),
          f"no room is walled in glass storefront panes ({len(walls)} interior wall styles)")

    check(buildtiles._structure("fencing_01_3") and buildtiles._structure("walls_exterior_house_01_0")
          and buildtiles._yields("lighting_outdoor_01_0") and not buildtiles._yields("fencing_01_3"),
          "a fence or wall is structure, and a lamp is what gives way to it")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        tbx_stats.main(["tbx_stats", os.path.join(out, "buildings")])
    stats = {k.strip(): v.strip() for k, v in
             (line.split(":", 1) for line in buf.getvalue().splitlines() if ":" in line)}
    over = int(stats["roof tiles over open ground"].split(" of ")[0])
    blocked = int(stats["flights with a wall across"].split(" of ")[0])
    check(int(stats["buildings"]) > 0 and over == 0,
          f"no roof hangs over open ground ({stats['buildings']} buildings)")
    check(blocked == 0, "and no staircase has a wall across it")


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


def check_garage_door(check, out: str) -> None:
    """A garage gets one wide garage door, not three house doors.

    _widen_vehicle_entry in knoxbuild/layout.py cuts the street-facing
    entry into a three-tile opening, but tbx.py used to write every one
    of the three door objects with the plain house door tile, so a
    garage read as three ordinary doors in a row.
    """
    import csv as _csv
    from knoxbuild.catalog import GARAGE_DOOR

    name = os.path.basename(out.rstrip(os.sep))
    bdir = os.path.join(out, "buildings")
    rows = list(_csv.DictReader(open(os.path.join(out, f"{name}_placements.csv"),
                                     encoding="utf-8")))
    garages = [r["file"] for r in rows if r["kind"] == "garage"]
    check(garages, "the town has a garage to check")

    tiles = []
    for fname in garages:
        text = open(os.path.join(bdir, fname), encoding="utf-8").read()
        tiles += [int(t) for t in re.findall(
            r'<object type="door"[^/]*Tile="(\d+)"', text)]
    garage_tiles = [t for t in tiles if t in GARAGE_DOOR]
    check(len(garage_tiles) >= 3 and set(garage_tiles) == set(GARAGE_DOOR),
          f"a garage gets one wide garage door, all three segments "
          f"({len(garage_tiles)} tiles, {sorted(set(garage_tiles))})")


def check_giant_outline(check, work: str) -> None:
    """A building past max_size is kept, and does not cost the buildings inside it.

    Placed first (largest first), the giant outline claimed every tile in it and
    the house standing inside came out "taken"; where 1.5.2 left the outline out
    and kept the house. Outlines past max_size are placed after the rest."""
    if check.fast:
        print("  skip  the giant outline, a whole map built again (--fast)")
        return
    import csv

    from generator import renderer
    from knoxbuild.build import MAX_OVERSIZE_TILES, build
    from knoxbuild.settings import Settings

    def corners(s, w, n, e):
        return [(s, w), (s, e), (n, e), (n, w), (s, w)]

    giant = corners(SOUTH + 0.0004, WEST + 0.0004, SOUTH + 0.0044, WEST + 0.0064)    # ~440 x 480 m
    house = corners(SOUTH + 0.0022, WEST + 0.0030, SOUTH + 0.00245, WEST + 0.00335)  # ~28 x 21 m
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


def check_house_plan(check) -> None:
    """A house you walk round, not through.

    Every room opening onto every room it touches is a warren: the commonest
    door in a generated town was one bedroom into the next, and an upstairs
    had no landing at all because only a lift or stair core was ever made a
    hall. Rooms open onto circulation now, bar the pairs a real house has -
    a bathroom off a bedroom, and the kitchen, dining and living rooms.
    """

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


def check_shared_buildings(check, work: str) -> None:
    """A building goes out as one file and comes back as the same building.

    Somebody builds a house, presses Share and sends the file; anybody with
    KnoxMap can take it in, and tools/add_shared_building.py can put it into
    the library that ships with it (knoxbuild/share.py). Checked here because
    what arrives that way came from a stranger over a chat program.
    """
    import json as _json

    from knoxbuild import designer as D
    from knoxbuild import presets as P
    from knoxbuild import share as S

    tbx = ('<building version="4" width="12" height="10"><room name="hall"/>'
           '<floor></floor><floor></floor></building>')
    home = os.path.join(work, "shared_home")
    sent = S.wrap("Station House", tbx, D.clean(
        {"width": 12, "height": 10, "storeys": 1,
         "rooms": [{"level": 0, "x": 0, "y": 0, "w": 12, "h": 10,
                    "kind": "hall"}]}), kind="police", author="Somebody")
    came, problem = S.read(_json.loads(_json.dumps(sent)))
    check(came is not None and not problem,
          f"a shared building survives being written out and read back ({problem})")
    if came:
        S.install(home, came)
        listed = P.library(home)
        check([p["name"] for p in listed] == ["Station House"]
              and listed[0]["kind"] == "police" and listed[0]["editable"]
              and P.read(home, "Station House") == tbx,
              "and lands whole: the .tbx as it was sent, its kind and its drawing")

    # What a stranger's file may not do.
    bomb = '<!DOCTYPE a [<!ENTITY b "bb">]>' + tbx
    refused = {what: S.read(data)[1] for what, data in (
        ("not ours", {"format": "something-else"}),
        ("a version we do not read", {**sent, "version": 99}),
        ("no building in it", {**sent, "tbx": "hello"}),
        ("an XML bomb", {**sent, "tbx": bomb}),
        ("a building the size of a county",
         {**sent, "tbx": tbx.replace('width="12"', f'width="{S.MAX_SIDE + 1}"')}),
    )}
    taken = [what for what, problem in refused.items() if not problem]
    check(not taken, f"and a file that is none of those is refused "
                     f"({', '.join(taken) if taken else 'all five'})")

    # The library that ships with KnoxMap: every building listed has its file,
    # and every file is listed, so a half-committed one is caught here.
    import knoxpaths
    folder = P.library_folder(knoxpaths.BASE_DIR)
    on_disk = {entry["name"] for entry in P._in_folder(folder)}
    recorded = set(P.shipped(knoxpaths.BASE_DIR))
    check(on_disk == recorded,
          f"the library that ships with KnoxMap matches its manifest "
          f"({len(on_disk)} buildings"
          + (f"; odd ones out: {sorted(on_disk ^ recorded)[:4]}"
             if on_disk != recorded else "") + ")")


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

    crate_tile = C.FURNITURE["crate"]["W"]["0,0"]
    check(crate_tile.endswith(("_016", "_017", "_018", "_019")),
          f"a box on the floor is the one drawn on the floor ({crate_tile})")

    # And a school is walked round, not through: only houses had circulation.
    from knoxbuild.settings import Settings as _S
    halls = 0
    plan = L.build_building(55, 40, levels=1, seed=3, kind="school",
                            commercial=True, settings=_S()).storeys[0]
    halls = sum(1 for r in plan.rooms if (r.kind or "") in L.CIRCULATION)
    check(halls >= 3, f"a school has corridors to reach its classrooms by "
                      f"({halls} of {len(plan.rooms)} rooms)")


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
    civic = {s["name"] for s in wall_variants("civic") + wall_variants("police")}
    house = {s["name"] for s in C.HOUSE_STYLES}
    got = pick_style("police", 500, 500, rng, settings, 0.6)
    check(got["name"] in civic and got["name"] not in house,
          f"a police station is built like a public building ({got['name']})")


def check_windows_open(check) -> None:
    """The windows on a house are ones the game lets you open.

    The table of locked window sprites is read off the game's own tile
    definitions, so it can go stale when the game changes. Where this PC has
    the game, the table is checked against it; where it has not, only the
    styles are checked, which is what CI can see.
    """
    import re as _re

    from knoxbuild import catalog as _C
    from knoxbuild.buildtiles import LOCKED_WINDOWS, window_locked

    def west(style):
        return (style.get("window") or {}).get("tiles", {}).get("West", "")

    shut = [s["name"] for s in _C.HOUSE_STYLES if window_locked(west(s))]
    check(not shut, f"every house style has windows that open ({shut or 'all 14'})")
    public = [k for k in ("civic", "medical", "school")
              if window_locked(west(_C.SPECIAL_STYLES[k]))]
    check(not public, f"so does every building people walk into ({public or 'all of them'})")

    import knoxpaths
    media = knoxpaths.pz_media_dir()
    path = os.path.join(str(media), "newtiledefinitions.tiles.txt") if media else ""
    if not path or not os.path.exists(path):
        print("  --    the game's own tile definitions are not on this PC, "
              "so the locked-window table is taken as read")
        return
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    locked = {}
    for block in _re.findall(r"tileset\s*\{(.*?)\n\}", text, _re.S):
        sheet = _re.search(r"file = (\S+)", block)
        if not sheet or sheet.group(1) not in LOCKED_WINDOWS:
            continue
        for tile in _re.finditer(r"//\s*(\S+)\n\s*tile\s*\{(.*?)\n    \}",
                                 block, _re.S):
            if "WindowLocked" in tile.group(2):
                locked.setdefault(sheet.group(1), set()).add(
                    int(tile.group(1).rsplit("_", 1)[1]))
    wrong = []
    for sheet, spans in LOCKED_WINDOWS.items():
        ours = {n for low, high in spans for n in range(low, high + 1)}
        theirs = locked.get(sheet, set())
        if ours != theirs:
            wrong.append(f"{sheet}: {sorted(ours ^ theirs)[:8]}")
    check(not wrong, f"the locked-window table matches this copy of the game "
                     f"({'; '.join(wrong) if wrong else 'all four sheets'})")

