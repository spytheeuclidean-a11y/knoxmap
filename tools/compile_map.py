"""Compile a Knoxify project to .lot files, a batch of cells at a time.

    python tools/compile_map.py output/mytown [--batch 4]

WorldEd's lot export never releases what it loads: every cell adds to the map
and tileset caches, so one process compiling a whole town climbs without limit.
A 572-cell map reached 13.7 GB and had done under a sixth of the work before the
machine started thrashing.

So the work is handed over in batches, each to a fresh PZWorldEd_cli process
which exits and gives the memory back. Output accumulates in the same lots
folder, because each batch only generates the cells it was given.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent import futures
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import knoxlog  # noqa: E402
import knoxpaths  # noqa: E402
import knoxstop  # noqa: E402


# A batch is a minute or two of work, three at the very most for the one that
# converts the bitmap. One that has run for half an hour is hung (WorldEd
# waiting on something that will not come), not slow; waiting two hours for it
# held the whole compile up and then threw away the run.
BATCH_TIMEOUT = 30 * 60
# How often a running batch is asked whether the window wants it stopped.
STOP_POLL_SECONDS = 1.0


# Off Windows the tools are started by `wine`, which is a launcher: it hands
# the program to wineserver and the program is not its child. Killing the
# launcher leaves WorldEd running, so a batch is given a process group of its
# own and the whole group is ended together.
_OWN_GROUP = os.name != "nt"


def _end_batch(proc) -> None:
    """End a batch, and anything it started with it. Never waits for ever."""
    def send(hard: bool) -> None:
        try:
            if _OWN_GROUP:
                os.killpg(os.getpgid(proc.pid),
                          signal.SIGKILL if hard else signal.SIGTERM)
            elif hard:
                proc.kill()
            else:
                proc.terminate()
        except OSError:            # already gone, or not ours to signal
            pass

    for hard, grace in ((False, 20), (True, 10)):
        send(hard)
        try:
            proc.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    class _HiddenDesktopProcess:
        """Runs PZWorldEd on an isolated Windows desktop.

        Qt GUI windows and secondary dialogs (e.g. 'Generate Lots' popups)
        belong to this hidden desktop and are physically impossible for DWM
        to composite onto the user's display, guaranteeing 0 ms visibility
        and zero flashes without any polling overhead.
        
        A background thread proxies error popups (or long-hanging dialogs)
        to the user's default desktop so they can be dismissed.
        """
        def __init__(self, cmd, stdout_f, stderr_f, env=None):
            self.cmd = cmd
            self._desk_name = "KnoxHiddenDesktop"
            self._hdesk = ctypes.windll.user32.CreateDesktopW(self._desk_name, None, None, 0, 0x01FF, None)

            h_out = msvcrt.get_osfhandle(stdout_f.fileno())
            h_err = msvcrt.get_osfhandle(stderr_f.fileno())
            ctypes.windll.kernel32.SetHandleInformation(h_out, 1, 1)
            ctypes.windll.kernel32.SetHandleInformation(h_err, 1, 1)

            si = _STARTUPINFOW()
            si.cb = ctypes.sizeof(_STARTUPINFOW)
            si.lpDesktop = self._desk_name
            si.dwFlags = 0x00000100 | 0x00000001  # STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
            si.hStdInput = ctypes.windll.kernel32.GetStdHandle(-10)
            si.hStdOutput = h_out
            si.hStdError = h_err

            pi = _PROCESS_INFORMATION()
            flags = 0
            env_buf = None
            if env:
                flags |= 0x00000400  # CREATE_UNICODE_ENVIRONMENT
                env_str = "".join(f"{k}={v}\0" for k, v in sorted(env.items())) + "\0"
                env_buf = ctypes.create_unicode_buffer(env_str)

            cmd_line = subprocess.list2cmdline([str(c) for c in cmd]) if isinstance(cmd, (list, tuple)) else str(cmd)
            ok = ctypes.windll.kernel32.CreateProcessW(
                None, cmd_line, None, None, True, flags, env_buf, None,
                ctypes.byref(si), ctypes.byref(pi)
            )
            if not ok:
                err = ctypes.GetLastError()
                raise OSError(f"CreateProcessW failed: {err}")

            self._hProcess = pi.hProcess
            self._hThread = pi.hThread
            self.pid = pi.dwProcessId
            self.returncode = None
            
            # Start error popup proxy thread
            self._monitor_thread = __import__("threading").Thread(target=self._monitor_popups, daemon=True)
            self._monitor_thread.start()

        def _monitor_popups(self):
            seen_times = {}
            proxied = set()
            
            EnumDesktopWindows = ctypes.windll.user32.EnumDesktopWindows
            EnumDesktopWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            
            def enum_proc(hwnd, lParam):
                if not ctypes.windll.user32.IsWindowVisible(hwnd):
                    return True
                if hwnd in proxied:
                    return True
                    
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                
                # Ignore windows with no title, or known progress dialogs
                if not title or title == "Generate Lots":
                    return True
                
                now = time.time()
                if hwnd not in seen_times:
                    seen_times[hwnd] = now
                    
                elapsed = now - seen_times[hwnd]
                title_lower = title.lower()

                # Only a window that says it is an error is worth a popup. A
                # progress window ("Loading resources") stays open for minutes
                # on a big map, and closing it would abort the batch, so a long
                # one is left alone.
                if "error" in title_lower or "warning" in title_lower or "exception" in title_lower:
                    proxied.add(hwnd)
                    # Said in the log, not in a popup: a batch that hits one is
                    # retried, and with several running a popup each is a flood.
                    # The window is closed so the batch can end and be retried.
                    print(f"  (WorldEd showed '{title}'; closing it, the batch "
                          f"will be retried if it failed)", flush=True)
                    ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0) # WM_CLOSE
                elif elapsed > 60.0 and hwnd not in proxied:
                    proxied.add(hwnd)
                    print(f"  (WorldEd window '{title}' open for {elapsed:.0f}s; leaving it)",
                          flush=True)

                return True
                
            c_enum_proc = EnumDesktopWindowsProc(enum_proc)
            
            while self._hdesk is not None and self.returncode is None:
                # EnumDesktopWindows blocks until all windows are enumerated
                try:
                    EnumDesktopWindows(self._hdesk, c_enum_proc, 0)
                except Exception:
                    pass
                time.sleep(1.0)

        def poll(self):
            if self.returncode is not None:
                return self.returncode
            code = wintypes.DWORD()
            if ctypes.windll.kernel32.GetExitCodeProcess(self._hProcess, ctypes.byref(code)):
                if code.value == 259:  # STILL_ACTIVE
                    return None
                self.returncode = code.value
                self._cleanup()
                return self.returncode
            return None

        def wait(self, timeout=None):
            if self.returncode is not None:
                return self.returncode
            ms = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
            res = ctypes.windll.kernel32.WaitForSingleObject(self._hProcess, ms)
            if res == 0:  # WAIT_OBJECT_0
                return self.poll()
            elif res == 0x00000102:  # WAIT_TIMEOUT
                raise subprocess.TimeoutExpired(self.cmd, timeout)
            return self.poll()

        def terminate(self):
            if self._hProcess:
                ctypes.windll.kernel32.TerminateProcess(self._hProcess, 1)

        def kill(self):
            self.terminate()

        def _cleanup(self):
            if self._hThread:
                try:
                    ctypes.windll.kernel32.CloseHandle(self._hThread)
                except Exception:
                    pass
                self._hThread = None
            if self._hProcess:
                try:
                    ctypes.windll.kernel32.CloseHandle(self._hProcess)
                except Exception:
                    pass
                self._hProcess = None
            if self._hdesk:
                try:
                    ctypes.windll.user32.CloseDesktop(self._hdesk)
                except Exception:
                    pass
                self._hdesk = None

        def __del__(self):
            self._cleanup()


def _run_batch(cmd, should_stop, started: float):
    """Run one WorldEd batch, watching for a stop while it works.

    subprocess.run waits for the process and nothing else, so a compile could
    only be stopped between batches - and one batch of a big map is minutes.
    This waits in short steps instead, and when the window asks it to stop it
    closes WorldEd down and raises.

    WorldEd's output goes to files rather than pipes, and what is waited for
    is the process, not the output. Under Wine the pipes are inherited by
    wineserver, which outlives everything it runs: after WorldEd died the
    pipes stayed open, so reading them to the end never ended. The window sat
    on "compiling" with nothing running at all, and Stop could not get out of
    it either, because closing the batch down read those same pipes. Waiting
    on the process alone cannot get stuck that way, on any system.
    """
    def scratch():
        return tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace")

    with scratch() as out_f, scratch() as err_f:
        if sys.platform == "win32":
            proc = _HiddenDesktopProcess(cmd, out_f, err_f, env=knoxpaths.tool_env())
        else:
            kwargs = {}
            if _OWN_GROUP:
                kwargs["start_new_session"] = True
            proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f,
                                    env=knoxpaths.tool_env(),
                                    **kwargs)

        def said() -> tuple[str, str]:
            """Whatever WorldEd wrote, however it ended."""
            texts = []
            for handle in (out_f, err_f):
                try:
                    handle.seek(0)
                    texts.append(handle.read())
                except OSError:
                    texts.append("")
            return texts[0], texts[1]

        while True:
            try:
                proc.wait(timeout=STOP_POLL_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            else:
                out, err = said()
                return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
            if should_stop is not None and should_stop():
                _end_batch(proc)
                raise knoxstop.Stopped("the compile")
            if time.time() - started > BATCH_TIMEOUT:
                _end_batch(proc)
                raise subprocess.TimeoutExpired(cmd, BATCH_TIMEOUT,
                                                output=said()[0], stderr=said()[1])


DEFAULT_EXE = knoxpaths.worlded_cli() or Path("PZWorldEd_cli.exe")


# WorldEd's BMP to TMX cannot load a landscape bitmap past about 2^28 pixels
# ("The image file couldn't be loaded"): 16500 x 16500 fails, 13800 x 18600
# (257 million) compiles. Measured with a plain bitmap of each size, so it is
# the size that matters, not what is drawn on it.
WORLDED_MAX_PIXELS = 2 ** 28


def bitmap_pixels(width: int, height: int) -> int:
    """Pixels in the bitmap of a map this many tiles across: the renderer pads each
    side up to a whole 300-tile cell."""
    return -(-width // 300) * 300 * (-(-height // 300) * 300)


def scale_that_fits(width: int, height: int, meters_per_tile: float) -> int | None:
    """The smallest whole-metre scale at which a map drawn at this one fits
    WorldEd, or None if no scale up to 100 does."""
    for m in range(max(1, int(meters_per_tile) + 1), 101):
        k = meters_per_tile / m
        if bitmap_pixels(int(width * k), int(height * k)) <= WORLDED_MAX_PIXELS:
            return m
    return None


def too_large_note(project: Path) -> str:
    """Why a compile that failed to load the bitmap may have, if it is too big for
    WorldEd; empty when it is not."""
    try:
        cells_x, cells_y = world_size(Path(project) / f"{Path(project).name}.pzw")
    except OSError:
        return ""
    px = cells_x * 300 * cells_y * 300
    if px <= WORLDED_MAX_PIXELS:
        return ""
    return (f" This map is {cells_x * 300} x {cells_y * 300} tiles ({px / 1e6:.0f} million), "
            f"and WorldEd cannot load a bitmap past {WORLDED_MAX_PIXELS / 1e6:.0f} million. "
            f"Make it again with a larger metres-per-tile or a smaller area.")


def world_size(pzw: Path) -> tuple[int, int]:
    text = pzw.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'<world version="[^"]*" width="(\d+)" height="(\d+)"', text)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _tool_path(path: Path) -> str:
    """A file as the map tools name it: forward slashes on Windows, and
    otherwise what the compiler in use can open - its own name for a native
    build, a Wine name for the Windows one."""
    if os.name == "nt":
        return path.as_posix()
    return knoxpaths.tool_path(path)


def assign_converted_maps(pzw: Path) -> int:
    """Point every cell that has a converted .tmx at it. Returns how many.

    Each batch is a fresh WorldEd process reading the project from disk. The
    first one converts the whole bitmap to .tmx maps, but it never saves which
    map belongs to which cell, so every later batch found map="" everywhere
    and converted the whole town again before compiling its own few cells.
    Writing the assignments back after a batch lets the rest skip straight to
    compiling.
    """
    text = pzw.read_text(encoding="utf-8", errors="replace")
    origin = re.search(r'<worldOrigin origin="(-?\d+),(-?\d+)"', text)
    bmp = re.search(r'<bmp path="([^"]+)"', text)
    if not (origin and bmp):
        return 0
    ox, oy = int(origin.group(1)), int(origin.group(2))
    base = Path(bmp.group(1)).stem
    # The converted maps sit in the project's own tmx folder. The path the
    # .pzw carries is the one the tools read, which under Wine is a Z: name
    # that means nothing here - so the file is looked for by its real name
    # and written back by the tools' one (knoxbuild/world.py _tool_path).
    folder = pzw.parent / "tmx"
    count = 0

    def fill(m):
        nonlocal count
        x, y = int(m.group(1)), int(m.group(2))
        path = folder / f"{base}_{ox + x}_{oy + y}.tmx"
        if not path.exists():
            return m.group(0)
        count += 1
        return f'<cell x="{x}" y="{y}" map="{_tool_path(path)}"'

    new = re.sub(r'<cell x="(\d+)" y="(\d+)" map=""', fill, text)
    if count:
        pzw.write_text(new, encoding="utf-8")
    return count


def clear_stale(project: Path) -> None:
    """Delete compiled output that is older than what it was compiled from.

    The patched CLI skips a batch whose cells all have a .lotheader, and skips
    converting a cell that already has a .tmx, so that a stopped compile picks
    up where it left off. That also meant a map rebuilt with new buildings or
    terrain "compiled" in seconds and kept every old lot. Output newer than
    its inputs is kept, so resuming still works.

    The .pzw is not an input here: assign_converted_maps rewrites it after the
    first batch, which would make every finished compile look stale.
    """
    def newest(paths) -> float:
        return max((p.stat().st_mtime for p in paths), default=0.0)

    lots, tmx = project / "lots", project / "tmx"
    terrain = newest(project.glob("*.bmp"))
    # The rules are baked in when a bitmap is converted, so new rules (Setup
    # adding street furniture, say) need the conversion done again too.
    settings_time = 0.0
    tools = knoxpaths.mapping_tools_dir()
    if tools:
        terrain = max(terrain, newest(p for p in (tools / "config" / "Rules.txt",
                                                  tools / "config" / "Blends.txt")
                                      if p.exists()))
        # Editor settings (the game folder, whose tile definitions shape every
        # window opening) change what the lots come out as.
        ini = tools / "settings" / "PZTools.ini"
        if ini.exists():
            settings_time = ini.stat().st_mtime
    inputs = max(terrain, newest((project / "buildings").glob("*.tbx")),
                 settings_time)
    written = [p for p in lots.glob("*") if p.is_file()] if lots.is_dir() else []
    if written and min(p.stat().st_mtime for p in written) < inputs:
        for p in written:
            p.unlink()
    converted = list(tmx.glob("*.tmx")) if tmx.is_dir() else []
    if converted and min(p.stat().st_mtime for p in converted) < terrain:
        for p in converted:
            p.unlink()
        # And forget them, or WorldEd stops on "missing assigned TMX".
        pzw = project / f"{project.name}.pzw"
        if pzw.exists():
            text = pzw.read_text(encoding="utf-8", errors="replace")
            unassigned = re.sub(r'(<cell x="\d+" y="\d+" map=")[^"]*\.tmx"', r'\1"', text)
            pzw.write_text(unassigned, encoding="utf-8")


# A batch that fails is tried again before the compile gives up on it. Most
# of what goes wrong in WorldEd's lot export goes wrong once - a texture read
# that returned short, a file still held open - and the second run of the same
# cells comes out clean. Three attempts, because a fourth has never helped.
#
# Nothing is deleted between attempts. The patched CLI skips a batch only when
# every one of its cells already has a .lotheader, so a batch that died
# part-way still has cells pending and is redone; and the lot files are named
# in 256-tile cells against the world origin, not the 300-tile cells a batch
# is given, so working out which files belong to a batch is a good way to
# delete somebody else's finished work.
BATCH_ATTEMPTS = 3

# What a compile leaves behind about the cells it could not do, for the
# window to offer and for a later run to pick up.
FAILURES_FILE = "compile_failures.json"

# One compile of a project at a time. The window already refuses a second
# while one is running, but the command line does not know about the window,
# and two compiles of one project write the same lots folder and the same
# .pzw: assign_converted_maps rewrites it after every batch.
LOCK_FILE = ".compiling"


def _pid_alive(pid: int) -> bool:
    """Whether a process is still running.

    Only used to tell a compile that is still going from a lock left behind
    by one that crashed, so "cannot tell" counts as alive: refusing to start
    is recoverable and two compiles in one folder are not.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False          # gone, or never ours to look at
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True               # somebody else's, but running
    except OSError:
        return True
    return True


