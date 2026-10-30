"""A building drawn by hand in the window, as a plan and as a .tbx.

The generator lays out every building from scratch, and a preset
(knoxbuild/presets.py) is the way out of that: a hand-built .tbx stamped onto
a plot instead of a generated one. Until now the only way to make one was
BuildingEd, which means leaving KnoxMap, learning another editor and knowing
which of the game's three thousand tiles a police station is built of.

This is the other half: rooms drawn on a sheet in the window, and everything
else - walls, doors, windows, the staircase, the roof, the furniture, the tile
for each of them - done by the same code that builds the rest of the map. So a
hand-drawn police station is a real police station: its lockers, its gun
storage and its cells hold what the game puts in those rooms, because they are
the same rooms the generator would have made, laid out where the mapper wanted
them instead of where the splitter happened to cut.

A design is plain data (`clean`), kept beside the preset it was saved as, so a
preset can be opened and changed again. What comes out of it is an ordinary
.tbx, written by knoxbuild/tbx.py: once saved, nothing can tell it from a
building made in BuildingEd.
"""
from __future__ import annotations

import json
import math
import os
import random
import zlib

from . import layout as L
from . import presets as P
from .settings import Settings

# A building smaller than this has no room in it; bigger than this is not a
# building but a district, and the editor draws every tile of it.
MIN_SIDE, MAX_SIDE = 4, 150
MAX_STOREYS = 8

# The rooms of a house, which no SPECIAL_MIXES entry covers because a house is
# what the generator builds when a building is nothing in particular.
HOUSE_ROOMS = ("livingroom", "openplan", "kitchen", "dining", "bedroom",
               "kidsbedroom", "bathroom", "hall", "closet", "laundry",
               "storage", "garage", "shed")


def room_label(kind: str) -> str:
    style = L.ROOM_STYLE.get(kind)
    return style[1] if style else kind


def _mix_for(kind: str | None) -> list[str]:
    """The rooms the generator itself would put in this kind of building."""
    if not kind or kind in ("house", "shed"):
        return [name for name in HOUSE_ROOMS if name in L.ROOM_STYLE]
    mix, fill = L.SPECIAL_MIXES.get(kind, ((), ()))
    out = []
    for name in list(mix) + list(fill):
        if name not in out and name in L.ROOM_STYLE:
            out.append(name)
    return out


def room_kinds(kind: str | None = None) -> list[dict]:
    """Every room that can be drawn, the ones this building has first.

    Taken from the room table itself rather than listed here, so a room the
    game knows and this window does not cannot happen; and ordered by what is
    being built, because a police station has 113 rooms to choose from and
    seven of them are the ones it is made of.
    """
    def entry(name: str, group: str) -> dict:
        # The colour it is drawn in on the plan, so the palette and the
        # picture agree about which room is which.
        return {"id": name, "label": room_label(name), "group": group,
                "colour": "#%02x%02x%02x" % room_colour(name)}

    first = _mix_for(kind)
    # With no kind chosen the rooms a house is made of are the ones offered
    # first, so saying they are "in this kind of building" would be saying
    # nothing: they are named for what they are.
    out = [entry(name, "In this kind of building" if kind else "Rooms of a house")
           for name in first]
    house = [name for name in HOUSE_ROOMS
             if name not in first and name in L.ROOM_STYLE]
    out += [entry(name, "Rooms of a house") for name in house]
    # A room with nothing to put in it is not a room anybody draws: the lift
    # shaft is machinery the builder fits where the stairs are, and drawn by
    # hand it is a sealed box with no way in and no lift in it.
    rest = sorted((name for name in L.ROOM_STYLE
                   if name not in first and name not in house
                   and L.ROOM_STYLE[name][2]),
                  key=room_label)
    out += [entry(name, "Every other room") for name in rest]
    return out


# ---- the design itself ------------------------------------------------------

def _listed(value) -> list:
    """A list of whatever was sent, or nothing. A cleaner never throws: this
    reads what the window posts and what is on disk, and a number where a
    list was expected used to come back as a Python TypeError."""
    return list(value) if isinstance(value, (list, tuple)) else []


def _table(value) -> dict:
    return value if isinstance(value, dict) else {}


