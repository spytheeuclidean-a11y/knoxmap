"""Draw a compiled map the way the game draws it, from the files the game loads.

    python tools/render_lots.py output/<map> out.png X Y W H [--max-level N] [--scale S]
    python tools/render_lots.py "<game>/media/maps/Muldraugh, KY" out.png X Y W H --world

With --world, X Y are world tile coordinates and the folder holds the
.lotheader files itself - a vanilla map, for comparing against the real thing.

X Y W H is an area of the map in its own tile coordinates (the same as the
terrain bitmap). --max-level cuts the view off above a floor, the way the game
hides the storeys above you when you walk inside, so interiors show; without it
you see rooftops. --scale shrinks the picture (1 = the game at 1x zoom).

This reads the compiled .lotheader/.lotpack files - every floor, wall, window,
door, piece of furniture, roof, tree and lift door exactly as WorldEd wrote
them for the game - and stacks their tile images isometrically. What it leaves
out is what the game adds at run time: lighting and shadows, weather, zombies,
loot, vehicles, and the fading of walls in front of the player.

File layout (WorldEd's LotFilesWorker256, little-endian):

    X_Y.lotheader      "LOTH", version, tile count, tile names ("name\\n"),
                       chunk width, chunk height (8), min level, max level, ...
    world_X_Y.lotpack  "LOTP", version, 1024 chunk offsets (int64, chunk x*32+y),
                       then per chunk: for z, for x 0..7, for y 0..7 either
                       (-1, run of empty squares) or (count+1, room id, count tile ids)
Cells are 256 tiles; the map's tile 0,0 is world tile (world origin cell x 300).
"""
from __future__ import annotations

from collections import OrderedDict
import os
import re
import struct
import subprocess
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CELL = 256
# The broadleaf species sheets (worlded/patch_rules_b42_trees.py DECIDUOUS).
SUMMER_SHEETS = {"e_redmaple_1", "e_americanlinden_1", "e_yellowwood_1",
                 "e_riverbirch_1", "e_dogwood_1", "e_easternredbud_1",
                 "e_cockspurhawthorn_1", "e_carolinasilverbell_1"}
CHUNKS = 32
CHUNK = 8
LEVEL_PX = 96          # screen height of one storey at 1x

# Persistent module-level LRU cache for decoded tile sheets and resized sprites
_SHEETS: OrderedDict[str, Image.Image | None] = OrderedDict()
_MAX_SHEETS = 48
_SPRITE_CACHE: OrderedDict[tuple[str, int], tuple | None] = OrderedDict()
_MAX_SPRITE_CACHE = 16384


def _lru_get(cache: OrderedDict, key):
    if key in cache:
        cache.move_to_end(key)
        return True, cache[key]
    return False, None


def _lru_put(cache: OrderedDict, key, value, limit: int) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > limit:
        cache.popitem(last=False)


def read_header(path: str) -> tuple[list[str], int, int]:
    with open(path, "rb") as fh:
        data = fh.read()
    pos = 4 if data[:4] == b"LOTH" else 0
    pos += 4                                   # version
    (count,) = struct.unpack_from("<i", data, pos); pos += 4
    names = []
    for _ in range(count):
        end = data.index(b"\n", pos)
        names.append(data[pos:end].decode("latin-1"))
        pos = end + 1
    _cw, _ch, lo, hi = struct.unpack_from("<4i", data, pos)
    return names, lo, hi


def _iter_squares(pack: str, names: list[str], lo: int, hi: int,
                  want: tuple[int, int, int, int],
                  max_level: int | None = None):
    """Yield (sx, sy, z, ids) for squares inside `want` without building a dict."""
    with open(pack, "rb") as fh:
        data = fh.read()
    pos = 4 if data[:4] == b"LOTP" else 0
    pos += 4
    (n,) = struct.unpack_from("<i", data, pos); pos += 4
    offsets = struct.unpack_from(f"<{n}q", data, pos)
    wx0, wy0, wx1, wy1 = want
    for cx in range(CHUNKS):
        for cy in range(CHUNKS):
            bx, by = cx * CHUNK, cy * CHUNK
            if bx + CHUNK <= wx0 or bx >= wx1 or by + CHUNK <= wy0 or by >= wy1:
                continue
            p = offsets[cx * CHUNKS + cy]
            if p < 0:
                continue
            skip = 0
            for z in range(lo, hi + 1):
                for x in range(CHUNK):
                    for y in range(CHUNK):
                        if skip > 0:
                            skip -= 1
                            continue
                        (count,) = struct.unpack_from("<i", data, p); p += 4
                        if count == -1:
                            (skip,) = struct.unpack_from("<i", data, p); p += 4
                            skip -= 1
                            continue
                        _room = struct.unpack_from("<i", data, p); p += 4
                        ids = struct.unpack_from(f"<{count - 1}i", data, p); p += 4 * (count - 1)
                        if max_level is not None and z > max_level:
                            continue
                        sx, sy = bx + x, by + y
                        if wx0 <= sx < wx1 and wy0 <= sy < wy1:
                            yield sx, sy, z, ids


