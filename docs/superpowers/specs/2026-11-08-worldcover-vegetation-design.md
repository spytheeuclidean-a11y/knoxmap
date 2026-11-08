# WorldCover vegetation, fields and wetland pools — design

Date: 2026-11-08
Branch: `worldcover-vegetation` (from `vp717/knoxmap` main, `c8121bf`)
Issue: vp717/knoxmap#5 (follow-up to PR #69)

## Background

PR #69 (release 1.8.4.2) added ESA WorldCover as an optional data layer
(`knoxdata/worldcover.py`). It reads a class grid for the map's box and
`_paint_landcover` in `generator/renderer.py` paints one ground **colour** per
class under OSM. Nothing downstream knows the class: a WorldCover forest is dark
grass with no trees, shrubland and grassland are the same medium grass, and
cropland is plain light grass. The vegetation passes (`_paint_wild_growth`,
`_paint_groves`) then scatter random growth over that grass as if it were
unmapped.

Separately, mapped OSM `farmland` is plain light grass, although the stock
WorldEd `Rules.txt` already has furrowed-dirt ground and corn tiles that
KnoxMap never uses.

## Goals

1. Plant vegetation that fits each WorldCover class, on ground OSM left blank.
2. Draw farm fields (furrows, corn, hedgerows) on WorldCover cropland **and**
   OSM farmland.
3. Put scattered open-water pools in wetland.
4. Install rasterio with Setup, so the layer can run on a normal install.
5. A before/after comparison on a rural area and a town edge.

## Non-goals (unchanged from upstream)

- The layer stays **on by default** (`landcover = "worldcover"`).
- The cache stays in `cache/datasets/worldcover/`.
- No download during generation and no UI button: tiles are fetched with
  `POST /api/datasets/refresh`. Until a follow-up adds a trigger, a user sees
  WorldCover only after that route has been called for the area.
- The `"osm"` option still does not disable the layer (`off_values` in
  `knoxdata/worldcover.py`). Known, out of scope.
- No new WorldEd rules patch: every tile used here already has a rule in the
  stock `Rules.txt`.

## Design

### 1. Which tiles belong to WorldCover — the OSM mask

`render()` draws an `L`-mode **claimed mask** alongside the OSM ground paint:
every ground polygon and stroke painted into `landscape` is also drawn into the
mask with 255. A tile is WorldCover's to plant only where

- the class grid has a non-zero class, and
- the claimed mask is 0.

Comparing the ground image before and after OSM is not enough: OSM grass over
WorldCover grassland is the same colour and would look unclaimed.

The class grid is the one `landcover_for(width, height)` already returns.
`render()` keeps it (today it is painted and dropped) and passes grid and mask
to the vegetation step. With the layer off, out of coverage or uncached, the
grid is `None` and everything below is skipped except OSM fields and OSM
wetland pools.

### 2. Class planting — `generator/rendering/landcover_veg.py`

New module, one entry point:

```python
def plant_landcover(veg, landscape, grid, claimed, proj, *,
                    tree_density=1.0, forest_density=1.0, seed=0) -> dict
```

It returns counts per class for the log. Each class works only on its own
unclaimed tiles:

| WorldCover class | Planting |
|---|---|
| 10 Tree cover | Returned as a boolean mask, OR-ed into the woodland mask `_paint_woodland` already builds, so it gets the dense core, thinned edge band, big trees and Forest density like mapped forest. |
| 20 Shrubland | Clumped scatter from a coarse noise field: mostly `BUSHES`, some `TREE_SMALL`, a little `SPARSE_TREES`. No grown trees. |
| 30 Grassland | `SHORT_GRASS` tufts and the odd `BUSHES`. No woods. |
| 40 Cropland | Fields (section 3). |
| 90 Herbaceous wetland, 95 Mangroves | `DENSE_BUSHES_GRASS` (ground forced to `DARK_GRASS`, which that rule needs), occasional `SPARSE_TREES`, and pools (section 4). |
| 50 Built-up | Nothing new; `_paint_gardens` handles yards. |
| 100 Moss and lichen | Rock field (section 5): dirt with patches of dark grass, walkable rocks in clumps over about 30% of tiles, blocking boulders on about 3%, the odd low bush. No trees. |
| 60 Bare / sparse | The same rock field, lighter: dirt, walkable rocks on about 10% of tiles, boulders on about 1%. |
| 70 Snow | Nothing. |
| 80 Water | Nothing (ground is already `WATER`). |

