"""Selftest checks for web presets."""
from __future__ import annotations

if __package__ == "tools.selftest_suite":
    from ..selftest import (
        Path, _os, json,
        os, re,
    )
else:
    from selftest import (
        Path, _os, json,
        os, re,
    )


def check_box_any(check) -> None:
    """The reach test the gardens use works a strip at a time, to keep a town's
    summed-area table out of memory; it must still answer the same."""
    import numpy as np

    from generator.rendering import vegetation
    from generator.rendering.vegetation import _box_any

    def whole_map(mask, radius):
        h, w = mask.shape
        pad = np.pad(mask.astype(np.int32), radius + 1)
        ii = pad.cumsum(0).cumsum(1)
        k = 2 * radius + 1
        return (ii[k:k + h, k:k + w] - ii[0:h, k:k + w]
                - ii[k:k + h, 0:w] + ii[0:h, 0:w]) > 0

    rng = np.random.default_rng(3)
    was = vegetation.BOX_STRIP_ROWS
    same = True
    try:
        for shape, radius, strip in (((300, 200), 3, 64), ((97, 61), 0, 7),
                                     ((512, 300), 12, 512), ((200, 200), 1, 3)):
            vegetation.BOX_STRIP_ROWS = strip
            mask = rng.random(shape) < 0.02
            same = same and np.array_equal(_box_any(mask, radius), whole_map(mask, radius))
    finally:
        vegetation.BOX_STRIP_ROWS = was
    check(same, "the gardens' reach test gives the same answer strip by strip")


