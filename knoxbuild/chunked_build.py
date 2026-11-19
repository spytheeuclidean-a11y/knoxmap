"""Chunked building generation and stitching for very large maps.

Maps past ``BUILD_CHUNK_MIN_CELLS`` are split along exact 300-tile cell
boundaries into 4, 8, or 16+ parts depending on map size (with a ``HALO_TILES``
overlap margin), built one part at a time so peak RAM stays bounded, and
stitched back into the final bitmaps, ``.pzw``, CSVs, spawn map, and paper map.
"""
from __future__ import annotations

import csv
import json
import math
import os
import shutil

from PIL import Image

import knoxfiles
import knoxstop
from generator.chunked import _SubProjector
from generator.rendering.projection import Projector

from . import bitmaps, guns, placement as _placement, worldmap
from .population import build_spawn_map, official_population, save_footprints
from .settings import Settings
from .world import CELL_SIZE, Placement, origin, render_pzw, set_origin

BUILD_CHUNK_MIN_CELLS = 144  # > 12x12 cells (3600x3600 tiles)
HALO_TILES = 64


def should_chunk_build(cells_x: int, cells_y: int) -> bool:
    """Whether building generation should split into cell-aligned parts."""
    return cells_x * cells_y > BUILD_CHUNK_MIN_CELLS and cells_x >= 4 and cells_y >= 4


def _chunk_grid(cells_x: int, cells_y: int) -> tuple[int, int]:
    """Choose (nx, ny) grid splits: 4 parts (>12x12), 8 (50x50+), 16+ (100x100+)."""
    total = cells_x * cells_y
    if total >= 10000:
        nx = max(4, math.ceil(cells_x / 25))
        ny = max(4, math.ceil(cells_y / 25))
    elif total >= 2500:
        nx, ny = (4, 2) if cells_x >= cells_y else (2, 4)
    else:
        nx, ny = 2, 2
    return min(nx, cells_x), min(ny, cells_y)


def _split_cells(total_cells: int, parts: int) -> list[tuple[int, int]]:
    base, rem = divmod(total_cells, parts)
    out = []
    cur = 0
    for i in range(parts):
        n = base + (1 if i < rem else 0)
        out.append((cur * CELL_SIZE, n * CELL_SIZE))
        cur += n
    return out


def _quadrant_boxes(cells_x: int, cells_y: int, width: int, height: int,
                    halo: int = HALO_TILES) -> tuple[int, int, list[tuple[int, int, int, int, int, int, int, int, int]]]:
    """Return ``(nx, ny, boxes)`` of ``(qi, qx0, qy0, qw, qh, hx0, hy0, hw, hh)``."""
    nx, ny = _chunk_grid(cells_x, cells_y)
    x_splits = _split_cells(cells_x, nx)
    y_splits = _split_cells(cells_y, ny)
    # Clamp rightmost/bottommost slice to actual pixel width/height
    x_splits[-1] = (x_splits[-1][0], width - x_splits[-1][0])
    y_splits[-1] = (y_splits[-1][0], height - y_splits[-1][0])
    boxes = []
    qi = 0
    for qy0, qh in y_splits:
        for qx0, qw in x_splits:
            hx0 = max(0, qx0 - halo)
            hy0 = max(0, qy0 - halo)
            hx1 = min(width, qx0 + qw + halo)
            hy1 = min(height, qy0 + qh + halo)
            boxes.append((qi, qx0, qy0, qw, qh, hx0, hy0, hx1 - hx0, hy1 - hy0))
            qi += 1
    return nx, ny, boxes


