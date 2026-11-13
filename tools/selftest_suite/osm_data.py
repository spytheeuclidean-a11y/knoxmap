"""Selftest checks for osm data."""
from __future__ import annotations

if __package__ == "tools.selftest_suite":
    from ..selftest import (
        EAST, NORTH, OSMFeature, SOUTH, WEST,
        json,
        math, os, shutil, tempfile,
    )
else:
    from selftest import (
        EAST, NORTH, OSMFeature, SOUTH, WEST,
        json,
        math, os, shutil, tempfile,
    )


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


def check_overpass_retry(check) -> None:
    """A busy Overpass server does not lose the map.

    The public instances are shared and go busy together. A tile that nothing
    answered used to fail the whole download: every tile that had arrived was
    thrown away uncached, so a town that fetched forty and missed one started
    again from nothing. Nothing here touches the network.
    """
    import requests

    from generator import osm as _osm

    was_split, was_ask, was_pause = (_osm._fetch_splitting, _osm._ask,
                                     _osm.RETRY_PAUSE_S)
    was_check, was_tiles = _osm.check_endpoints, _osm.TILE_CACHE_DIR
    tile_dir = tempfile.mkdtemp(prefix="knoxmap-tiles-")
    try:
        _osm.RETRY_PAUSE_S = 0
        # Two things here reach outside the test. check_endpoints asks the
        # real public instances whether they are up, which this must not do
        # and which the docstring above promises it does not. The tile cache
        # keeps what a tile "downloaded" under the project's own cache folder,
        # so the second run of this test was served sixteen tiles it had
        # written itself and never saw the failure it was checking for.
        _osm.check_endpoints = lambda *a, **k: None
        _osm.TILE_CACHE_DIR = tile_dir
        seen: dict = {}
        ids: dict = {}

        def once_then_works(south, west, north, east, timeout, depth=0, first=0):
            key = (round(south, 4), round(west, 4))
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 1:
                raise _osm.OverpassError("busy", timed_out=True)
            # One feature per tile, each with an id of its own: the tiles are
            # merged on (kind, id), so a shared id would hide a lost tile.
            return [_osm.OSMFeature(osm_id=ids.setdefault(key, len(ids) + 1),
                                    kind="way", tags={},
                                    geometry=[(west, south)])]

        _osm._fetch_splitting = once_then_works
        got = _osm.fetch_features_tiled(50.0, 5.0, 50.2, 5.3, max_tile_km2=30.0)
        check(len(got) == len(seen) and len(seen) > 1,
              f"a tile that fails once is asked for again, and the map still "
              f"arrives ({len(seen)} tiles)")

        def never_works(south, west, north, east, timeout, depth=0, first=0):
            raise _osm.OverpassError("every Overpass endpoint failed — busy",
                                     timed_out=True)

        # A fresh cache: the tiles the check above "downloaded" are kept for
        # a fortnight, and handing them back here would answer the very
        # question this is asking - whether a download that fails everywhere
        # says so.
        _osm.TILE_CACHE_DIR = tempfile.mkdtemp(prefix="knoxmap-tiles-")
        _osm._fetch_splitting = never_works
        try:
            _osm.fetch_features_tiled(50.0, 5.0, 50.2, 5.3, max_tile_km2=30.0)
            said = ""
        except _osm.OverpassError as exc:
            said = str(exc)
        check("tiles would not download" in said and "smaller area" in said,
              "and when they all fail it says how many and what to do")

        # A tile nothing answers is quartered like a refused one, but the
        # splitting has to stop: on a dropped connection every request times
        # out, and each one waits out the clock before it says so.
        _osm._fetch_splitting = was_split
        tries = []

        def dead(endpoint, query, timeout):
            tries.append(endpoint)
            raise requests.Timeout("no answer")

        _osm._ask = dead
        side = (30.0 ** 0.5) / 111.32
        for area, ceiling in ((side, 3), (side / 6, 2)):
            tries.clear()
            try:
                _osm._fetch_splitting(50.0, 5.0, 50.0 + area, 5.0 + area, 30)
            except _osm.OverpassError:
                pass
            check(len(tries) <= ceiling * len(_osm.OVERPASS_ENDPOINTS),
                  f"a tile nobody answers gives up after {len(tries)} requests")
    finally:
        _osm._fetch_splitting, _osm._ask = was_split, was_ask
        _osm.RETRY_PAUSE_S = was_pause
        used = _osm.TILE_CACHE_DIR
        _osm.check_endpoints, _osm.TILE_CACHE_DIR = was_check, was_tiles
        for d in {tile_dir, used}:
            shutil.rmtree(d, ignore_errors=True)


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


