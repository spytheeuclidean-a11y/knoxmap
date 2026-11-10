"""The second half of the selftest's checks: compile, install, updates, the game.

Split from tools/selftest.py alongside selftest_checks_a.py. The fixtures and
the driver live in selftest.py; the names below are imported from it.
"""
from __future__ import annotations

from selftest import (
    EAST,
    Image,
    NORTH,
    OSMFeature,
    Path,
    SOUTH,
    WEST,
    _os,
    box,
    contextlib,
    io,
    json,
    main,
    math,
    os,
    shutil,
    sys,
    tempfile,
    way,
)




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




def check_overpass_blank(check) -> None:
    """A server that answers with nothing does not empty the map.

    Two ways a download used to succeed and bring back no town. Overpass
    reports a query it could not finish as HTTP 200 with the reason in
    "remark" and whatever it had managed in "elements"; and one of the public
    instances answers every query at all with 200 and an empty list. Either
    read as a tile of open farmland, so a city came out a meadow with its
    river still in it - the river was in the tiles that did arrive. Nothing
    here touches the network.
    """
    from generator import osm as _osm

    class Reply:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    ONE = {"elements": [{"type": "node", "id": 1, "lat": 50.0, "lon": 5.0,
                         "tags": {"natural": "tree"}}]}
    EMPTY: dict = {"elements": []}

    was_post, was_sleep = _osm.requests.post, _osm.time.sleep
    try:
        _osm.time.sleep = lambda _s: None
        replies: dict = {}
        asked: list = []

        def post(endpoint, data=None, headers=None, timeout=None):
            asked.append(endpoint.split("/")[2])
            return replies.get(asked[-1], Reply(EMPTY))

        _osm.requests.post = post
        first_host = _osm.OVERPASS_ENDPOINTS[0].split("/")[2]

        # A part-finished query is a failure, not an empty tile.
        _osm._cooling.clear()
        replies = {first_host: Reply({**EMPTY, "remark":
                   'runtime error: Query timed out in "query" after 90 s.'})}
        try:
            _osm._ask(_osm.OVERPASS_ENDPOINTS[0], "", 60)
            said, big = "", False
        except _osm.OverpassError as exc:
            said, big = str(exc), exc.too_big
        check("timed out" in said and big,
              "a 200 that says the query timed out counts as too big, not as "
              "an empty tile")

        # The instance whose turn it is answers with nothing; another has the
        # data. The tile is the data.
        _osm._cooling.clear()
        second_host = _osm.ANSWERING_ENDPOINTS[1].split("/")[2]
        replies = {second_host: Reply(ONE)}
        asked.clear()
        got = _osm.fetch_features(50.0, 5.0, 50.1, 5.1, timeout=10, first=0)
        check(len(got) == 1 and asked[1] == second_host,
              f"a blank answer is not the tile; the next instance is asked "
              f"and its {len(got)} feature kept")

        # The instance that answers an ordinary query with nothing is asked
        # last, never first. Rotating over all three put every third tile on
        # it to begin with, which spent a round trip and a second's wait
        # before the tile had asked anything that could answer it.
        blank_host = _osm.OVERPASS_ENDPOINTS[-1].split("/")[2]
        firsts = set()
        _osm._cooling.clear()
        for turn in range(len(_osm.OVERPASS_ENDPOINTS) * 2):
            replies = {}
            asked.clear()
            _osm._cooling.clear()
            _osm.fetch_features(50.0, 5.0, 50.1, 5.1, timeout=10, first=turn)
            firsts.add(asked[0])
        check(blank_host not in firsts,
              f"{blank_host} answers with nothing, so no tile starts on it "
              f"(tiles started on {len(firsts)} of the others)")

        # ...but real open country is empty, and has to stay downloadable.
        _osm._cooling.clear()
        replies = {}
        got = _osm.fetch_features(50.0, 5.0, 50.1, 5.1, timeout=10)
        check(got == [],
              "a tile every instance agrees is empty is still an empty tile")

        # One instance saying nothing while the rest never answer is not
        # agreement. The tile goes back round the retry rather than into the
        # map as a field.
        _osm._cooling.clear()
        replies = {h.split("/")[2]: Reply({}, status=504)
                   for h in _osm.OVERPASS_ENDPOINTS[1:]}
        try:
            got = _osm.fetch_features(50.0, 5.0, 50.1, 5.1, timeout=10)
            said = f"returned {len(got)} features"
        except _osm.OverpassError:
            said = "raised"
        check(said == "raised",
              "one blank answer and no other answer at all is a failed tile, "
              f"not an empty one ({said})")

        # An instance that stopped answering is left out until it has had a
        # rest, so the tiles behind the first one do not each wait the whole
        # timeout to learn the same thing.
        _osm._cooling.clear()
        _osm._fails.clear()
        down = _osm.ANSWERING_ENDPOINTS[0]
        replies = {down.split("/")[2]: Reply({}, status=504)}
        asked.clear()
        _osm.fetch_features(50.0, 5.0, 50.1, 5.1, timeout=10, first=0)
        paid = list(asked)
        asked.clear()
        _osm.fetch_features(50.0, 5.0, 50.1, 5.1, timeout=10, first=0)
        check(down.split("/")[2] not in asked and asked,
              "an instance that answered 504 is left alone while it rests, and "
              f"the tiles behind it go to the others ({asked})")

        # ...and when every instance is resting nothing is asked at all: the
        # download waits and tries again after the rest (22,515 requests in a
        # day, 14,608 of them 504, is what asking anyway came to).
        _osm._cooling.clear()
        _osm._fails.clear()
        for e in _osm.ANSWERING_ENDPOINTS:
            _osm._note_down(e)
        order = _osm._endpoint_order(0)
        check(not any(e in order for e in _osm.ANSWERING_ENDPOINTS),
              "with every instance resting the tile asks none of them")
        _osm._cooling.clear()
        _osm._fails.clear()

        # The wait between passes outlasts a busy spell instead of landing
        # back inside it.
        pauses = [_osm._retry_pause(a) for a in range(1, _osm.TILE_ATTEMPTS)]
        check(pauses == sorted(pauses) and pauses[-1] >= 90 and len(pauses) >= 2,
              f"the retry backs off over minutes, not seconds ({pauses})")

        # A map small enough to be a single tile still gets every pass: it is
        # what the failure message tells people to try, so it must not be the
        # path that tries least.
        _osm._cooling.clear()
        passes = [0]
        real_split = _osm._fetch_splitting

        def counting(*a, **k):
            passes[0] += 1
            raise _osm.OverpassError("nope", timed_out=True)

        _osm._fetch_splitting = counting
        pause, _osm.RETRY_PAUSE_S = _osm.RETRY_PAUSE_S, 0
        try:
            _osm.fetch_features_tiled(50.0, 5.0, 50.01, 5.01, max_tile_km2=30.0)
        except Exception:
            pass
        finally:
            _osm._fetch_splitting = real_split
            _osm.RETRY_PAUSE_S = pause
        check(passes[0] == _osm.TILE_ATTEMPTS,
              f"a one-tile map is asked for on every pass, not just the first "
              f"({passes[0]} of {_osm.TILE_ATTEMPTS})")

        check("openstreetmap.fr" not in " ".join(_osm.OVERPASS_ENDPOINTS),
              "the endpoint that 403s every request is not asked")
    finally:
        _osm.requests.post, _osm.time.sleep = was_post, was_sleep




def check_no_size_wall(check, work: str) -> None:
    """An area bigger than the comfortable one is still built.

    Every size check used to answer 400 and the window greyed the button out,
    so somebody who wanted a whole city could not have one at all. They are
    warnings now: the window says what it will cost and the button stays lit.
    What is still refused is a scale that is not a scale, because dividing the
    world by zero is not a map anybody asked for.

    Nothing here touches the network. The OpenStreetMap fetch is replaced with
    something that fails at once, so a request that reaches it has been past
    every size gate there is - which is the thing being tested.
    """
    import app as knoxapp
    from web import common as webcommon

    class Reached(RuntimeError):
        """Raised where the download would start."""

    def no_download(*_a, **_k):
        raise Reached("got as far as the download")

    client = knoxapp.app.test_client()
    was_fetch = knoxapp.osm.fetch_features_tiled
    was_out = webcommon.OUTPUT_DIR
    knoxapp.osm.fetch_features_tiled = no_download
    webcommon.OUTPUT_DIR = Path(work) / "huge-maps"
    webcommon.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # Past every old limit but the one WorldEd has: 25 km x 10 km at a metre a
        # tile, 25,000 tiles a side and 250 million tiles. (A map past 268
        # million is refused: see check_worlded_size.)
        huge = {"south": 51.2, "west": -0.6, "north": 51.29, "east": -0.24,
                "metersPerTile": 1, "mapName": "selftest-huge"}
        import knoxlog as _kl
        _mem = _kl.memory_status
        _kl.memory_status = lambda: (2 ** 40, 2 ** 40, 2 ** 40)  # not the host's RAM
        try:
            said = client.post("/api/generate", json=huge)
        finally:
            _kl.memory_status = _mem
        body = (said.get_json() or {}).get("error", "")
        check("got as far as the download" in body,
              f"a map past every old limit but WorldEd's is built, not refused "
              f"({said.status_code}: {body[:60]})")

        for scale, what in ((0, "zero"), (-1, "a negative"), (1e9, "a silly")):
            bad = client.post("/api/generate", json={**huge, "metersPerTile": scale})
            if bad.status_code != 400:
                check(False, f"{what} scale should still be refused")
                break
        else:
            check(True, "but a scale of zero, a negative one or a silly one is not")
    finally:
        knoxapp.osm.fetch_features_tiled = was_fetch
        webcommon.OUTPUT_DIR = was_out

    check(knoxapp.BIG_AREA_KM2 > 0 and knoxapp.BIG_TILES_PER_SIDE > 0
          and knoxapp.BIG_LANDMARK_KM2 > 0,
          "and the numbers behind the warnings are still there to warn with")




