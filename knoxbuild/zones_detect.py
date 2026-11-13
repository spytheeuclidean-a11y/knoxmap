"""Zone detection (ParkingStall and TownZone) for Project KnoxMap."""
from __future__ import annotations

import numpy as np

from .settings import Settings

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
        img = source.convert("RGB")
    w, h = img.size
    px = img.load()
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
        return px[x, y] in ASPHALT

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
    if areas is not None:
        from shapely.geometry import box

        buildings = [box(p.tile_x, p.tile_y, p.tile_x + p.width, p.tile_y + p.height)
                     for p in placements]
        from shapely import STRtree
        built = STRtree(buildings) if buildings else None
        lots = [shape for shape, props in areas._items if props.get("category") == "parking"]
        hard = ASPHALT | {C.PALE_CONCRETE, C.PAVING}
        for lot in lots:
            bounds = tuple(int(v) for v in lot.bounds)
            for x, y, sw, sh in car_park_stalls(bounds, w, h):
                stall = box(x, y, x + sw, y + sh)
                if not lot.contains(stall):
                    continue
                if any(px[i, j] not in hard for i in (x, x + sw - 1)
                       for j in (y, y + sh - 1)):
                    continue
                if built is not None and any(buildings[int(i)].intersects(stall)
                                             for i in built.query(stall)):
                    continue
                if rng.random() > min(1.0, 0.55 * settings.parking_density):
                    continue
                taken.add((x // 8, y // 8))
                zones.append(Zone("ParkingStall", x, y, sw, sh))

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

    return zones
