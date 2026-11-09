"""A WorldEd that cannot start is a 400, not a 500.

On Linux and macOS the Windows build goes through Wine (knoxpaths.command_for).
When Wine is not installed, subprocess.Popen raises FileNotFoundError inside the
request thread and the page got "500 Internal Server Error" with nothing to read
- which reads as KnoxMap falling over rather than "install Wine, or set
PZWORLDED to a native build".
"""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as A
from web import generation


class WorldedLaunch(unittest.TestCase):
    def setUp(self):
        self.client = A.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.map_dir = Path(self.tmp.name) / "Tavacare"
        self.map_dir.mkdir()
        (self.map_dir / "Tavacare.pzw").write_text("<project/>", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_worlded_that_cannot_start_is_a_refusal(self):
        with mock.patch.object(generation, "_map_dir", return_value=self.map_dir), \
                mock.patch.object(generation, "_worlded_exe",
                                  return_value=Path("C:/nowhere/PZWorldEd.exe")), \
                mock.patch.object(subprocess, "Popen",
                                  side_effect=FileNotFoundError(2, "No such file", "wine")):
            out = self.client.post("/api/worlded", json={"mapName": "Tavacare"})
        self.assertEqual(out.status_code, 400, out.get_data(as_text=True))
        self.assertIn("Could not start PZWorldEd", out.get_json()["error"])

    def test_a_map_with_no_project_is_still_a_refusal(self):
        with mock.patch.object(generation, "_map_dir", return_value=self.map_dir), \
                mock.patch.object(generation, "_worlded_exe",
                                  return_value=Path("C:/nowhere/PZWorldEd.exe")):
            (self.map_dir / "Tavacare.pzw").unlink()
            out = self.client.post("/api/worlded", json={"mapName": "Tavacare"})
        self.assertEqual(out.status_code, 400, out.get_data(as_text=True))
        self.assertIn("No .pzw", out.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