def check_repeatable_seeds(check) -> None:
    """Two processes must pick the same floors and trims for one building: the
    seeds were hash() of a string, which Python randomises per process."""
    import subprocess

    code = ("from knoxbuild.tbx import _stable_seed; "
            "print(_stable_seed('Selftest House', 7, 9, 'trim'), "
            "_stable_seed('Selftest House', 12, 7, 9))")
    seen = set()
    for hashseed in ("1", "2", "random"):
        env = {**os.environ, "PYTHONHASHSEED": hashseed}
        got = subprocess.run([sys.executable, "-c", code], env=env,
                             cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             capture_output=True, text=True).stdout.strip()
        seen.add(got)
    check(len(seen) == 1 and "" not in seen,
          "a building's floor and trim seeds are the same in every process")




def check_compile_records(check, work: str) -> None:
    """The compile's record of what it compiled is only kept while it is true."""
    import numpy as np

    import knoxlog
    import knoxstop
    import knoxbuild.repair as repair
    from tools import compile_map as compiler
    from tools import compile_state as cs

    project = Path(work) / "records"
    (project / "lots").mkdir(parents=True)
    (project / "tmx").mkdir()
    (project / "buildings").mkdir()
    Image.fromarray(np.zeros((600, 600, 3), dtype=np.uint8)).save(
        project / "records.bmp", format="BMP")
    (project / "buildings" / "a.tbx").write_text("one")
    cell = '<cell x="{x}" y="{y}" map="">\n <lot x="1" y="1" level="0" width="2" height="2" map="buildings/a.tbx"/>\n</cell>\n'
    (project / "records.pzw").write_text(
        '<world version="1.0" width="2" height="2">\n<worldOrigin origin="70,0"/>\n'
        '<bmp path="records.bmp" x="0" y="0" width="2" height="2"/>\n'
        + "".join(cell.format(x=x, y=y) for x in range(2) for y in range(2))
        + "</world>", encoding="utf-8")
    exe = project / "PZWorldEd_cli"
    exe.write_text("", encoding="utf-8")

    ran: list = []
    explode = [False]

    class Done:
        returncode, stdout, stderr = 0, "", ""

    def fake(cmd, should_stop, started):
        arg = [a for a in cmd if a.startswith("--cells=")][0]
        box = tuple(int(v) for v in arg[len("--cells="):].split(","))
        ran.append(box)
        if explode[0]:
            raise knoxstop.Stopped("the compile")
        cells = {(x, y) for x in range(box[0], box[2] + 1) for y in range(box[1], box[3] + 1)}
        for lx, ly in cs.lot_files_of(cells, (70, 0)):
            (project / "lots" / f"{lx}_{ly}.lotheader").write_text("new")
        return Done()

    keep = {n: getattr(compiler, n) for n in ("_run_batch",)}
    keep_saved, keep_repair = knoxlog.save_tool_output, repair.repair_project
    compiler._run_batch = fake
    knoxlog.save_tool_output = lambda *a, **k: None
    repair.repair_project = lambda pzw: {"changed": 0, "moved": 0, "dropped": []}
    try:
        compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1)
        check(cs.load(project) is not None and len(ran) == 4,
              "a compile that finishes leaves a record, having run every batch")

        ran.clear()
        compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1)
        check(not ran, "and with nothing changed the next one starts no batch at all")

        (project / "lots" / "84_2.lotheader").write_text("old")
        compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1,
                             only_cells=[[0, 0, 0, 0]], fresh=True)
        check((project / "lots" / "84_2.lotheader").read_text() == "old",
              "starting from scratch does not apply to a retry of just some cells")

        (project / "buildings" / "a.tbx").write_text("two")
        ran.clear()
        explode[0] = True
        try:
            compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1)
        except knoxstop.Stopped:
            pass
        check(ran and cs.load(project) is None,
              "a compile that stops part way leaves no record of the lots it half changed")
        explode[0] = False
        compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1)
        check(cs.load(project) is not None, "and the next one that finishes writes it again")
    finally:
        compiler._run_batch = keep["_run_batch"]
        knoxlog.save_tool_output = keep_saved
        repair.repair_project = keep_repair




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
        try:
            knoxlog.memory_status = lambda: (8 * 2 ** 30, 4 * 2 ** 30, 2 ** 40)
            r = client.post("/api/generate", json={"south": 10.0, "west": 10.0,
                                                   "north": 10.1, "east": 10.1, "mapName": "x"})
            check(r.status_code == 400 and "cannot be made here" in r.get_json()["error"],
                  f"a map bigger than the PC's whole memory is refused ({r.status_code} {r.get_json()})")
        finally:
            knoxlog.memory_status = was_mem
    finally:
        knoxapp.osm.fetch_features_tiled = was_fetch
        webcommon.OUTPUT_DIR = was_out




def check_osm_parse_tolerant(check) -> None:
    """One bad element in an Overpass answer is skipped, not the end of the tile."""
    from generator import osm

    pt = {"lat": 1.0, "lon": 2.0}
    cases = {
        "a null point in a way": {"elements": [{"type": "way", "id": 1, "geometry": [pt, None, pt]}]},
        "a way with null geometry": {"elements": [{"type": "way", "id": 1, "geometry": None}]},
        "a null point in a relation": {"elements": [{"type": "relation", "id": 2, "members": [
            {"role": "outer", "geometry": [pt, None, {"lat": 1, "lon": 3}, pt]}]}]},
        "a point with no latitude": {"elements": [{"type": "way", "id": 1, "geometry": [{"lon": 2.0}]}]},
        "an element with no id": {"elements": [{"type": "way", "geometry": [pt, pt]}]},
        "null members": {"elements": [{"type": "relation", "id": 2, "members": None}]},
        "null elements": {"elements": None},
        "an answer that is not an object": [],
    }
    failed = []
    for what, payload in cases.items():
        try:
            osm._parse(payload)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{what}: {type(exc).__name__}")
    check(not failed, "an Overpass answer with nulls and gaps in it is still read"
                      + (f" (failed: {failed})" if failed else ""))
    good = osm._parse({"elements": [{"type": "way", "id": 1, "geometry": [pt, None, {"lat": 3, "lon": 4}]},
                                    "junk", {"type": "way", "id": 2, "geometry": [pt, pt]}]})
    check(len(good) == 2 and len(good[0].geometry) == 2,
          "and what is there is kept: the good points of a way, and the elements around it")




def check_windows_open(check) -> None:
    """The windows on a house are ones the game lets you open.

    The table of locked window sprites is read off the game's own tile
    definitions, so it can go stale when the game changes. Where this PC has
    the game, the table is checked against it; where it has not, only the
    styles are checked, which is what CI can see.
    """
    import re as _re

    from knoxbuild import catalog as _C
    from knoxbuild.buildtiles import LOCKED_WINDOWS, window_locked

    def west(style):
        return (style.get("window") or {}).get("tiles", {}).get("West", "")

    shut = [s["name"] for s in _C.HOUSE_STYLES if window_locked(west(s))]
    check(not shut, f"every house style has windows that open ({shut or 'all 14'})")
    public = [k for k in ("civic", "medical", "school")
              if window_locked(west(_C.SPECIAL_STYLES[k]))]
    check(not public, f"so does every building people walk into ({public or 'all of them'})")

    import knoxpaths
    media = knoxpaths.pz_media_dir()
    path = os.path.join(str(media), "newtiledefinitions.tiles.txt") if media else ""
    if not path or not os.path.exists(path):
        print("  --    the game's own tile definitions are not on this PC, "
              "so the locked-window table is taken as read")
        return
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    locked = {}
    for block in _re.findall(r"tileset\s*\{(.*?)\n\}", text, _re.S):
        sheet = _re.search(r"file = (\S+)", block)
        if not sheet or sheet.group(1) not in LOCKED_WINDOWS:
            continue
        for tile in _re.finditer(r"//\s*(\S+)\n\s*tile\s*\{(.*?)\n    \}",
                                 block, _re.S):
            if "WindowLocked" in tile.group(2):
                locked.setdefault(sheet.group(1), set()).add(
                    int(tile.group(1).rsplit("_", 1)[1]))
    wrong = []
    for sheet, spans in LOCKED_WINDOWS.items():
        ours = {n for low, high in spans for n in range(low, high + 1)}
        theirs = locked.get(sheet, set())
        if ours != theirs:
            wrong.append(f"{sheet}: {sorted(ours ^ theirs)[:8]}")
    check(not wrong, f"the locked-window table matches this copy of the game "
                     f"({'; '.join(wrong) if wrong else 'all four sheets'})")




