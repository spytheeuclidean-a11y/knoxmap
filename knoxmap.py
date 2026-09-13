"""KnoxMap — the whole pipeline in one native window.

A real place becomes a playable Project Zomboid map:

    draw an area  ->  terrain  ->  buildings  ->  compile  ->  install

This is a thin shell. It starts the Flask app on a loopback port and shows it in
a native window (Edge WebView2 via pywebview), so the window gets the real
Leaflet map with the rectangle tool, place search and landmark lookup, rather
than a second UI that would drift from the web one.

Compiling uses the patched PZWorldEd_cli.exe that Setup installs (see
worlded/README.md); without it the app opens WorldEd on the project instead.

Run it with:  pythonw knoxmap.py      (or double-click KnoxMap.bat)
"""
from __future__ import annotations

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


def main() -> int:
    import webview

    import app  # noqa: F401 - fail here, where it can be reported, not in the thread

    port = free_port()
    threading.Thread(target=serve, args=(port,), daemon=True).start()
    if not wait_for(port):
        raise RuntimeError("the local server did not start within 20 seconds")

    # Painted the page's own near-black before anything loads, so the window
    # does not flash white for the second it takes Flask to answer.
    webview.create_window(TITLE, f"http://127.0.0.1:{port}/",
                          width=1440, height=920, min_size=(1000, 680),
                          background_color="#07090B")
    webview.start()
    return 0


def report_crash() -> None:
    """pythonw has no console, so a failed start would just vanish.

    Write the traceback next to the app and say where it is in a message box.
    """
    import traceback

    log = BASE_DIR / "knoxmap_error.log"
    log.write_text(traceback.format_exc(), encoding="utf-8")
    text = (f"KnoxMap could not start:\n\n{sys.exc_info()[1]}\n\n"
            f"Details were saved to {log}.\n"
            "Running Setup.bat again fixes most problems.")
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
