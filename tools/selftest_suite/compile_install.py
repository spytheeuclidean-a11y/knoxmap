"""Selftest checks for compile install."""
from __future__ import annotations

if __package__ == "tools.selftest_suite":
    from ..selftest import (
        Image, Path, json,
        os, re, shutil, sys, tempfile,
    )
else:
    from selftest import (
        Image, Path, json,
        os, re, shutil, sys, tempfile,
    )


def check_compile_failures(check, work: str) -> None:
    """A batch that fails is tried again, and then stepped over.

    Reported from a 14-hour compile: batch 23 of 48 exited 1 after 849
    seconds and the whole run was thrown away. Three attempts now, and what
    still will not go is written down and skipped so the other 47 batches
    are not lost with it - except for the failures that are about the machine
    rather than the batch, which would fail all 48 the same way.
    """
    import json as _json

    import knoxlog

    from tools import compile_map as compiler

    class Proc:
        def __init__(self, rc, out=""):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    keep = {name: getattr(compiler, name) for name in
            ("_run_batch", "clear_stale", "assign_converted_maps", "world_size")}
    keep_saved = knoxlog.save_tool_output
    import knoxbuild.repair as _repair
    keep_repair = _repair.repair_project

    made = [0]

    def harness(plan):
        made[0] += 1
        project = Path(work) / f"compile-{made[0]}"
        (project / "lots").mkdir(parents=True)
        (project / "tmx").mkdir()
        (project / f"{project.name}.pzw").write_text("<world/>", encoding="utf-8")
        exe = project / "PZWorldEd_cli"
        exe.write_text("", encoding="utf-8")
        tries: dict = {}

        def fake(cmd, should_stop, started):
            arg = [a for a in cmd if a.startswith("--cells=")][0]
            bx, by, x1, y1 = (int(v) for v in arg[len("--cells="):].split(","))
            n = tries.get((bx, by), 0)
            tries[(bx, by)] = n + 1
            codes = plan.get((bx, by), [0])
            rc = codes[n] if n < len(codes) else codes[-1]
            if rc == 0:
                for cx in range(bx, x1 + 1):
                    for cy in range(by, y1 + 1):
                        (project / "lots" / f"{cx}_{cy}.lotheader").write_text("x")
            return Proc(rc, "Cannot mix incompatible Qt library (5.15.13) with "
                            "this library (5.15.3)" if rc == -6 else "")

        compiler._run_batch = fake
        return project, exe, tries

    try:
        compiler.clear_stale = lambda p: None
        compiler.assign_converted_maps = lambda p: None
        compiler.world_size = lambda p: (4, 4)
        # Same keyword arguments compile_map passes (knoxlots, should_stop,
        # on_progress): a bare `lambda p` here raised TypeError instead.
        _repair.repair_project = lambda p, **kwargs: {"changed": False, "moved": 0,
                                                      "dropped": []}
        knoxlog.save_tool_output = lambda *a, **k: Path("batch.log")

        # One bad batch out of four, good on the second attempt.
        project, exe, tries = harness({(2, 0): [1, 0]})
        cells = compiler.compile_map(str(project), batch=2, exe=str(exe))
        check(cells == 16 and tries[(2, 0)] == 2 and not compiler.failed_cells(project),
              f"a batch that fails once is tried again and the map is whole ({cells} cells)")

        # One that never works first time round: the other three batches still
        # compile, and it comes good when it is asked for again on its own.
        project, exe, tries = harness({(2, 0): [1, 1, 1, 0]})
        cells = compiler.compile_map(str(project), batch=2, exe=str(exe))
        failed = compiler.failed_cells(project)
        check(cells == 12 and tries[(2, 0)] == compiler.BATCH_ATTEMPTS
              and [f["cells"] for f in failed] == [[2, 0, 3, 1]],
              f"one that never works is stepped over, not thrown away ({cells} cells, "
              f"{len(failed)} recorded)")
        check(not (project / compiler.LOCK_FILE).exists(),
              "and the compile lock is let go afterwards")

        # ...and asking for just those cells again compiles them.
        again = compiler.compile_map(str(project), batch=2, exe=str(exe),
                                     only_cells=[f["cells"] for f in failed])
        check(again == 16 and not compiler.failed_cells(project),
              f"compiling only the failed cells finishes the map ({again} cells)")

        # A Qt that cannot start is not this batch's fault: 48 batches of it
        # is hours of the same abort, so it stops on the first.
        project, exe, tries = harness({(0, 0): [-6]})
        try:
            compiler.compile_map(str(project), batch=2, exe=str(exe))
            said = ""
        except RuntimeError as exc:
            said = str(exc)
        check(sum(tries.values()) == 1 and "5.15.13" in said,
              "a compiler that cannot start stops the run at once, with what is wrong")

        # Two at a time in one folder write the same lots and the same .pzw.
        project, exe, _tries = harness({})
        (project / compiler.LOCK_FILE).write_text(
            _json.dumps({"pid": os.getpid() + 1, "run": "other"}), encoding="utf-8")
        alive = compiler._pid_alive
        compiler._pid_alive = lambda pid: True
        try:
            compiler.compile_map(str(project), batch=2, exe=str(exe))
            refused = ""
        except RuntimeError as exc:
            refused = str(exc)
        finally:
            compiler._pid_alive = alive
        check("already being compiled" in refused,
              "a second compile of the same map is refused while one is running")

        # ...but a lock left by a compile that crashed is not forever.
        (project / compiler.LOCK_FILE).write_text(
            _json.dumps({"pid": 999999, "run": "crashed"}), encoding="utf-8")
        cells = compiler.compile_map(str(project), batch=2, exe=str(exe))
        check(cells == 16, "and a lock left behind by a crash is cleared, not fatal")
    finally:
        for name, value in keep.items():
            setattr(compiler, name, value)
        knoxlog.save_tool_output = keep_saved
        _repair.repair_project = keep_repair


