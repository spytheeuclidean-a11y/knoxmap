"""Furnishing rules: what matters most in a room, where people walk, and
whether a new piece would cut the free floor in two. No import of layout."""
import heapq
from collections import deque

ESSENTIAL, SECONDARY, DECORATION = 0, 1, 2

DECORATION_ROLES = (
    "plant", "erika_plant", "lamp", "shelf", "bookshelf", "erika_shelves",
    "painting", "mirror", "erika_art", "erika_ad", "rug", "shag_rug",
    "bath_mat", "corkboard", "bin")

_KITCHEN = ("fridge", "stove", "kitchen_sink", "counter")
_BED = ("double_bed", "bed", "bunk_bed")
ESSENTIALS = {
    "bathroom": ("toilet", "sink", "bath", "shower"),
    "kitchen": _KITCHEN,
    "openplan": _KITCHEN + ("sofa",),
    "livingroom": ("sofa",),
    "bedroom": _BED,
    "kidsbedroom": _BED,
    "motelroom": _BED,
    "laundry": ("washer",),
    "dining": ("dining_table", "round_table"),
    "closet": ("wardrobe",),
}


def priority(role, room_kind):
    """0 essential, 1 secondary, 2 decoration. Decoration is checked first so
    bath_mat is never read as bath."""
    if role.startswith(DECORATION_ROLES):
        return DECORATION
    if role.startswith(ESSENTIALS.get(room_kind, ())):
        return ESSENTIAL
    return SECONDARY


def in_priority_order(roles, room_kind):
    return sorted(roles, key=lambda r: priority(r, room_kind))


def _near(t):
    x, y = t
    return ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))


def _depth(cells):
    """1 for a tile with a 4-neighbour outside cells, +1 per step inward."""
    depth = {t: 1 for t in cells if any(n not in cells for n in _near(t))}
    todo = deque(sorted(depth))
    while todo:
        t = todo.popleft()
        for n in _near(t):
            if n in cells and n not in depth:
                depth[n] = depth[t] + 1
                todo.append(n)
    return depth


def _path(cells, depth, sources, goal):
    """Cheapest path from any source until goal(tile) is first popped: fewest
    tiles, ties away from walls. Returns the path tiles (source excluded from
    cost, included in the list), or None. A cost is tiles << 20 plus the wall
    tiles among them: one int sorts as the pair did, and faster."""
    best = {s: 0 for s in sources}
    parent = {}
    heap = [(0, y, x) for x, y in sources]
    heapq.heapify(heap)
    pop, push, step = heapq.heappop, heapq.heappush, 1 << 20
    while heap:
        cost, y, x = pop(heap)
        t = (x, y)
        if cost != best[t]:
            continue
        if t not in sources and goal(t):
            path = [t]
            while path[-1] in parent:
                path.append(parent[path[-1]])
            return path
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            d = depth.get(n)  # depth has a value for every tile of cells
            if d is None:
                continue
            c = cost + step + (d == 1)
            b = best.get(n)
            if b is None or c < b:
                best[n] = c
                parent[n] = t
                push(heap, (c, n[1], n[0]))
    return None


_WALKWAYS: dict = {}


def walkway(cells, entries):
    """Tiles that stay free: a path joining the room's ways in, or for a single
    way in a spine to the farthest tile that is off every wall, where the floor
    off the walls is at least two tiles across.

    Remembered by room and ways in: the window pass asks again for most rooms
    the furnishing already asked about, and a mall's concourse costs a search
    per shop door."""
    terminals = sorted({e for e in entries if e in cells})
    if not terminals:
        return set()
    key = (frozenset(cells), tuple(terminals))
    if key not in _WALKWAYS:
        if len(_WALKWAYS) > 512:  # ponytail: crude cap, an LRU if it ever matters
            _WALKWAYS.clear()
        _WALKWAYS[key] = frozenset(_walkway(cells, terminals))
    return set(_WALKWAYS[key])


