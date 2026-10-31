"""Serialise a Plan to BuildingEd's .tbx format.

Schema taken from BuildingWriter in timbaker/buildinged. Two index conventions
differ and are easy to get backwards:

    tile entries   1-based, and 0 means "none"   (entryIndex)
    furniture      0-based, no null form         (furnitureIndex)

Element order inside <building> follows the writer: tile entries, furniture,
user_tiles, used_tiles, used_furniture, the <room> list, then <floor>.
"""
from __future__ import annotations

import random
import zlib
from xml.sax.saxutils import escape, quoteattr

from . import catalog as C
from .layout import ROOM_STYLE, Building, Plan, _erika_ready, roof_rects


def _stable_seed(*parts) -> int:
    """A seed that is the same in every process. hash() of a string is not:
    Python randomises it per process, so two builds of one map picked
    different floors and trims, and the build could not be repeated."""
    return zlib.crc32(repr(parts).encode("utf-8"))


# Version 4 is the first that carries a per-room Ceiling tile. Writing 3 still
# loads - the reader accepts 1..7 - but then it silently back-fills ceilings
# itself, so we may as well state them.
VERSION = 4


def _attrs(pairs: list[tuple[str, object]]) -> str:
    # Nearly every value is a coordinate or an index. Quoting those through
    # quoteattr, nine million calls for a town, was 40% of the time spent
    # writing buildings; numbers never need escaping.
    return "".join(f' {k}="{v}"' if type(v) is int else f" {k}={quoteattr(str(v))}"
                   for k, v in pairs)


# A pitched roof needs room for two slopes; a narrower strip of a house (a
# porch, one step of a turned footprint) keeps a flat roof.
PEAK_MIN_TILES = 4
# The 30-degree roofs the game's own houses wear, which BuildingEd sizes to an
# odd number of tiles across, 3 to 11; a house up to two tiles wider takes an
# 11 and a flat strip. Wider than that, the steep 45-degree gable with a flat
# top in the middle is all the editor offers.
PEAK30_MAX_ACROSS = 11
HIP_MAX_ACROSS = 7
_PEAK_DEPTHS = {1: "Point5", 2: "One", 3: "OnePoint5", 4: "Two", 5: "TwoPoint5"}
_NO_CAPS = {"cappedW": False, "cappedN": False, "cappedE": False, "cappedS": False}


def _peak_depth(across: int) -> str:
    """BuildingEd's depth for a 45-degree peaked roof this many tiles across."""
    return _PEAK_DEPTHS.get(across, "Three")


# A one-storey part of a two-storey house is pitched too (it was always flat); only a strip
# narrower than NARROW_PEAK_MIN stays flat. Set PITCH_LOWER_ROOFS = False for the old roofs.
PITCH_LOWER_ROOFS = True
NARROW_PEAK_MIN = 2
# A footprint of many wings gives each its own roof, and a steep 30-degree one over a wide
# block rises twice as high as the 45-degree roofs of the wings beside it. Past
# MANY_WING_RECTS pieces a block wider than MANY_WING_PEAK30_MAX across takes the 45-degree
# roof too, whose height stops at three levels.
MANY_WING_RECTS = 3
MANY_WING_PEAK30_MAX = 7
# On a diagonal edge the same footprint breaks into many tiny rectangles, and a gable on each
# reads as a row of teeth along the eave. In such a footprint a piece under this many tiles
# stays flat, level with the wall top, so the eave is one line.
MANY_WING_MIN_PITCHED_AREA = 8