def check_trees_are_trees(check) -> None:
    """Every tree the rules place is one the game knows is a tree.

    A species sheet holds 24 pictures and Build 42 defines the first eight; it
    is the definition that carries `tree = 1..8`, the property that makes the
    tile a tree rather than a picture of one. Rules.txt asking for an index
    past that is the quietest failure KnoxMap has had - the picture draws, so
    nothing complains, and the wood is scenery - which is what this looks for.
    Where this PC has no game, only the rules are checked.
    """
    import re as _re

    import knoxpaths
    from knoxbuild.rules import parse_rules

    tools = knoxpaths.mapping_tools_dir()
    path = os.path.join(str(tools), "config", "Rules.txt") if tools else ""
    if not path or not os.path.exists(path):
        print("  --    the map tools are not on this PC, so the tree rules "
              "are taken as read")
        return
    with open(path, encoding="utf-8", errors="replace") as f:
        rules = parse_rules(f.read())
    named = {tile for rule in rules.rules for entry in rule.entries
             for tile in rules.aliases.get(entry, [entry])
             if tile.startswith("e_") and "grass" not in tile}
    check(any("JUMBO" in t for t in named),
          f"the rules place big trees ({sum('JUMBO' in t for t in named)} of "
          f"{len(named)} tree tiles)")

    media = knoxpaths.pz_media_dir()
    if not media or not os.path.isdir(str(media)):
        print("  --    the game is not on this PC, so the tree tiles are "
              "taken as read")
        return
    sizes: dict = {}
    for name in sorted(os.listdir(str(media))):
        if not name.endswith(".tiles.txt"):
            continue
        with open(os.path.join(str(media), name), encoding="utf-8",
                  errors="replace") as f:
            text = f.read()
        for tile in _re.finditer(r"//\s*(\S+)\n\s*tile\s*\n?\s*\{(.*?)\n    \}",
                                 text, _re.S):
            tree = _re.search(r"tree = (\d+)", tile.group(2))
            if tree:
                sizes[tile.group(1)] = int(tree.group(1))
    scenery = sorted(t for t in named if t not in sizes)
    check(not scenery, f"every tree the rules place is a tree the game grows "
                       f"({len(named) - len(scenery)} of {len(named)}"
                       + (f"; scenery: {', '.join(scenery[:4])}" if scenery else "") + ")")
    spread = {sizes[t] for t in named if t in sizes}
    check(len(spread) >= 6, f"and they come in every size the game has "
                            f"({sorted(spread)})")




def check_shared_buildings(check, work: str) -> None:
    """A building goes out as one file and comes back as the same building.

    Somebody builds a house, presses Share and sends the file; anybody with
    KnoxMap can take it in, and tools/add_shared_building.py can put it into
    the library that ships with it (knoxbuild/share.py). Checked here because
    what arrives that way came from a stranger over a chat program.
    """
    import json as _json

    from knoxbuild import designer as D
    from knoxbuild import presets as P
    from knoxbuild import share as S

    tbx = ('<building version="4" width="12" height="10"><room name="hall"/>'
           '<floor></floor><floor></floor></building>')
    home = os.path.join(work, "shared_home")
    sent = S.wrap("Station House", tbx, D.clean(
        {"width": 12, "height": 10, "storeys": 1,
         "rooms": [{"level": 0, "x": 0, "y": 0, "w": 12, "h": 10,
                    "kind": "hall"}]}), kind="police", author="Somebody")
    came, problem = S.read(_json.loads(_json.dumps(sent)))
    check(came is not None and not problem,
          f"a shared building survives being written out and read back ({problem})")
    if came:
        S.install(home, came)
        listed = P.library(home)
        check([p["name"] for p in listed] == ["Station House"]
              and listed[0]["kind"] == "police" and listed[0]["editable"]
              and P.read(home, "Station House") == tbx,
              "and lands whole: the .tbx as it was sent, its kind and its drawing")

    # What a stranger's file may not do.
    bomb = '<!DOCTYPE a [<!ENTITY b "bb">]>' + tbx
    refused = {what: S.read(data)[1] for what, data in (
        ("not ours", {"format": "something-else"}),
        ("a version we do not read", {**sent, "version": 99}),
        ("no building in it", {**sent, "tbx": "hello"}),
        ("an XML bomb", {**sent, "tbx": bomb}),
        ("a building the size of a county",
         {**sent, "tbx": tbx.replace('width="12"', f'width="{S.MAX_SIDE + 1}"')}),
    )}
    taken = [what for what, problem in refused.items() if not problem]
    check(not taken, f"and a file that is none of those is refused "
                     f"({', '.join(taken) if taken else 'all five'})")

    # The library that ships with KnoxMap: every building listed has its file,
    # and every file is listed, so a half-committed one is caught here.
    import knoxpaths
    folder = P.library_folder(knoxpaths.BASE_DIR)
    on_disk = {entry["name"] for entry in P._in_folder(folder)}
    recorded = set(P.shipped(knoxpaths.BASE_DIR))
    check(on_disk == recorded,
          f"the library that ships with KnoxMap matches its manifest "
          f"({len(on_disk)} buildings"
          + (f"; odd ones out: {sorted(on_disk ^ recorded)[:4]}"
             if on_disk != recorded else "") + ")")




def check_osm_cache(check, work: str) -> None:
    """A cached download that is damaged is a miss, and a save cannot leave half a file."""
    import gzip
    import json as _json

    from generator import osm

    path = os.path.join(work, "osm_cache", "area.json.gz")
    bbox = (1.0, 2.0, 3.0, 4.0)
    feats = [osm.OSMFeature(i, "way", {"building": "yes"}, [(1, 2), (2, 3), (3, 4)])
             for i in range(500)]
    osm.save_cache(path, bbox, feats)
    check(len(osm.load_cache(path, bbox)) == 500 and not os.path.exists(path + ".part"),
          "a saved download comes back whole, with no half-written file beside it")
    whole = open(path, "rb").read()
    good_header = {"filters": osm.FILTERS_VERSION, "bbox": list(bbox)}
    damaged = {
        "cut short by a crash": whole[:len(whole) // 2],
        "not a gzip file at all": b"nope",
        "empty": b"",
        "a list rather than an object": gzip.compress(b"[1, 2]"),
        "an entry with a field missing": gzip.compress(_json.dumps(
            {**good_header, "features": [{"kind": "way"}]}).encode()),
        "a feature that is not an object": gzip.compress(_json.dumps(
            {**good_header, "features": ["x"]}).encode()),
    }
    worked = []
    for what, data in damaged.items():
        with open(path, "wb") as fh:
            fh.write(data)
        try:
            if osm.load_cache(path, bbox) is not None:
                worked.append(what)
        except Exception as exc:  # noqa: BLE001
            worked.append(f"{what} raised {type(exc).__name__}")
    check(not worked, "a damaged cache file is read as 'not cached', never as an error"
                      + (f" (not so: {worked})" if worked else ""))

    class Boom(Exception):
        pass

    good_before = os.path.join(work, "osm_cache", "keep.json.gz")
    osm.save_cache(good_before, bbox, feats[:3])
    was_dump = osm.json.dump
    osm.json.dump = lambda *a, **k: (_ for _ in ()).throw(Boom())
    try:
        osm.save_cache(good_before, bbox, feats)
    except Boom:
        pass
    finally:
        osm.json.dump = was_dump
    check(len(osm.load_cache(good_before, bbox)) == 3 and not os.path.exists(good_before + ".part"),
          "a save that fails part way leaves the earlier file as it was")




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




def check_install_clears(check, work: str) -> None:
    """Installing over an old copy that cannot be removed stops, rather than mixing the two."""
    import shutil as _shutil

    from tools import make_map_mod

    old = Path(work) / "old_install"
    (old / "sub").mkdir(parents=True)
    (old / "sub" / "1_1.lotheader").write_text("old")
    make_map_mod._clear_folder(str(old))
    check(not old.exists(), "an old installed copy is removed before the new one goes in")

    stuck = Path(work) / "stuck_install"
    stuck.mkdir()
    (stuck / "5_5.lotheader").write_text("old")
    was = _shutil.rmtree
    make_map_mod.shutil.rmtree = lambda *a, **k: None       # a folder the game holds open
    try:
        try:
            make_map_mod._clear_folder(str(stuck), tries=1)
            said = ""
        except RuntimeError as exc:
            said = str(exc)
    finally:
        make_map_mod.shutil.rmtree = was
    check("could not be removed" in said and "Close Project Zomboid" in said and stuck.exists(),
          "and one that cannot be removed is reported, with what to do about it")




def check_odd_tags(check) -> None:
    """Heights and storeys come from free text on OpenStreetMap; none of it may stop a build."""
    from knoxbuild.build import levels_from_tags
    from knoxbuild.settings import Settings

    settings = Settings()
    worst = ["inf", "-inf", "Infinity", "nan", "1e999", "-1e999", "1e308", "9" * 400, "", " ",
             "-3", "0", "3;4", "3,5", "3 floors", "x", "40'", "12 ft", "0x10", "1_0"]
    bad = []
    for key in ("building:levels", "levels", "height", "building:height", "est_height"):
        for value in worst:
            try:
                got = levels_from_tags({key: value}, settings)
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{key}={value!r}: {type(exc).__name__}")
                continue
            if got is not None and not 1 <= got <= settings.max_levels:
                bad.append(f"{key}={value!r}: {got} storeys")
    for key in ("roof:levels", "min_height"):
        for value in worst:
            for base in ({"building:levels": "2"}, {"height": "20"}):
                try:
                    levels_from_tags({**base, key: value}, settings)
                except Exception as exc:  # noqa: BLE001
                    bad.append(f"{key}={value!r}: {type(exc).__name__}")
    from generator import renderer, structures
    from generator.osm import OSMFeature

    for value in worst:
        try:
            structures._storeys({"height": value}, 2)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"structures height={value!r}: {type(exc).__name__}")
        for key in ("width", "est_width", "lanes"):
            way = OSMFeature(1, "way", {"highway": "residential", key: value}, [(1, 2), (1, 3)])
            try:
                got = renderer._way_width_m(way, "road_minor")
            except Exception as exc:  # noqa: BLE001
                bad.append(f"road {key}={value!r}: {type(exc).__name__}")
                continue
            if value in ("nan", "inf", "-inf", "Infinity") and key != "lanes" \
                    and got != renderer._way_width_m(OSMFeature(1, "way", {"highway": "residential"}, []), "road_minor"):
                bad.append(f"road {key}={value!r} made a {got} m road")
    proj = renderer.Projector.build(SOUTH, WEST, NORTH, EAST, 1.0)
    for value in worst:
        try:
            structures.level_of({"layer": value, "highway": "residential"})
        except Exception as exc:  # noqa: BLE001
            bad.append(f"layer={value!r}: {type(exc).__name__}")
        try:
            renderer._places([OSMFeature(1, "node", {"place": "town", "population": value},
                                         [(SOUTH, WEST)])], proj)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"population={value!r}: {type(exc).__name__}")
    check(not bad, "no height or storey tag, however odd, raises" + (f" ({bad[:4]})" if bad else ""))
    check(levels_from_tags({"building:levels": "3;4"}, settings) == 3
          and levels_from_tags({"height": "12"}, settings) == 4
          and levels_from_tags({"building:levels": "inf", "height": "12"}, settings) == 4,
          "and a tag that is not a number falls through to the next one that is")




