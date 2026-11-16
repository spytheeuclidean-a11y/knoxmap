#!/usr/bin/env bash
# Build KnoxMap.exe, the launcher people double-click, with mingw-w64.
#
# The release builds it with MSVC instead (win/build_launcher.ps1),
# because antivirus heuristics treat a small mingw-built binary that
# spawns a process as the thing it structurally resembles. This is the
# same launcher from the same source, for building on Linux - and for
# anyone who would rather not need Visual Studio to check what ships.
#
#     sudo apt install gcc-mingw-w64-x86-64 binutils-mingw-w64-x86-64
#     win/build_launcher.sh [version]
#
# Writes KnoxMap.exe next to this repository's other files. It is not
# committed: the release workflow builds it and puts it in the Windows
# download only. See win/knoxmap_launcher.c for what it does.
set -euo pipefail
cd "$(dirname "$0")/.."

version="${1:-}"
if [ -z "$version" ]; then
  version="$(sed -n 's/^## \([0-9][0-9.]*\).*/\1/p' CHANGELOG.md | head -1)"
fi
major="$(echo "$version" | cut -d. -f1)"
minor="$(echo "$version" | cut -d. -f2)"
patch="$(echo "$version" | cut -d. -f3)"
build="$(echo "$version" | cut -d. -f4)"
: "${major:=0}" "${minor:=0}" "${patch:=0}" "${build:=0}"
if [ "$build" -gt 65535 ] 2>/dev/null; then build=0; fi

CC="${CC:-x86_64-w64-mingw32-gcc}"
WINDRES="${WINDRES:-x86_64-w64-mingw32-windres}"
for tool in "$CC" "$WINDRES"; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "$tool not found. On Debian or Ubuntu:" >&2
    echo "    sudo apt install gcc-mingw-w64-x86-64 binutils-mingw-w64-x86-64" >&2
    exit 1
  }
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
sed -e "s/@MAJOR@/$major/g" -e "s/@MINOR@/$minor/g" -e "s/@PATCH@/$patch/g" \
    -e "s/@BUILD@/$build/g" -e "s/@VERSION@/$version/g" win/knoxmap.rc > "$work/knoxmap.rc"
# The .rc names branding/knoxmap.ico relative to where windres is run.
"$WINDRES" -I. "$work/knoxmap.rc" -O coff -o "$work/knoxmap.res"

# -mwindows: no console window of its own. -municode: wWinMain, so the whole
# launcher is wide-character and a folder with any name in it works.
# No -s: a tiny binary with every symbol stripped out of it reads as
# something with something to hide, and 30 KB is not worth that.
"$CC" -O2 -municode -mwindows -Wall -Wextra \
      -o KnoxMap.exe win/knoxmap_launcher.c "$work/knoxmap.res" -luser32

echo "built KnoxMap.exe for KnoxMap $version"
file KnoxMap.exe 2>/dev/null || true
