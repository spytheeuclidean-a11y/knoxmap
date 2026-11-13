"""Compiling on a machine with no map tools says so.

From a report (1.8.5.8, "Tools: not installed"): the compile died twice with

    unsupported operand type(s) for /: 'NoneType' and 'str'

which is nothing anybody can act on. knoxpaths.mapping_tools_dir() returns
None when the tools are not installed, and the Rust backend handed that
straight to ensure_rail_rules, which divided it by "config". The WorldEd
backend had always guarded the same call.

The compile does need the tools - it reads Rules.txt and Blends.txt out of
them - and it already has words for their absence. This is about reaching
those words instead of a TypeError.
"""
import unittest
from unittest import mock

import knoxpaths
from tools import terrain_source
from tools.compile_map import ensure_rail_rules


class NoMapTools(unittest.TestCase):
    def test_the_rail_rules_step_does_not_divide_none_by_a_string(self):
        self.assertFalse(ensure_rail_rules(None))

    def test_and_the_compile_says_what_is_actually_wrong(self):
        with mock.patch.object(knoxpaths, "mapping_tools_dir", return_value=None):
            terrain_source._LOADED.clear()
            with self.assertRaises(FileNotFoundError) as caught:
                terrain_source.rules_path()
        self.assertIn("not installed", str(caught.exception))

    def test_both_backends_guard_it(self):
        # The WorldEd path already checked; only the Rust one did not, which
        # is why this only happened to people compiling with knoxlots.
        import inspect

        from tools import compile_map

        source = inspect.getsource(compile_map)
        self.assertIn("if tools_dir is None:", source)


if __name__ == "__main__":
    unittest.main()
