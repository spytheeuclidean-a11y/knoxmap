"""Run the whole generator on a made-up town, offline, and check the result.

    python tools/selftest.py [--keep] [--fast]

--fast (or -x) skips the checks that build a whole map a second time - the
giant outline and the knoxlots basement compile - which are most of a full
run's seventeen minutes. CI and a release still run them.

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


import os as _os



# The self-test fakes the Overpass servers, so it asks them rather than an extract.
_os.environ.setdefault("KNOXMAP_OSM_SOURCE", "overpass")


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
            elif (bx, by) == (0, 0):
                # A lone garage, for the door check: the street-facing
                # opening should come out as one wide garage door, not
                # three ordinary house doors side by side.
                feats.append(way({"building": "garage", "name": "Selftest Garage"},
                                 box(x0, y0, x0 + 14, y0 + 10)))
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
    # And one whose numbers are only an interpolation: a line saying 2 to 48
    # are along here, numbered at its two ends. Those ends are not houses.
    feats.append(way({"addr:interpolation": "even", "addr:street": "Range Row"},
                     [(270, 500), (390, 500)]))
    for number, x in (("2", 270), ("48", 390)):
        feats.append(OSMFeature(next(_ids), "node",
                                {"addr:housenumber": number, "addr:street": "Range Row"},
                                [_ll(x, 500)]))
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
    # The rest of the skyline: a silo over the farmyard, a transmission tower
    # on the ridge, and the two businesses that put a board up by the road.
    # The steeple is not here - a church does not carry its tower as its own
    # feature, and knoxbuild/landmarks.py puts one beside it.
    feats.append(way({"man_made": "silo", "building": "silo", "name": "Selftest Silo"},
                     box(340, 435, 346, 441)))
    feats.append(OSMFeature(next(_ids), "node", {"power": "tower",
                                                 "name": "Selftest Pylon"}, [_ll(470, 430)]))
    feats.append(way({"building": "yes", "tourism": "motel", "name": "Selftest Motel"},
                     box(168, 510, 190, 524)))
    # The same motel as a point inside its own outline, which is how a third of
    # them are mapped: one business, two targets, and only one board in front
    # of it (knoxbuild/landmarks.py).
    feats.append(OSMFeature(next(_ids), "node", {"tourism": "motel",
                                                 "name": "Selftest Motel"}, [_ll(179, 517)]))
    feats.append(way({"building": "yes", "amenity": "cinema", "drive_in": "yes",
                      "name": "Selftest Drive-In"}, box(248, 510, 272, 524)))
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




def _lot_tiles(path: str) -> list[tuple[int, int, int, str, str]]:
    """(x, y, level, layer, tile) from a tile-only lot, as the editor reads it."""
    text = open(path, encoding="utf-8").read()
    names = re.findall(r'<tile tile="([^"]+)"',
                       text.split("<user_tiles>")[1].split("</user_tiles>")[0])
    out = []
    for z, floor in enumerate(re.findall(r"<floor>(.*?)</floor>", text, re.S)):
        for layer, body in re.findall(r'<tiles layer="([^"]+)">(.*?)</tiles>', floor, re.S):
            for y, row in enumerate(body.strip().splitlines()):
                for x, value in enumerate(row.strip().rstrip(",").split(",")):
                    if value.strip() not in ("", "0"):
                        out.append((x, y, z, layer, names[int(value) - 1]))
    return out


def _project_lots(pzw_path: str, tag: str) -> list[tuple[int, int, str]]:
    """(x, y, tile) in map tiles for every lot of one kind, via the project.

    A lot's tbx is written in its own coordinates, so where it ended up is only
    answered by the .pzw: cell origin plus the lot's offset in the cell.
    """
    from knoxbuild.structures import CELL

    text = open(pzw_path, encoding="utf-8").read()
    out = []
    for cell in re.finditer(r'<cell x="(\d+)" y="(\d+)"[^>]*>(.*?)</cell>', text, re.S):
        cx, cy = int(cell.group(1)), int(cell.group(2))
        for lot in re.finditer(r'<lot x="(\d+)" y="(\d+)"[^>]*map="([^"]+)"',
                               cell.group(3)):
            if tag not in lot.group(3):
                continue
            path = os.path.join(os.path.dirname(pzw_path),
                                lot.group(3).replace("/", os.sep))
            for x, y, _z, _layer, tile in _lot_tiles(path):
                out.append((cx * CELL + int(lot.group(1)) + x,
                            cy * CELL + int(lot.group(2)) + y, tile))
    return out


class Checks:
    def __init__(self):
        self.failed = 0
        # --fast: the checks that render and build a whole town again look at
        # this and leave early. The cheap checks always run.
        self.fast = False

    def __call__(self, ok: bool, what: str) -> None:
        print(("  ok    " if ok else "  FAIL  ") + what)
        if not ok:
            self.failed += 1




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




def _dense(check, work, renderer, build, Settings) -> None:
    if check.fast:
        print("  skip  the dense town, rendered and built twice (--fast)")
        return
    import csv as _csv

    feats = dense_town()
    got = {}
    for name, true_map in (("true", 1), ("laid out", 0)):
        out = os.path.join(work, f"dense-{true_map}")
        renderer.render(feats, SOUTH, WEST, NORTH, EAST, meters_per_tile=2.0,
                        output_dir=out, map_name="dense")
        with contextlib.redirect_stdout(io.StringIO()):
            # Pinned to "smart": this is about how many houses the laid-out mode
            # drops, not about alignment, which changes how many footprints
            # survive in both modes (Rectilinear kept 85 of 117 here).
            build(out, settings=Settings(seed=1, true_map=true_map,
                                         building_alignment="smart"))
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
        build(laid_out, settings=Settings(seed=1, true_map=0,
                                          building_alignment="smart"))
    with open(os.path.join(laid_out, "dense_placements.csv"), encoding="utf-8") as f:
        again = list(_csv.DictReader(f))
    check([r["file"] for r in again] == [r["file"] for r in laid_rows],
          "the same town comes out of the same seed")




def _sides_for(grid, x, y, d):
    """The room ids either side of a wall edge; 0 is outside."""
    h, w = len(grid), len(grid[0])

    def at(px, py):
        return grid[py][px] if 0 <= px < w and 0 <= py < h else 0

    return (at(x - 1, y), at(x, y)) if d == "W" else (at(x, y - 1), at(x, y))




def main(argv: list[str]) -> int:
    # The compile checks drive a stand-in for WorldEd; they are about WorldEd's failures.
    os.environ["KNOXMAP_BACKEND"] = "worlded"
    keep = "--keep" in argv
    fast = "--fast" in argv or "-x" in argv
    check = Checks()
    check.fast = fast
    if fast:
        print("fast: skipping the whole-map rebuilds (--fast)")
    work = tempfile.mkdtemp(prefix="knoxmap-selftest-")
    os.environ["KNOXMAP_LOG_DIR"] = os.path.join(work, "logs")
    # The fake servers assume the shipped list, irrespective of the user's
    # selected server or persisted refusals. Keep every test write temporary.
    from generator import osm as _test_osm
    saved_urls = list(_test_osm.OVERPASS_ENDPOINTS)
    saved_state = [dict(d) for d in (_test_osm._cooling, _test_osm._fails, _test_osm._refused)]
    saved_refused_file = _test_osm._refused_file
    saved_source = os.environ.get("KNOXMAP_OSM_SOURCE")
    _test_osm.set_endpoints(None)
    for state in (_test_osm._cooling, _test_osm._fails, _test_osm._refused):
        state.clear()
    _test_osm._refused_file = lambda: os.path.join(work, "overpass_refused.json")
    os.environ["KNOXMAP_OSM_SOURCE"] = "overpass"
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
        # The same path, two more shapes: a silo is a drum with a cap, and a
        # transmission tower a mast with its arms out.
        sx, sy = proj.to_px(*_ll(343, 438))
        silo = [(x, y, z) for x, y, z, _l, _t in tiles
                if abs(x - sx) <= 5 and abs(y - sy) <= 5]
        silo_top = max((z for _x, _y, z in silo), default=0)
        drum = len({(x, y) for x, y, z in silo if z == silo_top - 1})
        cap = len({(x, y) for x, y, z in silo if z == silo_top})
        check(silo_top + 1 >= 5 and drum > 3 and cap == 1,
              f"the silo is a drum under a domed cap ({silo_top + 1} storeys, "
              f"{drum} squares wide, {cap} under the dome)")
        px_, py_ = proj.to_px(*_ll(470, 430))
        pylon = [(x, y, z, layer) for x, y, z, layer, _t in tiles
                 if abs(x - px_) <= 4 and abs(y - py_) <= 4]
        mast = {(x, y) for x, y, z, layer in pylon if layer == "Floor"}
        arms = {z for _x, _y, z, layer in pylon if layer == "Furniture"}
        check(len(mast) == 1 and len(arms) == 2
              and max((z for _x, _y, z, _l in pylon), default=0) >= 3,
              f"and the transmission tower is a mast with its arms out "
              f"({len(mast)} square up, {len(arms)} pairs of arms)")
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

        # The steeple and the boards by the road are put beside the buildings
        # (knoxbuild/landmarks.py): a tower on a church is not a feature of its
        # own on the map, and a motel's sign is a detail of the motel. Read
        # back from their lots, as the editor reads them.
        steeples = boards = 0
        landmark_lots = [n for n in os.listdir(os.path.join(out, "buildings"))
                         if n.endswith(".tbx") and "_landmarks_" in n]
        for name_ in landmark_lots:
            text = open(os.path.join(out, "buildings", name_), encoding="utf-8").read()
            boards += len(re.findall(r'layer="WallFurniture"', text))
            filled = [sum(value.strip() not in ("", "0")
                          for value in body.replace("\n", ",").split(","))
                      for body in re.findall(r'<tiles layer="Floor">(.*?)</tiles>',
                                             text, re.S)]
            steeples = max(steeples, len([f for f in filled if f]))
        check(steeples >= 5, f"the church has a steeple beside it ({steeples} storeys)")
        # Exactly one board each: the motel is mapped as an outline and a point
        # inside it, and two boards in front of one motel is the failure this
        # count catches.
        check(boards == 2,
              f"one board each for the motel and the drive-in ({boards})")
        # A board hangs on the WallFurniture layer with no wall on its square:
        # the tiles are furniture in BuildingFurniture.txt, not wall pieces, so
        # the editor has to accept the lot as it stands.
        import validate_tbx
        check(all(not validate_tbx.check(os.path.join(out, "buildings", n))
                  for n in landmark_lots),
              f"and a board with no wall behind it passes the editor "
              f"({len(landmark_lots)} landmark lots)")
        # A board hangs on its post. Every panel in a landmark lot must have a
        # column of post tiles on one of the squares the board covers, running
        # from the ground to the storey the board is on - otherwise the board
        # is a poster floating in the air, which is what the preview showed.
        from knoxbuild.landmarks import SIGN_POLE
        boards_seen = held = 0
        for name_ in landmark_lots:
            tiles_ = _lot_tiles(os.path.join(out, "buildings", name_))
            panels: dict[int, set] = {}
            columns: dict[tuple[int, int], set] = {}
            for x, y, z, layer, tile in tiles_:
                if layer == "WallFurniture":
                    panels.setdefault(z, set()).add((x, y))
                elif layer == "Furniture" and tile == SIGN_POLE:
                    columns.setdefault((x, y), set()).add(z)
            for z, cells in panels.items():
                boards_seen += 1
                if any(set(range(z + 1)) <= columns.get(cell, set())
                       for cell in cells):
                    held += 1
        check(boards_seen and held == boards_seen,
              f"every board stands on its post ({held} of {boards_seen} boards)")

        print("story vignettes")
        # The same props as the bases and the churchyards, put where the story
        # is: the way out of town held, the school turned into a refuge, a main
        # road stopped. Read back out of the project, so a checkpoint has to be
        # near the map's edge and a school's supplies near the school.
        import numpy as _np

        from knoxbuild.props import BARRICADE_X, BARRICADE_Y, CARRIAGEWAY, CRATES, DRUMS
        vignettes = _project_lots(os.path.join(out, "selftest.pzw"), "_vignettes")
        barriers = [(x, y) for x, y, tile in vignettes
                    if tile in BARRICADE_X + BARRICADE_Y]
        check(barriers, "the scenes are stamped from their props "
                        f"({len(vignettes)} props, {len(barriers)} barrier segments)")
        # A barrier across a road has to stand on the road: it is the one prop
        # here that goes onto the carriageway rather than beside it.
        on_road = [(x, y) for x, y in barriers
                   if tuple(ground.getpixel((x, y))) in CARRIAGEWAY]
        check(barriers and len(on_road) == len(barriers),
              f"and every barrier stands on the carriageway "
              f"({len(on_road)} of {len(barriers)} segments)")
        gw, gh = ground.width, ground.height
        # The checkpoint holds the way out of town, which is the outermost
        # tarmac there is - the border on a tight map, the edge of the built
        # area on one padded to a minimum size.
        ground_pixels = _np.asarray(ground)
        tarmac = _np.zeros((gh, gw), dtype=bool)
        for colour in CARRIAGEWAY:
            tarmac |= _np.all(ground_pixels == _np.array(colour), axis=2)
        ys, xs = _np.nonzero(tarmac)
        nearest = int(_np.minimum.reduce([xs, ys, gw - 1 - xs, gh - 1 - ys]).min())
        outer = min(min(x, y, gw - 1 - x, gh - 1 - y) for x, y in barriers) if barriers else -1
        check(barriers and outer <= nearest + 2,
              f"and a checkpoint holds the way out of town "
              f"({outer} tiles from the border, the outermost road)")
        places: list = []
        for x, y in barriers:
            for place in places:
                if abs(x - place[0]) < 20 and abs(y - place[1]) < 20:
                    break
            else:
                places.append((x, y))
        check(len(places) >= 2,
              f"and a main road away from the end is stopped too "
              f"({len(barriers)} segments in {len(places)} places)")
        import csv as _csv
        with open(os.path.join(out, "selftest_placements.csv"),
                  newline="", encoding="utf-8") as handle:
            school = next(row_ for row_ in _csv.DictReader(handle)
                          if row_["kind"] == "school")
        sx, sy = int(school["tile_x"]), int(school["tile_y"])
        sw, sh = int(school["width"]), int(school["height"])
        supplies = [(x, y) for x, y, tile in vignettes
                    if tile in CRATES + DRUMS
                    and sx - 6 <= x <= sx + sw + 6 and sy - 6 <= y <= sy + sh + 6]
        check(len(supplies) >= 3,
              f"and the school yard is an evacuation centre "
              f"({len(supplies)} crates and drums beside the school)")

        print("street props")
        # Painted into the vegetation bitmap, and placed by rules the map tools
        # read. Both halves have to be checked: a colour whose rule the tools
        # dropped - a blank cell in the sheet, as the utility pole once was -
        # is thrown away by WorldEd, and the prop silently disappears from the
        # map while the bitmap still looks right.
        #
        # A fresh clone ships the tools' Rules.txt without any of our rules, and
        # the generator gates every prop on that: until Setup has run there is
        # nothing to check, only the gate itself to prove. The rules are asked
        # for only once the file is one Setup has written.
        import knoxpaths
        from worlded import patch_rules_roads
        tools = knoxpaths.mapping_tools_dir()
        rules_text = knoxpaths.rules_text(tools) if tools else ""
        set_up = f"label = {patch_rules_roads.MARKER} " in rules_text
        prop_prefixes = ("Bench", "Kiosk", "Postbox", "Parking block",
                         "Manhole cover", "Utility pole", "Dog house", "Swing")
        prop_rules = [(label, colour) for label, colour, _tile, _layer
                      in patch_rules_roads.RULES if label.startswith(prop_prefixes)]
        with Image.open(os.path.join(out, "selftest_veg.bmp")) as veg_out:
            drawn = set(veg_out.convert("RGB").getdata())
        if set_up:
            for label, _colour in prop_rules:
                check(f"label = KnoxMap road {label}\n" in rules_text,
                      f"the map tools carry the {label} rule")
            for name, colours in (
                    ("utility poles", (C.UTILITY_POLE,)),
                    ("benches", C.BENCH_Y + C.BENCH_X),
                    ("kiosks", (C.KIOSK_N, C.KIOSK_E, C.KIOSK_S, C.KIOSK_W)),
                    ("collection boxes", (C.POSTBOX_N, C.POSTBOX_E,
                                          C.POSTBOX_S, C.POSTBOX_W)),
                    ("wheel stops", C.PARKING_BLOCK_X + C.PARKING_BLOCK_Y),
                    ("manhole covers", (C.MANHOLE,))):
                check(any(colour in drawn for colour in colours),
                      f"{name} reach the built map")
            # The tools drop a rule whose tile is blank, so a prop whose colour
            # is painted but whose rule is gone is the failure to catch, not
            # one or the other on its own.
            painted_without_rule = [label for label, colour in prop_rules
                                    if colour in drawn
                                    and f"label = KnoxMap road {label}\n" not in rules_text]
            check(not painted_without_rule,
                  "no prop is painted without a rule to place it")
        else:
            check(not any(colour in drawn for _label, colour in prop_rules),
                  "without the map tools' rules, no props are painted")
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
        check_garage_door(check, out)
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
        check_basements(check, out)
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
        check_long_streets(check)
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
            # Signs need the rule as well as the tiles, and a fresh clone has
            # the tiles' catalogue but none of our rules until Setup runs.
            from generator.rendering import furniture
            speed = sum(1 for c in pixels if c in C.SPEED_SIGNS.values())
            if furniture._mod_tiles_ready():
                check(speed > 0, f"speed limit signs on the streets ({speed})")
            else:
                check(speed == 0, "no speed limit signs until Setup writes their rule")
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
        from knoxbuild.worldmap import MAX_STREET_POINTS
        streets = ET.parse(os.path.join(out, "streets.xml")).getroot()
        longest = max((len(s.findall(".//point")) for s in streets.iter("street")), default=0)
        check(longest <= MAX_STREET_POINTS,
              f"no street on the paper map too long for the game to draw ({longest} points)")
        notes = open(os.path.join(out, "worldmap-annotations.lua"), encoding="utf-8").read()
        check("OpenStreetMap contributors" in notes, "OpenStreetMap credit on the in-game map")
        from knoxbuild import credits
        check(credits.MAKER in notes and all(n in notes for n in credits.CONTRIBUTORS),
              "KnoxMap and every contributor credited on the in-game map")
        check("Selftest School" in notes or "Selftest Church" in notes, "landmarks labelled")

        print("spawn map")
        pop = json.load(open(os.path.join(out, "selftest_population.json"), encoding="utf-8"))
        check(pop.get("residents", 0) > 0, f"people counted ({pop.get('residents')} residents)")

        print("app page")

        import app as knoxmap_app
        from web import common as webcommon
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
        from web import system as websystem
        was_lang = websystem.LANG_DIR
        websystem.LANG_DIR = lang_dir
        try:
            listed = client.get("/api/languages").get_json()
            words = client.get("/api/language/testish").get_json()
            missing = client.get("/api/language/klingon")
        finally:
            websystem.LANG_DIR = was_lang
        names = [x["name"] for x in listed["languages"]]
        check(names == ["English", "Testish"]
              and words["strings"] == {"Generate map": "Haritayi olustur", "1. Area": "1. Bolge"}
              and missing.status_code == 404,
              "a language file in lang/ is offered and read")

        import zipfile as _zip

        revealed = []
        was_open = _kl.open_folder
        was_output = webcommon.OUTPUT_DIR
        _kl.open_folder = lambda p=None: revealed.append(str(p)) or True
        webcommon.OUTPUT_DIR = Path(out).parent      # where this map really is
        try:
            saved = client.post("/api/save", json={"mapName": "selftest", "name": "zip"}).get_json()
            one = client.post("/api/save", json={"mapName": "selftest",
                                                 "name": "selftest_preview.png"}).get_json()
            escape = client.post("/api/save", json={"mapName": "selftest",
                                                    "name": "../../secrets.txt"})
        finally:
            _kl.open_folder = was_open
            webcommon.OUTPUT_DIR = was_output
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
        check_install_folder(check, out, work, client)
        check_build_audits(check, out)
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
        check_windows_open(check)
        check_trees_are_trees(check)
        check_shared_buildings(check, work)
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
        check_portable_presets(check, work)
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
        real = knoxmap_app.app.view_functions["maps.api_lots"]
        knoxmap_app.app.view_functions["maps.api_lots"] = _boom
        try:
            reply = client.get("/api/lots?map=x")
        finally:
            knoxmap_app.app.view_functions["maps.api_lots"] = real
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
        _test_osm.set_endpoints(saved_urls)
        for state, saved in zip((_test_osm._cooling, _test_osm._fails, _test_osm._refused), saved_state):
            state.clear()
            state.update(saved)
        _test_osm._refused_file = saved_refused_file
        if saved_source is None:
            os.environ.pop("KNOXMAP_OSM_SOURCE", None)
        else:
            os.environ["KNOXMAP_OSM_SOURCE"] = saved_source
        if keep:
            print(f"kept in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    print("selftest " + ("passed" if not check.failed else f"FAILED ({check.failed})"))
    return 1 if check.failed else 0


# The checks live in their own modules and import this one by
# name. Run as a script, this module is `__main__`; registering it
# under its own name lets those imports find it instead of loading
# a second copy (and running the fixture setup twice).
sys.modules.setdefault("selftest", sys.modules[__name__])
# Two ways in: `python tools/selftest.py` has tools/ on sys.path and no
# package, while the tests import this as tools.selftest. __package__ says
# which one this is, without a try/except that would also swallow a real
# ImportError from inside a check module.
# The check functions are imported by name, not with `*`: a star import hides
# every one of them from the linter (F405), so a renamed check only failed at
# run time, and it left the checks modules themselves unlintable.
if __package__:                      # imported as tools.selftest
    from .selftest_checks_a import (  # noqa: E402
        check_1_3_6, check_basements, check_compile_failures, check_dwellings,
        check_facing, check_garage_door, check_giant_outline, check_house_plan,
        check_kitchen_fit, check_long_streets, check_lots_apart, check_mapped_rooms,
        check_memory_guard, check_overpass_retry, check_overture, check_porch_lights,
        check_portable, check_procedural, check_qt_env, check_repair, check_rifle,
        check_rpath, check_split_large, check_squares, check_standing, check_stop,
        check_street_zombies, check_wall_corners, check_wall_styles,
    )
    from .selftest_checks_b import (  # noqa: E402
        check_big_bitmaps, check_box_any, check_build_audits, check_car_park_stalls,
        check_compile_records, check_compile_state, check_config_file,
        check_degenerate_footprints, check_flat_selection, check_ground_shares,
        check_health, check_install_clears, check_install_folder, check_mapstate,
        check_missing_drive, check_no_size_wall, check_odd_requests, check_odd_tags,
        check_osm_cache, check_osm_parse_tolerant, check_other_websites,
        check_overpass_blank, check_overpass_setting, check_portable_presets,
        check_prop_lattice, check_repeatable_seeds, check_saved_areas,
        check_shared_buildings, check_straight_roads, check_street_angle,
        check_throttle, check_trees_are_trees, check_updater, check_windows_open,
        check_workshop, check_worlded_size,
    )
else:                                # run as a script
    from selftest_checks_a import (  # noqa: E402
        check_1_3_6, check_basements, check_compile_failures, check_dwellings,
        check_facing, check_garage_door, check_giant_outline, check_house_plan,
        check_kitchen_fit, check_long_streets, check_lots_apart, check_mapped_rooms,
        check_memory_guard, check_overpass_retry, check_overture, check_porch_lights,
        check_portable, check_procedural, check_qt_env, check_repair, check_rifle,
        check_rpath, check_split_large, check_squares, check_standing, check_stop,
        check_street_zombies, check_wall_corners, check_wall_styles,
    )
    from selftest_checks_b import (  # noqa: E402
        check_big_bitmaps, check_box_any, check_build_audits, check_car_park_stalls,
        check_compile_records, check_compile_state, check_config_file,
        check_degenerate_footprints, check_flat_selection, check_ground_shares,
        check_health, check_install_clears, check_install_folder, check_mapstate,
        check_missing_drive, check_no_size_wall, check_odd_requests, check_odd_tags,
        check_osm_cache, check_osm_parse_tolerant, check_other_websites,
        check_overpass_blank, check_overpass_setting, check_portable_presets,
        check_prop_lattice, check_repeatable_seeds, check_saved_areas,
        check_shared_buildings, check_straight_roads, check_street_angle,
        check_throttle, check_trees_are_trees, check_updater, check_windows_open,
        check_workshop, check_worlded_size,
    )




if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(main(sys.argv))