def check_degenerate_footprints(check) -> None:
    """A footprint with too few points is too small, not an error."""
    import numpy as np

    from knoxbuild.footprint import place

    occupied = np.zeros((40, 40), dtype=bool)
    said = []
    for points in ([], [(5, 5)], [(5, 5), (9, 9)], [(5, 5), (5, 5), (5, 5)]):
        try:
            said.append(place(points, occupied, min_side=3)[1])
        except Exception as exc:  # noqa: BLE001
            said.append(type(exc).__name__)
    check(said == ["small"] * 4, f"a footprint of no, one, two or repeated points is 'small' ({said})")




def check_car_park_stalls(check) -> None:
    """Walking only the part of a car park that is on the map tries the same stalls."""
    import random as _random

    from knoxbuild.build import CAR_PARK_LANE, STALL_H, STALL_W, car_park_stalls

    def original(bounds, w, h):
        x0, y0, x1, y1 = bounds
        across = (x1 - x0) >= (y1 - y0)
        sw, sh = (STALL_W, STALL_H) if across else (STALL_H, STALL_W)
        for a in range(0, (y1 - y0 if across else x1 - x0), CAR_PARK_LANE):
            for row in (0, STALL_H):
                for b in range(0, (x1 - x0 if across else y1 - y0), STALL_W):
                    x, y = (x0 + b, y0 + a + row) if across else (x0 + a + row, y0 + b)
                    if not (0 <= x and x + sw <= w and 0 <= y and y + sh <= h):
                        continue
                    yield x, y, sw, sh

    rng = _random.Random(5)
    differ = 0
    for _ in range(3000):
        w, h = rng.randint(8, 400), rng.randint(8, 400)
        x0, y0 = rng.randint(-300, 450), rng.randint(-300, 450)
        bounds = (x0, y0, x0 + rng.randint(1, 500), y0 + rng.randint(1, 500))
        if list(original(bounds, w, h)) != list(car_park_stalls(bounds, w, h)):
            differ += 1
    check(differ == 0, f"a car park is tried at the same stalls, in the same order, as before ({differ} of 3000 differ)")
    import time as _time
    t0 = _time.time()
    n = sum(1 for _ in car_park_stalls((-10 ** 6, -10 ** 6, 10 ** 6, 10 ** 6), 300, 300))
    check(_time.time() - t0 < 2 and n > 0,
          f"and one the size of a continent is walked in no time ({_time.time() - t0:.2f} s)")




def check_prop_lattice(check) -> None:
    """Props are laid on the part of a polygon that is on the map, on the same lattice."""
    import random as _random
    import time as _time

    from knoxbuild.props import lattice_on_map

    rng = _random.Random(9)
    differ = 0
    for _ in range(5000):
        step = rng.randint(1, 40)
        first = rng.randint(-900, 600)
        stop = first + rng.randint(0, 1200)
        limit = rng.randint(1, 700)
        naive = [v for v in range(first, stop, step) if 0 <= v < limit]
        if list(lattice_on_map(first, stop, step, limit)) != naive:
            differ += 1
    check(differ == 0, f"the lattice of a polygon is walked only where it is on the map, "
                       f"at the same points ({differ} of 5000 differ)")
    t0 = _time.time()
    n = len(lattice_on_map(-10 ** 9, 10 ** 9, 3, 500))
    check(_time.time() - t0 < 1 and n == len(range((-10 ** 9) % 3, 500, 3)),
          f"and a polygon a thousand kilometres across costs nothing ({n} points)")




def check_ground_shares(check, work: str) -> None:
    """The street and water shares of the ground come out as they did, read a strip at a time."""
    import numpy as np

    from generator import pz_colors as _C
    from knoxbuild import bitmaps, population

    rng = np.random.default_rng(3)
    palette = np.array([_C.WATER, _C.MEDIUM_ASPHALT, _C.PALE_CONCRETE, _C.DARK_GRASS,
                        _C.PAVING, _C.DARK_POTHOLE], dtype=np.uint8)
    chunk = population.CHUNK
    gw, gh = 9, 7
    ground = palette[rng.integers(0, len(palette), (gh * chunk + 3, gw * chunk + 5))]
    path = os.path.join(work, "ground_shares.bmp")
    Image.fromarray(ground).save(path, format="BMP")

    def whole(path: str):
        """The way it was done: the whole picture converted, then cut."""
        paved = np.zeros((gh, gw))
        water = np.zeros((gh, gw))
        with Image.open(path) as img:
            full = np.asarray(img.convert("RGB"))
        for y in range(gh):
            for x in range(gw):
                cell = full[y * chunk:(y + 1) * chunk, x * chunk:(x + 1) * chunk]
                paved[y, x] = np.logical_or.reduce(
                    [np.all(cell == c, axis=2) for c in population.STREET_COLOURS]).mean()
                water[y, x] = np.all(cell == np.array(_C.WATER), axis=2).mean()
        return paved, water

    was = population.GROUND_STRIP_CHUNKS
    population.GROUND_STRIP_CHUNKS = 3          # several strips, the last one short
    try:
        got = population._ground_shares(path, gw, gh)
    finally:
        population.GROUND_STRIP_CHUNKS = was
    expected = whole(path)
    check(np.allclose(got[0], expected[0]) and np.allclose(got[1], expected[1]),
          "the share of each chunk that is street or water is the same read a strip at a time")
    rows = bitmaps.read_rgb_rows(path, 10, 40, 50)
    check(np.array_equal(rows, ground[10:40, :50]),
          "and a strip of rows read from a bitmap is those rows of the picture")




def check_street_angle(check) -> None:
    """The angle a map is turned to is the grid on the map, found to a fraction of a degree."""
    from generator import renderer

    south, west, north, east = 40.0, 20.0, 40.02, 20.026
    proj = renderer.Projector.build(south, west, north, east, 1.0)
    ids = iter(range(1, 10 ** 6))

    def street(p0, p1):
        return renderer.OSMFeature(next(ids), "way", {"highway": "residential"},
                                   [proj.to_latlon(*p0), proj.to_latlon(*p1)])

    def clip(p0, p1, x0, y0, x1, y1):
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        t0, t1 = 0.0, 1.0
        for p, q in ((-dx, p0[0] - x0), (dx, x1 - p0[0]), (-dy, p0[1] - y0), (dy, y1 - p0[1])):
            if p == 0:
                if q < 0:
                    return None
            else:
                t = q / p
                t0, t1 = (max(t0, t), t1) if p < 0 else (t0, min(t1, t))
        return None if t0 >= t1 else ((p0[0] + t0 * dx, p0[1] + t0 * dy), (p0[0] + t1 * dx, p0[1] + t1 * dy))

    def grid(angle, x0, y0, x1, y1, spacing=60):
        a = math.radians(angle)
        u, v = (math.cos(a), -math.sin(a)), (math.sin(a), math.cos(a))
        cx, cy, reach = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0)
        out = []
        for k in range(-int(reach / spacing), int(reach / spacing) + 1):
            for d, e in ((u, v), (v, u)):
                o = (cx + e[0] * k * spacing, cy + e[1] * k * spacing)
                seg = clip((o[0] - d[0] * reach, o[1] - d[1] * reach),
                           (o[0] + d[0] * reach, o[1] + d[1] * reach), x0, y0, x1, y1)
                if seg:
                    out.append(street(*seg))
        return out

    def turned(feats):
        return renderer.dominant_road_angle(feats, south, west, north, east)

    w, h = proj.width, proj.height
    errs = []
    for ang in (3, 22.5, 44, -30):
        got, strength = turned(grid(ang, 0, 0, w, h))
        errs.append(abs(got - ang) < 0.5 and strength > 0.9)
    check(all(errs), "a street grid is found to within half a degree, whichever way it runs")
    two, _s = turned(grid(30, 0, 0, w * 0.65, h) + grid(0, w * 0.7, 0, w, h))
    check(abs(two - 30) < 0.5, "and where two districts meet, the one with more street decides")
    inside = grid(20, 0, 0, w, h)
    both, _s = turned(inside + grid(0, -3000, -3000, -50, h + 3000))
    check(abs(both - 20) < 0.5,
          "a bigger grid in the margin beyond the map does not turn the map to its own angle")
    from generator import osm as _osm
    check(len(_osm._points([{"lat": float("nan"), "lon": 20.0}, {"lat": 1.0, "lon": 2.0}])) == 1,
          "and a point with no real coordinates is dropped on the way in")
    check(turned([]) == (0.0, 0.0), "a map with no streets has no angle")




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