Tree density scales the shrub, grass and wetland chances. The random
generator is seeded from the map seed, so a rebuild gives the same map.

**Wild growth and groves.** `_paint_wild_growth` and `_paint_groves` take an
extra `exclude` mask and skip any tile WorldCover classified, so real data
replaces the random guesses there. Where there is no class (layer off, outside
coverage, class 0) they run exactly as today.

### 3. Fields — `generator/rendering/fields.py`

Applies to OSM polygons tagged `landuse=farmland` and to unclaimed WorldCover
cropland. `classify` also files `farmyard` and `allotments` under `farmland`;
those are checked by tag and keep today's look.

- **Plots.** Each OSM farmland polygon is one field. A field, or a connected
  area of WorldCover cropland, wider than `FIELD_MAX_M` (150 m) is cut into
  plots on a grid of 60–150 m cells, rotated to the polygon's long axis
  (minimum rotated rectangle; WorldCover areas use the map axes).
- **Furrows.** Each plot gets ground of "Horizontal Dirt" (`120,110,95`) or
  "Vertical Dirt" (`120,100,75`), picked from the plot's long axis so rows run
  along it. The tiles are axis-aligned, so a rotated plot uses whichever axis
  is nearer.
- **Crop.** Per plot: about 50% corn (vegetation "Farm Corn 1 (dead)"
  `255,128,0` or "Farm Corn 2 (dead)" `220,100,0`, one kind per plot), about
  35% bare furrows, about 15% fallow (stays `LIGHT_GRASS` with `SHORT_GRASS`
  tufts).
- **Edges.** Each plot border gets a 1-tile `BUSHES` hedgerow strip with about
  40% probability, and furrows stop one tile short of every border so plots read
  as separate.
- **Clearance.** Fields are painted after OSM ground and before
  `_clear_building_vegetation` and `_clear_road_vegetation`, so roads,
  paths, buildings and anything OSM paints later stay intact.

New colours in `generator/pz_colors.py`, added to the colour sets:
`DIRT_ROWS_H`, `DIRT_ROWS_V` (landscape) and `CORN_1`, `CORN_2` (vegetation).

**Light-grass dependencies.** Some code reads `LIGHT_GRASS` as "farmland"
(wild growth stays off it; grass colour sets; road verges; the climate tint).
Each use found while implementing is checked against the new furrow colours,
and the furrow colours are added wherever farmland must be treated the same.

### 4. Wetland pools

Inside WorldCover wetland and mangroves, and OSM wetland polygons tagged
`wetland=marsh|swamp|bog|reedbed` or with no `wetland` tag (not `wet_meadow`):

- A smooth noise field (coarse grid, upsampled, like `_paint_groves`) is
  thresholded so pools cover about `POOL_SHARE` = 10% of the wetland, as
  irregular blobs about 3–15 tiles across. Blobs larger than `POOL_MAX_TILES`
  are dropped, so a big wetland gets many pools, not one lake.
- No pool within `POOL_CLEAR_TILES` = 2 tiles of a road, path, building or
  wetland edge.
- Pool tiles become landscape `WATER` with no vegetation. A 1-tile ring of
  `DENSE_BUSHES_GRASS` on dark grass forms the bank.

Water in Project Zomboid is impassable on foot. The share is a cap, and pools
come out separate, so a marsh is land broken by water, not a lake.

### 5. Rock fields

Moss and lichen is tundra or bare upland: low ground cover broken by stone.
It uses the stock WorldEd boulder rules, which are current (not `obsolete`)
and whose `boulders` sheet ships in the Build 42 texture packs:

| Rule | Vegetation colour | Tiles |
|---|---|---|
| Boulders (walkable) | `100,120,100` | `boulders2`: low rocks you can walk over |
| Boulders | `140,160,140` | `boulders1`: large and medium boulders that block movement |

New colours `ROCKS_WALKABLE` and `BOULDERS` in `generator/pz_colors.py`. The
pebbly rock ground tiles (`floors_exterior_natural_01_8`–`10`) have rules
marked `obsolete`, so they are not used. Asphalt is not used either: every
asphalt colour is read as road and would get kerbs, cracks and street lamps.

