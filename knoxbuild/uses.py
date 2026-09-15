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
    "garden_centre": ("gardenstore", "storage"), "furniture": ("furniturestore", "storage"),
    "interior_decoration": ("furniturestore", "storage"), "bed": ("furniturestore", "storage"),
    "music": ("musicstore", "storage"), "musical_instrument": ("musicstore", "storage"),
    "photo": ("camerastore", "storage"), "camera": ("camerastore", "storage"),
    "electronics": ("camerastore", "storage"), "mobile_phone": ("camerastore", "storage"),
    "computer": ("camerastore", "storage"), "hifi": ("camerastore", "storage"),
    "sports": ("sportstore", "storage"), "outdoor": ("sportstore", "storage"),
    "bicycle": ("sportstore", "storage"), "weapons": ("gunstore", "storage"),
    "hardware": ("toolstore", "storage"), "doityourself": ("toolstore", "storage"),
    "trade": ("toolstore", "storage"), "tools": ("toolstore", "storage"),
    "car_parts": ("toolstore", "storage"), "paint": ("toolstore", "storage"),
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


def is_hotel(tag_sets: list[dict]) -> bool:
    return any((t.get("tourism") or "") in ("hotel", "motel", "hostel") or
               (t.get("building") or "") == "hotel" for t in tag_sets)
