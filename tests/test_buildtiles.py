import unittest

from knoxbuild.buildtiles import level_tiles, parse_tbx, tile_name


def entry(category, **tiles):
    body = "".join(f'<tile enum="{k}" tile="{v}"/>' for k, v in tiles.items())
    return f'<tile_entry category="{category}">{body}</tile_entry>'


def tbx(width, height, floors, rooms=2, extra_attrs=""):
    """Entries, 1-based: 1 exterior wall, 2 trim, 3 grime, 4 door, 5 frame, 6 window, 7 curtains,
    8 shutters, 9 floor A, 10 interior wall A, 11 floor B, 12 interior wall B, 13 interior trim."""
    entries = [
        entry("exterior_walls", West="ew_000", North="ew_001", NorthWest="ew_002", SouthEast="ew_003",
              WestDoor="ew_010", NorthDoor="ew_011", WestWindow9="ew_020", NorthWindow9="ew_021"),
        entry("exterior_wall_trim", West="tr_000", North="tr_001", NorthWest="tr_002", SouthEast="tr_003",
              WestDoor="tr_010", NorthDoor="tr_011"),
        entry("grime_wall", West="gr_000", North="gr_001", NorthWest="gr_002", SouthEast="gr_003",
              WestDoor="gr_010", NorthDoor="gr_011"),
        entry("doors", West="door_000", North="door_001"),
        entry("door_frames", West="frame_000", North="frame_001"),
        entry("windows", West="fixtures_windows_white_016", North="fixtures_windows_white_017"),
        entry("curtains", West="cur_000", East="cur_001", North="cur_002", South="cur_003"),
        entry("shutters", WestBelow="sh_000", WestAbove="sh_001", NorthLeft="sh_002", NorthRight="sh_003"),
        entry("floors", Floor="floorA_000"),
        entry("interior_walls", West="iwA_000", North="iwA_001", NorthWest="iwA_002", WestDoor="iwA_010",
              NorthDoor="iwA_011", WestWindow="iwA_020", NorthWindow="iwA_021"),
        entry("floors", Floor="floorB_000"),
        entry("interior_walls", West="iwB_000", North="iwB_001", NorthWest="iwB_002"),
        entry("interior_wall_trim", West="it_000", North="it_001", NorthWest="it_002", NorthWindow="it_021"),
    ]
    room_defs = (
        '<room Name="a" InteriorWall="10" InteriorWallTrim="0" Floor="9" GrimeFloor="0" GrimeWall="0" Ceiling="0"/>'
        '<room Name="b" InteriorWall="12" InteriorWallTrim="13" Floor="11" GrimeFloor="0" GrimeWall="0" Ceiling="0"/>')
    fl = ""
    for rooms_grid, objects in floors:
        rows = ",\n".join(",".join(str(v) for v in row) for row in rooms_grid)
        objs = "".join("<object " + " ".join(f'{k}="{v}"' for k, v in o.items()) + "/>" for o in objects)
        fl += f"<floor>{objs}<rooms>\n{rows}\n</rooms></floor>"
    return (f'<building version="4" width="{width}" height="{height}" ExteriorWall="1" ExteriorWallTrim="2" '
            f'GrimeWall="3" Door="4" DoorFrame="5" Window="6" {extra_attrs}>' + "".join(entries) + room_defs + fl
            + "</building>")


def grid(w, h, fill=1, **cells):
    g = [[fill] * w for _ in range(h)]
    for (x, y), v in cells.items():
        g[y][x] = v
    return g


