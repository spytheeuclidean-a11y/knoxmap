"""KnoxMap — the whole pipeline in one native window.

A real place becomes a playable Project Zomboid map:

    draw an area  ->  terrain  ->  buildings  ->  compile  ->  install

This is a thin shell. It starts the Flask app on a loopback port and shows it in
a native window (Edge WebView2 via pywebview), so the window gets the real
Leaflet map with the rectangle tool, place search and landmark lookup, rather
than a second UI that would drift from the web one.

Compiling uses the patched PZWorldEd_cli.exe that Setup installs (see
worlded/README.md); without it the app opens WorldEd on the project instead.

Run it with:  pythonw knoxmap.py      (or double-click KnoxMap.exe)
On Linux or macOS:  ./knoxmap.sh
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))


TITLE = "KnoxMap — real places into Project Zomboid"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(port: int) -> None:
    from app import app

    # threaded so the long Overpass calls don't block the UI's polling requests.
    app.run(host="127.0.0.1", port=port, debug=False,
            use_reloader=False, threaded=True)


def wait_for(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _ensure_stdio() -> None:
    """pythonw.exe / windowed launches leave sys.stdout and sys.stderr as None;
    redirect them to os.devnull before colorama or logging wraps them."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def main() -> int:
    _ensure_stdio()
    import knoxlog
    knoxlog.setup("window")
    import updater
    # A downloaded update goes in before any of KnoxMap's code is loaded, and
    # the new version starts in a fresh process.
    if updater.apply_staged():
        updater.relaunch()
        return 0
    os.environ["KNOXMAP_WINDOW"] = "1"

    import app  # noqa: F401 - fail here, where it can be reported, not in the thread

    port = free_port()
    threading.Thread(target=serve, args=(port,), daemon=True).start()
    if not wait_for(port):
        raise RuntimeError("the local server did not start within 20 seconds")
    updater.check_in_background()
    # The window is up: say so on Discord, if it was asked to. Everything in
    # knoxpresence fails quietly and on its own thread, so a Discord that is
    # closed, restarting or refusing the socket costs the window nothing.
    try:
        import knoxpresence
        knoxpresence.idle()
    except Exception as exc:  # noqa: BLE001 - presence is never worth a failure
        knoxlog.log.debug("discord presence: %s", exc)

    url = f"http://127.0.0.1:{port}/"
    if in_a_browser():
        return show_in_browser(url)
    try:
        import webview

        # Painted the page's own near-black before anything loads, so the
        # window does not flash white for the second it takes Flask to answer.
        webview.create_window(f"{TITLE} ({knoxlog.version()})", url,
                              width=1440, height=920, min_size=(1000, 680),
                              background_color="#07090B")
        webview.start()
    except Exception as exc:  # noqa: BLE001 - see in_a_browser
        knoxlog.log.warning("no native window (%s); opening a browser instead", exc)
        return show_in_browser(url)
    end_jobs()
    return 0


def _busy_threads() -> list[threading.Thread]:
    """Threads doing a job for the window: requests, and the compile's worker."""
    return [t for t in threading.enumerate()
            if t is not threading.current_thread() and t.is_alive()
            and ("process_request_thread" in t.name or t.name.endswith("(worker)"))]


def end_jobs(grace: float = 15.0) -> None:
    """The window is gone: stop whatever it left running, and leave.

    Python will not exit while a process pool still has work queued, so a
    window closed while a city's buildings were being laid out left KnoxMap
    running unseen for hours - holding memory, and building the same map
    alongside the next window opened on it. Every job is asked to stop, as the
    Stop button does (it keeps what is finished), given a few seconds to do so,
    and whatever is left of its worker processes is ended with it.
    """
    import multiprocessing

    import knoxlog

    if not _busy_threads() and not multiprocessing.active_children():
        return                      # nothing running: leave the usual way
    from web import jobs
    jobs.stop_all()
    # Until the jobs have stopped and saved what they had. A stopped pool's
    # worker processes idle on after it, so they are not waited for.
    deadline = time.time() + grace
    while time.time() < deadline and _busy_threads():
        time.sleep(0.25)
    for child in multiprocessing.active_children():
        child.terminate()
    knoxlog.log.info("window closed: running jobs stopped")
    import logging
    try:
        logging.shutdown()
    except Exception:  # noqa: BLE001 - pythonw has None stdout/stderr under colorama
        pass
    os._exit(0)


def in_a_browser() -> bool:
    """Whether to skip the native window and use the player's browser.

    KnoxMap is a web page either way, so a browser tab is a perfectly good
    window - and on Linux it is often the only one there is. pywebview needs
    a system toolkit behind it (WebKitGTK through PyGObject, or Qt WebEngine)
    that pip cannot install, and a machine without one has no window at all.
    KNOXMAP_BROWSER=1 forces this on any system.
    """
    if os.environ.get("KNOXMAP_BROWSER") == "1":
        return True
    if os.name == "nt" or sys.platform == "darwin":
        return False        # WebView2 and WKWebView ship with the system
    try:
        import webview       # noqa: F401
    except ImportError:
        return True
    # pywebview picks its toolkit at import time and raises on start when
    # there is none; asking it now says so before the page is served.
    try:
        from webview import guilib
        guilib.initialize()
    except Exception:        # noqa: BLE001 - no toolkit, or a broken one
        return True
    return False


def show_in_browser(url: str) -> int:
    """Serve KnoxMap and open it in the default browser, in the foreground.

    The window is what usually keeps the process alive; without one this
    waits instead, so closing the terminal is what ends KnoxMap.
    """
    import webbrowser

    # Downloads go through the browser here, not through /api/save, which is
    # the app window's way round having nowhere to put a file.
    os.environ["KNOXMAP_WINDOW"] = "0"
    print(f"KnoxMap is running at {url}", flush=True)
    print("Leave this window open while you use it; press Ctrl+C to stop.", flush=True)
    try:
        webbrowser.open(url)
    except Exception:        # noqa: BLE001 - no browser configured; the URL is printed
        pass
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        end_jobs()
        return 0


def report_crash() -> None:
    """pythonw has no console, so a failed start would just vanish.

    Write the traceback next to the app and say where it is in a message box.
    """
    import traceback

    where = BASE_DIR / "logs" / "knoxmap.log"
    try:
        import knoxlog
        knoxlog.setup("window")
        eid = " as " + knoxlog.record(sys.exc_info()[1], "KnoxMap could not start")
    except Exception:  # noqa: BLE001 - the logger itself may be what broke
        eid = ""
        where = BASE_DIR / "knoxmap_error.log"
        where.write_text(traceback.format_exc(), encoding="utf-8")
    setup = "Setup.bat" if os.name == "nt" else "./setup.sh"
    text = (f"KnoxMap could not start:\n\n{sys.exc_info()[1]}\n\n"
            f"Details were saved to {where}{eid}.\n"
            f"Running {setup} again fixes most problems. If it does not, post "
            "that file in #bug-reports on the KnoxMap Discord.")
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "KnoxMap", 0x10)
    except Exception:  # noqa: BLE001 - not on Windows; the log is enough
        print(text, file=sys.stderr)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        report_crash()
        raise SystemExit(1)
