# Regional profiles: building a country the way it is built

Status: skeleton done (profile type, GB detection); GB steps 1 (materials and
roofs), 2 (storeys), 5 (terraces and semis, first part) and 6 (back alleys,
first part) done. First target: Great Britain (`gb`).

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
2. **Storeys.** *Done.* `GB_AREA_OVERRIDES` for untagged houses: up to
   60 m2 mostly 2 storeys, the odd 3 (terraces, semis, town houses); 60-120 m2
   mostly 2 with about one bungalow in six; larger 2-3. Default US reads a
   45 m2 footprint as a bungalow three times in four.
   **Found for step 5:** `building=residential` and `building=terrace` map to
   the `apartment` kind (`build.py` kind table), so British houses tagged that
   way (1,246 `residential` in Cambourne) get the 3-5 storey flats tables.
3. **Front of the plot.** Shallow front gardens (2-4 m), no 6-tile apron on
   houses (`roads.DENSE_APRON_TILES` -> profile; #202 already stops it for
   tagged houses), a short path or a single-car drive instead of a wide
   apron.
4. **Back of the plot.** Long narrow back gardens; sheds smaller and at the
   far end of the garden (`infill.SHED_SETBACKS`, `SHED_SIZE_M`,
   `SHED_SHARE`).
5. **Terraces and semis.** *First part done.* Rows were already cut into
   units wall to wall (`build.row_units`, `footprint.split_row`) and shared
   walls already lose their windows (`_party_walls`). For `gb`:
   - `british_house()`: `building=residential/terrace/terraced` up to 250 m2
     with no tagged third storey is a house, not flats (1,230 of Cambourne's
     1,247).
   - `row_units(..., region="gb")`: houses cut at `GB_TERRACE_FRONTAGE_M`
     (5.5 m, default 9 m); a terrace- or semi-tagged outline splits from 11 m
     (default 22 m), so a semi mapped as one outline is two houses.
   Left: garages off for terraced houses (the garage bay is #200, not in this
   stack); untagged semis (`building=yes`, ratio under 2.2) stay one house;
   address points as cut positions.
6. **Back alleys.** *First part done.* Mapped `service=alley` already draws
   as a 3.5 m lane (`road_service`, at least 3 tiles) and footways as 2.5 m
   paths. `generator/rendering/alleys.py` `back_alleys()` adds the unmapped
   ones: pairs of terraced houses (joined to a neighbour) whose backs face
   across a 3-30 m strip give midpoints; at least 4 pairs in line and 30 m
   make a lane, run on to a street where the gap between the end houses
   allows, cut where it would cross a building, skipped where a mapped way
   already runs. Added as `service=alley` ways once, at the top of
   `renderer.render`, for `country == "GB"`; `web/generation.py` passes the
   Natural Earth country (none when `arch_style` is Default).
   **The region now reaches the generator** (`render(country=...)`), which
   steps 3 and 4 need too.
   Measured (Anfield, Liverpool, mapped alleys removed): 79% of the drawn
   length lies on a real alley; it finds 38% of the mapped length - OSM maps
   alleys as networks with cross-links, which this does not draw. Cambourne:
   12 lanes, 555 m, on its rows of joined houses.
   Left: gates in back fences (step 7); cross-links; ends that turn a corner.
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
