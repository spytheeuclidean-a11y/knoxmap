#!/usr/bin/env bash
# KnoxMap setup on Linux or macOS. Safe to run again.
#
# The same as Setup.bat: a private Python environment beside this file, the PZ
# Mapping Tools, the patched map compiler, and the tile artwork from your own
# copy of the game. The tools are Windows programs; here they run under Wine,
# which a PC that plays Project Zomboid through Proton already has. See
# LINUX.md.
set -euo pipefail
cd "$(dirname "$0")"

# UTF-8 for every file Python reads and writes, whatever the locale is.
export PYTHONUTF8=1

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10) or sys.maxsize <= 2**32)' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "KnoxMap needs 64-bit Python 3.10 or newer."
  echo "Install it with your package manager, for example:"
  echo "    sudo apt install python3 python3-venv python3-pip     # Debian, Ubuntu"
  echo "    sudo pacman -S python                                 # Arch"
  echo "    sudo dnf install python3                              # Fedora"
  exit 1
fi

# Part of Python itself gone missing - a distribution that splits it into
# packages, or antivirus taking a file out - is not something pip can put back,
# and it surfaces much later as "No module named 'xml.etree.ElementTree'" in
# the middle of a build. Say so now, with the package to install.
if ! "$PY" -c "import xml.etree.ElementTree, xml.sax.saxutils, zlib, hashlib, zipfile, tarfile, ssl, ctypes" 2>/dev/null; then
  echo "The Python found on this machine is missing part of its own library."
  echo "pip cannot put that back. Install the full Python from your package manager:"
  echo "    sudo apt install python3 python3-venv python3-pip     # Debian, Ubuntu"
  echo "    sudo dnf install python3                              # Fedora"
  exit 1
fi

# An environment built by a 32-bit Python stays 32-bit, and a town-sized map
# needs more memory than one can address.
if [ -x ".venv/bin/python" ] && ! .venv/bin/python -c 'import sys; sys.exit(sys.maxsize <= 2**32)' 2>/dev/null; then
  echo "The Python environment is 32-bit, which runs out of memory on a big map."
  echo "Making it again with 64-bit Python..."
  rm -rf .venv
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating the Python environment..."
  "$PY" -m venv .venv
fi
echo "Installing Python packages..."
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt

# Both of these are worth saying before the long download, not after it.
if [ "$(uname -s)-$(uname -m)" != "Linux-x86_64" ] &&
   ! command -v wine >/dev/null 2>&1 && ! command -v wine64 >/dev/null 2>&1; then
  echo
  echo "Note: wine was not found. Everything works except Compile, which on"
  echo "this system runs the map tools' Windows build. Install wine, or build"
  echo "the tools for this system and put them in vendor/PZMappingTools/bin -"
  echo "see LINUX.md. (On 64-bit Linux the compiler is fetched for you.)"
  echo
fi

if [ "$(uname -s)" != "Darwin" ] &&
   ! .venv/bin/python -c 'from webview import guilib; guilib.initialize()' >/dev/null 2>&1; then
  echo
  echo "Note: no desktop toolkit for a native window, so KnoxMap will open in"
  echo "your browser instead. That is the whole app - nothing is missing. For"
  echo "a window of its own, install one of these and run KnoxMap again:"
  echo "    sudo apt install python3-gi gir1.2-webkit2-4.1 python3-gi-cairo"
  echo "    .venv/bin/python -m pip install \"pywebview[qt]\""
  echo
fi

.venv/bin/python knoxmap_setup.py
echo
echo "Start KnoxMap with ./knoxmap.sh"
