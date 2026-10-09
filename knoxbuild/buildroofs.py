"""Roof and ceiling tiles of a building, from its .tbx.

Worked out from WorldEd's output for roofs of each type and depth (every piece has a name
in the tile sets). Nothing is drawn for the north (or west) half of a peaked roof, only the
half facing the camera, plus caps at the gable ends.

  PeakWE / PeakNS (45 degrees): the half-slope at the south (east) end: `k` rows (columns) of
      Slope S1..Sk (E1..Ek) counted from the edge, and for depths with a "Point5" one more
      row of the ridge tile. Depth Three is always three. The caps stand on the roof's first
      column (row) and on the one just past its last: Fall tiles from the north (west), the
      ridge, then Rise tiles to the south (east); depth Three fills the rows between with the
      gap tile. A cap shares its square with the slope tile, under it.
  Peak30WE / Peak30NS (30 degrees): slopes on both sides of a middle row (column) of peak
      tiles; caps the same way.
  Peak30Quad: rings of slope and corner tiles round a centre tile (a rectangle is cut from the square of its longer side).
  FlatTop: the top tile on every square, on the level above the storey it is listed on.
  Ceilings: the ceiling tile goes on the level above a room wherever that level has no room.
"""
from __future__ import annotations

_DEPTHS = {"Point5": (0, True), "One": (1, False), "OnePoint5": (1, True), "Two": (2, False),
           "TwoPoint5": (2, True), "Three": (3, False)}
_PT5 = {"Point5": "Pt5", "OnePoint5": "OnePt5", "TwoPoint5": "TwoPt5"}


def roof_squares(entry, attrs: dict, o: dict) -> dict[tuple[int, int], list[str]]:
    """{(x, y): [cap, slope]} for a pitched roof object, over its rectangle and the
    squares just outside it where its caps stand. `entry(n)` gives tile entry n."""
    kind, depth = o.get("RoofType", ""), o.get("Depth", "")
    x0, y0, w, h = int(o["x"]), int(o["y"]), int(o["width"]), int(o["height"])
    slopes = entry(o.get("SlopeTiles", attrs.get("RoofSlope", 0)))
    caps = entry(o.get("CapTiles", attrs.get("RoofCap", 0)))
    capped = {d: o.get("capped" + d, "false") == "true" for d in "WNES"}
    if depth == "Three" and kind in ("PeakWE", "PeakNS"):
        # A roof too narrow for three rows each side takes the depth that fits.
        across = h if kind == "PeakWE" else w
        depth = {1: "Point5", 2: "One", 3: "OnePoint5", 4: "Two", 5: "TwoPoint5"}.get(across, "Three")
    slope_tiles: dict[tuple[int, int], str] = {}
    cap_tiles: dict[tuple[int, int], str] = {}

    def slope(x, y, enum):
        slope_tiles[(x, y)] = slopes.get(enum, "")

    def cap(x, y, enum):
        cap_tiles[(x, y)] = caps.get(enum, "")

    if kind in ("PeakWE", "PeakNS") and depth in _DEPTHS:
        k, ridge = _DEPTHS[depth]
        pt5 = _PT5.get(depth, "")
        if kind == "PeakWE":
            for i in range(1, k + 1):                      # the south half, from the edge
                for x in range(x0, x0 + w):
                    slope(x, y0 + h - i, f"SlopeS{i}")
            if ridge:
                for x in range(x0, x0 + w):
                    slope(x, y0 + h - k - 1, f"Slope{pt5}S")
            for side, x in (("W", x0), ("E", x0 + w)):
                if not capped[side]:
                    continue
                for i in range(1, k + 1):
                    cap(x, y0 + i - 1, f"CapFallE{i}")
                    cap(x, y0 + h - i, f"CapRiseE{i}")
                if ridge:
                    cap(x, y0 + k, f"Peak{pt5}E")
                if depth == "Three":
                    for y in range(y0 + k, y0 + h - k):
                        cap(x, y, "CapGapE3")
        else:
            for i in range(1, k + 1):                      # the east half, from the edge
                for y in range(y0, y0 + h):
                    slope(x0 + w - i, y, f"SlopeE{i}")
            if ridge:
                for y in range(y0, y0 + h):
                    slope(x0 + w - k - 1, y, f"Slope{pt5}E")
            for side, y in (("N", y0), ("S", y0 + h)):
                if not capped[side]:
                    continue
                for i in range(1, k + 1):
                    cap(x0 + i - 1, y, f"CapRiseS{i}")
                    cap(x0 + w - i, y, f"CapFallS{i}")
                if ridge:
                    cap(x0 + k, y, f"Peak{pt5}S")
                if depth == "Three":
                    for x in range(x0 + k, x0 + w - k):
                        cap(x, y, "CapGapS3")
    elif kind == "Peak30WE":
        # WorldEd limits the cross-section to eleven squares, anchored at the north edge.
        h = min(h, 11)
        k = (h - 1) // 2
        for x in range(x0, x0 + w):
            for i in range(1, k + 1):
                slope(x, y0 + i - 1, f"Slope30N{i}")
                slope(x, y0 + h - i, f"Slope30S{i}")
            slope(x, y0 + k, f"Peak30NS{k + 1}")
        for side, x in (("W", x0), ("E", x0 + w)):
            if capped[side]:
                for i in range(1, k + 1):
                    cap(x, y0 + i - 1, f"CapSlope30FallE{i}")
                    cap(x, y0 + h - i, f"CapSlope30RiseE{i}")
                cap(x, y0 + k, f"CapPeak30E{k + 1}")
    elif kind == "Peak30NS":
        # WorldEd limits the cross-section to eleven squares, anchored at the west edge.
        w = min(w, 11)
        k = (w - 1) // 2
        for y in range(y0, y0 + h):
            for i in range(1, k + 1):
                slope(x0 + i - 1, y, f"Slope30W{i}")
                slope(x0 + w - i, y, f"Slope30E{i}")
            slope(x0 + k, y, f"Peak30WE{k + 1}")
        for side, y in (("N", y0), ("S", y0 + h)):
            if capped[side]:
                for i in range(1, k + 1):
                    cap(x0 + i - 1, y, f"CapSlope30RiseS{i}")
                    cap(x0 + w - i, y, f"CapSlope30FallS{i}")
                cap(x0 + k, y, f"CapPeak30S{k + 1}")
    elif kind == "Peak30Quad" and max(w, h) % 2 == 1:
        # A rectangle is cut from the square of its longer side, anchored at the north-west.
        side = max(w, h)
        k = (side - 1) // 2
        for dy in range(h):
            for dx in range(w):
                r = min(dx, dy, side - 1 - dx, side - 1 - dy) + 1
                if r == k + 1:
                    enum = f"Peak30Quad{k + 1}"
                else:
                    top, bottom, left, right = dy == r - 1, dy == side - r, dx == r - 1, dx == side - r
                    if top and left:
                        enum = f"OuterSlope30NW{r}"
                    elif top and right:
                        enum = f"OuterSlope30NE{r}"
                    elif bottom and left:
                        enum = f"OuterSlope30SW{r}"
                    elif bottom and right:
                        enum = f"OuterSlope30SE{r}"
                    elif top:
                        enum = f"Slope30N{r}"
                    elif bottom:
                        enum = f"Slope30S{r}"
                    elif left:
                        enum = f"Slope30W{r}"
                    else:
                        enum = f"Slope30E{r}"
                slope(x0 + dx, y0 + dy, enum)
    out: dict[tuple[int, int], list[str]] = {}
    for pos in set(cap_tiles) | set(slope_tiles):
        out[pos] = [t for t in (cap_tiles.get(pos, ""), slope_tiles.get(pos, "")) if t]
    return out


