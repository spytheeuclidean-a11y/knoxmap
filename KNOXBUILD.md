# knoxbuild — furnished buildings for Knoxify maps

> **Just want the map?** Double-click `KnoxMap.bat`. It wraps everything below
> in one window: search a place, build terrain and buildings, compile them with
> the patched WorldEd, and install the result into `~/Zomboid/mods`. The rest of this file is what it does underneath, and how to
> drive each piece by hand.

Knoxify stops at building *footprints*: OSM has outlines but no interiors, so it
paints each building as a dirt placeholder and leaves you to drop `.tbx` lots on
top by hand. `knoxbuild` fills that gap — it generates a real, furnished PZ
building for every footprint and writes a WorldEd project with all of them
already placed.

```bash
# 1. make a map with Knoxify (web UI, or the API directly)
.venv/Scripts/python.exe app.py          # then draw a box and Generate

# 2. fill in the buildings
.venv/Scripts/python.exe -m knoxbuild output/<mapname>

# 3. optional: check the result before opening WorldEd
.venv/Scripts/python.exe tools/validate_tbx.py output/<mapname>/buildings
.venv/Scripts/python.exe tools/preview_buildings.py output/<mapname>
```

Step 2 writes:

| file | what it is |
|---|---|
| `buildings/<map>_NNNN.tbx` | one BuildingEd building per footprint |
| `<map>.pzw` | WorldEd project with every building placed on the cell grid |
| `<map>_placements.csv` | tile/cell coordinates, room and furniture counts |

## What it generates

Each footprint is reprojected with Knoxify's own `Projector`, so buildings line
up with the landscape BMP exactly. The footprint becomes a rectangle (see
*Footprint fitting* below), which is split BSP-style into rooms of roughly
`TARGET_ROOM_AREA` (56 tiles), and each room is:

- **named** from the tools' own `RoomNames.txt` (`kitchen`, `bedroom`,
  `bathroom`, `livingroom`, `dining`, `office`, `storage`, `hall`) and coloured
  with that file's official colour — a room with an unrecognised name never
  spawns loot;
- **floored** with a tile appropriate to its kind, and given a ceiling and
  interior wall trim;
- **furnished** along the walls, scaled to floor area (~1 piece per 7 tiles,
  capped at 14);
- **connected** — every room is reachable, verified by walking the door graph;
- **windowed** on exterior walls, with one exterior door and a flat roof.

Buildings tagged `retail`, `warehouse`, `school`, `hospital` and similar get a
commercial room mix (storage/office) instead of a domestic one.

## Building variety

Every building used to share one exterior wall, one interior wall and one floor
palette, so a whole town came out identical.

**Houses** draw from ten material styles — clapboard, brick, painted,
stucco, panel, timber, logs, trailer, render, plaster — chosen by *neighbourhood block*
(`NEIGHBOURHOOD_TILES`, 110 tiles) rather than per building. Houses on the same
street therefore look like they went up together, while the next block over
differs, and `STYLE_ODDITY` (18%) lets the occasional house break ranks. The
block hash is deterministic, so regenerating the same area gives the same town.

**Special buildings** get their own materials *and* their own room plan, driven
by OSM tags (`amenity`, `shop`, `healthcare`, `leisure`, `tourism`, `office`,
`building`) and, failing those, keywords in the name:

| kind | materials | rooms |
|---|---|---|
| school | commercial brick + school interior | classrooms, library, gym, lobby |
| church | church walls inside and out | church hall, lobby, office |
| restaurant | diner walls + diner floor | restaurant, kitchen, bar |
| shop | gas2go walls + shop floor | storage, office, lobby |
| industrial | industry walls + concrete | warehouses, garage, office |
| medical | commercial brick + pale tile | clinic, medical, lobby |
| civic / barn | commercial / barn walls | offices / warehouse, stable |

Room names all come from `RoomNames.txt`, so the loot tables recognise them —
a classroom is stocked like a classroom.

**Reading the neighbourhood** (`knoxbuild/context.py`). Most buildings in OSM
carry nothing but `building=yes`, so each untagged one borrows what its
surroundings make plain. The numbers below were measured on six test maps
(central Paris, Kadıköy, a Tokyo neighbourhood, Levittown, a French village
and a Gebze industrial estate):

- *Density picks the materials.* Building coverage of the ~120 m around each
  building decides which house styles are allowed. Log cabins and trailers
  only go on isolated buildings (coverage under 6%). Clapboard and timber stay
  out of dense quarters (over 28%). Before this, Kadıköy had 36 log houses.
