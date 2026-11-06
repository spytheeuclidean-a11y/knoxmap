"""Dependency readiness probe shared by launchers and setup; standard library only."""
import importlib
import sys

MIN_PYTHON = (3, 12)
NEEDED = ('flask', 'requests', 'numpy', 'PIL', 'pyproj', 'shapely')


def check():
    if sys.version_info < MIN_PYTHON or sys.maxsize <= 2**32:
        if sys.stderr is not None:
            print(f'KnoxMap needs 64-bit Python 3.12 or newer: {sys.executable}', file=sys.stderr)
        return 1
    for name in NEEDED:
        try:
            importlib.import_module(name)
        except Exception as exc:  # a missing package or one whose DLL/dependencies cannot load
            if sys.stderr is not None:
                print(f"Required package {name!r} could not load in {sys.executable}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(check())
