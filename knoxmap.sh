#!/usr/bin/env bash
# Launch KnoxMap on Linux or macOS. First run? setup.sh does the rest.
#
# KNOXMAP_BROWSER=1 ./knoxmap.sh   opens it in your browser even where there
#                                  is a desktop toolkit for a real window.
# KNOXMAP_WINE=/path/to/wine       runs the map tools with that Wine.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONUTF8=1
if [ ! -x ".venv/bin/python" ] || ! .venv/bin/python knoxruntime.py >/dev/null 2>&1; then
  echo "Setting up or repairing KnoxMap's Python environment."
  ./setup.sh
fi
.venv/bin/python knoxruntime.py
exec .venv/bin/python knoxmap.py "$@"
