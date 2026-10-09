# knoxlots

Reads and writes Project Zomboid lot files (`.lotheader`, `.lotpack`,
`chunkdata_*.bin`). First step toward a KnoxMap compiler that does not depend on
WorldEd. MIT licensed, like KnoxMap.

## Clean-room record

WorldEd is GPL-2.0; this crate is MIT, so it is written from the file formats, not
from WorldEd's code.

- **Layouts** were found by reading real files (a KnoxMap map compiled by WorldEd,
  and two maps by other authors: Chesnee and Galway) and testing each guess
  against every file: it counts only if every file parses to its exact end and
  writes back byte for byte.
- **Seen before the clean-room decision**, so stated here: the declarations and
  function names of WorldEd's lot writer (`lotfilesmanager256.h`/`.cpp`) and one
  source comment saying the `LOTH`/`LOTP` markers were added in version 1. No
  field layout or logic was taken from it. The source has not been read since.
- Nothing is copied from WorldEd, TileZed or BuildingEd. Where WorldEd is needed it
  is run as a program and its output is compared.

## Command line

    knoxlots verify <lots folder>           read every file, write it back, compare bytes
    knoxlots rebuild <lots folder>          also rebuild every cell's pack and tile table
                                            from a plain grid of squares, and compare
    knoxlots blank-chunkdata <in> <out>     copy a lots folder with every chunkdata blank
    knoxlots export <lots> <src> [--keep-zombie]   cell sources made from existing lot files
    knoxlots compile <src> <out> [--threads N]     lot files made from cell sources
    knoxlots compare <a> <b>                same .lotheader and .lotpack files in both folders?

`compile` reads the source format in `SOURCE_FORMAT.md`.

Exit status 0 when everything matched, 1 when not, 2 on bad usage.

## Status

`rebuild` on 9 maps (6,578 cells; KnoxMap's own and two other authors') gives identical
`.lotheader`, `.lotpack` and `chunkdata` files, and every cell rebuilt from its grid of
squares is byte-identical. So the rules below are complete enough to write a pack and a
header from a description. `cargo test` covers synthetic, truncated and absurd input.

Rules for writing a cell (module `cell`), each checked on every cell above:
- 256 x 256 squares, 32 x 32 chunks of 8 x 8, chunks listed as `chunk_x * 32 + chunk_y`.
- Inside a chunk, squares run level by level, then `x * 8 + y`.
- The header's tile table is the tiles the cell uses, once each, sorted by name.
- Zombie bytes: floor of the mean of the spawn map over the chunk (`spawn`).

**chunkdata can be blank** (`00 01` + 1024 zeros): a copy of the Worthville map with
every chunkdata blank played normally in Build 42 (tested by the author, 2026-10-08;
the console showed only the usual `loading ...lotheader` lines). So the writer does not
need to reproduce that file, and its layout is left undecoded.

## Known and unknown

Known (see the module docs): header, room and building tables, the pack's chunk
offsets and run-length records, a square as a room value plus tile numbers, and
that runs of empty squares are as long as they can be, across levels.

**Found by experiment** (`experiments/exp.py` makes small maps that differ in one
feature, has WorldEd compile them, and the lot files are compared):
- The 1024 bytes at the end of a `.lotheader` are zombie intensity, indexed
  `chunk_x * 32 + chunk_y`: the floor of the mean of the `_ZombieSpawnMap.bmp` over the
  chunk's 8 x 8 tiles (`spawn.rs`). Matches all 16,384 chunks in two experiments.
- `chunkdata` is not touched by water, forest or parks; a road does nothing to it
  either; a house adds the values 16, 4 and 2 and more 64-byte blocks. Values 5 and 32
  are chunks off the west/east and south edge of the map.
- The blocks use the same value set (0, 2, 4, 5, 16, 32) as the chunk values, so a block
  looks like a per-square version of a chunk's value for chunks that are not uniform.

Not known yet, and kept exactly as read:
- `Header::field_a` / `field_b` (always 8, 8 so far).
- `chunkdata` (no longer needed for a working map, see above): one fact is solid: for a house, the first `2` lands at flat index
  `chunk_y * 32 + chunk_x` of the house's north-west chunk (5 placements, all exact:
  322, 330, 66, 345, 973). Everything after it is not a plain map: a single house
  also sets runs of `16`/`4`/`2` in a staircase and stripes that repeat every 5 rows
  and every 8 columns across the whole cell, and no row width from 8 to 200 turns the
  flagged entries into a compact shape. So the rest of the index, which chunks get a
  64-byte block, and what 2, 4 and 16 mean are open. Next experiments: houses of
  different sizes, two houses, a house across a cell edge; and a game test of whether
  blank chunkdata (`00 01` + 1024 zero bytes, which WorldEd itself writes for empty
  cells) is accepted for cells with buildings.
- The three numbers of a room object (seen as kind, x, y).
- Whether the game accepts a file this crate *produced* from new data. Round trips
  prove the format, not the content; that needs the game.

## Next

1. Find what the unknown fields mean by changing one input at a time in
   WorldEd and comparing outputs.
2. A writer that takes a plain description (tiles per square, rooms, buildings) and
   produces these files; first test: rebuild an existing cell from its own decoded data.
3. Check a rebuilt map in the game.

## Release

`.github/workflows/knoxlots.yml` builds `knoxlots.exe` (Windows) and `knoxlots` (Linux). KnoxMap
looks for it beside `KnoxMap.exe`, so the release zip must carry the binary in its root: add a
step to the job that makes the zip that downloads this workflow's artifact and copies it there
(`knoxlots-windows-x86_64.exe` -> `knoxlots.exe`). `.gitattributes` keeps `fixtures/` out of a
zip made with `git archive`; a job that zips the checkout itself must exclude them too.
