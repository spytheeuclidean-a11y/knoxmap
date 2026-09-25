"""Where everything KnoxMap depends on lives, on whichever PC it runs on.

Nothing here assumes a particular machine. Each location is looked up in this
order, and the first that exists wins:

1. an environment variable, for people who keep things somewhere unusual
2. knoxmap_config.json next to this file, which Setup writes
3. the place Setup installs to by default, inside this folder
4. well-known locations (Steam libraries, ~/Zomboid)
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "knoxmap_config.json"
VENDOR_DIR = BASE_DIR / "vendor"


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(values: dict) -> None:
    config = load_config()
    config.update({k: str(v) for k, v in values.items() if v})
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def _first(*candidates) -> Path | None:
    for c in candidates:
        if c and _exists(Path(c)):
            return Path(c)
    return None


def mapping_tools_dir() -> Path | None:
    """The PZ Mapping Tools folder (the one holding bin/ and config/)."""
    return _first(
        os.environ.get("PZ_MAPPING_TOOLS"),
        load_config().get("mapping_tools"),
        VENDOR_DIR / "PZMappingTools",
        BASE_DIR.parent / "PZMappingTools",     # the layout this grew up in
    )


def _tool(name: str, override: str) -> Path | None:
    """One of the map tools' programs: the Windows build, or a Linux one built
    from the same source beside it (see worlded/README.md)."""
    chosen = os.environ.get(override)
    if chosen and _exists(Path(chosen)):
        return Path(chosen)
    tools = mapping_tools_dir()
    if not tools:
        return None
    for candidate in (tools / "bin" / f"{name}.exe", tools / "bin" / name):
        if _exists(candidate):
            return candidate
    return None


def worlded_cli() -> Path | None:
    """The patched, headless map compiler (PZWorldEd_cli)."""
    return _tool("PZWorldEd_cli", "PZWORLDED_CLI")


def worlded_gui() -> Path | None:
    return _tool("PZWorldEd", "PZWORLDED")


def command_for(program: Path | str) -> list[str]:
    """How to run one of the map tools here.

    A build for this system is run directly. The Windows build off Windows
    goes through Wine, which every Steam-on-Linux machine already has;
    KNOXMAP_WINE names a different one.
    """
    program = str(program)
    if os.name != "nt" and program.lower().endswith(".exe"):
        return [os.environ.get("KNOXMAP_WINE", "wine"), program]
    return [program]


def through_wine(program: Path | str | None = None) -> bool:
    """Whether running this tool means going through Wine.

    `program` defaults to the compiler, which is what writes the maps and so
    decides what the paths in a project have to look like.
    """
    if os.name == "nt":
        return False
    if program is None:
        program = worlded_cli()
    return bool(program) and str(program).lower().endswith(".exe")


def tool_env(program: Path | str | None = None) -> dict[str, str]:
    """The environment one of the map tools is run in.

    A native build is a Qt program, and it has to find *its own* Qt. The
    build for Linux travels with the exact Qt it was compiled against, in
    `lib/` beside the binary, and the binary records that folder - but as
    DT_RUNPATH, which the loader searches *after* LD_LIBRARY_PATH. Steam and
    Proton both export LD_LIBRARY_PATH, and a distribution with its own Qt 5
    on it then wins: the program was built against 5.15.3, loaded 5.15.13,
    and Qt killed it on the spot with

        Cannot mix incompatible Qt library (5.15.13) with this library
        (5.15.3)

    which is exit -6 in the middle of a compile and no map. So the bundled
    folder goes on the front of LD_LIBRARY_PATH, ahead of anything the
    machine already had there.

    Qt also will not start without a platform plugin - not even to compile a
    map, which draws nothing on screen. Only the offscreen and minimal
    plugins are bundled, so an inherited QT_QPA_PLATFORM naming any other
    (wayland, xcb) could only fail; the compile is headless whatever the
    desktop is. KNOXMAP_QT_PLATFORM overrides it for anyone who needs to.
    """
    env = dict(os.environ)
    if os.name == "nt":
        return env          # the Windows build brings its own Qt platform
    if program is None:
        program = worlded_cli()
    if not program or through_wine(program):
        return env
    beside = Path(program).parent
    libs = beside / "lib"
    if _is_dir(libs):
        already = env.get("LD_LIBRARY_PATH") or ""
        env["LD_LIBRARY_PATH"] = (f"{libs}{os.pathsep}{already}" if already
                                  else str(libs))
    plugins = beside / "plugins"
    if _is_dir(plugins / "platforms"):
        env["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugins / "platforms")
        env["QT_PLUGIN_PATH"] = str(plugins)
    env["QT_QPA_PLATFORM"] = os.environ.get("KNOXMAP_QT_PLATFORM", "offscreen")
    return env


# Qt's own words when a program built against one Qt loads another. It is a
# hard abort inside Qt's start-up, before any of WorldEd's code runs, so it
# looks like a crash rather than a configuration problem.
QT_MISMATCH = re.compile(
    r"Cannot mix incompatible Qt library \(([\d.]+)\) with this library \(([\d.]+)\)")
# The loader could not find a library at all, or Qt could not find a plugin.
LOADER_TROUBLE = re.compile(
    r"error while loading shared libraries|"
    r"no Qt platform plugin could be initialized|"
    r"symbol lookup error|version `[A-Z_]+[\d.]+' not found")


def qt_trouble(output: str) -> str | None:
    """A plain explanation of a Qt or loader failure in a tool's output.

    Returned for the message the window shows, because the raw one names two
    version numbers and nothing a person can act on.
    """
    if not output:
        return None
    found = QT_MISMATCH.search(output)
    if found:
        loaded, built = found.group(1), found.group(2)
        return (f"the map compiler loaded Qt {loaded} from this system instead of "
                f"the Qt {built} it ships with. Something on LD_LIBRARY_PATH is "
                f"ahead of it - Steam and Proton both set that. Start KnoxMap from "
                f"a plain terminal, or run it with LD_LIBRARY_PATH= emptied")
    if LOADER_TROUBLE.search(output):
        return ("the map compiler could not load the libraries it needs. If this "
                "system is older than Ubuntu 22.04 the build for Linux will not "
                "run on it; install wine and KnoxMap will use the Windows build "
                "instead (see LINUX.md)")
    return None


def compiler_trouble(timeout: float = 20.0) -> str | None:
    """Whether the map compiler can start on this system at all, in words.

    Runs it once against a project that is not there. What is being checked
    is only that the binary loads and Qt starts; anything past that is
    WorldEd's own complaint about the missing file, which is a pass. A Qt
    that cannot start aborts inside Qt's own start-up, before WorldEd runs a
    line, so it shows up in the first second or two - and if the program is
    still going when the time is up, it got past the part this is about.

    Returns None when there is nothing to say, which includes every case it
    does not recognise: a check that cries wolf about an unfamiliar warning
    is worse than no check.
    """
    import subprocess

    program = worlded_cli()
    if not program or os.name == "nt" or through_wine(program):
        return None          # the Windows build brings its own Qt
    missing = Path(program).parent / "knoxmap-no-such-project.pzw"
    try:
        proc = subprocess.Popen(
            command_for(program) + [f"--generate-map={tool_path(missing)}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors="replace", env=tool_env(program),
            start_new_session=True)
    except OSError as exc:
        return f"the map compiler at {program} would not start: {exc}"
    try:
        output, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Still running, so Qt is up and this is WorldEd waiting on something
        # of its own. End it and everything it started.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, AttributeError):
            proc.kill()
        proc.communicate(timeout=10)
        return None
    return qt_trouble(output)


def tool_path(path: Path | str) -> str:
    """A path as the map tools will read it.

    A build for this system reads the machine's own names. The Windows build
    under Wine does not: "/home/you/maps/town" means nothing to it.
    """
    return wine_path(path) if through_wine() else str(path)


def venv_python(windowless: bool = False) -> Path:
    """The Python inside KnoxMap's own .venv, whichever PC this is.

    Setup puts it in Scripts/ on Windows and bin/ everywhere else, and only
    Windows has a windowless build. Falls back to the Python running now, so
    a checkout without a .venv still works.
    """
    if os.name == "nt":
        names = ("pythonw.exe", "python.exe") if windowless else ("python.exe",)
        folder = BASE_DIR / ".venv" / "Scripts"
    else:
        names = ("python3", "python")
        folder = BASE_DIR / ".venv" / "bin"
    for name in names:
        if _exists(folder / name):
            return folder / name
    import sys
    if windowless and os.name == "nt":
        beside = Path(sys.executable).with_name("pythonw.exe")
        if _exists(beside):
            return beside
    return Path(sys.executable)


_WINE_PATHS: dict[str, str] = {}


def wine_path(path: Path | str) -> str:
    """A path as the map tools see it, which off Windows is through Wine.

    The tools are Windows programs, so "/home/you/maps/town" means nothing to
    them: Wine shows the whole filesystem as drive Z:, and that is the name
    they can open. `winepath -w` is Wine's own answer and is used when it is
    there; the Z: form it would have produced is the fallback.

    On Windows the path is already what the tools want.
    """
    text = str(path)
    if os.name == "nt":
        return text
    if text in _WINE_PATHS:
        return _WINE_PATHS[text]
    converted = ""
    import shutil
    import subprocess
    tool = shutil.which("winepath")
    if tool:
        try:
            done = subprocess.run([tool, "-w", text], capture_output=True, text=True,
                                  timeout=30, check=False)
            converted = done.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            converted = ""
    if not converted:
        converted = "Z:" + os.path.abspath(text).replace("/", "\\")
    _WINE_PATHS[text] = converted
    return converted


def setup_command() -> str:
    """What to tell the player to run: the setup script this PC has."""
    return "Setup.bat" if os.name == "nt" else "./setup.sh"


def wine() -> str | None:
    """The Wine that runs the map tools off Windows, or None if there is none.

    The tools are Windows programs. A PC that plays Project Zomboid through
    Proton already has Wine in one form or another, but not always on the
    path under that name, so KNOXMAP_WINE can point at any build.
    """
    if os.name == "nt":
        return None
    import shutil
    chosen = os.environ.get("KNOXMAP_WINE")
    if chosen:
        return chosen if (shutil.which(chosen) or _exists(Path(chosen))) else None
    return shutil.which("wine") or shutil.which("wine64")


def tools_runnable() -> bool:
    """Whether the map tools can be run at all on this PC: they are Windows
    programs, so off Windows that needs either Wine or a native build of them
    (one with no .exe on the end)."""
    if os.name == "nt":
        return True
    cli = worlded_cli()
    if cli and not str(cli).lower().endswith(".exe"):
        return True                 # built for this system, run directly
    return wine() is not None


def chosen_steam_folders() -> list[str]:
    """Drives or folders the player named as holding Steam games, in the app
    or in Setup, looked in before anything found automatically. The
    KNOXMAP_STEAM_FOLDERS environment variable adds more, separated by ';'."""
    chosen = [p for p in os.environ.get("KNOXMAP_STEAM_FOLDERS", "").split(";") if p.strip()]
    saved = load_config().get("steam_folders", [])
    if isinstance(saved, str):
        saved = saved.split(";")
    return [p.strip().strip('"') for p in chosen + list(saved) if str(p).strip()]


def save_steam_folders(folders: list[str]) -> None:
    config = load_config()
    config["steam_folders"] = [str(f).strip().strip('"') for f in folders if str(f).strip()]
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    _LIBRARY_CACHE["libraries"] = None


def library_of(folder: str | Path) -> list[Path]:
    """The Steam libraries a folder the player named could mean: the library
    itself, one inside it (a drive's SteamLibrary), or the library a path
    deeper inside it belongs to (…/steamapps/common/ProjectZomboid)."""
    text = str(folder).strip().strip('"')
    if not text:
        return []
    if re.fullmatch(r"[A-Za-z]:?[\\/]?", text):        # "E", "E:" or "E:\"
        text = text[0] + ":\\"
    path = Path(text)
    parts = [p.lower() for p in path.parts]
    if "steamapps" in parts:
        path = Path(*path.parts[:parts.index("steamapps")])
    candidates = [path] + [path / sub for sub in _LIBRARY_NAMES]
    return [c for c in candidates if _is_dir(c / "steamapps")]


# Folders a Steam library is usually called, relative to a drive or a mount
# point. Separators differ, so the two lists are kept apart rather than one
# list with backslashes in it - on Linux "Games\\Steam" is a single file name
# with a backslash in the middle of it.
_LIBRARY_NAMES_NT = ("SteamLibrary", "Steam", "Steam Library", "Games\\Steam",
                     "Games\\SteamLibrary", "Program Files (x86)\\Steam",
                     "Program Files\\Steam")
_LIBRARY_NAMES_POSIX = ("SteamLibrary", "Steam", "Steam Library", "Games/Steam",
                        "Games/SteamLibrary", "steam", "steamlibrary")
_LIBRARY_NAMES = _LIBRARY_NAMES_NT if os.name == "nt" else _LIBRARY_NAMES_POSIX


def steam_libraries_found() -> list[dict]:
    """Every Steam library in use, and whether the player chose it or it was
    found automatically - for the app and Setup to show."""
    chosen = {str(lib).lower() for folder in chosen_steam_folders() for lib in library_of(folder)}
    return [{"path": str(lib), "chosen": str(lib).lower() in chosen} for lib in _steam_libraries()]


_LIBRARY_CACHE: dict = {"at": 0.0, "libraries": None}


def _steam_libraries() -> list[Path]:
    """Every Steam library folder on this PC: the ones the player chose, then
    the ones Steam itself lists, then the usual folders on every drive.

    Remembered for a minute: the page asks several times on every load, and a
    mapped network drive that is not connected can take seconds to answer."""
    import time

    chosen = tuple(chosen_steam_folders())
    if (_LIBRARY_CACHE["libraries"] is not None and _LIBRARY_CACHE.get("chosen") == chosen
            and time.time() - _LIBRARY_CACHE["at"] < 60):
        return list(_LIBRARY_CACHE["libraries"])
    found = _find_steam_libraries()
    _LIBRARY_CACHE.update(at=time.time(), libraries=found, chosen=chosen)
    return list(found)


def _find_steam_libraries() -> list[Path]:
    libraries: list[Path] = [lib for folder in chosen_steam_folders() for lib in library_of(folder)]
    roots: list[Path] = []
    try:
        import winreg

        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            roots.append(Path(winreg.QueryValueEx(k, name)[0]))
                        except OSError:
                            pass
            except OSError:
                pass
    except ImportError:
        pass
    roots += _steam_roots()

    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if not _exists(vdf):
            continue
        libraries.append(root)
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            libraries.append(Path(m.group(1).replace("\\\\", "\\")))
    # Steam keeps listing a library on a drive that has been unplugged or
    # removed; also look for the usual library folders on every drive, for a
    # library Steam's own files do not name.
    if os.name == "nt":
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            libraries += [Path(f"{letter}:\\") / sub for sub in _LIBRARY_NAMES]
    else:
        for place in _mounted_places():
            libraries += [place / sub for sub in _LIBRARY_NAMES]
    seen, unique = set(), []
    for lib in libraries:
        key = str(lib).lower()
        if key not in seen and _is_dir(lib / "steamapps"):
            seen.add(key)
            unique.append(lib)
    return unique


def _steam_roots() -> list[Path]:
    """Where Steam itself is installed, on whichever system this is.

    Linux has the two paths every distribution uses, the Flatpak one (whose
    files live under ~/.var and are invisible to the others), and the Snap
    one; macOS keeps it in Application Support. The libraries on other disks
    are found from libraryfolders.vdf inside whichever of these exists.
    """
    home = Path.home()
    if os.name == "nt":
        return [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / "Steam"]
    return [
        home / ".steam" / "steam",
        home / ".steam" / "root",
        home / ".local" / "share" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
        home / "snap" / "steam" / "common" / ".local" / "share" / "Steam",
    ]


# Where a second disk is mounted, for a library Steam's own files do not name
# - the Linux answer to looking on every drive letter.
_MOUNT_POINTS = ("/mnt", "/media", "/run/media", "/srv", "/games")


def _mounted_places() -> list[Path]:
    """Every mounted disk, plus the home folder: the places a library that
    Steam has forgotten about might be."""
    out = [Path.home()]
    for base in _MOUNT_POINTS:
        root = Path(base)
        if not _is_dir(root):
            continue
        for child in _children(root):
            out.append(child)
            # /run/media/<user>/<disk> on most desktops.
            out.extend(_children(child))
    return out


def _children(path: Path) -> list[Path]:
    try:
        return [p for p in path.iterdir() if p.is_dir()]
    except (OSError, ValueError):
        return []


def _exists(path: Path) -> bool:
    """Path.exists that is False, not an error, for a missing drive, a
    disconnected network share or a folder Windows will not let us read."""
    try:
        return path.exists()
    except (OSError, ValueError):
        return False


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except (OSError, ValueError):
        return False


# Where the game keeps its artwork, which is not the same place on every
# system. Windows and Linux have <game>/media; macOS ships the game as an
# application bundle with everything inside it, and nothing here used to look
# in there - so a Mac install was found and then turned away for having no
# media in it, however the player spelled the path.
_BUNDLE_MEDIA = ("Contents/Java", "Contents/Resources", "Contents/MacOS", "Contents")


def _media_in(root: Path) -> Path | None:
    """The game's media folder at or just inside `root`, or None."""
    if _is_dir(root / "texturepacks"):
        return root                                  # the media folder itself
    if _is_dir(root / "media" / "texturepacks"):
        return root / "media"                        # Windows and Linux
    for sub in ("projectzomboid", "ProjectZomboid"):
        if _is_dir(root / sub / "media" / "texturepacks"):
            return root / sub / "media"              # Linux nested layout
        if _is_dir(root / sub / "texturepacks"):
            return root / sub
    bundles = [root] if root.suffix == ".app" else sorted(root.glob("*.app"))
    for bundle in bundles:
        for inside in _BUNDLE_MEDIA:
            media = bundle.joinpath(*inside.split("/")) / "media"
            if _is_dir(media / "texturepacks"):
                return media
    return None


def pz_media_dir(game: Path | str | None = None) -> Path | None:
    """The game's media folder - the one holding texturepacks.

    Everything that reads the game's artwork or its tile definitions goes
    through here, so the difference between systems is in one place.
    """
    if game is None:
        game = pz_install_dir()
    return _media_in(Path(game)) if game else None


def pz_install_from(answer: Path | str) -> Path | None:
    """Make sense of a folder somebody pasted as their game.

    People paste the Steam library, the common folder inside it, the game
    folder, the application bundle on a Mac, or the media folder itself. They
    all name the same install, so all of them are taken - being told "try
    again" while looking at the game is no way to start.
    """
    path = Path(str(answer).strip().strip('"').strip("'"))
    tries = [path,
             path / "steamapps" / "common" / "ProjectZomboid",
             path / "common" / "ProjectZomboid",
             path / "ProjectZomboid"]
    tries += list(path.parents)[:4]          # pasted from inside the install
    for candidate in tries:
        if _media_in(candidate):
            return candidate
    return None


def pz_install_dir() -> Path | None:
    """The Project Zomboid game folder (the one holding the media folder)."""
    configured = _first(os.environ.get("PZ_INSTALL"), load_config().get("pz_install"))
    if configured:
        return configured
    libraries = _steam_libraries()
    for lib in libraries:
        common = lib / "steamapps" / "common"
        for candidate in (common / "ProjectZomboid", common / "Project Zomboid"):
            if _media_in(candidate):
                return candidate
    # An install folder named something else. One level of each library's
    # common folder is a few dozen names, not a crawl of the disk.
    for lib in libraries:
        for candidate in _children(lib / "steamapps" / "common"):
            if "zomboid" in candidate.name.lower() and _media_in(candidate):
                return candidate
    # A folder the player named themselves that is not a Steam library at all
    # - a copy of the game somewhere of their own. The box asks for a library,
    # but somebody who pastes the game into it means the same thing, and being
    # ignored for it is no help to anybody.
    for folder in chosen_steam_folders():
        found = pz_install_from(folder)
        if found:
            return found
    return None


def is_build42(game: Path | None) -> bool:
    """Whether this install is Build 42, the only one KnoxMap's maps load in.

    Build 42 split the floor tiles into their own *.floor.pack files; Build 41,
    still Steam's default branch for many players, has none.
    """
    media = pz_media_dir(game)
    return bool(media) and any((media / "texturepacks").glob("*.floor.pack"))


ELEVATORS_WORKSHOP_ID = "3780306632"


SPAWN_SELECTOR_WORKSHOP_ID = "3772052709"


def workshop_mod_installed(workshop_id: str, folder: str) -> bool:
    """Whether a mod is on this PC: subscribed on the Workshop in any Steam
    library, or copied into the mods folder under its own name."""
    for lib in _steam_libraries():
        if _is_dir(lib / "steamapps" / "workshop" / "content" / "108600" / workshop_id):
            return True
    return _is_dir(zomboid_user_dir() / "mods" / folder)


ERIKAS_TILES_WORKSHOP_ID = "3346506593"
ERIKAS_TILES_MOD_ID = "Erikas_Tiles"


def erikas_tiles_media() -> Path | None:
    """The media folder of Erika's Tiles, if the mod is on this PC."""
    for lib in _steam_libraries():
        base = lib / "steamapps" / "workshop" / "content" / "108600" / ERIKAS_TILES_WORKSHOP_ID
        if not _is_dir(base):
            continue
        for media in base.glob("mods/*/common/media"):
            if _exists(media / "texturepacks" / "Erikas_Tiles.pack"):
                return media
    return None


def erikas_tiles_ready() -> bool:
    """Erika's Tiles is installed and its sheets are in the map tools, so
    buildings may use them (Setup extracts them)."""
    tools = mapping_tools_dir()
    return bool(erikas_tiles_media() and tools and
                _exists(tools / "Tiles" / "2x" / "walls_decoration_paintings_erika_01.png"))


def elevators_mod_installed() -> bool:
    """Whether the Elevators mod, which runs KnoxMap's lifts, is installed."""
    return workshop_mod_installed(ELEVATORS_WORKSHOP_ID, "Elevators")


def spawn_selector_installed() -> bool:
    """Whether Spawn Selector, which offers the map's landmarks as starts, is installed."""
    return workshop_mod_installed(SPAWN_SELECTOR_WORKSHOP_ID, "SpawnSelector")


def zomboid_user_dir() -> Path:
    """~/Zomboid, where the game keeps saves and mods."""
    configured = os.environ.get("ZOMBOID_DIR") or load_config().get("zomboid_dir")
    return Path(configured) if configured else Path.home() / "Zomboid"
