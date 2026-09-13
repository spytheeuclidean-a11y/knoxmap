# Licences and credits

This repository combines work under different terms. Please check which part
you are using before reusing it.

## Original Knoxify — arytek, no licence published

KnoxMap is a fork of [arytek/knoxify](https://github.com/arytek/knoxify).
That project has not published a licence, so its author keeps all rights to
it. These files come from it (most have since been modified here):

`README.md` · `app.py` · `generator/__init__.py` · `generator/osm.py` ·
`generator/pz_colors.py` · `generator/renderer.py` · `requirements.txt` ·
`static/css/app.css` · `static/js/app.js` · `static/logo.svg` ·
`templates/index.html` · `test_pipeline.py` · `.gitignore` · `branding/*`

This fork is published through GitHub's fork feature. If you want to reuse
these files beyond that, ask arytek.

## Added in this fork — MIT

See [LICENSE-MIT.txt](LICENSE-MIT.txt). Everything not listed in the other
two sections, including:

`knoxbuild/` · `tools/` · `knoxmap.py` · `knoxmap_setup.py` · `knoxpaths.py` ·
`KnoxMap.bat` · `Setup.bat` · `generator/places.py` · `static/js/fx.js` ·
`static/js/quirks.js` · `KNOXBUILD.md` · `LICENSES.md` · `docs/`

## The map compiler patch — GPL-2.0-or-later

Everything in [`worlded/`](worlded/), and the prebuilt `PZWorldEd_cli.exe` in
this repository's releases, modifies
[PZ Mapping Tools](https://github.com/Unjammer/PZ_Mapping_Tools) (Alree /
Unjammer, built on Tim Baker's TileZed and WorldEd) and is distributed under
the GNU General Public License version 2 or later. See
[worlded/README.md](worlded/README.md) for the corresponding source.

## Things this repository does not contain

- **Project Zomboid artwork.** Setup extracts tile sheets from each player's
  own installed copy of the game. They belong to The Indie Stone and are never
  included here or downloaded from anywhere.
- **PZ Mapping Tools itself.** Setup downloads the official release from its
  own GitHub page.

## Data and services

- **Map data** © [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors, available under the Open Database License. Maps you generate
  are built from it and should credit "© OpenStreetMap contributors" if you
  share them.
- **Overpass API** and **Nominatim** are free community services with usage
  policies; KnoxMap identifies itself and keeps to one search a second.
- **Map tiles** in the app: OpenStreetMap standard tiles (subject to the
  [tile usage policy](https://operations.osmfoundation.org/policies/tiles/))
  and Esri World Imagery for the satellite view.
- **Leaflet** (BSD-2-Clause) and **Leaflet.draw** (MIT), loaded from unpkg.
  **Fonts**: Oswald, Inter and JetBrains Mono (SIL Open Font License), from
  Google Fonts.

## Not affiliated

KnoxMap is an unofficial fan project. It is not made, endorsed or supported by
The Indie Stone. Project Zomboid is a trademark of The Indie Stone.
