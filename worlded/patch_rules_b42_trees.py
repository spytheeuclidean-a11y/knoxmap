"""Repoint WorldEd's Rules.txt at tree tiles Build 42 actually ships.

The shipped Rules.txt paints forests with `vegetation_trees_01_*` and flowers
with `vegetation_groundcover_01_*`. Build 42 still *defines* those tiles in
newtiledefinitions.tiles.txt, but ships no artwork for them: neither sheet
appears in any of the game's 24 texture packs, and there is no loose PNG for
them anywhere in the install. So BMP to TMX refuses to run - in the GUI as well
as from the command line.

Build 42's replacements are the per-species sheets (e_redmaple_1 and friends),
which use the same index convention: 0-7 bare, 8-11 green, 16+ autumn. The old
rules asked for indices 8-11, so the substitution is index-for-index; we just
rotate through several species so a forest is not a monoculture.

    python patch_rules_b42_trees.py <PZMappingTools dir>
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

TREE_SPECIES = [
    "e_redmaple_1",
    "e_riverbirch_1",
    "e_americanlinden_1",
    "e_dogwood_1",
]
FLOWER_SHEET = "f_flowerbed_1"
FLOWER_INDICES = [0, 1, 2, 3, 4, 5]


def sheet_sizes(tilesets_txt: Path) -> dict[str, tuple[int, int]]:
    out, name = {}, None
    for raw in tilesets_txt.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if s.startswith("file = "):
            name = s[7:].split("/")[-1]
        elif s.startswith("size = ") and name:
            c, r = s[7:].split(",")
            out[name] = (int(c), int(r))
            name = None
    return out


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".")
    cfg = root / "config"
    rules = cfg / "Rules.txt"
    tiles_dir = root / "Tiles" / "2x"
    if not rules.is_file():
        print(f"Rules.txt not found under {cfg}", file=sys.stderr)
        return 2

    sizes = sheet_sizes(cfg / "Tilesets.txt")

    # Every replacement sheet must exist on disk and be tall enough for the
    # indices we are about to reference.
    problems = []
    for sheet, needed in [(s, 11) for s in TREE_SPECIES] + \
                         [(FLOWER_SHEET, max(FLOWER_INDICES))]:
        if not (tiles_dir / f"{sheet}.png").exists():
            problems.append(f"{sheet}: PNG not extracted")
        elif sheet in sizes:
            cols, rows = sizes[sheet]
            if needed >= cols * rows:
                problems.append(f"{sheet}: index {needed} outside {cols}x{rows}")
    if problems:
        print("refusing to patch:", *problems, sep="\n  ", file=sys.stderr)
        return 3

    text = rules.read_text(encoding="utf-8", errors="replace")
    if "vegetation_trees_01" not in text and "vegetation_groundcover_01" not in text:
        print("already patched")
        return 0

    backup = rules.with_suffix(".txt.pre-b42")
    if not backup.exists():
        shutil.copy2(rules, backup)
        print(f"backed up to {backup.name}")

    counter = {"n": 0}

    def swap_tree(m: re.Match) -> str:
        species = TREE_SPECIES[counter["n"] % len(TREE_SPECIES)]
        counter["n"] += 1
        return f"{species}_{m.group(1)}"

    text, n_trees = re.subn(r"vegetation_trees_01_(\d+)", swap_tree, text)

    flower_counter = {"n": 0}

    def swap_flower(_m: re.Match) -> str:
        idx = FLOWER_INDICES[flower_counter["n"] % len(FLOWER_INDICES)]
        flower_counter["n"] += 1
        return f"{FLOWER_SHEET}_{idx}"

    text, n_flowers = re.subn(r"vegetation_groundcover_01_\d+", swap_flower, text)

    rules.write_text(text, encoding="utf-8")
    print(f"tree tiles repointed : {n_trees} across {len(TREE_SPECIES)} species")
    print(f"flower tiles repointed: {n_flowers} -> {FLOWER_SHEET}")
    print(f"wrote {rules}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
