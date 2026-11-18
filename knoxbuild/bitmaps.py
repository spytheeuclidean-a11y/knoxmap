"""Read the map's bitmaps without holding three copies of them.

``np.array(Image.open(p).convert("RGB"))`` decodes the file into a PIL image,
converts it into a second one and copies that into an array: about three times
the bitmap at once. A 285 Mpx map is 855 MB as an array, so that was 2.5 GB
before the building step had done anything.

The renderer writes plain 24-bit (landscape, vegetation) and 8-bit (road
hierarchy) BMPs. For those the pixels are read straight off the disk a strip of
rows at a time into one preallocated array, so the peak is the array and a
strip. Any other BMP, or a file this cannot make sense of, goes through Pillow
as before.
"""
from __future__ import annotations

import os
import struct

import numpy as np
from PIL import Image

STRIP_ROWS = 256


def _bmp_header(path: str):
    """(width, height, bottom_up, bits, data_offset) of a plain BMP, else None."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(54)
    except OSError:
        return None
    if len(head) < 54 or head[:2] != b"BM":
        return None
    offset, = struct.unpack_from("<I", head, 10)
    size, width, height, planes, bits, compression = struct.unpack_from(
        "<IiiHHI", head, 14)
    if size < 40 or compression != 0 or planes != 1 or width <= 0 or height == 0:
        return None
    return width, abs(height), height > 0, bits, offset


def _fast(path: str, bits_wanted: int, crop, step: int = 1):
    hdr = _bmp_header(path)
    if hdr is None or hdr[3] != bits_wanted:
        return None
    width, height, bottom_up, bits, offset = hdr
    bpp = bits // 8
    stride = (width * bpp + 3) // 4 * 4
    if os.path.getsize(path) < offset + stride * height:
        return None
    out_h, out_w = height, width
    if crop is not None:
        out_h, out_w = min(crop[0], height), min(crop[1], width)
    if step > 1:
        # Every step-th pixel in each direction: a picture to look at, not to
        # measure, so the full bitmap is never held.
        rows = range(0, out_h, step)
        cols = slice(0, out_w, step)
        shape = (len(rows), len(range(0, out_w, step))) + ((3,) if bpp == 3 else ())
        out = np.empty(shape, dtype=np.uint8)
        row_bytes = out_w * bpp
        with open(path, "rb") as fh:
            for n, y in enumerate(rows):
                src_y = height - 1 - y if bottom_up else y
                fh.seek(offset + src_y * stride)
                line = np.frombuffer(fh.read(row_bytes), dtype=np.uint8)
                if bpp == 3:
                    out[n] = line.reshape(out_w, 3)[cols][:, ::-1]
                else:
                    out[n] = line[cols]
        return out
    shape = (out_h, out_w, 3) if bpp == 3 else (out_h, out_w)
    out = np.empty(shape, dtype=np.uint8)
    # Read strips via buffered file I/O instead of memmapping the whole file,
    # avoiding Windows WinError 1450 commit-space exhaustion on multi-GB BMPs.
    with open(path, "rb") as fh:
        for top in range(0, out_h, STRIP_ROWS):
            bottom = min(top + STRIP_ROWS, out_h)
            count = bottom - top
            src_top = (height - bottom) if bottom_up else top
            fh.seek(offset + src_top * stride)
            buf = fh.read(count * stride)
            src = np.frombuffer(buf, dtype=np.uint8).reshape(count, stride)
            if bottom_up:
                src = src[::-1]
            if bpp == 3:
                px = src[:, :out_w * 3].reshape(count, out_w, 3)
                out[top:bottom] = px[:, :, ::-1]          # BGR -> RGB
            else:
                out[top:bottom] = src[:, :out_w]
    return out


_RGB_CACHE: dict[tuple[str, int, int], np.ndarray] = {}
_RGB_CACHE_MAX_BYTES = 128 * 1024 * 1024


def read_rgb(path: str, crop: tuple[int, int] | None = None,
             step: int = 1) -> np.ndarray:
    """The picture as a (height, width, 3) uint8 array. `crop` is (rows, cols);
    `step` keeps every step-th pixel, for a smaller picture of a big map."""
    try:
        st = os.stat(path)
        key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = None

    if key is not None and key in _RGB_CACHE:
        cached = _RGB_CACHE[key]
        out = cached[:crop[0], :crop[1]] if crop else cached
        out = out[::step, ::step] if step > 1 else out
        return out.copy()

    arr = _fast(path, 24, crop, step)
    if arr is None:
        with Image.open(path) as img:
            arr = np.array(img.convert("RGB"))
        arr = arr[:crop[0], :crop[1]] if crop else arr
        arr = arr[::step, ::step] if step > 1 else arr

    if key is not None and crop is None and step == 1 and arr.nbytes <= _RGB_CACHE_MAX_BYTES:
        if len(_RGB_CACHE) >= 2:
            _RGB_CACHE.pop(next(iter(_RGB_CACHE)))
        cached_copy = arr.copy()
        cached_copy.setflags(write=False)
        _RGB_CACHE[key] = cached_copy
    return arr


def read_gray(path: str, crop: tuple[int, int] | None = None) -> np.ndarray:
    """The picture as a (height, width) uint8 array of grey levels."""
    arr = _fast(path, 8, crop)
    if arr is not None:
        # An 8-bit BMP is palette indices; the renderer writes a grey ramp, so
        # they are the grey levels. Check, rather than trust it.
        with Image.open(path) as img:
            pal = img.getpalette()
        if pal is None or all(pal[i * 3] == i for i in range(256)
                              if i * 3 < len(pal)):
            return arr
    with Image.open(path) as img:
        arr = np.array(img.convert("L"))
    return arr[:crop[0], :crop[1]] if crop else arr


def same_colour(rgb: np.ndarray, colour) -> np.ndarray:
    """Boolean mask of the pixels equal to `colour`, without the (h, w, 3)
    boolean that ``np.all(rgb == colour, axis=2)`` builds."""
    r, g, b = colour[:3]
    mask = rgb[:, :, 0] == r
    mask &= rgb[:, :, 1] == g
    mask &= rgb[:, :, 2] == b
    return mask


def cell_hashes(path: str, cell: int) -> dict[tuple[int, int], str]:
    """A fingerprint of each cell x cell square of a picture, keyed (column, row).

    For telling which squares of a big bitmap changed between two builds without
    keeping the old bitmap: only the picture's bytes are read, a band of rows at
    a time. Two pictures give the same fingerprint for a square exactly when
    its pixels are the same. A square at the edge is just smaller.
    """
    import hashlib

    out: dict[tuple[int, int], str] = {}
    hdr = _bmp_header(path)
    if hdr is not None and hdr[3] in (8, 24):
        width, height, bottom_up, bits, offset = hdr
        bpp = bits // 8
        stride = (width * bpp + 3) // 4 * 4
        if os.path.getsize(path) >= offset + stride * height:
            raw = np.memmap(path, dtype=np.uint8, mode="r", offset=offset,
                            shape=(height, stride))
            try:
                for cy, y0 in enumerate(range(0, height, cell)):
                    y1 = min(y0 + cell, height)
                    band = raw[height - y1:height - y0] if bottom_up else raw[y0:y1]
                    for cx, x0 in enumerate(range(0, width, cell)):
                        part = band[:, x0 * bpp:min(x0 + cell, width) * bpp]
                        out[(cx, cy)] = hashlib.blake2b(
                            np.ascontiguousarray(part).tobytes(), digest_size=12).hexdigest()
            finally:
                del raw
            return out
    with Image.open(path) as img:
        arr = np.array(img.convert("RGB"))
    for cy, y0 in enumerate(range(0, arr.shape[0], cell)):
        for cx, x0 in enumerate(range(0, arr.shape[1], cell)):
            out[(cx, cy)] = hashlib.blake2b(
                np.ascontiguousarray(arr[y0:y0 + cell, x0:x0 + cell]).tobytes(),
                digest_size=12).hexdigest()
    return out


def read_rgb_rows(path: str, top: int, bottom: int, width: int | None = None) -> np.ndarray:
    """Rows top..bottom (exclusive) of the picture, as a (rows, width, 3) array.

    For working down a big bitmap a strip at a time: only that strip is read,
    where opening the picture and converting it holds all of it, twice."""
    hdr = _bmp_header(path)
    if hdr is not None and hdr[3] == 24:
        w, height, bottom_up, _bits, offset = hdr
        bottom = min(bottom, height)
        top = max(0, min(top, bottom))
        cols = min(width, w) if width else w
        stride = (w * 3 + 3) // 4 * 4
        if os.path.getsize(path) >= offset + stride * height:
            raw = np.memmap(path, dtype=np.uint8, mode="r", offset=offset,
                            shape=(height, stride))
            try:
                band = raw[height - bottom:height - top][::-1] if bottom_up else raw[top:bottom]
                return np.ascontiguousarray(
                    band[:, :cols * 3].reshape(bottom - top, cols, 3)[:, :, ::-1])
            finally:
                del raw
    with Image.open(path) as img:
        w, h = img.size
        cols = min(width, w) if width else w
        return np.array(img.convert("RGB").crop((0, top, cols, min(bottom, h))))


def read_window(path: str, x0: int, y0: int, win_w: int, win_h: int,
                *, bits: int = 24) -> np.ndarray:
    """Read ``[y0:y0+win_h, x0:x0+win_w]`` from a BMP using buffered strip I/O."""
    hdr = _bmp_header(path)
    if hdr is not None and hdr[3] == bits:
        w, height, bottom_up, _bits, offset = hdr
        bpp = bits // 8
        stride = (w * bpp + 3) // 4 * 4
        x1 = min(w, x0 + win_w)
        y1 = min(height, y0 + win_h)
        cw = max(0, x1 - x0)
        ch = max(0, y1 - y0)
        shape = (ch, cw, 3) if bpp == 3 else (ch, cw)
        out = np.empty(shape, dtype=np.uint8)
        if cw == 0 or ch == 0:
            return out
        if os.path.getsize(path) >= offset + stride * height:
            with open(path, "rb") as fh:
                for top in range(y0, y1, STRIP_ROWS):
                    bottom = min(top + STRIP_ROWS, y1)
                    count = bottom - top
                    src_top = (height - bottom) if bottom_up else top
                    fh.seek(offset + src_top * stride)
                    buf = fh.read(count * stride)
                    src = np.frombuffer(buf, dtype=np.uint8).reshape(count, stride)
                    if bottom_up:
                        src = src[::-1]
                    if bpp == 3:
                        px = src[:, x0 * 3:x1 * 3].reshape(count, cw, 3)
                        out[top - y0:bottom - y0] = px[:, :, ::-1]
                    else:
                        out[top - y0:bottom - y0] = src[:, x0:x1]
            return out
    with Image.open(path) as img:
        mode = "RGB" if bits == 24 else "L"
        return np.array(img.convert(mode).crop((x0, y0, x0 + win_w, y0 + win_h)))


def write_window(path: str, x0: int, y0: int, arr: np.ndarray) -> None:
    """Write ``arr`` into an existing uncompressed BMP at ``(x0, y0)`` in strips."""
    hdr = _bmp_header(path)
    win_h, win_w = arr.shape[:2]
    if hdr is not None and hdr[3] in (8, 24):
        w, height, bottom_up, bits, offset = hdr
        bpp = bits // 8
        stride = (w * bpp + 3) // 4 * 4
        if os.path.getsize(path) >= offset + stride * height:
            row_bytes = win_w * bpp
            with open(path, "r+b") as fh:
                for dy in range(win_h):
                    gy = y0 + dy
                    if not (0 <= gy < height):
                        continue
                    src_y = (height - 1 - gy) if bottom_up else gy
                    fh.seek(offset + src_y * stride + x0 * bpp)
                    if bpp == 3:
                        fh.write(np.ascontiguousarray(arr[dy, :, ::-1]).tobytes())
                    else:
                        fh.write(np.ascontiguousarray(arr[dy]).tobytes())
                    if row_bytes == 0:
                        continue
            return
    with Image.open(path) as img:
        base = img.copy()
    base.paste(Image.fromarray(arr), (x0, y0))
    base.save(path, format="BMP")
