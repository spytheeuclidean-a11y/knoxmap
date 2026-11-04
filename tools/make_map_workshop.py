"""Lay an installed KnoxMap map out for Project Zomboid's Workshop uploader.

    python tools/make_map_workshop.py MOD_ID [--title "My Town"] [--tags "Build 42;Map;"]

The game uploads from ~/Zomboid/Workshop/<folder>, wanting Contents/mods/<mod id>
with workshop.txt and preview.png beside it. This builds that folder from the
map already installed under ~/Zomboid/mods/<mod id> (the Install step), with
the same Workshop page every KnoxMap map gets: what it is, what it needs, the
OpenStreetMap credit its licence asks for, and the credit for KnoxMap and the
people who made it (knoxbuild/credits.py).

Afterwards: Project Zomboid -> Workshop -> Create and Upload, and pick the
folder this wrote. Steam gives the item an id; put it in workshop.txt as
id=<number> and every later run keeps it, so the next upload updates that item
instead of making a second one.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from knoxbuild import credits  # noqa: E402

DEFAULT_TAGS = "Build 42;Map;"
# The Workshop's description limit is 8000 characters.
DESCRIPTION_MAX = 8000


def _mod_info(mod_root: Path) -> dict:
    out = {}
    try:
        text = (mod_root / "mod.info").read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out.setdefault(key.strip(), value.strip())
    return out


def description(title: str, about: str, requires: str = "") -> str:
    """The Workshop page text, in Steam's BBCode."""
    needs = (f"[h2]Needs[/h2]\n[list]\n[*] {requires}\n[/list]\n\n" if requires else "")
    return (
        f"[h1]{title}[/h1]\n"
        f"{about}\n\n"
        "[h2]Start a new world[/h2]\n"
        "Pick this map from the spawn list when you make a new game. A world keeps the cells "
        "it has already generated, so a save made before this map was added or changed will "
        "not match it.\n\n"
        f"{needs}"
        "[hr][/hr]\n"
        "[h2]Credits[/h2]\n"
        f"{credits.bbcode()}\n\n"
        "Map data (c) OpenStreetMap contributors, available under the Open Database License "
        "(ODbL): https://www.openstreetmap.org/copyright. Buildings' interiors, residents and "
        "zombies are invented by the generator and do not describe the real places or anyone "
        "connected with them.\n\n"
        "Unofficial fan production for non-commercial purposes, made under the Indie Stone Terms. "
        "Not made, endorsed or supported by The Indie Stone. Thanks to The Indie Stone for "
        "creating Project Zomboid.\n"
    )


def workshop_txt(title: str, body: str, item_id: str = "", tags: str = DEFAULT_TAGS,
                 visibility: str = "public") -> str:
    """workshop.txt as the uploader reads it: one description= line per line of text."""
    if len(body) > DESCRIPTION_MAX:
        raise ValueError(f"the description is {len(body)} characters; the Workshop takes "
                         f"{DESCRIPTION_MAX}")
    lines = ["version=1"]
    if item_id:
        lines.append(f"id={item_id}")
    lines += [f"title={title}", f"tags={tags}", f"visibility={visibility}"]
    lines += [f"description={line}" for line in body.splitlines()]
    return "\n".join(lines) + "\n"


def _existing_id(workshop_file: Path) -> str:
    try:
        for line in workshop_file.read_text(encoding="utf-8").splitlines():
            m = re.match(r"id=(\d+)\s*$", line)
            if m:
                return m.group(1)
    except OSError:
        pass
    return ""


def build(mod_id: str, mods_dir: Path, workshop_dir: Path, title: str = "",
          tags: str = DEFAULT_TAGS, folder: str = "") -> Path:
    """Write ~/Zomboid/Workshop/<folder> for the installed map; returns it."""
    mod_root = mods_dir / mod_id
    if not mod_root.is_dir():
        raise FileNotFoundError(f"{mod_root} is not installed; run the Install step first")
    info = _mod_info(mod_root)
    title = title or info.get("name") or mod_id
    about = info.get("description", "").replace(" Map data (c) OpenStreetMap contributors (ODbL).", "")
    requires = "Erika's Tiles (the map's buildings use its tiles)." if info.get("require") else ""
    target = workshop_dir / (folder or re.sub(r"[^\w .-]+", "_", title).strip() or mod_id)
    keep_id = _existing_id(target / "workshop.txt")
    if target.exists():
        shutil.rmtree(target)
    (target / "Contents" / "mods").mkdir(parents=True)
    shutil.copytree(mod_root, target / "Contents" / "mods" / mod_id)
    preview = mod_root / "preview.png"
    if preview.exists():
        shutil.copy2(preview, target / "preview.png")
    (target / "workshop.txt").write_text(
        workshop_txt(title, description(title, about, requires), keep_id, tags),
        encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mod_id")
    parser.add_argument("--title", default="")
    parser.add_argument("--tags", default=DEFAULT_TAGS)
    parser.add_argument("--folder", default="", help="the folder under ~/Zomboid/Workshop")
    args = parser.parse_args(argv)

    import knoxpaths
    from tools import make_map_mod, workshop_check

    try:
        target = build(args.mod_id, Path(make_map_mod.default_mods_dir()),
                       knoxpaths.zomboid_user_dir() / "Workshop", args.title, args.tags,
                       args.folder)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"wrote {target}")
    results = workshop_check.check(str(target / "Contents" / "mods" / args.mod_id))
    for r in results:
        print(f"  {r['level']:5} {r['what']}")
    print("Now: Project Zomboid -> Workshop -> Create and Upload, and pick that folder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
