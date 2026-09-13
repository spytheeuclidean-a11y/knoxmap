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
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import knoxpaths  # noqa: E402

DEFAULT_EXE = knoxpaths.worlded_cli() or Path("PZWorldEd_cli.exe")


def world_size(pzw: Path) -> tuple[int, int]:
    text = pzw.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'<world version="[^"]*" width="(\d+)" height="(\d+)"', text)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


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
    tmx_dir = re.search(r'<tmxexportdir path="([^"]+)"', text)
    if not (origin and bmp and tmx_dir):
        return 0
    ox, oy = int(origin.group(1)), int(origin.group(2))
    base = Path(bmp.group(1)).stem
    folder = Path(tmx_dir.group(1))
    count = 0

    def fill(m):
        nonlocal count
        x, y = int(m.group(1)), int(m.group(2))
        path = folder / f"{base}_{ox + x}_{oy + y}.tmx"
        if not path.exists():
            return m.group(0)
        count += 1
        return f'<cell x="{x}" y="{y}" map="{path.as_posix()}"'

    new = re.sub(r'<cell x="(\d+)" y="(\d+)" map=""', fill, text)
    if count:
        pzw.write_text(new, encoding="utf-8")
    return count


def compile_map(project_dir: str, batch: int = 4, exe: str | None = None,
                on_progress=None) -> int:
    """Run every batch. Returns the number of compiled cells."""
    project = Path(project_dir).resolve()
    pzw = project / f"{project.name}.pzw"
    if not pzw.exists():
        raise FileNotFoundError(f"No {pzw.name} — generate the buildings first.")
    exe_path = Path(exe) if exe else DEFAULT_EXE
    if not exe_path.exists():
        raise FileNotFoundError(f"PZWorldEd_cli.exe not found at {exe_path}")

    lots = project / "lots"
    lots.mkdir(exist_ok=True)
    (project / "tmx").mkdir(exist_ok=True)

    w, h = world_size(pzw)
    if not w or not h:
        raise ValueError(f"Could not read the world size from {pzw.name}")

    batches = [(x, y) for y in range(0, h, batch) for x in range(0, w, batch)]
    started = time.time()
    for i, (bx, by) in enumerate(batches, start=1):
        x1 = min(bx + batch - 1, w - 1)
        y1 = min(by + batch - 1, h - 1)
        cmd = [str(exe_path), f"--generate-map={pzw}",
               f"--cells={bx},{by},{x1},{y1}"]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=2 * 3600)
        assign_converted_maps(pzw)
        cells = len(list(lots.glob("*.lotheader")))
        if on_progress:
            on_progress(i, len(batches), cells)
        else:
            elapsed = time.time() - started
            print(f"  batch {i}/{len(batches)} cells {bx},{by}..{x1},{y1} "
                  f"-> {cells} compiled  ({elapsed:.0f}s)", flush=True)
        # 65 used to be tolerated because the wait for WorldEd was a guess.
        # It now waits for the lot manager's own completion, so 65 means a
        # genuine stall or timeout and the batch's cells cannot be trusted.
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            raise RuntimeError(f"batch {bx},{by} failed "
                               f"({proc.returncode}): {' | '.join(tail)}")
    return len(list(lots.glob("*.lotheader")))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--batch", type=int, default=4,
                    help="source cells per side per batch (default 4)")
    ap.add_argument("--exe", default=None)
    args = ap.parse_args(argv)
    try:
        total = compile_map(args.project_dir, args.batch, args.exe)
    except Exception as exc:
        print(f"Compile failed: {exc}", file=sys.stderr)
        return 1
    print(f"compiled {total} cells into {args.project_dir}/lots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
