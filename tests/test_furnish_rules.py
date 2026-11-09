import copy
import random
import unittest
from unittest import mock

from knoxbuild import catalog, layout
from knoxbuild import furnish_rules as FR
from knoxbuild.furnish_rules import (
    DECORATION, DECORATION_ROLES, ESSENTIAL, ESSENTIALS, SECONDARY,
    in_priority_order, keeps_floor_open, priority, walkway)


def rect(w, h):
    return {(x, y) for x in range(w) for y in range(h)}


def connected(tiles):
    if not tiles:
        return True
    start = min(tiles)
    seen, todo = {start}, [start]
    while todo:
        x, y = todo.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n in tiles and n not in seen:
                seen.add(n)
                todo.append(n)
    return seen == set(tiles)


def _sample():
    for kind in ("house", "apartment"):
        for seed in range(30):
            rng = random.Random(seed)
            w = rng.randint(9, 20)
            h = rng.randint(8, 16)
            levels = rng.randint(1, 3) if kind == "house" else rng.randint(3, 5)
            yield kind, seed, dict(width=w, height=h, levels=levels, kind=kind, seed=seed)


# 30 houses + 30 flat blocks: (kind, seed, build_building kwargs).
SAMPLE = list(_sample())


def furnish_time_builds():
    """SAMPLE as furnished: no windows (doors stay put), nothing cleared."""
    # Patched where they are used: assemble.py holds its own bindings, so
    # patching the package attribute reached nothing after the split.
    with mock.patch.object(layout.assemble, "_place_windows", lambda *a, **k: None), \
            mock.patch.object(layout.assemble, "_clear_the_way", lambda *a, **k: 0):
        return [(kind, seed, layout.build_building(**args))
                for kind, seed, args in SAMPLE]


class PriorityTable(unittest.TestCase):
    def test_priorities(self):
        cases = [
            ("toilet", "bathroom", ESSENTIAL),
            ("sink_public", "bathroom", ESSENTIAL),
            ("bath_mat", "bathroom", DECORATION),
            ("double_bed_black", "bedroom", ESSENTIAL),
            ("wardrobe_oak", "bedroom", SECONDARY),
            ("wardrobe", "closet", ESSENTIAL),
            ("erika_plant_3", "livingroom", DECORATION),
            ("counter_4", "kitchen", ESSENTIAL),
            ("counter_4", "livingroom", SECONDARY),
            ("sofa_7", "livingroom", ESSENTIAL),
            ("dresser", "grocery", SECONDARY),
        ]
        for role, kind, want in cases:
            with self.subTest(role=role, kind=kind):
                self.assertEqual(priority(role, kind), want)

    def test_order_is_stable(self):
        got = in_priority_order(
            ["plant", "dresser", "double_bed", "lamp", "wardrobe"], "bedroom")
        self.assertEqual(
            got, ["double_bed", "dresser", "wardrobe", "plant", "lamp"])

    def test_every_prefix_names_real_furniture(self):
        prefixes = set(DECORATION_ROLES)
        for group in ESSENTIALS.values():
            prefixes.update(group)
        for p in sorted(prefixes):
            with self.subTest(prefix=p):
                self.assertTrue(any(k.startswith(p) for k in catalog.FURNITURE))
        for kind in layout.ROOM_STYLE:
            for role in catalog.FURNITURE:
                self.assertIn(priority(role, kind), {0, 1, 2})


