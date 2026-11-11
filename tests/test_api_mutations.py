"""What the window can change, and what it must refuse.

The endpoints that change something - a place, a version, a restart - were the
untested half of the web layer: 73 routes and two test files, and those two only
sent rubbish to the ones that read JSON. Two things are worth knowing about
every one of them without opening the app: another website cannot reach it, and
a request that makes no sense is a refusal rather than a crash.

The map's own bookkeeping (knoxbuild/mapstate.py) is here too. It decides what
a newer KnoxMap asks to be redone, so getting it wrong means either a map that
is silently out of date or a whole rebuild nobody needed.
"""
import os
import tempfile
import unittest
from unittest import mock

import app as A

MUTATING = {"POST", "PUT", "DELETE", "PATCH"}


def mutations() -> list[tuple[str, str, str]]:
    """(rule, a concrete path, a method it accepts) for every route that
    does more than read.

    The method matters: a route that only deletes answers a POST with 405
    during routing, before the cross-site guard ever runs, so asking every one
    of them with the same verb would prove nothing about it.
    """
    found = []
    for rule in A.app.url_map.iter_rules():
        allowed = sorted((rule.methods or set()) & MUTATING)
        if not allowed:
            continue
        path = rule.rule
        for part in [p for p in path.split("/") if p.startswith("<")]:
            path = path.replace(part, "no_such_thing")
        found.append((rule.rule, path, allowed[0]))
    return sorted(found)


class NoOtherWebsiteCanChangeAnything(unittest.TestCase):
    """A page in the player's browser can post to 127.0.0.1 - and every one of
    these used to take it. The port is random, which is not a defence."""

    def setUp(self):
        self.client = A.app.test_client()

    def test_a_page_on_another_site_is_refused(self):
        routes = mutations()
        self.assertGreater(len(routes), 15, f"only found {routes}")
        for rule, path, method in routes:
            with self.subTest(route=rule):
                answer = self.client.open(path, method=method,
                                          headers={"Origin": "https://example.invalid"})
                self.assertEqual(answer.status_code, 403,
                                 f"{rule} answered a request from another site")

    def test_a_cross_site_request_without_an_origin_is_refused(self):
        for rule, path, method in mutations():
            with self.subTest(route=rule):
                answer = self.client.open(path, method=method,
                                          headers={"Sec-Fetch-Site": "cross-site"})
                self.assertEqual(answer.status_code, 403, rule)

    def test_this_computer_is_let_through_to_the_one_route_that_answers_every_time(self):
        # The guard must not be a wall: a real page here has to still work.
        answer = self.client.post("/api/stop", headers={"Origin": "http://127.0.0.1"})
        self.assertNotEqual(answer.status_code, 403)


class TheSetupCard(unittest.TestCase):
    def test_it_says_what_is_installed(self):
        answer = A.app.test_client().get("/api/setup-status")
        self.assertEqual(answer.status_code, 200)
        data = answer.get_json()
        self.assertIsInstance(data, dict)
        self.assertIn("ready", data)
        self.assertIn("checks", data)
        for check in data["checks"]:
            with self.subTest(check=check.get("id")):
                self.assertIn("id", check)
                self.assertIn("label", check)
                self.assertIn("ok", check)


class InstallingAnOptionalPackage(unittest.TestCase):
    """The one route that runs pip, so the only thing worth testing without a
    network is that it runs it for the two packages it knows and nothing else."""

    def setUp(self):
        self.client = A.app.test_client()

    def test_anything_else_is_refused_and_pip_is_not_run(self):
        from web import system

        for bad in ("", "duckdb", "pip", "../../etc", None, ["duckdb"]):
            with self.subTest(id=bad):
                with mock.patch("subprocess.run") as run:
                    answer = self.client.post("/api/install-optional", json={"id": bad})
                self.assertEqual(answer.status_code, 400)
                run.assert_not_called()
        self.assertEqual(set(system.OPTIONAL_PACKAGES), {"overture", "room_solver"})

    def test_the_ids_are_the_ones_the_setup_report_offers(self):
        # The page asks for the id the report gave it, so a renamed one would
        # leave a button that installs nothing.
        from web import system

        offered = {c["id"] for c in self.client.get("/api/setup-status").get_json()["optional"]}
        self.assertTrue(set(system.OPTIONAL_PACKAGES) <= offered,
                        f"{set(system.OPTIONAL_PACKAGES) - offered} is not offered")


