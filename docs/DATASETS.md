# Optional data layers

Beyond OpenStreetMap, KnoxMap can fold in public datasets to fill ground OSM
left blank, identify real hospitals, add relief, and give a map regional
character. Every layer is optional, independently switchable, and never able
to lose a map: if it cannot run, it logs one line and the build proceeds as
before. **OSM and hand-drawn data always win.**

The code lives in `knoxdata/`. Each layer implements `DatasetSource` in
`knoxdata/__init__.py`:

| method | does |
|---|---|
| `available(bbox)` | can it run here (dependency present, area in coverage)? |
| `why_unavailable()` | one sentence for the log when it cannot |
| `fetch(bbox, cache_dir)` | download to cache (streamed, honest UA, retries) |
| `build_layer(map_ctx)` | read the cache into a `Layer` |
| `apply(map_ctx, layer)` | fold it into the map |

`knoxdata.SOURCES`/`sources()` lists them; `knoxdata.run_layers()` applies the
enabled ones in order and returns a report. `knoxdata.status()` tells Setup
what is on and what is missing.

## Fetching vs applying

Downloads happen in explicit `knoxdata.refresh(settings, bbox)`, which fills
`cache/datasets/`. The generate path calls `run_layers(..., require_cache=True)`,
so it applies only data already on disk and never waits on — or fails because
of — a network call. A fresh install therefore generates exactly today's map;
run `refresh` once (from the app or a script) to turn the layers on for that
area. This is what keeps the layers "offline-safe defaults".

## Order of application

`elevation_3dep → worldcover → natural_earth → hifld_hospitals → climate_normals`

Terrain first, then what stands on it. Conflicts resolve for OSM-derived and
hand-authored data every time.

## The layers

### `worldcover` — ESA WorldCover 10 m land cover
- **Source:** ESA WorldCover 2020 v100 / 2021 v200, Cloud-Optimized GeoTIFFs on
  the `esa-worldcover` AWS Open Data bucket. 3°×3° tiles.
- **License:** CC-BY 4.0. Attribution: *Contains modified Copernicus/ESA
  WorldCover data 2021*.
- **Coverage:** global. **Needs:** `rasterio`, `numpy`.
- **Does:** fills ground/vegetation where OSM has no landuse/natural tag;
  majority class per tile + 3×3 filter; class→behaviour table in
  `knoxdata/data/worldcover_classes.json`; class fractions feed the
  Rural/Town/Suburb/City preset suggestion.
- **What grows, per class** (only on ground OSM left blank; OSM wins, and
  OSM forest/scrub polygons count as claimed though they paint no ground):

  | Class | On the map |
  |---|---|
  | 10 Tree cover | a wood, through the same pass as mapped forest (edge, big trees, Forest density) |
  | 20 Shrubland | clumped bushes and young trees, no grown trees |
  | 30 Grassland | grass tufts and the odd bush |
  | 40 Cropland | fields: 60–150 m plots of furrows, about half in corn, some fallow, some hedged |
  | 50 Built-up | nothing new; gardens are planted as anywhere |
  | 60 Bare / sparse | dirt with low rocks in clumps (~10%) and a few boulders |
  | 70 Snow and ice | sand-coloured ground (no snow tile) |
  | 80 Water | water |
  | 90 Wetland, 95 Mangroves | dense marsh, the odd stunted tree, open-water pools on ~10% |
  | 100 Moss and lichen | dirt and moss patches, low rocks in clumps (~30%), boulders (~3%), no trees |

  Where WorldCover has a class, the random wild growth and woods KnoxMap
  scatters on unmapped grass stay off it. No building stands in a field or a
  lake: WorldCover cropland and water within 6 m of one becomes lawn, and OSM
  farmland is kept off it the same way. A building in woods - OSM's or
  WorldCover's - gets a clearing 10-30 m out from its walls with a wobbly,
  thinning edge, and a house (not a shed) a gently bent tarmac drive to the
  nearest road up to 400 m away, never through water or another building
  (`generator/rendering/homesteads.py`). Mapped OSM `landuse=farmland` gets
  the same fields, and OSM marsh/swamp/bog/reedbed wetland the same pools.
  The renderer paints this ground in marker colours until OSM has painted
  (`generator/rendering/landcover.py`); fields, pools and rocks are in
  `generator/rendering/fields.py`, the planting in
  `generator/rendering/landcover_veg.py`. All tiles come from rules already in
  stock WorldEd `Rules.txt`.
  Before/after previews (layer off, then on) of farm country, a marsh, a
  town edge and tundra: `docs/images/worldcover/`.