- *Tagged heights spread to their neighbours.* An untagged building takes the
  median storey count of the tagged buildings within 120 m, plus or minus
  one, once at least four of them agree. A large untagged building among
  3-storey-plus blocks becomes flats. Kadıköy's single-storey buildings fell
  from 168 to 117, and its blocks of flats rose from 295 to 475.
- *Outbuildings are sheds.* `shed`, `garage`, `hut`, `service` and similar
  tags, and any untagged building of 30 m² or less, get one storage or
  garage room, one storey and no residents. The village gained 55 sheds
  instead of 55 one-room "living rooms".
- *Things that are not buildings are skipped.* `roof`, `carport`, `ruins`,
  tanks and silos would otherwise stand as solid boxes where the real place is
  open.

**Lifts.** Buildings of five storeys or more get a 2x2 lift shaft against the
long side of the stair hall, on the same squares on every floor. Its doors
are the base game's own elevator tiles (`fixtures_escalators_01_48`-`51`), set
into the wall facing the landing through BuildingEd's Walls furniture layer.
The shaft is a sealed `elevator` room: no doorway, no switch, no furniture.
That is exactly what the [Elevators](https://steamcommunity.com/sharedfiles/filedetails/?id=3780306632)
mod looks for - door tiles repeated at one square through a column of floors,
with a small closed box behind them - so with it enabled the lifts run: call
one from the doors, pick a floor, ride. Without it they are doors that do not
open. `tools/audit_layouts.py` checks every tall building has one, aligned on
every floor, with its doors between shaft and landing. In Midtown Manhattan at
up to 30 storeys, 513 of 528 tall buildings got a lift; the rest have
footprints with no room for a shaft beside the stairs.

The smallest building kept is now 3 tiles across, down from 5. That had been
throwing away 28% of Tokyo's buildings: real narrow houses and kiosks.

The same density measure paints the ground (`_pave_dense_ground` in
`generator/renderer.py`). Unmapped ground in a built-up quarter becomes
concrete instead of wild grass; central Paris used to render as 77% meadow.
Mapped parks and gardens keep their grass. Pavements mapped as
`highway=footway` are also paved now, where they used to be dirt strips
running along every street.

This needed Knoxify's GeoJSON export widened: it previously kept only the
`building` tag, which cannot tell a school from a shed.

## Regional architecture (`knoxbuild/regional.py`)

The material styles, storey counts and room plans above describe the game's
own Kentucky. Most of the world does not build like Kentucky, and the
starkest case is China: a Chinese city is masonry and render with flat
roofs and a machine on every one of them, self-built houses of three and
four storeys on narrow footprints, and walk-up blocks five to eight storeys
tall - not weatherboard bungalows under pitched roofs with shutters.

**Detection is by script, not by borders.** The build reads up to 800 of the
map's own building names: Han ideographs alone mean Chinese-built (which
covers Hong Kong, Taiwan and Singapore as naturally as Guangzhou), kana in
the name marks it Japanese and hangul Korean whatever the Han in it, and
anything else is built the default way. A town is only read as a region when
at least six names are present and 30% of them agree, so a main street with
three Chinese restaurants on it stays what it is. A map that names nothing -
rural rectangles, in practice - falls back to its bounding box, with Korea
and Japan tested before China's longitudes. The `arch_style` setting forces
the question: `auto` (the default), `cn`, or `off` for the previous
behaviour everywhere.

**A regional style is a shipped style, rearranged.** The Chinese house pool
is the catalog's own render, painted, stucco, panel and brick entries with
`peaked` set to false and the shutters taken off - every wall, window, door,
trim and grime tile is one the catalog already shipped, so a regional build
cannot reference a tile the game has not got. The rooftop machinery that
flat roofs already carry (the AC units, vents and hatch from
`knoxbuild/tbx.py`) lands on them as on any flat roof. The wood-and-siding
styles - clapboard, logs, timber, trailer, the coloured sidings - are simply
not in the pool. Special buildings keep their own styles; apartment, shop,
civic, school and industrial styles are flat-roofed to begin with, and a
church keeps its pitched roof in China as anywhere, because a temple is the
one thing on a Chinese street that has one.

**Dated buildings are exempt.** A building the mapper dated - `start_date`,
`historic`, `heritage`, an architecture tag - and that predates 1945 keeps
its pitched roof and era materials rather than the regional pool. The
`BuildingProfile` now records whether its era came from the mapper or from
the age dice, so a lucky young house does not pass itself off as heritage;
only the genuinely dated ones keep the exemption.

