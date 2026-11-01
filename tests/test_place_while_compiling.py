"""A map cannot be moved while it compiles.

The compile reads the map's place once, at the start. Ticking Standalone during
it moved the map to cell 0,0 under the running compile, which then wrote lots
named for the old place, and the install refused them as "moved since it was
last compiled" (West_Union and Washington Court House, 2026-10-30/31).
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as A
from web import common
from web.jobs import _COMPILE, _PROGRESS_LOCK


class PlaceWhileCompiling(unittest.TestCase):
    def setUp(self):
        A.app.config["TESTING"] = True
        self.client = A.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        out = Path(self.tmp.name)
        (out / "Town").mkdir()
        patcher = mock.patch.object(common, "OUTPUT_DIR", out)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.map_dir = out / "Town"

    def _compiling(self, state):
        with _PROGRESS_LOCK:
            _COMPILE["Town"] = {"state": state}
        self.addCleanup(lambda: _COMPILE.pop("Town", None))

    def test_standalone_and_moves_are_refused_while_compiling(self):
        self._compiling("running")
        for method, body in (("post", {"standalone": True}),
                             ("post", {"cell_x": 90, "cell_y": 3}),
                             ("delete", None)):
            res = getattr(self.client, method)("/api/placement/Town", json=body)
            self.assertEqual(res.status_code, 409, (method, body))
            self.assertIn("compiling", res.get_json()["error"])
        self.assertFalse((self.map_dir / "placement.json").exists())

    def test_allowed_once_the_compile_is_done(self):
        self._compiling("done")
        res = self.client.post("/api/placement/Town", json={"standalone": True})
        self.assertEqual(res.status_code, 200)
        self.assertTrue((self.map_dir / "placement.json").exists())

    def test_looking_is_always_allowed(self):
        self._compiling("running")
        self.assertEqual(self.client.get("/api/placement/Town").status_code, 200)


if __name__ == "__main__":
    unittest.main()