def _walkway(cells, terminals):
    depth = _depth(cells)
    if len(terminals) == 1:
        start = terminals[0]
        steps = {start: 0}
        todo = deque([start])
        while todo:
            t = todo.popleft()
            for n in _near(t):
                if n in cells and n not in steps:
                    steps[n] = steps[t] + 1
                    todo.append(n)
        inner = {t for t in steps if depth[t] >= 2}
        # Only where the inner floor is two tiles across: a spine down the one
        # inner row of a three-wide room left nothing two deep (a double bed)
        # room on either side, and 117 of 176 such bedrooms lost their bed.
        inner = [(x, y) for x, y in inner
                 if {(x + 1, y), (x - 1, y)} & inner and {(x, y + 1), (x, y - 1)} & inner]
        if not inner:
            return {start}
        target = min(inner, key=lambda t: (-steps[t], t[1], t[0]))
        return set(_path(cells, depth, {start}, lambda t: t == target))
    tree = {terminals[0]}
    pending = set(terminals[1:])
    while pending:
        path = _path(cells, depth, tree, pending.__contains__)
        if path is None:  # unreachable (split cells): leave the rest out
            break
        tree.update(path)
        pending -= tree
    return tree


def keeps_floor_open(cells, blocked, walk, new, pocket):
    """True if placing `new` leaves the walkway untouched and every cut-off
    patch of free floor holds at most `pocket` tiles."""
    if new & walk:
        return False
    free = cells - blocked - new
    seen, comps = set(), []
    for start in sorted(free):
        if start in seen:
            continue
        comp, todo = {start}, [start]
        while todo:
            for n in _near(todo.pop()):
                if n in free and n not in comp:
                    comp.add(n)
                    todo.append(n)
        seen |= comp
        comps.append(comp)
    if not comps:
        return True
    anchor = walk & free
    if anchor:
        main = min(anchor)
        keep = next(c for c in comps if main in c)
    else:
        keep = max(comps, key=len)  # comps are in min-tile order: ties go to the smallest
    return all(len(c) <= pocket for c in comps if c is not keep)

class OpenFloor:
    """keeps_floor_open for one room as its pieces go in. The free floor's
    patches are kept as pieces are put down (block), and both a piece put down
    and a query flood the room only when the new tiles might cut a patch in
    two: when the free tiles beside them do not join up through the free ring
    of tiles about them. The answers are keeps_floor_open's, so a seed lays
    out the same room."""

    def __init__(self, cells, walk, pocket):
        self.cells, self.walk, self.pocket = cells, walk, pocket
        self.blocked = set()
        self.free = None

    def block(self, tiles):
        tiles = set(tiles) - self.blocked
        if not tiles:
            return
        self.blocked |= tiles
        if self.free is None:
            return
        gone = tiles & self.free
        if gone & self.walk or self._splits(gone, tiles):
            self.free = None
            return
        self.free -= gone
        for t in gone:
            self.size[self.patch.pop(t)] -= 1
        self.bad = {n for n in self.bad if self.size[n] > self.pocket}

    def _splits(self, gone, new):
        """Whether taking `new` off the free floor might cut a patch in two."""
        free = self.free
        edge = {n for t in gone for n in _near(t) if n in free and n not in new}
        if not edge:
            return False
        ring = {(x + dx, y + dy) for x, y in gone
                for dx in (-1, 0, 1) for dy in (-1, 0, 1)} & free
        ring -= new
        start = min(edge)
        seen, todo = {start}, [start]
        while todo:
            for t in _near(todo.pop()):
                if t in ring and t not in seen:
                    seen.add(t)
                    todo.append(t)
        return not edge <= seen

    def _patches(self):
        self.free = free = self.cells - self.blocked
        self.patch, self.size = {}, []
        for start in sorted(free):
            if start in self.patch:
                continue
            n = len(self.size)
            self.patch[start], todo, k = n, [start], 1
            while todo:
                for t in _near(todo.pop()):
                    if t in free and t not in self.patch:
                        self.patch[t] = n
                        todo.append(t)
                        k += 1
            self.size.append(k)
        anchor = self.walk & free
        self.keep = self.patch[min(anchor)] if anchor else None
        self.bad = {n for n, k in enumerate(self.size)
                    if n != self.keep and k > self.pocket}

    def keeps_open(self, new):
        new = set(new)
        if new & self.walk:
            return False
        if self.free is None:
            self._patches()
        if self.keep is None:
            return keeps_floor_open(self.cells, self.blocked, self.walk, new, self.pocket)
        gone = new & self.free
        if not gone:
            return not self.bad
        if self._splits(gone, new):
            return keeps_floor_open(self.cells, self.blocked, self.walk, new, self.pocket)
        # No patch is cut in two: each one the new tiles touch just shrinks.
        lost = {}
        for t in gone:
            lost[self.patch[t]] = lost.get(self.patch[t], 0) + 1
        if any(self.size[n] - lost.get(n, 0) > self.pocket for n in self.bad):
            return False
        return all(self.size[n] - k <= self.pocket
                   for n, k in lost.items() if n != self.keep)
