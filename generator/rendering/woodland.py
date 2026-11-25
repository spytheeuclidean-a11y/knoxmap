"""Bounded woodland pixel batches through the existing native terrain worker."""
import logging
import struct
import subprocess
from contextlib import closing

from PIL import Image

from .. import pz_colors as C
from ..roadgraph.rustsearch import exe
from .worker import run_strips

MAX_PIXELS = 1_048_576
MIN_PIXELS = 1_048_576


def paint(veg, landscape, mask, eroded, scrub, edge, inside, should_stop=None):
    """Apply strips, or return False so the idempotent Python loop can finish."""
    binary = exe()
    width, height = veg.size
    if binary is None or not 0 < width <= MAX_PIXELS or not height:
        return False
    if veg.mode != 'RGB' or landscape.mode != 'RGB':
        return False
    colours = (C.WATER, C.MEDIUM_GRASS, C.LIGHT_GRASS, C.DARK_GRASS,
               C.BUSHES_TREES_DARK_GRASS, edge, inside, C.VEG_NOTHING)
    palette = bytes(v for colour in colours for v in colour)
    rows = min(256, MAX_PIXELS // width)
    bands = [(top, min(top + rows, height)) for top in range(0, height, rows)]

    def strips():
        for i, (top, bottom) in enumerate(bands):
            box = (0, top, width, bottom)
            size = (width, bottom - top)
            n = size[0] * size[1]
            data = (b'KWD1' + struct.pack('<I', len(bands))) if i == 0 else b''
            data += struct.pack('<II', *size) + palette
            data += b''.join(im.crop(box).tobytes() for im in (veg, landscape, mask, eroded, scrub))
            yield data, 4 + 6 * n, b'KWD1'

    try:
        with closing(run_strips(binary, '--woodland', strips(), 'woodland', should_stop)) as replies:
            for (top, bottom), result in zip(bands, replies):
                size = (width, bottom - top)
                n = size[0] * size[1]
                box = (0, top, width, bottom)
                veg.paste(Image.frombytes('RGB', size, result[:3 * n]), box)
                landscape.paste(Image.frombytes('RGB', size, result[3 * n:]), box)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logging.getLogger(__name__).warning('native woodland unavailable; using Python: %s', exc)
        return False
    return True

