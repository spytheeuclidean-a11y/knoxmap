"""Dependency readiness probe shared by launchers and setup; standard library only."""
import importlib
import sys

MIN_PYTHON = (3, 12)
MIN_VC_RUNTIME = (14, 51, 36247, 0)
VC_RUNTIME_URL = 'https://aka.ms/vc14/vc_redist.x64.exe'
NEEDED = ('flask', 'requests', 'numpy', 'PIL', 'pyproj', 'shapely')


def vc_runtime_version():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            if winreg.QueryValueEx(key, 'Installed')[0] != 1:
                return None
            return tuple(winreg.QueryValueEx(key, name)[0] for name in ('Major', 'Minor', 'Bld', 'Rbld'))
    except OSError:
        return None


def check_vc_runtime():
    if sys.platform != 'win32':
        return 0
    version = vc_runtime_version()
    if version is not None and version >= MIN_VC_RUNTIME:
        return 0
    if sys.stderr is not None:
        required = '.'.join(map(str, MIN_VC_RUNTIME))
        print(f'KnoxMap needs the Microsoft Visual C++ x64 runtime {required} or newer. '
              f'Install it from {VC_RUNTIME_URL} and run Setup again.', file=sys.stderr)
    return 1


def check():
    if sys.version_info < MIN_PYTHON or sys.maxsize <= 2**32:
        if sys.stderr is not None:
            print(f'KnoxMap needs 64-bit Python 3.12 or newer: {sys.executable}', file=sys.stderr)
        return 1
    if check_vc_runtime():
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
    raise SystemExit(check_vc_runtime() if sys.argv[1:] == ['--check-vc'] else check())