def check_portable_presets(check, work: str) -> None:
    """Portable presets survive export/import and refuse unusable map geometry."""
    import app as knoxapp
    import json as _json
    import os as _os
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




def check_health(check) -> None:
    """The health check answers without the network, and says what the PC holds."""
    import app as knoxapp

    data = knoxapp.app.test_client().get("/api/health").get_json()
    res = data.get("resources", {})
    check(isinstance(data.get("checks"), list) and "compileWorkers" in res
          and res["compileWorkers"] >= 1 and "overpass" not in data,
          "the health check lists the setup and the PC's room, and leaves the network alone by default")




def check_worlded_size(check) -> None:
    """A map WorldEd cannot compile is refused before it is made, and told how to fit."""
    import app as knoxapp
    from tools.compile_map import WORLDED_MAX_PIXELS, bitmap_pixels, scale_that_fits

    box = {"south": 34.84560, "west": -120.76103, "north": 35.18564, "east": -120.38612}
    r = knoxapp.app.test_client().post("/api/generate", json={**box, "metersPerTile": 2})
    said = (r.get_json() or {}).get("error", "")
    check(r.status_code == 400 and "WorldEd cannot compile" in said and "At 3 m a tile" in said,
          f"a 345 million tile map is refused, with the scale that fits ({said[:60]!r})")
    check(bitmap_pixels(13800, 18600) <= WORLDED_MAX_PIXELS < bitmap_pixels(16500, 16500)
          and bitmap_pixels(1, 1) == 300 * 300
          and scale_that_fits(17700, 19500, 2.0) == 3 and scale_that_fits(10 ** 6, 10 ** 6, 100.0) is None,
          "the size limit sits between a map that compiled and one that did not")




def check_other_websites(check) -> None:
    """A page on another website cannot make KnoxMap do things by posting to it."""
    import app as knoxapp

    client = knoxapp.app.test_client()

    def post(**headers):
        # /api/stop with no map name answers 400 and does nothing: a refusal is 403.
        return client.post("/api/stop", json={}, headers=headers).status_code

    check(post() == 400 and post(Origin="http://127.0.0.1:5000") == 400
          and post(Origin="http://localhost:5000") == 400 and post(Origin="http://[::1]:5000") == 400,
          "posts from KnoxMap's own page, and from tools with no Origin, are answered")
    check(post(Origin="http://evil.example") == 403 and post(Origin="null") == 403
          and post(Origin="http://127.0.0.1.evil.example") == 403,
          "posts from other websites are refused")
    check(post(**{"Sec-Fetch-Site": "cross-site"}) == 403
          and client.get("/api/health", headers={"Origin": "http://evil.example"}).status_code == 200,
          "and so is a cross-site post that sends no Origin, while reading stays open")




def check_overpass_setting(check, work: str) -> None:
    """The map data servers can be named in the window and are used at once."""
    from pathlib import Path

    import app as knoxapp
    import knoxpaths
    from generator import osm

    was_path, was_urls = knoxpaths.CONFIG_PATH, list(osm.OVERPASS_ENDPOINTS)
    knoxpaths.CONFIG_PATH = Path(work) / "config_overpass.json"
    try:
        client = knoxapp.app.test_client()
        mine = "http://localhost:12345/api/interpreter"
        r = client.post("/api/overpass", json={"endpoints": f"  {mine}\n{mine} "})
        d = r.get_json()
        check(r.status_code == 200 and d["endpoints"] == [mine] and d["using"] == [mine]
              and osm.OVERPASS_ENDPOINTS == [mine],
              "a server of your own is saved and used at once (duplicates and spaces dropped)")
        check(client.get("/api/overpass").get_json()["endpoints"] == [mine],
              "and read back from the config")
        for bad in ("ftp://x/y", "not a url", {"a": 1}, ["javascript:alert(1)"]):
            check(client.post("/api/overpass", json={"endpoints": bad}).status_code == 400,
                  f"{str(bad)[:24]!r} is refused")
        check(client.post("/api/overpass", json=[1]).get_json()["using"] == [mine]
              and osm.OVERPASS_ENDPOINTS == [mine],
              "an invalid body does not change the selected servers")
        check(client.post("/api/overpass", json={"endpoints": []}).get_json()["using"]
              == list(osm._DEFAULT_ENDPOINTS),
              "an explicitly empty server list goes back to the public servers")

        # The status list: one row per server, from a stand-in probe.
        was_probe = osm._probe
        osm._probe = lambda endpoint, lat, lon: "osm.ch" not in endpoint
        try:
            rows = client.get("/api/overpass/status").get_json()["servers"]
        finally:
            osm._probe = was_probe
        check(len(rows) == len(osm.OVERPASS_ENDPOINTS)
              and any(not r["ok"] and r["regional"] for r in rows)
              and any(r["ok"] and not r["regional"] for r in rows),
              "the server test lists every server, says which answer, and marks the regional ones")

        # A server of your own in Docker, with Docker stood in for.
        from web import geo
        was_which, was_docker = geo.shutil.which, geo._docker
        calls = []

        class Done:
            def __init__(self, out="", code=0):
                self.stdout, self.stderr, self.returncode = out, "", code

        def fake_docker(*args, timeout=30):
            calls.append(args)
            return Done("" if args[0] == "ps" else "id")
        try:
            geo.shutil.which = lambda name: None
            check(client.get("/api/local-overpass").get_json()["docker"] is False
                  and client.post("/api/local-overpass", json={"action": "start"}).status_code == 400,
                  "without Docker the local server says so and starts nothing")
            geo.shutil.which, geo._docker = (lambda name: "docker"), fake_docker
            check(client.post("/api/local-overpass", json={
                "action": "start", "extract": "https://evil.example/x.osm.pbf"}).status_code == 400
                and not any(c[0] == "run" for c in calls),
                "only a Geofabrik extract is accepted, and nothing is run for any other")
            base = "https://download.geofabrik.de/north-america/us/tennessee-latest.osm"
            legacy = client.post("/api/local-overpass", json={
                "action": "start", "extract": f"{base}.bz2"})
            check(legacy.status_code == 400 and ".osm.pbf" in legacy.get_json()["error"]
                  and not any(c[0] == "run" for c in calls),
                  "a legacy BZ2 URL is rejected with guidance to use PBF")
            good = f"{base}.pbf"
            response = client.post("/api/local-overpass", json={"action": "start", "extract": good})
            run = next((c for c in calls if c[0] == "run"), ())
            check(response.status_code == 200 and f"OVERPASS_PLANET_URL={good}" in run
                  and "127.0.0.1:12345:80" in run,
                  "a Geofabrik PBF starts a localhost-only container")
            check(f"OVERPASS_PLANET_PREPROCESS={geo.LOCAL_PBF_PREPROCESS}" in run,
                  "the PBF import gets the conversion hook")
            d = client.post("/api/local-overpass", json={"action": "use"}).get_json()
            check(osm.OVERPASS_ENDPOINTS[0] == geo.LOCAL_URL
                  and len(osm.OVERPASS_ENDPOINTS) == len(osm._DEFAULT_ENDPOINTS) + 1,
                  "using it puts it first and keeps the public servers behind it")
        finally:
            geo.shutil.which, geo._docker = was_which, was_docker
    finally:
        knoxpaths.CONFIG_PATH = was_path
        osm.set_endpoints(was_urls if was_urls != list(osm._DEFAULT_ENDPOINTS) else None)