@contextlib.contextmanager
def _only_one(project: Path, run: str):
    """Hold this project's compile lock for the length of a run."""
    path = project / LOCK_FILE
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        held = None
    if isinstance(held, dict):
        pid = int(held.get("pid") or 0)
        if pid != os.getpid() and _pid_alive(pid):
            raise RuntimeError(
                f"{project.name} is already being compiled (run {held.get('run')}, "
                f"process {pid}). Wait for that to finish, or stop it, rather than "
                f"running two - they write the same files.")
        knoxlog.log.warning("compile %s [%s]: cleared a lock left by run %s (process "
                            "%s is gone)", project.name, run, held.get("run"), pid)
    try:
        path.write_text(json.dumps({"pid": os.getpid(), "run": run,
                                    "started": time.time()}), encoding="utf-8")
    except OSError:
        pass                      # a lock that cannot be written is not a reason to stop
    try:
        yield
    finally:
        try:
            path.unlink()
        except OSError:
            pass


def failed_cells(project_dir: str | Path) -> list[dict]:
    """The batches the last compile of this project could not do.

    Each is {"cells": [x0, y0, x1, y1], "exit": int, "why": str, "log": str}.
    Empty when the last compile did the lot, which is the usual answer.
    """
    try:
        with open(Path(project_dir) / FAILURES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    found = data.get("failed") if isinstance(data, dict) else None
    return [f for f in found if isinstance(f, dict)] if isinstance(found, list) else []


def _record_failures(project: Path, run: str, batch: int, failures: list[dict]) -> None:
    path = project / FAILURES_FILE
    if not failures:
        try:
            path.unlink()         # a clean run leaves nothing behind
        except OSError:
            pass
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"run": run, "when": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "batch": batch, "failed": failures}, f, indent=2)
    except OSError:
        knoxlog.log.warning("compile %s [%s]: could not write %s",
                            project.name, run, FAILURES_FILE)


