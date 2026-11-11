"""The floor plan itself: rooms, the plan grid, and the split that
starts every one of them.

Nothing here calls the numbers-to-rooms code: it is the floor everything else
stands on.
"""
from __future__ import annotations

from .. import catalog as C
from dataclasses import dataclass
from dataclasses import field
import random




MIN_ROOM = 3          # smallest room dimension, in tiles
MIN_SPLIT = MIN_ROOM * 2 + 1
# Keep cutting while a region is bigger than roughly one generous room. This,
# rather than a fixed recursion depth, is what stops a 26x27 shop ending up as
# one cavernous 21x23 space.
TARGET_ROOM_AREA = 56
# Only a safety net against runaway recursion; TARGET_ROOM_AREA is what should
# decide when to stop. At 5 the cap bound first and left 18x18 living rooms in
# large buildings, and at 8 a warehouse 200 tiles across still did. There is
# no cost to a generous cap: the target area is what decides.
MAX_DEPTH = 16


@dataclass
class Room:
    x0: int
    y0: int
    x1: int   # inclusive
    y1: int   # inclusive
    kind: str = "hall"
    # Which dwelling this room belongs to. 0 is shared circulation - the
    # landing and corridor everyone uses. A flat's rooms open onto each other
    # and onto the corridor once, never into the flat next door.
    unit: int = 0
    # The stair shaft or corridor. Kept as a flag rather than recognised by its
    # rectangle, because a sliver folded into it changes the rectangle.
    is_core: bool = False
    # Its kind is already decided and the mix must not overwrite it: the
    # mall concourse, carved before the units are cut out around it.
    fixed: bool = False
    # An elevator shaft: a sealed box with the lift doors set into one wall.
    # No doorway, no furniture, no windows, never merged into a neighbour.
    is_shaft: bool = False

    @property
    def w(self) -> int:
        return self.x1 - self.x0 + 1

    @property
    def h(self) -> int:
        return self.y1 - self.y0 + 1

    @property
    def area(self) -> int:
        return self.w * self.h


@dataclass
class Plan:
    width: int
    height: int
    rooms: list[Room] = field(default_factory=list)
    grid: list[list[int]] = field(default_factory=list)   # 1-based room index
    doors: list[tuple[int, int, str]] = field(default_factory=list)
    windows: list[tuple[int, int, str]] = field(default_factory=list)
    furniture: list[tuple[str, int, int, str]] = field(default_factory=list)
    # None = the building fills its rectangle; otherwise True where
    # the real footprint lies. Tiles outside it stay room 0, which is
    # how BuildingEd knows they are not part of the building.
    mask: list[list[bool]] | None = None
    # True when these rooms were drawn by hand rather than laid out here. A
    # plan cut out of a slanted footprint is full of wedges that are not
    # rooms; a plan somebody drew has none, and the pieces that look like one
    # are rooms they meant (knoxbuild/designer.py).
    drawn: bool = False
    # Squares deliberately left open to the storey below: the hole in an
    # upper floor of a mall, so the concourse is one space several storeys
    # tall and you can see the ground floor from the gallery. They belong to
    # no room, which is how BuildingEd leaves a square with no floor, and
    # tbx.py counts them as built-over so the storey below is not roofed.
    void: set = field(default_factory=set)
    # Squares of a room left without floor: the top of a flight rising from a
    # basement below (knoxbuild/basements.py), written as hole objects.
    holes: set = field(default_factory=set)
    # The edges of that hole, as (x, y, "W"|"N"): a gallery looks over the
    # floor below across a railing, not a glazed wall. tbx.py draws these as
    # wall runs of fencing.
    railing: set = field(default_factory=set)
    # Edges of the hole that carry nothing at all - where an escalator
    # arrives. Taking the railing off is not enough: with no wall object on
    # it the edge falls back to the building's exterior wall, and the way off
    # the escalator came out bricked up.
    open_edge: set = field(default_factory=set)
    # The stair shaft, as (x0, y0, x1, y1) inclusive, identical on every
    # storey of a building. Painted last so it is always exactly one room.
    core: tuple[int, int, int, int] | None = None
    # True when the core is a corridor flats open onto, not just a stair shaft.
    corridor: bool = False
    # The elevator shaft (x0, y0, x1, y1) inclusive, and where its doors hang:
    # (x, y, "W" or "N") for the two-square wall edge facing the stair hall.
    shaft: tuple[int, int, int, int] | None = None
    shaft_door: tuple[int, int, str] | None = None
    # Every lift on the storey as (rect, door), the first being shaft above.
    shafts: list = field(default_factory=list)
    # Flats laid out open plan: one room for the kitchen and the living room
    # together. Decided when the flat is cut, not after - a flat already
    # divided into four equal rooms cannot be made open by renaming one of
    # them, and at 16 m2 a room has no space for a sofa and a television.
    open_units: set = field(default_factory=set)
    # Wall edges carrying a switch, painting or mirror; windows keep off them.
    wall_pieces: set = field(default_factory=set)
    stalls: list = field(default_factory=list)  # toilet tile and back-wall direction
    # The sleeve of floor round each room's way in that no optional piece may
    # take: one tile either side of the walkway and of every door.
    sleeve: set = field(default_factory=set)
    # Ground-floor windows that are a shop front, glazed with big panels.
    shop_front: set = field(default_factory=set)
    # What the building is (build_plan's kind), for rooms furnished by it: an
    # office in a house is a study, in an office block it is desks.
    kind: str | None = None
    # A mall laid out as one (_mall_plan): the concourse spine between the
    # anchors, the centre court on it, and each anchor store, all as grid
    # rectangles (x0, y0, x1, y1) inclusive. None and empty on anything else.
    spine: tuple[int, int, int, int] | None = None
    court: tuple[int, int, int, int] | None = None
    anchors: list = field(default_factory=list)
    # Outside wall edges this storey shares with the building next door:
    # no window, shop front or door goes in them.
    party: set = field(default_factory=set)
    profile: object | None = None
    # A large house (build_plan): its rooms take a mansion's finishes and
    # dressing instead of a small house's.
    grand: bool = False


