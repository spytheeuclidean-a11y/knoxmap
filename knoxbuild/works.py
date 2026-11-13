"""Works yards: the paved yard round each industrial building and what stands
in it.

An industrial estate used to be gravel from fence to fence, a beige plain with
the works standing in it and nothing else. The estate's land is grass now
(generator/rendering/landcover.py), and each works gets what Knox County's have:
a tarmac yard round it, worn at the edges where it meets the grass, a drive out
to the road, cars parked in front, a dumpster by the wall, and pallets, drums,
barrels, crates and tyres stood along it. Run from yards.paint_paths, on the
same ground and vegetation bitmaps, after the houses.
"""
from __future__ import annotations

import math
from collections import deque

from generator import pz_colors as C

WORKS_KINDS = ("industrial",)
YARD_MIN, YARD_MAX = 6, 10       # tiles of yard out from the walls
YARD_EDGE = 3                    # worn ground past the yard: gravel, dirt, weeds
EDGE_WEAR = (0.55, 0.3, 0.12)    # how much of each row of it is worn, nearest first
DRIVE_MAX = 120
DRIVE_WIDTH = 3
CLUTTER_EVERY = 9                # tiles of wall per stack of clutter
# Wear on the yard's tarmac, as the street pass has it on the roads.
GRIME_SHARE = 0.0     # no dark patches on the tarmac, as on the roads
CRACK_SHARE = 1 / 14
# (colour, fewest and most in a row along the wall)
CLUTTER = [(C.WORKS_PALLET, (2, 4)), (C.WORKS_BRICKS, (1, 3)), (C.WORKS_DRUM, (2, 4)),
           (C.WORKS_BARREL, (2, 3)), (C.WORKS_CRATE, (2, 4)), (C.WORKS_TIRES, (1, 3))]
# A dumpster is two tiles and the game has it facing two ways: along a wall
# that runs east-west (S) or north-south (E), first tile then second.
DUMPSTERS = [{"S": (C.DUMPSTER_BLUE_S0, C.DUMPSTER_BLUE_S1),
              "E": (C.DUMPSTER_BLUE_E0, C.DUMPSTER_BLUE_E1)},
             {"S": (C.DUMPSTER_ORANGE_S0, C.DUMPSTER_ORANGE_S1),
              "E": (C.DUMPSTER_ORANGE_E0, C.DUMPSTER_ORANGE_E1)}]
PARKING_DEPTH = 5


def yard_width(bw: int, bh: int) -> int:
    """How far the yard runs out from the walls: wider round a bigger works."""
    return max(YARD_MIN, min(YARD_MAX, round(math.sqrt(bw * bh) / 4)))


def dress_works(rows: list[dict], door_lists: dict, cv, drives: list | None, rng) -> int:
    """Yards for the works in `rows`. `cv` is paint_paths' canvas: ground,
    veg, w, h, free(x, y), paint(x, y, colour), paved_at, occupied_at and
    claimed_bytes. Returns the works given a yard."""
    w = cv.w
    done = 0
    for row in rows:
        if row.get("kind") not in WORKS_KINDS:
            continue
        x0, y0, bw, bh = row["tile_x"], row["tile_y"], row["width"], row["height"]
        doors = door_lists.get(row["file"], [])
        r = yard_width(bw, bh)

        def ring(x, y):
            """How many tiles out from the building's rectangle a square is."""
            return max(x0 - x, x - (x0 + bw - 1), y0 - y, y - (y0 + bh - 1), 0)

        yard = {(x, y) for y in range(y0 - r, y0 + bh + r) for x in range(x0 - r, x0 + bw + r)
                if cv.free(x, y)}
        if not yard:
            continue
        # The squares at the doors, two out, and either side of the step,
        # where nothing is stood.
        fronts = set()
        for ox, oy, ix, iy in doors:
            dx, dy = ox - ix, oy - iy
            sx, sy = x0 + ox, y0 + oy
            fronts |= {(sx + dx * k, sy + dy * k) for k in range(3)}
            fronts |= {(sx - dy, sy + dx), (sx + dy, sy - dx)}

        # The drive: from the yard to the nearest road or paving, unless the
        # yard is on one already.
        door = (x0 + doors[0][0], y0 + doors[0][1]) if doors else (x0, y0)
        drive = _drive(yard, cv, door)
        for x, y in yard:
            cv.paint(x, y, C.MEDIUM_ASPHALT)
            cv.paved_at[y * w + x] = True
        for x, y in drive:
            cv.paint(x, y, C.MEDIUM_ASPHALT)
            cv.paved_at[y * w + x] = True

        # Where the tarmac gives out: gravel, dirt and weeds into the grass.
        for y in range(y0 - r - YARD_EDGE, y0 + bh + r + YARD_EDGE):
            for x in range(x0 - r - YARD_EDGE, x0 + bw + r + YARD_EDGE):
                k = ring(x, y) - r - 1
                if not 0 <= k < YARD_EDGE or not cv.free(x, y):
                    continue
                roll = rng.random()
                if roll < EDGE_WEAR[k]:
                    cv.paint(x, y, C.LIGHT_ASPHALT if rng.random() < 0.65 else C.DIRT)
                elif roll < EDGE_WEAR[k] + 0.25 and cv.veg is not None:
                    cv.veg[y, x] = C.SHORT_GRASS

        taken = set(fronts)

        def can(x, y):
            return (x, y) in yard and (x, y) not in taken and cv.veg is not None

        def stand(x, y, colour):
            if not can(x, y):
                return False
            cv.veg[y, x] = colour
            taken.add((x, y))
            return True

        # Along the walls: the squares of the yard next to the building.
        wall = [(x, y) for x, y in yard if ring(x, y) == 1]
        cx, cy = x0 + bw / 2, y0 + bh / 2
        wall.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
        _dumpster(wall, x0, y0, bw, bh, doors, can, stand, rng)
        i = rng.randrange(CLUTTER_EVERY)
        while i < len(wall):
            colour, (lo, hi) = rng.choice(CLUTTER)
            n, run = rng.randint(lo, hi), []
            for p in wall[i:i + hi + 2]:
                if len(run) == n:
                    break
                if p in taken:
                    continue
                if run and abs(p[0] - run[-1][0]) + abs(p[1] - run[-1][1]) != 1:
                    break
                run.append(p)
            for p in run:
                stand(*p, colour)
            i += CLUTTER_EVERY + rng.randrange(-2, 3)

        # Lights at two corners of the yard, their arms over it.
        for (x, y), lamp in (((x0 - r, y0 - r), C.LAMP_S), ((x0 + bw + r - 1, y0 + bh + r - 1), C.LAMP_N)):
            stand(x, y, lamp)

        # Cars parked in front of the first door, past its step.
        if drives is not None and doors:
            ox, oy, ix, iy = doors[0]
            dx, dy = ox - ix, oy - iy
            sx, sy = x0 + ox, y0 + oy
            depth = min(PARKING_DEPTH, r - 3)
            if depth > 0:
                if dy:
                    a, b = sorted((sy + dy * 3, sy + dy * (2 + depth)))
                    spot = (max(x0, sx - 6), a, min(12, bw), b - a + 1)
                else:
                    a, b = sorted((sx + dx * 3, sx + dx * (2 + depth)))
                    spot = (a, max(y0, sy - 6), b - a + 1, min(12, bh))
                drives.append(spot)
                px, py, pw, ph = spot
                taken |= {(x, y) for x in range(px, px + pw) for y in range(py, py + ph)}

        # Wear on the rest of the tarmac.
        if cv.veg is not None:
            for x, y in yard:
                if (x, y) in taken:
                    continue
                roll = rng.random()
                if roll < GRIME_SHARE:
                    cv.veg[y, x] = C.ASPHALT_GRIME
                elif roll < GRIME_SHARE + CRACK_SHARE:
                    cv.veg[y, x] = C.ASPHALT_CRACKS
        done += 1
    return done


