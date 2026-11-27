# Regional profiles: building a country the way it is built

Status: design, not started. First target: Great Britain (`gb`).

## Why

KnoxMap builds every town like the game's Knox County: detached weatherboard
houses one or two storeys tall, deep front lawns, driveways with concrete
aprons, attached garages. That is right for Kentucky and wrong for most of
the world. A British estate is terraces and semis in brick and render, small
front gardens behind low walls, long narrow back gardens, back alleys between
rows, on-street parking and lock-up garage blocks.

Tested on Cambourne (Cambridgeshire). It shows the gap: square US-style yards,
wide paving, sheds where the gardens should be, garages on terraced houses.

## What exists

- `knoxbuild/regional.py`: `detect_region(geo, bbox)` returns `cn`, `jp` or
  `kr` from the script of the map's building names, with rough country
  boxes as a fallback when nothing is named. Only `cn` changes anything:
  `cn_house_styles()` (catalog styles with flat roofs and no shutters) and the
  storey tables (`CN_DEFAULT_LEVELS`, `area_level_pool`).
- `knoxbuild/settings.py`: `arch_style` (`auto`, `cn`, `off`). It is a
  setting, but the window does not show it.
- `knoxdata/natural_earth.py`: `country_at(lat, lon)` returns `{iso, name}`
  from the Natural Earth countries layer (downloaded and cached; `None` when
  it cannot be had).
- `region` is threaded through `knoxbuild/build.py` as a bare string and
  tested with `== "cn"` in 4 places.

### The ordering problem

The map is made in two stages. The generator (`generator/renderer.py`) draws
the ground, roads, aprons, yards, address houses and back sheds into the BMPs
and `<map>_buildings.geojson`. Then `knoxbuild.build` reads those files and
detects the region (`build.py`, after the BMPs are loaded). So today the
region is unknown to every generator-stage decision, which is where most of
the British look is made (aprons, sheds, front setbacks).

## Design

### 1. One profile object, US values as the defaults

New `knoxbuild/regional.py` type, roughly:

```python
@dataclass(frozen=True)
class Profile:
    code: str = "us"                   # "us", "cn", "gb", ...
    house_styles: str = "default"      # which style pool (see 3.1)
    default_levels: dict = ...         # today's tables
    front_setback_m: float = 2.0       # ADDRESS_SETBACK_M
    dense_apron_tiles: int = 6         # roads.DENSE_APRON_TILES
    shed_setbacks: tuple = (6, 5, 4)   # infill.SHED_SETBACKS
    shed_size_m: tuple = ((3.0, 6.0), (3.0, 5.0))
    garage_share: float = 0.4          # openings.GARAGE_SHARE (after #200)
    ...

PROFILES = {"us": Profile(), "cn": Profile(code="cn", ...), "gb": Profile(code="gb", ...)}
def profile(code: str | None) -> Profile
```

Each module reads its knob from the active profile instead of its own module
constant. The constants stay as the `us` defaults, so a US map comes out
byte-identical. `cn` moves its existing special cases into its profile; the
`region == "cn"` tests become profile fields.

A knob joins `Profile` only when a GB step needs it. No speculative fields.

### 2. Detection: decided once, in the generator, saved with the map

- Order in `detect_region`: script of the names first (`cn`, `jp`, `kr`, as
  now); if the names are Latin or there are none, `country_at()` at the bbox
  centre; then the existing boxes. Only codes with a profile are returned;
  everything else is `None`, which is `us`.
- Called once at the start of the generator stage and written to
  `<map>_info.json` as `"region"`. `knoxbuild.build` reads it from there
  instead of detecting again. A map folder from before this has no key and is
  detected as today.
- `arch_style` gains `gb` (and any later code) as forcing values. It is not
  added to the window: the user never picks a region.
- Offline: when Natural Earth cannot be downloaded or isn't cached, fall back
  to a GB box in `_BOXES` (-8.7, 49.8, 1.8, 60.9). Northern Ireland is
  included; Ireland (`IE`) is not, to start with.

### 3. The GB profile, in delivery order

Each item is its own PR, checked on Cambourne in-game, like the fixes of
27 Nov 2026. Cheapest and most visible first.

1. **Materials and roofs.** A `gb_house_styles()` pool built like
   `cn_house_styles()`: only catalog entries that are already shipped and
   verified. Brick (red/brown), render, pebble-dash; pitched roofs; no
   clapboard, logs, sidings or shutters. Lives in `build.py` house-style
   choice (today line ~901).
2. **Storeys.** Default 2; small footprints (bungalows) 1; narrow tall
   terraced footprints in town centres 3. Via `area_level_pool`.
3. **Front of the plot.** Shallow front gardens (2-4 m), no 6-tile apron on
   houses (`roads.DENSE_APRON_TILES` -> profile; #202 already stops it for
   tagged houses), a short path or a single-car drive instead of a wide
   apron.
4. **Back of the plot.** Long narrow back gardens; sheds smaller and at the
   far end of the garden (`infill.SHED_SETBACKS`, `SHED_SIZE_M`,
   `SHED_SHARE`).
5. **Terraces and semis.** Long residential footprints split into narrow
   houses side by side, using address points where OSM has them
   (`houses_from_addresses`); party walls with no windows. Garages off for
   terraced houses. Needs a look at how Cambourne's 51/53/55 split was done
   before designing.
6. **Back alleys.** Keep `highway=service, service=alley` and alley footways
   as narrow paved lanes on the ground. Where two back-to-back rows of
   terraces leave a strip with no mapped way, add a 2-3 m alley with a gate
   in each back fence.
7. **Boundaries.** Low brick walls or hedges at the front, close-board
   wooden fences between back gardens (`knoxbuild/fences.py`,
   `knoxbuild/yards.py`).
8. **Garages and parking.** Lower `garage_share`; rows of lock-up garages
   where OSM maps `building=garages`; on-street parking in place of
   driveways.

## Not in scope

- Interiors and furniture (British kitchens, no basements) - later.
- Driving on the left (car spawn direction) - check whether the game cares.
- Other countries. The point of the profile is that `de`, `fr`, `nl` and so
  on can follow, each as data plus the steps it needs.
- A user-facing region picker.

## Testing

- Every PR: US output unchanged. A regression map from
  `tools/regression_maps.py` built before and after must match.
- Unit tests per knob (profile lookup, detection order, offline fallback).
- In-game on Cambourne for every visible step; screenshots in the PR.

## Open questions

- Is Natural Earth always available in the generator stage, or does the
  offline box have to carry the load?
- Should Ireland share `gb` at first? Its housing is close; its roads are not
  the issue.
- Terrace splitting: where does the current split live, and how good are
  Overture/OSM address points in UK towns?
