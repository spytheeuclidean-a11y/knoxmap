"""Buildings built by hand, kept and used again.

The generator lays out every building from scratch, which is what makes a map
of ten thousand of them possible and is also its limit: it will never produce
the one house somebody drew themselves, or the terrace they have been
perfecting in BuildingEd for a month. A preset is that building, saved whole
and stamped onto a footprint instead of a generated one.

A preset is a `.tbx` file - the same thing the generator writes and the same
thing BuildingEd reads and writes - so anything that can make one can make a
preset: a building out of a map that came out well, or one drawn by hand in
the game's own editor and dropped into the folder. Nothing is converted, and
nothing is re-rendered: the file that goes in is the file that comes out,
which is the whole point of hand-building one.

There are two ways one gets used. A zone names the presets it draws from
(knoxbuild/zones.py), which is how a particular estate is built of particular
houses. And a preset says what kind of building it stands in for - a police
station, a church, a shop - and the kinds that are switched on here are used
wherever the map has a building of that kind: turn "police" on and every
police station on the map is the one that was built by hand, not an arranged
set of offices that happens to be called a police station.

Either way a footprint takes a preset that fits inside it, chosen from its own
seed so a rebuild puts the same building on the same spot; a footprint nothing
fits goes back to the generator, because a town with holes in it where no
preset fitted is worse than one with some generated houses in it.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata

# The .tbx header: <building version="4" width="12" height="10" ...>
_SIZE = re.compile(r'<building\b[^>]*\bwidth="(\d+)"[^>]*\bheight="(\d+)"')
_ROOM = re.compile(r"<room\b")
_FLOOR = re.compile(r"<floor>")
# The generator writes a <floor> for each storey and one more for the roof, so
# a two-storey house has three. Counted against the levels recorded beside the
# buildings of a built map: of 61 buildings of Manhattan, every 5-storey one
# has 6 <floor> and every 6-storey one has 7.
FLOORS_OVER_STOREYS = 1

SAFE = re.compile(r"[^A-Za-z0-9 _-]+")

# What each preset is for, and which kinds are switched on, kept beside the
# files rather than in them: a .tbx is used exactly as it was saved, so
# nothing about KnoxMap is written into it.
MANIFEST = "presets.json"
# The drawing a preset was made from, kept beside it (knoxbuild/designer.py)
# so one made in the window can be opened and changed again.
DESIGN_SUFFIX = ".design.json"
# Buildings other people built and sent in, which ship with KnoxMap and are
# there in a fresh install (knoxbuild/share.py, tools/add_shared_building.py).
# They are read and never written: somebody's own folder is theirs, and this
# one is replaced wholesale by every update, so a building changed here would
# lose the change at the next one. What each is and who built it travels with
# them in their own manifest, because the one above is somebody's own settings
# and these are not.
LIBRARY = "library"
LIBRARY_MANIFEST = "library.json"
# A preset with no kind recorded stands in for any building. It is only ever
# reached as a fallback (`choose_for_kind`), so turning "police" on cannot
# quietly make somebody's hand-built house into the town's police station
# while there is a police station preset that fits.
ANY = ""


def folder(base_dir) -> str:
    return os.path.join(str(base_dir), "presets", "buildings")


def library_folder(base_dir) -> str:
    """Where the buildings that ship with KnoxMap live."""
    return os.path.join(str(base_dir), "presets", LIBRARY)


def shipped(base_dir) -> dict:
    """What each building in that library is, and who built it."""
    path = os.path.join(library_folder(base_dir), LIBRARY_MANIFEST)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    listed = data.get("buildings") if isinstance(data, dict) else None
    if not isinstance(listed, dict):
        return {}
    out = {}
    for name, about in listed.items():
        if isinstance(about, dict):
            out[str(name)] = {"kind": str(about.get("kind") or ANY),
                              "author": str(about.get("author") or ""),
                              "notes": str(about.get("notes") or ""),
                              "added": str(about.get("added") or "")}
    return out


def write_shipped(base_dir, buildings: dict) -> None:
    """Rewrite that manifest. Only tools/add_shared_building.py does this."""
    where = library_folder(base_dir)
    os.makedirs(where, exist_ok=True)
    path = os.path.join(where, LIBRARY_MANIFEST)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"version": 1, "buildings": dict(sorted(buildings.items()))},
                  f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def safe_name(name: str) -> str:
    """A name that is a filename on every system, or "" if nothing is left."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = SAFE.sub(" ", text).strip()
    return re.sub(r"\s+", " ", text)[:60]


