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
    biggest = 0
    for kind, w, h in (("industrial", 140, 110), ("civic", 200, 200),
                       ("apartment", 60, 40), (None, 30, 24)):
        plan = layout.build_building(w, h, commercial=True, seed=3, kind=kind,
                                     levels=1, settings=_S()).storeys[0]
        # Bar the landing of a block of flats, which is a corridor by
        # design and holds nothing worth filling.
        biggest = max(biggest, max((r.x1 - r.x0 + 1) * (r.y1 - r.y0 + 1)
                                   for r in plan.rooms if not r.is_core))
    check(0 < biggest <= layout.MAX_ROOM_AREA,
          f"no room is bigger than the game will fill ({biggest} tiles)")

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

    # The first map on a PC keeps the old origin; the next one stands clear.
    origin = re.search(r'<worldOrigin origin="(\d+),(\d+)"', pzw_text)
    check(origin and (int(origin.group(1)), int(origin.group(2))) == WORLD_ORIGIN_CELLS,
          "the first map is built where every map used to be")
    beside = os.path.join(os.path.dirname(out), "elsewhere")
    os.makedirs(beside, exist_ok=True)
    picked = choose_origin(beside, 3, 3)
    check(picked[0] >= WORLD_ORIGIN_CELLS[0] + 3,
          f"a second map is built clear of the first (cell {picked[0]},{picked[1]})")
    shutil.rmtree(beside, ignore_errors=True)


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

    was = os.environ.get("LD_LIBRARY_PATH")
    os.environ["LD_LIBRARY_PATH"] = "/usr/lib/x86_64-linux-gnu"
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
    check(windows or "/usr/lib/x86_64-linux-gnu" in path,
          "and what was already there is kept, not thrown away")
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
        # Far past every old limit: about 1,100 km2 at half a metre a tile,
        # which is 2.4 million tiles a side and a terabyte of bitmap.
        huge = {"south": 51.2, "west": -0.6, "north": 51.5, "east": -0.1,
                "metersPerTile": 0.5, "mapName": "selftest-huge"}
        said = client.post("/api/generate", json=huge)
        body = (said.get_json() or {}).get("error", "")
        check("got as far as the download" in body,
              f"a map far past every old limit is built, not refused "
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
                                              "current_version", "enabled")}
    try:
        updater.BASE_DIR, updater.UPDATE_DIR = base, update_dir
        updater.STAGED, updater.MANIFEST = update_dir / "staged.json", base / saved["MANIFEST"].name
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
    finally:
        for k, v in saved.items():
            setattr(updater, k, v)


def main(argv: list[str]) -> int:
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
        veg = Image.open(os.path.join(out, "selftest_veg.bmp")).convert("RGB")
        pixels = veg.get_flattened_data() if hasattr(veg, "get_flattened_data") else veg.getdata()
        kerbs = sum(1 for c in pixels if c[0] == 12 and c[1] == 34)
        check(kerbs > 100, f"kerbs laid ({kerbs})")
        trees = sum(1 for c in pixels if c == C.TREES)
        shrubs = sum(1 for c in pixels if c == C.BUSHES)
        check(trees > 20 and shrubs > 20, f"gardens planted ({trees} trees, {shrubs} shrubs)")

        print("buildings")
        with contextlib.redirect_stdout(io.StringIO()) as log:
            build(out, settings=Settings(seed=1))
        rows = open(os.path.join(out, "selftest_placements.csv"), encoding="utf-8").read().splitlines()
        check(len(rows) - 1 >= 60, f"buildings placed ({len(rows) - 1})")
        pzw_text = open(os.path.join(out, "selftest.pzw"), encoding="utf-8").read()
        size = re.search(r'<world version="[^"]*" width="(\d+)" height="(\d+)"', pzw_text)
        cells = [(int(a), int(b)) for a, b in re.findall(r'<cell x="(\d+)" y="(\d+)"', pzw_text)]
        check(size and all(x < int(size.group(1)) and y < int(size.group(2)) for x, y in cells),
              "every cell in the WorldEd project is inside the world")
        check_lots_apart(check, out)
        check_procedural(check, work)
        check_qt_env(check)
        check_compile_failures(check, work)
        check_wall_corners(check)
        check_overture(check, work)
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
        houses_tbx = [t for p, t in zip(tbx, texts) if not any(k in p for k in ("_fences_", "_structures_", "_pumps_", "_props_"))]
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
        check_memory_guard(check)
        check_box_any(check)

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
