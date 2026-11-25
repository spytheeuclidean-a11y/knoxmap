"""The update routes: what they refuse, and what they must not start.

`web/updates.py` is the one screen that can replace the running copy, so its
refusals matter more than its successes: a bad version name, a copy that is a
git checkout, a restart with nothing downloaded, a restart outside the window.
Each is checked here without letting a download begin - `updater.check` and
`updater.restart` are the only things that touch the network or the process,
and both are stubbed.
"""
import unittest
from unittest import mock

import app as A


def post(path, body=None, **headers):
    return A.app.test_client().post(path, json=body, headers=headers or None)


class UpdateRoutes(unittest.TestCase):
    def test_status_reads_back_as_a_state(self):
        answer = A.app.test_client().get("/api/update")
        self.assertEqual(answer.status_code, 200)
        self.assertIn("state", answer.get_json())

    def test_a_version_that_is_not_a_version_is_refused(self):
        answer = post("/api/versions/install", {"version": "latest"})
        self.assertEqual(answer.status_code, 400)
        self.assertIn("Choose a version", answer.get_json()["error"])

    def test_a_git_checkout_is_told_to_use_git(self):
        import updater
        with mock.patch.object(updater, "managed", return_value=False):
            answer = post("/api/versions/install", {"version": "1.8.4.2"})
        self.assertEqual(answer.status_code, 400)
        self.assertIn("git checkout", answer.get_json()["error"])

    def test_choosing_a_version_starts_one_download(self):
        import updater
        version = "1.2.3.4.5"
        with mock.patch.object(updater, "managed", return_value=True), \
                mock.patch.object(updater, "status", return_value={"state": "idle"}), \
                mock.patch("threading.Thread") as thread:
            answer = post("/api/versions/install", {"version": version})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.get_json(), {"started": True, "version": version})
        thread.assert_called_once_with(target=updater.choose, args=(version,),
                                       name="choose-version", daemon=True)
        thread.return_value.start.assert_called_once_with()

    def test_deep_and_multi_digit_versions_are_accepted_and_ordered(self):
        import re
        from pathlib import Path

        import updater
        from knoxbuild import mapstate

        for tag in ("1.8.5.10", "v1.8.5.10", "1.8.5.10.1", "v1.8.5.10.1", "v1.8.6.1.2-mc1"):
            self.assertTrue(updater._is_knoxmap({"tag_name": tag}), tag)
        self.assertFalse(updater._is_knoxmap({"tag_name": "worlded-cli-linux-20260909f"}))

        pairs = (
            ("1.8.5.10", "1.8.5.9"),
            ("1.8.5.11", "1.8.5.10"),
            ("1.8.5.10.1", "1.8.5.10"),
            ("1.8.5.10.2", "1.8.5.10.1"),
            ("1.8.6.1", "1.8.6"),
            ("1.8.6.1.1", "1.8.6.1"),
        )
        for newer, older in pairs:
            self.assertTrue(updater.is_newer(newer, older), (newer, older))
            self.assertFalse(updater.is_newer(older, newer), (older, newer))
            self.assertGreater(mapstate._parse(newer), mapstate._parse(older))

        for ver in ("1.8.5.10", "1.8.5.10.1", "1.8.6.1.2-mc1"):
            with mock.patch.object(updater, "managed", return_value=False):
                answer = post("/api/versions/install", {"version": ver})
            self.assertEqual(answer.status_code, 400)
            self.assertIn("git checkout", answer.get_json()["error"], ver)

        yml = (Path(updater.BASE_DIR) / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        m = re.search(r"grep -Eq '([^']+)'", yml)
        self.assertIsNotNone(m)
        gate_re = re.compile(m.group(1))
        for tag in ("v1.8.5.10", "v1.8.5.10.1", "1.8.6.1.1", "v1.8.5.10.1-mc1"):
            self.assertIsNotNone(gate_re.fullmatch(tag), tag)
        self.assertIsNone(gate_re.fullmatch("worlded-cli-linux-20260909f"))

    def test_a_restart_outside_the_window_is_refused(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("KNOXMAP_WINDOW", None)
            answer = post("/api/update/restart")
        self.assertEqual(answer.status_code, 400)
        self.assertIn("open it again", answer.get_json()["error"])

    def test_a_restart_with_nothing_downloaded_is_refused(self):
        import updater
        with mock.patch.dict("os.environ", {"KNOXMAP_WINDOW": "1"}), \
                mock.patch.object(updater, "status", return_value={"state": "idle"}), \
                mock.patch.object(updater, "restart") as restart:
            answer = post("/api/update/restart")
        self.assertEqual(answer.status_code, 409)
        restart.assert_not_called()


if __name__ == "__main__":
    unittest.main()
