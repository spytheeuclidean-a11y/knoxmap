# Room sizes by room type (houses and flats)

## Goal
Rooms in houses and flats get sizes that fit their type: a bathroom is small, a living room is big.
Sizes and room mix vary from home to home.

## Problem (measured, 150 houses + 150 flat blocks, median tiles)
- Flats: bathroom 15, bedroom 16, kitchen 20, living 24; 1,202 bathrooms vs 1,002 bedrooms.
- Houses: bathroom 9, living 30, bedroom 20, but hall 21, laundry 16, storage 16.
- Cause: `_split` cuts the floor into similar-sized pieces and kinds are assigned afterwards
  (`_assign_flat_kinds`, `_assign_house_kinds`), so a room's size does not depend on its type.
- Measuring script: scratchpad `measure.py` (re-run after the change to compare).

## In scope
- New `knoxbuild/sizing.py`:
  - size table per room kind: min / target / max tiles and max aspect, derived from the "kinds"
    table in `knoxbuild/room_solver.json` (m2 converted with the project's metres-per-tile).
  - `programme_for_flat(area, rng)` -> list of room kinds (studio, 1-bed, 2-bed, 3-bed by area).
  - `programme_for_house_floor(area, level, levels, rng)` -> list of room kinds (house path).
  - `split_by_targets(box, kinds, rng, mask)` -> rooms cut in proportion to their targets
    (recursive guillotine split: divide the kinds into two groups, cut at the ratio of their
    target areas, respect min size, minimum side `MIN_ROOM`).
- Flats first: `_apartment_rooms` cuts each flat with `split_by_targets`; kinds are set at creation
  and the room is marked `fixed`, so `_assign_flat_kinds` keeps them.
- Then houses, non-solver path only: `build_plan` house floors.

## Out of scope
- The OR-Tools solver (`room_solver`) and its dependency.
- Furniture placement (separate spec).
- Non-home buildings, hotels, exteriors.

## Must keep
- Every flat opens onto the corridor; the room at the door is the living room; flats touch the corridor.
- Stair, lift, window and door rules, party walls, open-plan flats, hotel flats unchanged.
- Floors with no fitting programme fall back to the current splitter (never fail a build).
- Deterministic for a given seed; CRLF line endings.

## Testing
- `tests/test_sizing.py`: size ranges respected per kind; bathroom median < bedroom median < living
  median over many seeds; programme counts by area; split fills the box exactly with no overlaps;
  fallback when the box is too small.
- Existing walkability/layout tests and `tools/selftest.py` pass.
- Re-run the 150+150 measurement and report the before/after medians.

## Result (median tiles; before = 7a72969)
- Flats (150 blocks, measure.py), before -> after: bathroom 15 -> 12, bedroom 16 -> 16, kitchen 20 -> 12,
  living 24 -> 20, hall 20 -> 9, openplan 28 -> 27.
- Rectangular houses (150, measure.py): bathroom 9 -> 12, bedroom 20 -> 25, living 30 -> 32, kitchen 21 -> 20,
  hall 21 -> 12, laundry 16 -> 12, storage 16 -> 12, office 16 -> 16; separate dining rooms in fewer than
  20 of 150 houses.
- Turned houses (150, audit_layouts.rotated_mask): unchanged from before (bathroom 12, living 42, bedroom
  27 -> 30): a footprint filling under 80% of its box keeps the old splitter, since a cut drawn on the
  box made every unclipped room about twice its size (living median 99, max 528).
- Big rectangles (150, 20-32 x 16-24): bathroom 9 -> 10, bedroom 21 -> 24, living 36 -> 36, kitchen 25 -> 20.
  A big floor gets more rooms (one per 14 tiles, up to 40 spares), not bigger ones, and a cut whose
  room comes out over 1.5 x its kind's largest size is not kept.
- Circulation (300 mixed houses): the hall is cut beside the stairs and spare rooms off it become halls
  where bedrooms would chain; upper stair cores opening only into bedrooms/bathrooms 2 -> 12,
  bedroom-to-bedroom doors 38 -> 55, bedroom-to-bathroom 49 -> 57.
- Flat bathrooms stay at 12: corridor flats are only 3-5 tiles deep, so a bathroom is 3x4 or 3x5. Deeper flats are out of scope.
- Fallback to the old splitter (floors): rectangular houses 5%, big rectangles 8%, irregular
  (notched) houses 36%, turned houses all; masked flats about 44%.
- Speed: 300 mixed houses 9.9 s -> 11.6 s; big rectangles 12 s -> 25 s (twice the rooms, cut by kind).
- Furniture still gets deleted to clear doors: 6.7 pieces per house (was 5.3) and 26 per flat block (project 2).
