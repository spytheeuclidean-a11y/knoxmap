"""Every knob that shapes the woods, in one value the renderer passes down.

The settings panel's Forest card sets these (knoxbuild/settings.py has one
`forest_*` setting per field). The defaults are the values the code used
before they were knobs, so a map made with the defaults is the map it was.
Frozen, so a set of them can key a cache (the preview's).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ForestParams:
    stand_m: float = 60.0          # how big a stand is
    edge_m: float = 30.0           # how far a wood spills past its edge
    thickets: float = 1.0          # times the share of a wood that is a wall
    stand_variety: float = 0.0     # weight of stands 2.5 times as big
    raggedness: float = 0.25       # weight of stands a quarter as big
    edge_wobble: float = 0.4       # how far the spill's reach is moved by noise
    spill_thick: float = 0.4       # share of the spill that is trees in grass
    keep_meadows: float = 0.33     # how far across a clearing the spill reaches
    seed: int = 2207               # the woods' own noise
    house_clearing_m: float = 20.0  # the far end of a house's clearing
    big_trees: float = 1.0         # times the chance of a big tree in a wood
    groves: float = 1.0            # times the share of made-up woods
    wild_growth: float = 1.0       # times the scrub on open ground
    shrubland: float = 1.0         # times the land cover's shrub, tufts and marsh


# Setting key -> field.
FIELD_FOR_SETTING = {
    "forest_stand_m": "stand_m",
    "forest_edge_m": "edge_m",
    "forest_thickets": "thickets",
    "forest_stand_variety": "stand_variety",
    "forest_raggedness": "raggedness",
    "forest_edge_wobble": "edge_wobble",
    "forest_spill_thick": "spill_thick",
    "forest_keep_meadows": "keep_meadows",
    "forest_seed": "seed",
    "forest_house_clearing_m": "house_clearing_m",
    "forest_big_trees": "big_trees",
    "forest_groves": "groves",
    "forest_wild_growth": "wild_growth",
    "forest_shrubland": "shrubland",
}
