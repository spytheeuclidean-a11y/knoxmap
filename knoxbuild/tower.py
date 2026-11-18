"""Office-tower interiors: which buildings qualify and where the core goes.

A tower core is one block near the middle of the floor, the same on every
storey: a stair hall (the lift lobby), a row of lifts along one long side of
it with their doors on the hall, and a toilet plus a riser room on the other.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import layout

TOWER_FROM_LEVELS = 12
TOWER_MIN_SIDE = 14
PLANT_SHARE = 0.9      # the plant floor sits this far up the building
SERVICE_WIDE = 4       # toilet and riser: deep enough to be rooms
HALL_MIN_LONG = layout.STAIR_RUN + 1
# A core further than this from the middle is not a tower core: no fit, no tower.
CENTRE_SLACK = 4

Rect = tuple[int, int, int, int]
Door = tuple[int, int, str]


def qualifies(kind: str | None, levels: int, width: int, height: int) -> bool:
    return (kind == "civic" and levels >= TOWER_FROM_LEVELS
            and min(width, height) >= TOWER_MIN_SIDE)


def plant_level(levels: int) -> int:
    return round(levels * PLANT_SHARE)


@dataclass
class TowerCore:
    stair: Rect
    lifts: list[tuple[Rect, Door]] = field(default_factory=list)
    service: list[tuple[Rect, str]] = field(default_factory=list)


def _lift_count(width: int, height: int) -> int:
    area = width * height
    return 2 if area < 400 else 3 if area < 700 else 4


def _shape(n: int, lifts_west: bool) -> TowerCore:
    """The core of an N-S hall with its top-left corner at (0, 0)."""
    s, wide = layout.SHAFT_SIZE, 1
    long_ = max(HALL_MIN_LONG, s * n)
    hx = s if lifts_west else SERVICE_WIDE
    svc_x = hx + wide if lifts_west else 0
    lift_x = 0 if lifts_west else hx + wide
    door_x = hx if lifts_west else lift_x
    core = TowerCore(stair=(hx, 0, hx + wide - 1, long_ - 1))
    for i in range(n):
        y = s * i
        core.lifts.append(((lift_x, y, lift_x + s - 1, y + s - 1), (door_x, y, "W")))
    # One toilet and the riser, stacked down the far side. Every tower gets
    # exactly these two: the hall is at most 8 long (4 lifts of 2), and a
    # third room would make each thinner than MIN_ROOM, a sliver that
    # layout._mend_fragments folds away.
    kinds = ("bathroom", "storage")
    each = long_ // len(kinds)
    for i, kind in enumerate(kinds):
        y = each * i
        h = each if i < len(kinds) - 1 else long_ - y
        core.service.append(((svc_x, y, svc_x + SERVICE_WIDE - 1, y + h - 1), kind))
    return core


def _moved(core: TowerCore, ox: int, oy: int, across: bool) -> TowerCore:
    """Shift to (ox, oy); `across` turns it to run east-west (x and y swap)."""
    def mv(rc: Rect) -> Rect:
        x0, y0, x1, y1 = rc
        if across:
            x0, y0, x1, y1 = y0, x0, y1, x1
        return x0 + ox, y0 + oy, x1 + ox, y1 + oy

    def door(d: Door) -> Door:
        x, y, o = d
        return (y + ox, x + oy, "N") if across else (x + ox, y + oy, o)

    return TowerCore(mv(core.stair),
                     [(mv(rc), door(d)) for rc, d in core.lifts],
                     [(mv(rc), k) for rc, k in core.service])


def pick_core(width: int, height: int, mask: list[list[bool]] | None,
              rng: random.Random) -> TowerCore | None:
    """The tower core nearest the middle of the footprint, or None if the
    mask has no room for the whole core block (it is one rectangle, as the
    spec has it, so a notch in its corner rules it out)."""
    for n in range(_lift_count(width, height), 1, -1):
        best: list[TowerCore] = []
        best_score = None
        for west in (True, False):
            base = _shape(n, west)
            bw = SERVICE_WIDE + layout.CORE_WIDE + layout.SHAFT_SIZE
            bl = base.stair[3] + 1
            for across in (False, True):
                w, h = (bl, bw) if across else (bw, bl)
                for oy in range(height - h + 1):
                    for ox in range(width - w + 1):
                        core = _moved(base, ox, oy, across)
                        sx0, sy0, sx1, sy1 = core.stair
                        dx = abs((sx0 + sx1 + 1) / 2 - width / 2)
                        dy = abs((sy0 + sy1 + 1) / 2 - height / 2)
                        if dx > CENTRE_SLACK or dy > CENTRE_SLACK:
                            continue
                        score = dx + dy
                        if best_score is not None and score > best_score + 1e-9:
                            continue
                        if mask is not None and not all(
                                mask[y][x] for y in range(oy, oy + h)
                                for x in range(ox, ox + w)):
                            continue
                        if best_score is None or score < best_score - 1e-9:
                            best_score, best = score, [core]
                        else:
                            best.append(core)
        if best:
            return rng.choice(best)
    return None
