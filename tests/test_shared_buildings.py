"""Buildings passed from one person to another, and the library they ship in.

A hand-built building lived in two or three files beside the app and could not
leave the PC it was made on. It now goes out as one file - the .tbx, the
drawing it was made from and what it stands in for - which anyone can take in,
and which `tools/add_shared_building.py` can put into the library that ships
with KnoxMap (knoxbuild/share.py).

What arrives that way came from a stranger over a chat program, so most of
this is about what `read` refuses.
"""
import json
import os
import tempfile
import unittest

from knoxbuild import designer as D
from knoxbuild import presets as P
from knoxbuild import share as S

# What `measure` needs to see to call something a building: the header, and a
# <floor> per storey plus one for the roof.
TBX = ('<building version="4" width="12" height="10">'
       '<room name="hall"/><room name="kitchen"/>'
       '<floor></floor><floor></floor><floor></floor>'
       '</building>')
DESIGN = {"width": 12, "height": 10, "storeys": 2, "kind": "police",
          "rooms": [{"level": 0, "x": 0, "y": 0, "w": 6, "h": 10, "kind": "hall"},
                    {"level": 0, "x": 6, "y": 0, "w": 6, "h": 10, "kind": "office"}]}


def shared(**changes) -> dict:
    out = S.wrap("Station House", TBX, D.clean(DESIGN), kind="police",
                 author="Zombaxx", notes="Cells at the back.")
    out.update(changes)
    return out


class WhatComesInIsChecked(unittest.TestCase):
    def refused(self, data) -> str:
        entry, problem = S.read(data)
        self.assertIsNone(entry)
        self.assertTrue(problem)
        return problem

    def test_a_building_shared_from_knoxmap_is_taken(self):
        entry, problem = S.read(shared())
        self.assertIsNone(problem)
        self.assertEqual(entry["name"], "Station House")
        self.assertEqual(entry["kind"], "police")
        self.assertEqual(entry["author"], "Zombaxx")
        self.assertEqual((entry["width"], entry["height"], entry["storeys"]),
                         (12, 10, 2))

    def test_and_it_survives_being_written_out_and_read_back(self):
        entry, _ = S.read(json.loads(json.dumps(shared())))
        self.assertEqual(entry["tbx"], TBX)
        self.assertEqual(len(entry["design"]["rooms"]), 2)

    def test_anything_else_is_not_a_building(self):
        for what in (None, [], "a string", 7, {}, {"format": "zip"}):
            with self.subTest(what=what):
                self.refused(what)

    def test_a_file_from_another_version_says_so(self):
        self.assertIn("another version", self.refused(shared(version=99)))

    def test_a_building_with_no_name_is_refused(self):
        self.refused(shared(name=""))
        self.refused(shared(name="///"))

    def test_so_is_one_with_no_building_in_it(self):
        self.refused(shared(tbx=""))
        self.refused(shared(tbx="hello"))
        self.refused(shared(tbx=None))

    def test_and_one_too_big_to_be_a_building(self):
        self.assertIn("past the", self.refused(shared(tbx="x" * (S.MAX_TBX_CHARS + 1))))
        wide = TBX.replace('width="12"', f'width="{S.MAX_SIDE + 1}"')
        self.assertIn("a side", self.refused(shared(tbx=wide)))

    def test_an_xml_bomb_is_not_even_opened(self):
        # A few nested entities expand into gigabytes in the parser, and
        # knoxbuild/buildtiles.py reads these with ElementTree, which expands
        # them. A .tbx never needs a doctype, so one that has it is refused.
        bomb = ('<!DOCTYPE lol [<!ENTITY a "aaaaaaaaaa">'
                '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>' + TBX)
        self.assertIn("document type", self.refused(shared(tbx=bomb)))
        self.refused(shared(tbx=TBX.replace("<building", "<!ENTITY x><building")))

    def test_a_kind_this_version_does_not_have_is_no_kind(self):
        entry, problem = S.read(shared(kind="spaceport"))
        self.assertIsNone(problem)
        self.assertEqual(entry["kind"], P.ANY)

    def test_a_drawing_that_cannot_be_read_does_not_cost_the_building(self):
        entry, problem = S.read(shared(design="not a drawing"))
        self.assertIsNone(problem)
        self.assertIsNone(entry["design"])
        self.assertEqual(entry["tbx"], TBX)

    def test_the_name_of_the_file_cannot_walk_out_of_the_folder(self):
        for name in ("../../etc/passwd", "..\\..\\windows", "a/b", "CON"):
            with self.subTest(name=name):
                out = S.file_name(name)
                self.assertTrue(out.endswith(S.SUFFIX))
                self.assertNotIn("/", out)
                self.assertNotIn("\\", out)
                self.assertNotIn("..", out)