- A smooth noise field (like the pools) clumps the rocks into rock fields
  and gaps. The rock share is reached by thresholding it.
- The ground is `DIRT`. For moss and lichen, noise patches of `DARK_GRASS`
  (about 30%) stand in for the moss.
- Blocking boulders stay `ROCK_CLEAR_TILES` = 2 tiles clear of roads, paths
  and buildings, so they never close a route.
- Tree density does not scale rocks.

### 6. Dependency

`rasterio` is pinned in `requirements.txt` at the newest release at least two
weeks old (1.5.x). Setup on all platforms installs `requirements.txt`, so
nothing else changes. The `available()` gate stays, for installs made before
this change.

### 7. Data flow in `render()`

1. Ground starts `DARK_GRASS`. If `landcover_for` is given, the class grid is
   computed once, painted with `_paint_landcover` as now, and **kept**.
2. OSM ground paint draws into `landscape` and into `claimed`.
3. Fields (OSM farmland and WorldCover cropland), wetland pools and rock fields paint the
   ground.
4. Vegetation: `_paint_vegetation` (woodland mask OR WorldCover tree cover),
   parks, gardens, `plant_landcover`, then wild growth and groves with
   `exclude`.
5. Big trees, building and road clearing, road details and street furniture,
   as today.

## Error handling

The layer is optional and must never fail a map. Any exception in
`plant_landcover` is logged and skipped, and the map is built as if the grid
were `None`. Fields and pools on OSM data run whether or not the layer works.

## Testing

Unit tests (`tests/test_landcover_veg.py`, `tests/test_fields.py`):

- On a synthetic grid, each class gets only its expected vegetation colours.
- A tile inside the claimed mask gets no WorldCover vegetation.
- Tree-cover tiles reach the woodland pass (trees present, edge thinned).
- Wild growth and groves skip classified tiles and still run without a grid.
- A 400 × 100 m OSM field is split into several plots whose furrows run along
  the long axis. A small field stays one plot.
- Corn, bare and fallow shares are roughly right over many plots (seeded).
- Pools cover about 10%, no pool sits within 2 tiles of a road, and
  `wet_meadow` gets none.
- Moss and lichen gets about 30% walkable rocks and bare ground about 10%,
  and no blocking boulder sits within 2 tiles of a road.
- The same seed gives an identical output.

**Comparison.** Two areas, each rendered with `landcover = "off"` and
`"worldcover"`, previews side by side:

- rural: farmland with woods and a wetland (a US Midwest county area);
- town edge: a small town fading into fields and scrub.

Saved under `docs/images/worldcover/` and shown in the PR description.

## Files

| File | Change |
|---|---|
| `generator/rendering/landcover_veg.py` | new: class planting |
| `generator/rendering/fields.py` | new: plots, furrows, crops, hedgerows, wetland pools, rock fields |
| `generator/renderer.py` | keep grid, claimed mask, call order |
| `generator/rendering/vegetation.py` | `exclude` for wild growth and groves; woodland mask accepts extra mask |
| `generator/pz_colors.py` | 6 colours and their sets |
| `requirements.txt` | rasterio pin |
| `docs/DATASETS.md`, `CHANGELOG.md` | describe the new behaviour |
| `tests/test_landcover_veg.py`, `tests/test_fields.py` | new |

## As built — deviations from this design

- **OSM mask:** WorldCover ground is painted in per-class marker colours
  (`landcover.MARKER`) while OSM paints; tiles still in a marker colour are
  WorldCover's. This replaced drawing a second mask at every OSM paint call.
  OSM forest and scrub polygons paint no ground, so they are claimed
  explicitly.
- **Seeds:** fixed seed constants per pass, as every existing pass uses. The
  renderer has no map seed. Rebuilds are still identical.
- **Pool size cap:** `POOL_MAX_TILES` was dropped. Pools come from a
  small-scale noise field (cell 10 m) cut at the top 10%, which gives separate
  blobs without a connected-component pass (no scipy).
- **Relief:** with WorldCover on, 3DEP relief shades only WorldCover-owned
  ground, after OSM, which is what it shaded before.
- **CHANGELOG:** left for the release commit, as upstream does.
