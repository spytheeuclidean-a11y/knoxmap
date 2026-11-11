"""Compiling a built map into the game's lot files (tools/compile_map.py does the work)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

import knoxlog
import knoxstop
from knoxbuild import mapstate

from web.common import _json_body, _map_dir, _worlded_exe, log
from web.jobs import _COMPILE, _PROGRESS_LOCK, _done_stopping, _stopper

bp = Blueprint("compiling", __name__)


# Source cells per side handed to one WorldEd process. 4x4 keeps its peak
# memory around a gigabyte; larger batches are faster per cell but climb.
COMPILE_BATCH = 4


def _expected_cells(map_dir: Path) -> int:
    """How many 256-tile cells the compile should produce, for a progress bar."""
    try:
        with open(map_dir / f"{map_dir.name}_info.json", encoding="utf-8") as f:
            info = json.load(f)
    except Exception:
        return 0
    from knoxbuild.world import CELL_SIZE, WORLD_ORIGIN_CELLS, _project_box

    # Where this map was actually built, which is not 70,0 once a PC holds
    # more than one of them (knoxbuild/world.py choose_origin).
    box = _project_box(str(map_dir / f"{map_dir.name}.pzw"))
    ox = (box[0] if box else WORLD_ORIGIN_CELLS[0]) * CELL_SIZE
    oy = (box[1] if box else WORLD_ORIGIN_CELLS[1]) * CELL_SIZE
    w = info.get("cells_x", 0) * CELL_SIZE
    h = info.get("cells_y", 0) * CELL_SIZE
    x0, x1 = ox // 256, (ox + w + 255) // 256
    y0, y1 = oy // 256, (oy + h + 255) // 256
    return max(0, (x1 - x0) * (y1 - y0))


@bp.route("/api/compile-status")
def api_compile_status():
    """Progress of a running compile, so the page never has to block on one."""
    map_dir = _map_dir(request.args.get("map", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    with _PROGRESS_LOCK:
        state = dict(_COMPILE.get(map_dir.name, {"state": "idle"}))
    lots = map_dir / "lots"
    state["cells"] = len(list(lots.glob("*.lotheader"))) if lots.is_dir() else 0
    state["expected"] = _expected_cells(map_dir)
    state["tmx"] = len(list((map_dir / "tmx").glob("*.tmx"))) \
        if (map_dir / "tmx").is_dir() else 0
    # Cells the last compile tried three times and could not do. It steps over
    # them rather than throwing away the hours already spent, so this is how
    # the window knows to offer them again instead of saying "done".
    from tools.compile_map import failed_cells
    state["failed"] = failed_cells(map_dir)
    return jsonify(state)


@bp.route("/api/compile", methods=["POST"])
def api_compile():
    """Convert and compile the whole map without touching WorldEd's menus.

    Uses the patched PZWorldEd_cli.exe, which adds a --generate-map switch that
    runs BMP to TMX and Generate Lots in order. Stock WorldEd has no such
    switch, so without the patched build this falls back to /api/worlded.
    """
    import subprocess

    data = _json_body()
    map_dir = _map_dir(data.get("mapName", ""))
    if map_dir is None:
        return jsonify({"error": "Unknown map."}), 404
    from tools.compile_map import default_backend
    rust = (data.get("backend") or default_backend()) == "rust"
    exe = _worlded_exe(cli=True)
    if exe is None and rust:
        exe = Path("PZWorldEd_cli.exe")        # not used by the rust backend
    if exe is None:
        return jsonify({"error": "Patched PZWorldEd_cli.exe not found — use "
                                 "Open in WorldEd and run the two menu "
                                 "commands instead."}), 400
    pzw = map_dir / f"{map_dir.name}.pzw"
    if not pzw.exists():
        return jsonify({"error": "No .pzw yet — generate the buildings first."}), 400

    # "Compile the cells that failed" rather than the whole town again. A full
    # re-run would skip the batches already on disk anyway, but it walks every
    # one of them to find that out, and on a big map that is minutes before it
    # reaches the handful that matter.
    from tools.compile_map import failed_cells
    only = [f["cells"] for f in failed_cells(map_dir)] if data.get("onlyFailed") else None
    if data.get("onlyFailed") and not only:
        return jsonify({"error": "Nothing is recorded as failed."}), 400

    (map_dir / "tmx").mkdir(exist_ok=True)
    (map_dir / "lots").mkdir(exist_ok=True)

    name = map_dir.name
    with _PROGRESS_LOCK:
        if _COMPILE.get(name, {}).get("state") == "running":
            return jsonify({"started": False, "state": "running"})
        _COMPILE[name] = {"state": "running", "error": None}

    def worker() -> None:
        """Compiling a town takes many minutes.

        Running it inside the request blocked the whole UI - the window simply
        froze until it finished. It runs on its own thread now and the page
        polls /api/compile-status, so the app stays usable and shows progress.

        The work goes out in batches of cells, one short-lived WorldEd
        process each: a single process compiling a whole town never gives
        its memory back and took the machine down at 13.7 GB. See
        tools/compile_map.py.
        """
        from tools import compile_map as compiler

        def note(done: int, total: int, cells: int) -> None:
            with _PROGRESS_LOCK:
                now = _COMPILE.get(name, {})
                # Keep what the detail callback added, and a stop in progress.
                state = "stopping" if now.get("state") == "stopping" else "running"
                _COMPILE[name] = {**now, "state": state, "error": None,
                                  "batch": done, "batches": total}

        def phase(text: str, fraction: float) -> None:
            # The Rust compile has no batches: it says where it is and how far along.
            with _PROGRESS_LOCK:
                now = _COMPILE.get(name, {})
                state = "stopping" if now.get("state") == "stopping" else "running"
                _COMPILE[name] = {**now, "state": state, "error": None,
                                  "phase": text, "fraction": round(fraction, 3)}

        def detail(info: dict) -> None:
            with _PROGRESS_LOCK:
                now = {**_COMPILE.get(name, {"state": "running"}),
                       "workers": info["workers"],
                       "workersStart": info["started_with"],
                       "etaSeconds": info["eta_s"]}
                # Said once, before the first batch, and kept for the run.
                if info.get("incremental"):
                    now["incremental"] = info["incremental"]
                _COMPILE[name] = now

        log.info("compile %s: started", name)
        t0 = time.time()
        try:
            produced = compiler.compile_map(str(map_dir), batch=COMPILE_BATCH,
                                            exe=str(exe), on_progress=note,
                                            on_detail=detail, on_phase=phase,
                                            should_stop=_stopper(name),
                                            only_cells=only,
                                            fresh=bool(data.get("fresh")),
                                            backend="rust" if rust else "worlded")
            if not produced:
                eid = knoxlog.record(None, f"compile {name}: produced no cells")
                with _PROGRESS_LOCK:
                    _COMPILE[name] = {"state": "error", "errorId": eid,
                                      "error": "Compile produced no cells."}
                return
            log.info("compile %s: %d cells in %.0fs", name, produced, time.time() - t0)
            # A compile that stepped over a batch is finished but not whole:
            # installing it gives a map with a hole in it, so the window is
            # told what is missing rather than a plain "done".
            left = compiler.failed_cells(str(map_dir))
            with _PROGRESS_LOCK:
                mapstate.stamp(str(map_dir), "compile", took=time.time() - t0)
                _COMPILE[name] = {"state": "done", "error": None, "failed": left}
            # Pre-generate overview pictures in the background so the In-game 2.5D view
            # loads instantly as soon as the user opens it.
            try:
                from knoxbuild import picture as pictures
                threading.Thread(target=pictures.pictures_of, args=(map_dir,), daemon=True).start()
            except Exception:
                pass
        except knoxstop.Stopped:
            log.info("compile %s: stopped after %.0fs", name, time.time() - t0)
            _done_stopping(name)
            with _PROGRESS_LOCK:
                _COMPILE[name] = {"state": "stopped", "error": None}
            return
        except subprocess.TimeoutExpired as exc:
            eid = knoxlog.record(exc, f"compile {name}: timed out")
            with _PROGRESS_LOCK:
                _COMPILE[name] = {"state": "error", "errorId": eid,
                                  "error": "Compile timed out."}
        except MemoryError as exc:
            eid = knoxlog.record(exc, f"compile {name}: ran out of memory")
            with _PROGRESS_LOCK:
                _COMPILE[name] = {"state": "error", "errorId": eid, "error": (
                    "The compile ran out of memory. Close other programs and press "
                    "Compile again: what it had already made is kept.")}
        except Exception as exc:
            # A MemoryError, among others, has no message: the window said
            # "Compile failed" and nothing else, and the log line ended in a space.
            what = str(exc) or type(exc).__name__
            eid = knoxlog.record(exc, f"compile {name}: failed - {what}")
            with _PROGRESS_LOCK:
                _COMPILE[name] = {"state": "error", "errorId": eid, "error": what}

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"started": True, "expected": _expected_cells(map_dir)})
