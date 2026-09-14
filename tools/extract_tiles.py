"""Rebuild PZ tilesheet PNGs from the game's .pack files.

The mapping tools need a "Tiles" tree of tilesheets, and ship only a GUI
extractor. This does the same job headlessly.

    python tools/extract_tiles.py <packs dir or .pack> <Tilesets.txt> <out 2x dir> [name ...]

With no names it extracts every tileset in Tilesets.txt; otherwise only the
named ones. Output lands at <out>/<tileset>.png, which is where
TilesetManager::getTilesetFileName looks (`<TilesDirectory>/2x/<name>.png`).

The sheets are spread over several packs and Tilesets.txt says which one each
comes from ("file = Overlays2x.pack/appliances_01"). Point this at the
texturepacks folder, not a single pack: reading only Tiles2x.pack yields 467 of
the 543 sheets, and the 76 it leaves out are not merely absent from the map -
WorldEd retries the whole catalogue on every building it loads, so a lot export
spins at one core and never finishes.

Pack format, from PackFile::read in texturepackfile.cpp - little-endian
throughout, strings are int32 length + latin1 bytes:

    "PZPK" magic + int32 version   (absent in the legacy version-0 stream)
    int32 pageCount
    per page:
        string  name
        int32   entryCount
        int32   mask
        per entry:
            string name             e.g. walls_exterior_house_01_32
            int32  x, y, w, h       crop rectangle on the page atlas
            int32  ox, oy           offset of that crop inside the full frame
            int32  fx, fy           full (untrimmed) frame size
        int32   pngLength           (version 1)
        bytes   pngData
"""
from __future__ import annotations

import io
import os
import re
import struct
import sys

from PIL import Image

LEGACY_PAGE_MARKER = bytes.fromhex("efbeadde")


class PackReader:
    def __init__(self, path: str):
        self.f = open(path, "rb")
        magic = self.f.read(4)
        if magic == b"PZPK":
            self.version = self._int()
            self.page_count = self._int()
        else:
            self.f.seek(0)
            self.version = 0
            self.page_count = self._int()

    def _int(self) -> int:
        data = self.f.read(4)
        if len(data) != 4:
            raise EOFError("truncated pack")
        return struct.unpack("<i", data)[0]

    def _string(self) -> str:
        n = self._int()
        if n < 0 or n > 1024 * 1024:
            raise ValueError(f"bad string length {n}")
        return self.f.read(n).decode("latin-1")

    def pages(self):
        """Yield (page_name, entries, read_png) for each page.

        `read_png` must be called exactly once per page before advancing, so
        that the stream stays in sync. It returns the raw PNG bytes; callers
        that do not need the pixels should still call it to skip past them.
        """
        for _ in range(self.page_count):
            name = self._string()
            entry_count = self._int()
            self._int()  # mask
            entries = []
            for _ in range(entry_count):
                ename = self._string()
                vals = struct.unpack("<8i", self.f.read(32))
                entries.append((ename, *vals))

            def read_png() -> bytes:
                if self.version == 0:
                    buf = bytearray()
                    while True:
                        b = self.f.read(1)
                        if not b:
                            raise EOFError("missing legacy page terminator")
                        buf += b
                        if buf.endswith(LEGACY_PAGE_MARKER):
                            return bytes(buf[: -len(LEGACY_PAGE_MARKER)])
                n = self._int()
                return self.f.read(n)

            yield name, entries, read_png


def split_name(entry: str) -> tuple[str, int] | None:
    """'walls_exterior_house_01_32' -> ('walls_exterior_house_01', 32)."""
    m = re.match(r"^(.*)_(\d+)$", entry)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def read_tilesets_txt(path: str) -> tuple[dict[str, tuple[int, int]],
                                          dict[str, str]]:
    """(tileset name -> (columns, rows), tileset name -> pack file name).

    A "file =" line is either a bare sheet name or "<pack>/<sheet>". The pack
    half says where to look; a bare name has to be hunted for across all of
    them.
    """
    sizes: dict[str, tuple[int, int]] = {}
    packs: dict[str, str] = {}
    name = None
    for raw in open(path, encoding="utf-8", errors="replace"):
        s = raw.strip()
        if s.startswith("file = "):
            ref = s[7:]
            name = ref.split("/")[-1]
            if "/" in ref:
                packs[name] = ref.rsplit("/", 1)[0]
        elif s.startswith("size = ") and name:
            cols, rows = s[7:].split(",")
            sizes[name] = (int(cols), int(rows))
            name = None
    return sizes, packs


