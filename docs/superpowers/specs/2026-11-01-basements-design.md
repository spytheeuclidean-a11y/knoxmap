# Basements

Date: 2026-11-01. Status: design approved in chat, spec awaiting review.

## Goal

Generated maps get basements that KnoxMap lays out itself and bakes into the
lots, below level 0. A building's kind decides whether it has one and how big
it is: a house gets a cellar, a school or hospital a larger one, and a
military installation a basement many levels deep that spreads under its whole
site.

Success: in game, a player walks down stairs from a ground floor into a
furnished room underground. Maps without basements compile byte-for-byte as
they do today. Compile, install and the save-buffer warning stay correct.

## Facts this design rests on

- Build 42 levels run from -32 to 31 (`zombie.iso.IsoChunkMap`:
  `BOTTOM_LEVEL = -32`, `TOP_LEVEL = 31`; read with `javap` for analysis only).
- The vanilla map bakes basements into its lots: of Muldraugh's 4,065
  lotheaders, 66 start at level -1, 3 at -2, 1 at -4 and 2 at -17, with 944
  rooms below ground. A lotheader's min and max level are plain ints.
- The game also stamps hand-made basements at runtime (`basements.lua`,
  `media/binmap/*.pzby`). This design does not use that system.
- KnoxMap's compile path is its own: layout -> `.tbx` -> `tools/map_source.py`
  -> `.kcell` -> `knoxlots` -> lotheader and lotpack. Today `.kcell` and
  `knoxlots` store `min_z`, `max_z` and room `z` as u32, `map_source` stacks
  only levels 0 and up, and the `.pzw` lot reader only accepts `level="\d+"`.

## Tiers

Starting values; Piqua and one military map tune them before release.

| Tier | Kinds | Levels | Extent |
|---|---|---|---|
| House | `house` | 1 | Under the footprint |
| Large building | `school`, `medical`, `civic`, `police`, `mall`, `industrial`; `church` of 600 m2 or more | 1; 2 when the footprint is 3,000 m2 or more | Under the footprint |
| Installation | `military`; `industrial` on a site of 50,000 m2 or more | `clamp(1 + site_m2 // 20000, 2, max_basement_depth)` | Under the whole site polygon (the `landuse` area around it, from `knoxbuild/areas.py`), not just the building; the footprint when there is no such area |

Who gets one:

- House: a share set by the new setting `basement_share` (default 0.4; a
  quarter of that where `regional.detect_region` says `cn`, `jp` or `kr`).
- Large building and installation: every one that has a clear stair spot.

New settings, with ranges in `knoxbuild/settings.py`:

- `basement_share`: 0.0 to 1.0, default 0.4.
- `max_basement_depth`: 1 to 32, default 8.

Rooms by tier, furnished with the existing `furnish_rules`, no windows,
ceiling lights on:

- House: laundry, storage, workshop, rec room, utility (boiler, water heater).
- Large building, by kind: school boiler room and storage; hospital morgue
  and plant room; police holding cells and evidence; mall service corridors
  and storage; civic archive and plant room; industrial plant room.
- Installation: a corridor spine on every level with armory, barracks,
  command, generator and storage rooms off it.

## Structure

Each basement is its own `.tbx`, `buildings/<parent>_bsmt.tbx`, placed as its
own lot at base level `-levels`, so its top floor is at -1. The game still
sees one building: the basement's rooms are listed in the parent's
BuildingDef.

Why its own lot rather than extra storeys in the parent's `.tbx`: an
installation's basement is larger than any one building's footprint, and
about 20 places in the code treat `storeys[0]` / `floors[0]` as the ground
floor (doors, yards, furnishing). Those stay as they are.

### Units

1. `knoxbuild/basements.py` (new)
   - `tier(row, site) -> str | None`: which tier a building is, or none.
   - `plan_basement(parent, row, tier, site, underground, rng) -> Basement | None`:
     a `layout.Building` of `levels` storeys, the stair spot handed to the
     parent, and the lot rectangle. `underground` is the occupancy map below;
     the planned squares are added to it.
   - Stairs: one stair core stacked through every level, using the stair-core
     rules the towers use (`layout._stairs_in_core`, `STAIR_RUN`). The top
     flight rises from -1 into a ground-floor room of the parent.
2. Stair hand-off, in `knoxbuild/build.py` after the parent is laid out and
   before its `.tbx` is rendered:
   - Choose the spot: under the parent's own staircase core when it has one,
     else a hall, kitchen or (large tier) corridor or service room with
     `STAIR_RUN + 2` clear tiles in a line, off doors and windows.
   - `layout._clear_for_stairs` on the parent's ground floor at that spot.
   - The parent's ground floor gets no floor tiles over the run, by the rule
     `tbx.py` already uses for the floor above a storey's stairs.
3. Underground occupancy: one set of `(x, y, z)` squares per map, filled as
   basements are planned, in build order. A basement that would overlap is
   shrunk to its parent's footprint; if it still overlaps, it is dropped.
4. Placement and room tables
   - `.pzw` lots: written and read with signed levels (`level="-?\d+"` in
     `tools/map_source.read_lots` and wherever else the lot is parsed).
   - `cell_tables` puts every room of a basement lot into its parent's
     building list. Rooms keep their negative `z`.
5. Compile
   - `tools/map_source.py`: levels below 0 hold building tiles only, no
     terrain. A cell's arrays are indexed `z - min_z`, with `min_z` the
     lowest level used in that cell.
   - `knoxbuild/kcell.py`: `min_z` written signed.
   - `rust/knoxlots`: `min_z`, `max_z` and room `z` are i32 in `.kcell` and
     in the lotheader; level counts come from `max_z - min_z + 1` in i32. A
     level outside -32..31 is an error, not a file the game cannot read.
   - Same bytes as today when nothing is below 0.
6. Install, limits and pictures
   - The 9 MB save-buffer warning (`make_map_mod.save_bytes`) counts basement
     rooms like any other; nothing to add.
   - `worldmap`, `worldmap_bin` and previews draw level 0 and up only.

## Error handling

- No clear stair spot in the parent: no basement. The build log counts these
  per tier.
- Overlap with another basement: shrink, then drop (above).
- Depth: clamped to `max_basement_depth` and to -32.
- `knoxlots` refuses `min_z < -32` or `max_z > 31`.

## Testing

Each test fails on today's code before the change that makes it pass.

- Rust, `knoxlots`: a lotheader and `.kcell` with `min_z = -3` round-trip; a
  room at `z = -2` survives; `-33` is refused.
- Python:
  - A house with a basement compiles to a cell with `min_z = -1`; its
    basement rooms are in the house's BuildingDef; the ground floor has no
    floor tile over the stair run; the stairs land in a room.
  - A military site of a given area gets the expected number of levels; one
    stair core reaches every level; the basement extends past the building's
    footprint and stays inside the site.
  - Two neighbouring basements never share a square at any level.
  - A map with `basement_share = 0` and no large buildings compiles to the
    same bytes as before.
- `tools/selftest.py`: a basement check (a house with one, compiled and read
  back).
- `tools/audit_layouts.py`: basement plans audited like storeys (doors boxed
  in, rooms with no way in).
- Piqua rebuilt: basements counted by tier.
- In game (needs the user): walk down into a house basement and into a
  military one, levels -1 to the bottom.

## Not in this work

- Apartment basements; OSM-mapped underground (`parking=underground`,
  `building:levels:underground`, subway stations).
- Zombies spawned underground; flooding.
- The game's runtime-stamped `.pzby` basements.

## Branch

Committed to `crash-fixes`, the branch of PR #62 (the user's choice).