**Storeys, when OSM says nothing, come from the kind and the footprint
together** - the approach Arnis (github.com/louis-e/arnis) takes for
Minecraft, re-based to one storey per level. The tables in
`knoxbuild/regional.py` map each kind and floor-area band (in real square
metres, so the answer holds at any map scale) to a weighted pool of storey
counts: a 90 m² footprint stays at one or two storeys whether it is in
Muldraugh or Chengdu, and a 2,500 m² one does not come out a bungalow. The
Chinese tables override them where the housing genuinely differs - the
self-built house runs 2-4 storeys (37 of 62 untagged houses on the renamed
selftest town came out at three or more), and the walk-up blocks run 5-8.
A mapper's own `building:levels` or `height` still beats every table, the
neighbourhood median still beats it for the kinds that follow their
neighbours, and `max_levels` still caps the lot.

## Buildings built by hand, and passed around

The generator lays out every building from scratch, which is what makes a map
of ten thousand of them possible and is also its limit: it will never produce
the one house somebody drew themselves. A **preset** is that building, saved
whole and stamped onto a footprint instead of a generated one
(`knoxbuild/presets.py`). It is a `.tbx` — the same file the generator writes
and BuildingEd reads — used exactly as saved: nothing is converted, stretched
or re-rendered. A footprint takes the biggest preset that fits, chosen from its
own seed so a rebuild puts the same building back; a plot nothing fits goes to
the generator.

They come from two places and go to three:

| | |
|---|---|
| `presets/buildings/` | Somebody's own, written by the window. Not in the repository and never touched by an update. |
| `presets/library/` | Buildings people sent in, shipped with every release. Read-only: an update replaces the folder. |
| `<name>.knoxbuilding.json` | One building in one file, to send to somebody (`knoxbuild/share.py`). |

A name in both folders is the person's own, so a shipped building can be
opened, changed and saved and the change survives updates. `library.json`
beside the shipped ones records what each stands in for, who built it and when
it was added — kept with the buildings rather than in the user's own manifest,
which is their settings and not ours to write.

A share file arrives from a stranger over a chat program, so `share.read` is
the one door it comes through: it must say it is a KnoxMap building of a
version we read, have a name that is a filename, hold a `.tbx` under the size
cap that `measure` recognises as a building no bigger than a cell, and carry no
XML document type declaration — `buildtiles.parse_tbx` reads these with
ElementTree, which expands entities, and a few nested ones expand into
gigabytes. The drawing beside it is best-effort: one that cannot be read costs
the drawing, not the building.

`python tools/add_shared_building.py <file>` is the other end — it checks a
submission, copies it into `presets/library/` and records it. `--check` looks
without adding, `--list` shows what is there, `--remove` takes one out.

## Footprint fitting

A plain bounding box is wrong for anything not aligned to north: a 10x20
building turned 45 degrees boxes out to about 21x21. On a diagonal street grid
this is not a rounding error — measured over 207 Lexington footprints, the
bounding box inflated building area by a **median of 2.09x**, with 205 of 207
oversized by more than 25%.

So `_footprint_rect` takes the polygon's *minimum rotated rectangle* to recover
the true side lengths, then places an axis-aligned building of those dimensions
centred on the footprint, snapping orientation to whichever axis the long side
is nearer. PZ buildings are axis-aligned grids and cannot be rotated, so the
angle itself is unavoidably lost — but the size and proportions survive.

## Laying a town out for the game (`true_map = 0`)

An accurate model of a street is not a street worth playing. Measured on a
test town at 2 m a tile, OSM's own density gives houses of about 30 tiles —
**one room each**, walls included. Knox County's houses are four to six rooms
with a yard round them, and it is the yard as much as the rooms that makes the
game's towns readable: somewhere to be seen crossing, somewhere to run.

With `true_map` off, `knoxbuild/procedural.py` answers two questions for each
footprint before `footprint.place` sees it. Roads, water, woodland, terrain
and the zone detector are untouched — only the housing changes.

**Thinning.** Housing is taken largest first and one is dropped when something
already kept stands closer than `GAP` (1.55) times the distance at which the
two would touch, measuring the kept building at its *grown* width. It is a
spacing rule, not a coin toss, so it degrades properly at both ends: a terrace
at one house-width loses every other house, a farmhouse in a field loses
nothing, and the larger of a crowded pair is the one that survives. No random
stream is involved, so a seed still reproduces a town exactly.

