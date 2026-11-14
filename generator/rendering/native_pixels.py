"""Native pixel-pass workers via the knoxroute binary."""
from __future__ import annotations

import logging
import struct
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from PIL import Image

from ..roadgraph.rustsearch import exe

MAX_STRIP_PIXELS = 1_048_576
MIN_CLEAR_PIXELS = 65_536
MIN_BOX_PIXELS = 65_536
TIMEOUT_S = 30


def _exchange(proc, data: bytes, expected: int, magic: bytes) -> bytes:
    view = memoryview(data)
    while view:
        sent = proc.stdin.write(view)
        if not sent:
            raise RuntimeError("native pixel worker input closed")
        view = view[sent:]
    proc.stdin.flush()
    reply = proc.stdout.read(expected)
    if len(reply) != expected or reply[:4] != magic:
        raise RuntimeError("invalid native pixel worker reply")
    return reply[4:]


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
    strips = (height + rows - 1) // rows
    header = (
        b"KRV1"
        + struct.pack("<II", strips, len(road_colours))
        + road_bytes
        + struct.pack("<I", len(veg_colours))
        + veg_bytes
        + nothing_bytes
    )

    try:
        with subprocess.Popen(
            [binary, "--clear-road-veg"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ) as proc:
            with ThreadPoolExecutor(max_workers=1) as pool:
                try:
                    for top in range(0, height, rows):
                        box = (0, top, width, min(top + rows, height))
                        size = (width, box[3] - top)
                        n = size[0] * size[1]
                        payload = (header if top == 0 else b"") + struct.pack("<II", *size)
                        payload += veg.crop(box).tobytes() + landscape.crop(box).tobytes()
                        future = pool.submit(_exchange, proc, payload, 4 + 3 * n, b"KRV1")
                        deadline = time.monotonic() + TIMEOUT_S
                        while True:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise TimeoutError("native clear-road-veg worker timed out")
                            try:
                                result = future.result(timeout=min(0.1, remaining))
                                break
                            except FutureTimeout:
                                continue
                        veg.paste(Image.frombytes("RGB", size, result), box)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()
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