def _roof_pieces(rects, peaked: bool, roof30: bool = True):
    """(RoofType, Depth, caps, (x, y, w, h)) for each roof over a footprint.

    Flat roofs are never capped: at depth three a cap is a storey-high wall of
    roof tiles laid over the top storey's own walls. A pitched roof is capped
    at its gable ends where they are the outside of the house, and left open
    where it runs into the next roof.

    30-degree roofs need an odd width across their slopes. On an even one the
    roof covers one tile less and a flat strip takes the last row, on the side
    away from the camera (north or west) where it shows least. A house that is
    a single rectangle gets a hip roof about half the time, as Knox County's
    do; an L-shape keeps gables, whose ends meet cleanly.
    """
    out = []
    single = len(rects) == 1
    for rx, ry, rw, rh, caps in rects:
        across = min(rw, rh)
        tooth = len(rects) >= MANY_WING_RECTS and rw * rh < MANY_WING_MIN_PITCHED_AREA
        if not peaked or across < NARROW_PEAK_MIN or tooth:
            out.append(("FlatTop", "Three", dict(_NO_CAPS), (rx, ry, rw, rh)))
            continue
        along_x = rw >= rh
        # a narrow wing (2-3 across) takes a low 45-degree roof rather than a flat one
        steep_block = len(rects) >= MANY_WING_RECTS and across > MANY_WING_PEAK30_MAX
        if not roof30 or steep_block or across > PEAK30_MAX_ACROSS + 2 or across < PEAK_MIN_TILES:
            cap = dict(_NO_CAPS)
            if along_x:
                cap["cappedW"], cap["cappedE"] = caps["cappedW"], caps["cappedE"]
                out.append(("PeakWE", _peak_depth(rh), cap, (rx, ry, rw, rh)))
            else:
                cap["cappedN"], cap["cappedS"] = caps["cappedN"], caps["cappedS"]
                out.append(("PeakNS", _peak_depth(rw), cap, (rx, ry, rw, rh)))
            continue
        odd = across if across % 2 else across - 1
        # Hips only on small houses: across a wide one the four slopes meet
        # in a tall point that looks like a hat.
        hip = single and odd <= HIP_MAX_ACROSS and (rx * 31 + ry * 17 + rw * 7 + rh) % 2 == 0
        cap = dict(_NO_CAPS)
        if along_x:
            box = (rx, ry + (rh - odd), rw, odd)
            if rh != odd:
                out.append(("FlatTop", "Three", dict(_NO_CAPS), (rx, ry, rw, rh - odd)))
            if not hip:
                cap["cappedW"], cap["cappedE"] = caps["cappedW"], caps["cappedE"]
            out.append(("Peak30Quad" if hip else "Peak30WE", "Zero", cap, box))
        else:
            box = (rx + (rw - odd), ry, odd, rh)
            if rw != odd:
                out.append(("FlatTop", "Three", dict(_NO_CAPS), (rx, ry, rw - odd, rh)))
            if not hip:
                cap["cappedN"], cap["cappedS"] = caps["cappedN"], caps["cappedS"]
            out.append(("Peak30Quad" if hip else "Peak30NS", "Zero", cap, box))
    return out


# Flat roofs carry plant: bare tar from edge to edge read as unfinished. One
# air-conditioning unit per ROOF_AC_EVERY tiles of roof, a vent per
# ROOF_VENT_EVERY, and a hatch, kept off the edges and off each other.
ROOF_MIN_TILES = 60
ROOF_AC_EVERY = 90
ROOF_VENT_EVERY = 60


