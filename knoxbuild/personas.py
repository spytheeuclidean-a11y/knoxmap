"""Who lives in a home, beyond a family, a retired couple or adults.

interiors.household() decides the household's makeup; this gives it a way of
living: a musician has a piano, a runner a treadmill, a hoarder boxes in every
room. A persona only changes what a room's wishlist asks for - the furnisher
still places it where it fits, so a small room that cannot take a piano simply
goes without.

Each persona is {"weight": f(who) -> float, "rooms": {room kind: {"add": [(role,
chance)], "drop": [roles], "swap": {old: new}}}}. A weight of 0 means this home
cannot be that persona. "spare" is applied to any office or storeroom, the rooms
a home has no fixed use for.
"""
from __future__ import annotations

import random

from . import catalog as C

SPARE_KINDS = ("office", "storage")
# A home that is nobody in particular still exists.
PLAIN_WEIGHT = 0.9


def _w(who: dict, **kw) -> float:
    """1.0 shaped by the home's wealth, wear, age and setting (see below)."""
    weight = kw.get("base", 1.0)
    wealth, wear = who["wealth"], who["wear"]
    if "rich" in kw:
        weight *= max(0.0, 0.25 + kw["rich"] * (wealth - 0.5) * 2.0 + (1 - kw["rich"]) * 0.75)
    if "worn" in kw:
        weight *= max(0.05, 1.0 + kw["worn"] * (wear - 0.4) * 2.5)
    if "setting" in kw:
        weight *= kw["setting"].get(who["setting"], 1.0)
    if "kind" in kw:
        weight *= kw["kind"].get(who["household"], 0.0)
    if "plan" in kw:
        weight *= kw["plan"].get(who["plan_kind"], 0.4)
    if "old" in kw and who["age"] >= 40:
        weight *= kw["old"]
    return weight


FAMILY = {"family": 1.0}
ANY = {"family": 1.0, "adults": 1.0, "retired": 1.0}
ADULTS = {"adults": 1.0}
NOT_RETIRED = {"family": 1.0, "adults": 1.0}
HOUSE = {None: 1.0, "house": 1.0, "apartment": 0.35}
FLAT = {None: 0.5, "house": 0.5, "apartment": 1.0}

