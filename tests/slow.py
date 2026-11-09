"""Which tests take minutes, and how to leave them out.

    python -m unittest discover tests                   # everything
    KNOXMAP_FAST=1 python -m unittest discover tests    # the quick half

checks.yml runs the two halves as separate jobs, so a town being built and
compiled in one does not hold up the lint in the other, and neither job can
grow into the workflow's 30-minute ceiling on its own.

A class is marked rather than a file: the basement tests that only do
arithmetic are still in the quick half, and only the ones that build and
compile a town are left out of it.
"""
from __future__ import annotations

import os
import unittest

# Set by whoever wants the quick half: the CI fast job, or a contributor
# before a pull request. Unset - what CI's slow job and a full local run do -
# means nothing is skipped.
FAST = os.environ.get("KNOXMAP_FAST") == "1"


def slow(obj):
    """Skip a test class or method when only the quick half was asked for."""
    return unittest.skipIf(FAST, "slow: run without KNOXMAP_FAST=1")(obj)