- **Setting:** `landcover=worldcover|osm|off` (default `worldcover`); `osm` and `off` both leave WorldCover out, and the ground OSM leaves blank is grass with KnoxMap's scattered woods.
- **Refresh cache:** delete `cache/datasets/worldcover/`.

### `elevation_3dep` — USGS 3DEP relief (US)
- **Source:** USGS The National Map 1/3 arc-second DEM; data public domain.
  Workflow reference: OpenTopography `OT_3DEP_Workflows` (GPL-3; **no code
  copied** — only the public S3/The National Map endpoints are used).
- **License:** public domain. **Coverage:** CONUS, AK, HI, PR, VI.
- **Needs:** `rasterio`, `numpy`.
- **Does:** one elevation sample per tile, normalised and clamped to
  `max_relief`. Project Zomboid's outdoor ground is flat by format, so relief
  is **compressed into the ground**: a north-west hillshade plus rock/snow
  bands painted under the OSM features (flat ground is left alone). True
  z-level relief (building pads, road beds, walkable slope) waits for a
  compiler that carries per-tile ground height.
- **Setting:** `elevation=3dep|flat`, `max_relief` (0..12).
- **Refresh cache:** delete `cache/datasets/3dep/`.

### `natural_earth` — Natural Earth 1:110m context
- **Source:** `martynafford/natural-earth-geojson`, 1:110m themes.
- **License:** CC0 1.0 (public domain — bundling permitted).
- **Coverage:** global. **Needs:** `shapely` only.
- **Does:** country/region at the map centre (for regional defaults and
  `region_override`), populated-place labels for the paper map, and a
  coastline fallback where Overpass truncated water at the bbox edge.
- **Setting:** `ne_context=1|0`, `region_override=auto|<ISO-2>`.
- **Refresh cache:** delete `cache/datasets/natural_earth/` (30-day TTL).

### `hifld_hospitals` — HIFLD Hospitals (US)
- **Source:** HIFLD Open Data hospitals (US Government). Endpoint overridable
  with `KNOXMAP_HIFLD_URL`.
- **License:** public domain. **Coverage:** US only.
- **Does:** matches each facility to the nearest OSM building within 150 m —
  name match > nearest tagged hospital > nearest candidate building, best tier
  only — and records NAME, BEDS, TYPE, STATUS, HELIPAD for interior and loot.
- **Setting:** `hospitals=hifld|osm|off`, `hospitals_place_missing=0|1`.
- **Cache:** one national file, 7-day TTL, at `cache/datasets/hifld/`.

### `climate_normals` — NOAA U.S. Climate Normals (US)
- **Source:** NOAA 1991–2020 monthly normals (GeoParquet).
- **License:** public domain. **Coverage:** US only.
- **Needs:** `pyarrow`.
- **Does:** nearest station (IDW over the three nearest) → January/July mean,
  precipitation, aridity class, stored on the map for the info panel; tint only
  (`knoxdata/data/climate_palette.json`). `winter_look=auto|on|off`.
- **Setting:** `climate_flavor=1|0`.
- **Cache:** `cache/datasets/noaa/`.

## Dependencies

Heavy dependencies are **lazily imported**, exactly like DuckDB for Overture:
`rasterio` (WorldCover, 3DEP), `pyarrow` (climate). `shapely`, `numpy` and
`pyproj` already ship with KnoxMap. Nothing is imported at `knoxdata` import
time, so the package loads on a bare install and each layer reports the one
command that would enable it.

```bash
pip install rasterio pyarrow
```

## CLI

Every knob is a `--set`:

```bash
python -m knoxbuild output/mytown --set landcover=osm --set elevation=flat \
    --set region_override=gb --set hospitals=off
```

## Tests

`tests/test_knoxdata.py` runs offline with mocked fetchers: registry,
disable/skip/degrade/failure paths, WorldCover tile naming, Natural Earth
point-in-polygon, HIFLD matching, and settings parsing.
