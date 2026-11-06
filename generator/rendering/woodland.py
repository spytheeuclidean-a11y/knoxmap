"""Bounded woodland pixel batches through the existing native terrain worker."""
import logging
import struct
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from PIL import Image

import knoxstop
from .. import pz_colors as C
from ..roadgraph.rustsearch import exe

MAX_PIXELS = 1_048_576
MIN_PIXELS = 1_048_576
TIMEOUT_S = 30


def _exchange(proc, data, expected):
    view = memoryview(data)
    while view:
        sent = proc.stdin.write(view)
        if not sent:
            raise RuntimeError('woodland worker input closed')
        view = view[sent:]
    proc.stdin.flush()
    reply = proc.stdout.read(expected)
    if len(reply) != expected or reply[:4] != b'KWD1':
        raise RuntimeError('invalid woodland worker reply')
    return reply[4:]


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
    try:
        with subprocess.Popen([binary, '--woodland'], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as proc:
            with ThreadPoolExecutor(max_workers=1) as pool:
                try:
                    for top in range(0, height, rows):
                        knoxstop.check(should_stop, 'the woodland')
                        box = (0, top, width, min(top+rows, height))
                        size = (width, box[3]-top)
                        n = size[0]*size[1]
                        data = (b'KWD1'+struct.pack('<I', (height+rows-1)//rows)) if top == 0 else b''
                        data += struct.pack('<II', *size) + palette
                        data += b''.join(im.crop(box).tobytes() for im in (veg, landscape, mask, eroded, scrub))
                        future = pool.submit(_exchange, proc, data, 4+6*n)
                        deadline = time.monotonic() + TIMEOUT_S
                        while True:
                            knoxstop.check(should_stop, 'the woodland')
                            if time.monotonic() >= deadline:
                                raise TimeoutError('native woodland worker timed out')
                            try:
                                result = future.result(timeout=.1)
                                break
                            except FutureTimeout:
                                continue
                        veg.paste(Image.frombytes('RGB', size, result[:3*n]), box)
                        landscape.paste(Image.frombytes('RGB', size, result[3*n:]), box)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logging.getLogger(__name__).warning('native woodland unavailable; using Python: %s', exc)
        return False
    return True
