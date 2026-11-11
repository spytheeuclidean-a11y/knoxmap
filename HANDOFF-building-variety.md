# HANDOFF - KnoxMap building-type variety

Paste this into another AI. Nothing for this task has been started.

## What KnoxMap is
Flask app (`app.py`, Python) that turns real places (OpenStreetMap data) into Project Zomboid maps. The building interior code is in `knoxbuild/`. Folder: `C:\KnoxMap` (not a git repo; files use LF line endings).

## Goal
Make non-home buildings read as what they are: shops, offices, schools, restaurants, clinics, and so on. That means room sizes, circulation (halls and corridors), and adjacency (what sits next to what) that fit each type. Today most of the care went into flats, houses and towers; other types mostly get a generic room mix.

The user has not confirmed the scope. Ask which building types to start with before building anything.

## What already exists (read these first)
- `knoxbuild/layout.py`
  - `build_plan(...)` (~line 5396) cuts one storey into rooms and assigns kinds.
  - `SPECIAL_MIXES` (~line 408): per-type room lists for school, church, restaurant, shop, retail, industrial, barn, garage, military and more. Each entry is `(mix, fill)`: the first rooms dealt, then the cycle used for the rest.
  - `_assign_kinds`, `_circulation`, `_merge_halls`, `NEEDS_CORRIDOR`, `MERGE_CIRCULATION`: how special mixes get corridors.
  - `_assign_shop_floor`: the shop-floor path (front shop, back storeroom).
  - `_assign_flat_kinds` and `_assign_house_kinds`: the adjacency-based kind logic for homes. It is the model to copy for other types.
  - `COMMERCIAL_FILL`, `RESIDENTIAL_FILL`: fallback fills.
- `knoxbuild/uses.py`: `use_of(tags)` maps OSM tags to a use pair such as `("mechanic", "storage")`.
- `knoxbuild/build.py`: `classify_building`, `_business_kind`, `pick_style`.
- `tests/test_business_layouts.py`: examples of testing a business layout through `layout.build_building(...)`.
- `tools/audit_layouts.py 400`: audits 400 generated layouts. `tools/selftest.py` checks every room name emitted is one the game knows.

## Work from the sibling branches (not in `C:\KnoxMap` yet)
Other work is in a git clone at `C:\Users\TheTaZe\AppData\Local\Temp\claude\C--KnoxMap\bd68b2aa-9aa8-4f74-8b22-3c071121fabe\scratchpad\up`. Branches stack: `draw-core` -> `skyscrapers` -> `room-sizing` -> `furniture-placement`.
- `knoxbuild/sizing.py` (branch `room-sizing`) cuts flats and houses by room kind. A good model for per-type sizes in non-home buildings.
- `knoxbuild/furnish_rules.py` (branch `furniture-placement`) reserves a walkway before placing furniture and keeps doors clear. Non-home furnishing is the slow path (about 1.9x slower; budget 1.5x), so keep any new per-room work cheap.
- `knoxbuild/tower.py` has office-tower floors: one toilet, one stair, offices capped at the civic room size.
- Build in the clone, then copy to `C:\KnoxMap` with `git show <commit>:<path>`, not the working tree (the clone is CRLF).
- The furniture branch had fixes still running when this was written. Check `git status` and `git log` there before basing work on it.

## Suggested approach
1. Ask the user for the building types and what "realistic" means for each (sizes, corridor shape, which rooms touch).
2. Run `python tools/audit_layouts.py 400` first to get a baseline per type.
3. Write a short spec and a failing test per type, then change `SPECIAL_MIXES` / the assign functions. Prefer a rule table like `furnish_rules.py` over more special cases in `layout.py` (it is over 5,000 lines).
4. Re-run the audit and the full tests. Report before/after numbers.

## Checks
```
python -m unittest discover -s tests
python tools/selftest.py
python tools/audit_layouts.py 400
```
The full test run takes about 8 minutes. Run the app with `PORT=5055`, `ZOMBOID_DIR` set to a temp folder, `python app.py`, then open `http://127.0.0.1:5055/`.

## Do not
- Do not loosen a test threshold silently. If a number moves, document the measured cause.
- Do not change `_open_up`'s window rule in `layout.py`.
- Do not use Build 42 storey counts above 31 (the roof takes one of its 32 levels).
- Do not push, open a PR, merge, or touch the real Zomboid mods folder without the user's approval.
- Overpass (OSM live data) is unreachable from the dev machine, so tests on real coasts need data from the user.

## Not verified in game
31-storey roof, lifts, new room sizes, Standalone maps. Treat room sizes from `room-sizing` as untested in game.