class BuildTilesTests(unittest.TestCase):
    def square(self, text, x, y, z=0):
        return level_tiles(parse_tbx(text), z).get((x, y), [])

    def test_names_lose_their_padding(self):
        self.assertEqual(tile_name("walls_exterior_house_02_064"), "walls_exterior_house_02_64")
        self.assertEqual(tile_name("floors_interior_carpet_01_000"), "floors_interior_carpet_01_0")
        self.assertEqual(tile_name("nothing"), "nothing")

    def test_a_room_has_floor_and_interior_walls_on_its_north_and_west_edges(self):
        t = tbx(4, 3, [(grid(4, 3), [])])
        self.assertEqual(self.square(t, 0, 0), ["floorA_0", "iwA_2"])              # both: the corner tile
        self.assertEqual(self.square(t, 2, 0), ["floorA_0", "iwA_1"])
        self.assertEqual(self.square(t, 0, 2), ["floorA_0", "iwA_0"])
        self.assertEqual(self.square(t, 2, 2), ["floorA_0"])

    def test_exterior_walls_stand_on_the_squares_outside_the_south_and_east(self):
        t = tbx(4, 3, [(grid(4, 3), [])])
        self.assertEqual(self.square(t, 1, 3), ["ew_1", "tr_1", "gr_1"])           # south side
        self.assertEqual(self.square(t, 4, 1), ["ew_0", "tr_0", "gr_0"])           # east side
        self.assertEqual(self.square(t, 4, 3), ["ew_3", "tr_3", "gr_3"])           # the post at the corner
        self.assertEqual(self.square(t, 5, 5), [])

    def test_upper_levels_have_no_trim_or_grime_outside(self):
        t = tbx(4, 3, [(grid(4, 3), []), (grid(4, 3), [])])
        self.assertEqual(self.square(t, 1, 3, z=1), ["ew_1"])
        self.assertEqual(self.square(t, 1, 3, z=0), ["ew_1", "tr_1", "gr_1"])

    def test_a_wall_between_two_rooms_belongs_to_the_room_on_its_south_or_east(self):
        g = [[1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2]]
        t = tbx(4, 3, [(g, [])])
        self.assertEqual(self.square(t, 2, 1), ["floorB_0", "iwB_0", "it_0"])      # room b has trim
        self.assertEqual(self.square(t, 1, 1), ["floorA_0"])
        self.assertEqual(self.square(t, 2, 0), ["floorB_0", "iwB_2", "it_2"])

    def test_a_door_swaps_the_wall_and_adds_frame_and_door(self):
        t = tbx(4, 3, [(grid(4, 3), [dict(type="door", x=2, y=0, dir="N")])])
        self.assertEqual(self.square(t, 2, 0), ["floorA_0", "iwA_11", "frame_1", "door_1"])
        t = tbx(4, 3, [(grid(4, 3), [dict(type="door", x=1, y=3, dir="N")])])      # exterior
        self.assertEqual(self.square(t, 1, 3), ["ew_11", "tr_11", "gr_11", "frame_1", "door_1"])

    def test_a_window_with_curtains_and_shutters(self):
        obj = dict(type="window", x=2, y=3, dir="N", CurtainsTile=7, ShuttersTile=8)
        t = tbx(5, 3, [(grid(5, 3), [obj])])
        self.assertEqual(self.square(t, 2, 3), ["ew_21", "sh_2", "sh_3", "fixtures_windows_white_17"])
        self.assertEqual(self.square(t, 1, 3), ["ew_1", "tr_1", "gr_1", "sh_2"])
        self.assertEqual(self.square(t, 3, 3), ["ew_1", "tr_1", "gr_1", "sh_3"])
        self.assertEqual(self.square(t, 2, 2), ["floorA_0", "cur_3"])               # on the inside
        inside = dict(type="window", x=2, y=0, dir="N", CurtainsTile=7)
        t = tbx(5, 3, [(grid(5, 3), [inside])])
        self.assertEqual(self.square(t, 2, 0), ["floorA_0", "iwA_21", "fixtures_windows_white_17", "cur_2"])

    def test_a_floor_with_the_wrong_number_of_rooms_is_refused(self):
        with self.assertRaises(ValueError):
            parse_tbx(tbx(4, 3, [(grid(3, 3), [])]))


def small_building(floors, furniture=()):
    """A 4 x 3 building of one room whose floor tile is F, with a set of stairs and curtains."""
    from knoxbuild.buildtiles import Building
    entries = [
        {"Floor": "F"},                                                  # 1 floor
        {"West": "iw_w", "North": "iw_n", "NorthWest": "iw_nw"},          # 2 interior walls
        {"West1": "st1", "West2": "st2", "West3": "st3", "North1": "sn1", "North2": "sn2", "North3": "sn3"},  # 3
        {"South": "cur_s", "North": "cur_n", "East": "cur_e", "West": "cur_w"},                              # 4
    ]
    room = {"Floor": "1", "InteriorWall": "2", "InteriorWallTrim": "0", "Ceiling": "0"}
    return Building(4, 3, {"Stairs": "3"}, entries, [room], floors, list(furniture))


