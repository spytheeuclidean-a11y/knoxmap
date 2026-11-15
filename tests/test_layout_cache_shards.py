"""LayoutCache appends to per-process shards instead of rewriting layouts.json."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from knoxbuild import room_solver as R  # noqa: E402


def _entry(n):
    return {"programme": "semi_interwar", "hash": "h", "layouts": [{"n": n}]}


class Shards(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_save_appends_and_leaves_the_base_alone(self):
        c = R.LayoutCache(self.dir)
        c.data["a"] = c._pending["a"] = _entry(1)
        c.save()
        self.assertFalse(os.path.exists(c.path))
        size = os.path.getsize(c._shard)
        c.data["b"] = c._pending["b"] = _entry(2)
        c.save()
        self.assertGreater(os.path.getsize(c._shard), size)
        self.assertEqual(set(R.LayoutCache(self.dir).data), {"a", "b"})

    def test_a_torn_last_line_is_skipped(self):
        c = R.LayoutCache(self.dir)
        c.data["a"] = c._pending["a"] = _entry(1)
        c.save()
        with open(c._shard, "a", encoding="utf-8") as f:
            f.write('["torn", {"lay')
        self.assertEqual(set(R.LayoutCache(self.dir).data), {"a"})

    def test_compact_folds_shards_into_the_base(self):
        c = R.LayoutCache(self.dir)
        c.data["a"] = c._pending["a"] = _entry(1)
        self.assertTrue(c.compact(force=True))
        self.assertEqual(list(json.load(open(c.path, encoding="utf-8"))), ["a"])
        self.assertEqual(c._shard_files(), [])
        self.assertEqual(set(R.LayoutCache(self.dir).data), {"a"})

    def test_pruned_entries_leave_the_base_at_compact(self):
        c = R.LayoutCache(self.dir)
        c.data["a"] = c._pending["a"] = {"programme": "no_such", "hash": "x", "layouts": []}
        c.compact(force=True)
        c = R.LayoutCache(self.dir)
        self.assertEqual(c.prune(), 1)
        c.compact()
        self.assertEqual(R.LayoutCache(self.dir).data, {})


if __name__ == "__main__":
    unittest.main()