def check_config_file(check, work: str) -> None:
    """The settings file survives being damaged, and being written twice at once."""
    import json as _json
    import threading

    import knoxpaths

    was = knoxpaths.CONFIG_PATH
    knoxpaths.CONFIG_PATH = Path(work) / "config_test.json"
    try:
        for what, text in (("a list", "[1, 2]"), ("null", "null"), ("a string", '"x"'),
                           ("cut short", '{"pz_install": "C:/Games/Zomb'), ("empty", "")):
            knoxpaths.CONFIG_PATH.write_text(text, encoding="utf-8")
            if knoxpaths.load_config() != {}:
                check(False, f"{what} should read as no settings at all")
                break
        else:
            check(True, "a settings file that is not an object reads as no settings")
        knoxpaths.CONFIG_PATH.write_text(_json.dumps({"pz_install": "C:/Games/PZ"}), encoding="utf-8")
        knoxpaths.update_config({"language": "english"})
        knoxpaths.update_config({"auto_update": False})
        got = knoxpaths.load_config()
        check(got == {"pz_install": "C:/Games/PZ", "language": "english", "auto_update": False}
              and not Path(str(knoxpaths.CONFIG_PATH) + ".tmp").exists(),
              "changing one setting keeps the rest, and False is kept as False")
        threads = [threading.Thread(target=knoxpaths.update_config, args=({f"key{i}": i},))
                   for i in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        got = knoxpaths.load_config()
        check(all(got.get(f"key{i}") == i for i in range(40)),
              "forty changes made at once are all kept")
    finally:
        knoxpaths.CONFIG_PATH = was


def check_flat_selection(check) -> None:
    """An outline with no area is refused, not built as an empty map.

    A lasso drawn as one stroke, or a traced outline whose points land on each
    other, gets through as a valid polygon that encloses nothing. The renderer
    clips the map to it, which turns everything outside - all of it - back
    into grass, and the generation finishes and hands over a meadow.
    """
    import app as knoxapp

    w, s, e, n = 19.20, 42.40, 19.32, 42.48

    def ask(ring):
        shape, problem = knoxapp._clean_shape(
            {"type": "Polygon", "coordinates": [ring]})
        return shape, problem

    shape, problem = ask([[w, s], [e, s], [e, n], [w, n], [w, s]])
    check(shape is not None and not problem,
          "an outline drawn round a town is taken")

    # Small, but a real selection: roughly 220 m across. Nothing here may
    # refuse a genuinely small map.
    shape, problem = ask([[w, s], [w + 0.002, s], [w + 0.002, s + 0.002],
                          [w, s + 0.002], [w, s]])
    check(shape is not None and not problem,
          "and so is a small one, a couple of hundred metres across")

    for label, ring in (
        ("one stroke", [[w, s], [(w + e) / 2, (s + n) / 2], [e, n], [w, s]]),
        ("all one point", [[w, s]] * 4),
    ):
        shape, problem = ask(ring)
        check(shape is None and problem and "no area" in problem,
              f"an outline that is {label} is refused with a reason, not "
              f"generated as empty ground")


def check_health(check) -> None:
    """The health check answers without the network, and says what the PC holds."""
    import app as knoxapp

    data = knoxapp.app.test_client().get("/api/health").get_json()
    res = data.get("resources", {})
    check(isinstance(data.get("checks"), list) and "compileWorkers" in res
          and res["compileWorkers"] >= 1 and "overpass" not in data,
          "the health check lists the setup and the PC's room, and leaves the network alone by default")


def check_mapstate(check, out: str) -> None:
    """What a newer KnoxMap needs redone on an older map, and what it leaves
    alone (knoxbuild/mapstate.py)."""
    import knoxlog
    from knoxbuild import mapstate

    # The map the selftest just made: built, compiled and installed by this
    # version, so there is nothing to redo.
    for stage in mapstate.STAGES:
        mapstate.stamp(out, stage)
    check(mapstate.needs(out) == [] and mapstate.made_with(out) == knoxlog.version(),
          "a map this KnoxMap made needs nothing redone")

    def with_stages(versions: dict) -> list[str]:
        state = {"stages": {k: {"version": v} for k, v in versions.items()}}
        with open(os.path.join(out, mapstate.STATE_FILE), "w", encoding="utf-8") as f:
            json.dump(state, f)
        return mapstate.needs(out)

    # A map older than every step: all four, in order.
    old = {k: "1.0" for k in mapstate.STAGES}
    check(with_stages(old) == list(mapstate.STAGES) and mapstate.made_with(out) == "1.0",
          "a map older than everything is redone from the start")

    # One whose terrain is current but whose buildings are not: build again,
    # and everything after it - but not the terrain.
    current = {k: knoxlog.version() for k in mapstate.STAGES}
    check(with_stages({**current, "build": "1.0", "compile": "1.0", "install": "1.0"})
          == ["build", "compile", "install"],
          "a map with older buildings is built, compiled and installed again")

    # And one that only has to go in again.
    check(with_stages({**current, "install": "1.0"}) == ["install"],
          "a map that only needs installing again is only installed again")

    # A step redone makes what came after it stale.
    mapstate.stamp(out, "build")
    done = mapstate.done(out)
    check("compile" not in done and "install" not in done,
          "building again clears the compile and install it made stale")


def check_memory_guard(check) -> None:
    """A map too big for the memory there is says so before it starts.

    It is a warning now, not a refusal: nothing about an area stops a map
    being built, because a big map can be built and what it costs is the
    mapper's to spend. What this still has to do is say the number, so
    somebody choosing an area knows, and so a run that does die of it has the
    figure in its log."""
    import app as knoxapp
    import knoxlog
    from web import checks as webchecks

    real = knoxlog.memory_status
    try:
        knoxlog.memory_status = lambda: (15_000_000_000, 5_300_000_000, 2_100_000_000)

        class Small:                      # a 32-bit Python
            maxsize = 2 ** 32 - 1

        # The area is worked out from the per-tile cost the code declares, not
        # written down here: at 80 bytes a tile 5400x6000 was over a 32-bit
        # Python's room, and at 20 it is not. What is being tested is the rule.
        room = 2_100_000_000 * 0.8
        side = int(((room - webchecks.BASE_BYTES) / webchecks.BYTES_PER_TILE * 1.5) ** 0.5) + 1
        was, webchecks.sys = webchecks.sys, Small
        try:
            big = knoxapp._too_big_for_memory(side, side)
            small = knoxapp._too_big_for_memory(1200, 1200)
        finally:
            webchecks.sys = was
        import knoxpaths as _kp
        check(big and "32-bit" in big and _kp.setup_command() in big and not small,
              "a map too big for a 32-bit Python is warned about, with a way out")
        knoxlog.memory_status = lambda: (15_000_000_000, 900_000_000, 140_000_000_000)
        tight = knoxapp._too_big_for_memory(side, side)
        check(tight and "free" in tight,
              "and so is one too big for the memory that is free")
    finally:
        knoxlog.memory_status = real


def check_odd_requests(check, work: str) -> None:
    """Requests with the wrong kind of value in them are answered, not crashed on,
    and a download that fails leaves no folder behind."""
    import app as knoxapp
    from web import common as webcommon

    def no_download(*_a, **_k):
        raise RuntimeError("the network is off in this test")

    was_fetch, was_out = knoxapp.osm.fetch_features_tiled, webcommon.OUTPUT_DIR
    knoxapp.osm.fetch_features_tiled = no_download
    webcommon.OUTPUT_DIR = Path(work) / "odd_output"
    webcommon.OUTPUT_DIR.mkdir()
    try:
        client = knoxapp.app.test_client()
        box = {"south": 40.0, "west": 20.0, "north": 40.01, "east": 20.01}
        statuses = [client.post("/api/generate", json={**box, "mapName": what}).status_code
                    for what in (7, ["x"], {"a": 1}, True)]
        check(set(statuses) == {502},
              f"a map name that is not text is replaced by one, not a crash ({statuses})")
        check(not any(webcommon.OUTPUT_DIR.iterdir()),
              "and a download that fails leaves no folder in output/")
        check(all(client.post("/api/client-error", json=v).status_code == 200
                  for v in ("x", 5, [], None)),
              "the page's error report is taken whatever it sends")
        import knoxlog
        before = open(knoxlog.MAIN_LOG, encoding="utf-8").read().count("page error")
        client.post("/api/client-error", json={})
        check(open(knoxlog.MAIN_LOG, encoding="utf-8").read().count("page error") == before,
              "an empty page error report is not written to the log")
        was_mem = knoxlog.memory_status
        from web import checks as webchecks
        was_tile = webchecks.BYTES_PER_TILE
        try:
            # A tenth of a degree is a small box; it is only bigger than this
            # PC's whole memory at a per-tile cost that adds up, so the test
            # says what that cost is instead of leaning on today's number.
            webchecks.BYTES_PER_TILE = 100_000
            knoxlog.memory_status = lambda: (8 * 2 ** 30, 4 * 2 ** 30, 2 ** 40)
            r = client.post("/api/generate", json={"south": 10.0, "west": 10.0,
                                                   "north": 10.1, "east": 10.1, "mapName": "x"})
            check(r.status_code == 400 and "cannot be made here" in r.get_json()["error"],
                  f"a map bigger than the PC's whole memory is refused ({r.status_code} {r.get_json()})")
        finally:
            knoxlog.memory_status = was_mem
            webchecks.BYTES_PER_TILE = was_tile
    finally:
        knoxapp.osm.fetch_features_tiled = was_fetch
        webcommon.OUTPUT_DIR = was_out


def check_portable_presets(check, work: str) -> None:
    """Portable presets survive export/import and refuse unusable map geometry."""
    import app as knoxapp
    import json as _json
    from unittest.mock import patch

    from web import presets as webpresets

    client = knoxapp.app.test_client()
    polygon = {"type": "Polygon", "coordinates": [
        [[20, 40], [20.01, 40], [20.01, 40.01], [20, 40.01], [20, 40]]]}
    data = {"format": "knoxmap-preset", "version": 1, "name": "Village / A",
            "south": 40, "west": 20, "north": 40.01, "east": 20.01,
            "metersPerTile": 2, "shape": polygon,
            "settings": {"preset": "city", "seed": 42, "max_levels": 12,
                         "arch_style": "cn", "tree_density": 0.25}}
    reply = client.post("/api/presets/validate", json=data)
    good = reply.get_json().get("preset", {})
    check(reply.status_code == 200 and good.get("shape") == polygon
          and good.get("settings", {}).get("seed") == 42
          and good.get("settings", {}).get("arch_style") == "cn"
          and good.get("preset") == "city",
          "a portable outline, scale and settings survive validation")
    exported = client.post("/api/presets/export", json=data)
    check(exported.status_code == 200
          and "attachment" in exported.headers.get("Content-Disposition", "")
          and _json.loads(exported.data) == good,
          "the browser downloads an importable portable JSON preset")
    restored = client.post("/api/presets/validate", json=_json.loads(exported.data))
    check(restored.status_code == 200 and restored.get_json()["preset"] == good,
          "an exported preset imports without losing any settings or coordinates")
    page = client.get("/").get_data(as_text=True)
    labels = ("Export file", "Import file", "Copy link", "Open link")
    english = (Path(knoxapp.BASE_DIR) / "lang" / "english.txt").read_text(encoding="utf-8")
    check(all(f'id="{tag}"' in page for tag in
              ("presetExport", "presetImport", "presetShare", "presetOpenLink", "presetFile"))
          and all(f"{label} = {label}" in english for label in labels),
          "all sharing controls and their English translations are present")
    rect = {**data, "shape": None, "metersPerTile": 0.5, "name": "Rectangle"}
    simple = client.post("/api/presets/validate", json=rect)
    check(simple.status_code == 200 and simple.get_json()["preset"]["shape"] is None
          and simple.get_json()["preset"]["metersPerTile"] == 0.5,
          "a rectangular selection with half-metre scale is shareable")
    poly2 = {"type": "MultiPolygon", "coordinates": [polygon["coordinates"]]}
    multi = client.post("/api/presets/validate", json={**data, "shape": poly2})
    check(multi.status_code == 200 and multi.get_json()["preset"]["shape"] == poly2,
          "a MultiPolygon survives the same round trip")
    bad_cases = [
        {**data, "format": "unknown"},
        {**data, "version": 2},
        {**data, "south": 40.02},
        {**data, "west": float("nan")},
        {**data, "metersPerTile": 0},
        {**data, "settings": None},
        {**data, "shape": {"type": "Point", "coordinates": [20, 40]}},
        {**data, "shape": {"type": "Polygon", "coordinates": [
            [[20, 40], [20.01, 40], [20.02, 40], [20, 40]]]}},
        {**data, "shape": {"type": "Polygon", "coordinates": [
            [[20, 40], [20.03, 40], [20.03, 40.01], [20, 40]]]}},
        {**data, "shape": {"type": "Polygon", "coordinates": [
            [[20, 40]] * (knoxapp.MAX_PRESET_POINTS + 1)]}},
    ]
    check(all(client.post("/api/presets/validate", json=d).status_code == 400
              for d in bad_cases),
          "invalid format, coordinates, scale and outlines cannot be imported")
    odd_preset = client.post("/api/presets/validate", json={**data, "preset": ["city"]})
    check(odd_preset.status_code == 200 and odd_preset.get_json()["preset"]["preset"] is None,
          "a malformed optional style name cannot crash a preset import")
    target_root = Path(work) / "portable_preset_export"
    target_root.mkdir(exist_ok=True)
    with patch.object(webpresets, "BASE_DIR", target_root), \
            patch("knoxlog.open_folder") as show, \
            patch.dict(_os.environ, {"KNOXMAP_WINDOW": "1"}):
        first = client.post("/api/presets/export", json=data)
        second = client.post("/api/presets/export", json=data)
        folder = target_root / "preset_exports"
        files = list(folder.glob("*.knoxmap.json"))
        check(first.status_code == 200 and second.status_code == 200
              and len(files) == 2 and show.call_count == 2
              and all(_json.loads(path.read_text(encoding="utf-8")) == good
                      for path in files),
              "the desktop exports a real file without overwriting an existing export")


def check_saved_areas(check, work: str) -> None:
    """Saved areas: kept by name, checked on the way in, gone when deleted."""
    import app as knoxapp
    from web import presets as webpresets

    was = webpresets.PRESETS_FILE
    webpresets.PRESETS_FILE = Path(work) / "presets_test.json"
    try:
        client = knoxapp.app.test_client()
        body = {"name": "Old town", "south": 40.0, "west": 20.0, "north": 40.01,
                "east": 20.01, "metersPerTile": 2, "shape": None,
                "settings": {"preset": "default", "seed": 7, "tree_density": 0.5}}
        check(client.get("/api/presets").get_json()["presets"] == [],
              "no saved areas to begin with")
        saved = client.post("/api/presets", json=body)
        check(saved.status_code == 200, "an area is saved under a name")
        got = client.get("/api/presets").get_json()["presets"]
        check(len(got) == 1 and got[0]["name"] == "Old town"
              and got[0]["metersPerTile"] == 2 and got[0]["settings"]["seed"] == 7,
              "and comes back with its scale and settings")
        client.post("/api/presets", json={**body, "metersPerTile": 4})
        got = client.get("/api/presets").get_json()["presets"]
        check(len(got) == 1 and got[0]["metersPerTile"] == 4,
              "saving under the same name replaces it")
        poly = {"type": "Polygon", "coordinates": [[[20, 40], [20.01, 40], [20.01, 40.01], [20, 40]]]}
        check(client.post("/api/presets", json={**body, "name": "Shape", "shape": poly})
              .status_code == 200, "an outline can be saved")
        for bad, why in (({**body, "name": " "}, "a blank name"),
                         ({**body, "north": 39.0}, "an area upside down"),
                         ({**body, "south": 95.0, "north": 96.0}, "an area off the map"),
                         ({**body, "shape": {"type": "Point", "coordinates": [1, 2]}},
                          "an outline that is not a polygon"),
                         ({"name": "x"}, "no area at all")):
            if client.post("/api/presets", json=bad).status_code != 400:
                check(False, f"{why} should be refused")
                break
        else:
            check(True, "a blank name, a bad area and a bad outline are refused")
        check(client.delete("/api/presets/Old%20town").status_code == 200
              and [p["name"] for p in client.get("/api/presets").get_json()["presets"]] == ["Shape"],
              "a saved area can be deleted")
        check(client.delete("/api/presets/Old%20town").status_code == 404,
              "and deleting it again says it is not there")
    finally:
        webpresets.PRESETS_FILE = was


def check_stop(check) -> None:
    """Stopping a long job: it gives up where it is asked to, and nothing it
    was working on is thrown away (knoxstop.py)."""
    import knoxstop

    stop = {"now": False}
    asked = lambda: stop["now"]          # noqa: E731 - what the jobs are given

    knoxstop.check(asked, "the download")    # not asked yet: no exception
    check(True, "a job that has not been stopped carries on")

    stop["now"] = True
    try:
        knoxstop.check(asked, "the download")
        stopped = False
    except knoxstop.Stopped as exc:
        stopped = "download" in str(exc)
    check(stopped, "a job that has been stopped raises Stopped, saying which")

    # The compile stops between batches and kills the batch it is in.
    import inspect

    from tools import compile_map as compiler
    src = inspect.getsource(compiler.compile_map)
    check("should_stop" in inspect.signature(compiler.compile_map).parameters
          and "_run_batch" in src,
          "the compile watches for a stop inside a batch, not only between them")
    batch = inspect.getsource(compiler._run_batch)
    check("terminate" in inspect.getsource(compiler._end_batch),
          "and closes WorldEd down rather than waiting it out")
    # Under Wine the tools' pipes are inherited by wineserver, which outlives
    # them: reading those to the end never ended, so a dead WorldEd left the
    # window compiling for ever and Stop could not get out of it either.
    check("PIPE" not in batch and "communicate" not in batch
          and "proc.wait(" in batch,
          "a batch is waited for by the process, never by its pipes")
    check("killpg" in inspect.getsource(compiler._end_batch)
          and "start_new_session" in batch,
          "and off Windows the whole group goes, since `wine` is only a launcher")
    for source in (batch, inspect.getsource(compiler._end_batch)):
        waits = re.findall(r"\.wait\(([^)]*)\)", source)
        check(waits and all("timeout" in w for w in waits),
              "nothing in a batch waits without a deadline")


def check_throttle(check) -> None:
    """The compile eases off when WorldEd fails under load, and only so far."""
    import threading
    import time as _time

    from tools.compile_map import Throttle

    t = Throttle(4)
    check(t.limit == 4 and t.ease() == 3, "the compile gives up a slot after a failure")
    check(t.ease() is None and t.limit == 3,
          "a burst of failures from one overload counts once")
    t._eased_at = 0.0
    check(t.ease() == 2, "and again if it still fails a while later")
    one = Throttle(1)
    check(one.ease() is None and one.limit == 1, "but never below one")

    # A slot held by a batch keeps the next one waiting, and the limit it waits
    # under is whatever it is by then.
    t = Throttle(2)
    t.acquire()
    t.acquire()
    got = []
    waiter = threading.Thread(target=lambda: (t.acquire(), got.append(1)), daemon=True)
    waiter.start()
    _time.sleep(0.3)
    check(not got, "a third batch waits while two are running")
    t.release()
    waiter.join(3)
    check(got == [1], "and starts as soon as one ends")

