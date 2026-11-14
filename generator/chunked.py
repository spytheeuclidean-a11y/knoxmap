"""Chunked terrain rendering and streaming BMP stitching for very large maps.

Maps past ``CHUNK_MIN_CELLS`` split along exact 300-tile cell boundaries into
``CHUNK_CELLS x CHUNK_CELLS`` chunks with a ``HALO_TILES`` overlap margin.
Each chunk renders through ``renderer.render`` using a ``_SubProjector`` pinned
to the global UTM/rotation frame, crops its halo, and streams pixels directly
into pre-allocated 24-bit/8-bit BMP files on disk so peak RAM stays bounded by
one chunk regardless of total map size.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import struct
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

import knoxfiles
import knoxstop

from . import pz_colors as C
from .osm import OSMFeature, classify
from .rendering.geometry import _is_polygon
from .rendering.noise import global_tile_offset
from .rendering.projection import Projector, _inside, shape_px

_log = logging.getLogger(__name__)

CHUNK_CELLS = 8
CHUNK_MIN_CELLS = 144  # > 12x12 cells (3600x3600 tiles)
HALO_TILES = 64
MAX_PREVIEW_DIM = 2048


class _SubProjector:
    """Slice of a global ``Projector`` shifted by ``(offset_x, offset_y)`` tiles."""

    def __init__(self, parent: Projector, offset_x: int, offset_y: int,
                 width: int, height: int) -> None:
        self._parent = parent
        self.offset_x = int(offset_x)
        self.offset_y = int(offset_y)
        self.width = int(width)
        self.height = int(height)
        self.meters_per_tile = parent.meters_per_tile
        self.rotation = parent.rotation
        self.min_x_m = parent.min_x_m + self.offset_x * parent.meters_per_tile
        self.min_y_m = parent.min_y_m + (
            parent.height - (self.offset_y + self.height)
        ) * parent.meters_per_tile
        s, w, n, e = self.latlon_bbox()
        self.south, self.west, self.north, self.east = s, w, n, e

    def to_px(self, lat: float, lon: float) -> tuple[float, float]:
        gx, gy = self._parent.to_px(lat, lon)
        return gx - self.offset_x, gy - self.offset_y

    def to_latlon(self, px: float, py: float) -> tuple[float, float]:
        return self._parent.to_latlon(px + self.offset_x, py + self.offset_y)

    def cell_grid(self) -> tuple[int, int]:
        return self.width // C.CELL_SIZE, self.height // C.CELL_SIZE

    def latlon_bbox(self) -> tuple[float, float, float, float]:
        corners = [
            self.to_latlon(0.0, 0.0),
            self.to_latlon(float(self.width), 0.0),
            self.to_latlon(0.0, float(self.height)),
            self.to_latlon(float(self.width), float(self.height)),
        ]
        lats = [p[0] for p in corners]
        lons = [p[1] for p in corners]
        return min(lats), min(lons), max(lats), max(lons)


class _BmpWriter:
    """Streaming bottom-up uncompressed BMP writer (24-bit RGB or 8-bit grayscale)."""

    def __init__(self, path: str, width: int, height: int, bpp: int = 3,
                 resume: bool = False) -> None:
        if bpp not in (1, 3):
            raise ValueError(f"unsupported bpp: {bpp}")
        self.path = path
        self.width = int(width)
        self.height = int(height)
        self.bpp = bpp
        self.stride = ((self.width * bpp + 3) // 4) * 4
        palette_size = 1024 if bpp == 1 else 0
        self.header_size = 54 + palette_size
        pixel_bytes = self.stride * self.height
        self.file_size = self.header_size + pixel_bytes

        if resume and os.path.exists(path) and os.path.getsize(path) == self.file_size:
            self._f = open(path, "r+b")
            return

        self._f = open(path, "w+b")
        file_hdr = struct.pack("<2sIHHI", b"BM", self.file_size, 0, 0, self.header_size)
        info_hdr = struct.pack(
            "<IiiHHIIiiII",
            40, self.width, self.height, 1, bpp * 8, 0, pixel_bytes, 0, 0,
            256 if bpp == 1 else 0, 0,
        )
        self._f.write(file_hdr)
        self._f.write(info_hdr)
        if bpp == 1:
            self._f.write(bytes(b for i in range(256) for b in (i, i, i, 0)))
        if pixel_bytes > 0:
            self._f.seek(self.file_size - 1)
            self._f.write(b"\x00")

    def write_block(self, x0: int, y0: int, arr: np.ndarray) -> None:
        bh, bw = arr.shape[:2]
        if bh <= 0 or bw <= 0:
            return
        raw = np.ascontiguousarray(arr[:, :, ::-1]) if self.bpp == 3 else np.ascontiguousarray(arr)
        row_bytes = bw * self.bpp
        for dy in range(bh):
            bmp_y = self.height - 1 - (y0 + dy)
            self._f.seek(self.header_size + bmp_y * self.stride + x0 * self.bpp)
            self._f.write(raw[dy].tobytes()[:row_bytes])

    def flush(self) -> None:
        self._f.flush()

    def close(self) -> None:
        self._f.flush()
        self._f.close()

    def __enter__(self) -> "_BmpWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _link_or_copy(src: str, dst: str) -> None:
    """Hardlink ``dst`` to ``src`` when on the same volume, else copy."""
    try:
        if os.path.exists(dst):
            os.remove(dst)
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _feature_px_bbox(feat: OSMFeature, proj: Projector) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    if feat.kind == "relation" and feat.members:
        for pts, _role in feat.members:
            for lat, lon in pts:
                px, py = proj.to_px(lat, lon)
                xs.append(px)
                ys.append(py)
    else:
        for lat, lon in feat.geometry:
            px, py = proj.to_px(lat, lon)
            xs.append(px)
            ys.append(py)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def render_chunked(
    features: list[OSMFeature],
    south: float, west: float, north: float, east: float,
    meters_per_tile: float,
    output_dir: str, map_name: str,
    *,
    spawn_density: int = 10,
    tree_density: float = 1.0,
    forest_density: float = 1.0,
    forest_stand_m: float = 60,
    forest_edge_m: float = 30,
    forest_params=None,
    rotation: float = 0.0,
    osm_cache: str | None = None,
    osm_bbox: tuple[float, float, float, float] | None = None,
    shape: dict | None = None,
    straight_roads: int = 0,
    include_proposed_roads: int = 0,
    fill_frontage: int = 0,
    terrain_only: int = 0,
    landcover_for=None,
    climate=None,
    winter_look: str = "auto",
    elevation=None,
    elevation_span=None,
    should_stop=None,
    progress=None,
    chunk_cells: int = CHUNK_CELLS,
    halo_tiles: int = HALO_TILES,
):
    """Render a large map in cell-aligned chunks and stitch outputs to ``output_dir``."""
    from . import renderer as R
    from .rendering.forest_params import ForestParams

    t0 = time.perf_counter()
    full_proj = Projector.build(south, west, north, east, meters_per_tile, rotation)
    cells_x, cells_y = full_proj.cell_grid()
    fp = forest_params or ForestParams(stand_m=forest_stand_m, edge_m=forest_edge_m)

    feats = [copy.copy(f) for f in features]
    road_layout = int(straight_roads or 0)
    if road_layout == 0:
        from .mapped_roads import clean_mapped_roads
        clean_mapped_roads(feats, full_proj, classify, _is_polygon)
    elif road_layout == 5:
        from .vanilla_grid import apply_vanilla_grid
        apply_vanilla_grid(feats, full_proj, classify, _is_polygon)
    elif road_layout in (1, 4):
        from .octilinear import straighten_roads
        straighten_roads(feats, full_proj, classify, _is_polygon, clean=True)
    elif road_layout in R.ROAD_LAYOUTS:
        from .octilinear import apply_road_graph, graph_path
        from .roadgraph.route import route
        graph = route(feats, full_proj, R.ROAD_LAYOUTS[road_layout], shape)
        knoxfiles.write(graph_path(output_dir, map_name), graph)
        apply_road_graph(feats, graph, full_proj)

    bboxes = [_feature_px_bbox(f, full_proj) for f in feats]

    os.makedirs(output_dir, exist_ok=True)
    landscape_path = os.path.join(output_dir, f"{map_name}.bmp")
    veg_path = os.path.join(output_dir, f"{map_name}_veg.bmp")
    hierarchy_path = os.path.join(output_dir, f"{map_name}_road_hierarchy.bmp")
    spawn_path = os.path.join(output_dir, f"{map_name}_ZombieSpawnMap.bmp")
    preview_path = os.path.join(output_dir, f"{map_name}_preview.png")

    w, h = full_proj.width, full_proj.height
    spawn_w = w // C.SPAWN_MAP_SCALE
    spawn_h = h // C.SPAWN_MAP_SCALE
    prev_scale = min(1.0, MAX_PREVIEW_DIM / max(w, h))
    prev_w = max(1, int(round(w * prev_scale)))
    prev_h = max(1, int(round(h * prev_scale)))
    preview_img = Image.new("RGB", (prev_w, prev_h), C.DARK_GRASS)

    x_ranges = [(c, min(cells_x, c + chunk_cells)) for c in range(0, cells_x, chunk_cells)]
    y_ranges = [(r, min(cells_y, r + chunk_cells)) for r in range(0, cells_y, chunk_cells)]
    total_chunks = len(x_ranges) * len(y_ranges)

    merged_bridges = 0
    merged_monuments = 0
    merged_tiles: list = []
    seen_struct_tiles: set[tuple[int, int, str]] = set()
    pad = max(96, halo_tiles)

    ckpt_path = os.path.join(output_dir, f".{map_name}_chunks.json")
    preview_wip_path = os.path.join(output_dir, f".{map_name}_preview_wip.png")
    sig = {
        "w": w, "h": h, "cells_x": cells_x, "cells_y": cells_y,
        "chunk_cells": chunk_cells, "halo_tiles": halo_tiles,
        "meters_per_tile": float(meters_per_tile), "rotation": float(rotation),
        "road_layout": road_layout, "terrain_only": int(terrain_only or 0),
        "spawn_density": int(spawn_density),
        "tree_density": float(tree_density),
        "forest_density": float(forest_density),
    }
    done_chunks: set[tuple[int, int]] = set()
    can_resume = False
    if os.path.exists(ckpt_path):
        try:
            with open(ckpt_path, encoding="utf-8") as cf:
                ckpt = json.load(cf)
            if ckpt.get("sig") == sig:
                done_chunks = {(int(c[0]), int(c[1])) for c in ckpt.get("done", [])}
                merged_bridges = int(ckpt.get("bridges", 0))
                merged_monuments = int(ckpt.get("monuments", 0))
                merged_tiles = list(ckpt.get("tiles", []))
                seen_struct_tiles = {
                    (int(r["x"]), int(r["y"]), r.get("layer", ""))
                    for r in merged_tiles
                }
                if os.path.exists(preview_wip_path):
                    with Image.open(preview_wip_path) as pim:
                        preview_img = pim.convert("RGB")
                can_resume = True
                _log.info("chunked %s: resuming with %d/%d chunks already done",
                          map_name, len(done_chunks), total_chunks)
        except Exception:
            done_chunks.clear()
            can_resume = False

    def _stitch_chunk(idx, cx0, cy0, x0, y0, x1, y1, hx0, hy0,
                      land_arr, veg_arr, hier_arr, sp_arr, st):
        nonlocal merged_bridges, merged_monuments
        w_land.write_block(x0, y0, land_arr)
        w_veg.write_block(x0, y0, veg_arr)
        w_hier.write_block(x0, y0, hier_arr)
        w_spawn.write_block(x0 // C.SPAWN_MAP_SCALE, y0 // C.SPAWN_MAP_SCALE, sp_arr)

        px0 = int(round(x0 * prev_scale))
        py0 = int(round(y0 * prev_scale))
        px1 = min(prev_w, max(px0 + 1, int(round(x1 * prev_scale))))
        py1 = min(prev_h, max(py0 + 1, int(round(y1 * prev_scale))))
        p_arr = land_arr.copy()
        vm = veg_arr.any(axis=2)
        p_arr[vm] = veg_arr[vm]
        chunk_prev = Image.fromarray(p_arr).resize(
            (px1 - px0, py1 - py0), Image.Resampling.BILINEAR
        )
        preview_img.paste(chunk_prev, (px0, py0))

        if st:
            merged_bridges += int(st.get("bridges", 0))
            merged_monuments += int(st.get("monuments", 0))
            for row in st.get("tiles", []):
                gx = row["x"] + hx0
                gy = row["y"] + hy0
                if x0 <= gx < x1 and y0 <= gy < y1:
                    tkey = (gx, gy, row.get("layer", ""))
                    if tkey not in seen_struct_tiles:
                        seen_struct_tiles.add(tkey)
                        merged_tiles.append({**row, "x": gx, "y": gy})

        w_land.flush()
        w_veg.flush()
        w_hier.flush()
        w_spawn.flush()
        done_chunks.add((cx0, cy0))
        knoxfiles.save(preview_img, preview_wip_path, format="PNG")
        knoxfiles.write(ckpt_path, {
            "sig": sig,
            "done": sorted(done_chunks),
            "bridges": merged_bridges,
            "monuments": merged_monuments,
            "tiles": merged_tiles,
        })
        _log.info("chunked %s: stitched chunk %d/%d (%d..%d, %d..%d)",
                  map_name, idx, total_chunks, x0, x1, y0, y1)

    with (
        _BmpWriter(landscape_path, w, h, 3, resume=can_resume) as w_land,
        _BmpWriter(veg_path, w, h, 3, resume=can_resume) as w_veg,
        _BmpWriter(hierarchy_path, w, h, 1, resume=can_resume) as w_hier,
        _BmpWriter(spawn_path, spawn_w, spawn_h, 1, resume=can_resume) as w_spawn,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="chunk_stitch") as stitch_pool,
    ):
        pending_stitch = None
        idx = 0
        for cy0, cy1 in y_ranges:
            for cx0, cx1 in x_ranges:
                idx += 1
                if (cx0, cy0) in done_chunks:
                    if progress:
                        progress(idx, total_chunks)
                    continue
                knoxstop.check(should_stop, "the terrain")
                if progress:
                    progress(idx - 1, total_chunks)

                x0, y0 = cx0 * C.CELL_SIZE, cy0 * C.CELL_SIZE
                x1, y1 = cx1 * C.CELL_SIZE, cy1 * C.CELL_SIZE
                hx0, hy0 = max(0, x0 - halo_tiles), max(0, y0 - halo_tiles)
                hx1, hy1 = min(w, x1 + halo_tiles), min(h, y1 + halo_tiles)

                sub_proj = _SubProjector(full_proj, hx0, hy0, hx1 - hx0, hy1 - hy0)
                chunk_feats = [
                    f for f, bb in zip(feats, bboxes)
                    if bb is None or (
                        bb[2] >= hx0 - pad and bb[0] <= hx1 + pad
                        and bb[3] >= hy0 - pad and bb[1] <= hy1 + pad
                    )
                ]
                chunk_out: dict = {}
                with global_tile_offset(hx0, hy0):
                    R.render(
                        chunk_feats,
                        sub_proj.south, sub_proj.west, sub_proj.north, sub_proj.east,
                        meters_per_tile=meters_per_tile,
                        output_dir=output_dir,
                        map_name="chunk",
                        spawn_density=spawn_density,
                        tree_density=tree_density,
                        forest_density=forest_density,
                        forest_params=fp,
                        rotation=rotation,
                        shape=shape,
                        straight_roads=road_layout,
                        include_proposed_roads=include_proposed_roads,
                        fill_frontage=fill_frontage,
                        terrain_only=terrain_only,
                        landcover_for=landcover_for,
                        climate=climate,
                        winter_look=winter_look,
                        elevation=elevation,
                        elevation_span=elevation_span,
                        should_stop=should_stop,
                        _proj_override=sub_proj,
                        _skip_road_layout=True,
                        _write_geojson=False,
                        _chunk_out=chunk_out,
                    )

                cx_off, cy_off = x0 - hx0, y0 - hy0
                cw, ch = x1 - x0, y1 - y0
                crop_box = (cx_off, cy_off, cx_off + cw, cy_off + ch)
                land_arr = np.ascontiguousarray(
                    np.asarray(chunk_out["landscape"].crop(crop_box).convert("RGB"))
                )
                veg_arr = np.ascontiguousarray(
                    np.asarray(chunk_out["vegetation"].crop(crop_box).convert("RGB"))
                )
                hier_arr = np.ascontiguousarray(
                    np.asarray(chunk_out["hierarchy"].crop(crop_box).convert("L"))
                )
                scx, scy = cx_off // C.SPAWN_MAP_SCALE, cy_off // C.SPAWN_MAP_SCALE
                sw, sh = (x1 - x0) // C.SPAWN_MAP_SCALE, (y1 - y0) // C.SPAWN_MAP_SCALE
                sp_arr = np.ascontiguousarray(
                    np.asarray(
                        chunk_out["spawn_map"]
                        .crop((scx, scy, scx + sw, scy + sh))
                        .convert("L")
                    )
                )
                st = chunk_out.get("structures")
                chunk_out.clear()

                if pending_stitch is not None:
                    pending_stitch.result()
                pending_stitch = stitch_pool.submit(
                    _stitch_chunk, idx, cx0, cy0, x0, y0, x1, y1, hx0, hy0,
                    land_arr, veg_arr, hier_arr, sp_arr, st,
                )

        if pending_stitch is not None:
            pending_stitch.result()

    for tmp_f in (ckpt_path, preview_wip_path):
        if os.path.exists(tmp_f):
            try:
                os.remove(tmp_f)
            except OSError:
                pass

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [
            pool.submit(_link_or_copy, landscape_path,
                        os.path.join(output_dir, f"{map_name}_ground_base.bmp")),
            pool.submit(_link_or_copy, veg_path,
                        os.path.join(output_dir, f"{map_name}_veg_base.bmp")),
            pool.submit(knoxfiles.save, preview_img, preview_path, format="PNG"),
        ]
        for fut in futs:
            fut.result()

    # Global GeoJSON/metadata outputs matching renderer.render().
    clip = shape_px(shape, full_proj)
    buckets, building_feats, indoor_feats, fence_feats, gate_feats, place_feats = (
        R._collect_global_features(feats, full_proj, clip, include_proposed_roads)
    )
    knoxfiles.write(os.path.join(output_dir, f"{map_name}_buildings.geojson"),
                    R._buildings_geojson(building_feats, indoor_feats))
    knoxfiles.write(os.path.join(output_dir, f"{map_name}_areas.geojson"),
                    R._areas_geojson(buckets))
    knoxfiles.write(os.path.join(output_dir, f"{map_name}_fences.geojson"),
                    R._lines_geojson([f for f in fence_feats
                                      if clip is None or _inside(f, full_proj, clip)]))
    knoxfiles.write(os.path.join(output_dir, f"{map_name}_fence_openings.geojson"),
                    R._openings_geojson(gate_feats, buckets))
    knoxfiles.write(os.path.join(output_dir, f"{map_name}_structures.json"),
                    {"bridges": merged_bridges, "monuments": merged_monuments,
                     "tiles": merged_tiles})
    knoxfiles.write(os.path.join(output_dir, f"{map_name}_places.json"),
                    R._places(place_feats, full_proj), ensure_ascii=False)

    meta_path = os.path.join(output_dir, f"{map_name}_info.json")
    knoxfiles.write(meta_path, {
        "map_name": map_name,
        "bbox": {"south": south, "west": west, "north": north, "east": east},
        "rotation": rotation,
        "osm_cache": osm_cache,
        "straight_roads": road_layout,
        "include_proposed_roads": include_proposed_roads,
        "osm_bbox": list(osm_bbox) if osm_bbox else None,
        "shape": shape,
        "meters_per_tile": meters_per_tile,
        "width_tiles": w,
        "height_tiles": h,
        "cells_x": cells_x,
        "cells_y": cells_y,
        "spawn_density_max": spawn_density,
        "building_count": len(building_feats),
        "feature_count": sum(len(v) for v in buckets.values()),
        "houses_from_addresses": 0,
        "houses_infilled": 0,
        "sheds_infilled": 0,
        "chunked": True,
        "chunk_count": total_chunks,
        "guide_reference": "Thuztor Mapping Guide v0.2",
    }, indent=2)

    _log.info("chunked %s: %dx%d (%d chunks) finished in %.2fs",
              map_name, w, h, total_chunks, time.perf_counter() - t0)
    return R.RenderResult(
        landscape_path=landscape_path,
        vegetation_path=veg_path,
        spawn_map_path=spawn_path,
        preview_path=preview_path,
        buildings_geojson_path=os.path.join(output_dir, f"{map_name}_buildings.geojson"),
        meta_path=meta_path,
        width=w,
        height=h,
        cells_x=cells_x,
        cells_y=cells_y,
    )
