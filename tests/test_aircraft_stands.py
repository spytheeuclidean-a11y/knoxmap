"""Aircraft parked on this map's aprons, for the Wingsmith mods.

Every place those mods know about is on the game's own map, so an airfield
this tool generated had its aprons stand empty however many aircraft mods
were installed. These check the stands written for them are on the concrete,
clear of the buildings, in the shape the mod reads.
"""
import json
import os
import tempfile
import unittest

from knoxbuild import aircraft


def square(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


class WhereAnAircraftStands(unittest.TestCase):
    def test_a_big_apron_gets_stands(self):
        sites = aircraft.apron_spots([square(0, 0, 200, 200)], [], 2.0)
        self.assertTrue(sites)
        self.assertTrue(sites[0]["spots"])
        for x, y in sites[0]["spots"]:
            self.assertTrue(0 < x < 200 and 0 < y < 200)

    def test_a_scrap_of_hardstanding_gets_none(self):
        # A corner of concrete by a flying club's hut is not a stand.
        self.assertEqual(aircraft.apron_spots([square(0, 0, 8, 8)], [], 2.0), [])

    def test_they_keep_clear_of_the_buildings(self):
        full = aircraft.apron_spots([square(0, 0, 200, 200)], [], 2.0)
        blocked = aircraft.apron_spots([square(0, 0, 200, 200)],
                                       [(0, 0, 200, 200)], 2.0)
        self.assertTrue(full)
        self.assertEqual(blocked, [], "stands were put inside a building")

    def test_nothing_lands_outside_an_L_shaped_apron(self):
        ring = [(0, 0), (200, 0), (200, 80), (80, 80), (80, 200), (0, 200), (0, 0)]
        for site in aircraft.apron_spots([ring], [], 2.0):
            for x, y in site["spots"]:
                self.assertFalse(x > 80 and y > 80, f"{x},{y} is off the apron")

    def test_an_airfield_gets_no_more_than_its_share(self):
        # Wingsmith puts one aircraft on each place it is given and marks
        # that place done for every aircraft mod, so the number of aprons
        # offered is the number of aircraft the field ends up with.
        field = square(0, 0, 5000, 500)
        many = [square(i * 500, 0, i * 500 + 200, 200) for i in range(9)]
        sites = aircraft.apron_spots(many, [], 2.0, fields=[field])
        self.assertEqual(len(sites), aircraft.MAX_PER_AIRFIELD)
        self.assertEqual({s["field"] for s in sites}, {0})

    def test_two_airfields_get_that_many_each(self):
        # A map with two airports should not have to share two aircraft.
        west = square(0, 0, 1000, 1000)
        east = square(5000, 0, 6000, 1000)
        aprons = ([square(i * 250, 100, i * 250 + 200, 300) for i in range(3)]
                  + [square(5000 + i * 250, 100, 5000 + i * 250 + 200, 300)
                     for i in range(3)])
        sites = aircraft.apron_spots(aprons, [], 2.0, fields=[west, east])
        self.assertEqual(len(sites), 2 * aircraft.MAX_PER_AIRFIELD)
        self.assertEqual(sorted(s["field"] for s in sites), [0, 0, 1, 1])

    def test_aprons_off_any_mapped_aerodrome_share_one_cap(self):
        # Nothing says which strip they belong to, so they count as one.
        aprons = [square(i * 500, 0, i * 500 + 200, 200) for i in range(5)]
        sites = aircraft.apron_spots(aprons, [], 2.0, fields=[])
        self.assertEqual(len(sites), aircraft.MAX_PER_AIRFIELD)
        self.assertEqual({s["field"] for s in sites}, {-1})

    def test_at_most_two(self):
        self.assertEqual(aircraft.MAX_PER_AIRFIELD, 2)

    def test_the_biggest_aprons_are_the_ones_kept(self):
        small = square(0, 0, 120, 120)
        big = square(1000, 0, 1400, 400)
        sites = aircraft.apron_spots([small, big], [], 2.0)
        self.assertEqual(sites[0]["area_tiles"], 160000)


class TheLuaItWrites(unittest.TestCase):
    def sites(self):
        return aircraft.apron_spots([square(0, 0, 200, 200)], [], 2.0)

    def test_the_spots_are_absolute_world_tiles(self):
        sites = self.sites()
        text = aircraft.lua(sites, (21000, 600), "mytown")
        x, y = sites[0]["spots"][0]
        self.assertIn(f"{{ {x + 21000}, {y + 600} }}", text)

    def test_it_is_in_the_shape_the_mod_reads(self):
        text = aircraft.lua(self.sites(), (0, 0), "mytown")
        for needed in ("id =", "dir =", "spots =", "cond =", "fuel =",
                       "Wingsmith", "Events.OnGameBoot.Add"):
            with self.subTest(needed=needed):
                self.assertIn(needed, text)

    def test_it_does_nothing_without_the_mod(self):
        text = aircraft.lua(self.sites(), (0, 0), "mytown")
        self.assertIn("if not (W and W.aircraft) then return end", text)

    def test_it_does_not_add_the_same_stand_twice(self):
        # Loading a save runs OnGameBoot again; the mod keeps what it read.
        text = aircraft.lua(self.sites(), (0, 0), "mytown")
        self.assertIn("already", text)
        self.assertIn("W.Spawn.list = nil", text)

    def test_nothing_is_written_for_a_map_with_no_apron(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = "notown"
            with open(os.path.join(tmp, f"{name}_areas.geojson"), "w",
                      encoding="utf-8") as fh:
                json.dump({"features": []}, fh)
            with open(os.path.join(tmp, f"{name}_info.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"bbox": {"south": 40.0, "west": -85.0,
                                    "north": 40.01, "east": -84.99},
                           "meters_per_tile": 2.0, "rotation": 0.0}, fh)
            mod = os.path.join(tmp, "mod")
            self.assertEqual(aircraft.write(tmp, mod, "notown", (0, 0)), 0)
            self.assertFalse(os.path.exists(
                os.path.join(mod, "common", "media", "lua")))


class OnAStandaloneMap(unittest.TestCase):
    """Wingsmith turns spawning off for a world that is not Knox County."""

    def lua(self, folder="bowman"):
        sites = aircraft.apron_spots([square(0, 0, 200, 200)], [], 2.0)
        return aircraft.lua(sites, (0, 0), "mytown", folder)

    def test_it_says_which_map_is_its_own(self):
        self.assertIn('string.find(map, "bowman", 1, true)', self.lua())

    def test_it_turns_spawning_back_on_for_that_map(self):
        text = self.lua()
        self.assertIn("W.Spawn.mapOn = true", text)

    def test_it_waits_until_the_world_exists(self):
        # OnGameBoot is before there is a world to ask, so the stands go in
        # there and the switch goes in later.
        text = self.lua()
        self.assertIn("Events.OnGameBoot.Add(addStands)", text)
        self.assertIn("OnGameStart", text)
        self.assertNotIn("Events.OnGameBoot.Add(spawningOn)", text)

    def test_it_leaves_another_map_s_world_alone(self):
        # Set unconditionally it would switch spawning on in somebody else's
        # map, where none of the places Wingsmith knows exist.
        text = self.lua()
        start = text.index("local function spawningOn")
        body = text[start:]
        self.assertIn("if string.find(map, ", body)
        self.assertLess(body.index("string.find(map, "),
                        body.index("W.Spawn.mapOn = true"))

    def test_the_map_name_is_quoted_safely(self):
        # A quote or a backslash in the folder name would otherwise end the
        # Lua string early and the mod would not load at all.
        quote, slash = chr(34), chr(92)
        name = "od" + quote + "d" + slash + "name"
        text = aircraft.lua(
            aircraft.apron_spots([square(0, 0, 200, 200)], [], 2.0),
            (0, 0), "mytown", name)
        want = "od" + slash + quote + "d" + slash + slash + "name"
        self.assertIn(want, text)


class WhereTheMapsSit(unittest.TestCase):
    """Packing a new map in beside the ones already installed."""

    def test_a_cell_is_read_from_the_name_the_game_uses(self):
        # The game's own maps, and this one's, name a cell `<x>_<y>`. The
        # pattern used to want a base name in front of it, which nothing
        # writes, so nothing was ever found and every map was laid on 70,0
        # on top of whatever was there.
        import re

        from knoxbuild import world

        src = io_read(world.__file__)
        pattern = re.search(r're\.fullmatch\(r"([^"]+)", entry\)', src)
        self.assertIsNotNone(pattern)
        self.assertIsNotNone(re.fullmatch(pattern.group(1), "100_9.lotheader"),
                             "a plain <x>_<y>.lotheader is not matched")
        self.assertIsNotNone(re.fullmatch(pattern.group(1),
                                          "bowman_82_0.lotheader"))

    def test_the_workshop_is_looked_in_as_well(self):
        # A map mod from Steam sits outside the Zomboid folder, so looking
        # only there missed every subscribed map.
        from knoxbuild import world

        src = io_read(world.__file__)
        self.assertIn("workshop", src)
        self.assertIn("108600", src)

    def test_a_workshop_map_is_found(self):
        import os
        import tempfile

        from knoxbuild.world import _map_folders

        with tempfile.TemporaryDirectory() as tmp:
            deep = os.path.join(tmp, "3824463369", "mods", "LV200Airliner",
                                "common", "media", "maps", "RKC_WS_Interiors")
            os.makedirs(deep)
            from pathlib import Path
            found = [str(p) for p in _map_folders([Path(tmp)])]
            self.assertTrue(any("RKC_WS_Interiors" in p for p in found), found)


def io_read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


if __name__ == "__main__":
    unittest.main()