def check_compile_records(check, work: str) -> None:
    """The compile's record of what it compiled is only kept while it is true."""
    import numpy as np

    import knoxlog
    import knoxstop
    import knoxbuild.repair as repair
    from tools import compile_map as compiler
    from tools import compile_state as cs

    project = Path(work) / "records"
    (project / "lots").mkdir(parents=True)
    (project / "tmx").mkdir()
    (project / "buildings").mkdir()
    Image.fromarray(np.zeros((600, 600, 3), dtype=np.uint8)).save(
        project / "records.bmp", format="BMP")
    (project / "buildings" / "a.tbx").write_text("one")
    cell = '<cell x="{x}" y="{y}" map="">\n <lot x="1" y="1" level="0" width="2" height="2" map="buildings/a.tbx"/>\n</cell>\n'
    (project / "records.pzw").write_text(
        '<world version="1.0" width="2" height="2">\n<worldOrigin origin="70,0"/>\n'
        '<bmp path="records.bmp" x="0" y="0" width="2" height="2"/>\n'
        + "".join(cell.format(x=x, y=y) for x in range(2) for y in range(2))
        + "</world>", encoding="utf-8")
    exe = project / "PZWorldEd_cli"
    exe.write_text("", encoding="utf-8")

    ran: list = []
    explode = [False]

    class Done:
        returncode, stdout, stderr = 0, "", ""

    def fake(cmd, should_stop, started):
        arg = [a for a in cmd if a.startswith("--cells=")][0]
        box = tuple(int(v) for v in arg[len("--cells="):].split(","))
        ran.append(box)
        if explode[0]:
            raise knoxstop.Stopped("the compile")
        cells = {(x, y) for x in range(box[0], box[2] + 1) for y in range(box[1], box[3] + 1)}
        for lx, ly in cs.lot_files_of(cells, (70, 0)):
            (project / "lots" / f"{lx}_{ly}.lotheader").write_text("new")
        return Done()

    keep = {n: getattr(compiler, n) for n in ("_run_batch",)}
    keep_saved, keep_repair = knoxlog.save_tool_output, repair.repair_project
    compiler._run_batch = fake
    knoxlog.save_tool_output = lambda *a, **k: None
    repair.repair_project = lambda pzw: {"changed": 0, "moved": 0, "dropped": []}
    try:
        compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1)
        check(cs.load(project) is not None and len(ran) == 4,
              "a compile that finishes leaves a record, having run every batch")

        ran.clear()
        compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1)
        check(not ran, "and with nothing changed the next one starts no batch at all")

        (project / "lots" / "84_2.lotheader").write_text("old")
        compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1,
                             only_cells=[[0, 0, 0, 0]], fresh=True)
        check((project / "lots" / "84_2.lotheader").read_text() == "old",
              "starting from scratch does not apply to a retry of just some cells")

        (project / "buildings" / "a.tbx").write_text("two")
        ran.clear()
        explode[0] = True
        try:
            compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1)
        except knoxstop.Stopped:
            pass
        check(ran and cs.load(project) is None,
              "a compile that stops part way leaves no record of the lots it half changed")
        explode[0] = False
        compiler.compile_map(str(project), batch=1, exe=str(exe), workers=1)
        check(cs.load(project) is not None, "and the next one that finishes writes it again")
    finally:
        compiler._run_batch = keep["_run_batch"]
        knoxlog.save_tool_output = keep_saved
        repair.repair_project = keep_repair


def check_compile_state(check, work: str) -> None:
    """Working out which cells of a compiled map are out of date."""
    import numpy as np

    from knoxbuild import bitmaps
    from tools import compile_state as cs

    rng = np.random.default_rng(11)
    rgb = rng.integers(0, 256, (130, 205, 3), dtype=np.uint8)
    a_path, b_path = os.path.join(work, "cells_a.bmp"), os.path.join(work, "cells_b.bmp")
    Image.fromarray(rgb).save(a_path, format="BMP")
    changed = rgb.copy()
    changed[75, 160] = 255 - changed[75, 160]            # one pixel, in cell (2, 1)
    Image.fromarray(changed).save(b_path, format="BMP")
    ha, hb = bitmaps.cell_hashes(a_path, 60), bitmaps.cell_hashes(b_path, 60)
    check(len(ha) == 4 * 3 and bitmaps.cell_hashes(a_path, 60) == ha
          and [k for k in ha if ha[k] != hb[k]] == [(2, 1)],
          "one changed pixel changes the fingerprint of its own square and no other")
    grey = rng.integers(0, 256, (70, 90), dtype=np.uint8)
    g_path = os.path.join(work, "cells_g.bmp")
    Image.fromarray(grey, "L").save(g_path, format="BMP")
    check(len(bitmaps.cell_hashes(g_path, 30)) == 3 * 3, "and it reads a grey picture too")
    step3 = bitmaps.read_rgb(a_path, step=3)
    check(np.array_equal(step3, rgb[::3, ::3]), "a smaller picture of a bitmap is every third pixel")

    check(cs.lot_files_of({(0, 0)}, (70, 0)) == {(82, 0), (82, 1), (83, 0), (83, 1)},
          "a cell names the lot files that overlap it")

    def record(terrain_edit=None, content_edit=None) -> dict:
        t = {f"{x},{y}": f"t{x}{y}" for x in range(5) for y in range(5)}
        c = {f"{x},{y}": f"c{x}{y}" for x in range(5) for y in range(5)}
        t.update(terrain_edit or {})
        c.update(content_edit or {})
        return {"version": cs.VERSION, "global": "g", "origin": [70, 0],
                "size": [5, 5], "terrain": t, "content": c}

    base = record()
    check(cs.plan(None, base, True) is None and cs.plan(base, base, False) is None,
          "with no record, or nothing compiled, nothing is trusted")
    check(cs.plan(base, {**base, "global": "other"}, True) is None,
          "and a change to the rules or the compiler redoes everything")
    same = cs.plan(base, record(), True)
    check(same["changed"] == 0 and not same["lots"], "an unchanged map has nothing to redo")
    one = cs.plan(base, record(content_edit={"0,0": "new"}), True)
    check(one["changed"] == 1 and one["lots"] == {(0, 0), (1, 0), (0, 1), (1, 1)}
          and not one["terrain"],
          "a changed building in a corner redoes that cell and its neighbours, not the maps")
    mid = cs.plan(base, record(terrain_edit={"2,2": "new"}), True)
    check(len(mid["terrain"]) == 9 and len(mid["lots"]) == 9,
          "changed ground redoes its map and its neighbours' too")

    project = Path(work) / "statemap"
    (project / "lots").mkdir(parents=True)
    (project / "tmx").mkdir()
    pzw = project / "statemap.pzw"
    cell = '<cell x="{x}" y="{y}" map="C:/m/tmx/statemap_{tx}_{y}.tmx">\n</cell>\n'
    pzw.write_text('<world version="1.0" width="2" height="2">\n'
                   '<worldOrigin origin="70,0"/>\n<bmp path="statemap.bmp" x="0" y="0"/>\n'
                   + "".join(cell.format(x=x, y=y, tx=70 + x)
                             for x in range(2) for y in range(2)) + "</world>",
                   encoding="utf-8")
    for lx in range(82, 86):
        for ly in range(0, 4):
            for name in (f"{lx}_{ly}.lotheader", f"chunkdata_{lx}_{ly}.bin",
                         f"world_{lx}_{ly}.lotpack"):
                (project / "lots" / name).write_text("x")

    def make_maps() -> None:
        for x in range(2):
            for y in range(2):
                (project / "tmx" / f"statemap_{70 + x}_{y}.tmx").write_text("x")

    make_maps()
    # Ground changed somewhere: every map goes, because WorldEd does not make
    # up a partial set (its log said 375 of 384), but only the changed cell's
    # lot files.
    gone = cs.discard(project, {"lots": {(0, 0)}, "terrain": {(0, 0)}}, (70, 0))
    left = pzw.read_text(encoding="utf-8")
    check(gone == {"lots": 12, "tmx": 4}
          and not (project / "lots" / "82_0.lotheader").exists()
          and (project / "lots" / "85_3.lotheader").exists()
          and left.count('map=""') == 4 and ".tmx" not in left
          and not list((project / "tmx").glob("*.tmx")),
          "discarding takes just those cells' lot files, and every map when ground changed")
    make_maps()
    pzw.write_text(left.replace('map=""', 'map="C:/m/tmx/statemap_70_0.tmx"', 1),
                   encoding="utf-8")
    kept = cs.discard(project, {"lots": {(1, 1)}, "terrain": set()}, (70, 0))
    check(kept["tmx"] == 0 and len(list((project / "tmx").glob("*.tmx"))) == 4
          and "statemap_70_0.tmx" in pzw.read_text(encoding="utf-8"),
          "and changes that are not to the ground leave the maps alone")
    for lx in range(82, 86):
        for ly in range(0, 4):
            (project / "lots" / f"{lx}_{ly}.lotheader").write_text("x")
    (project / "lots" / "84_1.lotheader").unlink()
    check(cs.batch_needs_work(project, (1, 1, 1, 1), (70, 0), (2, 2))
          and not cs.batch_needs_work(project, (0, 0, 0, 0), (70, 0), (2, 2)),
          "a batch is run only when a lot file it would write is missing")
    cs.wipe(project)
    check(not any((project / "lots").iterdir()) and not any((project / "tmx").iterdir()),
          "starting from scratch empties lots and maps")


