"""Check what you changed, not everything: lint the changed files and run only
the tests that can see them.

    python tools/quick_check.py [--base REF] [--depth N] [--slow] [--selftest] [-j N]

Changed files are the working tree against HEAD (staged, unstaged and new), or
against REF with --base (a branch's whole change). A test module is picked when
it imports a changed module, directly or through one module between (--depth), or
is itself changed. A change to something almost everything imports (the
catalogue, the footprint code) picks nearly every test; that is said, and
the full runner is the better tool then.
"""
from __future__ import annotations

import argparse
import ast
import json
import concurrent.futures
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

PACKAGES = ("knoxbuild", "generator", "web", "tools")
TOP_LEVEL = ("knoxfiles", "knoxpaths", "knoxstop", "app")
# More than this share of the tests picked: say so, the change reaches everything.
CORE_SHARE = 0.6


def changed_files(base: str | None) -> list[str]:
    def git(*args) -> list[str]:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
        return [line for line in out.stdout.splitlines() if line]

    files = set(git("diff", "--name-only", base or "HEAD"))
    if not base:
        files |= set(git("ls-files", "--others", "--exclude-standard"))
    return sorted(f.replace("\\", "/") for f in files if (ROOT / f).exists())


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imports_of(path: Path) -> set[str]:
    """Every repo module this file imports, as dotted names (relative imports resolved)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    here = module_name(path).split(".")
    package = here if path.name == "__init__.py" else here[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[:len(package) - node.level + 1]
                prefix = ".".join(base + ([node.module] if node.module else []))
            else:
                prefix = node.module or ""
            found.add(prefix)
            found.update(f"{prefix}.{a.name}" for a in node.names)
    return {n for n in found if n.split(".")[0] in PACKAGES + TOP_LEVEL + ("tests",)}


def repo_modules() -> dict[str, Path]:
    mods = {}
    for pkg in PACKAGES + ("tests",):
        for p in (ROOT / pkg).rglob("*.py"):
            if "__pycache__" not in p.parts and ".venv" not in p.parts:
                mods[module_name(p)] = p
    for top in TOP_LEVEL:
        if (ROOT / f"{top}.py").exists():
            mods[top] = ROOT / f"{top}.py"
    return mods


def affected(changed: list[str], depth: int = 2) -> tuple[list[str], dict]:
    mods = repo_modules()
    deps = {name: imports_of(path) & set(mods) for name, path in mods.items()}
    reverse: dict[str, set[str]] = {}
    for name, ds in deps.items():
        for d in ds:
            reverse.setdefault(d, set()).add(name)
    seeds = {module_name(ROOT / f) for f in changed if f.endswith(".py")
             and module_name(ROOT / f) in mods}
    reach, frontier = set(seeds), set(seeds)
    for _ in range(depth):
        frontier = {d for m in frontier for d in reverse.get(m, ())} - reach
        reach |= frontier
    tests = sorted(m.split(".", 1)[1] for m in reach
                   if m.startswith("tests.") and m.count(".") == 1
                   and m.split(".", 1)[1].startswith("test_"))
    return tests, {"seeds": sorted(seeds), "reached": len(reach)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", help="compare against this ref instead of HEAD")
    ap.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--depth", type=int, default=2,
                    help="how many importers away still count (default 2; 99 is all of them)")
    ap.add_argument("--slow", action="store_true", help="include the modules that take long")
    ap.add_argument("--slow-limit", type=float, default=45.0,
                    help="seconds a module took last time, above which it is left out")
    ap.add_argument("--selftest", action="store_true", help="also run tools/selftest.py --fast")
    ap.add_argument("--list", action="store_true", help="only say what would run")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    changed = changed_files(args.base)
    py = [f for f in changed if f.endswith(".py")]
    print(f"{len(changed)} changed file(s), {len(py)} Python")
    if not changed:
        print("nothing changed")
        return 0

    status = 0
    if py:
        lint = subprocess.run([sys.executable, "-m", "ruff", "check", *py], cwd=ROOT)
        print("lint: " + ("ok" if lint.returncode == 0 else "FAILED"))
        status |= lint.returncode != 0

    tests, info = affected(changed, args.depth)
    every = len(list((ROOT / "tests").glob("test_*.py")))
    if any(not f.endswith(".py") and f.startswith(("static/", "lang/")) for f in changed):
        print("(front-end or language files changed: tests/test_i18n* are added)")
        tests = sorted(set(tests) | {p.stem for p in (ROOT / "tests").glob("test_i18n*.py")})
    print(f"{len(tests)} of {every} test modules can see the change")
    if every and len(tests) / every > CORE_SHARE:
        print("  that is most of them: the change is to something everything imports;"
              " tools/run_tests.py runs all of it the same way")
    left_out = []
    if not args.slow:
        times = {}
        try:
            times = json.loads((ROOT / ".test_timings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        left_out = [(m, times[m]) for m in tests if times.get(m, 0) > args.slow_limit]
        tests = [m for m in tests if m not in dict(left_out)]
        if left_out:
            print("left out as slow (--slow to include): " + ", ".join(
                f"{m} {t:.0f}s" for m, t in sorted(left_out, key=lambda x: -x[1])))
    if args.list or not tests:
        print("\n".join(f"  {t}" for t in tests))
        return status

    import run_tests
    failures = []
    ran = failed = 0
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_tests._run_module, m) for m in
                   sorted(tests, key=lambda m: -(ROOT / "tests" / f"{m}.py").stat().st_size)]
        for fut in concurrent.futures.as_completed(futures):
            mod, n, bad, _skipped, secs, detail = fut.result()
            ran += n
            failed += bad
            print(f"  {'FAIL' if bad else 'ok  '}  {mod:34} {n:4} tests ({secs:.1f}s)", flush=True)
            if detail:
                failures.append((mod, detail))
    for mod, detail in failures:
        print(f"\n=== {mod} ===\n{detail}", file=sys.stderr)
    status |= failed > 0

    if args.selftest:
        st = subprocess.run([sys.executable, "tools/selftest.py", "--fast"], cwd=ROOT)
        print("selftest --fast: " + ("ok" if st.returncode == 0 else "FAILED"))
        status |= st.returncode != 0

    print(f"\n{ran} tests, {failed} failed, in {time.monotonic() - t0:.1f}s")
    return int(bool(status))


if __name__ == "__main__":
    raise SystemExit(main())
