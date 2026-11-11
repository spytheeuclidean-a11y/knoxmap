"""Progress and stop requests for the long jobs: generate, build and compile."""
from __future__ import annotations

import threading
import time

from flask import Blueprint, jsonify, request

from web.common import _json_body, failed, log

bp = Blueprint("jobs", __name__)


# Big maps take minutes, so generation reports where it has got to and the page
# polls /api/progress. Keyed by map name; the generate call owns its entry.
_PROGRESS: dict[str, dict] = {}
_COMPILE: dict[str, dict] = {}
_PROGRESS_LOCK = threading.Lock()

# A stage's pace needs a few seconds behind it before the time it implies is
# worth showing: off the first tile of a big map it is noise, and a time-left
# that jumps about is worse than none.
ETA_AFTER_SECONDS = 5


def _eta(now: dict) -> int | None:
    """Seconds left in the stage `now` describes, from the pace it has set.

    The share of the work done - tiles, files, buildings - against the time
    since the stage began. None until there is enough of both to mean anything.
    """
    done, total = now.get("done"), now.get("total")
    share = done / total if done and total and 0 < done < total else now.get("fraction")
    started = now.get("started")
    if not isinstance(share, (int, float)) or not 0 < share < 1 or not started:
        return None
    elapsed = time.time() - started
    if elapsed < ETA_AFTER_SECONDS:
        return None
    return max(1, int(round(elapsed / share * (1 - share))))


def _set_progress(map_name: str, **fields) -> None:
    with _PROGRESS_LOCK:
        now = _PROGRESS.setdefault(map_name, {})
        stage = fields.get("stage")
        if stage is not None and stage != now.get("stage"):
            now["started"] = time.time()      # a new stage starts its own clock
        now.update(fields)
        left = _eta(now)
        if left is None:
            now.pop("etaSeconds", None)
        else:
            now["etaSeconds"] = left
    # Discord Rich Presence, if the player asked for it. It is a set on a
    # background thread and nothing here waits on it: knoxpresence swallows
    # its own errors so a Discord that is closed, restarting or not installed
    # cannot interrupt a map halfway through.
    if "stage" in fields:
        try:
            import knoxpresence
            knoxpresence.stage(str(fields["stage"]))
        except Exception:  # noqa: BLE001 - presence is never worth a failure
            pass


# Maps the window has asked to stop. A long job looks at this between the
# pieces of work it can be interrupted between (knoxstop.py); the name comes
# off the list when the job it stopped notices, so the next run is not
# stopped before it starts.
_STOPPING: set[str] = set()
# Every job, at once: the window has closed (knoxmap.py).
_STOP_ALL = threading.Event()


def _stopper(map_name: str):
    """A callable the long jobs poll: True once the window has asked."""
    return lambda: map_name in _STOPPING or _STOP_ALL.is_set()


def stop_all() -> None:
    """Ask every running job to stop, as the window does when it closes."""
    _STOP_ALL.set()
    log.info("stop: every job, the window has closed")


def _hold(map_dir, doing: str):
    """Take the map's lock for the length of this request, so a second KnoxMap
    process cannot generate, build or compile the same map alongside it
    (tools/compile_map.claim). Returns the reply to send instead when another
    one holds it, else None; the lock goes with the reply."""
    import uuid

    from flask import after_this_request

    from tools.compile_map import claim, release

    run = uuid.uuid4().hex[:8]
    try:
        claim(map_dir, run, doing)
    except RuntimeError as exc:
        return failed(str(exc), 409)

    @after_this_request
    def _let_go(response):
        release(map_dir, run)
        return response

    return None


def _done_stopping(map_name: str) -> None:
    _STOPPING.discard(map_name)


def _stopped(map_name: str, step: str):
    """The reply for a job the window stopped: not an error, and the map's
    area and settings are untouched."""
    _done_stopping(map_name)
    log.info("stop %s: %s stopped", map_name, step)
    with _PROGRESS_LOCK:
        _PROGRESS.setdefault(map_name, {})["stage"] = "stopped"
    return jsonify({"stopped": True, "step": step, "mapName": map_name}), 409


@bp.route("/api/stop", methods=["POST"])
def api_stop():
    """Stop making this map, and leave everything else as it is.

    The drawn area, the settings and whatever has already been written stay
    where they are: pressing the button again starts the same map over. Used
    to mean closing the window, which threw the drawn rectangle away with it.
    """
    name = str((_json_body() or {}).get("mapName", "")).strip()
    if not name:
        return failed("Which map?", 400)
    _STOPPING.add(name)
    log.info("stop %s: asked by the window", name)
    with _PROGRESS_LOCK:
        _PROGRESS.setdefault(name, {})["stage"] = "stopping"
        if _COMPILE.get(name, {}).get("state") == "running":
            _COMPILE[name] = {**_COMPILE[name], "state": "stopping"}
    return jsonify({"stopping": True, "mapName": name})


@bp.route("/api/progress")
def api_progress():
    with _PROGRESS_LOCK:
        return jsonify(_PROGRESS.get(request.args.get("map", ""), {}))