def check_install_clears(check, work: str) -> None:
    """Installing over an old copy that cannot be removed stops, rather than mixing the two."""
    import shutil as _shutil

    from tools import make_map_mod

    old = Path(work) / "old_install"
    (old / "sub").mkdir(parents=True)
    (old / "sub" / "1_1.lotheader").write_text("old")
    make_map_mod._clear_folder(str(old))
    check(not old.exists(), "an old installed copy is removed before the new one goes in")

    stuck = Path(work) / "stuck_install"
    stuck.mkdir()
    (stuck / "5_5.lotheader").write_text("old")
    was = _shutil.rmtree
    make_map_mod.shutil.rmtree = lambda *a, **k: None       # a folder the game holds open
    try:
        try:
            make_map_mod._clear_folder(str(stuck), tries=1)
            said = ""
        except RuntimeError as exc:
            said = str(exc)
    finally:
        make_map_mod.shutil.rmtree = was
    check("could not be removed" in said and "Close Project Zomboid" in said and stuck.exists(),
          "and one that cannot be removed is reported, with what to do about it")


def check_install_folder(check, out: str, work: str, client) -> None:
    """Installing into a chosen folder, the space check, and taking a map out
    again - which must never delete a folder that is not a KnoxMap mod."""
    import knoxpaths
    from knoxbuild import mapstate
    from tools import make_map_mod
    from web import common as webcommon

    zroot = Path(work) / "zomboid_choice"
    was_env, was_cfg = os.environ.get("ZOMBOID_DIR"), knoxpaths.CONFIG_PATH
    was_free, was_output = make_map_mod.free_bytes, webcommon.OUTPUT_DIR
    knoxpaths.CONFIG_PATH = Path(work) / "choice_config.json"
    os.environ.pop("ZOMBOID_DIR", None)
    webcommon.OUTPUT_DIR = Path(out).parent
    try:
        r = client.post("/api/zomboid-folder", json={"folder": str(zroot)})
        got = client.get("/api/zomboid-folder").get_json()
        check(r.status_code == 200 and (zroot / "mods").is_dir() and got["chosen"]
              and Path(got["mods"]) == zroot / "mods"
              and knoxpaths.zomboid_user_dir() == zroot,
              "the Zomboid folder chosen in the app is made and used")
        blocker = Path(work) / "not_a_folder"
        blocker.write_text("x")
        r = client.post("/api/zomboid-folder", json={"folder": str(blocker / "sub")})
        check(r.status_code == 400 and knoxpaths.zomboid_user_dir() == zroot,
              "and one that cannot be made is refused, the old choice kept")
        client.post("/api/zomboid-folder", json={"folder": ""})
        check(not client.get("/api/zomboid-folder").get_json()["chosen"],
              "an empty one goes back to the default")
        client.post("/api/zomboid-folder", json={"folder": str(zroot)})

        make_map_mod.free_bytes = lambda path: 1 << 20       # 1 MB free
        r = client.post("/api/install", json={"mapName": "selftest"})
        check(r.status_code == 400 and "Not enough room" in (r.get_json() or {}).get("error", "")
              and not any((zroot / "mods").iterdir()),
              "an install that will not fit is refused before anything is written")
        make_map_mod.free_bytes = was_free

        # The selftest map has no compiled cells to package, so the installed
        # mod is laid down by hand, as package() writes it.
        check(Path(make_map_mod.default_mods_dir()) == zroot / "mods",
              "installs go into the chosen folder")
        mod = zroot / "mods" / "SelftestMod"
        (mod / "common").mkdir(parents=True)
        (mod / "mod.info").write_text(
            "name=Selftest\ndescription=Selftest, generated from real-world map data "
            "with KnoxMap by euclid80tr.\n")
        mapstate.record_install(out, str(mod), "SelftestMod")
        check(mapstate.installed(out) is not None, "an installed map is recorded")
        r = client.post("/api/uninstall", json={"mapName": "selftest"})
        check(r.status_code == 200 and not mod.exists() and mapstate.installed(out) is None
              and (zroot / "mods").is_dir(),
              "uninstalling removes the mod folder and forgets it")
        check(client.post("/api/uninstall", json={"mapName": "selftest"}).status_code == 404,
              "and a map that is not installed has nothing to remove")

        # Update: no title or id sent, so the installed ones are used again.
        from tools import make_map_mod as _mmm
        mod.mkdir(parents=True, exist_ok=True)
        (mod / "mod.info").write_text("name=Kept Title\n", encoding="utf-8")
        mapstate.record_install(out, str(mod), "KeptId", "Kept Title")
        asked = []
        was_package = _mmm.package
        _mmm.package = lambda d, title, mid, **kw: (asked.append((title, mid)) or (str(mod), 1, []))
        try:
            r = client.post("/api/install", json={"mapName": "selftest"})
        finally:
            _mmm.package = was_package
        check(r.status_code == 200 and asked == [("Kept Title", "KeptId")],
              "updating an installed map puts it back under its own title and id")
        mapstate.forget_install(out)
        shutil.rmtree(mod, ignore_errors=True)

        # A record that points at someone else's folder: refused, nothing deleted.
        theirs = zroot / "mods" / "SomeoneElsesMod"
        theirs.mkdir()
        (theirs / "mod.info").write_text("name=Theirs\ndescription=a different mod\n")
        (theirs / "keep.txt").write_text("keep")
        mapstate.record_install(out, str(theirs), "SomeoneElsesMod")
        r = client.post("/api/uninstall", json={"mapName": "selftest"})
        check(r.status_code == 400 and (theirs / "keep.txt").exists(),
              "a folder that is not a KnoxMap mod is left alone, whatever the record says")
        elsewhere = Path(work) / "elsewhere" / "SelftestMod"
        elsewhere.mkdir(parents=True)
        (elsewhere / "mod.info").write_text(
            "description=generated from real-world map data with KnoxMap\n")
        mapstate.record_install(out, str(elsewhere), "SelftestMod")
        r = client.post("/api/uninstall", json={"mapName": "selftest"})
        check(r.status_code == 400 and elsewhere.exists(),
              "and so is a KnoxMap-looking folder that is not inside a mods folder")
    finally:
        make_map_mod.free_bytes = was_free
        webcommon.OUTPUT_DIR = was_output
        knoxpaths.CONFIG_PATH = was_cfg
        if was_env is not None:
            os.environ["ZOMBOID_DIR"] = was_env
        mapstate.forget_install(out)


