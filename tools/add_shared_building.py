"""Put a building somebody sent in into the library KnoxMap ships with.

Somebody builds a house in the window, presses Share and sends the file; this
is the other end of that. It checks the file, copies the building into
`presets/library/` and records what it is and who built it, so the next
release carries it and every map can be built from it.

    python tools/add_shared_building.py <file.knoxbuilding.json> ...
    python tools/add_shared_building.py --check <file> ...     look, add nothing
    python tools/add_shared_building.py --list                 what is in there
    python tools/add_shared_building.py --remove "A Name"      take one out

Options when adding:

    --name "What To Call It"   instead of the name it came with
    --kind police              what it stands in for ("" for any building)
    --author "Who Built It"    instead of the name in the file
    --replace                  a building already called that is overwritten

What goes in is committed, so look at the building before adding it: open the
file in KnoxMap (Hand-built buildings, "Take one in") and build a small map
with it. A .tbx names tiles, and a building naming tiles the game does not
have is not dangerous but is full of holes.
"""
from __future__ import annotations

import datetime as _datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from knoxbuild import presets as P  # noqa: E402
from knoxbuild import share as S  # noqa: E402


def describe(entry: dict) -> str:
    kind = entry.get("kind") or "any building"
    who = f", by {entry['author']}" if entry.get("author") else ""
    return (f"{entry['name']}: {entry['width']}x{entry['height']}, "
            f"{entry['storeys']} storey{'' if entry['storeys'] == 1 else 's'}, "
            f"{entry['rooms']} rooms, stands in for {kind}{who}"
            + (" (with its drawing)" if entry.get("design") else ""))


def listing() -> int:
    on_disk = {p["name"] for p in P._in_folder(P.library_folder(ROOT))}
    recorded = P.shipped(ROOT)
    for name in sorted(on_disk | set(recorded)):
        about = recorded.get(name, {})
        where = "" if name in on_disk else "   (recorded, but no .tbx!)"
        print(f"  {name:30} {about.get('kind') or 'any building':16}"
              f" {about.get('author') or '-':20} {about.get('added') or ''}{where}")
    print(f"{len(on_disk)} buildings in {P.library_folder(ROOT)}")
    return 0


def remove(name: str) -> int:
    clean = P.safe_name(name)
    folder = P.library_folder(ROOT)
    gone = False
    for path in (os.path.join(folder, f"{clean}.tbx"),
                 os.path.join(folder, f"{clean}{P.DESIGN_SUFFIX}")):
        if os.path.exists(path):
            os.remove(path)
            gone = True
    recorded = P.shipped(ROOT)
    if recorded.pop(clean, None) is not None:
        P.write_shipped(ROOT, recorded)
        gone = True
    print(f"{'removed' if gone else 'no building called'} {clean}")
    return 0 if gone else 1


def add(paths: list[str], check_only: bool, name: str, kind: str | None,
        author: str, replace: bool) -> int:
    folder = P.library_folder(ROOT)
    recorded = P.shipped(ROOT)
    added = []
    for path in paths:
        entry, problem = S.load(path)
        if problem:
            print(f"{os.path.basename(path)}: {problem}", file=sys.stderr)
            return 3
        if name:
            entry["name"] = P.safe_name(name)
        if author:
            entry["author"] = author[:S.MAX_AUTHOR]
        if kind is not None:
            known = {k["id"] for k in P.kinds()}
            if kind and kind not in known:
                print(f"No such kind of building: {kind}\n"
                      f"  one of: {', '.join(sorted(known))}", file=sys.stderr)
                return 2
            entry["kind"] = kind
        print(f"  {describe(entry)}")
        if check_only:
            continue
        there = os.path.join(folder, f"{entry['name']}.tbx")
        if os.path.exists(there) and not replace:
            print(f"{entry['name']}: already in the library. Pass --replace to "
                  f"overwrite it, or --name to add it under another name.",
                  file=sys.stderr)
            return 4
        about = S.install(ROOT, entry, folder=folder)
        recorded[entry["name"]] = {
            "kind": entry.get("kind") or P.ANY,
            "author": entry.get("author") or "",
            "notes": entry.get("notes") or "",
            "added": _datetime.date.today().isoformat()}
        added.append((entry, about))
    if check_only:
        print("checked, nothing added")
        return 0
    P.write_shipped(ROOT, recorded)
    print(f"\nwrote {len(added)} into {folder}")
    print("Commit the .tbx, the drawing beside it and library.json, and put a "
          "line in the changelog:")
    for entry, _about in added:
        who = f" by {entry['author']}" if entry.get("author") else ""
        print(f"  - **{entry['name']}**{who}, a {entry['width']}x"
              f"{entry['height']} {entry.get('kind') or 'building'}, is in the "
              f"library of hand-built buildings.")
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    if args[0] == "--list":
        return listing()
    if args[0] == "--remove":
        if len(args) < 2:
            print("--remove needs the name of a building", file=sys.stderr)
            return 2
        return remove(args[1])
    check_only = replace = False
    name = author = ""
    kind = None
    paths = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--check":
            check_only = True
        elif arg == "--replace":
            replace = True
        elif arg in ("--name", "--kind", "--author"):
            if i + 1 >= len(args):
                print(f"{arg} needs a value", file=sys.stderr)
                return 2
            value = args[i + 1]
            i += 1
            if arg == "--name":
                name = value
            elif arg == "--author":
                author = value
            else:
                kind = value.strip().lower()
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}\n{__doc__}", file=sys.stderr)
            return 2
        else:
            paths.append(arg)
        i += 1
    if not paths:
        print("Name at least one shared building file.", file=sys.stderr)
        return 2
    if name and len(paths) > 1:
        print("--name renames one building; add them one at a time.",
              file=sys.stderr)
        return 2
    try:
        return add(paths, check_only, name, kind, author, replace)
    except OSError as exc:
        print(f"Could not write the library: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
