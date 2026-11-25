import unittest
from xml.etree import ElementTree

from knoxbuild.structures import render_tiles_tbx


class UserTileLayers(unittest.TestCase):
    def test_sparse_layer_keeps_edge_tiles_empty_rows_and_storeys(self):
        tiles = [
            (4.0, 0.0, 0, "Floor", 'edge & "tile"'),
            (1, 3, 0, "Floor", "brick"),
            (1.5, 1, 0, "Floor", "brick"),
            (5, 2, 0, "Floor", "brick"),
            (0, 0, 2, "Roof", "brick"),
        ]
        root = ElementTree.fromstring(render_tiles_tbx(4, 3, tiles))
        self.assertEqual([tile.get("tile") for tile in root.findall("user_tiles/tile")],
                         ["brick", 'edge & "tile"'])
        ground, middle, roof = root.findall("floor")
        self.assertEqual(ground.find("tiles").text,
                         "\n0,0,0,0,2,\n0,0,0,0,0,\n0,0,0,0,0,\n0,1,0,0,0\n")
        self.assertIsNone(middle.find("tiles"))
        self.assertEqual(roof.find("tiles").text,
                         "\n1,0,0,0,0,\n0,0,0,0,0,\n0,0,0,0,0,\n0,0,0,0,0\n")

    def test_dense_layer_keeps_row_separators_and_numbering(self):
        tiles = [(x, y, 0, "Floor", "floorA" if (x + y) % 2 else "floorB")
                 for y in range(3) for x in range(3)]
        root = ElementTree.fromstring(render_tiles_tbx(2, 2, tiles))
        self.assertEqual(root.find("floor/tiles").text,
                         "\n2,1,2,\n1,2,1,\n2,1,2\n")
