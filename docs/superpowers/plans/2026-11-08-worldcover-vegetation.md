# WorldCover Vegetation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the WorldCover class grid into class-appropriate ground and vegetation (woods, scrub, meadow, fields, marsh with pools, rock fields) on ground OSM leaves blank, and draw fields on OSM farmland.

**Architecture:** The WorldCover base is painted in per-class *marker* colours that no real ground uses. After OSM ground is painted, the tiles still in a marker colour are WorldCover's own (`owned`); they are settled to their real colours. Two new modules then work off `grid` + `owned`: `fields.py` paints ground (fields, pools, rock fields) and `landcover_veg.py` plants vegetation and returns the tree-cover mask for the existing woodland pass. Wild growth and groves skip owned tiles.

**Tech Stack:** Python 3.12, numpy, Pillow, shapely (already deps); rasterio (new pin); unittest.

## Global Constraints

- Layer stays on by default; cache location unchanged; no download in the generate path; `"osm"` option unchanged.
- OSM always wins: nothing in this plan paints a tile OSM claimed, except fields and pools on OSM `landuse=farmland` / OSM wetland polygons themselves.
- Only rules already in stock `vendor/PZMappingTools/config/Rules.txt`: Horizontal Dirt `120,110,95`, Vertical Dirt `120,100,75` (ground); Farm Corn 1 (dead) `255,128,0`, Farm Corn 2 (dead) `220,100,0`, Boulders `140,160,140`, Boulders (walkable) `100,120,100` (vegetation).
- Determinism: fixed seed constants per pass (the renderer has no map seed; every existing pass does the same).
- Optional data never fails a map: any exception in WorldCover handling is logged and the map is built as if `grid` were `None`.
- Tests are `unittest`, run with `/home/boates/code/knoxmap/.venv/bin/python -m unittest`.
- `rasterio==1.5.2` (released 2026-09-30).

## Spec deviations (to record in the spec at the end)

- "Seeded from the map seed" → fixed seed constants (no map seed exists in `render`).
- `POOL_MAX_TILES` dropped: pools come from a small-scale noise field (cell ≈ 10 tiles) thresholded at the top 10%, which yields separate blobs without a connected-component pass (no scipy dependency).
- The OSM mask is computed with marker colours, not a second mask drawn at every paint call.

## File Structure

| File | Responsibility |
|---|---|
| `generator/pz_colors.py` | 6 new colours + colour sets |
| `generator/rendering/noise.py` (new) | `smooth_noise()` — the grove pass's lattice noise, shared |
| `generator/rendering/landcover.py` | marker colours, `paint_markers()`, `settle_markers()` |
| `generator/rendering/fields.py` (new) | `paint_fields()`, `paint_pools()`, `paint_rocks()` — ground |
| `generator/rendering/landcover_veg.py` (new) | `plant_landcover()` — vegetation per class |
| `generator/rendering/vegetation.py` | `exclude=` on wild growth + groves; `extra_forest=` on woodland; groves use `noise.py` |
| `generator/renderer.py` | wiring and order |
| `generator/rendering/outputs.py` | preview colours for corn, rocks, bushes, marsh |
| `knoxbuild/yards.py`, `generator/rendering/furniture.py` | furrow colours count as open ground |
| `requirements.txt` | rasterio pin |
| `docs/DATASETS.md`, `CHANGELOG.md`, spec | docs |

---

### Task 1: Colours and shared noise

**Files:** Modify `generator/pz_colors.py`; Create `generator/rendering/noise.py`; Modify `generator/rendering/vegetation.py` (`_paint_groves` uses the helper); Test `tests/test_landcover_noise.py`

