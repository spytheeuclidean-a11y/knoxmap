# Room Sizing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rooms in houses and flats get sizes that fit their type (bathroom small, living room big), with varied sizes and room mix.

**Architecture:** New `knoxbuild/sizing.py` holds a size table per room kind, programmes (which rooms a flat or house floor gets) and a splitter that cuts a box in proportion to each room's target size. `_apartment_rooms` and the non-solver house path in `build_plan` call it; kinds are fixed at creation.

**Tech Stack:** Python 3, `unittest`, existing `knoxbuild.layout` (`Room`, `_split`, `MIN_ROOM`), `knoxbuild/room_solver.json` "kinds".

**Spec:** `docs/superpowers/specs/2026-10-29-room-sizing-design.md`

## Global Constraints

- Every flat opens onto the corridor; the room at the flat's door is the living room (or open plan); flats touch the corridor.
- Stair, lift, window, door, party-wall, open-plan and hotel-flat rules unchanged.
- No fitting programme or box too small -> fall back to the current `_split` path. Never fail a build.
- Deterministic for a given seed. Smallest room side stays `MIN_ROOM` (3).
- m2 -> tiles uses the project's existing ratio (`Settings.room_size` comment: 16 m2 = 24 tiles).
- Not in scope: OR-Tools solver, furniture, non-home buildings, hotels, exteriors.
- Files: match each file's working-tree line endings (`file`). Tests: `python -m unittest discover -s tests`, `python tools/selftest.py`.
- Baseline measurement: 150 houses + 150 flat blocks, median tiles (flats: bath 15, bed 16, kitchen 20, living 24; houses: bath 9, living 30, bed 20, hall 21, laundry 16, storage 16). Script: `C:\Users\TheTaZe\AppData\Local\Temp\claude\C--KnoxMap\edc14b9e-7d35-452c-9495-df11894fb339\scratchpad\measure.py`.

## Review Focus

- Flat too small for any programme (e.g. 3x5 tiles) -> falls back, no exception (Task 3).
- Open-plan and hotel flats keep their current behaviour (Task 3).
- Irregular/masked footprints: split must respect the mask and still touch the corridor (Task 3).
- Narrow houses (8 wide) and one-storey houses -> still get kitchen, bath, bedroom (Task 4).
- Same seed -> same layout across runs (Task 2).

---

### Task 1: Size table and programmes

**Files:**
- Create: `knoxbuild/sizing.py`
- Test: `tests/test_sizing.py` (create)

**Interfaces:**
- Produces:
  - `@dataclass Size`: `lo: int, target: int, hi: int, aspect: float` (tiles)
  - `SIZES: dict[str, Size]` keyed by Build room kind (`bathroom, bedroom, kidsbedroom, kitchen, livingroom, openplan, dining, hall, closet, laundry, storage, office`), built from `room_solver.json` "kinds" (area in m2, `build` field gives the Build kind) and converted to tiles; kinds the json lacks get explicit fallbacks in `sizing.py`.
  - `programme_for_flat(area: int, rng: random.Random, open_plan: bool = False) -> list[str] | None` — studio / 1-bed / 2-bed / 3-bed by area; always a living room (or `openplan`), one bathroom per 1-2 bedrooms; `None` when area < smallest programme.
  - `programme_for_house_floor(area: int, level: int, levels: int, rng: random.Random) -> list[str] | None`.

- [ ] **Step 1: Write failing tests** `tests/test_sizing.py`: `SIZES["bathroom"].target < SIZES["bedroom"].target < SIZES["livingroom"].target`; every `Size` has `lo <= target <= hi`; `programme_for_flat(20, rng)` has exactly one living/openplan and one bathroom; `programme_for_flat(70, rng)` has >= 2 bedrooms and bathrooms <= bedrooms; `programme_for_flat(8, rng) is None`; house ground floor has a kitchen, upper floor of a 2-storey house has a bedroom and a bathroom.
- [ ] **Step 2: Run** `python -m unittest tests.test_sizing -v` -> FAIL (module missing).
- [ ] **Step 3: Implement** the three names above in `knoxbuild/sizing.py`.
- [ ] **Step 4: Run** `python -m unittest tests.test_sizing -v` -> PASS.

### Task 2: Proportional splitter

**Files:**
- Modify: `knoxbuild/sizing.py`
- Test: `tests/test_sizing.py`

