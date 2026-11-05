"""The compile must not take more than three quarters of this PC's RAM."""
import unittest
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


if __name__ == "__main__":
    unittest.main()
