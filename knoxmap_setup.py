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

REPO = "spytheeuclidean-a11y/knoxify"
CLI_URL = (f"https://github.com/{REPO}/releases/download/"
           "worlded-cli-20260909f/PZWorldEd_cli.exe")
CLI_SHA256 = "dbae186f1f1f541decd123604ec9fc822d930f8f7c1ec8b17c1b89874628f3e2"

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
    if existing and (existing / "bin" / "PZWorldEd.exe").exists():
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


def ensure_patched_cli(tools: Path) -> bool:
    step(2, "Patched map compiler (PZWorldEd_cli.exe)")
    exe = tools / "bin" / "PZWorldEd_cli.exe"
    if exe.exists():
        say(f"      found ({'verified' if sha256(exe) == CLI_SHA256 else 'custom build'})")
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


def find_game() -> Path | None:
    step(3, "Project Zomboid install")
    game = knoxpaths.pz_install_dir()
    if game:
        say(f"      found at {game}")
        _warn_if_not_build42(game)
        return game
    say("      Could not find Project Zomboid in your Steam libraries.")
    while True:
        answer = input("      Paste the ProjectZomboid folder path (or press Enter to skip): ").strip().strip('"')
        if not answer:
            return None
        if (Path(answer) / "media" / "texturepacks").exists():
            _warn_if_not_build42(Path(answer))
            return Path(answer)
        say("      That folder has no media/texturepacks inside - try again.")


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
    ini.write_text("[%General]\nSettingsSchema=2\n\n[Paths]\n"
                   f"ConfigDirectory={config_dir.as_posix()}\n"
                   f"TilesDirectory={tiles_dir.as_posix()}\n", encoding="utf-8")
    say("      editor paths written")

    if game is None:
        say("      skipped tile extraction - no game folder. Run Setup again once it is installed.")
        return
    from tools import extract_tiles, prune_tilesets

    tilesets = config_dir / "Tilesets.txt"
    # Start again from the full catalogue, so a sheet pruned by an earlier run
    # (say, before the game was updated) gets another chance to be extracted.
    full = config_dir / "Tilesets.txt.pre-prune"
    if full.exists():
        shutil.copyfile(full, tilesets)
    catalog, _packs = extract_tiles.read_tilesets_txt(str(tilesets))
    missing = sorted(n for n in catalog if not (two_x / f"{n}.png").exists())
    if missing:
        say(f"      extracting {len(missing)} tile sheets from your game (a few minutes) ...")
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            extract_tiles.main(["extract_tiles", str(game / "media" / "texturepacks"),
                                str(tilesets), str(two_x), *missing])
        (tools / "settings" / "extract_tiles.log").write_text(log.getvalue(), encoding="utf-8")
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

    for script, what in (("patch_rules_b42_trees.py", "Build 42 trees and flowers"),
                         ("patch_rules_roads.py", "Kerbs and road markings")):
        rules = subprocess.run([sys.executable, str(BASE_DIR / "worlded" / script), str(tools)],
                               capture_output=True, text=True, check=False)
        say(f"      {what} " +
            ("set up" if rules.returncode == 0 else f"not set up: {rules.stderr.strip()[-200:]}"))


# ---- 5. where the game keeps mods ---------------------------------------------------

def finish(tools: Path, game: Path | None, cli_ok: bool) -> None:
    step(5, "Saving settings")
    zomboid = knoxpaths.zomboid_user_dir()
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
    tools = ensure_mapping_tools()
    cli_ok = ensure_patched_cli(tools)
    game = find_game()
    configure_tools(tools, game)
    finish(tools, game, cli_ok)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
