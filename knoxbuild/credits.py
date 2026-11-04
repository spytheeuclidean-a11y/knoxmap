"""Who made KnoxMap, in one place: the credit every map carries.

A map's ATTRIBUTION.txt and its Steam Workshop page (tools/make_map_workshop.py)
both read this, so a name added here shows up in both. Names are the authors'
own, as they appear on the project's commits.
"""
from __future__ import annotations

KNOXMAP_URL = "https://github.com/spytheeuclidean-a11y/knoxmap"
# The person who made KnoxMap.
MAKER = "euclid80tr"
# Everyone else who has worked on it, in the order they began.
CONTRIBUTORS = ["PonSky", "SolarisMare", "yoruvell", "hamurabi11", "spongebobik",
                "Soner Kochan", "Tom N", "Zombaxx"]
# What KnoxMap stands on.
BUILT_ON = [
    ("Knoxify", "arytek", "https://github.com/arytek/knoxify",
     "the original OpenStreetMap-to-Project-Zomboid terrain generator KnoxMap is built on"),
    ("PZ Mapping Tools", "Alree / Unjammer", "https://github.com/Unjammer/PZ_Mapping_Tools",
     "built on Tim Baker's TileZed and WorldEd"),
]


def plain() -> str:
    """The credit as lines of text, for ATTRIBUTION.txt."""
    lines = [f"Made with KnoxMap ({KNOXMAP_URL}) by {MAKER}, with work from "
             + ", ".join(CONTRIBUTORS) + ".",
             "KnoxMap is built on:"]
    lines += [f"  - {name} by {who} ({url}): {what}" for name, who, url, what in BUILT_ON]
    return "\n".join(lines)


def bbcode() -> str:
    """The same, for a Steam Workshop page."""
    out = [f"[b]Made with [url={KNOXMAP_URL}]KnoxMap[/url][/b] by [b]{MAKER}[/b], with work "
           "from " + ", ".join(CONTRIBUTORS) + ".",
           "",
           "KnoxMap is a free program that turns a real place into a Project Zomboid map. "
           "It is built on:",
           "[list]"]
    out += [f"[*] [url={url}]{name}[/url] by {who}: {what}" for name, who, url, what in BUILT_ON]
    out.append("[/list]")
    return "\n".join(out)
