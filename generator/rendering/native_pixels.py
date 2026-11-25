"""Native pixel-pass workers via the knoxroute binary."""
from __future__ import annotations

import logging
import struct
import subprocess
from contextlib import closing

from PIL import Image

from ..roadgraph.rustsearch import exe
from .worker import TIMEOUT_S, run_strips

MAX_STRIP_PIXELS = 1_048_576
MIN_CLEAR_PIXELS = 65_536
MIN_BOX_PIXELS = 65_536


def clear_road_vegetation(
    veg: Image.Image,
    landscape: Image.Image,
    road_colours,
    veg_colours,
    veg_nothing: tuple[int, int, int],
) -> bool:
    """Clear vegetation on road/water pixels in Rust, or return False for Python fallback."""
    binary = exe()
    width, height = veg.size
    if binary is None or width * height < MIN_CLEAR_PIXELS:
        return False
    if not 0 < width <= MAX_STRIP_PIXELS or not height:
        return False
    if veg.mode != "RGB" or landscape.mode != "RGB":
        return False

    road_bytes = bytes(int(v) for c in road_colours for v in c)
    veg_bytes = bytes(int(v) for c in veg_colours for v in c)
    nothing_bytes = bytes(int(v) for v in veg_nothing)
    rows = min(256, MAX_STRIP_PIXELS // width)
    bands = [(top, min(top + rows, height)) for top in range(0, height, rows)]
    header = (
        b"KRV1"
        + struct.pack("<II", len(bands), len(road_colours))
        + road_bytes
        + struct.pack("<I", len(veg_colours))
        + veg_bytes
        + nothing_bytes
    )

    def strips():
        for i, (top, bottom) in enumerate(bands):
            size = (width, bottom - top)
            n = size[0] * size[1]
            payload = (header if i == 0 else b"") + struct.pack("<II", *size)
            payload += veg.crop((0, top, width, bottom)).tobytes()
            payload += landscape.crop((0, top, width, bottom)).tobytes()
            yield payload, 4 + 3 * n, b"KRV1"

    try:
        with closing(run_strips(binary, "--clear-road-veg", strips(), "clear-road-veg")) as replies:
            for (top, bottom), result in zip(bands, replies):
                veg.paste(Image.frombytes("RGB", (width, bottom - top), result), (0, top, width, bottom))
    except (OSError, RuntimeError, TimeoutError, subprocess.SubprocessError) as exc:
        logging.getLogger(__name__).warning(
            "native clear-road-veg unavailable; using Python: %s", exc
        )
        return False
    return True


def box_any(mask_bytes: bytes, width: int, height: int, radius: int) -> bytes | None:
    """2D binary box dilation via knoxroute --box-any, or None to use Python."""
    binary = exe()
    if binary is None or width * height < MIN_BOX_PIXELS:
        return None
    if width <= 0 or height <= 0 or radius < 0:
        return None
    n = width * height
    if len(mask_bytes) != n:
        return None
    payload = b"KBX1" + struct.pack("<III", width, height, radius) + mask_bytes
    try:
        proc = subprocess.run(
            [binary, "--box-any"],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=TIMEOUT_S,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0 or len(proc.stdout) != 4 + n or proc.stdout[:4] != b"KBX1":
            raise RuntimeError(f"box-any worker failed (rc={proc.returncode})")
        return proc.stdout[4:]
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logging.getLogger(__name__).warning(
            "native box-any unavailable; using Python: %s", exc
        )
        return None


def smooth_road_edges(
    landscape: Image.Image,
    asphalt,
    pave_rgb: tuple[int, int, int],
    medium_grass_rgb: tuple[int, int, int],
    verge_colours,
) -> bool:
    """Smooth 1-tile notches and bumps on road/pavement edges in Rust."""
    binary = exe()
    width, height = landscape.size
    if binary is None or width * height < MIN_CLEAR_PIXELS:
        return False
    if not 0 < width <= 32768 or not height or landscape.mode != "RGB":
        return False

    strip = min(1024, max(1, 33_554_432 // width))
    bands = [(y0, min(height, y0 + strip)) for y0 in range(0, height, strip)]
    asphalt_bytes = bytes(int(v) for c in asphalt for v in c)
    verge_bytes = bytes(int(v) for c in verge_colours for v in c)
    header = (
        b"KRS1"
        + struct.pack("<II", len(bands), len(asphalt))
        + asphalt_bytes
        + bytes(int(v) for v in pave_rgb)
        + bytes(int(v) for v in medium_grass_rgb)
        + struct.pack("<I", len(verge_colours))
        + verge_bytes
    )

    def strips():
        for i, (y0, y1) in enumerate(bands):
            top, bottom = max(0, y0 - 1), min(height, y1 + 1)
            out_h = y1 - y0
            payload = (
                (header if i == 0 else b"")
                + struct.pack("<IIII", width, bottom - top, y0 - top, out_h)
                + landscape.crop((0, top, width, bottom)).tobytes()
            )
            yield payload, 4 + 3 * width * out_h, b"KRS1"

    try:
        with closing(run_strips(binary, "--smooth-roads", strips(), "smooth-roads")) as replies:
            for (y0, y1), result in zip(bands, replies):
                landscape.paste(Image.frombytes("RGB", (width, y1 - y0), result), (0, y0))
    except (OSError, RuntimeError, TimeoutError, subprocess.SubprocessError) as exc:
        logging.getLogger(__name__).warning(
            "native smooth-roads unavailable; using Python: %s", exc
        )
        return False
    return True


def paint_kerbs(
    veg: Image.Image,
    landscape: Image.Image,
    asphalt,
    pave_colour: tuple[int, int, int],
    kerb_colours: tuple[tuple[int, int, int], ...],
) -> bool:
    """Paint straight and corner kerbs onto ``veg`` in Rust, or return False for Python."""
    binary = exe()
    width, height = landscape.size
    if binary is None or width * height < MIN_CLEAR_PIXELS:
        return False
    if not 0 < width <= MAX_STRIP_PIXELS or not height:
        return False
    if veg.size != (width, height) or veg.mode != "RGB" or landscape.mode != "RGB":
        return False
    if len(kerb_colours) != 8:
        return False

    strip = min(1024, max(1, MAX_STRIP_PIXELS // width))
    bands = [(y0, min(height, y0 + strip)) for y0 in range(0, height, strip)]
    asphalt_bytes = bytes(int(v) for c in asphalt for v in c)
    pave_bytes = bytes(int(v) for v in pave_colour)
    kerb_bytes = bytes(int(v) for c in kerb_colours for v in c)
    header = (
        b"KRK1"
        + struct.pack("<II", len(bands), len(asphalt))
        + asphalt_bytes
        + pave_bytes
        + kerb_bytes
    )

    def strips():
        for i, (y0, y1) in enumerate(bands):
            top, bottom = max(0, y0 - 1), min(height, y1 + 1)
            out_h = y1 - y0
            payload = (
                (header if i == 0 else b"")
                + struct.pack("<IIII", width, bottom - top, y0 - top, out_h)
                + landscape.crop((0, top, width, bottom)).tobytes()
                + veg.crop((0, y0, width, y1)).tobytes()
            )
            yield payload, 4 + 3 * width * out_h, b"KRK1"

    try:
        with closing(run_strips(binary, "--paint-kerbs", strips(), "paint-kerbs")) as replies:
            for (y0, y1), result in zip(bands, replies):
                veg.paste(Image.frombytes("RGB", (width, y1 - y0), result), (0, y0))
    except (OSError, RuntimeError, TimeoutError, subprocess.SubprocessError) as exc:
        logging.getLogger(__name__).warning(
            "native paint-kerbs unavailable; using Python: %s", exc
        )
        return False
    return True
