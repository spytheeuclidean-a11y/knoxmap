"""Street furniture and road wear: lamps, signs, hydrants, drains, cracks and litter."""
from __future__ import annotations

import os

from PIL import Image, ImageFilter

from .. import pz_colors as C
from ..osm import ROAD_HIERARCHY_BY_CODE


# How often the vanilla streets have each, measured on their squares
# (tools/building_stats.py's neighbourhoods): grime on 9% of the tarmac, cracks
# on under 0.5%, a lamp per ~290 squares of street, and so on. Spacings are in
# tiles along the kerb.
# The grime was smooth dark patches on the road that read as shadows across it,
# so it is off; set above 0 to bring it back.
GRIME_SHARE = 0.0
# Roads at least this wide get a faded edge line down each side.
EDGE_LINE_MIN_WIDTH = 5
# Straight edge runs shorter than this are staircase steps on a diagonal road;
# placing axis-aligned white edge lines on them leaves broken jagged dashes.
EDGE_LINE_MIN_RUN = 6
CRACK_SHARE = 0.012
LITTER_SHARE = 0.002
LAMP_EVERY = 18
# A hydrant, a bin or a mailbox only stands where there is something for it to
# serve: within this many tiles of a building. Out on open road they were
# street furniture for nobody.
NEAR_BUILDING_TILES = 12
# A speed limit sign every so many tiles along a main street's kerb (Erika's
# Tiles only), with the limit going by how wide the carriageway is.
SPEED_SIGN_EVERY = 80
SPEED_BY_WIDTH = ((12, 45), (8, 35), (0, 25))
BIN_EVERY = 28
MAILBOX_EVERY = 34
# Street furniture besides the essentials: a bench, the news kiosk, the blue
# collection box. A bench is two squares long and needs both free.
BENCH_EVERY = 110
KIOSK_EVERY = 150
POSTBOX_EVERY = 190
# A manhole cover on the pavement, one square in a few hundred.
MANHOLE_SHARE = 0.003
# Which way a prop on each kerb faces. The tools' orient is the direction an
# object points - the kerbs say so, since roads.py puts KERB_W on the strip
# whose road is to its west - so a prop stands with its back to the pavement
# and its face across the carriageway.
FACES_THE_ROAD = {C.EDGE_LINE_W: "E", C.EDGE_LINE_E: "W",
                  C.EDGE_LINE_N: "S", C.EDGE_LINE_S: "N"}
# A bench is backless, so it has no facing: the catalogue draws it in two axes
# (orient W along y, orient N along x) and a bench lies along its kerb.
BENCH_RUNS = {C.EDGE_LINE_W: (C.BENCH_Y, True), C.EDGE_LINE_E: (C.BENCH_Y, True),
              C.EDGE_LINE_N: (C.BENCH_X, False), C.EDGE_LINE_S: (C.BENCH_X, False)}
# A utility pole every so many tiles of kerb. Trunk roads and motorways carry
# their cables on pylons, which are structures of their own.
UTILITY_POLE_EVERY = {
    "motorway": 1 << 30, "trunk": 1 << 30, "primary": 60,
    "secondary": 50, "tertiary": 45, "residential": 40,
    "service": 90, "footway": 1 << 30,
}
ROAD_FURNITURE_INTERVALS = {
    "motorway": {"lamp": 55, "hydrant": 1 << 30, "speed": 55, "drain": 40, "bin": 1 << 30, "mailbox": 1 << 30},
    "trunk": {"lamp": 36, "hydrant": 80, "speed": 65, "drain": 32, "bin": 1 << 30, "mailbox": 1 << 30},
    "primary": {"lamp": 20, "hydrant": 42, "speed": 75, "drain": 24, "bin": 24, "mailbox": 42},
    "secondary": {"lamp": 18, "hydrant": 38, "speed": 85, "drain": 24, "bin": 26, "mailbox": 38},
    "tertiary": {"lamp": 16, "hydrant": 35, "speed": 100, "drain": 24, "bin": 28, "mailbox": 34},
    "residential": {"lamp": 14, "hydrant": 32, "speed": 120, "drain": 24, "bin": 28, "mailbox": 30},
    "service": {"lamp": 30, "hydrant": 75, "speed": 1 << 30, "drain": 34, "bin": 36, "mailbox": 1 << 30},
    "footway": {"lamp": 22, "hydrant": 1 << 30, "speed": 1 << 30, "drain": 1 << 30, "bin": 28, "mailbox": 1 << 30},
}


