# What each WorldCover class becomes on the map

This applies only to ground that OpenStreetMap leaves blank. Anything OSM maps
(land use, water, roads, buildings) is painted over WorldCover and wins. Where
the layer is off, outside coverage or not downloaded, the map is built as it is
today.

| Code | WorldCover class | Ground | Vegetation | On the map |
|---|---|---|---|---|
| 10 | Tree cover | Dark grass | Treated as forest: dense trees in the middle, thinner toward the edges, big trees, scaled by Forest density | A real wood, the same as a mapped OSM forest |
| 20 | Shrubland | Medium grass | Clumps of bushes and young trees with some sparse trees, and no grown trees | Scrubby ground, thicker in some places and open in others |
| 30 | Grassland | Medium grass | Short grass tufts and the odd bush, with no woods | Open meadow |
| 40 | Cropland | Ploughed furrows along each plot's long axis | Split into 60–150 m plots: about 50% corn, 35% bare furrows, 15% fallow grass. Some plot edges get a hedgerow | Farm fields. Mapped OSM `landuse=farmland` gets the same treatment |
| 50 | Built-up | Medium grass | Nothing new. Gardens round houses are planted as today | Yards and verges. Roads and buildings come from OSM |
| 60 | Bare / sparse vegetation | Dirt | Low rocks in clumps over about 10% of the ground, and a few boulders (about 1%) | Stony bare earth |
| 70 | Snow and ice | Sand (the game has no snow ground tile) | None | Pale bare ground |
| 80 | Permanent water | Water | None | Water where OSM has no water mapped |
| 90 | Herbaceous wetland | Dark grass | Dense bushes and marsh grass, occasional sparse trees, and open-water pools over about 10% of it | Marsh broken up by small ponds |
| 95 | Mangroves | Dark grass | Same as herbaceous wetland | Marsh with ponds |
| 100 | Moss and lichen | Dirt, with patches of dark grass for the moss | Clumps of walkable rocks over about 30% of the ground, blocking boulders on about 3%, the odd low bush, and no trees | A rocky tundra field you can still cross |

## Applies on every map

- **Tree density** scales the shrubs, grass tufts and marsh plants. **Forest
  density** scales tree cover, as it does for mapped forest.
- **Random trees and woods** that KnoxMap scatters over unmapped grass are
  skipped wherever WorldCover has a class, so real data replaces the guesses.
- **Roads, paths and buildings** are always cleared of vegetation. Pools and
  blocking boulders never come within 2 tiles of them.
- **The same seed gives the same map** on every rebuild.
- **OSM wetland** tagged `marsh`, `swamp`, `bog` or `reedbed`, or with no
  `wetland` tag, also gets pools. `wet_meadow` does not.
