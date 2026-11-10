"""The knoxroute pipe: a partial write must never lose the request's tail."""
import unittest
from unittest.mock import patch

from generator.roadgraph import rustsearch, snap


class _Stdin:
    def __init__(self, chunk):
        self.chunk = chunk
        self.got = b""
        self.flushed = False

    def write(self, view):
        n = min(self.chunk, len(view))
        self.got += bytes(view[:n])
        return n

    def flush(self):
        self.flushed = True


class _Proc:
    def __init__(self, chunk):
        self.stdin = _Stdin(chunk)


def _router(proc):
    router = object.__new__(rustsearch.Router)
    router.proc = proc
    return router


class Send(unittest.TestCase):
    def test_partial_writes_are_completed(self):
        proc = _Proc(chunk=7)
        blob = bytes(range(256))
        _router(proc)._send(blob)
        self.assertEqual(proc.stdin.got, blob)
        self.assertTrue(proc.stdin.flushed)

    def test_a_closed_pipe_raises(self):
        proc = _Proc(chunk=0)
        with self.assertRaises(RuntimeError):
            _router(proc)._send(b"abc")


class GraphSearch(unittest.TestCase):
    def route(self, taken):
        pts = [(10, 10), (30, 14), (60, 35)]
        return snap._route(pts, pts[0], pts[-1], None, None, 1, 4, taken, 0)

    def test_plain_curves_dispatches_and_only_sends_occupancy_in_window(self):
        with patch.object(snap, "BACKEND", "rust"), patch.object(snap, "_rust_search") as search:
            search.return_value = ([(10, 10), (60, 35)], 10)
            self.assertIsNotNone(self.route({(30, 14): 7, (-100, 14): 8, (200, 14): 9}))
        args = search.call_args.kwargs
        self.assertIsNone(args["turnable"])
        self.assertEqual(args["taken_owner"].tolist(), [7])
        self.assertEqual(args["taken_idx"].tolist(),
                         [(14 - args["y0"]) * args["w"] + 30 - args["x0"]])

    def test_heuristic_retries_prepare_the_window_once(self):
        with patch.object(snap, "_search_fields", wraps=snap._search_fields) as prepare:
            with patch.object(snap, "_search", return_value=None) as search:
                self.assertIsNone(self.route({}))
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(search.call_count, len(snap.LADDER))

    @unittest.skipUnless(rustsearch.available(), "build knoxroute to compare both searches")
    def test_plain_curves_matches_python_with_native_worker(self):
        with patch.object(snap, "BACKEND", "python"):
            expected = self.route({(30, 14): 7, (-100, 14): 8})
        self.assertIsNotNone(expected)
        before = snap.STATES["rust"]
        try:
            with patch.object(snap, "BACKEND", "rust"):
                self.assertEqual(self.route({(30, 14): 7, (-100, 14): 8}), expected)
            self.assertGreater(snap.STATES["rust"], before)
        finally:
            snap.close_router()


if __name__ == "__main__":
    unittest.main()
