"""The first half of the selftest's checks: the town itself, terrain, buildings.

Split from tools/selftest.py, which had grown past 4,800 lines. The fixtures
and the driver live in selftest.py; the names below are imported from it, and
`selftest` is on sys.path because tools/ is the script's own folder.
"""
from __future__ import annotations

from selftest import (
    C,
    EAST,
    Image,
    NORTH,
    OSMFeature,
    Path,
    SOUTH,
    WEST,
    _dense,
    _ids,
    _sides_for,
    contextlib,
    io,
    json,
    math,
    os,
    re,
    shutil,
    sys,
    tempfile,
)




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


          
def check_long_streets(check) -> None:
    """No <street> in streets.xml longer than the game can draw.

    Build 42 builds each street's outline for the M map in one shared 3 KB
    buffer and never grows it there; a street of ~190 points or more throws
    BufferOverflowException inside the map's render and blanks the whole map
    window. OpenStreetMap country roads reach that (648 points, Hollister).
    """
    from knoxbuild.worldmap import MAX_STREET_POINTS, _street_pieces

    road = [(float(i), float(i % 7)) for i in range(648)]
    pieces = _street_pieces(road)
    rebuilt = pieces[0] + [p for piece in pieces[1:] for p in piece[1:]]
    check(max(len(p) for p in pieces) <= MAX_STREET_POINTS and min(len(p) for p in pieces) >= 2
          and rebuilt == road and all(a[-1] == b[0] for a, b in zip(pieces, pieces[1:]))
          and _street_pieces(road[:5]) == [road[:5]],
          f"a long street is written as joined pieces the map can draw "
          f"({len(pieces)} pieces of at most {MAX_STREET_POINTS} points)")






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
        # Same keyword arguments compile_map passes (knoxlots, should_stop,
        # on_progress): a bare `lambda p` here raised TypeError instead.
        _repair.repair_project = lambda p, **kwargs: {"changed": False, "moved": 0,
                                                      "dropped": []}
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
    bounds = (38.60, 34.90, 38.64, 34.94)
    path = overture.cache_path(work, "ovtest")
    overture.save_cache(path, bounds, rows)
    check(overture.load_cache(path, bounds) is not None,
          "a fetch is kept beside the map, so the minutes are paid once")
    check(overture.load_cache(path, (38.60, 34.90, 38.64, 34.95)) is None,
          "a different area is not answered from it")
    was = os.environ.get("KNOXMAP_OVERTURE_RELEASE")
    os.environ["KNOXMAP_OVERTURE_RELEASE"] = "1999-01-01.0"
    try:
        stale = overture.load_cache(path, bounds)
    finally:
        if was is None:
            os.environ.pop("KNOXMAP_OVERTURE_RELEASE", None)
        else:
            os.environ["KNOXMAP_OVERTURE_RELEASE"] = was
    check(stale is None, "nor is a newer release answered from an older one")

    # Without DuckDB the map is still made, from OSM alone.
    out, stats = overture.add_missing([], bounds, work, "ovtest2")
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
    overture.save_cache(overture.cache_path(seeded, "m"), bounds, rows)
    out, stats = overture.add_missing([], bounds, seeded, "m")
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
        _json.dump({"osm_bbox": list(bounds)}, f)
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
    from web import checks as webchecks

    real = knoxlog.memory_status
    try:
        knoxlog.memory_status = lambda: (15_000_000_000, 5_300_000_000, 2_100_000_000)

        class Small:                      # a 32-bit Python
            maxsize = 2 ** 32 - 1

        # The area is worked out from the per-tile cost the code declares, not
        # written down here: at 80 bytes a tile 5400x6000 was over a 32-bit
        # Python's room, and at 20 it is not. What is being tested is the rule.
        room = 2_100_000_000 * 0.8
        side = int(((room - webchecks.BASE_BYTES) / webchecks.BYTES_PER_TILE * 1.5) ** 0.5) + 1
        was, webchecks.sys = webchecks.sys, Small
        try:
            big = knoxapp._too_big_for_memory(side, side)
            small = knoxapp._too_big_for_memory(1200, 1200)
        finally:
            webchecks.sys = was
        import knoxpaths as _kp
        check(big and "32-bit" in big and _kp.setup_command() in big and not small,
              "a map too big for a 32-bit Python is warned about, with a way out")
        knoxlog.memory_status = lambda: (15_000_000_000, 900_000_000, 140_000_000_000)
        tight = knoxapp._too_big_for_memory(side, side)
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
