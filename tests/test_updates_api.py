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
        started = []
        with mock.patch.object(updater, "managed", return_value=True), \
                mock.patch.object(updater, "status", return_value={"state": "idle"}), \
                mock.patch.object(updater, "choose", side_effect=started.append), \
                mock.patch("threading.Thread") as thread:
            thread.return_value.start.side_effect = lambda: started.append("ran")
            answer = post("/api/versions/install", {"version": "1.8.4.2"})
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(answer.get_json()["started"])

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
