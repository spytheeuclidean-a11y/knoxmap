"""Appearance and layout defaults inferred for each generated building."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

GAME_YEAR = 1993
_YEAR = re.compile(r"(?:18|19|20)\d{2}")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def construction_year(tags: dict, *, before: int = 2099) -> int | None:
    for key in ("start_date", "year_built", "building:start_date",
                "construction_date", "start_construction_date"):
        match = _YEAR.search(str(tags.get(key) or ""))
        if match:
            year = int(match.group())
            if 1750 <= year <= before:
                return year
    return None


def _year(tags: dict) -> int | None:
    year = construction_year(tags, before=GAME_YEAR)
    if year is not None:
        return year
    architecture = " ".join(str(tags.get(key) or "") for key in
                             ("building:architecture", "architectural_style")).lower()
    if any(word in architecture for word in
           ("victorian", "georgian", "colonial", "craftsman", "gothic", "roman")):
        return 1910
    if any(word in architecture for word in ("mid-century", "midcentury", "art deco")):
        return 1955
    if tags.get("historic"):
        return 1890
    return None


@dataclass(frozen=True)
class ApartmentAccessRules:
    """Defaults for generated access, overridable independently per building."""

    compact_landing_max_levels: int = 5
    lift_from_levels: int = 6
    lobby_min_section_tiles: int = 224
    lobby_recent_from_year: int = 1990
    lobby_busy_from_flats: int = 24
    stair_via_balcony: bool = False


DEFAULT_APARTMENT_ACCESS = ApartmentAccessRules()


@dataclass(frozen=True)
class BuildingProfile:
    year_built: int
    age: int
    era: str
    wealth: float
    setting: str
    wear: float
    seed: int
    dated: bool = False
    apartment_access: ApartmentAccessRules = DEFAULT_APARTMENT_ACCESS
    source_year: int | None = None
    apartment_balconies: bool | None = None
    # How often this house gets an integral garage; None is the layout's own
    # GARAGE_SHARE (a regional profile sets it, knoxbuild/regional.py).
    garage_share: float | None = None

    @classmethod
    def infer(cls, tags: dict, kind: str | None, density: float,
              area_m2: float, levels: int, seed: int) -> "BuildingProfile":
        """Infer a profile from mapper facts, neighborhood context and a stable seed."""
        rng = random.Random(seed ^ 0xB17D1A)
        place = (tags.get("building:use") or tags.get("landuse") or "").lower()
        building = (tags.get("building") or "").lower()
        if place in {"farm", "farmyard", "farmland", "rural"} \
                or building in {"barn", "farmhouse", "cabin", "hut", "shed"} \
                or density < 0.06:
            setting = "rural"
        elif density >= 0.28:
            setting = "urban"
        else:
            setting = "suburban"

        year = _year(tags)
        dated = year is not None
        if year is None:
            if setting == "rural":
                typical_age = 48
            elif setting == "urban":
                typical_age = 38
            else:
                typical_age = 28
            if kind in {"church", "industrial", "civic"}:
                typical_age += 12
            age = max(0, typical_age + rng.randint(-22, 22))
            year = GAME_YEAR - age
        else:
            age = GAME_YEAR - year
        era = "prewar" if year < 1945 else "midcentury" if year < 1975 else "modern"

        classification = " ".join(str(tags.get(key) or "") for key in
                                  ("class", "building:class", "building:use")).lower()
        wealthy = any(word in classification for word in
                      ("luxury", "upper", "premium", "wealthy", "villa", "mansion"))
        modest = any(word in classification for word in
                     ("social_housing", "low_income", "working_class", "basic"))
        if wealthy:
            wealth = 0.78
        elif modest:
            wealth = 0.28
        elif kind in {"hotel", "civic", "medical"} or building in {"hotel", "office", "commercial"}:
            wealth = 0.62
        elif kind in {"industrial", "barn", "shed", "garage", "military"} or setting == "rural":
            wealth = 0.38
        else:
            wealth = 0.48
        wealth += min(0.14, max(0, levels - 2) * 0.035)
        wealth += 0.04 if area_m2 >= 500 else 0.0
        wealth += rng.uniform(-0.08, 0.08)
        wealth = _clamp(wealth)

        state = str(tags.get("building:condition") or tags.get("condition") or "").lower()
        condition = {"excellent": 0.08, "good": 0.18, "average": 0.38,
                     "fair": 0.58, "poor": 0.76, "ruinous": 0.95,
                     "ruined": 0.95}.get(state)
        if condition is None:
            condition = (0.20 + min(age, 100) * 0.0025
                         + (1.0 - wealth) * 0.16
                         + (0.08 if setting == "urban" else 0.0)
                         + rng.uniform(-0.12, 0.12))
        if str(tags.get("ruins") or "").lower() in {"yes", "building"}:
            condition = max(condition, 0.92)
        elif any(str(tags.get(key) or "").lower() == "yes"
                 for key in ("abandoned", "disused", "vacant")):
            condition = max(condition, 0.78 if tags.get("abandoned") else 0.65)

        balcony = str(tags.get("building:balconies", tags.get("balcony", ""))).lower()
        return cls(year, age, era, wealth, setting, _clamp(condition), int(seed), dated,
                   source_year=construction_year(tags),
                   apartment_balconies={"yes": True, "no": False}.get(balcony))

    def style_weight(self, name: str) -> float:
        style = name.lower()
        if self.era == "prewar":
            preferred = ("brick", "clapboard", "timber", "logs")
            modern = ("panel", "render", "trailer")
        elif self.era == "midcentury":
            preferred = ("brick", "panel", "stucco", "clapboard")
            modern = ("render", "logs")
        else:
            preferred = ("render", "panel", "painted", "stucco")
            modern = ("logs", "timber", "clapboard")
        weight = 1.35 if any(word in style for word in preferred) else 0.8 if any(
            word in style for word in modern) else 1.0
        if self.setting == "rural" and any(word in style for word in ("logs", "timber", "barn")):
            weight *= 1.35
        if self.wealth > 0.68 and any(word in style for word in ("render", "painted", "stucco")):
            weight *= 1.2
        return weight

    def furniture_weight(self, name: str) -> float:
        item = name.lower()
        weight = 1.0
        if self.wealth >= 0.65:
            if any(word in item for word in ("oak", "black", "alt", "dresser")):
                weight *= 1.35
            if "pale" in item or "tan" in item:
                weight *= 0.8
        elif self.wealth <= 0.35:
            if any(word in item for word in ("pale", "tan", "plain")):
                weight *= 1.25
            if any(word in item for word in ("black", "oak")):
                weight *= 0.7
        if self.era == "prewar" and any(word in item for word in ("alt", "tan", "brown")):
            weight *= 1.15
        return weight

    def floor_weight(self, name: str) -> float:
        floor = name.lower()
        weight = 1.0
        if self.era == "prewar" and any(word in floor for word in
                                         ("wood_mid", "wood_dark", "carpet_brown", "carpet_beige")):
            weight *= 1.35
        if self.era == "modern" and any(word in floor for word in
                                         ("tile_white", "tile_grey", "wood_pale", "office_grey")):
            weight *= 1.25
        if self.wealth >= 0.68 and any(word in floor for word in
                                       ("carpet_red", "tile_white", "wood_pale")):
            weight *= 1.3
        if self.wear >= 0.65 and any(word in floor for word in
                                     ("worn", "scuff", "dark", "grey", "brown")):
            weight *= 1.4
        if self.wear <= 0.2 and any(word in floor for word in ("worn", "scuff", "dark")):
            weight *= 0.65
        return weight

    @property
    def clutter(self) -> float:
        """A modest 0..1 estimate used to vary room dressing, not spawn loot."""
        return _clamp(self.wear * 0.65 + (1.0 - self.wealth) * 0.2
                      + (0.08 if self.setting == "urban" else 0.0))


def apartment_access_rules(profile: object | None) -> ApartmentAccessRules:
    return getattr(profile, "apartment_access", DEFAULT_APARTMENT_ACCESS)
