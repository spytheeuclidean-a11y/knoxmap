import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knoxbuild import build


class BuildCacheFingerprint(unittest.TestCase):
    def test_layout_code_changes_invalidate_buildings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build.py").write_text("build", encoding="utf-8")
            (root / "layout").mkdir()
            layout = root / "layout" / "furnishing.py"
            layout.write_text("before", encoding="utf-8")
            with patch.object(build, "__file__", str(root / "build.py")), \
                    patch("knoxbuild.layout._erika_ready", return_value=False):
                before = build._code_fingerprint()
                layout.write_text("after", encoding="utf-8")
                self.assertNotEqual(before, build._code_fingerprint())


if __name__ == "__main__":
    unittest.main()