def extract_pack(pack_path: str, catalog: dict, wanted: set,
                 out_dir: str, merge: bool = False) -> set:
    """Write every wanted sheet this pack holds. Returns the names written.

    With `merge`, a sheet already on disk is added to rather than replaced.
    """
    os.makedirs(out_dir, exist_ok=True)

    # Pass 1, metadata only: which page does each tileset last appear on?
    # Extracting all 543 sheets at once would hold several GB of RGBA at peak,
    # so pass 2 writes each sheet out and frees it as soon as its last page has
    # been read. Skipping the PNG payloads makes this pass cheap.
    scout = PackReader(pack_path)
    last_page: dict[str, int] = {}
    for page_index, (_name, entries, read_png) in enumerate(scout.pages()):
        for ename, *_rest in entries:
            parsed = split_name(ename)
            if parsed and parsed[0] in wanted:
                last_page[parsed[0]] = page_index
        read_png()  # keeps the stream aligned
    scout.f.close()

    reader = PackReader(pack_path)
    print(f"pack version {reader.version}, {reader.page_count} pages; "
          f"want {len(wanted)} tilesets, {len(last_page)} present in this pack")

    sheets: dict[str, Image.Image] = {}
    cell: dict[str, tuple[int, int]] = {}
    placed = 0
    pages_decoded = 0
    written = 0

    def flush(tname: str) -> None:
        nonlocal written
        img = sheets.pop(tname, None)
        if img is None:
            return
        img.save(os.path.join(out_dir, f"{tname}.png"))
        img.close()
        written += 1

    for page_index, (page_name, entries, read_png) in enumerate(reader.pages()):
        relevant = []
        for ename, x, y, w, h, ox, oy, fx, fy in entries:
            parsed = split_name(ename)
            if parsed and parsed[0] in wanted:
                relevant.append((parsed[0], parsed[1], x, y, w, h, ox, oy, fx, fy))
        png = read_png()
        if not relevant:
            continue
        pages_decoded += 1
        page_img = Image.open(io.BytesIO(png)).convert("RGBA")

        for tname, idx, x, y, w, h, ox, oy, fx, fy in relevant:
            cols, rows = catalog[tname]
            if tname not in sheets:
                cell[tname] = (fx, fy)
                existing = os.path.join(out_dir, f"{tname}.png")
                if merge and os.path.exists(existing):
                    with Image.open(existing) as old:
                        sheets[tname] = old.convert("RGBA")
                else:
                    sheets[tname] = Image.new("RGBA", (cols * fx, rows * fy),
                                              (0, 0, 0, 0))
            cw, ch = cell[tname]
            col, row = idx % cols, idx // cols
            if row >= rows:
                continue
            crop = page_img.crop((x, y, x + w, y + h))
            sheets[tname].paste(crop, (col * cw + ox, row * ch + oy))
            placed += 1

        page_img.close()
        # Anything whose last page this was is complete - write it and let go.
        for tname in [t for t, p in last_page.items() if p == page_index]:
            flush(tname)
        if pages_decoded % 25 == 0:
            print(f"  page {page_index}: {pages_decoded} decoded, "
                  f"{placed} tiles, {written} sheets written, "
                  f"{len(sheets)} open")

    for tname in list(sheets):
        flush(tname)
    print(f"decoded {pages_decoded} pages, placed {placed} tiles, "
          f"wrote {written} sheets to {out_dir}")
    return set(last_page)


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    packs_arg, tilesets_txt, out_dir = argv[1], argv[2], argv[3]
    wanted = set(argv[4:])

    catalog, pack_of = read_tilesets_txt(tilesets_txt)
    if not wanted:
        wanted = set(catalog)
    unknown = sorted(wanted - set(catalog))
    if unknown:
        print(f"not in Tilesets.txt, skipping: {unknown}")
        wanted -= set(unknown)

    if os.path.isdir(packs_arg):
        available = {os.path.basename(p): os.path.join(packs_arg, p)
                     for p in os.listdir(packs_arg) if p.endswith(".pack")}
    else:
        available = {os.path.basename(packs_arg): packs_arg}

    # Group by the pack each sheet says it lives in. Anything unprefixed has to
    # be looked for everywhere, so it rides along with every pack.
    by_pack: dict[str, set] = {}
    floating = {n for n in wanted if n not in pack_of}
    for name in wanted - floating:
        pack = pack_of[name]
        if pack in available:
            by_pack.setdefault(pack, set()).add(name)
        else:
            print(f"pack not found for {name}: {pack}")
    for pack in available:
        if pack in by_pack or floating:
            by_pack.setdefault(pack, set()).update(floating)

    found: set = set()
    for pack in sorted(by_pack):
        names = by_pack[pack] - found
        if not names:
            continue
        print(f"== {pack}: looking for {len(names)} sheets ==")
        found |= extract_pack(available[pack], catalog, names, out_dir)

    # Build 42 moved the floor sheets (grass blends, kerbs, ceilings...) into
    # "<pack>.floor.pack" while Tilesets.txt still names the old pack. Some
    # sheets are split between the two: roofs_01 keeps its slopes in Tiles2x
    # but its flat tops (54, 55) went to the floor pack, so every flat roof
    # previewed as blank. The 2x floor packs are therefore merged into every
    # sheet; any other 2x pack is then searched for whatever is still missing.
    # 1x packs are skipped: their frames would make half-size sheets.
    for pack in sorted(p for p in available if "2x" in p.lower() and ".floor." in p):
        print(f"== {pack}: merging floor tiles into {len(wanted)} sheets ==")
        found |= extract_pack(available[pack], catalog, wanted, out_dir, merge=True)
    for pack in sorted(p for p in available if "2x" in p.lower() and ".floor." not in p):
        names = wanted - found
        if not names:
            break
        print(f"== {pack}: retrying {len(names)} missing sheets ==")
        found |= extract_pack(available[pack], catalog, names, out_dir)

    absent = sorted(wanted - found)
    if absent:
        print()
        print(f"no tiles in any pack for ({len(absent)}): {absent}")
    print(f"extracted {len(found)} of {len(wanted)} sheets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
