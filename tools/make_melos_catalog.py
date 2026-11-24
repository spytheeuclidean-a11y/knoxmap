"""Build ``knoxbuild/data/melos_catalog.json.gz`` from Melos Tiles (workshop 2879745353)."""
from __future__ import annotations

import collections
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import knoxpaths
from tools.extract_tiles import PackReader, read_tiles_bin

FACING_TO_ORIENT = {"S": "N", "E": "W", "N": "S", "W": "E"}

# Glass doors in melos_tiles_doors_01 (doorTrans + doorW/N, 4-tile blocks).
MELOS_GLASS_DOORS = [0, 32, 40, 48, 56, 64]
SIGN_SHEETS = (
    "melos_tiles_shop_signs_01",
    "melos_tiles_shop_signs_02",
    "melos_tiles_shop_signs_04",
    "melos_tiles_shop_signs_05",
)


def _present_sprites(media: Path) -> set[str]:
    present: set[str] = set()
    for pname in ("melos_tiles_for_miles1.pack", "melos_tiles_for_miles2.pack"):
        pack = media / "texturepacks" / pname
        if not pack.is_file():
            continue
        r = PackReader(str(pack))
        try:
            for _pn, entries, read_png in r.pages():
                for ename, _x, _y, w, h, *_ in entries:
                    if w > 0 and h > 0 and "_" in ename:
                        sh, idx_s = ename.rsplit("_", 1)
                        if idx_s.isdigit():
                            present.add(f"{sh}_{int(idx_s):03d}")
                read_png()
        finally:
            r.f.close()
    return present


