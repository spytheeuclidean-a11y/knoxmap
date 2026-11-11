"""KnoxMap's logs: one folder, everything that goes wrong, and a report to send.

Before this, a failure left at most one line in the window - "Generation
failed" or "<!doctype ... is not valid JSON" - and nothing on disk, so a bug
report on the Discord was a screenshot of a message that said nothing. Now:

* logs/knoxmap.log records every run: a header describing the PC (Windows
  version and code page, Python, memory, disk, where the game and the map tools
  are), each step of generating, building, compiling and installing, and the
  full traceback of every error, whether it happened in a request, a background
  compile, the page itself or at start-up. It rolls over at 2 MB, keeping five.
* Each error gets a short id (E-7F3A2C) that is shown in the app next to the
  message and written beside the traceback, so "I got E-7F3A2C" finds it.
* WorldEd's own output from every compile batch is kept in logs/worlded/.
* Setup writes logs/setup.log.
* report_zip() bundles all of it with a system summary into one zip for
  #bug-reports, with the user's name taken out of every path.
"""
from __future__ import annotations

import io
import json
import logging
import logging.handlers
import os
import platform
import re
import secrets
import sys
import threading
import time
import traceback
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# KNOXMAP_LOG_DIR moves them, so the self-test does not write into a real log.
LOG_DIR = Path(os.environ.get("KNOXMAP_LOG_DIR") or BASE_DIR / "logs")
MAIN_LOG = LOG_DIR / "knoxmap.log"
WORLDED_DIR = LOG_DIR / "worlded"
KEEP_WORLDED_LOGS = 40
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 5

log = logging.getLogger("knoxmap")
_ready = threading.Lock()
_configured: list[str] = []


def setup(program: str = "app", console: bool = False) -> logging.Logger:
    """Send KnoxMap's logging to logs/knoxmap.log (once per process) and write
    the header for this run."""
    with _ready:
        if _configured:
            return log
        _configured.append(program)
        try:
            LOG_DIR.mkdir(exist_ok=True)
            handler: logging.Handler = logging.handlers.RotatingFileHandler(
                MAIN_LOG, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8",
                delay=True)
        except OSError:
            # A read-only folder (a zip opened in place): log nowhere rather
            # than not start.
            handler = logging.NullHandler()
        fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s",
                                "%Y-%m-%d %H:%M:%S")
        handler.setFormatter(fmt)
        log.addHandler(handler)
        if console:
            stream = logging.StreamHandler()
            stream.setFormatter(fmt)
            log.addHandler(stream)
        log.setLevel(logging.INFO)
        log.propagate = False
        _install_hooks()
    log.info("=" * 70)
    log.info("KnoxMap %s started (%s)", version(), program)
    for line in system_summary().splitlines():
        log.info("  %s", line)
    return log


def _install_hooks() -> None:
    """Uncaught errors anywhere - the main thread, a compile thread - go to the
    log as well as wherever they went before."""
    previous = sys.excepthook

    def on_error(kind, value, tb):
        log.critical("Uncaught error\n%s", "".join(traceback.format_exception(kind, value, tb)))
        previous(kind, value, tb)

    sys.excepthook = on_error
    previous_thread = threading.excepthook

    def on_thread_error(args):
        if args.exc_type is not SystemExit:
            log.critical("Uncaught error in thread %s\n%s",
                         getattr(args.thread, "name", "?"),
                         "".join(traceback.format_exception(args.exc_type, args.exc_value,
                                                            args.exc_traceback)))
        previous_thread(args)

    threading.excepthook = on_thread_error


def error_id() -> str:
    return "E-" + secrets.token_hex(3).upper()


def record(exc: BaseException | None = None, where: str = "", **context) -> str:
    """Log an error with its traceback and context. Returns the id to show."""
    eid = error_id()
    detail = ""
    if exc is not None:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    extra = " ".join(f"{k}={_short(v)}" for k, v in context.items() if v not in (None, ""))
    log.error("%s %s %s\n%s", eid, where, extra, detail)
    return eid


