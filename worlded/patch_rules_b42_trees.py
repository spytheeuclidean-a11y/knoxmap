"""Repoint WorldEd's Rules.txt at tree tiles Build 42 actually ships, in the
sizes it ships them in, and add rules for the big trees.

The shipped Rules.txt paints forests with `vegetation_trees_01_*` and flowers
with `vegetation_groundcover_01_*`. Build 42 still *defines* those tiles in
newtiledefinitions.tiles.txt, but ships no artwork for them: neither sheet
appears in any of the game's 24 texture packs, and there is no loose PNG for
them anywhere in the install. So BMP to TMX refuses to run - in the GUI as
well as from the command line.

Build 42's replacements are the per-species sheets (e_redmaple_1 and friends).
Their index is not a free choice: of the 24 pictures on each sheet the game
gives a tile definition to the first eight only, four sizes in two seasons,
and it is that definition which carries `tree = 1..4` - the property that
makes the thing a tree the game can grow, chop and blow about in the wind. An
index past the eighth is a picture with no definition behind it: it draws, so
nothing complains, and it is scenery. Every tree KnoxMap has ever placed was
one of those (the first version of this script substituted index for index,
and the old rules asked for 8 to 11), which is why its woods looked flat and
why nothing in them could be felled.

The sizes within a wood come from the rule: a dense wood is grown trees, and
the sparse rules - a scrubby edge, a few trees over grass - keep the saplings
and the half-grown ones.

Then the big trees. These are the jumbo sheets, one tile each whose picture
is several tiles across, and Build 42 leans on them hard: in the game's own
maple forest a jumbo XL or XXL comes up about thirty times as often as a
plain tree (media/lua/server/WorldGen/biomes/worldgen/maple_forest.lua), and
Knox County's own cells carry 1800 big trees. KnoxMap placed none, so its
woods and parks were all undergrowth - "big trees seem to almost never
generate, leading to very disappointing results".

The colours they answer to are in generator/pz_colors.py; the renderer plants
them with a clear square around each, which is what the game's own tree
features do (media/lua/server/WorldGen/features/tree/maple_jumbo*.lua).

    python patch_rules_b42_trees.py <PZMappingTools dir>

Safe to run again, and on a file an older version patched: trees already
pointed at a picture with no definition are moved onto one that has.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

# The green one on each sheet. Deciduous sheets run bare, snowy, spring,
# summer, autumn, late autumn; the evergreens have no seasons to run through.
# Which of them is stored matters less than it looks - Knox County's own maps
# store the bare variant in places - but the summer picture is right either
# way, and is what its cells mostly carry.
DECIDUOUS = ["e_redmaple_1", "e_americanlinden_1", "e_yellowwood_1",
             "e_riverbirch_1", "e_dogwood_1", "e_easternredbud_1",
             "e_cockspurhawthorn_1", "e_carolinasilverbell_1"]
EVERGREEN = ["e_virginiapine_1", "e_canadianhemlock_1", "e_americanholly_1"]

# Sizes 1/4 to 4/4 are the sheet's first four tiles; the game's own world
# generator plants 2 and 3 as "a tree" and 0 and 1 as a sapling.
SIZE_INDEX = {1: 0, 2: 1, 3: 2, 4: 3}

# What sizes a rule's trees get, by what the rule is called. Dense woodland is
# grown trees with the odd three-quarter one; the sparse rules are where a
# sapling belongs.
MIXES = {
    "dense": (4, 3, 4, 4),
    "mixed": (4, 3, 4, 2),
    "light": (3, 2, 4, 1),
}
FLOWER_SHEET = "f_flowerbed_1"
FLOWER_INDICES = [0, 1, 2, 3, 4, 5]

# Rules.txt has no comment syntax - a "#" line makes WorldEd reject the whole
# file - so our rules carry the marker in their labels, as the road ones do.
MARKER = "KnoxMap tree"
# A jumbo sheet is two columns, the left one Jumbo and the right Jumbo L, with
# a row per season; the XL and XXL sheets are one row of seasons. 6 and 7 are
# the summer pair, 3 the summer single, and 0 the evergreens' only green.
TREE_RULES = [
    # The other end of the scale: a young tree, quarter or half grown. The
    # rules call for "a tree" and the size comes from the rule, so a park or a
    # wood had nothing small in it until this colour existed.
    ("Small tree", (255, 0, 4),
     [f"{sp}_{SIZE_INDEX[size]}" for sp in DECIDUOUS + EVERGREEN
      for size in (1, 2)]),
    ("Big tree", (255, 0, 1),
     [f"{sp[:-2]}JUMBO_1_{i}" for sp in DECIDUOUS for i in (6, 7)]
     + [f"{sp[:-2]}JUMBO_1_0" for sp in EVERGREEN]),
    ("Huge tree", (255, 0, 2),
     [f"{sp[:-2]}JUMBOXL_1_3" for sp in DECIDUOUS]
     + [f"{sp[:-2]}JUMBOXL_1_0" for sp in EVERGREEN]),
    ("Giant tree", (255, 0, 3),
     [f"{sp[:-2]}JUMBOXXL_1_3" for sp in DECIDUOUS]
     + [f"{sp[:-2]}JUMBOXXL_1_0" for sp in EVERGREEN]),
]


def mix_for(label: str) -> tuple[int, ...]:
    """Which size mix a rule's trees take, from the rule's own name."""
    name = label.lower()
    if "sparse" in name or "few" in name:
        return MIXES["light"]
    if "dense" in name or name == "trees":
        return MIXES["dense"]
    return MIXES["mixed"]


def sheet_sizes(tilesets_txt: Path) -> dict[str, tuple[int, int]]:
    out, name = {}, None
    if not tilesets_txt.is_file():
        return out
    for raw in tilesets_txt.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if s.startswith("file = "):
            name = s[7:].split("/")[-1]
        elif s.startswith("size = ") and name:
            c, r = s[7:].split(",")
            out[name] = (int(c), int(r))
            name = None
    return out


def rewrite_trees(text: str) -> tuple[str, int]:
    """Point every tree entry at a tile the game defines as a tree.

    Takes both the shipped names and the ones an older version of this script
    wrote, which is what makes it safe to run twice. Entries already on a
    defined tile (index 0 to 7) are left alone, so running it again changes
    nothing.
    """
    stale = re.compile(r"\b(?:vegetation_trees_01|e_\w+_1)_(?:[89]|1[0-5])\b")
    # The species carry on from one rule to the next, so the file as a whole
    # works through all of them: a rule holds four trees at most, and starting
    # over at each would leave half the species on the shelf and every wood
    # made of the same four.
    count = {"n": 0}

    def rewrite_block(block: re.Match) -> str:
        body = block.group(0)
        label = re.search(r"label = (.*)", body)
        label = label.group(1).strip() if label else ""
        species = EVERGREEN if "fir" in label.lower() else DECIDUOUS
        mix = mix_for(label)
        seen = {"n": 0}

        def one(_m: re.Match) -> str:
            i, n = seen["n"], count["n"]
            seen["n"] += 1
            count["n"] += 1
            sheet = species[n % len(species)]
            return f"{sheet}_{SIZE_INDEX[mix[i % len(mix)]]}"

        return stale.sub(one, body)

    return re.sub(r"rule\s*\n\{.*?\n\}", rewrite_block, text, flags=re.S), count["n"]


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".")
    cfg = root / "config"
    rules = cfg / "Rules.txt"
    tiles_dir = root / "Tiles" / "2x"
    if not rules.is_file():
        print(f"Rules.txt not found under {cfg}", file=sys.stderr)
        return 2

    sizes = sheet_sizes(cfg / "Tilesets.txt")

    # Every sheet named must exist on disk and be big enough for the indices
    # about to be referenced, or WorldEd rejects the whole file.
    def unusable(tile: str) -> str:
        sheet, _, index = tile.rpartition("_")
        if not (tiles_dir / f"{sheet}.png").exists():
            return f"{sheet}: PNG not extracted"
        cols, rows = sizes.get(sheet, (0, 0))
        if cols and int(index) >= cols * rows:
            return f"{sheet}: index {index} outside {cols}x{rows}"
        return ""

    needed = [f"{sheet}_{max(SIZE_INDEX.values())}" for sheet in DECIDUOUS + EVERGREEN]
    needed.append(f"{FLOWER_SHEET}_{max(FLOWER_INDICES)}")
    problems = [bad for bad in map(unusable, needed) if bad]
    if problems:
        print("refusing to patch:", *problems, sep="\n  ", file=sys.stderr)
        return 3
    # A tree whose sheet this install has not got is left out on its own,
    # rather than costing the other rules their fix as well.
    ours, left_out = [], []
    for label, colour, tiles in TREE_RULES:
        keep = [t for t in tiles if not unusable(t)]
        left_out += [t for t in tiles if t not in keep]
        if keep:
            ours.append((label, colour, keep))

    text = rules.read_text(encoding="utf-8", errors="replace")
    before = text
    if "vegetation_trees_01" in text:
        backup = rules.with_suffix(".txt.pre-b42")
        if not backup.exists():
            shutil.copy2(rules, backup)
            print(f"backed up to {backup.name}")

    text, n_trees = rewrite_trees(text)

    flower_counter = {"n": 0}

    def swap_flower(_m: re.Match) -> str:
        idx = FLOWER_INDICES[flower_counter["n"] % len(FLOWER_INDICES)]
        flower_counter["n"] += 1
        return f"{FLOWER_SHEET}_{idx}"

    text, n_flowers = re.subn(r"vegetation_groundcover_01_\d+", swap_flower, text)

    # Our own rules, rewritten whole, so a changed tile reaches an install
    # patched by an older version.
    old = len(re.findall(rf"label = {MARKER} ", text))
    text = re.sub(rf"\n?rule\n\{{\n    label = {MARKER} .*?\n\}}\n?", "\n", text, flags=re.S)
    blocks = []
    for label, (r, g, b), tiles in ours:
        listed = "".join(f"        {t}\n" for t in tiles)
        blocks.append("rule\n{\n"
                      f"    label = {MARKER} {label}\n"
                      "    bitmap = 1\n"
                      f"    color = {r} {g} {b}\n"
                      f"    tiles = [\n{listed}    ]\n"
                      "    layer = 0_Vegetation\n"
                      "}\n")
    text = text.rstrip("\n") + "\n\n" + "\n".join(blocks)

    if text == before:
        print("trees already up to date")
        return 0
    rules.write_text(text, encoding="utf-8")
    print(f"tree tiles repointed  : {n_trees} across "
          f"{len(DECIDUOUS)} species and {len(SIZE_INDEX)} sizes")
    print(f"tree rules written    : {len(blocks)} (replacing {old})")
    if left_out:
        print(f"    left out {len(left_out)} trees this install has no "
              f"sheet for: {', '.join(sorted(set(left_out))[:4])}")
    print(f"flower tiles repointed: {n_flowers} -> {FLOWER_SHEET}")
    print(f"wrote {rules}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
