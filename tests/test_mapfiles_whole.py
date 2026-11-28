"""A map file is written whole, or the one from before is still there.

A generate writes a dozen files into the map folder - the ground, the
buildings, the land use, the fences - and each used to be written straight to
its own name. Stop the generate, close the window or lose the machine halfway
through one and what stayed was half a file, which the next Build read as the
map and died on:

    Expecting ',' delimiter: line 1 column 32790 (char 32789)

What is worth checking is that an interrupted write leaves the file that was
there before, that a half-written one is reported as damaged rather than
silently read as an empty map, and that a file which is simply not there is
still "nothing of that kind here".
"""
import json
import os
import tempfile
import unittest

import knoxfiles
from knoxbuild import fences, structures, zones
from knoxbuild.areas import AreaIndex
from knoxbuild.build import _drawn_features
from knoxbuild.population import official_population


class Unserialisable:
    """Stands in for whatever goes wrong halfway down a long write."""


class WrittenWholeOrNotAtAll(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "thing.json")

    def test_a_write_that_fails_leaves_the_one_from_before(self):
        knoxfiles.write(self.path, {"features": [1, 2, 3]})
        with self.assertRaises(TypeError):
            knoxfiles.write(self.path, {"features": Unserialisable()})
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"features": [1, 2, 3]})
        # And the half of it that was written is taken away again rather
        # than left in the map folder.
        self.assertEqual(os.listdir(self.dir), ["thing.json"])

    def test_and_nothing_at_all_when_there_was_nothing_before(self):
        with self.assertRaises(TypeError):
            knoxfiles.write(self.path, Unserialisable())
        self.assertFalse(os.path.exists(self.path))

    def test_a_file_held_open_for_a_moment_is_still_replaced(self):
        # Windows: antivirus or the window reading settings.json makes the
        # move fail with "Access is denied" until it lets go.
        from unittest import mock
        real, failures = os.replace, [PermissionError(13, "Access is denied")] * 3

        def held(src, dst):
            if failures:
                raise failures.pop()
            real(src, dst)

        with mock.patch.object(knoxfiles.os, "replace", held), \
                mock.patch.object(knoxfiles, "REPLACE_WAIT_S", 0):
            knoxfiles.write(self.path, {"a": 1})
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"a": 1})
        self.assertEqual(os.listdir(self.dir), ["thing.json"])

    def test_a_file_that_stays_locked_still_says_so(self):
        from unittest import mock

        def locked(src, dst):
            raise PermissionError(13, "Access is denied")

        with mock.patch.object(knoxfiles.os, "replace", locked), \
                mock.patch.object(knoxfiles, "REPLACE_WAIT_S", 0):
            with self.assertRaises(PermissionError):
                knoxfiles.write(self.path, {"a": 1})
        self.assertEqual(os.listdir(self.dir), [])

    def test_the_half_written_file_is_not_left_lying_in_its_place(self):
        knoxfiles.write(self.path, {"a": 1})
        self.assertEqual(os.listdir(self.dir), ["thing.json"])

    def test_a_bitmap_is_written_the_same_way(self):
        from PIL import Image

        picture = os.path.join(self.dir, "ground.bmp")
        knoxfiles.save(Image.new("RGB", (4, 4), (1, 2, 3)), picture, format="BMP")
        self.assertEqual(os.listdir(self.dir), ["ground.bmp"])
        with Image.open(picture) as written:
            self.assertEqual(written.size, (4, 4))


class ReadingOneThatWentWrong(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def half(self, name, text='{"type": "FeatureCollection", "features": [{"geo'):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_it_says_which_file_it_is_and_what_to_do(self):
        path = self.half("m_fences.geojson")
        with self.assertRaises(knoxfiles.Damaged) as caught:
            knoxfiles.read(path, "the fences")
        said = str(caught.exception)
        self.assertIn("m_fences.geojson", said)
        self.assertIn("the fences", said)
        self.assertIn("Generate the map again", said)

    def test_a_file_that_is_not_there_is_not_a_file_that_is_damaged(self):
        missing = os.path.join(self.dir, "nothing.json")
        self.assertIsNone(knoxfiles.read(missing, "the fences"))
        self.assertEqual(knoxfiles.read(missing, "the fences", default=[]), [])

    def test_the_build_stops_on_a_half_written_layer_rather_than_ignoring_it(self):
        # Each of these used to be either a raw JSONDecodeError out of the
        # middle of the build, or - worse - swallowed, so the map came out
        # with no fences and nobody was told why.
        self.half("m_fences.geojson")
        with self.assertRaises(knoxfiles.Damaged):
            fences.build_fences(self.dir, "m", None, None, None, self.dir)
        self.half("m_areas.geojson")
        with self.assertRaises(knoxfiles.Damaged):
            AreaIndex.load(self.dir, "m", None)
        self.half("m_structures.json")
        with self.assertRaises(knoxfiles.Damaged):
            structures.build_structures(self.dir, "m", self.dir)
        self.half("m_places.json")
        with self.assertRaises(knoxfiles.Damaged):
            official_population(self.dir, "m")

    def test_the_drawing_a_map_is_made_of_is_never_dropped_in_silence(self):
        # These two were swallowed: a half-written sheet meant a hand-drawn
        # map built as empty ground, and half a zones file meant a town built
        # to the map's own numbers everywhere the mapper had set others -
        # both without a word.
        self.half("m_design.json")
        with self.assertRaises(knoxfiles.Damaged):
            _drawn_features(self.dir, "m")
        os.remove(os.path.join(self.dir, "m_design.json"))
        self.half("m_zones.json")
        with self.assertRaises(knoxfiles.Damaged):
            zones.load(self.dir, "m")

    def test_a_map_folder_with_none_of_them_still_builds(self):
        self.assertEqual(AreaIndex.load(self.dir, "m", None)._items, [])
        self.assertEqual(official_population(self.dir, "m"), [])
        self.assertEqual(structures.build_structures(self.dir, "m", self.dir),
                         ([], {"bridges": 0, "monuments": 0, "tiles": 0}))
        self.assertEqual(zones.load(self.dir, "m"), [])
        self.assertEqual(_drawn_features(self.dir, "m"), [])


if __name__ == "__main__":
    unittest.main()