**Produces:**
- `C.DIRT_ROWS_H = (120,110,95)`, `C.DIRT_ROWS_V = (120,100,75)` (in `LANDSCAPE_COLORS`)
- `C.CORN_1 = (255,128,0)`, `C.CORN_2 = (220,100,0)`, `C.BOULDERS = (140,160,140)`, `C.ROCKS = (100,120,100)` (in `VEGETATION_COLORS`)
- `noise.smooth_noise(rows: np.ndarray, cols: np.ndarray, lattices: list[tuple[np.ndarray, int, float]]) -> np.ndarray[float32]` and `noise.lattices(h, w, specs: list[tuple[int, float]], seed: int)` building `(lattice, cell, weight)` triples.

- [ ] Test: `smooth_noise` is in [0,1], deterministic for a seed, smooth (adjacent tiles differ < 0.2 with cell 20); all 6 colours unique vs every other colour in `pz_colors`.
- [ ] Run, see fail. Implement by moving `lattice()`/`noise()` out of `_paint_groves` into `noise.py`; `_paint_groves` calls it with the same lattices and seed so its output is byte-identical.
- [ ] Run new test + `tests.test_big_trees` + `tools/selftest.py` grove-related checks pass. Commit.

### Task 2: Marker colours and the owned mask

**Files:** Modify `generator/rendering/landcover.py`; Test `tests/test_landcover_markers.py`

**Produces:**
- `MARKER = {code: (3, 7, code) for code in WORLDCOVER_PAINT}` — asserted disjoint from `LANDSCAPE_COLORS`.
- `paint_markers(landscape, grid) -> None` — paints marker colours (resized NEAREST to the image size) where `grid>0`; leaves class 0 alone.
- `settle_markers(landscape, grid) -> np.ndarray[bool]` — returns `owned` (tile still a marker colour), replaces every marker pixel with `WORLDCOVER_PAINT[code]`. Works in strips of 1024 rows.
- `refine_owned(landscape, grid, owned) -> None` — in place, `owned &= landscape == WORLDCOVER_PAINT[grid]` (drops tiles dense paving or shape clipping repainted).

