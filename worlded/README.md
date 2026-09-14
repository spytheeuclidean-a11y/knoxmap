# The patched map compiler

KnoxMap compiles maps without anyone clicking through WorldEd's menus. Stock
WorldEd can only convert a map (`BMP To TMX`) and compile it (`Generate Lots`)
from its File menu, so this folder holds a small patch that adds a headless
switch:

```
PZWorldEd_cli.exe --generate-map=<project.pzw> [--cells=x0,y0,x1,y1]
```

`Setup.bat` downloads a prebuilt `PZWorldEd_cli.exe` from this repository's
releases and checks its SHA-256 fingerprint, so most people never touch this.

## What the patch changes

`patch_worlded_cli.py` edits two files of
[PZ Mapping Tools](https://github.com/Unjammer/PZ_Mapping_Tools) at commit
`4e86b80c505b3d77a2fb5f5675b752da966306f6` (release 43.00B260909):

- **`WorldEd/src/editor/main.cpp`** — adds `--generate-map` and `--cells`.
  Converts only when a cell has no map yet, compiles a batch of cells, and
  waits for the lot manager's own completion before exiting. Modal "Finished!"
  boxes from either step are dismissed, since nobody is there to click them.
- **`WorldEd/src/editor/lotfilesmanager256.h`** — adds one public accessor,
  `isGenerating()`, so the command line can tell when the export has
  genuinely finished.

`patch_rules_b42_trees.py` repoints the tools' `Rules.txt` at tree and flower
tile sheets Build 42 actually ships. Setup runs it for you.

## Building it yourself

Needs Visual Studio 2022 Build Tools (C++ workload), Qt 5.14.2 `msvc2017_64`
and git.

```bat
worlded\build_worlded.bat C:\Qt\5.14.2\msvc2017_64
```

It clones PZ Mapping Tools at the pinned commit, applies the patch and builds.
Copy the resulting `PZWorldEd_cli.exe` into the `bin` folder of PZ Mapping
Tools release 43.00B260909; it links against that release's Qt and editor
libraries.

## Licence

PZ Mapping Tools is licensed under the GNU General Public License version 2
(see its `COPYING` and `licenses/GPL-2.0.txt`). The patch scripts in this
folder contain and modify that code, so **everything in this folder is
distributed under GPL-2.0-or-later**, as is the prebuilt `PZWorldEd_cli.exe`
in this repository's releases. Its complete corresponding source is the
upstream repository at the commit above plus `patch_worlded_cli.py`.

## Releases and the GPL

Each compiler release on GitHub carries four files, built by
`python worlded/make_release.py <PZ_Mapping_Tools checkout> <built exe> <out dir>`:

- `PZWorldEd_cli.exe` - the patched build (its SHA-256 is pinned in `knoxmap_setup.py`);
- `PZWorldEd_cli-source.zip` - its complete corresponding source: the upstream
  tree at the pinned commit with the patch applied, plus these scripts;
- `LICENSE-GPL-2.0.txt` - the licence;
- `README-RELEASE.txt` - build instructions and a written offer of the source
  for at least three years.

The two files the patch changes carry a notice at their end saying so, as
GPL-2.0 section 2(a) requires.