def _short(value, limit: int = 300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


# --- the PC this is running on ---------------------------------------------

def version() -> str:
    try:
        for line in (BASE_DIR / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
            # "1.3.9", and also "1.3.9 mc1" - a release for one system only,
            # which carries the platform and its number after the version.
            m = re.match(r"##\s+(\d[\w.]*(?:\s+[a-z]+\d*)?)", line)
            if m:
                return m.group(1)
    except OSError:
        pass
    return "unknown"


def memory_status() -> tuple[int, int, int] | None:
    """(total, free, room this process has left) in bytes, or None elsewhere.

    The last one is the address space: on a 32-bit Python it is about 2 GB
    however much memory the PC has, which is what a big map runs out of.
    """
    if os.name != "nt":
        return _memory_status_posix()
    try:
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("pagetotal", ctypes.c_ulonglong), ("pageavail", ctypes.c_ulonglong),
                        ("virttotal", ctypes.c_ulonglong), ("virtavail", ctypes.c_ulonglong),
                        ("extavail", ctypes.c_ulonglong)]
        st = Status()
        st.length = ctypes.sizeof(Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return int(st.total), int(st.avail), int(st.virtavail)
    except Exception:  # noqa: BLE001 - not Windows
        pass
    return None


def _memory_status_posix() -> tuple[int, int, int] | None:
    """The same three numbers from /proc/meminfo, on Linux."""
    try:
        values = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                key, _, rest = line.partition(":")
                values[key] = int(rest.split()[0]) * 1024
        total = values.get("MemTotal", 0)
        free = values.get("MemAvailable", values.get("MemFree", 0))
        if total:
            # 64-bit address space is effectively unlimited here; a 32-bit
            # build is capped, which is what the room figure is for.
            room = free if sys.maxsize > 2 ** 32 else min(free, 2 ** 31)
            return total, free, room
    except (OSError, ValueError, IndexError):
        pass
    return None


def _memory() -> str:
    status = memory_status()
    if status:
        total, free, _room = status
        return f"{total / 2**30:.1f} GB, {free / 2**30:.1f} GB free"
    return "unknown"


def _road_router() -> str:
    """Whether knoxroute is here: without it one road layout is a hundred times slower,
    so a report about a slow map should say at once which it was."""
    try:
        from generator.roadgraph import rustsearch
        return "found" if rustsearch.available() else "not found (slow roads)"
    except Exception:  # noqa: BLE001 - the summary must never fail
        return "unknown"


def system_summary() -> str:
    import locale
    import shutil

    lines = [
        f"KnoxMap:  {version()}",
        f"OS:       {platform.platform()} ({platform.version()})",
        f"Python:   {sys.version.split()[0]} {platform.architecture()[0]}, "
        f"UTF-8 mode {'on' if sys.flags.utf8_mode else 'OFF'}, "
        f"code page {locale.getpreferredencoding(False)}",
        f"Memory:   {_memory()}",
    ]
    try:
        free = shutil.disk_usage(BASE_DIR).free / 2**30
        lines.append(f"Disk:     {free:.1f} GB free where KnoxMap is")
    except OSError:
        pass
    try:
        import knoxpaths
        lines += [
            f"Game:     {knoxpaths.pz_install_dir() or 'not found'}"
            f" (Build 42: {knoxpaths.is_build42(knoxpaths.pz_install_dir())})",
            f"Tools:    {knoxpaths.mapping_tools_dir() or 'not installed'}",
            f"Compiler: {'found' if knoxpaths.worlded_cli() else 'not found'}",
            f"Road router: {_road_router()}",
            f"Erika's Tiles: {'yes' if knoxpaths.erikas_tiles_ready() else 'no'}, "
            f"Elevators: {'yes' if knoxpaths.elevators_mod_installed() else 'no'}, "
            f"Spawn Selector: {'yes' if knoxpaths.spawn_selector_installed() else 'no'}",
        ]
    except Exception as exc:  # noqa: BLE001 - the summary must never fail
        lines.append(f"Paths:    could not be checked ({exc})")
    return redact("\n".join(lines))


# --- WorldEd's output --------------------------------------------------------

def save_tool_output(tool: str, map_name: str, label: str, returncode: int,
                     stdout: str, stderr: str) -> Path | None:
    """Keep a compile batch's own output. Returns the file."""
    try:
        WORLDED_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = WORLDED_DIR / f"{stamp}_{_safe(map_name)}_{_safe(label)}.log"
        path.write_text(f"{tool} exit code {returncode} ({explain_exit(returncode)})\n\n"
                        f"--- stdout ---\n{stdout or ''}\n--- stderr ---\n{stderr or ''}\n",
                        encoding="utf-8", errors="replace")
        old = sorted(WORLDED_DIR.glob("*.log"))
        for stale in old[:-KEEP_WORLDED_LOGS]:
            stale.unlink(missing_ok=True)
        return path
    except OSError:
        return None


# Windows reports a crashed program by the exception that killed it.
_EXIT_CODES = {
    0: "finished",
    -1073741819: "crashed: access violation (0xC0000005)",
    3221225477: "crashed: access violation (0xC0000005)",
    -1073741571: "crashed: stack overflow (0xC00000FD)",
    3221225725: "crashed: stack overflow (0xC00000FD)",
    -1073740791: "crashed: internal error (0xC0000409)",
    3221226505: "crashed: internal error (0xC0000409)",
    -1073741515: "could not start: a DLL is missing (0xC0000135)",
    3221225781: "could not start: a DLL is missing (0xC0000135)",
    -1073741510: "closed from outside (0xC000013A)",
    3221225786: "closed from outside (0xC000013A)",
    -1073741801: "ran out of memory (0xC0000017)",
    3221225495: "ran out of memory (0xC0000017)",
    65: "stalled or timed out",
    124: "hung and was stopped",
}


def explain_exit(code: int) -> str:
    return _EXIT_CODES.get(code, "failed")


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:60] or "x"


# --- the report --------------------------------------------------------------

def redact(text: str) -> str:
    """The user's name out of paths: C:\\Users\\alice\\... becomes C:\\Users\\<you>\\..."""
    home = str(Path.home())
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    for form in {home, home.replace("\\", "/")}:
        if form and len(form) > 3:
            text = text.replace(form, "<home>")
    text = re.sub(r"(?i)([\\/]Users[\\/])[^\\/\s\"']+", r"\1<you>", text)
    if user and len(user) > 2:
        text = re.sub(re.escape(user), "<you>", text, flags=re.I)
    return text


def report_zip(output_dir: Path | None = None, recent_maps: int = 3) -> bytes:
    """Everything a bug report needs, in one zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("system.txt", system_summary() + "\n")
        for path in sorted(LOG_DIR.glob("knoxmap.log*")) + sorted(LOG_DIR.glob("setup.log*")):
            z.writestr(f"logs/{path.name}", redact(_tail(path)))
        for path in sorted(WORLDED_DIR.glob("*.log"))[-10:]:
            z.writestr(f"logs/worlded/{path.name}", redact(_tail(path)))
        # WorldEd's own logs: the one place that says why it would not open a
        # project, which its console output does not.
        try:
            import knoxpaths
            tools = knoxpaths.mapping_tools_dir()
            if tools:
                for path in sorted((tools / "settings" / "logs").glob("PZWorldEd-*.log"))[-5:]:
                    z.writestr(f"logs/worlded-app/{path.name}", redact(_tail(path, 1024 * 1024)))
        except Exception:  # noqa: BLE001 - the report goes out without them
            pass
        old_log = BASE_DIR / "knoxmap_error.log"
        if old_log.exists():
            z.writestr("logs/knoxmap_error.log", redact(_tail(old_log)))
        if output_dir and output_dir.is_dir():
            maps = sorted((d for d in output_dir.iterdir() if d.is_dir()),
                          key=lambda d: d.stat().st_mtime, reverse=True)[:recent_maps]
            for d in maps:
                # _left_out.csv is why each footprint did not become a
                # building: the first thing to look at when somebody reports a
                # hole in their town (tools/why_no_building.py reads it).
                for name in (f"{d.name}_info.json", "settings.json",
                             f"{d.name}_population.json", f"{d.name}_left_out.csv"):
                    p = d / name
                    if p.exists():
                        z.writestr(f"maps/{d.name}/{name}", redact(_tail(p)))
                listing = "\n".join(f"{f.name}\t{f.stat().st_size}" for f in sorted(d.iterdir())
                                    if f.is_file())
                lots = d / "lots"
                count = len(list(lots.glob("*.lotheader"))) if lots.is_dir() else 0
                z.writestr(f"maps/{d.name}/files.txt", f"{listing}\nlots: {count} cells\n")
    return buf.getvalue()


def _tail(path: Path, limit: int = 3 * 1024 * 1024) -> str:
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - limit))
            return f.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return f"(could not read: {exc})"


def open_folder(path=None) -> bool:
    """Show a file or folder in Explorer; the logs folder by default."""
    import subprocess

    try:
        if path is None:
            LOG_DIR.mkdir(exist_ok=True)
            os.startfile(str(LOG_DIR))  # type: ignore[attr-defined]
            return True
        path = Path(path)
        if os.name != "nt":
            # No Explorer: open the folder it is in with whatever the desktop
            # uses. Nothing is selected, which is as close as this gets.
            folder = path if path.is_dir() else path.parent
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, str(folder)])
            return True
        if path.is_dir():
            os.startfile(str(path))     # type: ignore[attr-defined]
        else:
            # Explorer wants the comma joined to the switch, and the path as
            # its own argument, or it opens Documents instead.
            subprocess.Popen(["explorer", "/select,", str(path)])
        return True
    except (OSError, AttributeError):
        return False
