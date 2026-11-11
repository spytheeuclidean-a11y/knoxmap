# Furniture placement that keeps doors and routes clear

## Goal
Furniture never blocks a door or part of a room, and rooms keep the pieces that make them that room
(toilet, sink, bed, fridge) instead of having them deleted afterwards.

## Problem (measured, 100 houses + 100 flat blocks)
- Rooms are furnished one at a time (`_furnish`), then `_clear_the_way` / `_open_up` deletes the fewest
  pieces that make every room reachable. About 10% of placed furniture is deleted (3,900 of 39,500).
- Deleted by role: counter 555, dresser 536, plant 432, sink 295, lamp 241, bookshelf 236, shelf 189,
  kitchen 154, toilet 135, wardrobe 93, tv 88, fridge 82.
- Deleted by room: bedroom 807, bathroom 724, openplan 615, livingroom 536, kitchen 286.
- Essential fixtures (toilet, sink, bed, fridge) are deleted along with decoration, because the
  clear-up picks pieces by path cost, not by importance.
- Measuring script: scratchpad `removed.py`.

## Design
- **Reserve before placing.** For each room, before any piece goes in, compute a walkway: the shortest
  tile path joining every door of the room (and the stair/lift landing, window squares that must stay
  reachable) plus the 1-tile clearance in front of each door (existing `DOOR_CLEAR_DEPTH`). Those tiles
  are off limits to blocking furniture. Rooms with one door get a spine from the door to the room's
  far side so the room is walkable end to end.
- **Place in priority order.** Essentials first (kind-defining pieces), then secondary, then
  decoration (plants, lamps, shelves). A piece is placed only if its tiles avoid the walkway and the
  free floor of the room stays connected (flood fill) after the piece is added; otherwise it is skipped
  or tried at another spot. Decoration is the first thing dropped when a room is tight.
- **Keep `_clear_the_way` as a safety net**, but when it must delete, it deletes by priority (decoration
  before secondary before essentials) and never deletes an essential if a lower-priority piece on the
  same route can go instead.
- **Priority table:** a table in a new module `knoxbuild/furnish_rules.py` mapping each role to
  essential / secondary / decoration, with a per-room-kind list of essentials.

## In scope
- Homes first (rooms of houses and flats), then the same mechanism for all building kinds since
  `_furnish` is shared.
- New `knoxbuild/furnish_rules.py` (priorities, walkway computation, connectivity check).
- `_furnish` / `_place_group` in `knoxbuild/layout.py` use the walkway and priorities; `_open_up`
  deletes by priority.

## Out of scope
- New furniture or catalogue entries; changing which pieces a room kind wants; mod furniture rules.
- Room layout/size changes (separate specs).

## Must keep
- Existing door clearance, window and wall-hanging rules; lights/switch per room; wall pieces.
- Never fail a build; deterministic per seed; line endings as in the working tree.
- Non-home furnishing (shops, schools, etc.) stays correct (tests pass); behaviour there may change only
  where it stops blocking doors/routes.

## Testing
- `tests/test_furnish_rules.py`: walkway joins all doors of a room; pieces never land on walkway tiles;
  free floor stays connected after each placement; priority order respected when a room is tight.
- Re-run `removed.py`: pieces deleted per building drops sharply (target: < 3% of placed pieces) and
  essentials (toilet, sink, bed, fridge, kitchen counter) deleted: ~0.
- Existing walkability tests, `tools/audit_layouts.py 400`, `tools/selftest.py` pass.
- Compile-time check: furnishing time per building within 1.5x of today.

## Result (furnish_measure.py, 100 houses + 100 flat blocks; before = f92dea5, after = Task 5)
| | before (Task 3) | after |
|---|---|---|
| placed | 43,189 | 43,191 |
| removed | 3,093 (7.2%) | 1,052 (2.4%) |
| essentials removed | 971 | 31 |
| on a window square / elsewhere | 2,813 / 280 | 868 / 184 |
| bathroom with toilet | .87 | 1.00 |
| kitchen with fridge | .80 | .99 |
| openplan with fridge | .97 | 1.00 |
| livingroom with sofa | .99 | .99 |
| bedroom with bed | .79 | .81 |
| kidsbedroom with bed | .89 | .99 |
| time | 9.9 s | 10.8 s |

- Against the plan baseline (a731daa: 3,327 removed of 42,875, 7.8%, 1,065 essentials, 9.2 s): removed 2.4%,
  essentials 31, time 1.17x.
- removed.py (same sample), removed by room before (4b6a326) -> after: bedroom 791 -> 444, bathroom 728 -> 36,
  openplan 615 -> 10, livingroom 557 -> 388, kitchen 291 -> 9, kidsbedroom 159 -> 86, hall 156 -> 53;
  3,414 -> 1,052 in all.
- Essentials are not ~0. The 31 that are left: 16 bathroom sinks in 3x3 bathrooms where the sink's tile is the
  window square and there is no free wall; 12 on the clearance of doors slid off corners after furnishing (bath 4,
  double bed 3, counter 2, stove 2, kitchen sink 1); 3 fridges in full kitchens.
- Pieces removed away from window squares (184) come from window squares in corner pockets of full rooms (the
  window rule wants an occupied square reached, so the stack on the way goes too), pieces on a moved door's
  clearance that cannot move, and knock-ons of doors sliding into corner pockets. The window rule is unchanged.
- Test guards on SAMPLE (30 + 30): removed 2.8% (< 3%), essentials 12 (<= 16), elsewhere 0.37% (< 0.45%).
