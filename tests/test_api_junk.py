"""Nothing the window can post should come back as a server error.

Every one of these endpoints reads JSON the page sent, and the page is not the
only thing that can post to it: an older release's script, a half-finished
request, somebody's own tooling. Several of them answered a list where a table
was expected with a 500 and a Python message - "'int' object has no attribute
'get'" - which tells the person nothing and reads as KnoxMap falling over.

A refusal is fine; 400 and "Expected a sheet." is the right answer to rubbish.
A 500 is not.
"""
import unittest

import app as A

# Left out on purpose: the ones that write to the config or start work -
# saving an area, the Steam libraries, generate, compile, install, update.
SAFE_POSTS = [
    "/api/client-error",
    "/api/landmarks",
    "/api/stop",
    "/api/presets/validate",
    "/api/presets/export",
    "/api/builder/kind",
    "/api/builder/use",
    "/api/builder/save",
    "/api/builder/preview",
    "/api/builder/autofill",
    "/api/presets/buildings/probe",
    "/api/placement/no_such_map",
    "/api/placement/no_such_map/link",
    "/api/board/place-beside",
    "/api/zones/no_such_map",
    "/api/edits/no_such_map",
    "/api/design/no_such_map",
    "/api/sketch/no_such_map",
    "/api/overpass",
    "/api/forecast",
]

# A value of the wrong shape at every level: not a dict, not a list, not a
# number, and the two strings float() takes and nothing else does.
JUNK = [None, "", "x", 5, -1, 1.5, True, [], {}, [1, 2], {"a": 1}, "NaN",
        "inf", [[1, 2], [3]], [[None]], {"features": 7}, {"name": 5},
        {"design": 5}, {"design": {"rooms": "x"}}, {"points": 1.5},
        {"cells": "x"}, {"zones": 5}, {"folders": 5}, {"ring": 7}]

KEYS = ["name", "map", "neighbour", "side", "cells", "zones", "design",
        "rooms", "kind", "tbx", "preset", "points", "features", "width",
        "height", "settings", "scenery"]


class NoServerErrors(unittest.TestCase):
    def setUp(self):
        A.app.config["TESTING"] = True
        self.client = A.app.test_client()

    def test_every_editor_endpoint_refuses_rubbish_without_falling_over(self):
        # Each key paired with a different piece of junk, rather than every
        # pairing: the same lines of code read them, and the suite is run on
        # every change.
        bodies = list(JUNK) + [{key: JUNK[i % len(JUNK)]}
                               for i, key in enumerate(KEYS)]
        bodies += [{key: JUNK[(i + 7) % len(JUNK)]}
                   for i, key in enumerate(KEYS)]
        for path in SAFE_POSTS:
            for body in bodies:
                reply = self.client.post(path, json=body)
                if reply.status_code >= 500:
                    self.fail(f"{path} answered {reply.status_code} to "
                              f"{body!r}: {reply.get_json()}")

    def test_and_says_something_rather_than_nothing(self):
        # A refusal carries a message the window can show.
        reply = self.client.post("/api/design/no_such_map", json=5)
        self.assertEqual(reply.status_code, 400)
        self.assertTrue((reply.get_json() or {}).get("error"))


if __name__ == "__main__":
    unittest.main()
