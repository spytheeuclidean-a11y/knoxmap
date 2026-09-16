# Contributing

Thanks for helping. A few things keep KnoxMap working and publishable.

## Before you open a pull request

Run these from the KnoxMap folder (they are what GitHub Actions runs):

```bat
.venv\Scripts\python tools\selftest.py
.venv\Scripts\python tools\audit_layouts.py 200
```

`selftest.py` needs no internet, game or map tools. If you changed how
buildings or roads look, also generate a small real area and look at it with
`tools\render_ground.py`, or better, in the game, and include a screenshot.

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