def check_workshop(check, work: str) -> None:
    """The pre-upload check finds a missing credit, a bad id and a missing picture."""
    import shutil

    from tools import workshop_check as wc

    root = os.path.join(work, "wmod", "My_Map")
    shutil.rmtree(os.path.dirname(root), ignore_errors=True)
    for where in ("", "common", "42"):
        os.makedirs(os.path.join(root, where), exist_ok=True)
        with open(os.path.join(root, where, "mod.info"), "w", encoding="utf-8") as f:
            f.write("name=My Map\nid=My_Map\ndescription=A map. Map data (c) OpenStreetMap contributors (ODbL).\n")
    maps = os.path.join(root, "common", "media", "maps", "My_Map")
    os.makedirs(maps)
    open(os.path.join(maps, "0_0.lotheader"), "wb").close()
    open(os.path.join(maps, "map.info"), "w").close()
    with open(os.path.join(root, "ATTRIBUTION.txt"), "w", encoding="utf-8") as f:
        from knoxbuild import credits
        f.write("Map data (c) OpenStreetMap contributors, available under the Open Database "
                "License (ODbL)\n" + credits.plain())

    def levels():
        res = wc.check(root)
        return {r["level"] for r in res}, wc.summary(res)

    lv, s = levels()
    check("bad" not in lv and s["ready"] and s["warn"] == 1,
          "a complete mod is ready, with only the missing preview picture to warn about")
    Image.new("RGB", (300, 300)).save(os.path.join(root, "preview.png"))
    lv, s = levels()
    check(lv == {"ok"} and s["warn"] == 0, "and with a square preview it has nothing to say")
    Image.new("RGB", (300, 200)).save(os.path.join(root, "preview.png"))
    check(levels()[1]["warn"] == 1, "a preview that is not square is warned about")
    with open(os.path.join(root, "preview.png"), "wb") as f:
        f.write(b"not a png")
    check(not levels()[1]["ready"], "a preview that is not a PNG stops it")
    os.remove(os.path.join(root, "preview.png"))
    with open(os.path.join(root, "ATTRIBUTION.txt"), "w", encoding="utf-8") as f:
        f.write("made with KnoxMap")
    check(not levels()[1]["ready"], "an attribution without the OpenStreetMap credit stops it")
    with open(os.path.join(root, "ATTRIBUTION.txt"), "w", encoding="utf-8") as f:
        f.write("Map data (c) OpenStreetMap contributors, available under the Open Database\nLicense (ODbL)")
    check("bad" not in levels()[0], "the credit passes when the file wraps it over two lines")
    os.remove(os.path.join(root, "ATTRIBUTION.txt"))
    check(not levels()[1]["ready"], "no attribution file stops it")
    with open(os.path.join(root, "mod.info"), "w", encoding="utf-8") as f:
        f.write("name=x\nid=bad id!\ndescription=nothing\n")
    check(not levels()[1]["ready"], "a mod id with odd characters and a copy that differs stop it")
    check(not wc.summary(wc.check(os.path.join(work, "nowhere")))["ready"],
          "a mod that is not installed is not ready")




def check_compile_state(check, work: str) -> None:
    """Working out which cells of a compiled map are out of date."""
    import numpy as np

    from knoxbuild import bitmaps
    from tools import compile_state as cs

    rng = np.random.default_rng(11)
    rgb = rng.integers(0, 256, (130, 205, 3), dtype=np.uint8)
    a_path, b_path = os.path.join(work, "cells_a.bmp"), os.path.join(work, "cells_b.bmp")
    Image.fromarray(rgb).save(a_path, format="BMP")
    changed = rgb.copy()
    changed[75, 160] = 255 - changed[75, 160]            # one pixel, in cell (2, 1)
    Image.fromarray(changed).save(b_path, format="BMP")
    ha, hb = bitmaps.cell_hashes(a_path, 60), bitmaps.cell_hashes(b_path, 60)
    check(len(ha) == 4 * 3 and bitmaps.cell_hashes(a_path, 60) == ha
          and [k for k in ha if ha[k] != hb[k]] == [(2, 1)],
          "one changed pixel changes the fingerprint of its own square and no other")
    grey = rng.integers(0, 256, (70, 90), dtype=np.uint8)
    g_path = os.path.join(work, "cells_g.bmp")
    Image.fromarray(grey, "L").save(g_path, format="BMP")
    check(len(bitmaps.cell_hashes(g_path, 30)) == 3 * 3, "and it reads a grey picture too")
    step3 = bitmaps.read_rgb(a_path, step=3)
    check(np.array_equal(step3, rgb[::3, ::3]), "a smaller picture of a bitmap is every third pixel")

    check(cs.lot_files_of({(0, 0)}, (70, 0)) == {(82, 0), (82, 1), (83, 0), (83, 1)},
          "a cell names the lot files that overlap it")

    def record(terrain_edit=None, content_edit=None) -> dict:
        t = {f"{x},{y}": f"t{x}{y}" for x in range(5) for y in range(5)}
        c = {f"{x},{y}": f"c{x}{y}" for x in range(5) for y in range(5)}
        t.update(terrain_edit or {})
        c.update(content_edit or {})
        return {"version": cs.VERSION, "global": "g", "origin": [70, 0],
                "size": [5, 5], "terrain": t, "content": c}

    base = record()
    check(cs.plan(None, base, True) is None and cs.plan(base, base, False) is None,
          "with no record, or nothing compiled, nothing is trusted")
    check(cs.plan(base, {**base, "global": "other"}, True) is None,
          "and a change to the rules or the compiler redoes everything")
    same = cs.plan(base, record(), True)
    check(same["changed"] == 0 and not same["lots"], "an unchanged map has nothing to redo")
    one = cs.plan(base, record(content_edit={"0,0": "new"}), True)
    check(one["changed"] == 1 and one["lots"] == {(0, 0), (1, 0), (0, 1), (1, 1)}
          and not one["terrain"],
          "a changed building in a corner redoes that cell and its neighbours, not the maps")
    mid = cs.plan(base, record(terrain_edit={"2,2": "new"}), True)
    check(len(mid["terrain"]) == 9 and len(mid["lots"]) == 9,
          "changed ground redoes its map and its neighbours' too")

    project = Path(work) / "statemap"
    (project / "lots").mkdir(parents=True)
    (project / "tmx").mkdir()
    pzw = project / "statemap.pzw"
    cell = '<cell x="{x}" y="{y}" map="C:/m/tmx/statemap_{tx}_{y}.tmx">\n</cell>\n'
    pzw.write_text('<world version="1.0" width="2" height="2">\n'
                   '<worldOrigin origin="70,0"/>\n<bmp path="statemap.bmp" x="0" y="0"/>\n'
                   + "".join(cell.format(x=x, y=y, tx=70 + x)
                             for x in range(2) for y in range(2)) + "</world>",
                   encoding="utf-8")
    for lx in range(82, 86):
        for ly in range(0, 4):
            for name in (f"{lx}_{ly}.lotheader", f"chunkdata_{lx}_{ly}.bin",
                         f"world_{lx}_{ly}.lotpack"):
                (project / "lots" / name).write_text("x")

    def make_maps() -> None:
        for x in range(2):
            for y in range(2):
                (project / "tmx" / f"statemap_{70 + x}_{y}.tmx").write_text("x")

    make_maps()
    # Ground changed somewhere: every map goes, because WorldEd does not make
    # up a partial set (its log said 375 of 384), but only the changed cell's
    # lot files.
    gone = cs.discard(project, {"lots": {(0, 0)}, "terrain": {(0, 0)}}, (70, 0))
    left = pzw.read_text(encoding="utf-8")
    check(gone == {"lots": 12, "tmx": 4}
          and not (project / "lots" / "82_0.lotheader").exists()
          and (project / "lots" / "85_3.lotheader").exists()
          and left.count('map=""') == 4 and ".tmx" not in left
          and not list((project / "tmx").glob("*.tmx")),
          "discarding takes just those cells' lot files, and every map when ground changed")
    make_maps()
    pzw.write_text(left.replace('map=""', 'map="C:/m/tmx/statemap_70_0.tmx"', 1),
                   encoding="utf-8")
    kept = cs.discard(project, {"lots": {(1, 1)}, "terrain": set()}, (70, 0))
    check(kept["tmx"] == 0 and len(list((project / "tmx").glob("*.tmx"))) == 4
          and "statemap_70_0.tmx" in pzw.read_text(encoding="utf-8"),
          "and changes that are not to the ground leave the maps alone")
    for lx in range(82, 86):
        for ly in range(0, 4):
            (project / "lots" / f"{lx}_{ly}.lotheader").write_text("x")
    (project / "lots" / "84_1.lotheader").unlink()
    check(cs.batch_needs_work(project, (1, 1, 1, 1), (70, 0), (2, 2))
          and not cs.batch_needs_work(project, (0, 0, 0, 0), (70, 0), (2, 2)),
          "a batch is run only when a lot file it would write is missing")
    cs.wipe(project)
    check(not any((project / "lots").iterdir()) and not any((project / "tmx").iterdir()),
          "starting from scratch empties lots and maps")