class Updates(unittest.TestCase):
    def test_restarting_with_nothing_ready_is_a_refusal(self):
        with mock.patch.dict(os.environ, {"KNOXMAP_WINDOW": "1"}):
            answer = A.app.test_client().post("/api/update/restart")
        self.assertEqual(answer.status_code, 409)
        self.assertIn("ready", answer.get_json()["error"].lower())

    def test_choosing_something_that_is_not_a_version_is_refused(self):
        for bad in ("../../etc", "latest", "", "1.2.3.4.5", None):
            with self.subTest(version=bad):
                answer = A.app.test_client().post("/api/versions/install",
                                                  json={"version": bad})
                self.assertEqual(answer.status_code, 400)
                self.assertIn("version", answer.get_json()["error"].lower())

    def test_the_version_list_says_so_when_github_cannot_be_reached(self):
        with mock.patch("updater.releases", side_effect=OSError("offline")):
            answer = A.app.test_client().get("/api/versions")
        self.assertEqual(answer.status_code, 502)
        self.assertIn("GitHub", answer.get_json()["error"])

    def test_the_update_state_is_readable_without_a_download(self):
        answer = A.app.test_client().get("/api/update")
        self.assertEqual(answer.status_code, 200)
        self.assertIn("state", answer.get_json())


class WhatTheMapRemembers(unittest.TestCase):
    """knoxbuild/mapstate.py: which KnoxMap made which step of a map."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, True))

    def test_a_step_records_the_version_that_ran_it(self):
        from knoxbuild import mapstate as M
        M.stamp(self.dir, "generate", "1.8.4.2")
        stages = M.read(self.dir)["stages"]
        self.assertEqual(stages["generate"]["version"], "1.8.4.2")
        self.assertTrue(stages["generate"]["at"])

    def test_running_a_step_again_forgets_the_ones_after_it(self):
        from knoxbuild import mapstate as M
        for stage in M.STAGES:
            M.stamp(self.dir, stage, "1.8.4.2")
        M.stamp(self.dir, "build", "1.8.4.2")
        self.assertEqual(sorted(M.read(self.dir)["stages"]), ["build", "generate"])

    def test_a_map_made_by_an_older_knoxmap_says_what_to_redo(self):
        from knoxbuild import mapstate as M
        M.stamp(self.dir, "generate", "1.0")
        M.stamp(self.dir, "build", "1.0")
        self.assertEqual(M.needs(self.dir), ["generate", "build"])

    def test_a_map_that_is_up_to_date_needs_nothing(self):
        from knoxbuild import mapstate as M
        for stage in M.STAGES:
            M.stamp(self.dir, stage, "99.0")
        self.assertEqual(M.needs(self.dir), [])

    def test_the_oldest_version_is_the_one_named(self):
        from knoxbuild import mapstate as M
        M.stamp(self.dir, "generate", "1.8.4.2")
        M.stamp(self.dir, "build", "1.3.9")
        self.assertEqual(M.made_with(self.dir), "1.3.9")

    def test_an_install_that_has_been_deleted_by_hand_is_not_an_install(self):
        from knoxbuild import mapstate as M
        mod = os.path.join(self.dir, "mods", "Town")
        os.makedirs(mod)
        open(os.path.join(mod, "mod.info"), "w").close()
        M.record_install(self.dir, mod, "Town", "Town")
        self.assertEqual(M.installed(self.dir)["modId"], "Town")
        os.remove(os.path.join(mod, "mod.info"))
        self.assertIsNone(M.installed(self.dir), "a folder with no mod.info is not installed")

    def test_a_map_nothing_has_been_done_to_is_not_out_of_date(self):
        from knoxbuild import mapstate as M
        self.assertEqual(M.needs(self.dir), [])
        self.assertIsNone(M.made_with(self.dir))

    def test_delete_map_endpoint_returns_404_for_unknown_map(self):
        client = A.app.test_client()
        answer = client.delete("/api/maps/nonexistent_dummy_map_xyz")
        self.assertEqual(answer.status_code, 404)
        self.assertIn("error", answer.get_json() or {})


if __name__ == "__main__":
    unittest.main()
