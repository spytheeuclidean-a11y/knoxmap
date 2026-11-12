"""Updates and the version menu (updater.py does the work)."""
from __future__ import annotations

import os
import re
import threading

from flask import Blueprint, jsonify

from web.common import _json_body, failed, log

bp = Blueprint("updates", __name__)


@bp.route("/api/update")
def api_update():
    """Whether a newer KnoxMap is downloading or ready (updater.py)."""
    import updater
    return jsonify(updater.status())


@bp.route("/api/update/check", methods=["POST"])
def api_update_check():
    import updater
    threading.Thread(target=updater.check, name="update-check", daemon=True).start()
    return jsonify(updater.status())


@bp.route("/api/versions")
def api_versions():
    """The KnoxMap releases on GitHub, for the version menu."""
    import updater
    try:
        return jsonify(updater.releases())
    except Exception as exc:  # noqa: BLE001 - offline or rate-limited
        return failed(f"Could not reach GitHub for the list of versions: {exc}", 502, exc)


@bp.route("/api/versions/install", methods=["POST"])
def api_versions_install():
    """Download the version chosen in the menu, to go in on restart."""
    import updater
    version = str(_json_body().get("version", "")).strip()
    if not re.fullmatch(r"\d+(?:\.\d+){0,3}(?:-[a-z]+\d*)?", version):
        return failed("Choose a version from the list.", 400)
    if not updater.managed():
        return failed("This copy of KnoxMap is a git checkout: switch versions with git.", 400)
    if updater.status().get("state") in ("checking", "downloading"):
        return failed("A download is already running; try again in a moment.", 409)
    log.info("version %s chosen in the window (this is %s)", version, updater.current_version())
    threading.Thread(target=updater.choose, args=(version,), name="choose-version",
                     daemon=True).start()
    return jsonify({"started": True, "version": version})


@bp.route("/api/update/restart", methods=["POST"])
def api_update_restart():
    import updater
    if os.environ.get("KNOXMAP_WINDOW") != "1":
        return failed("Close KnoxMap and open it again to update.", 400)
    if updater.status().get("state") != "ready":
        return failed("No update is ready yet.", 409)
    updater.restart()
    return jsonify({"restarting": True})