def check_big_bitmaps(check, work: str) -> None:
    """A map past Pillow's 179 Mpx bomb guard still opens, and the strip reader
    gives back exactly what Pillow does, at any width (BMP rows are padded)."""
    import numpy as np

    import generator  # noqa: F401 - lifts the pixel limit
    import knoxbuild  # noqa: F401
    from knoxbuild import bitmaps

    # 20000 x 20000 is 400 Mpx, twice the limit where Pillow stops warning and
    # starts refusing; 1-bit keeps the file at 50 MB.
    big = os.path.join(work, "big.bmp")
    Image.new("1", (20000, 20000)).save(big, format="BMP")
    try:
        with Image.open(big) as img:
            check(img.size == (20000, 20000),
                  "a bitmap past Pillow's decompression-bomb limit still opens")
    except Image.DecompressionBombError:
        check(False, "a bitmap past Pillow's decompression-bomb limit still opens")
    os.remove(big)

    rng = np.random.default_rng(5)
    same = True
    for w, h in ((1, 1), (5, 3), (7, 600), (301, 257)):      # widths off a 4-byte row
        rgb = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        path = os.path.join(work, f"rgb_{w}x{h}.bmp")
        Image.fromarray(rgb).save(path, format="BMP")
        same &= np.array_equal(bitmaps.read_rgb(path), rgb)
        crop = (max(1, h // 2), max(1, w // 2))
        same &= np.array_equal(bitmaps.read_rgb(path, crop=crop), rgb[:crop[0], :crop[1]])
        grey = rng.integers(0, 256, (h, w), dtype=np.uint8)
        gpath = os.path.join(work, f"grey_{w}x{h}.bmp")
        Image.fromarray(grey, "L").save(gpath, format="BMP")
        same &= np.array_equal(bitmaps.read_gray(gpath), grey)
        colour = tuple(int(v) for v in rgb[0, 0])
        same &= np.array_equal(bitmaps.same_colour(rgb, colour),
                               np.all(rgb == colour, axis=2))
    check(bool(same), "the strip reader returns the same pixels as Pillow, "
                      "whole or cropped, in colour and grey")




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




def check_install_folder(check, out: str, work: str, client) -> None:
    """Installing into a chosen folder, the space check, and taking a map out
    again - which must never delete a folder that is not a KnoxMap mod."""
    import knoxpaths
    from knoxbuild import mapstate
    from tools import make_map_mod
    from web import common as webcommon

    zroot = Path(work) / "zomboid_choice"
    was_env, was_cfg = os.environ.get("ZOMBOID_DIR"), knoxpaths.CONFIG_PATH
    was_free, was_output = make_map_mod.free_bytes, webcommon.OUTPUT_DIR
    knoxpaths.CONFIG_PATH = Path(work) / "choice_config.json"
    os.environ.pop("ZOMBOID_DIR", None)
    webcommon.OUTPUT_DIR = Path(out).parent
    try:
        r = client.post("/api/zomboid-folder", json={"folder": str(zroot)})
        got = client.get("/api/zomboid-folder").get_json()
        check(r.status_code == 200 and (zroot / "mods").is_dir() and got["chosen"]
              and Path(got["mods"]) == zroot / "mods"
              and knoxpaths.zomboid_user_dir() == zroot,
              "the Zomboid folder chosen in the app is made and used")
        blocker = Path(work) / "not_a_folder"
        blocker.write_text("x")
        r = client.post("/api/zomboid-folder", json={"folder": str(blocker / "sub")})
        check(r.status_code == 400 and knoxpaths.zomboid_user_dir() == zroot,
              "and one that cannot be made is refused, the old choice kept")
        client.post("/api/zomboid-folder", json={"folder": ""})
        check(not client.get("/api/zomboid-folder").get_json()["chosen"],
              "an empty one goes back to the default")
        client.post("/api/zomboid-folder", json={"folder": str(zroot)})

        make_map_mod.free_bytes = lambda path: 1 << 20       # 1 MB free
        r = client.post("/api/install", json={"mapName": "selftest"})
        check(r.status_code == 400 and "Not enough room" in (r.get_json() or {}).get("error", "")
              and not any((zroot / "mods").iterdir()),
              "an install that will not fit is refused before anything is written")
        make_map_mod.free_bytes = was_free

        # The selftest map has no compiled cells to package, so the installed
        # mod is laid down by hand, as package() writes it.
        check(Path(make_map_mod.default_mods_dir()) == zroot / "mods",
              "installs go into the chosen folder")
        mod = zroot / "mods" / "SelftestMod"
        (mod / "common").mkdir(parents=True)
        (mod / "mod.info").write_text(
            "name=Selftest\ndescription=Selftest, generated from real-world map data "
            "with KnoxMap by euclid80tr.\n")
        mapstate.record_install(out, str(mod), "SelftestMod")
        check(mapstate.installed(out) is not None, "an installed map is recorded")
        r = client.post("/api/uninstall", json={"mapName": "selftest"})
        check(r.status_code == 200 and not mod.exists() and mapstate.installed(out) is None
              and (zroot / "mods").is_dir(),
              "uninstalling removes the mod folder and forgets it")
        check(client.post("/api/uninstall", json={"mapName": "selftest"}).status_code == 404,
              "and a map that is not installed has nothing to remove")

        # Update: no title or id sent, so the installed ones are used again.
        from tools import make_map_mod as _mmm
        mod.mkdir(parents=True, exist_ok=True)
        (mod / "mod.info").write_text("name=Kept Title\n", encoding="utf-8")
        mapstate.record_install(out, str(mod), "KeptId", "Kept Title")
        asked = []
        was_package = _mmm.package
        _mmm.package = lambda d, title, mid, **kw: (asked.append((title, mid)) or (str(mod), 1, []))
        try:
            r = client.post("/api/install", json={"mapName": "selftest"})
        finally:
            _mmm.package = was_package
        check(r.status_code == 200 and asked == [("Kept Title", "KeptId")],
              "updating an installed map puts it back under its own title and id")
        mapstate.forget_install(out)
        shutil.rmtree(mod, ignore_errors=True)

        # A record that points at someone else's folder: refused, nothing deleted.
        theirs = zroot / "mods" / "SomeoneElsesMod"
        theirs.mkdir()
        (theirs / "mod.info").write_text("name=Theirs\ndescription=a different mod\n")
        (theirs / "keep.txt").write_text("keep")
        mapstate.record_install(out, str(theirs), "SomeoneElsesMod")
        r = client.post("/api/uninstall", json={"mapName": "selftest"})
        check(r.status_code == 400 and (theirs / "keep.txt").exists(),
              "a folder that is not a KnoxMap mod is left alone, whatever the record says")
        elsewhere = Path(work) / "elsewhere" / "SelftestMod"
        elsewhere.mkdir(parents=True)
        (elsewhere / "mod.info").write_text(
            "description=generated from real-world map data with KnoxMap\n")
        mapstate.record_install(out, str(elsewhere), "SelftestMod")
        r = client.post("/api/uninstall", json={"mapName": "selftest"})
        check(r.status_code == 400 and elsewhere.exists(),
              "and so is a KnoxMap-looking folder that is not inside a mods folder")
    finally:
        make_map_mod.free_bytes = was_free
        webcommon.OUTPUT_DIR = was_output
        knoxpaths.CONFIG_PATH = was_cfg
        if was_env is not None:
            os.environ["ZOMBOID_DIR"] = was_env
        mapstate.forget_install(out)




def check_build_audits(check, out: str) -> None:
    """The things the fixes from the field reports put right, checked on what
    the build just wrote: no glass walls inside, no fence lost to a lamp, no
    roof over open ground, no staircase with a wall across it."""
    from knoxbuild import buildtiles, catalog
    from tools import tbx_stats

    glass = catalog.GLASS_WALL_TILES
    walls = catalog._all_interior_walls()
    check(walls and not any(t in glass for e in walls for t in e["tiles"].values()),
          f"no room is walled in glass storefront panes ({len(walls)} interior wall styles)")

    check(buildtiles._structure("fencing_01_3") and buildtiles._structure("walls_exterior_house_01_0")
          and buildtiles._yields("lighting_outdoor_01_0") and not buildtiles._yields("fencing_01_3"),
          "a fence or wall is structure, and a lamp is what gives way to it")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        tbx_stats.main(["tbx_stats", os.path.join(out, "buildings")])
    stats = {k.strip(): v.strip() for k, v in
             (line.split(":", 1) for line in buf.getvalue().splitlines() if ":" in line)}
    over = int(stats["roof tiles over open ground"].split(" of ")[0])
    blocked = int(stats["flights with a wall across"].split(" of ")[0])
    check(int(stats["buildings"]) > 0 and over == 0,
          f"no roof hangs over open ground ({stats['buildings']} buildings)")
    check(blocked == 0, "and no staircase has a wall across it")




def check_straight_roads(check) -> None:
    """Knox County roads: every road in grid or 45-degree runs, roads that met
    still meeting, and the buildings beside them moved with them."""
    from shapely.geometry import LineString, Point

    from generator.octilinear import straighten_roads
    from generator.renderer import Projector, _is_polygon, classify

    proj = Projector.build(SOUTH, WEST, SOUTH + 0.0054, WEST + 0.0068, 1.0)
    # A long road at 12 degrees, a side street off it at 70, a crescent, and a
    # house beside the first.
    main = way({"highway": "primary"}, [(20, 100), (560, 215)])
    side = way({"highway": "residential"}, [(20, 100), (80, 265), (140, 430)])
    crescent = way({"highway": "residential"},
                   [(300, 400 + 60 * math.sin(t / 10)) for t in range(0, 32)])
    house = way({"building": "house"}, box(300, 170, 312, 180))
    before = proj.to_px(*house.geometry[0])

    def gap() -> float:
        """How far the house's nearest corner is from the main road, in tiles."""
        line = LineString([proj.to_px(*p) for p in main.geometry])
        return min(Point(proj.to_px(*p)).distance(line) for p in house.geometry)

    was_gap = gap()
    feats = [main, side, crescent, house]
    straighten_roads(feats, proj, classify, _is_polygon)

    def runs_ok(f):
        pts = [proj.to_px(*p) for p in f.geometry]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            dx, dy = round(x1 - x0), round(y1 - y0)
            if not (dx == 0 or dy == 0 or abs(dx) == abs(dy)):
                return False
        return True

    check(all(runs_ok(f) for f in (main, side, crescent)),
          "Knox County roads run only along the tiles or on 45-degree diagonals")
    check(main.geometry[0] == side.geometry[0],
          "roads that met still meet once straightened")
    check(len({round(proj.to_px(*p)[1]) for p in main.geometry}) <= 2,
          "a long road at 12 degrees becomes straight, not a staircase")
    after = proj.to_px(*house.geometry[0])
    check(math.dist(before, after) > 0.5, "the houses beside a road move with it")
    # Not just "moved a little": it has to sit the same way against the road
    # it was beside, or the town has drifted off the street the game will draw.
    check(abs(gap() - was_gap) <= 1.0,
          f"and stay the same distance from it ({was_gap:.1f} tiles before, {gap():.1f} after)")




def check_missing_drive(check) -> None:
    """A Steam library on a drive that is gone (Windows raises for it rather
    than saying it is not there) is skipped, not a crash in Setup."""
    import knoxpaths

    class Gone(type(Path())):
        def stat(self, *a, **k):
            raise OSError(433, "A device which does not exist was specified", str(self))

    gone = Gone("F:/SteamLibrary")
    check(not knoxpaths._is_dir(gone / "steamapps") and not knoxpaths._exists(gone),
          "a Steam library on a missing drive is skipped")

    # A drive or folder the player names finds the library in it or above it.
    import tempfile
    with tempfile.TemporaryDirectory() as drive:
        lib = Path(drive) / "SteamLibrary"
        game = lib / "steamapps" / "common" / "ProjectZomboid"
        game.mkdir(parents=True)
        check(knoxpaths.library_of(drive) == [lib] and knoxpaths.library_of(game) == [lib]
              and knoxpaths.library_of(Path(drive) / "nothing") == [],
              "a chosen drive or folder finds its Steam library")
        old = os.environ.get("KNOXMAP_STEAM_FOLDERS")
        os.environ["KNOXMAP_STEAM_FOLDERS"] = drive
        try:
            found = knoxpaths.steam_libraries_found()
            check(found and found[0]["path"] == str(lib) and found[0]["chosen"],
                  "a chosen Steam library is looked in first")
        finally:
            if old is None:
                os.environ.pop("KNOXMAP_STEAM_FOLDERS")
            else:
                os.environ["KNOXMAP_STEAM_FOLDERS"] = old




def check_updater(check, work: str) -> None:
    """An update applied to a pretend install: new and changed files go in,
    dropped files go, and maps, logs and the Python environment are left alone."""
    import zipfile

    import updater

    base = Path(work) / "install"
    (base / "output" / "mytown").mkdir(parents=True)
    (base / "output" / "mytown" / "mytown.bmp").write_text("map")
    (base / ".venv").mkdir()
    (base / ".venv" / "keep.txt").write_text("env")
    (base / "knoxmap.py").write_text("old")
    (base / "dropped.py").write_text("gone in the new version")
    (base / "requirements.txt").write_text("flask")
    (base / "knoxmap_setup.py").write_text("setup")
    (base / updater.MANIFEST.name).write_text(json.dumps(
        {"version": "1.0", "files": ["knoxmap.py", "dropped.py", "requirements.txt",
                                     "knoxmap_setup.py"]}))
    update_dir = base / "update"
    update_dir.mkdir()
    zip_path = update_dir / "KnoxMap-v9.9.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("KnoxMap/knoxmap.py", "new")
        z.writestr("KnoxMap/requirements.txt", "flask")
        z.writestr("KnoxMap/knoxmap_setup.py", "setup")
        z.writestr("KnoxMap/added/module.py", "added")
        z.writestr("KnoxMap/output/mytown/mytown.bmp", "a release must not overwrite maps")
        z.writestr("KnoxMap/../escape.txt", "outside the folder")
    saved = {k: getattr(updater, k) for k in ("BASE_DIR", "UPDATE_DIR", "STAGED", "MANIFEST",
                                              "ASIDE_DIR", "FILE_TRIES", "FILE_GAP_S",
                                              "current_version", "enabled")}
    try:
        updater.BASE_DIR, updater.UPDATE_DIR = base, update_dir
        updater.STAGED, updater.MANIFEST = update_dir / "staged.json", base / saved["MANIFEST"].name
        updater.ASIDE_DIR = update_dir / "replaced"
        updater.FILE_TRIES, updater.FILE_GAP_S = 2, 0.01
        updater.current_version = lambda: "1.0"
        updater.enabled = lambda: True
        updater.STAGED.write_text(json.dumps({"version": "9.9", "zip": str(zip_path)}))
        applied = updater.apply_staged()
        check(applied and (base / "knoxmap.py").read_text() == "new"
              and (base / "added" / "module.py").exists() and not (base / "dropped.py").exists(),
              "an update puts in the new files and takes out the dropped ones")
        check((base / "output" / "mytown" / "mytown.bmp").read_text() == "map"
              and (base / ".venv" / "keep.txt").exists()
              and not (Path(work) / "escape.txt").exists(),
              "an update leaves maps and the Python environment alone and stays in its folder")
        check(not updater.STAGED.exists() and not zip_path.exists() and not updater.apply_staged(),
              "an update is applied once")
        # An older version goes in only when it was chosen in the version menu.
        old_zip = update_dir / "KnoxMap-v0.5.zip"
        with zipfile.ZipFile(old_zip, "w") as z:
            z.writestr("KnoxMap/knoxmap.py", "old release")
        updater.STAGED.write_text(json.dumps({"version": "0.5", "zip": str(old_zip)}))
        check(not updater.apply_staged() and (base / "knoxmap.py").read_text() == "new",
              "an automatic update never goes back to an older version")
        updater.STAGED.write_text(json.dumps({"version": "0.5", "zip": str(old_zip), "chosen": True}))
        updater.enabled = lambda: False       # choosing an older one turns them off
        check(updater.apply_staged() and (base / "knoxmap.py").read_text() == "old release",
              "a version chosen in the menu goes in, older ones too")
        check(updater.is_newer("1.10", "1.9") and not updater.is_newer("1.2", "1.2.0")
              and updater.is_newer("1.2.1", "1.2"), "versions compare as numbers")

        # One file that will not go in must not lose the whole update. Windows
        # refuses to overwrite a file another program has open - a virus
        # scanner reading KnoxMap.exe was enough - and the run used to stop
        # there with half the release in place, CHANGELOG.md among it, so
        # KnoxMap read as the new version and never looked again.
        updater.enabled = lambda: True
        (base / updater.VERSION_FILE).write_text("## 1.0\n")
        # A folder where the release has a file cannot be overwritten on any
        # system, which is the same dead end: the old one is moved aside.
        stuck = base / "stuck"
        stuck.mkdir()
        (stuck / "in the way").write_text("not something a file can replace")
        aside_zip = update_dir / "KnoxMap-v9.9.zip"
        with zipfile.ZipFile(aside_zip, "w") as z:
            z.writestr(f"KnoxMap/{updater.VERSION_FILE}", "## 9.9\n")
            z.writestr("KnoxMap/stuck", "a file where the install has a folder")
        updater.STAGED.write_text(json.dumps({"version": "9.9", "zip": str(aside_zip)}))
        check(updater.apply_staged() and (base / "stuck").is_file()
              and (updater.ASIDE_DIR / "stuck" / "in the way").exists(),
              "a file that will not be overwritten is moved aside and the update goes in")

        # And when it cannot even be moved: the version stays as it was and
        # the download waits for the next start rather than being thrown away.
        (base / updater.VERSION_FILE).write_text("## 1.0\n")
        (base / "locked").write_text("a file where the release has a folder")
        half_zip = update_dir / "KnoxMap-v9.9b.zip"
        with zipfile.ZipFile(half_zip, "w") as z:
            z.writestr(f"KnoxMap/{updater.VERSION_FILE}", "## 9.9\n")
            z.writestr("KnoxMap/locked/module.py", "cannot be unpacked over a file")
        updater.STAGED.write_text(json.dumps({"version": "9.9", "zip": str(half_zip)}))
        blocked = updater.apply_staged()
        left = json.loads(updater.STAGED.read_text()) if updater.STAGED.exists() else {}
        check(not blocked and (base / updater.VERSION_FILE).read_text().startswith("## 1.0")
              and left.get("tries") == 1 and half_zip.exists(),
              "an update that will not go in keeps the version it had and stays staged")
        (base / "locked").unlink()
        check(updater.apply_staged()
              and (base / "locked" / "module.py").exists()
              and (base / updater.VERSION_FILE).read_text().startswith("## 9.9"),
              "and the next start puts that update in")

        # A failure part way through moving files in: whatever was already
        # replaced goes back, so the install is not left half old and half new.
        for name in ("one.py", "two.py", "three.py"):
            (base / name).write_text(f"old {name}")
        (base / updater.VERSION_FILE).write_text("## 1.0\n")
        updater.MANIFEST.write_text(json.dumps({"version": "1.0", "files": []}))
        mid_zip = update_dir / "KnoxMap-v9.9c.zip"
        with zipfile.ZipFile(mid_zip, "w") as z:
            for name in ("one.py", "two.py", "three.py", "four.py"):
                z.writestr(f"KnoxMap/{name}", f"new {name}")
            z.writestr(f"KnoxMap/{updater.VERSION_FILE}", "## 9.9\n")
        updater.STAGED.write_text(json.dumps({"version": "9.9", "zip": str(mid_zip)}))
        real_put = updater._put_in_place
        calls = [0]

        def breaks_on_third(src, dest, rel, budget):
            calls[0] += 1
            if calls[0] == 3:
                raise OSError("a scanner has this one open")
            return real_put(src, dest, rel, budget)

        updater._put_in_place = breaks_on_third
        try:
            failed = not updater.apply_staged()
        finally:
            updater._put_in_place = real_put
        check(failed
              and all((base / n).read_text() == f"old {n}" for n in ("one.py", "two.py", "three.py"))
              and not (base / "four.py").exists()
              and (base / updater.VERSION_FILE).read_text().startswith("## 1.0")
              and mid_zip.exists(),
              "an update that fails part way through puts back the files it had replaced")
    finally:
        for k, v in saved.items():
            setattr(updater, k, v)