def flat_squares(entry, attrs: dict, o: dict) -> dict[tuple[int, int], list[str]]:
    x0, y0, w, h = int(o["x"]), int(o["y"]), int(o["width"]), int(o["height"])
    tops = entry(o.get("TopTiles", attrs.get("RoofTop", 0)))
    tile = tops.get("West1") or next(iter(tops.values()), "")
    return {(x, y): [tile] for y in range(y0, y0 + h) for x in range(x0, x0 + w)} if tile else {}


def band_squares(entry, attrs: dict, o: dict) -> dict[tuple[int, int], list[str]]:
    """The flat band between the slopes of a depth Three peaked roof more than six
    squares across: top tiles on the level above the roof (the rows or columns left
    after three each side)."""
    kind = o.get("RoofType", "")
    if o.get("Depth") != "Three" or kind not in ("PeakWE", "PeakNS"):
        return {}
    x0, y0, w, h = int(o["x"]), int(o["y"]), int(o["width"]), int(o["height"])
    tops = entry(o.get("TopTiles", attrs.get("RoofTop", 0)))
    tile = tops.get("West1" if kind == "PeakWE" else "North1") or next(iter(tops.values()), "")
    if not tile:
        return {}
    if kind == "PeakWE":
        return {(x, y): [tile] for y in range(y0 + 3, y0 + h - 3) for x in range(x0, x0 + w)}
    return {(x, y): [tile] for y in range(y0, y0 + h) for x in range(x0 + 3, x0 + w - 3)}


def upper_layers(entry, attrs: dict, width: int, height: int, room_defs: list[dict],
                 floors: list, z: int) -> tuple[dict, dict]:
    """What goes on level z because of the storey below it and the roofs: ceilings over the
    rooms of level z - 1 where level z has no room, flat roofs listed on level z - 1 (they
    replace the ceiling), and the pitched roofs listed on level z. `floors` have .rooms and
    .objects."""
    out: dict[tuple[int, int], list[str]] = {}
    if z >= 1:
        below = floors[z - 1]
        here = floors[z].rooms if z < len(floors) else None
        for y in range(height):
            for x in range(width):
                r = below.rooms[y][x]
                if r > 0 and (here is None or here[y][x] == 0):
                    ceiling = entry(room_defs[r - 1].get("Ceiling", 0)).get("Ceiling", "")
                    if ceiling:
                        out[(x, y)] = [ceiling]
        for o in below.objects:
            if o.get("type") == "roof" and o.get("RoofType") == "FlatTop":
                out.update(flat_squares(entry, attrs, o))
            elif o.get("type") == "roof":
                out.update(band_squares(entry, attrs, o))
    pitched: dict[tuple[int, int], list[str]] = {}
    if z < len(floors):
        for o in floors[z].objects:
            if o.get("type") == "roof" and o.get("RoofType") != "FlatTop":
                for pos, tiles in roof_squares(entry, attrs, o).items():
                    pitched[pos] = pitched.get(pos, []) + tiles
    return out, pitched


def upper_level(entry, attrs: dict, width: int, height: int, room_defs: list[dict],
                floors: list, z: int) -> dict[tuple[int, int], list[str]]:
    """Combined upper layers, for callers that only need the roof and ceiling tiles."""
    out, pitched = upper_layers(entry, attrs, width, height, room_defs, floors, z)
    for pos, tiles in pitched.items():
        out[pos] = out.get(pos, []) + tiles
    return out
