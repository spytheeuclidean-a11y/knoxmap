"""KnoxMap setup: everything a fresh PC needs, in one go.

    Setup.bat           (or: python knoxmap_setup.py)

Safe to run again at any time; every step checks first and skips what is
already done. What it does:

1. Downloads PZ Mapping Tools (the community map editor, GPL) into vendor/.
2. Downloads the patched PZWorldEd_cli.exe that lets KnoxMap compile maps
   without clicking through WorldEd's menus, and checks its fingerprint.
3. Finds your Project Zomboid install and extracts the tile artwork the map
   tools need from *your own copy of the game*. Game artwork is never
   downloaded or redistributed - it only ever comes from your install.
4. Adjusts the tool configuration for Build 42 and points it at this PC's
   folders.

Nothing is installed outside this folder, and nothing needs admin rights.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import knoxpaths  # noqa: E402

# The exact PZ Mapping Tools release the patched compiler was built from. The
# compiler links against this release's Qt and editor libraries, so the two
# are pinned together rather than following "latest".
TOOLS_RELEASE = "43.00B260909"
TOOLS_URL = ("https://github.com/Unjammer/PZ_Mapping_Tools/releases/download/"
             "43.00B260909/PZ_Mapping_Tools_build20260909f.zip")

REPO = "spytheeuclidean-a11y/knoxmap"
CLI_URL = (f"https://github.com/{REPO}/releases/download/"
           "worlded-cli-20260909f/PZWorldEd_cli.exe")
CLI_SHA256 = "dbae186f1f1f541decd123604ec9fc822d930f8f7c1ec8b17c1b89874628f3e2"

# The same compiler built for Linux, from the same source at the same commit,
# so that making a map there does not go through Wine at all. Upstream
# publishes Windows binaries only, so this one is KnoxMap's: it carries its
# own Qt and its complete source (.github/workflows/worlded-linux.yml).
CLI_LINUX_URL = (f"https://github.com/{REPO}/releases/download/"
                 "worlded-cli-linux-20260909f/PZWorldEd_cli-linux-x86_64.tar.gz")
CLI_LINUX_SHA256 = "9ef88e23cb58e3fe3e1f9b5d901244b59203ec15d1a456f9f5e16d33164bf3af"

USER_AGENT = f"KnoxMap-setup (+https://github.com/{REPO})"


def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(n: int, title: str) -> None:
    say()
    say(f"[{n}/5] {title}")


def download(url: str, what: str) -> bytes:
    import requests

    say(f"      downloading {what} ...")
    with requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True,
                      timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        buf = io.BytesIO()
        done = 0
        for chunk in r.iter_content(1 << 16):
            buf.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r      {done / total:5.0%} of {total / 1e6:.0f} MB", end="", flush=True)
        print()
    return buf.getvalue()


# ---- 1. mapping tools ---------------------------------------------------------------

def ensure_mapping_tools() -> Path:
    step(1, "PZ Mapping Tools")
    existing = knoxpaths.mapping_tools_dir()
    # worlded_gui finds either the Windows build or one compiled for this
    # system, so a native build is not thrown away and downloaded over.
    if existing and knoxpaths.worlded_gui():
        say(f"      found at {existing}")
        return existing

    data = download(TOOLS_URL, f"PZ Mapping Tools {TOOLS_RELEASE} (~40 MB)")
    target = knoxpaths.VENDOR_DIR / "PZMappingTools"
    with tempfile.TemporaryDirectory() as tmp:
        zipfile.ZipFile(io.BytesIO(data)).extractall(tmp)
        # The archive may or may not wrap everything in a top-level folder.
        root = next((p.parent.parent for p in Path(tmp).rglob("PZWorldEd.exe")
                     if p.parent.name == "bin"), None)
        if root is None:
            raise SystemExit("The downloaded archive has no bin/PZWorldEd.exe - "
                             "the release layout may have changed.")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(root, target)
    say(f"      installed to {target}")
    return target


# ---- 2. patched compiler ------------------------------------------------------------

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _install_linux_cli(tools: Path) -> bool:
    """The compiler built for Linux, unpacked into the tools' bin folder.

    It brings its own Qt, so there is nothing to install and no Wine in the
    way. It goes in bin/ beside where the Windows one would be because
    WorldEd takes the folder above the binary as its installation root, and
    that is where its configuration and the tile artwork live.
    """
    import tarfile

    try:
        data = download(CLI_LINUX_URL, "the compiler built for Linux (~29 MB)")
    except Exception as exc:     # noqa: BLE001 - any failure means "use Wine"
        say(f"      could not download it: {exc}")
        return False
    if hashlib.sha256(data).hexdigest() != CLI_LINUX_SHA256:
        say("      the download does not match the expected fingerprint - not installed.")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            try:
                tar.extractall(tmp, filter="data")
            except TypeError:    # Python older than 3.12 has no filter
                tar.extractall(tmp)
        program = next((p for p in Path(tmp).rglob("PZWorldEd_cli") if p.is_file()), None)
        if program is None:
            say("      the archive has no PZWorldEd_cli - the layout may have changed.")
            return False
        bin_dir = tools / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        for item in program.parent.iterdir():
            target = bin_dir / item.name
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(item, target, symlinks=True)
            else:
                shutil.copy2(item, target)
        (bin_dir / "PZWorldEd_cli").chmod(0o755)
    say(f"      installed to {bin_dir / 'PZWorldEd_cli'} - no Wine needed")
    return True


def _say_if_it_will_not_start() -> None:
    """Check the compiler starts, and say what is wrong if it does not.

    A compiler that cannot load its Qt does not fail politely: Qt aborts
    inside its own start-up and the compile dies with exit -6 on the first
    batch of cells, with two version numbers and nothing to act on. Whoever
    hits that has already drawn a map and waited through a build, and the
    answer has nothing to do with the map. Better to find it here, in the
    seconds after the compiler is installed, and say it in words.
    """
    # Before asking, make the bundled Qt outrank anything LD_LIBRARY_PATH
    # names. It is what the check would otherwise catch it failing on.
    fixed = knoxpaths.force_bundled_qt()
    if fixed:
        say(f"      pointed {fixed} files at the Qt they ship with")
    trouble = knoxpaths.compiler_trouble()
    if trouble:
        say("")
        say(f"      WARNING: {trouble}.")
        say("      Compile will fail until that is sorted; everything else works.")


def ensure_patched_cli(tools: Path) -> bool:
    step(2, "Patched map compiler (PZWorldEd_cli)")
    native = knoxpaths.worlded_cli()
    if native and not str(native).lower().endswith(".exe"):
        say(f"      found a build for this system at {native}")
        _say_if_it_will_not_start()
        return True
    # On Linux the compiler is fetched for this system rather than run
    # through Wine. Anywhere else, and on any other processor, the Windows
    # build is still the one there is.
    if sys.platform.startswith("linux") and platform.machine() in ("x86_64", "AMD64"):
        if _install_linux_cli(tools):
            _say_if_it_will_not_start()
            return True
        say("      falling back to the Windows build, which needs Wine")
    exe = tools / "bin" / "PZWorldEd_cli.exe"
    if exe.exists():
        have = sha256(exe)
        previous = knoxpaths.load_config().get("cli_sha256")
        # A compiler this setup installed, from an older release, is replaced
        # by the new one; one somebody built themselves is left alone.
        if have != CLI_SHA256 and have == previous:
            say("      a newer compiler is available - updating")
        else:
            say(f"      found ({'verified' if have == CLI_SHA256 else 'custom build'})")
            if have == CLI_SHA256 and previous != CLI_SHA256:
                knoxpaths.save_config({"cli_sha256": CLI_SHA256})
            return True
    try:
        data = download(CLI_URL, "the patched compiler (~6 MB)")
    except Exception as exc:     # noqa: BLE001 - any failure means "build it yourself"
        say(f"      could not download it: {exc}")
        say("      You can still use KnoxMap: compile with 'Open in WorldEd' instead,")
        say("      or build the compiler yourself - see worlded/README.md.")
        return False
    if hashlib.sha256(data).hexdigest() != CLI_SHA256:
        say("      the download does not match the expected fingerprint - not installed.")
        return False
    exe.write_bytes(data)
    knoxpaths.save_config({"cli_sha256": CLI_SHA256})
    say("      installed and verified")
    return True


# ---- 3 & 4. game artwork and configuration ------------------------------------------

def _warn_if_not_build42(game: Path) -> None:
    if knoxpaths.is_build42(game):
        return
    say("")
    say("      !! This looks like Build 41. KnoxMap makes Build 42 maps, which")
    say("         Build 41 cannot load. In Steam: right-click Project Zomboid >")
    say("         Properties > Betas, choose the Build 42 (unstable) branch, let")
    say("         it update, then run Setup.bat again.")
    say("")


def _ask(prompt: str) -> str:
    """input(), or nothing when there is no one to answer (no console)."""
    try:
        return input(prompt)
    except (EOFError, OSError):
        say("")
        return ""


def choose_steam_folders() -> None:
    """Show the Steam libraries found on their own, and let the player add a
    drive or folder they were not found on (games and Workshop mods on
    another drive). Also chosen later in the app, under Steam libraries."""
    found = knoxpaths.steam_libraries_found()
    say("      Steam libraries: " + (", ".join(f["path"] for f in found) or "none found"))
    if os.environ.get("KNOXMAP_UNATTENDED") == "1":
        return
    while True:
        answer = _ask("      Games or Workshop mods on another drive? Type the drive or folder\n"
                       "      (like E: or E:\\Games\\Steam, several separated by ;),\n"
                       "      or press Enter to go on: ").strip()
        if not answer:
            return
        folders = [a.strip().strip('"') for a in answer.split(";") if a.strip()]
        bad = [f for f in folders if not knoxpaths.library_of(f)]
        if bad:
            say(f"      No Steam library in {', '.join(bad)} - try again.")
            continue
        saved = knoxpaths.load_config().get("steam_folders") or []
        knoxpaths.save_steam_folders(list(saved) + folders)
        say("      Steam libraries: " + ", ".join(f["path"] for f in knoxpaths.steam_libraries_found()))
        return


def find_game() -> Path | None:
    step(3, "Project Zomboid install")
    choose_steam_folders()
    game = knoxpaths.pz_install_dir()
    if game:
        say(f"      found at {game}")
        _warn_if_not_build42(game)
        return game
    say("      Could not find Project Zomboid in your Steam libraries.")
    if os.environ.get("KNOXMAP_UNATTENDED") == "1":
        # Run by the updater, with nobody to answer: keep the folder set before.
        saved = knoxpaths.load_config().get("pz_install")
        return Path(saved) if saved else None
    if sys.platform == "darwin":
        say("      On a Mac the game lives inside ProjectZomboid.app. If you do not")
        say("      know where, this prints it:")
        say("        find ~/Library/Application\\ Support/Steam -type d -name texturepacks")
    say("      Any of these will do: the Steam library, the ProjectZomboid folder,")
    say("      the .app on a Mac, or the media folder itself.")
    while True:
        answer = _ask("      Paste the path (or press Enter to skip): ").strip().strip('"')
        if not answer:
            return None
        found = knoxpaths.pz_install_from(answer)
        if found:
            say(f"      using {found}")
            _warn_if_not_build42(found)
            return found
        say(f"      No Project Zomboid there: nothing under {answer} holds a")
        say("      media/texturepacks folder. Try again, or press Enter to skip.")


def configure_tools(tools: Path, game: Path | None) -> None:
    step(4, "Tile artwork and tool configuration")
    config_dir = tools / "config"
    tiles_dir = tools / "Tiles"
    two_x = tiles_dir / "2x"
    two_x.mkdir(parents=True, exist_ok=True)

    # The editors store absolute folder paths, so they have to be written for
    # wherever the tools landed on this PC.
    settings = tools / "settings"
    settings.mkdir(exist_ok=True)
    ini = settings / "PZTools.ini"
    # The game folder too: the editor reads the game's tile definitions from
    # it, and without them every window - a floor-to-ceiling glass panel as
    # much as a small sash - got a small house-window hole cut in the wall, so
    # tall windows showed wall behind the glass. A Steam library off the
    # default drive is not found by the editor's own search.
    # The editor appends "media" to this itself, so it wants the folder above
    # the media folder - which on a Mac is inside the application bundle, not
    # the game folder. And every path here has to be spelled the way the
    # editor will read it: one running under Wine cannot open /Users/somebody.
    media = knoxpaths.pz_media_dir(game) if game else None

    def ini_path(path: Path) -> str:
        return path.as_posix() if os.name == "nt" else knoxpaths.tool_path(path)

    game_line = f"ProjectZomboidDirectory={ini_path(media.parent)}\n" if media else ""
    ini.write_text("[%General]\nSettingsSchema=2\n\n[Paths]\n"
                   f"ConfigDirectory={ini_path(config_dir)}\n"
                   f"TilesDirectory={ini_path(tiles_dir)}\n" + game_line,
                   encoding="utf-8")
    say("      editor paths written")

    if game is None:
        say("      skipped tile extraction - no game folder. Run Setup again once it is installed.")
        return
    from tools import extract_tiles, prune_tilesets

    # Wherever this system keeps the game's artwork - inside the application
    # bundle on a Mac, in <game>/media everywhere else.
    packs = knoxpaths.pz_media_dir(game) / "texturepacks"
    tilesets = config_dir / "Tilesets.txt"
    # Start again from the full catalogue, so a sheet pruned by an earlier run
    # (say, before the game was updated) gets another chance to be extracted.
    full = config_dir / "Tilesets.txt.pre-prune"
    if full.exists():
        shutil.copyfile(full, tilesets)
    catalog, _packs = extract_tiles.read_tilesets_txt(str(tilesets))
    # Sheets extracted before the split-sheet fix lack the tiles B42 keeps in
    # the floor packs - flat roof tops among them - so merge those in once.
    merged = tools / "settings" / "floor_tiles_merged"
    present = sorted(n for n in catalog if (two_x / f"{n}.png").exists())
    if present and not merged.exists():
        say("      adding Build 42 floor-pack tiles to your tile sheets ...")
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            for pack in sorted(packs.glob("*2x.floor.pack")):
                extract_tiles.extract_pack(str(pack), catalog, set(present), str(two_x), merge=True)
        merged.parent.mkdir(parents=True, exist_ok=True)
        merged.write_text("1", encoding="utf-8")
    missing = sorted(n for n in catalog if not (two_x / f"{n}.png").exists())
    if missing:
        say(f"      extracting {len(missing)} tile sheets from your game (a few minutes) ...")
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            extract_tiles.main(["extract_tiles", str(packs),
                                str(tilesets), str(two_x), *missing])
        (tools / "settings" / "extract_tiles.log").write_text(log.getvalue(), encoding="utf-8")
        merged.write_text("1", encoding="utf-8")   # main() merges the floor packs itself
        found = sum(1 for n in missing if (two_x / f"{n}.png").exists())
        say(f"      extracted {found} of {len(missing)}"
            + ("" if found == len(missing) else
               f" - {len(missing) - found} no longer exist in Build 42, which is fine"))
    else:
        say("      tile sheets already extracted")
    # Sheets Build 42 no longer ships would otherwise be retried by the
    # editor on every building it loads, stalling compiles for minutes.
    with contextlib.redirect_stdout(io.StringIO()):
        prune_tilesets.main(["prune_tilesets", str(tilesets), str(two_x)])

    add_erikas_tiles(tools, tilesets, two_x)

    for script, what in (("patch_rules_b42_trees.py", "Build 42 trees and flowers"),
                         ("patch_rules_roads.py", "Kerbs and road markings")):
        rules = subprocess.run([sys.executable, str(BASE_DIR / "worlded" / script), str(tools)],
                               capture_output=True, text=True, check=False)
        say(f"      {what} " +
            ("set up" if rules.returncode == 0 else f"not set up: {rules.stderr.strip()[-200:]}"))


def add_erikas_tiles(tools: Path, tilesets: Path, two_x: Path) -> None:
    """Erika's Tiles, if subscribed: its sheets into the map tools, so maps
    can use its pictures and plants (and then require the mod)."""
    import re

    from tools import extract_tiles

    media = knoxpaths.erikas_tiles_media()
    if media is None:
        say("      Erika's Tiles not installed - buildings use vanilla decor only")
        return
    defs = media / "Erikas_Tiles.tiles.txt"
    txt = defs.read_text(encoding="utf-8", errors="replace") if defs.exists() else ""
    catalog = {name: (int(c), int(r)) for name, c, r in
               re.findall(r"file\s*=\s*(\S+)\s*\n\s*size\s*=\s*(\d+),(\d+)", txt)}
    missing = {n for n in catalog if not (two_x / f"{n}.png").exists()}
    if missing:
        with contextlib.redirect_stdout(io.StringIO()):
            extract_tiles.extract_pack(str(media / "texturepacks" / "Erikas_Tiles.pack"),
                                       catalog, missing, str(two_x))
    text = tilesets.read_text(encoding="utf-8", errors="replace")
    add = "".join(f"tileset\n{{\n    file = Erikas_Tiles.pack/{n}\n    size = {c},{r}\n}}\n"
                  for n, (c, r) in catalog.items() if f"/{n}\n" not in text)
    if add:
        tilesets.write_text(text.rstrip("\n") + "\n" + add, encoding="utf-8")
    say(f"      Erika's Tiles set up ({len(catalog)} sheets)")


# ---- 5. where the game keeps mods ---------------------------------------------------

def choose_zomboid_folder() -> Path:
    """Show the Zomboid folder maps are installed into (its mods folder) and
    let the player pick another. Kept as it was when nobody can answer."""
    zomboid = knoxpaths.zomboid_user_dir()
    say(f"      Maps are installed into {zomboid / 'mods'}")
    if os.environ.get("KNOXMAP_UNATTENDED") == "1":
        return zomboid
    while True:
        answer = _ask("      Use a different Zomboid folder? Type it, or press Enter to keep\n"
                      "      this one: ").strip().strip('"')
        if not answer:
            return zomboid
        chosen = Path(answer).expanduser()
        try:
            (chosen / "mods").mkdir(parents=True, exist_ok=True)
        except OSError as e:
            say(f"      Cannot use {chosen}: {e} - try again.")
            continue
        return chosen


def finish(tools: Path, game: Path | None, cli_ok: bool) -> None:
    step(5, "Saving settings")
    zomboid = choose_zomboid_folder()
    knoxpaths.save_config({"mapping_tools": tools, "pz_install": game,
                           "zomboid_dir": zomboid})
    say(f"      maps will be installed into {zomboid / 'mods'}")
    say()
    say("Setup complete." if game and cli_ok else "Setup finished with notes above.")
    say("Start KnoxMap by double-clicking KnoxMap.bat.")


def main() -> int:
    # Place names can be in any script, and a Windows console using a legacy
    # code page cannot print most of them - "OSM says Kadıköy" crashed a build
    # on cp1252. Print what it can and mark the rest, rather than dying.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    say("KnoxMap setup")
    say("=============")
    if sys.maxsize <= 2 ** 32:
        # 2 GB is all a 32-bit process can address, and a town-sized map needs
        # more: it dies part-way through with "MemoryError".
        say("")
        say("      !! This is a 32-bit Python. It can only use about 2 GB of memory,")
        say("         so maps of more than a few square kilometres will fail with")
        say("         'MemoryError'. Close this, run Setup.bat again, and KnoxMap")
        say("         will fetch a 64-bit Python for itself.")
        say("")
    tools = ensure_mapping_tools()
    cli_ok = ensure_patched_cli(tools)
    game = find_game()
    configure_tools(tools, game)
    finish(tools, game, cli_ok)
    return 0


class _Tee:
    """Everything setup prints, also written to logs/setup.log: a setup that
    failed on someone else's PC left nothing behind but a closed window."""

    def __init__(self, stream, log):
        self.stream, self.log = stream, log

    def write(self, text):
        if self.stream is not None:
            self.stream.write(text)
        self.log.write(text)
        self.log.flush()

    def flush(self):
        if self.stream is not None:
            self.stream.flush()

    def reconfigure(self, **kw):
        if self.stream is not None and hasattr(self.stream, "reconfigure"):
            self.stream.reconfigure(**kw)


def _log_to_file() -> None:
    import time

    logs = Path(__file__).resolve().parent / "logs"
    try:
        logs.mkdir(exist_ok=True)
        setup_log = open(logs / "setup.log", "a", encoding="utf-8", errors="replace")
    except OSError:
        return
    setup_log.write(f"\n===== setup {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    try:
        import knoxlog
        setup_log.write(knoxlog.system_summary() + "\n\n")
    except Exception:  # noqa: BLE001 - the summary is a nicety
        pass
    sys.stdout = _Tee(sys.stdout, setup_log)
    sys.stderr = _Tee(sys.stderr, setup_log)


if __name__ == "__main__":
    import traceback

    _log_to_file()
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        traceback.print_exc()
        print("\nSetup failed. The details are in logs/setup.log - post that file in "
              "#bug-reports on the KnoxMap Discord if running Setup.bat again does not help.")
        raise SystemExit(1)