# kind -> (floor tile entry index, display name, furniture wishlist)
ROOM_STYLE = {
    "livingroom": (C.FLOOR_CARPET_RED, "Living Room",
                   ["sofa", "armchair", "tv", "sidetable", "bookshelf", "lamp",
                    "painting", "plant", "armchair", "shelf", "lamp", "shag_rug"]),
    # Nothing here that wants a wall: the counters fill whatever wall the
    # wishlist leaves, and Knox County's kitchens carry as much counter as
    # ours do. What ours were short of - a table, chairs, a mat - stands in
    # the middle, so it is in the centre group rather than on this list.
    # The washing machine is on its own list: Knox County keeps laundry out of
    # four kitchens in five, and having it in the wishlist proper put one in
    # 80% of ours. See LAUNDRY_IN_KITCHEN.
    "kitchen": (C.FLOOR_TILE_CHECK, "Kitchen",
                ["fridge", "stove", "kitchen_sink", "counter", "counter",
                 "shelf", "plant"]),
    # One room that is kitchen and living room both, for a flat with no wall
    # between them. The cooking end comes first so it takes the wall it needs
    # before the sofa and the television are placed.
    # The cooking end first, so it takes the wall it needs before the rest.
    # The sofa is on both this list and the centre group: these rooms come out
    # as strips about four tiles deep, and a sofa with a walkway round it does
    # not fit in four tiles - against the wall is what a flat that size really
    # has, and the centre group takes over in the ones with room for it.
    "openplan": (C.FLOOR_WOOD, "Living Room (open plan)",
                 ["fridge", "stove", "kitchen_sink", "counter", "counter",
                  "sofa", "tv", "shelf", "plant", "painting"]),
    "bedroom": (C.FLOOR_CARPET_BLUE, "Bedroom",
                ["double_bed", "wardrobe", "dresser_alt", "sidetable", "lamp",
                 "painting", "mirror", "dresser", "bookshelf", "plant"]),
    "bathroom": (C.FLOOR_TILE_PALE, "Bathroom",
                 ["toilet", "bath", "sink", "mirror", "bath_mat", "shelf", "shower"]),
    "dining": (C.FLOOR_WOOD, "Dining Room",
               ["dresser", "painting", "plant", "shelf", "lamp", "bookshelf"]),
    "hall": (C.FLOOR_WOOD, "Hall",
             ["sidetable", "painting", "plant", "mirror", "lamp", "shelf",
              "bookshelf", "painting"]),
    "storage": (C.FLOOR_LINO, "Storage",
                ["shelf", "crate", "shelf", "crate", "bookshelf"]),
    # Vanilla room names, with the game's own loot for them.
    "kidsbedroom": (C.FLOOR_CARPET_BLUE, "Kids Bedroom",
                    ["bed", "dresser", "bookshelf", "lamp", "shelf", "plant",
                     "painting", "sidetable"]),
    "closet": (C.FLOOR_WOOD, "Closet", ["wardrobe", "shelf", "crate", "wardrobe2"]),
    # A school canteen: the hall the food is eaten in, with the kitchen that
    # serves it next door. The tables are the centre group below.
    "diningroom": (C.FLOOR_TILE_CHECK, "Canteen",
                   ["counter", "vending", "shelf", "plant", "painting",
                    "water_cooler"]),
    "schoollab": (C.FLOOR_TILE_PALE, "Laboratory",
                  ["counter", "counter", "sink", "table", "shelf",
                   "chair", "stove", "chair"]),
    "schoolstorage": (C.FLOOR_LINO, "School Storage",
                      ["shelf", "crate", "metal_rack", "crate", "bookshelf"]),
    "sportstorage": (C.FLOOR_LINO, "Sports Store Stockroom",
                     ["metal_rack", "crate", "shelf", "crate"]),
    "janitor": (C.FLOOR_LINO, "Janitor",
                ["shelf", "crate", "sink", "metal_rack"]),
    "security": (C.FLOOR_LINO, "Security",
                 ["desk", "office_chair", "corkboard", "filing_cabinet",
                  "shelf"]),
    "officestorage": (C.FLOOR_LINO, "Office Storage",
                      ["shelf", "filing_cabinet", "crate", "metal_rack"]),
    "laundry": (C.FLOOR_TILE_PALE, "Laundry", ["washer", "shelf", "crate", "sink"]),
    "generalstore": (C.FLOOR_TILE_CHECK, "General Store",
                     ["shop_shelf", "shop_shelf_wood", "shop_counter", "shop_fridge_double"]),
    "conveniencestore": (C.FLOOR_TILE_PALE, "Convenience Store",
                         ["shop_shelf_red", "shop_fridge", "shop_counter_red", "vending"]),
    "clothingstore": (C.FLOOR_WOOD, "Clothing Store",
                      ["clothes_rack", "shop_shelf_wood", "mirror", "shop_counter", "mannequin"]),
    "cafe": (C.FLOOR_WOOD, "Cafe",
             ["counter", "fridge", "stove", "chair", "chair", "plant", "painting"]),
    # Shops fitted out by interiors.furnish_store; the wishlists are for a
    # room too small for rows of shelving.
    "grocery": (C.FLOOR_TILE_CHECK, "Grocery", ["shop_shelf", "shop_fridge_double", "shop_counter"]),
    "liquorstore": (C.FLOOR_TILE_PALE, "Liquor Store", ["shop_shelf", "shop_fridge", "shop_counter"]),
    "pharmacy": (C.FLOOR_TILE_PALE, "Pharmacy", ["shop_shelf_white", "shop_counter", "shop_case"]),
    "bookstore": (C.FLOOR_WOOD, "Bookstore", ["bookshelf", "bookshelf", "shop_counter"]),
    "toolstore": (C.FLOOR_LINO, "Tool Store", ["metal_rack", "shop_shelf", "shop_counter"]),
    "grocerystorage": (C.FLOOR_LINO, "Grocery Storage", ["metal_rack", "crate", "crate", "shelf"]),
    # A concourse is walked down, not furnished. Knox County's has 16 pieces
    # of furniture in 5,855 tiles - 0.03 per 10 - and what fills it instead is
    # the shopfronts along its edges (location_shop_mall_01). A planter and a
    # bin here and there is the whole of it; anything more and the hundreds of
    # people it is built for cannot get past.
    "concourse": (C.FLOOR_TILE_PALE, "Concourse",
                  ["plant", "shop_bin", "vending"]),
    # The units Knox County's mall is let out to, and the storerooms behind
    # them. Fitted out by interiors.furnish_store like the shops above; these
    # wishlists are for a unit too small for rows of shelving.
    "clothesstore": (C.FLOOR_WOOD, "Clothes Store",
                     ["clothes_rack", "shop_shelf_wood", "mirror", "shop_counter", "mannequin"]),
    "shoestore": (C.FLOOR_WOOD, "Shoe Store",
                  ["shop_shelf_wood", "shop_display", "mirror", "shop_counter"]),
    "sewingstore": (C.FLOOR_WOOD, "Sewing Store",
                    ["shop_shelf_wood", "shop_display", "shop_counter"]),
    "electronicsstore": (C.FLOOR_TILE_PALE, "Electronics Store",
                         ["shop_shelf", "shop_case", "shop_counter"]),
    "housewarestore": (C.FLOOR_TILE_CHECK, "Houseware Store",
                       ["shop_shelf_wood", "dresser", "shop_counter"]),
    "cornerstore": (C.FLOOR_TILE_PALE, "Corner Store",
                    ["shop_shelf_red", "shop_fridge", "shop_counter_red"]),
    "optometrist": (C.FLOOR_TILE_PALE, "Optometrist",
                    ["shop_case", "shop_counter", "mirror", "chair"]),
    "dressingrooms": (C.FLOOR_WOOD, "Dressing Rooms", ["mirror", "chair"]),
    "foodcourt": (C.FLOOR_TILE_CHECK, "Food Court",
                  ["table", "chair", "chair", "chair", "bin", "plant"]),
    "clothesstorage": (C.FLOOR_LINO, "Clothes Storage",
                       ["metal_rack", "crate", "shelf", "clothes_rack"]),
    "departmentstorage": (C.FLOOR_LINO, "Department Storage",
                          ["metal_rack", "crate", "crate", "shelf"]),
    "giftstorage": (C.FLOOR_LINO, "Gift Storage", ["shelf", "crate", "metal_rack"]),
    "toystorage": (C.FLOOR_LINO, "Toy Storage", ["shelf", "crate", "metal_rack"]),
    "bookstorage": (C.FLOOR_LINO, "Book Storage", ["shelf", "crate", "bookshelf"]),
    # What OpenStreetMap says a ground floor is (knoxbuild/uses.py), by the
    # game's own room names so the loot fits: eating places and their
    # kitchens, and the other shops and services of a high street.
    "restaurantdining": (C.FLOOR_TILE_CHECK, "Restaurant Dining",
                         ["plant", "painting", "plant"]),
    "italianrestaurant": (C.FLOOR_WOOD, "Italian Restaurant",
                          ["plant", "painting", "bookshelf", "plant"]),
    "chineserestaurant": (C.FLOOR_CARPET_RED, "Chinese Restaurant",
                          ["plant", "painting", "plant"]),
    "icecream": (C.FLOOR_TILE_PALE, "Ice Cream Parlour",
                 ["shop_freezer", "shop_counter", "shop_freezer", "plant"]),
    **{k: (C.FLOOR_TILE_PALE, label,
           ["stove", "stove_alt", "fridge", "kitchen_sink", "shop_fridge_double", "metal_rack",
            "crate", "stove"])
       for k, label in (("restaurantkitchen", "Restaurant Kitchen"), ("pizzakitchen", "Pizza Kitchen"),
                        ("burgerkitchen", "Burger Kitchen"), ("dinerkitchen", "Diner Kitchen"),
                        ("chinesekitchen", "Chinese Kitchen"), ("sushikitchen", "Sushi Kitchen"),
                        ("mexicankitchen", "Mexican Kitchen"), ("seafoodkitchen", "Seafood Kitchen"),
                        ("cafekitchen", "Cafe Kitchen"), ("bakerykitchen", "Bakery Kitchen"),
                        ("icecreamkitchen", "Ice Cream Kitchen"))},
    "barstorage": (C.FLOOR_LINO, "Bar Storage", ["crate", "crate", "metal_rack", "shop_fridge"]),
    "bank": (C.FLOOR_TILE_CHECK, "Bank",
             ["shop_counter", "shop_counter", "desk", "office_chair", "filing_cabinet", "plant",
              "painting", "water_cooler"]),
    "post": (C.FLOOR_LINO, "Post Office",
             ["shop_counter", "shop_counter", "shop_shelf", "crate", "crate", "corkboard"]),
    "aesthetic": (C.FLOOR_TILE_CHECK, "Salon",
                  ["chair", "mirror", "sink", "chair", "mirror", "sink", "armchair", "shelf",
                   "plant"]),
    "dentist": (C.FLOOR_TILE_PALE, "Dentist",
                ["bed", "sink", "counter", "shelf", "chair", "filing_cabinet"]),
    "medicaloffice": (C.FLOOR_TILE_PALE, "Medical Office",
                      ["bed", "sink", "counter", "desk", "office_chair", "filing_cabinet"]),
    # Seats come in rows (CENTRE_GROUPS); along the walls only a plant.
    "theatre": (C.FLOOR_CARPET_RED, "Theatre", ["plant", "painting"]),
    "policeoffice": (C.FLOOR_LINO, "Police Office",
                     ["desk", "office_chair", "filing_cabinet", "corkboard", "water_cooler"]),
    # The rest of a police station. Every name is one of the game's own, so
    # the uniforms, the guns and the evidence lockers spawn where they should.
    "policehall": (C.FLOOR_LINO, "Police Hall",
                   ["shop_counter", "corkboard", "chair", "plant", "painting"]),
    "policelocker": (C.FLOOR_LINO, "Police Lockers",
                     ["wardrobe", "wardrobe", "shelf", "chair", "wardrobe_pale"]),
    "policeoutfitstorage": (C.FLOOR_LINO, "Police Outfit Storage",
                            ["wardrobe", "metal_rack", "shelf", "crate"]),
    "policestorage": (C.FLOOR_LINO, "Police Storage",
                      ["metal_rack", "shelf", "crate", "filing_cabinet"]),
    "policegunstorage": (C.FLOOR_LINO, "Police Gun Storage",
                         ["gun_locker", "gun_locker", "metal_rack", "crate",
                          "shelf"]),
    # The armoury proper: racks and lockers, no desks. A separate room from
    # the gun store, which is where the ammunition and the spares live. Both
    # names are the game's own - armory is in 2 of its buildings and
    # policegunstorage in 15 - so both are looted.
    "armory": (C.FLOOR_LINO, "Armory",
               ["gun_locker", "gun_locker", "metal_rack", "gun_locker",
                "crate", "corkboard"]),
    # Knox County calls this lockerroom in 99 buildings and policelocker in
    # 27; both are real, and a station has both a changing room and its own.
    "lockerroom": (C.FLOOR_LINO, "Locker Room",
                   ["wardrobe", "wardrobe", "wardrobe_pale", "chair", "shelf",
                    "mirror"]),
    "evidenceroom": (C.FLOOR_LINO, "Evidence Room",
                     ["metal_rack", "shelf", "crate", "filing_cabinet",
                      "corkboard"]),
    "policearchive": (C.FLOOR_LINO, "Police Archive",
                      ["filing_cabinet", "filing_cabinet", "shelf", "desk", "office_chair"]),
    "interrogationroom": (C.FLOOR_LINO, "Interrogation Room",
                          ["table", "chair", "chair", "mirror"]),
    # Knox County has 540 prisoncells and no "cells" at all - the name is
    # what the loot tables key off, so ours filled with nothing.
    "prisoncells": (C.FLOOR_LINO, "Cells", ["bed", "toilet", "sink"]),
    # A fire station: the appliance bay, the gear and the crew's quarters.
    "firegarage": (C.FLOOR_LINO, "Fire Garage",
                   ["metal_rack", "crate", "counter", "shelf"]),
    "firestorage": (C.FLOOR_LINO, "Fire Storage",
                    ["wardrobe", "metal_rack", "shelf", "crate"]),
    "daycare": (C.FLOOR_CARPET_BLUE, "Daycare",
                ["table", "chair", "chair", "bookshelf", "shag_rug", "plant"]),
    "mechanic": (C.FLOOR_LINO, "Mechanic", ["metal_rack", "crate", "counter", "metal_rack"]),
    "motelroom": (C.FLOOR_CARPET_BLUE, "Hotel Room",
                  ["double_bed", "sidetable", "tv", "armchair", "dresser", "lamp", "painting"]),
    "bakery": (C.FLOOR_TILE_PALE, "Bakery", ["shop_display_bakery", "shop_counter", "shop_shelf"]),
    **{k: (floor, label, ["shop_shelf", "shop_counter", "shop_shelf_wood"])
       for k, floor, label in (
           ("gasstore", C.FLOOR_TILE_PALE, "Gas Station Store"),
           ("giftstore", C.FLOOR_WOOD, "Gift Store"), ("toystore", C.FLOOR_CARPET_BLUE, "Toy Store"),
           ("candystore", C.FLOOR_TILE_CHECK, "Candy Store"), ("butcher", C.FLOOR_TILE_PALE, "Butcher"),
           ("departmentstore", C.FLOOR_TILE_PALE, "Department Store"),
           ("jewelrystore", C.FLOOR_CARPET_RED, "Jewelry Store"),
           ("camerastore", C.FLOOR_TILE_PALE, "Camera Store"),
           ("musicstore", C.FLOOR_WOOD, "Music Store"), ("movierental", C.FLOOR_CARPET_BLUE, "Video Store"),
           ("gunstore", C.FLOOR_LINO, "Gun Store"), ("sportstore", C.FLOOR_WOOD, "Sports Store"),
           ("gardenstore", C.FLOOR_LINO, "Farm and Garden Store"),
           ("armysurplus", C.FLOOR_LINO, "Army Surplus"),
           ("hunting", C.FLOOR_LINO, "Hunting and Outdoor Store"),
           ("artstore", C.FLOOR_WOOD, "Art Supply Store"),
           ("petstore", C.FLOOR_TILE_PALE, "Pet Store"),
           ("furniturestore", C.FLOOR_CARPET_RED, "Furniture Store"))},
    "armystorage": (C.FLOOR_LINO, "Army Storage",
                    ["metal_rack", "crate", "metal_rack", "crate", "filing_cabinet", "shelf"]),
    "breakroom": (C.FLOOR_LINO, "Break Room",
                  ["fridge", "counter", "counter", "sink", "vending", "water_cooler",
                   "plant"]),
    "office": (C.FLOOR_WOOD, "Office",
               ["table", "chair", "bookshelf", "painting", "plant"]),
    # Rooms only special buildings use. Every name is in RoomNames.txt, so loot
    # tables recognise them.
    # Desks, not a table and two chairs. Knox County's classrooms are 2.97
    # location_community_school_01_32-35 is the commonest thing in a vanilla
    # classroom and stands against a wall in 93-95% of sightings, which is
    # why it was taken for a desk and called school_desk. It is a wall clock.
    # Adding it put 765 of them in one school and is what "too many clocks"
    # was. Whatever the classroom desk is in that tileset, it is not those
    # four; until it is identified a classroom is tables and chairs.
    # No corkboard either: Knox County's school rooms carry none at all -
    # location_business_office_generic_01_7/15 appears zero times in 13,243
    # tiles of them - where ours had 0.24 per 10 m2.
    "classroom": (C.FLOOR_TILE_PALE, "Classroom",
                  ["whiteboard", "table", "chair", "chair", "desk", "table", "chair",
                   "bookshelf", "chair", "shelf"]),
    "library": (C.FLOOR_WOOD, "Library",
                ["bookshelf", "bookshelf", "table", "chair"]),
    "gym": (C.FLOOR_WOOD, "Gym", ["shelf", "crate", "painting"]),
    "lobby": (C.FLOOR_TILE_CHECK, "Lobby",
              ["sofa", "armchair", "sidetable", "plant", "painting"]),
    "church": (C.FLOOR_WOOD, "Church",
               ["chair", "chair", "table", "painting", "plant"]),
    "restaurant": (C.FLOOR_TILE_CHECK, "Restaurant",
                   ["table", "chair", "chair", "counter", "plant"]),
    "bar": (C.FLOOR_WOOD, "Bar", ["shelf", "painting", "plant"]),
    "clinic": (C.FLOOR_TILE_PALE, "Clinic",
               ["bed", "sink", "shelf", "counter", "chair"]),
    "medical": (C.FLOOR_TILE_PALE, "Medical",
                ["counter", "shelf", "sink", "bed", "chair"]),
    "warehouse": (C.FLOOR_LINO, "Warehouse",
                  ["crate", "crate", "shelf", "shelf", "crate"]),
    "garage": (C.FLOOR_LINO, "Garage", ["crate", "shelf", "counter"]),
    # Nothing goes in a lift car; the door is hung separately (see _furnish).
    "elevator": (C.FLOOR_LINO, "Elevator", []),
    # The game's own shed room: its loot is carpentry, farming and metalwork
    # tools, where "garage" would stock a garden shed with car parts.
    "shed": (C.FLOOR_WOOD, "Shed", ["counter", "shelf", "crate"]),
}

