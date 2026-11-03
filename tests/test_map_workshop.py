"""The Workshop picture and page every installed map gets
(tools/make_map_mod.py, tools/make_map_workshop.py)."""
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from knoxbuild import credits
from tools import make_map_mod, make_map_workshop, workshop_check


def project(root: str, size=(900, 600)) -> str:
    d = os.path.join(root, "town")
    os.makedirs(d)
    Image.new("RGB", size, (80, 120, 60)).save(os.path.join(d, "town_preview.png"))
    return d


class Preview(unittest.TestCase):
    def test_a_square_preview_and_posters_are_written(self):
        with tempfile.TemporaryDirectory() as t:
            mod = os.path.join(t, "mod")
            os.makedirs(mod)
            self.assertTrue(make_map_mod.write_preview(project(t), mod))
            for where in ("preview.png", "poster.png", "common/poster.png", "42/poster.png"):
                with Image.open(os.path.join(mod, where)) as im:
                    self.assertEqual(im.size, (make_map_mod.PREVIEW_SIDE,) * 2, where)
            self.assertLess(os.path.getsize(os.path.join(mod, "preview.png")),
                            workshop_check.PREVIEW_MAX_BYTES)

    def test_the_workshop_check_accepts_it(self):
        with tempfile.TemporaryDirectory() as t:
            mod = os.path.join(t, "mod")
            os.makedirs(mod)
            make_map_mod.write_preview(project(t), mod)
            got = [r for r in workshop_check.check(mod) if "preview.png" in r["what"]]
            self.assertEqual([r["level"] for r in got], ["ok"], got)

    def test_no_map_preview_writes_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            d = os.path.join(t, "bare")
            os.makedirs(d)
            self.assertFalse(make_map_mod.write_preview(d, t))
            self.assertFalse(os.path.exists(os.path.join(t, "preview.png")))


class Page(unittest.TestCase):
    def installed(self, t):
        mods = Path(t) / "mods"
        root = mods / "TownMod"
        (root / "42").mkdir(parents=True)
        (root / "mod.info").write_text(
            "name=Town\nid=TownMod\ndescription=A town. Map data (c) OpenStreetMap "
            "contributors (ODbL).\nposter=poster.png\n", encoding="utf-8")
        make_map_mod.write_preview(project(t), str(root))
        return mods

    def test_the_page_credits_knoxmap_and_everyone_who_made_it(self):
        text = make_map_workshop.description("Town", "A town.")
        self.assertIn(credits.MAKER, text)
        for name in credits.CONTRIBUTORS:
            self.assertIn(name, text)
        self.assertIn(credits.KNOXMAP_URL, text)
        self.assertIn("OpenStreetMap contributors", text)

    def test_the_folder_has_what_the_uploader_reads(self):
        with tempfile.TemporaryDirectory() as t:
            mods = self.installed(t)
            out = make_map_workshop.build("TownMod", mods, Path(t) / "ws")
            self.assertTrue((out / "Contents/mods/TownMod/mod.info").exists())
            self.assertTrue((out / "preview.png").exists())
            txt = (out / "workshop.txt").read_text(encoding="utf-8")
            self.assertIn("title=Town", txt)
            self.assertIn(f"description=Made with", txt.replace("[b]", ""))

    def test_a_rerun_keeps_the_steam_id(self):
        with tempfile.TemporaryDirectory() as t:
            mods = self.installed(t)
            out = make_map_workshop.build("TownMod", mods, Path(t) / "ws")
            txt = (out / "workshop.txt").read_text(encoding="utf-8")
            (out / "workshop.txt").write_text(txt.replace("version=1", "version=1\nid=123456"),
                                              encoding="utf-8")
            again = make_map_workshop.build("TownMod", mods, Path(t) / "ws")
            self.assertIn("\nid=123456\n", (again / "workshop.txt").read_text(encoding="utf-8"))

    def test_an_uninstalled_map_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(FileNotFoundError):
                make_map_workshop.build("Nope", Path(t), Path(t) / "ws")

    def test_a_description_over_the_limit_is_refused(self):
        with self.assertRaises(ValueError):
            make_map_workshop.workshop_txt("t", "x" * 9000)


if __name__ == "__main__":
    unittest.main()
