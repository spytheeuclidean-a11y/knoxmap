"""The compile must not take more than three quarters of this PC's RAM,"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import compile_map


class Workers(unittest.TestCase):
    def test_the_ceiling_follows_this_pcs_memory(self):
        with mock.patch.object(compile_map, "_memory_gb", return_value=(2.0, 16.0)):
            self.assertEqual(compile_map.worker_ceiling(), 4)   # 16 * 0.75 // 3
        with mock.patch.object(compile_map, "_memory_gb", return_value=(2.0, 64.0)):
            self.assertEqual(compile_map.worker_ceiling(), 16)

    def test_unknown_memory_still_runs_one(self):
        with mock.patch.object(compile_map, "_memory_gb", return_value=(0.0, 0.0)):
            self.assertEqual(compile_map.worker_ceiling(), 1)

    def test_a_configured_count_is_capped_by_memory(self):
        with mock.patch.object(compile_map, "_memory_gb", return_value=(1.0, 8.0)), \
             mock.patch.object(compile_map.knoxpaths, "load_config",
                               return_value={"compile_workers": 6}):
            self.assertEqual(compile_map.default_workers(), 2)   # 8 * 0.75 // 3

    def test_the_default_never_passes_the_ceiling(self):
        with mock.patch.object(compile_map, "_memory_gb", return_value=(1.0, 12.0)):
            self.assertLessEqual(compile_map.default_workers(),
                                 compile_map.worker_ceiling())


class BothCompilersPrepareTheOutput(unittest.TestCase):
    """The folders, the repairs and the leftover lots, from one place.

    Each backend used to do this itself, so pruning the lots a map left behind
    - the fix for install refusing a map as "moved since it was last
    compiled" - landed on the WorldEd path only, and knoxlots went on
    compiling over them.
    """

    class Prepared(Exception):
        """Raised where the compile would have started."""

    def project(self, folder: str) -> Path:
        project = Path(folder) / "town"
        project.mkdir()
        (project / "town.pzw").write_text(
            '<world version="1.0" width="30" height="30">'
            '<worldOrigin origin="70,0"/></world>', encoding="utf-8")
        return project

    def prepared_flags(self, run) -> list:
        seen = []

        def prepare(*args, **kwargs):
            seen.append(kwargs.get("knoxlots"))
            raise self.Prepared

        with mock.patch.object(compile_map, "prepare_output", side_effect=prepare):
            with self.assertRaises(self.Prepared):
                run()
        return seen

    def test_knoxlots_prepares_the_output_too(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            with mock.patch.object(compile_map, "knoxlots_exe",
                                   return_value=Path("knoxlots")), \
                    mock.patch.object(compile_map, "ensure_rail_rules"):
                seen = self.prepared_flags(lambda: compile_map.compile_rust(str(project)))
        self.assertEqual(seen, [True])

    def test_worlded_prepares_the_output(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            exe = Path(folder) / "PZWorldEd_cli.exe"
            exe.write_bytes(b"")
            seen = self.prepared_flags(
                lambda: compile_map.compile_map(str(project), exe=str(exe),
                                                backend="worlded"))
        self.assertEqual(seen, [False])


if __name__ == "__main__":
    unittest.main()
