"""Launch knoxlots row workers. Python owns scheduling, checkpoints and cancellation."""
from __future__ import annotations

from concurrent import futures
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import xml.etree.ElementTree as ET

import knoxstop
from knoxbuild.buildheader import group_buildings_by_row


def supported(exe):
    cmd = [str(exe), "source-worker-version"]
    try:
        probe = subprocess.run(cmd, capture_output=True, timeout=15,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (subprocess.TimeoutExpired, OSError):
        return False
    return probe.returncode == 0 and probe.stdout.strip() == b"1"


def _run(exe, job, folder, should_stop):
    knoxstop.check(should_stop, "the compile")
    request = Path(folder) / "job.xml"
    ET.ElementTree(job).write(request, encoding="utf-8", xml_declaration=True)
    with tempfile.TemporaryFile() as error:
        with subprocess.Popen([str(exe), "source-worker", str(request)], stderr=error,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as proc:
            try:
                while True:
                    try:
                        code = proc.wait(timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        knoxstop.check(should_stop, "the compile")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        if code:
            error.seek(0)
            raise RuntimeError(f"knoxlots source worker exited {code}: "
                               + error.read().decode("utf-8", errors="replace").strip())


def _lots(job, lots):
    for name, x, y, z, *_ in lots:
        ET.SubElement(job, "lot", name=name, x=str(x), y=str(y), z=str(z))


def changed_cells(exe, project, lots, origin, margin, should_stop):
    with tempfile.TemporaryDirectory(dir=project / ".knoxlots") as tmp:
        result = Path(tmp).resolve() / "cells.txt"
        job = ET.Element("changes", project=str(project), out=str(result),
                         ox=str(origin[0]), oy=str(origin[1]), margin=str(margin))
        _lots(job, lots)
        if not len(job):
            return set()
        _run(exe, job, tmp, should_stop)
        return {tuple(map(int, line.split())) for line in result.read_text().splitlines()}


def tables(exe, project, out, lots, origin, should_stop):
    with tempfile.TemporaryDirectory(prefix="knoxlots_tables_") as tmp:
        result = Path(tmp) / "tables.xml"
        job = ET.Element("tables", project=os.path.abspath(project), out=str(result.resolve()))
        _lots(job, lots)
        _run(exe, job, tmp, should_stop)
        sizes = []
        placed = []
        for _, element in ET.iterparse(result, events=("end",)):
            if element.tag == "size":
                sizes.append((int(element.attrib["w"]), int(element.attrib["h"])))
            elif element.tag == "building":
                entries = []
                for room in element:
                    values = iter(map(int, (room.text or "").split()))
                    entries.append(dict(name=room.attrib["name"], z=int(room.attrib["z"]),
                                        rects=list(zip(values, values, values, values, strict=True))))
                placed.append((int(element.attrib["x"]), int(element.attrib["y"]), entries))
                element.clear()
        return group_buildings_by_row(placed, origin), sizes


def row(exe, project, out, cy, band, room_columns, origin, size, columns,
        seed, seams, rules, track, should_stop):
    ox, oy = origin
    w, h = size
    if columns is None:
        columns = range(ox // 256, (ox + w - 1) // 256 + 1)
    with tempfile.TemporaryDirectory(prefix="knoxlots_row_") as tmp:
        job = ET.Element("row", project=os.path.abspath(project), out=os.path.abspath(out),
                         cy=str(cy), ox=str(ox), oy=str(oy), width=str(w), height=str(h),
                         seed=str(seed), seams=str(int(seams)), rules=os.path.abspath(rules))
        result = Path(tmp).resolve() / "footprints.xml"
        if track:
            job.set("footprints", str(result))
        _lots(job, band)
        for cx in columns:
            cell = ET.SubElement(job, "cell", x=str(cx))
            for _, _, entries in room_columns.get(cx, []):
                building = ET.SubElement(cell, "building")
                for r in entries:
                    room = ET.SubElement(building, "room", name=r["name"], z=str(r["z"]))
                    room.text = " ".join(str(v) for rect in r["rects"] for v in rect)
        _run(exe, job, tmp, should_stop)
        if track:
            footprints = {e.attrib["name"]: list(map(int, (e.text or "").split()))
                          for e in ET.parse(result).getroot()}
            (Path(out) / f"footprints_{cy}.json").write_text(json.dumps(footprints), encoding="utf-8")
    return len(columns)


def rows(todo, workers, run, finished, should_stop):
    """Each thread waits on one native child. Reap siblings on failure or Stop."""
    abort = threading.Event()

    def stopping():
        return abort.is_set() or (should_stop and should_stop())

    written = 0
    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(run, cy, stopping): cy for cy in todo}
        try:
            for n, future in enumerate(futures.as_completed(jobs), 1):
                written += future.result()
                finished(jobs[future], n)
        finally:
            abort.set()
            for future in jobs:
                future.cancel()
    return written
