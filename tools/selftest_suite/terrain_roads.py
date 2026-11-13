"""Selftest checks for terrain roads."""
from __future__ import annotations

if __package__ == "tools.selftest_suite":
    from ..selftest import (
        C, Image, Path, SOUTH, WEST,
        box, math, os, shutil, sys, tempfile, way,
    )
else:
    from selftest import (
        C, Image, Path, SOUTH, WEST,
        box, math, os, shutil, sys, tempfile, way,
    )


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
    from web import common as webcommon

    class Reached(RuntimeError):
        """Raised where the download would start."""

    def no_download(*_a, **_k):
        raise Reached("got as far as the download")

    client = knoxapp.app.test_client()
    was_fetch = knoxapp.osm.fetch_features_tiled
    was_out = webcommon.OUTPUT_DIR
    knoxapp.osm.fetch_features_tiled = no_download
    webcommon.OUTPUT_DIR = Path(work) / "huge-maps"
    webcommon.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # Past every old limit but the one WorldEd has: 25 km x 10 km at a metre a
        # tile, 25,000 tiles a side and 250 million tiles. (A map past 268
        # million is refused: see check_worlded_size.)
        huge = {"south": 51.2, "west": -0.6, "north": 51.29, "east": -0.24,
                "metersPerTile": 1, "mapName": "selftest-huge"}
        import knoxlog as _kl
        _mem = _kl.memory_status
        _kl.memory_status = lambda: (2 ** 40, 2 ** 40, 2 ** 40)  # not the host's RAM
        try:
            said = client.post("/api/generate", json=huge)
        finally:
            _kl.memory_status = _mem
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
        webcommon.OUTPUT_DIR = was_out

    check(knoxapp.BIG_AREA_KM2 > 0 and knoxapp.BIG_TILES_PER_SIDE > 0
          and knoxapp.BIG_LANDMARK_KM2 > 0,
          "and the numbers behind the warnings are still there to warn with")


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
                             cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             capture_output=True, text=True).stdout.strip()
        seen.add(got)
    check(len(seen) == 1 and "" not in seen,
          "a building's floor and trim seeds are the same in every process")


def check_straight_roads(check) -> None:
    """Knox County roads: every road in grid or 45-degree runs, roads that met
    still meeting, and the buildings beside them moved with them."""
    from shapely.geometry import LineString, Point

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

    def gap() -> float:
        """How far the house's nearest corner is from the main road, in tiles."""
        line = LineString([proj.to_px(*p) for p in main.geometry])
        return min(Point(proj.to_px(*p)).distance(line) for p in house.geometry)

    was_gap = gap()
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
    # Not just "moved a little": it has to sit the same way against the road
    # it was beside, or the town has drifted off the street the game will draw.
    check(abs(gap() - was_gap) <= 1.0,
          f"and stay the same distance from it ({was_gap:.1f} tiles before, {gap():.1f} after)")


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


def check_trees_are_trees(check) -> None:
    """Every tree the rules place is one the game knows is a tree.

    A species sheet holds 24 pictures and Build 42 defines the first eight; it
    is the definition that carries `tree = 1..8`, the property that makes the
    tile a tree rather than a picture of one. Rules.txt asking for an index
    past that is the quietest failure KnoxMap has had - the picture draws, so
    nothing complains, and the wood is scenery - which is what this looks for.
    Where this PC has no game, only the rules are checked.
    """
    import re as _re

    import knoxpaths
    from knoxbuild.rules import parse_rules

    tools = knoxpaths.mapping_tools_dir()
    path = os.path.join(str(tools), "config", "Rules.txt") if tools else ""
    if not path or not os.path.exists(path):
        print("  --    the map tools are not on this PC, so the tree rules "
              "are taken as read")
        return
    with open(path, encoding="utf-8", errors="replace") as f:
        rules = parse_rules(f.read())
    named = {tile for rule in rules.rules for entry in rule.entries
             for tile in rules.aliases.get(entry, [entry])
             if tile.startswith("e_") and "grass" not in tile}
    check(any("JUMBO" in t for t in named),
          f"the rules place big trees ({sum('JUMBO' in t for t in named)} of "
          f"{len(named)} tree tiles)")

    media = knoxpaths.pz_media_dir()
    if not media or not os.path.isdir(str(media)):
        print("  --    the game is not on this PC, so the tree tiles are "
              "taken as read")
        return
    sizes: dict = {}
    for name in sorted(os.listdir(str(media))):
        if not name.endswith(".tiles.txt"):
            continue
        with open(os.path.join(str(media), name), encoding="utf-8",
                  errors="replace") as f:
            text = f.read()
        for tile in _re.finditer(r"//\s*(\S+)\n\s*tile\s*\n?\s*\{(.*?)\n    \}",
                                 text, _re.S):
            tree = _re.search(r"tree = (\d+)", tile.group(2))
            if tree:
                sizes[tile.group(1)] = int(tree.group(1))
    scenery = sorted(t for t in named if t not in sizes)
    check(not scenery, f"every tree the rules place is a tree the game grows "
                       f"({len(named) - len(scenery)} of {len(named)}"
                       + (f"; scenery: {', '.join(scenery[:4])}" if scenery else "") + ")")
    spread = {sizes[t] for t in named if t in sizes}
    check(len(spread) >= 6, f"and they come in every size the game has "
                            f"({sorted(spread)})")

