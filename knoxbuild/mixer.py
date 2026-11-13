"""How a map's ceiling is shared out: by kind of building, and by town.

`max_buildings` says how many buildings the whole map may hold
(knoxbuild/procedural.cap). On its own it keeps whatever the spacing rule
keeps, which is the map's own mix - and a map whose real mix is nine houses
to a shop comes out as nine houses to a shop however few buildings are
asked for.

Two things are asked for instead, and both are shares of that one total:

**By kind.** "Of 3000 buildings, 40% houses, 15% shops, 10% industrial" -
so a map can be made to feel like a place with a high street rather than an
estate, without touching what the ground really is.

**By town.** A box with two cities and ten villages in it has nearly all
its footprints in the cities, so a ceiling takes the villages away first
and leaves two cities and ten hamlets of three houses. Shared evenly, each
of the twelve gets the same number and a village stays a village.

Neither is a promise, and cannot be: the map can only keep buildings that
are on it. Ask for 450 shops where OpenStreetMap has 20 and you get 20 -
so what a kind cannot use is handed to the kinds that can, and what a town
cannot use to the towns that can. Without that, asking for 3000 buildings
on a map whose mix is nothing like the one asked for would quietly build
800.
"""
from __future__ import annotations

import math

# The kinds knoxbuild builds, under the names somebody would use for them.
# A mix may be written in either: "farm=5" and "barn=5" are the same ask.
ALIASES = {
    "farm": "barn",
    "farmhouse": "barn",
    "houses": "house",
    "flats": "apartment",
    "apartments": "apartment",
    "shops": "shop",
    "retail": "shop",
    "factory": "industrial",
    # knoxbuild has no warehouse of its own: OpenStreetMap's warehouses are
    # built as industrial buildings, so the two are one share.
    "warehouse": "industrial",
    "works": "industrial",
    "garages": "garage",
    "schools": "school",
    "hospital": "medical",
    "healthcare": "medical",
    "churches": "church",
    "public": "civic",
    "government": "civic",
}

# What is counted as what. A kind with no line here falls in "other", which
# is why "other" is worth a share of its own: it is the libraries, hotels,
# stadiums, castles and hangars, and a map with none of them should not
# lose the share they were promised.
OF_KIND = {
    None: "house",
    "house": "house",
    "apartment": "apartment",
    "shop": "shop",
    "mall": "shop",
    "restaurant": "shop",
    "industrial": "industrial",
    "garage": "garage",
    "barn": "barn",
    "school": "school",
    "medical": "medical",
    "police": "police",
    "church": "church",
    "civic": "civic",
}

# The shares a map takes when none are given but one is asked for by name.
# Somebody's own numbers, as a starting point rather than a rule.
PRESET_MIX = ("house=40,apartment=10,shop=15,industrial=13,garage=5,"
              "barn=5,school=3,medical=2,police=2,church=2,civic=2,other=1")


def category_of(kind: str | None) -> str:
    """Which share this building comes out of."""
    return OF_KIND.get(kind, "other")


def parse(spec: str) -> dict[str, float]:
    """A mix as shares that add to 1, or {} when nothing usable is in it.

    Written as "house=40,shop=15". The numbers are read as weights and
    normalised, so they need not add to a hundred: half the people who
    write one of these will not make them, and refusing the map over
    arithmetic helps nobody.
    """
    if not isinstance(spec, str):
        return {}
    spec = spec.strip()
    if not spec:
        return {}
    if spec.lower() in ("preset", "default", "typical"):
        spec = PRESET_MIX
    weights: dict[str, float] = {}
    for part in spec.replace(";", ",").split(","):
        if "=" not in part:
            continue
        name, _, raw = part.partition("=")
        name = name.strip().lower().replace(" ", "_")
        name = ALIASES.get(name, name)
        try:
            weight = float(raw.strip().rstrip("%"))
        except ValueError:
            continue
        if weight > 0 and math.isfinite(weight):
            weights[name] = weights.get(name, 0.0) + weight
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {name: weight / total for name, weight in weights.items()}


def nearest_place(x: float, y: float, places: list) -> str:
    """Which town's share this building comes out of.

    Every building belongs to the nearest one, however far that is: a farm
    five miles out is that village's countryside, and a radius here would
    only be a number nobody could guess the right value for.
    """
    best, best_d2 = "", None
    for place in places:
        try:
            dx = float(place["tile_x"]) - x
            dy = float(place["tile_y"]) - y
        except (KeyError, TypeError, ValueError):
            continue
        d2 = dx * dx + dy * dy
        if best_d2 is None or d2 < best_d2:
            best, best_d2 = str(place.get("name") or f"{place.get('tile_x')},"
                                                    f"{place.get('tile_y')}"), d2
    return best


def share_out(counts: dict, limit: int, shares: dict | None = None) -> dict:
    """How many of `limit` each group gets, given how many it could use.

    `counts` is how many buildings each group has to offer. `shares` is what
    each group was promised, as fractions of one; with none, every group is
    promised the same. A group that cannot fill its promise hands the rest
    back, and what comes back is shared among the groups that still have
    buildings left - repeatedly, because the second round can overflow too.
    """
    groups = [g for g, n in counts.items() if n > 0]
    if not groups or limit <= 0:
        return {}
    if shares:
        weights = {g: float(shares.get(g, 0.0)) for g in groups}
        if sum(weights.values()) <= 0:
            weights = {g: 1.0 for g in groups}
    else:
        weights = {g: 1.0 for g in groups}

    budget: dict = {g: 0 for g in groups}
    left = int(limit)
    open_groups = set(groups)
    while left > 0 and open_groups:
        total = sum(weights[g] for g in open_groups)
        if total <= 0:
            break
        handed = 0
        for g in sorted(open_groups):
            room = counts[g] - budget[g]
            if room <= 0:
                continue
            want = int(left * weights[g] / total)
            take = max(0, min(room, want))
            budget[g] += take
            handed += take
        if handed == 0:
            # Rounding left everybody at zero: hand the remainder out one at
            # a time, biggest share first, so a limit smaller than the number
            # of groups still places buildings.
            for g in sorted(open_groups, key=lambda g: (-weights[g], g)):
                if left <= 0:
                    break
                if counts[g] - budget[g] > 0:
                    budget[g] += 1
                    left -= 1
            break
        left -= handed
        open_groups = {g for g in open_groups if counts[g] - budget[g] > 0}
    return {g: n for g, n in budget.items() if n > 0}


def budgets(items: list, limit: int, mix: dict | None,
            by_place: bool) -> tuple[dict, dict]:
    """(budget per group, group of each item) for a map held to `limit`.

    `items` are (index, kind, place). A group is a kind, a town, or both,
    depending on what was asked for; with neither it is one group and the
    ceiling behaves as it always did.
    """
    group_of: dict = {}
    for index, kind, place in items:
        key = []
        if by_place:
            key.append(place)
        if mix:
            key.append(category_of(kind))
        group_of[index] = tuple(key) if key else ("all",)

    counts: dict = {}
    for key in group_of.values():
        counts[key] = counts.get(key, 0) + 1

    shares = None
    if mix or by_place:
        places = {k[0] for k in counts} if by_place else {None}
        shares = {}
        for key in counts:
            share = 1.0 / max(1, len(places)) if by_place else 1.0
            if mix:
                share *= mix.get(key[-1], 0.0)
            shares[key] = share
        if sum(shares.values()) <= 0:
            shares = None
    return share_out(counts, limit, shares), group_of
