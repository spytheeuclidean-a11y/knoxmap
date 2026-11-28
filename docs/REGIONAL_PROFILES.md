# Regional profiles: building a country the way it is built

Status: skeleton done (profile type, GB detection); a first pass of every GB
step (1-8) done, several with parts left (see each). First target: Great
Britain (`gb`).

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
3. **Front of the plot.** *First part done* (on top of #202, which stops the
   dense-block apron for tagged houses). `roads._pave_dense_ground(...,
   country="GB")` also leaves `building=yes` outlines up to
   `GB_HOUSE_MAX_M2` (250 m2) unpaved: 4,226 of Cambourne's 4,332 OSM
   `building=yes`. `country` now reaches every chunk of a large map
   (`render_chunked`). Front-garden depth is the mapped position of the
   house; drives are already one car wide (`yards.DRIVE_WIDTH` = 3) and
   terraced houses get none where there is no room.
   Front hedges: done in step 7.
4. **Back of the plot.** *Done.*
   - Garden (`knoxbuild/yards.py`): `GB_YARD_DEPTH` 14 (default 9) and only
     as wide as the house (default tries 2 tiles past each side first), so a
     terrace's gardens are side-by-side strips.
   - Sheds (`generator/rendering/infill._back_sheds(..., country="GB")`):
     2-3 m square, 7-11 m behind the house, inside the house's own width,
     for half the houses from 35 m2 (default: 3-6 x 3-5 m, 4-6 m back, 35%
     of houses from 70 m2, which left every terraced house without one).
   Limit, as before: the garden stops at the shed's row, so the shed stands
   just past the garden fence.
5. **Terraces and semis.** *First part done.* Rows were already cut into
   units wall to wall (`build.row_units`, `footprint.split_row`) and shared
   walls already lose their windows (`_party_walls`). For `gb`:
   - `british_house()`: `building=residential/terrace/terraced` up to 250 m2
     with no tagged third storey is a house, not flats (1,230 of Cambourne's
     1,247).
   - `row_units(..., region="gb")`: houses cut at `GB_TERRACE_FRONTAGE_M`
     (5.5 m, default 9 m); a terrace- or semi-tagged outline splits from 11 m
     (default 22 m), so a semi mapped as one outline is two houses.
   Garages off for terraced houses: done in step 8. Left: untagged semis (`building=yes`, ratio under 2.2) stay one house;
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
   Left: gates in back fences (step 7); ends that turn a corner.
   Cross-links (`_cross_links`): a passage square off the lane through a gap
   in the row (1-4 m clear of buildings) to the street in front, one per gap,
   40 m apart per side. Anfield: 26 links, 574 m, 54% on a mapped alley;
   without the gap-width limit 45 links at 38% (every wider gap was a missing
   house or open ground).
7. **Boundaries.** *First part done* (`knoxbuild/yards.py`).
   - Back: `yard_plan(..., region="gb")` picks `tall_wooden` (75%) or
     `short_wooden` (25%), fenced 95% (default: picket and chain-link too,
     85%).
   - Front: `_front_boundary()` runs a fence along the pavement edge across
     the house's front, found straight out of the front door on the ground as
     it was before paths and drives were painted; broken wherever the path,
     the drive or anything else crosses. `black_metal` (railings, 35%),
     `short_wooden` (25%) or a hedge (40%, bushes on the lawn row at the
     pavement); 30% of front gardens are left open-plan.
   The game has no low brick wall fence, so railings stand in for wall and
   railings. Left: gates in back fences onto back alleys.
8. **Garages and parking.** *First part done.*
   - Lock-ups: `row_units(..., region="gb")` cuts `building=garages` into
     one garage per `GB_LOCKUP_FRONTAGE_M` (5 m; a real lock-up is about 3 m,
     but nothing is cut narrower than `footprint.MIN_ROOM_SIDE`).
   - Kerbside parking: `zones_detect.kerbside_rate(tier, "gb")` takes
     `GB_KERBSIDE_RATES` (residential 0.85, default 0.55; tertiary 0.5,
     default 0.38). Main roads unchanged.
   - Attached garages: a British house's `BuildingProfile.garage_share` is
     `GB_GARAGE_SHARE` (0.15; default `openings.GARAGE_SHARE` 0.4), and 0 for
     any house with a party wall (terraced or semi-detached). The layout's
     `_garage_bay` and `_attach_garage` read it through
     `openings.garage_share(profile)`.

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
