# HANDOFF - KnoxMap

Project Zomboid map generator (Flask `app.py`), repo `spytheeuclidean-a11y/knoxmap`.
`C:\KnoxMap` is the user's install, NOT a git repo; it is updated by copying files out of the clone.
Clone: `C:\Users\TheTaZe\AppData\Local\Temp\claude\C--KnoxMap\bd68b2aa-9aa8-4f74-8b22-3c071121fabe\scratchpad\up`
(temp folder; its uncommitted work is lost if it goes). Branch `basement-stairwells`, cut from `main` at `ed20d32` (1.8.4).

## Goal
Generated maps that look lived-in: basements reached by a proper stairwell, industrial estates with yards, malls that read as malls.

## Done (uncommitted, on `basement-stairwells`)
- Basement stairs in a room of their own (`knoxbuild/basements.py`: `_well`, `WELL_TRIES`, `find_stair_spot(well=)`, `_wall_off`):
  houses, flats, ordinary industrial get a 1-wide stairwell with a door at the top; schools, hospitals, civic, police,
  malls, churches, military get a stair hall (flight + lane) with a door; open hole only when nothing fits.
- Flats get basements (`tier("apartment")` = "house"; `basement_apartment` programme in `knoxbuild/layout.py`).
- Industrial yards: new `knoxbuild/works.py` (tarmac yard, worn edge, drive from the front door, dumpster, clutter,
  lights, parking zone), hooked into `knoxbuild/yards.py` `paint_paths`; industrial ground now `LIGHT_GRASS`
  (`generator/rendering/landcover.py`); colours in `generator/pz_colors.py` (12,39,200-213); tile rules in
  `worlded/patch_rules_roads.py`.
- Tests: `tests/test_basements.py` (stairwell, stair hall, tiers), `tests/test_works.py`.
- Checked: 946 unit tests, `tools/selftest.py`, `tools/audit_layouts.py 400` all pass (basement rooms with no way in 0/3559).
- Not checked: in game; Piqua save-buffer size with flats' basements.

## Not done
- Mall redesign: spec written, not approved. `docs/superpowers/specs/2026-11-02-malls-design.md` (in the clone, untracked).
  Blocker: user review of the spec. Then writing-plans, then implement.

## Git (as of last check)
- `main` = `ed20d32` (1.8.4 released, Latest). PR #62 merged. No open PRs.
- `basement-stairwells`: no commits, not pushed; 7 modified + 3 new files (above).
- `docs/superpowers/` stays local and untracked (user asked it out of PRs).

## Next steps
1. needs user: approve or change `docs/superpowers/specs/2026-11-02-malls-design.md`; then invoke writing-plans.
2. needs user: go-ahead to commit `basement-stairwells` and open a PR (do not stage `docs/superpowers/`).
3. needs user: go-ahead to copy changed files into `C:\KnoxMap` (back up first under `C:\KnoxMap\update\`) and run
   `python worlded\patch_rules_roads.py C:\KnoxMap\vendor\PZMappingTools` so the works objects have tiles.
4. needs user: regenerate Piqua, new world; check a house stairwell, a school stair hall, an industrial yard.
5. Measure Piqua save buffer after flats' basements (was 3.97 of 9 MB before).

## To resume
- Checks from the clone, with `PZ_MAPPING_TOOLS=C:\KnoxMap\vendor\PZMappingTools`:
  `python -m unittest discover tests`, `python tools/selftest.py`, `python tools/audit_layouts.py 400`
  (use `C:\KnoxMap\.venv\Scripts\python`).
- App: in `C:\KnoxMap`, `.venv\Scripts\python app.py` (PowerShell: `$env:PORT="5055"` first), open `http://127.0.0.1:5055/`.
- Committing, pushing, PRs, merges, releases and copying into `C:\KnoxMap` each need the user's go-ahead.

## Do not redo
- A basement is its own BuildingDef, never joined to the house above (joined, the game hid the house's roof; vanilla has 113, none joined).
- Stair shaft must lie inside the basement (inset a tile), so a stairwell can't use an outer wall; it stands free when no inner wall fits.
- Mall style chosen: US enclosed mall; tagged malls kept whole up to 60,000 m² (`_cut_big` currently cuts at 6,000 m²).
- Never loosen a test threshold; fix code. `catalog.py` tail is generated from `tools/game_pieces.py`.
- Bash heredocs with Python `'''` break here; write scripts with the Write tool.
- Background check runs read the working tree: don't edit shared files while they run.
