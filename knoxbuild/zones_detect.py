"""Zone detection (ParkingStall and TownZone) for Project KnoxMap."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from .settings import Settings

if TYPE_CHECKING:
    from .world import Zone

STALL_W, STALL_H = 3, 5
CAR_PARK_LANE = 17            # two rows of 5, and a 7-tile lane


def car_park_stalls(bounds: tuple[int, int, int, int], w: int, h: int):
    """Where a stall could go in a car park with these bounds, as (x, y, sw, sh),
    in the order they are tried - only the ones that lie on the map.

    This used to walk the whole bounding box of the car park and throw away what
    was off the map afterwards. A car park a few hundred metres past the edge
    costs nothing; a polygon of the whole country mapped as one (it happens) was
    hundreds of millions of steps. Starting each run at the first position that
    can be on the map visits the same stalls in the same order."""
    x0, y0, x1, y1 = bounds
    across = (x1 - x0) >= (y1 - y0)          # rows run along the long side
    sw, sh = (STALL_W, STALL_H) if across else (STALL_H, STALL_W)
    # b runs along the rows, a across them; a + row is the offset of a stall's row.
    b_origin, b_len, b_map = (x0, x1 - x0, w) if across else (y0, y1 - y0, h)
    a_origin, a_len, a_map = (y0, y1 - y0, h) if across else (x0, x1 - x0, w)
    lane = CAR_PARK_LANE
    a_lo = max(0, -a_origin - STALL_H)
    a_start = -(-a_lo // lane) * lane
    a_stop = min(a_len, a_map - STALL_H - a_origin + 1)
    b_lo = max(0, -b_origin)
    b_start = -(-b_lo // STALL_W) * STALL_W
    b_stop = min(b_len, b_map - STALL_W - b_origin + 1)
    for a in range(a_start, a_stop, lane):
        for row in (0, STALL_H):
            for b in range(b_start, b_stop, STALL_W):
                x, y = (x0 + b, y0 + a + row) if across else (x0 + a + row, y0 + b)
                if 0 <= x and x + sw <= w and 0 <= y and y + sh <= h:
                    yield x, y, sw, sh


def _detect_zones(landscape_path: str, placements, rng_seed: int = 7,
                  settings: Settings | None = None, areas=None, drives=(),
                  keep_clear=(), road_hierarchy: np.ndarray | None = None,
                  veg_path: str | None = None):
    """Parking stalls along the roads, town zones over built-up ground.

    Without these the streets are bare: vehicles only ever spawn inside
    ParkingStall zones, and TownZone is what marks ground as urban. Vanilla
    Knox County ships 9694 of the former and 2715 of the latter.

    Stalls are found by scanning the landscape bitmap for asphalt that sits on
    a road *edge* — a stall in the middle of a carriageway would block it.
    """
    import random

    from PIL import Image

    from generator import pz_colors as C

    from .world import Zone

    ASPHALT = {C.MEDIUM_ASPHALT, C.DARK_ASPHALT, C.DARKEST_ASPHALT,
               C.DARK_POTHOLE, C.LIGHT_POTHOLE}

    settings = settings or Settings()
    rng = random.Random(rng_seed)
    zones: list[Zone] = []

    with Image.open(landscape_path) as source:
        land_arr = np.asarray(source.convert("RGB"))
    h, w = land_arr.shape[:2]
    land_key = _pack_rgb(land_arr)
    del land_arr
    asphalt_mask = np.isin(land_key, [_code(c) for c in ASPHALT])
    hard_mask = asphalt_mask | np.isin(land_key, [_code(C.PALE_CONCRETE), _code(C.PAVING)])
    if road_hierarchy is not None:
        road_hierarchy = road_hierarchy[:h, :w]

    def is_asphalt(x: int, y: int) -> bool:
        """Carriageway or car park, as opposed to the pavement beside it."""
        if not (0 <= x < w and 0 <= y < h):
            return False
        # The three street shades plus the two pothole shades that weather
        # them. Kerbs and paving slabs are deliberately out: parking a car on
        # the pavement is where stalls ended up once roads grew kerbs, because
        # any grey pixel in a wide range counted as road.
        return bool(asphalt_mask[y, x])

    STALL_W, STALL_H = 3, 5
    step = 14           # how often to consider a spot
    taken: set[tuple[int, int]] = set()

    # A car on most drives, as in Knox County.
    for x, y, sw, sh in drives:
        if rng.random() <= min(1.0, 0.6 * settings.parking_density):
            taken.add((x // 8, y // 8))
            zones.append(Zone("ParkingStall", x, y, sw, sh))

    # Car parks OpenStreetMap maps as such: rows of stalls across the whole of
    # each, two rows back to back and then a lane, the way a real one is laid
    # out. Sampling the tarmac every 14 tiles found at most a stall or two in
    # anything smaller than a supermarket's, so most car parks had no cars.
    painted_stalls: list[tuple[int, int, int, int, bool, bool]] = []
    island_boxes: list[tuple[int, int, int, int, bool]] = []
    extra_lamps: list[tuple[int, int, tuple[int, int, int]]] = []
    if areas is not None:
        from shapely.geometry import box

        buildings = [box(p.tile_x, p.tile_y, p.tile_x + p.width, p.tile_y + p.height)
                     for p in placements]
        from shapely import STRtree
        from shapely.prepared import prep
        built = STRtree(buildings) if buildings else None
        lots = [shape for shape, props in areas._items if props.get("category") == "parking"]
        for lot in lots:
            lot_prep = prep(lot)
            bounds = tuple(int(v) for v in lot.bounds)
            across = (bounds[2] - bounds[0]) >= (bounds[3] - bounds[1])
            a_origin = bounds[1] if across else bounds[0]
            b_origin = bounds[0] if across else bounds[1]
            lot_stalls: list[tuple[int, int, int, int, bool, int, int]] = []
            for x, y, sw, sh in car_park_stalls(bounds, w, h):
                stall = box(x, y, x + sw, y + sh)
                if not lot_prep.contains(stall):
                    continue
                if not (hard_mask[y, x] and hard_mask[y, x + sw - 1]
                        and hard_mask[y + sh - 1, x] and hard_mask[y + sh - 1, x + sw - 1]):
                    continue
                if built is not None and any(buildings[int(i)].intersects(stall)
                                             for i in built.query(stall)):
                    continue
                a_coord = y if across else x
                b_coord = x if across else y
                is_first_row = ((a_coord - a_origin) % CAR_PARK_LANE) == 0
                band = (a_coord - a_origin) // CAR_PARK_LANE
                slot = (b_coord - b_origin) // STALL_W
                lot_stalls.append((x, y, sw, sh, is_first_row, band, slot))

            if not lot_stalls:
                continue

            # Reserve a stall-pair column every 6 stalls along long rows as a
            # curbed divider island with a light pole and greenery.
            band_slots: dict[int, set[int]] = {}
            for _x, _y, _sw, _sh, _first, band, slot in lot_stalls:
                band_slots.setdefault(band, set()).add(slot)
            island_keys: set[tuple[int, int]] = set()
            for band, slots in band_slots.items():
                ordered = sorted(slots)
                run: list[int] = []
                for s in ordered:
                    if not run or s == run[-1] + 1:
                        run.append(s)
                    else:
                        if len(run) >= 6:
                            for idx in range(5, len(run) - 1, 6):
                                island_keys.add((band, run[idx]))
                        run = [s]
                if len(run) >= 6:
                    for idx in range(5, len(run) - 1, 6):
                        island_keys.add((band, run[idx]))

            grouped_islands: dict[tuple[int, int], list[tuple[int, int, int, int]]] = {}
            for x, y, sw, sh, is_first_row, band, slot in lot_stalls:
                if (band, slot) in island_keys:
                    grouped_islands.setdefault((band, slot), []).append((x, y, sw, sh))
                    continue
                painted_stalls.append((x, y, sw, sh, is_first_row, across))
                if rng.random() > min(1.0, 0.55 * settings.parking_density):
                    continue
                taken.add((x // 8, y // 8))
                zones.append(Zone("ParkingStall", x, y, sw, sh))

            for parts in grouped_islands.values():
                ix0 = min(p[0] for p in parts)
                iy0 = min(p[1] for p in parts)
                ix1 = max(p[0] + p[2] for p in parts)
                iy1 = max(p[1] + p[3] for p in parts)
                island_boxes.append((ix0, iy0, ix1, iy1, across))

            # Medium lots without divider islands still get edge light poles.
            if not grouped_islands and len(lot_stalls) >= 4:
                x0, y0, sw0, sh0, _, _, _ = lot_stalls[0]
                lx, ly = (x0, max(0, y0 - 1)) if across else (max(0, x0 - 1), y0)
                if 0 <= lx < w and 0 <= ly < h and hard_mask[ly, lx]:
                    lamp = C.LAMP_S if across else C.LAMP_E
                    extra_lamps.append((lx, ly, lamp))

    for y in range(4, h - STALL_H - 4, step):
        for x in range(4, w - STALL_W - 4, step):
            if not is_asphalt(x, y):
                continue
            kerbside = not (is_asphalt(x - 4, y) and is_asphalt(x + 4, y)
                            and is_asphalt(x, y - 4) and is_asphalt(x, y + 4))
            # Deep inside a wide expanse of tarmac: no carriageway is 16 tiles
            # across, so this is a car park, and its middle is exactly where
            # the cars go. The old rule skipped every interior spot to avoid
            # blocking a road, which left car parks themselves empty.
            car_park = (is_asphalt(x - 8, y) and is_asphalt(x + 8, y)
                        and is_asphalt(x, y - 8) and is_asphalt(x, y + 8))
            if not kerbside and not car_park:
                continue
            if car_park:
                rate = 0.75
            elif road_hierarchy is None or not road_hierarchy[y, x]:
                rate = 0.45
            else:
                rate = {
                    1: 0.0, 2: 0.18, 3: 0.55, 4: 0.38,
                    5: 0.28, 6: 0.16, 7: 0.08, 8: 0.02,
                }.get(int(road_hierarchy[y, x]), 0.45)
            chance = rate * settings.parking_density
            if rng.random() > chance:
                continue
            vertical = is_asphalt(x, y - 2) or is_asphalt(x, y + 2)
            sw, sh = (STALL_W, STALL_H) if vertical else (STALL_H, STALL_W)
            # Not on a petrol station's forecourt, where the pumps stand.
            if any(x < fx + fw and fx < x + sw and y < fy + fh and fy < y + sh
                   for fx, fy, fw, fh in keep_clear):
                continue
            key = (x // 8, y // 8)
            if key in taken:
                continue
            taken.add(key)
            zones.append(Zone("ParkingStall", x, y, sw, sh))

    # One town zone per cell that holds buildings, covering their extent with a
    # margin so gardens and the street frontage count as town too.
    by_cell: dict[tuple[int, int], list] = {}
    for p in placements:
        by_cell.setdefault((p.cell_x, p.cell_y), []).append(p)
    for (cx, cy), group in by_cell.items():
        x0 = max(0, min(p.tile_x for p in group) - 8)
        y0 = max(0, min(p.tile_y for p in group) - 8)
        x1 = min(w, max(p.tile_x + p.width for p in group) + 8)
        y1 = min(h, max(p.tile_y + p.height for p in group) + 8)
        # Clamp into the owning cell so the rectangle stays where it is written.
        x0 = max(x0, cx * 300)
        y0 = max(y0, cy * 300)
        x1 = min(x1, (cx + 1) * 300)
        y1 = min(y1, (cy + 1) * 300)
        if x1 - x0 > 4 and y1 - y0 > 4:
            zones.append(Zone("TownZone", x0, y0, x1 - x0, y1 - y0))

    veg_arr = None
    if veg_path:
        with Image.open(veg_path) as v_src:
            veg_arr = np.asarray(v_src.convert("RGB"))
    town_boxes = [(z.tile_x, z.tile_y, z.tile_x + z.width, z.tile_y + z.height)
                  for z in zones if z.kind == "TownZone"]
    if road_hierarchy is not None and settings.parking_density > 0:
        zones.extend(_highway_traffic_jams(
            is_asphalt, road_hierarchy, w, h, town_boxes, keep_clear, taken,
            settings.parking_density, rng))
    zones.extend(_forage_and_nav_zones(None, veg_arr, w, h, town_boxes,
                                       land_key=land_key))

    if veg_path and veg_arr is not None and (painted_stalls or island_boxes or extra_lamps):
        veg_out = _paint_parking_lots(
            veg_arr, painted_stalls, island_boxes, extra_lamps
        )
        if veg_out is not None:
            import knoxfiles
            knoxfiles.save(Image.fromarray(veg_out), veg_path, format="BMP")

    return zones


def _paint_parking_lots(
    veg_arr: np.ndarray,
    stalls: list[tuple[int, int, int, int, bool, bool]],
    islands: list[tuple[int, int, int, int, bool]] = (),
    extra_lamps: list[tuple[int, int, tuple[int, int, int]]] = (),
) -> np.ndarray | None:
    """Paint bay lines, wheel stops, divider islands, and light poles onto _veg.bmp."""
    from generator import pz_colors as C

    h, w = veg_arr.shape[:2]
    out = veg_arr.copy()
    empty = np.all(out == C.VEG_NOTHING, axis=2)
    stall_origins = {(x, y) for x, y, _sw, _sh, _first, _across in stalls}
    changed = False

    def put(tx: int, ty: int, colour: tuple[int, int, int]) -> None:
        nonlocal changed
        if 0 <= tx < w and 0 <= ty < h and empty[ty, tx]:
            out[ty, tx] = colour
            empty[ty, tx] = False
            changed = True

    for x, y, sw, sh, is_first_row, across in stalls:
        if across:
            head_y = y + sh - 1 if is_first_row else y
            for dx, colour in enumerate(C.PARKING_BLOCK_X):
                put(x + dx, head_y, colour)
            dy_range = range(0, sh - 1) if is_first_row else range(1, sh)
            right_end = (x + sw, y) not in stall_origins
            for dy in dy_range:
                put(x, y + dy, C.EDGE_LINE_W)
                if right_end:
                    put(x + sw - 1, y + dy, C.EDGE_LINE_E)
        else:
            head_x = x + sw - 1 if is_first_row else x
            for dy, colour in enumerate(C.PARKING_BLOCK_Y):
                put(head_x, y + dy, colour)
            dx_range = range(0, sw - 1) if is_first_row else range(1, sw)
            bottom_end = (x, y + sh) not in stall_origins
            for dx in dx_range:
                put(x + dx, y, C.EDGE_LINE_N)
                if bottom_end:
                    put(x + dx, y + sh - 1, C.EDGE_LINE_S)

    for ix0, iy0, ix1, iy1, across in islands:
        if ix1 - ix0 < 3 or iy1 - iy0 < 3:
            continue
        # Perimeter curbstones around the divider island.
        put(ix0, iy0, C.KERB_NW)
        put(ix1 - 1, iy0, C.KERB_NE)
        put(ix0, iy1 - 1, C.KERB_SW)
        put(ix1 - 1, iy1 - 1, C.KERB_SE)
        for tx in range(ix0 + 1, ix1 - 1):
            put(tx, iy0, C.KERB_N)
            put(tx, iy1 - 1, C.KERB_S)
        for ty in range(iy0 + 1, iy1 - 1):
            put(ix0, ty, C.KERB_W)
            put(ix1 - 1, ty, C.KERB_E)

        # Interior: light pole in the middle, greenery/tree along the spine.
        cx, cy = (ix0 + ix1) // 2, (iy0 + iy1) // 2
        put(cx, cy, C.LAMP_S if across else C.LAMP_E)
        if across:
            for ty in range(iy0 + 1, iy1 - 1):
                if ty == cy:
                    continue
                put(cx, ty, C.TREE_SMALL if ty in (iy0 + 2, iy1 - 3) else C.BUSHES)
        else:
            for tx in range(ix0 + 1, ix1 - 1):
                if tx == cx:
                    continue
                put(tx, cy, C.TREE_SMALL if tx in (ix0 + 2, ix1 - 3) else C.BUSHES)

    for lx, ly, lamp in extra_lamps:
        put(lx, ly, lamp)

    return out if changed else None


JAM_SPACING = 90              # tiles between highway pileups so routes stay drivable


def _in_boxes(x: int, y: int, sw: int, sh: int,
              boxes: list[tuple[int, int, int, int]]) -> bool:
    return any(x < x1 and x0 < x + sw and y < y1 and y0 < y + sh
               for x0, y0, x1, y1 in boxes)


def _highway_traffic_jams(is_asphalt, road_hierarchy: np.ndarray,
                          w: int, h: int,
                          town_boxes: list[tuple[int, int, int, int]],
                          keep_clear: list[tuple[int, int, int, int]],
                          taken: set[tuple[int, int]],
                          parking_density: float, rng) -> list[Zone]:
    """Place occasional multi-car ParkingStall clusters on major roads out of town.

    PZ spawns traffic jams, burnt wrecks and roadside emergency vehicles from
    ParkingStall zones; placing small staggered clusters on secondary/primary/
    trunk/motorway stretches outside TownZone turns empty highways into
    believable evacuation bottlenecks.
    """
    from .world import Zone

    jams: list[Zone] = []
    centers: list[tuple[int, int]] = []
    rh_h, rh_w = road_hierarchy.shape[:2]
    clear_boxes = [(fx, fy, fx + fw, fy + fh) for fx, fy, fw, fh in keep_clear]

    for y in range(6, h - STALL_H - 6, 12):
        for x in range(6, w - STALL_W - 6, 12):
            if y >= rh_h or x >= rh_w:
                continue
            tier = int(road_hierarchy[y, x])
            if tier < 5 or not is_asphalt(x, y):
                continue
            if _in_boxes(x, y, STALL_W, STALL_H, town_boxes):
                continue
            if any((x - cx) ** 2 + (y - cy) ** 2 < JAM_SPACING ** 2
                   for cx, cy in centers):
                continue
            chance = (0.16 if tier >= 6 else 0.07) * parking_density
            if rng.random() > chance:
                continue

            vertical = is_asphalt(x, y - 3) and is_asphalt(x, y + 3)
            sw, sh = (STALL_W, STALL_H) if vertical else (STALL_H, STALL_W)
            # Stagger 2-3 vehicles along and slightly across the carriageway.
            offsets = ([(0, 0), (-2, 5), (2, -5)] if vertical
                       else [(0, 0), (5, -2), (-5, 2)])
            count = rng.choice((2, 3))
            placed_here = 0
            for dx, dy in offsets[:count]:
                sx, sy = x + dx, y + dy
                if not (4 <= sx < w - sw - 4 and 4 <= sy < h - sh - 4):
                    continue
                if not is_asphalt(sx, sy):
                    continue
                if _in_boxes(sx, sy, sw, sh, clear_boxes):
                    continue
                key = (sx // 8, sy // 8)
                if key in taken:
                    continue
                taken.add(key)
                jams.append(Zone("ParkingStall", sx, sy, sw, sh))
                placed_here += 1
            if placed_here:
                centers.append((x, y))
    return jams


FORAGE_BLOCK = 20


def _pack_rgb(arr: np.ndarray) -> np.ndarray:
    return ((arr[:, :, 0].astype(np.uint32) << 16)
            | (arr[:, :, 1].astype(np.uint32) << 8)
            | arr[:, :, 2].astype(np.uint32))


def _code(c: tuple[int, int, int]) -> int:
    return (c[0] << 16) | (c[1] << 8) | c[2]


def _forage_and_nav_zones(land_arr: np.ndarray | None, veg_arr: np.ndarray | None,
                          w: int, h: int,
                          town_boxes: list[tuple[int, int, int, int]],
                          land_key: np.ndarray | None = None):
    """Emit per-cell Forest, DeepForest, Vegitation, Farm, and Nav zones."""
    from generator import pz_colors as C
    from .world import CELL_SIZE, Zone

    if land_key is None:
        land_key = _pack_rgb(land_arr)
    veg_key = _pack_rgb(veg_arr) if veg_arr is not None else None

    nav_mask = np.isin(land_key, [_code(C.MEDIUM_ASPHALT), _code(C.DARKEST_ASPHALT),
                                  _code(C.DARK_ASPHALT), _code(C.DARK_POTHOLE),
                                  _code(C.LIGHT_POTHOLE)])
    farm_mask = np.isin(land_key, [_code(C.DIRT_ROWS_H), _code(C.DIRT_ROWS_V)])
    grass_mask = np.isin(land_key, [_code(C.DARK_GRASS), _code(C.MEDIUM_GRASS),
                                    _code(C.LIGHT_GRASS)])
    if veg_key is not None:
        farm_mask |= np.isin(veg_key, [_code(C.CORN_1), _code(C.CORN_2)])
        deep_mask = np.isin(veg_key, [_code(C.TREES), _code(C.TREE_BIG),
                                      _code(C.TREE_HUGE), _code(C.TREE_GIANT)])
        forest_mask = deep_mask | np.isin(veg_key, [
            _code(C.TREES_DARK_GRASS), _code(C.SPARSE_TREES),
            _code(C.BUSHES_TREES_DARK_GRASS), _code(C.TREE_SMALL),
        ])
        veg_open_mask = grass_mask | np.isin(veg_key, [
            _code(C.BUSHES), _code(C.DENSE_BUSHES_GRASS),
            _code(C.SHORT_GRASS), _code(C.GRASS_ON_DARK), _code(C.FLOWERS),
        ])
    else:
        deep_mask = np.zeros((h, w), dtype=bool)
        forest_mask = np.zeros((h, w), dtype=bool)
        veg_open_mask = grass_mask

    town_mask = np.zeros((h, w), dtype=bool)
    for tx0, ty0, tx1, ty1 in town_boxes:
        town_mask[max(0, ty0):min(h, ty1), max(0, tx0):min(w, tx1)] = True

    out: list[Zone] = []
    bs = FORAGE_BLOCK
    for cy in range((h + CELL_SIZE - 1) // CELL_SIZE):
        cy0, cy1 = cy * CELL_SIZE, min(h, (cy + 1) * CELL_SIZE)
        for cx in range((w + CELL_SIZE - 1) // CELL_SIZE):
            cx0, cx1 = cx * CELL_SIZE, min(w, (cx + 1) * CELL_SIZE)
            for y0 in range(cy0, cy1, bs):
                y1 = min(cy1, y0 + bs)
                run_kind: str | None = None
                run_x0 = cx0
                run_x1 = cx0
                for x0 in range(cx0, cx1, bs):
                    x1 = min(cx1, x0 + bs)
                    area = (x1 - x0) * (y1 - y0)
                    if area <= 0:
                        continue
                    kind: str | None = None
                    if int(nav_mask[y0:y1, x0:x1].sum()) * 100 >= area * 35:
                        kind = "Nav"
                    elif int(deep_mask[y0:y1, x0:x1].sum()) * 100 >= area * 60:
                        kind = "DeepForest"
                    elif int(forest_mask[y0:y1, x0:x1].sum()) * 100 >= area * 25:
                        kind = "Forest"
                    elif int(farm_mask[y0:y1, x0:x1].sum()) * 100 >= area * 35:
                        kind = "Farm"
                    elif (not town_mask[y0:y1, x0:x1].any()
                          and int(veg_open_mask[y0:y1, x0:x1].sum()) * 100 >= area * 50):
                        kind = "Vegitation"

                    if kind == run_kind:
                        run_x1 = x1
                    else:
                        if run_kind is not None:
                            out.append(Zone(run_kind, run_x0, y0, run_x1 - run_x0, y1 - y0))
                        run_kind = kind
                        run_x0 = x0
                        run_x1 = x1
                if run_kind is not None:
                    out.append(Zone(run_kind, run_x0, y0, run_x1 - run_x0, y1 - y0))
    return out