def measure(text: str) -> dict | None:
    """What this .tbx is: its size on the ground, its storeys, its rooms.

    None when it is not a building file at all, so a stray text file dropped
    into the folder is left out rather than offered as a preset.
    """
    found = _SIZE.search(text or "")
    if not found:
        return None
    width, height = int(found.group(1)), int(found.group(2))
    if width <= 0 or height <= 0:
        return None
    floors = len(_FLOOR.findall(text))
    return {"width": width, "height": height,
            "storeys": max(1, floors - FLOORS_OVER_STOREYS),
            "rooms": len(_ROOM.findall(text))}


def kinds() -> list[dict]:
    """Every kind of building a preset can stand in for, with its name.

    Taken from what the generator can actually recognise in a building's tags
    (knoxbuild/build.classify_building) rather than listed here, so a kind
    this window offers is a kind the map can really have, and a kind added to
    the generator turns up here on its own.
    """
    from .build import SPECIAL_BY_VALUE

    labels = {"house": "House", "apartment": "Block of flats", "shop": "Shop",
              "mall": "Shopping centre", "restaurant": "Restaurant or bar",
              "school": "School", "library": "Library", "church": "Church",
              "civic": "Civic or office", "police": "Police station",
              "fire": "Fire station", "medical": "Hospital or clinic",
              "industrial": "Factory or warehouse", "garage": "Garage",
              "barn": "Barn or farm building", "military": "Military",
              "castle": "Castle or manor", "stadium": "Sports ground",
              "shed": "Shed or outbuilding"}
    # "house" and "shed" are what the build calls a building its tags say
    # nothing special about, so neither is in the table of tag values.
    found = {"house", "shed"} | set(SPECIAL_BY_VALUE.values())
    return [{"id": name, "label": labels.get(name, name.title())}
            for name in sorted(found, key=lambda n: labels.get(n, n).lower())]


def manifest(base_dir) -> dict:
    """What each preset is for, and which kinds are switched on."""
    path = os.path.join(folder(base_dir), MANIFEST)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    by_name = data.get("kinds")
    use = data.get("use")
    return {"kinds": {str(k): str(v) for k, v in by_name.items()}
                      if isinstance(by_name, dict) else {},
            "use": {str(k): bool(v) for k, v in use.items()}
                   if isinstance(use, dict) else {}}


def _write_manifest(base_dir, data: dict) -> None:
    where = folder(base_dir)
    os.makedirs(where, exist_ok=True)
    path = os.path.join(where, MANIFEST)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"kinds": data.get("kinds") or {},
                   "use": data.get("use") or {}}, f)
    os.replace(tmp, path)


def set_kind(base_dir, name: str, kind: str) -> str:
    """Say what a preset stands in for. "" means any building."""
    clean = safe_name(name)
    known = {entry["id"] for entry in kinds()}
    kind = str(kind or "").strip().lower()
    if kind and kind not in known:
        raise ValueError(f"No such kind of building: {kind}")
    data = manifest(base_dir)
    if kind:
        data["kinds"][clean] = kind
    else:
        data["kinds"].pop(clean, None)
    _write_manifest(base_dir, data)
    return kind


def set_use(base_dir, kind: str, on: bool) -> bool:
    """Switch hand-built buildings on or off for one kind of building."""
    known = {entry["id"] for entry in kinds()}
    kind = str(kind or "").strip().lower()
    if kind not in known:
        raise ValueError(f"No such kind of building: {kind}")
    data = manifest(base_dir)
    if on:
        data["use"][kind] = True
    else:
        data["use"].pop(kind, None)
    _write_manifest(base_dir, data)
    return bool(on)


def using(base_dir) -> set:
    """The kinds of building that are to be stamped from presets."""
    return {k for k, on in manifest(base_dir)["use"].items() if on}


def _in_folder(where: str) -> list[dict]:
    """Every .tbx in one folder, measured. Anything else there is ignored."""
    out = []
    try:
        names = sorted(os.listdir(where))
    except OSError:
        return []
    for entry in names:
        if not entry.lower().endswith(".tbx"):
            continue
        path = os.path.join(where, entry)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                about = measure(f.read())
        except OSError:
            continue
        if about is None:
            continue
        about["name"] = entry[:-4]
        about["file"] = path
        # Whether there is a drawing to open and change, or only the .tbx -
        # a building out of a map, or one made in BuildingEd, has none.
        about["editable"] = os.path.exists(path[:-4] + DESIGN_SUFFIX)
        out.append(about)
    return out


