import unittest

from knoxbuild import layout, tbx


class RoofLayouts(unittest.TestCase):
    def test_roof_rectangles_cover_an_irregular_footprint_once(self):
        grid = [[1] * 8 + [0] * 4 for _ in range(4)]
        grid.extend([[1] * 12 for _ in range(8)])
        rects = layout.roof_rects(grid)

        for peaked, roof30 in ((False, False), (True, False), (True, True)):
            with self.subTest(peaked=peaked, roof30=roof30):
                covered = [[0] * 12 for _ in range(12)]
                for _kind, _depth, _caps, (x0, y0, width, height) in tbx._roof_pieces(
                        rects, peaked, roof30):
                    for y in range(y0, y0 + height):
                        for x in range(x0, x0 + width):
                            covered[y][x] += 1
                self.assertEqual(covered, grid)

    def test_flat_roof_equipment_varies_by_building_without_overlapping(self):
        grid = [[1] * 10 for _ in range(10)]
        first = tbx._rooftop(grid, 10, 10, "house-a")
        second = tbx._rooftop(grid, 10, 10, "house-b")

        self.assertNotEqual(first, second)
        for placement in (first, second):
            for index, (_role, x, y, _orientation) in enumerate(placement):
                for _other, other_x, other_y, _other_orientation in placement[index + 1:]:
                    self.assertTrue(abs(x - other_x) > 1 or abs(y - other_y) > 1)

    def test_every_roof_piece_is_one_the_world_painter_can_draw(self):
        # buildroofs.roof_squares has no branch for a Peak30Quad whose longer
        # side is even, so such a piece paints nothing: the house keeps its
        # walls and loses its entire roof (108 houses in one town).
        from knoxbuild.buildroofs import roof_squares

        for w in range(3, 14):
            for h in range(3, 14):
                grid = [[1] * w for _ in range(h)]
                for kind, depth, _caps, (x, y, pw, ph) in tbx._roof_pieces(
                        layout.roof_rects(grid), True, True):
                    if kind == "FlatTop":
                        continue
                    with self.subTest(kind=kind, w=w, h=h):
                        self.assertTrue(roof_squares(
                            lambda n: {}, {},
                            dict(RoofType=kind, Depth=depth, x=x, y=y,
                                 width=pw, height=ph)))

    def test_flat_roof_plant_stands_on_the_roof(self):
        # The game hangs an attachedCeiling tile from the ceiling of its level:
        # on the roof floor that is a storey above the roof, which is how the
        # vents and the hatch came to float over the buildings. Only the
        # air-conditioning unit stands on the floor, so it is all a roof gets.
        from knoxbuild import catalog as C

        grid = [[1] * 12 for _ in range(12)]
        roles = {role for role, *_rest in tbx._rooftop(grid, 12, 12, "house-a")}
        self.assertEqual(roles, {"roof_ac"})
        tiles = {tile for orients in C.FURNITURE["roof_ac"].values()
                 for tile in orients.values()}
        self.assertEqual(tiles, {"rooftop_furniture_000", "rooftop_furniture_001"})

    def test_a_pitched_roof_gets_a_chimney(self):
        from knoxbuild import catalog as C

        grid = [[1] * 12 for _ in range(12)]
        placed = tbx._chimneys(grid, 12, 12, "house-a")
        self.assertTrue(1 <= len(placed) <= 2, placed)
        self.assertEqual({role for role, *_rest in placed}, {"roof_chimney"})
        self.assertEqual(C.FURNITURE_LAYERS["roof_chimney"], "Roof")
        for _role, x, y, _orientation in placed:
            self.assertTrue(grid[y][x])
        for index, (_role, x, y, _orientation) in enumerate(placed):
            for _other, other_x, other_y, _other_orientation in placed[index + 1:]:
                self.assertTrue(abs(x - other_x) > 1 or abs(y - other_y) > 1)

    def test_a_shed_is_too_small_for_a_chimney(self):
        grid = [[1] * 4 for _ in range(4)]
        self.assertEqual(tbx._chimneys(grid, 4, 4, "shed"), [])

    def test_a_wide_block_among_many_wings_is_not_given_the_steep_roof(self):
        # An 11-wide block with two narrow wings: three pieces, so the block takes the
        # 45-degree roof (three levels at most), not a 30-degree one six levels high.
        grid = [[1] * 11 for _ in range(12)]
        for y in range(2, 5):
            grid[y] += [1] * 3
        for y in range(8, 11):
            grid[y] += [1] * 3
        grid = [row + [0] * (14 - len(row)) for row in grid]
        kinds = [k for k, _d, _c, box in tbx._roof_pieces(layout.roof_rects(grid), True, True)
                 if box[2] * box[3] >= 100]
        self.assertTrue(kinds and all(not k.startswith("Peak30") for k in kinds), kinds)
        # Alone, the same block keeps it.
        alone = tbx._roof_pieces(layout.roof_rects([[1] * 11 for _ in range(12)]), True, True)
        self.assertTrue(any(k.startswith("Peak30") for k, *_ in alone), alone)

    def test_tiny_pieces_of_a_many_wing_footprint_stay_flat(self):
        # A staircase of 2x2 steps: many small rectangles, none worth a gable of its own.
        grid = [[0] * 12 for _ in range(12)]
        for i in range(6):
            for y in range(2 * i, 2 * i + 2):
                for x in range(2 * i, 12):
                    grid[y][x] = 1
        pieces = tbx._roof_pieces(layout.roof_rects(grid), True, True)
        small = [k for k, _d, _c, (_x, _y, w, h) in pieces if w * h < tbx.MANY_WING_MIN_PITCHED_AREA]
        self.assertTrue(len(pieces) >= tbx.MANY_WING_RECTS and small)
        self.assertEqual(set(small), {"FlatTop"})
        # One small house on its own keeps its gable.
        alone = tbx._roof_pieces(layout.roof_rects([[1] * 3 for _ in range(2)]), True, True)
        self.assertNotEqual(alone[0][0], "FlatTop")


if __name__ == "__main__":
    unittest.main()