**Interfaces:**
- Consumes: `SIZES`, `layout.Room`, `layout.MIN_ROOM`.
- Produces: `split_by_targets(box: tuple[int,int,int,int], kinds: list[str], rng: random.Random, mask: list[list[bool]] | None = None) -> list[Room] | None` — rooms (kind set, `fixed=True`) covering the box (inside the mask) exactly, areas proportional to each kind's target within `lo..hi` where possible, each side >= `MIN_ROOM`; `None` when it cannot honour `MIN_ROOM`. Recursive guillotine: choose a split of `kinds` into two groups, cut along the longer axis at the ratio of group target areas, recurse; shuffle group choice with `rng` for variety.

- [ ] **Step 1: Write failing tests**: over seeds 0-49 on box (0,0,11,9) with `["livingroom","kitchen","bedroom","bathroom"]` the rooms tile the box exactly (no overlap, full coverage), every side >= 3, bathroom area < bedroom area < livingroom area in >= 90% of seeds; `split_by_targets((0,0,4,3), 4 kinds, rng) is None`; same seed -> identical result; a masked box (L-shape) puts no room tile outside the mask.
- [ ] **Step 2: Run** -> FAIL.
- [ ] **Step 3: Implement** `split_by_targets`.
- [ ] **Step 4: Run** `python -m unittest tests.test_sizing -v` -> PASS.

### Task 3: Flats use kind-first sizing

**Files:**
- Modify: `knoxbuild/layout.py` (`_apartment_rooms` flat cutting ~l.926-948; `_assign_flat_kinds` ~l.1060 must keep `fixed` kinds)
- Test: `tests/test_sizing.py`, existing layout tests

**Interfaces:**
- Consumes: `programme_for_flat`, `split_by_targets`.
- Produces: flats cut by `split_by_targets` when a programme fits (not hotel, not open-plan: open-plan flats pass `open_plan=True` to the programme and use `openplan` + the bedrooms/bath); on `None` from either, the existing `_split` path runs. `_assign_flat_kinds` skips rooms with `fixed=True` but still guarantees the room at the corridor door is the living room: the splitter must place the first kind (`livingroom`/`openplan`) at the box edge on the corridor side.

- [ ] **Step 1: Write failing tests**: over 100 flat blocks (kind="apartment", varied footprints), median bathroom area < median bedroom area < median living/openplan area; bathrooms count <= bedrooms count + number of flats; every flat has a room touching the corridor of kind living/openplan; a 6x5 flat falls back without exception; hotel build (`hotel=True`) output is identical to before (hash a fixed seed's rooms vs a recorded tuple).
- [ ] **Step 2: Run** -> FAIL.
- [ ] **Step 3: Implement** the wiring; keep `FLAT_ROOMS`-based path as the fallback.
- [ ] **Step 4: Run** `python -m unittest tests.test_sizing tests.test_layout_walkability tests.test_designer -v` and the full suite -> PASS.

### Task 4: Houses use kind-first sizing (non-solver path)

**Files:**
- Modify: `knoxbuild/layout.py` (`build_plan` house branch ~l.5438-5451 and `_assign_house_kinds` ~l.1276)
- Test: `tests/test_sizing.py`, `tests/test_house_room_quotas.py`

**Interfaces:**
- Consumes: `programme_for_house_floor`, `split_by_targets`.
- Produces: house floors cut with `split_by_targets` around the reserved stair core (existing `core`/`stairs`), kinds fixed at creation; `_assign_house_kinds` keeps `fixed` rooms and only assigns what remains (halls/landings). Falls back to `_split` when `None`.

- [ ] **Step 1: Write failing tests**: over 100 houses, median hall <= bedroom median, laundry and storage medians < bedroom median, bathroom median < bedroom median < living median; an 8x10 one-storey house still has kitchen, bathroom, bedroom; a 3-storey house has a bathroom on every floor that has a bedroom; `tests/test_house_room_quotas.py` still passes.
- [ ] **Step 2: Run** -> FAIL.
- [ ] **Step 3: Implement** the wiring.
- [ ] **Step 4: Run** the full suite and `python tools/selftest.py` -> PASS.

### Task 5: Measure and record

**Files:**
- Modify: `CHANGELOG.md` (new entry under the current top version section), `docs/superpowers/specs/2026-10-29-room-sizing-design.md` (append "Result" with before/after medians)

- [ ] **Step 1: Run** `measure.py` (path in Global Constraints); expect flats bathroom median clearly below bedroom and living, houses hall/laundry/storage below bedroom.
- [ ] **Step 2: Append** the before/after medians to the spec; add a CHANGELOG line: room sizes now follow room type in houses and flats.
- [ ] **Step 3: Run** the full suite and `python tools/selftest.py` -> PASS; list anything needing the game (does the new spread of room sizes look right in-game).