PERSONAS: dict[str, dict] = {
    "runner": {
        "weight": lambda w: _w(w, kind=NOT_RETIRED, plan=HOUSE, base=0.7),
        "spare": {"add": [("treadmill", 0.9), ("mirror", 0.5), ("plant", 0.3)]},
        "rooms": {"bedroom": {"add": [("clothes_rack_small", 0.5)]}},
    },
    "lifter": {
        "weight": lambda w: _w(w, kind=ADULTS, plan=HOUSE, base=0.55),
        "spare": {"add": [("weight_machine", 0.8), ("weight_machine_alt", 0.8), ("mirror", 0.6)],
                  "drop": ["plant"]},
        "rooms": {"storage": {"add": [("weight_machine_alt", 0.5)]},
                  "livingroom": {"add": [("weight_machine", 0.25)]},
                  "bedroom": {"add": [("weight_machine_alt", 0.3)]}},
    },
    "musician": {
        "weight": lambda w: _w(w, kind=NOT_RETIRED, plan=HOUSE, rich=0.4, base=0.6),
        "rooms": {"livingroom": {"add": [("piano", 0.85), ("radio", 0.5)]},
                  "bedroom": {"add": [("shelf", 0.4)]}},
        "spare": {"add": [("shelf_1", 0.5), ("chair", 0.4)]},
    },
    "pianist_elder": {
        "weight": lambda w: _w(w, kind={"retired": 1.0}, plan=HOUSE, base=0.6),
        "rooms": {"livingroom": {"add": [("piano", 0.7), ("clock", 0.5), ("rug", 0.6)]}},
    },
    "gamer": {
        "weight": lambda w: _w(w, kind={"family": 0.6, "adults": 1.0}, base=0.7),
        "spare": {"add": [("arcade", 0.6), ("tv", 0.6), ("sofa_2", 0.5)]},
        "rooms": {"livingroom": {"add": [("arcade", 0.25)], "drop": ["plant"]},
                  "bedroom": {"add": [("tv", 0.3), ("poster_3", 0.6)]}},
    },
    "bookworm": {
        "weight": lambda w: _w(w, kind=ANY, base=0.9),
        "rooms": {"livingroom": {"add": [("bookshelf", 1.0), ("bookshelf", 0.6), ("armchair_2", 0.7)]},
                  "bedroom": {"add": [("bookshelf", 0.8)]},
                  "dining": {"add": [("bookshelf", 0.5)]}},
        "spare": {"add": [("bookshelf", 1.0), ("bookshelf", 0.8), ("desk", 0.5),
                          ("armchair_5", 0.6)]},
    },
    "home_office": {
        "weight": lambda w: _w(w, kind=NOT_RETIRED, plan=FLAT, base=0.9),
        "spare": {"add": [("desk_long", 0.9), ("office_chair", 0.9), ("filing_cabinet", 0.8),
                          ("corkboard", 0.5), ("whiteboard", 0.3), ("lamp", 0.5)]},
        "rooms": {"bedroom": {"add": [("desk_dark", 0.3), ("office_chair", 0.3)]}},
    },
    "green_thumb": {
        "weight": lambda w: _w(w, kind=ANY, base=0.9, setting={"rural": 1.2}),
        "rooms": {"livingroom": {"add": [("erika_plant_3", 0.9), ("erika_plant_8", 0.8),
                                         ("plant", 0.8), ("erika_plant_15", 0.5)]},
                  "kitchen": {"add": [("erika_plant_5", 0.8), ("plant", 0.6)]},
                  "bedroom": {"add": [("erika_plant_11", 0.7)]},
                  "dining": {"add": [("erika_plant_1", 0.7)]}},
        "spare": {"add": [("erika_plant_19", 0.8), ("erika_plant_6", 0.7)]},
    },
    "collector": {
        "weight": lambda w: _w(w, kind=ANY, rich=0.9, base=0.5),
        "rooms": {"livingroom": {"add": [("erika_art_6", 0.9), ("erika_art_14", 0.8),
                                         ("mirror", 0.6), ("sidetable", 0.6)]},
                  "dining": {"add": [("erika_art_22", 0.9), ("mirror", 0.5)]},
                  "bedroom": {"add": [("erika_art_30", 0.7)]},
                  "hall": {"add": [("sidetable", 0.6), ("plant", 0.5)]}},
    },
    "rec_room": {
        "weight": lambda w: _w(w, kind=NOT_RETIRED, plan=HOUSE, rich=0.8, base=0.45),
        "spare": {"add": [("pool_table", 0.9), ("jukebox", 0.5), ("sofa_4", 0.4)]},
        "rooms": {"storage": {"add": [("pool_table", 0.35)]}},
    },
    "host": {
        "weight": lambda w: _w(w, kind=NOT_RETIRED, rich=0.5, base=0.55),
        "rooms": {"dining": {"add": [("bar_counter", 0.5), ("bar_stool", 0.7), ("bar_stool", 0.5),
                                     ("mirror", 0.4)]},
                  "livingroom": {"add": [("jukebox", 0.25), ("coffee_table", 0.7)]}},
    },
    "hoarder": {
        "weight": lambda w: _w(w, kind=ANY, worn=1.0, base=0.45),
        "rooms": {r: {"add": [("box", 0.8), ("box_battered", 0.7), ("crate", 0.5)]}
                  for r in ("livingroom", "bedroom", "kitchen", "hall", "dining", "laundry")},
        "spare": {"add": [("box", 1.0), ("box", 0.8), ("box_battered", 0.8), ("crate", 0.8),
                          ("metal_rack", 0.7)]},
    },
    "minimalist": {
        "weight": lambda w: _w(w, kind=NOT_RETIRED, plan=FLAT, rich=0.4, base=0.55),
        "rooms": {r: {"drop": ["plant", "painting", "rug", "mirror", "clock", "bookshelf"]}
                  for r in ("livingroom", "bedroom", "dining", "hall", "kitchen")},
    },
    "students": {
        "weight": lambda w: _w(w, kind=ADULTS, plan=FLAT, setting={"urban": 1.4, "rural": 0.3},
                               base=0.7),
        "rooms": {"bedroom": {"add": [("desk", 0.8), ("office_chair", 0.7), ("poster_2", 0.8),
                                      ("poster_6", 0.6), ("corkboard", 0.5)],
                              "swap": {"double_bed": "bed_plain", "bed": "bed_plain"}},
                  "livingroom": {"add": [("coffee_table", 0.5), ("poster_6", 0.5)],
                                 "drop": ["plant", "painting"]}},
    },
    "young_parents": {
        "weight": lambda w: _w(w, kind=FAMILY, base=0.8),
        "rooms": {"livingroom": {"add": [("rug_small", 0.8), ("low_table_white", 0.7),
                                         ("sidetable", 0.5)]},
                  "bedroom": {"add": [("clothes_rack_small", 0.4)]},
                  "kitchen": {"add": [("coffee_maker", 0.8)]}},
    },
    "big_family": {
        "weight": lambda w: _w(w, kind=FAMILY, plan=HOUSE, base=0.6),
        "rooms": {"livingroom": {"add": [("armchair_3", 0.7), ("rug_wide", 0.6)]},
                  "kidsbedroom": {"add": [("desk", 0.6), ("poster_4", 0.7), ("poster_1", 0.5)]},
                  "kitchen": {"add": [("dining_table", 0.3)]},
                  "laundry": {"add": [("hamper", 0.9), ("hamper", 0.5)]},
                  "hall": {"add": [("coat_rack", 0.9)]}},
    },
    "widow": {
        "weight": lambda w: _w(w, kind={"retired": 1.0}, base=1.0),
        "rooms": {"livingroom": {"add": [("armchair_7", 0.9), ("radio", 0.9), ("clock", 0.7),
                                         ("sidetable", 0.8), ("rug", 0.8), ("phone", 0.5),
                                         ("erika_plant_3", 0.7)]},
                  "bedroom": {"add": [("nightstand", 0.8), ("mirror_small", 0.7)]},
                  "kitchen": {"add": [("clock", 0.6), ("radio", 0.4)]},
                  "hall": {"add": [("sidetable", 0.7), ("coat_rack", 0.6)]}},
    },
    "retired_handyman": {
        "weight": lambda w: _w(w, kind={"retired": 1.0, "adults": 0.5}, plan=HOUSE,
                               setting={"rural": 1.4}, base=0.7),
        "spare": {"add": [("metal_rack", 0.9), ("crate", 0.8), ("counter", 0.5),
                          ("shelf_2", 0.7), ("radio", 0.5)]},
        "rooms": {"laundry": {"add": [("crate", 0.5)]}},
    },
    "prepper": {
        "weight": lambda w: _w(w, kind=NOT_RETIRED, plan=HOUSE, setting={"rural": 1.8, "urban": 0.3},
                               base=0.4),
        "spare": {"add": [("gun_locker", 0.6), ("metal_rack", 0.9), ("crate", 0.9), ("crate", 0.8),
                          ("radio", 0.7), ("box", 0.7)]},
        "rooms": {"kitchen": {"add": [("shelf", 0.9), ("shelf_1", 0.7)]},
                  "hall": {"add": [("coat_rack", 0.6)]}},
    },
    "seamstress": {
        "weight": lambda w: _w(w, kind=ANY, base=0.45),
        "spare": {"add": [("mannequin", 0.9), ("clothes_rack", 0.9), ("table", 0.7),
                          ("mirror", 0.7), ("shelf_2", 0.5)]},
    },
    "bachelor": {
        "weight": lambda w: _w(w, kind=ADULTS, worn=0.6, base=0.7),
        "rooms": {"livingroom": {"add": [("coffee_table", 0.7), ("radio", 0.4)],
                                 "drop": ["plant", "painting"]},
                  "bedroom": {"add": [("poster_5", 0.5)], "drop": ["plant"]},
                  "kitchen": {"drop": ["plant"]}},
    },
    "cook": {
        "weight": lambda w: _w(w, kind=ANY, base=0.7),
        "rooms": {"kitchen": {"add": [("counter_3", 0.8), ("microwave", 0.6), ("coffee_maker", 0.7),
                                      ("toaster", 0.6), ("shelf_2", 0.7), ("erika_plant_5", 0.4)]},
                  "dining": {"add": [("dining_table_oak", 0.4)]}},
    },
    "sports_fan": {
        "weight": lambda w: _w(w, kind=NOT_RETIRED, base=0.5),
        "rooms": {"livingroom": {"add": [("poster_7", 0.8), ("poster_0", 0.6)],
                                 "drop": ["painting"]},
                  "bedroom": {"add": [("poster_7", 0.6)]}},
        "spare": {"add": [("poster_0", 0.8), ("clothes_rack_small", 0.4), ("treadmill", 0.3)]},
    },
    "classic": {
        "weight": lambda w: _w(w, kind=ANY, old=1.6, rich=0.3, base=0.65),
        "rooms": {"livingroom": {"add": [("clock", 0.8), ("rug_wide", 0.8), ("armchair_9", 0.7),
                                         ("sidetable", 0.7), ("mirror", 0.4)],
                                 "swap": {"sofa": "sofa_6"}},
                  "dining": {"add": [("dining_table_oak", 0.5), ("clock", 0.4)]},
                  "bedroom": {"swap": {"dresser": "dresser_tan", "wardrobe": "wardrobe_oak"}}},
    },
    "modern": {
        "weight": lambda w: _w(w, kind=NOT_RETIRED, rich=0.6, base=0.55,
                               plan={None: 0.8, "house": 0.8, "apartment": 1.0})
                            * (1.5 if w["age"] < 25 else 0.5),
        "rooms": {"livingroom": {"add": [("shag_rug", 0.6), ("low_table_black", 0.7),
                                         ("erika_art_44", 0.5)],
                                 "swap": {"sofa": "sofa_12"}},
                  "bedroom": {"swap": {"dresser": "dresser_black", "wardrobe": "wardrobe_black",
                                       "double_bed": "double_bed_black"}},
                  "dining": {"swap": {"dining_table": "dining_table_white"}}},
    },
}