def _int(value, low, high, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    # float() takes "NaN" and "inf" and int() takes neither: a sheet whose
    # width arrived as one of those ended in "cannot convert float infinity
    # to integer" rather than in the size it was supposed to fall back to.
    if not math.isfinite(number):
        return fallback
    return min(max(int(number), low), high)


def _stable_seed(*parts) -> int:
    return zlib.crc32(repr(parts).encode("utf-8")) & 0x7FFFFFFF


def blank(kind: str | None = None, width: int = 20, height: int = 16) -> dict:
    return clean({"kind": kind or "", "width": width, "height": height,
                  "storeys": 1, "rooms": []})


def clean(raw) -> dict:
    """A design from untrusted input, with its rooms made to not overlap.

    Rooms are drawn one over another, as in any paint program: the newest wins
    and whatever was under it keeps the rest of itself. The pieces are worked
    out here rather than in the window because the rest of the pipeline is
    built on rectangular rooms (knoxbuild/layout.py) and this is the one place
    that has to be true.

    A room with no kind is the eraser: it takes its rectangle out of whatever
    is under it and leaves nothing behind, which is also how a footprint is
    cut to an L or a T.
    """
    raw = raw if isinstance(raw, dict) else {}
    width = _int(raw.get("width"), MIN_SIDE, MAX_SIDE, 20)
    height = _int(raw.get("height"), MIN_SIDE, MAX_SIDE, 16)
    storeys = _int(raw.get("storeys"), 1, MAX_STOREYS, 1)
    kind = str(raw.get("kind") or "").strip().lower()[:40]
    if kind and kind not in {entry["id"] for entry in P.kinds()}:
        kind = ""          # a kind the generator cannot recognise is no kind
    style = str(raw.get("style") or "").strip()[:60]
    name = P.safe_name(raw.get("name") or "")
    seed = _int(raw.get("seed"), 0, 2 ** 31 - 1, 0) or _stable_seed(name or "x")

    # Level by level, so a room drawn upstairs cannot cut one downstairs.
    by_level: dict[int, list[tuple[tuple, str]]] = {}
    for item in _listed(raw.get("rooms")):
        if not isinstance(item, dict):
            continue
        level = _int(item.get("level"), 0, storeys - 1, 0)
        x0 = _int(item.get("x"), 0, width - 1, 0)
        y0 = _int(item.get("y"), 0, height - 1, 0)
        x1 = min(width - 1, x0 + _int(item.get("w"), 1, MAX_SIDE, 1) - 1)
        y1 = min(height - 1, y0 + _int(item.get("h"), 1, MAX_SIDE, 1) - 1)
        room_kind = str(item.get("kind") or "").strip().lower()[:40]
        if room_kind and room_kind not in L.ROOM_STYLE:
            continue
        kept = []
        for box, had in by_level.get(level, []):
            for piece in L._subtract(box, [(x0, y0, x1, y1)]):
                kept.append((piece, had))
        if room_kind:
            kept.append(((x0, y0, x1, y1), room_kind))
        by_level[level] = kept

    rooms = []
    for level in sorted(by_level):
        for (x0, y0, x1, y1), room_kind in by_level[level]:
            rooms.append({"level": level, "x": x0, "y": y0,
                          "w": x1 - x0 + 1, "h": y1 - y0 + 1,
                          "kind": room_kind})
    return {"name": name, "kind": kind, "style": style, "seed": seed,
            "width": width, "height": height, "storeys": storeys,
            "rooms": rooms}


def painted(design: dict, level: int = 0) -> int:
    """How many tiles of this storey are inside the building."""
    return sum(r["w"] * r["h"] for r in design["rooms"] if r["level"] == level)


def tally(design: dict, level: int | None = None) -> list[tuple[str, int]]:
    """The rooms of a storey, most floor first, for the window's list."""
    area: dict[str, int] = {}
    for room in design["rooms"]:
        if level is not None and room["level"] != level:
            continue
        area[room["kind"]] = area.get(room["kind"], 0) + room["w"] * room["h"]
    return sorted(area.items(), key=lambda kv: (-kv[1], kv[0]))


# ---- from a design to a building --------------------------------------------

def _mask(design: dict, level: int) -> list[list[bool]]:
    mask = [[False] * design["width"] for _ in range(design["height"])]
    for room in design["rooms"]:
        if room["level"] != level:
            continue
        for y in range(room["y"], room["y"] + room["h"]):
            for x in range(room["x"], room["x"] + room["w"]):
                mask[y][x] = True
    return mask


def _rooms_of(design: dict, level: int) -> list[L.Room]:
    return [L.Room(r["x"], r["y"], r["x"] + r["w"] - 1, r["y"] + r["h"] - 1,
                   kind=r["kind"])
            for r in design["rooms"] if r["level"] == level]


def _split_by(box: tuple[int, int, int, int],
              core: tuple[int, int, int, int]) -> int:
    """How badly a staircase cuts a room: 2 if it leaves two pieces, 1 if it
    takes a bite out of one, 3 if it eats the room whole.

    A strip two tiles thick is not a room - the layout folds anything that
    thin into its neighbour (_mend_fragments) - so a shaft that leaves only
    strips has eaten the room, whatever the arithmetic says.
    """
    pieces = [piece for piece in L._subtract(box, [core])
              if min(piece[2] - piece[0], piece[3] - piece[1]) + 1 >= 3]
    if not pieces:
        return 3
    if len(pieces) == 1:
        return 1
    # _subtract gives rectangles, not regions: two of them along the same side
    # of the shaft are still one room. Walk them to see which really touch.
    seen = {0}
    edge = [0]
    while edge:
        i = edge.pop()
        ax0, ay0, ax1, ay1 = pieces[i]
        for j, (bx0, by0, bx1, by1) in enumerate(pieces):
            if j in seen:
                continue
            if (ax0 <= bx1 + 1 and bx0 <= ax1 + 1
                    and ay0 <= by1 + 1 and by0 <= ay1 + 1):
                seen.add(j)
                edge.append(j)
    return 1 if len(seen) == len(pieces) else 2


def _core_for(design: dict, rng: random.Random):
    """Where the staircase goes in a building somebody drew.

    The generator puts its shaft in the middle of the floor, which is right
    for a plan it laid out itself around one. Over a drawing it is wrong: the
    shaft landed in the middle of a drawn room and cut it in two, and in a
    room barely bigger than the shaft it ate the whole thing - draw a 6x6
    room on a two-storey building and what came back was two rooms.

    So it is put where it takes the least out of what was drawn: a corner of
    one room rather than its middle, against an outside wall where a house
    really keeps its stairs. It must stand on painted floor on every storey,
    because a shaft over the garden upstairs is a flight into the air.
    """
    width, height = design["width"], design["height"]
    levels = design["storeys"]
    masks = [_mask(design, level) for level in range(levels)]
    rooms = [(level, (r["x"], r["y"], r["x"] + r["w"] - 1, r["y"] + r["h"] - 1))
             for level in range(levels)
             for r in design["rooms"] if r["level"] == level]

    best, best_score = [], None
    for cw, ch in ((L.CORE_WIDE, L.STAIR_RUN + 1), (L.STAIR_RUN + 1, L.CORE_WIDE)):
        if cw > width or ch > height:
            continue
        for y0 in range(height - ch + 1):
            for x0 in range(width - cw + 1):
                core = (x0, y0, x0 + cw - 1, y0 + ch - 1)
                if not all(mask[y][x] for mask in masks
                           for y in range(y0, y0 + ch)
                           for x in range(x0, x0 + cw)):
                    continue
                harm = eaten = 0
                for _level, box in rooms:
                    if (box[0] > core[2] or box[2] < core[0]
                            or box[1] > core[3] or box[3] < core[1]):
                        continue
                    cut = _split_by(box, core)
                    harm += cut
                    eaten += cut == 3
                # Against a wall: how much of the shaft's own edge has nothing
                # painted beyond it.
                outside = 0
                for y in range(y0, y0 + ch):
                    for x, step in ((x0, -1), (x0 + cw - 1, 1)):
                        at = x + step
                        outside += at < 0 or at >= width or not masks[0][y][at]
                for x in range(x0, x0 + cw):
                    for y, step in ((y0, -1), (y0 + ch - 1, 1)):
                        at = y + step
                        outside += at < 0 or at >= height or not masks[0][at][x]
                score = (eaten, harm, -outside,
                         round(abs((x0 + cw / 2) - width / 2)
                               + abs((y0 + ch / 2) - height / 2), 3))
                if best_score is None or score < best_score:
                    best, best_score = [core], score
                elif score == best_score:
                    best.append(core)
    # Every place the stairs could stand would swallow a room whole, which is
    # to say the drawing has no room for stairs: one storey of it, then, the
    # same answer as a building with nowhere to put a shaft at all.
    if not best or best_score[0]:
        return None
    return rng.choice(best)


def style_for(design: dict) -> dict:
    """The materials this building is built of.

    A style named in the design is looked up for the kind being built, so
    "brick" on a church is the church's brick; a design that names none is
    built in whatever the generator would have picked for that kind, which is
    also what makes a one-click preset look like the rest of the map.
    """
    from . import build as B

    kind = design.get("kind") or None
    if design.get("style"):
        found = B.style_named(design["style"], kind)
        if found:
            return found
    return B.pick_style(kind, 0, 0, random.Random(design.get("seed") or 0),
                        Settings())


def style_choices(kind: str | None = None) -> list[str]:
    from . import build as B

    return B.style_names(kind or None)


# Laying a storey out and furnishing it costs about a second per 20,000 tiles,
# which is nothing for a house and seven seconds for 150x150 over eight floors
# - too long to wait for after every drag. Past this much, only the storey
# being looked at is built for the picture; the whole building is still built
# when it is saved.
PREVIEW_BUDGET = 40000


def stack(design: dict, settings: Settings | None = None,
          only: int | None = None) -> L.Building:
    """The design as a finished building: walls, doors, windows, furniture.

    Everything that is not the room plan is done by the generator's own
    passes, in the order build_building does them - doors between rooms, a way
    in on the ground floor, the furniture, then the windows for the whole
    facade at once so they stack in columns. A hand-drawn building is
    therefore furnished to the same rules as every other building on the map.

    `only` builds that storey alone, for drawing a big building quickly; what
    is saved is always the whole stack.
    """
    settings = settings or Settings()
    design = clean(design)
    kind = design.get("kind") or None
    levels = design["storeys"]
    seed = design["seed"]
    rng = random.Random(seed ^ 0x5745)

    core = stairs = None
    if levels > 1:
        core = _core_for(design, rng)
        if core is None:
            levels = 1          # nowhere for a staircase, so one storey it is
        else:
            stairs = L._stairs_in_core(core)

    wanted = range(levels) if only is None else [min(max(only, 0), levels - 1)]
    storeys = []
    for level in wanted:
        plan = L.Plan(width=design["width"], height=design["height"],
                      rooms=_rooms_of(design, level), core=core, kind=kind,
                      drawn=True)
        L._paint(plan)
        if not plan.rooms:
            storeys.append(plan)
            continue
        floor_rng = random.Random(seed + 977 * level)
        L._doors(plan, floor_rng)
        if level == 0:
            L._exterior_door(plan, floor_rng, avoid=L._stair_foot(stairs))
            if kind in (None, "house"):
                L._back_door(plan)
        L._furnish(plan, floor_rng, stairs)
        storeys.append(plan)

    building = L.Building(width=design["width"], height=design["height"],
                          storeys=storeys)
    if stairs is not None and only is None:
        for level in range(levels - 1):
            building.stairs.append(stairs)
            L._clear_for_stairs(storeys[level], *stairs)
            L._clear_for_stairs(storeys[level + 1], *stairs)
    elif stairs is not None:
        # One storey on its own still has the staircase standing in it.
        L._clear_for_stairs(storeys[0], *stairs)
    L._place_windows(building, kind)
    L._clear_the_way(building)
    return building


def tbx_text(design: dict, name: str | None = None) -> str:
    """The design as the .tbx a preset is."""
    from .tbx import render_tbx

    design = clean(design)
    label = P.safe_name(name or design.get("name") or "") or "Hand-built"
    return render_tbx(stack(design), label, style_for(design))


def autofill(design: dict, settings: Settings | None = None) -> dict:
    """Rooms laid out by the generator, to start from or to fill a storey.

    Drawing a 30-room school by hand is work nobody should have to do twice.
    This is the building the map would have got, handed over as a design to
    change: the rooms it would have cut, where it would have cut them.
    """
    design = clean(design)
    built = L.build_building(design["width"], design["height"],
                             levels=design["storeys"],
                             kind=design.get("kind") or None,
                             seed=design["seed"],
                             settings=settings or Settings())
    rooms = []
    for level, storey in enumerate(built.storeys):
        for room in storey.rooms:
            if room.is_shaft or room.kind not in L.ROOM_STYLE:
                continue
            rooms.append({"level": level, "x": room.x0, "y": room.y0,
                          "w": room.w, "h": room.h, "kind": room.kind})
    out = dict(design)
    out["rooms"] = rooms
    out["storeys"] = max(1, len(built.storeys))
    return clean(out)


# ---- what it is made of -----------------------------------------------------

def _tile_names(entry, limit: int = 6) -> list[str]:
    if not isinstance(entry, dict):
        return []
    tiles = entry.get("tiles")
    if not isinstance(tiles, dict):
        return []
    return sorted({str(t) for t in tiles.values() if t})[:limit]


def tiles_used(design: dict) -> list[dict]:
    """The game tiles this building is built of, for the window to show.

    "Which tiles" is the question BuildingEd answers with a tile picker and
    three thousand thumbnails. A preset is built of its style's walls, its
    rooms' floors and the fittings those rooms carry, so that is what is
    listed: the walls by name, and each room's floor and furniture.
    """
    design = clean(design)
    style = style_for(design)
    out = [{"what": "Outside walls", "name": style.get("name") or "",
            "tiles": _tile_names(style.get("exterior"))},
           {"what": "Inside walls", "name": style.get("name") or "",
            "tiles": _tile_names(style.get("interior"))}]
    for room_kind, _area in tally(design):
        entry = L.ROOM_STYLE.get(room_kind)
        if not entry:
            continue
        out.append({"what": room_label(room_kind), "name": room_kind,
                    "tiles": _tile_names(entry[0], 3),
                    "fittings": sorted(set(entry[2] or ()))[:12]})
    return out


# ---- a picture of it --------------------------------------------------------

OUTSIDE = (232, 231, 226)
WALL = (58, 56, 54)
DOOR = (196, 120, 40)
WINDOW = (96, 170, 220)
PIECE = (74, 70, 66)
GRID = (214, 212, 206)
# The sheet under the drawing. Asked for in #suggestions: the grid only
# appeared under a room once one had been drawn, and a floor you are about to
# draw is exactly when it is worth seeing - it is how you judge how big to
# make the room. Every fifth line is darker so tiles can be counted without
# following one across the whole sheet.
EMPTY_GRID = (223, 222, 216)
EMPTY_GRID_FIFTH = (209, 207, 200)
GRID_EVERY = 5


def room_colour(kind: str) -> tuple[int, int, int]:
    """A colour per room kind, the same one every time.

    Worked out from the name rather than listed, because there are 113 rooms
    and a table of them would be a table to forget to add to.
    """
    import colorsys

    hue = (zlib.crc32(kind.encode("utf-8")) % 997) / 997.0
    sat = 0.30 + ((zlib.crc32(kind[::-1].encode("utf-8")) >> 3) % 20) / 100.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.78, sat)
    return int(r * 255), int(g * 255), int(b * 255)


