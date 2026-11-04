"""Knoxify — Flask entry point.

Real-world areas → Project Zomboid maps.

Run:
    source .venv/bin/activate
    python app.py

Then open http://127.0.0.1:5000/ in a browser.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse

from flask import Flask, jsonify, render_template, request

import knoxlog

from web import (compiling, datasets, generation, geo, jobs, maps, presets,
                 system, updates, zones)
from web.common import _request_context, failed

# Names the tests and tools/selftest.py reach through this module. The code
# moved to web/; the old names still work for anything that reads them.
from generator import osm  # noqa: F401
from web.checks import (BIG_AREA_KM2, BIG_LANDMARK_KM2, BIG_TILES_PER_SIDE,  # noqa: F401
                        MAX_METERS_PER_TILE, MIN_METERS_PER_TILE, RENDER_SETTINGS,
                        _clean_shape, _too_big_for_memory, tidy_scale)
from web.common import BASE_DIR  # noqa: F401
from web.generation import generate  # noqa: F401
from web.presets import MAX_PRESET_POINTS  # noqa: F401


# Builds print place names in any script; a console on a legacy code page
# would raise mid-request on the first one it cannot show.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

app = Flask(__name__, template_folder="templates", static_folder="static")

# Only this PC may talk to the app. The server listens on 127.0.0.1, but a web
# page in any browser on the PC can still point a hostname of its own at that
# address ("DNS rebinding") and call the API as if it were the app's own page.
# Such a request carries the attacker's hostname, so anything not addressed to
# localhost is refused before it reaches a route.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


@app.errorhandler(Exception)
def _api_error(exc):
    """Every failure as JSON the page can show, with the details in the log.

    Flask's default answer to an exception is an HTML page. The page reads
    every reply as JSON, so a crash anywhere in a request showed only
    "Unexpected token '<', "<!doctype"... is not valid JSON", which says
    nothing about what went wrong or where.
    """
    from werkzeug.exceptions import HTTPException

    if isinstance(exc, HTTPException):
        if not request.path.startswith("/api/"):
            return exc
        return jsonify({"error": f"{exc.code} {exc.name}"}), exc.code
    return failed(f"{type(exc).__name__}: {exc}", 500, exc)


@app.after_request
def _log_refusals(response):
    """Every error the API answers with goes in the log, not just crashes: a
    "Missing or invalid bbox" is as much a clue as a traceback."""
    if (request.path.startswith("/api/") and response.status_code >= 400
            and response.is_json):
        data = response.get_json(silent=True) or {}
        if data.get("stopped"):
            return response          # asked for; already in the log as a stop
        if not data.get("errorId"):
            eid = knoxlog.record(None, f"{request.method} {request.path} -> "
                                       f"{response.status_code}: {data.get('error')}",
                                 **_request_context())
            data["errorId"] = eid
            response.set_data(json.dumps(data))
    return response


@app.before_request
def _only_local():
    host = (request.host or "").rsplit(":", 1)[0] if not (request.host or "").startswith("[")         else (request.host or "").split("]")[0] + "]"
    if host not in LOCAL_HOSTS:
        return ("KnoxMap only answers requests from this computer.", 403)
    # A page open in the browser can send this server a plain POST with no body
    # (open the logs, restart for an update, change the language): the browser
    # allows it and the Host above is ours. Browsers say where such a request
    # came from, so one that came from somewhere else is refused. A request with
    # no Origin (the test client, curl) is not a browser's and passes.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin is not None:
            try:
                origin_host = urllib.parse.urlparse(origin).hostname
            except ValueError:
                origin_host = None
            if origin_host not in LOCAL_HOSTS:
                return ("KnoxMap does not take requests from other websites.", 403)
        elif request.headers.get("Sec-Fetch-Site") == "cross-site":
            return ("KnoxMap does not take requests from other websites.", 403)


@app.route("/")
def index():
    # The app window cannot download a file the way a browser does - clicking
    # a download link there did nothing at all - so the page asks the server
    # to save it and show it in Explorer instead. See /api/save.
    return render_template("index.html", version=knoxlog.version(),
                           in_window=os.environ.get("KNOXMAP_WINDOW") == "1")


# ---- the routes: one blueprint per area, in web/ ----------------------------------
app.register_blueprint(jobs.bp)
app.register_blueprint(updates.bp)
app.register_blueprint(geo.bp)
app.register_blueprint(system.bp)
app.register_blueprint(presets.bp)
app.register_blueprint(zones.bp)
app.register_blueprint(compiling.bp)
app.register_blueprint(generation.bp)
app.register_blueprint(datasets.bp)
app.register_blueprint(maps.bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)
