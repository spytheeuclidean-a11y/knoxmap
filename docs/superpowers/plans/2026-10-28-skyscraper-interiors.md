# Skyscraper Interiors and 32-Storey Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Office towers get a central-core, open-floor interior with a lobby and plant floor, and maps can build up to 32 storeys.

**Architecture:** New `knoxbuild/tower.py` decides whether a building is a tower and where its core goes (stair hall, 2-4 lifts, toilets, riser). `build_building` calls it and passes the result to `build_plan`, which cuts each floor around the core. `Plan` learns to carry several lifts.

**Tech Stack:** Python 3, `unittest`, existing `knoxbuild.layout` helpers (`_split`, `_assign_kinds`, `_carve_shaft`, `_doors`).

**Spec:** `docs/superpowers/specs/2026-10-28-skyscraper-interiors-design.md`

## Global Constraints

- Trigger: `kind == "civic"` and `levels >= 12` and `min(width, height) >= 14`. Anything else runs the existing path unchanged.
- Height cap: `LIMITS["max_levels"] = (1, 32)` (Build 42: 32 levels above ground).
- Core is the same rectangle(s) on every floor, wholly inside the mask and inside the setback's upper mask.
- Plant floor level = `round(levels * 0.9)`; no offices on it.
- Towers keep ONE stair (`Building.stairs` unchanged). Exteriors, facades, flat/hotel towers untouched.
- No central core fits -> fall back to the existing path. Never fail a build.
- `C:\KnoxMap` is not a git repo: skip commit steps; match each file's existing line endings (check with `file`).
- Tests: `python -m unittest discover -s tests` (581 pass now) and `python tools/selftest.py`.

## Review Focus

- L/T-shaped mask whose notch leaves no room for a central core -> falls back, no exception (Task 3).
- Ground floor with OSM `uses` (shop/bank) or `mapped` rooms on a tower -> still gets a lobby and a reachable core, no crash (Task 4).
- Setback storeys (>= 8 when levels = 12) -> core, lifts and lift doors all still inside the narrower upper mask (Task 5).
- Non-square, odd-sized footprints (15x37, 14x14 exactly) -> every office area has a door to the lift lobby (Task 4).
- `levels = 32` end to end -> 32 storeys, plant floor at 29, no office on it (Task 5).

---

### Task 1: Raise the height cap to 32

**Files:**
- Modify: `knoxbuild/settings.py:218-222`, `static/js/app.js:462`, `tests/test_suggested.py:61`
- Test: `tests/test_zones.py` (existing clamp test reads `LIMITS`)

**Interfaces:**
- Produces: `LIMITS["max_levels"] == (1, 32)`

- [ ] **Step 1: Write the failing test** in `tests/test_zones.py`: `test_max_levels_ceiling_is_build_42` asserting `LIMITS["max_levels"] == (1, 32)`.
- [ ] **Step 2: Run it** `python -m unittest tests.test_zones -v` -> FAIL (30 != 32).
- [ ] **Step 3: Change** the limit to `(1, 32)`; fix the settings comment; change the `app.js` hint text to "up to 32 - Build 42's height limit"; check `tests/test_suggested.py:61` still makes sense (it passes `max_levels: 30` as a value, leave unless it asserts the cap).
- [ ] **Step 4: Run** `python -m unittest tests.test_zones tests.test_suggested -v` -> PASS.

### Task 2: Plans can carry several lifts

**Files:**
- Modify: `knoxbuild/layout.py` (`Plan` ~l.110, `_carve_shaft` ~l.4867, `_cut_off_by_the_shaft` ~l.4826, `_furnish` shaft-door sites ~l.3956 and ~l.3974, `build_plan` ~l.5493)
- Test: `tests/test_lifts.py` (create)

**Interfaces:**
- Produces: `Plan.shafts: list[tuple[tuple[int,int,int,int], tuple[int,int,str]]]` (rect, door). `Plan.shaft` / `Plan.shaft_door` stay and hold the first lift, so existing readers keep working. `_carve_shaft(plan, shaft, door)` may be called repeatedly. `build_plan(..., extra_shafts: list[tuple[rect, door]] | None = None)` carves each after the first.

- [ ] **Step 1: Write the failing test** `test_two_lifts_are_two_sealed_rooms_with_two_door_pieces`: build a plan via `build_plan(30, 30, kind="civic", core=..., shaft=A, shaft_door=da, extra_shafts=[(B, db)], levels=2, level=0)`; assert two rooms with `is_shaft`, `len(plan.shafts) == 2`, and two `elevator_door` furniture entries.
- [ ] **Step 2: Run** `python -m unittest tests.test_lifts -v` -> FAIL.
- [ ] **Step 3: Implement.** Add the field; `_carve_shaft` appends to `plan.shafts` and sets `shaft`/`shaft_door` only the first time; `_furnish` loops over `plan.shafts` for door edges and `elevator_door` pieces; `_cut_off_by_the_shaft` treats every `is_shaft` room as sealed (start from the largest non-shaft room, as now).
- [ ] **Step 4: Run** `python -m unittest tests.test_lifts tests.test_layout_walkability tests.test_designer -v` -> PASS.

### Task 3: Tower core picker

**Files:**
- Create: `knoxbuild/tower.py`
- Test: `tests/test_tower.py` (create)