class TakingOneIn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def take(self, data=None):
        entry, problem = S.read(data or shared())
        self.assertIsNone(problem)
        return S.install(self.home, entry)

    def test_it_lands_as_a_building_of_your_own(self):
        about = self.take()
        self.assertEqual(about["name"], "Station House")
        listed = P.library(self.home)
        self.assertEqual([p["name"] for p in listed], ["Station House"])
        self.assertFalse(listed[0]["shared"])
        self.assertEqual(listed[0]["kind"], "police")

    def test_the_tbx_is_kept_exactly_as_it_was_sent(self):
        self.take()
        self.assertEqual(P.read(self.home, "Station House"), TBX)

    def test_and_the_drawing_comes_with_it_so_it_can_be_changed(self):
        self.take()
        self.assertTrue(P.library(self.home)[0]["editable"])
        self.assertTrue(D.load_design(self.home, "Station House"))

    def test_one_sent_without_a_drawing_is_still_a_building(self):
        self.take(shared(design=None))
        self.assertFalse(P.library(self.home)[0]["editable"])
        self.assertEqual(P.read(self.home, "Station House"), TBX)


class TheLibraryThatShipsWithKnoxmap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        entry, _ = S.read(shared())
        S.install(self.home, entry, folder=P.library_folder(self.home))
        P.write_shipped(self.home, {"Station House": {
            "kind": "police", "author": "Zombaxx", "notes": "Cells at the back.",
            "added": "2026-10-29"}})

    def test_a_shipped_building_is_there_to_be_used(self):
        listed = P.library(self.home)
        self.assertEqual([p["name"] for p in listed], ["Station House"])
        self.assertTrue(listed[0]["shared"])
        self.assertEqual(listed[0]["kind"], "police")
        self.assertEqual(listed[0]["author"], "Zombaxx")
        self.assertTrue(os.path.exists(listed[0]["file"]))

    def test_its_tbx_and_its_drawing_are_both_found(self):
        self.assertEqual(P.read(self.home, "Station House"), TBX)
        self.assertTrue(D.load_design(self.home, "Station House"))

    def test_it_is_not_somebody_s_to_throw_away(self):
        self.assertFalse(P.remove(self.home, "Station House"))
        self.assertEqual(len(P.library(self.home)), 1)

    def test_but_their_own_building_of_that_name_is_the_one_used(self):
        P.save(self.home, "Station House", TBX.replace('width="12"', 'width="9"'),
               kind="fire")
        listed = P.library(self.home)
        self.assertEqual(len(listed), 1, "the same building twice")
        self.assertFalse(listed[0]["shared"])
        self.assertEqual(listed[0]["width"], 9)
        self.assertEqual(listed[0]["kind"], "fire")

    def test_a_manifest_that_is_rubbish_leaves_the_buildings_standing(self):
        path = os.path.join(P.library_folder(self.home), P.LIBRARY_MANIFEST)
        for junk in ("", "[1, 2]", "{\"buildings\": 7}", "not json at all"):
            with self.subTest(junk=junk):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(junk)
                listed = P.library(self.home)
                self.assertEqual([p["name"] for p in listed], ["Station House"])
                self.assertEqual(listed[0]["kind"], P.ANY)

    def test_and_the_build_picks_it_up_like_any_other(self):
        # What knoxbuild/build.py asks for a plot the map says is a police
        # station, with "police" switched on.
        listed = P.library(self.home)
        pick = P.choose_for_kind(listed, "police", 20, 16, seed=3)
        self.assertIsNotNone(pick, "a shipped building was not offered")
        self.assertEqual(pick["name"], "Station House")
        self.assertTrue(os.path.exists(pick["file"]))
        # And not for a plot it does not fit on.
        self.assertIsNone(P.choose_for_kind(listed, "police", 8, 8, seed=3))

    def test_sharing_a_shipped_one_keeps_the_credit_on_it(self):
        entry = S.of_preset(self.home, "Station House")
        self.assertEqual(entry["author"], "Zombaxx")
        self.assertEqual(entry["kind"], "police")
        self.assertTrue(entry.get("design"))
        self.assertEqual(entry["tbx"], TBX)

    def test_and_sharing_one_that_is_not_there_says_so(self):
        with self.assertRaises(ValueError):
            S.of_preset(self.home, "No Such Building")


if __name__ == "__main__":
    unittest.main()
