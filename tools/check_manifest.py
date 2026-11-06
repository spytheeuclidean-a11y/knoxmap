"""Does .knoxmap_files.json list what a release actually ships?

An update deletes every file the previous release listed and this one does not
(updater.py), so the manifest is not paperwork. A new module missing from it
never reaches anybody's PC - the copy that installs the update keeps the old
files and finds no new one - and a line left behind makes every update try to
delete a file that is not there. Neither is visible until a player reports it,
which is why this runs in CI.

What a release ships is what release.yml puts in the zip: `git archive HEAD`,
which honours .gitattributes export-ignore, plus the two binaries the release
step copies in. Asking git for that list, rather than walking the folder, is
the difference between a check and a nuisance - the folder also holds build
output, logs and scratch directories that never go near a release.

    python tools/check_manifest.py

Prints what disagrees and exits 1, or exits 0 saying how many files it checked.
Without a git checkout (a zip download, say) there is nothing to compare with
and it says so; in CI, where git is always there, that is a failure instead.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / ".knoxmap_files.json"

# Copied into each download after `git archive` ran (release.yml), so they are
# in the release without being in the tree git knows about.
ADDED_BY_RELEASE = {"KnoxMap.exe", "knoxlots.exe", "knoxroute.exe"}


def shipped() -> list[str] | None:
    """The files `git archive HEAD` would write, or None without a checkout."""
    try:
        done = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", "HEAD"],
                              capture_output=True, check=False)
    except OSError:
        return None
    if done.returncode != 0 or not done.stdout:
        return None
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as tar:
        return sorted(member.name for member in tar.getmembers() if member.isfile())


def main(argv: list[str]) -> int:
    files = shipped()
    if files is None:
        print("no git checkout here, so nothing to compare the manifest with",
              file=sys.stderr)
        return 1 if os.environ.get("CI") else 0

    expected = set(files) | ADDED_BY_RELEASE
    try:
        listed = set(json.loads(MANIFEST.read_text(encoding="utf-8"))["files"])
    except (OSError, ValueError, KeyError) as exc:
        print(f"{MANIFEST.name} cannot be read: {exc}", file=sys.stderr)
        return 1

    missing = sorted(expected - listed)
    extra = sorted(listed - expected)
    if not missing and not extra:
        print(f"{len(listed)} files ship, and the manifest is all of them")
        return 0
    for name in missing:
        print(f"  ships, but is not in {MANIFEST.name}: {name}")
    for name in extra:
        print(f"  in {MANIFEST.name}, but is not shipped: {name}")
    print(f"{len(missing)} missing and {len(extra)} stale - "
          f"update {MANIFEST.name} before releasing")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
