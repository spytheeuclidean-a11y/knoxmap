# Changelog

## 1.0 (first release)

KnoxMap grows [Knoxify](https://github.com/arytek/knoxify)'s terrain generator
into a full pipeline, from a real place to an installed Project Zomboid Build 42
map.

**Choosing an area**
- Rectangle, polygon, circle and freehand lasso tools, and a search result's
  real boundary (a park, a district, a town). Only the shape is built; main
  roads and rivers run on past it.
- `?q=<place>&outline=1` opens the app straight to a place.

**Terrain**
- Streets at real widths, with pavements, kerbs and centre lines; the map turns
  so the main street grid runs along the tiles.
- Seas from OpenStreetMap coastlines, harbours and lakes from multipolygons,
  rivers with their bridges, canals, piers and railways.
- Parks, schoolyards, industrial yards, cemeteries, orchards, playgrounds,
  pools, fences, walls and hedges; dense city blocks paved.

**Buildings**
- Every building on its real footprint, turned to the grid, with rooms laid out
  for what it is: houses, blocks of flats with corridors and separate flats,
  shops, schools, churches, clinics, offices, factories and sheds.
- Real heights up to 30 storeys, borrowed from tagged neighbours where missing.
- Lifts in buildings of five storeys or more, working with the Elevators mod.
- Windows that suit the building: kind, size and spacing follow what it is
  and how tall (glass towers, shop fronts, tall panes on flats), with
  matching curtains or blinds. Window count is not a setting.
- A light switch in every room, clear staircases, roofs that follow the
  footprint, loot tables that match the room.

**In the game**
- The paper map (M) with real buildings, water, streets, street names and
  landmarks.
- Zombies spawned from an estimate of who lived and worked in each building,
  with a census and a one-second recount.
- Buildings are what they really are: the shops, restaurants, banks, offices,
  hotels and theatres OpenStreetMap maps inside them become the game's own
  rooms - a pizza place is a dining room and a pizza kitchen, a hotel's floors
  are guest rooms, a theatre is a foyer and an auditorium - so the loot fits.
- Shops fitted out like Knox County's: rows of shelving, fridges along the
  walls, a till by the door and a stockroom behind; offices with desks and
  filing cabinets; every flat with its own sofa, beds, wardrobes and kitchen.
- No windows, shop fronts or doors in walls shared with the building next door;
  stairs at the back of a shop, not in the middle of it.
- Uses Erika's Tiles when it is installed: glass shop fronts with glass doors
  and shop signs, drinks machines, posters and bookcases in shops, pictures,
  mirrors and plants in homes, and speed limit signs on the streets. Maps made
  with it require it.
- Spawn points inside homes across the town, and the map's landmarks as
  starting points in the Spawn Selector mod when it is installed.

**The app**
- One window: search, generate, build, compile, install. Setup.bat downloads
  the tools, extracts tiles from your own game and checks everything.
- Presets and fine tuning for zombies, living space, heights,
  woodland, parking and more.
- A patched, headless map compiler so compiling needs no clicks in WorldEd.

**Behind the scenes**
- Follows OpenStreetMap's tile, Nominatim and Overpass usage policies; credits
  OpenStreetMap in every map; ships the compiler with its GPL source. See
  [docs/LEGAL.md](docs/LEGAL.md).
- `tools/selftest.py` runs the whole pipeline offline, `tools/audit_layouts.py`
  stress-tests floor plans, and GitHub Actions runs both on every push.
