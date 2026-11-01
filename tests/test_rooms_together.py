"""Pieces that belong together are put together.

Measured over 60 houses and flats before and after: a bed with a bedside
table 19% to 74%, a sofa with a coffee table 34% to 51%, dining tables 2.0 to
2.7 chairs, a kitchen with fridge, stove and sink in one run of worktop 36% to
48%. The thresholds sit under the after figures on a smaller sample.
"""
import random
import unittest

from knoxbuild import layout as L


def near(a, b, d=1):
    return any(abs(x1 - x2) + abs(y1 - y2) <= d
               for x1, y1 in L._tiles_under(*a) for x2, y2 in L._tiles_under(*b))


class RoomsTogether(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rooms = []
        rng = random.Random(3)
        for i in range(30):
            kind = rng.choice([None, None, "apartment"])
            b = L.build_building(rng.randint(10, 22), rng.randint(9, 18),
                                 levels=rng.choice((1, 2)), seed=i, kind=kind)
            for s in b.storeys:
                for idx, r in enumerate(s.rooms, 1):
                    fs = [f for f in s.furniture if 0 <= f[2] < s.height and 0 <= f[1] < s.width
                          and s.grid[f[2]][f[1]] == idx]
                    cls.rooms.append((r.kind, fs))

    def share(self, pick, ok):
        got = [ok(p, fs) for _k, fs in self.rooms for p in fs if pick(p)]
        self.assertGreater(len(got), 10)
        return sum(got) / len(got)

    def test_beds_have_a_bedside_table(self):
        self.assertGreater(self.share(
            lambda f: f[0].startswith(("bed", "double_bed")),
            lambda b, fs: any(f[0] in ("nightstand", "sidetable") and near(f, b) for f in fs)), 0.6)

    def test_sofas_have_a_coffee_table(self):
        self.assertGreater(self.share(
            lambda f: f[0] == "sofa" or f[0].startswith("sofa_"),
            lambda so, fs: any(f[0] == "coffee_table" and near(f, so, 2) for f in fs)), 0.4)

    def test_kitchens_are_one_run(self):
        runs = total = 0
        for kind, fs in self.rooms:
            if kind not in ("kitchen", "openplan"):
                continue
            pieces = [f for f in fs if f[0].startswith(("counter", "stove", "fridge"))
                      or L._is_sink(f[0])]
            key = [next((f for f in pieces if f[0].startswith(k)), None) for k in ("fridge", "stove")]
            key.append(next((f for f in pieces if L._is_sink(f[0])), None))
            if None in key:
                continue
            total += 1
            seen, todo = {0}, [0]
            while todo:
                a = todo.pop()
                for j, p in enumerate(pieces):
                    if j not in seen and near(pieces[a], p):
                        seen.add(j)
                        todo.append(j)
            runs += all(any(pieces[j] is k for j in seen) for k in key)
        self.assertGreater(total, 20)
        self.assertGreater(runs / total, 0.38)


if __name__ == "__main__":
    unittest.main()
