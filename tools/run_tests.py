"""Run the unittest suite in parallel across test modules.

    python tools/run_tests.py [-j JOBS] [pattern ...]

Each matching ``tests/test_*.py`` module runs in its own worker process
(largest files scheduled first so long suites do not trail at the end).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import io
import json
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMINGS = ROOT / ".test_timings.json"


def _run_module(module_name: str) -> tuple[str, int, int, int, float, str]:
    """Run one test module in a worker process and return summary + failure text."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    t0 = time.monotonic()
    buf = io.StringIO()
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName(f"tests.{module_name}")
    runner = unittest.TextTestRunner(stream=buf, verbosity=1)
    result = runner.run(suite)
    elapsed = time.monotonic() - t0
    skipped = len(result.skipped)
    failed = len(result.failures) + len(result.errors)
    detail = buf.getvalue() if not result.wasSuccessful() else ""
    return module_name, result.testsRun, failed, skipped, elapsed, detail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run unittest modules in parallel.")
    ap.add_argument("-j", "--jobs", type=int, default=max(1, os.cpu_count() or 4),
                    help="Worker processes (default: CPU count)")
    ap.add_argument("patterns", nargs="*",
                    help="Optional substrings to filter test_*.py module names")
    args = ap.parse_args(argv)

    tests_dir = ROOT / "tests"
    paths = sorted(tests_dir.glob("test_*.py"), key=lambda p: -p.stat().st_size)
    if args.patterns:
        paths = [p for p in paths if any(pat in p.stem for pat in args.patterns)]
    if not paths:
        print("No matching test modules found.", file=sys.stderr)
        return 1

    modules = [p.stem for p in paths]
    t0 = time.monotonic()
    total_run = 0
    total_failed = 0
    total_skipped = 0
    failures: list[tuple[str, str]] = []
    timings: dict[str, float] = {}

    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(_run_module, m): m for m in modules}
        for fut in concurrent.futures.as_completed(futures):
            mod, ran, failed, skipped, elapsed, detail = fut.result()
            total_run += ran
            total_failed += failed
            total_skipped += skipped
            timings[mod] = round(elapsed, 1)
            status = "FAIL" if failed else "ok"
            print(f"  {status:4}  {mod:32} {ran:4} tests  ({elapsed:.1f}s)", flush=True)
            if detail:
                failures.append((mod, detail))

    # What each module took, so tools/quick_check.py can leave the slow ones out.
    try:
        old = json.loads(TIMINGS.read_text(encoding="utf-8")) if TIMINGS.exists() else {}
        TIMINGS.write_text(json.dumps({**old, **timings}, indent=1, sort_keys=True),
                           encoding="utf-8")
    except (OSError, ValueError):
        pass

    for mod, detail in failures:
        print(f"\n=== {mod} ===", file=sys.stderr)
        print(detail, file=sys.stderr)

    wall = time.monotonic() - t0
    print(f"\nRan {total_run} tests across {len(modules)} modules in {wall:.1f}s "
          f"(workers={args.jobs}, skipped={total_skipped}, failed={total_failed})")
    return 1 if total_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
