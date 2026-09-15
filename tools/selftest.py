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
            else:
                for k in range(3):
                    feats.append(way({"building": "house"},
                                     box(x0 + k * 20, y0, x0 + k * 20 + 12, y0 + 10)))
    feats.append(way({"leisure": "park", "name": "Selftest Park"}, box(410, 410, 470, 470)))
    # A river with a bridge carrying High Street over it.
    feats.append(way({"waterway": "river", "name": "Selftest River"}, [(560, 30), (560, 600)]))
    feats.append(way({"natural": "water", "water": "river"}, box(550, 0, 572, 600)))
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


def main(argv: list[str]) -> int:
    keep = "--keep" in argv
    check = Checks()
    work = tempfile.mkdtemp(prefix="knoxmap-selftest-")
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
        tbx = [os.path.join(out, "buildings", f) for f in os.listdir(os.path.join(out, "buildings"))]
        import validate_tbx
        bad = [p for p in tbx if validate_tbx.check(p)]
        check(not bad, f"every building passes the editor's rules ({len(tbx)} files)")
        tall = [p for p in tbx if "fixtures_escalators_01_49" in open(p, encoding="utf-8").read()]
        check(len(tall) >= 1, "the seven-storey flats have a lift")
        school = [p for p in tbx if 'InternalName="classroom"' in open(p, encoding="utf-8").read()]
        check(len(school) >= 1, "the school has classrooms")
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
        houses_tbx = [t for p, t in zip(tbx, texts) if "_fences_" not in p]
        check(all(gaps_match(t) for t in houses_tbx), "flat roofs wall in the top floor with its own material")
        check(any("_fences_" in p for p in tbx), "back yards are fenced")
        yard = Image.open(os.path.join(out, "selftest.bmp")).convert("RGB")
        stone = sum(1 for c in (yard.get_flattened_data() if hasattr(yard, "get_flattened_data") else yard.getdata())
                    if c == C.PAVING_STONE)
        check(stone > 50, f"front paths laid ({stone} stone tiles)")
        check(any('RoofType="Peak' in t for t in texts), "houses have pitched roofs")
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
        check(not re.search(r'(?:href|src)="https?://', page.get_data(as_text=True)),
              "page loads nothing from other sites")

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
        open(os.path.join(lots, "0_0.lotheader"), "wb").write(b"LOTH\x01\x00\x00\x00signs_erika_01_000\n")
        with contextlib.redirect_stdout(io.StringIO()):
            mod_root, cells, extras = package(out, "Selftest: Town", "selftest", mods_dir=mods)
        info_erika = open(os.path.join(mod_root, "mod.info"), encoding="utf-8").read()
        check("require=\\Erikas_Tiles" in info_erika, "a map using Erika's tiles requires Erika's Tiles")
        check(os.path.isdir(os.path.join(mod_root, "common", "media", "maps", "Selftest Town")),
              "map folder name is safe for Windows")
        lua_dir = os.path.join(mod_root, "common", "media", "lua", "shared", "KnoxMap")
        selector = [open(os.path.join(lua_dir, f), encoding="utf-8").read()
                    for f in os.listdir(lua_dir)] if os.path.isdir(lua_dir) else []
        check(selector and "Selftest School" in selector[0] and "OnGameBoot" in selector[0]
              and selector[0].count("{") == selector[0].count("}"),
              "Spawn Selector gets the town and its landmarks")
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
