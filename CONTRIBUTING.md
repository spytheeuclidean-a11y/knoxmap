# Contributing

Thanks for helping. A few things keep KnoxMap working and publishable.

## Before you open a pull request

Run these from the KnoxMap folder (they are what GitHub Actions runs):

```bat
.venv\Scripts\python tools\selftest.py
.venv\Scripts\python tools\audit_layouts.py 200
```

The unit suite is `python -m unittest discover tests`. The tests that build and
compile a town make it slow, so the quick half leaves those out:

```bat
set KNOXMAP_FAST=1 && .venv\Scripts\python -m unittest discover tests
```

(`KNOXMAP_FAST=1 python -m unittest discover tests` on Linux/macOS.) CI runs
both halves in separate jobs; `tests/slow.py` says how to mark another class.

To see where the tests do not reach yet:

```bat
.venv\Scripts\python -m coverage run -m unittest discover tests
.venv\Scripts\python -m coverage report
```

Coverage is report-only in CI: the number is the point, not a threshold.

`selftest.py` needs no internet, game or map tools. If you changed how
buildings or roads look, also generate a small real area and look at it with
`tools\render_ground.py`, or better, in the game, and include a screenshot.

To catch byte-level layout changes after modifying the renderer, furnishings,
map source or Rust compiler, run `\.venv\Scripts\python tools\regression_maps.py`
(or `python tools/regression_maps.py` on Linux/macOS). It generates a fixed-seed
dense city, village and coast offline, compiles their cells with **knoxlots**,
and checks every `.lotheader`, `.lotpack` and `chunkdata` SHA-256 against
`tests/fixtures/regression_maps/hashes.json`. This needs map-tool
`Rules.txt`/`Blends.txt` from Setup and `knoxlots` built with `cargo build
--release`; there is no WorldEd invocation or need to copy game art into git.
The test fails if either dependency is missing. When a change to the maps is
intentional, inspect it first, then run `python tools/regression_maps.py
--record` to accept the new hashes. Review that manifest in the change.
Before a release that touches the compiler, also run the 51 x 48 cell scale
check by hand: `python tools/large_compile_check.py <map folder>`. It tiles a
real map out to 2,448 cells, compiles and verifies them (about 43 s, 4 GB of
disk). It is not in CI because it needs a real generated map and `knoxlots`.
The manifest and mismatch-reporting unit checks need no extra test framework:
`python -m unittest discover -s tests -p test_regression_maps.py`.

## Native terrain search

Build the road/rail worker before testing terrain changes:

```text
cargo test --release --locked --manifest-path rust/knoxroute/Cargo.toml
cargo build --release --locked --manifest-path rust/knoxroute/Cargo.toml
python -m unittest tests.test_rust_rails tests.test_continuous_rails tests.test_road_layout
```

`knoxroute --rails` runs the rail assembly search over the exact corridor raster
Pillow produces. Python retains projection, raster painting and file handling.
The rail search preserves Python's queue order, rounding and assembly ports;
`rail_sections(points, backend="python")` is the reference for parity checks.
A missing or incompatible worker falls back to Python. Stop requests terminate
the native process and return through the existing stopped-job handler.

Releases carry `knoxroute.exe` (Windows) or executable `knoxroute` (Linux/macOS).
The `KNOXROUTE` environment variable can select another build; otherwise the
app checks its own directory, then `rust/knoxroute/target/release`.

`knoxroute --woodland` processes woodland pixels in bounded strips through one
worker per pass. Python draws the masks and computes density grades; Rust
applies the existing scrub, forest and ground-colour rules. `KWD1` sends a strip
count, then each strip's dimensions, eight RGB palette entries, vegetation and
ground RGB bytes, and three L masks. Each reply is `KWD1` followed by the updated
vegetation and ground RGB bytes. All integers are little-endian. Small images
stay in Python; missing or older workers fall back to the Python loop.
Run `python -m unittest tests.test_rust_woodland` for pixel parity, fallback,
malformed-input and cancellation checks.

## Never commit

- **Project Zomboid files**, including tile sheets extracted by Setup
  (`Tiles/`, `*.pack`). They belong to The Indie Stone. The `.gitignore` already
  excludes them; please don't force them in.
- **Generated maps** (`output/`), downloaded tools (`vendor/`) or the tile cache
  (`cache/`).
- **Personal paths or keys.** Paths go through `knoxpaths.py`.

## Be a good citizen of OpenStreetMap's servers

KnoxMap uses free, volunteer-run services. Changes must keep to their usage
policies (see [docs/LEGAL.md](docs/LEGAL.md)): no search-as-you-type, identify
the app, cache what you fetch, and never bulk-download tiles.

## Style

- Match the code around you. Comments say *why*, and usually what went wrong
  before: a measured failure beats a guess.
- New behaviour gets a check in `tools/selftest.py` or `tools/audit_layouts.py`
  when it can break.
- Keep terms and credits intact: OpenStreetMap attribution, The Indie Stone's
  fan-production credit, and the licences in `LICENSES.md`.

## Licences

By contributing you agree your work is released under the licence of the part
of the project it goes into: MIT for most files, GPL for `worlded/` (see
[LICENSES.md](LICENSES.md)).

## Releasing

Add a `## <version>` section to CHANGELOG.md, then push a tag:

    git tag v1.1
    git push origin v1.1

GitHub Actions runs the checks, zips the repository as `KnoxMap-v1.1.zip` and
publishes a release with that CHANGELOG section as its notes.

The Discord server is told about releases and nothing else: the repository's
webhook is subscribed to the `release` event alone. It used to carry `push`
as well, which announced every commit in the channel people read for new
versions.
