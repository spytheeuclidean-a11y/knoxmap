import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from generator import chunked, octilinear
from tools.regression_maps import LAT_PER_M, LON_PER_M, SOUTH, WEST
from web import common, generation, jobs


class RoadRenderProgress(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.output = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(patch.object(common, "OUTPUT_DIR", self.output))
        stack.enter_context(patch.object(jobs, "_PROGRESS", {}))
        stack.enter_context(patch.object(jobs, "_STOPPING", set()))
        stack.enter_context(patch.object(generation, "_fetch_landcover"))
        stack.enter_context(patch("knoxdata.run_layers", return_value={}))
        app = Flask(__name__)
        app.register_blueprint(generation.bp)
        app.register_blueprint(jobs.bp)
        self.client = app.test_client()

    def generate(self, name, *, in_chunks, mode, stop=False):
        lines = [[(20, 100), (100, 100), (200, 100), (250, 100)]]
        if not stop:
            lines += [[(x, 100), (x, 215)] for x in (100, 200)]
        sketch = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"kind": "residential"},
             "geometry": {"type": "LineString", "coordinates": [
                 [WEST + x * LON_PER_M, SOUTH + y * LAT_PER_M] for x, y in line
             ]}}
            for line in lines
        ]}
        events = []

        def record_progress(map_name, **fields):
            jobs._set_progress(map_name, **fields)
            if fields.get("stage") in ("roads", "chunks"):
                current = self.client.get("/api/progress", query_string={"map": name}).get_json()
                events.append((current["stage"], current["done"], current["total"]))
                if stop and len(events) == 1:
                    reply = self.client.post("/api/stop", json={"mapName": name})
                    self.assertTrue(reply.get_json()["stopping"])

        # Use the real renderer's dispatch on the same small map in both cases.
        with (
            patch.object(chunked, "CHUNK_MIN_CELLS", 0 if in_chunks else 144),
            patch.object(generation, "_set_progress", side_effect=record_progress),
        ):
            reply = self.client.post("/api/generate", json={
                "mapName": name, "south": SOUTH, "west": WEST,
                "north": SOUTH + 260 * LAT_PER_M, "east": WEST + 410 * LON_PER_M,
                "drawnOnly": True, "sketch": sketch,
                "settings": {"straight_roads": mode, "align_streets": 0, "terrain_only": 1},
            })
        return reply, events

    def graph(self, name):
        return Path(octilinear.graph_path(str(self.output / name), name))

    def test_road_progress_is_separate_from_chunk_progress(self):
        for mode in (2, 3):
            with self.subTest(mode=mode):
                single = f"single_{mode}"
                chunk_map = f"chunked_{mode}"
                single_reply, single_events = self.generate(single, in_chunks=False, mode=mode)
                chunk_reply, chunk_events = self.generate(chunk_map, in_chunks=True, mode=mode)
                for reply in (single_reply, chunk_reply):
                    self.assertEqual(reply.status_code, 200, reply.get_json())
                self.assertTrue(single_events)
                self.assertGreater(max(done for _, done, _ in single_events), 0)
                self.assertTrue(all(stage == "roads" for stage, _, _ in single_events))
                self.assertEqual(chunk_events[:len(single_events)], single_events)
                self.assertEqual(chunk_events[len(single_events):], [("chunks", 0, 1), ("chunks", 1, 1)])
                self.assertEqual(json.loads(self.graph(single).read_text()),
                                 json.loads(self.graph(chunk_map).read_text()))

    def test_stop_during_routing_preserves_the_previous_graph(self):
        for in_chunks in (False, True):
            with self.subTest(in_chunks=in_chunks):
                name = f"stopping_{int(in_chunks)}"
                graph = self.graph(name)
                graph.parent.mkdir()
                previous = b'{"previous": true}'
                graph.write_bytes(previous)
                reply, events = self.generate(name, in_chunks=in_chunks, mode=2, stop=True)
                self.assertEqual(events, [("roads", 0, 1)])
                self.assertEqual(reply.status_code, 409, reply.get_json())
                self.assertEqual(reply.get_json(), {"stopped": True, "step": "generate", "mapName": name})
                self.assertEqual(graph.read_bytes(), previous)
                self.assertFalse((graph.parent / f"{name}.bmp").exists())
