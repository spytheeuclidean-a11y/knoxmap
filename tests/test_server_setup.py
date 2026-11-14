"""Putting a map on a dedicated server without anybody editing an .ini.

The mod has always shipped a SERVER SETUP.txt naming exactly what to add,
and people get it wrong anyway, because the editing is the hard part:

  - one more mod on a line of forty, without dropping a semicolon
  - the map at the *front* of Map= with Muldraugh still at the back
  - a spawn regions file named for the server, not the map - which is why
    players spawn in Muldraugh and nobody knows why

knoxbuild/serverconf.py does those three things. What it must never do is
lose anything the server owner put there, which is most of what is checked
here: a map tool has no business being the reason a server will not start.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import knoxpaths

LIVED_IN = (
    "PublicName=Peru Sim\n"
    "Mods=AutoKeyRing;MNAutoMark;ArmorMakesSense\n"
    "Map=Muldraugh, KY\n"
    "WorkshopItems=2392709985\n"
    "Password=\n"
)


class OnARealServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.zomboid = Path(self.tmp.name)
        (self.zomboid / "Server").mkdir(parents=True)
        patcher = mock.patch.object(knoxpaths, "zomboid_user_dir",
                                    return_value=self.zomboid)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ini = self.zomboid / "Server" / "peru.ini"
        self.ini.write_text(LIVED_IN, encoding="utf-8")
        from knoxbuild import serverconf
        self.conf = serverconf

    def apply(self, **kw):
        return self.conf.apply("peru", "bellavista", "bellavista",
                               title="Bella Vista", **kw)

    def text(self):
        return self.ini.read_text(encoding="utf-8")

    def value(self, key):
        for line in self.text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1]
        return None

    # --- what it adds -----------------------------------------------------
    def test_the_mod_goes_on_the_end_of_the_list(self):
        self.apply()
        self.assertEqual(self.value("Mods"),
                         "AutoKeyRing;MNAutoMark;ArmorMakesSense;bellavista")

    def test_the_map_goes_at_the_front_and_muldraugh_stays_at_the_back(self):
        # The game reads the vanilla lot definitions from Muldraugh, and the
        # map has to be ahead of it.
        self.apply()
        self.assertEqual(self.value("Map"), "bellavista;Muldraugh, KY")

    def test_the_spawn_regions_file_is_named_for_the_server(self):
        self.apply()
        written = self.zomboid / "Server" / "peru_spawnregions.lua"
        self.assertTrue(written.is_file())
        body = written.read_text(encoding="utf-8")
        self.assertIn('name = "Bella Vista"', body)
        self.assertIn("media/maps/bellavista/spawnpoints.lua", body)
        self.assertIn("Muldraugh, KY", body)

    def test_a_standalone_map_is_the_whole_world(self):
        self.apply(standalone=True)
        self.assertEqual(self.value("Map"), "bellavista")
        body = (self.zomboid / "Server" / "peru_spawnregions.lua").read_text(
            encoding="utf-8")
        self.assertNotIn("Muldraugh", body)

    def test_the_tile_mod_comes_with_its_workshop_id(self):
        self.apply(extra_mods=["Erikas_Tiles"], workshop=["3346506593"])
        self.assertIn("Erikas_Tiles", self.value("Mods"))
        self.assertIn("3346506593", self.value("WorkshopItems"))
        self.assertIn("2392709985", self.value("WorkshopItems"))

    # --- what it must never do -------------------------------------------
    def test_nothing_the_owner_put_there_is_lost(self):
        before = self.text()
        self.apply()
        after = self.text()
        for mod in ("AutoKeyRing", "MNAutoMark", "ArmorMakesSense"):
            self.assertIn(mod, after)
        for line in before.splitlines():
            key = line.split("=", 1)[0]
            if key not in ("Mods", "Map"):
                self.assertIn(line, after, f"{key} was changed")

    def test_the_old_ini_is_kept(self):
        report = self.apply()
        self.assertTrue(report["backup"])
        self.assertEqual(Path(report["backup"]).read_text(encoding="utf-8"),
                         LIVED_IN)

    def test_doing_it_twice_changes_nothing_the_second_time(self):
        self.apply()
        once = self.text()
        report = self.apply()
        self.assertEqual(self.text(), once)
        self.assertEqual(report["changed"], [])
        self.assertFalse(report["backup"])

    def test_a_server_that_is_not_there(self):
        with self.assertRaises(FileNotFoundError):
            self.conf.apply("nosuch", "m", "m")

    def test_a_world_that_has_been_played_is_reported_not_deleted(self):
        save = self.zomboid / "Saves" / "Multiplayer" / "peru"
        save.mkdir(parents=True)
        (save / "map_t.bin").write_text("x", encoding="utf-8")
        report = self.apply()
        self.assertTrue(report["save"])
        self.assertTrue((save / "map_t.bin").is_file(),
                        "somebody's world was deleted")

    def test_a_key_the_ini_has_not_got_is_added(self):
        self.ini.write_text("PublicName=Bare\n", encoding="utf-8")
        self.apply()
        self.assertEqual(self.value("Mods"), "bellavista")
        self.assertEqual(self.value("Map"), "bellavista;Muldraugh, KY")


class FindingThem(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.zomboid = Path(self.tmp.name)
        (self.zomboid / "Server").mkdir(parents=True)
        patcher = mock.patch.object(knoxpaths, "zomboid_user_dir",
                                    return_value=self.zomboid)
        patcher.start()
        self.addCleanup(patcher.stop)
        from knoxbuild import serverconf
        self.conf = serverconf

    def test_every_ini_is_a_server(self):
        for name in ("alpha", "beta"):
            (self.zomboid / "Server" / f"{name}.ini").write_text(
                LIVED_IN, encoding="utf-8")
        found = {s["name"]: s for s in self.conf.servers()}
        self.assertEqual(sorted(found), ["alpha", "beta"])
        self.assertEqual(found["alpha"]["map"], "Muldraugh, KY")
        self.assertEqual(len(found["alpha"]["mods"]), 3)

    def test_a_played_world_is_flagged(self):
        (self.zomboid / "Server" / "alpha.ini").write_text(LIVED_IN, encoding="utf-8")
        (self.zomboid / "Saves" / "Multiplayer" / "alpha").mkdir(parents=True)
        self.assertTrue(self.conf.servers()[0]["save"])

    def test_no_server_folder_at_all(self):
        import shutil
        shutil.rmtree(self.zomboid / "Server")
        self.assertEqual(self.conf.servers(), [])


class MergingLists(unittest.TestCase):
    def setUp(self):
        from knoxbuild import serverconf
        self.merge = serverconf.merge_entries

    def test_an_entry_already_there_is_not_added_twice(self):
        self.assertEqual(self.merge("a;b", ["b"]), "a;b")

    def test_an_empty_list_is_just_the_new_entry(self):
        self.assertEqual(self.merge("", ["a"]), "a")

    def test_whitespace_and_stray_semicolons_survive_it(self):
        self.assertEqual(self.merge(" a ; ;b ", ["c"]), "a;b;c")

    def test_first_puts_it_at_the_front(self):
        self.assertEqual(self.merge("Muldraugh, KY", ["mine"], first=True),
                         "mine;Muldraugh, KY")


if __name__ == "__main__":
    unittest.main()