**Growing.** What survives is scaled about its own centroid toward
`HOUSE_TILES` (90) or, for a landmark, `LANDMARK_TILES[kind]` — 300 for a
police station, 600 for a school. Three clamps apply: `GROW_MAX_*` linear
(1.9 houses, 2.6 landmarks), `max_size` so the placer does not reject the
result as `"large"`, and `_clamped`, which stops a building growing into one
already grown. Without the last, two barracks a few tiles apart both asked for
400 tiles and the second lost its ground to the first, so an army base with
two buildings came out with one.

Growing is a request, not a promise: `place()` still cuts a footprint back to
the largest part of itself whose lot rectangle is clear, so nothing here can
produce overlapping lots (`check_lots_apart` runs against a procedural town
too).

**Landmarks are never thinned** and claim their ground before any housing. A
landmark is anything `classify_building` names, anything `is_notable` flags, or
anything with a shop, surgery or office mapped inside it. It is also anything
the *land around it* identifies: `areas.kind_for` is consulted in the pre-pass
exactly as the placement loop consults it later, because without that the huts
on an army base and the wings of a hospital read as untagged houses and get
thinned away with them. Sheds are excluded by the same `SHED_MAX_M2` rule the
placement loop uses, so a garage on an industrial estate stays a garage rather
than growing into a works.

Net effect on the test town at 2 m a tile: 140 houses of 1 room become 95 of
4; the police station goes from 42 tiles to 221, the school from 144 to 1122.

### The guaranteed rifle

`Base.AssaultRifle` — the M16 — spawns from army and police loot and almost
nowhere else. A real town has no checkpoints and usually no gun shop, so a
generated map can contain no container anywhere that could ever roll one.

`knoxbuild/guns.py` picks a host after the placements are decided, in order:
an army building, the police station, a gun shop (a unit whose `uses` include
`("gunstore", "storage")`), then a survivor house — of the largest quarter of
the houses, the one furthest from the centre of the built area. The choice,
in **world** tile coordinates (`origin() * CELL_SIZE + tile`), goes to
`<map>_guncache.json`.

`make_map_mod.write_gun_cache` ships two Lua files under
`common/media/lua/server/KnoxMap/`: the shared handler `KnoxMapGunCache.lua`,
and `KnoxMapGunCache_<mod_id>.lua` registering this map's box. Either may load
first — both do `KnoxMapGunCache = KnoxMapGunCache or { boxes = {} }` — and the
handler guards itself with `wired` so several maps carrying it register one
handler between them.

The handler hangs off `OnFillContainer`, takes whichever argument answers
`getSourceGrid` rather than trusting the argument order across game versions,
skips the floor and body containers and anything that cannot carry 12 units,
and records the fill in `ModData` so it happens once per map per save. It
cannot be baked into the `.tbx`: a `.tbx` holds walls, floors and furniture and
no items, and container contents are rolled by the game on first load.

## Where the tile names come from

Nothing here is invented. `knoxbuild/catalog.py` started as the output of
`tools/make_catalog.py`, which reads the `config` folder of a PZ_Mapping_Tools
install — the same `BuildingTemplates.txt`, `BuildingFurniture.txt` and
`RoomNames.txt` that BuildingEd itself loads. The committed file has since been
extended by hand (the interior wall styles in `GAME_WALL_STYLES`, the
escalators and more) and no longer matches what the generator writes, so edit
it directly. Running the generator over it would drop those sections. To see
what the config holds, write the output somewhere else and compare:

```bash
python tools/make_catalog.py ../PZMappingTools/config /tmp/catalog_gen.py
```

Entries are selected by tile **name**, and a missing anchor is a hard error. An
earlier version indexed into the file numerically; run against the Build 42
config those indices pointed at entirely different entries, and it had picked
`walls_interior_house_01_020` and two floor tiles that Build 42 does not
contain. Never reintroduce positional lookup.

Picking an anchor by name proves nothing about what it *looks* like, so
`tools/preview_catalog.py` crops every chosen tile out of the extracted sheets
into a labelled contact sheet:

```bash
python tools/preview_catalog.py ../PZMappingTools/Tiles/2x \
    ../PZMappingTools/config/Tilesets.txt catalog.png
```

That check earned its keep immediately - four anchors were wrong: an armchair
filed as a plain chair, an ottoman as an armchair, a **cardboard box as a
wardrobe**, and a **second toilet as a bath**. Every bedroom had a packing crate
in it and every bathroom two toilets. Re-render this sheet after touching any
anchor.

