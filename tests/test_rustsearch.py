"""The knoxroute pipe: a partial write must never lose the request's tail."""
import unittest

from generator.roadgraph import rustsearch


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


if __name__ == "__main__":
    unittest.main()
