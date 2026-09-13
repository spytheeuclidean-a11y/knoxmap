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
        if c and Path(c).exists():
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


def worlded_cli() -> Path | None:
    """The patched, headless PZWorldEd_cli.exe."""
    override = os.environ.get("PZWORLDED_CLI")
    if override and Path(override).exists():
        return Path(override)
    tools = mapping_tools_dir()
    exe = tools / "bin" / "PZWorldEd_cli.exe" if tools else None
    return exe if exe and exe.exists() else None


def worlded_gui() -> Path | None:
    override = os.environ.get("PZWORLDED")
    if override and Path(override).exists():
        return Path(override)
    tools = mapping_tools_dir()
    exe = tools / "bin" / "PZWorldEd.exe" if tools else None
    return exe if exe and exe.exists() else None


def _steam_libraries() -> list[Path]:
    """Every Steam library folder on this PC, read from Steam itself."""
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
    roots += [Path(r"C:\Program Files (x86)\Steam"), Path.home() / ".steam" / "steam",
              Path.home() / ".local" / "share" / "Steam"]

    libraries: list[Path] = []
    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if not vdf.exists():
            continue
        libraries.append(root)
        text = vdf.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            libraries.append(Path(m.group(1).replace("\\\\", "\\")))
    seen, unique = set(), []
    for lib in libraries:
        key = str(lib).lower()
        if key not in seen:
            seen.add(key)
            unique.append(lib)
    return unique


def pz_install_dir() -> Path | None:
    """The Project Zomboid game folder (the one holding media/texturepacks)."""
    configured = _first(os.environ.get("PZ_INSTALL"), load_config().get("pz_install"))
    if configured:
        return configured
    for lib in _steam_libraries():
        candidate = lib / "steamapps" / "common" / "ProjectZomboid"
        if (candidate / "media" / "texturepacks").exists():
            return candidate
    return None


def is_build42(game: Path | None) -> bool:
    """Whether this install is Build 42, the only one KnoxMap's maps load in.

    Build 42 split the floor tiles into their own *.floor.pack files; Build 41,
    still Steam's default branch for many players, has none.
    """
    return bool(game) and any((Path(game) / "media" / "texturepacks").glob("*.floor.pack"))


def zomboid_user_dir() -> Path:
    """~/Zomboid, where the game keeps saves and mods."""
    configured = os.environ.get("ZOMBOID_DIR") or load_config().get("zomboid_dir")
    return Path(configured) if configured else Path.home() / "Zomboid"