def _rule_ready(label: str) -> bool:
    """Whether the map tools' Rules.txt carries one of our rules yet.

    A colour with no rule behind it is dropped with a warning, so this is what
    keeps a pole off the verge on an install that Setup has not been run on
    since the poles were added.
    """
    if os.environ.get("KNOXMAP_NO_POLES") == "1":
        return False
    try:
        import knoxpaths
        rules = knoxpaths.mapping_tools_dir() / "config" / "Rules.txt"
        return f"KnoxMap road {label}" in rules.read_text(encoding="utf-8", errors="replace")
    except Exception:      # noqa: BLE001 - no tools, no pole
        return False


def _mod_tiles_ready() -> bool:
    """Whether maps may use Erika's Tiles: installed and set up, and not
    turned off with KNOXMAP_NO_MOD_TILES=1."""
    if os.environ.get("KNOXMAP_NO_MOD_TILES") == "1":
        return False
    try:
        import knoxpaths
        if not knoxpaths.erikas_tiles_ready():
            return False
        # Tools set up before the signs existed have no rule for them, and a
        # colour without a rule is dropped with a warning: run Setup again.
        rules = knoxpaths.mapping_tools_dir() / "config" / "Rules.txt"
        return "KnoxMap road Speed limit 25 S" in rules.read_text(encoding="utf-8", errors="replace")
    except Exception:      # noqa: BLE001 - no tools, no mod tiles
        return False
HYDRANT_EVERY = 38
DRAIN_EVERY = 24


def _long_runs(mask, min_len: int, axis: int):
    """Keep only contiguous True runs of length >= min_len along `axis`."""
    import numpy as np

    if min_len <= 1:
        return mask
    h, w = mask.shape
    if (axis == 1 and w < min_len) or (axis == 0 and h < min_len):
        return np.zeros_like(mask)
    starts = mask.copy()
    for offset in range(1, min_len):
        if axis == 1:
            starts[:, :-offset] &= mask[:, offset:]
            starts[:, -offset:] = False
        else:
            starts[:-offset, :] &= mask[offset:, :]
            starts[-offset:, :] = False
    out = starts.copy()
    for offset in range(1, min_len):
        if axis == 1:
            out[:, offset:] |= starts[:, :-offset]
        else:
            out[offset:, :] |= starts[:-offset, :]
    return out