def _feature_owner(feat: dict, proj: Projector,
                   boxes: list[tuple[int, int, int, int, int, int, int, int, int]],
                   nx: int, ny: int) -> int:
    """Assign each GeoJSON feature to exactly one part by its centroid."""
    geom = feat.get("geometry") or {}
    coords = geom.get("coordinates") or []
    ring = coords[0] if geom.get("type") == "Polygon" else (
        coords[0][0] if geom.get("type") == "MultiPolygon" and coords and coords[0] else []
    )
    if not ring:
        return 0
    pts = [proj.to_px(lat, lon) for lon, lat in ring]
    cx = sum(x for x, _ in pts) / len(pts)
    cy = sum(y for _, y in pts) / len(pts)
    for qi, qx0, qy0, qw, qh, *_ in boxes:
        col, row = qi % nx, qi // nx
        in_x = (qx0 <= cx < qx0 + qw) or (col == 0 and cx < qx0) or (col == nx - 1 and cx >= qx0 + qw)
        in_y = (qy0 <= cy < qy0 + qh) or (row == 0 and cy < qy0) or (row == ny - 1 and cy >= qy0 + qh)
        if in_x and in_y:
            return qi
    return 0


def build_chunked(
    out_dir: str,
    map_name: str,
    info: dict,
    geo: dict,
    proj: Projector,
    *,
    seed: int,
    min_size: int,
    max_size: int,
    settings: Settings,
    should_stop=None,
    progress=None,
) -> int:
    """Build buildings in 4 cell-aligned quadrants and stitch outputs at the end."""
    from .build import build

    def say(text: str, fraction: float | None = None) -> None:
        if progress:
            progress(text, fraction)

    map_origin = _placement.settled_origin(
        out_dir, info.get("map_name") or os.path.basename(out_dir.rstrip("\\/")),
        info["cells_x"], info["cells_y"])
    set_origin(map_origin)
    _placement.save(out_dir, map_origin)
    try:
        knoxfiles.write(os.path.join(out_dir, "settings.json"),
                        settings.to_dict(), indent=2)
    except OSError:
        pass

    bdir = os.path.join(out_dir, "buildings")
    os.makedirs(bdir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "tmx"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "lots"), exist_ok=True)

    nx, ny, boxes = _quadrant_boxes(info["cells_x"], info["cells_y"], proj.width, proj.height)
    total_parts = len(boxes)
    buckets: list[list[dict]] = [[] for _ in range(total_parts)]
    for feat in geo.get("features", []):
        buckets[_feature_owner(feat, proj, boxes, nx, ny)].append(feat)

    quad_root = os.path.join(out_dir, ".quadrants")
    if os.path.isdir(quad_root):
        shutil.rmtree(quad_root, ignore_errors=True)
    os.makedirs(quad_root, exist_ok=True)

    all_placements: list[Placement] = []
    all_zones: list = []
    all_rows: list[dict] = []
    all_left_out: list[dict] = []
    all_peopled: list = []
    all_outlines: list = []
    total_split = 0
    total_skipped_large = 0
    gunshops: set[str] = set()

    src_bmp = os.path.join(out_dir, f"{map_name}.bmp")
    src_veg = os.path.join(out_dir, f"{map_name}_veg.bmp")
    src_hier = os.path.join(out_dir, f"{map_name}_road_hierarchy.bmp")
    src_areas = os.path.join(out_dir, f"{map_name}_areas.geojson")
    src_points = os.path.join(out_dir, f"{map_name}_points.json")

    try:
        for qi, qx0, qy0, qw, qh, hx0, hy0, hw, hh in boxes:
            knoxstop.check(should_stop, "the buildings")
            say(f"Building part {qi + 1} of {total_parts}", qi * 0.85 / total_parts)
            q_name = f"{map_name}_q{qi}"
            q_dir = os.path.join(quad_root, f"q{qi}")
            os.makedirs(q_dir, exist_ok=True)

            sub_proj = _SubProjector(proj, hx0, hy0, hw, hh)
            s, w, n, e = sub_proj.latlon_bbox()
            q_info = {
                **info,
                "map_name": q_name,
                "width_tiles": hw,
                "height_tiles": hh,
                "cells_x": max(1, hw // CELL_SIZE),
                "cells_y": max(1, hh // CELL_SIZE),
                "bbox": {"south": s, "west": w, "north": n, "east": e},
            }
            knoxfiles.write(os.path.join(q_dir, f"{q_name}_info.json"), q_info, indent=2)
            knoxfiles.write(os.path.join(q_dir, f"{q_name}_buildings.geojson"),
                            {"type": "FeatureCollection", "features": buckets[qi]})

            for src_path, dst_name, bits in (
                (src_bmp, f"{q_name}.bmp", 24),
                (src_veg, f"{q_name}_veg.bmp", 24),
                (src_hier, f"{q_name}_road_hierarchy.bmp", 8),
            ):
                if os.path.isfile(src_path):
                    win = bitmaps.read_window(src_path, hx0, hy0, hw, hh, bits=bits)
                    Image.fromarray(win).save(os.path.join(q_dir, dst_name), format="BMP")

            if os.path.isfile(src_areas):
                shutil.copy2(src_areas, os.path.join(q_dir, f"{q_name}_areas.geojson"))
            if os.path.isfile(src_points):
                shutil.copy2(src_points, os.path.join(q_dir, f"{q_name}_points.json"))

            stitch: dict = {}

            def q_say(text: str, frac: float | None = None, _qi: int = qi) -> None:
                f = 0.0 if frac is None else max(0.0, min(1.0, frac))
                say(f"Part {_qi + 1}/{total_parts} — {text}", (_qi + f) * 0.85 / total_parts)

            rc = build(
                q_dir, seed=seed + qi, min_size=min_size, max_size=max_size,
                settings=settings, should_stop=should_stop, progress=q_say,
                _proj_override=sub_proj, _skip_chunked=True, _stitch_out=stitch,
            )
            if rc != 0:
                return rc

            # Stitch bitmaps (non-halo interior only) back into the global BMPs.
            ix0, iy0 = qx0 - hx0, qy0 - hy0
            q_bmp = os.path.join(q_dir, f"{q_name}.bmp")
            q_veg = os.path.join(q_dir, f"{q_name}_veg.bmp")
            if os.path.isfile(q_bmp) and os.path.isfile(src_bmp):
                bitmaps.write_window(src_bmp, qx0, qy0,
                                     bitmaps.read_window(q_bmp, ix0, iy0, qw, qh, bits=24))
            if os.path.isfile(q_veg) and os.path.isfile(src_veg):
                bitmaps.write_window(src_veg, qx0, qy0,
                                     bitmaps.read_window(q_veg, ix0, iy0, qw, qh, bits=24))

            # Move .tbx files into global buildings/ with unique q{qi}_ prefix.
            q_bdir = os.path.join(q_dir, "buildings")
            prefix = f"q{qi}_"
            if os.path.isdir(q_bdir):
                for fname in os.listdir(q_bdir):
                    if fname.endswith(".tbx"):
                        shutil.move(os.path.join(q_bdir, fname),
                                    os.path.join(bdir, prefix + fname))

            for p in stitch.get("placements", ()):
                if ix0 <= p.tile_x < ix0 + qw and iy0 <= p.tile_y < iy0 + qh:
                    rel_dir = os.path.dirname(p.tbx_path)
                    new_name = prefix + os.path.basename(p.tbx_path)
                    new_tbx = f"{rel_dir}/{new_name}" if rel_dir else new_name
                    all_placements.append(Placement(
                        tbx_path=new_tbx,
                        tile_x=p.tile_x + hx0, tile_y=p.tile_y + hy0,
                        width=p.width, height=p.height, on_top=p.on_top,
                    ))
            for z in stitch.get("zones", ()):
                zx0 = max(qx0, z.tile_x + hx0)
                zy0 = max(qy0, z.tile_y + hy0)
                zx1 = min(qx0 + qw, z.tile_x + hx0 + z.width)
                zy1 = min(qy0 + qh, z.tile_y + hy0 + z.height)
                if zx1 > zx0 and zy1 > zy0:
                    all_zones.append(type(z)(
                        kind=z.kind,
                        tile_x=zx0, tile_y=zy0, width=zx1 - zx0, height=zy1 - zy0,
                    ))
            for row in stitch.get("rows", ()):
                all_rows.append({
                    **row,
                    "file": prefix + row["file"],
                    "tile_x": int(row["tile_x"]) + hx0,
                    "tile_y": int(row["tile_y"]) + hy0,
                })
            for lo in stitch.get("left_out", ()):
                all_left_out.append({
                    **lo,
                    "tile_x": int(lo["tile_x"]) + hx0,
                    "tile_y": int(lo["tile_y"]) + hy0,
                })
            for x0, y0, mask, storeys, kind in stitch.get("peopled", ()):
                all_peopled.append((x0 + hx0, y0 + hy0, mask, storeys, kind))
            for ring, kind, name in stitch.get("outlines", ()):
                all_outlines.append(([(px + hx0, py + hy0) for px, py in ring], kind, name))
            for gf in stitch.get("gunshops", ()):
                gunshops.add(prefix + gf)
            total_split += int(stitch.get("split_large", 0))
            total_skipped_large += int(stitch.get("skipped_large", 0))

        say("Stitching quadrants together", 0.88)
        set_origin(map_origin)
        gun_cache = guns.write(
            out_dir, map_name,
            guns.choose(all_rows, gunshops) if settings.guaranteed_rifle else None,
            origin(), CELL_SIZE,
        )

        # Global spawn map, paper map, .pzw, and CSVs.
        spawn_img, pop = build_spawn_map(
            all_peopled, proj.width, proj.height, info["meters_per_tile"],
            src_bmp, settings, None,
        )
        knoxfiles.save(spawn_img, os.path.join(out_dir, f"{map_name}_ZombieSpawnMap.bmp"),
                       format="BMP")
        save_footprints(os.path.join(out_dir, f"{map_name}_footprints.npz"), all_peopled)
        pop["official"] = [p for p in official_population(out_dir, map_name) if p.get("inside")][:5]
        knoxfiles.write(os.path.join(out_dir, f"{map_name}_population.json"),
                        pop, indent=2, ensure_ascii=False)
        worldmap.write(out_dir, map_name, proj, info, all_outlines)

        pzw_path = os.path.join(out_dir, f"{map_name}.pzw")
        with open(pzw_path, "w", encoding="utf-8") as f:
            f.write(render_pzw(info["cells_x"], info["cells_y"],
                               f"{map_name}.bmp", all_placements, map_name,
                               project_dir=out_dir, zones=all_zones))

        csv_path = os.path.join(out_dir, f"{map_name}_placements.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            wtr = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()) if all_rows else ["file"])
            wtr.writeheader()
            wtr.writerows(all_rows)

        left_path = os.path.join(out_dir, f"{map_name}_left_out.csv")
        left_fields = ["reason", "tile_x", "tile_y", "lat", "lon", "tiles_wide",
                       "tiles_tall", "building", "name", "osm_id"]
        with open(left_path, "w", newline="", encoding="utf-8") as f:
            wtr = csv.DictWriter(f, fieldnames=left_fields)
            wtr.writeheader()
            wtr.writerows(sorted(all_left_out, key=lambda r: (r["tile_y"], r["tile_x"])))

        with open(os.path.join(out_dir, f"{map_name}_oversized.json"), "w", encoding="utf-8") as f:
            json.dump({"split": total_split, "skipped": total_skipped_large}, f)

        if gun_cache:
            print(f"guaranteed rifle      : {gun_cache['kind']} - "
                  f"{gun_cache['name'] or gun_cache['building']}")
        print(f"chunked build         : stitched {total_parts} parts ({nx}x{ny}) into {len(all_rows)} buildings")
        say("Done", 1.0)
        return 0
    finally:
        shutil.rmtree(quad_root, ignore_errors=True)
