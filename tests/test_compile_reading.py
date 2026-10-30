"""Reading the buildings before a compile: the quick reader sees what the full one does."""
import os
import tempfile
import unittest

from knoxbuild.buildheader import placed_rooms
from knoxbuild.buildtiles import parse_tbx, parse_tbx_rooms
from knoxbuild.layout import build_building
from knoxbuild.tbx import render_tbx
from tools.map_source import read_buildings


def _tbx(seed):
    return render_tbx(build_building(14 + seed % 6, 12 + seed % 5, levels=1 + seed % 3, seed=seed), "b", None)


class RoomsOnlyReader(unittest.TestCase):
    def test_same_size_rooms_and_room_numbers(self):
        for seed in range(6):
            text = _tbx(seed)
            full, quick = parse_tbx(text), parse_tbx_rooms(text)
            self.assertEqual((full.width, full.height), (quick.width, quick.height))
            self.assertEqual(full.rooms, quick.rooms)
            self.assertEqual([f.rooms for f in full.floors], [f.rooms for f in quick.floors])

    def test_the_room_tables_come_out_the_same(self):
        lots = [(i, 20 * (i % 5), 20 * (i // 5), 0) for i in range(10)]
        texts = [_tbx(i) for i in range(10)]
        full = placed_rooms([(parse_tbx(t), x, y, z) for t, (_i, x, y, z) in zip(texts, lots)])
        quick = placed_rooms([(parse_tbx_rooms(t), x, y, z) for t, (_i, x, y, z) in zip(texts, lots)])
        self.assertEqual(full, quick)

    def test_buildings_come_back_in_the_order_asked_for(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "buildings"))
            for n in range(3):
                with open(os.path.join(d, "buildings", f"b{n}.tbx"), "w", encoding="utf-8") as f:
                    f.write(_tbx(n))
            got = read_buildings(d, ["b2", "b0", "b1"])
            want = [parse_tbx_rooms(_tbx(n)) for n in (2, 0, 1)]
            self.assertEqual([(b.width, b.height) for b in got], [(b.width, b.height) for b in want])


if __name__ == "__main__":
    unittest.main()
