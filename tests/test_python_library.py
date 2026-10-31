"""KnoxMap says when the Python running it is missing part of its own library.

Reported from a map that stopped with `No module named
'xml.etree.ElementTree'`. That module is part of Python, not a package
KnoxMap installs, so pip cannot put it back and the message means the Python
on that PC has been trimmed or had a file taken out of it - antivirus
software is the usual reason. Said in the middle of a build it tells the
person nothing they can act on, so the setup check looks for it and Setup
itself refuses such a Python before it builds anything on top of it.
"""
import unittest
from unittest.mock import patch

from web import system


class WhatKnoxmapNeedsFromPython(unittest.TestCase):
    def test_the_list_is_what_the_code_really_imports(self):
        # Each of these is imported somewhere in KnoxMap; if one were dropped
        # from the list, a Python without it would pass the check and fail
        # later in a build.
        for name in ("xml.etree.ElementTree", "xml.sax.saxutils", "zlib",
                     "hashlib", "zipfile", "tarfile", "ssl", "ctypes"):
            with self.subTest(name=name):
                self.assertIn(name, system.NEEDED_FROM_PYTHON)

    def test_this_python_has_all_of_it(self):
        self.assertEqual(system._missing_from_python(), [])

    def test_one_that_is_missing_is_named(self):
        def gone(name):
            if name == "xml.etree.ElementTree":
                raise ImportError("no such module")
            return object()

        with patch("importlib.util.find_spec", gone):
            self.assertEqual(system._missing_from_python(),
                             ["xml.etree.ElementTree"])

    def test_the_setup_check_says_what_to_do_about_it(self):
        with patch.object(system, "_missing_from_python",
                          lambda: ["xml.etree.ElementTree"]):
            report = system._setup_report()
        check = next(c for c in report["checks"] if c["id"] == "python_library")
        self.assertFalse(check["ok"])
        # The name of what is gone, that pip is not the answer, and a way out.
        self.assertIn("xml.etree.ElementTree", check["fix"])
        self.assertIn("pip", check["fix"])
        self.assertIn("python.org", check["fix"])

    def test_and_passes_quietly_when_nothing_is_missing(self):
        report = system._setup_report()
        check = next(c for c in report["checks"] if c["id"] == "python_library")
        self.assertTrue(check["ok"])


class SetupRefusesSuchAPython(unittest.TestCase):
    """Both setup scripts check before they build an environment on it."""

    def script(self, name):
        # The names as they are spelled in the repository: Windows finds
        # "setup.bat" whatever the case, and Linux - where this runs in CI -
        # does not.
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent / name).read_text(
            encoding="utf-8", errors="replace")

    def test_windows_setup_checks_and_falls_back_to_a_private_copy(self):
        text = self.script("Setup.bat")
        self.assertIn("import xml.etree.ElementTree", text)
        self.assertIn(":python_damaged", text)
        # It must recover rather than stop: the private copy is fetched again.
        after = text.split(":python_damaged", 1)[1]
        self.assertIn("call :portable_python", after)

    def test_the_other_setup_checks_too_and_names_the_packages(self):
        text = self.script("setup.sh")
        self.assertIn("import xml.etree.ElementTree", text)
        self.assertIn("apt install python3", text)


if __name__ == "__main__":
    unittest.main()