# Room mixes per building flavour. Order matters: the biggest room gets the
# first kind and so on down. Every name here appears in the game's own
# Distributions.lua, so loot actually spawns in them.
RESIDENTIAL = ["livingroom", "kitchen", "bedroom", "bedroom", "dining",
               "bathroom", "hall"]
COMMERCIAL = ["storage", "office", "storage", "kitchen", "bathroom", "hall"]

# Once the mix above is spent, big buildings cycle through these instead of
# repeating the last entry - otherwise a 26x27 shop comes out as nine halls,
# and halls carry almost no loot.
# Houses do not read these: _assign_house_kinds places their rooms by what
# each one sits next to. They are kept because the selftest checks every name
# we can emit is one the game knows.
RESIDENTIAL_FILL = ["closet", "bedroom", "storage", "bedroom",
                    "livingroom", "laundry", "bathroom", "office"]
COMMERCIAL_FILL = ["storage", "office", "storage", "bathroom"]

# Room plans for buildings OSM identifies as something specific. A school full
# of bedrooms reads as wrong immediately; these keep the interior in character,
# and the room names drive what loot spawns there.
SPECIAL_MIXES = {
    # The canteen is a kitchen serving a dining hall, which is what a school
    # is missing without it. schoollab, schoolstorage, sportstorage and
    # janitor are the game's own school rooms.
    # Mostly classrooms. Enlarging the rooms instead dropped them from 6 a
    # floor to 3 and filled the space with offices, because the mix covers
    # more of a floor when there are fewer rooms on it.
    "school":     (["lobby", "classroom", "classroom", "diningroom",
                    "classroom", "gym", "kitchen",
                    "library", "office", "classroom", "schoollab",
                    "bathroom", "schoolstorage", "sportstorage"],
                   ["classroom", "classroom", "classroom", "schoolstorage",
                    "classroom", "office", "janitor", "bathroom"]),
    "church":     (["church", "lobby", "office", "storage", "bathroom"],
                   ["church", "church", "church", "storage"]),
    "restaurant": (["restaurant", "kitchen", "bar", "storage", "bathroom",
                    "office"],
                   ["restaurant", "storage"]),
    "shop":       (["storage", "office", "storage", "bathroom", "lobby"],
                   ["storage", "office"]),
    # The shops under a block of flats: the game's own shop rooms, with a
    # stockroom behind.
    "retail":     (["generalstore", "conveniencestore", "clothingstore", "cafe",
                    "storage"],
                   ["generalstore", "cafe", "storage"]),
    "industrial": (["warehouse", "warehouse", "office", "storage", "bathroom",
                    "garage"],
                   ["warehouse", "storage"]),
    "barn":       (["warehouse", "storage", "garage"], ["warehouse", "storage"]),
    "garage":     (["garage"], ["garage"]),
    # A base's buildings: army stores (the game's army loot), offices,
    # dormitory rooms, a mess kitchen.
    "military":   (["armystorage", "office", "bedroom", "armystorage",
                    "bathroom", "kitchen", "bedroom"],
                   ["bedroom", "bedroom", "armystorage", "storage", "office"]),
    # Basements (knoxbuild/basements.py), from the rooms the game already
    # furnishes: a house's cellar is laundry, storage, a workshop and a rec
    # room; a base's bunker is stores, bunks and offices.
    "basement_house":      (["laundry", "storage", "garage", "livingroom"],
                            ["storage", "livingroom"]),
    # ...and the other things a house's cellar is (basements.HOUSE_BASEMENTS):
    # a finished rec room, a workshop, a family's shelter, a plain store.
    "basement_house_rec":      (["livingroom", "bathroom", "laundry", "storage"],
                                ["livingroom", "storage"]),
    "basement_house_workshop": (["garage", "storage", "laundry", "storage"],
                                ["garage", "storage"]),
    "basement_house_shelter":  (["storage", "bedroom", "kitchen", "storage", "bathroom"],
                                ["storage", "bedroom"]),
    "basement_house_cellar":   (["storage", "storage", "laundry"], ["storage"]),
    # A block of flats keeps its shared laundry and the tenants' store rooms
    # downstairs.
    "basement_apartment":  (["laundry", "storage", "storage"], ["storage"]),
    "basement_school":     (["janitor", "storage"], ["storage"]),
    "basement_medical":    (["storage", "janitor"], ["storage"]),
    "basement_police":     (["prisoncells", "policestorage"], ["prisoncells", "storage"]),
    "basement_mall":       (["storage", "office"], ["storage"]),
    "basement_civic":      (["storage", "office"], ["storage"]),
    "basement_industrial": (["storage", "warehouse"], ["warehouse", "storage"]),
    "basement_church":     (["storage", "kitchen"], ["storage"]),
    "basement_military":   (["armystorage", "bedroom", "office", "storage", "kitchen",
                             "bathroom"],
                            ["armystorage", "bedroom", "storage", "office"]),
    "shed":       (["shed"], ["shed"]),
    # A shopping centre, measured off Muldraugh 54_22: a third of the floor
    # is concourse, and the rest is units of 150-400 tiles - clothes,
    # department, furniture, gift, toy, book and sports shops - with a food
    # court, lavatories, a janitor's and the centre office behind. Every one
    # of these is a room interiors.py can fit out as a shop.
    # No "hall" in either list: the concourse is cut before the units
    # (_mall_rooms) and dealing more halls on top of it took the mall to 53%
    # circulation against the game's 33.6%.
    "mall":       (["foodcourt", "clothesstore", "departmentstore",
                    "sportstore", "bookstore", "pizzakitchen",
                    "giftstore", "toystore", "shoestore", "electronicsstore",
                    "furniturestore", "bathroom", "jewelrystore",
                    "housewarestore", "chinesekitchen", "gunstore",
                    "clothesstorage", "office", "toolstore", "musicstore",
                    "pharmacy", "candystore", "bakery", "icecreamkitchen",
                    "sewingstore", "optometrist", "janitor", "cornerstore",
                    "gardenstore", "armysurplus", "hunting", "artstore",
                    "petstore", "camerastore",
                    "departmentstorage", "security", "storage", "breakroom"],
                   ["clothesstore", "giftstore", "clothesstorage",
                    "toystore", "bookstore", "shoestore", "sportstore",
                    "housewarestore", "storage", "electronicsstore",
                    "jewelrystore", "musicstore", "candystore"]),
    # A castle is a great hall with a chapel, a kitchen that fed everybody and
    # the rooms people slept in, and today a ticket desk and a gift counter by
    # the door. Every name here is one the game furnishes; "throne room" would
    # look right and spawn nothing, the loot tables keying off the name.
    "castle":     (["hall", "church", "kitchen", "storage", "bedroom",
                    "library", "office", "bathroom", "generalstore"],
                   ["hall", "bedroom", "storage", "hall"]),
    # A ground: the concourse under the stand, the changing rooms and showers
    # off it, the kit store, a first aid room and the club offices. The food
    # is a counter on the concourse, which is what cafe is.
    # lockerroom is not in the fill: it is one of the kinds _split_to_size
    # cuts down to size, so every one the fill handed out became a row of
    # eight and a big ground came out 57% changing rooms. Twice in the mix is
    # the home side and the away side, and that is where they stay.
    "stadium":    (["hall", "lockerroom", "bathroom", "sportstorage", "cafe",
                    "office", "clinic", "gym", "storage", "hall"],
                   ["hall", "cafe", "storage", "office", "sportstorage"]),
    "medical":    (["clinic", "medical", "lobby", "office", "bathroom",
                    "storage"],
                   ["clinic", "medical", "clinic", "office", "storage"]),
    # Offices, a few at a time: a town hall's storerooms are a closet or two
    # off a corridor, not a quarter of the floor.
    "civic":      (["office", "lobby", "office", "storage", "bathroom",
                    "library"],
                   ["office", "office", "office", "storage"]),
    # A police station was "civic" - offices and a storeroom - so the one
    # thing players go to a police station for was not in it. These are the
    # game's own police rooms, which is what puts the uniforms, the evidence
    # and the guns behind the counter.
    # Knox County's police rooms by how many there are: prisoncells 540,
    # policeoffice 220, policelocker 27, policegunstorage 15. policestorage
    # has two in the whole county, so leaning on it filled a station with a
    # room the game has no loot for.
    # A police station, not a jail. Knox County's buildings that hold a
    # policeoffice are 31% cells because most of them are the county jail with
    # a station attached; a town station is a front desk, offices, an
    # interrogation room, somewhere to change, the armoury and a few cells at
    # the back. prisoncells is capped hard in ROOM_CAP_PER so "a few" stays a
    # few. Every name here is one the game furnishes: reception and
    # holdingcell are not, so the lobby and the cells carry their real names.
    "police":     (["lobby", "policeoffice", "hall", "interrogationroom",
                    "lockerroom", "policegunstorage", "armory", "prisoncells",
                    "evidenceroom", "bathroom", "security", "breakroom",
                    "policelocker", "policearchive"],
                   ["policeoffice", "hall", "policeoffice", "officestorage",
                    "prisoncells", "policeoffice", "janitor", "bathroom",
                    "policeoutfitstorage"]),
    # A library is its reading rooms, not an office block with one in it.
    "library":    (["library", "library", "lobby", "office", "bathroom",
                    "storage", "library"],
                   ["library", "library", "library", "storage", "office"]),
    # A fire station: the appliance bay, the gear store and the crew's rooms.
    "fire":       (["firegarage", "firestorage", "office", "bedroom",
                    "kitchen", "bathroom", "firestorage"],
                   ["bedroom", "office", "storage"]),
    # The floors above a shop: offices, as in any high street.
    "offices":    (["office", "office", "breakroom", "bathroom", "storage", "office"],
                   ["office", "office", "storage"]),
    # A block of flats is not one big house: it is several small dwellings off
    # a shared landing, so the mix repeats a compact bedroom/living/kitchen set
    # rather than laying out one household across the whole floor.
    "apartment":  (["hall", "livingroom", "kitchen", "bedroom", "bathroom",
                    "livingroom", "bedroom", "kitchen", "bathroom", "storage"],
                   ["bedroom", "livingroom", "kitchen", "bathroom"]),
}


