# Licences and credits

This repository combines work under different terms. Please check which part
you are using before reusing it.

## Original Knoxify — arytek, no licence published

KnoxMap is a fork of [arytek/knoxify](https://github.com/arytek/knoxify).
That project has not published a licence, so its author keeps all rights to
it. These files come from it (most have since been modified here):

`README.md` · `app.py` · `generator/__init__.py` · `generator/osm.py` ·
`generator/pz_colors.py` · `generator/renderer.py` · `requirements.txt` ·
`static/css/app.css` · `static/js/app.js` ·
`templates/index.html` · `test_pipeline.py` · `.gitignore`

The KnoxMap logo and cover (`branding/*`, `static/logo.svg`) are new to this
fork and replace Knoxify's own artwork; they are under the MIT licence below.

If you want to reuse
these files beyond that, ask arytek.

## Added in this fork — MIT

See [LICENSE-MIT.txt](LICENSE-MIT.txt). Everything not listed in the other
two sections, including:

`knoxbuild/` · `tools/` · `knoxmap.py` · `knoxmap_setup.py` · `knoxpaths.py` ·
`KnoxMap.bat` · `Setup.bat` · `generator/places.py` · `static/js/fx.js` ·
`KNOXBUILD.md` · `LICENSES.md` · `CHANGELOG.md` ·
`CONTRIBUTING.md` · `.github/` · `docs/`

## The map compiler patch — GPL-2.0-or-later

Everything in [`worlded/`](worlded/), and the prebuilt `PZWorldEd_cli.exe` in
this repository's releases, modifies
[PZ Mapping Tools](https://github.com/Unjammer/PZ_Mapping_Tools) (Alree /
Unjammer, built on Tim Baker's TileZed and WorldEd) and is distributed under
the GNU General Public License version 2 or later. Each compiler release
carries the binary's complete corresponding source (`PZWorldEd_cli-source.zip`,
made by `worlded/make_release.py`), the licence text and a written source
offer. See [worlded/README.md](worlded/README.md) and
[docs/LEGAL.md](docs/LEGAL.md#the-map-compiler-gnu-gpl-version-2).

## Things this repository does not contain

- **Project Zomboid artwork.** Setup extracts tile sheets from each player's
  own installed copy of the game. They belong to The Indie Stone and are never
  included here or downloaded from anywhere.
- **PZ Mapping Tools itself.** Setup downloads the official release from its
  own GitHub page.
- **The Elevators mod.** KnoxMap lays out lifts the way that mod recognises
  them; the mod is a separate work, installed by players from the Steam
  Workshop.

Some pictures in `docs/images/` (`roads_ingame_tiles.jpg`) are drawn from
Project Zomboid's tile artwork by `tools/render_ground.py`. That artwork is
© The Indie Stone and is shown only to illustrate what KnoxMap produces; it is
not covered by this repository's licences. Pictures made from map data
(`nyc_midtown.png`, `shape_circle.png`, `app.jpg`) contain OpenStreetMap data
and tiles, © OpenStreetMap contributors.

## Data and services

- **Map data** © [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors, available under the Open Database License. Maps you generate
  are built from it and should credit "© OpenStreetMap contributors" if you
  share them.
- **Overpass API** and **Nominatim** are free community services with usage
  policies; KnoxMap identifies itself and keeps to one search a second.
- **Map tiles** in the app: OpenStreetMap standard tiles, fetched through
  KnoxMap's local server under the
  [tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
  (There is no satellite view: Esri's imagery terms do not cover this use.)
- **Bundled in `static/vendor/`**, each with its licence text beside it:
  **Leaflet** 1.9.4 (BSD-2-Clause, © Volodymyr Agafonkin), **Leaflet.draw**
  1.0.4 (MIT, © Jon West, Jacob Toye and Leaflet).

## Not affiliated

KnoxMap is an unofficial fan project. It is not made, endorsed or supported by
The Indie Stone. Project Zomboid is a trademark of The Indie Stone.
