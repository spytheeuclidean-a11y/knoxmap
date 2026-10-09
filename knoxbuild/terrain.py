"""Tiles for the ground, from the landscape and vegetation pictures and Rules.txt.

For every rule the pixels of its colour get a tile from its list. The pick is a hash of
the pixel's position, the rule and a seed, so the same map always gets the same tiles
and a cell can be made without making the ones around it.

Only the rules are applied here, not the blends along edges between two ground kinds.
"""
from __future__ import annotations

import numpy as np

from .rules import Rule, Ruleset

# Bottom of the stack first. Layers not listed go after these, by name.
LAYER_ORDER = ["0_Floor", "0_FloorOverlay", "0_FloorOverlay2", "0_FloorOverlay3", "0_FloorOverlay4",
               "0_FloorOverlay5", "0_FloorOverlay6", "0_Curbs", "0_Furniture", "0_Vegetation"]

_M = np.uint64(0xFFFFFFFFFFFFFFFF)


def mix(x: np.ndarray, y: np.ndarray, salt: int) -> np.ndarray:
    """A well-mixed 64-bit number for every (x, y): splitmix64 on the position."""
    z = (x.astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)) ^ (y.astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F))
    z = z + np.uint64((salt * 0x165667B19E3779F9) & 0xFFFFFFFFFFFFFFFF)
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return z ^ (z >> np.uint64(31))


class Palette:
    """Tile names to small numbers, shared by every cell of a map."""

    def __init__(self):
        self.names: list[str] = [""]          # 0 means no tile
        self.index: dict[str, int] = {"": 0}

    def of(self, name: str) -> int:
        i = self.index.get(name)
        if i is None:
            i = self.index[name] = len(self.names)
            self.names.append(name)
        return i


def _pick(rule: Rule, rules: Ruleset, pal: Palette, xs: np.ndarray, ys: np.ndarray, seed: int, salt: int) -> np.ndarray:
    """Palette numbers for the tiles of `rule` at these positions."""
    n = len(rule.entries)
    h1 = mix(xs, ys, seed * 1000003 + salt)
    entry = (h1 % np.uint64(n)).astype(np.int64)
    out = np.zeros(len(xs), np.int64)
    h2 = mix(xs, ys, seed * 1000003 + salt + 7919)
    for e, name in enumerate(rule.entries):
        sel = entry == e
        if not sel.any():
            continue
        if name in rules.aliases:
            sub = rules.aliases[name]
            j = (h2[sel] % np.uint64(len(sub))).astype(np.int64)
            out[sel] = np.array([pal.of(t) for t in sub], np.int64)[j]
        else:
            out[sel] = pal.of(name)
    return out


def colour_keys(img: np.ndarray) -> np.ndarray:
    """A colour picture (h, w, 3) as one number per pixel, r * 65536 + g * 256 + b."""
    return (img[..., 0].astype(np.uint32) << 16) | (img[..., 1].astype(np.uint32) << 8) | img[..., 2]


def _key(c) -> int:
    return (c[0] << 16) | (c[1] << 8) | c[2]


def ground_layers(land: np.ndarray, veg: np.ndarray, rules: Ruleset, pal: Palette, seed: int,
                  x0: int = 0, y0: int = 0) -> dict[str, np.ndarray]:
    """{layer: (h, w) palette numbers} for a window of the pictures.

    `land` and `veg` are (h, w, 3) uint8; (x0, y0) is where the window starts in the
    world, so the picks do not depend on how the world was cut up."""
    h, w = land.shape[:2]
    gy, gx = np.mgrid[0:h, 0:w]
    gx = gx.astype(np.int64) + x0
    gy = gy.astype(np.int64) + y0
    layers: dict[str, np.ndarray] = {}

    def paint(rule: Rule, mask: np.ndarray, salt: int) -> None:
        if not mask.any():
            return
        layer = layers.setdefault(rule.layer, np.zeros((h, w), np.int64))
        layer[mask] = _pick(rule, rules, pal, gx[mask], gy[mask], seed, salt)

    # Colours as single numbers, and only the rules whose colour is in the picture at all
    # (a window holds a handful of the 148).
    land_key, veg_key = colour_keys(land), colour_keys(veg)
    in_land, in_veg = set(np.unique(land_key).tolist()), set(np.unique(veg_key).tolist())
    for n, rule in enumerate(rules.rules):
        key = _key(rule.color)
        if key not in (in_land if rule.bitmap == 0 else in_veg):
            continue
        if rule.condition is not None and _key(rule.condition) not in in_land:
            continue
        mask = (land_key if rule.bitmap == 0 else veg_key) == key
        if rule.condition is not None:
            mask &= land_key == _key(rule.condition)
        paint(rule, mask, n)
    return layers


def stack_order(layer_names) -> list[str]:
    known = [n for n in LAYER_ORDER if n in layer_names]
    return known + sorted(n for n in layer_names if n not in LAYER_ORDER)
