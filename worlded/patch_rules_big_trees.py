"""Add Build 42's jumbo trees to the tree rules in WorldEd's Rules.txt.

Every rule that paints trees picks one tile at random from its list, and the
lists are all the ordinary species (e_redmaple_1_8 and friends), so every tree
on a map is the same modest size and a wood reads as a field of saplings. The
game also ships a jumbo version of three of them, e_redmapleJUMBO_1 and so on,
with the same indices. Putting those into each list beside the ordinary ones
mixes tall trees in with the rest: about two in five come out large.

Safe to run twice (a list that already has a jumbo tile is left alone) and
after patch_rules_b42_trees.py, which is what sets the ordinary species up.

    python patch_rules_big_trees.py <PZMappingTools dir>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# The species the game has a jumbo sheet for that Setup extracts.
BIG_SPECIES = ("e_redmaple", "e_riverbirch", "e_dogwood")

_TILES = re.compile(r"(tiles\s*=\s*\[)(.*?)(\])", re.S)
_TREE = re.compile(r"^([ \t]*)(%s)_1_(\d+)[ \t]*$" % "|".join(BIG_SPECIES), re.M)


def sheet_sizes(tilesets_txt: str) -> dict[str, tuple[int, int]]:
    out, name = {}, None
    for raw in tilesets_txt.splitlines():
        s = raw.strip()
        if s.startswith("file = "):
            name = s[7:].split("/")[-1]
        elif s.startswith("size = ") and name:
            c, r = s[7:].split(",")
            out[name] = (int(c), int(r))
            name = None
    return out


def add_big_trees(text: str, usable) -> tuple[str, int]:
    """`text` with a jumbo tile added to every tree list that lacks one.
    `usable(species, index)` says whether the sheet has that tile on disk."""
    added = 0

    def one_list(m: re.Match) -> str:
        nonlocal added
        body = m.group(2)
        if "JUMBO" in body:
            return m.group(0)
        extra = []
        for t in _TREE.finditer(body):
            species, index = t.group(2), int(t.group(3))
            if usable(species, index):
                extra.append(f"{t.group(1)}{species}JUMBO_1_{index}")
        if not extra:
            return m.group(0)
        added += len(extra)
        return m.group(1) + body.rstrip() + "\n" + "\n".join(extra) + "\n    " + m.group(3)

    return _TILES.sub(one_list, text), added


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".")
    cfg = root / "config"
    rules = cfg / "Rules.txt"
    if not rules.is_file():
        print(f"Rules.txt not found under {cfg}", file=sys.stderr)
        return 2
    sizes = sheet_sizes((cfg / "Tilesets.txt").read_text(encoding="utf-8", errors="replace"))
    tiles_dir = root / "Tiles" / "2x"

    def usable(species: str, index: int) -> bool:
        sheet = f"{species}JUMBO_1"
        if not (tiles_dir / f"{sheet}.png").exists() or sheet not in sizes:
            return False
        cols, rows = sizes[sheet]
        return index < cols * rows

    text = rules.read_text(encoding="utf-8", errors="replace")
    new, n = add_big_trees(text, usable)
    if not n:
        print("no tree list needs jumbo trees (already patched, or the sheets are missing)")
        return 0
    backup = rules.with_suffix(".txt.pre-jumbo")
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")
    rules.write_text(new, encoding="utf-8")
    print(f"jumbo trees added: {n} tiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