def one_storey_at_a_time(design: dict) -> bool:
    """Whether this design is too big to build whole for every change."""
    return (design["storeys"] > 1
            and design["width"] * design["height"] * design["storeys"]
            > PREVIEW_BUDGET)


def scale_for(design: dict, longest: int = 760) -> int:
    side = max(design["width"], design["height"], 1)
    return max(4, min(26, longest // side))


def _sheet_grid(pen, width: int, height: int, px: int) -> None:
    """One square a tile, over the whole sheet, under whatever is drawn."""
    for x in range(width + 1):
        pen.line([x * px, 0, x * px, height * px],
                 fill=EMPTY_GRID_FIFTH if x % GRID_EVERY == 0 else EMPTY_GRID)
    for y in range(height + 1):
        pen.line([0, y * px, width * px, y * px],
                 fill=EMPTY_GRID_FIFTH if y % GRID_EVERY == 0 else EMPTY_GRID)


def preview(design: dict, level: int = 0, scale: int | None = None,
            building: L.Building | None = None):
    """A picture of one storey: rooms, walls, doors, windows, furniture.

    Drawn from the finished building rather than from the drawing, so what is
    on the screen is what the .tbx will hold - the doors the generator put in,
    the windows it put in the facade, the furniture standing in each room -
    and not only the rectangles that were drawn.
    """
    from PIL import Image, ImageDraw

    design = clean(design)
    built = building if building is not None else stack(design)
    width, height = design["width"], design["height"]
    px = scale or scale_for(design)
    img = Image.new("RGB", (width * px + 1, height * px + 1), OUTSIDE)
    pen = ImageDraw.Draw(img)
    _sheet_grid(pen, width, height, px)
    if not built.storeys:
        return img
    level = min(max(level, 0), len(built.storeys) - 1)
    plan = built.storeys[level]
    if not plan.grid:
        return img

    def room_at(x, y):
        if 0 <= x < width and 0 <= y < height:
            return plan.grid[y][x]
        return 0

    for y in range(height):
        for x in range(width):
            idx = room_at(x, y)
            if not idx:
                continue
            pen.rectangle([x * px, y * px, x * px + px, y * px + px],
                          fill=room_colour(plan.rooms[idx - 1].kind),
                          outline=GRID)

    thick = max(1, px // 5)
    for y in range(height + 1):
        for x in range(width + 1):
            # A wall stands wherever two different rooms meet, and round the
            # outside of the building: the rule tbx.py writes them by.
            if room_at(x, y) != room_at(x - 1, y):
                pen.line([x * px, y * px, x * px, y * px + px],
                         fill=WALL, width=thick)
            if room_at(x, y) != room_at(x, y - 1):
                pen.line([x * px, y * px, x * px + px, y * px],
                         fill=WALL, width=thick)

    for x, y, d in plan.windows:
        if d == "W":
            pen.line([x * px, y * px + 2, x * px, y * px + px - 2],
                     fill=WINDOW, width=thick + 1)
        else:
            pen.line([x * px + 2, y * px, x * px + px - 2, y * px],
                     fill=WINDOW, width=thick + 1)
    # Doors last of the wall things: a doorway is a gap in the wall, so it has
    # to be drawn over the wall rather than under it.
    for x, y, d in plan.doors:
        if d == "W":
            pen.line([x * px, y * px + 1, x * px, y * px + px - 1],
                     fill=DOOR, width=thick + 1)
        else:
            pen.line([x * px + 1, y * px, x * px + px - 1, y * px],
                     fill=DOOR, width=thick + 1)

    spot = max(2, px // 3)
    for _role, x, y, _d in plan.furniture:
        cx, cy = x * px + px // 2, y * px + px // 2
        pen.ellipse([cx - spot // 2, cy - spot // 2,
                     cx + spot // 2, cy + spot // 2], fill=PIECE)
    return img


# ---- keeping one ------------------------------------------------------------

def design_path(base_dir, name: str) -> str:
    return os.path.join(P.folder(base_dir),
                        f"{P.safe_name(name)}{P.DESIGN_SUFFIX}")


def save_design(base_dir, name: str, design: dict) -> None:
    """Keep the drawing beside the preset, so it can be opened and changed."""
    clean_name = P.safe_name(name)
    if not clean_name:
        raise ValueError("A preset needs a name.")
    os.makedirs(P.folder(base_dir), exist_ok=True)
    path = design_path(base_dir, clean_name)
    out = dict(clean(design))
    out["name"] = clean_name
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f)
    os.replace(tmp, path)


def load_design(base_dir, name: str) -> dict | None:
    """The drawing a preset was made from: somebody's own, or a shipped one.

    A building that ships with KnoxMap keeps its drawing beside it, so one can
    be opened, changed and saved - which saves it as a building of their own
    and leaves the shipped one alone (knoxbuild/presets.py, library).
    """
    clean_name = P.safe_name(name)
    for where in (P.folder(base_dir), P.library_folder(base_dir)):
        try:
            with open(os.path.join(where, f"{clean_name}{P.DESIGN_SUFFIX}"),
                      encoding="utf-8") as f:
                return clean(json.load(f))
        except (OSError, ValueError):
            continue
    return None


def drop_design(base_dir, name: str) -> bool:
    try:
        os.remove(design_path(base_dir, name))
        return True
    except OSError:
        return False


def keep(base_dir, name: str, design: dict) -> dict:
    """Save a design as a preset: the drawing, and the .tbx it builds into."""
    design = _table(design)
    clean_name = P.safe_name(name or design.get("name") or "")
    if not clean_name:
        raise ValueError("A preset needs a name.")
    design = clean(design)
    if not design["rooms"]:
        raise ValueError("Draw at least one room first.")
    about = P.save(base_dir, clean_name, tbx_text(design, clean_name),
                   kind=design.get("kind") or "")
    save_design(base_dir, clean_name, design)
    about["editable"] = True
    return about
