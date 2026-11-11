# Skyscraper interiors and the 31-storey limit

## Goal
Office towers get a real tower interior (central core, open floors, lobby, plant floor) instead of
stacked ordinary floors, and maps can build up to 31 storeys, the most Build 42's height limit
allows once the roof is on.

Ruling (2026-10-29): the cap is 31, not 32. Build 42's 64 levels are -32 to 31 and tbx.py always
adds a roof floor above the top storey, so a 32-storey building would put its roof at level 32.

## In scope
- New `knoxbuild/tower.py`, called from `build_building` in `knoxbuild/layout.py`.
- `LIMITS["max_levels"]` in `knoxbuild/settings.py`: 30 -> 31. Update the hint in `static/js/app.js`
  (`max_levels`) and any test that pins 30 (`tests/test_suggested.py`).
- `Plan.shaft` / `Plan.shaft_door` become lists so a building can have several lifts.

## Out of scope
- Exterior shape, facades, crowns, podiums. Existing glass facade and setback rules stay.
- Flat and hotel towers (`kind == "apartment"`) keep today's layout.
- A second fire stair. Towers keep one stair, as buildings do now.

## Trigger
`kind == "civic"` and `levels >= 12` and `min(width, height) >= 14`. Otherwise the current path runs
unchanged.

## Layout (identical core on every floor)
- **Core:** one rectangle near the footprint centre, wholly inside the mask (and inside the
  setback's upper mask). Holds the stair hall, a lift bank of 2-4 shafts (2x2 each, doors facing the
  lift lobby, as `_pick_shaft` does now), one toilet, and a riser room.
- **Office areas** are no bigger than `_room_cap("civic")`: a large area is cut into strips running
  away from the hall, each with its own door onto it (ruling, 2026-10-29).
- **Upper floors:** the ring around the core is cut into a few large office areas (`office` kind,
  few partitions). Every area has a door onto the lift lobby.
- **Ground floor:** lobby is the front room with the entrance and reception; core as above.
- **Plant floor:** at `round(levels * 0.9)`. Storage/mechanical rooms, no offices.
- Floors that share a footprint share a seed, as apartments do, so windows line up.

## Error handling
If no central core fits the mask, fall back to the existing path (never fail a build).

## Testing
- Unit tests (`tests/test_tower.py`): core identical on every floor; shafts inside the footprint;
  every office area reaches the lift lobby by a door; plant floor has no offices; fallback on a
  footprint with no room for a core.
- A 31-storey build through `build_building`; `max_levels` clamp at 31.
- `tools/selftest.py` and `python -m unittest discover -s tests` pass.
- Acceptance: 100 Summer Street, Boston MA (32 storeys, built at the 31 cap). Overpass is unreachable from this machine,
  so the footprint needs the user's data or a hand-built fixture. Needs a look in the game: that a
  31-storey roof loads, and that the lifts work with the Elevators mod.
