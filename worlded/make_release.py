"""Put together the compiler release: binary, licence, and its complete source.

    python worlded/make_release.py <PZ_Mapping_Tools git checkout> <built PZWorldEd.exe> <out dir>

GPL-2.0 section 3 lets a modified program be passed on as a binary only with
its complete corresponding source - "all the source code for all modules it
contains, plus any associated interface definition files, plus the scripts
used to control compilation and installation" - offered from the same place.
A link to upstream plus a patch is not that: upstream can move or vanish. So
the release carries, next to PZWorldEd_cli.exe:

    PZWorldEd_cli-source.zip   the upstream tree at the pinned commit with the
                               KnoxMap patch already applied, plus the patch
                               and build scripts from worlded/
    LICENSE-GPL-2.0.txt        the licence
    README-RELEASE.txt         what this is, how to build it, the source offer

Qt is not in the release (it comes with PZ Mapping Tools, which provides its
own source offer), so no Qt source is needed here.
"""
from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMIT = "4e86b80c505b3d77a2fb5f5675b752da966306f6"
TAG = "worlded-cli-20260909f"


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    repo, exe, out = Path(argv[1]), Path(argv[2]), Path(argv[3])
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "PZ_Mapping_Tools"
        archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=zip", COMMIT],
                                 check=True, capture_output=True).stdout
        zipfile.ZipFile(io.BytesIO(archive)).extractall(tree)
        subprocess.run([sys.executable, str(HERE / "patch_worlded_cli.py"), str(tree)], check=True)
        for leftover in tree.rglob("*.orig"):
            leftover.unlink()
        kit = tree / "knoxmap-worlded"
        kit.mkdir()
        for name in ("patch_worlded_cli.py", "build_worlded.bat", "README.md", "make_release.py"):
            shutil.copy2(HERE / name, kit / name)
        source_zip = out / "PZWorldEd_cli-source.zip"
        with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(tree.rglob("*")):
                if path.is_file():
                    z.write(path, path.relative_to(tree.parent))

    shutil.copy2(exe, out / "PZWorldEd_cli.exe")
    licence = repo / "licenses" / "GPL-2.0.txt"
    if not licence.exists():
        licence = next(repo.rglob("GPL-2.0*.txt"), None) or next(repo.rglob("COPYING*"))
    shutil.copy2(licence, out / "LICENSE-GPL-2.0.txt")

    digest = hashlib.sha256((out / "PZWorldEd_cli.exe").read_bytes()).hexdigest()
    (out / "README-RELEASE.txt").write_text(f"""PZWorldEd_cli.exe - release {TAG}
{"=" * (len(TAG) + 30)}

A build of PZWorldEd from PZ Mapping Tools (https://github.com/Unjammer/PZ_Mapping_Tools),
commit {COMMIT}, with a small patch that adds the --generate-map and --cells
command-line switches so KnoxMap can compile maps without the editor's menus.

SHA-256 of PZWorldEd_cli.exe: {digest}

Use it by copying it into the bin folder of PZ Mapping Tools release
43.00B260909 (KnoxMap's Setup.bat does this for you). It needs that release's
Qt and editor libraries beside it.

LICENCE
PZ Mapping Tools, and therefore this modified build, is distributed under the
GNU General Public License version 2 or (where a source file says so) any later
version - see LICENSE-GPL-2.0.txt. There is NO WARRANTY, to the extent
permitted by law.

SOURCE
PZWorldEd_cli-source.zip in this same release is the complete corresponding
source of this binary: the upstream tree at the commit above with the patch
applied (the changed files say so at their end), and the scripts used to patch
and build it (in knoxmap-worlded/). To build it: install Visual Studio 2022
Build Tools (C++) and Qt 5.14.2 msvc2017_64, then run
knoxmap-worlded\\build_worlded.bat.

If this release's source archive is ever unavailable, open an issue at
https://github.com/spytheeuclidean-a11y/knoxify/issues and the source will be
provided, for at least three years from this release.

Not affiliated with The Indie Stone or the PZ Mapping Tools authors.
""", encoding="utf-8")
    print(f"release files in {out}")
    for f in sorted(out.iterdir()):
        print(f"  {f.name}  {f.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
