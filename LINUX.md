# KnoxMap on Linux and macOS

Everything KnoxMap does itself is Python, and runs anywhere Python does:
downloading the area from OpenStreetMap, drawing the terrain, laying out and
furnishing the buildings, writing the paper map and installing the mod. Only
one step needs help, and that is **Compile**, which drives the PZ Mapping
Tools. On 64-bit Linux, Setup fetches a build of the map compiler made for
this system, so that needs no help either; anywhere else it is a Windows
program and runs through Wine.

Download `KnoxMap-v…-linux.tar.gz` (or `…-macos.tar.gz`) from
[Releases](https://github.com/spytheeuclidean-a11y/knoxmap/releases/latest),
unpack it, and:

    tar -xzf KnoxMap-v1.3.7-linux.tar.gz
    cd KnoxMap
    ./setup.sh        once
    ./knoxmap.sh      every time

The tarball keeps the executable bit; a zip does not, which is why the
downloads are per system.

If the scripts are not executable after a `git clone` or an unzip:

    chmod +x setup.sh knoxmap.sh

## What setup does

The same as `Setup.bat`: a private Python environment in `.venv`, the PZ
Mapping Tools into `vendor/`, the patched map compiler, and the tile artwork
extracted from **your own copy of the game** — never downloaded.

It needs 64-bit Python 3.12 or newer. A 32-bit one can only address about
2 GB, which a town-sized map runs out of part-way through.

    sudo apt install python3 python3-venv python3-pip     # Debian, Ubuntu
    sudo pacman -S python                                 # Arch
    sudo dnf install python3                              # Fedora

## The window

On Windows KnoxMap opens in a native window (Edge WebView2) and on macOS in
a WKWebView one. On Linux pywebview needs a system toolkit behind it that pip
cannot install, so if there is none KnoxMap **opens in your browser instead**
and prints the address it is serving on. That is the whole app; nothing is
missing from it.

For a real window, install one of the toolkits first and KnoxMap will use it:

    sudo apt install python3-gi gir1.2-webkit2-4.1 python3-gi-cairo   # GTK
    .venv/bin/python -m pip install "pywebview[qt]"                   # or Qt

`KNOXMAP_BROWSER=1 ./knoxmap.sh` forces the browser on any system.

## Compile

On 64-bit Linux there is nothing to install. Setup downloads the map
compiler built for this system — the same program from the same source as
the Windows one, with the Qt it needs beside it — checks its fingerprint and
puts it in `vendor/PZMappingTools/bin/`. No Wine, no Qt to install, and
WorldEd's own log ends up in `logs/worlded/` where you can read it.

On macOS, on a 32-bit or ARM machine, or if that download fails, the map
compiler is the Windows one and KnoxMap runs it through Wine, which a PC
that plays Project Zomboid through Proton already has in some form:

    sudo apt install wine       # or wine64, or your distribution's package

`KNOXMAP_WINE=/path/to/wine ./knoxmap.sh` points KnoxMap at a particular
build — a Proton runtime's, for instance.

### If the compiler will not start

The build for Linux carries its own Qt, and it has to be the one that loads.
The binary records that folder as DT_RUNPATH, which the loader searches after
`LD_LIBRARY_PATH` - so KnoxMap puts it on the front of `LD_LIBRARY_PATH`
itself before running the compiler. Without that, a machine with its own Qt 5
on it compiled against 5.15.3 and loaded 5.15.13, and Qt aborted the run:

    Cannot mix incompatible Qt library (5.15.13) with this library (5.15.3)

Setup runs the compiler once after installing it and says so if it will not
start. If it still happens, something is putting a Qt ahead of the bundled
one: start KnoxMap from a plain terminal rather than from Steam, or clear
`LD_LIBRARY_PATH` for it. `KNOXMAP_QT_PLATFORM` overrides the platform
plugin, which is `offscreen` because a compile draws nothing.

This system also has to be Ubuntu 22.04's vintage or newer - the build
leaves the C library and libstdc++ to the machine. On anything older,
install wine and KnoxMap will use the Windows build instead.

With neither, every step except Compile works, and the window says so under
**Setup isn't finished**. You can still finish a map by hand: use **Open in
WorldEd** and run *BMP To TMX → All Cells* and *Generate Lots → All Cells*
yourself, then **Install**.

If you build the tools natively (see `worlded/README.md`), drop the
binaries in `vendor/PZMappingTools/bin/` **without** the `.exe` — KnoxMap
finds `PZWorldEd_cli` as readily as `PZWorldEd_cli.exe`, runs it directly,
and setup leaves it alone.

## Where things are found

- **The game**, and the mods folder it installs into, come from Steam:
  `~/.steam/steam`, `~/.local/share/Steam`, the Flatpak
  (`~/.var/app/com.valvesoftware.Steam/…`) and Snap paths, plus every
  library `libraryfolders.vdf` names. Libraries on a second disk are looked
  for under `/mnt`, `/media`, `/run/media` and your home folder.
- **Saves and mods** are in `~/Zomboid`, as on Windows. `ZOMBOID_DIR` moves
  that if yours is somewhere else.
- If a library is somewhere none of this looks, add it in the window under
  **Steam libraries**, or set `KNOXMAP_STEAM_FOLDERS=/path/one;/path/two`.

## Proton and the game's memory

A big map needs more memory than Project Zomboid gives itself. Under Proton
the setting is in the same place as on Windows — `ProjectZomboid64.json` in
the game folder — and a map's mod folder carries a `HOW TO PLAY.txt` saying
what to change when it is big enough to matter.
