"""Which KnoxMap made a map, and what a newer one needs redone.

A map is built in four steps - generate, build, compile, install - and a
release rarely changes all of them. Cars, for instance, were a missing file
that install writes, so a map made with an older KnoxMap only has to be
installed again; the Knox County roads setting changes the terrain, so that
one starts from Generate.

Every step writes the version that ran it into knoxmap_map.json beside the
map. Opening a map made by an older release, the window can then say exactly
what is out of date - and offer to bring it up to date without starting over.

    {"stages": {"generate": {"version": "1.3.2", "at": "2026-09-16T20:11:04"},
                "build": ..., "compile": ..., "install": ...}}
"""
from __future__ import annotations

import json
import os
import time

import knoxfiles

STATE_FILE = "knoxmap_map.json"
STAGES = ("generate", "build", "compile", "install")

# The release that last changed what a step writes. A map whose step ran on
# anything older is redone by that step - and by the ones after it, since each
# works on what the one before produced.
CHANGED_IN = {
    # 1.3.6: houses where the map has only an address, trees and scrub over
    # open country, military sites read from military=* as well as landuse.
    "generate": "1.3.6",
    # 1.3.9: every wall carries a cut-out for every window style, so a window
    # has a wall behind it. 1.3.6: rows of shops cut into their units, rooms
    # small enough for the game to fill every container in them, police
    # stations, libraries and fire stations, headstones in the churchyards, a
    # place of its own in the world so two maps can be installed at once.
    "build": "1.3.9",
    # 1.3.1: the project is repaired before compiling.
    "compile": "1.3.1",
    # 1.3.6: the old map's cells are cleared out before the new ones go in.
    "install": "1.3.6",
}
# What each step is called in the window, for the message.
LABELS = {"generate": "Generate map", "build": "Build", "compile": "Compile",
          "install": "Install"}


def _parse(version: str) -> tuple[int, ...]:
    import re

    return tuple(int(p) for p in re.findall(r"\d+", version or "")[:4]) or (0,)


def _path(map_dir: str) -> str:
    return os.path.join(map_dir, STATE_FILE)


def read(map_dir: str) -> dict:
    try:
        with open(_path(map_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def stamp(map_dir: str, stage: str, version: str | None = None,
          took: float | None = None) -> None:
    """Record that `stage` just ran, with this KnoxMap's version.

    `took` is how many seconds it took, when the caller timed it: it is what the
    window's forecast for the next map is worked out from, and it costs a line
    in a file that is already being written.
    """
    if version is None:
        import knoxlog
        version = knoxlog.version()
    state = read(map_dir)
    stages = state.setdefault("stages", {})
    stages[stage] = {"version": version, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if took is not None and took > 0:
        stages[stage]["took"] = round(float(took), 1)
    # A step invalidates whatever was made from its output.
    for later in STAGES[STAGES.index(stage) + 1:]:
        stages.pop(later, None)
    try:
        knoxfiles.write(_path(map_dir), state, indent=2)
    except OSError:
        pass          # a map whose stamp cannot be written still works


def took(map_dir: str, stage: str) -> float | None:
    """How long this map's last run of `stage` took, or None if it was not timed.

    Maps stamped before durations were recorded have only `at`, and a guessed
    stage has nothing at all - both read as unknown rather than as fast.
    """
    rec = (read(map_dir).get("stages") or {}).get(stage) or {}
    value = rec.get("took")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


def record_install(map_dir: str, mod_root: str, mod_id: str, title: str = "") -> None:
    """Remember which mod folder this map was installed into, so the window can
    show it, check it is current and take it out again."""
    state = read(map_dir)
    state["installed"] = {"modRoot": mod_root, "modId": mod_id, "title": title,
                          "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        knoxfiles.write(_path(map_dir), state, indent=2)
    except OSError:
        pass


def installed(map_dir: str) -> dict | None:
    """Where this map is installed, or None when it is not - or when that mod
    folder has since been deleted or moved by hand."""
    rec = read(map_dir).get("installed")
    if not isinstance(rec, dict) or not rec.get("modRoot"):
        return None
    if not os.path.isfile(os.path.join(str(rec["modRoot"]), "mod.info")):
        return None
    return rec


def forget_install(map_dir: str) -> None:
    state = read(map_dir)
    if state.pop("installed", None) is None:
        return
    try:
        knoxfiles.write(_path(map_dir), state, indent=2)
    except OSError:
        pass


def done(map_dir: str) -> dict:
    """What has been done to this map, from its files where there is no stamp:
    maps made before stamps existed still have to be recognised."""
    from pathlib import Path

    path = Path(map_dir)
    name = path.name
    stages = dict(read(map_dir).get("stages") or {})
    # Nothing stamped maps before 1.3.5, so read what is there. A terrain with
    # the bridges and monuments file was drawn by 1.1 or later; a project from
    # before the stamps is older than the parking spaces and pumps (1.3.3),
    # which is what the steps after it would be redone for anyway.
    compiled = any((path / "lots").glob("*.lotheader")) if (path / "lots").is_dir() else False
    guesses = {
        "generate": ((path / f"{name}_info.json").exists(),
                     "1.1" if (path / f"{name}_structures.json").exists() else "0"),
        "build": ((path / f"{name}.pzw").exists(), "0"),
        "compile": (compiled, "0"),
        # Nothing here says whether it was installed, and the step that puts
        # the cars and the in-game map into a map made before 1.3.5 is exactly
        # that one - so a compiled map is taken to want installing.
        "install": (compiled, "0"),
    }
    for stage, (there, version) in guesses.items():
        if there and stage not in stages:
            stages[stage] = {"version": version, "at": None, "guessed": True}
    return stages


def needs(map_dir: str) -> list[str]:
    """The steps to run to bring this map up to this KnoxMap, in order.

    Empty when the map is up to date. A step is in the list when it ran on an
    older release than the one that last changed it - and then so is every
    step after it, which was made from its output.
    """
    stages = done(map_dir)
    if not stages:
        return []
    out: list[str] = []
    for stage in STAGES:
        if out:                        # something earlier is being redone
            if stage in stages:
                out.append(stage)
            continue
        ran = stages.get(stage)
        if ran is None:
            continue                   # never done; not out of date either
        if _parse(ran.get("version", "0")) < _parse(CHANGED_IN[stage]):
            out.append(stage)
    return out


def made_with(map_dir: str) -> str | None:
    """The oldest KnoxMap that made part of this map, for the message.

    Only versions a step wrote down count: before 1.3.5 nothing was stamped,
    and what is read from the files is a guess at what is missing, not a
    version to name."""
    stages = done(map_dir)
    stamped = [s.get("version") for s in stages.values()
               if not s.get("guessed") and s.get("version")]
    if stamped:
        return min(stamped, key=_parse)
    return "an early release" if stages else None
