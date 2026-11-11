# Furniture Placement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Furniture never blocks a door or cuts off part of a room, and rooms keep the pieces that make them that room (toilet, sink, bed, fridge, kitchen counter) instead of losing them to the clear-up afterwards.

**Architecture:** New `knoxbuild/furnish_rules.py` holds the priority table (essential / secondary / decoration), the walkway computation (a path joining a room's ways in, or a spine for a one-door room) and the free-floor connectivity check. `_furnish` reserves each room's walkway before placing anything and places pieces in priority order, refusing any blocking piece that would cut off free floor. After windows are placed, `_clear_the_way` first moves single-tile pieces off window squares, then `_open_up` deletes what is left by priority (decoration before secondary before essentials).

**Tech Stack:** Python 3, `unittest`, `unittest.mock`, `heapq`, existing `knoxbuild.layout` (`Plan`, `Room`, `_furnish`, `_place_group`, `_open_up`, `_clear_the_way`, `_cells_for`, `_blocks`, `POCKET_TILES`, `DOOR_CLEAR_DEPTH`), `knoxbuild.interiors`, `knoxbuild.catalog` (`FURNITURE`, `FURNITURE_LAYERS`).

**Spec:** `docs/superpowers/specs/2026-10-29-furniture-placement-design.md`

## Global Constraints

- Door clearance (`DOOR_CLEAR_DEPTH`), window rules (`_under_a_window`, `_place_windows` untouched), wall-hanging rules, a light switch in every room, wall pieces: unchanged.
- Never fail a build: a room with no door, no inner tile or no free spot just gets fewer pieces. Deterministic per seed: heaps keyed on `(cost, y, x)`, terminals sorted, no output depends on set iteration order.
- Files: match each file's working-tree line endings (`file`): `knoxbuild/*.py`, `tests/*.py`, `CHANGELOG.md` are CRLF (new `.py` files too); this plan and the spec are LF. Tests: `python -m unittest discover -s tests`, `python tools/selftest.py`, `python tools/audit_layouts.py 400`.
- Non-home furnishing (shops, schools, offices, eateries) must keep passing its tests; it may only change where pieces stop blocking doors/routes.
- Baseline (measured on this branch, `a731daa`):
  - `furnish_measure.py` (100 houses + 100 flat blocks, same sample as `removed.py`): placed 42,875, removed 3,327 (7.8%), essentials removed 1,065, on a window square 2,825 / elsewhere 502; present: bathroom toilet 0.87, kitchen fridge 0.83, openplan fridge 0.97, livingroom sofa 0.99, bedroom bed 0.80, kidsbedroom bed 0.87; 9.2 s (`removed.py` 9.7 s). Script: `C:\Users\TheTaZe\AppData\Local\Temp\claude\C--KnoxMap\edc14b9e-7d35-452c-9495-df11894fb339\scratchpad\furnish_measure.py` (run from the repo root); `removed.py` in the same folder.
  - Test sample (`SAMPLE` below, 30 houses + 30 flat blocks): 1,046 removed of 13,296 (7.9%), essentials removed ~283, window 880 / route 166; present: bathroom toilet 0.87, kitchen fridge 0.87, bedroom bed 0.78, livingroom sofa 0.99.
- `SAMPLE` (defined once in `tests/test_furnish_rules.py`): for `kind in ("house", "apartment")`, `seed in range(30)`: `rng = random.Random(seed); w = rng.randint(9, 20); h = rng.randint(8, 16); levels = rng.randint(1, 3) if kind == "house" else rng.randint(3, 5)`; `layout.build_building(w, h, levels=levels, kind=kind, seed=seed)`. "Furnish-time state" = the same builds with `layout._place_windows` and `layout._clear_the_way` patched to no-ops (`mock.patch.object`), so doors do not move and nothing is deleted. Build once per test class in `setUpClass`.
- Time: `furnish_measure.py` must stay <= 1.5x baseline (<= 13.8 s on the same machine).
- **Deviations from the spec:**
  1. Window squares are not part of the furnish-time walkway: windows are placed after furnishing (`build_building` -> `_place_windows`), so nobody knows where they are yet. Window squares are the main cause anyway (2,825 of 3,327 deletions are pieces on a window square, not on a route), so Task 5 moves single-tile pieces off window squares after the windows go in, which is the spec's "tried at another spot", and only then does the safety net delete.
  2. No lift landing terminal: lift doors open onto the core (stair hall/corridor), which takes nothing standing. The stair landing is the tile just off each end of the flight when that tile is in the room.
  3. "Shortest path" means fewest tiles, with ties broken away from the walls (so wall slots stay free). Rooms with several ways in are joined greedily (nearest unjoined way in next), not by an exact Steiner tree.
  4. A one-door spine ends at the farthest tile that is at least one tile in from every wall. A room with no such tile (2 tiles wide) gets only the door clearance.
  5. Shops (`furnish_store`), service bays and dining wall sets avoid the walkway (it is passed in their `keep_clear`) but get no per-piece connectivity check; their layouts already leave aisles, and the safety net still covers them.
  6. Centre groups keep their rugs off the walkway too (the group is checked as one block). Bath mats may lie on it (floor furniture).
  7. ~~Doors moved by `_doors_off_corners` after furnishing (23 of 1,558 on the sample) are not re-cleared; the safety net handles them.~~ No longer holds (Task 5): `_make_way_for_windows` also moves one-tile stacks off the clearance of every door; what cannot move is left to the safety net.
  8. `tests/test_layout_walkability.py::test_furniture_is_removed_from_window_approach` changes: the bookshelf is now moved, not deleted (Task 5).

## Review Focus

- Tiny rooms (3x3 bathroom or closet, 2-wide rooms) still get their essentials. A room with no door or no inner tile must not raise (Tasks 1, 3).
- Walkway and connectivity cost: the mall concourse (1,600 tiles) and big rooms must stay inside the time budget (Tasks 1, 6).
- Centre groups (living room sofa) lose space to the walkway: the presence guard must hold (Tasks 2, 5).
- `_open_up` must still pass both existing walkability tests, with lexicographic cost tuples (Task 4).
- Moving a piece keeps its stack together (lamp on dresser, sink on counter) and its draw order. It never moves a stack with a wall cabinet or microwave above it (Task 5).
- Same seed -> same furniture across runs (Tasks 1, 3).

---

### Task 1: Priority table, walkway and connectivity check

**Files:**
- Create: `knoxbuild/furnish_rules.py` (CRLF)
- Test: `tests/test_furnish_rules.py` (create, CRLF)

**Interfaces:**
- Consumes: nothing from `layout` (no import of it: `layout` imports this module). Tests use `knoxbuild.catalog.FURNITURE`, `layout.ROOM_STYLE`.
- Produces:
  - `ESSENTIAL, SECONDARY, DECORATION = 0, 1, 2` (lower = more important, placed first, deleted last).
  - `DECORATION_ROLES: tuple[str, ...] = ("plant", "erika_plant", "lamp", "shelf", "bookshelf", "erika_shelves", "painting", "mirror", "erika_art", "erika_ad", "rug", "shag_rug", "bath_mat", "corkboard")`, matched as role prefixes.
  - `ESSENTIALS: dict[str, tuple[str, ...]]` (role prefixes per room kind): `bathroom: (toilet, sink, bath, shower)`, `kitchen: (fridge, stove, kitchen_sink, counter)`, `openplan: (fridge, stove, kitchen_sink, counter, sofa)`, `livingroom: (sofa,)`, `bedroom` and `kidsbedroom` and `motelroom: (double_bed, bed)`, `laundry: (washer,)`, `dining: (dining_table, round_table)`, `closet: (wardrobe,)`.
  - `priority(role: str, room_kind: str) -> int`: `DECORATION` if `role.startswith(DECORATION_ROLES)`, else `ESSENTIAL` if `role.startswith(ESSENTIALS.get(room_kind, ()))`, else `SECONDARY`. Decoration is checked first, so `bath_mat` is never read as `bath`.
  - `in_priority_order(roles: list[str], room_kind: str) -> list[str]`: stable sort by `priority`.
  - `walkway(cells: set[tuple[int, int]], entries: Iterable[tuple[int, int]]) -> set[tuple[int, int]]`:
    - Terminals are the entries inside `cells`, sorted and deduplicated; none -> `set()`.
    - `depth` comes from a multi-source BFS: 1 for a tile with a 4-neighbour outside `cells`, +1 per step inward.
    - Step cost onto tile `t` is the tuple `(1, 1 if depth[t] == 1 else 0)`, so the fewest tiles wins and ties go away from walls. Dijkstra uses `heapq` entries `(cost, y, x)`.
    - One terminal: target = the tile with `depth >= 2` that has the most BFS steps from it, ties to the smallest `(y, x)`. No such tile -> `{terminal}`. Otherwise the cheapest path terminal -> target.
    - Two or more: `tree = {terminals[0]}`. Repeat: multi-source Dijkstra from `tree`, stop at the first unjoined terminal popped, add its path.
    - Returns the tree.
  - `keeps_floor_open(cells: set, blocked: set, walk: set, new: set, pocket: int) -> bool`:
    - `False` if `new & walk`.
    - Otherwise flood-fill the 4-connected components of `free = cells - blocked - new`. The main component is the one holding `min(walk & free)`; without one, the largest (ties: the one holding the smallest tile).
    - `True` iff every other component has `<= pocket` tiles. Empty `free` -> `True`.

- [ ] **Step 1: Write failing tests** `tests/test_furnish_rules.py`, class `PriorityTable`:
  - `test_priorities`: `priority("toilet","bathroom") == ESSENTIAL`; `priority("sink_public","bathroom") == ESSENTIAL`; `priority("bath_mat","bathroom") == DECORATION`; `priority("double_bed_black","bedroom") == ESSENTIAL`; `priority("wardrobe_oak","bedroom") == SECONDARY`; `priority("wardrobe","closet") == ESSENTIAL`; `priority("erika_plant_3","livingroom") == DECORATION`; `priority("counter_4","kitchen") == ESSENTIAL`; `priority("counter_4","livingroom") == SECONDARY`; `priority("sofa_7","livingroom") == ESSENTIAL`; `priority("dresser","grocery") == SECONDARY`.
  - `test_order_is_stable`: `in_priority_order(["plant","dresser","double_bed","lamp","wardrobe"], "bedroom") == ["double_bed","dresser","wardrobe","plant","lamp"]`.
  - `test_every_prefix_names_real_furniture`: every prefix in `ESSENTIALS` values and `DECORATION_ROLES` is a prefix of some `catalog.FURNITURE` key; every role in `FURNITURE` for every `layout.ROOM_STYLE` kind gets a value in `{0, 1, 2}`.

  Class `Walkway` (helper `rect(w, h)` = set of tiles, `connected(tiles)` = 4-connected):
  - `test_two_doors_joined_by_shortest_path`: `walkway(rect(7,5), [(0,2),(6,2)])` contains both, is connected, `len == 7`.
  - `test_three_doors_all_joined`: entries `(0,2),(6,2),(3,0)` -> all contained, connected, `len <= 10`.
  - `test_one_door_gets_a_spine`: `walkway(rect(5,5), [(0,2)])` contains `(0,2)` and `(3,1)`, connected, `len == 5`.
  - `test_spine_keeps_off_walls`: in `rect(7,5)` with one entry `(0,2)`, every tile except the entry has `depth >= 2`, i.e. `1 <= x <= 5 and 1 <= y <= 3`.
  - `test_narrow_room_gets_only_the_door`: `walkway(rect(2,6), [(0,0)]) == {(0,0)}`.
  - `test_no_entries`: `walkway(rect(4,4), []) == set()` and entries outside cells -> `set()`.
  - `test_l_shape_stays_inside`: L-shaped cells (`rect(6,3) | {(x,y) for x in range(3) for y in range(3,6)}`), entries `(5,1),(1,5)` -> result is a subset of cells, connected.
  - `test_deterministic`: the same call twice gives equal sets.

  Class `FloorStaysOpen` (cells `rect(5,5)`, `walk = {(2,4),(2,3),(2,2)}`):
  - `keeps_floor_open(cells, set(), walk, {(2,3)}, 2) is False` (walkway).
  - `blocked={(2,0),(2,1)}`, `new={(0,2),(1,2)}` -> `False` (4-tile corner cut off).
  - `blocked={(1,0)}`, `new={(0,1)}` -> `True` (1-tile pocket).
  - `keeps_floor_open(cells, set(), walk, set(), 2) is True`.
- [ ] **Step 2: Run** `python -m unittest tests.test_furnish_rules -v` -> FAIL (module missing).
- [ ] **Step 3: Implement** the names above in `knoxbuild/furnish_rules.py`.
- [ ] **Step 4: Run** `python -m unittest tests.test_furnish_rules -v` -> PASS.

### Task 2: Reserve each room's walkway before placing

**Files:**
- Modify: `knoxbuild/layout.py` (import next to `from . import catalog as C`; `_furnish` door tiles ~l.4183-4198, `keep_clear` ~l.4295, call sites ~l.4342-4362, 4491, 4522, 4560, 4580-4584)
- Test: `tests/test_furnish_rules.py`

**Interfaces:**
- Consumes: `furnish_rules.walkway`, `DOOR_CLEAR_DEPTH`, `STAIR_RUN`.
- Produces:
  - `from . import furnish_rules as FR` in `layout.py`.
  - `_door_tiles(plan: Plan) -> set[tuple[int, int]]`: lines ~4183-4198 extracted verbatim (ways in = `plan.doors` + sorted `plan.open_edge`, `DOOR_CLEAR_DEPTH` deep both sides). `_furnish` calls it; `door_edges` stays inline.
  - `_room_walkway(plan: Plan, idx: int, door_tiles: set, stairs: tuple[int, int, str] | None) -> set[tuple[int, int]]`: `set()` for a core or shaft room.
    - `cells` = the room's tiles (`grid == idx`).
    - `entries` = for each `(x, y, d)` in doors + open_edge, both side tiles (`(x, y)` and `(x-1, y)` for `W`, `(x, y-1)` for `N`) that are in `cells`; plus the stair landings `(sx-dx, sy-dy)` and `(sx+dx*STAIR_RUN, sy+dy*STAIR_RUN)` when in `cells`.
    - Returns `FR.walkway(cells, entries) | (door_tiles & cells)`.
  - In `_furnish`, per room, replacing line ~4295:
    - `walk = _room_walkway(plan, idx, door_tiles, stairs)`
    - `keep_clear = door_tiles | stair_tiles | walk`
    - `no_go = door_tiles | walk`
  - Call-site changes:
    - Generic wishlist loop: `c in door_tiles` -> `c in no_go`.
    - `bed_against_wall(..., no_go, ...)`.
    - `_counter_runs(plan, idx, slots, occupied, no_go, stair_tiles, ...)`, both calls.
    - `furnish_store(plan, idx, r, rng, door_tiles, stair_tiles | walk, street)`.
    - `furnish_dining(plan, idx, r, rng, occupied, stair_tiles | walk, door_tiles, street)`.
    - `furnish_service_bay` and `furnish_office` and `_furnish_middle` already take `keep_clear`.
    - `_bath_mat_spot(plan, idx, r, occupied, door_tiles | stair_tiles)` (mats may lie on the walkway).
    - The switch code (`mine`) and `door_frontier` keep using `door_tiles`.

- [ ] **Step 1: Write failing tests** in `tests/test_furnish_rules.py`, class `WalkwayIsKeptClear` (furnish-time state of `SAMPLE`):
  - `test_no_blocking_piece_on_a_walkway`: for every storey and every room that is not core or shaft, `walk = layout._room_walkway(storey, idx, layout._door_tiles(storey), building.stairs[0] if building.stairs else None)`. No piece with `layout._blocks(role)` anchored in the room has a tile in `walk`. Use `subTest(kind, seed, level, room kind)`.
  - `test_walkway_joins_every_way_in`: for the same rooms, every entry tile of the room is in `walk`, and `walk` is 4-connected whenever the room has at least one entry.
- [ ] **Step 2: Run** `python -m unittest tests.test_furnish_rules -v` -> FAIL (`_room_walkway` missing).
- [ ] **Step 3: Implement** `_door_tiles`, `_room_walkway` and the call-site changes.
- [ ] **Step 4: Run** `python -m unittest tests.test_furnish_rules tests.test_room_furniture_layouts tests.test_layout_walkability tests.test_business_layouts tests.test_layout_focal tests.test_bathroom_sinks -v`, then the full suite -> PASS.

### Task 3: Priority-ordered placement with the connectivity check

**Files:**
- Modify: `knoxbuild/layout.py` (`_furnish_middle` ~l.3994, `_seat_the_table` ~l.4035, `_place_group` ~l.4072, `_counter_runs` ~l.4778, `_furnish` wishlist section ~l.4460-4585), `knoxbuild/interiors.py` (`furnish_office` l.414, `bed_against_wall` l.475, `furnish_dining` l.628)
- Test: `tests/test_furnish_rules.py`

**Interfaces:**
- Consumes: `FR.priority`, `FR.in_priority_order`, `FR.keeps_floor_open`, `POCKET_TILES`, `walk` from Task 2.
- Produces:
  - New trailing kwarg `keeps_open: Callable[[Iterable[tuple[int, int]]], bool] | None = None` on all of these:
    - `_place_group(plan, idx, room, group, repeat, occupied, keep_clear, keeps_open=None) -> int`: skip a spot if `keeps_open` rejects the group's `solid` tiles.
    - `_furnish_middle(..., palette=None, keeps_open=None) -> int`: passed to both `_place_group` calls and to `_seat_the_table`.
    - `_seat_the_table(plan, idx, keep_clear, added, keeps_open=None) -> None`: skip a chair tile it rejects.
    - `_counter_runs(..., rng=None, keeps_open=None) -> None`: skip a counter whose cells it rejects.
    - `interiors.bed_against_wall(..., side_table, keeps_open=None) -> bool`: skip a bed spot it rejects; skip a bedside table it rejects.
    - `interiors.furnish_office(..., keep_clear, keeps_open=None)` and `interiors.furnish_dining(..., street, keeps_open=None)`: passed to their `_place_group` calls.
  - In `_furnish`, per room:
    - `start = len(plan.furniture)` at the top of the room's iteration.
    - `cells` = room tiles.
    - Local `keeps_open(tiles)` = `FR.keeps_floor_open(cells, blocked, walk, set(tiles), POCKET_TILES)`. Here `blocked` = the tiles (`_cells_for`) of the `_blocks` pieces in `plan.furniture[start:]`; only this room's pieces are appended while it is furnished.
    - Passed to every call above. In the generic loop a blocking piece is placed only if `keeps_open(cells)`; otherwise the next slot is tried.
  - Placement order, replacing ~l.4474-4575:
    1. Whiteboard, as now.
    2. Centre group first only if `centre_first` = any role of `CENTRE_GROUPS[r.kind]` (palette applied) has `FR.priority == ESSENTIAL`; then remove consumed roles, as now.
    3. Bed against wall.
    4. Essential wishlist roles.
    5. Centre group if it was not first, then remove consumed roles.
    6. The rest in `FR.in_priority_order` (secondary, then decoration).
    7. Counter runs, then `_stand_on_something`.

    Move the existing loop body into a local `place(role)` and the middle-plus-consume block into a local `centre()`. Compute `floor_slots` before step 1; it depends only on slots and doors.

- [ ] **Step 1: Write failing tests** in `tests/test_furnish_rules.py`:
  - Class `PriorityWhenTight` (setUp/tearDown disable Erika's Tiles exactly as `tests/test_room_furniture_layouts.py` does):
    - `test_essentials_go_in_before_decoration`: `mock.patch.dict(layout.ROOM_STYLE, {"kitchen": (12, "Kitchen", ["plant"] * 8 + ["fridge"])})`. `room = Room(0, 0, 2, 2, kind="kitchen")`; `Plan(3, 3, rooms=[room], grid=[[1]*3 for _ in range(3)], doors=[(0, 1, "W")], kind="house")`. For seeds 0-9 run `layout._furnish(plan_copy, random.Random(seed))`, then assert a `fridge` is present and at most 6 plants. Today 7 plants fill every free tile and the fridge is lost.
  - Class `FloorStaysInOnePiece` (furnish-time state of `SAMPLE`):
    - `test_free_floor_hangs_together`: for every room that is not core or shaft, `FR.keeps_floor_open(cells, blocked_in_room, walk, set(), layout.POCKET_TILES)` holds (`walk` from `_room_walkway`).
    - `test_same_seed_same_furniture`: two furnish-time builds of `("house", seed 3)` give equal `furniture` lists on every storey.
  - Class `FewerRouteRemovals` (full `SAMPLE` builds, `_open_up` wrapped to record what it returns and whether each piece covers a window square):
    - `test_route_removals_drop`: pieces removed that do not touch a window square <= 0.3% of pieces placed (baseline 166 = 1.25%).
- [ ] **Step 2: Run** `python -m unittest tests.test_furnish_rules -v` -> FAIL (tight kitchen, free floor, route removals).
- [ ] **Step 3: Implement** the `keeps_open` kwargs and the new placement order.
- [ ] **Step 4: Run** `python -m unittest tests.test_furnish_rules tests.test_room_furniture_layouts tests.test_layout_focal tests.test_business_layouts tests.test_designer tests.test_room_solver -v`, then the full suite -> PASS. If `test_route_removals_drop` still fails, list the removed pieces by room kind and cause and stop to report; do not loosen the threshold.

### Task 4: `_open_up` deletes by priority

**Files:**
- Modify: `knoxbuild/layout.py` (`_open_up` ~l.5195-5295; add `import heapq`)
- Test: `tests/test_furnish_rules.py`, `tests/test_layout_walkability.py` (unchanged, must pass)

**Interfaces:**
- Consumes: `FR.priority`.
- Produces: `_open_up(storey, starts) -> set` with the same signature and return value.
  - Each tile's step cost is the tuple `(essentials, secondary, decoration)`, counting the blocking pieces on it by `FR.priority(role, kind of the room at the piece's anchor)` (`""` when outside).
  - The 0-1 deque becomes a `heapq` Dijkstra on `(cost, (x, y))` with componentwise tuple sums, so it minimises essentials first, then secondary, then decoration.
  - `ZERO = (0, 0, 0)`; `NONE = (MANY, MANY, MANY)` replaces `MANY`. Every `== 0`, `> 0`, `best.get(t, MANY)` comparison uses `ZERO` / `NONE`.
  - Goals, window and pocket rules, and the back-pointer collection are unchanged.

- [ ] **Step 1: Write failing test** class `ClearUpByPriority`:
  - `test_decoration_goes_before_an_essential`: `Room(0, 0, 5, 4, kind="bathroom")`, `Plan(6, 5, ...)`, door `(0, 2, "W")`. Furniture: `("plant", 2, 0, "N")`, `("plant", 3, 0, "N")`, then `("toilet", 2, y, "N")` for `y` in 1-4.
  - Assert `layout._open_up(plan, {(0, 2)}) == {0, 1}`. Today it takes one toilet: cost 1 against 2 plants.
- [ ] **Step 2: Run** `python -m unittest tests.test_furnish_rules.ClearUpByPriority -v` -> FAIL.
- [ ] **Step 3: Implement** the weighted search in `_open_up`.
- [ ] **Step 4: Run** `python -m unittest tests.test_furnish_rules tests.test_layout_walkability tests.test_lifts -v`, then the full suite -> PASS.

### Task 5: Window squares: move pieces, delete only what cannot move

**Files:**
- Modify: `knoxbuild/layout.py` (new `_make_way_for_windows` beside `_open_up`; `_clear_the_way` ~l.5298)
- Test: `tests/test_layout_walkability.py` (change `test_furniture_is_removed_from_window_approach`, add one test), `tests/test_furnish_rules.py`

**Interfaces:**
- Consumes: `_door_tiles`, `_room_walkway`, `FR.keeps_floor_open`, `_under_a_window`, `_needs_front`, `_facing`, `_cells_for`, `_blocks`, `_is_wall_piece`, `NORTH_WEST_ONLY`, `POCKET_TILES`.
- Produces: `_make_way_for_windows(storey: Plan, stairs: tuple[int, int, str] | None) -> int` (pieces moved).
  - For each window inside tile `t` (both sides of each window edge that are room tiles), in sorted order, find the *stack*: the floor pieces covering `t`.
  - Skip `t` when:
    - the stack has no blocking piece;
    - every piece is `_under_a_window`;
    - any piece covers more than one tile;
    - a `wall_cabinet` or `microwave` is anchored at `t`.
  - Destination `d`:
    - in the same room;
    - not a window square, not in the room's `_room_walkway(...)` (cached per room), not a stair tile;
    - covered by no piece;
    - on a wall, with facing `f` = the first of `N, W, S, E` whose neighbour is outside the room; only `N` or `W` when the stack holds a `NORTH_WEST_ONLY` role;
    - when the stack holds a `_needs_front` role, its front tile is in the room and not blocked;
    - `FR.keeps_floor_open(cells, blocked - {t}, walk, {d}, POCKET_TILES)` holds.

    Pick the `d` nearest to `t` (Manhattan), ties to the smallest `(y, x)`.
  - Rewrite each stack piece in place as `(role, dx, dy, _facing(role, f))`, so list order (draw order) is kept.
  - `_clear_the_way` calls it per storey with `building.stairs[0] if building.stairs else None` before the `_open_up` rounds. Its return value stays the number deleted.

- [ ] **Step 1: Write failing tests**:
  - In `tests/test_layout_walkability.py`, rename `test_furniture_is_removed_from_window_approach` -> `test_furniture_is_moved_off_the_window_approach`. Same plan; assert `removed == 0`, exactly one bookshelf remains, and none stands on `(0, 2)`.
  - Add `test_window_square_is_cleared_when_nothing_can_move`: `Room(0, 0, 2, 2, kind="livingroom")`, door `(1, 0, "N")`, window `(0, 1, "W")`. Furniture: `("bookshelf", 0, 1, "W")`, plus `("dresser", x, y, "N")` on `(0,0), (2,0), (2,1), (0,2), (1,2), (2,2)`. Assert `removed == 1` and no bookshelf left.
  - In `tests/test_furnish_rules.py`, class `ClearUpAfterBuild` (full `SAMPLE` builds, `_open_up` wrapped to record removals):
    - `test_few_pieces_removed`: removed < 3% of placed (placed = what is left + removed; baseline 7.9%).
    - `test_essentials_not_removed`: removed pieces with `FR.priority(role, room kind) == ESSENTIAL` <= 5 (baseline ~283).
    - `test_rooms_keep_their_essentials`: bathroom with a toilet >= 0.87, kitchen with a fridge >= 0.87, bedroom with a bed >= 0.78, livingroom with a sofa >= 0.95. These are non-regression guards and may already pass.
- [ ] **Step 2: Run** `python -m unittest tests.test_layout_walkability tests.test_furnish_rules -v` -> FAIL.
- [ ] **Step 3: Implement** `_make_way_for_windows` and the call in `_clear_the_way`.
- [ ] **Step 4: Run** the full suite -> PASS. If the 3% or essentials test fails, report the remaining removals by cause (window / route) and role and stop; do not loosen the threshold.

### Task 6: Measure and record

**Files:**
- Modify: `CHANGELOG.md` (new entry under the current top version section, `## 1.7.6.5`), `docs/superpowers/specs/2026-10-29-furniture-placement-design.md` (append "## Result")

- [ ] **Step 1: Run** `python <scratchpad>\furnish_measure.py` and `removed.py` from the repo root (paths in Global Constraints). Expect: removed < 3% of placed, essentials removed ~0, presence at or above baseline, time <= 13.8 s.
- [ ] **Step 2: Append** "## Result" to the spec, with before/after for:
  - placed, removed, share, essentials removed;
  - window / route split and the top 12 removed roles;
  - presence per room kind and time.

  Record the spec deviations listed in Global Constraints. Add a CHANGELOG bullet in the house style: **Furniture keeps doors and routes clear** (`knoxbuild/furnish_rules.py`, `knoxbuild/layout.py`). Rooms keep a walkway between their doors free and place the pieces that make the room first, so toilets, sinks, beds and fridges are no longer cleared away. A piece standing where a window goes is moved along the wall instead.
- [ ] **Step 3: Run** the full suite, `python tools/audit_layouts.py 400` and `python tools/selftest.py` -> PASS. List what needs the game: rooms walkable end to end, nothing in front of doors, pieces moved off windows look natural, living rooms still read as furnished.
