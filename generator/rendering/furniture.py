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
CRACK_SHARE = 0.012
LITTER_SHARE = 0.002
LAMP_EVERY = 18
# A speed limit sign every so many tiles along a main street's kerb (Erika's
# Tiles only), with the limit going by how wide the carriageway is.
SPEED_SIGN_EVERY = 80
SPEED_BY_WIDTH = ((12, 45), (8, 35), (0, 25))
BENCH_EVERY = 32
BIN_EVERY = 28
MAILBOX_EVERY = 34
ROAD_FURNITURE_INTERVALS = {
    "motorway": {"lamp": 55, "hydrant": 1 << 30, "speed": 55, "drain": 40,
                 "bench": 1 << 30, "bin": 1 << 30, "mailbox": 1 << 30},
    "trunk": {"lamp": 36, "hydrant": 80, "speed": 65, "drain": 32,
              "bench": 1 << 30, "bin": 1 << 30, "mailbox": 1 << 30},
    "primary": {"lamp": 20, "hydrant": 42, "speed": 75, "drain": 24,
                "bench": 28, "bin": 24, "mailbox": 42},
    "secondary": {"lamp": 18, "hydrant": 38, "speed": 85, "drain": 24,
                  "bench": 30, "bin": 26, "mailbox": 38},
    "tertiary": {"lamp": 16, "hydrant": 35, "speed": 100, "drain": 24,
                 "bench": 32, "bin": 28, "mailbox": 34},
    "residential": {"lamp": 14, "hydrant": 32, "speed": 120, "drain": 24,
                    "bench": 34, "bin": 28, "mailbox": 30},
    "service": {"lamp": 30, "hydrant": 75, "speed": 1 << 30, "drain": 34,
                "bench": 1 << 30, "bin": 36, "mailbox": 1 << 30},
    "footway": {"lamp": 22, "hydrant": 1 << 30, "speed": 1 << 30, "drain": 1 << 30,
                "bench": 26, "bin": 28, "mailbox": 1 << 30},
}


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


def _paint_street_furniture(veg: Image.Image, landscape: Image.Image,
                            road_hierarchy: Image.Image | None = None) -> dict:
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
    roadside = pavement | is_colour(
        ground, (C.DARK_GRASS, C.MEDIUM_GRASS, C.LIGHT_GRASS, C.PAVING))
    counts = {}

    # Edge lines: tarmac with the road's edge on exactly one side and enough
    # road across from it to be a carriageway, not a car park aisle's end.
    # (Dark tarmac, 100, is car parks and yards, and is left out.)
    k = EDGE_LINE_MIN_WIDTH
    edge_lines = 0
    diag_kerbs = {}
    for colour, (dx, dy) in ((C.EDGE_LINE_W, (-1, 0)), (C.EDGE_LINE_E, (1, 0)),
                             (C.EDGE_LINE_N, (0, -1)), (C.EDGE_LINE_S, (0, 1))):
        outside = np.zeros_like(asphalt)
        across = np.ones_like(asphalt)
        if dx:
            if dx < 0:
                outside[:, 1:] = ~asphalt[:, :-1]
                for i in range(1, k):
                    across[:, :-i] &= asphalt[:, i:]
                    across[:, -i:] = False
            else:
                outside[:, :-1] = ~asphalt[:, 1:]
                for i in range(1, k):
                    across[:, i:] &= asphalt[:, :-i]
                    across[:, :i] = False
            side_a = np.zeros_like(asphalt); side_b = np.zeros_like(asphalt)
            side_a[1:, :] = asphalt[:-1, :]; side_b[:-1, :] = asphalt[1:, :]
        else:
            if dy < 0:
                outside[1:, :] = ~asphalt[:-1, :]
                for i in range(1, k):
                    across[:-i, :] &= asphalt[i:, :]
                    across[-i:, :] = False
            else:
                outside[:-1, :] = ~asphalt[1:, :]
                for i in range(1, k):
                    across[i:, :] &= asphalt[:-i, :]
                    across[:i, :] = False
            side_a = np.zeros_like(asphalt); side_b = np.zeros_like(asphalt)
            side_a[:, 1:] = asphalt[:, :-1]; side_b[:, :-1] = asphalt[:, 1:]
        # Straight edges only: the road continues along the line both ways.
        pick = asphalt & outside & across & side_a & side_b & empty
        diag_kerbs[colour] = asphalt & outside & across & (side_a | side_b) & ~pick
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
        "bench": set(), "bin": set(), "mailbox": set(),
    }
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
            bench_pair = ((C.TABLE_Y0, C.TABLE_Y1, (bx, by + 1))
                          if sx else (C.TABLE_X0, C.TABLE_X1, (bx + 1, by)))
            for what, every, colour, at, partner in (
                    ("speed", spacing.get("speed", SPEED_SIGN_EVERY), speed, (bx, by), None),
                    ("lamp", spacing.get("lamp", LAMP_EVERY), lamp, (bx, by), None),
                    ("hydrant", spacing.get("hydrant", HYDRANT_EVERY), C.HYDRANT, (bx, by), None),
                    ("bench", spacing.get("bench", BENCH_EVERY), bench_pair[0], (bx, by), (bench_pair[1], bench_pair[2])),
                    ("bin", spacing.get("bin", BIN_EVERY), C.BIN, (bx, by), None),
                    ("mailbox", spacing.get("mailbox", MAILBOX_EVERY), C.MAILBOX, (bx, by), None),
                    ("drain", spacing.get("drain", DRAIN_EVERY), C.STORM_DRAIN, (gx, gy), None)):
                if every >= (1 << 29):
                    continue
                px, py = at
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
    lo = 0.0
    for mask, share, colour, name in (
            (asphalt, CRACK_SHARE, C.ASPHALT_CRACKS, "cracks"),
            (pavement, LITTER_SHARE, C.LITTER, "litter")):
        pick = mask & empty & (roll >= lo) & (roll < lo + share)
        lo += share
        out[pick] = colour
        empty &= ~pick
        counts[name] = int(pick.sum())
    veg.paste(Image.fromarray(out), (0, 0))
    return counts
