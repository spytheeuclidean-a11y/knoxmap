# Legal notes

What KnoxMap has to respect, where each rule comes from, and how it is met.
Written in good faith by the project, not by a lawyer, and **not legal advice**.
Checked September 2026; terms change, so follow the links for the current text.

## OpenStreetMap data: Open Database License (ODbL)

Source: [openstreetmap.org/copyright](https://www.openstreetmap.org/copyright) ·
[Attribution Guidelines](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines) ·
[Produced Work guideline](https://osmfoundation.org/wiki/Licence/Community_Guidelines/Produced_Work_-_Guideline)

| Requirement | How KnoxMap meets it |
|---|---|
| Credit "OpenStreetMap" and say the data is under the ODbL, linking to the copyright page where possible. | The app's map shows "© OpenStreetMap contributors" linked to the copyright page, bottom right. The README and LICENSES.md credit it. |
| A game or other produced work may carry the credit in its menus, credits, loading screen or game view, legibly. | Every generated map shows "Map data (c) OpenStreetMap contributors" on the in-game paper map and in the mod's description in the Mods menu. |
| A map, image or game world made from OSM data is a *Produced Work*. Whoever publishes one must credit OSM and make available the data used, or the method of deriving it (ODbL 4.6). | Each installed mod gets an `ATTRIBUTION.txt` giving the credit, the area and date of the data, and a link to KnoxMap's open-source method. |

**Your part, if you publish a map** (Steam Workshop or anywhere else): keep
`ATTRIBUTION.txt` in the mod, and credit "Map data © OpenStreetMap contributors"
on the mod's page.

## OpenStreetMap services

### Tile server
Source: [Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/)

| Requirement | How KnoxMap meets it |
|---|---|
| Installed apps must send their own User-Agent naming the app, never a browser's. | Tiles are fetched by KnoxMap's local server (`/tiles` in `app.py`) with `KnoxMap/1.0 (+repository URL)`, not by the app window. |
| Honour caching headers, or cache for at least 7 days. | Tiles are kept in `cache/tiles` for the longer of 7 days and the server's `max-age`, and revalidated with `If-None-Match`. |
| No bulk downloading, pre-seeding or offline use. | Only tiles the map is showing are requested, at most two at a time. |
| Attribution visible on the map. | Bottom right, not hidden. |

### Nominatim (place search)
Source: [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/)

| Requirement | How KnoxMap meets it |
|---|---|
| At most one request per second. | `generator/places.py` throttles searches to one a second. |
| Identify the application. | Every request sends KnoxMap's User-Agent. |
| No autocomplete search. | Searching runs only when you press Enter. |
| Cache results. | Repeated searches are answered from a 24-hour cache. |
| No bulk or systematic geocoding. | KnoxMap only searches what you type. |

The policy asks that code integrating Nominatim point to it prominently: this
is that pointer, and `places.py` and the README link to it too.

### Overpass API (map data downloads)
Source: [Overpass API commons](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html)

Public instances expect roughly **under 10,000 requests and 1 GB per day** per
user. KnoxMap identifies itself, splits large areas into a modest number of
queries, backs off when refused, and caches every download next to the map so
regenerating an area does not download it again. Very large or repeated use
should run its own Overpass instance.

### Satellite imagery
KnoxMap used to offer Esri World Imagery as a background. Esri's
[terms](https://www.esri.com/en-us/legal/terms/web-site-service) cover use
outside ArcGIS only under its Master Agreement, so the satellite view was
removed.

## Project Zomboid and The Indie Stone

Source: [Project Zomboid Terms & Conditions](https://store.steampowered.com/eula/108600_eula_1) ·
[Modding Policy](https://projectzomboid.com/blog/modding-policy/)

| Requirement | How KnoxMap meets it |
|---|---|
| Changing base files is allowed as long as the game is not made available and nothing enables cheating or harm (Terms 2.1). | Setup only *reads* tile artwork from the player's installed game into the map tools' folder on that PC. Nothing from the game is uploaded or redistributed. |
| Game assets may be used for non-commercial creative work that promotes the game, with this exact credit (Terms 2.2). | README and each mod's `ATTRIBUTION.txt` carry the credit quoted below. The only asset use in this repository is illustrative renders of tiles in `docs/images`. |
| Mods must comply with the Modding Policy (Terms 2.6): not appear official, not be sold, credit third-party content, nothing harmful or objectionable. | KnoxMap and its maps are marked unofficial and free; third-party work is credited in LICENSES.md. |
| Publishing a mod grants The Indie Stone a non-exclusive, permanent, royalty-free licence to use it in connection with the game. | Noted in the README for anyone publishing a map. |

The credit, as the Terms require it:

> Thanks to The Indie Stone for creating Project Zomboid (https://projectzomboid.com/),
> which made this possible. This is an unofficial fan production for non-commercial
> purposes made under the Indie Stone Terms (https://projectzomboid.com/blog/support/terms-conditions/).

## The map compiler: GNU GPL version 2

Source: [GPL-2.0](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html)

`PZWorldEd_cli.exe` is a modified build of PZ Mapping Tools, which is GPL-2.0
(or later where a file says so).

| Requirement | How KnoxMap meets it |
|---|---|
| Modified files carry a notice that they were changed, and when (2a). | `worlded/patch_worlded_cli.py` appends one to both files it changes. |
| The modified program is under the GPL (2b). | `worlded/` and the binary are GPL; LICENSES.md says so. |
| A binary comes with its complete corresponding source, including build scripts, from the same place (3a), or a written offer (3b). | Each compiler release carries `PZWorldEd_cli-source.zip` (the upstream tree at the pinned commit with the patch applied, plus build scripts), the licence text, and a written offer for three years. `worlded/make_release.py` builds these. |
| Qt (LGPL) sources for Qt binaries. | The release does not include Qt; it comes with PZ Mapping Tools, which gives its own source offer. |

## Code from other projects

- **Knoxify** (arytek) has **no published licence**, so its author keeps all
  rights. GitHub's Terms of Service let others view and fork public
  repositories on GitHub, which is how this project's public release is meant
  to be published (as a fork). Asking arytek to add a licence would settle it.
  Until then, reuse of those files outside a GitHub fork needs arytek's
  permission.
- **PZ Mapping Tools** is downloaded by Setup from its official release, not
  included here.
- **Leaflet** (BSD-2-Clause), **Leaflet.draw** (MIT) and the fonts **Oswald,
  Inter and JetBrains Mono** (SIL Open Font License 1.1) are bundled in
  `static/vendor/` with their licence texts, as all three licences require
  when redistributing.
- Python dependencies (Flask, Pillow, requests, pyproj, shapely, numpy,
  pywebview) are installed by pip from PyPI under their own permissive
  licences, and are not included in this repository.
- The **Elevators** mod is not included or modified. KnoxMap only builds lifts
  the way that mod recognises them, from vanilla tile names.

## Privacy

KnoxMap has no accounts, telemetry or analytics. While it runs, your PC
contacts:

- OpenStreetMap's tile server, Nominatim and Overpass servers, for the map,
  searches and map data (these see your IP address and what you look up);
- GitHub, once during setup, to download PZ Mapping Tools and the compiler.

The map library and fonts are bundled, so no CDN or font service is contacted.

Your searches and chosen areas are not sent anywhere else.
