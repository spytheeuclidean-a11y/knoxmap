"""Turn a footprint rectangle into a furnished floor plan.

This used to be one 8,333-line module. It is now a package with one module per
seam that was already visible in it:

    core        rooms, the plan grid, the first split
    openings    doors, ways in, wall runs
    malls       concourse, arms, anchors, units
    dwellings   flats and the small rooms of an apartment block
    houses      room budgets by floor, wings, spare rooms
    shops       sales floors and back rooms
    furnishing  stairs, cores, walls, windows, furniture
    assemble    build_plan, build_building, the roof grid

Every name is re-exported here, so `from knoxbuild.layout import build_plan`
reads exactly as it did before the split, and the modules depend only on the
ones above them in that list.
"""
from __future__ import annotations

from . import (assemble, core, dwellings, furnishing, houses, malls,
               openings, shops)

_MODULES = (core, openings, malls, dwellings, houses, shops, furnishing,
            assemble)

# Re-export every name, private helpers included: the tests and
# tools/audit_layouts.py reach for _blocks, _room_edges and friends. These are
# copies: to swap a helper or tune a number, set it on the module that reads it
# (e.g. `layout.houses._house_by_kind = spy`), not on this package.
for _module in _MODULES:
    globals().update({k: v for k, v in vars(_module).items()
                      if not k.startswith('__')})
del _module
