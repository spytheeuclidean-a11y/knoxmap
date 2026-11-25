"""Strips sent to one knoxroute worker process, one reply read back per strip."""
from __future__ import annotations

import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

import knoxstop

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


def run_strips(binary: str, flag: str, strips, what: str, should_stop=None):
    """Yield the reply body for each ``(payload, expected, magic)`` in ``strips``.

    One worker process serves every strip. It is killed when the generator
    ends, raises, or is closed, and a strip that takes longer than TIMEOUT_S
    raises TimeoutError.
    """
    with subprocess.Popen(
        [binary, flag],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as proc:
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                for payload, expected, magic in strips:
                    future = pool.submit(_exchange, proc, payload, expected, magic)
                    deadline = time.monotonic() + TIMEOUT_S
                    while True:
                        knoxstop.check(should_stop, what)
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError(f"native {what} worker timed out")
                        try:
                            result = future.result(timeout=min(0.1, remaining))
                            break
                        except FutureTimeout:
                            continue
                    yield result
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