def _drive(yard: set, cv, door: tuple[int, int]) -> list:
    """The squares of a drive from `yard` to the nearest road or paving, three
    wide, leaving the yard as near the front door as it can; none when the
    yard already meets one or none is in reach."""
    w, h = cv.w, cv.h
    paved_at = cv.paved_at
    queue = deque()
    prev = {}
    # Searched from the squares nearest the door first, so of the ways out
    # that are equally short the one from the front wins.
    for x, y in sorted(yard, key=lambda p: (abs(p[0] - door[0]) + abs(p[1] - door[1]), p)):
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in yard or not (0 <= nx < w and 0 <= ny < h):
                continue
            if paved_at[ny * w + nx] and not cv.occupied_at[ny * w + nx]:
                return []
        prev[(x, y)] = None
        queue.append((x, y, 0))
    end = None
    while queue:
        x, y, n = queue.popleft()
        if (x, y) not in yard and paved_at[y * w + x]:
            end = (x, y)
            break
        if n >= DRIVE_MAX:
            continue
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in prev or not (0 <= nx < w and 0 <= ny < h):
                continue
            if paved_at[ny * w + nx] and not cv.occupied_at[ny * w + nx] or cv.free(nx, ny):
                prev[(nx, ny)] = (x, y)
                queue.append((nx, ny, n + 1))
    if end is None:
        return []
    route = []
    step = prev[end]
    while step is not None and step not in yard:
        route.append(step)
        step = prev[step]
    out = []
    for i, (x, y) in enumerate(route):
        before, after = route[max(0, i - 1)], route[min(len(route) - 1, i + 1)]
        across = ((x, y - 1), (x, y), (x, y + 1)) if before[0] != after[0] else \
            ((x - 1, y), (x, y), (x + 1, y))
        out += [p for p in across[:DRIVE_WIDTH] if cv.free(*p)]
    return out


def _dumpster(wall, x0, y0, bw, bh, doors, can, stand, rng) -> bool:
    """One dumpster against the wall, as near a door as it can stand without
    being in the way of one."""
    near = [(x0 + ox, y0 + oy) for ox, oy, _ix, _iy in doors] or [(x0, y0)]
    spots = []
    on_wall = set(wall)
    for x, y in wall:
        if (x + 1, y) in on_wall and (y == y0 - 1 or y == y0 + bh):
            spots.append(((x, y), (x + 1, y), "S"))
        if (x, y + 1) in on_wall and (x == x0 - 1 or x == x0 + bw):
            spots.append(((x, y), (x, y + 1), "E"))
    spots.sort(key=lambda s: min(abs(s[0][0] - a) + abs(s[0][1] - b) for a, b in near))
    colours = rng.choice(DUMPSTERS)
    for a, b, facing in spots:
        if can(*a) and can(*b):
            first, second = colours[facing]
            stand(*a, first)
            stand(*b, second)
            return True
    return False