def _rooftop(grid: list[list[int]], width: int, height: int,
             seed: str | int = 0) -> list[tuple[str, int, int, str]]:
    import random

    tiles = [(x, y) for y in range(1, height - 1) for x in range(1, width - 1)
             if all(grid[y + dy][x + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1))]
    area = sum(1 for row in grid for v in row if v)
    if area < ROOF_MIN_TILES or not tiles:
        return []
    rng = random.Random(f"{seed}:{width}:{height}:{area}")
    wanted = (["roof_hatch"] + ["roof_ac"] * max(1, area // ROOF_AC_EVERY)
              + ["roof_vent"] * (area // ROOF_VENT_EVERY))
    taken: set[tuple[int, int]] = set()
    out = []
    rng.shuffle(tiles)
    for role in wanted:
        for x, y in tiles:
            if any((x + dx, y + dy) in taken for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                continue
            taken.add((x, y))
            out.append((role, x, y, rng.choice(("W", "N"))))
            break
    return out


def _storefront_runs(storey, doors) -> list[tuple[str, int, int, int]]:
    """The ground floor's shop glass as straight runs of wall: (edge dir,
    fixed coordinate, first tile along, length). A run spans from its first
    glazed tile to its last, taking in the doors and the bits of wall beside
    them, and stops wherever the line is no longer an outside wall."""
    grid = storey.grid
    h, w = len(grid), len(grid[0])

    def cell(x, y):
        return grid[y][x] if 0 <= x < w and 0 <= y < h else 0

    def outside(d, fixed, t):
        x, y = (fixed, t) if d == "W" else (t, fixed)
        a, b = (cell(x - 1, y), cell(x, y)) if d == "W" else (cell(x, y - 1), cell(x, y))
        return bool(a) != bool(b)

    lines: dict[tuple[str, int], list[int]] = {}
    for x, y, d in storey.shop_front:
        lines.setdefault((d, x if d == "W" else y), []).append(y if d == "W" else x)
    door_at = {(d, x if d == "W" else y, y if d == "W" else x) for x, y, d in doors}
    runs = []
    for (d, fixed), along in sorted(lines.items()):
        lo, hi = min(along), max(along)
        # A shop door just past the last pane belongs to the shop front too.
        for step in (-1, 1):
            end = lo if step < 0 else hi
            for k in (1, 2):
                if (d, fixed, end + k * step) in door_at and all(
                        outside(d, fixed, end + i * step) for i in range(1, k + 1)):
                    end += k * step
                    break
            lo, hi = (end, hi) if step < 0 else (lo, end)
        start = None
        for t in range(lo, hi + 2):
            if t <= hi and outside(d, fixed, t):
                start = t if start is None else start
            elif start is not None:
                runs.append((d, fixed, start, t - start))
                start = None
    return runs


def _add(entries: list[dict], entry: dict | None) -> int:
    """The 1-based index of `entry` in the tile-entry table, appending it if it
    is not there yet; 0, BuildingEd's "none", for no entry."""
    if not entry:
        return 0
    C._complete_window_cutouts(entry)
    if entry in entries:
        return entries.index(entry) + 1
    entries.append(entry)
    return len(entries)


# How many room kinds in a building carry wall trim. Knox County's schools
# How many different interior wall sets one building uses. Knox County's
# figure, measured over 77 buildings in Muldraugh, is 4.48.
#
# A mall is the exception: every unit in it is let to somebody else and
# painted to suit, and the game's own runs to 117 different wall tiles in the
# one building where an ordinary house has a dozen. It gets one per room kind
# instead, out of the whole list.
INTERIOR_WALLS_PER_BUILDING = 4
# One per storey for a mall concourse, so the ground floor seen through the
# atrium is plainly a different floor from the gallery you are standing on.
CONCOURSE_FLOORS = ("tile_cream", "tile_grey", "civic_pale", "tile_white")
WALLS_PER_KIND = {"mall": 99}
# run to 0.25 pieces of walls_interior_detailing per 10 m2 and ours to 2.43
# with every room trimmed, so about one kind in ten keeps it.
TRIM_SHARE = 0.12


def render_tbx(plan: Plan | Building, name: str,
               style: dict | None = None) -> str:
    """Return the complete .tbx document for a plan or a stack of them.

    `style` supplies this building's own exterior and interior wall materials,
    and optionally a floor that overrides the usual per-room palette. Each .tbx
    carries its own tile-entry table, so styles cost nothing globally: the
    style's entries are simply appended after the shared ones and referenced by
    their new indices.
    """
    building = plan if isinstance(plan, Building) else Building(
        width=plan.width, height=plan.height, storeys=[plan], profile=plan.profile)
    storeys = building.storeys

    entries = list(C.TILE_ENTRIES)
    exterior_idx = C.EXTERIOR_WALL
    interior_idx = C.INTERIOR_WALL
    floor_override = None
    window_idx = C.WINDOW
    roof_cap_idx = C.ROOF_CAP
    curtains_idx = C.CURTAINS
    front_idx = front_curtains = None
    slope_idx, top_idx, peaked = C.ROOF_SLOPE, C.ROOF_TOP, False
    trim_idx = shutters_idx = grime_idx = 0
    roof30 = False

    if style:
        C._complete_window_cutouts(style["exterior"])
        C._complete_window_cutouts(style["interior"])
        entries.append(style["exterior"])
        exterior_idx = len(entries)
        entries.append(style["interior"])
        interior_idx = len(entries)
        if style.get("floor"):
            entries.append(style["floor"])
            floor_override = len(entries)
        if style.get("window"):
            entries.append(style["window"])
            window_idx = len(entries)
        curtains_idx = _add(entries, style.get("curtains")) if "curtains" in style else C.CURTAINS
        # Taller buildings of a kind take bigger windows: the last row whose
        # storey count this building reaches.
        for levels, entry, curtains in style.get("windows_by_levels") or ():
            if len(storeys) >= levels and levels > 1:
                window_idx = _add(entries, entry)
                curtains_idx = _add(entries, curtains)
        trim_idx = _add(entries, style.get("trim"))
        shutters_idx = _add(entries, style.get("shutters"))
        grime_idx = _add(entries, style.get("grime"))
        if style.get("roof"):
            roof = style["roof"]
            if roof.get("slopes"):
                slope_idx = _add(entries, roof["slopes"])
            top_idx = _add(entries, roof["tops"])
            peaked = bool(roof.get("peaked"))
            # 30-degree roofs only where the gable ends have 30-degree tiles.
            roof30 = "CapPeak30S1" in ((roof.get("caps") or {}).get("tiles") or {})                 and "Slope30S1" in ((roof.get("slopes") or {}).get("tiles") or {})
        if style.get("shop_front"):
            entry, curtains = style["shop_front"]
            front_idx = _add(entries, entry)
            front_curtains = _add(entries, curtains)
    # With Erika's Tiles, a shop front is a wall of glass in a painted frame,
    # not windows set in brick, and a sign hangs over it.
    runs: list[tuple[str, int, int, int]] = []
    glazed: set[tuple[int, int, str]] = set()
    user_tiles: dict[int, dict[tuple[int, int], str]] = {}
    store_ext = store_int = store_door = 0
    if front_idx and C.ERIKA_STOREFRONTS and storeys[0].shop_front and _erika_ready():
        rng = random.Random(name)
        ext, inte, door = rng.choice(C.ERIKA_STOREFRONTS)
        store_ext, store_int, store_door = _add(entries, ext), _add(entries, inte), _add(entries, door)
        # A one-tile run is a step in a slanted wall, not a shop window.
        runs = [r for r in _storefront_runs(storeys[0], storeys[0].doors) if r[3] >= 2]
        for d, fixed, start, length in runs:
            glazed.update((fixed, t, d) if d == "W" else (t, fixed, d)
                          for t in range(start, start + length))
        # The sign goes on the longest run the street can see, one storey up
        # so it hangs above the glass. Only the south and east faces are
        # seen: a sign on a north or west wall is drawn on its inner side.
        grid = storeys[0].grid
        seen = [r for r in runs
                if (r[0] == "N" and (r[1] >= len(grid) or not grid[r[1]][r[2]]))
                or (r[0] == "W" and (r[1] >= len(grid[0]) or not grid[r[2]][r[1]]))]
        if seen:
            d, fixed, start, length = max(seen, key=lambda r: r[3])
            fits = [s for s in C.ERIKA_SIGNS.get(d, ()) if len(s) <= length]
            if fits:
                sign = rng.choice(fits)
                first = start + (length - len(sign)) // 2
                user_tiles[1] = {((fixed, first + j) if d == "W" else (first + j, fixed)): tile
                                 for j, tile in enumerate(sign)}
    # A depth-three flat roof walls in its storey with the cap entry's
    # CapGap tiles, which BuildingTemplates.txt sets to stucco - every top
    # floor came out stucco whatever the building was made of. Give each
    # building a cap entry whose gaps are its own exterior wall.
    ext_tiles = entries[exterior_idx - 1]["tiles"]
    if ext_tiles.get("West") and ext_tiles.get("North"):
        base = ((style or {}).get("roof") or {}).get("caps") or entries[C.ROOF_CAP - 1]
        cap = dict(base["tiles"])
        cap["CapGapE3"], cap["CapGapS3"] = ext_tiles["West"], ext_tiles["North"]
        entries.append({"category": "roof_caps", "tiles": cap})
        roof_cap_idx = len(entries)

    rooftop = [] if peaked else _rooftop(
        storeys[-1].grid, building.width, building.height, name)
    # Which furniture roles this building actually uses, in first-use order.
    roles: list[str] = []
    for storey in storeys:
        for role, _x, _y, _o in storey.furniture:
            if role not in roles:
                roles.append(role)
    for role, _x, _y, _o in rooftop:
        if role not in roles:
            roles.append(role)

    out: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']

    building_attrs = [
        ("version", VERSION),
        ("width", building.width),
        ("height", building.height),
        ("ExteriorWall", exterior_idx),
        ("ExteriorWallTrim", trim_idx),
        ("Door", C.DOOR),
        ("DoorFrame", C.DOOR_FRAME),
        ("Window", window_idx),
        ("Curtains", curtains_idx),
        ("Shutters", shutters_idx),
        ("Stairs", C.STAIRS),
        ("RoofCap", roof_cap_idx),
        ("RoofSlope", slope_idx),
        ("RoofTop", top_idx),
        ("GrimeWall", grime_idx),
    ]
    # A floor per room kind, drawn once for this building from the shares the
    # game lays them in (layout.FLOOR_CHOICES). One house keeps one floor per
    # kind so it reads as one house; the next house down the street draws
    # again. A style's own floor still overrides the lot. This has to happen
    # before the tile entries are written out below, and before used_tiles is
    # counted, or the new entries never reach the file.
    from .layout import FLOOR_CHOICES, KIND_FLOOR_CHOICES

    # What sort of building this is, for the rooms it floors differently: a
    # station's corridor is not somebody's hallway.
    of_kind = KIND_FLOOR_CHOICES.get(
        next((s.kind for s in storeys if s.kind), None) or "", {})
    # The style's floor is the building's default, not its whole story. It
    # used to override every room, which meant a school, a shop, a civic
    # building and a block of flats each had one floor throughout - a shop
    # tile down a school corridor, one carpet over a flat's bathroom and its
    # kitchen alike - and none of the per-room floors below ever applied to
    # them. Knox County gives a bathroom 18 different floors and a kitchen 35.
    # A room with a floor of its own takes it; the rest fall back to the
    # style's.
    # Which room kinds this building trims (see InteriorWallTrim below).
    trim_rng = random.Random(
        _stable_seed(name, building.width, building.height, 'trim'))
    trimmed = {k for k in sorted({r.kind for r in building.rooms})
               if trim_rng.random() < TRIM_SHARE}
    room_floor: dict[str, int] = {}
    pick_rng = random.Random(
        _stable_seed(name, len(building.rooms), building.width,
                     building.height))
    for kind in sorted({r.kind for r in building.rooms}):
        options = [o for o in of_kind.get(kind, FLOOR_CHOICES.get(kind, ()))
                   if o in C.EXTRA_FLOORS]
        if not options:
            continue
        if building.profile:
            choice = pick_rng.choices(
                options, weights=[building.profile.floor_weight(option)
                                  for option in options], k=1)[0]
        else:
            choice = pick_rng.choice(options)
        entries.append(C.floor_entry(choice))
        room_floor[kind] = len(entries)

    # A mall's concourse runs the same floor on every storey in Knox County,
    # which reads as one surface when two of them are in view at once and the
    # opening is all that tells them apart. Each storey gets its own here, so
    # a glance down the atrium shows which floor is which.
    storey_floor: dict[int, int] = {}
    if any(r.kind == "concourse" for r in building.rooms):
        for level in range(len(storeys)):
            name_ = CONCOURSE_FLOORS[level % len(CONCOURSE_FLOORS)]
            entries.append(C.floor_entry(name_))
            storey_floor[level] = len(entries)
    level_of = {id(r): lvl for lvl, st in enumerate(storeys) for r in st.rooms}

    # Interior walls, room by room. InteriorWall has always been a per-room
    # attribute here and every room was given the same one, so a building was
    # one colour throughout however many its style could have used. Knox
    # County paints 4.48 different sets into a single building - a kitchen is
    # not the colour of the bedroom next door - over 9 in all. A few are dealt
    # out per room kind rather than per room, so two bedrooms match and the
    # kitchen does not, the way the floors above already work.
    room_wall: dict[str, int] = {}
    palette = [interior_idx]
    spare = [e for e in C.INTERIOR_WALLS
             if not style or e != style.get("interior")]
    pick_rng.shuffle(spare)
    kinds_here = sorted({r.kind for r in building.rooms})
    want = min(WALLS_PER_KIND.get(getattr(storeys[0], "kind", None) or "",
                                  INTERIOR_WALLS_PER_BUILDING),
               len(kinds_here))
    for entry in spare[:max(0, want - 1)]:
        entries.append(entry)
        palette.append(len(entries))
    for i, kind in enumerate(kinds_here):
        # A mall gives each trade its own; everywhere else they share a few.
        room_wall[kind] = (palette[i % len(palette)] if want >= len(kinds_here)
                           else pick_rng.choice(palette))

    # Every tile entry has to be in the table before the table is written:
    # one added later indexes past the end of it.
    rails = any(st.railing for st in storeys)
    rail_idx = _add(entries, C.RAILING) if rails else 0
    rail_ext_idx = _add(entries, C.RAILING_EXT) if rails else 0

    out.append(f"<building{_attrs(building_attrs)}>")

    for entry in entries:
        out.append(f' <tile_entry category={quoteattr(entry["category"])}>')
        for enum_name, tile in entry["tiles"].items():
            out.append(f'  <tile enum={quoteattr(enum_name)} tile={quoteattr(tile)}/>')
        out.append(" </tile_entry>")

    for role in roles:
        # BuildingWriter only writes a layer when it is not the default. Leaving
        # it off a wall piece drops it onto the floor layer, which is how light
        # switches, paintings and mirrors ended up standing mid-room.
        layer = C.FURNITURE_LAYERS.get(role, "Furniture")
        out.append(" <furniture>" if layer == "Furniture"
                   else f" <furniture layer={quoteattr(layer)}>")
        # All four facings, in the order BuildingWriter emits them. Writing only
        # W and N leaves the E/S slots empty, so any object facing that way
        # renders as nothing at all.
        for orient in ("W", "N", "E", "S"):
            tiles = C.FURNITURE[role].get(orient)
            if not tiles:
                continue
            out.append(f'  <entry orient="{orient}">')
            for key, tile in tiles.items():
                dx, dy = key.split(",")
                out.append(f'   <tile x="{dx}" y="{dy}" name={quoteattr(tile)}/>')
            out.append("  </entry>")
        out.append(" </furniture>")

    names = sorted({t for tiles in user_tiles.values() for t in tiles.values()})
    if names:
        out.append(" <user_tiles>")
        out.extend(f"  <tile tile={quoteattr(t)}/>" for t in names)
        out.append(" </user_tiles>")

    def user_tile_layer(level: int) -> str | None:
        tiles = user_tiles.get(level)
        if not tiles:
            return None
        cols, rows = building.width + 1, building.height + 1
        text = ["\n"]
        for y in range(rows):
            row = [str(names.index(tiles[(x, y)]) + 1) if (x, y) in tiles else "0"
                   for x in range(cols)]
            text.append(",".join(row) + ("," if y < rows - 1 else "") + "\n")
        return '  <tiles layer="WallFurniture">' + escape("".join(text)) + "</tiles>"

    used = " ".join(str(i) for i in range(1, len(entries) + 1))
    out.append(f" <used_tiles>{used}</used_tiles>")
    used_f = " ".join(str(i) for i in range(len(roles)))
    out.append(f" <used_furniture>{used_f}</used_furniture>")

    for room in building.rooms:
        floor_idx, _label, _ = ROOM_STYLE[room.kind]
        floor_idx = room_floor.get(room.kind, floor_idx)
        # The shipped templates set Name identical to InternalName; the room
        # name is what reaches the game's room definitions, so don't get
        # creative with it.
        # An open-plan flat's one room is ours; the game knows it as a living
        # room, and the name is what its loot tables key off (layout.ROOM_NAME).
        from .layout import ROOM_NAME
        game_name = ROOM_NAME.get(room.kind, room.kind)
        room_attrs = [
            ("Name", game_name),
            ("InternalName", game_name),
            ("Color", C.ROOM_COLORS[room.kind]),
            ("InteriorWall", room_wall.get(room.kind, interior_idx)),
            # Skirting and picture rail. Set on every room it came to 2.43
            # pieces per 10 m2 against Knox County's 0.25 - a band of
            # detailing round every wall of every room, which at a distance
            # reads as fittings hung all the way along. Only some rooms get
            # it, drawn once per building per kind so one room is not
            # trimmed and the one next door bare.
            ("InteriorWallTrim",
             C.INTERIOR_WALL_TRIM if room.kind in trimmed else 0),
            # A room with a floor of its own first, then the style's, then
            # the room kind's own default.
            ("Floor",
             (storey_floor.get(level_of.get(id(room)), 0)
              if room.kind == "concourse" else 0)
             or room_floor.get(room.kind) or floor_override or floor_idx),
            ("GrimeFloor", 0),
            ("GrimeWall", 0),
            # A concourse has no ceiling: it is open to the storey above, and
            # BuildingEd draws a room's ceiling on the floor above it - which
            # laid a lid straight across the hole and hid the ground floor
            # the hole is cut to show.
            ("Ceiling", 0 if room.kind == "concourse" else C.CEILING),
        ]
        out.append(f" <room{_attrs(room_attrs)}/>")

    attic: list[str] = []
    # pitched roofs over a lower storey's exposed part stand on the floor above that storey,
    # as the top storey's stand on the roof floor
    above_roofs: dict[int, list[str]] = {}
    for level, storey in enumerate(storeys):
        out.append(" <floor>")
        out.extend(above_roofs.pop(level, []))
        
        # The three doors _widen_vehicle_entry cut into one wide opening are
        # still three door objects - BuildingEd has no object that spans more
        # than one tile - but each takes its own third of the garage door
        # tile instead of all three using the plain house door.
        garage_tiles = getattr(storey, "garage_door_tiles", ())

        for x, y, direction in storey.doors:
            # In the shop glass: a glass door, framed by the glass wall itself.
            shop_door = level == 0 and (x, y, direction) in glazed
            garage_pos = (garage_tiles.index((x, y, direction))
                          if (x, y, direction) in garage_tiles else None)
            if garage_pos is not None:
                # garage_tiles is (center, neighbour, neighbour): position 0
                # is the original door tile before _widen_vehicle_entry grew
                # it sideways, which ends up in the middle of the opening, not
                # on the left. remap to the catalog's left/mid/right order.
                garage_slot = (1, 0, 2)[garage_pos]
                attrs = [("type", "door"), ("FrameTile", 0),
                         ("x", x), ("y", y), ("dir", direction),
                         ("Tile", C.GARAGE_DOOR[garage_slot])]
            else:
                attrs = [("type", "door"), ("FrameTile", 0 if shop_door else C.DOOR_FRAME),
                         ("x", x), ("y", y), ("dir", direction),
                         ("Tile", store_door if shop_door else C.DOOR)]
            out.append(f"  <object{_attrs(attrs)}/>")
        # The railing round the hole in this floor, one run per edge. A wall
        # object overrides what the room adjacency would have drawn, which is
        # how the shop glass below works too.
        # Nothing at all where an escalator arrives: a wall object with no
        # tile on it, which is what stops the exterior wall coming back.
        for x, y, d in sorted(storey.open_edge):
            out.append("  <object" + _attrs([
                ("type", "wall"), ("length", 1), ("InteriorTile", 0),
                ("ExteriorTrim", 0), ("InteriorTrim", 0), ("x", x), ("y", y),
                ("dir", "N" if d == "W" else "W"), ("Tile", 0)]) + "/>")

        if storey.railing and rail_idx:
            for x, y, d in sorted(storey.railing):
                rail_attrs = [("type", "wall"), ("length", 1),
                              ("InteriorTile", rail_idx), ("ExteriorTrim", 0),
                              ("InteriorTrim", 0), ("x", x), ("y", y),
                              ("dir", "N" if d == "W" else "W"),
                              ("Tile", rail_ext_idx)]
                out.append(f"  <object{_attrs(rail_attrs)}/>")

        if level == 0:
            for d, fixed, start, length in runs:
                x, y = (fixed, start) if d == "W" else (start, fixed)
                # A wall object runs along y when its dir is N, placing west
                # walls, and along x when it is W.
                attrs = [("type", "wall"), ("length", length), ("InteriorTile", store_int),
                         ("ExteriorTrim", 0), ("InteriorTrim", 0), ("x", x), ("y", y),
                         ("dir", "N" if d == "W" else "W"), ("Tile", store_ext)]
                out.append(f"  <object{_attrs(attrs)}/>")

        for x, y, direction in storey.windows:
            if level == 0 and (x, y, direction) in glazed:
                continue                        # the glass wall is the window
            tile, curtains = window_idx, curtains_idx
            if front_idx and (x, y, direction) in getattr(storey, "shop_front", ()):
                tile, curtains = front_idx, front_curtains
            attrs = [("type", "window"), ("CurtainsTile", curtains),
                     ("ShuttersTile", 0 if tile == front_idx else shutters_idx),
                     ("x", x), ("y", y),
                     ("dir", direction), ("Tile", tile)]
            out.append(f"  <object{_attrs(attrs)}/>")

        for role, x, y, orient in storey.furniture:
            attrs = [("type", "furniture"),
                     ("FurnitureTiles", roles.index(role)),
                     ("orient", orient), ("x", x), ("y", y)]
            out.append(f"  <object{_attrs(attrs)}/>")

        # A staircase belongs to the storey it rises from; the reader puts the
        # opening in the floor above by itself. Only N and W are valid
        # directions - Stairs::bounds returns an empty rect for anything else,
        # and an empty rect is treated as an invalid object.
        if level < len(building.stairs):
            sx, sy, sdir = building.stairs[level]
            attrs = [("type", "stairs"), ("x", sx), ("y", sy),
                     ("dir", sdir), ("Tile", C.STAIRS)]
            out.append(f"  <object{_attrs(attrs)}/>")

        # Roofs on the top storey only - one on each would bury every floor
        # below under a ceiling of roof tiles - and shaped to the footprint
        # rather than its bounding box, so an L-shaped building does not carry
        # a roof over its own back yard.
        # A roof over whatever of this storey has no storey above it: the
        # whole top floor, and the ledge where a tower steps back.
        above = storeys[level + 1].grid if level + 1 < len(storeys) else None
        # A square left open in the storey above - the hole down the middle of
        # a mall's upper floor - has no room there, but it is still built
        # over: roofing it would put a ceiling across the concourse and hide
        # the floor the hole exists to show.
        open_above = (storeys[level + 1].void
                      if level + 1 < len(storeys) else set())
        exposed = [[v if above is None or not (above[y][x] or (x, y) in open_above)
                    else 0
                    for x, v in enumerate(row)] for y, row in enumerate(storey.grid)]
        if any(any(row) for row in exposed):
            rects = roof_rects(exposed)
            for roof_type, depth, cap, (rx, ry, rw, rh) in _roof_pieces(
                    rects, peaked and (above is None or PITCH_LOWER_ROOFS), roof30):
                roof_attrs = [
                    ("type", "roof"),
                    ("width", rw),
                    ("height", rh),
                    ("RoofType", roof_type),
                    ("Depth", depth),
                    ("cappedW", str(cap["cappedW"]).lower()),
                    ("cappedN", str(cap["cappedN"]).lower()),
                    ("cappedE", str(cap["cappedE"]).lower()),
                    ("cappedS", str(cap["cappedS"]).lower()),
                    ("CapTiles", roof_cap_idx),
                    ("SlopeTiles", slope_idx),
                    ("TopTiles", top_idx),
                    ("x", rx), ("y", ry),
                ]
                line = f"  <object{_attrs(roof_attrs)}/>"
                # BuildingEd measures a roof's height up from the floor it is
                # on. A flat roof at depth three on the top storey ends level
                # with its ceiling, which is right; a pitched roof there rose
                # through the top storey, its gable ends covering the upstairs
                # walls. Pitched roofs go on the roof floor above instead.
                if roof_type == "FlatTop":
                    out.append(line)
                elif above is None:
                    attic.append(line)
                else:
                    above_roofs.setdefault(level + 1, []).append(line)

        # Match BuildingWriter byte for byte: a comma follows every value
        # except the very last one, and each row ends with a newline.
        grid = building.grid_for(level)
        text = ["\n"]
        count, total = 0, building.width * building.height
        for y in range(building.height):
            for x in range(building.width):
                text.append(str(grid[y][x]))
                count += 1
                if count < total:
                    text.append(",")
            text.append("\n")
        out.append("  <rooms>" + escape("".join(text)) + "</rooms>")
        if (layer := user_tile_layer(level)):
            out.append(layer)

        out.append(" </floor>")

    # The roof floor: no rooms. It holds the pitched roofs, and the flat roof
    # tops BuildingEd places here from the depth-three roofs below.
    empty = ["\n"]
    count, total = 0, building.width * building.height
    for _y in range(building.height):
        for _x in range(building.width):
            empty.append("0")
            count += 1
            if count < total:
                empty.append(",")
        empty.append("\n")
    out.append(" <floor>")
    out.extend(attic)
    for role, x, y, orient in rooftop:
        attrs = [("type", "furniture"), ("FurnitureTiles", roles.index(role)),
                 ("orient", orient), ("x", x), ("y", y)]
        out.append(f"  <object{_attrs(attrs)}/>")
    out.append("  <rooms>" + escape("".join(empty)) + "</rooms>")
    if (layer := user_tile_layer(len(storeys))):
        out.append(layer)
    out.append(" </floor>")
    if attic:
        # A pitched roof's top rises a full storey above the roof floor, and
        # BuildingEd lays what is up there on the floor above that.
        out.append(" <floor>")
        out.append("  <rooms>" + escape("".join(empty)) + "</rooms>")
        out.append(" </floor>")
    out.append("</building>")
    return "\n".join(out) + "\n"
