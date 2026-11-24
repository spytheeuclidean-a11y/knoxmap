"""What a real building is used for, from OpenStreetMap, as the game's rooms.

A pizza place in New York is rarely its own building on the map: it is a
point - amenity=restaurant, cuisine=pizza - inside a block of flats. Built
from the building outline alone, that block came out as flats over a random
shop. Here every such point inside a footprint becomes a use of its ground
floor, and each use becomes the room names the game knows, so the loot in it
is a pizza kitchen's and not a clothes shop's.

A use is (front room, back room): the room on the street - a dining room, a
sales floor, a bank hall - and the one behind it - the kitchen, the stockroom.
Every name is in the game's RoomNames.txt; those with loot of their own in
Distributions.lua were preferred.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from .entrances import closed_entrance

# Restaurants and takeaways by cuisine=*: the kitchen the game has for it.
KITCHEN_BY_CUISINE = {
    "pizza": "pizzakitchen", "italian": "restaurantkitchen",
    "burger": "burgerkitchen", "chicken": "burgerkitchen", "american": "dinerkitchen",
    "diner": "dinerkitchen", "breakfast": "dinerkitchen", "sandwich": "dinerkitchen",
    "chinese": "chinesekitchen", "asian": "chinesekitchen", "thai": "chinesekitchen",
    "vietnamese": "chinesekitchen", "korean": "chinesekitchen", "indian": "chinesekitchen",
    "japanese": "sushikitchen", "sushi": "sushikitchen", "ramen": "sushikitchen",
    "mexican": "mexicankitchen", "tex-mex": "mexicankitchen", "latin_american": "mexicankitchen",
    "seafood": "seafoodkitchen", "fish": "seafoodkitchen", "fish_and_chips": "seafoodkitchen",
    "coffee_shop": "cafekitchen", "donut": "bakerykitchen", "ice_cream": "icecreamkitchen",
}
# Dining rooms with names of their own.
DINING_BY_CUISINE = {"italian": "italianrestaurant", "chinese": "chineserestaurant"}

AMENITY_USES = {
    "restaurant": ("restaurantdining", "restaurantkitchen"),
    "fast_food": ("restaurantdining", "restaurantkitchen"),
    "food_court": ("restaurantdining", "restaurantkitchen"),
    "cafe": ("cafe", "cafekitchen"),
    "ice_cream": ("icecream", "icecreamkitchen"),
    "bar": ("bar", "barstorage"), "pub": ("bar", "barstorage"),
    "nightclub": ("bar", "barstorage"), "biergarten": ("bar", "barstorage"),
    "bank": ("bank", "office"), "bureau_de_change": ("bank", "office"),
    "post_office": ("post", "storage"),
    "pharmacy": ("pharmacy", "storage"),
    "dentist": ("dentist", "medicaloffice"),
    "doctors": ("medicaloffice", "medicaloffice"), "clinic": ("medicaloffice", "medicaloffice"),
    "veterinary": ("medicaloffice", "storage"),
    "library": ("library", "office"),
    "cinema": ("lobby", "theatre"), "theatre": ("lobby", "theatre"),
    "arts_centre": ("lobby", "theatre"),
    "police": ("policeoffice", "office"),
    "childcare": ("daycare", "storage"), "kindergarten": ("daycare", "storage"),
    "fuel": ("gasstore", "storage"),
    "car_repair": ("mechanic", "storage"),
}
SHOP_USES = {
    # Food
    "supermarket": ("grocery", "grocerystorage"), "grocery": ("grocery", "grocerystorage"),
    "greengrocer": ("grocery", "grocerystorage"), "deli": ("grocery", "grocerystorage"),
    "convenience": ("conveniencestore", "storage"), "kiosk": ("conveniencestore", "storage"),
    "newsagent": ("conveniencestore", "storage"), "tobacco": ("conveniencestore", "storage"),
    "e-cigarette": ("conveniencestore", "storage"), "beverages": ("liquorstore", "storage"),
    "alcohol": ("liquorstore", "storage"), "wine": ("liquorstore", "storage"),
    "bakery": ("bakery", "bakerykitchen"), "pastry": ("bakery", "bakerykitchen"),
    "confectionery": ("candystore", "storage"), "chocolate": ("candystore", "storage"),
    "coffee": ("cafe", "cafekitchen"), "tea": ("cafe", "cafekitchen"),
    "ice_cream": ("icecream", "icecreamkitchen"), "butcher": ("butcher", "storage"),
    "seafood": ("butcher", "storage"),
    # Health and beauty
    "chemist": ("pharmacy", "storage"), "pharmacy": ("pharmacy", "storage"),
    "medical_supply": ("pharmacy", "storage"), "optician": ("pharmacy", "storage"),
    "cosmetics": ("pharmacy", "storage"), "perfumery": ("pharmacy", "storage"),
    "hairdresser": ("aesthetic", "storage"), "beauty": ("aesthetic", "storage"),
    "massage": ("aesthetic", "storage"), "tattoo": ("aesthetic", "storage"),
    "nails": ("aesthetic", "storage"),
    # Clothes and things
    "clothes": ("clothingstore", "storage"), "shoes": ("clothingstore", "storage"),
    "fashion": ("clothingstore", "storage"), "boutique": ("clothingstore", "storage"),
    "bag": ("clothingstore", "storage"), "fashion_accessories": ("clothingstore", "storage"),
    "department_store": ("departmentstore", "storage"), "mall": ("departmentstore", "storage"),
    "jewelry": ("jewelrystore", "storage"), "watches": ("jewelrystore", "storage"),
    "books": ("bookstore", "storage"), "stationery": ("bookstore", "storage"),
    "newspaper": ("bookstore", "storage"), "video": ("movierental", "storage"),
    "video_games": ("movierental", "storage"), "toys": ("toystore", "storage"),
    "games": ("toystore", "storage"), "gift": ("giftstore", "storage"),
    "souvenir": ("giftstore", "storage"), "variety_store": ("giftstore", "storage"),
    "art": ("giftstore", "storage"), "florist": ("gardenstore", "storage"),
    "garden_centre": ("gardenstore", "storage"), "farm": ("gardenstore", "storage"),
    "furniture": ("furniturestore", "storage"),
    "interior_decoration": ("furniturestore", "storage"), "bed": ("furniturestore", "storage"),
    "music": ("musicstore", "storage"), "musical_instrument": ("musicstore", "storage"),
    "photo": ("camerastore", "storage"), "camera": ("camerastore", "storage"),
    "electronics": ("electronicsstore", "storage"), "mobile_phone": ("electronicsstore", "storage"),
    "computer": ("electronicsstore", "storage"), "hifi": ("electronicsstore", "storage"),
    "sports": ("sportstore", "storage"), "outdoor": ("sportstore", "storage"),
    "bicycle": ("sportstore", "storage"), "weapons": ("gunstore", "storage"),
    "hardware": ("toolstore", "storage"), "doityourself": ("toolstore", "storage"),
    "trade": ("toolstore", "storage"), "tools": ("toolstore", "storage"),
    "car_parts": ("toolstore", "storage"), "paint": ("toolstore", "storage"),
    "car_repair": ("mechanic", "storage"),
    "laundry": ("laundry", "storage"), "dry_cleaning": ("laundry", "storage"),
    "general": ("generalstore", "storage"),
}
HEALTHCARE_USES = {"dentist": ("dentist", "medicaloffice"), "doctor": ("medicaloffice", "medicaloffice"),
                   "clinic": ("medicaloffice", "medicaloffice"), "pharmacy": ("pharmacy", "storage")}
LEISURE_USES = {"fitness_centre": ("gym", "storage"), "sports_centre": ("gym", "storage"),
                "dance": ("gym", "storage"), "bowling_alley": ("bar", "barstorage")}
TOURISM_USES = {"hotel": ("lobby", "office"), "motel": ("lobby", "office"),
                "hostel": ("lobby", "office"), "guest_house": ("lobby", "office"),
                "museum": ("lobby", "storage"), "gallery": ("giftstore", "storage")}
OFFICE_USE = ("office", "office")

# Rooms on the street a shop front is glazed for and a door goes into.
FRONT_ROOMS = {front for table in (AMENITY_USES, SHOP_USES, HEALTHCARE_USES, LEISURE_USES,
                                   TOURISM_USES) for front, _back in table.values()} \
    - {"library", "theatre", "policeoffice", "daycare", "mechanic", "office"} \
    | {"italianrestaurant", "chineserestaurant"}
# The keys of the OSM tags this reads; the overpass query asks for points
# with any of them (generator/osm.py).
USE_KEYS = ("amenity", "shop", "healthcare", "leisure", "tourism", "office", "craft")
# Food rooms; the others are sold from.
FOOD_FRONTS = {"restaurantdining", "italianrestaurant", "chineserestaurant", "cafe", "icecream",
               "bar", "bakery"}


def use_of(tags: dict) -> tuple[str, str] | None:
    """The (front room, back room) one set of OSM tags makes, or None."""
    amenity = (tags.get("amenity") or "").strip().lower()
    cuisine = (tags.get("cuisine") or "").split(";")[0].strip().lower()
    if amenity in ("restaurant", "fast_food", "food_court", "cafe"):
        front, back = AMENITY_USES[amenity]
        if cuisine in KITCHEN_BY_CUISINE and amenity != "cafe":
            back = KITCHEN_BY_CUISINE[cuisine]
            front = DINING_BY_CUISINE.get(cuisine, front)
        return front, back
    if amenity in AMENITY_USES:
        return AMENITY_USES[amenity]
    shop = (tags.get("shop") or "").strip().lower()
    if shop in SHOP_USES:
        return SHOP_USES[shop]
    if shop and shop not in ("no", "vacant", "yes"):
        return ("generalstore", "storage")
    for key, table in (("healthcare", HEALTHCARE_USES), ("leisure", LEISURE_USES),
                       ("tourism", TOURISM_USES)):
        value = (tags.get(key) or "").strip().lower()
        if value in table:
            return table[value]
    if tags.get("office") or tags.get("craft"):
        return OFFICE_USE
    return None


def uses_of(tag_sets: list[dict], limit: int = 8) -> list[tuple[str, str]]:
    """The uses of a building's own tags and the points inside it, in order,
    each once."""
    out: list[tuple[str, str]] = []
    for tags in tag_sets:
        use = use_of(tags)
        if use and use not in out:
            out.append(use)
    return out[:limit]


@dataclass(frozen=True)
class GroundBusiness:
    front: str
    back: str
    position: tuple[float, float] | None
    name: str = ""
    entrance: tuple[float, float] | None = None


def _at_ground(tags: dict) -> bool:
    if tags.get("location") == "underground":
        return False
    raw = tags.get("level")
    if raw is None or raw == "":
        raw = tags.get("min_level", "")
    level = str(raw if raw is not None else "").casefold().replace(" ", "")
    return not level or bool({"0", "ground"} & set(level.split(";")))


def ground_businesses(tags: dict, points, entrances=(), *, mode="auto",
                      commercial_area=False) -> tuple[GroundBusiness, ...]:
    """Use confirmed ground-floor venues before inferring the floor of other POIs."""
    if mode == "residential":
        return ()

    def has_level(item):
        return any(item.get(key) not in (None, "") for key in ("level", "min_level"))

    building_uses = {s.strip().casefold() for s in str(tags.get("building:use") or "").split(";")}
    building_business = use_of(tags)
    at_ground = _at_ground(tags)
    commercial_building = at_ground and (building_business or building_uses & {"commercial", "retail"})
    infer_floor = mode == "mixed" or commercial_area or commercial_building
    result = []
    sources = []
    unconfirmed = set()
    identities = ("wikidata", "ref", "contact:website", "website")
    candidates = []
    portals = [(x, y, item) for x, y, item in entrances
               if _at_ground(item) and not closed_entrance(item)
               and not item.get("addr:flats")
               and item.get("entrance") not in ("staircase", "service", "emergency_exit")]
    for x, y, item in sorted(points, key=lambda p: (not has_level(p[2]), bool(p[2].get("_knox_area_poi")))):
        use = use_of(item)
        if not use:
            continue
        name = str(item.get("name") or "")
        normalized = name.strip().casefold()
        pos = (x, y)
        area = bool(item.get("_knox_area_poi"))
        refs = {(key, str(item[key])) for key in identities[:2] if item.get(key)}
        ground = _at_ground(item)
        if any(use == use2 and math.dist(pos, pos2) <= 5
               and (ground == ground2 or not has_level(item))
               and (not normalized or not name2 or normalized == name2) and (
                bool(refs & refs2)
                or (area != area2 and normalized and normalized == name2))
               for use2, pos2, name2, refs2, area2, ground2 in sources):
            continue
        sources.append((use, pos, normalized, refs, area, ground))
        if not ground:
            continue
        for ex, ey, info in portals:
            portal_name = str(info.get("name") or "").strip().casefold()
            distance = math.dist(pos, (ex, ey))
            if portal_name and normalized:
                if portal_name != normalized:
                    continue
                rank = 0
            elif any(item.get(k) and item.get(k) == info.get(k) for k in identities):
                rank = 1
            elif not portal_name and info.get("entrance") == "shop" and distance <= 3:
                rank = 2
            else:
                continue
            candidates.append((rank, distance, len(result), ex, ey))
        result.append(GroundBusiness(*use, pos, name))
        if not has_level(item):
            unconfirmed.add(len(result) - 1)

    assigned = set()
    for _rank, _distance, i, x, y in sorted(candidates, key=lambda c: (c[2] in unconfirmed, *c)):
        if result[i].entrance is None and (x, y) not in assigned:
            result[i] = replace(result[i], entrance=(x, y))
            assigned.add((x, y))

    result = [business for i, business in enumerate(result)
              if i not in unconfirmed or business.entrance is not None or infer_floor]
    if building_business and at_ground and not any((b.front, b.back) == building_business for b in result):
        result.append(GroundBusiness(*building_business, None, str(tags.get("name") or "")))
    for x, y, item in portals:
        if item.get("entrance") == "shop" and (x, y) not in assigned:
            result.append(GroundBusiness(*(use_of(item) or ("generalstore", "storage")),
                                         (x, y), str(item.get("name") or ""), (x, y)))
            assigned.add((x, y))
    if not result and (mode == "mixed" or (at_ground and "retail" in building_uses)):
        result.append(GroundBusiness("generalstore", "storage", None))
    return tuple(result)


def is_hotel(tag_sets: list[dict]) -> bool:
    return any((t.get("tourism") or "") in ("hotel", "motel", "hostel") or
               (t.get("building") or "") == "hotel" for t in tag_sets)