def library(base_dir) -> list[dict]:
    """Every preset, somebody's own and the shipped ones, smallest first.

    A name in both folders is theirs: opening a shipped building, changing it
    and saving it writes a building of their own, and from then on that is the
    one used - an update replacing the library cannot undo somebody's work.
    """
    recorded = manifest(base_dir)["kinds"]
    out = _in_folder(folder(base_dir))
    for about in out:
        about["kind"] = recorded.get(about["name"], ANY)
        about["shared"] = False
    mine = {about["name"] for about in out}
    from_others = shipped(base_dir)
    for about in _in_folder(library_folder(base_dir)):
        if about["name"] in mine:
            continue
        credit = from_others.get(about["name"], {})
        # A shipped building's kind travels with it, but somebody who has said
        # what it stands in for here has the last word.
        about["kind"] = recorded.get(about["name"], credit.get("kind", ANY))
        about["shared"] = True
        about["author"] = credit.get("author", "")
        about["notes"] = credit.get("notes", "")
        out.append(about)
    out.sort(key=lambda p: (p["width"] * p["height"], p["name"]))
    return out


def read(base_dir, name: str) -> str | None:
    """A preset's .tbx, somebody's own first and then the shipped one."""
    clean = safe_name(name)
    for where in (folder(base_dir), library_folder(base_dir)):
        try:
            with open(os.path.join(where, f"{clean}.tbx"),
                      encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            continue
    return None


def save(base_dir, name: str, text: str, kind: str | None = None) -> dict:
    """Keep a .tbx as a preset. Returns what it is; raises if it is not one.

    `kind` is the sort of building it stands in for, or "" for any.
    """
    clean = safe_name(name)
    if not clean:
        raise ValueError("A preset needs a name.")
    about = measure(text)
    if about is None:
        raise ValueError("That is not a building file: no <building> with a "
                         "width and a height in it.")
    where = folder(base_dir)
    os.makedirs(where, exist_ok=True)
    path = os.path.join(where, f"{clean}.tbx")
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    about["name"] = clean
    about["file"] = path
    about["kind"] = set_kind(base_dir, clean, kind or ANY)
    return about


def remove(base_dir, name: str) -> bool:
    """Throw away one of somebody's own buildings.

    A shipped one is not theirs to throw away - it would come back with the
    next update anyway - so this leaves it alone and says it did nothing.
    """
    clean = safe_name(name)
    path = os.path.join(folder(base_dir), f"{clean}.tbx")
    if not os.path.exists(path):
        return False
    data = manifest(base_dir)
    if data["kinds"].pop(clean, None) is not None:
        _write_manifest(base_dir, data)
    # The drawing goes with it: a design with no preset is a preset nothing
    # can stamp, and it would come back the next time one was saved by name.
    try:
        os.remove(path[:-4] + DESIGN_SUFFIX)
    except OSError:
        pass
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def fitting(entries: list[dict], width: int, height: int) -> list[dict]:
    """The presets that would stand on a footprint this big.

    A preset is used at the size it was built; it is not stretched, because a
    hand-built building stretched is no longer the building somebody built.
    So it has to fit inside the footprint, either way round being no help -
    the .tbx is not rotated either.
    """
    return [p for p in entries
            if p["width"] <= width and p["height"] <= height]


def choose(entries: list[dict], width: int, height: int, seed: int) -> dict | None:
    """One preset for a footprint, the same one every time it is rebuilt.

    The biggest that fits, so a preset meant for the plot is preferred over a
    shed that would also go on it; among equals the seed picks, so a street of
    identical plots is not a street of identical houses.
    """
    fits = fitting(entries, width, height)
    if not fits:
        return None
    best = max(p["width"] * p["height"] for p in fits)
    tied = [p for p in fits if p["width"] * p["height"] == best]
    return tied[seed % len(tied)]


def for_kind(entries: list[dict], kind: str | None) -> list[dict]:
    """The presets built to stand in for this kind of building."""
    want = str(kind or "house").lower()
    return [p for p in entries if (p.get("kind") or ANY) == want]


def choose_for_kind(entries: list[dict], kind: str | None, width: int,
                    height: int, seed: int) -> dict | None:
    """One preset for a plot the map says is this kind of building.

    A preset built for the kind is preferred; one built for any building is
    only reached when nothing of the kind fits the plot, so a hand-built
    police station is used where there is one and a hand-built shed is not
    made into a police station while there is.
    """
    pick = choose(for_kind(entries, kind), width, height, seed)
    if pick is None:
        pick = choose([p for p in entries if not p.get("kind")],
                      width, height, seed)
    return pick
