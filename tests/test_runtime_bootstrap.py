"""Incomplete environments must be repaired before the window starts."""
import contextlib
import ctypes
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import knoxruntime

ROOT = Path(__file__).resolve().parents[1]


class RuntimeCheck(unittest.TestCase):
    def test_missing_flask_is_reported_with_the_interpreter(self):
        error = io.StringIO()
        with mock.patch.object(knoxruntime.importlib, 'import_module', side_effect=ModuleNotFoundError("No module named 'flask'")), \
                contextlib.redirect_stderr(error):
            self.assertEqual(knoxruntime.check(), 1)
        self.assertIn('flask', error.getvalue())
        self.assertIn(sys.executable, error.getvalue())

    def test_latest_python_is_not_rejected_by_an_upper_version_limit(self):
        with mock.patch.object(knoxruntime.sys, 'version_info', (3, 15)), \
                mock.patch.object(knoxruntime.importlib, 'import_module') as load:
            self.assertEqual(knoxruntime.check(), 0)
        self.assertEqual([call.args[0] for call in load.call_args_list], list(knoxruntime.NEEDED))

    def test_python_too_old_for_the_pinned_packages_is_rejected(self):
        with mock.patch.object(knoxruntime.sys, 'version_info', (3, 11)), \
                mock.patch.object(knoxruntime.importlib, 'import_module') as load, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(knoxruntime.check(), 1)
        load.assert_not_called()

    def test_real_python_without_site_packages_fails_without_opening_the_app(self):
        result = subprocess.run([sys.executable, '-S', str(ROOT/'knoxruntime.py')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1)
        self.assertIn('flask', result.stderr)

    def test_all_launchers_and_setup_use_the_same_runtime_probe(self):
        for name in ('KnoxMap.bat', 'Setup.bat', 'knoxmap.sh', 'setup.sh', 'win/knoxmap_launcher.c'):
            with self.subTest(name=name):
                self.assertIn('knoxruntime.py', (ROOT/name).read_text(encoding='utf-8'))


@unittest.skipUnless(os.name == 'nt', 'Windows launchers')
class WindowsLaunch(unittest.TestCase):
    def run_fixture(self, initially_ready, setup_repairs, setup_code, native=False):
        with tempfile.TemporaryDirectory(prefix='KnoxMap runtime ') as temp:
            folder = Path(temp)
            subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(folder/'.venv')],
                           check=True, capture_output=True, timeout=60)
            shutil.copyfile(ROOT/'KnoxMap.bat', folder/'KnoxMap.bat')
            if native:
                shutil.copyfile(ROOT/'KnoxMap.exe', folder/'KnoxMap.exe')
            (folder/'knoxruntime.py').write_text(
                "from pathlib import Path\nraise SystemExit(0 if Path('ready').exists() else 1)\n")
            (folder/'knoxmap.py').write_text(
                "import os\nfrom pathlib import Path\n"
                "Path('started').write_text(f'{os.getpid()} {os.getppid()}')\n")
            (folder/'Setup.bat').write_bytes(('@echo off\r\necho yes>setup-called\r\n'
                + ('echo yes>ready\r\n' if setup_repairs else '')
                + f'exit /b {setup_code}\r\n').encode())
            if initially_ready:
                (folder/'ready').write_text('yes')
            command = [str(folder/'KnoxMap.exe')] if native else ['cmd.exe', '/d', '/c', str(folder/'KnoxMap.bat')]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=30,
                                    env=dict(os.environ, KNOXMAP_NO_PAUSE='1'),
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            should_start = initially_ready or setup_repairs
            if should_start:
                deadline = time.monotonic()+10
                while not (folder/'started').exists() and time.monotonic() < deadline:
                    time.sleep(.05)
            self.assertEqual(result.returncode, 0 if should_start else 1, result.stdout)
            self.assertEqual((folder/'started').exists(), should_start)
            self.assertEqual((folder/'setup-called').exists(), not initially_ready)
            if should_start:
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
                kernel.OpenProcess.restype = ctypes.c_void_p
                kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
                kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
                # Windows venv pythonw is a redirector that outlives its Python child.
                for pid in map(int, (folder/'started').read_text().split()):
                    handle = kernel.OpenProcess(0x100000, False, pid)
                    if handle:
                        try:
                            self.assertEqual(kernel.WaitForSingleObject(handle, 10000), 0)
                        finally:
                            kernel.CloseHandle(handle)

    def test_bat_repairs_a_partial_environment_and_verifies_before_launch(self):
        for ready, repair, code in ((True, False, 0), (False, True, 0),
                                     (False, False, 1), (False, True, 1)):
            with self.subTest(ready=ready, repair=repair, setup_code=code):
                self.run_fixture(ready, repair, code)

    @unittest.skipUnless((ROOT/'KnoxMap.exe').exists(), 'build the native launcher')
    def test_native_launcher_checks_its_own_environment_from_another_directory(self):
        self.run_fixture(True, False, 0, native=True)
