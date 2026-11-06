"""Road and railway searches, run out of the interpreter (``rust/knoxroute``).

Python still works out the ground - the band's costs, the way the real line
runs, the frontage density, the buildings, which corners a road may turn on -
because that is shapely's and numpy's work and it is fast. The *search* is the
part that cost ~50 microseconds a state, so it lives in the Rust binary beside
``rust/knoxlots``: ``search()`` takes what ``snap._search`` takes once the
ground is known, sends it, and gets the corners back.

The binary is found the way ``knoxlots`` is (see ``tools/compile_map.py``): the
``KNOXROUTE`` environment variable, else ``rust/knoxroute/target/release``.
Build it with::

    cargo build --release --manifest-path rust/knoxroute/Cargo.toml

A search that has no worked-out turn field (`turnable`) is the "graph" mode:
this client leaves that to the interpreter's own search rather than guess.

``rail_search`` uses the same binary's ``--rails`` mode with an independent
versioned frame, so older road workers still work and rails can fall back.
"""
from __future__ import annotations

import os
import logging
import struct
import subprocess
import threading
import time

import numpy as np

import knoxstop

from ..rail_tiles import RAIL_END_RADIUS

from . import snap

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VERSION = 1
NO_HEADING = -2 ** 31
_HERE = os.path.dirname(os.path.abspath(__file__))


def exe() -> str | None:
    """The knoxroute binary: KNOXROUTE, else one a release ships beside KnoxMap.exe, else
    the local release build - the same order knoxlots is looked for in
    (tools/compile_map.py)."""
    named = os.environ.get("KNOXROUTE")
    if named:
        return named if os.path.exists(named) else None
    name = "knoxroute.exe" if os.name == "nt" else "knoxroute"
    for path in (os.path.join(BASE_DIR, name),
                 os.path.join(BASE_DIR, "rust", "knoxroute", "target", "release", name)):
        if os.path.exists(path):
            return path
    return None


def available() -> bool:
    return exe() is not None


