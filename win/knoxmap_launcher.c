/* KnoxMap.exe - what KnoxMap.bat did, as something you can double-click.
 *
 * A batch file opens a console window, can be blocked by policy, and looks
 * like something you should not run. This does the same four things and
 * nothing else:
 *
 *   1. work in the folder it is in, wherever that is,
 *   2. PYTHONUTF8=1, so every file KnoxMap reads and writes is UTF-8 on a
 *      Windows whose code page cannot hold all of its text,
 *   3. run Setup.bat first, in a console of its own, if there is no
 *      working environment yet - that is the long first run, and it has to be
 *      watchable,
 *   4. start .venv\Scripts\pythonw.exe knoxmap.py and exit straight away.
 *
 * Exiting straight away matters: an update replaces the files in this
 * folder, and Windows will not overwrite a running .exe.
 *
 * KnoxMap.bat is still there and still works, for anyone who would rather
 * read what they are running than trust a binary.
 *
 * Built by .github/workflows/release.yml with mingw-w64; it is not committed
 * as a binary.
 */
#include <windows.h>
#include <stdio.h>

#define PYTHONW L".venv\\Scripts\\pythonw.exe"

static void say(const wchar_t *what) {
    MessageBoxW(NULL, what, L"KnoxMap", MB_ICONERROR | MB_OK);
}

static BOOL there(const wchar_t *path) {
    return GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES;
}

/* Run a command line and wait for it. Its exit code, or -1 if it would not
 * start at all. */
static int run_and_wait(wchar_t *line, DWORD flags) {
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    DWORD code = (DWORD)-1;

    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    ZeroMemory(&pi, sizeof pi);
    if (!CreateProcessW(NULL, line, NULL, NULL, FALSE, flags, NULL, NULL, &si, &pi)) {
        return -1;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)code;
}

static BOOL runtime_ready(void) {
    wchar_t probe[] = L"\"" PYTHONW L"\" \"knoxruntime.py\"";
    return there(PYTHONW) && there(L"knoxruntime.py") &&
           run_and_wait(probe, CREATE_NO_WINDOW) == 0;
}

int WINAPI wWinMain(HINSTANCE self, HINSTANCE previous, PWSTR args, int show) {
    static wchar_t here[32768];
    static wchar_t line[32768];
    DWORD n;
    size_t i;
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;

    (void)self; (void)previous; (void)show;

    /* The folder this .exe is in, whatever the working directory was. */
    n = GetModuleFileNameW(NULL, here, (DWORD)(sizeof here / sizeof here[0]));
    if (n == 0 || n >= sizeof here / sizeof here[0]) {
        say(L"KnoxMap could not work out which folder it is in.");
        return 1;
    }
    for (i = n; i > 0; i--) {
        if (here[i - 1] == L'\\' || here[i - 1] == L'/') {
            here[i - 1] = L'\0';
            break;
        }
    }
    if (!SetCurrentDirectoryW(here)) {
        say(L"KnoxMap could not open the folder it is in.");
        return 1;
    }
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");

    /* First run: setup builds the environment and fetches the map tools.
     * It takes minutes and says what it is doing, so it gets a console. */
    if (!runtime_ready()) {
        int code;
        if (!there(L"Setup.bat")) {
            say(L"KnoxMap is not set up yet and Setup.bat is missing.\n\n"
                L"Unpack the whole KnoxMap folder from the release and run "
                L"KnoxMap.exe from inside it.");
            return 1;
        }
        wcscpy(line, L"cmd.exe /c \"Setup.bat\"");
        code = run_and_wait(line, CREATE_NEW_CONSOLE);
        if (code < 0) {
            say(L"KnoxMap could not start Setup.bat.");
            return 1;
        }
        /* Missing map tools can be repaired later; Python packages cannot. */
        if (!runtime_ready()) {
            say(L"Setup did not finish, so KnoxMap cannot start.\n\n"
                L"Run Setup.bat on its own to see what it says; the whole run "
                L"is written to logs\\setup.log.");
            return 1;
        }
    }

    /* Start the window and get out of the way, so an update is free to
     * replace this file. */
    if (args != NULL && args[0] != L'\0') {
        _snwprintf(line, sizeof line / sizeof line[0] - 1,
                   L"\"" PYTHONW L"\" \"knoxmap.py\" %s", args);
    } else {
        _snwprintf(line, sizeof line / sizeof line[0] - 1,
                   L"\"" PYTHONW L"\" \"knoxmap.py\"");
    }
    line[sizeof line / sizeof line[0] - 1] = L'\0';

    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    ZeroMemory(&pi, sizeof pi);
    if (!CreateProcessW(NULL, line, NULL, NULL, FALSE,
                        DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                        NULL, NULL, &si, &pi)) {
        say(L"KnoxMap could not start.\n\n"
            L"Running Setup.bat again fixes most causes; if it does not, "
            L"post logs\\knoxmap.log in #bug-reports on the KnoxMap Discord.");
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