def build_melos_catalog(media: Path) -> dict:
    present = _present_sprites(media)
    all_sets = []
    for def_name in ("melos_tiles_for_miles_def1.tiles", "melos_tiles_for_miles_def2.tiles"):
        p = media / def_name
        if p.is_file():
            all_sets.extend(read_tiles_bin(str(p)))

    furniture: dict[str, dict] = {}
    layers: dict[str, str] = {}
    wall_art: list[str] = []
    plants: list[str] = []
    shelves: list[str] = []
    storefronts: list[list[dict]] = []
    signs: dict[str, list[list[str]]] = {"N": [], "W": []}
    ext_walls: dict[str, list[dict]] = collections.defaultdict(list)
    int_walls: list[dict] = []
    used_sheets: set[str] = set()

    def _wall_entry(sheet: str, tiles: dict[int, dict[str, str]], category: str) -> dict | None:
        w = next((i for i, p in sorted(tiles.items())
                  if "WallW" in p and "WindowW" not in p and "DoorWallW" not in p
                  and f"{sheet}_{i:03d}" in present), None)
        n = next((i for i, p in sorted(tiles.items())
                  if "WallN" in p and "WindowN" not in p and "DoorWallN" not in p
                  and f"{sheet}_{i:03d}" in present), None)
        nw = next((i for i, p in sorted(tiles.items())
                   if "WallNW" in p and f"{sheet}_{i:03d}" in present), None)
        se = next((i for i, p in sorted(tiles.items())
                   if "WallSE" in p and f"{sheet}_{i:03d}" in present), None)
        if 8 in tiles and "WindowW" in tiles[8] and f"{sheet}_008" in present:
            ww = 8
        else:
            ww = next((i for i, p in sorted(tiles.items())
                       if "WindowW" in p and f"{sheet}_{i:03d}" in present), None)
        if 9 in tiles and "WindowN" in tiles[9] and f"{sheet}_009" in present:
            wn = 9
        else:
            wn = next((i for i, p in sorted(tiles.items())
                       if "WindowN" in p and f"{sheet}_{i:03d}" in present), None)
        dw = next((i for i, p in sorted(tiles.items())
                   if "DoorWallW" in p and f"{sheet}_{i:03d}" in present), None)
        dn = next((i for i, p in sorted(tiles.items())
                   if "DoorWallN" in p and f"{sheet}_{i:03d}" in present), None)
        if None in (w, n, nw, se, ww, wn, dw, dn):
            return None
        wtiles = {
            "West": f"{sheet}_{w:03d}",
            "North": f"{sheet}_{n:03d}",
            "NorthWest": f"{sheet}_{nw:03d}",
            "SouthEast": f"{sheet}_{se:03d}",
            "WestWindow": f"{sheet}_{ww:03d}",
            "NorthWindow": f"{sheet}_{wn:03d}",
            "WestDoor": f"{sheet}_{dw:03d}",
            "NorthDoor": f"{sheet}_{dn:03d}",
        }
        for k in range(1, 20):
            wtiles[f"WestWindow{k}"] = wtiles["WestWindow"]
            wtiles[f"NorthWindow{k}"] = wtiles["NorthWindow"]
        return {"name": sheet, "entry": {"category": category, "tiles": wtiles}}

    for name, _fname, cols, _rows, tiles in all_sets:
        # 1. Wall art (paintings/posters/wall deco)
        if name.startswith("melos_tiles_wall_deco"):
            pieces: dict[tuple[str, str], dict[str, str]] = collections.defaultdict(dict)
            for idx, p in sorted(tiles.items()):
                if "SpriteGridPos" in p or p.get("MoveType") != "WallObject":
                    continue
                f = p.get("Facing")
                if f not in ("E", "S"):
                    continue
                tname = f"{name}_{idx:03d}"
                if tname in present:
                    pieces[(p.get("GroupName", ""), p.get("CustomName", ""))][FACING_TO_ORIENT[f]] = tname
            for by_o in pieces.values():
                if {"N", "W"} <= set(by_o):
                    role = f"melos_art_{len(wall_art)}"
                    furniture[role] = {o: {"0,0": by_o[o]} for o in ("N", "W")}
                    layers[role] = "WallFurniture"
                    wall_art.append(role)
                    used_sheets.add(name)

        # 2. Floor plants (Melos Large Plant & Pot Plant)
        elif name == "melos_tiles_gardencenter_plants_02":
            for idx, p in sorted(tiles.items()):
                if p.get("CustomName") in ("Melos Large Plant", "Pot Plant") and "SpriteGridPos" not in p:
                    tname = f"{name}_{idx:03d}"
                    if tname in present:
                        role = f"melos_plant_{len(plants)}"
                        furniture[role] = {o: {"0,0": tname} for o in ("W", "N", "E", "S")}
                        layers[role] = "Furniture"
                        plants.append(role)
                        used_sheets.add(name)

        # 3. Shelves (4-facing container=shelves)
        elif name in ("melos_tiles_furniture_storage_02", "melos_tiles_furniture_storage_02a"):
            pieces = collections.defaultdict(dict)
            for idx, p in sorted(tiles.items()):
                if p.get("container") == "shelves" and p.get("Facing") in FACING_TO_ORIENT and "SpriteGridPos" not in p:
                    tname = f"{name}_{idx:03d}"
                    if tname in present:
                        pieces[(p.get("GroupName", ""), p.get("CustomName", ""))][FACING_TO_ORIENT[p["Facing"]]] = tname
            for by_o in pieces.values():
                if len(by_o) == 4:
                    role = f"melos_shelves_{len(shelves)}"
                    furniture[role] = {o: {"0,0": by_o[o]} for o in ("W", "N", "E", "S")}
                    layers[role] = "Furniture"
                    shelves.append(role)
                    used_sheets.add(name)

        # 4. Commercial storefronts
        elif name.startswith("melos_tiles_walls_commercial_") and "overgrown" not in name:
            sheet_idx = len(storefronts) // 3
            door_base = MELOS_GLASS_DOORS[sheet_idx % len(MELOS_GLASS_DOORS)]
            door_tiles = {
                "West": f"melos_tiles_doors_01_{door_base:03d}",
                "North": f"melos_tiles_doors_01_{door_base + 1:03d}",
                "WestOpen": f"melos_tiles_doors_01_{door_base + 2:03d}",
                "NorthOpen": f"melos_tiles_doors_01_{door_base + 3:03d}",
            }
            if all(t in present for t in door_tiles.values()):
                doors = {"category": "doors", "tiles": door_tiles}
                for base_idx in (0, 16, 32):
                    req = (base_idx, base_idx + 1, base_idx + 2, base_idx + 3, 8, 9)
                    if not all(f"{name}_{i:03d}" in present for i in req):
                        continue
                    wtiles = {
                        "West": f"{name}_{base_idx:03d}",
                        "North": f"{name}_{base_idx + 1:03d}",
                        "NorthWest": f"{name}_{base_idx + 2:03d}",
                        "SouthEast": f"{name}_{base_idx + 3:03d}",
                        "WestWindow": f"{name}_{base_idx:03d}",
                        "NorthWindow": f"{name}_{base_idx + 1:03d}",
                        "WestDoor": f"{name}_008",
                        "NorthDoor": f"{name}_009",
                    }
                    for n in range(1, 20):
                        wtiles[f"WestWindow{n}"] = wtiles["WestWindow"]
                        wtiles[f"NorthWindow{n}"] = wtiles["NorthWindow"]
                    storefronts.append([
                        {"category": "exterior_walls", "tiles": wtiles},
                        {"category": "interior_walls", "tiles": dict(wtiles)},
                        doors,
                    ])
                    used_sheets.add(name)
                    used_sheets.add("melos_tiles_doors_01")

        # 5. Shop signs
        elif name in SIGN_SHEETS:
            by_gf: dict[tuple[str, str], list[int]] = collections.defaultdict(list)
            for idx in sorted(tiles):
                p = tiles[idx]
                g, f = p.get("GroupName"), p.get("Facing")
                if g and f in ("E", "S") and f"{name}_{idx:03d}" in present:
                    by_gf[(g, f)].append(idx)
            for (_g, f), idxs in by_gf.items():
                if len(idxs) >= 2 and all(
                    idxs[k + 1] == idxs[k] + 1 and idxs[k + 1] // cols == idxs[0] // cols
                    for k in range(len(idxs) - 1)
                ):
                    wall = FACING_TO_ORIENT[f]
                    seq = list(reversed(idxs)) if wall == "W" else idxs
                    signs[wall].append([f"{name}_{i:03d}" for i in seq])
                    used_sheets.add(name)

        # 6. Building exterior & interior walls
        elif name.startswith("melos_tiles_walls_") and not any(
            bad in name for bad in (
                "overgrown", "ruin", "damaged", "grime", "castle", "bunker",
                "basement", "detailing", "windowframes", "doorframes",
                "commercial", "bathroom", "double_doorframes", "slanted",
                "garage", "burnt", "soviet", "children",
            )
        ):
            if any(k in name for k in ("_interior_", "_livingroom_", "_indoor_")):
                entry = _wall_entry(name, tiles, "interior_walls")
                if entry:
                    int_walls.append(entry)
                    used_sheets.add(name)
            else:
                if "_brick_" in name:
                    grp = "brick"
                elif "_wood_" in name:
                    grp = "wood"
                elif "_plaster_" in name or "_concrete_" in name:
                    grp = "plaster"
                elif "_industry_" in name:
                    grp = "industrial"
                elif "_church_" in name:
                    grp = "church"
                elif any(k in name for k in ("_en_newburbs_", "_pert_add_", "_vanilla_add_")):
                    grp = "siding"
                else:
                    grp = None
                if grp:
                    entry = _wall_entry(name, tiles, "exterior_walls")
                    if entry:
                        ext_walls[grp].append(entry)
                        used_sheets.add(name)

    return {
        "FURNITURE": furniture,
        "FURNITURE_LAYERS": layers,
        "MELOS_WALL_ART": wall_art,
        "MELOS_PLANTS": plants,
        "MELOS_SHELVES": shelves,
        "MELOS_STOREFRONTS": storefronts,
        "MELOS_SIGNS": signs,
        "MELOS_EXTERIOR_WALLS": dict(ext_walls),
        "MELOS_INTERIOR_WALLS": int_walls,
        "MELOS_SHEETS": sorted(used_sheets),
    }


def main() -> int:
    media = knoxpaths.melos_tiles_media()
    if media is None:
        print("Melos Tiles not found on this PC.")
        return 1
    data = build_melos_catalog(media)
    out = ROOT / "knoxbuild" / "data" / "melos_catalog.json.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    print(
        f"Wrote {out} ({out.stat().st_size} bytes): "
        f"art={len(data['MELOS_WALL_ART'])}, plants={len(data['MELOS_PLANTS'])}, "
        f"shelves={len(data['MELOS_SHELVES'])}, storefronts={len(data['MELOS_STOREFRONTS'])}, "
        f"signs=N:{len(data['MELOS_SIGNS']['N'])}/W:{len(data['MELOS_SIGNS']['W'])}, "
        f"sheets={len(data['MELOS_SHEETS'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
