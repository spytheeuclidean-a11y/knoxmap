"""What a release ships, and what Setup installs on somebody else's PC.

`.knoxmap_files.json` is the list an update deletes by, and `requirements.txt`
is what Setup installs. Both are easy to leave a version behind, and neither
failure can be seen from here: the manifest shows up as a module that never
arrives, the requirements as a package that installs itself newer than anything
KnoxMap was ever run against.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TheShippedFileList(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / ".knoxmap_files.json").read_text(encoding="utf-8"))
        self.files = self.manifest["files"]

    def test_the_tests_do_not_ship(self):
        # 107 of the files in a download, and the installed app runs none of
        # them. .gitattributes keeps them out of the zip; this keeps them out of
        # the list an update deletes by, which is the other half of the same job.
        self.assertEqual([f for f in self.files if f.startswith("tests/")], [])
        self.assertNotIn("test_pipeline.py", self.files)

    def test_every_shipped_file_is_on_disk(self):
        from tools.check_manifest import ADDED_BY_RELEASE
        # Source checkouts do not carry the binaries built by release jobs.
        missing = [f for f in self.files if f not in ADDED_BY_RELEASE and not (ROOT / f).exists()]
        self.assertEqual(missing, [], "an update cannot put these back")

    def test_the_list_is_a_set(self):
        self.assertEqual(len(self.files), len(set(self.files)))

    def test_the_developer_tooling_does_not_ship(self):
        # pyproject.toml and requirements-dev.txt are for whoever works on
        # KnoxMap: a linter and its settings, which a player has no use for.
        # Keeping them out of the zip is also what keeps check_manifest.py's
        # comparison exact, since git archive would otherwise ship them.
        # The frontend's ESLint and node:test setup is the same arrangement.
        text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        for name in ("pyproject.toml", "requirements-dev.txt",
                     "package.json", "package-lock.json", "eslint.config.js"):
            with self.subTest(name=name):
                self.assertIn(f"{name} export-ignore", text)
                self.assertNotIn(name, self.files)

    def test_the_binaries_come_from_the_release_and_not_the_repository(self):
        # It used to be one of each: KnoxMap.exe ignored, knoxlots.exe committed.
        # Native binaries are built by the launcher/knoxlots workflows and
        # copied into downloads. The repository carries their source; a copy
        # built here still works, but is not committed.
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for name in ("/KnoxMap.exe", "/knoxlots.exe", "/knoxroute.exe"):
            self.assertIn(name, ignored)
        for name in ("KnoxMap.exe", "knoxlots.exe", "knoxroute.exe"):
            self.assertIn(name, self.files, "a download has to carry every native binary")

    def test_it_has_a_version(self):
        # updater.py compares this with the changelog heading; a manifest from a
        # different version is how a half-applied update reads as complete.
        self.assertRegex(str(self.manifest.get("version")), r"^\d+(\.\d+)+$")


class WhatSetupInstalls(unittest.TestCase):
    def requirements(self) -> list[str]:
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        return [line.strip() for line in text.splitlines()
                if line.strip() and not line.strip().startswith("#")]

    def test_every_package_is_pinned(self):
        # A floor like numpy>=1.26 installs whatever is newest the day somebody
        # runs Setup - months after this was tested, on their PC, with no way
        # back. Setup.bat and setup.sh both install this list.
        unpinned = [line for line in self.requirements() if "==" not in line]
        self.assertEqual(unpinned, [], "Setup would install a moving target")

    def test_the_pins_are_versions_and_not_ranges(self):
        for line in self.requirements():
            name, _, version = line.partition("==")
            self.assertRegex(version, r"^\d+(\.\d+)+$", f"{name} is not pinned to a version")

    def test_the_window_is_in_there(self):
        # CI leaves pywebview out (no GUI toolkit on a runner); Setup must not.
        self.assertTrue(any(line.lower().startswith("pywebview") for line in self.requirements()))

    def test_nothing_is_listed_twice(self):
        names = [re.split(r"[=<>!\[]", line, maxsplit=1)[0].lower()
                 for line in self.requirements()]
        self.assertEqual(len(names), len(set(names)))


class TheCatalogGenerator(unittest.TestCase):
    """The committed catalog is not the generator's output any more.

    Its own header says so: GAME_WALL_STYLES and the escalators were added by
    hand and tools/make_catalog.py does not write them. A warning in a
    docstring is not a guard - the generator would have written straight over
    them - so writing the committed file now has to be asked for with --force.
    """

    def test_it_refuses_to_overwrite_the_committed_catalog(self):
        from tools import make_catalog
        code = make_catalog.main(["make_catalog", "no/such/config",
                                  str(ROOT / "knoxbuild" / "catalog.py")])
        self.assertEqual(code, 2)

    def test_it_still_writes_where_it_was_told_to(self):
        # Past the guard it reads the game's config, which is not there - the
        # point is that it got that far instead of refusing the destination.
        from tools import make_catalog
        with self.assertRaises(FileNotFoundError):
            make_catalog.main(["make_catalog", "no/such/config",
                               str(ROOT / "catalog-scratch.py")])


if __name__ == "__main__":
    unittest.main()
