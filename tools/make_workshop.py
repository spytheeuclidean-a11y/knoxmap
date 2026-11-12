"""Put the Steam Workshop item where Project Zomboid's uploader looks.

    python tools/make_workshop.py [--name KnoxMap]

The game uploads from ~/Zomboid/Workshop/<name>, and wants the item laid out
as Contents/mods/<mod id> with workshop.txt and preview.png beside it. This
copies workshop/ there, with the Reset loot code taken from the one KnoxMap
installs into every map so the two cannot drift apart.

Afterwards: Project Zomboid -> Workshop -> Create and Upload, and pick the
folder this wrote - "KnoxMap" unless --name says otherwise. The uploader lists
that folder, not the mod id inside it, so there is nothing called KnoxMapTools
to choose there. Steam gives the item an id; put it in workshop/workshop.txt
as id=<number> and every later run updates that item instead of making a
second one.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import knoxpaths  # noqa: E402

SOURCE = BASE_DIR / "workshop"
MOD_ID = "KnoxMapTools"
# The one file the item ships, and where it comes from.
RESET_LOOT = BASE_DIR / "knoxbuild" / "lua" / "resetloot.lua"
RESET_LOOT_AT = Path("Contents/mods") / MOD_ID / "common/media/lua/client/KnoxMap" / \
    "KnoxMapResetLoot.lua"
# Every mod.info says poster=poster.png, and the game looks for it beside that
# file. Without one the mod is a blank square in the mod list, so the item's
# own thumbnail is copied to each of them rather than kept in step by hand.
POSTER = SOURCE / "preview.png"
POSTER_AT = [Path("Contents/mods") / MOD_ID / "poster.png",
             Path("Contents/mods") / MOD_ID / "common" / "poster.png",
             Path("Contents/mods") / MOD_ID / "42" / "poster.png"]
# What the uploader reads, and what is only for whoever maintains the page.
UPLOADED = ("Contents", "workshop.txt", "preview.png")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="KnoxMap",
                        help="the folder under ~/Zomboid/Workshop (default: KnoxMap)")
    args = parser.parse_args(argv)

    target = knoxpaths.zomboid_user_dir() / "Workshop" / args.name
    if not SOURCE.is_dir():
        print(f"{SOURCE} is missing", file=sys.stderr)
        return 2

    # Always the current Reset loot, so the Workshop copy is the same code
    # every generated map carries.
    shutil.copy2(RESET_LOOT, SOURCE / RESET_LOOT_AT)
    if POSTER.exists():
        for at in POSTER_AT:
            (SOURCE / at).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(POSTER, SOURCE / at)

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    missing = []
    for name in UPLOADED:
        src = SOURCE / name
        if not src.exists():
            missing.append(name)
            continue
        if src.is_dir():
            shutil.copytree(src, target / name)
        else:
            shutil.copy2(src, target / name)

    print(f"item written to {target}")
    for path in sorted(p for p in target.rglob("*") if p.is_file()):
        print(f"   {path.relative_to(target)}")
    if missing:
        print("\nnot there yet: " + ", ".join(missing), file=sys.stderr)
        if "preview.png" in missing:
            print("  python tools/make_workshop_art.py makes the pictures",
                  file=sys.stderr)
        return 1
    ident = ""
    for line in (SOURCE / "workshop.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("id="):
            ident = line[3:].strip()
    print()
    print("Project Zomboid -> Workshop -> Create and Upload, and pick it there.")
    if not ident:
        print("workshop.txt has no id yet: this uploads as a new item, and Steam")
        print("gives it one. Put that number in workshop/workshop.txt afterwards,")
        print("or the next upload makes a second item instead of updating this.")
    else:
        print(f"workshop.txt has id={ident}, so this updates that item.")
    print(f"The page text is in {SOURCE / 'description.txt'} (Steam BBCode), and")
    print(f"the gallery pictures are in {SOURCE / 'screenshots'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