def read_squares(pack: str, names: list[str], lo: int, hi: int,
                 want: tuple[int, int, int, int]) -> dict:
    """{(cell-local x, y, z): [tile names]} for squares inside `want` (x0, y0, x1, y1)."""
    return {
        (sx, sy, z): [names[i] for i in ids]
        for sx, sy, z, ids in _iter_squares(pack, names, lo, hi, want)
    }


def _sprite_for(name: str, tw: int, tiles_dir):
    import numpy as np

    key = (name, tw)
    hit, cached = _lru_get(_SPRITE_CACHE, key)
    if hit:
        return cached
    resample = Image.BILINEAR if tw <= 16 else Image.LANCZOS
    entry = None
    m = re.match(r"^(.*)_(\d+)$", name)
    if m:
        sheet_name, idx = m.group(1), int(m.group(2))
        # A broadleaf tree is stored as its bare picture (sizes 0-3) and
        # the game draws the season's; the picture shows summer, which is
        # four rows of four on: bare, snow, spring, summer.
        if sheet_name in SUMMER_SHEETS and idx < 4:
            idx += 12
        shit, sheet = _lru_get(_SHEETS, sheet_name)
        if not shit:
            path = tiles_dir / f"{sheet_name}.png"
            sheet = Image.open(path).convert("RGBA") if path.exists() else None
            _lru_put(_SHEETS, sheet_name, sheet, _MAX_SHEETS)
        if sheet is not None:
            cols = max(1, sheet.width // 128)
            cx, cy = (idx % cols) * 128, (idx // cols) * 256
            if cy + 256 <= sheet.height:
                im = sheet.crop((cx, cy, cx + 128, cy + 256)).resize((tw, tw * 2), resample)
                bbox = im.getbbox()
                if bbox is not None:
                    ox, oy, x1, y1 = bbox
                    rgba_u8 = np.ascontiguousarray(im.crop(bbox), dtype=np.uint8)
                    arr = rgba_u8.astype(np.uint16)
                    a = arr[:, :, 3:4]
                    opaque = bool(np.all(rgba_u8[:, :, 3] == 255))
                    entry = (ox, oy, x1 - ox, y1 - oy, arr[:, :, :3] * a, 255 - a, opaque, rgba_u8)
    _lru_put(_SPRITE_CACHE, key, entry, _MAX_SPRITE_CACHE)
    return entry


def _write_sprite_bank(path: str, names: list[str], tw: int, tiles_dir) -> int:
    entries = []
    for name in names:
        sp = _sprite_for(name, tw, tiles_dir)
        if sp is not None:
            ox, oy, sw, sh, _pre, _inv, opaque, rgba_u8 = sp
            entries.append((name.encode("utf-8"), ox, oy, sw, sh, 1 if opaque else 0, rgba_u8.tobytes()))
    with open(path, "wb") as fh:
        fh.write(b"SPR1")
        fh.write(struct.pack("<I", len(entries)))
        for bname, ox, oy, sw, sh, opaque, raw in entries:
            fh.write(struct.pack("<H", len(bname)))
            fh.write(bname)
            fh.write(struct.pack("<hhhhB", ox, oy, sw, sh, opaque))
            fh.write(raw)
    return len(entries)


def _render_rust(lots: str, ox: int, oy: int, X: int, Y: int, W: int, H: int,
                 tw: int, max_level: int | None, skip_blends: bool,
                 tiles_dir, progress=None) -> tuple[bool, Image.Image | None]:
    """Use the Rust `knoxlots` binary when built. Returns (handled, image_or_none)."""
    if os.environ.get("KNOXMAP_PYTHON_RENDER") == "1":
        return False, None
    try:
        from tools.compile_map import knoxlots_exe
        exe = knoxlots_exe()
    except Exception:
        exe = None
    if exe is None:
        return False, None

    kw = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW

    if progress:
        progress(2, "Scanning compiled tile names…")
    tl = subprocess.run(
        [str(exe), "tile-list", lots, str(ox), str(oy), str(X), str(Y), str(W), str(H)],
        capture_output=True, text=True, **kw,
    )
    if tl.returncode != 0:
        return False, None
    names = [line for line in tl.stdout.splitlines() if line]
    if not names:
        return True, None

    with tempfile.TemporaryDirectory() as tmp:
        spr_path = os.path.join(tmp, "sprites.bin")
        raw_path = os.path.join(tmp, "canvas.raw")
        if progress:
            progress(5, f"Preparing {len(names)} tile sprites…")
        _write_sprite_bank(spr_path, names, tw, tiles_dir)
        cmd = [str(exe), "render", lots, spr_path, raw_path,
               str(ox), str(oy), str(X), str(Y), str(W), str(H), str(tw)]
        if max_level is not None:
            cmd.extend(["--max-level", str(max_level)])
        if skip_blends:
            cmd.append("--skip-blends")
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", **kw,
        )
        assert proc.stderr is not None
        for line in proc.stderr:
            if progress and line.startswith("PROGRESS "):
                parts = line.rstrip("\r\n").split(" ", 2)
                if len(parts) == 3:
                    try:
                        progress(int(parts[1]), parts[2])
                    except ValueError:
                        pass
        rc = proc.wait()
        if rc == 3:
            return True, None
        if rc != 0 or not os.path.isfile(raw_path):
            return False, None
        with open(raw_path, "rb") as fh:
            hdr = fh.read(16)
            if len(hdr) != 16 or hdr[:4] != b"RAW1":
                return False, None
            cw, ch, _pad = struct.unpack("<III", hdr[4:16])
            rgb_bytes = fh.read()
        im = Image.frombuffer("RGB", (cw, ch), rgb_bytes, "raw", "RGB", 0, 1).convert("RGBA")
        return True, im


def render(map_dir: str, X: int, Y: int, W: int, H: int,
           max_level: int | None = None, scale: float = 1.0,
           world: bool = False, progress=None) -> Image.Image | None:
    """An area of a compiled map, drawn the way the game draws it.

    Returns the picture, or None when nothing in that area has been compiled
    yet. The caller decides what to do with it - the command line writes it
    out, knoxbuild/picture.py frames it.
    """
    import knoxpaths
    from knoxbuild.world import WORLD_ORIGIN_CELLS, _project_box

    if world:
        ox = oy = 0
        lots = map_dir
    else:
        # The origin this map was built at, not the default one: a PC with
        # more than one KnoxMap map puts them side by side.
        name = os.path.basename(os.path.abspath(map_dir).rstrip(os.sep))
        box = _project_box(os.path.join(map_dir, f"{name}.pzw")) or WORLD_ORIGIN_CELLS
        ox, oy = box[0] * 300, box[1] * 300
        lots = os.path.join(map_dir, "lots")
    tiles_dir = knoxpaths.mapping_tools_dir() / "Tiles" / "2x"
    tw = max(4, round(64 * scale))
    skip_blends = (scale < 0.25)

    handled, rust_img = _render_rust(
        lots, ox, oy, X, Y, W, H, tw, max_level, skip_blends, tiles_dir, progress=progress,
    )
    if handled:
        return rust_img

    # Stream populated squares directly into per-level buckets (sorted in-place
    # and freed level-by-level) instead of holding both a giant dict and a
    # sorted copy of every square in RAM.
    by_z: dict[int, list[tuple[int, int, int, tuple[str, ...]]]] = {}
    intern: dict[tuple[str, ...], tuple[str, ...]] = {}
    top = 0
    wx0, wy0 = ox + X, oy + Y
    # At very small scales (broad county/town overviews), individual grass blend
    # overlays are sub-pixel and skipping them cuts out over a million alpha-blends.
    cxs = range(wx0 // CELL, (wx0 + W - 1) // CELL + 1)
    cys = range(wy0 // CELL, (wy0 + H - 1) // CELL + 1)
    total_cells = max(1, len(cxs) * len(cys))
    done_cells = 0
    for cxw in cxs:
        for cyw in cys:
            done_cells += 1
            if progress:
                pct = int(45 * done_cells / total_cells)
                progress(pct, f"Reading compiled cells ({done_cells}/{total_cells})…")
            header = os.path.join(lots, f"{cxw}_{cyw}.lotheader")
            pack = os.path.join(lots, f"world_{cxw}_{cyw}.lotpack")
            if not (os.path.exists(header) and os.path.exists(pack)):
                continue
            names, lo, hi = read_header(header)
            base_x, base_y = cxw * CELL, cyw * CELL
            local = (wx0 - base_x, wy0 - base_y, wx0 + W - base_x, wy0 + H - base_y)
            local_intern: dict[tuple[int, ...], tuple[str, ...]] = {}
            for sx, sy, z, ids in _iter_squares(pack, names, lo, hi, local, max_level=max_level):
                tiles = local_intern.get(ids)
                if tiles is None:
                    raw = tuple(names[i] for i in ids)
                    if skip_blends:
                        # Keep the base terrain tile (raw[0] on z == 0, which is
                        # itself a blends_natural / blends_street tile) and only
                        # skip extra blend overlays stacked on top of it.
                        head = raw[:1] if z == 0 else ()
                        tail = tuple(t for t in raw[len(head):] if not t.startswith("blends_"))
                        raw = head + tail
                    tiles = intern.setdefault(raw, raw) if raw else ()
                    local_intern[ids] = tiles
                if not tiles:
                    continue
                dx = base_x + sx - wx0
                dy = base_y + sy - wy0
                bucket = by_z.get(z)
                if bucket is None:
                    bucket = []
                    by_z[z] = bucket
                bucket.append((dx + dy, dx, dy, tiles))
                if z > top:
                    top = z
    intern.clear()
    if not by_z:
        return None
    if max_level is not None:
        top = min(top, max_level)

    import numpy as np

    def sprite_for(name: str):
        return _sprite_for(name, tw, tiles_dir)

    # Sprites are shrunk before they are stacked, so a whole district can be
    # drawn: at full size two square kilometres is a 96,000-pixel-wide image.
    TW = tw
    half, quarter, level_px = TW // 2, TW // 4, round(LEVEL_PX * TW / 64)
    width = (W + H) * half + TW
    height = (W + H) * quarter + 2 * TW + (top + 1) * level_px
    canvas = np.empty((height, width, 3), dtype=np.uint8)
    canvas[:] = (24, 26, 28)
    lift = (top + 1) * level_px

    # Iterating sorted populated squares per level directly is mathematically
    # equivalent to the (z, s, dx) triple loop while skipping empty coordinates
    # and freeing each level's list as soon as it has been composited.
    total_squares = max(1, sum(len(v) for v in by_z.values()))
    done_squares = 0
    for z in sorted(by_z):
        rows = by_z.pop(z)
        if progress:
            pct = 45 + int(50 * done_squares / total_squares)
            progress(pct, f"Sorting level {z} ({len(rows):,} tiles)…")
        rows.sort()
        for _diag, dx, dy, tile_names in rows:
            done_squares += 1
            if progress and (done_squares & 0x7FFF) == 0:
                pct = 45 + int(50 * done_squares / total_squares)
                progress(pct, f"Drawing level {z} ({done_squares:,}/{total_squares:,} tiles)…")
            px = (dx - dy) * half + H * half
            py = (dx + dy) * quarter + lift - z * level_px - TW * 3 // 2
            for name in tile_names:
                sp = sprite_for(name)
                if sp is None:
                    continue
                ox, oy, sw, sh, pre_rgb, inv_a, opaque, rgba_u8 = sp
                x0, y0 = px + ox, py + oy
                x1, y1 = x0 + sw, y0 + sh
                if x1 <= 0 or y1 <= 0 or x0 >= width or y0 >= height:
                    continue
                sx0 = max(0, -x0)
                sy0 = max(0, -y0)
                sx1 = sw - max(0, x1 - width)
                sy1 = sh - max(0, y1 - height)
                cx0, cy0 = x0 + sx0, y0 + sy0
                cx1, cy1 = x0 + sx1, y0 + sy1
                dst = canvas[cy0:cy1, cx0:cx1]
                if opaque:
                    if sx0 == 0 and sy0 == 0 and sx1 == sw and sy1 == sh:
                        dst[:] = rgba_u8[:, :, :3]
                    else:
                        dst[:] = rgba_u8[sy0:sy1, sx0:sx1, :3]
                else:
                    if sx0 == 0 and sy0 == 0 and sx1 == sw and sy1 == sh:
                        t = pre_rgb + dst * inv_a
                    else:
                        t = pre_rgb[sy0:sy1, sx0:sx1] + dst * inv_a[sy0:sy1, sx0:sx1]
                    dst[:] = (t + (t >> 8) + 1) >> 8
        del rows
    return Image.fromarray(canvas, "RGB").convert("RGBA")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) < 6:
        print(__doc__)
        return 2
    opts = {a.split("=")[0]: a.split("=", 1)[1] for a in argv[1:] if a.startswith("--") and "=" in a}
    for i, a in enumerate(argv):
        if a in ("--max-level", "--scale") and i + 1 < len(argv):
            opts[a] = argv[i + 1]
    map_dir, out_png = args[0], args[1]
    X, Y, W, H = (int(v) for v in args[2:6])
    picture = render(map_dir, X, Y, W, H,
                     max_level=int(opts["--max-level"]) if "--max-level" in opts else None,
                     scale=float(opts.get("--scale", 1)),
                     world="--world" in argv)
    if picture is None:
        print("nothing compiled in that area")
        return 1
    result = picture.convert("RGB")
    result.save(out_png)
    print(f"wrote {out_png} {result.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