def check_portable(check) -> None:
    """Running off Windows: the map tools through Wine, the private Python in
    bin/ rather than Scripts/, Steam where this system keeps it, and a window
    that falls back to the browser. On the Linux CI these run for real."""
    import knoxmap
    import knoxpaths

    windows = os.name == "nt"

    # The map tools are Windows programs. Off Windows they go through Wine;
    # a build made for this system (no .exe) is run directly either way.
    wine_cmd = knoxpaths.command_for("/tools/bin/PZWorldEd_cli.exe")
    native = knoxpaths.command_for("/tools/bin/PZWorldEd_cli")
    check(len(native) == 1 and native[0].endswith("PZWorldEd_cli"),
          "a build of the map tools for this system is run directly")
    check(wine_cmd == ["/tools/bin/PZWorldEd_cli.exe"] if windows
          else (len(wine_cmd) == 2 and wine_cmd[0].endswith("wine")),
          "a .exe is run through Wine off Windows, and directly on it")
    os.environ["KNOXMAP_WINE"] = "/opt/wine/bin/wine"
    try:
        chosen = knoxpaths.command_for("/tools/bin/PZWorldEd_cli.exe")
        check(chosen[0] == "/opt/wine/bin/wine" if not windows else True,
              "KNOXMAP_WINE picks which Wine runs them")
    finally:
        del os.environ["KNOXMAP_WINE"]

    # Which compiler is in use decides what the paths in a project have to
    # look like. A build for this system reads the machine's own names; the
    # Windows one under Wine cannot, and needs the Z: form.
    check(not knoxpaths.through_wine("/tools/bin/PZWorldEd_cli"),
          "a build for this system is not going through Wine")
    check(knoxpaths.through_wine("/tools/bin/PZWorldEd_cli.exe") != windows,
          "a .exe is, off Windows")
    here = os.path.abspath(os.path.join(tempfile.gettempdir(), "knoxmap-paths"))
    if knoxpaths.through_wine():
        check(knoxpaths.tool_path(here).startswith(("Z:", "z:")) or ":" in knoxpaths.tool_path(here),
              "compiling through Wine hands the tools a Wine path")
    else:
        check(knoxpaths.tool_path(here) == here,
              "compiling with a native build hands the tools the real path")
    # Qt will not start without a platform plugin, and a compile draws
    # nothing, so a native build is asked for the offscreen one.
    env = knoxpaths.tool_env("/tools/bin/PZWorldEd_cli")
    check(windows or env.get("QT_QPA_PLATFORM") == "offscreen",
          "a native build is run headless, so no window opens mid-compile")
    check(knoxpaths.tool_env("/tools/bin/PZWorldEd_cli.exe").get("QT_QPA_PLATFORM")
          == os.environ.get("QT_QPA_PLATFORM"),
          "and the Windows build is left alone")

    # Setup fetches the compiler built for this system on Linux rather than
    # leaning on Wine, and checks what it downloaded.
    import inspect

    import knoxmap_setup
    check(len(knoxmap_setup.CLI_LINUX_SHA256) == 64
          and knoxmap_setup.CLI_LINUX_URL.endswith(".tar.gz"),
          "the Linux compiler is pinned by fingerprint, not just by name")
    source = inspect.getsource(knoxmap_setup.ensure_patched_cli)
    check("_install_linux_cli" in source and "linux" in source,
          "and Setup reaches for it before it reaches for Wine")

    # Setup puts the private Python in Scripts/ on Windows and bin/ elsewhere.
    python = str(knoxpaths.venv_python())
    wanted = "Scripts" if windows else "bin"
    check(python.endswith((".exe", "python", "python3"))
          and (wanted in python or python == sys.executable),
          f"the private Python is looked for in {wanted}/ ({os.path.basename(python)})")
    check(str(knoxpaths.venv_python(windowless=True)).endswith(
        "pythonw.exe" if windows else ("python", "python3")),
        "and the windowless one only where there is one")

    # Steam, where this system keeps it.
    roots = [str(p) for p in knoxpaths._steam_roots()]
    check(bool(roots) and all(("Steam" in r or "steam" in r) for r in roots),
          f"Steam is looked for where this system keeps it ({len(roots)} places)")
    check(all("\\" not in name for name in knoxpaths._LIBRARY_NAMES) if not windows
          else True,
          "and library folder names use this system's separator")
    check(knoxpaths.setup_command() == ("Setup.bat" if windows else "./setup.sh"),
          f"the window names the right setup script ({knoxpaths.setup_command()})")

    # macOS keeps the game inside an application bundle, so <game>/media is
    # not there and a Mac install was found and then turned away for having no
    # artwork in it. Every way somebody might name that install has to work.
    mac = Path(tempfile.mkdtemp()) / "Steam"
    bundle = mac / "steamapps/common/ProjectZomboid/ProjectZomboid.app"
    packs = bundle / "Contents/Java/media/texturepacks"
    packs.mkdir(parents=True)
    (packs / "Tiles2x.floor.pack").write_bytes(b"")
    game = mac / "steamapps/common/ProjectZomboid"
    ways = {
        "the Steam library": mac,
        "the game folder": game,
        "the .app": bundle,
        "inside the bundle": bundle / "Contents/Java",
        "the media folder": bundle / "Contents/Java/media",
    }
    missed = [what for what, path in ways.items()
              if (knoxpaths.pz_media_dir(knoxpaths.pz_install_from(path) or "") or Path("x"))
              != packs.parent]
    check(not missed,
          "the game inside a Mac .app is found however its folder is named"
          + (f" (missed: {missed})" if missed else ""))
    check(knoxpaths.is_build42(knoxpaths.pz_install_from(game)),
          "and Build 42 is recognised through the bundle")
    real = Path(tempfile.mkdtemp()) / "ProjectZomboid"
    (real / "media" / "texturepacks").mkdir(parents=True)
    check(knoxpaths.pz_media_dir(real) == real / "media",
          "while Windows and Linux still find <game>/media")
    linux_nested = Path(tempfile.mkdtemp()) / "ProjectZomboid"
    (linux_nested / "projectzomboid" / "media" / "texturepacks").mkdir(parents=True)
    check(knoxpaths.pz_media_dir(linux_nested) == linux_nested / "projectzomboid" / "media",
          "and Linux finds <game>/projectzomboid/media when nested")
    check(knoxpaths.pz_install_from(Path(tempfile.mkdtemp())) is None,
          "and a folder with no game in it is still refused")

    # A machine with no desktop toolkit still gets the whole app, in a browser.
    os.environ["KNOXMAP_BROWSER"] = "1"
    try:
        check(knoxmap.in_a_browser(), "KNOXMAP_BROWSER opens it in a browser instead")
    finally:
        del os.environ["KNOXMAP_BROWSER"]
    check(windows or not knoxpaths.wine() or knoxpaths.tools_runnable(),
          "with Wine on the path, the map tools count as runnable")

    # The project file the map tools read. Off Windows they are Windows
    # programs under Wine, which shows the filesystem as drive Z:, so what
    # is written in the .pzw is not what Python opens.
    import compile_map as compiler
    from knoxbuild.world import Placement, render_pzw

    work = tempfile.mkdtemp(prefix="knoxmap-tools-")
    try:
        project = Path(work) / "town"
        (project / "tmx").mkdir(parents=True)
        (project / "town.bmp").write_bytes(b"")
        pzw = project / "town.pzw"
        pzw.write_text(render_pzw(1, 1, "town.bmp", [Placement("buildings/a.tbx", 0, 0, 4, 4)],
                                  "town", project_dir=str(project)), encoding="utf-8")
        told = re.search(r'<tmxexportdir path="([^"]+)"', pzw.read_text(encoding="utf-8"))
        check(bool(told) and (told.group(1).startswith(("Z:", "/")) if not windows
                              else ":" in told.group(1)),
              f"the export folder is written as the tools read it ({told.group(1)[:24]}…)")
        # The cell is empty until the bitmap has been converted; once the
        # .tmx is there it is matched by its real name, whatever the .pzw
        # calls the folder it is in.
        check('map=""' in pzw.read_text(encoding="utf-8"),
              "a cell with nothing converted for it yet is left empty")
        (project / "tmx" / "town_70_0.tmx").write_text("<map/>", encoding="utf-8")
        assigned = compiler.assign_converted_maps(pzw)
        after = pzw.read_text(encoding="utf-8")
        check(assigned == 1 and 'map=""' not in after,
              "a converted cell is found on disk and written into the project")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # A release carries one file per system; the updater takes the right one.
    import updater
    three = {"assets": [{"name": "KnoxMap-v9.9-windows.zip"},
                        {"name": "KnoxMap-v9.9-linux.tar.gz"},
                        {"name": "KnoxMap-v9.9-macos.tar.gz"}]}
    want = "windows" if windows else ("macos" if sys.platform == "darwin" else "linux")
    picked = (updater._asset(three) or {}).get("name", "")
    check(want in picked, f"the updater takes the release built for this system ({picked})")
    named = {"assets": [{"name": "KnoxMap-v9.9-rnd-windows.zip"},
                        {"name": "KnoxMap-v9.9-rnd-linux.tar.gz"},
                        {"name": "KnoxMap-v9.9-rnd-macos.tar.gz"}]}
    # A named release puts the name in the filename too, and the name must not
    # be mistaken for the system - a Linux PC handed the Windows zip is worse
    # than no update at all.
    got = (updater._asset(named) or {}).get("name", "")
    check(want in got and got.endswith(".zip" if windows else ".tar.gz"),
          f"and from a named release too ({got})")

    # The map compiler is published from this repository too, and its tags are
    # dates: "worlded-cli-linux-20260909f" read as a version is 20260909, far
    # newer than any KnoxMap, and GitHub had made it the "latest" release. The
    # updater would have offered a player 30 MB of Qt as an upgrade.
    check(not updater._is_knoxmap({"tag_name": "worlded-cli-linux-20260909f"})
          and not updater._is_knoxmap({"tag_name": "worlded-cli-20260909f"}),
          "a release that is not KnoxMap is not an update")
    check(updater._is_knoxmap({"tag_name": "v1.3.9"})
          and not updater._is_knoxmap({"tag_name": "v1.3.9", "prerelease": True})
          and not updater._is_knoxmap({"tag_name": "v1.4.0", "draft": True}),
          "a released version of KnoxMap is, and a draft or a pre-release is not")

    # 1.4.1 was tagged without the v, so release.yml - which listened for
    # "v*" alone - never ran, and the release went out with no files on it.
    # Both ends of that are worth holding down.
    check(updater._is_knoxmap({"tag_name": "1.4.1"}),
          "a tag with no v in front of it is still a KnoxMap release")
    check(not updater._for_this_system({"tag_name": "v9.9", "assets": []})
          and updater._for_this_system(dict(three, tag_name="v9.9")),
          "and a release with nothing on it to download is not an update")

    # A release can be named on top of a version - "1.3.9 mc1" was the macOS
    # fix, "1.3.9 rnd" the pictures - and has to come out newer than the
    # version it sits on, or nobody is ever offered it.
    order = [("1.3.9 rnd", "1.3.9"), ("1.3.9 mc1", "1.3.9"),
             ("1.3.9 rnd", "1.3.9 mc1"), ("1.3.10", "1.3.9 rnd")]
    check(all(updater.is_newer(a, b) for a, b in order)
          and not updater.is_newer("1.3.9", "1.3.9 rnd")
          and not updater.is_newer("1.3.9", "1.3.9"),
          "a named release is newer than the version it is named after")
    check(updater._is_knoxmap({"tag_name": "v1.3.9-rnd"}),
          "and its tag is recognised as one of ours")
    check((updater._asset({"assets": [{"name": "KnoxMap-v1.3.6.zip"}]}) or {}).get("name")
          == "KnoxMap-v1.3.6.zip",
          "and a release from before they were split is still for everybody")

    # The launchers must keep LF, or /bin/sh chokes on the carriage returns.
    root = Path(__file__).resolve().parents[2]
    flow = root / ".github" / "workflows" / "release.yml"
    if flow.exists():
        # Whichever way a release is made - pushing the tag or drafting the
        # release on GitHub - the files have to get built, or the updater has
        # nothing to offer.
        text = flow.read_text(encoding="utf-8")
        check('tags: ["v*", "[0-9]*"]' in text and "types: [published]" in text,
              "release.yml builds for a tag either way, and for a release "
              "drafted by hand")

    for name in ("setup.sh", "knoxmap.sh"):
        path = root / name
        if path.exists():
            check(b"\r\n" not in path.read_bytes(), f"{name} has no carriage returns in it")


