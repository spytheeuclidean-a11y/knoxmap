# Basements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generated basements for houses, large buildings and military/industrial installations, baked into the lots at levels -1 to -32.

**Architecture:** Each basement is its own `.tbx` lot at a negative base level, joined to its parent's BuildingDef in the room tables. Basement extents are reserved in build order in the main process (one underground occupancy map); rooms and stairs are planned inside each building's `_make_one` job, which also cuts the stair opening in the parent's ground floor. The compile chain (`map_source` -> `.kcell` -> `knoxlots`) carries signed levels.

**Tech Stack:** Python 3 (numpy, shapely, unittest), Rust (`rust/knoxlots`, cargo).

**Spec:** `docs/superpowers/specs/2026-11-01-basements-design.md`

## Global Constraints

- Levels: -32 to 31 (`IsoChunkMap.BOTTOM_LEVEL = -32`, `TOP_LEVEL = 31`). A basement's top floor is -1.
- A map with no basements compiles to the same bytes as before this work.
- Settings: `basement_share` 0.0-1.0, default 0.4 (x0.25 where `regional.detect_region` is `cn`, `jp` or `kr`); `max_basement_depth` 1-32, default 8.
- Tier thresholds (spec table): church 600 m2; large-building second level at 3,000 m2; industrial installation site 50,000 m2; installation levels `clamp(1 + site_m2 // 20000, 2, max_basement_depth)`. One tile counts as one m2.
- Basement file: `buildings/<parent stem>_bsmt.tbx`. Its rooms join the parent's BuildingDef.
- Never loosen a test threshold; change the code. Never copy game code or assets into the repo.
- `catalog.py` is generated; furniture pieces go in `tools/game_pieces.py`.
- Run Python checks with `PZ_MAPPING_TOOLS=C:\KnoxMap\vendor\PZMappingTools` and the `C:\KnoxMap\.venv` interpreter.
- Commit after each task on `crash-fixes` (PR #62), with the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` trailer.

Deviations from the spec, to tell the user at the end:
- No basement goes "under the parent's own staircase": the ground floor's up-flight stands on those squares, so the opening would cut it. The stair spot is always a free run elsewhere (Task 7).
- No morgue: no morgue room or furniture exists in the code. Hospitals get `storage` and `janitor`.
- An installation basement is capped at `INSTALLATION_MAX_TILES = 40_000` tiles per level, centred on its parent, so a km-wide base does not become one building of thousands of rooms (save buffer, build time). Marked `ponytail:`.
- Lights: basement rooms get what `build_plan` gives a non-ground storey; no new light code.

## Review Focus

1. Two units of one split building, both with basements: their basements touch at -1 and `placed_rooms` would merge the two units into one building (the "uber building"). Expected: two buildings. Test in Task 6.
2. An installation basement that crosses a cell edge: each cell gets its own `min_z`, and the rooms stay in the parent's cell's tables. Test in Task 2.
3. A rebuild over an older build cache (results with no basement field), or a rebuild with `basement_share` lowered: no crash, and no `_bsmt` lot left in the `.pzw` for a building that no longer has one. Test in Task 8.
4. Hand-built preset buildings and room-solver houses: a preset gets no basement; a room-solver house still can. Test in Task 8.
5. An older `knoxlots.exe` reading a source with levels below 0: it must refuse, not write a broken lotheader. `.kcell` version becomes 2 only when `min_z < 0`. Test in Task 1.

---

### Task 1: knoxlots reads and writes signed levels

**Files:**
- Modify: `rust/knoxlots/src/kcell.rs`, `rust/knoxlots/src/header.rs`, `rust/knoxlots/src/compile.rs`, `rust/knoxlots/src/bin/knoxlots.rs`, `rust/knoxlots/src/lib.rs` (a `Reader::i32`), `rust/knoxlots/SOURCE_FORMAT.md`
- Test: `rust/knoxlots/tests/formats.rs`, `rust/knoxlots/tests/source.rs`

**Interfaces:**
- Produces: `KCell.min_z: i32`; `Header.min_z: i32`, `Header.max_z: i32`; `Room.z: i32`. `.kcell` version word: 1 when `min_z >= 0`, 2 when `min_z < 0`; both are read. Levels are `(max_z - min_z + 1) as usize`, computed in i32.
- Errors: `"level {z} is outside -32..31"` for any `min_z < -32` or `max_z > 31`, from `KCell::parse`, `Header::parse` and `compile_cell`.

- [ ] **Step 1: Write the failing tests**

```rust
// tests/formats.rs
#[test]
fn header_with_basement_levels_round_trips() {
    let mut h = header();
    h.min_z = -3; h.max_z = 2;
    h.rooms[0].z = -2;
    let back = Header::parse(&h.write()).unwrap();
    assert_eq!((back.min_z, back.max_z, back.rooms[0].z), (-3, 2, -2));
}
#[test]
fn levels_below_minus_32_are_refused() {
    let mut h = header();
    h.min_z = -33;
    assert!(Header::parse(&h.write()).unwrap_err().contains("outside -32..31"));
}
// tests/source.rs
#[test]
fn source_below_ground_round_trips_and_compiles() {
    let mut k = sample();
    k.min_z = -1;
    let back = KCell::parse(&k.write()).unwrap();
    assert_eq!(back.min_z, -1);
    let files = compile_cell(&back, &manifest(), None);
    let h = Header::parse(&files.header).unwrap();
    assert_eq!((h.min_z, h.max_z), (-1, -1 + back.squares.levels as i32 - 1));
}
#[test]
fn a_source_above_ground_keeps_version_1() {
    assert_eq!(&sample().write()[4..8], &1u32.to_le_bytes());
}
```

Use the helpers already in those files (`header()`, `sample()`); add `manifest()` beside `sample()` if `source.rs` has none, built the way `compiled_files_read_back_as_the_same_cell` builds its manifest.

- [ ] **Step 2: Run, expect compile errors / FAIL**

Run: `cargo test --manifest-path rust/knoxlots/Cargo.toml`
Expected: type errors (`-3` is not `u32`), then FAIL.

- [ ] **Step 3: Implement**

Change the four fields to `i32`. Read and write them as the same four little-endian bytes (`as i32` / `as u32`), so files above ground are byte-identical. `KCell::write` writes version 2 only when `min_z < 0`. Check the range in `parse` and `compile_cell`. Update `SOURCE_FORMAT.md` (signed `min_z`, version 2, range).

- [ ] **Step 4: Run, expect PASS, plus the old tests**

Run: `cargo test --manifest-path rust/knoxlots/Cargo.toml`
Expected: all pass.

- [ ] **Step 5: Build the release binary**

Run: `cargo build --release --manifest-path rust/knoxlots/Cargo.toml`
Expected: `rust/knoxlots/target/release/knoxlots.exe` rebuilt (`tools/compile_map.knoxlots_exe` finds it).

- [ ] **Step 6: Commit**

```bash
git add rust/knoxlots
git commit -m "knoxlots: levels below ground (-32..31)"
```

---

### Task 2: Signed levels through placement and map_source

**Files:**
- Modify: `knoxbuild/world.py` (`Placement`, the `<lot ... level=` writer near line 357), `knoxbuild/kcell.py` (`cell_source`), `tools/map_source.py` (`read_lots`, `_row`)
- Test: `tests/test_basement_compile.py` (new)

**Interfaces:**
- Consumes: Task 1's `.kcell` version rule.
- Produces: `tests/fixtures/basements_baseline.json` (Step 0), used by Task 8's same-bytes test. `Placement.base_level: int = 0`, written as `level="{p.base_level}"`. `read_lots` returns a negative base level from `level="-2"`. `cell_source(..., min_z: int = 0, ...)` packs `min_z` signed and room `z` signed, version word 2 when `min_z < 0`. `_row` stacks levels below 0 (building tiles only, no terrain, no `merge_stack`) and indexes arrays by `z - min_z`, where `min_z = min(0, lowest z in the cell)`.

- [ ] **Step 0: Save the baseline, before any Python change**

Build the selftest's fixture town with today's code and save the SHA-1 of its `.pzw`, every `buildings/*.tbx` and every compiled `.lotheader` to `tests/fixtures/basements_baseline.json`. Commit it on its own (`"Basements: baseline of a town without them"`).

- [ ] **Step 1: Write the failing tests**

```python
class SignedLevels(unittest.TestCase):
    def test_a_lot_at_level_minus_2_is_read_back(self):
        # write a one-lot .pzw with Placement(base_level=-2) via world.py's writer
        ...
        self.assertEqual(read_lots(project)[0][3], -2)

    def test_cell_source_below_ground_is_version_2_and_signed(self):
        data = cell_source(0, 0, ["floors_a_01_0"], [[layer]] * 2, min_z=-1,
                           rooms=[("storage", -1, [(1, 1, 2, 2)], [])])
        version, _cx, _cy, min_z, levels = struct.unpack_from("<3IiI", data, 4)
        self.assertEqual((version, min_z, levels), (2, -1, 2))

    def test_cell_source_above_ground_is_unchanged(self):
        self.assertEqual(cell_source(0, 0, names, [[layer]], min_z=0)[4:8],
                         struct.pack("<I", 1))

    def test_a_basement_lot_compiles_to_level_minus_1(self):
        # tiny project: ground bmp, one house .tbx at level 0, one _bsmt .tbx at -1
        # make_map_source -> knoxlots compile -> read the lotheader
        self.assertEqual(header_levels(cell), (-1, 1))

    def test_an_installation_across_a_cell_edge_gives_both_cells_min_z(self):
        # a _bsmt lot spanning cells (0,0) and (1,0), parent wholly in (0,0)
        self.assertEqual([header_levels(c)[0] for c in (c00, c10)], [-2, -2])
        self.assertTrue(all(r["z"] >= -2 for r in rooms_of(c00)))
        self.assertEqual(rooms_of(c10), [])   # rooms listed in the parent's cell
```

Fill the `...` with the file's own fixture helpers; the assertions above are the contract. `header_levels` reads min/max with `"<4i"` after the tile names (as `tools/building_stats.read_header` does). Skip the two compile tests when `tools.compile_map.knoxlots_exe()` is `None`.

- [ ] **Step 2: Run, expect FAIL**

Run: `python -m unittest tests.test_basement_compile -v`

- [ ] **Step 3: Implement** as in Interfaces. The `read_lots` regex becomes `level="(-?\d+)"`; grep `tools/` for other `<lot ` parsers (`compile_state.py`, `compile_verify_incremental.py`) and make any that read `level` accept the sign.

- [ ] **Step 4: Run Task 2 tests and the compile tests already there**

Run: `python -m unittest tests.test_basement_compile -v` and `python tools/selftest.py`
Expected: PASS; selftest still passes (no basements yet, same bytes).

- [ ] **Step 5: Commit** (`git commit -m "Lots below ground: signed levels through the .pzw and map_source"`)

---

### Task 3: A basement joins its parent's building

**Files:**
- Modify: `knoxbuild/buildheader.py` (`placed_rooms`), `tools/map_source.py` (where `placed_rooms` is called)
- Test: `tests/test_basement_compile.py`

**Interfaces:**
- Produces: `placed_rooms(lots, joins: dict[int, int] | None = None)`: `joins[i] = j` puts lot `i` in lot `j`'s building group. `map_source` builds `joins` from lot names: a lot named `<stem>_bsmt` joins the lot named `<stem>`.

- [ ] **Step 1: Failing test**

```python
def test_basement_rooms_are_in_the_parents_building(self):
    house, bsmt = one_room_building(4, 4), one_room_building(4, 4)
    out = placed_rooms([(house, 10, 10, 0), (bsmt, 10, 10, -1)], joins={1: 0})
    self.assertEqual(len(out), 1)
    self.assertEqual(sorted(e["z"] for e in out[0][2]), [-1, 0])

def test_without_joins_nothing_changes(self):
    lots = [(house, 10, 10, 0), (bsmt, 10, 10, -1)]
    self.assertEqual(len(placed_rooms(lots)), 2)
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement**: after the touching-squares unions, `lot_parent[lfind(i)] = lfind(j)` for each join; the group's corner stays its first lot in `order`.
- [ ] **Step 4: Run, expect PASS** (plus `python -m unittest discover tests -k placed` or the file holding the existing `placed_rooms` tests).
- [ ] **Step 5: Commit** (`"Room tables: a basement is part of its parent building"`)

---

### Task 4: tbx renders stair openings, a basement's top flight, and no roof

**Files:**
- Modify: `knoxbuild/layout.py` (`Plan`), `knoxbuild/tbx.py` (`render_tbx`)
- Test: `tests/test_basement_tbx.py` (new)

**Interfaces:**
- Produces: `Plan.holes: set[tuple[int, int]]`, rendered as `<object type="hole" x="" y=""/>` on that storey (read back by `buildtiles.level_layers`). `render_tbx(plan, name, style=None, roof: bool = True)`; `roof=False` writes no roof floor. A `Building` whose `stairs` has one entry per storey renders a flight on its top storey too (`if level < len(building.stairs)` already does; check nothing else assumes `len(stairs) == len(storeys) - 1`).

- [ ] **Step 1: Failing tests**

```python
def test_holes_are_written_and_leave_no_floor(self):
    plan = small_plan(); plan.holes = {(2, 2), (2, 3), (2, 4)}
    b = parse_tbx(render_tbx(plan, "t"))
    layers = level_layers(b, 0)
    self.assertFalse(any(k == "floor" for k, _ in layers.get((2, 3), [])))

def test_no_roof_floor_when_asked(self):
    b = parse_tbx(render_tbx(small_building(levels=2), "t", roof=False))
    self.assertEqual(len(b.floors), 2)

def test_a_flight_on_the_top_storey(self):
    bld = small_building(levels=1); bld.stairs = [(2, 1, "N")]
    b = parse_tbx(render_tbx(bld, "t", roof=False))
    self.assertTrue(any(o.get("type") == "stairs" for o in b.floors[0].objects))
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** the field, the hole objects and the `roof` switch.
- [ ] **Step 4: Run, expect PASS**, plus `python -m unittest tests.test_window_columns` and the other tbx tests.
- [ ] **Step 5: Commit** (`"tbx: stair openings, a top-storey flight, no roof on request"`)

---

### Task 5: Settings

**Files:**
- Modify: `knoxbuild/settings.py` (dataclass and the ranges table near line 231), wherever `parking_density` gets a label and help text (grep `templates/`, `static/`, `lang/`)
- Test: `tests/test_settings.py` if it exists, else `tests/test_basements.py`

**Interfaces:**
- Produces: `Settings.basement_share: float = 0.4`, `Settings.max_basement_depth: int = 8`; ranges `(0.0, 1.0)` and `(1, 32)`.

- [ ] **Step 1: Failing test**: defaults are 0.4 and 8; a settings file with `max_basement_depth: 40` is clamped to 32 by the existing range handling.
- [ ] **Step 2: Run, expect FAIL.** - [ ] **Step 3: Implement.** - [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** (`"Settings: basement_share, max_basement_depth"`)

---

### Task 6: Tiers and reserving the underground

**Files:**
- Create: `knoxbuild/basements.py`
- Modify: `knoxbuild/areas.py` (`AreaIndex.shape_around`)
- Test: `tests/test_basements.py` (new)

**Interfaces:**
- Consumes: Task 5 settings.
- Produces:
  - `TIERS` constants as in Global Constraints; `INSTALLATION_MAX_TILES = 40_000`.
  - `tier(kind: str | None, footprint_m2: float, site_m2: float) -> str | None` returning `"house"`, `"large"`, `"installation"` or `None`.
  - `levels_for(tier: str, footprint_m2: float, site_m2: float, max_depth: int) -> int`.
  - `class Underground`: `fits(x0: int, y0: int, mask: np.ndarray, levels: int) -> bool`, `take(x0, y0, mask, levels) -> None`. Levels are -1 down to `-levels`. Sparse: per level, a dict of 32x32 boolean blocks keyed by block coordinate.
  - `@dataclass BasementSpec: tier: str; levels: int; dx: int; dy: int; mask: np.ndarray` (dx, dy: the basement lot's corner relative to the parent lot's corner; mask: the basement's squares in its own lot).
  - `reserve(decided_rows: list[dict], settings, region: str | None, areas: AreaIndex | None, rng: random.Random) -> list[BasementSpec | None]`. Each row: `{"kind", "x0", "y0", "w", "h", "mask"}` (the parent's footprint mask). In order: tier, share roll (houses only), extent, `fits`, else shrink to the footprint, `fits`, else `None`; `take` on success.
  - `AreaIndex.shape_around(x: float, y: float) -> Polygon | None`: the polygon `around()` would pick.
- Extents: house and large: the footprint mask eroded by one tile (a wall's width), so units of one split building never touch underground. Installation: the site polygon rasterised into tiles, clipped to the map, cropped to `INSTALLATION_MAX_TILES` centred on the parent, unioned with the eroded footprint; the footprint when there is no site.

- [ ] **Step 1: Failing tests**

```python
def test_tiers(self):
    self.assertEqual(tier("house", 80, 0), "house")
    self.assertEqual(tier("church", 599, 0), None)
    self.assertEqual(tier("church", 600, 0), "large")
    self.assertEqual(tier("industrial", 900, 49_999), "large")
    self.assertEqual(tier("industrial", 900, 50_000), "installation")
    self.assertEqual(tier("military", 50, 0), "installation")
    self.assertEqual(tier("shed", 40, 0), None)

def test_levels(self):
    self.assertEqual(levels_for("house", 90, 0, 8), 1)
    self.assertEqual(levels_for("large", 2_999, 0, 8), 1)
    self.assertEqual(levels_for("large", 3_000, 0, 8), 2)
    self.assertEqual(levels_for("installation", 500, 0, 8), 2)
    self.assertEqual(levels_for("installation", 500, 130_000, 8), 7)
    self.assertEqual(levels_for("installation", 500, 10**7, 8), 8)
    self.assertEqual(levels_for("installation", 500, 10**7, 40), 32)

def test_two_units_of_one_building_do_not_touch_underground(self):
    a = row("house", 10, 10, 6, 6); b = row("house", 16, 10, 6, 6)   # share a wall
    specs = reserve([a, b], settings(basement_share=1.0), None, None, rng())
    lots = [(bld_from(a), 10, 10, 0), (bld_from(b), 16, 10, 0),
            (bsmt_from(a, specs[0]), ..., -1), (bsmt_from(b, specs[1]), ..., -1)]
    self.assertEqual(len(placed_rooms(lots, joins={2: 0, 3: 1})), 2)

def test_an_installation_spreads_over_its_site_but_not_past_it(self): ...
def test_a_second_installation_on_the_same_squares_shrinks_then_drops(self): ...
def test_share_zero_reserves_no_house_basement(self): ...
def test_east_asian_region_quarters_the_house_share(self):
    # 4,000 houses, share 0.4, region "jp": between 300 and 500 basements
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** as in Interfaces. The crop: `# ponytail: square crop centred on the parent; follow the site's shape if bases look cut off`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** (`"Basements: tiers and the underground occupancy map"`)

---

### Task 7: Planning a basement and its stairs

**Files:**
- Modify: `knoxbuild/basements.py`, `knoxbuild/layout.py` (`SPECIAL_MIXES`)
- Test: `tests/test_basements.py`

**Interfaces:**
- Consumes: `BasementSpec` (Task 6); `layout.build_plan`, `layout.Building`, `layout._clear_for_stairs`, `layout.STAIR_RUN`; `Plan.holes` (Task 4).
- Produces:
  - `SPECIAL_MIXES` entries, using room names that already exist: `"basement_house"`: laundry, storage, garage (workshop), livingroom (rec room), storage (utility). `"basement_school"`: janitor, storage. `"basement_medical"`: storage, janitor. `"basement_police"`: prisoncells, policestorage. `"basement_mall"` and `"basement_civic"`: storage, office. `"basement_industrial"`: storage, warehouse. `"basement_church"`: storage, kitchen. `"basement_military"`: armystorage, bedroom, office, storage, kitchen, bathroom.
  - `find_stair_spot(ground: Plan, mask_in_parent: np.ndarray) -> tuple[int, int, str] | None`: a `(x, y, dir)` whose `STAIR_RUN` squares lie in one room named hall, kitchen, laundry, storage, office, lobby or corridor (large and installation tiers also any room except bathroom and bedroom), none of them a door square or the square in front of a door, all inside the basement mask. Scan rows top-left first, `"N"` before `"W"`, and take the first one, so it is deterministic.
  - `@dataclass Basement: building: Building; dx: int; dy: int; levels: int`.
  - `plan_basement(parent: Building, spec: BasementSpec, seed: int, settings) -> Basement | None`: `None` when `find_stair_spot` finds nothing. Otherwise, one `build_plan(w, h, kind=f"basement_{kind}", mask=spec.mask, ground=False, stairs=spot_in_basement, level=i, levels=spec.levels, corridor=spec.tier == "installation", settings=settings, seed=seed + i)` per level, bottom first. `windows = []` and no outside doors on every storey. `stairs` is the same spot on every storey (one stacked core). On `parent.storeys[0]`: `_clear_for_stairs` at the spot, and `holes` gets the three squares `buildtiles._stair_squares` gives for it.
  - `render_basement(b: Basement, label: str, style: dict) -> str`: `render_tbx(b.building, label, basement_style(style), roof=False)`, where `basement_style` swaps the outer walls and floors for the concrete ones the industrial style uses.

- [ ] **Step 1: Failing tests**

```python
def test_a_house_basement_stairs_land_in_a_ground_floor_room(self):
    parent = build_building(9, 8, seed=3)
    b = plan_basement(parent, spec_under(parent), 3, Settings())
    sx, sy, d = b.building.stairs[-1]
    room = parent.storeys[0].grid[sy + b.dy][sx + b.dx]   # spot in parent tiles
    self.assertNotEqual(room, 0)
    self.assertTrue(set(stair_squares(sx + b.dx, sy + b.dy, d)) <= parent.storeys[0].holes)

def test_no_spot_no_basement(self):
    parent = build_building(4, 4, seed=1)          # too small for a 5-tile run
    self.assertIsNone(plan_basement(parent, spec_under(parent), 1, Settings()))

def test_a_basement_has_no_windows_or_outside_doors(self): ...
def test_an_installation_has_one_stair_core_through_every_level(self):
    b = plan_basement(barracks, installation_spec(levels=4), 5, Settings())
    self.assertEqual(len(b.building.storeys), 4)
    self.assertEqual(len(set(b.building.stairs)), 1)
def test_the_rendered_basement_has_no_roof_floor(self): ...
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS**, plus `python tools/audit_layouts.py 400` (layouts unchanged so far).
- [ ] **Step 5: Commit** (`"Basements: rooms, stairs and the opening above them"`)

---

### Task 8: Wiring into the build

**Files:**
- Modify: `knoxbuild/build.py` (after the party-wall loop near line 1838; `_make_one`; the cache read near line 1855 and wherever the cache is written; the placement loop near line 1874; the summary prints near line 2095)
- Modify: any tool that counts buildings from `buildings/*.tbx` (grep `glob("*.tbx")`, `listdir(... "buildings")`): skip `*_bsmt.tbx` where it counts buildings
- Test: `tests/test_basements.py` (small end-to-end build)

**Interfaces:**
- Consumes: Tasks 2-7.
- Produces:
  - Jobs gain one last element, `BasementSpec | None` (after `party`), from `basements.reserve`. `_job_key` covers it as is.
  - `_make_one` returns a sixth element: `None`, or `{"file": "<stem>_bsmt.tbx", "dx", "dy", "w", "h", "levels", "rooms"}`. Preset buildings return `None` before any basement work. Room-solver plans go through `plan_basement` like any other.
  - The cache stores that sixth element; an older entry without it reads as `None`.
  - The placement loop adds `Placement(f"buildings/{file}", x0 + dx, y0 + dy, w, h, levels=levels, base_level=-levels)` after the parent's.
  - A stale `<stem>_bsmt.tbx` from an earlier build, whose building now has none, is deleted.
  - Summary line: `basements           : {houses} houses, {large} large, {installations} installations ({skipped} without a stair spot)`.

- [ ] **Step 1: Failing tests**

```python
def test_a_town_with_basements_builds_and_compiles(self):
    out = build_small_town(basement_share=1.0)     # the selftest's fixture town
    pzw = read_text(out, "*.pzw")
    self.assertIn('level="-1"', pzw)
    self.assertTrue(glob(out, "buildings/*_bsmt.tbx"))

def test_share_zero_leaves_no_basement_lots_behind(self):
    out = build_small_town(basement_share=1.0)
    build_small_town(basement_share=0.0, out=out)  # rebuild over the same folder
    self.assertNotIn("_bsmt", read_text(out, "*.pzw"))
    self.assertFalse(glob(out, "buildings/*_bsmt.tbx"))

def test_an_old_cache_entry_without_a_basement_still_reuses(self): ...
def test_a_preset_building_gets_no_basement(self): ...
def test_no_basements_same_bytes(self):
    # basement_share 0 and no large kinds: hashes equal
    # tests/fixtures/basements_baseline.json (Task 2, Step 0)
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover tests` and `python tools/selftest.py`
Expected: all pass.

- [ ] **Step 5: Commit** (`"Build: basements under houses, large buildings and installations"`)

---

### Task 9: selftest and the layout audit

**Files:**
- Modify: `tools/selftest.py`, `tools/audit_layouts.py`

**Interfaces:**
- Produces: selftest check `"a house basement compiles to level -1 and its stairs reach the house"`; the audit runs its door/room checks on basement storeys and reports a line `basement rooms with no way in: N of M`.

- [ ] **Step 1: Add the selftest check and run it, expect FAIL** on a selftest town built with `basement_share` 0 (proves the check can fail); then set the selftest town's share to 1.0.
- [ ] **Step 2: Run `python tools/selftest.py`**: expect `selftest passed`.
- [ ] **Step 3: Run `python tools/audit_layouts.py 400`**: expect exit 0 and `basement rooms with no way in: 0 of M`.
- [ ] **Step 4: Commit** (`"selftest and audit: basements"`)

---

### Task 10: Real maps, then the game

- [ ] **Step 1:** Rebuild the Piqua copy in the scratchpad (`python -m knoxbuild <copy>`), compile it, and report the summary line plus the basement-room count against the 9 MB save-buffer warning.
- [ ] **Step 2:** Build one map with a military base (ask the user which) and report levels and rooms per installation.
- [ ] **Step 3:** Push to PR #62 and update its description.
- [ ] **Step 4 (needs user):** In game, walk down into a house basement and into a military one, -1 to the bottom. Send the `DebugLog` if anything fails.