Only enum-to-tile pairs are copied. Roof entries also carry
`offset = SlopePt5S 1 1`, a property rather than a tile; passing it through made
BuildingEd reject every building with `Unknown roof_slopes enum 'offset'`. A
real tile value is a single token, so values containing whitespace are dropped.

The `.tbx` and `.pzw` schemas were read off `BuildingWriter`/`BuildingReader`
and `WorldWriter` in the mapping-tools source. Things worth knowing:

- tile entries are **1-based**, and `0` means "none"; `FurnitureTiles` is
  **0-based**;
- walls live on the north and west *edges* of tiles, so a building `w` x `h`
  has valid object coordinates `0..w` and `0..h` — the south wall is at
  `y == h`. The reader confirms it: only `x >= width + 1` is rejected;
- the reader accepts versions 1..7 and caps dimensions at 300. We write
  version 4, the first that carries a per-room `Ceiling`; older versions load
  but get ceilings silently back-filled.

## Verification status

Both formats have been loaded by the real editors (PZ_Mapping_Tools build
`42.20B260828`, matching game 42.20.4).

- **`.tbx` opens in BuildingEd.** Six buildings across the size range were
  opened; each logs `Reading building ...` followed by a constructed
  `BuildingEditor::BuildingDocument`, with no `Could not read building`.
- **Every tile reference resolves to real game artwork.** With the tilesheets
  extracted (see below) BuildingEd reports
  `Building tileset resolution: 27 requested, 27 loaded, 0 unresolved`.
  The `tile_entry` block is identical in every generated building, so this
  covers the shared part of all of them; what varies per file - room grids and
  object coordinates - is what `validate_tbx.py` bounds-checks.
- **`.pzw` opens in PZWorldEd**, which reports the composition it parsed:
  `cells 9, lots 29` for the 29-building map and `cells 6, lots 182` for the
  182-building map — both exactly matching what was generated.
- Every generated `.tbx` also passes `tools/validate_tbx.py`, which replicates
  BuildingReader's rejection paths. 211/211.
- Room connectivity is swept over 608 generated plans: zero unreachable rooms.

## Local changes to Knoxify itself

This clone carries two changes beyond upstream; both are worth re-applying if
you ever re-clone:

1. **`generator/osm.py` sends a `User-Agent`.** Without one every Overpass
   mirror answers `403`, so the tool could not fetch anything at all.
2. **Place search and landmark lookup in the web UI** —
   `generator/places.py`, the `/api/search` and `/api/landmarks` routes, and
   the search box and landmarks panel in the front end.
3. **One-click download.** Upstream wrote a zip at generation time holding the
   three BMPs and the README, and listed eight separate links. The
   `/download/<map>.zip` route instead builds the archive when it is asked for,
   from everything currently in `output/<map>/` — so once `knoxbuild` has run,
   the same button also hands over the `.tbx` buildings, the `.pzw` project and
   the placement CSV. Individual files are still there, folded into a
   disclosure below the button.

Search uses Nominatim: type a name, pick a result, and the map flies there and
drops the selection rectangle for you. A result's own bounding box is used when
it is a reasonable size; searching something huge like a whole city centres a
1.2 km box instead rather than handing back a selection the generator would
refuse. "Only this view" restricts results to the current viewport.

The landmarks panel asks Overpass what named things are inside the current
selection - schools, shops, parks, places of worship - grouped by kind with
counts, and clicking one zooms to it. It is the quickest way to judge whether
an area is worth generating before spending a minute on it.

Nominatim's usage policy allows one request per second, which `places._throttle`
enforces process-wide, and the front end debounces typing by 500 ms.

## Map size

The old 20 km² cap was an Overpass limit wearing a renderer's clothes: one
query that size is about all the API will answer. `osm.fetch_features_tiled`
splits a large request into a grid of sub-queries of `OVERPASS_TILE_KM2`
(12 km²) each, pausing between them, and de-duplicates on `(kind, osm_id)` —
`out geom` returns a way's complete geometry from every tile it touches, so
features that straddle a boundary survive whole.

Current rails, all in `web/checks.py`:

| | | |
|---|---|---|
| `MAX_AREA_KM2` | 400 | patience, not API limits |
| `MAX_TILES_PER_SIDE` | 9000 (30 cells) | memory: landscape + vegetation at 3 bytes a tile is ~490 MB at that size |
| `MAX_METERS_PER_TILE` | 8.0 | coarse enough to fit a region inside the tile cap |
| `MAX_LANDMARK_KM2` | 40 | the landmark query asks for far more tag keys |