def _why(proc) -> str:
    """The lines of a batch's output that say what went wrong, rather than
    the last three, which after a crash are thread shutdown chatter."""
    lines = (proc.stderr or proc.stdout or "").strip().splitlines()
    said = [ln for ln in lines
            if re.search(r"CRITICAL|ERROR|FATAL|Could not|failed", ln)]
    return " | ".join((said or lines)[-3:])


# Each WorldEd process peaks around a gigabyte on a 4x4 batch (see COMPILE_BATCH
# in app.py), so how many may run together is bounded by memory as much as by
# cores. "compile_workers" in knoxmap_config.json overrides this; 1 is the old
# one-at-a-time behaviour.
GB_PER_WORKER = 3.0
MAX_WORKERS = 3   # what the byte-for-byte comparison was run at. Six was tried
                  # on 8 cores / 32 GB: WorldEd failed with "Error Loading Image"
                  # and most batches needed retries.


def default_workers() -> int:
    try:
        wanted = int(knoxpaths.load_config().get("compile_workers") or 0)
    except (TypeError, ValueError):
        wanted = 0
    if wanted > 0:
        return wanted
    cores = os.cpu_count() or 2
    free_gb = _free_memory_gb()
    by_memory = int(free_gb // GB_PER_WORKER) if free_gb else 1
    return max(1, min(MAX_WORKERS, cores // 4, by_memory))


class Throttle:
    """How many batches may run at once, lowered when WorldEd starts failing.

    Six at once on an 8-core, 32 GB PC made WorldEd fail with "Error Loading
    Image" and most batches needed a retry, each retry costing minutes. What
    is too many depends on the PC, so the run starts at the configured number
    and gives up one slot whenever a batch fails while others are running, then
    stays there. It only goes down, and never below one. A burst of failures
    from one overload counts once: the batches that were already running fail
    together, and easing for each would drop straight to one.
    """

    EASE_EVERY_S = 90.0

    def __init__(self, limit: int):
        self.start = self.limit = max(1, int(limit))
        self.running = 0
        self._cond = threading.Condition()
        self._eased_at = 0.0

    def acquire(self, should_stop=None) -> None:
        with self._cond:
            while self.running >= self.limit:
                knoxstop.check(should_stop, "the compile")
                self._cond.wait(timeout=1.0)
            self.running += 1

    def release(self) -> None:
        with self._cond:
            self.running -= 1
            self._cond.notify_all()

    def ease(self) -> int | None:
        """Give up a slot after a failure. Returns the new limit when it went
        down, None when it stayed (already at one, or eased a moment ago)."""
        with self._cond:
            now = time.time()
            if self.limit <= 1 or now - self._eased_at < self.EASE_EVERY_S:
                return None
            self.limit -= 1
            self._eased_at = now
            return self.limit


def _free_memory_gb() -> float:
    """Memory available right now, in GB; 0 when it cannot be told."""
    try:
        if os.name == "nt":
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                            ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong),
                            ("tvirt", ctypes.c_ulonglong), ("avirt", ctypes.c_ulonglong),
                            ("ext", ctypes.c_ulonglong)]
            m = MEM()
            m.length = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.avail / 2 ** 30
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 2 ** 20
    except Exception:  # noqa: BLE001 - unknown memory means "run one"
        pass
    return 0.0


def knoxlots_exe() -> Path | None:
    """The Rust compiler: KNOXLOTS, else the one a release ships beside KnoxMap.exe, else a
    local release build, else one on PATH."""
    import shutil
    env = os.environ.get("KNOXLOTS")
    for cand in ([Path(env)] if env else []) + [
            BASE_DIR / "knoxlots.exe", BASE_DIR / "knoxlots",
            BASE_DIR / "rust" / "knoxlots" / "target" / "release" / "knoxlots.exe",
            BASE_DIR / "rust" / "knoxlots" / "target" / "release" / "knoxlots"]:
        if cand.exists():
            return cand
    found = shutil.which("knoxlots")
    return Path(found) if found else None


def default_backend() -> str:
    """knoxlots when it is built (or KNOXLOTS names it), else WorldEd; KNOXMAP_BACKEND=worlded|rust
    chooses outright."""
    chosen = os.environ.get("KNOXMAP_BACKEND")
    if chosen in ("worlded", "rust"):
        return chosen
    return "rust" if knoxlots_exe() else "worlded"


def compile_rust(project_dir: str, on_progress=None, should_stop=None, workers: int | None = None) -> int:
    """Compile with knoxlots instead of WorldEd: no bitmap limit, no batches.

    Makes the cell sources from the project (tools/map_source.py), compiles them into a
    scratch folder and, only when that worked, replaces the project's lots with the result.
    Returns the number of cells."""
    import shutil
    exe = knoxlots_exe()
    if exe is None:
        raise FileNotFoundError("knoxlots not found - build it with `cargo build --release` in "
                                "rust/knoxlots, or set KNOXLOTS to its path")
    project = Path(project_dir).resolve()
    if not (project / f"{project.name}.pzw").exists():
        raise FileNotFoundError(f"No {project.name}.pzw - generate the buildings first.")
    from tools.map_source import make_map_source
    run = uuid.uuid4().hex[:8]
    scratch = project / ".knoxlots"
    src, out = scratch / "src", scratch / "lots"
    shutil.rmtree(scratch, ignore_errors=True)
    with _only_one(project, run):
        try:
            if should_stop and should_stop():
                raise RuntimeError("stopped")
            make_map_source(str(project), str(src), seams=True, workers=workers, should_stop=should_stop)
            cmd = [str(exe), "compile", str(src), str(out), "--threads", str(workers or os.cpu_count() or 1)]
            proc = _run_batch(cmd, should_stop or (lambda: False), time.time())
            if proc.returncode != 0:
                raise RuntimeError(f"knoxlots failed (exit {proc.returncode}): {_why(proc)}")
            cells = len(list(out.glob("*.lotheader")))
            if not cells:
                raise RuntimeError("knoxlots produced no cells")
            lots = project / "lots"
            lots.mkdir(exist_ok=True)
            for old in lots.glob("*.lotheader"):
                old.unlink()
            for old in list(lots.glob("world_*.lotpack")) + list(lots.glob("chunkdata_*.bin")):
                old.unlink()
            for f in out.iterdir():
                shutil.move(str(f), str(lots / f.name))
            if on_progress:
                on_progress(cells, cells, cells)
            knoxlog.log.info("compile %s [%s]: knoxlots wrote %d cells", project.name, run, cells)
            return cells
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


def compile_map(project_dir: str, batch: int = 4, exe: str | None = None,
                on_progress=None, should_stop=None,
                only_cells: list | None = None, workers: int | None = None,
                on_detail=None, incremental: bool = True, fresh: bool = False,
                backend: str | None = None) -> int:
    """Run every batch. Returns the number of compiled cells.

    A batch that fails is tried again (BATCH_ATTEMPTS) and, if it still will
    not go, written down and stepped over: half a day's compiling should not
    be thrown away because batch 23 of 48 hit a bad texture read. What could
    not be done ends up in compile_failures.json and is offered again, and
    `only_cells` - a list of [x0, y0, x1, y1] - compiles just those.

    Some failures are not worth a second attempt because they are about this
    machine rather than this batch: a Qt that cannot start fails every batch
    in exactly the same way, and forty-eight batches of it is hours of
    nothing. Those stop the run at once, with what to do about it.

    `on_detail`, when given, is called with {"workers": batches allowed at
    once, "started_with": what the run began at, "eta_s": seconds left or None}
    whenever a batch ends, for the window to show. The first call, before any
    batch starts, also carries "incremental": {"changed": cells that differ
    from the last compile, "cells": cells in the world, "batches": how many
    batches will run, "of": how many there are} when the compile is only
    redoing what changed.

    `incremental` lets a map that was compiled cleanly before keep the lots of
    every cell that has not changed (see compile_state.py); `fresh` throws
    everything compiled away first.
    """
    if (backend or default_backend()) == "rust":
        return compile_rust(project_dir, on_progress, should_stop, workers)
    if workers is None:
        workers = default_workers()
    project = Path(project_dir).resolve()
    pzw = project / f"{project.name}.pzw"
    if not pzw.exists():
        raise FileNotFoundError(f"No {pzw.name} — generate the buildings first.")
    exe_path = Path(exe) if exe else DEFAULT_EXE
    if not exe_path.exists():
        raise FileNotFoundError(f"PZWorldEd_cli not found at {exe_path}")

    # Every line of this run's log carries it, so two runs in one log file can
    # be told apart - which is the first question to ask of any compile that
    # looks like it did its batches out of order.
    run = uuid.uuid4().hex[:8]

    with _only_one(project, run):
        # Whatever wrote the project, one entry past the edge of the map must not
        # stop the whole compile: WorldEd refuses a project over a single one.
        from knoxbuild.repair import repair_project
        try:
            fixed = repair_project(pzw)
        except Exception:  # noqa: BLE001 - a repair that fails leaves the project as it was
            knoxlog.log.exception("compile %s: checking the project failed", project.name)
        else:
            if fixed["changed"]:
                knoxlog.log.warning("compile %s: repaired the project before compiling - moved %d, "
                                    "dropped %d%s", project.name, fixed["moved"],
                                    len(fixed["dropped"]),
                                    "".join(f"\n  dropped {what}: {why}"
                                            for what, why in fixed["dropped"][:50]))
        lots = project / "lots"
        lots.mkdir(exist_ok=True)
        (project / "tmx").mkdir(exist_ok=True)

        w, h = world_size(pzw)
        if not w or not h:
            raise ValueError(f"Could not read the world size from {pzw.name}")

        # What to throw away before compiling. With a record of the last clean
        # compile, only the cells that changed; otherwise whatever is older
        # than what it was compiled from, as before.
        from tools import compile_state as cstate
        # Not when only some cells were asked for: that is a retry of the ones
        # that failed, and it must not throw away all the ones that did not.
        if fresh and not only_cells:
            cstate.wipe(project)
        now = None
        redo = None
        if only_cells or not incremental:
            clear_stale(project)
        else:
            try:
                now = cstate.fingerprints(project)
                redo = cstate.plan(cstate.load(project), now,
                                   any(lots.glob("*.lotheader")))
            except Exception as exc:  # noqa: BLE001 - no record is not a reason to stop
                knoxlog.log.warning("compile %s [%s]: could not tell what changed (%s: %s); "
                                    "using file times", project.name, run,
                                    type(exc).__name__, exc)
            if redo is None:
                clear_stale(project)
            else:
                gone = cstate.discard(project, redo, tuple(now["origin"]))
                knoxlog.log.info(
                    "compile %s [%s]: %d of %d cells changed; discarded %d lot files "
                    "and %d maps, the rest is kept", project.name, run, redo["changed"],
                    w * h, gone["lots"], gone["tmx"])

        # The record describes the lots as they were after the last compile that
        # finished, and this one is about to change them. If it stops half way
        # and the inputs then go back to what they were, a record that still
        # said "unchanged" would keep lots that were already rebuilt from the
        # other inputs. It is written again, from this run's fingerprints, only
        # when the run finishes cleanly.
        cstate.forget(project)

        if only_cells:
            batches = [tuple(int(v) for v in cells[:4]) for cells in only_cells]
        else:
            batches = [(x, y, min(x + batch - 1, w - 1), min(y + batch - 1, h - 1))
                       for y in range(0, h, batch) for x in range(0, w, batch)]
            # Starting WorldEd loads the whole tile catalogue, a minute or more
            # each, so a batch that has nothing to do is not started at all.
            origin = tuple(now["origin"]) if now else cstate.origin_of(pzw)
            every = len(batches)
            batches = [b for b in batches
                       if cstate.batch_needs_work(project, b, origin, (w, h))]
            if on_detail and redo is not None:
                on_detail({"workers": workers, "started_with": workers, "eta_s": None,
                           "incremental": {"changed": redo["changed"], "cells": w * h,
                                           "batches": len(batches), "of": every}})
            if not batches:
                knoxlog.log.info("compile %s [%s]: every lot file is there; nothing to "
                                 "compile", project.name, run)
        started = time.time()
        failures: list[dict] = []
        total = len(batches)
        # The first batch converts the whole bitmap to .tmx maps and
        # assign_converted_maps writes them back; every later batch reads the
        # result. Two processes converting at once would write the same files,
        # so it goes alone, and the rest may then run side by side.
        guard = threading.Lock()
        finished = [0]
        throttle = Throttle(workers)
        timing = {"first_done": None}

        def do_batch(i, bx, by, x1, y1):
            cmd = knoxpaths.command_for(exe_path) + [
                f"--generate-map={knoxpaths.tool_path(pzw)}",
                f"--cells={bx},{by},{x1},{y1}"]
            for attempt in range(1, BATCH_ATTEMPTS + 1):
                knoxstop.check(should_stop, "the compile")
                # A slot is held for one attempt, not the whole batch, so a
                # retry waits its turn under whatever the limit is by then.
                throttle.acquire(should_stop)
                try:
                    attempt_started = time.time()
                    try:
                        proc = _run_batch(cmd, should_stop, attempt_started)
                    except subprocess.TimeoutExpired as hung:
                        # A hung batch is a failed attempt like any other:
                        # tried again, then written down and stepped over.
                        knoxlog.log.warning(
                            "compile %s [%s]: batch %d/%d cells %d,%d..%d,%d hung - no end "
                            "after %d minutes, stopped", project.name, run, i, total,
                            bx, by, x1, y1, BATCH_TIMEOUT // 60)
                        proc = subprocess.CompletedProcess(
                            cmd, 124, hung.output or "",
                            (hung.stderr or "") + "\nWorldEd did not finish in "
                            f"{BATCH_TIMEOUT // 60} minutes and was stopped.")
                finally:
                    throttle.release()
                # WorldEd's own account of the batch, kept whatever happened: when it
                # crashes this is the only record of how far it got.
                saved = knoxlog.save_tool_output("PZWorldEd_cli", project.name,
                                                 f"cells_{bx}_{by}-{x1}_{y1}", proc.returncode,
                                                 proc.stdout, proc.stderr)
                again = f" (attempt {attempt}/{BATCH_ATTEMPTS})" if attempt > 1 else ""
                knoxlog.log.info("compile %s [%s]: batch %d/%d cells %d,%d..%d,%d exit %d "
                                 "(%s) in %.0fs%s", project.name, run, i, total,
                                 bx, by, x1, y1, proc.returncode,
                                 knoxlog.explain_exit(proc.returncode),
                                 time.time() - attempt_started, again)
                if proc.returncode == 0:
                    break
                eased = throttle.ease() if throttle.running else None
                if eased is not None:
                    knoxlog.log.warning(
                        "compile %s [%s]: batch %d/%d failed while others were "
                        "running; from now on %d at a time (it began at %d)",
                        project.name, run, i, total, eased, throttle.start)
                # Not this batch's fault, and every other batch would go the
                # same way: stop now and say what to do about it.
                trouble = knoxpaths.qt_trouble((proc.stderr or "") + (proc.stdout or ""))
                if trouble:
                    raise RuntimeError(f"Compile cannot run on this system: {trouble}.")
                if attempt < BATCH_ATTEMPTS:
                    knoxlog.log.warning("compile %s [%s]: batch %d/%d failed, trying again",
                                        project.name, run, i, total)
            with guard:
                assign_converted_maps(pzw)
                cells = len(list(lots.glob("*.lotheader")))
                # 65 used to be tolerated because the wait for WorldEd was a guess.
                # It now waits for the lot manager's own completion, so 65 means a
                # genuine stall or timeout and the batch's cells cannot be trusted.
                if proc.returncode != 0:
                    where = f"logs/worlded/{saved.name}" if saved else ""
                    failures.append({"cells": [bx, by, x1, y1], "exit": proc.returncode,
                                     "why": _why(proc), "log": where,
                                     "attempts": BATCH_ATTEMPTS})
                    knoxlog.log.error("compile %s [%s]: giving up on batch %d/%d cells "
                                      "%d,%d..%d,%d after %d attempts - carrying on with the "
                                      "rest", project.name, run, i, total,
                                      bx, by, x1, y1, BATCH_ATTEMPTS)
                finished[0] += 1
                now_t = time.time()
                if timing["first_done"] is None:
                    timing["first_done"] = (now_t, finished[0])
                eta = None
                t_first, n_first = timing["first_done"]
                # Seconds per batch since the first one ended (the first runs
                # alone and converts the whole bitmap, so it is not typical),
                # needing a few batches before the figure means anything.
                if finished[0] - n_first >= 3 and now_t > t_first:
                    rate = (finished[0] - n_first) / (now_t - t_first)
                    eta = int((total - finished[0]) / rate)
                if on_detail:
                    on_detail({"workers": throttle.limit,
                               "started_with": throttle.start, "eta_s": eta})
                if on_progress:
                    on_progress(finished[0], total, cells)
                else:
                    elapsed = time.time() - started
                    state = "FAILED" if proc.returncode != 0 else f"-> {cells} compiled"
                    print(f"  batch {i}/{total} cells {bx},{by}..{x1},{y1} "
                          f"{state}  ({elapsed:.0f}s)", flush=True)

        jobs = [(i, *box) for i, box in enumerate(batches, start=1)]
        pool_size = max(1, min(int(workers), len(jobs) - 1))
        if pool_size <= 1 or len(jobs) < 3:
            for job in jobs:
                do_batch(*job)
        else:
            do_batch(*jobs[0])
            knoxlog.log.info("compile %s [%s]: %d batches at a time", project.name,
                             run, pool_size)
            with futures.ThreadPoolExecutor(max_workers=pool_size) as pool:
                pending = [pool.submit(do_batch, *job) for job in jobs[1:]]
                try:
                    for fut in futures.as_completed(pending):
                        fut.result()
                except BaseException:
                    # A stop or a fatal error: do not start what has not begun.
                    for fut in pending:
                        fut.cancel()
                    raise

        # Asked for particular cells, the batches that were not in this run
        # keep whatever the last full compile said about them - retrying two
        # of five failures must not lose the other three.
        this_run = list(failures)
        if only_cells:
            done = {tuple(b) for b in batches}
            failures = [f for f in failed_cells(project)
                        if tuple(f.get("cells") or ()) not in done] + failures
        _record_failures(project, run, batch, failures)
        # A compile that did everything it was asked to leaves a record, so the
        # next one can do only what changes after it.
        if now is not None and not failures and not only_cells:
            cstate.save(project, now)
        if this_run and len(this_run) >= len(batches):
            first = this_run[0]
            where = f" - WorldEd's output is in {first['log']}" if first.get("log") else ""
            at = (f"{first['cells'][0]},{first['cells'][1]}.."
                  f"{first['cells'][2]},{first['cells'][3]}")
            if only_cells:
                raise RuntimeError(f"Those cells still will not compile. {at} "
                                   f"(exit {first['exit']}): {first['why']}{where}"
                                   f"{too_large_note(project)}")
            raise RuntimeError(f"WorldEd failed on every batch. The first was cells "
                               f"{at} (exit {first['exit']}): {first['why']}{where}"
                               f"{too_large_note(project)}")
        if failures:
            knoxlog.log.warning("compile %s [%s]: finished with %d of %d batches failed",
                                project.name, run, len(failures), len(batches))
        return len(list(lots.glob("*.lotheader")))


def main(argv: list[str] | None = None) -> int:
    # Place names can be in any script, and a Windows console using a legacy
    # code page cannot print most of them - "OSM says Kadıköy" crashed a build
    # on cp1252. Print what it can and mark the rest, rather than dying.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--batch", type=int, default=4,
                    help="source cells per side per batch (default 4)")
    ap.add_argument("--exe", default=None)
    ap.add_argument("--backend", choices=["worlded", "rust"], default=None,
                    help="default: rust (knoxlots, no size limit) when built, else worlded; "
                         "or KNOXMAP_BACKEND")
    args = ap.parse_args(argv)
    try:
        total = compile_map(args.project_dir, args.batch, args.exe, backend=args.backend)
    except Exception as exc:
        print(f"Compile failed: {exc}", file=sys.stderr)
        return 1
    print(f"compiled {total} cells into {args.project_dir}/lots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
