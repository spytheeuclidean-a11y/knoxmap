"""What a city-sized map needs: room tables that fit in memory, buildings made in
small batches that can be stopped, a compile that carries on after a crash, and
one KnoxMap process at a time on a map."""
import json
import os
import random
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

import knoxstop
from knoxbuild import build as B
from knoxbuild import repair as R
from knoxbuild.buildheader import placed_rooms, room_rects
from knoxbuild.settings import Settings
from tools import compile_map as C
from tools import map_source as M


def _reference_placed_rooms(lots):
    """placed_rooms as it was before it went level by level, one dict entry per square: the
    output the per-level rewrite has to match exactly."""
    order = sorted(range(len(lots)), key=lambda i: (lots[i][2] // 300, lots[i][1] // 300, i))
    owner = {}
    for i in order:
        b, tx, ty, base = lots[i]
        for z, floor in enumerate(b.floors):
            for y, row in enumerate(floor.rooms):
                for x, v in enumerate(row):
                    if v > 0:
                        owner[(tx + x, ty + y, base + z)] = (i, v)
    squares = {}
    for (x, y, z), (i, rid) in owner.items():
        squares.setdefault((i, z, rid), set()).add((x, y))
    rank = {lot: n for n, lot in enumerate(order)}
    parts = sorted(squares, key=lambda k: (rank[k[0]], k[1], k[2]))
    at = {(x, y, k[1]): k for k in parts for (x, y) in squares[k]}
    lot_parent = list(range(len(lots)))

    def lfind(i):
        while lot_parent[i] != i:
            lot_parent[i] = lot_parent[lot_parent[i]]
            i = lot_parent[i]
        return i

    for k in parts:
        for (x, y) in squares[k]:
            for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
                n = at.get((x + dx, y + dy, k[1]))
                if n and n[0] != k[0]:
                    lot_parent[lfind(n[0])] = lfind(k[0])
    groups = {}
    for i in order:
        groups.setdefault(lfind(i), []).append(i)
    parts_of = {}
    for k in parts:
        parts_of.setdefault(k[0], []).append(k)
    out = []
    for members in groups.values():
        entries = [{"name": lots[k[0]][0].rooms[k[2] - 1].get("Name", ""), "z": k[1],
                    "rects": room_rects(squares[k])}
                   for lot in members for k in parts_of.get(lot, ())]
        out.append((lots[members[0]][1], lots[members[0]][2], entries))
    return out


def _town(rnd, n, arrays=False):
    lots = []
    for _ in range(n):
        w, h, rooms = rnd.randint(1, 9), rnd.randint(1, 9), rnd.randint(1, 4)
        floors = []
        for _z in range(rnd.randint(1, 3)):
            grid = [[rnd.choice([0] + list(range(1, rooms + 1))) for _x in range(w)]
                    for _y in range(h)]
            floors.append(SimpleNamespace(rooms=np.array(grid, np.int32) if arrays else grid))
        b = SimpleNamespace(floors=floors, rooms=[{"Name": f"room{k}"} for k in range(rooms)])
        # Close enough together to overlap and touch, across 300-tile cells.
        lots.append((b, rnd.randint(0, 700), rnd.randint(0, 700), rnd.choice([0, 0, -1, 1])))
    return lots


class RoomTables(unittest.TestCase):
    def test_the_same_tables_as_one_entry_per_square(self):
        rnd = random.Random(7)
        for _ in range(150):
            lots = _town(rnd, rnd.randint(0, 300))
            self.assertEqual(placed_rooms(lots), _reference_placed_rooms(lots))

    def test_room_grids_read_as_arrays_give_the_same_tables(self):
        rnd = random.Random(11)
        lots = _town(rnd, 200)
        as_arrays = [(SimpleNamespace(floors=[SimpleNamespace(rooms=np.array(f.rooms, np.int32))
                                              for f in b.floors], rooms=b.rooms), x, y, z)
                     for b, x, y, z in lots]
        self.assertEqual(placed_rooms(as_arrays), _reference_placed_rooms(lots))


def _quick_batch(jobs):
    time.sleep(0.05)
    return [(job[0] * 2,) for job in jobs]


def _jobs(n):
    settings = Settings()
    return [(i, 0, 0, 0, 0, 0, 0, settings) for i in range(n)]


class MakingBuildings(unittest.TestCase):
    def setUp(self):
        self._workers = os.environ.get("KNOXBUILD_WORKERS")
        os.environ["KNOXBUILD_WORKERS"] = "2"

    def tearDown(self):
        if self._workers is None:
            os.environ.pop("KNOXBUILD_WORKERS", None)
        else:
            os.environ["KNOXBUILD_WORKERS"] = self._workers

    def test_every_result_in_order_with_progress_as_it_goes(self):
        jobs = _jobs(B.PARALLEL_FROM + 100)
        seen, ticks = {}, []
        out = B._make_all(jobs, tick=lambda d, t: ticks.append((d, t)),
                          on_result=lambda i, r: seen.__setitem__(i, r), make_batch=_quick_batch)
        self.assertEqual(out, [(i * 2,) for i in range(len(jobs))])
        self.assertEqual(seen, dict(enumerate(out)))
        self.assertTrue(ticks and all(t == len(jobs) for _d, t in ticks))

    def test_a_stop_drops_the_work_not_started(self):
        jobs = _jobs(B.MAKE_BATCH * 200)        # 200 batches of 0.05 s on 2 workers: 5 s
        made = []
        t0 = time.time()
        with self.assertRaises(knoxstop.Stopped):
            B._make_all(jobs, should_stop=lambda: len(made) >= B.MAKE_BATCH * 4,
                        on_result=lambda i, r: made.append(i), make_batch=_quick_batch)
        self.assertLess(time.time() - t0, 3.0)
        self.assertLess(len(made), len(jobs))


def _nap(seconds):
    time.sleep(seconds)
    return seconds


class StoppingACompile(unittest.TestCase):
    def _pool(self, naps):
        from concurrent.futures import ProcessPoolExecutor
        pool = ProcessPoolExecutor(max_workers=2)
        return pool, {pool.submit(_nap, s): n for n, s in enumerate(naps)}

    def test_every_job_handed_over(self):
        pool, pending = self._pool([0.2, 0.0, 0.1])
        got = {}
        M._gather(pool, pending, None, lambda fut, n: got.__setitem__(n, fut.result()))
        self.assertEqual(got, {0: 0.2, 1: 0.0, 2: 0.1})

    def test_a_stop_does_not_wait_for_the_jobs_running(self):
        # Each job as long as a row of a city's cells: a stop used to wait them out.
        pool, pending = self._pool([60, 60, 60])
        asked = time.time() + 1.0
        t0 = time.time()
        with self.assertRaises(knoxstop.Stopped):
            M._gather(pool, pending, lambda: time.time() > asked, lambda fut, n: None)
        self.assertLess(time.time() - t0, 10.0)


class CheckingTheBuildings(unittest.TestCase):
    """The check before a compile: what it drops, and not doing it twice."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.base = Path(self._dir.name)
        (self.base / "buildings").mkdir()
        self.refs = []
        for n in range(5):
            ref = f"buildings/b{n}.tbx"
            (self.base / ref).write_text(f"<building {n}/>", encoding="utf-8")
            self.refs.append(ref)
        self.read = []

    def tearDown(self):
        self._dir.cleanup()

    def _check(self, refs=None, should_stop=None):
        def batch(paths, knoxlots):
            self.read.extend(Path(p).name for p in paths)
            return [["broken"] if p.endswith("b3.tbx") else [] for p in paths]

        with mock.patch.object(R, "_check_batch", batch):
            return R.check_lot_files(self.base, refs or self.refs, True, should_stop)

    def test_a_file_checked_before_is_not_read_again(self):
        first = self._check()
        self.assertEqual(first["buildings/b3.tbx"], ["broken"])
        self.assertEqual(len(self.read), 5)
        self.read.clear()
        self.assertEqual(self._check(), first)
        self.assertEqual(self.read, [])
        later = time.time() + 5
        os.utime(self.base / "buildings" / "b1.tbx", (later, later))
        self._check()
        self.assertEqual(self.read, ["b1.tbx"], "only the one that changed")

    def test_a_missing_file_is_said_without_reading(self):
        got = self._check(self.refs + ["buildings/gone.tbx"])
        self.assertEqual(got["buildings/gone.tbx"], ["the file is missing"])
        self.assertNotIn("gone.tbx", self.read)

    def test_a_stop_keeps_what_was_checked(self):
        refs = []
        for n in range(120):
            ref = f"buildings/many{n}.tbx"
            (self.base / ref).write_text("<building/>", encoding="utf-8")
            refs.append(ref)
        with mock.patch.object(R, "PARALLEL_CHECK_FROM", 10 ** 9):
            with self.assertRaises(knoxstop.Stopped):
                self._check(refs, should_stop=lambda: len(self.read) > 0)
            self.assertEqual(len(self.read), 50, "stopped after the first batch")
            self.read.clear()
            self._check(refs)
        self.assertEqual(len(self.read), 70, "the first 50 were kept")

    def test_furniture_out_of_its_room_does_not_drop_a_building(self):
        import sys
        tools = str(Path(R.__file__).resolve().parent.parent / "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        with mock.patch("validate_tbx.check", return_value=[]) as check:
            R._check_building(self.base / self.refs[0], True)
        self.assertIs(check.call_args.kwargs.get("flaws"), False)


class CarryingOnACompile(unittest.TestCase):
    def _run(self, out, rows_made, fail_at=None, resume=True):
        calls = {"read": 0}

        def row(project, out_, cy, band, placed, seed, seams, size):
            if cy == fail_at:
                raise MemoryError()
            rows_made.append(cy)
            return 1

        def read_lots(project):
            calls["read"] += 1
            return []

        with mock.patch.object(M.bitmaps, "_bmp_header", return_value=(256, 256 * 4)), \
                mock.patch.object(M, "project_origin", return_value=(0, 0)), \
                mock.patch.object(M, "read_lots", read_lots), \
                mock.patch.object(M, "read_buildings", return_value=[]), \
                mock.patch.object(M, "_row", row):
            M.make_map_source(self.project, out, workers=1, resume=resume)
        return calls["read"]

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.project = os.path.join(self._dir.name, "town")
        os.makedirs(self.project)

    def tearDown(self):
        self._dir.cleanup()

    def test_rows_finished_before_a_crash_are_not_made_again(self):
        out = os.path.join(self._dir.name, "src")
        made = []
        with self.assertRaises(MemoryError):
            self._run(out, made, fail_at=2)
        self.assertEqual(made, [0, 1])
        made.clear()
        self._run(out, made)
        self.assertEqual(made, [2, 3])
        made.clear()
        read = self._run(out, made)
        self.assertEqual((made, read), ([], 0), "all rows done: the buildings are not read")

    def test_without_resume_every_row_is_made(self):
        out = os.path.join(self._dir.name, "src")
        made = []
        self._run(out, made)
        made.clear()
        self._run(out, made, resume=False)
        self.assertEqual(made, [0, 1, 2, 3])

    def _compile(self, stamp):
        """compile_rust as far as making the cell sources: whether the rows a
        stopped run left were still there when it got that far."""
        project = Path(self.project)
        (project / "town.pzw").write_text("<world/>", encoding="utf-8")
        seen = {}

        def make_map_source(project_, out, **kw):
            seen["kept"] = sorted(p.name for p in Path(out).glob("row_*.done"))
            raise knoxstop.Stopped("the compile")

        with mock.patch.object(C, "knoxlots_exe", return_value="knoxlots"), \
                mock.patch.object(C, "ensure_rail_rules"), \
                mock.patch.object(C, "knoxpaths"), \
                mock.patch.object(C, "prepare_output"), \
                mock.patch.object(C, "_source_stamp", return_value=stamp), \
                mock.patch.object(M, "make_map_source", make_map_source):
            with self.assertRaises(knoxstop.Stopped):
                C.compile_rust(self.project)
        return seen["kept"]

    def test_a_stopped_compile_is_carried_on_only_for_the_same_map(self):
        src = Path(self.project) / ".knoxlots" / "src"
        src.mkdir(parents=True)
        (src / C.SOURCE_STAMP).write_text(json.dumps({"map": 1}), encoding="utf-8")
        (src / "row_0.done").write_text("", encoding="utf-8")
        self.assertEqual(self._compile({"map": 1}), ["row_0.done"])
        self.assertEqual(self._compile({"map": 2}), [], "changed since: made afresh")

    def test_the_stamp_changes_with_the_map(self):
        project = Path(self.project)
        pzw = project / "town.pzw"
        pzw.write_text("<world/>", encoding="utf-8")
        before = C._source_stamp(project)
        self.assertEqual(json.loads(json.dumps(before)), C._source_stamp(project))
        pzw.write_text("<world moved/>", encoding="utf-8")
        self.assertNotEqual(before, C._source_stamp(project))


class OneProcessPerMap(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.project = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()

    def test_another_live_process_building_it_is_refused(self):
        (self.project / C.LOCK_FILE).write_text(json.dumps(
            {"pid": os.getpid() + 1, "run": "other", "doing": "built"}), encoding="utf-8")
        with mock.patch.object(C, "_pid_alive", return_value=True):
            with self.assertRaises(RuntimeError) as said:
                C.claim(self.project, "mine", "compiled")
        self.assertIn("already being built", str(said.exception))

    def test_letting_go_leaves_another_runs_lock_alone(self):
        C.claim(self.project, "mine", "built")
        C.release(self.project, "someone else")
        self.assertTrue((self.project / C.LOCK_FILE).exists())
        C.release(self.project, "mine")
        self.assertFalse((self.project / C.LOCK_FILE).exists())


if __name__ == "__main__":
    unittest.main()
