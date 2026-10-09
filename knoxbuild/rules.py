"""The colour-to-tile rules (Rules.txt) that turn the landscape bitmaps into tiles.

Rules.txt is a data file that ships with the mapping tools. Its layout:

    alias { name = darkgrass  tiles = [ blends_natural_01_16 ... ] }
    rule  { label = ...  bitmap = 0|1  color = r g b  tiles = name | [ names ]
            layer = 0_Floor  condition = r g b }

`bitmap` 0 is the landscape picture and 1 the vegetation picture. `condition`, when
there is one, is a landscape colour the rule only applies on. A tile entry is a tile
or an alias; a tile is picked by choosing an entry (repeats count as weight), then,
if it is an alias, one of its tiles.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Rule:
    label: str
    bitmap: int
    color: tuple[int, int, int]
    entries: list[str]
    layer: str
    condition: tuple[int, int, int] | None = None


@dataclass
class Ruleset:
    aliases: dict[str, list[str]] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)

    def for_bitmap(self, bitmap: int) -> list[Rule]:
        return [r for r in self.rules if r.bitmap == bitmap]


def _blocks(text: str):
    """(kind, {key: str | list[str]}) for every `alias {}` / `rule {}` block."""
    lines = [ln.split("//")[0].strip() for ln in text.splitlines()]
    i = 0
    while i < len(lines):
        kind = lines[i]
        if kind in ("alias", "rule") and i + 1 < len(lines) and lines[i + 1] == "{":
            i += 2
            body: dict = {}
            while i < len(lines) and lines[i] != "}":
                m = re.match(r"(\w+)\s*=\s*(.*)$", lines[i])
                if m:
                    key, value = m.group(1), m.group(2).strip()
                    if value == "[":
                        items = []
                        i += 1
                        while i < len(lines) and lines[i] != "]":
                            if lines[i]:
                                items.append(lines[i])
                            i += 1
                        body[key] = items
                    else:
                        body[key] = value
                i += 1
            yield kind, body
        i += 1


def _triple(v: str) -> tuple[int, int, int]:
    r, g, b = (int(t) for t in v.split())
    return r, g, b


def parse_rules(text: str) -> Ruleset:
    rs = Ruleset()
    for kind, b in _blocks(text):
        tiles = b.get("tiles", [])
        entries = tiles if isinstance(tiles, list) else [tiles]
        if kind == "alias":
            rs.aliases[b["name"]] = entries
        else:
            rs.rules.append(Rule(
                label=b.get("label", ""), bitmap=int(b["bitmap"]), color=_triple(b["color"]),
                entries=entries, layer=b["layer"],
                condition=_triple(b["condition"]) if "condition" in b else None))
    return rs


def load_rules(path: str) -> Ruleset:
    with open(path, encoding="utf-8", errors="replace") as f:
        return parse_rules(f.read())