class Walkway(unittest.TestCase):
    def test_two_doors_joined_by_shortest_path(self):
        w = walkway(rect(7, 5), [(0, 2), (6, 2)])
        self.assertTrue({(0, 2), (6, 2)} <= w)
        self.assertTrue(connected(w))
        self.assertEqual(len(w), 7)

    def test_three_doors_all_joined(self):
        w = walkway(rect(7, 5), [(0, 2), (6, 2), (3, 0)])
        self.assertTrue({(0, 2), (6, 2), (3, 0)} <= w)
        self.assertTrue(connected(w))
        self.assertLessEqual(len(w), 10)

    def test_one_door_gets_a_spine(self):
        w = walkway(rect(5, 5), [(0, 2)])
        self.assertIn((0, 2), w)
        self.assertIn((3, 1), w)
        self.assertTrue(connected(w))
        self.assertEqual(len(w), 5)

    def test_spine_keeps_off_walls(self):
        w = walkway(rect(7, 5), [(0, 2)])
        for x, y in w - {(0, 2)}:
            self.assertTrue(1 <= x <= 5 and 1 <= y <= 3, (x, y))

    def test_narrow_room_gets_only_the_door(self):
        self.assertEqual(walkway(rect(2, 6), [(0, 0)]), {(0, 0)})

    def test_three_wide_room_gets_only_the_door(self):
        # A spine down the one inner row leaves nothing two deep (a double
        # bed) room on either side.
        self.assertEqual(walkway(rect(3, 7), [(1, 0)]), {(1, 0)})

    def test_no_entries(self):
        self.assertEqual(walkway(rect(4, 4), []), set())
        self.assertEqual(walkway(rect(4, 4), [(9, 9)]), set())

    def test_l_shape_stays_inside(self):
        cells = rect(6, 3) | {(x, y) for x in range(3) for y in range(3, 6)}
        w = walkway(cells, [(5, 1), (1, 5)])
        self.assertTrue(w <= cells)
        self.assertTrue({(5, 1), (1, 5)} <= w)
        self.assertTrue(connected(w))

    def test_tree_as_one_search_per_way_in(self):
        # walkway grows its tree from one kept distance field; it must join
        # the ways in exactly as a fresh _path search per way in did.
        def reference(cells, entries):
            terminals = sorted({e for e in entries if e in cells})
            depth = FR._depth(cells)
            tree, pending = {terminals[0]}, set(terminals[1:])
            while pending:
                path = FR._path(cells, depth, tree, pending.__contains__)
                if path is None:
                    break
                tree.update(path)
                pending -= tree
            return tree

        rng = random.Random(11)
        for case in range(400):
            w, h = rng.randint(2, 12), rng.randint(2, 12)
            cells = rect(w, h) - {(rng.randrange(w), rng.randrange(h))
                                  for _ in range(rng.randint(0, w * h // 4))}
            if not cells:
                continue
            entries = rng.sample(sorted(cells), min(len(cells), rng.randint(2, 8)))
            with self.subTest(case=case):
                self.assertEqual(walkway(cells, entries), reference(cells, entries))

    def test_deterministic(self):
        entries = [(0, 2), (6, 2), (3, 0)]
        self.assertEqual(walkway(rect(7, 5), entries),
                         walkway(rect(7, 5), entries))


class FloorStaysOpen(unittest.TestCase):
    cells = rect(5, 5)
    walk = {(2, 4), (2, 3), (2, 2)}

    def test_walkway_is_never_blocked(self):
        self.assertIs(keeps_floor_open(self.cells, set(), self.walk, {(2, 3)}, 2), False)

    def test_corner_cut_off(self):
        self.assertIs(keeps_floor_open(
            self.cells, {(2, 0), (2, 1)}, self.walk, {(0, 2), (1, 2)}, 2), False)

    def test_small_pocket_allowed(self):
        self.assertIs(keeps_floor_open(
            self.cells, {(1, 0)}, self.walk, {(0, 1)}, 2), True)

    def test_nothing_new(self):
        self.assertIs(keeps_floor_open(self.cells, set(), self.walk, set(), 2), True)

    def test_small_pockets_add_up(self):
        """An upstairs bedroom in Piqua: a 4x3 room whose doors open off a
        one-wide strip at x=3. A double bed and a dresser at the foot left
        pockets of two squares each; a second dresser at (3, 2), on the one
        square joining room and strip, shut the room off in pockets of 2, 2
        and 1, none of them over the limit alone."""
        cells = rect(4, 3) | {(3, 3), (3, 4), (3, 5)}
        walk = {(3, 3), (3, 4), (3, 5)}
        bed = {(1, 0), (2, 0), (1, 1), (2, 1)}
        blocked = bed | {(3, 0), (0, 2)}
        self.assertIs(keeps_floor_open(cells, blocked, walk, {(3, 2)}, 2), False)

    def test_open_floor_answers_as_keeps_floor_open(self):
        # The incremental check must give the same answer for every query, so
        # a seed lays out the same rooms with it as without.
        rng = random.Random(5)
        for case in range(300):
            w, h = rng.randint(2, 7), rng.randint(2, 7)
            cells = rect(w, h) - {(rng.randrange(w), rng.randrange(h))
                                  for _ in range(rng.randint(0, 3))}
            walk = set(rng.sample(sorted(cells), min(len(cells), rng.randint(0, 3))))
            floor = FR.OpenFloor(cells, walk, 2)
            blocked = set()
            for _ in range(12):
                x, y = rng.randrange(-1, w + 1), rng.randrange(-1, h + 1)
                new = {(x, y)} | ({(x + 1, y)} if rng.random() < 0.3 else set())
                with self.subTest(case=case, blocked=sorted(blocked), new=sorted(new)):
                    self.assertIs(floor.keeps_open(new),
                                  keeps_floor_open(cells, blocked, walk, new, 2))
                if rng.random() < 0.5:
                    blocked |= new
                    floor.block(new)



class WalkwayIsKeptClear(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builds = furnish_time_builds()

    def rooms(self):
        """(label, storey, idx, cells, entries, walk) for every room that is
        neither core nor shaft."""
        for kind, seed, b in self.builds:
            stairs = b.stairs[0] if b.stairs else None
            for level, s in enumerate(b.storeys):
                doors = layout._door_tiles(s)
                for idx, r in enumerate(s.rooms, 1):
                    if r.is_core or r.is_shaft:
                        continue
                    cells = {(x, y) for y, row in enumerate(s.grid)
                             for x, v in enumerate(row) if v == idx}
                    entries = set()
                    for x, y, d in list(s.doors) + sorted(s.open_edge):
                        entries |= {(x, y), (x - 1, y) if d == "W" else (x, y - 1)}
                    if stairs is not None:
                        sx, sy, sd = stairs
                        dx, dy = (0, 1) if sd == "N" else (1, 0)
                        entries |= {(sx - dx, sy - dy),
                                    (sx + dx * layout.STAIR_RUN, sy + dy * layout.STAIR_RUN)}
                    walk = layout._room_walkway(s, idx, doors, stairs)
                    yield ((kind, seed, level, r.kind), s, idx, cells,
                           entries & cells, walk)

    def test_no_blocking_piece_on_a_walkway(self):
        for label, s, idx, _cells, _entries, walk in self.rooms():
            for role, x, y, o in s.furniture:
                if s.grid[y][x] != idx or not layout._blocks(role):
                    continue
                with self.subTest(label, role=role):
                    self.assertFalse(set(layout._tiles_under(role, x, y, o)) & walk)

    def test_walkway_joins_every_way_in(self):
        for label, _s, _idx, _cells, entries, walk in self.rooms():
            with self.subTest(label):
                self.assertLessEqual(entries, walk)
                if entries:
                    self.assertTrue(connected(walk))

    def test_bedrooms_keep_their_beds(self):
        # Before the walkway 293 of 347 bedrooms had a bed at furnish time.
        rooms = beds = 0
        for _kind, _seed, b in self.builds:
            for s in b.storeys:
                for idx, r in enumerate(s.rooms, 1):
                    if r.kind != "bedroom":
                        continue
                    rooms += 1
                    beds += any(role.startswith(("bed", "double_bed"))
                                for role, x, y, _o in s.furniture if s.grid[y][x] == idx)
        self.assertGreaterEqual(beds / rooms, 0.80)


class PriorityWhenTight(unittest.TestCase):
    def setUp(self):
        self._erika = list(layout._ERIKA_ALLOWED)
        layout.use_mod_tiles(False)

    def tearDown(self):
        layout._ERIKA_ALLOWED[:] = self._erika
        layout._ERIKA.clear()

    def test_essentials_go_in_before_decoration(self):
        room = layout.Room(0, 0, 2, 2, kind="kitchen")
        plan = layout.Plan(3, 3, rooms=[room], grid=[[1] * 3 for _ in range(3)],
                           doors=[(0, 1, "W")], kind="house")
        style = {"kitchen": (12, "Kitchen", ["plant"] * 8 + ["fridge"])}
        with mock.patch.dict(layout.ROOM_STYLE, style):
            for seed in range(10):
                p = copy.deepcopy(plan)
                layout._furnish(p, random.Random(seed))
                roles = [f[0] for f in p.furniture]
                with self.subTest(seed=seed):
                    self.assertTrue(any(r.startswith("fridge") for r in roles), roles)
                    self.assertLessEqual(roles.count("plant"), 6, roles)


class FloorStaysInOnePiece(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builds = furnish_time_builds()

    def test_free_floor_hangs_together(self):
        for kind, seed, b in self.builds:
            stairs = b.stairs[0] if b.stairs else None
            for level, s in enumerate(b.storeys):
                doors = layout._door_tiles(s)
                blocked = {t for role, x, y, o in s.furniture if layout._blocks(role)
                           for t in layout._cells_for(role, x, y, o)}
                for idx, r in enumerate(s.rooms, 1):
                    if r.is_core or r.is_shaft:
                        continue
                    cells = {(x, y) for y, row in enumerate(s.grid)
                             for x, v in enumerate(row) if v == idx}
                    walk = layout._room_walkway(s, idx, doors, stairs)
                    with self.subTest(kind=kind, seed=seed, level=level, room=r.kind):
                        self.assertTrue(FR.keeps_floor_open(
                            cells, blocked & cells, walk, set(), layout.POCKET_TILES))

    def test_same_seed_same_furniture(self):
        args = next(a for k, sd, a in SAMPLE if k == "house" and sd == 3)
        with mock.patch.object(layout.assemble, "_place_windows", lambda *a, **k: None),                 mock.patch.object(layout.assemble, "_clear_the_way", lambda *a, **k: 0):
            one = layout.build_building(**args)
            two = layout.build_building(**args)
        self.assertEqual([s.furniture for s in one.storeys],
                         [s.furniture for s in two.storeys])


class ClearUpByPriority(unittest.TestCase):
    def test_decoration_goes_before_an_essential(self):
        room = layout.Room(0, 0, 5, 4, kind="bathroom")
        furniture = [("plant", 2, 0, "N"), ("plant", 3, 0, "N")]
        furniture += [("toilet", 2, y, "N") for y in range(1, 5)]
        plan = layout.Plan(6, 5, rooms=[room], grid=[[1] * 6 for _ in range(5)],
                           doors=[(0, 2, "W")], furniture=furniture)
        self.assertEqual(layout._open_up(plan, {(0, 2)}), {0, 1})


class ClearUpAfterBuild(unittest.TestCase):
    """Full SAMPLE builds, recording what _open_up takes out."""

    @classmethod
    def setUpClass(cls):
        cls.removed = []      # (role, room kind, touches a window square)
        orig = layout._open_up

        def spy(storey, starts):
            gone = orig(storey, starts)
            win = set()
            for x, y, d in storey.windows:
                win |= {(x - 1, y), (x, y)} if d == "W" else {(x, y - 1), (x, y)}
            for i in gone:
                role, x, y, o = storey.furniture[i]
                idx = storey.grid[y][x]
                kind = storey.rooms[idx - 1].kind if idx else ""
                cls.removed.append(
                    (role, kind, bool(set(layout._tiles_under(role, x, y, o)) & win)))
            return gone

        with mock.patch.object(layout.furnishing, "_open_up", spy):
            cls.builds = [layout.build_building(**args) for _k, _s, args in SAMPLE]
        cls.placed = len(cls.removed) + sum(
            len(s.furniture) for b in cls.builds for s in b.storeys)

    def test_few_pieces_removed(self):
        self.assertLess(len(self.removed) / self.placed, 0.03)

    def test_essentials_not_removed(self):
        # Measured 12 (baseline ~283): 8 from one flat kitchen on 4 storeys,
        # counter and sink on the window square with no other counter or free
        # wall; 3 beds/wardrobe on moved doors; 1 sofa knocked on by one.
        # What is left has three causes, none of them furnish-time placement:
        # a window square in a corner pocket of a full room (its stack can
        # neither move nor swap, and the window rule wants the square reached,
        # so the stack on the way goes too), pieces on the clearance of a door
        # slid off a corner after furnishing that cannot move (beds, wardrobes,
        # full rooms), and knock-ons of doors that slid into a corner pocket.
        lost = [(r, k) for r, k, _w in self.removed if priority(r, k) == ESSENTIAL]
        self.assertLessEqual(len(lost), 16, lost)

    def test_route_removals_drop(self):
        # Pieces taken out that do not touch a window square. Measured 50 of
        # 13,354 = 0.37% (baseline 166 = 1.25%): 26 on the way to a window
        # square, 11 on a moved door's clearance, 12 knock-ons of moved doors.
        # What is left has three causes, none of them furnish-time placement:
        # a window square in a corner pocket of a full room (its stack can
        # neither move nor swap, and the window rule wants the square reached,
        # so the stack on the way goes too), pieces on the clearance of a door
        # slid off a corner after furnishing that cannot move (beds, wardrobes,
        # full rooms), and knock-ons of doors that slid into a corner pocket.
        route = [(r, k) for r, k, w in self.removed if not w]
        self.assertLess(len(route), 0.0045 * self.placed, route)

    def test_window_squares_are_not_shut_in(self):
        # A piece moved off a window square must not box the square in: free
        # window squares in a pocket of two tiles or fewer. Measured 28 of
        # 1,993 (136 of 2,013 when the move ignored it); what is left are
        # squares the plan itself leaves in a corner.
        free = pocket = 0
        for b in self.builds:
            for s in b.storeys:
                cover = {c for role, x, y, o in s.furniture if layout._blocks(role)
                         for c in layout._tiles_under(role, x, y, o)}
                for x, y, d in s.windows:
                    for t in (((x - 1, y), (x, y)) if d == "W" else ((x, y - 1), (x, y))):
                        if not (0 <= t[0] < s.width and 0 <= t[1] < s.height
                                and s.grid[t[1]][t[0]]) or t in cover:
                            continue
                        free += 1
                        seen, todo = {t}, [t]
                        while todo and len(seen) <= 2:
                            cx, cy = todo.pop()
                            for q in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                                if (0 <= q[0] < s.width and 0 <= q[1] < s.height
                                        and s.grid[q[1]][q[0]] == s.grid[t[1]][t[0]]
                                        and q not in cover and q not in seen):
                                    seen.add(q)
                                    todo.append(q)
                        pocket += len(seen) <= 2
        self.assertLess(pocket, 0.02 * free, (pocket, free))

    def test_kitchens_keep_a_table(self):
        # 27 of 149 kitchens before the walkway rule (18%), 3 when the table's
        # aisle could not cross it; the aisle is bare floor, so it may.
        kitchens = tables = 0
        for b in self.builds:
            for s in b.storeys:
                for idx, r in enumerate(s.rooms, 1):
                    if r.kind != "kitchen":
                        continue
                    kitchens += 1
                    tables += any(role in ("round_table", "dining_table", "table")
                                  for role, x, y, _o in s.furniture
                                  if s.grid[y][x] == idx)
        self.assertGreaterEqual(tables / kitchens, 0.08)

    def test_rooms_keep_their_essentials(self):
        want = {"bathroom": (("toilet",), 0.87), "kitchen": (("fridge",), 0.87),
                "bedroom": (("bed", "double_bed"), 0.78),
                "livingroom": (("sofa",), 0.95)}
        rooms = dict.fromkeys(want, 0)
        have = dict.fromkeys(want, 0)
        for b in self.builds:
            for s in b.storeys:
                for idx, r in enumerate(s.rooms, 1):
                    if r.kind not in want:
                        continue
                    rooms[r.kind] += 1
                    have[r.kind] += any(role.startswith(want[r.kind][0])
                                        for role, x, y, _o in s.furniture
                                        if s.grid[y][x] == idx)
        for kind, (_roles, floor) in want.items():
            with self.subTest(kind=kind):
                self.assertGreaterEqual(have[kind] / rooms[kind], floor)



if __name__ == "__main__":
    unittest.main()


class NothingStandsInADoorway(unittest.TestCase):
    """A door's tiles have no blocking piece on them.

    Furnishing keeps off them, but the pass that moves a door off the flight
    can put one back afterwards, and it landed on a bed already made up: a
    bedroom whose only way in was the foot of its bed.
    """

    SHAPES = ((11, 10, 0), (13, 12, 3), (17, 12, 1), (12, 12, 0), (14, 11, 2))

    def test_a_doorway_is_clear_in_every_built_house(self):
        built = 0
        for w, h, seed in self.SHAPES:
            b = layout.build_building(w, h, levels=1, seed=seed, kind="house")
            for level, s in enumerate(b.storeys):
                clear = layout._door_tiles(s)
                for role, x, y, o in s.furniture:
                    if not layout._blocks(role):
                        continue
                    hit = set(layout._cells_for(role, x, y, o)).intersection(clear)
                    with self.subTest(shape=(w, h, seed), level=level, role=role):
                        self.assertFalse(
                            hit, f"{role} at {(x, y)} stands in a doorway at {sorted(hit)}")
                built += 1
        self.assertGreaterEqual(built, len(self.SHAPES))
