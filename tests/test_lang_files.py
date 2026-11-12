"""The language files and the template they are keyed by.

A translation is found by its English side: the left of each "=" in
lang/english.txt. Reword a line and every translation of it stops matching -
silently, because the window simply shows English again. Until now nothing
looked: the only language check was one Russian sentence, and the four files
had drifted by 20 dead lines and 48 English lines that were in the window but
not in the template.

These tests hold the two ends together:

  * every key a language file translates exists in english.txt, so a renamed
    line shows up here instead of as a sentence that quietly went back to
    English, and a dead line gets deleted rather than carried forever;
  * every placeholder ({area}, {count} ...) on the English side survives on the
    translated side, because a dropped one is a number the reader never sees.

Coverage is printed, not asserted: a half-finished file is by design, and
whatever is not translated is simply shown in English.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tools import make_lang_template

ROOT = Path(__file__).resolve().parent.parent
LANG = ROOT / "lang"
TEMPLATE = LANG / "english.txt"

PLACEHOLDER = re.compile(r"\{([A-Za-z_]\w*)\}")


def entries(path: Path) -> dict[str, str]:
    """English side -> translated side, as the window reads the file."""
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        english, _, theirs = line.partition("=")
        english, theirs = english.strip(), theirs.strip()
        if english:
            out[english] = theirs
    return out


class TheLanguageTemplate(unittest.TestCase):
    def test_the_template_has_no_duplicate_keys(self):
        # A duplicate is harmless to read and impossible to spot in a file of
        # 900 lines, but it means two entries compete for the same sentence.
        seen, duplicates = set(), []
        for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key = line.partition("=")[0].strip()
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        self.assertEqual(duplicates, [])

    def test_every_template_line_is_pending_or_translated(self):
        # english.txt is the template: "English = English" says nothing is
        # translated yet. A line whose two sides differ would make English
        # itself read as another language.
        for english, theirs in entries(TEMPLATE).items():
            with self.subTest(english=english[:50]):
                self.assertEqual(english, theirs)


class TheTranslationFiles(unittest.TestCase):
    def setUp(self):
        self.english = entries(TEMPLATE)
        self.files = sorted(p for p in LANG.glob("*.txt") if p.name != "english.txt")

    def test_there_is_something_to_check(self):
        self.assertTrue(self.files, "no language files found")

    def test_every_key_is_in_the_template(self):
        # The drift check. A key the template no longer has can never match
        # anything the window says, so it is either a reworded line whose
        # translation should be moved, or a typo.
        for path in self.files:
            stale = sorted(set(entries(path)) - set(self.english))
            with self.subTest(file=path.name):
                self.assertEqual(stale, [],
                                 f"{len(stale)} key(s) in {path.name} are not in "
                                 f"lang/english.txt: {stale[:5]}")

    def test_placeholders_survive_translation(self):
        # "{area} km²" translated without {area} shows a size the map never
        # fills in. Only the English placeholders are required: a translator
        # may repeat one, which is fine, and may not invent one.
        for path in self.files:
            for english, theirs in entries(path).items():
                if not theirs or theirs == english:
                    continue                    # untranslated: not a translation
                missing = set(PLACEHOLDER.findall(english)) - set(PLACEHOLDER.findall(theirs))
                with self.subTest(file=path.name, english=english[:40]):
                    self.assertEqual(missing, set(),
                                     f"{path.name} drops {sorted(missing)} from {english!r}")

    def test_every_file_translates_something(self):
        # An empty file still loads and looks like a language that works.
        for path in self.files:
            done = sum(1 for key, theirs in entries(path).items()
                       if theirs and theirs != key)
            with self.subTest(file=path.name):
                self.assertGreater(done, 0)
                print(f"  {path.name}: {done} of {len(self.english)} lines "
                      f"({100 * done / len(self.english):.0f}%)")


class TheTemplateGenerator(unittest.TestCase):
    """Regenerating must never subtract a line: a key is what a translation is.

    The extractor reads the window by pattern, so it cannot promise to find
    every hand-written line. tools/make_lang_template.py adds rather than
    rewrites for that reason, and these tests hold it to it.
    """

    def test_regenerating_keeps_every_committed_line(self):
        lines, _dropped = make_lang_template.template_lines()
        keys = {line.partition(" = ")[0] for line in lines}
        missing = sorted(set(entries(TEMPLATE)) - keys)
        self.assertEqual(missing, [],
                         f"{len(missing)} committed key(s) would be deleted: {missing[:5]}")

    def test_a_template_literal_with_a_placeholder_is_found(self):
        # `${placeRoad}` in draw.js is a sentence a translator reads; before
        # the extractor allowed braces and backticks it was invisible.
        found = make_lang_template.messages()
        self.assertTrue(any(line.startswith("A road of {placeRoad}") for line in found),
                        found[:5])

    def test_a_curated_placeholder_message_keeps_its_braces(self):
        # The CODE regex used to reject anything with {} - including every
        # EXTRA_MESSAGES line with a live number in it.
        self.assertIn("Map data source set to {source}", make_lang_template.messages())

    def test_the_committed_template_is_up_to_date(self):
        # What CI runs: every whole message the code says is in the file.
        self.assertEqual(make_lang_template.main(["--check"]), 0)

    def test_a_line_the_code_no_longer_says_is_kept_unless_pruned(self):
        previous = ["Only in the old template"]
        kept, dropped = make_lang_template.template_lines(previous)
        self.assertIn("Only in the old template", kept)
        self.assertEqual(dropped, previous)
        pruned, _dropped = make_lang_template.template_lines(previous, prune=True)
        self.assertNotIn("Only in the old template", pruned)


if __name__ == "__main__":
    unittest.main()