def check_overture(check, work: str) -> None:
    """Buildings from Overture, where OpenStreetMap has none.

    OSM is drawn by people, so a town is on it as far as somebody traced it.
    Measured over the same size of box, Overture added 60 buildings to a
    German town and 761 to a Turkish one - nearly trebling it. None of this
    check needs the network or DuckDB: what is tested is the shape of the
    answer and the rule that decides what to keep, which is where the bugs
    would be.
    """
    import json as _json

    from generator import osm as _osm
    from generator import overture

    check(isinstance(overture.available(), bool),
          f"whether Overture can be reached is a plain yes or no "
          f"({'DuckDB is installed' if overture.available() else 'no DuckDB here'})")
    check("duckdb" in overture.why_unavailable().lower(),
          "and without it the window says what to install")

    def square(lat, lon, side_m, **row):
        """One Overture row: a square building of `side_m` metres."""
        d = side_m / 111320.0
        e = d / max(0.2, math.cos(math.radians(lat)))
        ring = [[lon, lat], [lon + e, lat], [lon + e, lat + d], [lon, lat + d],
                [lon, lat]]
        return {"id": row.get("id", "x"), "height": row.get("height"),
                "levels": row.get("levels"), "class": row.get("cls"),
                "geometry": {"type": "Polygon", "coordinates": [ring]}}

    rows = [
        square(38.60, 34.90, 12.0, id="a", cls="house"),
        square(38.61, 34.91, 20.0, id="b", cls=None, levels=3, height=9.5),
        square(38.62, 34.92, 1.5, id="c"),          # a sliver, not a building
        {"id": "d", "geometry": {"type": "MultiPolygon", "coordinates": [
            [[[34.93, 38.63], [34.9302, 38.63], [34.9302, 38.6302],
              [34.93, 38.6302], [34.93, 38.63]]]]},
         "height": None, "levels": None, "class": "barn"},
    ]
    feats = overture.to_features(rows)
    check(len(feats) == 3,
          f"a sliver is not a building and is left out ({len(rows)} rows, "
          f"{len(feats)} kept)")
    tags = {f.tags["building"] for f in feats}
    check("house" in tags and "barn" in tags and "yes" in tags,
          "Overture's class goes straight into the building tag, and a "
          "machine-found roof with no class becomes a plain footprint")
    levelled = [f for f in feats if f.tags.get("building:levels")]
    check(levelled and levelled[0].tags["building:levels"] == "3"
          and levelled[0].tags.get("height") == "9.5",
          "storeys and height come across where Overture has them")
    check(all(f.kind == "way" and f.osm_id < 0 for f in feats),
          "and they arrive as ways with ids no OSM way can have, so nothing "
          "downstream has to know where they came from")

    # The rule that decides what is new: a centre inside a mapped building.
    mapped = []
    for f in feats[:1]:
        mapped.append(_osm.OSMFeature(osm_id=1, kind="way",
                                      tags={"building": "house"},
                                      geometry=list(f.geometry)))
    kept = overture.only_missing(feats, mapped)
    check(len(kept) == len(feats) - 1,
          f"a roof standing on a building OSM already has is dropped "
          f"({len(feats)} offered, {len(kept)} kept)")
    check(overture.only_missing(feats, []) == feats,
          "and where OSM has nothing at all, all of them are kept")

    # What is cached is only reused for the same box and the same release.
    bounds = (38.60, 34.90, 38.64, 34.94)
    path = overture.cache_path(work, "ovtest")
    overture.save_cache(path, bounds, rows)
    check(overture.load_cache(path, bounds) is not None,
          "a fetch is kept beside the map, so the minutes are paid once")
    check(overture.load_cache(path, (38.60, 34.90, 38.64, 34.95)) is None,
          "a different area is not answered from it")
    was = os.environ.get("KNOXMAP_OVERTURE_RELEASE")
    os.environ["KNOXMAP_OVERTURE_RELEASE"] = "1999-01-01.0"
    try:
        stale = overture.load_cache(path, bounds)
    finally:
        if was is None:
            os.environ.pop("KNOXMAP_OVERTURE_RELEASE", None)
        else:
            os.environ["KNOXMAP_OVERTURE_RELEASE"] = was
    check(stale is None, "nor is a newer release answered from an older one")

    # Without DuckDB the map is still made, from OSM alone.
    out, stats = overture.add_missing([], bounds, work, "ovtest2")
    if overture.available():
        check(True, "DuckDB is here, so gap filling would run (not fetched in a check)")
    else:
        check(out == [] and stats["added"] == 0 and stats.get("why"),
              "without DuckDB the map is the one OSM alone makes, and says why")

    # ...but a map already fetched re-renders without it. Fetching is the one
    # thing DuckDB is for, and asking for it before looking in the cache meant
    # a folder handed to somebody else lost the buildings it had already paid
    # minutes for.
    seeded = os.path.join(work, "ovseed")
    os.makedirs(seeded, exist_ok=True)
    overture.save_cache(overture.cache_path(seeded, "m"), bounds, rows)
    out, stats = overture.add_missing([], bounds, seeded, "m")
    check(stats["cached"] and stats["added"] == len(feats)
          and len(out) == len(feats),
          f"a map already fetched fills its gaps again with no DuckDB at all "
          f"({stats['added']} buildings back out of the cache)")

    # The credit Overture's licence asks for, only on a map that used it.
    import make_map_mod as _mod

    proj = os.path.join(work, "ovattr-proj")
    mod = os.path.join(work, "ovattr-mod")
    os.makedirs(proj, exist_ok=True)
    os.makedirs(mod, exist_ok=True)
    with open(os.path.join(proj, "t_info.json"), "w", encoding="utf-8") as f:
        _json.dump({"osm_bbox": list(bounds)}, f)
    _mod.write_attribution(proj, mod, "Test Town")
    plain = open(os.path.join(mod, "ATTRIBUTION.txt"), encoding="utf-8").read()
    open(os.path.join(proj, "t_overture.json.gz"), "wb").write(b"x")
    _mod.write_attribution(proj, mod, "Test Town")
    filled = open(os.path.join(mod, "ATTRIBUTION.txt"), encoding="utf-8").read()
    check("Overture" not in plain and "Overture Maps Foundation" in filled
          and "OpenStreetMap" in filled,
          "a map that used Overture credits it, and one that did not does not")

