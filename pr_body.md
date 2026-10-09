## What

Compile maps without WorldEd. KnoxMap now builds the tile stack of every square itself and a small Rust program, `knoxlots`, writes the lot files. There is no bitmap size limit and no batches.

- **Ground and blends** from `Rules.txt` / `Blends.txt` (`knoxbuild/terrain.py`, `blends.py`)
- **Buildings** from their `.tbx`: floors, walls, doors, windows, curtains, furniture, stairs, ceilings, roofs, porch lights and signs (`buildtiles.py`, `buildroofs.py`)
- **Header** room and building tables (`buildheader.py`)
- **`tools/map_source.py`** turns a project folder into cell sources, one process per row of cells; **`knoxlots compile`** writes `.lotheader`, `.lotpack` and blank `chunkdata`
- **`tools/compile_map.py`** uses it when `knoxlots` is found (beside `KnoxMap.exe` in a release, in `rust/knoxlots/target/release`, `KNOXLOTS`, or PATH), and WorldEd otherwise. `KNOXMAP_BACKEND=worlded|rust` or `--backend` chooses outright
- **`app.py`** compile endpoint takes `"backend"`; the size refusal from #25 only applies when WorldEd is the compiler
- **Release**: new `knoxlots.yml` builds and tests the binary on Windows, Linux and macOS; `release.yml` puts each system's binary in that system's download

## Clean-room

WorldEd is GPL-2.0; this is MIT. Nothing was read or ported from WorldEd's source. The file formats were read from real lot files, and the rules were found by running WorldEd on small hand-made inputs and comparing what it wrote. Method and notes: `rust/knoxlots/README.md`, `SOURCE_FORMAT.md`. The same work, with the 50 MB of comparison test maps, lives at https://github.com/thehorseofcourse45/worlded-rusted (private for now). The test maps are not in this PR; the tests that use them skip when they are absent.

## How it was checked

- A 9-cell map of 113 real buildings, compiled by WorldEd and by this: all 422,696 squares on every level identical (random tile picks compared by Rules.txt alias).
- A 1,500 m map of 1,177 buildings: 2,020,709 of 2,020,734 squares identical over 25 cells. What differs is a few window, door and wall details and the order of tiles within a square. Rust took 60 s for 64 cells; WorldEd took 271 s for 25.
- Room and building tables equal WorldEd's on 8 of 9 cells of the small map and 19 of 25 on the large one. The rest are 12 same-name rooms that WorldEd joins across lots for a reason I could not find. This only changes the room lists.
- The 1,500 m map was played in Build 42: buildings, loot, zombies and upper floors worked.
- `python -m unittest discover tests` passes; `cargo test --release --locked` passes.

## Not checked

- Nothing at the size that motivated this (about 51 x 48 source cells). Time and memory there are unmeasured. Rows are built in parallel with a memory-based worker count, and each row loads the buildings within 8 tiles of it; a building that reaches further than that could show a seam at a row edge.
- The release workflow changes were not run (I cannot trigger a tag build). `knoxlots.yml` builds `cargo test`/`build` on three systems; macOS and the tarball copy of `knoxlots` are untested.
- Fences, lights and the like come from the existing `.tbx` lots. Vehicle zones and world objects are not written by the Rust path.
- Room objects in headers are omitted (no rule found).

## If you would rather not take the compiler yet

Nothing changes for a checkout without a built `knoxlots`: `default_backend()` finds none and WorldEd is used as before.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