class Router:
    """One knoxroute process: the handshake once, then a search per link."""

    def __init__(self, binary: str | None = None):
        binary = binary or exe()
        if binary is None:
            raise FileNotFoundError("knoxroute not built: cargo build --release --manifest-path "
                                    "rust/knoxroute/Cargo.toml")
        self.proc = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     bufsize=0)
        self._moves: dict = {}
        self._lock = threading.Lock()       # one search at a time on this pipe
        self._timer: threading.Timer | None = None
        self._hello()

    # --- handshake -------------------------------------------------------------------------
    def _hello(self) -> None:
        parts = [b"KRTE", struct.pack("<i", VERSION)]
        # Per heading, in the order rust/knoxroute/src/main.rs reads them.
        for h in range(snap.N):
            parts.append(struct.pack("<ii", snap.STEP[h][0], snap.STEP[h][1]))
            parts.append(struct.pack("<dd", snap.ANGLE[h], snap.LENGTH[h]))
            parts.append(struct.pack("<i", ("grid", "45", "2:1").index(snap.SLOPE[h])))
            parts.append(struct.pack("<dd", snap.SLOPE_COST[snap.SLOPE[h]],
                                     snap.DIR_PENALTY[snap.SLOPE[h]]))
        # A notch of turn costs beta x this, and beta is the search's own.
        parts.append(struct.pack("<dd", snap.TURN_SHARE, snap.REVERSE))
        parts.append(struct.pack("<i", len(snap.SWING_BOUNDS)))
        parts.append(np.asarray(snap.SWING_BOUNDS, "<f8").tobytes())
        swing = np.asarray(snap.SWING_TABLE, "<u1")
        parts.append(swing.tobytes())
        self._send(b"".join(parts))

    # --- one search ------------------------------------------------------------------------
    def search(self, **kw) -> tuple:
        """One search at a time: the pipe carries a request and its reply whole."""
        with self._lock:
            return self._search(**kw)

    def _search(self, *, x0, y0, w, h, s, g, h_start, h_arrive, reach, run_min, cap, end_run, end_r,
               road_width, beta, lean, limit, weight, way, dens, occ, turnable, run_here,
               taken_idx, taken_owner, me=0, end_short=None, jog_end=None, stops=(), trace=0) -> tuple:
        """(path or None, states). `weight`, `way`, `dens`, `occ`, `turnable` and `run_here`
        are the window's arrays; `taken` comes as the corners and their owners."""
        packing = self._moves.get((run_min, beta))
        if packing is None:
            chunks = []
            for hd in range(snap.N):
                # A curve's radius is the search's own width (run_min in snap._search), not
                # the road's painted width.
                for moves in (snap._sharp_moves(hd, beta),
                              snap._curved_moves(hd, run_min, 1.0, beta),
                              snap._curved_moves(hd, run_min, 2.0, beta)):
                    chunks.append(struct.pack("<i", len(moves)))
                    for steps, nh, nr, sign, cost in moves:
                        chunks.append(struct.pack("<i", len(steps)))
                        for sh, count in steps:
                            chunks.append(struct.pack("<ii", sh, count))
                        chunks.append(struct.pack("<iiid", nh, nr, sign, cost))
            packing = self._moves[(run_min, beta)] = b"".join(chunks)
        flat = (np.asarray(weight) != np.inf).ravel()
        idx = np.nonzero(flat)[0].astype("<i4")
        head = [b"\x00\x00\x00\x00", struct.pack("<iiii", w, h, x0, y0),
                struct.pack("<iiii", s[0], s[1], g[0], g[1]),
                struct.pack("<ii", NO_HEADING if h_start is None else h_start,
                            NO_HEADING if h_arrive is None else h_arrive),
                struct.pack("<iiiii", reach, run_min, cap, end_run, end_r),
                struct.pack("<iii", road_width, int(jog_end if jog_end is not None else snap.JOG_END), me),
                struct.pack("<i", len(stops)),
                b"".join(struct.pack("<ii", int(q[0]), int(q[1])) for q in stops),
                struct.pack("<d", snap.END_SHORT if end_short is None else end_short),
                struct.pack("<dd", lean, beta),
                struct.pack("<q", -1 if limit is None else int(limit)),
                struct.pack("<i", trace),
                packing,
                struct.pack("<ii", dens is not None, occ is not None),
                struct.pack("<i", idx.size)]
        bulk = [idx.tobytes(),
                np.asarray(weight).ravel()[flat].astype("<f8").tobytes(),
                np.asarray(way).ravel()[flat].astype("<f8").tobytes()]
        if dens is not None:
            bulk.append(np.asarray(dens).ravel()[flat].astype("<f8").tobytes())
        if occ is not None:
            bulk.append(np.asarray(occ).ravel()[flat].astype("<f8").tobytes())
        bulk.append(np.asarray(turnable, "<u1").ravel()[flat].tobytes())
        bulk.append(np.asarray(run_here, "<i4").ravel()[flat].tobytes())
        taken_idx = np.asarray(taken_idx, "<i4")
        taken_owner = np.asarray(taken_owner, "<i4")
        bulk.append(struct.pack("<i", taken_idx.size))
        bulk.append(taken_idx.tobytes())
        bulk.append(taken_owner.tobytes())
        self._arm()
        try:
            self._send(b"".join(head) + b"".join(bulk))
            return self._read()
        finally:
            self._disarm()

    # --- the pipe --------------------------------------------------------------------------
    # A wedged search used to hang the generate thread with both processes idle.
    # After this long with no reply the router is killed; _exact sees EOF and
    # snap falls back to the interpreter's search.
    SEARCH_TIMEOUT_S = float(os.environ.get("KNOXROUTE_TIMEOUT") or 600)

    def _arm(self) -> None:
        self._disarm()
        self._timer = threading.Timer(self.SEARCH_TIMEOUT_S, self.proc.kill)
        self._timer.daemon = True
        self._timer.start()

    def _disarm(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _send(self, blob: bytes) -> None:
        # RawIOBase.write may write only part of the blob; the router waits for
        # the whole request before it answers, so a lost tail deadlocks both
        # ends (it happened on a large request at link 390 of 1771).
        view = memoryview(blob)
        while view:
            sent = self.proc.stdin.write(view)
            if not sent:
                raise RuntimeError("knoxroute stopped (its input closed)")
            view = view[sent:]
        self.proc.stdin.flush()

    def _read(self) -> tuple:
        ok, states, n = struct.unpack("<iqi", self._exact(16))
        if ok == 2:                        # a trace, for the equivalence harness
            raw = self._exact(36 * n) if n else b""
            return [struct.unpack_from("<ddiiiii", raw, 36 * k) for k in range(n)], states
        pts = []
        if n:
            raw = self._exact(8 * n)
            vals = struct.unpack(f"<{2 * n}i", raw)
            pts = list(zip(vals[0::2], vals[1::2]))
        return (pts if ok else None), states

    def _exact(self, n: int) -> bytes:
        chunks = []
        got = 0
        while got < n:
            piece = self.proc.stdout.read(n - got)
            if not piece:
                raise RuntimeError("knoxroute stopped (its output closed)")
            chunks.append(piece)
            got += len(piece)
        return b"".join(chunks)

    def close(self) -> None:
        for pipe in (self.proc.stdin, self.proc.stdout):
            try:
                pipe.close()
            except OSError:
                pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def rail_search(guide, x0, y0, start, target, last_dir, assemblies, should_stop=None):
    """Connected rail sections, or None when the native worker is unavailable.

    KRL2: origin/dimensions, start state, target, endpoint radius, last heading,
    assembly ports, then Pillow's L raster. Reply: KRL2, signed count (-1: no route), then
    (tile_x, tile_y, assembly_index) triples. Start/target/ports use half tiles;
    raster origin and result origins use whole tiles.
    The existing no-argument road protocol is unchanged.
    """
    binary = exe()
    if binary is None:
        return None
    knoxstop.check(should_stop, "the railways")
    header = b"KRL2" + struct.pack("<8i3d3i", x0, y0, *guide.size, *start,
                                    *target, RAIL_END_RADIUS, *last_dir, len(assemblies))
    ports = b"".join(struct.pack("<8i", *a, *b, *incoming, *outgoing)
                     for a, b, incoming, outgoing, _pieces in assemblies)
    deadline = time.monotonic() + Router.SEARCH_TIMEOUT_S
    try:
        with subprocess.Popen([binary, "--rails"], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as proc:
            pending = header + ports + guide.tobytes()
            try:
                while True:
                    knoxstop.check(should_stop, "the railways")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("native railway search timed out")
                    try:
                        reply, error = proc.communicate(pending, timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        pending = None   # communicate retains partially written input
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
            if proc.returncode:
                raise RuntimeError(error.decode("utf-8", errors="replace").strip() or "worker failed")
        if len(reply) < 8 or reply[:4] != b"KRL2":
            raise RuntimeError("invalid railway worker reply")
        count, = struct.unpack_from("<i", reply, 4)
        if count < -1 or count == 0 or len(reply) != 8 + 12 * max(count, 0):
            raise RuntimeError("invalid railway worker result length")
        sections = list(struct.iter_unpack("<iii", reply[8:]))
        if any(not 0 <= row[2] < len(assemblies) for row in sections):
            raise RuntimeError("invalid railway worker assembly")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logging.getLogger(__name__).warning("native rail fitter unavailable; using Python: %s", exc)
        return None
    if count == -1:
        raise ValueError("Railway cannot fit connected vanilla track within its mapped corridor")
    return sections