Measured on a 62 km² slice of Muncie at 3 m/tile: 9 Overpass queries, 17,282
features, 3300x3000 tiles (11x10 cells), 3,908 footprints, and `knoxbuild` then
produced 2,206 buildings with 45,840 furniture pieces in under three seconds —
all 2,206 valid. That map is left in `output/bigtest2` as a ready example.

Because a big map means minutes of querying, generation reports its stage
through `GET /api/progress?map=<name>` and the page polls it, so you see
"area 4 of 9" rather than a dead spinner. The area panel also predicts the
query count and bitmap size before you commit, warns above 60 km², and blocks
only at the real ceilings.

If you want a map larger than 400 km², raise `MAX_AREA_KM2` and coarsen metres
per tile to stay under the tile cap — the tiling itself has no upper bound, only
your RAM and willingness to wait.

## Getting the tilesheets (tools/extract_tiles.py)

The mapping tools want a "Tiles" tree of tilesheet PNGs and ship only a GUI
extractor. `tools/extract_tiles.py` does the same job headlessly, reading the
game's `.pack` files directly:

```bash
PACKS="<your ProjectZomboid folder>/media/texturepacks"   # Setup.bat does all this for you
TOOLS="../PZMappingTools"
python tools/extract_tiles.py "$PACKS/Tiles2x.pack"       "$TOOLS/config/Tilesets.txt" "$TOOLS/Tiles/2x"
python tools/extract_tiles.py "$PACKS/Tiles2x.floor.pack" "$TOOLS/config/Tilesets.txt" "$TOOLS/Tiles/2x"
```

Both packs are needed: floor and ceiling sheets (`ceilings_01`,
`floors_interior_carpet_01`) live only in `Tiles2x.floor.pack`. Sheets land at
`<Tiles>/2x/<name>.png`, which is exactly where
`TilesetManager::getTilesetFileName` looks.

Each sheet is rebuilt by pasting every `<tileset>_<index>` sub-texture into an
8-column grid at the columns/rows `Tilesets.txt` declares, honouring each
entry's trim offset. Extracting all 543 sheets at once would hold several GB of
RGBA, so a cheap metadata-only first pass records each tileset's last page and
the second pass writes sheets out and frees them as they complete.

## The app (knoxmap.py)

`KnoxMap.bat` launches `knoxmap.py`, which is deliberately thin: it starts the
Flask app on a loopback port and shows it in a native window through pywebview
(Edge WebView2). The window therefore gets the real Leaflet map — rectangle
tool, place search, landmark lookup — instead of a second UI that would drift
from the web one. There is one front end, used two ways.

The page carries the whole pipeline:

1. **Draw or search an area**, then **Generate map** — Overpass query and
   terrain render.
2. **Generate buildings** — `POST /api/buildings`, which calls `knoxbuild`.
3. **Open in WorldEd** — `POST /api/worlded` launches PZWorldEd with the `.pzw`
   already open. It finds `../PZMappingTools/bin/PZWorldEd.exe` by itself; set
   `PZWORLDED` to override.
4. The page then polls `GET /api/lots` every few seconds and enables **Install**
   by itself the moment `lots/*.lotheader` appears — you never have to tell it
   you are done.
5. **Install** — `POST /api/install` calls `make_map_mod.package()` into
   `~/Zomboid/mods/<id>/`.

Steps 3's two menu commands are the only manual part, and the app never blocks
waiting on them. The routes are thin wrappers over the same functions the CLI
uses, so the two cannot drift.

Map names are sanitised and every path is resolved and checked against the
output directory, so `../` in a map name is a 404 rather than a filesystem walk.

## The patched WorldEd (fully automatic compiling)

Stock WorldEd exposes BMP to TMX and Generate Lots only as menu items — every
command-line switch it ships is a developer self-test. `patch_worlded_cli.py`
(in the parent folder) adds a `--generate-map=<project.pzw>` switch that runs
both, so the app compiles without anyone clicking a menu:

```bat
PZWorldEd_cli.exe --generate-map=C:\...\output\mytown\mytown.pzw
```

Build it with `build_worlded.bat` (Qt 5.14.2 msvc2017_64 + VS 2022 Build
Tools); the result is copied to `PZMappingTools\bin\PZWorldEd_cli.exe`, leaving
the stock `PZWorldEd.exe` untouched. `/api/compile` uses it when present and
tells you to use the manual route when it isn't.