# A bathroom in Knox County is 6.5 m2. Ours were 13.7 - a bathroom the size of
# a bedroom - because a floor is cut to one target area and the bathroom then
# takes the smallest of the ordinary rooms, there being no small one. One
# region per house floor gives up a corner to a bathroom-sized room first.
# MIN_ROOM is 3, so 9 to 12 tiles is as near the game's as squares allow.
SMALL_ROOM_RUN = (MIN_ROOM, MIN_ROOM + 1)
# The bottom of that band, and so the smallest household bathroom that is
# fitted out with a bath rather than a shower (_bathroom_wishlist).
BATHROOM_TILES = MIN_ROOM * MIN_ROOM


def _inside(x0: int, y0: int, x1: int, y1: int,
            mask: list[list[bool]] | None) -> int:
    """Tiles of a rectangle that are really inside the building.

    On a footprint turned 38 degrees half of every bounding rectangle is empty
    corner, and sizing rooms by the rectangle kept splitting until a house had
    fifteen rooms a floor, most of them offices and storerooms.
    """
    if mask is None:
        return (x1 - x0 + 1) * (y1 - y0 + 1)
    return sum(1 for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if mask[y][x])


def _split(x0: int, y0: int, x1: int, y1: int, rng: random.Random,
           depth: int, out: list[Room],
           target_area: int = TARGET_ROOM_AREA,
           mask: list[list[bool]] | None = None,
           small: list[bool] | None = None) -> None:
    w, h = x1 - x0 + 1, y1 - y0 + 1
    can_v = w >= MIN_SPLIT
    can_h = h >= MIN_SPLIT
    area = _inside(x0, y0, x1, y1, mask)
    if depth <= 0 or not (can_v or can_h) or area <= target_area:
        out.append(Room(x0, y0, x1, y1))
        return

    # The one small room. A corner taken out of a rectangle leaves an L and
    # the plan is rectangles, so it takes two cuts: a strip the minimum depth
    # off one end, and the room off one end of the strip. What is left of the
    # strip is a closet or a box room, which is what sits beside a bathroom in
    # the game's houses too.
    if small and small[0] and w >= MIN_ROOM * 2 and h >= MIN_ROOM * 2 \
            and area >= target_area * 2:
        wide = w >= h
        length = w if wide else h
        run = rng.randint(SMALL_ROOM_RUN[0],
                          min(SMALL_ROOM_RUN[1], length - MIN_ROOM))
        far_end = rng.random() < 0.5        # which end of the region the strip is
        far_side = rng.random() < 0.5       # which end of the strip the room is
        if wide:
            sy0, sy1 = ((y1 - MIN_ROOM + 1, y1) if far_end else (y0, y0 + MIN_ROOM - 1))
            bx0, bx1 = ((x1 - run + 1, x1) if far_side else (x0, x0 + run - 1))
            room = (bx0, sy0, bx1, sy1)
            strip = ((x0, sy0, bx0 - 1, sy1) if far_side else (bx1 + 1, sy0, x1, sy1))
            rest = (x0, y0, x1, y1 - MIN_ROOM) if far_end else (x0, y0 + MIN_ROOM, x1, y1)
        else:
            sx0, sx1 = ((x1 - MIN_ROOM + 1, x1) if far_end else (x0, x0 + MIN_ROOM - 1))
            by0, by1 = ((y1 - run + 1, y1) if far_side else (y0, y0 + run - 1))
            room = (sx0, by0, sx1, by1)
            strip = ((sx0, y0, sx1, by0 - 1) if far_side else (sx0, by1 + 1, sx1, y1))
            rest = (x0, y0, x1 - MIN_ROOM, y1) if far_end else (x0 + MIN_ROOM, y0, x1, y1)
        # Not where the footprint has cut most of it away: a room of three
        # tiles in the corner of a turned building is not a bathroom.
        if _inside(*room, mask) >= MIN_ROOM * MIN_ROOM - 2:
            small[0] = False
            out.append(Room(*room))
            _split(*strip, rng, depth - 1, out, target_area, mask)
            _split(*rest, rng, depth - 1, out, target_area, mask)
            return
    if not can_h:
        vertical = True
    elif not can_v:
        vertical = False
    else:
        vertical = w > h if w != h else rng.random() < 0.5
    # Where to cut. Anywhere, for a region already near the size of a room -
    # that is what stops every house being a grid. But a region far bigger
    # than a room has to come down towards one on both sides of the cut, and
    # a random cut kept shaving a sliver off a floor the size of a factory
    # until it ran out of depth and left a room of two thousand tiles.
    lo = (x0 if vertical else y0) + MIN_ROOM
    hi = (x1 if vertical else y1) - MIN_ROOM
    if area > target_area * 2.5:
        mid = ((x0 + x1) if vertical else (y0 + y1)) // 2
        reach = max(1, ((x1 - x0) if vertical else (y1 - y0)) // 6)
        lo, hi = max(lo, mid - reach), min(hi, mid + reach)
        if lo > hi:
            lo = hi = min(max(mid, (x0 if vertical else y0) + MIN_ROOM),
                          (x1 if vertical else y1) - MIN_ROOM)
    if vertical:
        cut = rng.randint(lo, hi)
        _split(x0, y0, cut - 1, y1, rng, depth - 1, out, target_area, mask)
        _split(cut, y0, x1, y1, rng, depth - 1, out, target_area, mask)
    else:
        cut = rng.randint(lo, hi)
        _split(x0, y0, x1, cut - 1, rng, depth - 1, out, target_area, mask)
        _split(x0, cut, x1, y1, rng, depth - 1, out, target_area, mask)


def _subtract(box: tuple, others: list[tuple]) -> list[tuple]:
    """`box` minus every rectangle in `others`, as non-overlapping rects.

    Guillotine cuts: the part of `box` left after each rectangle in `others`
    is taken out of it is up to four smaller rectangles, which is exactly the
    kind of thing the rest of this module can work with.
    """
    pieces = [box]
    for ox0, oy0, ox1, oy1 in others:
        nxt = []
        for x0, y0, x1, y1 in pieces:
            if ox1 < x0 or x1 < ox0 or oy1 < y0 or y1 < oy0:
                nxt.append((x0, y0, x1, y1))
                continue
            if x0 < ox0:
                nxt.append((x0, y0, ox0 - 1, y1))
            if ox1 < x1:
                nxt.append((ox1 + 1, y0, x1, y1))
            mx0, mx1 = max(x0, ox0), min(x1, ox1)
            if y0 < oy0:
                nxt.append((mx0, y0, mx1, oy0 - 1))
            if oy1 < y1:
                nxt.append((mx0, oy1 + 1, mx1, y1))
        pieces = nxt
        if not pieces:
            break
    return pieces


def _intersect(box: tuple, others: list[tuple]) -> list[tuple]:
    """The parts of `box` lying in `others`: one rect per rectangle it meets."""
    x0, y0, x1, y1 = box
    out = []
    for ox0, oy0, ox1, oy1 in others:
        ix0, iy0 = max(x0, ox0), max(y0, oy0)
        ix1, iy1 = min(x1, ox1), min(y1, oy1)
        if ix0 <= ix1 and iy0 <= iy1:
            out.append((ix0, iy0, ix1, iy1))
    return out


def _mapped_rooms(plan: Plan, rng: random.Random,
                  mapped: list[tuple[list[tuple[int, int]], str | None]],
                  target_area: int, mask: list[list[bool]] | None,
                  small: list[bool] | None) -> None:
    """Rooms where the mapper drew them, the rest of the floor cut as usual.

    `mapped` is [(ring, kind)] in this storey's tiles: the indoor=room ways
    from OpenStreetMap, attached to their building (renderer._buildings_geojson)
    and carried with the footprint (knoxbuild.build). A building whose rooms
    are surveyed has a plan worth keeping - a school's classrooms along its
    corridor, an office's rooms round its core - and cutting it with the
    ordinary BSP ignored all of it and guessed.

    The plan is rectangles, so each room arrives as its bounding box, biggest
    first; one landing on rooms already placed keeps only the part of itself
    that is still free, and whatever floor is left over is cut by _split just
    as it would have been - the storey still tiles whole. A ring carrying a
    room tag the game knows becomes a fixed room of that kind; the rest keep
    their geometry and are assigned kinds after painting, as every other room
    is.
    """
    w, h = plan.width, plan.height
    boxes = []
    for pts, kind in mapped:
        if len(pts) < 3:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bx0, bx1 = max(0, min(xs)), min(w - 1, max(xs))
        by0, by1 = max(0, min(ys)), min(h - 1, max(ys))
        if bx1 - bx0 + 1 < MIN_ROOM or by1 - by0 + 1 < MIN_ROOM:
            continue            # too small to stand in, once on our grid
        if _inside(bx0, by0, bx1, by1, mask) < MIN_ROOM * MIN_ROOM:
            continue            # almost all of it outside the real footprint
        boxes.append((kind, bx0, by0, bx1, by1))
    # Biggest first: a small room's box fits into what the big ones leave far
    # more often than the other way round.
    boxes.sort(key=lambda b: -((b[3] - b[1] + 1) * (b[4] - b[2] + 1)))
    free = [(0, 0, w - 1, h - 1)]
    for kind, bx0, by0, bx1, by1 in boxes:
        # What of this box is still floor no mapped room has taken.
        pieces = _intersect((bx0, by0, bx1, by1), free)
        if not pieces:
            continue
        best = max(pieces, key=lambda r: (r[2] - r[0] + 1) * (r[3] - r[1] + 1))
        bw, bh = best[2] - best[0] + 1, best[3] - best[1] + 1
        if bw < MIN_ROOM or bh < MIN_ROOM or bw * bh < MIN_ROOM * MIN_ROOM:
            continue
        plan.rooms.append(Room(*best, kind=kind or "hall", fixed=bool(kind)))
        next_free = []
        for frag in free:
            next_free.extend(_subtract(frag, [best]))
        free = next_free
        if not free:
            return
    for rect in free:
        _split(*rect, rng, MAX_DEPTH, plan.rooms, target_area=target_area,
               mask=mask, small=small)
# Rooms a mansion dresses past its wishlist: the pictures, rugs, bookcases and
# lamps a house with money has in every room. Roles, mapped by the palette and
# the game's own art like any other.
# Paintings are wall furniture: they hang over a wall square and take no floor,
# so a gallery of them costs a mansion's rooms nothing. Shelves are the
# opposite, and a study is the one room that wants them wall to wall.
MANSION_EXTRA = {
    "livingroom": ["piano", "painting", "painting", "plant", "bookshelf",
                   "shag_rug", "armchair", "lamp", "clock"],
    "hall": ["painting", "painting", "painting", "plant", "mirror_small",
             "sidetable", "bookshelf"],
    "dining": ["painting", "painting", "plant", "lamp", "rug_wide", "clock",
               "bookshelf"],
    "office": ["erika_shelves_2", "erika_shelves_6", "bookshelf", "bookshelf",
               "painting", "plant", "clock"],
    "bedroom": ["painting", "painting", "plant", "lamp", "mirror", "bookshelf",
                "rug_small"],
    "bathroom": ["plant", "mirror_small", "rug_small"],
}
# Nor is a cut kept where a room it keeps is more than this many times the
# biggest its kind comes.
HOUSE_OVERSIZE = 2.0
RETAIL_ROOMS = {"generalstore", "conveniencestore", "clothingstore", "cafe", "grocery",
                "liquorstore", "pharmacy", "bookstore", "toolstore"}


STAIR_RUN = 5      # tiles a staircase occupies, from Stairs::bounds