class FurnitureStairsTests(unittest.TestCase):
    def test_roof_furniture_stands_above_a_flat_roof(self):
        furniture = [{"layer": "Roof", "orients": {"N": [(0, 0, "vent")]}}]
        b = small_building(self.floors([dict(type="roof", RoofType="FlatTop", x=1, y=1,
                                          width=1, height=1, TopTiles=5)], upper=True), furniture)
        b.entries.append({"West1": "roof_floor"})
        b.floors[1].objects.append(dict(type="furniture", FurnitureTiles=0, orient="N", x=1, y=1))
        self.assertEqual(level_tiles(b, 1)[(1, 1)], ["F", "roof_floor", "vent"])

    def test_walls_furniture_replaces_only_its_wall_direction(self):
        furniture = [{"layer": "Walls", "orients": {"N": [(0, 0, "escalator"), (1, 0, "landing")]}}]
        objs = [dict(type="furniture", FurnitureTiles=0, orient="N", x=0, y=0)]
        b = small_building(self.floors(objs), furniture)
        tiles = level_tiles(b, 0)
        self.assertEqual(tiles[(0, 0)], ["F", "iw_w", "escalator"])
        self.assertEqual(tiles[(1, 0)], ["F", "landing"])

    def test_north_curtain_precedes_ordinary_furniture(self):
        furniture = [{"layer": "", "orients": {"N": [(0, 0, "table")]}}]
        objs = [dict(type="furniture", FurnitureTiles=0, orient="N", x=1, y=0),
                dict(type="window", x=1, y=0, dir="N", CurtainsTile=4, Tile=3)]
        b = small_building(self.floors(objs), furniture)
        tiles = level_tiles(b, 0)[(1, 0)]
        self.assertLess(tiles.index("cur_n"), tiles.index("table"))

    def floors(self, objects, upper=None):
        from knoxbuild.buildtiles import Floor
        full = [[1] * 4 for _ in range(3)]
        out = [Floor(full, objects)]
        if upper is not None:
            out.append(Floor([[1] * 4 for _ in range(3)], []))
        return out

    def test_stairs_make_three_steps_and_a_hole_above(self):
        b = small_building(self.floors([dict(type="stairs", x=0, y=1, dir="W", Tile=3)], upper=True))
        ground = level_tiles(b, 0)
        self.assertEqual([ground[(x, 1)][-1] for x in (1, 2, 3)], ["st3", "st2", "st1"])
        above = level_tiles(b, 1)
        self.assertTrue(all((x, 1) not in above for x in (1, 2, 3)))        # no floor over the stairwell
        self.assertIn((0, 1), above)
        b = small_building(self.floors([dict(type="stairs", x=2, y=-1, dir="N", Tile=3)], upper=True))
        self.assertEqual([level_tiles(b, 0)[(2, y)][-1] for y in (0, 1, 2)], ["sn3", "sn2", "sn1"])

    def test_furniture_layers_stack_in_buildinged_order(self):
        furn = [
            {"layer": "", "orients": {"N": [(0, 0, "table")]}},                               # 0 ordinary
            {"layer": "WallFurniture", "orients": {"N": [(0, 0, "paint_n")], "E": [(0, 0, "paint_e")]}},   # 1
            {"layer": "FloorFurniture", "orients": {"N": [(0, 0, "rug")]}},                   # 2
            {"layer": "", "orients": {"N": [(0, 0, "big_a"), (1, 0, "big_b")]}},              # 3 two tiles
        ]
        objs = [dict(type="furniture", FurnitureTiles=0, orient="N", x=1, y=1),
                dict(type="furniture", FurnitureTiles=1, orient="E", x=1, y=1),
                dict(type="furniture", FurnitureTiles=1, orient="N", x=1, y=1),
                dict(type="furniture", FurnitureTiles=2, orient="N", x=1, y=1)]
        b = small_building(self.floors(objs), furn)
        # rug under everything, wall furniture facing north before the table, facing east after it
        self.assertEqual(level_tiles(b, 0)[(1, 1)], ["F", "rug", "paint_n", "table", "paint_e"])
        # Offsets put the second tile on its own square.
        objs = [dict(type="furniture", FurnitureTiles=3, orient="N", x=1, y=1),
                dict(type="window", x=2, y=0, dir="N", CurtainsTile=4, ShuttersTile=0, Tile=3)]
        b = small_building(self.floors(objs), furn)
        t = level_tiles(b, 0)
        self.assertEqual(t[(1, 1)], ["F", "big_a"])
        self.assertEqual(t[(2, 1)], ["F", "big_b"])

    def test_window_variant_follows_the_sprite_pair(self):
        from knoxbuild.buildtiles import _window_variant
        self.assertEqual([_window_variant(f"fixtures_windows_white_{n}") for n in (16, 17, 10, 11, 24, 25)],
                         [9, 9, 6, 6, 13, 13])
        self.assertEqual(_window_variant("fixtures_windows_metal_15"), 8)
        self.assertEqual(_window_variant("fixtures_windows_wood_9"), 5)
        self.assertEqual(_window_variant("fixtures_windows_01_24"), 0)