Four things had to be right, and each failed loudly before it worked:

1. **`Rules.txt` pointed at tiles Build 42 no longer ships.** It painted forests
   with `vegetation_trees_01_*` and flowers with `vegetation_groundcover_01_*`.
   B42 still *defines* those tiles but ships no artwork — they are in none of
   the 24 texture packs and exist as no loose PNG. `patch_rules_b42_trees.py`
   repoints them at the per-species sheets B42 does ship (`e_redmaple_1` and
   ten more), rotating the species so a forest is not a monoculture. Flowers
   become `f_flowerbed_1`. **This affects the GUI too** — without it, clicking
   the menu fails identically.

   **The index is not a free choice.** A species sheet holds 24 pictures — six
   seasons of four sizes — and the game gives a tile definition to the first
   eight only, which is where `tree = 1..4` lives. That property is what makes
   the tile a tree the game grows, chops and blows about in the wind; past the
   eighth there is a picture and nothing behind it, so it draws and is scenery.
   The first version of this script swapped index for index and the old rules
   asked for 8-11, so until 1.7.7 every tree on a KnoxMap map was scenery.
   Trees go on indices 0-3 now, the size chosen by the rule they come from.

   **Big trees** are the jumbo sheets (`e_redmapleJUMBO_1`, `...JUMBOXL_1`,
   `...JUMBOXXL_1`): one tile each, carrying `tree = 5..8`, with a picture
   several tiles across. Build 42 leans on them — in its own maple forest a
   jumbo XL or XXL comes up about thirty times as often as a plain tree
   (`media/lua/server/WorldGen/biomes/worldgen/maple_forest.lua`), and Knox
   County's cells carry some 1800 of them. The script writes three
   `KnoxMap tree` rules for them, one per size, and the renderer keeps the
   square of clear ground round each that the game's own tree features reserve
   (`media/lua/server/WorldGen/features/tree/maple_jumbo*.lua`): 2x2 for a
   jumbo, 3x3 for an XL, 5x5 for an XXL.
2. **`update-existing` must be false on a first run.** With it on, BMPToTMX
   writes to each cell's existing map path, and a fresh project has none, so it
   silently produces nothing.
3. **Export directories must be absolute and must already exist.** WorldEd
   resolves a relative path against its own working directory, and it does not
   create the folder — you get "Could not open file for writing". `knoxbuild`
   now writes absolute paths and creates `tmx/` and `lots/`.
4. **Generate Lots is asynchronous.** It starts worker threads and returns
   immediately; the block that waited for them is `#if 0`'d out, and the GUI
   simply keeps running while they work. Headless, the process would exit and
   kill the workers mid-write, so the patch holds the Qt event loop open and
   watches the export directory until it goes quiet.

Measured on a 3x3-cell test map: 9 TMX, 48 lot files, `output cells 16,
buildings 29, rooms 444, room objects 195, reported issues 0` — matching what
knoxbuild generated exactly — then a 50-file mod in `~/Zomboid/mods`.

## Getting to a playable map

`knoxbuild` pre-fills the project's `BMPToTMX` and `GenerateLots` settings
(tmx dir, lots dir, the Knoxify zombie-spawn BMP, `assign-maps-to-world` on), so
in PZWorldEd the remaining work is two menu commands:

1. **BMP to TMX**, all cells — converts the landscape BMP into cell TMX maps
   and attaches them to the cells.
2. **Generate Lots**, all cells — compiles everything, buildings included, into
   the `lots/` folder.

Neither has a command-line entry point (WorldEd's `--` options are developer
self-tests), so these two are unavoidable from here.

Knoxify's palette does line up with the tools' terrain rules: of the 18 colours
it paints, 17 are defined in `config/Rules.txt` with the right bitmap and layer.
The only one missing is `VEG_NOTHING` `(0,0,0)`, which means "no vegetation"
anyway. So BMP to TMX needs no rules setup. The colours added since — the road
details and the big trees — do need the rules Setup writes, and the renderer
asks before it paints them: without those rules it leaves the trees as they
were rather than painting a colour that would be dropped with a warning.

Then package the result as a mod:

```bash
python tools/make_map_mod.py output/mytown --name "My Town, KY" --id mytown
```

