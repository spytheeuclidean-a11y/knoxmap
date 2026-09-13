"""Drop catalogue entries whose tilesheet does not exist.

Tilesets.txt is inherited from Build 41 and still lists sheets that no Build 42
pack contains. They are not harmless dead entries: TilesetManager retries the
whole catalogue every time a map or building is loaded, and a lot export loads
thousands of buildings. A 7x7 town spent three minutes at 100% of one core,
writing the same 74-name "Missing tileset images" warning five times a second,
and produced no cells at all.

Run the extractor first - most of what looks absent is simply in another pack.
Only entries with no source anywhere should be pruned.

    python tools/prune_tilesets.py <Tilesets.txt> <Tiles/2x dir>
"""
from __future__ import annotations

import os
import re
import shutil
import sys


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    cfg, tiles_dir = argv[1], argv[2]
    text = open(cfg, encoding="utf-8", errors="replace").read()

    blocks = re.findall(r"tileset\s*\{[^}]*\}", text)
    dropped = []
    for block in blocks:
        m = re.search(r"file\s*=\s*(\S+)", block)
        if not m:
            continue
        name = m.group(1).split("/")[-1]
        if os.path.exists(os.path.join(tiles_dir, name + ".png")):
            continue
        dropped.append(name)
        text = text.replace(block + "\n", "", 1)

    if not dropped:
        print("nothing to prune — every catalogue entry has a sheet")
        return 0

    backup = cfg + ".pre-prune"
    if not os.path.exists(backup):
        shutil.copy2(cfg, backup)
        print(f"backed up to {os.path.basename(backup)}")
    open(cfg, "w", encoding="utf-8").write(text)
    print(f"pruned {len(dropped)}: {', '.join(sorted(dropped))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
