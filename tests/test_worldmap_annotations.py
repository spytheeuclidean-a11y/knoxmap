"""The labels on the paper map, and the one way they reach the game as text.

worldmap-annotations.lua is Lua the game reads itself, and a non-ASCII byte in it
took a whole in-game map down: the workaround a player found was to replace the
Cyrillic character in a place name with a Latin lookalike, and all 44 annotations
of their map appeared (#38). Names are written as Lua decimal escapes now: the
same bytes, and nothing above ASCII in the file.
"""
import json
import os
import re
import tempfile
import unittest

from knoxbuild import world, worldmap
from tools import make_map_mod


def decode(literal: str) -> bytes:
    """The bytes a Lua string literal stands for, escapes and all."""
    assert literal.startswith('"') and literal.endswith('"'), literal
    body, out, i = literal[1:-1], bytearray(), 0
    while i < len(body):
        char = body[i]
        if char != "\\":
            out += char.encode("utf-8")
            i += 1
            continue
        following = body[i + 1]
        digits = re.match(r"\d{1,3}", body[i + 1:])
        if digits:
            out.append(int(digits.group(0)))
            i += 1 + len(digits.group(0))
        else:
            out += {"\\": b"\\", '"': b'"'}.get(following, following.encode("utf-8"))
            i += 2
    return bytes(out)


class TheAnnotationsFile(unittest.TestCase):
    def setUp(self):
        self.was = world.origin()
        world.set_origin((0, 0))

    def tearDown(self):
        world.set_origin(self.was)

    def write(self, labels) -> str:
        with tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "worldmap-annotations.lua")
            worldmap._write_annotations(path, labels, 200, 200)
            with open(path, encoding="utf-8") as f:
                return f.read()

    def literal(self, text: str) -> str:
        found = re.search(r'addUntranslatedText\(("[^"]*")', text)
        self.assertIsNotNone(found, text)
        return found.group(1)

    def test_a_cyrillic_name_keeps_its_bytes_and_leaves_the_file_ascii(self):
        text = self.write([("Херсон", "text-place", 1.0, 10, 10)])
        self.assertTrue(text.isascii(), "the file the game reads is not ASCII")
        self.assertEqual(decode(self.literal(text)).decode("utf-8"), "Херсон")

    def test_an_ascii_name_is_written_exactly_as_it_was(self):
        text = self.write([("Main Street", "text-place", 1.0, 10, 10)])
        self.assertIn('addUntranslatedText("Main Street", "text-place"', text)

    def test_quotes_and_backslashes_still_survive(self):
        name = 'The "Old" \\ Crown'
        literal = worldmap.lua_string(name)
        self.assertTrue(literal.isascii())
        self.assertEqual(decode(literal).decode("utf-8"), name)

    def test_every_non_ascii_name_in_a_map_is_escaped(self):
        # Greek, Chinese and an emoji, as a town's landmarks could be.
        for name in ("Πλατεία", "中央公园", "Café ☕"):
            with self.subTest(name=name):
                literal = worldmap.lua_string(name)
                self.assertTrue(literal.isascii(), literal)
                self.assertEqual(decode(literal).decode("utf-8"), name)


class TheSpawnSelectorFile(unittest.TestCase):
    """The same names go into Spawn Selector's file, read back out of the
    annotations file - so escaping one and not decoding the other would show the
    player the escapes themselves instead of the name."""

    def test_a_cyrillic_place_survives_the_round_trip(self):
        with tempfile.TemporaryDirectory() as t:
            project = os.path.join(t, "town")
            os.makedirs(project)
            with open(os.path.join(project, "town_info.json"), "w", encoding="utf-8") as f:
                json.dump({"width_tiles": 100, "height_tiles": 100}, f)
            with open(os.path.join(project, "worldmap-annotations.lua"), "w",
                      encoding="utf-8") as f:
                f.write('return function(mapUI)\n'
                        f'\tsymbol = symbolsAPI:addUntranslatedText({worldmap.lua_string("Херсон")},'
                        ' "text-town", 10, 10)\n'
                        f'\tsymbol = symbolsAPI:addUntranslatedText({worldmap.lua_string("Площа")},'
                        ' "text-place", 20, 20)\nend\n')
            mod = os.path.join(t, "mod")
            added = make_map_mod.write_spawn_selector(project, mod, "town", "Town")
            self.assertEqual(added, 1)
            folder = os.path.join(mod, "common", "media", "lua", "shared", "KnoxMap")
            written = os.path.join(folder, os.listdir(folder)[0])
            with open(written, encoding="utf-8") as f:
                text = f.read()
            self.assertTrue(text.isascii(), text)
            self.assertIn(worldmap.lua_string("Херсон"), text)
            self.assertIn(worldmap.lua_string("Площа"), text)
            self.assertNotIn("\\\\208", text, "the escape was escaped again")


if __name__ == "__main__":
    unittest.main()