which writes `~/Zomboid/mods/<id>/common/media/maps/<Map Name>/` holding the
compiled cells, `map.info`, and the Lua files WorldEd emitted. Layout and
`map.info` fields (`lots=Muldraugh, KY`, `fixed2x=true`) follow an installed
Build 42 workshop map. Enable it in the game's Mods menu and start a new save.

> **A map with no `spawnpoints.lua` is not a startable region.** The mod shows
> up in the Mods menu, you enable it, and then the map is simply nowhere on the
> new-game screen. The packager now writes one, placing spawns at the middle of
> generated buildings so you start indoors.
>
> Mind the coordinate systems, which differ between files: compiled lot files
> use **256-tile cells** (`0_0.lotheader`…), while `spawnpoints.lua` in Build
> 42's own maps uses **absolute world tile coordinates** with a single
> `unemployed` list and no `worldX`/`worldY` at all. Older community maps use
> the legacy `worldX`/`worldY` cell form with a 300-tile in-cell offset — which
> is why you see `posX = 282` in them. Knoxify projects sit at world origin
> 0,0, so a building's map tile position is already its world position.

> **Build 42 needs a `mod.info` in each version folder.** A root-only one leaves
> the mod invisible in the Mods menu — the game scans `common/` and `42/` and
> expects each to identify itself. An installed workshop map ships three
> identical copies: root, `common/` (next to the media), and `42/` as the
> "works on B42" marker. The packager writes all three; don't trim it back to
> one.

### Reproducing the editor check without game artwork

BuildingEd normally demands a Tiles directory of tilesheets extracted from the
game's `.pack` files through a GUI-only tool. That is not needed just to prove a
file parses, because `TileMetaInfoMgr::readTxt` builds the tileset catalogue
with `loadFromNothing()` — names, columns and rows come from `Tilesets.txt` and
no image is read. The only gate is `PortableSettings::isTilesPath`, which merely
requires the directory (or a `1x`/`2x`/`custom` child) to hold at least one
`*.png`.

So: drop any PNG into `<tools>/Tiles/2x/`, point `settings/PZTools.ini` at it —

```ini
[Paths]
TilesDirectory=C:/Users/.../PZMappingTools/Tiles
```

— then launch `bin/BuildingEd.exe <file.tbx>` and read the newest log under
`settings/logs/`. Tiles render as placeholders; parsing, tile-name resolution
and room handling all run for real. This is how the `offset` bug below was
caught.

> Writing that INI by hand needs a **BOM-free** file. PowerShell 5.1's
> `Set-Content -Encoding utf8` adds one, and the tools then silently ignore the
> whole file and fall back to defaults.

## Compiling, and what happens when a batch will not

WorldEd's lot export never gives back what it loads, so `tools/compile_map.py`
hands the work over a few cells at a time, each to a fresh `PZWorldEd_cli`
that exits and returns its memory. The loop is strictly sequential and always
has been.

**A batch that fails is tried `BATCH_ATTEMPTS` times** (3) and then written to
`compile_failures.json` and stepped over. A fourteen-hour compile that lost
all 48 batches because batch 23 exited 1 after 849 seconds is the reason.
Nothing is deleted between attempts: the patched CLI skips a batch only when
*every* one of its cells already has a `.lotheader`, so a batch that died
part-way still has cells pending and is redone — and the lot files are named
in 256-tile cells against the world origin, not the 300-tile cells a batch is
given, so working out which files belong to a batch is a good way to delete
somebody else's finished work.

**Some failures stop everything.** `knoxpaths.qt_trouble()` reads a batch's
output for a Qt or loader failure, which is about the machine and not the
batch: all 48 would abort identically, and three attempts each is hours of
nothing. Those raise at once with what to do about it.

**`only_cells`** compiles a given list of `[x0, y0, x1, y1]` instead of the
whole grid — what **Compile the cells that failed** sends. A retry of some
failures keeps the record of the ones it did not touch.

**One compile per project.** Every run takes a `.compiling` lock holding its
pid, and carries a short run id on every log line so two runs in one log file
can be told apart. The batch counter is checked against the one before it. A
lock whose process is gone is cleared by the next run rather than jamming the
project for ever.

## Limits worth knowing

- **Rotation is lost** — see *Footprint fitting*. Size is right; angle is not.
- **Single storey.** No upper floors, and the stairs entry goes unused.
- **Size filtered.** Footprints under 5 or over 60 tiles are skipped
  (`--min-size` / `--max-size`).
- **Interiors are plausible, not architectural.** BSP rooms don't know a
  bathroom should sit off a hallway.