def _paint_street_furniture(veg: Image.Image, landscape: Image.Image,
                            road_hierarchy: Image.Image | None = None,
                            buildings: Image.Image | None = None) -> dict:
    """Lamps, hydrants and drains along the kerbs; grime, cracks and litter.

    A generated street was clean tarmac, kerb and pavement and nothing else;
    Knox County's have all of these, and a road without them reads as a
    diagram. They go by the kerbs already painted: a lamp stands on the
    pavement one tile back from a straight kerb with its arm over the road, a
    hydrant likewise, a drain in the gutter in front of it.
    """
    import numpy as np

    rng = np.random.default_rng(4321)
    ground = np.asarray(landscape.convert("RGB"))
    vp = np.array(veg.convert("RGB"))
    h, w = ground.shape[:2]
    road_classes = (np.asarray(road_hierarchy.convert("L"))
                    if road_hierarchy is not None else None)

    def is_colour(arr, colours):
        mask = np.zeros(arr.shape[:2], dtype=bool)
        for c in colours:
            mask |= np.all(arr == c, axis=2)
        return mask

    empty = np.all(vp == 0, axis=2)
    asphalt = is_colour(ground, (C.MEDIUM_ASPHALT, C.DARKEST_ASPHALT))
    driveable = is_colour(ground, (C.MEDIUM_ASPHALT, C.DARK_ASPHALT,
                                  C.DARKEST_ASPHALT))
    pavement = is_colour(ground, (C.PALE_CONCRETE,))
    roadside = is_colour(
        ground, (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS, C.PAVING,
                 C.DIRT_ROWS_H, C.DIRT_ROWS_V))
    # Hydrants, bins and mailboxes stand on the grass or paving beside the
    # sidewalk, never on the sidewalk itself, and only where there is a
    # building to serve: down an open stretch of road they were furniture for
    # nobody.
    verge = is_colour(ground, (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS,
                               C.PAVING))
    near_buildings = None
    if buildings is not None:
        from . import native_pixels

        mask = buildings if buildings.mode == "L" else buildings.convert("L")
        mw, mh = mask.size
        raw = native_pixels.box_any(mask.tobytes(), mw, mh, NEAR_BUILDING_TILES)
        if raw is not None:
            near_buildings = np.frombuffer(raw, dtype=bool).reshape(mh, mw).copy()
        else:
            reach = ImageFilter.MaxFilter(2 * NEAR_BUILDING_TILES + 1)
            near_buildings = np.asarray(mask.filter(reach)) > 0
    counts = {}

    # Edge lines: tarmac with the road's edge on exactly one side and enough
    # road across from it to be a carriageway, not a car park aisle's end.
    # (Dark tarmac, 100, is car parks and yards, and is left out.)
    k = EDGE_LINE_MIN_WIDTH
    edge_lines = 0
    diag_kerbs = {}
    # What counts as "no road on the far side": a car park's dark tarmac is
    # road too, and a kerb drawn against it stood in the middle of a paved
    # yard in game - a white strip with nothing to kerb.
    beside = driveable
    for colour, (dx, dy) in ((C.EDGE_LINE_W, (-1, 0)), (C.EDGE_LINE_E, (1, 0)),
                             (C.EDGE_LINE_N, (0, -1)), (C.EDGE_LINE_S, (0, 1))):
        outside = np.zeros_like(asphalt)
        across = np.ones_like(asphalt)
        if dx:
            if dx < 0:
                outside[:, 1:] = ~beside[:, :-1]
                for i in range(1, k):
                    across[:, :-i] &= asphalt[:, i:]
                    across[:, -i:] = False
            else:
                outside[:, :-1] = ~beside[:, 1:]
                for i in range(1, k):
                    across[:, i:] &= asphalt[:, :-i]
                    across[:, :i] = False
            side_a = np.zeros_like(asphalt); side_b = np.zeros_like(asphalt)
            side_a[1:, :] = asphalt[:-1, :]; side_b[:-1, :] = asphalt[1:, :]
        else:
            if dy < 0:
                outside[1:, :] = ~beside[:-1, :]
                for i in range(1, k):
                    across[:-i, :] &= asphalt[i:, :]
                    across[-i:, :] = False
            else:
                outside[:-1, :] = ~beside[1:, :]
                for i in range(1, k):
                    across[i:, :] &= asphalt[:-i, :]
                    across[:i, :] = False
            side_a = np.zeros_like(asphalt); side_b = np.zeros_like(asphalt)
            side_a[:, 1:] = asphalt[:, :-1]; side_b[:, :-1] = asphalt[:, 1:]
        # Straight edges only: the road continues along the line both ways, and
        # the run is long enough not to be a staircase step on a diagonal road.
        candidate = asphalt & outside & across
        long_edge = _long_runs(candidate, EDGE_LINE_MIN_RUN, 0 if dx else 1)
        pick = long_edge & side_a & side_b & empty
        diag_kerbs[colour] = candidate & (side_a | side_b) & ~pick
        vp[pick] = colour
        empty &= ~pick
        edge_lines += int(pick.sum())
    counts["edge lines"] = edge_lines

    # Along each straight edge of the carriageway, road on one side: the lamp
    # stands a tile or two off the tarmac (past the kerb or on the verge) with
    # its arm reaching back over the road, the drain sits in the gutter.
    # (edge colour just painted, step away from the road, lamp colour)
    straight = [(C.EDGE_LINE_W, (-1, 0), C.LAMP_E), (C.EDGE_LINE_E, (1, 0), C.LAMP_W),
                (C.EDGE_LINE_N, (0, -1), C.LAMP_S), (C.EDGE_LINE_S, (0, 1), C.LAMP_N)]
    taken: dict[str, set] = {
        "lamp": set(), "hydrant": set(), "drain": set(), "speed": set(),
        "bin": set(), "mailbox": set(), "pole": set(), "bench": set(),
        "kiosk": set(), "postbox": set(),
    }
    pole = C.UTILITY_POLE if _rule_ready("Utility pole") else None
    # The kiosk and the collection box face out from the pavement, across the
    # road they stand beside.
    kiosk = None if not _rule_ready("Kiosk N") else {
        "N": C.KIOSK_N, "E": C.KIOSK_E, "S": C.KIOSK_S, "W": C.KIOSK_W}
    postbox = None if not _rule_ready("Postbox N") else {
        "N": C.POSTBOX_N, "E": C.POSTBOX_E, "S": C.POSTBOX_S, "W": C.POSTBOX_W}
    out = vp.copy()
    # Speed signs stand where drivers keeping right see their faces: on the
    # east kerb of a north-south road facing south, the north kerb of an
    # east-west one facing east. Erika's signs only face those two ways.
    speed_side = {C.EDGE_LINE_E: "S", C.EDGE_LINE_N: "E"} if _mod_tiles_ready() else {}

    def carriageway(gx, gy, sx, sy):
        n = 0
        while n < 24 and 0 <= gx - n * sx < w and 0 <= gy - n * sy < h \
                and asphalt[gy - n * sy, gx - n * sx]:
            n += 1
        return n

    def hierarchy_at(gx, gy, sx, sy):
        if road_classes is None:
            return None
        for n in range(24):
            x, y = gx - n * sx, gy - n * sy
            if not (0 <= x < w and 0 <= y < h):
                break
            if asphalt[y, x] and road_classes[y, x]:
                return ROAD_HIERARCHY_BY_CODE.get(int(road_classes[y, x]))
        return None

    def beside_the_pavement(gx, gy, sx, sy):
        """The first free grass or paving tile that touches the sidewalk."""
        for n in range(2, 6):
            x, y = gx + n * sx, gy + n * sy
            if not (0 <= x < w and 0 <= y < h):
                return None
            if not (empty[y, x] and not driveable[y, x] and verge[y, x]):
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and pavement[ny, nx]:
                    return x, y
        return None

    def off_the_pavement(gx, gy, sx, sy):
        """First free non-sidewalk roadside tile off the kerb."""
        x1, y1 = gx + sx, gy + sy
        x2, y2 = gx + 2 * sx, gy + 2 * sy
        if (0 <= x1 < w and 0 <= y1 < h and 0 <= x2 < w and 0 <= y2 < h
                and pavement[y2, x2] and empty[y1, x1]
                and not driveable[y1, x1] and roadside[y1, x1]):
            return x1, y1
        for n in range(2, 6):
            x, y = gx + n * sx, gy + n * sy
            if not (0 <= x < w and 0 <= y < h) or driveable[y, x]:
                return None
            if empty[y, x] and roadside[y, x]:
                return x, y
        return None

    for edge, (sx, sy), lamp in straight:
        kerb_mask = np.all(vp == edge, axis=2) | diag_kerbs[edge]
        ys, xs = np.nonzero(kerb_mask)
        order = rng.permutation(len(xs))
        for i in order.tolist():
            gx, gy = int(xs[i]), int(ys[i])     # the gutter square itself
            bx, by = gx + 2 * sx, gy + 2 * sy   # past the kerb or the verge
            if not (0 <= bx < w and 0 <= by < h):
                continue
            hierarchy = hierarchy_at(gx, gy, sx, sy)
            spacing = ROAD_FURNITURE_INTERVALS.get(hierarchy, {})
            facing = speed_side.get(edge)
            speed = None
            if facing:
                across = carriageway(gx, gy, sx, sy)
                limit = next(v for width, v in SPEED_BY_WIDTH if across >= width)
                speed = C.SPEED_SIGNS[(limit, facing)]
            for what, every, colour, at, partner in (
                    ("speed", spacing.get("speed", SPEED_SIGN_EVERY), speed, (bx, by), None),
                    ("lamp", spacing.get("lamp", LAMP_EVERY), lamp, (bx, by), None),
                    ("hydrant", spacing.get("hydrant", HYDRANT_EVERY), C.HYDRANT, (bx, by), None),
                    ("bin", spacing.get("bin", BIN_EVERY), C.BIN, (bx, by), None),
                    ("mailbox", spacing.get("mailbox", MAILBOX_EVERY), C.MAILBOX, (bx, by), None),
                    ("kiosk", KIOSK_EVERY,
                     kiosk.get(FACES_THE_ROAD[edge]) if kiosk else None, (bx, by), None),
                    ("postbox", POSTBOX_EVERY,
                     postbox.get(FACES_THE_ROAD[edge]) if postbox else None, (bx, by), None),
                    # Last of the verge props, so a lamp or a hydrant that is
                    # due on the same square keeps it: the poles fall in the
                    # gaps between them, as they do along a real street.
                    ("pole", UTILITY_POLE_EVERY.get(hierarchy, 55), pole, (bx, by), None),
                    ("drain", spacing.get("drain", DRAIN_EVERY), C.STORM_DRAIN, (gx, gy), None)):
                if every >= (1 << 29):
                    continue
                px, py = at
                if what in ("hydrant", "bin", "mailbox", "kiosk", "postbox"):
                    spot = beside_the_pavement(gx, gy, sx, sy)
                    if spot is None:
                        continue
                    px, py = spot
                    if near_buildings is not None and not near_buildings[py, px]:
                        continue
                elif what in ("speed", "lamp", "pole"):
                    spot = off_the_pavement(gx, gy, sx, sy)
                    if spot is None:
                        continue
                    px, py = spot
                if colour is None or not (0 <= px < w and 0 <= py < h):
                    continue
                # Speed signs keep a spacing per facing: the north-south roads,
                # met first, took every cell and left east-west ones none.
                cell = (px // every, py // every, facing if what == "speed" else None)
                if cell in taken[what]:
                    continue
                # A drain takes the gutter square from its edge line; other
                # props need an empty sidewalk or verge tile, not a road or lot.
                if what == "drain" and not np.array_equal(vp[py, px], edge):
                    continue
                if what != "drain" and (not empty[py, px] or driveable[py, px]
                                         or not roadside[py, px]):
                    continue
                if partner is not None:
                    p_colour, (px2, py2) = partner
                    if not (0 <= px2 < w and 0 <= py2 < h) \
                            or not empty[py2, px2] or driveable[py2, px2] \
                            or not roadside[py2, px2]:
                        continue
                    out[py2, px2] = p_colour
                    empty[py2, px2] = False
                taken[what].add(cell)
                out[py, px] = colour
                empty[py, px] = False
                counts[what] = counts.get(what, 0) + 1
                break

    # Wear comes in patches, as it does on a real road and on the vanilla
    # map; picked square by square it came out as a chequerboard. Smooth noise
    # - coarse random values, blurred up to full size - gives the patches.
    coarse = Image.fromarray((rng.random((max(1, h // 5), max(1, w // 5))) * 255).astype(np.uint8))
    noise = np.asarray(coarse.resize((w, h), Image.BICUBIC)
                       .filter(ImageFilter.GaussianBlur(2)), dtype=np.float32)
    level = (np.quantile(noise[asphalt], 1 - GRIME_SHARE)
             if GRIME_SHARE > 0 and asphalt.any() else 256)
    pick = asphalt & empty & (noise >= level)
    out[pick] = C.ASPHALT_GRIME
    empty &= ~pick
    counts["grime"] = int(pick.sum())
    # Scattered things: each square rolls once, and each kind has its own band
    # of the roll, so no square gets two.
    roll = rng.random((h, w))
    scattered = [(asphalt, CRACK_SHARE, C.ASPHALT_CRACKS, "cracks"),
                 (pavement, LITTER_SHARE, C.LITTER, "litter")]
    if _rule_ready("Manhole cover"):
        scattered.append((pavement, MANHOLE_SHARE, C.MANHOLE, "manholes"))
    lo = 0.0
    for mask, share, colour, name in scattered:
        pick = mask & empty & (roll >= lo) & (roll < lo + share)
        lo += share
        out[pick] = colour
        empty &= ~pick
        counts[name] = int(pick.sum())
    # Benches: three squares along the kerb with the seat facing the road. They
    # need the whole run free, so they take a pass of their own rather than a
    # square in the props loop.
    if _rule_ready("Bench Y0"):
        for edge, (sx, sy), _lamp in straight:
            tiles, along_y = BENCH_RUNS[edge]
            dx, dy = (0, 1) if along_y else (1, 0)
            kerb_mask = np.all(vp == edge, axis=2) | diag_kerbs[edge]
            ys, xs = np.nonzero(kerb_mask)
            for i in rng.permutation(len(xs)).tolist():
                gx, gy = int(xs[i]), int(ys[i])
                # A bench leans on a straight kerb. On a road at an angle the
                # kerb steps a square at a time, so the squares either side of
                # this one along its own axis are road, not edge - and a seat
                # laid along that step hangs off the pavement.
                if along_y:
                    if not (0 < gy < h - 1 and kerb_mask[gy - 1, gx]
                            and kerb_mask[gy + 1, gx]):
                        continue
                elif not (0 < gx < w - 1 and kerb_mask[gy, gx - 1]
                          and kerb_mask[gy, gx + 1]):
                    continue
                spot = beside_the_pavement(gx, gy, sx, sy)
                if spot is None:
                    continue
                px, py = spot
                if near_buildings is not None and not near_buildings[py, px]:
                    continue
                cell = (px // BENCH_EVERY, py // BENCH_EVERY)
                if cell in taken["bench"]:
                    continue
                run = [(px + k * dx, py + k * dy) for k in range(len(tiles))]
                if not all(0 <= x < w and 0 <= y < h and empty[y, x]
                           and not driveable[y, x] and roadside[y, x] for x, y in run):
                    continue
                for (x, y), colour in zip(run, tiles):
                    out[y, x] = colour
                    empty[y, x] = False
                taken["bench"].add(cell)
                counts["bench"] = counts.get("bench", 0) + 1
    veg.paste(Image.fromarray(out), (0, 0))
    return counts
