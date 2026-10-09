# Source format for `knoxlots compile`

What a producer (KnoxMap) writes so `knoxlots compile <src> <out>` can make the lot
files. Design aims: easy to write from Python/numpy, about the size of the lot files
themselves, checked on read, and proven against real maps.

```
<src>/
    source.txt                    world settings
    <spawn map>.bmp               optional, named in source.txt
    cell_<x>_<y>.kcell            one per 256-tile cell, <x>_<y> as in the lot files (83_2)
```

## `source.txt`

Plain `key = value`, `#` starts a comment. The first setting must be the format line.

```
format = knoxlots-source 1
origin_x = 21000      # tile x of the world's west edge in lot-file coordinates (70 * 300)
origin_y = 0
spawn_map = Worthville_ZombieSpawnMap.bmp    # optional; path relative to this file
field_a = 8           # optional; two header values that have always been 8
field_b = 8
```

`origin_x` and `origin_y` must be multiples of 8. The spawn map is an uncompressed 8- or
24-bit BMP, one pixel to 10 x 10 tiles, from the world's north-west corner.

## `cell_<x>_<y>.kcell`

Binary, little-endian; the byte layout is the comment at the top of `src/kcell.rs`.
In short: the cell's position and levels, a table of tile names (any order), the room
and building tables, optionally the 1024 zombie bytes, then every square of every level
(level by level, row by row, x within a row) as run-length records: a run of empty
squares, or a square with its room value and a list of tile names, bottom first.

A cell with no zombie bytes gets them from the spawn map (floor of the mean over each
8 x 8 chunk); with neither, zero.

## What the compiler does with it

- Reorders the squares into chunks (`chunk_x * 32 + chunk_y`; inside a chunk level by
  level, then `x * 8 + y`) and writes `world_<x>_<y>.lotpack`.
- Writes `<x>_<y>.lotheader`: the tile table (the tiles used, once each, sorted by name),
  the room and building tables, the zombie bytes.
- Writes a blank `chunkdata_<x>_<y>.bin` (works in Build 42, tested).
- Reads every file with checks (counts, tile numbers, run lengths, trailing bytes) and
  reports a damaged cell by name instead of stopping the whole compile.

## Proof

`knoxlots export <lots> <src> --keep-zombie` makes this format from an existing map and
`knoxlots compile` turns it back; `knoxlots compare` found every `.lotheader` and
`.lotpack` identical on four maps (Worthville, Chesnee, Portsmouth, Galway: 2,284
cells). Without `--keep-zombie`, with the spawn map instead, four fresh WorldEd maps
(a road, three house placements) also came back identical.

## What it does not cover yet

- Producing the squares: KnoxMap has to emit tile stacks (terrain, walls, floors, roofs,
  furniture, vegetation) per square. That is the next, larger piece.
- Room values in squares: KnoxMap maps carry none, so neither does the format's use of
  them here; what other maps' values mean is not understood.
- The header's three-number room objects are carried as read.
