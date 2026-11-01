"""Where things are: the map tiles, the place search, landmarks and the Overpass servers."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import urllib.parse

from flask import Blueprint, jsonify, request, send_file

from generator import osm, places

from web.checks import BIG_LANDMARK_KM2
from web.common import CACHE_DIR, _bbox_area_km2, _json_body, log

bp = Blueprint("geo", __name__)


# ---- map tiles, fetched the way the OSM tile policy asks -------------------------
#
# https://operations.osmfoundation.org/policies/tiles/ - an installed app must
# identify itself with its own User-Agent (never a browser's), honour the
# server's caching headers or keep tiles at least 7 days, and never pre-fetch
# or bulk-download. The page's map used to load tiles straight from
# tile.openstreetmap.org inside the app window, which sent WebView2's browser
# identity and cached nothing. Tiles now come through here: fetched only when
# the map shows them, with KnoxMap's User-Agent, kept on disk and revalidated.
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_CACHE = CACHE_DIR / "tiles"
TILE_MIN_AGE = 7 * 24 * 3600
# How many tiles are fetched at once. A map view is twenty or thirty tiles,
# and at two at a time they arrived in a slow ripple; a browser asking
# tile.openstreetmap.org directly opens six connections, so four through one
# proxy is no heavier than the page would be on its own. This is interactive
# browsing, not the bulk downloading the tile policy asks people not to do.
TILE_FETCHES = threading.BoundedSemaphore(4)
# One connection pool for all of them. Without it every tile paid for a new
# TCP connection and a TLS handshake - most of the wait, on a map of tiles
# that are only a few kilobytes each.
TILE_TIMEOUT = (5, 15)          # connect, read
_TILE_SESSION = None
_TILE_SESSION_LOCK = threading.Lock()
# Tiles being revalidated in the background, so a stale one is not fetched
# once per request while the first fetch is still running.
_TILE_REVALIDATING: set = set()


def _tile_session():
    global _TILE_SESSION
    with _TILE_SESSION_LOCK:
        if _TILE_SESSION is None:
            import requests
            from requests.adapters import HTTPAdapter

            session = requests.Session()
            adapter = HTTPAdapter(pool_connections=4, pool_maxsize=8)
            session.mount("https://", adapter)
            session.headers["User-Agent"] = places.HEADERS["User-Agent"]
            _TILE_SESSION = session
    return _TILE_SESSION


def _fetch_tile(z: int, x: int, y: int, path, meta, info: dict) -> bool:
    """Fetch or revalidate one tile. True when it is on disk afterwards."""
    import requests

    headers = {}
    if path.exists() and info.get("etag"):
        headers["If-None-Match"] = info["etag"]
    try:
        with TILE_FETCHES:
            r = _tile_session().get(TILE_URL.format(z=z, x=x, y=y),
                                    headers=headers, timeout=TILE_TIMEOUT)
    except requests.RequestException:
        return path.exists()
    if r.status_code not in (200, 304):
        return path.exists()
    max_age = TILE_MIN_AGE
    for part in (r.headers.get("Cache-Control") or "").split(","):
        if part.strip().startswith("max-age="):
            try:
                max_age = max(TILE_MIN_AGE, int(part.split("=", 1)[1]))
            except ValueError:
                pass
    if r.status_code == 200:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        info["etag"] = r.headers.get("ETag")
    info["expires"] = time.time() + max_age
    try:
        meta.write_text(json.dumps(info), encoding="utf-8")
    except OSError:
        pass
    return path.exists()


@bp.route("/tiles/<int:z>/<int:x>/<int:y>.png")
def tile(z: int, x: int, y: int):
    if not (0 <= z <= 19 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return ("", 404)
    path = TILE_CACHE / str(z) / str(x) / f"{y}.png"
    meta = path.with_suffix(".json")
    info = {}
    if path.exists() and meta.exists():
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
    fresh = path.exists() and time.time() < info.get("expires", 0)
    if path.exists() and not fresh:
        # A tile we already have is served straight away and checked against
        # the server behind the page's back. Waiting on that round trip made
        # panning back over somewhere already visited as slow as the first
        # time, for a picture of a street that had not changed in a week.
        key = (z, x, y)
        if key not in _TILE_REVALIDATING:
            _TILE_REVALIDATING.add(key)

            def revalidate():
                try:
                    _fetch_tile(z, x, y, path, meta, info)
                finally:
                    _TILE_REVALIDATING.discard(key)

            threading.Thread(target=revalidate, name=f"tile-{z}-{x}-{y}",
                             daemon=True).start()
    elif not fresh and not _fetch_tile(z, x, y, path, meta, info):
        return ("", 502)
    resp = send_file(path, mimetype="image/png")
    resp.headers["Cache-Control"] = f"max-age={TILE_MIN_AGE}"
    return resp


# Nominatim asks that results are cached on the application's side and that
# the same query is not sent again and again
# (https://operations.osmfoundation.org/policies/nominatim/).
_SEARCH_CACHE: dict[tuple, tuple[float, list]] = {}
SEARCH_CACHE_SECONDS = 24 * 3600


@bp.route("/api/search")
def api_search():
    """Find a place by name, so the map can jump to it."""
    q = request.args.get("q", "")
    if not q.strip():
        return jsonify({"results": []})

    viewbox = None
    try:
        viewbox = (float(request.args["south"]), float(request.args["west"]),
                   float(request.args["north"]), float(request.args["east"]))
    except (KeyError, ValueError):
        pass
    bounded = request.args.get("bounded") == "1"

    key = (q.strip().lower(), viewbox and tuple(round(v, 3) for v in viewbox), bounded)
    cached = _SEARCH_CACHE.get(key)
    if cached and time.time() - cached[0] < SEARCH_CACHE_SECONDS:
        return jsonify({"results": cached[1]})
    try:
        results = places.search(q, viewbox=viewbox, bounded=bounded)
    except Exception as exc:  # network, rate limit, bad JSON
        return jsonify({"error": f"Search failed: {exc}"}), 502
    if len(_SEARCH_CACHE) > 500:
        _SEARCH_CACHE.clear()
    _SEARCH_CACHE[key] = (time.time(), results)
    return jsonify({"results": results})


@bp.route("/api/landmarks", methods=["POST"])
def api_landmarks():
    """List the named landmarks inside a bbox."""
    data = _json_body()
    try:
        south = float(data["south"])
        west = float(data["west"])
        north = float(data["north"])
        east = float(data["east"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Need south, west, north and east."}), 400

    landmark_area = _bbox_area_km2(south, west, north, east)
    if landmark_area > BIG_LANDMARK_KM2:
        # Slow, not impossible. It used to be refused outright.
        log.info("landmarks: %.1f km2, over the %g km2 this gets slow at",
                 landmark_area, BIG_LANDMARK_KM2)

    try:
        found = places.landmarks(south, west, north, east)
    except Exception as exc:
        return jsonify({"error": f"Lookup failed: {exc}"}), 502
    return jsonify({"landmarks": found})


@bp.route("/api/overpass", methods=["GET", "POST"])
def api_overpass():
    """Which Overpass servers map data is downloaded from.

    The public ones by default; your own (docs/SELF_HOSTING_OVERPASS.md) when
    named here. Saved as "overpass_endpoints" in knoxmap_config.json and used
    at once, so a download started after saving already goes there."""
    import knoxpaths

    if request.method == "POST":
        body = _json_body()
        if "osm_source" in body:
            src = str(body["osm_source"]).strip().lower()
            if src in ("auto", "overpass", "extract"):
                knoxpaths.update_config({"osm_source": src})
                log.info("osm source set to %s", src)

        if "endpoints" in body:
            raw = body.get("endpoints")
            if raw is None or raw == "":
                raw = []
            if isinstance(raw, str):
                raw = re.split(r"[\s,;]+", raw)
            if not isinstance(raw, list):
                return jsonify({"error": "Give the servers as a list of addresses."}), 400
            try:
                urls = osm.normalise_endpoints(raw)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            if len(urls) > 8:
                return jsonify({"error": "At most 8 servers."}), 400
            knoxpaths.update_config({"overpass_endpoints": urls})
            osm.set_endpoints(urls)
            log.info("overpass servers: %s", urls or "the public ones")
    try:
        cfg = knoxpaths.load_config()
        configured = cfg.get("overpass_endpoints")
        current_source = cfg.get("osm_source") or "auto"
    except Exception:  # noqa: BLE001
        configured = None
        current_source = "auto"
    return jsonify({"endpoints": [str(u) for u in configured] if isinstance(configured, list) else [],
                    "using": list(osm.OVERPASS_ENDPOINTS),
                    "public": list(osm._DEFAULT_ENDPOINTS),
                    "osm_source": current_source if current_source in ("auto", "overpass", "extract") else "auto"})


@bp.route("/api/overpass/status")
def api_overpass_status():
    """Whether each server in use answers right now, and how fast. One tiny
    query per server, asked together, so this costs a few seconds in all.
    "resting" is what the downloads themselves currently think of it."""
    from concurrent import futures

    def one(endpoint: str) -> dict:
        t0 = time.time()
        ok = osm._probe(endpoint, 40.0, -74.0)
        return {"url": endpoint, "host": endpoint.split("/")[2], "ok": ok,
                "seconds": round(time.time() - t0, 1),
                "resting": osm._is_cooling(endpoint),
                "regional": any(h in endpoint for h in osm.BLANK_ONLY_HOSTS)}

    endpoints = list(osm.OVERPASS_ENDPOINTS)
    with futures.ThreadPoolExecutor(max_workers=max(1, len(endpoints))) as pool:
        return jsonify({"servers": list(pool.map(one, endpoints))})


# ---- a server of your own, in Docker ---------------------------------------------
#
# docs/SELF_HOSTING_OVERPASS.md by hand, as buttons. KnoxMap only starts and
# stops one container of its own name; the extract has to come from Geofabrik.
LOCAL_NAME = "knoxmap-overpass"
LOCAL_PORT = 12345
LOCAL_URL = f"http://localhost:{LOCAL_PORT}/api/interpreter"
LOCAL_EXTRACT = re.compile(r"^https://download\.geofabrik\.de/[A-Za-z0-9._/-]+\.osm\.bz2$")


def _docker(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          timeout=timeout, errors="replace")


def _local_state() -> dict:
    """Docker present or not, and what the container is doing."""
    import requests

    if not shutil.which("docker"):
        return {"docker": False, "state": "none", "url": LOCAL_URL}
    try:
        ps = _docker("ps", "-a", "--filter", f"name=^{LOCAL_NAME}$",
                     "--format", "{{.State}}")
    except (OSError, subprocess.SubprocessError):
        return {"docker": False, "state": "none", "url": LOCAL_URL}
    if ps.returncode != 0:
        return {"docker": False, "state": "none", "url": LOCAL_URL,
                "error": (ps.stderr or "").strip()[-300:]}
    running = ps.stdout.strip()
    if not running:
        return {"docker": True, "state": "none", "url": LOCAL_URL}
    out = {"docker": True, "url": LOCAL_URL,
           "state": "stopped" if running != "running" else "loading"}
    if running == "running":
        try:
            ready = requests.get(f"http://localhost:{LOCAL_PORT}/api/status", timeout=3).ok
        except requests.RequestException:
            ready = False
        out["state"] = "ready" if ready else "loading"
        if not ready:
            try:
                tail = _docker("logs", "--tail", "1", LOCAL_NAME).stdout
                tail = tail or _docker("logs", "--tail", "1", LOCAL_NAME).stderr
                out["log"] = (tail or "").strip()[-200:]
            except (OSError, subprocess.SubprocessError):
                pass
    return out


@bp.route("/api/local-overpass", methods=["GET", "POST"])
def api_local_overpass():
    """Run, stop, remove or start using a local Overpass server in Docker."""
    import knoxpaths

    if request.method == "GET":
        return jsonify(_local_state())
    body = _json_body()
    action = str(body.get("action") or "")
    state = _local_state()
    if action in ("start", "stop", "remove") and not state["docker"]:
        return jsonify({"error": "Docker is not installed or not running. Install Docker "
                                 "Desktop, start it, and try again."}), 400
    try:
        if action == "start":
            if state["state"] == "none":
                extract = str(body.get("extract") or "").strip()
                if not LOCAL_EXTRACT.match(extract):
                    return jsonify({"error": "Give a Geofabrik extract ending in .osm.bz2, "
                                             "e.g. https://download.geofabrik.de/north-america/"
                                             "us/tennessee-latest.osm.bz2"}), 400
                r = _docker("run", "-d", "--name", LOCAL_NAME,
                            "-p", f"127.0.0.1:{LOCAL_PORT}:80", "-v", "knoxmap_overpass_db:/db",
                            "-e", "OVERPASS_MODE=init", "-e", f"OVERPASS_PLANET_URL={extract}",
                            "-e", "OVERPASS_RULES_LOAD=10", "wiktorn/overpass-api", timeout=600)
            else:
                r = _docker("start", LOCAL_NAME)
        elif action == "stop":
            r = _docker("stop", LOCAL_NAME, timeout=120)
        elif action == "remove":
            r = _docker("rm", "-f", LOCAL_NAME, timeout=120)
        elif action == "use":
            current = [u for u in osm.OVERPASS_ENDPOINTS if u != LOCAL_URL]
            urls = [LOCAL_URL] + current
            knoxpaths.update_config({"overpass_endpoints": urls})
            osm.set_endpoints(urls)
            log.info("overpass servers: %s", urls)
            return jsonify(_local_state())
        else:
            return jsonify({"error": "Unknown action."}), 400
    except (OSError, subprocess.SubprocessError) as exc:
        return jsonify({"error": f"Docker did not answer: {exc}"}), 502
    if r.returncode != 0:
        return jsonify({"error": (r.stderr or r.stdout or "docker failed").strip()[-400:]}), 502
    log.info("local overpass: %s", action)
    return jsonify(_local_state())