def pick(rng: random.Random, who: dict) -> str | None:
    """A persona for this home, or None: most homes have one, not all."""
    names = list(PERSONAS)
    weights = [max(0.0, PERSONAS[n]["weight"](who)) for n in names]
    names.append(None)
    weights.append(PLAIN_WEIGHT)
    if sum(weights) <= 0:
        return None
    return rng.choices(names, weights=weights)[0]


def second(rng: random.Random, who: dict, first: str | None) -> str | None:
    """Some homes are two things: a runner who also reads. Only a few."""
    if first is None or rng.random() >= SECOND_SHARE:
        return None
    others = [n for n in PERSONAS if n != first]
    weights = [max(0.0, PERSONAS[n]["weight"](who)) for n in others]
    if sum(weights) <= 0:
        return None
    return rng.choices(others, weights=weights)[0]


SECOND_SHARE = 0.25


def _swapped(role: str, swap: dict) -> str:
    """`role` swapped for what the persona prefers, a piece's variants (double_bed_alt
    for double_bed) included."""
    for old, new in swap.items():
        if role == old or role.startswith(old + "_"):
            return new
    return role


def apply(base: list[str], room_kind: str, persona: str | None,
          rng: random.Random) -> list[str]:
    """`base` as this persona asks for it. Roles the catalog does not have are
    skipped, so a persona can name a piece before the tiles for it exist."""
    spec = PERSONAS.get(persona or "")
    if spec is None:
        return base
    out = list(base)
    parts = []
    if room_kind in spec.get("rooms", {}):
        parts.append(spec["rooms"][room_kind])
    if room_kind in SPARE_KINDS and "spare" in spec:
        parts.append(spec["spare"])
    for part in parts:
        drop = set(part.get("drop", ()))
        swap = part.get("swap", {})
        out = [_swapped(r, swap) for r in out if r not in drop]
        for role, chance in part.get("add", ()):
            if role in C.FURNITURE and rng.random() < chance:
                out.append(role)
    return out