**Interfaces:**
- Produces:
  - `TOWER_FROM_LEVELS = 12`, `TOWER_MIN_SIDE = 14`, `PLANT_SHARE = 0.9`
  - `qualifies(kind: str | None, levels: int, width: int, height: int) -> bool`
  - `plant_level(levels: int) -> int`
  - `@dataclass TowerCore`: `stair: tuple[int,int,int,int]` (stair hall, same shape `_pick_core` returns), `lifts: list[tuple[rect, door]]` (2-4, same shape `_pick_shaft` returns), `service: list[tuple[rect, str]]` (toilets as `"bathroom"`, riser as `"storage"`)
  - `pick_core(width: int, height: int, mask: list[list[bool]] | None, rng: random.Random) -> TowerCore | None`
- Consumes: `layout._stairs_in_core`, `layout.STAIR_RUN`, `layout.SHAFT_SIZE`.

- [ ] **Step 1: Write failing tests** in `tests/test_tower.py`: `qualifies("civic", 12, 14, 14)` true; false for `"apartment"`, `levels=11`, `min side 13`; `plant_level(32) == 29`; `pick_core(30, 30, None, Random(1))` returns 2-4 lifts, all rects inside 30x30, no two rects overlap, stair centre within 4 tiles of footprint centre; a 20x20 mask with a 12x12 notch removed returns `None`.
- [ ] **Step 2: Run** `python -m unittest tests.test_tower -v` -> FAIL (module missing).
- [ ] **Step 3: Implement** `tower.py`. Place the stair hall at the centre of the mask (try offsets outward until the rect is fully in the mask), put lifts in a row against its long side (doors facing the hall, as `_pick_shaft` does), toilets and riser on the opposite side. Return `None` when any piece falls outside the mask.
- [ ] **Step 4: Run** `python -m unittest tests.test_tower -v` -> PASS.

### Task 4: Cut a tower floor around the core

**Files:**
- Modify: `knoxbuild/layout.py` (`build_plan`: new `tower: TowerCore | None = None` and `plant: bool = False` parameters; new helper `_tower_rooms(plan, rng, tower, ground, plant)`)
- Test: `tests/test_tower.py`

**Interfaces:**
- Consumes: `TowerCore` (Task 3), multi-lift `build_plan` (Task 2).
- Produces: `build_plan(..., tower=TowerCore | None, plant=bool)`. With `tower`: the ring around the core is cut into a few large `office` areas (target area about a quarter of the ring, partitions kept few); toilets/riser from `tower.service`; every area gets a door to the lift lobby (the hall around the core). `ground=True` makes the room facing the street a `lobby` with the entrance. `plant=True` makes every non-core room `storage`.

- [ ] **Step 1: Write failing tests**: for footprints (14,14), (15,37), (30,30): `test_every_office_area_has_a_door_to_the_lift_lobby` (walk `plan.doors`/room adjacency; every `office` room reaches the hall room), `test_ground_floor_has_a_lobby_with_an_entrance`, `test_plant_floor_has_no_offices`, and `test_ground_floor_with_uses_and_mapped_rooms_still_builds` (pass `uses=[("shop","office")]`).
- [ ] **Step 2: Run** `python -m unittest tests.test_tower -v` -> FAIL.
- [ ] **Step 3: Implement** `_tower_rooms` using `_split` on the ring with a large `target_area`, `_paint`, then `_assign_kinds` for offices; reuse `_doors` for connectivity and `_exterior_door` for the entrance. Skip the shop/retail ground branch when `tower` is set.
- [ ] **Step 4: Run** `python -m unittest tests.test_tower tests.test_layout_walkability -v` -> PASS.

### Task 5: Wire towers into `build_building`

**Files:**
- Modify: `knoxbuild/layout.py` `build_building` (~l.5086-5195) and `_setback` (~l.5207)
- Test: `tests/test_tower.py`

**Interfaces:**
- Consumes: `tower.qualifies`, `tower.pick_core`, `tower.plant_level`.
- Produces: no new public names. When `qualifies(kind, levels, width, height)` and `pick_core(...)` is not `None`: `core` = the tower's stair hall, `stairs = _stairs_in_core(core)`, the first lift is `shaft`/`shaft_door`, the rest go to `build_plan(extra_shafts=...)`; each storey gets `tower=` and `plant=(lvl == plant_level(levels))`. `_setback` checks every lift rect, not just `shaft`.

- [ ] **Step 1: Write failing tests**: `test_a_32_storey_tower_builds` (`build_building(30, 40, levels=32, kind="civic", seed=3)`: 32 storeys, same lift rects on every storey, storey 29 has no `office`); `test_setback_keeps_core_inside_upper_floors` (levels=12; every lift rect inside the upper floors' mask); `test_a_footprint_with_no_room_for_a_core_falls_back` (notched mask: builds, no exception).
- [ ] **Step 2: Run** `python -m unittest tests.test_tower -v` -> FAIL.
- [ ] **Step 3: Implement** the branch in `build_building`; otherwise leave the function alone.
- [ ] **Step 4: Run** `python -m unittest tests.test_tower -v` -> PASS.

### Task 6: Full verification and acceptance fixture

**Files:**
- Create: `tests/fixtures/summer_street_100.json` (footprint polygon, tiles) if the user supplies data; otherwise a 40x24 rectangle stand-in noted as such
- Test: `tests/test_tower.py`; `docs`/`CHANGELOG` entry under 1.7.6.5

- [ ] **Step 1: Add** `test_summer_street_footprint_builds_32_storeys` using the fixture footprint at 32 levels.
- [ ] **Step 2: Run** `python -m unittest discover -s tests` -> all pass (581 + new).
- [ ] **Step 3: Run** `python tools/selftest.py` -> passes.
- [ ] **Step 4: Add** a CHANGELOG line: towers get a central core and open floors; height limit 32.
- [ ] **Step 5: Report** what needs the game: 32-storey roof loads, lifts work with the Elevators mod.