class AdditionalBuildingRulesTests(unittest.TestCase):
    def test_custom_wall_runs_use_their_material_and_end_post(self):
        for direction, axis in (("W", "North"), ("N", "West")):
            with self.subTest(direction=direction):
                obj = dict(type="wall", x=1, y=1, length=2, dir=direction,
                           Tile=1, InteriorTile=12, ExteriorTrim=2, InteriorTrim=13)
                b = parse_tbx(tbx(4, 4, [(grid(4, 4), [obj])]))
                tiles = level_tiles(b, 0)
                self.assertEqual(tiles[(1, 1)], ["floorA_0", "iwB_1" if axis == "North" else "iwB_0",
                                                "it_1" if axis == "North" else "it_0"])
                # Interior palette lacks SouthEast, so no invented post tile.
                endpoint = (3, 1) if direction == "W" else (1, 3)
                self.assertEqual(tiles[endpoint], ["floorA_0"])
                b.floors[0].rooms = grid(4, 4, fill=0)
                tiles = level_tiles(b, 0)
                self.assertEqual(tiles[endpoint], ["ew_3", "tr_3", "gr_3"])

    def test_corner_door_preserves_perpendicular_wall_and_duplicate_is_written_once(self):
        obj = dict(type="door", x=0, y=0, dir="N")
        b = parse_tbx(tbx(4, 3, [(grid(4, 3), [obj, obj.copy()])]))
        self.assertEqual(level_tiles(b, 0)[(0, 0)], ["floorA_0", "iwA_0", "iwA_11", "frame_1", "door_1"])

    def test_unusual_windows_keep_known_variants_and_unknown_fallback(self):
        from knoxbuild.buildtiles import _window_variant
        self.assertEqual(_window_variant("fixtures_windows_church_15"), 8)
        for n in (40, 42, 48, 50):
            self.assertEqual(_window_variant(f"fixtures_windows_01_{n}"), 17)
        for n in (41, 43, 49, 51):
            self.assertEqual(_window_variant(f"fixtures_windows_01_{n}"), 18)
        self.assertEqual(_window_variant("fixtures_windows_unknown_40"), 0)

    def test_secondary_furniture_precedes_south_curtain(self):
        from knoxbuild.buildtiles import Floor
        furn = [{"layer": "", "orients": {"N": [(0, 0, "first"), (1, 0, "second")]}}]
        objs = [dict(type="furniture", FurnitureTiles=0, orient="N", x=1, y=2),
                dict(type="window", x=2, y=3, dir="N", CurtainsTile=4, Tile=3)]
        b = small_building([Floor(grid(4, 3), objs)], furn)
        self.assertEqual(level_tiles(b, 0)[(2, 2)], ["F", "second", "cur_s"])

    def test_stairs_follow_door_frame_and_door(self):
        b = parse_tbx(tbx(4, 3, [(grid(4, 3), [dict(type="stairs", x=0, y=0, dir="W", Tile=14),
                                             dict(type="door", x=1, y=0, dir="N")])]))
        b.entries.append({"West3": "step"})
        self.assertEqual(level_tiles(b, 0)[(1, 0)], ["floorA_0", "iwA_11", "frame_1", "door_1", "step"])

    def test_composition_preserves_floor_under_later_external_wall_and_sparse_empty_squares(self):
        from knoxbuild.buildtiles import compose_lots
        a = parse_tbx(tbx(4, 3, [(grid(4, 3), [])]))
        sparse = grid(4, 3, fill=0)
        sparse[0][0] = 2
        b = parse_tbx(tbx(4, 3, [(sparse, [])]))
        world = compose_lots([(a, 10, 20, 2), (b, 11, 21, 2)])
        self.assertEqual(world[(11, 21, 2)], ["floorB_0", "iwB_2", "it_2"])
        self.assertEqual(world[(12, 21, 2)], ["floorA_0", "ew_0", "tr_0", "gr_0"])
        self.assertEqual(world[(13, 22, 2)], ["floorA_0"])
        reverse = compose_lots([(b, 11, 21, 2), (a, 10, 20, 2)])
        self.assertEqual(reverse[(11, 21, 2)], ["floorA_0"])

    def test_corner_trim_is_replaced_by_north_wall_and_preserved_by_west_wall(self):
        from knoxbuild.buildtiles import compose_lots
        a = parse_tbx(tbx(4, 3, [(grid(4, 3), [])]))
        sparse = grid(4, 3, fill=0)
        sparse[0][:2] = [2, 2]
        b = parse_tbx(tbx(4, 3, [(sparse, [])]))
        west = compose_lots([(a, 0, 0, 0), (b, 2, 3, 0)])
        self.assertEqual(west[(4, 3, 0)], ["tr_3", "ew_0", "tr_0", "gr_0"])
        north = compose_lots([(a, 0, 0, 0), (b, 3, 2, 0)])
        self.assertEqual(north[(4, 3, 0)], ["gr_3", "ew_1", "tr_1", "gr_1"])


if __name__ == "__main__":
    unittest.main()