def check_qt_env(check) -> None:
    """The map compiler is made to find its own Qt, and a Qt that got away
    with it is explained rather than reported as a crash.

    The build for Linux carries the Qt it was compiled against in lib/ beside
    it, and records that folder as DT_RUNPATH - which the loader searches
    *after* LD_LIBRARY_PATH. Steam and Proton both export that, so on a
    machine with its own Qt 5 the compiler loaded the wrong one and Qt killed
    it mid-compile: "Cannot mix incompatible Qt library (5.15.13) with this
    library (5.15.3)", exit -6, reported from Linux Mint.
    """
    import knoxpaths

    windows = os.name == "nt"
    work = tempfile.mkdtemp(prefix="knoxmap-qt-")
    binary = Path(work) / "bin" / "PZWorldEd_cli"
    (binary.parent / "lib").mkdir(parents=True)
    (binary.parent / "plugins" / "platforms").mkdir(parents=True)
    binary.write_text("", encoding="utf-8")

    # One folder with a Qt of its own, as Steam and Proton put on the path,
    # and one with something else in it.
    theirs = Path(work) / "their-qt"
    theirs.mkdir()
    (theirs / "libQt5Core.so.5").write_bytes(b"not really Qt")
    plain = Path(work) / "their-other-libs"
    plain.mkdir()

    was = os.environ.get("LD_LIBRARY_PATH")
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join([str(theirs), str(plain)])
    try:
        env = knoxpaths.tool_env(binary)
    finally:
        if was is None:
            os.environ.pop("LD_LIBRARY_PATH", None)
        else:
            os.environ["LD_LIBRARY_PATH"] = was
    path = (env.get("LD_LIBRARY_PATH") or "").split(os.pathsep)
    check(windows or (path and path[0] == str(binary.parent / "lib")),
          "the compiler's own Qt goes ahead of the machine's on LD_LIBRARY_PATH")
    check(windows or str(plain) in path,
          "and what was already there is kept, not thrown away")
    check(windows or str(theirs) not in path,
          "except a folder carrying a Qt of its own, which is left off")
    check(windows or env.get("QT_QPA_PLATFORM_PLUGIN_PATH")
          == str(binary.parent / "plugins" / "platforms"),
          "and its own platform plugins are the ones it is pointed at")

    # Only offscreen and minimal are bundled, so an inherited platform could
    # only fail; a compile draws nothing whatever the desktop is.
    was = os.environ.get("QT_QPA_PLATFORM")
    os.environ["QT_QPA_PLATFORM"] = "wayland"
    try:
        forced = knoxpaths.tool_env(binary).get("QT_QPA_PLATFORM")
    finally:
        if was is None:
            os.environ.pop("QT_QPA_PLATFORM", None)
        else:
            os.environ["QT_QPA_PLATFORM"] = was
    check(windows or forced == "offscreen",
          "a desktop's own QT_QPA_PLATFORM does not follow the compiler in")

    real = ("QStandardPaths: XDG_RUNTIME_DIR not set\n"
            "Cannot mix incompatible Qt library (5.15.13) with this library (5.15.3)\n")
    said = knoxpaths.qt_trouble(real) or ""
    check("5.15.13" in said and "5.15.3" in said and "LD_LIBRARY_PATH" in said,
          "a Qt version clash is explained with both versions and what to do")
    check(knoxpaths.qt_trouble(
        "./PZWorldEd_cli: error while loading shared libraries: libQt5Core.so.5"),
        "so is a library the loader could not find at all")
    check(knoxpaths.qt_trouble("Generate Lots: batch 3 of 48, 12 cells") is None
          and knoxpaths.qt_trouble("") is None,
          "and an ordinary line is left alone - the check must not cry wolf")


