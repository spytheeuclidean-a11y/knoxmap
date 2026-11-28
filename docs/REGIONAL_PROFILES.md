# Regional profiles: building a country the way it is built

Status: skeleton done (profile type, GB detection); GB step 1 (materials and
roofs) done. First target: Great Britain (`gb`).

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
- `knoxbuild/settings.py`: `arch_style` (`auto`, `cn`, `off`), shown in the
  window as Auto / Chinese / Default. `region_override` (auto or an ISO code)
  is also a setting, but nothing reads it.
- `knoxdata/natural_earth.py`: `country_at(lat, lon)` returns `{iso, name}`
  from the Natural Earth countries layer (downloaded and cached; `None` when
  it cannot be had). `web/generation.py` runs the data layers before the map
  is drawn and saves the country as `region` in `<map>_knoxdata.json`
  (Cambourne: `"GB"`).
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

### 2. Detection (done in the skeleton)

- `detect_region(geo, bbox, country)`: script of the names first (`cn`, `jp`,
  `kr`, as before). If the names are Latin, the recorded country decides
  through `COUNTRY_REGIONS` (`{"GB": "gb"}`). With no names, the old boxes
  first (rural China), then the country.
- `country` comes from `map_country(out_dir, map_name)`, which reads
  `region` from `<map>_knoxdata.json`. No generator change was needed.
- No country on record (older map, Natural Earth unreachable): a GB box,
  (-6.0, 49.8, 1.8, 60.9). It stops east of Dublin, so Ireland stays
  default; Northern Ireland and the Outer Hebrides fall outside too and build
  the default way offline.
- No new `arch_style` value: it is in the window, and the user should not
  pick a region. Auto finds GB; Default turns it off.
- `profile(region)` returns a `Profile`; anything without one (`jp`, `kr`,
  `None`) is `us`. `Profile` has only `code` until a GB step adds a field.

**Still open for generator-stage knobs (items 3, 4):** the generator draws
aprons and sheds before the build runs and does not import `knoxbuild`. When
the first of those lands, `Profile` and `detect_region` move where both can
read them (or the generator reads the region from the knoxdata country
itself), and `arch_style` has to reach the generator.

### 3. The GB profile, in delivery order

Each item is its own PR, checked on Cambourne in-game, like the fixes of
27 Nov 2026. Cheapest and most visible first.

1. **Materials and roofs.** *Done.* `gb_house_styles()` (`GB_BASES`): the
   catalog's brick (half the pool), render, stucco and painted styles with
   their own pitched roofs, shutters removed. No clapboard, sidings, timber,
   logs or panel. `pick_style` uses it for every GB house, dated ones too,
   and before the Melos/Erika mod styles, as `cn` does. The catalog has one
   brick wall tile; more brick colours would need new verified entries.
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