- [ ] Test: 20×20 grid half 10 half 30; paint markers; draw an OSM polygon (MEDIUM_GRASS, same as class 30's colour) over a corner; settle → corner not owned, rest owned, no marker colour left, colours equal `WORLDCOVER_PAINT`. `refine_owned` drops a tile repainted PALE_CONCRETE.
- [ ] Run fail → implement → pass. Commit.

### Task 3: Fields

**Files:** Create `generator/rendering/fields.py`; Test `tests/test_fields.py`

**Constants:** `FIELD_CELL_M = (60.0, 150.0)`, `CORN_SHARE = 0.5`, `BARE_SHARE = 0.35` (rest fallow), `HEDGE_CHANCE = 0.4`, `FALLOW_TUFTS = 0.2`, `FIELD_SEED = 4421`.

**Produces:** `paint_fields(landscape, veg, proj, polygons: list[list[tuple[float,float]]], cropland: np.ndarray | None) -> int` (plots painted).
- One field per OSM polygon (pixel rings): its mask = polygon raster & ground == `LIGHT_GRASS` (so roads/paths OSM painted over it survive). Angle θ from shapely `minimum_rotated_rectangle` long side. Plot ids from rotated coords `u = x cosθ + y sinθ`, `v = -x sinθ + y cosθ`, cell sizes drawn per field from `FIELD_CELL_M` / `meters_per_tile`. Furrow colour: `DIRT_ROWS_H` if the long axis is nearer horizontal, else `DIRT_ROWS_V`.
- WorldCover cropland (`cropland` bool mask, already `LIGHT_GRASS`): θ = 0, one global grid with per-column / per-row sizes drawn from `FIELD_CELL_M`; furrow direction per plot = its longer side.
- Per plot (rng by plot id): corn (CORN_1 or CORN_2 for the whole plot) / bare / fallow by shares. Border tiles (4-neighbour has another plot id or is outside the field) stay `LIGHT_GRASS`; with `HEDGE_CHANCE` a plot's border gets `BUSHES`. Interior: furrow ground; corn plots also get the corn vegetation; fallow keeps `LIGHT_GRASS` + `SHORT_GRASS` on `FALLOW_TUFTS` of tiles.
- Polygon fields processed in their bounding box; cropland processed in strips of 512 rows with a 1-row halo.

- [ ] Tests: (a) 400×100 m OSM rectangle at 1 m/tile → ≥ 3 plot ids, interior ground only furrows/LIGHT_GRASS, furrows are `DIRT_ROWS_H`; rotated 90° → `DIRT_ROWS_V`. (b) A road stroke painted over the field before → still road after. (c) 2000×2000 cropland mask → corn share of plots 0.35–0.65, bare 0.2–0.5. (d) Same input twice → identical images.
- [ ] Fail → implement → pass. Commit.

### Task 4: Wetland pools and rock fields

**Files:** Modify `generator/rendering/fields.py`; Test `tests/test_fields.py`

**Constants:** `POOL_SHARE = 0.10`, `POOL_CELL_M = 10.0`, `POOL_CLEAR_TILES = 2`, `POOL_SEED = 7001`; `ROCK_SHARE = {100: 0.30, 60: 0.10}`, `BOULDER_SHARE = {100: 0.03, 60: 0.01}`, `MOSS_SHARE = 0.30`, `ROCK_CLUMP_M = 25.0`, `ROCK_CLEAR_TILES = 2`, `ROCK_SEED = 8123`, `TUNDRA_BUSH = 0.02`.

**Produces:**
- `paint_pools(landscape, veg, proj, wet: np.ndarray, blocked: np.ndarray) -> int` — `wet` = WC wetland/mangrove owned tiles | OSM wetland polygons (types per spec); `blocked` = building footprints. Allowed = `wet & ~_box_any(~wet | blocked, POOL_CLEAR_TILES)`. Threshold `smooth_noise` (cell `POOL_CELL_M`) at the `1-POOL_SHARE` quantile of its values on `wet`. Pool → ground `WATER`, veg nothing; a 1-tile ring inside `wet` → `DENSE_BUSHES_GRASS` on `DARK_GRASS`.
- `paint_rocks(landscape, veg, proj, grid, owned) -> int` — for codes 100 and 60 on owned tiles: ground `DIRT`; for 100, `DARK_GRASS` where a second noise is in its top `MOSS_SHARE`. Clumps: noise (cell `ROCK_CLUMP_M`) top `2*share` of the class's tiles; inside clumps each tile `ROCKS` with p=0.5. `BOULDERS` with p=`BOULDER_SHARE` on tiles not within `ROCK_CLEAR_TILES` of a non-owned tile (roads, paths, buildings). Class 100: `BUSHES` on `TUNDRA_BUSH` of remaining tiles.

- [ ] Tests: pools cover 0.06–0.14 of a 300×300 wetland; none within 2 tiles of a road painted through it; `wet_meadow` excluded is the caller's job (tested in Task 6). Rocks ≈ 0.30 (±0.08) on class 100, ≈ 0.10 (±0.05) on class 60; no boulder within 2 tiles of a non-owned strip; no trees.
- [ ] Fail → implement → pass. Commit.

### Task 5: Class planting

**Files:** Create `generator/rendering/landcover_veg.py`; Test `tests/test_landcover_veg.py`

**Constants:** `SHRUB_CLUMP_M = 40.0`, `SHRUB_IN = 0.35`, `SHRUB_OUT = 0.08`, shrub mix `BUSHES 0.65 / young 0.25 / SPARSE_TREES 0.10`; `GRASS_TUFTS = 0.20`, `GRASS_BUSH = 0.01`; `MARSH = 0.6`, `MARSH_TREE = 0.03`; `VEG_SEED = 6203`.

**Produces:** `plant_landcover(veg, landscape, grid, owned, proj, density=1.0) -> tuple[np.ndarray, dict]` — returns `(forest_mask, counts)`. Only on `owned & veg empty`:
- 10 → into `forest_mask` (not painted here).
- 20 → clumped scatter; young = `TREE_SMALL` if `tree_rules_ready()` else `SPARSE_TREES`; `SPARSE_TREES` tiles get `DARK_GRASS` ground.
- 30 → `SHORT_GRASS` / `BUSHES`.
- 90, 95 → `DENSE_BUSHES_GRASS` (ground `DARK_GRASS`), `SPARSE_TREES`.
- 40, 50, 60, 70, 80, 100 → nothing here (fields/rocks/gardens own them).
Chances × `density`, capped at 1.

- [ ] Tests: synthetic 200×200 grid of 5 stripes (10,20,30,90,60): each stripe only its allowed colours; class 10 stripe in `forest_mask` and unpainted; unowned tiles untouched; density 0 plants nothing; deterministic.
- [ ] Fail → implement → pass. Commit.

### Task 6: Renderer wiring, vegetation hooks, dependents

**Files:** Modify `generator/renderer.py`, `generator/rendering/vegetation.py`, `generator/rendering/outputs.py`, `knoxbuild/yards.py`, `generator/rendering/furniture.py`; Test `tests/test_landcover_render.py`

- `vegetation.py`: `_paint_wild_growth(..., exclude=None)` and `_paint_groves(..., exclude=None)` do `free &= ~exclude`; `_paint_vegetation(..., extra_forest=None)` → `_paint_woodland(..., extra_forest=None)` pastes `extra_forest` (255) into `mask` before erosion.
- `renderer.render()`:
  1. `grid = landcover_for(w,h)` in try; if grid: `paint_markers`; relief (if any) deferred; else relief as today.
  2. After rails + bridge decks, before `_pave_dense_ground`: `owned = settle_markers(...)`.
  3. After `_weather_roads`: `refine_owned`; relief on owned tiles only (relief on a copy, pasted through the `owned` mask).
  4. Ground: `paint_fields` (OSM `landuse=farmland` rings + `owned & grid==40`), `paint_pools` (WC 90/95 owned | OSM wetland whose `wetland` tag is missing or in marsh/swamp/bog/reedbed; blocked = building footprints), `paint_rocks`.
  5. Veg: `_paint_vegetation(..., extra_forest=forest)` where `forest, counts = plant_landcover(...)` is computed **before** `_paint_vegetation` but its painting must not be overwritten by woodland — so call `plant_landcover` first (woodland only paints the forest mask and OSM woods, which don't overlap owned non-forest tiles). Then parks, gardens, wild growth and groves with `exclude=owned`.
  6. Everything wrapped so an exception logs and falls back (`grid=None, owned=None`) — with markers already painted, the fallback calls `settle_markers` to restore real colours.
- `outputs._build_preview`: corn → (200,170,60), rocks/boulders → (150,150,145), bushes/marsh → (80,110,50); furrows show as their ground colour.
- `yards.CROSSABLE`, furniture `roadside` add `DIRT_ROWS_H`, `DIRT_ROWS_V`.

- [ ] Test (`test_landcover_render.py`): call `renderer.render` on a tiny synthetic feature list (one road, one OSM residential polygon, one `landuse=farmland`) with a `landcover_for` returning a fixed grid → no marker colour in `<map>.bmp`; residential polygon has no WC vegetation; farmland has furrows; class-10 area has trees; a `landcover_for` that raises still produces a map.
- [ ] Run whole suite `python -m unittest discover tests` and `python tools/selftest.py`; fix regressions. Commit.

### Task 7: Dependency, docs, comparison

**Files:** `requirements.txt`, `docs/DATASETS.md`, `CHANGELOG.md`, spec, `docs/images/worldcover/*`

- [ ] `rasterio==1.5.2` in `requirements.txt` with a comment; install into the venv.
- [ ] Fetch WorldCover for two boxes via `knoxdata.refresh`; render each with `landcover="off"` and `"worldcover"`; save side-by-side previews to `docs/images/worldcover/`.
- [ ] DATASETS.md WorldCover section: per-class table. CHANGELOG entry. Spec deviations recorded. Commit.