def check_repair(check, out: str) -> None:
    """A project broken at its edges, as older versions and hand edits leave
    them, is repaired before compiling instead of stopping it."""
    from knoxbuild.repair import repair_project

    source = os.path.join(out, "selftest.pzw")
    broken = os.path.join(out, "broken.pzw")
    text = open(source, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in text else "\n"
    first_lot = re.search(r'map="(buildings/selftest_\d+\.tbx)"', text).group(1)
    # Not among the buildings: the checks further on read every file there.
    os.makedirs(os.path.join(out, "broken"), exist_ok=True)
    with open(os.path.join(out, "broken", "broken.tbx"), "w", encoding="utf-8") as f:
        f.write("<building version=\"4\" width=\"0\" height=\"3\"></building>")
    extra = nl.join([
        ' <cell x="9" y="0" map="">',                       # a whole cell past the edge
        f'  <lot x="5" y="5" level="0" width="3" height="3" map="{first_lot}"/>',
        " </cell>",
        ' <cell x="0" y="0" map="">',
        f'  <lot x="310" y="20" level="0" width="3" height="3" map="{first_lot}"/>',  # in cell 1,0 really
        '  <lot x="20" y="20" level="0" width="3" height="3" map="buildings/missing.tbx"/>',
        '  <lot x="30" y="20" level="0" width="3" height="3" map="broken/broken.tbx"/>',
        '  <object name="" group="TownZone" type="TownZone" x="10" y="950" level="0" width="5" height="5"/>',
        " </cell>",
    ])
    text = text.replace("</world>", extra + nl + "</world>")
    with open(broken, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    report = repair_project(broken)
    fixed = open(broken, encoding="utf-8").read()
    cells = [(int(a), int(b)) for a, b in re.findall(r'<cell x="(-?\d+)" y="(-?\d+)"', fixed)]
    size = re.search(r'<world version="[^"]*" width="(\d+)" height="(\d+)"', fixed)
    w, h = int(size.group(1)), int(size.group(2))
    reasons = " ".join(why for _what, why in report["dropped"])
    check(report["changed"] and report["moved"] == 1 and len(report["dropped"]) == 4
          and all(0 <= x < w and 0 <= y < h for x, y in cells)
          and len(cells) == len(set(cells))
          and "missing.tbx" not in fixed and "broken.tbx" not in fixed
          and "missing" in reasons and "outside" in reasons
          and os.path.exists(broken + ".bak"),
          f"a project broken at its edges is repaired, not refused "
          f"(moved {report['moved']}, dropped {len(report['dropped'])})")
    check(not repair_project(broken)["changed"] and not repair_project(source)["changed"],
          "a sound project is left exactly as it is")


def check_rpath(check) -> None:
    """The compiler's own Qt outranks whatever LD_LIBRARY_PATH names.

    patchelf writes DT_RUNPATH, which the loader searches *after*
    LD_LIBRARY_PATH, so Steam's or Proton's Qt was found first and Qt aborted
    on the spot. DT_RPATH is searched before it, and the change is one word:
    the tag number, in place.
    """
    import struct

    import knoxpaths

    def elf(tag: int) -> bytes:
        """A 64-bit ELF with one PT_DYNAMIC holding `tag` and DT_NULL."""
        dyn_at = 128
        head = bytearray(64)
        head[0:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<HHI", head, 0x10, 2, 0x3E, 1)     # EXEC, x86-64
        struct.pack_into("<Q", head, 0x20, 64)               # e_phoff
        struct.pack_into("<HH", head, 0x34, 64, 56)          # e_ehsize, phentsize
        struct.pack_into("<H", head, 0x38, 1)                # e_phnum
        ph = bytearray(56)
        struct.pack_into("<I", ph, 0, 2)                     # PT_DYNAMIC
        struct.pack_into("<Q", ph, 8, dyn_at)                # p_offset
        struct.pack_into("<Q", ph, 32, 32)                   # p_filesz
        body = struct.pack("<qQ", tag, 0x40) + struct.pack("<qQ", 0, 0)
        out = bytearray(dyn_at + 32)
        out[0:64] = head
        out[64:120] = ph
        out[dyn_at:dyn_at + 32] = body
        return bytes(out)

    def tag_of(raw: bytes) -> int:
        return struct.unpack_from("<q", raw, 128)[0]

    work = Path(tempfile.mkdtemp(prefix="knoxmap-rpath-"))
    runpath = work / "runpath.so"
    runpath.write_bytes(elf(29))                             # DT_RUNPATH
    size = runpath.stat().st_size
    check(knoxpaths._force_rpath(runpath) and tag_of(runpath.read_bytes()) == 15,
          "DT_RUNPATH becomes DT_RPATH, which the loader reads first")
    check(runpath.stat().st_size == size,
          "and the file is the same size, because only the tag changed")
    check(not knoxpaths._force_rpath(runpath),
          "one that already says DT_RPATH is left alone")

    for name, raw in (("nonsense.so", b"not an ELF at all"),
                      ("empty.so", b""),
                      ("32bit.so", b"\x7fELF\x01\x01\x01" + bytes(200))):
        path = work / name
        path.write_bytes(raw)
        before = path.read_bytes()
        check(not knoxpaths._force_rpath(path) and path.read_bytes() == before,
              f"and {name} is not touched")

    # Loading the right Qt is only half of it: Qt looks for its plugins under
    # the prefix it was compiled with, and on Ubuntu 24.04 that meant the
    # bundled Qt 5.15.3 reading the system's plugin tree and pulling 5.15.13
    # in behind it. qt.conf replaces the prefix.
    bin_dir = work / "bin"
    (bin_dir / "plugins" / "platforms").mkdir(parents=True)
    binary = bin_dir / "PZWorldEd_cli"
    binary.write_bytes(elf(29))
    check(knoxpaths.write_qt_conf(binary)
          and "Plugins=plugins" in (bin_dir / "qt.conf").read_text(encoding="utf-8"),
          "a qt.conf beside the compiler points Qt at the bundled plugins")
    check(not knoxpaths.write_qt_conf(binary),
          "and one that already says so is left alone")
    bare = work / "bare"
    bare.mkdir()
    check(not knoxpaths.write_qt_conf(bare / "PZWorldEd_cli")
          and not (bare / "qt.conf").exists(),
          "with no bundled plugins to point at, none is written")
    shutil.rmtree(work, ignore_errors=True)


def check_updater(check, work: str) -> None:
    """An update applied to a pretend install: new and changed files go in,
    dropped files go, and maps, logs and the Python environment are left alone."""
    import zipfile

    import updater

    base = Path(work) / "install"
    (base / "output" / "mytown").mkdir(parents=True)
    (base / "output" / "mytown" / "mytown.bmp").write_text("map")
    (base / ".venv").mkdir()
    (base / ".venv" / "keep.txt").write_text("env")
    (base / "knoxmap.py").write_text("old")
    (base / "dropped.py").write_text("gone in the new version")
    (base / "requirements.txt").write_text("flask")
    (base / "knoxmap_setup.py").write_text("setup")
    (base / updater.MANIFEST.name).write_text(json.dumps(
        {"version": "1.0", "files": ["knoxmap.py", "dropped.py", "requirements.txt",
                                     "knoxmap_setup.py"]}))
    update_dir = base / "update"
    update_dir.mkdir()
    zip_path = update_dir / "KnoxMap-v9.9.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("KnoxMap/knoxmap.py", "new")
        z.writestr("KnoxMap/requirements.txt", "flask")
        z.writestr("KnoxMap/knoxmap_setup.py", "setup")
        z.writestr("KnoxMap/added/module.py", "added")
        z.writestr("KnoxMap/output/mytown/mytown.bmp", "a release must not overwrite maps")
        z.writestr("KnoxMap/../escape.txt", "outside the folder")
    saved = {k: getattr(updater, k) for k in ("BASE_DIR", "UPDATE_DIR", "STAGED", "MANIFEST",
                                              "ASIDE_DIR", "FILE_TRIES", "FILE_GAP_S",
                                              "current_version", "enabled")}
    try:
        updater.BASE_DIR, updater.UPDATE_DIR = base, update_dir
        updater.STAGED, updater.MANIFEST = update_dir / "staged.json", base / saved["MANIFEST"].name
        updater.ASIDE_DIR = update_dir / "replaced"
        updater.FILE_TRIES, updater.FILE_GAP_S = 2, 0.01
        updater.current_version = lambda: "1.0"
        updater.enabled = lambda: True
        updater.STAGED.write_text(json.dumps({"version": "9.9", "zip": str(zip_path)}))
        applied = updater.apply_staged()
        check(applied and (base / "knoxmap.py").read_text() == "new"
              and (base / "added" / "module.py").exists() and not (base / "dropped.py").exists(),
              "an update puts in the new files and takes out the dropped ones")
        check((base / "output" / "mytown" / "mytown.bmp").read_text() == "map"
              and (base / ".venv" / "keep.txt").exists()
              and not (Path(work) / "escape.txt").exists(),
              "an update leaves maps and the Python environment alone and stays in its folder")
        check(not updater.STAGED.exists() and not zip_path.exists() and not updater.apply_staged(),
              "an update is applied once")
        # An older version goes in only when it was chosen in the version menu.
        old_zip = update_dir / "KnoxMap-v0.5.zip"
        with zipfile.ZipFile(old_zip, "w") as z:
            z.writestr("KnoxMap/knoxmap.py", "old release")
        updater.STAGED.write_text(json.dumps({"version": "0.5", "zip": str(old_zip)}))
        check(not updater.apply_staged() and (base / "knoxmap.py").read_text() == "new",
              "an automatic update never goes back to an older version")
        updater.STAGED.write_text(json.dumps({"version": "0.5", "zip": str(old_zip), "chosen": True}))
        updater.enabled = lambda: False       # choosing an older one turns them off
        check(updater.apply_staged() and (base / "knoxmap.py").read_text() == "old release",
              "a version chosen in the menu goes in, older ones too")
        check(updater.is_newer("1.10", "1.9") and not updater.is_newer("1.2", "1.2.0")
              and updater.is_newer("1.2.1", "1.2"), "versions compare as numbers")

        # One file that will not go in must not lose the whole update. Windows
        # refuses to overwrite a file another program has open - a virus
        # scanner reading KnoxMap.exe was enough - and the run used to stop
        # there with half the release in place, CHANGELOG.md among it, so
        # KnoxMap read as the new version and never looked again.
        updater.enabled = lambda: True
        (base / updater.VERSION_FILE).write_text("## 1.0\n")
        # A folder where the release has a file cannot be overwritten on any
        # system, which is the same dead end: the old one is moved aside.
        stuck = base / "stuck"
        stuck.mkdir()
        (stuck / "in the way").write_text("not something a file can replace")
        aside_zip = update_dir / "KnoxMap-v9.9.zip"
        with zipfile.ZipFile(aside_zip, "w") as z:
            z.writestr(f"KnoxMap/{updater.VERSION_FILE}", "## 9.9\n")
            z.writestr("KnoxMap/stuck", "a file where the install has a folder")
        updater.STAGED.write_text(json.dumps({"version": "9.9", "zip": str(aside_zip)}))
        check(updater.apply_staged() and (base / "stuck").is_file()
              and (updater.ASIDE_DIR / "stuck" / "in the way").exists(),
              "a file that will not be overwritten is moved aside and the update goes in")

        # And when it cannot even be moved: the version stays as it was and
        # the download waits for the next start rather than being thrown away.
        (base / updater.VERSION_FILE).write_text("## 1.0\n")
        (base / "locked").write_text("a file where the release has a folder")
        half_zip = update_dir / "KnoxMap-v9.9b.zip"
        with zipfile.ZipFile(half_zip, "w") as z:
            z.writestr(f"KnoxMap/{updater.VERSION_FILE}", "## 9.9\n")
            z.writestr("KnoxMap/locked/module.py", "cannot be unpacked over a file")
        updater.STAGED.write_text(json.dumps({"version": "9.9", "zip": str(half_zip)}))
        blocked = updater.apply_staged()
        left = json.loads(updater.STAGED.read_text()) if updater.STAGED.exists() else {}
        check(not blocked and (base / updater.VERSION_FILE).read_text().startswith("## 1.0")
              and left.get("tries") == 1 and half_zip.exists(),
              "an update that will not go in keeps the version it had and stays staged")
        (base / "locked").unlink()
        check(updater.apply_staged()
              and (base / "locked" / "module.py").exists()
              and (base / updater.VERSION_FILE).read_text().startswith("## 9.9"),
              "and the next start puts that update in")

        # A failure part way through moving files in: whatever was already
        # replaced goes back, so the install is not left half old and half new.
        for name in ("one.py", "two.py", "three.py"):
            (base / name).write_text(f"old {name}")
        (base / updater.VERSION_FILE).write_text("## 1.0\n")
        updater.MANIFEST.write_text(json.dumps({"version": "1.0", "files": []}))
        mid_zip = update_dir / "KnoxMap-v9.9c.zip"
        with zipfile.ZipFile(mid_zip, "w") as z:
            for name in ("one.py", "two.py", "three.py", "four.py"):
                z.writestr(f"KnoxMap/{name}", f"new {name}")
            z.writestr(f"KnoxMap/{updater.VERSION_FILE}", "## 9.9\n")
        updater.STAGED.write_text(json.dumps({"version": "9.9", "zip": str(mid_zip)}))
        real_put = updater._put_in_place
        calls = [0]

        def breaks_on_third(src, dest, rel, budget):
            calls[0] += 1
            if calls[0] == 3:
                raise OSError("a scanner has this one open")
            return real_put(src, dest, rel, budget)

        updater._put_in_place = breaks_on_third
        try:
            failed = not updater.apply_staged()
        finally:
            updater._put_in_place = real_put
        check(failed
              and all((base / n).read_text() == f"old {n}" for n in ("one.py", "two.py", "three.py"))
              and not (base / "four.py").exists()
              and (base / updater.VERSION_FILE).read_text().startswith("## 1.0")
              and mid_zip.exists(),
              "an update that fails part way through puts back the files it had replaced")
    finally:
        for k, v in saved.items():
            setattr(updater, k, v)


def check_workshop(check, work: str) -> None:
    """The pre-upload check finds a missing credit, a bad id and a missing picture."""
    import shutil

    from tools import workshop_check as wc

    root = os.path.join(work, "wmod", "My_Map")
    shutil.rmtree(os.path.dirname(root), ignore_errors=True)
    for where in ("", "common", "42"):
        os.makedirs(os.path.join(root, where), exist_ok=True)
        with open(os.path.join(root, where, "mod.info"), "w", encoding="utf-8") as f:
            f.write("name=My Map\nid=My_Map\ndescription=A map. Map data (c) OpenStreetMap contributors (ODbL).\n")
    maps = os.path.join(root, "common", "media", "maps", "My_Map")
    os.makedirs(maps)
    open(os.path.join(maps, "0_0.lotheader"), "wb").close()
    open(os.path.join(maps, "map.info"), "w").close()
    # Build 42 draws the in-game map (M) from worldmap.xml.bin and cannot read
    # the XML, so an installed mod has one (tools/make_map_mod.py).
    paper = os.path.join(maps, "worldmap.xml.bin")
    open(paper, "wb").close()
    with open(os.path.join(root, "ATTRIBUTION.txt"), "w", encoding="utf-8") as f:
        from knoxbuild import credits
        f.write("Map data (c) OpenStreetMap contributors, available under the Open Database "
                "License (ODbL)\n" + credits.plain())

    def levels():
        res = wc.check(root)
        return {r["level"] for r in res}, wc.summary(res)

    lv, s = levels()
    check("bad" not in lv and s["ready"] and s["warn"] == 1,
          "a complete mod is ready, with only the missing preview picture to warn about")
    Image.new("RGB", (300, 300)).save(os.path.join(root, "preview.png"))
    lv, s = levels()
    check(lv == {"ok"} and s["warn"] == 0, "and with a square preview it has nothing to say")
    os.remove(paper)
    res = wc.check(root)
    said = [r for r in res if "worldmap.xml.bin" in r["what"]]
    check("bad" in {r["level"] for r in res} and not wc.summary(res)["ready"] and said
          and "in-game map" in said[0]["what"],
          "a mod with no paper map is not ready, and says the in-game map will be blank")
    open(paper, "wb").close()
    Image.new("RGB", (300, 200)).save(os.path.join(root, "preview.png"))
    check(levels()[1]["warn"] == 1, "a preview that is not square is warned about")
    with open(os.path.join(root, "preview.png"), "wb") as f:
        f.write(b"not a png")
    check(not levels()[1]["ready"], "a preview that is not a PNG stops it")
    os.remove(os.path.join(root, "preview.png"))
    with open(os.path.join(root, "ATTRIBUTION.txt"), "w", encoding="utf-8") as f:
        f.write("made with KnoxMap")
    check(not levels()[1]["ready"], "an attribution without the OpenStreetMap credit stops it")
    with open(os.path.join(root, "ATTRIBUTION.txt"), "w", encoding="utf-8") as f:
        f.write("Map data (c) OpenStreetMap contributors, available under the Open Database\nLicense (ODbL)")
    check("bad" not in levels()[0], "the credit passes when the file wraps it over two lines")
    os.remove(os.path.join(root, "ATTRIBUTION.txt"))
    check(not levels()[1]["ready"], "no attribution file stops it")
    with open(os.path.join(root, "mod.info"), "w", encoding="utf-8") as f:
        f.write("name=x\nid=bad id!\ndescription=nothing\n")
    check(not levels()[1]["ready"], "a mod id with odd characters and a copy that differs stop it")
    check(not wc.summary(wc.check(os.path.join(work, "nowhere")))["ready"],
          "a mod that is not installed is not ready")


def check_worlded_size(check) -> None:
    """A map WorldEd cannot compile is refused before it is made, and told how to fit."""
    import app as knoxapp
    from tools.compile_map import WORLDED_MAX_PIXELS, bitmap_pixels, scale_that_fits

    box = {"south": 34.84560, "west": -120.76103, "north": 35.18564, "east": -120.38612}
    r = knoxapp.app.test_client().post("/api/generate", json={**box, "metersPerTile": 2})
    said = (r.get_json() or {}).get("error", "")
    check(r.status_code == 400 and "WorldEd cannot compile" in said and "At 3 m a tile" in said,
          f"a 345 million tile map is refused, with the scale that fits ({said[:60]!r})")
    check(bitmap_pixels(13800, 18600) <= WORLDED_MAX_PIXELS < bitmap_pixels(16500, 16500)
          and bitmap_pixels(1, 1) == 300 * 300
          and scale_that_fits(17700, 19500, 2.0) == 3 and scale_that_fits(10 ** 6, 10 ** 6, 100.0) is None,
          "the size limit sits between a map that compiled and one that did not")

