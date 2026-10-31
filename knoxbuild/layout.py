"""Turn a footprint rectangle into a furnished floor plan.

Wall model, which the rest of the package depends on: BuildingEd stores walls on
the north and west *edges* of tiles, which is why its per-floor tile grids are
(width+1) x (height+1). So for a building w tiles wide and h tall:

    north exterior wall   y = 0,  dir N,  x in 0..w-1
    west  exterior wall   x = 0,  dir W,  y in 0..h-1
    south exterior wall   y = h,  dir N
    east  exterior wall   x = w,  dir W

Interior walls appear automatically wherever two adjacent tiles hold different
room indices, so we only ever paint rooms - we never emit wall objects.
"""
from __future__ import annotations

import heapq
import random
from collections import deque
from dataclasses import dataclass, field

from . import catalog as C
from . import furnish_rules as FR
from .uses import FRONT_ROOMS
from .settings import Settings
from .sizing import (SIZES, capacity, min_area, programme_for_flat,
                     programme_for_house_floor, split_by_targets)

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
    # Ground-floor windows that are a shop front, glazed with big panels.
    shop_front: set = field(default_factory=set)
    # What the building is (build_plan's kind), for rooms furnished by it: an
    # office in a house is a study, in an office block it is desks.
    kind: str | None = None
    # Outside wall edges this storey shares with the building next door:
    # no window, shop front or door goes in them.
    party: set = field(default_factory=set)
    profile: object | None = None


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
    "bakery": (C.FLOOR_TILE_PALE, "Bakery", ["shop_display", "shop_counter", "shop_shelf"]),
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
           ("gardenstore", C.FLOOR_LINO, "Garden Store"),
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


# What a flat contains, by how many rooms it got. The first entry goes to the
# room the front door opens into; the rest are handed out biggest-first, so the
# bathroom lands on the smallest room.
#
# Size matters: a two-room flat is a bedsit and wants a bathroom more than it
# wants a separate bedroom.
FLAT_PLANS = {
    # A one-room flat is a bedsit: somewhere to sleep, not a sofa and nothing.
    1: ["bedroom"],
    2: ["kitchen", "bathroom"],
    3: ["kitchen", "bedroom", "bathroom"],
    4: ["livingroom", "kitchen", "bedroom", "bathroom"],
    # From five rooms up the flat gets a little hall to open them off. Knox
    # County has 0.12 halls to a flat and two thirds of its floors of flats
    # have none at all - because its flats are small. Ours run to five, six
    # and eight rooms once they trade with the neighbour, and at that size a
    # third of the rooms were two doors deep and some were three or four: a
    # bedroom through a bathroom through a kitchen. Only the big ones get it,
    # which comes to about 0.09 halls a flat.
    5: ["hall", "livingroom", "kitchen", "bedroom", "bathroom"],
}
# From this many rooms up, a flat is entered through a hall.
FLAT_HALL_FROM = 5
# Not every flat is a set of small rectangles. Knox County gives only 0.56
# kitchens to a flat: the rest have no kitchen room at all, just a living room
# with the cooker and the fridge along one wall. The game draws a wall between
# any two rooms, so open plan is not a wall we leave out - it is one room that
# is both, which is what "openplan" is. It reaches the game as a livingroom,
# because the name is what the loot tables key off.
FLAT_PLANS_OPEN = {
    1: ["openplan"],
    2: ["openplan", "bathroom"],
    3: ["openplan", "bedroom", "bathroom"],
    4: ["openplan", "bedroom", "bedroom", "bathroom"],
    5: ["hall", "openplan", "bedroom", "bedroom", "bathroom"],
}
OPEN_PLAN_SHARE = 0.44
# Our room kinds are written out as the game's room names. Where the two
# differ, this maps ours to one the game furnishes and loots.
ROOM_NAME = {
    "openplan": "livingroom",
    # The mall concourse. The game knows it as a hall and the loot tables key
    # off that, so that is the name it is written under; it is a kind of its
    # own here only so it can be furnished as a concourse - planters, bins,
    # vending, the odd kiosk - instead of as the bare corridor a hall is.
    "concourse": "hall",
    # Knox County has 694 rooms called diningroom and 11 called dining. Ours
    # called every house's one "dining", which is a name the loot tables do
    # not know - the same mistake as "cells" for "prisoncells". The kind stays
    # separate from the canteen kind, which is furnished quite differently.
    "dining": "diningroom",
}
FLAT_EXTRA = ["bedroom", "storage"]
# Floor area, in tiles, from which a flat is cut into at least three rooms.
FLAT_MIN_SPLIT_AREA = 30
# Tiles of corridor wall each flat gets. Narrower slices gave two- and
# three-room flats, and with the bathroom going to the smallest room, a flat
# of two big rooms had a bathroom the size of its living room.
# This is the fallback: _flat_frontage works it out from how deep the
# floorplate is, because one fixed frontage cannot suit every building. At 8
# to 11 tiles a deep plate gave 117 m2 flats of six rooms; at 5 to 7 a shallow
# one gave 40 m2 flats that could not hold three.
FLAT_FRONTAGE = (5, 7)
# What a flat should come out at. Knox County's are 57 m2; a little over gives
# room for the separate kitchen ours each need.
FLAT_TARGET_AREA = 62


def _flat_frontage(depth: int) -> tuple[int, int]:
    """How wide to slice flats off a corridor a given depth of floor deep.

    A flat wants about FLAT_TARGET_AREA of floor however deep the building is,
    so the frontage falls as the plate gets deeper. The lower bound is what
    three rooms can physically be cut from: below MIN_SPLIT * MIN_ROOM a room
    cannot be halved again, so a narrow flat comes out as two rooms whatever
    the plan asks for.
    """
    want = max(MIN_ROOM + 1, round(FLAT_TARGET_AREA / max(1, depth)))
    least = max(MIN_ROOM + 1, (MIN_SPLIT * MIN_ROOM * 2) // max(1, depth))
    low = max(want, least)
    return (low, low + 2)
# What a flat is. Knox County's blocks hold, per block, 13.8 bathrooms, 13.7
# living rooms, 10.6 bedrooms, 7.7 kitchens and 4.8 closets. Counting one
# bathroom to a flat - the surest marker, being the commonest room - that is
# about 3.8 rooms to a flat. Ours were 6 rooms in 117 m2: two flats' worth of
# floor cut into two flats' worth of rooms and called one home, which is why a
# floor read as a grid of cells rather than as somewhere people live.
#
# The game gives only 0.56 kitchens to a flat, the rest being a kitchenette in
# the living room. Ours gives every flat one, because a flat with no kitchen
# room spawns no food: the room name is what the loot tables key off.
FLAT_ROOMS = 4
# An open-plan flat is cut into fewer: the living end is one room that is
# also the kitchen, so it has to stay big enough to hold a sofa facing a
# television. At FLAT_ROOMS the open room came out at 16 m2.
FLAT_ROOMS_OPEN = 2
# A floorplate deeper than this gets two ranks of flats back to back, the way
# a real block does, rather than one flat running the whole depth of it.
FLAT_MAX_DEPTH = 11
# A hotel room is narrower than a flat: a room and its bathroom.
HOTEL_FRONTAGE = (4, 6)


def _slices(length: int, rng: random.Random,
            lo: int, hi: int) -> list[tuple[int, int]]:
    """Cut 0..length-1 into runs close to lo..hi, sized evenly.

    Taking random lengths from one end and giving the last slice whatever was
    left made the final flat on each side up to twice the size of the others -
    a 26-tile corridor came out as flats of 7 and 19. Deciding how many flats
    fit first and then sharing the length out keeps them comparable, with a
    tile of jitter so a row of flats is not perfectly regular.
    """
    count = max(1, round(length / ((lo + hi) / 2)))
    widths = [length // count] * count
    for i in range(length - sum(widths)):
        widths[i] += 1
    for i in range(count - 1):
        shift = rng.choice((-1, 0, 1))
        if widths[i] + shift >= lo and widths[i + 1] - shift >= lo:
            widths[i] += shift
            widths[i + 1] -= shift
    out, a = [], 0
    for wdt in widths:
        out.append((a, a + wdt - 1))
        a += wdt
    return out


def _corridor_axis(plan: Plan) -> str | None:
    """"y" or "x" for the direction a corridor runs, None without one."""
    if plan.core is None or not plan.corridor:
        return None
    x0, y0, x1, y1 = plan.core
    return "y" if (y1 - y0) >= (x1 - x0) else "x"


def _flat_by_kind(box: tuple[int, int, int, int], rng: random.Random,
                  open_plan: bool, mask: list[list[bool]] | None,
                  edge: str) -> list[Room] | None:
    """A flat's rooms cut to its programme's sizes, the living room on `edge`.

    Kinds are set and fixed here, so a bathroom is cut bathroom-sized rather
    than named after whichever piece came out smallest. A programme no cut
    can carve (four rooms in a strip five tiles deep) steps down to the next
    smaller one. None when none fits: the caller falls back.
    """
    x0, y0, x1, y1 = box
    area = (sum(mask[y][x] for y in range(y0, y1 + 1) for x in range(x0, x1 + 1))
            if mask is not None else (x1 - x0 + 1) * (y1 - y0 + 1))
    while kinds := programme_for_flat(area, rng, open_plan):
        # The front door opens into the living room, so it goes first.
        if kinds[0] == "hall":
            kinds = kinds[1:2] + kinds[:1] + kinds[2:]
        rooms = split_by_targets(box, kinds, rng, mask, edge)
        # Cut to the footprint, only one flat in seven on an irregular or
        # turned one found a cut at all. Failing that, the whole box is cut
        # and _paint clips it - kept only where every room keeps a piece of
        # its kind's least floor inside the walls that _mend_fragments will
        # not fold away as a sliver, or the bathroom is the first to go.
        if not rooms and mask is not None:
            rooms = split_by_targets(box, kinds, rng, None, edge)
            if rooms and any(
                    len(p) < SIZES[r.kind].lo or _too_small(p)
                    for r in rooms for p in [_kept_piece(r, mask)]):
                rooms = None
        if rooms:
            return rooms
        area = min_area(kinds) - 1
    return None


def _apartment_rooms(plan: Plan, rng: random.Random, target: int,
                     frontage: tuple[int, int] = FLAT_FRONTAGE) -> None:
    """Lay a floor out as flats either side of a corridor.

    The order is what matters. Splitting the whole floor into rooms, grouping
    those into flats and then painting a corridor over the top - the first
    attempt at this - left most flats not touching the corridor at all, and cut
    rooms in half where the corridor ran through them. 191 of 200 blocks came
    out with a room nobody could get into.

    Here the corridor exists first. Each side of it is sliced into flats that
    run from the corridor wall to the outside wall, so every flat has a front
    door onto the corridor and a window onto the street by construction, and
    only then is each flat divided into its own rooms.
    """
    axis = _corridor_axis(plan)
    if axis is None:
        # No corridor fits (an irregular footprint, usually). One flat per
        # floor is a real kind of building, so lay it out as that.
        _split(0, 0, plan.width - 1, plan.height - 1, rng, MAX_DEPTH,
               plan.rooms, target_area=target, mask=plan.mask)
        for room in plan.rooms:
            room.unit = 1
        return

    cx0, cy0, cx1, cy1 = plan.core
    unit = 0
    if axis == "y":
        sides = [(0, cx0 - 1), (cx1 + 1, plan.width - 1)]
        length = plan.height
    else:
        sides = [(0, cy0 - 1), (cy1 + 1, plan.height - 1)]
        length = plan.width
    # The side of each flat's box that faces the corridor.
    edges = ("E", "W") if axis == "y" else ("S", "N")
    for (a0, a1), edge in zip(sides, edges):
        if a1 - a0 + 1 < MIN_ROOM:
            continue
        # Each side sliced independently, so the flats do not line up across
        # the corridor like a spreadsheet.
        # A floorplate deeper than one flat gets two ranks back to back, the
        # way a real block does, rather than one flat running the whole depth.
        depth = a1 - a0 + 1
        if frontage == FLAT_FRONTAGE and depth > FLAT_MAX_DEPTH + MIN_ROOM:
            ranks = [(a0, a0 + depth // 2 - 1), (a0 + depth // 2, a1)]
        else:
            ranks = [(a0, a1)]
        for b0, b1 in ranks:
            cut = (_flat_frontage(b1 - b0 + 1)
                   if frontage == FLAT_FRONTAGE else frontage)
            for s0, s1 in _slices(length, rng, *cut):
                unit += 1
                box = (b0, s0, b1, s1) if axis == "y" else (s0, b0, s1, b1)
                area = (box[2] - box[0] + 1) * (box[3] - box[1] + 1)
                flat: list[Room] = []
                # A flat is cut towards FLAT_ROOMS rooms, not towards the
                # building's own room size: at that size a 117 m2 flat came
                # out as six rooms, where the game's 57 m2 flat has three.
                # An open-plan flat is cut towards fewer, so the living end
                # stays one big room instead of two small ones.
                open_plan = (frontage == FLAT_FRONTAGE
                             and rng.random() < OPEN_PLAN_SHARE)
                if open_plan:
                    plan.open_units.add(unit)
                rooms_wanted = FLAT_ROOMS_OPEN if open_plan else FLAT_ROOMS
                want = (max(target, area // rooms_wanted)
                        if frontage == FLAT_FRONTAGE else target)
                # A flat is cut by what it holds, sized by kind; a hotel, and
                # a flat no programme fits, is cut as it always was.
                by_kind = (_flat_by_kind(box, rng, open_plan, plan.mask, edge)
                           if frontage == FLAT_FRONTAGE else None)
                if by_kind:
                    flat = by_kind
                else:
                    _split(*box, rng, MAX_DEPTH, flat, target_area=want,
                           mask=plan.mask)
                # A flat that came out as one or two rooms was all living
                # room: in a small block every flat on every floor had nothing
                # else, not a bed or a bathroom in the building. Cut it into a
                # home's rooms when it is big enough for them.
                if (frontage == FLAT_FRONTAGE and not open_plan
                        and not by_kind and len(flat) < 3
                        and area >= FLAT_MIN_SPLIT_AREA):
                    flat = []
                    _split(*box, rng, MAX_DEPTH, flat,
                           target_area=max(MIN_SPLIT * MIN_ROOM, area // 3),
                           mask=plan.mask)
                for room in flat:
                    room.unit = unit
                plan.rooms.extend(flat)

    # Beyond the ends of a corridor that stops short of the building's ends,
    # its own width of floor would otherwise belong to no room at all.
    if axis == "y":
        caps = [(cx0, 0, cx1, cy0 - 1), (cx0, cy1 + 1, cx1, plan.height - 1)]
    else:
        caps = [(0, cy0, cx0 - 1, cy1), (cx1 + 1, cy0, plan.width - 1, cy1)]
    for x0, y0, x1, y1 in caps:
        if x1 < x0 or y1 < y0:
            continue
        unit += 1
        cap: list[Room] = []
        _split(x0, y0, x1, y1, rng, MAX_DEPTH, cap, target_area=target, mask=plan.mask)
        for room in cap:
            room.unit = unit
        plan.rooms.extend(cap)


# How many flats trade a room with the one next door, so the two of them come
# out L-shaped around each other instead of both being boxes. Every flat used
# to be one rectangle sliced off the corridor, which is what made a floor read
# as a spreadsheet however well the rooms inside it were arranged.
FLAT_STAGGER_SHARE = 0.35


def _contiguous(members: list[int], adj: dict[int, dict[int, int]]) -> bool:
    """Whether these rooms all touch each other, directly or through others."""
    if len(members) <= 1:
        return True
    want = set(members)
    seen = {members[0]}
    edge = [members[0]]
    while edge:
        nxt = []
        for i in edge:
            for n in adj.get(i, ()):
                if n in want and n not in seen:
                    seen.add(n)
                    nxt.append(n)
        edge = nxt
    return seen == want


def _stagger_flats(plan: Plan, rng: random.Random) -> None:
    """Hand a room from one flat to the flat next door, where both survive it.

    A flat is cut as a rectangle, so a floor of them is a grid. Giving a
    boundary room to the neighbour leaves both of them L-shaped around each
    other, which is how a real block comes out once the flats are not all the
    same size. A room only moves when what it leaves behind still holds
    together and neither flat is emptied.
    """
    adj = _neighbours(plan)
    units: dict[int, list[int]] = {}
    for i, room in enumerate(plan.rooms, 1):
        if room.unit:
            units.setdefault(room.unit, []).append(i)
    order = sorted(units)
    rng.shuffle(order)
    for unit in order:
        members = units.get(unit, [])
        if len(members) < 3 or rng.random() >= FLAT_STAGGER_SHARE:
            continue
        # The room to give away: one on the flat's edge, touching another flat.
        # A room cut to its kind moves only if it is a bedroom: giving away a
        # living room, kitchen or bathroom would leave its flat without one.
        options = [(i, plan.rooms[n - 1].unit)
                   for i in members
                   if not plan.rooms[i - 1].fixed
                   or plan.rooms[i - 1].kind in ("bedroom", "kidsbedroom")
                   for n in adj.get(i, ())
                   if plan.rooms[n - 1].unit
                   and plan.rooms[n - 1].unit != unit]
        rng.shuffle(options)
        for give, to in options:
            left = [i for i in members if i != give]
            if not _contiguous(left, adj):
                continue
            gained = units.get(to, []) + [give]
            if not _contiguous(gained, adj):
                continue
            # Touching is not enough: the flat has to be able to put a door
            # between them. A room joined across two tiles of wall could not
            # be reached from its new flat's front door, so the door tree
            # fell through to its last resort and joined two flats together
            # or gave one of them a second front door - 175 and 89 of them.
            if max((adj[give].get(n, 0) for n in units.get(to, ())),
                   default=0) < MIN_SPLIT:
                continue
            plan.rooms[give - 1].unit = to
            units[unit] = left
            units[to] = gained
            plan.open_units.discard(unit)
            plan.open_units.discard(to)
            break


def _neighbours(plan: Plan) -> dict[int, dict[int, int]]:
    """Room index -> {neighbour index: length of shared wall in tiles}."""
    adj: dict[int, dict[int, int]] = {i: {} for i in range(1, len(plan.rooms) + 1)}
    for y in range(plan.height):
        for x in range(plan.width):
            a = plan.grid[y][x]
            if not a:
                continue
            for bx, by in ((x + 1, y), (x, y + 1)):
                if bx >= plan.width or by >= plan.height:
                    continue
                b = plan.grid[by][bx]
                if b and b != a:
                    adj[a][b] = adj[a].get(b, 0) + 1
                    adj[b][a] = adj[b].get(a, 0) + 1
    return adj


def _assign_flat_kinds(plan: Plan, hotel: bool = False,
                       reception: bool = False,
                       rng: random.Random | None = None) -> None:
    """Give every flat its own set of rooms, arranged around its front door.

    The room touching the corridor is where you walk in, so it becomes the
    living room; the rest follow by size, with the bathroom on the smallest.
    In a hotel each "flat" is guest rooms with a bathroom.
    """
    rng = rng or random.Random(len(plan.rooms))
    adj = _neighbours(plan)
    corridor = {i for i, r in enumerate(plan.rooms, 1) if r.unit == 0}
    units: dict[int, list[int]] = {}
    for i, room in enumerate(plan.rooms, 1):
        if room.unit == 0:
            room.kind = "hall"
        else:
            units.setdefault(room.unit, []).append(i)
    for u, members in units.items():
        entry = [i for i in members if any(n in corridor for n in adj[i])]
        by_size = sorted(members, key=lambda i: -plan.rooms[i - 1].area)
        # A flat cut by kind (_flat_by_kind) keeps its kinds while its living
        # room still opens off the corridor. One that took in a neighbour's
        # rooms keeps a single living room, kitchen and hall - the one by the
        # door first - and the doubles, like any piece the cut never named,
        # are handed out as extras. A living room cut off from the corridor
        # throws the flat back to being named by size.
        door = [i for i in entry if plan.rooms[i - 1].fixed
                and plan.rooms[i - 1].kind in ("livingroom", "openplan")]
        if door and not hotel:
            keep = max(door, key=lambda i: plan.rooms[i - 1].area)
            taken: set[str] = set()
            extra = 0
            for i in [keep] + [i for i in by_size if i != keep]:
                room = plan.rooms[i - 1]
                slot = "livingroom" if room.kind == "openplan" else room.kind
                if room.fixed and (slot not in ("livingroom", "kitchen", "hall")
                                   or slot not in taken):
                    taken.add(slot)
                    continue
                room.kind = FLAT_EXTRA[extra % len(FLAT_EXTRA)]
                extra += 1
            continue
        first = max(entry, key=lambda i: plan.rooms[i - 1].area) \
            if entry else by_size[0]
        # In a flat big enough for a hall, the hall is the first of the plan,
        # so it has to fall on the room that can actually serve as one: the
        # one touching the most of the others. Giving the name to the room by
        # the door instead left it bordering two rooms out of six, and the
        # rest still opened through each other.
        if len(members) >= FLAT_HALL_FROM and not hotel:
            inside = {i: sum(1 for n in adj[i] if n in members)
                      for i in members}
            first = max(members, key=lambda i: (inside[i],
                                                i in entry,
                                                plan.rooms[i - 1].area))
        ordered = [first] + [i for i in by_size if i != first]
        # Some flats are open plan: one room for the kitchen and the living
        # room together rather than a wall between them.
        open_plan = u in plan.open_units
        kinds = ((FLAT_PLANS_OPEN if open_plan else FLAT_PLANS)
                 .get(len(ordered)))
        if hotel:
            # A guest room, its bathroom, and a wardrobe closet in a big one.
            kinds = (["motelroom", "closet"][:max(1, len(ordered) - 1)]
                     + ["motelroom"] * max(0, len(ordered) - 3) + ["bathroom"])[:len(ordered)]                 if len(ordered) > 1 else ["motelroom"]
            if reception and u == min(units):
                kinds[0] = "lobby"
        elif kinds is None:
            base = FLAT_PLANS_OPEN[5] if open_plan else FLAT_PLANS[5]
            extra = [FLAT_EXTRA[k % len(FLAT_EXTRA)]
                     for k in range(len(ordered) - 5)]
            kinds = base[:-1] + extra + base[-1:]
        for i, kind in zip(ordered, kinds):
            plan.rooms[i - 1].kind = kind


def _flats_keep_bathrooms(plan: Plan) -> None:
    """Give a bathroom back to any flat of two rooms or more that lost it.

    A bathroom cut to its kind is 3x3: a lift shaft landing on it, or a notch
    in the footprint parting it from its flat, leaves a sliver folded into
    the room next door or a piece handed to the neighbouring flat. The
    smallest room that is not the living room - a kitchen last - takes over.
    """
    units: dict[int, list[Room]] = {}
    for room in plan.rooms:
        if room.unit and not room.is_shaft:
            units.setdefault(room.unit, []).append(room)
    for rooms in units.values():
        if len(rooms) < 2 or any(r.kind == "bathroom" for r in rooms):
            continue
        spare = [r for r in rooms if r.kind not in ("livingroom", "openplan")]
        if spare:
            min(spare, key=lambda r: (r.kind == "kitchen", r.area)).kind = "bathroom"


def _graph_distance(adj: dict[int, dict[int, int]], start: int) -> dict[int, int]:
    dist = {start: 0}
    frontier = [start]
    while frontier:
        nxt = []
        for cur in frontier:
            for n in adj[cur]:
                if n not in dist:
                    dist[n] = dist[cur] + 1
                    nxt.append(n)
        frontier = nxt
    return dist


# Knox County's houses (546 measured) have per house about 1.4 bedrooms, 0.4
# children's bedrooms, 0.5 closets and 0.2 laundries - and ours had three
# bedrooms and an office apiece, every spare room another bedroom. A room this
# small is a closet; the rest take turns down these lists.
# A room this size or under is a closet rather than a bedroom. It was 8,
# which no room can ever be: MIN_ROOM and MIN_SPLIT put the smallest room
# the splitter can make at 9 tiles, so the rule never once fired and Knox
# County's commonest small room - 5,397 closets - was one we never built.
SMALL_ROOM_TILES = 10
# Upstairs. The game's houses have 1.39 bedrooms and 0.42 children's rooms
# each; ours had 2.15 and 1.21, an upstairs of nothing but beds. A closet on
# the landing is what it really has - 0.50 a house, and none of ours had one.
# A separate dining room, in Knox County, is in 13% of houses.
DINING_ROOM_SHARE = 0.13
HOUSE_SLEEPING = ["bedroom", "kidsbedroom", "bedroom", "storage"]
# What is left of a floor once its bedrooms, its bathroom and its one office
# are dealt out. Everything past them used to become storage, which turned a
# fourteen-room house into five bedrooms and nine store cupboards - 2747
# storerooms in 200 houses against 321 before, and storage the commonest room
# in a house by three times over. These are the rooms a house has more than
# one of, and they are dealt round in turn.
HOUSE_SPARE = ["storage", "laundry", "office", "storage", "closet", "office"]
UPSTAIRS = ["bedroom", "kidsbedroom", "bedroom", "laundry",
            "bedroom", "office", "storage"]


def _footprint(plan: Plan) -> int:
    return (sum(sum(row) for row in plan.mask)
            if plan.mask is not None else plan.width * plan.height)


def _house_room_budgets(plan: Plan, levels: int) -> tuple[int, int]:
    floor_area = _footprint(plan) * max(1, levels)
    bedrooms = min(5, max(1, (floor_area + 89) // 90))
    bathrooms = 2 if floor_area >= 900 else 1
    return bedrooms, bathrooms


def _house_bedrooms_on_floor(bedrooms: int, levels: int, level: int) -> int:
    each, remainder = divmod(bedrooms, max(1, levels))
    return each + (level < remainder)


def _house_floor_bedrooms(bedrooms: int, levels: int, level: int) -> int:
    """A house's bedrooms on one floor: all of them in a bungalow, none on
    the ground floor of a house with an upstairs, the rest shared upstairs."""
    if levels <= 1:
        return bedrooms
    return _house_bedrooms_on_floor(bedrooms, levels - 1, level - 1) if level else 0


# Some two-storey houses keep a bedroom downstairs as well - for a guest or
# a grandparent - with a bathroom beside it, when the house has bedrooms
# enough upstairs and the ground floor room for both. All of them had one
# before bedrooms went upstairs; then none, and ground-floor bathrooms went
# with them (18 in 203 multi-storey houses to 5).
GROUND_BEDROOM_SHARE = 0.2
GROUND_EXTRA_TILES = 60


def _ground_bedroom(bedrooms: int, levels: int, floor: int,
                    rng: random.Random) -> bool:
    """Whether a house's ground floor keeps a bedroom of its own."""
    return (levels == 2 and bedrooms >= 2 and floor >= GROUND_EXTRA_TILES
            and rng.random() < GROUND_BEDROOM_SHARE)


def _house_spares(profile, rng: random.Random, upstairs: bool = False,
                  big: bool = False):
    """Rooms for a floor past its bedrooms, in turn: a study (or storage, by
    the household's _house_study_share), then storage and offices. The
    laundry is in the programme, the closets are the pieces a cut leaves.
    Only those: a house has a study and a store room, not a row of them, so
    past that an upper floor takes bedrooms, which are big enough to fill
    it, rather than filling with cupboards; a ground floor's rooms grow."""
    first = "office" if rng.random() < _house_study_share(profile) else "storage"
    yield first
    yield from (k for k in HOUSE_TOP_UP if k != first)
    if big:
        # A large house keeps its bedroom and bathroom budget; the extra
        # floor goes to a dining room and the rooms beside it.
        if not upstairs:
            yield "dining"
        # And past those, the rooms a big house really has more of, dealt
        # round: a floor of four hundred tiles is not seven rooms of sixty.
        while True:
            yield from BIG_HOUSE_FILL
    elif upstairs:
        yield from ("bedroom", "bedroom")


# A house floor cut by kind gets spare rooms while it is bigger than its
# rooms can fill (sizing.capacity: the big ones at their hi), so a big floor
# gets more rooms rather than a living room of 90 tiles - up to one room per
# HOUSE_ROOM_TILES of floor and HOUSE_MAX_SPARE spares.
HOUSE_ROOM_TILES = 22
HOUSE_MAX_SPARE = 40
# A floor this many tiles or more is a large house and takes more rooms of the
# kinds that fill a floor.
HOUSE_BIG_FLOOR = 260
# On a floor that size the bedrooms still stay bedrooms, not suites: the wings
# give the other rooms the space.
BIG_FLOOR_BEDROOM_OVERSIZE = 1.2
HOUSE_TOP_UP = ["storage", "office"]
HOUSE_GROW_TRIES = 10
BIG_HOUSE_FILL = ["closet", "livingroom", "laundry", "office", "storage",
                  "office", "storage", "livingroom"]
# Rooms a cut may clip away: what is left of one is folded into the room
# beside it or kept as a closet. The hall too, unless it is the landing.
HOUSE_LOSABLE = {"hall", "laundry", *HOUSE_TOP_UP}
# Shuffles of a programme cut as a whole box before it sheds a room, and of
# the bare programme before the floor falls back: a 3x3 bathroom lands
# clear of a turned footprint's corners only so often.
HOUSE_TRIES = 3
HOUSE_LAST_TRIES = 10
# A footprint filling less of its box than this - a turned or L-shaped
# house - is cut as it always was. The cut is drawn on the whole box, so
# every room the footprint does not clip came out the box's share of it:
# twice its size on a turned house, living rooms of 500 tiles.
HOUSE_MIN_FILL = 0.8
# Nor is a cut kept where a room it keeps is more than this many times the
# biggest its kind comes.
HOUSE_OVERSIZE = 2.0


def _wall_shared(a, b, run: int = 2) -> bool:
    """Whether two rectangles (anything with x0 y0 x1 y1) share a wall of at
    least `run` tiles."""
    ox = min(a.x1, b.x1) - max(a.x0, b.x0) + 1
    oy = min(a.y1, b.y1) - max(a.y0, b.y0) + 1
    return ((ox >= run and (a.y1 + 1 == b.y0 or b.y1 + 1 == a.y0))
            or (oy >= run and (a.x1 + 1 == b.x0 or b.x1 + 1 == a.x0)))


# The rooms of a large house's day wing; the rest sleep.
_DAY_ROOMS = {"hall", "livingroom", "openplan", "kitchen", "dining", "laundry",
              "office", "storage"}


def _cut_in_wings(box, kinds: list[str], rng: random.Random, floor, core,
                  landing) -> list[Room] | None:
    """A big house floor cut in two wings, each with a hall of its own.

    One cut over four hundred tiles has to put every bedroom beside a hall,
    and cannot, so a large house came out as rooms that open into rooms. Two
    wings are two small houses side by side: the stairs and the day rooms in
    one, the bedrooms in the other, and the halls meet. Returns None when
    the floor will not split (the caller cuts it whole)."""
    from .sizing import capacity
    rest = kinds[1:]
    day = [k for k in rest if k in _DAY_ROOMS]
    night = [k for k in rest if k not in _DAY_ROOMS]
    if len(day) < 2 or len(night) < 2:
        # Upstairs is all bedrooms: share them out, the second wing gets a hall.
        half = max(2, len(rest) // 2)
        day, night = rest[:half], rest[half:]
        if len(night) < 2:
            return None
    wing_a, wing_b = ["hall"] + day, ["hall"] + night
    # Split by what each wing can hold, not by its rooms' targets: a floor cut
    # in proportion to the targets gave a wing of three bedrooms the room of
    # five, and bedrooms of fifty tiles.
    ta = capacity(wing_a)
    tb = capacity(wing_b)
    x0, y0, x1, y1 = box
    wide = (x1 - x0) >= (y1 - y0)
    lo, hi = (x0, x1) if wide else (y0, y1)
    cut = lo + round((hi - lo + 1) * ta / (ta + tb))
    cut = min(max(cut, lo + 6), hi - 5)
    if core is not None:
        # The stairs stay in the first wing: the line goes past them, or in
        # front of them if that is nearer the ideal.
        c0, c1 = (core[0], core[2]) if wide else (core[1], core[3])
        if c0 < cut <= c1:
            cut = c1 + 1 if c1 + 1 <= hi - 5 else c0
    a_box = (x0, y0, cut - 1, y1) if wide else (x0, y0, x1, cut - 1)
    b_box = (cut, y0, x1, y1) if wide else (x0, cut, x1, y1)

    def tiles(b):
        return sum(1 for y in range(b[1], b[3] + 1) for x in range(b[0], b[2] + 1)
                   if floor[y][x])

    out = []
    for sub, wing in ((a_box, wing_a), (b_box, wing_b)):
        holds_core = core is not None and not (
            core[2] < sub[0] or core[0] > sub[2] or core[3] < sub[1] or core[1] > sub[3])
        got = split_by_targets(sub, wing, rng, area=tiles(sub),
                               touch=landing if holds_core else None)
        if got is None:
            return None
        out += got
    return out


def _house_by_kind(plan: Plan, level: int, levels: int,
                   rng: random.Random) -> list[Room] | None:
    """A house floor's rooms cut to its programme's sizes, kinds fixed.

    The whole box is cut, sized for the floor inside the walls, and kept
    only where every room keeps one piece of its kind's least floor inside
    the walls and clear of the stair shaft (painted over whatever is beneath
    it) - a bathroom the shaft lands on is not a bathroom - and none comes
    out far bigger than its kind. The hall is cut beside the stairs, so they
    arrive in it. A programme no cut fits sheds its extra rooms. None when
    the floor is too small, the footprint fills too little of its box, or
    nothing fits: the caller falls back to _split.
    """
    if _footprint(plan) < HOUSE_MIN_FILL * plan.width * plan.height:
        return None
    core = plan.core
    floor = [[(plan.mask is None or plan.mask[y][x])
              and not (core and core[0] <= x <= core[2] and core[1] <= y <= core[3])
              for x in range(plan.width)] for y in range(plan.height)]
    area = sum(map(sum, floor))
    kinds = programme_for_house_floor(area, level, levels, rng)
    if kinds is None:
        return None
    need = 5 if levels == 1 else 3      # rooms no floor of its kind goes without
    # An open-plan house has one room for living and cooking, cut as one.
    if level == 0 and rng.random() < _house_open_plan_share(plan.profile):
        kinds[kinds.index("livingroom")] = "openplan"
        kinds.remove("kitchen")
        need -= 1
    # A dining room as often as households have one (_house_dining_share).
    if (level == 0 and area >= (70 if levels == 1 else 45)
            and rng.random() < _house_dining_share(plan.profile)):
        kinds.append("dining")
    bedrooms, bathrooms = _house_room_budgets(plan, levels)
    quota = _house_floor_bedrooms(bedrooms, levels, level)
    spares = _house_spares(plan.profile, rng, level > 0, area >= HOUSE_BIG_FLOOR)
    beds = [i for i, k in enumerate(kinds) if k in ("bedroom", "kidsbedroom")]
    for i in beds[quota:]:     # past the house's bedroom budget
        kinds[i] = next(spares, "storage")
    spare = ["bedroom"] * (quota - len(beds))
    if level == 0:
        if _ground_bedroom(bedrooms, levels, area, rng):
            kinds += ["bedroom", "bathroom"]
        elif levels > 1 and bathrooms > levels - 1:
            spare.insert(0, "bathroom")
        if "laundry" not in kinds:
            spare.append("laundry")
    n = 0
    while (area > capacity(kinds)
           and n < HOUSE_MAX_SPARE and len(kinds) < area // HOUSE_ROOM_TILES):
        more = spare[n] if n < len(spare) else next(spares, None)
        if more is None:
            break
        kinds.append(more)
        n += 1
    box = (0, 0, plan.width - 1, plan.height - 1)
    landing = core if core is not None and kinds[0] == "hall" else None
    losable = HOUSE_LOSABLE - {"hall"} if landing else HOUSE_LOSABLE

    def keeps(room: Room) -> bool:
        ps = _pieces(room, floor)
        return bool(ps) and SIZES[room.kind].lo <= len(ps[0]) and not (
            _too_small(ps[0]) or (len(ps) > 1 and not _too_small(ps[1])))

    def _on_circulation(room: Room, rooms: list, core) -> bool:
        """A bedroom opens onto a hall, the stairs or the living room, else it
        is reached through another bedroom."""
        if room.kind not in ("bedroom", "kidsbedroom"):
            return True
        if core is not None:
            c = Room(*core)
            if _wall_shared(room, c):
                return True
        return any(o is not room and o.kind in ("hall", "livingroom", "openplan")
                   and _wall_shared(room, o) for o in rooms)

    # A big floor has more of everything, and each room may be bigger too.
    oversize = HOUSE_OVERSIZE

    def too_big(room: Room) -> bool:
        return (room.kind != "hall" and sum(map(len, _pieces(room, floor)))
                > (BIG_FLOOR_BEDROOM_OVERSIZE if room.kind in ("bedroom", "kidsbedroom")
                   and area >= HOUSE_BIG_FLOOR else oversize) * SIZES[room.kind].hi)

    grown = 0
    while True:
        always_big = True
        for _ in range(HOUSE_TRIES if len(kinds) > need else HOUSE_LAST_TRIES):
            rooms = (_cut_in_wings(box, kinds, rng, floor, core, landing)
                     if area >= HOUSE_BIG_FLOOR else None)
            if rooms is None:
                rooms = split_by_targets(box, kinds, rng, area=area, touch=landing)
            kept = [r for r in rooms or () if r.kind not in losable]
            big = any(map(too_big, kept))
            # One hall cannot touch every bedroom of a large house, and the
            # wings already give each half its own, so only a smaller floor
            # is held to it.
            if rooms and not big and all(map(keeps, kept)) and (
                    area >= HOUSE_BIG_FLOOR
                    or all(_on_circulation(r, rooms, core) for r in rooms)):
                return rooms
            always_big &= big
        # Every cut had a room too big for its kind. On a large floor that
        # means too few rooms, not too many: add some and cut again, a few
        # times, before the floor is given up to the plain splitter.
        if always_big and area >= HOUSE_BIG_FLOOR and grown < HOUSE_GROW_TRIES:
            grown += 1
            kinds.extend(k for k in (next(spares, None) for _ in range(2)) if k)
            continue
        # Fewer rooms would only come out bigger.
        if always_big or len(kinds) <= need:
            return None
        # Half the rooms it can shed at a time, so a footprint that only
        # takes the bare programme gets there in a few cuts, not a dozen.
        del kinds[len(kinds) - max(1, (len(kinds) - need) // 2):]


def _house_open_plan_share(profile) -> float:
    if profile is None:
        return 0.0
    era_share = {"prewar": 0.03, "midcentury": 0.12, "modern": 0.28}
    share = era_share.get(profile.era, 0.08) * (0.75 + 0.5 * profile.wealth)
    return min(0.38, share + (0.04 if profile.setting == "urban" else 0.0))


def _house_dining_share(profile) -> float:
    if profile is None:
        return DINING_ROOM_SHARE
    era_factor = {"prewar": 1.45, "midcentury": 1.0, "modern": 0.65}
    return min(0.3, DINING_ROOM_SHARE
               * era_factor.get(profile.era, 1.0)
               * (0.75 + 0.5 * profile.wealth))


def _house_study_share(profile) -> float:
    if profile is None:
        return 1.0
    share = 0.25 + 0.45 * profile.wealth
    if profile.era == "modern":
        share += 0.12
    if profile.wear >= 0.75:
        share -= 0.08
    return max(0.1, min(0.9, share))


def _merge_house_open_plan(plan: Plan, living_id: int, kitchen_id: int) -> bool:
    living, kitchen = plan.rooms[living_id - 1], plan.rooms[kitchen_id - 1]
    side_by_side = (living.y0 == kitchen.y0 and living.y1 == kitchen.y1
                    and (living.x1 + 1 == kitchen.x0 or kitchen.x1 + 1 == living.x0))
    stacked = (living.x0 == kitchen.x0 and living.x1 == kitchen.x1
               and (living.y1 + 1 == kitchen.y0 or kitchen.y1 + 1 == living.y0))
    if not (side_by_side or stacked):
        return False
    living.x0, living.y0 = min(living.x0, kitchen.x0), min(living.y0, kitchen.y0)
    living.x1, living.y1 = max(living.x1, kitchen.x1), max(living.y1, kitchen.y1)
    living.kind = "openplan"
    for y in range(plan.height):
        for x in range(plan.width):
            if plan.grid[y][x] == kitchen_id:
                plan.grid[y][x] = living_id
    kitchen.kind = None
    _renumber(plan)
    return True


# Where you walk when you are not in a room. Knox County's houses have a hall
# in 42% of them and a living room in nearly all, and everything opens off one
# or the other; ours had no circulation upstairs at all, so a floor of bedrooms
# was a chain of them - the commonest door in the whole town was one bedroom
# into the next.
CIRCULATION = {"hall", "lobby", "livingroom", "openplan", "concourse"}


def _landing(plan: Plan, adj: dict, free: list,
             stairs: tuple[int, int, str] | None) -> int | None:
    """The room a floor is walked through: where the stairs arrive, or failing
    that whichever room touches the most others."""
    if stairs is not None:
        x, y, d = stairs
        dx, dy = (0, 1) if d == "N" else (1, 0)
        for i in range(STAIR_RUN):
            room = _room_at(plan, x + dx * i, y + dy * i)
            if room in free:
                return room
    if not free:
        return None
    return max(free, key=lambda i: (len([n for n in adj.get(i, ()) if n in free]),
                                    plan.rooms[i - 1].area))


# One more hall per this many rooms on a floor, on top of the corridor and the
# landing. It is a balance between two ways of being wrong, and the number was
# picked by measuring both against Knox County. Too few and rooms chain: at
# one per twelve, 230 doors in 300 buildings went bedroom into bedroom. Too
# many and the plan is corridor: at one per six, a house was a third
# circulation where the game's are a quarter by room. One per eight puts a
# house at 23.3% of its rooms against the game's 23.7%, and bedroom-to-bedroom
# doors at 120 where the old plan had 771.
ROOMS_PER_HALL = 8


def _more_halls(plan: Plan, adj: dict, free: list, kinds: dict,
                seeds: list[int], cap: int, want: list[int] | None = None) -> int:
    """Rooms turned into halls until the rest (or `want`) all open onto one."""
    made = 0
    while made < cap and free:
        covered = set(seeds)
        for i in seeds:
            covered |= set(adj.get(i, ()))
        left = [i for i in (free if want is None else want) if i not in covered]
        if not left:
            break
        seed_set = set(seeds)
        best = max(free, key=lambda i: (
            len([n for n in adj.get(i, ()) if n in left]),
            len(set(adj.get(i, ())) & seed_set),
            plan.rooms[i - 1].area))
        if not any(n in left for n in adj.get(best, ())):
            break
        kinds[best] = "hall"
        free.remove(best)
        seeds.append(best)
        made += 1
    return made


def _assign_house_kinds(plan: Plan, level: int, levels: int,
                        stairs: tuple[int, int, str] | None = None,
                        rng: random.Random | None = None,
                        by_kind: bool = False) -> None:
    """Rooms of a house, placed by what they sit next to.

    Handing kinds out in size order put the kitchen wherever the second-biggest
    rectangle fell, bathrooms opening off living rooms, and a kitchen on every
    storey of a three-storey house. Here the ground floor holds the rooms a
    household shares - the living room, the kitchen beside it, dining beside
    that - and upper floors hold bedrooms. Bedrooms go as far from the living
    room as the plan allows; the bathroom takes the smallest room.

    A floor cut `by_kind` (_house_by_kind) already has its kinds, open plan
    included; only a piece the shaft or the footprint split off a room is
    named here, and a spare room off the hall becomes another hall where
    bedrooms and bathrooms would otherwise open into each other.
    """
    rng = rng or random.Random(plan.width * 31 + plan.height)
    if by_kind:
        for room in plan.rooms:
            if not room.is_core and not room.fixed:
                room.kind = "closet" if room.area <= SMALL_ROOM_TILES else "storage"
        adj = _neighbours(plan)
        rooms = list(enumerate(plan.rooms, 1))
        seeds = [i for i, r in rooms if r.is_core or r.kind in CIRCULATION]
        near = {n for i in seeds for n in adj[i]}
        free = [i for i, r in rooms if i in near and not r.is_core
                and r.kind in ("office", "storage", "laundry")]
        kinds: dict[int, str] = {}
        _more_halls(plan, adj, free, kinds, seeds, 1 + len(rooms) // ROOMS_PER_HALL,
                    want=[i for i, r in rooms
                          if r.kind in ("bedroom", "kidsbedroom", "bathroom")])
        for i, kind in kinds.items():
            plan.rooms[i - 1].kind = kind
        # A bedroom or bathroom still off every hall trades kinds with a
        # spare room on one that is the right size for it.
        def off_hall(i: int) -> bool:
            return not any(plan.rooms[n - 1].is_core
                           or plan.rooms[n - 1].kind in CIRCULATION for n in adj[i])
        for i, room in rooms:
            if room.kind not in ("bedroom", "kidsbedroom", "bathroom") or not off_hall(i):
                continue
            size = SIZES[room.kind]
            swap = [j for j, r in rooms if r.fixed and r.kind in HOUSE_TOP_UP
                    and not off_hall(j)
                    and size.lo <= r.area <= HOUSE_OVERSIZE * size.hi]
            if swap:
                j = min(swap, key=lambda j: abs(plan.rooms[j - 1].area - room.area))
                room.kind, plan.rooms[j - 1].kind = plan.rooms[j - 1].kind, room.kind
        return
    adj = _neighbours(plan)
    # A room the mapper drew with a kind of its own keeps it; only the rest
    # are dealt out, and whatever is left out of that is a core, hence the
    # hall below.
    free = [i for i, r in enumerate(plan.rooms, 1)
            if not r.is_core and not r.fixed]
    for i, room in enumerate(plan.rooms, 1):
        if i not in free and not room.fixed:
            room.kind = "hall"
    if not free:
        return
    area = {i: plan.rooms[i - 1].area for i in free}
    kinds: dict[int, str] = {}
    bedroom_budget, bathroom_budget = _house_room_budgets(plan, levels)
    ground_bed = level == 0 and _ground_bedroom(bedroom_budget, levels,
                                                _footprint(plan), rng)
    bedroom_quota = _house_floor_bedrooms(bedroom_budget, levels, level) + ground_bed
    # A bathroom on every floor with a bedroom, and on the ground floor too
    # when the house has one to spare.
    bathroom_floors = {n for n in range(levels)
                       if _house_floor_bedrooms(bedroom_budget, levels, n)}
    if bathroom_budget > len(bathroom_floors) or ground_bed:
        bathroom_floors.add(0)

    def take(i: int, kind: str) -> None:
        kinds[i] = kind
        free.remove(i)

    if level == 0:
        living = max(free, key=lambda i: area[i])
        take(living, "livingroom")
        if free:
            near = [n for n in adj[living] if n in free] or free
            kitchen = max(near, key=lambda i: area[i])
            take(kitchen, "kitchen")
            near = [n for n in adj[kitchen] if n in free]
            # A separate dining room is the exception: Knox County has one in
            # 13% of its houses, the rest eating in the kitchen or the living
            # room. Taking one whenever there was a room to spare gave ours
            # one in 93%.
            if near and len(free) >= 3 and rng.random() < _house_dining_share(plan.profile):
                take(max(near, key=lambda i: area[i]), "dining")
        if free and level in bathroom_floors and (levels == 1 or len(free) >= 2):
            take(min(free, key=lambda i: area[i]), "bathroom")
        # A small room beside the kitchen is its laundry.
        near = [n for n in adj.get(kitchens[0], ()) if n in free
                and area[n] <= SMALL_ROOM_TILES] if (kitchens := [i for i, k in kinds.items()
                                                                  if k == "kitchen"]) else []
        if near:
            take(min(near, key=lambda i: area[i]), "laundry")
        _more_halls(plan, adj, free, kinds, [living] + [i for i, k in kinds.items()
                                                        if k == "hall"],
                    len(free) // ROOMS_PER_HALL)
        dist = _graph_distance(adj, living)
        rest = sorted(free, key=lambda i: -dist.get(i, 99))
        bedroom_count = min(bedroom_quota, len(rest))
        kids_room = bedroom_count > 1 and rng.random() < 0.4
        for n, i in enumerate(rest):
            if n < bedroom_count:
                kinds[i] = "kidsbedroom" if kids_room and n == bedroom_count - 1 else "bedroom"
            elif area[i] <= SMALL_ROOM_TILES:
                kinds[i] = "closet"
            elif n == bedroom_count:
                kinds[i] = ("office" if rng.random() < _house_study_share(plan.profile)
                            else "storage")
            else:
                kinds[i] = HOUSE_SPARE[(n - bedroom_count - 1) % len(HOUSE_SPARE)]
    else:
        # The landing. Without one an upstairs was a row of bedrooms opening
        # into each other, which is what a plan should never ask you to walk
        # through. It is taken before the bathroom, which would otherwise take
        # the smallest room and leave nothing to walk in.
        landing = _landing(plan, adj, free, stairs)
        if landing is not None and len(free) >= 3:
            take(landing, "hall")
        _more_halls(plan, adj, free, kinds,
                    [i for i, k in kinds.items() if k == "hall"],
                    len(free) // ROOMS_PER_HALL)
        if free and level in bathroom_floors:
            take(min(free, key=lambda i: area[i]), "bathroom")
        rest = sorted(free, key=lambda i: -area[i])
        bedroom_count = min(bedroom_quota, len(rest))
        kids_room = bedroom_count > 1 and rng.random() < 0.4
        for n, i in enumerate(rest):
            if n < bedroom_count:
                kinds[i] = "kidsbedroom" if kids_room and n == bedroom_count - 1 else "bedroom"
            elif area[i] <= SMALL_ROOM_TILES:
                kinds[i] = "closet"
            elif level == 1 and n == bedroom_count:
                kinds[i] = "laundry"
            elif n == bedroom_count:
                kinds[i] = ("office" if rng.random() < _house_study_share(plan.profile)
                            else "storage")
            else:
                kinds[i] = HOUSE_SPARE[(n - bedroom_count - 1) % len(HOUSE_SPARE)]

    for i, kind in kinds.items():
        plan.rooms[i - 1].kind = kind
    _house_open_plan(plan, level, rng)


def _house_open_plan(plan: Plan, level: int, rng: random.Random) -> None:
    """Knock the ground floor's living room and kitchen into one, sometimes."""
    if level == 0 and rng.random() < _house_open_plan_share(plan.profile):
        living = next((i for i, room in enumerate(plan.rooms, 1)
                       if room.kind == "livingroom"), None)
        kitchen = next((i for i, room in enumerate(plan.rooms, 1)
                        if room.kind == "kitchen"), None)
        if living is not None and kitchen is not None:
            _merge_house_open_plan(plan, living, kitchen)


SHOP_BACK_ROOMS = ["storage", "office", "storage"]
# A shop's back rooms take this share of its depth, within these many tiles.
SHOP_BACK_SHARE = 0.3
SHOP_BACK_TILES = (3, 7)
MIN_SALES_DEPTH = 8
# A sales floor bigger than this is cut into sections, as a department store
# or a mall is: each about this big, none narrower than the minimum, and
# deeper floors cut into rows of them as well as columns.
SECTION_TILES = 450
MIN_SECTION_WIDTH = 12
SECTION_DEPTH = 22


def _grid(length: int, depth: int) -> tuple[list[int], list[int]]:
    """Column widths along the street and row depths back from it for a sales
    floor `length` by `depth`; one of each for a floor small enough to stay whole."""
    n = round(length * depth / SECTION_TILES)
    rows = max(1, min(round(depth / SECTION_DEPTH), n // 2))
    cols = min(max(1, round(n / rows)), length // MIN_SECTION_WIDTH)
    if rows * cols < 2:
        return [length], [depth]

    def cut(total, parts):
        base, extra = divmod(total, parts)
        return [base + (i < extra) for i in range(parts)]
    return cut(length, cols), cut(depth, rows)


# A petrol station's shop is small and has its back rooms all the same: the
# toilets and the stockroom are what a station is required to have.
GAS_BACK_TILES = (3, 5)
GAS_MIN_SALES_DEPTH = 5


def _shop_rooms(plan: Plan, rng: random.Random, street: str | None,
                gas: bool = False) -> list[int]:
    """A shop's ground floor as one sales floor the width of the shop front,
    and a strip of back rooms behind it: stockroom, office, toilet.

    Cut up like a house, a supermarket was eight rooms of 24 tiles, and the
    one that became the shop was a corridor four tiles wide with nothing but
    a shelf along each wall. A sales floor too big for one shop is cut into
    sections, each its own shop; returns the numbers of the sales rooms.
    """
    w, h = plan.width, plan.height
    side = street if street in ("N", "S", "W", "E") else ("S" if w >= h else "E")
    total = h if side in ("N", "S") else w
    lo, hi = GAS_BACK_TILES if gas else SHOP_BACK_TILES
    back = max(lo, min(hi, round(total * SHOP_BACK_SHARE)))
    if total - back < (GAS_MIN_SALES_DEPTH if gas else MIN_SALES_DEPTH):
        plan.rooms.append(Room(0, 0, w - 1, h - 1))
        return [1]
    if side == "S":
        sales, strip = (0, back, w - 1, h - 1), (0, 0, w - 1, back - 1)
    elif side == "N":
        sales, strip = (0, 0, w - 1, h - 1 - back), (0, h - back, w - 1, h - 1)
    elif side == "E":
        sales, strip = (back, 0, w - 1, h - 1), (0, 0, back - 1, h - 1)
    else:
        sales, strip = (0, 0, w - 1 - back, h - 1), (w - back, 0, w - 1, h - 1)
    x0, y0, x1, y1 = sales
    along_x = side in ("N", "S")
    cols, rows = _grid(x1 - x0 + 1 if along_x else y1 - y0 + 1,
                       y1 - y0 + 1 if along_x else x1 - x0 + 1)
    # Rows run back from the street: the one on the street first.
    far_first = side in ("S", "E")
    sections = []
    back_at = (y0 if along_x else x0)
    for depth in (rows[::-1] if far_first else rows):
        at = x0 if along_x else y0
        for width in cols:
            plan.rooms.append(Room(at, back_at, at + width - 1, back_at + depth - 1) if along_x
                              else Room(back_at, at, back_at + depth - 1, at + width - 1))
            sections.append(len(plan.rooms))
            at += width
        back_at += depth
    _split(*strip, rng, MAX_DEPTH, plan.rooms, target_area=max(16, back * 8),
           mask=plan.mask, small=[True])
    return sections
MIN_SHOP_ROOM = 16


def _fit_out_sections(plan: Plan, rng: random.Random, sections: list[int],
                      uses: list | None) -> None:
    """The sections that are not on the street are shops as well, not back
    rooms: a department store's far end is as much sales floor as its front.
    With no known use each section is a different kind of shop while the kinds
    last, as in a mall, not four general stores in a row."""
    from . import interiors
    if uses:
        for i in sections:
            if plan.rooms[i - 1].kind not in interiors.STORES:
                plan.rooms[i - 1].kind = uses[0][0]
        return
    kinds = list(interiors.STORE_WEIGHTS)
    rng.shuffle(kinds)
    for n, i in enumerate(sections):
        plan.rooms[i - 1].kind = kinds[n % len(kinds)]
    adj = _neighbours(plan)
    for i, room in enumerate(plan.rooms, 1):
        if room.kind == "grocerystorage" and not any(
                plan.rooms[j - 1].kind == "grocery" for j in adj.get(i, ())):
            room.kind = "storage"


def _assign_shop_floor(plan: Plan, rng: random.Random, street: str | None,
                       uses: list[tuple[str, str]] | None, several: bool) -> None:
    """A commercial ground floor: what is on the street in front, what serves
    it behind.

    The rooms with an outside wall on the street (or on any side, when the
    street is not known) and floor enough become the fronts, taken along the
    street. Each takes the next of the building's real uses
    (knoxbuild/uses.py) - the pizza place's dining room, the bank hall - and
    a room behind it becomes that use's back room: the pizza kitchen, the
    stockroom. A block of flats with more shop fronts than known uses fills
    the rest with shops of the usual kinds; the remaining back rooms are
    storerooms, an office and a toilet.
    """
    from . import interiors
    rooms = [(i, r) for i, r in enumerate(plan.rooms, 1) if not r.is_core and not r.is_shaft]
    if not rooms:
        return
    uses = list(uses or [])

    def street_wall(i):
        n = 0
        for side, wall in _outside_runs(plan, i):
            if street is None or side == street:
                n += len(wall)
        return n

    fronts = [ir for ir in rooms if street_wall(ir[0]) >= 3 and ir[1].area >= MIN_SHOP_ROOM]
    if not fronts:
        fronts = [max(rooms, key=lambda ir: ir[1].area)]
    if not several:
        fronts = [max(fronts, key=lambda ir: ir[1].area)]
    # Along the street, so the uses keep the order they were found in.
    fronts.sort(key=lambda ir: (ir[1].x0, ir[1].y0) if street in ("N", "S", None) else (ir[1].y0, ir[1].x0))
    adj = _neighbours(plan)
    taken = {i for i, _ in fronts}
    backs: list[tuple[int, str]] = []
    for n, (i, r) in enumerate(fronts):
        if n < len(uses):
            front, back = uses[n]
        elif uses:
            # More shop fronts than the map has businesses: the last one
            # along the street takes the room next door as well.
            front, back = uses[-1][0], "storage"
        else:
            front = interiors.store_kind(rng)
            back = "grocerystorage" if front == "grocery" else "storage"
        r.kind = front
        backs.append((i, back))
    for i, back in backs:
        # The biggest room behind this front that nobody has yet.
        near = sorted((j for j in adj.get(i, {}) if j not in taken
                       and not plan.rooms[j - 1].is_core and not plan.rooms[j - 1].is_shaft),
                      key=lambda j: -plan.rooms[j - 1].area)
        if near:
            plan.rooms[near[0] - 1].kind = back
            taken.add(near[0])
    rest = sorted((ir for ir in rooms if ir[0] not in taken), key=lambda ir: -ir[1].area)
    for n, (i, r) in enumerate(rest):
        r.kind = SHOP_BACK_ROOMS[n % len(SHOP_BACK_ROOMS)]
    if len(rest) >= 2:
        rest[-1][1].kind = "bathroom"
    if any(front == "gasstore" for front, _back in uses):
        # A petrol station has toilets, one a side where there is room.
        back_rooms = [r for _i, r in rest]
        toilets = [r for r in back_rooms if r.kind == "bathroom"]
        spare = sorted((r for r in back_rooms if r.kind != "bathroom"), key=lambda r: r.area)
        want = 2 if len(back_rooms) >= 4 else 1
        for room in spare[:max(0, want - len(toilets))]:
            room.kind = "bathroom"


# At most one room of this kind per this many rooms on a floor. The fill list
# was cycled round-robin once the mix was spent, so every kind in it ended up
# with an equal share however silly that was: a school came out with 61
# lavatories and 58 offices to its 63 classrooms, a police station with seven
# locker rooms, and a church with as many storerooms as nave. A kind that has
# had its share is skipped and the next one in the list takes the room.
# One room in this many may be of that kind. A kind missing from here has no
# cap at all, which is how a police station came out 36% policeoffice: the
# fill fell through to it every time. Measured over Knox County's 13 buildings
# with a policeoffice in them, a station is 31% cells, 17% offices, 13% hall
# and 8% bathroom - so cells get the run of the place and offices do not.
ROOM_CAP_PER = {
    # A school has one library, one gym, one canteen and one janitor,
    # not one per six rooms: at a cap of 6 a 25-room floor came out with
    # four libraries. These are the rooms a building has exactly one of.
    "library": 40, "gym": 40, "kitchen": 40, "diningroom": 40,
    "lobby": 40, "schoollab": 24, "schoolstorage": 24,
    "sportstorage": 40,
    "bathroom": 10, "hall": 12,
    "breakroom": 25, "office": 12, "storage": 8, "garage": 15,
    "policeoffice": 6, "evidenceroom": 25,
    # A few cells, not a cell block: one room in eight at most, so a
    # 30-room station gets three or four rather than the eleven that a
    # cap of 3 gave it.
    "prisoncells": 8, "interrogationroom": 20, "policearchive": 30,
    "lobby_police": 30, "armory": 30, "lockerroom": 20,
    "policegunstorage": 30, "policeoutfitstorage": 30, "policelocker": 15,
    "policehall": 25, "firegarage": 12, "armystorage": 4, "medical": 4,
    # janitor: this was written twice, 40 among the rooms above and 18 here, and the
    # later one is the one that counted. Measured, the difference is small (a police
    # station averages 2.4 of them at 18 and 2.1 at 40, a school gets next to none
    # either way), so the live value stays rather than changing every existing map.
    "clinic": 4, "officestorage": 12, "janitor": 18,
    "security": 25,
    # A castle's chambers. Everything past the mix falls to the fill, and
    # bedroom was the only kind in the castle's with no cap, so it took every
    # room a bigger keep had: 5% of a small one, 51% at the size the landmark
    # growth actually gives them, 63% at the largest. A barracks is unmoved -
    # its fill falls back to bedroom, which is what a dormitory block is.
    "bedroom": 4,
    # A ground has a few counters on the concourse, not a food hall: cafe was
    # the one kind in the stadium's fill with no cap and took 36% of a big
    # one once the rest were spent.
    "cafe": 10,
    # No mall is all one chain. Each unit kind takes a share of the units,
    # the way a fill kind without a cap took the whole of a big castle.
    "clothingstore": 8, "giftstore": 12, "toystore": 14, "bookstore": 14,
    "furniturestore": 14, "sportstore": 14, "departmentstore": 16,
    # No mall is all one chain, and Knox County's lets to about thirty
    # different trades: clothes 11 units, department 21, gift 3, toy 3, shoe
    # 1, jeweller 3, houseware 3. These keep any one of them to a share.
    "clothesstore": 9, "shoestore": 16, "electronicsstore": 18,
    "housewarestore": 16, "sewingstore": 30, "cornerstore": 30,
    "optometrist": 30, "jewelrystore": 16, "musicstore": 20,
    "candystore": 20, "toolstore": 20, "gunstore": 30, "pharmacy": 25,
    "bakery": 25, "foodcourt": 40, "clothesstorage": 12,
    "departmentstorage": 25, }


# How big each kind of room is in Knox County, in tiles. The mix used to be
# handed to rooms in size order, so whatever stood first in the list got the
# biggest room: a station's cells landed on its fifth-largest room and came
# out at 24 m2 against the game's 15, while its corridor got 36 against 51.
# Ordering the mix by these instead puts a cell on a small room and a hall on
# a big one. A kind that is not here keeps its place in the list.
ROOM_MEDIAN_AREA = {
    # Measured over every room of that name in Knox County, not estimated.
    # The first version of this table was guessed and several were far out: a
    # classroom is 24 m2 and had 48, a dining room 22 and had 55, a hall 27
    # and had 51, a closet 2 and had 6. _split_to_size cuts a room down to
    # these, so a wrong number here decides how big rooms actually come out.
    "library": 100, "gym": 88, "church": 110, "policehall": 51,
    "restaurant": 50, "corridor": 45,
    "policeoffice": 30, "office": 30, "livingroom": 29,
    # Knox County's classrooms are 24 m2 and its schools are a warren of
    # them. These are set higher on purpose: a school of a dozen big
    # rooms reads better than one of forty small ones, and _split_to_size
    # cuts a room down to these, so they are what decides it.
    "hall": 27, "lobby": 40, "classroom": 140, "secondaryclassroom": 140,
    "schoollab": 56, "diningroom": 60, "kitchen": 21,
    "policelocker": 24, "lockerroom": 24, "breakroom": 24, "storage": 20,
    "policegunstorage": 18, "policeoutfitstorage": 18, "policearchive": 18,
    "evidenceroom": 18, "armory": 18,
    "interrogationroom": 16, "bedroom": 15, "prisoncells": 15,
    "security": 15, "officestorage": 14, "janitor": 12,
    "bathroom": 6, "closet": 2,
}


def _by_expected_size(kinds: list[str]) -> list[str]:
    """The same kinds, biggest-roomed first, so they meet rooms of their size.

    Stable on anything ROOM_MEDIAN_AREA does not know, which keeps a list
    whose order was chosen for other reasons in the order it was written.
    """
    if not any(k in ROOM_MEDIAN_AREA for k in kinds):
        return kinds
    return sorted(kinds, key=lambda k: -ROOM_MEDIAN_AREA.get(k, 25))


# A room is cut down to its kind's size when it is this many times too big.
# Below that the spread is just how buildings are.
OVERSIZE = 1.6
# Rooms a building has one of. Splitting an oversized one in two gave a
# school four libraries and two gyms however hard the mix was capped,
# because _split_to_size copies the kind into both halves.
# Only these are cut down to their kind's size. The pass was written to
# stop a police cell coming out at 24 m2 when the game's are 15, and
# applying it to every kind quietly became what decided room size
# everywhere: it was shredding a school floor into halls of 43 m2 and
# offices of 48 however big the splitter had made them.
SHRINK_TO_KIND = {"prisoncells", "closet", "policelocker", "lockerroom",
                  "janitor", "officestorage"}
# How many rooms one oversized room may be cut into. In a big building every
# room is big, so a kind that is small everywhere is always oversized and was
# halved until it fit: two changing rooms in a 70x56 ground became sixteen,
# 39% of the building. A cell block of eight is still a cell block.
MAX_SPLIT_PIECES = 4
ONE_OF_A_KIND = {"library", "gym", "kitchen", "diningroom", "lobby",
                 "janitor", "schoollab", "interrogationroom", "armory",
                 "evidenceroom", "security", "breakroom"}


def _split_to_size(plan: Plan, rng: random.Random) -> None:
    """Cut a room that is far bigger than its kind ever is into rooms of it.

    The splitter makes rooms of roughly one size, so a police station came out
    with every room near 34 m2 - which meant its cells were 24 m2 where Knox
    County's are 15, because there was no small room for a cell to be. Sizing
    the kinds afterwards cannot fix that; there has to be a cell block. Once
    the kind is known the room is halved until it is about the size that kind
    is, which turns one oversized cell into a row of them.

    Runs after the kinds are handed out and before the doors, so the doors are
    placed on the rooms that actually exist.
    """
    for idx in range(len(plan.rooms)):
        room = plan.rooms[idx]
        want = ROOM_MEDIAN_AREA.get(room.kind)
        if (want is None or room.is_core or room.is_shaft
                or room.kind in ONE_OF_A_KIND
                or room.kind not in SHRINK_TO_KIND):
            continue
        queue = [idx]
        pieces = 1
        while queue:
            i = queue.pop()
            r = plan.rooms[i]
            if r.area < want * OVERSIZE or pieces >= MAX_SPLIT_PIECES:
                continue
            # Halve the long way, so a cell block comes out as a row.
            if r.w >= r.h:
                if r.w < MIN_SPLIT:
                    continue
                cut = r.x0 + r.w // 2
                new = Room(cut, r.y0, r.x1, r.y1, kind=r.kind, unit=r.unit)
                r.x1 = cut - 1
            else:
                if r.h < MIN_SPLIT:
                    continue
                cut = r.y0 + r.h // 2
                new = Room(r.x0, cut, r.x1, r.y1, kind=r.kind, unit=r.unit)
                r.y1 = cut - 1
            if min(r.w, r.h, new.w, new.h) < MIN_ROOM:
                # Put it back: the halves would be slivers.
                if new.x0 > r.x0:
                    r.x1 = new.x1
                else:
                    r.y1 = new.y1
                continue
            plan.rooms.append(new)
            pieces += 1
            at = len(plan.rooms)
            for y in range(new.y0, new.y1 + 1):
                for x in range(new.x0, new.x1 + 1):
                    if plan.grid[y][x] == i + 1:
                        plan.grid[y][x] = at
            queue.extend([i, at - 1])


def _assign_kinds(rooms: list[Room], mix: list[str], fill: list[str]) -> None:
    import collections as _c

    mix = _by_expected_size(mix)
    order = sorted(rooms, key=lambda r: -r.area)
    total = len(order)
    used: _c.Counter = _c.Counter()

    def spare(kind: str) -> bool:
        per = ROOM_CAP_PER.get(kind)
        return per is None or used[kind] < max(1, total // per)

    for i, room in enumerate(order):
        if room.fixed:
            continue        # the kind the mapper gave this room stands
        if i < len(mix):
            kind = mix[i]
        else:
            # Of the fill kinds that still have a share going, the one whose
            # rooms are this size in Knox County. Cycling the list instead
            # handed cells and cupboards whatever room came next, so a
            # station's cells averaged 24 m2 against the game's 15 while its
            # storerooms took the big ones.
            start = (i - len(mix)) % len(fill)
            ready = [fill[(start + k) % len(fill)] for k in range(len(fill))
                     if spare(fill[(start + k) % len(fill)])]
            if ready and any(k in ROOM_MEDIAN_AREA for k in ready):
                kind = min(ready, key=lambda k: abs(
                    ROOM_MEDIAN_AREA.get(k, 25) - room.area))
            else:
                # Every fill kind is spent. Carry on round the list from
                # where this room falls rather than dropping the whole
                # remainder on the first entry: a big building has far more
                # rooms than the mix and the caps together cover, and that
                # gave a stadium sixteen identical corridors and a castle a
                # floor of beds.
                kind = ready[0] if ready else fill[start]
        room.kind = kind
        used[kind] += 1
    # The smallest room makes a far more convincing bathroom than a hall. It
    # trades kinds with whatever the mix made the bathroom rather than adding
    # one, or a nine-room church came out with two lavatories in it. Fixed
    # rooms - drawn with a kind of their own - are neither moved into nor out
    # of: the smallest one the mix still owns takes the trade.
    swappable = [r for r in order if not r.fixed]
    if len(order) >= 3 and "bathroom" in mix and swappable \
            and swappable[-1].kind != "bathroom":
        swap = next((r for r in swappable if r.kind == "bathroom"), None)
        if swap is not None:
            swap.kind = swappable[-1].kind
        swappable[-1].kind = "bathroom"


# Buildings you walk through to get somewhere else. A school of classrooms
# wants a corridor and a police station wants one; a church does not, its nave
# being the way through, and nor does a warehouse or a shop floor. Only houses
# got circulation before this, so a school was classrooms opening into one
# another the way the bedrooms upstairs used to.
# A floor wants a corridor once it holds about this many rooms; below that
# the corridor is more of the building than the rooms it serves.
CORRIDOR_WORTH_IT = 8


NEEDS_CORRIDOR = {"school", "police", "civic", "medical", "fire", "military",
                  "library", "offices"}

# Pairs that belong together when both rooms fit on the floor. Shop and
# restaurant fronts already choose an adjacent back room in _assign_shop_floor.
BUSINESS_NEIGHBOURS = {
    "school": (("kitchen", "diningroom"), ("gym", "sportstorage"),
               ("classroom", "schoollab")),
    "church": (("lobby", "church"), ("office", "storage")),
    "industrial": (("warehouse", "storage"), ("warehouse", "garage")),
    "barn": (("warehouse", "storage"), ("warehouse", "garage")),
    "military": (("kitchen", "bedroom"), ("armystorage", "office")),
    "castle": (("hall", "church"), ("hall", "kitchen")),
    "stadium": (("lockerroom", "sportstorage"), ("hall", "cafe")),
    "medical": (("clinic", "medical"), ("lobby", "office")),
    "civic": (("lobby", "office"), ("library", "storage")),
    "police": (("policeoffice", "interrogationroom"),
               ("policeoffice", "evidenceroom"), ("policelocker", "lockerroom")),
    "library": (("library", "storage"), ("lobby", "library")),
    "fire": (("firegarage", "firestorage"), ("kitchen", "bedroom")),
    "offices": (("office", "officestorage"), ("office", "breakroom")),
}


def _arrange_business_rooms(plan: Plan, kind: str) -> None:
    """Improve related-room adjacency without changing the mix or circulation."""
    pairs = BUSINESS_NEIGHBOURS.get(kind, ())
    if not pairs:
        return
    adj = _neighbours(plan)
    rooms = plan.rooms

    def satisfied(pair):
        a, b = pair
        return any(rooms[i - 1].kind == a and
                   any(rooms[j - 1].kind == b for j in neighbours)
                   for i, neighbours in adj.items())

    for pair in pairs:
        if satisfied(pair):
            continue
        before = sum(satisfied(p) for p in pairs)
        done = False
        for i, room in enumerate(rooms, 1):
            if room.kind != pair[0]:
                continue
            for j in sorted(adj[i]):
                candidate = rooms[j - 1]
                if candidate.fixed or candidate.is_core or candidate.is_shaft or candidate.kind in CIRCULATION:
                    continue
                for other in rooms:
                    if (other.kind != pair[1] or other.fixed or other.is_core
                            or other.is_shaft or other.kind in CIRCULATION):
                        continue
                    if max(candidate.area, other.area) > 2 * min(candidate.area, other.area):
                        continue
                    candidate.kind, other.kind = other.kind, candidate.kind
                    if satisfied(pair) and sum(satisfied(p) for p in pairs) > before:
                        done = True
                        break
                    candidate.kind, other.kind = other.kind, candidate.kind
                if done:
                    break
            if done:
                break

MIN_SPECIAL_ROOMS = {
    "school": {"classroom": 1, "diningroom": 1, "kitchen": 1, "gym": 1, "library": 1},
    "police": {"policeoffice": 1, "policelocker": 1},
    "civic": {"office": 1, "lobby": 1},
    "medical": {"clinic": 1, "medical": 1},
    "fire": {"firegarage": 1},
    "military": {"armystorage": 1},
    "library": {"library": 1},
    "offices": {"office": 1},
}


def _circulation(plan: Plan, rooms: list[Room]) -> int:
    """Rooms turned into halls until the rest all open onto one."""
    adj = _neighbours(plan)
    where = {id(r): i for i, r in enumerate(plan.rooms, 1)}
    protected = set()
    for kind, minimum in MIN_SPECIAL_ROOMS.get(plan.kind or "", {}).items():
        matches = sorted((r for r in rooms if r.kind == kind),
                         key=lambda r: -r.area)
        protected.update(id(r) for r in matches[:minimum])
    free = [where[id(r)] for r in rooms if (r.kind or "") not in CIRCULATION
            and id(r) not in protected]
    seeds = [where[id(r)] for r in rooms if (r.kind or "") in CIRCULATION]
    kinds: dict[int, str] = {}
    made = _more_halls(plan, adj, free, kinds, seeds,
                       len(free) // ROOMS_PER_HALL)
    for i, kind in kinds.items():
        plan.rooms[i - 1].kind = kind
    return made


# Kinds whose rooms are run together into one space rather than left as a row
# of separate corridors. Knox County's mall is one concourse of 5,855 tiles on
# the ground floor - a single room made of 62 rectangles - where ours was
# seven halls of about 300 tiles each, because the splitter's target caps
# every room in a building and a hall is no exception. A mall holds hundreds
# of people and the concourse is the reason it can.
MERGE_CIRCULATION: set[str] = set()


# How much of a mall's depth the concourse takes, and the width it is held
# between. Knox County's mall is 33.6% hall by floor and that hall is one
# room of 5,855 tiles, not a row of corridors: the units open onto it and it
# is where the hundreds of people are. Cut before the units, so it is one
# rectangle rather than whatever the splitter leaves over.
MALL_CONCOURSE_SHARE = 0.16
MALL_CONCOURSE_MIN = 9
MALL_CONCOURSE_MAX = 26
# The gallery either side of the hole on an upper floor. Knox County's mall
# leaves 89% of the ground concourse open to the floor above - 5,185 of its
# 5,855 squares have nothing on them at level 1 - so the two floors read as
# one space. This is how much of the band stays walkable up there.
MALL_GALLERY = 3
# The arms that run off the spine to the far walls: how wide against the
# spine, the bounds on that, how far apart, and how many at most. Knox
# County's concourse is 27% of its bounding box because of these; without
# them a mall is one aisle with rooms down each side.
MALL_ARM_SHARE = 0.60
MALL_ARM_MIN = 5
MALL_ARM_MAX = 8
MALL_ARM_EVERY = 26
MALL_ARMS_MAX = 3
# How far the hole stops short of each end of the spine. The concourse wraps
# round both ends of the opening, which is what joins the two galleries and
# keeps the stairs reachable - so nothing has to bridge the hole and the
# railing runs round one clean opening instead of round each bay.
MALL_HOLE_END = 6


def _mall_rooms(plan: Plan, rng: random.Random, target: int,
                level: int = 0) -> None:
    """A branching concourse, with the units filling the blocks between it.

    Knox County's mall concourse is not a corridor down the middle: it is a
    wide spine across the building with arms running off it to the far walls,
    and it covers 27% of its own bounding box. A single band covered 100% of
    one and read as a warehouse aisle. The spine and each arm is its own
    rectangle - a Room here is its rectangle, and the doors and the furnishing
    both read it - and they are all concourse, so the game sees one run of
    hall the shopper walks the length of.

    Above the ground floor the middle of the spine is left open (no room, so
    no floor) with a gallery either side, which is how the mall is one space
    several storeys tall.
    """
    w, h = plan.width, plan.height
    along_x = w >= h
    across, length = (h, w) if along_x else (w, h)
    band = max(MALL_CONCOURSE_MIN,
               min(MALL_CONCOURSE_MAX, round(across * MALL_CONCOURSE_SHARE)))
    if across - band < 2 * MIN_ROOM:
        _split(0, 0, w - 1, h - 1, rng, MAX_DEPTH, plan.rooms,
               target_area=target, mask=plan.mask)
        return
    start = (across - band) // 2

    def put(a0, b0, a1, b1, kind=None, fixed=False):
        """A room in the building's own axes (a = along, b = across)."""
        if a1 < a0 or b1 < b0:
            return
        if along_x:
            plan.rooms.append(Room(a0, b0, a1, b1, kind=kind or "hall",
                                   fixed=fixed) if kind
                              else Room(a0, b0, a1, b1))
        else:
            plan.rooms.append(Room(b0, a0, b1, a1, kind=kind or "hall",
                                   fixed=fixed) if kind
                              else Room(b0, a0, b1, a1))

    def cut(a0, b0, a1, b1):
        if a1 < a0 or b1 < b0:
            return
        box = (a0, b0, a1, b1) if along_x else (b0, a0, b1, a1)
        _split(box[0], box[1], box[2], box[3], rng, MAX_DEPTH, plan.rooms,
               target_area=target, mask=plan.mask)

    # Where the arms meet the spine, worked out first: the hole in an upper
    # floor stops at them, so each arm carries on across as a bridge. Without
    # that the hole cut the storey in two and half the units had no way to
    # the stairs.
    arm = max(MALL_ARM_MIN, min(MALL_ARM_MAX, round(band * MALL_ARM_SHARE)))
    count = max(1, min(MALL_ARMS_MAX, (length - arm) // MALL_ARM_EVERY))
    centres = [round(length * (k + 1) / (count + 1)) for k in range(count)]
    spans = []
    for c in centres:
        a0 = max(0, min(length - arm, c - arm // 2))
        if not spans or a0 > spans[-1][1] + MIN_ROOM:
            spans.append((a0, a0 + arm - 1))
    # The spine, all the way across.
    hole = band - 2 * MALL_GALLERY
    lo_end, hi_end = MALL_HOLE_END, length - 1 - MALL_HOLE_END
    open_middle = level > 0 and hole >= 3 and hi_end - lo_end >= MIN_ROOM
    if open_middle:
        put(0, start, length - 1, start + MALL_GALLERY - 1, "concourse", True)
        put(0, start + band - MALL_GALLERY, length - 1, start + band - 1,
            "concourse", True)
        # The concourse carries on round both ends of the opening, which is
        # what the galleries walk round to reach each other.
        put(0, start + MALL_GALLERY, lo_end - 1,
            start + band - MALL_GALLERY - 1, "concourse", True)
        put(hi_end + 1, start + MALL_GALLERY, length - 1,
            start + band - MALL_GALLERY - 1, "concourse", True)
        for b in range(start + MALL_GALLERY, start + band - MALL_GALLERY):
            for a in range(lo_end, hi_end + 1):
                plan.void.add((a, b) if along_x else (b, a))
    else:
        put(0, start, length - 1, start + band - 1, "concourse", True)

    # The units fill the blocks between the arms.
    for lo, hi in (0, start - 1), (start + band, across - 1):
        if hi < lo:
            continue
        edge = 0
        for a0, a1 in spans:
            cut(edge, lo, a0 - 1, hi)
            put(a0, lo, a1, hi, "concourse", True)
            edge = a1 + 1
        cut(edge, lo, length - 1, hi)
    # The stairs stand in the middle of the building, which is the middle of
    # the concourse, which is where the hole is: left alone they are a landing
    # in mid-air. The core keeps its floor and a walkway of concourse runs
    # from it out to the nearer gallery. Both come out of the hole, and the
    # walkway is a room of its own or it would have no floor either.
    if plan.void and plan.core:
        cx0, cy0, cx1, cy1 = plan.core
        a0, a1, b0, b1 = ((cx0, cx1, cy0, cy1) if along_x
                          else (cy0, cy1, cx0, cx1))
        lo = start + MALL_GALLERY
        hi = start + band - MALL_GALLERY - 1
        if lo <= b1 and b0 <= hi:
            near_top = (b0 - lo) <= (hi - b1)
            wb0, wb1 = (lo, b0 - 1) if near_top else (b1 + 1, hi)
            put(a0, wb0, a1, wb1, "concourse", True)
            for a in range(a0, a1 + 1):
                for b in range(min(wb0, b0), max(wb1, b1) + 1):
                    plan.void.discard((a, b) if along_x else (b, a))


# What may stand on the concourse: what its own wishlist puts there, plus the
# light switches and lamps every room gets. With Erika's Tiles the plants come
# through as erika_plant_*, so these are matched as prefixes.
CONCOURSE_KEEP = {"plant", "erika_plant", "shop_bin", "vending",
                  "erika_vending", "switch", "lamp", "light"}


def _clear_concourse(plan: Plan) -> int:
    """Take off the concourse whatever the units put there.

    A shop is fitted from its own walls out, and a unit whose front is the
    concourse edge lays its wall pieces on the far side of that wall - a
    furniture shop left fourteen dressers standing in the middle of the mall.
    Anything on a concourse tile that is not concourse fitting comes off.
    """
    concourse = {i for i, r in enumerate(plan.rooms, start=1)
                 if r.kind == "concourse"}
    if not concourse:
        return 0
    kept, dropped = [], 0
    for piece in plan.furniture:
        role, x, y = piece[0], piece[1], piece[2]
        inside = (0 <= y < len(plan.grid) and 0 <= x < len(plan.grid[0])
                  and plan.grid[y][x] in concourse)
        if inside and not any(role.startswith(k) for k in CONCOURSE_KEEP):
            dropped += 1
            continue
        kept.append(piece)
    plan.furniture = kept
    return dropped


def _bridge_core(plan: Plan, along_x: bool) -> None:
    """Keep the stairs out of the hole, and a way to them across it.

    The stair core stands in the middle of the building, which is the middle
    of the concourse, which is exactly where the hole goes: left alone it was
    a landing marooned in mid-air with the galleries out of reach either side.
    The core keeps its floor and a walkway runs from it to the nearer gallery.
    """
    if not plan.core:
        return
    cx0, cy0, cx1, cy1 = plan.core
    rows = [y for x, y in plan.void]
    cols = [x for x, y in plan.void]
    lo, hi = (min(rows), max(rows)) if along_x else (min(cols), max(cols))
    for x in range(cx0, cx1 + 1):
        for y in range(cy0, cy1 + 1):
            plan.void.discard((x, y))
    if along_x:
        # Out of the core to whichever edge of the hole is closer.
        up = (cy0 - lo) <= (hi - cy1)
        span = range(lo, cy0) if up else range(cy1 + 1, hi + 1)
        for y in span:
            for x in range(cx0, cx1 + 1):
                plan.void.discard((x, y))
    else:
        left = (cx0 - lo) <= (hi - cx1)
        span = range(lo, cx0) if left else range(cx1 + 1, hi + 1)
        for x in span:
            for y in range(cy0, cy1 + 1):
                plan.void.discard((x, y))


def _atrium_railings(plan: Plan) -> None:
    """Rail the edge of the hole, and take the windows off it.

    A gallery's inner edge borders the hole, which is nothing, and nothing
    reads as outdoors: it was given an exterior wall with windows in it -
    glazing over a two-storey opening inside the building. It gets a railing
    instead, which is what a balcony over a mall floor has.
    """
    if not plan.void:
        return
    h, w = len(plan.grid), len(plan.grid[0])

    def room_at(x, y):
        return plan.grid[y][x] if 0 <= x < w and 0 <= y < h else 0

    for x, y in plan.void:
        # The square west of the hole, and the one north of it, each carry
        # the edge between them on the hole's own square.
        if room_at(x - 1, y) and (x - 1, y) not in plan.void:
            plan.railing.add((x, y, "W"))
        if room_at(x + 1, y) and (x + 1, y) not in plan.void:
            plan.railing.add((x + 1, y, "W"))
        if room_at(x, y - 1) and (x, y - 1) not in plan.void:
            plan.railing.add((x, y, "N"))
        if room_at(x, y + 1) and (x, y + 1) not in plan.void:
            plan.railing.add((x, y + 1, "N"))
    # The windows themselves are placed later, over the whole building
    # (_place_windows), which skips these edges; nothing is on them yet here.


# How much of a unit's frontage stands open to the concourse. Knox County's
# mall has no door at all between a unit and the hall: of 584 boundary
# squares, 305 are wall and 279 are simply open, which is how a shop is
# entered there.
# The rooms in a mall that stand open to the concourse. A lavatory, the
# centre office and the storerooms behind the units keep their wall and door.
GLAZED_UNITS = {"clothesstore", "shoestore", "sewingstore", "electronicsstore",
                "housewarestore", "cornerstore", "optometrist", "departmentstore",
                "giftstore", "toystore", "bookstore", "furniturestore",
                "sportstore", "jewelrystore", "musicstore", "candystore",
                "toolstore", "pharmacy", "generalstore", "gunstore", "bakery",
                "cafe", "foodcourt", "grocery", "conveniencestore"}
SHOP_OPENING = 0.45
MIN_OPENING = 3


def _open_shopfronts(plan: Plan) -> None:
    """Open a run of each unit's frontage, and take its door off it."""
    concourse = {i for i, r in enumerate(plan.rooms, start=1)
                 if r.kind == "concourse"}
    if not concourse:
        return
    h, w = len(plan.grid), len(plan.grid[0])
    runs: dict = {}
    frontage: dict = {}
    for y in range(h):
        for x in range(w):
            here = plan.grid[y][x]
            if not here:
                continue
            for nx, ny, d in ((x - 1, y, "W"), (x, y - 1, "N")):
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                there = plan.grid[ny][nx]
                if not there or there == here:
                    continue
                pair = {here, there}
                if not pair & concourse:
                    continue
                unit = (pair - concourse)
                if not unit:
                    continue
                idx = next(iter(unit))
                if plan.rooms[idx - 1].kind not in GLAZED_UNITS:
                    continue
                runs.setdefault((idx, d, x if d == "W" else y), []).append(
                    y if d == "W" else x)
                frontage.setdefault(idx, set()).add((x, y, d))
    opened = set()
    got_opening: set = set()
    for (idx, d, fixed), along in runs.items():
        along.sort()
        spans, run = [], [along[0]]
        for t in along[1:]:
            if t == run[-1] + 1:
                run.append(t)
            else:
                spans.append(run); run = [t]
        spans.append(run)
        best = max(spans, key=len)
        if len(best) < MIN_OPENING:
            continue
        width = max(MIN_OPENING, round(len(best) * SHOP_OPENING))
        start = best[0] + (len(best) - width) // 2
        for t in range(start, start + width):
            opened.add((fixed, t, d) if d == "W" else (t, fixed, d))
        got_opening.add(idx)
    plan.open_edge |= opened
    # A gap in the wall is the way in, and that is the only way in: the game's
    # mall has not one door between a shop and the concourse, so a unit with
    # an opening gives up every door along its frontage, not just the ones
    # the gap swallowed.
    shut = set(opened)
    for idx in got_opening:
        shut |= frontage.get(idx, set())
    plan.doors = [e for e in plan.doors if e not in shut]


def _merge_concourse(plan: Plan) -> None:
    """Make the whole concourse one room, so no wall runs across it.

    The spine, the galleries and the arms are cut as separate rectangles, and
    a wall appears wherever two rooms meet - which walled the concourse off
    from its own arms and made the hall read as a row of corridors. They all
    become one room here. Its rectangle is the whole box they cover, which
    furnishing is safe with: everything that fills a room checks the grid for
    the tiles that are really its own.
    """
    first = next((i for i, r in enumerate(plan.rooms, start=1)
                  if r.kind == "concourse"), None)
    if first is None:
        return
    rest = [i for i, r in enumerate(plan.rooms, start=1)
            if r.kind == "concourse" and i != first]
    if not rest:
        return
    keep = plan.rooms[first - 1]
    for i in rest:
        room = plan.rooms[i - 1]
        keep.x0, keep.y0 = min(keep.x0, room.x0), min(keep.y0, room.y0)
        keep.x1, keep.y1 = max(keep.x1, room.x1), max(keep.y1, room.y1)
        room.kind = None
    drop = set(rest)
    for y, row in enumerate(plan.grid):
        for x, v in enumerate(row):
            if v in drop:
                row[x] = first
    _renumber(plan)


def _merge_halls(plan: Plan) -> int:
    """Run neighbouring halls together into one concourse.

    Only where the two make a rectangle between them: a Room here is its
    rectangle, and the doors and the furnishing both read it, so an L-shaped
    room would put doors and shelving outside the room. Repeated until nothing
    else will join, which turns a row of corridor cells into one long hall.
    """
    merged = 0
    changed = True
    while changed:
        changed = False
        halls = [(i, r) for i, r in enumerate(plan.rooms, start=1)
                 if r.kind == "hall" and not r.is_core and not r.is_shaft]
        for ai, a in halls:
            for bi, b in halls:
                if ai >= bi or a.kind != "hall" or b.kind != "hall":
                    continue
                side_by_side = (a.y0 == b.y0 and a.y1 == b.y1
                                and (a.x1 + 1 == b.x0 or b.x1 + 1 == a.x0))
                stacked = (a.x0 == b.x0 and a.x1 == b.x1
                           and (a.y1 + 1 == b.y0 or b.y1 + 1 == a.y0))
                if not (side_by_side or stacked):
                    continue
                for y in range(b.y0, b.y1 + 1):
                    for x in range(b.x0, b.x1 + 1):
                        if plan.grid[y][x] == bi:
                            plan.grid[y][x] = ai
                a.x0, a.y0 = min(a.x0, b.x0), min(a.y0, b.y0)
                a.x1, a.y1 = max(a.x1, b.x1), max(a.y1, b.y1)
                b.kind = None          # owns no tiles now; _renumber drops it
                merged += 1
                changed = True
                break
            if changed:
                break
    if merged:
        _renumber(plan)
    return merged


def _renumber(plan: Plan) -> None:
    """Drop rooms that own no tiles and close the gaps in the numbering."""
    used = {v for row in plan.grid for v in row if v}
    if len(used) == len(plan.rooms):
        return
    remap = {}
    kept = []
    for idx, room in enumerate(plan.rooms, start=1):
        if idx in used:
            kept.append(room)
            remap[idx] = len(kept)
    for y in range(plan.height):
        for x in range(plan.width):
            v = plan.grid[y][x]
            if v:
                plan.grid[y][x] = remap[v]
    plan.rooms = kept


def _refit(plan: Plan) -> None:
    """Shrink or grow each room's rectangle to the tiles it actually owns."""
    bounds: dict[int, list[int]] = {}
    for y in range(plan.height):
        for x in range(plan.width):
            v = plan.grid[y][x]
            if v:
                b = bounds.setdefault(v, [x, y, x, y])
                b[0], b[1] = min(b[0], x), min(b[1], y)
                b[2], b[3] = max(b[2], x), max(b[3], y)
    for idx, room in enumerate(plan.rooms, start=1):
        if idx in bounds:
            room.x0, room.y0, room.x1, room.y1 = bounds[idx]


def _paint(plan: Plan) -> None:
    plan.grid = [[0] * plan.width for _ in range(plan.height)]
    for idx, r in enumerate(plan.rooms, start=1):
        for y in range(r.y0, r.y1 + 1):
            for x in range(r.x0, r.x1 + 1):
                if plan.mask is not None and not plan.mask[y][x]:
                    continue
                plan.grid[y][x] = idx

    # The stair shaft is painted over whatever is beneath it, identically on
    # every storey. Stairs used to be dropped wherever five tiles happened to be
    # inside the building, which on 80% of them meant a flight crossing a room
    # boundary and running into an interior wall.
    if plan.core is not None:
        cx0, cy0, cx1, cy1 = plan.core
        plan.rooms.append(Room(cx0, cy0, cx1, cy1, kind="hall", unit=0,
                               is_core=True))
        idx = len(plan.rooms)
        for y in range(cy0, cy1 + 1):
            for x in range(cx0, cx1 + 1):
                plan.grid[y][x] = idx

    _renumber(plan)
    _mend_fragments(plan)
    _refit(plan)


# A room piece smaller than this, or only this thick, is not a room. Along a
# diagonal wall the grid cuts the corners of every rectangle into wedges of a
# few tiles; left alone each became a room of its own - a house turned 38
# degrees came out with 18 rooms, most of them triangles you could not stand in.
SLIVER = 10
SLIVER_THICKNESS = 2


def _too_small(cells, drawn: bool = False) -> bool:
    """Whether a piece of room is a sliver _mend_fragments folds away."""
    if len(cells) < 4:
        return True
    if drawn:
        # Hand-drawn: a strip two tiles thick is a corridor if that is
        # what it was drawn as. Folding those into the room next door ate
        # rooms people had just drawn - draw a room, draw another over
        # part of it, and what was left of the first became part of the
        # second, under a name they never picked.
        return False
    xs = {x for x, _ in cells}
    ys = {y for _, y in cells}
    # A whole rectangle of 3x3 or more is a real room - a small bathroom
    # is exactly that. Only the ragged wedges a diagonal wall leaves go.
    if len(cells) == len(xs) * len(ys) and min(len(xs), len(ys)) >= 3:
        return False
    return len(cells) < SLIVER or (min(len(xs), len(ys)) <= SLIVER_THICKNESS
                                   and len(cells) < 3 * SLIVER)


def _pieces(room: Room, mask: list[list[bool]]) -> list[set[tuple[int, int]]]:
    """The connected pieces of a room left inside the footprint, biggest first."""
    cells = {(x, y) for y in range(room.y0, room.y1 + 1)
             for x in range(room.x0, room.x1 + 1) if mask[y][x]}
    out = []
    while cells:
        stack = [cells.pop()]
        piece = set(stack)
        while stack:
            x, y = stack.pop()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in cells:
                    cells.remove(n)
                    piece.add(n)
                    stack.append(n)
        out.append(piece)
    return sorted(out, key=len, reverse=True)


def _kept_piece(room: Room, mask: list[list[bool]]) -> set[tuple[int, int]]:
    """The biggest connected piece of a room left inside the footprint."""
    return (_pieces(room, mask) or [set()])[0]


def _mend_fragments(plan: Plan) -> None:
    """Split rooms that were cut in two, and fold slivers into a neighbour.

    An irregular footprint or the stair shaft can cut one rectangle into pieces
    that no longer touch. BuildingEd treats them as one room, so the only door
    lands in one piece and the other is sealed; the game then has a room with
    no way in. Each piece becomes a room of its own, and pieces too small to
    be a room are given to whatever they border, preferring the same flat.
    """
    for idx in range(1, len(plan.rooms) + 1):
        cells = {(x, y) for y in range(plan.height) for x in range(plan.width)
                 if plan.grid[y][x] == idx}
        pieces = []
        while cells:
            seed = cells.pop()
            piece = {seed}
            stack = [seed]
            while stack:
                x, y = stack.pop()
                for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if n in cells:
                        cells.remove(n)
                        piece.add(n)
                        stack.append(n)
            pieces.append(piece)
        if len(pieces) <= 1:
            continue
        pieces.sort(key=len, reverse=True)
        base = plan.rooms[idx - 1]
        for piece in pieces[1:]:
            plan.rooms.append(Room(0, 0, 0, 0, kind=base.kind, unit=base.unit))
            new = len(plan.rooms)
            for x, y in piece:
                plan.grid[y][x] = new

    def too_small(cells) -> bool:
        return _too_small(cells, plan.drawn)

    for idx in range(1, len(plan.rooms) + 1):
        if plan.rooms[idx - 1].is_core or plan.rooms[idx - 1].is_shaft:
            continue
        cells = [(x, y) for y in range(plan.height) for x in range(plan.width)
                 if plan.grid[y][x] == idx]
        if not cells or not too_small(cells):
            continue
        unit = plan.rooms[idx - 1].unit
        options: dict[int, int] = {}
        for x, y in cells:
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < plan.width and 0 <= ny < plan.height:
                    v = plan.grid[ny][nx]
                    if v and v != idx and not plan.rooms[v - 1].is_shaft:
                        options[v] = options.get(v, 0) + 1
        if not options:
            continue
        home = max(options, key=lambda v: (plan.rooms[v - 1].unit == unit,
                                           options[v]))
        for x, y in cells:
            plan.grid[y][x] = home

    _renumber(plan)


def _unit_touches_corridor(plan: Plan) -> None:
    """Make every flat one connected piece with a wall on the corridor.

    A flat can be cut in two by a notch in the footprint, and a flat sliced
    where the building narrows can border only its neighbours. Either way,
    some of its rooms could only be reached by walking through somebody
    else's home. Working piece by piece: a piece that reaches the corridor
    stays a flat of its own (split off if it had become separated from the
    rest), and a piece that does not is joined to the neighbouring flat it
    shares most wall with.
    """
    corridor_units = {r.unit for r in plan.rooms if r.unit == 0}
    if not corridor_units:
        return
    for _ in range(len(plan.rooms) + 1):
        adj = _neighbours(plan)
        by_unit: dict[int, list[int]] = {}
        for i, room in enumerate(plan.rooms, 1):
            if room.unit:
                by_unit.setdefault(room.unit, []).append(i)

        def pieces(members: list[int]) -> list[set[int]]:
            left, out = set(members), []
            while left:
                seed = left.pop()
                piece, stack = {seed}, [seed]
                while stack:
                    cur = stack.pop()
                    for n in adj[cur]:
                        if n in left:
                            left.remove(n)
                            piece.add(n)
                            stack.append(n)
                out.append(piece)
            return out

        def reaches(piece: set[int]) -> bool:
            return any(plan.rooms[n - 1].unit == 0 for i in piece for n in adj[i])

        changed = False
        next_unit = max(by_unit, default=0) + 1
        for unit, members in by_unit.items():
            parts = pieces(members)
            if len(parts) == 1 and reaches(parts[0]):
                continue
            touching = [part for part in parts if reaches(part)]
            # Every separate piece that reaches the corridor becomes its own
            # flat; the first keeps the flat's number.
            for extra in touching[1:]:
                for i in extra:
                    plan.rooms[i - 1].unit = next_unit
                next_unit += 1
                changed = True
            for part in parts:
                if reaches(part):
                    continue
                border: dict[int, int] = {}
                for i in part:
                    for n, length in adj[i].items():
                        u = plan.rooms[n - 1].unit
                        if u and n not in part:
                            border[u] = border.get(u, 0) + length
                if not border:
                    continue
                into = max(border, key=lambda u: border[u])
                for i in part:
                    plan.rooms[i - 1].unit = into
                changed = True
            if changed:
                break
        if not changed:
            return


def _boundary_edges(plan: Plan) -> dict[tuple[int, int], list[tuple[int, int, str]]]:
    """(room a, room b) with a < b -> every wall edge between them."""
    out: dict[tuple[int, int], list[tuple[int, int, str]]] = {}
    for y in range(plan.height):
        for x in range(plan.width):
            b = plan.grid[y][x]
            if not b:
                continue
            if x > 0:
                a = plan.grid[y][x - 1]
                if a and a != b:
                    out.setdefault((min(a, b), max(a, b)), []).append((x, y, "W"))
            if y > 0:
                a = plan.grid[y - 1][x]
                if a and a != b:
                    out.setdefault((min(a, b), max(a, b)), []).append((x, y, "N"))
    return out


# How far along a wall a door may sit, as a share of the run, and how much
# wall it keeps beside it. Every door used to go at run[len(run) // 2], dead
# centre of the longest wall, which reads as a corridor of identical openings
# rather than as rooms somebody built. Real doors sit off to one side, but not
# hard against the corner: a frame needs a tile beside it.
DOOR_ALONG = (0.18, 0.82)
DOOR_FROM_CORNER = 1


def _door_spot(edges: list[tuple[int, int, str]], min_run: int,
               rng: random.Random | None = None
               ) -> tuple[tuple[int, int, str], int] | None:
    """A place on the longest straight run of wall, and that run's length.

    Somewhere along the run rather than its middle - see DOOR_ALONG. Without
    an rng it still takes the middle, so callers that want the old certainty
    keep it.
    """
    best = None
    for d in ("W", "N"):
        # Along a W edge the wall runs in y; along an N edge, in x.
        keyed = sorted((e[0], e[1]) if d == "W" else (e[1], e[0])
                       for e in edges if e[2] == d)
        run: list[tuple[int, int]] = []
        for fixed, moving in keyed + [(None, None)]:
            if run and (fixed != run[-1][0] or moving != run[-1][1] + 1):
                if len(run) >= min_run and (best is None or len(run) > best[1]):
                    f, m = run[_along(len(run), rng)]
                    spot = (f, m, "W") if d == "W" else (m, f, "N")
                    best = (spot, len(run))
                run = []
            if fixed is not None:
                run.append((fixed, moving))
    return best


def _along(length: int, rng: random.Random | None) -> int:
    """Which tile of a wall run of this length the door goes on."""
    if rng is None or length < 3:
        return length // 2
    low = max(DOOR_FROM_CORNER, int(length * DOOR_ALONG[0]))
    high = min(length - 1 - DOOR_FROM_CORNER, int(length * DOOR_ALONG[1]))
    if high < low:
        return length // 2
    return rng.randint(low, high)


# How much a door between two kinds of room is worth avoiding. Circulation is
# cheap to open onto; rooms a household uses together are cheap to join; a
# bathroom off a kitchen or a bedroom through another bedroom is not how
# anybody builds.
TOGETHER = [{"livingroom", "kitchen"}, {"kitchen", "dining"},
            {"livingroom", "dining"}]
# A flat's front door, by the room it opens into.
FRONT_DOOR_COST = {"livingroom": 0.0, "openplan": 0.0, "hall": 0.5, "kitchen": 1.5,
                   "dining": 1.5, "storage": 6.0, "bedroom": 7.0,
                   "bathroom": 12.0, "motelroom": 0.0}


# Rooms you sleep, wash or work in. A door between two of them is a room you
# have to walk through to reach another, which is what made a plan read as a
# warren rather than a house - the commonest door in a generated town was one
# bedroom into the next. The one pair a real house does have is a bathroom off
# a bedroom, and the kitchen, dining room and living room share their walls
# openly; everything else goes through the hall.
PRIVATE_ROOMS = {"bedroom", "kidsbedroom", "bathroom", "office", "kitchen",
                 "dining", "storage", "closet", "laundry"}
ENSUITE = ({"bedroom", "bathroom"}, {"kidsbedroom", "bathroom"})
# Dear enough that the tree takes any other way round, cheap enough that a
# room with no other wall to open on is still reached rather than sealed.
PRIVATE_PAIR_COST = 24.0
# What each room already walked through costs. The tree took the cheapest
# door anywhere on the frontier, which strings rooms into a chain: a third of
# the rooms in a big flat sat two doors from the front door and some sat four,
# a bedroom through a bathroom through a kitchen. Hanging a room off one that
# is already deep now costs more than hanging it off one near the door, so
# the plan fans out instead of running away from the entrance.
# At this weight three rooms deep costs more than PRIVATE_PAIR_COST, so in
# theory the tree would rather open a bedroom into a bedroom than go on -
# measured, it does not: that pair is 0.6% of doors at this setting and 0.5%
# at a third of it, because the frontier rarely offers the choice.
DEPTH_COST = 9.0


def _door_cost(a: str, b: str) -> float:
    kinds = {a, b}
    if a == b == "hall":
        # Two halls side by side - the stair core and the landing - open onto
        # each other before either opens onto a bedroom.
        cost = 0.5
    elif "hall" in kinds or "lobby" in kinds:
        cost = 1.0
    elif kinds in TOGETHER:
        cost = 1.5
    elif "livingroom" in kinds:
        cost = 3.0
    elif kinds in ENSUITE:
        cost = 4.0
    elif kinds <= PRIVATE_ROOMS:
        cost = PRIVATE_PAIR_COST
    else:
        cost = 6.0
    # Where Knox County's bathrooms open, counted off the compiled map: 614 of
    # its 807 bathroom doors are onto a living room, 56 onto a kitchen, 36 off
    # a bedroom. Ours had the living room on the dear side of this and did
    # 30% of its bathrooms as bedroom en-suites against the game's 4%, so the
    # commonest arrangement in the game was the one we almost never built.
    if ("bathroom" in kinds
            and not kinds & {"hall", "lobby", "livingroom", "bedroom",
                             "kidsbedroom"}):
        cost += 6.0
    # ...and a bathroom off a bedroom is the exception there, not the rule.
    if kinds in ENSUITE:
        cost += 5.0
    return cost


def _doors(plan: Plan, rng: random.Random) -> None:
    """Connect every room, with as few doors as a real plan would have.

    The old rule put a door on every boundary between two rooms. A floor where
    every room opens into every room it touches is a maze of doorways, not a
    home. This grows a tree outward from the circulation instead - hall, then
    living room - choosing the cheapest door each time, so a bedroom gets the
    one door it needs and a bathroom opens off a hall rather than a kitchen.

    Flats are enforced here as well: rooms of the same flat may open onto each
    other, a flat opens onto the corridor once, and two different flats never
    share a door. Only if a room could otherwise not be reached at all are
    those rules relaxed, one at a time, cheapest first.
    """
    n = len(plan.rooms)
    if n <= 1:
        return
    rooms = plan.rooms
    sealed = {i for i, r in enumerate(rooms, 1) if r.is_shaft}
    edges = {k: v for k, v in _boundary_edges(plan).items()
             if k[0] not in sealed and k[1] not in sealed}

    def start_room() -> int:
        for kind in ("hall", "lobby", "livingroom", "openplan"):
            found = [i for i, r in enumerate(rooms, 1) if r.kind == kind]
            # The stairs arrive in the core: grow from there, or a second hall
            # beside it wins on size and the stairs open into a bedroom.
            at_stairs = [i for i in found if rooms[i - 1].is_core]
            if found:
                return max(at_stairs or found, key=lambda i: rooms[i - 1].area)
        return max(range(1, n + 1), key=lambda i: rooms[i - 1].area)

    connected = {start_room()} | sealed
    front: set[int] = set()
    placed: set[tuple[int, int]] = set()
    doors_of: dict[int, int] = {}
    # How many doors from the way in each connected room is, for DEPTH_COST.
    depth: dict[int, int] = {i: 0 for i in connected}

    # Each pass relaxes one rule, and only for rooms still unreached.
    for relax in range(4):
        min_run = 1
        while True:
            best = None
            for (a, b), wall in edges.items():
                if (a in connected) == (b in connected):
                    continue
                ra, rb = rooms[a - 1], rooms[b - 1]
                if ra.unit != rb.unit:
                    flat = ra.unit or rb.unit
                    if ra.unit and rb.unit:
                        if relax < 3:
                            continue
                    elif flat in front and relax < 3:
                        # A flat has one front door. This was relaxed a
                        # pass earlier, and every room that could not be
                        # reached any other way opened its own way onto the
                        # corridor - 101 flats with two or three of them.
                        continue
                spot = _door_spot(wall, min_run, rng)
                if spot is None:
                    continue
                if ra.unit != rb.unit and not (ra.unit and rb.unit):
                    inner = rb if ra.unit == 0 else ra
                    cost = FRONT_DOOR_COST.get(inner.kind, 3.0)
                else:
                    cost = _door_cost(ra.kind, rb.kind)
                # A wall one tile long takes a door, but only if nothing
                # better exists: skipping them outright sent a bedroom through
                # the bathroom to reach a hall it shared a one-tile wall with.
                if spot[1] < 2:
                    cost += 3.0
                # A bathroom is a room you choose to go into, never a way
                # through to somewhere else: once it has its door it takes no
                # other, so nothing is ever reached by walking through it.
                # This was a cost of 12, which the tree simply paid whenever
                # the way round was dearer - 4.8% of rooms were still reached
                # through one. Only the last relax pass may break it, and that
                # runs when the alternative is a room with no door at all.
                if any(rooms[i - 1].kind == "bathroom" and doors_of.get(i)
                       for i in (a, b)):
                    if relax < 2:
                        continue
                    # Last pass: allowed, but dearer than anything else on
                    # the board, so it happens only where a room would
                    # otherwise have no door at all.
                    cost += 100.0
                cost -= min(spot[1], 6) * 0.05
                # Hanging a room off one that is already deep costs more, so
                # the plan fans out from the way in rather than chaining.
                grown = a if a in connected else b
                cost += DEPTH_COST * depth.get(grown, 0)
                if best is None or cost < best[0]:
                    best = (cost, a, b, spot[0])
            if best is None:
                break
            _, a, b, door = best
            plan.doors.append(door)
            placed.add((a, b))
            doors_of[a] = doors_of.get(a, 0) + 1
            doors_of[b] = doors_of.get(b, 0) + 1
            ra, rb = rooms[a - 1], rooms[b - 1]
            if ra.unit != rb.unit and not (ra.unit and rb.unit):
                front.add(ra.unit or rb.unit)
            grown, fresh = (a, b) if a in connected else (b, a)
            depth[fresh] = depth.get(grown, 0) + 1
            connected.add(a)
            connected.add(b)
        if len(connected) == n:
            break

    # A few extra openings between shared rooms of the same household, so a
    # kitchen opens onto both living and dining rooms instead of being reached
    # only through one of them.
    shared = {"livingroom", "kitchen", "dining", "hall", "lobby"}
    for (a, b), wall in edges.items():
        if (a, b) in placed:
            continue
        ra, rb = rooms[a - 1], rooms[b - 1]
        if ra.unit != rb.unit or ra.kind not in shared or rb.kind not in shared:
            continue
        if ra.unit and (ra.kind == "hall" or rb.kind == "hall"):
            continue
        spot = _door_spot(wall, 3, rng)
        if spot and rng.random() < 0.6:
            plan.doors.append(spot[0])

    # A room whose only way in is a bathroom gets a second door, onto any
    # other room of its own household it touches: nobody should have to walk
    # through the bathroom to reach a bedroom.
    baths = {i for i, r in enumerate(rooms, 1) if r.kind == "bathroom"}
    if baths:
        links: dict[int, set[int]] = {}
        for x, y, d in plan.doors:
            a = _room_at(plan, x - 1, y) if d == "W" else _room_at(plan, x, y - 1)
            b = _room_at(plan, x, y)
            if a and b and a != b:
                links.setdefault(a, set()).add(b)
                links.setdefault(b, set()).add(a)
        for i in range(1, n + 1):
            if i in baths or i in sealed or not links.get(i) or not links[i] <= baths:
                continue
            for (a, b), wall in edges.items():
                other = b if a == i else a if b == i else 0
                if not other or other in baths or other in sealed:
                    continue
                if rooms[a - 1].unit != rooms[b - 1].unit:
                    continue
                spot = _door_spot(wall, 1, rng)
                if spot and spot[0] not in plan.doors:
                    plan.doors.append(spot[0])
                    break


def _room_at(plan: Plan, x: int, y: int) -> int:
    if 0 <= x < plan.width and 0 <= y < plan.height:
        return plan.grid[y][x]
    return 0


def _side_edge(side: str, fixed: int, pos: int) -> tuple[int, int, str]:
    """The wall edge at `pos` along a side line, as _outside_runs keys them."""
    if side in ("N", "S"):
        return (pos, fixed, "N")
    return (fixed, pos, "W")


def _outside_runs(plan: Plan, idx: int) -> list[tuple[str, list[tuple[int, int, str]]]]:
    """A room's exterior walls, as (facing, edges) straight runs, longest first.

    Built per room and per side so that a run is a real stretch of one wall.
    Walking the whole building's edge list instead - every tile's four sides
    interleaved - broke the side walls into runs one tile long, which is why
    windows landed where they did.
    """
    sides: dict[str, dict[int, list[int]]] = {"N": {}, "S": {}, "W": {}, "E": {}}
    for y in range(plan.height):
        for x in range(plan.width):
            if plan.grid[y][x] != idx:
                continue
            if not _room_at(plan, x, y - 1):
                sides["N"].setdefault(y, []).append(x)
            if not _room_at(plan, x, y + 1):
                sides["S"].setdefault(y + 1, []).append(x)
            if not _room_at(plan, x - 1, y):
                sides["W"].setdefault(x, []).append(y)
            if not _room_at(plan, x + 1, y):
                sides["E"].setdefault(x + 1, []).append(y)
    # A wall shared with the next building is not outside.
    for side, lines in sides.items():
        for fixed in list(lines):
            lines[fixed] = [p for p in lines[fixed] if _side_edge(side, fixed, p) not in plan.party]
    runs: list[tuple[str, list[tuple[int, int, str]]]] = []
    for side, lines in sides.items():
        for fixed, positions in lines.items():
            positions.sort()
            run: list[int] = []
            for p in positions + [None]:
                if run and (p is None or p != run[-1] + 1):
                    if side in ("N", "S"):
                        runs.append((side, [(m, fixed, "N") for m in run]))
                    else:
                        runs.append((side, [(fixed, m, "W") for m in run]))
                    run = []
                if p is not None:
                    run.append(p)
    runs.sort(key=lambda r: -len(r[1]))
    return runs


# Where the way in goes, in order of preference. Never straight into a
# bathroom or a bedroom unless there is truly nothing else.
ENTRY_KINDS = ["hall", "lobby", "livingroom", "restaurant", "church",
               "classroom", "clinic", "warehouse", "kitchen", "office",
               "garage", "dining", "storage", "bedroom", "bathroom"]


def _exterior_door(plan: Plan, rng: random.Random,
                   avoid: tuple[int, int] | None = None,
                   street: str | None = None,
                   entrances: list[tuple[float, float, dict]] | None = None) -> None:
    """One way in, into the room a visitor would expect to arrive in.

    `avoid` is the foot of the staircase, so the front door does not open
    straight onto the bottom step.
    """
    if entrances:
        placed = []
        ordered = sorted(entrances, key=_entrance_priority)
        for x, y, tags in ordered:
            edge = _entrance_wall(plan, x, y, tags)
            if edge is None or edge in placed:
                continue
            plan.doors.append(edge)
            placed.append(edge)
        if placed:
            return
    order = {k: i for i, k in enumerate(ENTRY_KINDS)}
    if plan.kind in ("shop", "restaurant"):
        # Customers come in through the shop, not the staff stairs.
        order.update({k: -1 for k in RETAIL_ROOMS | FRONT_ROOMS})
    candidates = sorted((i for i in range(1, len(plan.rooms) + 1)
                         if not plan.rooms[i - 1].is_shaft),
                        key=lambda i: (order.get(plan.rooms[i - 1].kind, 50),
                                       -plan.rooms[i - 1].area))

    def from_stairs(wall) -> float:
        """How far the middle of this wall is from the foot of the stairs."""
        if avoid is None:
            return 0.0
        mid = wall[len(wall) // 2]
        return abs(mid[0] - avoid[0]) + abs(mid[1] - avoid[1])

    def score(run):
        side, wall = run
        # Facing the street, as front doors do; without that the door went on
        # the south wall and half the paths wrapped round houses.
        return (len(wall) >= 3, side == (street or "S"),
                from_stairs(wall), len(wall))

    # The street comes before the room. Taking the best room first and then
    # its best wall put a house's door wherever its hall happened to be, and
    # a hall that does not reach the street side - most of them - turned the
    # house's back on it: 5 houses in 100 had a door on the street. A room
    # anybody would walk in through and a wall on the street beats the room
    # that would have been first; between two such rooms it is the room's own
    # order, then the stairs, then the longer wall, as it always was.
    facing = [(idx, run) for idx in candidates
              if plan.rooms[idx - 1].kind in order
              for run in _outside_runs(plan, idx)
              if run[0] == (street or "S") and len(run[1]) >= 3]
    if not facing:
        # No room anybody would arrive in reaches the street side - a large
        # house cut in wings can have nothing but bedrooms there. Any room
        # but a bathroom or a cupboard on the street beats a door round the
        # back.
        facing = [(idx, run) for idx in candidates
                  if plan.rooms[idx - 1].kind not in ("bathroom", "closet")
                  for run in _outside_runs(plan, idx)
                  if run[0] == (street or "S") and len(run[1]) >= 3]
    if facing:
        idx, (_side, wall) = min(facing, key=lambda ir: (
            order.get(plan.rooms[ir[0] - 1].kind, 50),
            -from_stairs(ir[1][1]), -len(ir[1][1])))
        front = wall[len(wall) // 2]
        plan.doors.append(front)
        _more_ways_in(plan, front)
        return

    for idx in candidates:
        runs = _outside_runs(plan, idx)
        if not runs:
            continue
        side, wall = max(runs, key=score)
        front = wall[len(wall) // 2]
        plan.doors.append(front)
        _more_ways_in(plan, front)
        return


def _widen_vehicle_entry(plan: Plan, street: str | None) -> None:
    """Turn the street-facing garage entry into a three-tile door opening."""
    candidates = []
    for room_id in range(1, len(plan.rooms) + 1):
        for side, wall in _outside_runs(plan, room_id):
            for door in plan.doors:
                if door in wall:
                    candidates.append((side == (street or "S"), len(wall),
                                       door, wall))
    if not candidates:
        return
    _faces_street, _length, entry, wall = max(candidates)
    width = min(3, len(wall))
    center = wall.index(entry)
    start = min(max(0, center - width // 2), len(wall) - width)
    opening = wall[start:start + width]
    ordered = [entry] + sorted((edge for edge in opening if edge != entry),
                               key=lambda edge: (abs(wall.index(edge) - center), edge))

    doors = []
    inserted = False
    for door in plan.doors:
        if door == entry and not inserted:
            doors.extend(ordered)
            inserted = True
        elif door not in opening:
            doors.append(door)
    plan.doors = doors
    # (x, y, dir) triples: entry first (this stays the middle leaf once the
    # opening is centred on it), then its two new neighbours - tbx.py remaps
    # this order to the catalog's actual left/mid/right tiles
    plan.garage_door_tiles = tuple(ordered)

def _entrance_priority(entrance: tuple[float, float, dict]) -> tuple:
    """Main and accessible entrances take precedence when choosing the front."""
    tags = entrance[2]
    value = str(tags.get("entrance") or "yes").lower()
    if value == "main":
        rank = 0 if tags.get("wheelchair") == "yes" else 1
    elif tags.get("wheelchair") == "yes":
        rank = 2
    elif value in ("emergency", "service"):
        rank = 3
    elif value == "exit":
        rank = 5
    else:
        rank = 4
    return rank, entrance[1], entrance[0]


def _entrance_wall(plan: Plan, x: float, y: float,
                   tags: dict) -> tuple[int, int, str] | None:
    """Nearest legal exterior wall edge to one mapped entrance node."""
    if str(tags.get("access") or "").lower() == "no":
        return None
    level = tags.get("level")
    if level not in (None, ""):
        values = [part.strip().lower() for part in str(level).split(";")]
        if "ground" not in values:
            try:
                if not any(float(value) == 0 for value in values):
                    return None
            except ValueError:
                return None

    entrance = str(tags.get("entrance") or "yes").lower()
    preferred = {
        "main": {"lobby", "hall"},
        "emergency": {"clinic", "medical", "firegarage", "policehall", "lobby", "hall"},
        "service": {"storage", "schoolstorage", "firestorage", "kitchen",
                    "diningroom", "warehouse", "firegarage"},
        "exit": {"lobby", "hall"},
    }.get(entrance, set())
    choices = []
    for idx, room in enumerate(plan.rooms, start=1):
        if room.is_shaft:
            continue
        room_rank = 0 if room.kind in preferred else 1
        for _side, wall in _outside_runs(plan, idx):
            for ex, ey, direction in wall:
                if direction == "W":
                    dx = ex - x
                    dy = max(ey - y, 0.0, y - ey - 1)
                else:
                    dx = max(ex - x, 0.0, x - ex - 1)
                    dy = ey - y
                distance = dx * dx + dy * dy
                choices.append((distance, room_rank, ex, ey, direction))
    if not choices:
        return None
    distance, _room_rank, ex, ey, direction = min(choices)
    if distance > 2.25:
        return None
    return ex, ey, direction


# One door per this much exterior wall, in tiles.
#
# A building got exactly one, wherever it landed. On a house that is a front
# door; on a church, a works or a parade of shops a hundred metres round, it
# is one door somewhere along the back, and everyone who walked up to the
# front reported a building with no door anywhere. Real buildings that size
# have several ways in, so these do - about one every thirty-odd metres,
# which is near enough that you meet one whichever side you arrive from.
DOOR_EVERY_TILES = 34
MAX_EXTERIOR_DOORS = 6
# Two doors closer together than this are one entrance, not two.
DOORS_APART_TILES = 12
# Nobody's front door opens into these, and a second one need not either.
PRIVATE_ROOMS = {"bathroom", "bedroom", "kidsbedroom", "closet", "prisoncells"}


def _more_ways_in(plan: Plan, front: tuple[int, int, str]) -> None:
    """Extra doors round a big building, spread along its walls.

    `front` is the door already hung, which the rest keep away from.
    """
    if plan.kind in (None, "house"):
        return          # a house has its front door and its back door
    walls: list[tuple[int, list]] = []
    for idx in range(1, len(plan.rooms) + 1):
        room = plan.rooms[idx - 1]
        if room.is_shaft:
            continue
        private = room.kind in PRIVATE_ROOMS
        for _side, wall in _outside_runs(plan, idx):
            if len(wall) >= 3:
                walls.append((len(wall) - (1000 if private else 0), wall))
    perimeter = sum(len(wall) for _rank, wall in walls)
    want = min(MAX_EXTERIOR_DOORS, perimeter // DOOR_EVERY_TILES)
    placed = [(front[0], front[1])]
    # Longest walls first, and never twice on one stretch or beside a door
    # already hung. Rooms nobody enters a building through come last.
    for _rank, wall in sorted(walls, key=lambda r: -r[0]):
        if len(placed) >= want:
            break
        spot = wall[len(wall) // 2]
        if any(abs(spot[0] - px) + abs(spot[1] - py) < DOORS_APART_TILES
               for px, py in placed):
            continue
        plan.doors.append(spot)
        placed.append((spot[0], spot[1]))


OPPOSITE_SIDE = {"N": "S", "S": "N", "W": "E", "E": "W"}


def _back_door(plan: Plan, street: str | None = None) -> None:
    """A second way out, into the back yard: on the wall facing away from the
    street, from the kitchen if it has that wall, else the room nearest it.

    Knox County's houses have two outside doors as a rule (the median of 546);
    ours had one, and the second one picked any far wall, so it could open
    onto the side of the house instead of the yard behind it.
    """
    if not plan.doors:
        return
    fx, fy, _fd = plan.doors[-1]
    back = OPPOSITE_SIDE.get(street or "S", "N")
    for wanted in (back, None):
        for kind in ("kitchen", "dining", "hall", "livingroom", "laundry", "bedroom"):
            for idx, room in enumerate(plan.rooms, 1):
                if room.kind != kind or room.is_shaft:
                    continue
                runs = [wall for side, wall in _outside_runs(plan, idx)
                        if len(wall) >= 3 and (side == wanted if wanted else
                        abs(wall[len(wall) // 2][0] - fx) + abs(wall[len(wall) // 2][1] - fy) > 6)]
                if runs:
                    wall = max(runs, key=len)
                    plan.doors.append(wall[len(wall) // 2])
                    return


# Tiles of wall per window bay, by what the building is, on its front and on
# its other sides. Not a setting: how glazed a facade is follows from what the
# building is. A tile is about a metre, and real buildings put a window in
# roughly every room-width of wall: a house every four metres or so across its
# front and fewer down the side; flats every three metres on every side, since
# each flat looks out wherever it can; offices and hotels close to a band of
# glass; a works or a barn only a few high windows. The old spacings (nine and
# sixteen tiles for flats) left city blocks looking like warehouses.
FACADE_SPACING = {
    "house": (3, 4), "apartment": (3, 3), "barn": (10, 20), "shed": (12, 24),
    "garage": (12, 24),
    "industrial": (6, 9), "shop": (3, 5), "restaurant": (3, 5),
    "civic": (2, 2), "school": (3, 3), "church": (4, 5), "medical": (3, 3),
}
DEFAULT_FACADE_SPACING = (4, 6)
# Towers are glass: from this many storeys an office or hotel is glazed on
# every tile of its outside wall.
GLASS_TOWER_FROM_LEVELS = 8
# The ground floor of a shop or restaurant is its shop front: glass across the
# front, broken only by the door.
SHOP_FRONT_KINDS = {"shop", "restaurant"}
RETAIL_ROOMS = {"generalstore", "conveniencestore", "clothingstore", "cafe", "grocery",
                "liquorstore", "pharmacy", "bookstore", "toolstore"}
# Buildings laid out like a house, where each room takes only the windows it
# needs. Elsewhere a room takes whatever its stretch of facade offers - an
# open office along a glazed wall is not limited to one window.
HOUSE_LIKE_KINDS = {"house", "barn", "shed", None}
# A house window per this many tiles of a room's outside wall, and the tiles
# kept clear either side of a shuttered window (its shutters, and a gap).
HOUSE_WINDOW_EVERY = 3
WINDOW_CLEARANCE_SHUTTERED = 2
# Most windows one room may take, whatever the facade offers it.
ROOM_WINDOW_CAP = {
    "bathroom": 1, "storage": 1, "hall": 1, "garage": 0, "shed": 1, "elevator": 0,
    "kitchen": 2, "bedroom": 3, "dining": 3, "office": 2, "livingroom": 5,
    "kidsbedroom": 2, "closet": 0, "laundry": 1,
    "generalstore": 6, "conveniencestore": 6, "clothingstore": 6, "cafe": 6,
}
DEFAULT_ROOM_WINDOW_CAP = 4
# Outside house-like buildings a facade keeps its rhythm whatever is behind
# it - a stockroom or washroom on an office front still has its window - so
# only these are capped. Limiting bathrooms and storerooms as in a house left
# a third of an office block's bays empty, holes all over the grid.
SERVICE_WINDOW_CAP = {"garage": 0, "mechanic": 0, "elevator": 0, "shed": 1}
# Rooms that must not be left without daylight.
# Kept to the rooms that matter: guaranteeing every office and dining room a
# window as well pushed facades back up to 1.09 windows per ten tiles of wall.
# Those rooms still get windows from the bays; they just are not promised one.
LIVED_IN = {"livingroom", "openplan", "bedroom", "kidsbedroom", "kitchen",
            "classroom", "restaurant"}
MIN_WALL_FOR_WINDOW = 3
# What "a shelf" is, by the room it stands in.
#
# One generic wooden shelf was on nearly every room's list and was always the
# same sprite, which made it the third commonest object in a town. Varying it
# per home was worse: it put warehouse wire racking in people's bathrooms. A
# shelf is a different piece of furniture in a kitchen, a study and a garage,
# so the room picks, and only a room that would really have one gets the
# racking.
# wall_cabinet is not in here on purpose. It is an upper cabinet that hangs
# above a counter, on the roof layer so it draws over one, and the kitchen
# already puts them there. Offering it as a shelf stood one on any wall with
# nothing underneath, taking floor space it does not stand on.
# "shelf" here means the plain household shelf in any of its styles. It used
# to mean one sprite, furniture_shelving_01_001-004, which is on nearly every
# room's list: it came to 4% of all the furniture in a town, one shelf you saw
# in every house. Knox County's most-used single shelf is 12% of its shelving
# and the rest is spread over a dozen styles, so ours spreads over three.
SHELVES = ("shelf", "shelf_1", "shelf_2")
SHELVING = {
    # Nothing stands along a concourse wall: that edge is the shopfronts.
    "concourse": (),
    "bathroom": SHELVES + ("dresser",),
    "kitchen": SHELVES,
    "laundry": SHELVES + ("dresser",),
    "livingroom": ("bookshelf",) + SHELVES,
    "dining": ("bookshelf",) + SHELVES,
    "bedroom": ("bookshelf",) + SHELVES,
    "kidsbedroom": ("bookshelf",) + SHELVES,
    "hall": SHELVES + ("bookshelf",),
    "office": ("bookshelf", "filing_cabinet"),
    "library": ("bookshelf",),
    "classroom": ("bookshelf",) + SHELVES,
    "storage": ("metal_rack", "crate") + SHELVES,
    "garage": ("metal_rack", "crate"),
    "shed": ("metal_rack",) + SHELVES,
    "warehouse": ("metal_rack", "crate"),
    "factory": ("metal_rack", "crate"),
    "workshop": ("metal_rack",) + SHELVES,
}
DEFAULT_SHELVING = SHELVES + ("bookshelf",)
# What goes on a corridor's walls, and how much of its facade may be used
# before the windows lose their columns. Rugs go on the floor because they
# are the one thing you can walk over.
CORE_WALL_ART = ("painting", "mirror", "painting", "corkboard")
# ...and nothing at all down a workplace corridor.
CORE_WALL_ART_CIVIC: tuple = ()
CORE_FACADE_SHARE = 4
# One piece of art per this many wall slots. Hanging one on every slot filled
# a corridor edge to edge and made pictures the commonest thing in a house.
CORE_ART_EVERY = 3
# Pictures and mirrors a room may hold, however long its wishlist, and how
# often a room gets one at all. They repeat where other things do not and
# they are on nearly every room's list, so almost every room had one or two
# and wall art came to 11.8% of everything in a house. Not every room in a
# house has a picture in it.
WALL_ART_CAP = 1
WALL_ART_CHANCE = 0.55
# Workplaces hang nothing. Knox County's school rooms carry 0.19 pieces of
# wall decoration per 10 m2 and ours sat at 0.21, but with Erika's Tiles
# installed the substitution below turns every picture and mirror into one
# of her 59 wall-art sprites - among them round faces that read as clocks,
# and a school came out with a wall of them. A classroom, a corridor and a
# police office get none.
ART_FREE_KINDS = {"police", "civic", "school", "medical", "fire",
                  "military", "library"}
# Buildings that are places of work, not homes, and the rooms in them whose
# usual wishlist is a domestic one. A station, a school or a clinic gets a
# noticeboard and a water cooler where a house gets a side table and a
# picture.
# Tiles of floor per piece of furniture, where a room is not the usual 4.
ROOM_DENSITY = {"classroom": 2, "secondaryclassroom": 2, "schoollab": 2,
                "library": 3, "prisoncells": 3}
# Warehouse fittings. A house keeps none of them: its box room had a steel
# rack and a packing crate in it, which is a stockroom, not a cupboard under
# the stairs. Barns and sheds are outbuildings and may keep theirs.
WAREHOUSE_ROLES = {"metal_rack", "crate"}
HOME_KINDS = {None, "house", "apartment"}
# What a home puts in a box room instead.
HOME_STORE = {"metal_rack": "shelf", "crate": "dresser"}
CIVIC_KINDS = {"police", "civic", "school", "medical", "fire", "military",
               "library"}
CIVIC_ROOMS = {
    "hall": ["plant", "water_cooler", "chair", "painting", "chair"],
    "lobby": ["shop_counter", "chair", "chair", "plant", "painting",
              "chair", "water_cooler"],
    "office": ["desk", "office_chair", "filing_cabinet", "corkboard",
               "filing_cabinet", "plant"],
    "breakroom": ["counter", "fridge", "chair", "chair", "corkboard",
                  "water_cooler"],
}
CORE_RUGS = ("rug_wide", "rug", "rug_small")
# One rug per this many tiles of corridor. It was 3, chosen to reach '7
# pieces per 10 m2' - a figure read off a per-house median over a filtered
# set of houses, not off the halls themselves. Measured over the whole map,
# a Knox County hall carries 1.2 pieces per 10 m2 of everything and 0.08
# rugs: a corridor there is bare floor, not a runner of carpet.
CORE_RUG_EVERY = 125


def _facade_runs(grid: list[list[int]]) -> list[tuple[str, list[tuple[int, int, str, int, int]]]]:
    """The building's outside walls as straight runs.

    Each edge is (x, y, dir, inside_x, inside_y): where BuildingEd draws the
    wall, and the tile of the building behind it.
    """
    h, w = len(grid), len(grid[0])

    def inside(x, y):
        return 0 <= x < w and 0 <= y < h and grid[y][x]

    lines: dict[tuple[str, int], list[int]] = {}
    for y in range(h):
        for x in range(w):
            if not grid[y][x]:
                continue
            if not inside(x, y - 1):
                lines.setdefault(("N", y), []).append(x)
            if not inside(x, y + 1):
                lines.setdefault(("S", y + 1), []).append(x)
            if not inside(x - 1, y):
                lines.setdefault(("W", x), []).append(y)
            if not inside(x + 1, y):
                lines.setdefault(("E", x + 1), []).append(y)
    runs = []
    for (side, fixed), positions in lines.items():
        positions.sort()
        run: list[int] = []
        for p in positions + [None]:
            if run and (p is None or p != run[-1] + 1):
                edges = []
                for m in run:
                    if side == "N":
                        edges.append((m, fixed, "N", m, fixed))
                    elif side == "S":
                        edges.append((m, fixed, "N", m, fixed - 1))
                    elif side == "W":
                        edges.append((fixed, m, "W", fixed, m))
                    else:
                        edges.append((fixed, m, "W", fixed - 1, m))
                runs.append((side, edges))
                run = []
            if p is not None:
                run.append(p)
    return runs


def _room_edges(grid: list[list[int]]) -> set[tuple[int, int, str]]:
    """The walls BuildingEd draws between one room and the next.

    _facade_runs only knows about the outside of the building. These are just
    as real to the renderer: where a room wall meets the facade on the same
    tile, that tile carries both a west and a north wall and is drawn as one
    corner piece.
    """
    h, w = len(grid), len(grid[0])
    out: set[tuple[int, int, str]] = set()
    for y in range(h):
        for x in range(w):
            here = grid[y][x]
            if not here:
                continue
            if x > 0 and grid[y][x - 1] and grid[y][x - 1] != here:
                out.add((x, y, "W"))
            if y > 0 and grid[y - 1][x] and grid[y - 1][x] != here:
                out.add((x, y, "N"))
    return out


def _sides_of(grid: list[list[int]], x: int, y: int, d: str) -> tuple[int, int]:
    """The room ids either side of a wall edge; 0 is outside."""
    h, w = len(grid), len(grid[0])

    def at(px, py):
        return grid[py][px] if 0 <= px < w and 0 <= py < h else 0

    return (at(x - 1, y), at(x, y)) if d == "W" else (at(x, y - 1), at(x, y))


def _doors_off_corners(storey, edges: set, corners: set) -> int:
    """Slide a door off an inside corner, where there is somewhere to slide to.

    A door has the same trouble a window does - BuildingEd draws a tile
    carrying both a west and a north wall as one corner piece, and a door on
    one comes out as neither door nor wall. On a shipped town map 989 doorways
    of 57,357 sat on one, over 741 buildings, which is what a player reads as
    a door that will not open.

    It moves along its own wall to the nearest tile that is not a corner, and
    where that whole boundary is corners - a stepped diagonal wall is one or
    two tiles long - to a clean wall the room shares with some other
    neighbour. Never at the cost of shutting a room off: every swap is checked
    against the rooms that could be reached before it.
    """
    keep_off = set(storey.party) | set(getattr(storey, "wall_pieces", ()))
    # Every wall that is not a corner, by the pair of rooms it stands between.
    # Sliding along the door's own wall is not enough: a stepped diagonal side
    # is a wall one or two tiles long, so there is nowhere on it to slide to.
    # A door only has to separate the same two spaces, and the rest of that
    # boundary will do.
    boundary: dict[tuple[int, int], list] = {}
    for (ex, ey, ed) in edges:
        if (ex, ey) in corners or (ex, ey, ed) in keep_off:
            continue
        boundary.setdefault(_sides_of(storey.grid, ex, ey, ed), []).append((ex, ey, ed))

    def homes(pair) -> tuple:
        """Which dwellings a wall stands between; -1 is the outside."""
        return tuple(sorted(storey.rooms[r - 1].unit if r else -1 for r in pair))

    def joinable(pair) -> bool:
        """Whether a door may hang between these two rooms at all."""
        a, b = pair
        if a == b or (a and storey.rooms[a - 1].is_shaft) \
                or (b and storey.rooms[b - 1].is_shaft):
            return False
        # Never a door from one person's flat into the next.
        ua, ub = homes(pair)
        return not (ua > 0 and ub > 0 and ua != ub)

    # Not from outside: a floor above the ground has no outside door, so a
    # walk that started there reached nothing and the check below waved
    # everything through. From a room, so it holds on every storey, and with
    # the outside among the rooms it reaches, so a front door cannot be moved
    # indoors either.
    start = next((i for i, r in enumerate(storey.rooms, 1) if not r.is_shaft), 0)

    def reaches(doors) -> set:
        """What can be walked to from inside, through doors alone. 0 is the
        outside, so it is in the set when a way in survives."""
        adj: dict[int, set] = {}
        for (x, y, d) in doors:
            a, b = _sides_of(storey.grid, x, y, d)
            if a == b:
                continue
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
        seen, stack = {start}, [start]
        while stack:
            here = stack.pop()
            # The outside counts as reached, so a way in cannot be moved
            # away, but it is not a corridor: going out of the front door and
            # round to the back is not how a room is got into.
            if here == 0:
                continue
            for nxt in adj.get(here, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    moved = 0
    for i, (x, y, d) in enumerate(storey.doors):
        if (x, y) not in corners:
            continue
        want = _sides_of(storey.grid, x, y, d)
        taken = set(storey.doors)
        before = reaches(storey.doors)
        spots = [s for s in boundary.get(want, ()) if s not in taken]
        if not spots:
            # That boundary is corners end to end. The room still has to open
            # onto something, so any clean wall it shares with a neighbour
            # will do - as long as the door keeps its job. A wall between the
            # same two dwellings only: move a flat's front door onto an inside
            # wall and the flat has no front door, move it onto the corridor
            # somewhere else and the flat it lands on has two.
            mine = {r for r in want if r}
            role = homes(want)
            spots = [s for pair, places in boundary.items()
                     if joinable(pair) and mine & set(pair) and homes(pair) == role
                     for s in places if s not in taken]
        # The nearest first, so a front door stays on the front of the house.
        spots.sort(key=lambda s: (abs(s[0] - x) + abs(s[1] - y), s))
        for spot in spots[:DOOR_SPOTS_TRIED]:
            trial = list(storey.doors)
            trial[i] = spot
            if reaches(trial) >= before:
                storey.doors[i] = spot
                moved += 1
                break
    return moved


def _front_side(building: "Building", kind: str | None) -> set[str]:
    """Which walls count as the front, and get the closer window spacing.

    For a house, the wall with the front door. For a block of flats, both long
    sides: the ends are where the corridor comes out, and the flats look out
    over the street from the sides.
    """
    ground = building.storeys[0]
    if kind == "apartment" and ground.core is not None:
        x0, y0, x1, y1 = ground.core
        return {"W", "E"} if (y1 - y0) >= (x1 - x0) else {"N", "S"}
    for x, y, d in ground.doors:
        # An outside door has building on exactly one side of it.
        if d == "N":
            above, below = _room_at(ground, x, y - 1), _room_at(ground, x, y)
            if bool(above) != bool(below):
                return {"N"} if below else {"S"}
        else:
            left, right = _room_at(ground, x - 1, y), _room_at(ground, x, y)
            if bool(left) != bool(right):
                return {"W"} if right else {"E"}
    return {"S"}


def _bays(by_side: dict, front: set[str], near: int, far: int,
          only: set[str] | None = None) -> list[tuple[int, int, str, int, int]]:
    """Window positions along each side, `near` tiles apart on the front and
    `far` elsewhere. `only` limits them to those sides."""
    bays: list[tuple[int, int, str, int, int]] = []
    for side, edges in by_side.items():
        if only is not None and side not in only:
            continue
        # Position along the side: x for north and south faces, y for west
        # and east.
        along = (lambda e: e[3]) if side in ("N", "S") else (lambda e: e[4])
        positions = sorted({along(e) for e in edges})
        if len(positions) < MIN_WALL_FOR_WINDOW:
            continue
        spacing = max(1, near if side in front else far)
        if side not in front and len(positions) < spacing:
            continue            # a short side stays blank
        inner = positions[1:-1]
        if spacing == 1:
            chosen = set(inner)
        else:
            count = max(1, round(len(inner) / spacing))
            step = len(inner) / count
            chosen = {inner[int((i + 0.5) * step)] for i in range(count)}
        bays.extend(e for e in edges if along(e) in chosen)
    return bays


def _place_windows(building: "Building", kind: str | None,
                   shop_ground: bool = False) -> None:
    """Windows in bays down the facade, the same bays on every storey.

    Two things made the buildings look wrong. Windows were spaced along every
    wall at the same pitch, so a house was as glazed down its side as across
    its front; and each storey placed its own, so no window sat above the one
    below. Real facades are built in bays: the positions are decided once for
    the building and repeated floor by floor, and a storey skips a bay only
    where the room behind has no use for a window.

    How many bays there are is not a setting. It follows from what the
    building is (FACADE_SPACING): a glass tower, a shop front, a block of
    flats and a barn are glazed nothing alike, and one dial for all of them
    could only ever be right for one.

    Bays are counted along each side of the building rather than along each
    straight run of wall. A building on its real footprint at 38 degrees has
    no straight runs at all - its sides are staircases of one- and two-tile
    steps - and requiring three tiles of straight wall left such a house with
    two windows. Counting along the side puts a window every few steps of the
    staircase, the way it would sit on the real diagonal wall.
    """
    if not building.storeys:
        return
    front = _front_side(building, kind)
    near, far = FACADE_SPACING.get(kind or "house", DEFAULT_FACADE_SPACING)
    if kind == "civic" and len(building.storeys) >= GLASS_TOWER_FROM_LEVELS:
        near = far = 1
    by_side: dict[str, list[tuple[int, int, str, int, int]]] = {}
    for side, wall in _facade_runs(building.storeys[0].grid):
        by_side.setdefault(side, []).extend(wall)
    bays = _bays(by_side, front, near, far)
    ground_bays = bays
    glass: list[tuple[int, int, str, int, int]] = []
    glass_set: set = set()
    # A storey stepped back from the ones below has its own outside walls.
    bays_by_grid: dict = {}

    def bays_for(grid):
        key = tuple(tuple(bool(v) for v in row) for row in grid)
        if key not in bays_by_grid:
            sides: dict[str, list] = {}
            for side, wall in _facade_runs(grid):
                sides.setdefault(side, []).extend(wall)
            bays_by_grid[key] = _bays(sides, front, near, far)
        return bays_by_grid[key]

    if kind in SHOP_FRONT_KINDS or shop_ground:
        glass = _bays(by_side, front, 1, far, only=front)
        # Glass only where there is a shop behind it: a block of flats' long
        # sides are both "front", and its offices and toilets were glazed
        # like the shops.
        g0 = building.storeys[0]
        sales = RETAIL_ROOMS | FRONT_ROOMS | {"restaurant"}
        glass = [b for b in glass if g0.grid[b[4]][b[3]]
                 and g0.rooms[g0.grid[b[4]][b[3]] - 1].kind in sales]
        glass_set = set(glass)
        ground_bays = glass + [b for b in bays if b not in glass_set]
    house_like = kind in HOUSE_LIKE_KINDS

    for level, storey in enumerate(building.storeys):
        # Where the floor below put its windows. A house is laid out room by
        # room on every storey, so its rooms upstairs are not the rooms
        # downstairs and its windows landed wherever this floor's rooms
        # happened to want them: looking up at one from the street, 27 of
        # every 100 upstairs windows stood above a window. A wall that has a
        # window below it takes that column first, and the even spacing fills
        # whatever is left.
        under = set(building.storeys[level - 1].windows) if level else set()
        blocked = set(getattr(storey, "wall_pieces", set())) | storey.party
        # No window where a tile carries both a west and a north wall - the
        # inside corner of every step down a diagonal side. BuildingEd draws
        # that corner as one piece; a window there replaced it with a window
        # facing one way, and the other half of the wall was left out.
        #
        # A room wall counts as much as the facade does. This used to ask
        # _facade_runs alone, which only knows the outside of the building, so
        # the corner where a room's wall meets the facade was not blocked -
        # and that is most of them. Counted on a city map: 290 windows over
        # 60 buildings hanging in a gap, every one of them where an inside
        # wall arrives at the outside one on the same tile.
        edges = {(x, y, d) for _side, wall in _facade_runs(storey.grid)
                 for x, y, d, _ix, _iy in wall} | _room_edges(storey.grid)
        on_corner = {(x, y) for x, y, d in edges
                     if (x, y, "N" if d == "W" else "W") in edges}
        blocked |= {(x, y, d) for x, y, d in edges if (x, y) in on_corner}
        # Doors land on those corners too, and break them the same way. They
        # move along their wall rather than being dropped, so nothing is shut
        # in - and it happens before the windows are placed, which keep clear
        # of wherever the doors end up.
        _doors_off_corners(storey, edges, on_corner)
        # Shuttered windows need the tile either side for their shutters: a
        # window two tiles from a door or another window had its shutters
        # jammed against the frame or overlapping the next one's.
        clear = WINDOW_CLEARANCE_SHUTTERED if house_like else 1
        for x, y, d in storey.doors:
            for off in range(-clear, clear + 1):
                blocked.add((x + off, y, d) if d == "N" else (x, y + off, d))
        placed: list[tuple[int, int, str]] = []

        def spaced(x, y, d):
            for px, py, pd in placed:
                if pd != d:
                    continue
                if d == "N" and py == y and abs(px - x) <= clear:
                    return False
                if d == "W" and px == x and abs(py - y) <= clear:
                    return False
            return True

        def add(edge):
            # Never across the hole in a mall floor. That edge is a railing
            # over the concourse below, and glazing it put windows in mid-air
            # inside the building.
            if edge in storey.railing or edge in storey.open_edge:
                return
            storey.windows.append(edge)
            placed.append(edge)

        taken: dict[int, int] = {}
        if house_like and under:
            # Every column the floor below glazed, in one pass over the
            # facade rather than room by room: the room boundaries upstairs
            # are not the ones downstairs, and asking per room left half the
            # columns to the even spacing again.
            where = {(x, y, d): (ix, iy)
                     for _side, wall in _facade_runs(storey.grid)
                     for x, y, d, ix, iy in wall}
            for edge in sorted(under):
                spot = where.get(edge)
                if spot is None or edge in blocked or not spaced(*edge):
                    continue
                idx = storey.grid[spot[1]][spot[0]]
                if not idx:
                    continue
                room = storey.rooms[idx - 1]
                cap = 0 if room.is_core else ROOM_WINDOW_CAP.get(
                    room.kind, DEFAULT_ROOM_WINDOW_CAP)
                if room.is_shaft or taken.get(idx, 0) >= cap:
                    continue
                add(edge)
                taken[idx] = taken.get(idx, 0) + 1
        if house_like:
            # A house's windows are placed room by room, centred on each
            # outside wall and evenly spread along it, as Knox County's are.
            # Bays laid out for the whole facade put two or three windows
            # side by side in one room and none along the rest of the wall.
            for idx, room in enumerate(storey.rooms, 1):
                if room.is_shaft:
                    continue
                cap = ROOM_WINDOW_CAP.get(room.kind, DEFAULT_ROOM_WINDOW_CAP)
                if room.is_core:
                    cap = 0
                runs = sorted(_outside_runs(storey, idx), key=lambda r: -len(r[1]))
                for _side, wall in runs:
                    if taken.get(idx, 0) >= cap or len(wall) < MIN_WALL_FOR_WINDOW:
                        continue
                    n = max(1, min(cap - taken.get(idx, 0),
                                   (len(wall) + 1) // HOUSE_WINDOW_EVERY))
                    for k in range(n):
                        i = int((k + 0.5) * len(wall) / max(1, n))
                        # The nearest spot to the even spacing that is clear
                        # of doors, corners and the other windows.
                        for j in sorted(range(1, len(wall) - 1), key=lambda j: abs(j - i)):
                            edge = wall[j]
                            if edge not in blocked and spaced(*edge):
                                add(edge)
                                taken[idx] = taken.get(idx, 0) + 1
                                break
        for x, y, d, ix, iy in ([] if house_like else (ground_bays if level == 0 else bays_for(storey.grid))):
            if (x, y, d) in blocked:
                continue
            idx = storey.grid[iy][ix]
            if not idx:
                continue
            room = storey.rooms[idx - 1]
            if house_like:
                cap = ROOM_WINDOW_CAP.get(room.kind, DEFAULT_ROOM_WINDOW_CAP)
            else:
                cap = SERVICE_WINDOW_CAP.get(room.kind, 1 << 30)
            if room.is_shaft:
                continue
            # A corridor or stair hall along an outside wall gets that wall's
            # windows like any room: capped at one, a corridor running the
            # length of a tower's side left sixty tiles of blank brick.
            if taken.get(idx, 0) >= cap:
                continue
            add((x, y, d))
            taken[idx] = taken.get(idx, 0) + 1
            if level == 0 and (kind in SHOP_FRONT_KINDS or shop_ground) \
                    and (x, y, d, ix, iy) in glass_set:
                storey.shop_front.add((x, y, d))

        # The bays keep windows in columns, but a room they miss would have no
        # daylight at all. Any room people spend time in that still has none
        # gets one in the middle of its longest outside wall.
        for idx, room in enumerate(storey.rooms, 1):
            if taken.get(idx) or room.kind not in LIVED_IN:
                continue
            for _side, wall in _outside_runs(storey, idx):
                # A straight wall keeps its corners clear; a one- or two-tile
                # step of a diagonal wall has no corners to spare.
                inner = wall[1:-1] if len(wall) >= MIN_WALL_FOR_WINDOW else wall
                candidates = sorted(inner, key=lambda e: abs(
                    wall.index(e) - len(wall) // 2))
                spot = next((e for e in candidates if e not in blocked and spaced(*e)), None)
                if spot is not None:
                    add(spot)
                    taken[idx] = 1
                    break


# A piece against a wall should have its back to that wall. Most pieces define
# all four facings; the few that only define N and W fall back to the nearest.
_ORIENT_FALLBACK = {"S": "N", "E": "W", "N": "N", "W": "W"}


def _facing(role: str, wanted: str) -> str:
    """The orientation to actually emit for `role` against a given wall."""
    have = C.FURNITURE[role]
    if wanted in have:
        return wanted
    alt = _ORIENT_FALLBACK[wanted]
    return alt if alt in have else next(iter(have))


def _cells_for(role: str, x: int, y: int, orient: str) -> list[tuple[int, int]]:
    """Tiles a furniture piece covers, derived from its tile-offset keys."""
    out = []
    for key in C.FURNITURE[role][orient]:
        dx, dy = (int(v) for v in key.split(","))
        out.append((x + dx, y + dy))
    return out


def _wall_anchor(role: str, x: int, y: int, orient: str,
                 wall: str) -> tuple[int, int]:
    """Anchor a multi-tile piece so its footprint ends at the named wall."""
    cells = _cells_for(role, 0, 0, orient)
    if wall == "E":
        x -= max(cx for cx, _cy in cells)
    elif wall == "S":
        y -= max(cy for _cx, cy in cells)
    return x, y


SWITCH = "switch"
# One light switch per this much floor, in tiles, and never more than this
# many in a room. A room of a hundred tiles keeps its single switch; a
# supermarket's sales floor gets one about every eight metres.
LIGHT_EVERY_TILES = 110
MAX_SWITCHES = 8
# How often a room too small to need one by area gets a switch anyway. In a
# house every room has one and there are eight rooms; a school has forty and
# a switch in each came to 0.20 per 10 m2 against Knox County's 0.03 - a
# wall of light switches down every corridor. Workplaces get them sparsely.
# These are the round wall fittings that read as clocks in a render, and
# there were dozens of them: 0.27 per 10 m2 against Knox County's 0.12 over
# the same cells. Not every room in any building has one.
SWITCH_SHARE_CIVIC = 0.14
SWITCH_SHARE_HOME = 0.22
SWITCHES_APART = 7
# Things fixed to a wall rather than standing against it. A painting has only
# north and west sprites, so on a south or east wall the fallback drew it on
# the far edge of the tile, hanging in mid-air a tile into the room; shelves
# and mirrors on those walls rendered as planks floating over the floor. They
# go on north and west walls only. (The switch has true east and south
# sprites, and every room needs one, so it may go anywhere.)
# Pieces that read the same whichever wall they are against: a table has no
# front, so the north sprite on a south wall is not wrong, it is just a table.
_EITHER_WAY = {"table", "coffee_table", "dining_table", "diner_table",
               "picnic_table", "pizza_table", "bath_mat", "rug", "rug_small",
               "rug_wide", "shag_rug", "roof_ac", "roof_vent", "roof_hatch",
               "elevator_door"}
# Anything with no south or east sprite, worked out from the catalogue rather
# than listed by hand. The fallback draws such a piece with its north or west
# sprite, which puts it on the far edge of the tile: a corkboard on a south
# wall hangs a tile into the room, a rack faces its own back. Listing them by
# hand meant a role added later was quietly wrong, which is how 1076 pieces
# in 200 houses ended up against a wall they have no sprite for.
#
# Painting, mirror and shelf are here despite having all four: on a south or
# east wall they render as planks floating over the floor.
NORTH_WEST_ONLY = (
    {role for role, facings in C.FURNITURE.items() if set(facings) <= {"N", "W"}}
    - _EITHER_WAY
    | {"painting", "mirror", "shelf"}
    | set(getattr(C, "ERIKA_WALL_ART", ()))
    | set(getattr(C, "ERIKA_SHOP_ADS", ())))
# With Erika's Tiles: shops hang its drinks and magazine posters instead of
# paintings, and these rooms get a drinks machine.
SHOP_DECOR_ROOMS = {"generalstore", "conveniencestore", "clothingstore", "cafe", "bar",
                    "grocery", "liquorstore", "pharmacy", "bookstore", "toolstore",
                    "restaurant", "gym"}
VENDING_ROOMS = {"cafe", "lobby", "gym", "classroom", "clinic", "breakroom"}
ERIKA_SHELF_SHARE = 0.5

_ERIKA: list[bool] = []
# Set from the map's settings before anything is laid out. None means nobody
# has said, and the answer is whatever is installed.
_ERIKA_ALLOWED: list[bool] = []


def use_mod_tiles(allowed: bool) -> None:
    """Say whether this map may use Erika's Tiles, whatever is installed.

    A map built with the mod's tiles needs the mod to look right, and a player
    who would rather keep to the game's own art - or hand the map to somebody
    who has not subscribed - has no way back once it is built. The settings
    carry the answer (vanilla_tiles), and the build sets it here before the
    first building, because the check below is asked once and remembered.
    """
    _ERIKA_ALLOWED[:] = [bool(allowed)]
    _ERIKA.clear()


def _erika_ready() -> bool:
    """Whether buildings may use Erika's Tiles; asked once per process."""
    if _ERIKA_ALLOWED and not _ERIKA_ALLOWED[0]:
        return False
    if not _ERIKA:
        import os
        try:
            import knoxpaths
            _ERIKA.append(os.environ.get("KNOXMAP_NO_MOD_TILES") != "1"
                          and knoxpaths.erikas_tiles_ready())
        except Exception:      # noqa: BLE001 - no tools, no mod tiles
            _ERIKA.append(False)
    return _ERIKA[0]


def _is_wall_piece(role: str) -> bool:
    """Hung on a wall rather than standing on the floor. Rugs are on their own
    floor layer but are floor pieces: placed as wall pieces, their 2x2
    footprint was never checked against the room and hung out through the
    outside wall, floating beside the building."""
    return C.FURNITURE_LAYERS.get(role, "Furniture") not in ("Furniture", "FloorFurniture")


def _wall_edge(x: int, y: int, facing: str) -> tuple[int, int, str]:
    """The wall a piece facing `facing` on tile (x, y) hangs on, as a door or
    window would name it."""
    if facing == "N":
        return (x, y, "N")
    if facing == "S":
        return (x, y + 1, "N")
    if facing == "W":
        return (x, y, "W")
    return (x + 1, y, "W")


# What stands in the middle of a room, as (role, dx, dy, orient) laid out for
# a room wider than it is deep; turned for the other way. Orient is the side a
# piece has its back to, as for pieces against a wall, so a chair north of a
# table has its back to the north. Rugs go on the floor layer under the rest.
# The group, and a clear tile all round it, has to fit inside the room away
# from the furniture along its walls and the tiles in front of doors, or the
# room keeps an open floor instead. `repeat` is how many a big room may take.
# FALLBACK_GROUPS are smaller sets tried when the first does not fit.
CENTRE_GROUPS: dict[str, tuple[list[tuple[str, int, int, str]], int]] = {
    # The sofa facing the television across the coffee table, an armchair at
    # the side: how every lived-in living room in Knox County is arranged.
    "livingroom": ([("rug_wide", 0, 1, "W"), ("sofa", 0, 0, "N"), ("armchair", 3, 2, "E"),
                    ("coffee_table", 0, 2, "N"), ("tv", 1, 4, "S")], 1),
    "motelroom": ([("double_bed", 0, 0, "W"), ("sidetable", 0, 2, "W"),
                   ("tv", 3, 0, "E"), ("armchair", 3, 2, "W")], 1),
    # An open-plan flat: the same seating, set out in the middle of the floor,
    # because the cooking end has the walls.
    "openplan": ([("rug_wide", 0, 1, "W"), ("sofa", 0, 0, "N"),
                  ("coffee_table", 0, 2, "N")], 1),
    "lobby": ([("rug_wide", 0, 0, "W"), ("coffee_table", 1, 0, "W")], 2),
    "dining": ([("rug_wide", 0, 0, "W"), ("dining_table", 1, 1, "W"),
                ("chair", 0, 1, "W"), ("chair", 3, 1, "E"),
                ("chair", 1, 0, "N"), ("chair", 2, 2, "S")], 1),
    # A mat under the table. Rugs lie on their own layer and block nothing, so
    # it costs the group a row of clearance and nothing else.
    "kitchen": ([("rug_small", 0, 0, "W"), ("round_table", 1, 0, "W"),
                 ("chair", 0, 0, "W"), ("chair", 2, 0, "E")], 1),
    # A canteen is rows of long tables, not one table in the middle.
    "diningroom": ([("dining_table", 1, 1, "W"), ("chair", 0, 1, "W"),
                    ("chair", 3, 1, "E"), ("chair", 1, 0, "N"),
                    ("chair", 2, 2, "S")], 10),
    # A bedroom has no centre group. Its whole group used to be a rug, which
    # put one in every bedroom in the town: 63% of our rugs sat in bedrooms
    # against Knox County's 6%, where two thirds of them are in living
    # rooms. The bed and its tables come from bed_against_wall instead.
    "office": ([("dining_table", 0, 1, "W"), ("chair", 0, 0, "N")], 3),
    "library": ([("dining_table", 1, 1, "W"), ("chair", 0, 1, "W"),
                 ("chair", 3, 1, "E")], 3),
    "classroom": ([("dining_table", 0, 0, "W"), ("chair", 0, 1, "S"),
                   ("chair", 1, 1, "S")], 6),
    "church": ([("table", 2, 0, "W"), ("chair", 0, 2, "S"),
                ("chair", 2, 2, "S"), ("chair", 4, 2, "S"),
                ("chair", 1, 4, "S"), ("chair", 3, 4, "S")], 1),
    "cafe": ([("round_table", 1, 0, "W"), ("chair", 0, 0, "W"),
              ("chair", 2, 0, "E")], 3),
    "restaurant": ([("round_table", 1, 1, "W"), ("chair", 0, 1, "W"),
                    ("chair", 2, 1, "E"), ("chair", 1, 0, "N"),
                    ("chair", 1, 2, "S")], 6),
}
# An exam room's couch stands out from the wall where the doctor can reach
# both sides of it, and a ward's beds stand in rows with room to walk between.
CENTRE_GROUPS["clinic"] = ([("bed_plain", 0, 0, "W")], 1)
CENTRE_GROUPS["medical"] = ([("bed_plain", 0, 0, "W")], 4)
# Every dining room seats people the same way, however it is named; the salon
# and the ice cream parlour have tables too.
# (Dining rooms, cafés and bars are fitted out by interiors.furnish_dining.)
CENTRE_GROUPS["breakroom"] = CENTRE_GROUPS["cafe"]
CENTRE_GROUPS["theatre"] = ([("chair", 0, 0, "S"), ("chair", 1, 0, "S"), ("chair", 2, 0, "S"),
                             ("chair", 3, 0, "S"), ("chair", 4, 0, "S"), ("chair", 5, 0, "S")], 40)
# A stockroom is not one wall of shelving: racks stand out in the floor in
# rows with the boxes beside them, and the aisles between are walked. A home's
# box room gets none (_furnish_middle).
STOCK_GROUP = ([("metal_rack", 0, 0, "N"), ("metal_rack", 0, 1, "N"),
                ("crate", 3, 0, "N"), ("crate", 3, 1, "N")], 4)
STOCKROOMS = {"storage", "warehouse", "factory", "workshop", "armory", "evidenceroom"}
for _kind in list(ROOM_STYLE) + list(STOCKROOMS):
    if (_kind in STOCKROOMS or _kind.endswith("storage")) and _kind not in CENTRE_GROUPS:
        CENTRE_GROUPS[_kind] = STOCK_GROUP
# Commercial kitchens are fitted with counters wall to wall, like a home's.
KITCHENS = {"kitchen", "openplan", "breakroom", "restaurantkitchen", "pizzakitchen", "burgerkitchen",
            "dinerkitchen", "chinesekitchen", "sushikitchen", "mexicankitchen", "seafoodkitchen",
            "cafekitchen", "bakerykitchen", "icecreamkitchen"}
FALLBACK_GROUPS: dict[str, list[list[tuple[str, int, int, str]]]] = {
    "motelroom": [[("double_bed", 0, 0, "W"), ("tv", 3, 0, "E")]],
    "church": [[("table", 1, 0, "W"), ("chair", 0, 2, "S"),
                ("chair", 2, 2, "S")]],
    "livingroom": [[("sofa", 0, 0, "N"), ("coffee_table", 0, 2, "N"), ("tv", 0, 4, "S")],
                   [("sofa", 0, 0, "N"), ("coffee_table", 0, 2, "N")],
                   [("rug_small", 0, 0, "W"), ("coffee_table", 0, 0, "N")]],
    "dining": [[("dining_table", 1, 0, "W"), ("chair", 0, 0, "W"), ("chair", 3, 0, "E")],
               [("round_table", 1, 0, "W"), ("chair", 0, 0, "W"), ("chair", 2, 0, "E")]],
    # Half the game's kitchens have a table in them and one in eight of ours
    # did: the group and its aisle want a five-by-three clear block, and a
    # kitchen four tiles across with two doors in it has nowhere to put one.
    # A table on its own is the last thing tried, as it is what a kitchen too
    # small to eat in still has.
    "kitchen": [[("round_table", 0, 0, "W"), ("chair", 1, 0, "E")],
                [("round_table", 0, 0, "W")]],
    "lobby": [[("rug_small", 0, 0, "W"), ("coffee_table", 0, 0, "N")]],
}
_TURN = {"W": "N", "N": "W", "E": "S", "S": "E"}


# For a television on each wall: where the wall starts, the way along it and
# the way into the room.
_TV_WALLS = {"N": ("x0", "y0", (1, 0), (0, 1)), "S": ("x0", "y1", (1, 0), (0, -1)),
             "W": ("x0", "y0", (0, 1), (1, 0)), "E": ("x1", "y0", (0, 1), (-1, 0))}
_SIDE_OF_VECTOR = {(1, 0): "E", (-1, 0): "W", (0, 1): "S", (0, -1): "N"}
_OPPOSITE_SIDE = {"N": "S", "S": "N", "W": "E", "E": "W"}


def _furnish_living(plan: Plan, idx: int, room: Room,
                    occupied: set[tuple[int, int]],
                    keep_clear: set[tuple[int, int]],
                    palette: dict[str, str], keeps_open=None) -> bool:
    """The television against a wall, the sofa straight across from it facing
    it, the coffee table between, an armchair at the side and a rug under the
    table: how people arrange a living room. Tries each wall and each spot
    along it, the most open first, and takes the first that fits whole. False
    if none does, and the room is laid out the old way."""
    cells = {(x, y) for y in range(room.y0, room.y1 + 1)
             for x in range(room.x0, room.x1 + 1) if _room_at(plan, x, y) == idx}
    if len(cells) < 20:
        return False
    sofa = palette.get("sofa", "sofa")
    armchair = palette.get("armchair", "armchair")
    if any(r not in C.FURNITURE for r in (sofa, armchair, "tv", "coffee_table")):
        return False
    taken = occupied | keep_clear

    def footprint(role, orient, tile):
        """The tiles a piece covers with its middle on `tile`, and its anchor."""
        base = _cells_for(role, 0, 0, orient)
        xs, ys = [c[0] for c in base], [c[1] for c in base]
        px = tile[0] - (min(xs) + (max(xs) - min(xs)) // 2)
        py = tile[1] - (min(ys) + (max(ys) - min(ys)) // 2)
        return (px, py), [(cx + px, cy + py) for cx, cy in base]

    bounds = {"x0": room.x0, "x1": room.x1, "y0": room.y0, "y1": room.y1}
    options = []
    for side, (ox_name, oy_name, along, into) in _TV_WALLS.items():
        origin = (bounds[ox_name], bounds[oy_name])
        length = (room.x1 - room.x0 + 1) if along[0] else (room.y1 - room.y0 + 1)
        depth = (room.y1 - room.y0 + 1) if along[0] else (room.x1 - room.x0 + 1)
        if depth < 5 or length < 3:
            continue

        def tile(a, d, origin=origin, along=along, into=into):
            return (origin[0] + along[0] * a + into[0] * d,
                    origin[1] + along[1] * a + into[1] * d)
        blocked = sum(tile(a, 0) in keep_clear or tile(a, 1) in keep_clear
                      for a in range(length))
        # The windows go in last and along the outside walls, so a television
        # (or a sofa's back) there ends up in front of one: an inside wall
        # first.
        outside = sum(_room_at(plan, tile(a, 0)[0] - into[0], tile(a, 0)[1] - into[1]) == 0
                      for a in range(length))
        options.append((blocked, outside, -min(depth, 8), side, tile, length, depth, along))
    options.sort(key=lambda o: o[:4])

    for _blocked, _outside, _d, side, tile, length, depth, along in options:
        sofa_d = 4 if depth >= 6 else 3
        centre = length // 2
        spots = sorted(range(1, length - 1), key=lambda a: (abs(a - centre), a))
        table_orient = "N" if side in "NS" else "W"
        for a in spots:
            tv_at, tv_cells = footprint("tv", _facing("tv", side), tile(a, 0))
            tb_at, tb_cells = footprint("coffee_table", table_orient, tile(a, 2))
            sf_orient = _facing(sofa, _OPPOSITE_SIDE[side])
            sf_at, sf_cells = footprint(sofa, sf_orient, tile(a, sofa_d))
            tv_orient = _facing("tv", side)
            parts = [("tv", tv_orient, tv_at, tv_cells),
                     ("coffee_table", table_orient, tb_at, tb_cells),
                     (sofa, sf_orient, sf_at, sf_cells)]
            # The armchair at the end of the table, turned to face it.
            for lateral in (1, -1):
                back = _SIDE_OF_VECTOR[(along[0] * lateral, along[1] * lateral)]
                ac_orient = _facing(armchair, back)
                ac_at, ac_cells = footprint(armchair, ac_orient, tile(a + 3 * lateral, 2))
                trial = parts + [(armchair, ac_orient, ac_at, ac_cells)]
                if _living_fits(plan, idx, trial, cells, taken, tile(a, 1), keeps_open):
                    parts = trial
                    break
            else:
                if not _living_fits(plan, idx, parts, cells, taken, tile(a, 1), keeps_open):
                    continue
            rug = "rug_wide" if side in "NS" else "rug"
            rug_at, rug_cells = footprint(rug, "W", tile(a, 2))
            if rug in C.FURNITURE and all(c in cells for c in rug_cells):
                plan.furniture.append((rug, rug_at[0], rug_at[1], "W"))
            for role, orient, at, cs in parts:
                plan.furniture.append((role, at[0], at[1], orient))
                occupied.update(cs)
            occupied.add(tile(a, 1))
            return True
    return False


def _living_fits(plan, idx, parts, cells, taken, gap, keeps_open) -> bool:
    every = [c for _r, _o, _a, cs in parts for c in cs]
    if len(set(every)) != len(every) or gap in taken:
        return False
    if any(c not in cells or c in taken for c in every):
        return False
    return not (keeps_open and not keeps_open(set(every)))


def _furnish_middle(plan: Plan, idx: int, room: Room,
                    occupied: set[tuple[int, int]],
                    keep_clear: set[tuple[int, int]],
                    palette: dict[str, str] | None = None,
                    keeps_open=None) -> int:
    """Put the room's centre group(s) in its open middle. Returns how many.
    keeps_open(tiles), when given, may refuse a spot that cuts the floor."""
    spec = CENTRE_GROUPS.get(room.kind)
    if room.kind == "lobby" and (plan.kind in CIVIC_KINDS or plan.kind == "apartment"):
        spec = ([("shop_counter", 1, 0, "N"), ("chair", 0, 2, "S"),
                 ("chair", 1, 2, "S"), ("chair", 2, 2, "S")], 1)
    if spec is None or room.is_core or room.is_shaft:
        return 0
    if spec is STOCK_GROUP and plan.kind in HOME_KINDS:
        return 0          # a box room in a house is a cupboard, not a stockroom
    palette = palette or {}
    if room.kind == "livingroom" and _furnish_living(
            plan, idx, room, occupied, keep_clear, palette, keeps_open):
        return 1

    def own(group):
        return [(palette.get(role, role), dx, dy, o) for role, dx, dy, o in group]

    group, repeat = spec
    before = len(plan.furniture)
    placed = _place_group(plan, idx, room, own(group), repeat, occupied, keep_clear,
                          keeps_open)
    fallbacks = FALLBACK_GROUPS.get(room.kind, ())
    if room.kind == "lobby" and (plan.kind in CIVIC_KINDS or plan.kind == "apartment"):
        fallbacks = [[("shop_counter", 0, 0, "N"), ("chair", 0, 2, "S")],
                     [("shop_counter", 0, 0, "N")]]
    for smaller in fallbacks:
        if placed:
            break
        placed = _place_group(plan, idx, room, own(smaller), 1, occupied, keep_clear,
                              keeps_open)
    if placed:
        _seat_the_table(plan, idx, keep_clear, plan.furniture[before:], keeps_open)
    return placed


# Every piece in a centre group needs its own clear block and a tile of aisle
# all round the group, so in a kitchen four tiles across only the bare table
# ever fitted: 0.17 chairs a kitchen against the game's 1.10. A chair is
# tucked against the table, not given an aisle of its own, so they go on after
# the group is down.
TABLE_SEATS = 2
_BESIDE = (((-1, 0), "W"), ((1, 0), "E"), ((0, -1), "N"), ((0, 1), "S"))


def _seat_the_table(plan: Plan, idx: int, keep_clear: set[tuple[int, int]],
                    added: list, keeps_open=None) -> None:
    """Chairs on the free tiles beside a table the centre group just put down."""
    tables = [(role, x, y, o) for role, x, y, o in added
              if role in ("round_table", "dining_table")]
    if not tables:
        return
    taken = {c for role, x, y, o in plan.furniture
             if C.FURNITURE_LAYERS.get(role, "Furniture") == "Furniture"
             for c in _cells_for(role, x, y, o)}
    # Only up to what the group would have seated anyway: a dining table that
    # already came with four chairs is not given two more.
    already = sum(1 for role, *_ in added if role == "chair") // len(tables)
    for role, tx, ty, orient in tables:
        seats = already
        for cell in _cells_for(role, tx, ty, orient):
            for (dx, dy), side in _BESIDE:
                if seats >= TABLE_SEATS:
                    break
                x, y = cell[0] + dx, cell[1] + dy
                if (x, y) in taken or (x, y) in keep_clear or _room_at(plan, x, y) != idx:
                    continue
                if keeps_open and not keeps_open({(x, y)}):
                    continue
                plan.furniture.append(("chair", x, y, _facing("chair", side)))
                taken.add((x, y))
                seats += 1


# Pieces a room has one of, however big it is.
ONCE = {"sofa", "tv", "double_bed", "bed", "bath", "toilet", "stove", "fridge", "washer",
        "shower", "kitchen_sink", "sink", "coffee_table", "dining_table", "wardrobe",
        "water_cooler", "whiteboard", "corkboard", "vending"}


def _once(role: str) -> bool:
    return role in ONCE or role.startswith(("sofa_", "double_bed", "bed_", "wardrobe", "erika_vending"))


def _place_group(plan: Plan, idx: int, room: Room,
                 group: list[tuple[str, int, int, str]], repeat: int,
                 occupied: set[tuple[int, int]],
                 keep_clear: set[tuple[int, int]], keeps_open=None) -> int:
    """Up to `repeat` copies of one group, nearest the room's middle first,
    skipping a spot whose solid tiles keeps_open(tiles) refuses."""
    if (room.x1 - room.x0) < (room.y1 - room.y0):
        # Rugs are drawn one way round whatever their orient, so a turned
        # group swaps the wide rug for the long one.
        swap = {"rug_wide": "rug", "rug": "rug_wide"}
        group = [(swap.get(role, role), dy, dx, _TURN[o]) for role, dx, dy, o in group]
    pieces = [(role, dx, dy, _facing(role, o)) for role, dx, dy, o in group]
    shape = [(dx + cx, dy + cy) for role, dx, dy, o in pieces
             for cx, cy in _cells_for(role, 0, 0, o)]
    gx0 = min(x for x, _ in shape)
    gy0 = min(y for _, y in shape)
    gx1 = max(x for x, _ in shape)
    gy1 = max(y for _, y in shape)
    solid = {(dx + cx, dy + cy) for role, dx, dy, o in pieces
             if C.FURNITURE_LAYERS.get(role, "Furniture") == "Furniture"
             for cx, cy in _cells_for(role, 0, 0, o)}
    mid_x, mid_y = (room.x0 + room.x1) / 2, (room.y0 + room.y1) / 2
    spots = sorted(
        ((x, y) for y in range(room.y0 - gy0, room.y1 - gy1 + 1)
         for x in range(room.x0 - gx0, room.x1 - gx1 + 1)),
        key=lambda p: abs(p[0] + (gx0 + gx1) / 2 - mid_x)
        + abs(p[1] + (gy0 + gy1) / 2 - mid_y))
    placed = 0
    for ox, oy in spots:
        if placed >= repeat:
            break
        ring = {(x, y) for y in range(oy + gy0 - 1, oy + gy1 + 2)
                for x in range(ox + gx0 - 1, ox + gx1 + 2)}
        # The aisle round the group may run over the walkway or a doorway's
        # clearance - it is bare floor there - but nothing solid may.
        if any(_room_at(plan, x, y) != idx or (x, y) in occupied for x, y in ring):
            continue
        if any((ox + x, oy + y) in keep_clear for x, y in solid):
            continue
        if keeps_open and not keeps_open({(ox + x, oy + y) for x, y in solid}):
            continue
        for role, dx, dy, o in pieces:
            plan.furniture.append((role, ox + dx, oy + dy, o))
        # The whole footprint and its ring stay clear of the next copy, so
        # tables in a classroom keep an aisle between them.
        occupied.update(ring)
        occupied.update((ox + x, oy + y) for x, y in solid)
        placed += 1
    return placed


def _bathroom_wishlist(area: int, public: bool) -> list[str]:
    if public:
        basins = max(1, min(3, area // 12))
        return [role for _ in range(basins) for role in ("toilet", "sink_public")] \
            + ["mirror"]
    # Biggest fixture first. The tub and the cubicle are two tiles against
    # everything else's one, and with the slots now dealt out in a fixed order
    # rather than shuffled, a toilet and a basin taking the plumbing wall first
    # left no run of two anywhere and 86 of 227 bathrooms got neither - the
    # mat follows the tub it is laid beside, and the mirror the basin it hangs
    # over, so both of those still come after their own fixture.
    fixtures = ["bath" if area >= BATHROOM_TILES else "shower",
                "toilet", "sink", "mirror"]
    # A tub is two tiles and its mat two more, which a bathroom the size this
    # generator aims for takes without trouble: the band above is 9 to 12
    # tiles, matching Knox County's 6.5 m2, and a Knox County bathroom has a
    # bath in it. Asking for 14 asked for more than the generator ever cuts -
    # 1.5% of them - so every bathroom got the shower instead and 378 baths in
    # 200 houses became none. Below the band, in a flat's or a motel's
    # bathroom, there is only room for the shower.
    if area >= BATHROOM_TILES:
        fixtures.append("bath_mat")
    if area >= 18:
        fixtures.append("shelf")
    return fixtures


def _bath_mat_spot(plan: Plan, idx: int, room: Room,
                   occupied: set[tuple[int, int]], keep_clear: set[tuple[int, int]]):
    tub = next(((x, y, orient) for role, x, y, orient in plan.furniture
                if role == "bath" and _room_at(plan, x, y) == idx), None)
    if tub is None:
        return None
    tx, ty, orient = tub
    tub_cells = _cells_for("bath", tx, ty, orient)
    center_x, center_y = (room.x0 + room.x1) / 2, (room.y0 + room.y1) / 2
    candidates = []
    for x, y in tub_cells:
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            ax, ay = x + dx, y + dy
            for mat_orient in C.FURNITURE["bath_mat"]:
                cells = _cells_for("bath_mat", ax, ay, mat_orient)
                if any(_room_at(plan, cx, cy) != idx or (cx, cy) in occupied
                       or (cx, cy) in keep_clear for cx, cy in cells):
                    continue
                mat_x = sum(cx for cx, _cy in cells) / len(cells)
                mat_y = sum(cy for _cx, cy in cells) / len(cells)
                distance = abs(mat_x - center_x) + abs(mat_y - center_y)
                candidates.append((distance, ay, ax, mat_orient, cells))
    if not candidates:
        return None
    _distance, ay, ax, mat_orient, cells = min(candidates)
    return ax, ay, mat_orient, cells


def _door_tiles(plan: Plan) -> set[tuple[int, int]]:
    """Tiles every way in keeps clear, DOOR_CLEAR_DEPTH deep either side."""
    door_tiles: set[tuple[int, int]] = set()
    # An opened shopfront is a way in just as much as a door, so it gets a
    # door's clearance. The game's mall keeps its openings empty; ours had a
    # shelf or a chiller across 64% of them, which is no way into a shop.
    ways_in = list(plan.doors) + sorted(plan.open_edge)
    for x, y, d in ways_in:
        # Two tiles deep either side: one clear tile in front of a door still
        # had a fridge or a bookcase on the next, and nobody could step past.
        for k in range(DOOR_CLEAR_DEPTH):
            door_tiles.add((x + k, y) if d == "W" else (x, y + k))
            door_tiles.add((x - 1 - k, y) if d == "W" else (x, y - 1 - k))
    return door_tiles


SHOP_STAFF_ROOMS = {"storage", "grocerystorage", "office", "bathroom"}


def SHOP_FLOOR_KINDS() -> set:
    from . import interiors
    return set(interiors.STORES)


def _room_walkway(plan: Plan, idx: int, door_tiles: set,
                  stairs: tuple[int, int, str] | None) -> set[tuple[int, int]]:
    """Tiles of room idx nothing standing may cover: a path joining its ways
    in (doors, opened shopfronts, the stair landings), or a spine from its one
    way in, plus the door clearance that touches it. Empty for the core or a
    lift shaft, which take nothing standing anyway.

    Clearance that does not touch the path is left out: the second tile in
    front of a door across a one-tile hall lands in the room beyond, cut off
    from its walkway. door_tiles keeps it clear all the same."""
    r = plan.rooms[idx - 1]
    if r.is_core or r.is_shaft:
        return set()
    cells = {(x, y) for y in range(r.y0, r.y1 + 1) for x in range(r.x0, r.x1 + 1)
             if plan.grid[y][x] == idx}
    entries = []
    shop = r.kind in SHOP_FLOOR_KINDS()
    for x, y, d in list(plan.doors) + sorted(plan.open_edge):
        inside, other = (((x, y), (x - 1, y)) if d == "W" else ((x, y), (x, y - 1)))
        if inside not in cells:
            inside, other = other, inside
        # A shop's customers do not walk to its staff doors: the way through
        # joins the street to the rest of the sales floor, and the stock room
        # and office doors open onto whatever aisle is beside them. Counting
        # them put the walkway along the back wall, where the coolers go.
        if shop and (x, y, d) in plan.doors and _room_at(plan, *other) and                 plan.rooms[_room_at(plan, *other) - 1].kind in SHOP_STAFF_ROOMS:
            continue
        entries += [(x, y), (x - 1, y) if d == "W" else (x, y - 1)]
    if stairs is not None:
        sx, sy, sd = stairs
        dx, dy = (0, 1) if sd == "N" else (1, 0)
        entries += [(sx - dx, sy - dy), (sx + dx * STAIR_RUN, sy + dy * STAIR_RUN)]
    walk = FR.walkway(cells, entries)
    clear = door_tiles & cells
    todo = sorted(walk)
    while todo:
        x, y = todo.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n in clear and n not in walk:
                walk.add(n)
                todo.append(n)
    return walk


def _furnish(plan: Plan, rng: random.Random,
             stairs: tuple[int, int, str] | None = None,
             street: str | None = None) -> None:
    """Push furniture against room walls, skipping tiles a door needs clear.

    Every room, the corridor and stair hall included, first gets a light
    switch on the wall beside its door. The game hangs a room's ceiling light
    off its switch, so a room without one has no light at all - which is why
    so many rooms were pitch dark: the switch was only on some rooms'
    wishlists, and even there it was written to the floor rather than a wall.
    """
    door_tiles = _door_tiles(plan)
    door_edges = set(plan.doors) | set(plan.open_edge)
    # The lift doors take their stretch of wall: nothing hangs on it.
    for _rect, (lx, ly, ld) in plan.shafts:
        door_edges |= {(lx, ly + i, "W") if ld == "W" else (lx + i, ly, "N")
                       for i in range(SHAFT_SIZE)}
    # Tiles of the flight. A switch hung there would be deleted along with the
    # furniture cleared off the staircase, leaving the stair hall dark.
    stair_tiles: set[tuple[int, int]] = set()
    if stairs is not None:
        sx, sy, sd = stairs
        dx, dy = (0, 1) if sd == "N" else (1, 0)
        stair_tiles = {(sx + dx * i, sy + dy * i) for i in range(STAIR_RUN)}

    for _rect, (lx, ly, ld) in plan.shafts:
        plan.furniture.append(("elevator_door", lx, ly, ld))

    from . import interiors
    # Each home its own furniture: one palette per flat, or per storey of a
    # house, drawn from a seed of this storey's own.
    home_seed = rng.random()
    palettes: dict[int, dict[str, str]] = {}

    for idx, r in enumerate(plan.rooms, start=1):
        # A lift car has no switch and no furniture: it is a sealed box.
        if r.is_shaft:
            continue
        start = len(plan.furniture)
        # Walls this room has, as (x, y, facing) for a piece standing on the
        # tile with its back to that wall.
        slots = []
        for y in range(r.y0, r.y1 + 1):
            for x in range(r.x0, r.x1 + 1):
                if plan.grid[y][x] != idx or (x, y) in stair_tiles:
                    continue
                for facing, nx, ny in (("N", x, y - 1), ("S", x, y + 1),
                                       ("W", x - 1, y), ("E", x + 1, y)):
                    if _room_at(plan, nx, ny) != idx:
                        slots.append((x, y, facing))
        used_walls: set[tuple[int, int, str]] = set()
        # Outside walls are where the windows go, and the windows are laid out
        # last, in columns up the facade: a painting or switch hung there took
        # the bay and left a hole in the column. Hang things inside first.
        step = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}

        def on_facade(slot: tuple[int, int, str]) -> bool:
            x, y, facing = slot
            ox, oy = step[facing]
            return not _room_at(plan, x + ox, y + oy)

        def hang(role: str, x: int, y: int, facing: str) -> bool:
            if role in NORTH_WEST_ONLY and facing in ("S", "E"):
                return False
            edge = _wall_edge(x, y, facing)
            if edge in door_edges or edge in used_walls:
                return False
            orient = _facing(role, facing)
            # Every tile of the piece in this room: a two-tile mirror hung at
            # the end of a wall reached through the outside wall.
            if any(_room_at(plan, cx, cy) != idx for cx, cy in _cells_for(role, x, y, orient)):
                return False
            plan.furniture.append((role, x, y, orient))
            used_walls.add(edge)
            plan.wall_pieces.add(edge)
            return True

        # The switch: on a wall one tile from this room's door, the way people
        # actually fit them, or on any wall if the door is awkward.
        mine = [(x, y) for x, y in door_tiles if _room_at(plan, x, y) == idx]
        by_reach = sorted(
            slots,
            key=lambda s: min((abs(s[0] - dx) + abs(s[1] - dy) for dx, dy in mine),
                              default=0) + (4 if on_facade(s) else 0))
        # The game hangs one ceiling light off each switch, and that light
        # only reaches so far, so a sales floor or a warehouse lit by the one
        # switch beside its door was dark everywhere else - "lighting seems
        # somewhat broken". A big room gets a switch every so often, spread
        # out along its walls, the way a real shop is wired.
        # Every room keeps one. The game lights a room from the switch in
        # it, so a room without one is dark whatever the sprite count says -
        # tools/audit_layouts.py fails a plan for it. Thinning these out to
        # match Knox County's 0.12 per 10 m2 left 1,945 rooms unlit, and it
        # was chasing the wrong thing anyway: the round fittings that read as
        # clocks were school_desk, not these.
        floor_switch = 1
        want_switches = max(floor_switch,
                            min(MAX_SWITCHES,
                                r.area // LIGHT_EVERY_TILES))
        lit: list[tuple[int, int]] = []
        for x, y, facing in by_reach:
            if len(lit) >= want_switches:
                break
            if (x, y) in mine and _wall_edge(x, y, facing) in door_edges:
                continue
            if lit and min(abs(x - lx) + abs(y - ly) for lx, ly in lit) < SWITCHES_APART:
                continue
            if hang(SWITCH, x, y, facing):
                lit.append((x, y))
        if not lit and want_switches:
            for x, y, facing in by_reach:
                if hang(SWITCH, x, y, facing):
                    break

        # The walkway: a path joining this room's ways in, or a spine from its
        # one door, that nothing standing may cover. Placed round it rather
        # than cleared afterwards, which deleted toilets and beds along with
        # the plants.
        walk = _room_walkway(plan, idx, door_tiles, stairs)
        keep_clear = door_tiles | stair_tiles | walk
        no_go = door_tiles | walk
        room_cells = {(x, y) for y in range(r.y0, r.y1 + 1)
                      for x in range(r.x0, r.x1 + 1) if plan.grid[y][x] == idx}

        floor = FR.OpenFloor(room_cells, walk, POCKET_TILES)
        counted = [start]

        def keeps_open(tiles) -> bool:
            """Whether a new blocking piece on `tiles` leaves the walkway clear
            and cuts off no patch of floor bigger than a pocket. Only this
            room's pieces have gone in since `start`, and only by appending
            (_stand_on_something inserts once the room is done)."""
            for role, x, y, o in plan.furniture[counted[0]:]:
                if _blocks(role):
                    floor.block(_cells_for(role, x, y, o))
            counted[0] = len(plan.furniture)
            return floor.keeps_open(tiles)
        # Nothing standing goes in the stair hall or corridor: a flat's front
        # door and the only way past the flight both run through it, and one
        # bookcase beside the stairs closes the corridor.
        if r.is_core:
            # The walls are fair game, though, and a rug is walked over.
            # Sparingly: a hall in Knox County holds 1.2 pieces per 10 m2
            # all told, most of it a chair or a light rather than anything
            # underfoot.
            inside = [s for s in slots if not on_facade(s)]
            facade = [s for s in slots if on_facade(s)]
            # Inside walls first and most of the facade left alone, because
            # the windows are laid out last and in columns: a picture on a
            # bay takes it and leaves a hole up the front of the building.
            hung = 0
            for n, slot in enumerate(
                    inside + facade[:max(1, len(facade) // CORE_FACADE_SHARE)]):
                if n % CORE_ART_EVERY:
                    continue
                art_set = (CORE_WALL_ART_CIVIC
                           if plan.kind in ART_FREE_KINDS else CORE_WALL_ART)
                if not art_set:
                    break
                if hang(art_set[hung % len(art_set)], *slot):
                    hung += 1
            laid = 0
            for n, (x, y) in enumerate(
                    (x, y) for y in range(r.y0, r.y1 + 1)
                    for x in range(r.x0, r.x1 + 1)
                    if plan.grid[y][x] == idx and (x, y) not in keep_clear):
                if n % CORE_RUG_EVERY:
                    continue
                # A rug is two or three tiles wide, so every tile of it has to
                # be this room's floor and clear; one hanging over the edge is
                # a rug through the wall.
                order = CORE_RUGS[laid % len(CORE_RUGS):] + CORE_RUGS[:laid % len(CORE_RUGS)]
                for role in order:
                    cells = _cells_for(role, x, y, "N")
                    if any(_room_at(plan, cx, cy) != idx or (cx, cy) in keep_clear
                           for cx, cy in cells):
                        continue
                    plan.furniture.append((role, x, y, "N"))
                    laid += 1
                    break
            continue
        # A shop's sales floor is fitted out as a whole - rows of shelving,
        # the till by the door - not from a list pushed against its walls.
        if r.kind in interiors.STORES and interiors.furnish_store(
                plan, idx, r, rng, door_tiles, stair_tiles | walk, street):
            continue
        pal = palettes.get(r.unit)
        if pal is None:
            pal = palettes[r.unit] = interiors.palette(
                random.Random(f"{home_seed}:{r.unit}"), profile=plan.profile)
        _, _, base = ROOM_STYLE[r.kind]
        occupied: set[tuple[int, int]] = set()
        office = r.kind == "office" and plan.kind not in HOUSE_LIKE_KINDS
        office_fitted = False
        classroom = r.kind == "classroom" and plan.kind in CIVIC_KINDS
        eatery = r.kind in interiors.DINING_ROOMS
        salon = r.kind == "aesthetic" and plan.kind not in HOME_KINDS
        commercial_kitchen = r.kind in interiors.COMMERCIAL_KITCHENS
        if r.kind in ("garage", "mechanic") and interiors.furnish_service_bay(
                plan, idx, r, rng, door_tiles, keep_clear,
                mechanic=(r.kind == "mechanic")):
            continue
        if office:
            base, office_fitted = interiors.furnish_office(
                plan, idx, r, rng, occupied, keep_clear, keeps_open)
        elif classroom:
            base, office_fitted = interiors.furnish_classroom(
                plan, idx, r, rng, occupied, keep_clear, keeps_open)
        elif salon:
            base = interiors.furnish_salon(plan, idx, r, rng, occupied, no_go, keeps_open)
        elif eatery:
            base = interiors.furnish_dining(plan, idx, r, rng, occupied,
                                            stair_tiles | walk, door_tiles, street,
                                            keeps_open)
        elif commercial_kitchen:
            base = interiors.KITCHEN_KIT.get(r.kind, interiors.DEFAULT_KITCHEN_KIT)
        elif r.kind == "bathroom":
            public = plan.kind not in HOUSE_LIKE_KINDS | {"apartment"}
            base = _bathroom_wishlist(r.area, public)
        elif plan.kind in CIVIC_KINDS and r.kind in CIVIC_ROOMS:
            # A police station's corridor is not somebody's hallway. The
            # wishlist for hall and lobby is a domestic one - side table,
            # picture, bookcase, sofa - and a station was getting 8.2 side
            # tables, 6.9 chests and 5.3 pictures a building, which is what
            # reads as a living room with a cell block attached. Knox County
            # furnishes a police office out of location_business_office at
            # 3.15 pieces per 10 m2 and almost nothing else.
            base = list(CIVIC_ROOMS[r.kind])
        if not base:
            # A room with nothing on its wishlist: the lift shaft, which the
            # builder puts in as machinery rather than a room, and anything
            # drawn as one by hand (knoxbuild/designer.py). Nothing to stand
            # in it, and asking for one piece in a list of none used to end
            # the whole building in "integer modulo by zero".
            continue
        shelving = [s for s in SHELVING.get(r.kind, DEFAULT_SHELVING)
                    if s in C.FURNITURE] or ["shelf"]
        if plan.kind in HOME_KINDS:
            # No warehouse racking in somebody's house.
            keep = [s for s in shelving if s not in WAREHOUSE_ROLES]
            shelving = keep or ["shelf"]
        base = [rng.choice(shelving) if role == "shelf" else pal.get(role, role)
                for role in base]
        if plan.kind in HOME_KINDS:
            base = [HOME_STORE.get(role, role) for role in base]
        if _erika_ready():
            # With Erika's Tiles installed, pictures and plants come from its
            # far larger range, so no two living rooms hang the same print.
            shop = r.kind in SHOP_DECOR_ROOMS
            base = [rng.choice(C.ERIKA_SHOP_ADS) if role == "painting" and shop and C.ERIKA_SHOP_ADS
                    else rng.choice(C.ERIKA_WALL_ART)
                    if role in ("painting", "mirror") and C.ERIKA_WALL_ART
                    and plan.kind not in ART_FREE_KINDS
                    and not (role == "mirror" and (salon or r.kind == "bathroom"))
                    else rng.choice(C.ERIKA_PLANTS)
                    if role == "plant" and C.ERIKA_PLANTS and plan.kind in HOME_KINDS
                    else rng.choice(C.ERIKA_SHELVES)
                    if role == "bookshelf" and C.ERIKA_SHELVES and rng.random() < ERIKA_SHELF_SHARE
                    else role for role in base]
            if r.kind in VENDING_ROOMS and C.ERIKA_VENDING:
                base = base + [rng.choice(C.ERIKA_VENDING)]
        # Scale the wishlist with floor area, or a 12x9 living room ends up
        # with four items rattling around in it.
        # Knox County's rooms hold 8-13 pieces per 10 m2 of floor (counting
        # each tile a piece covers); one piece per 7 tiles gave 3-4. Only the
        # small things repeat: a big living room got a second sofa and
        # television, a big bathroom two baths.
        # A house's laundry is mostly not in the kitchen. Knox County has a
        # washer or dryer in 16% of its kitchens; ours had one in 80%, because
        # anything on the wishlist proper is placed every time. Added before
        # the target is counted, so it is one of the pieces the room is worth
        # rather than an extra on top.
        if r.kind == "kitchen" and rng.random() < LAUNDRY_IN_KITCHEN:
            base = base + ["washer"]
        # One piece per four tiles, which is 2.5 per 10 m2 - about what a
        # living room or a bedroom holds. A room packed with furniture by
        # its nature gets more: Knox County's classrooms run to 8.2 pieces
        # per 10 m2, nearly all of them desks, and at the standard rate ours
        # could only reach 1.36 of 2.97.
        per = ROOM_DENSITY.get(r.kind, 4)
        if plan.profile:
            per = max(1, round(per * (1.18 - 0.36 * plan.profile.clutter)))
        target = max(len(base), min(40, r.area // per))
        if (eatery or salon or commercial_kitchen or office_fitted
                or r.kind in {"bathroom", "theatre"}):
            target = len(base)       # fitted out; nothing more to scatter
        wishlist = []
        art_chance = WALL_ART_CHANCE
        art_cap = WALL_ART_CAP
        if plan.profile:
            art_chance = max(0.2, min(0.85,
                                     art_chance + (plan.profile.wealth - 0.5) * 0.25
                                     - plan.profile.wear * 0.12))
            if plan.profile.wealth >= 0.78 and plan.profile.wear < 0.3:
                art_cap = 2
        art = (art_cap if plan.kind in ART_FREE_KINDS
               else 0 if rng.random() < art_chance else art_cap)
        for i in range(target):
            role = base[i % len(base)]
            if i >= len(base) and _once(role):
                continue
            # Pictures and mirrors are the one thing that repeats freely, so
            # scaling the list with floor area turned a big room into a
            # gallery. Everything else keeps its share.
            if role in ("painting", "mirror") or role.startswith(("erika_art", "erika_ad")):
                if art >= art_cap:
                    continue
                art += 1
            # Counters have a budget of their own (_counter_runs), and the
            # wishlist cycling round put a big kitchen over it before the
            # budget was ever consulted.
            if role.startswith("counter") and wishlist.count(role) >= WISHLIST_COUNTERS:
                continue
            wishlist.append(role)
        plumbing_rooms = KITCHENS | {"kitchen", "bathroom", "laundry"}
        side_scores = {side: [0, 0, 0] for side in step}
        for x, y, facing in slots:
            dx, dy = step[facing]
            neighbor = _room_at(plan, x + dx, y + dy)
            linked_plumbing = (neighbor and neighbor != idx
                               and r.kind in plumbing_rooms
                               and plan.rooms[neighbor - 1].kind in plumbing_rooms)
            side_scores[facing][0] += int(bool(linked_plumbing))
            side_scores[facing][1] += int(not on_facade((x, y, facing)))
            side_scores[facing][2] += 1
        side_order = sorted(step, key=lambda side: (
            -side_scores[side][0], -side_scores[side][1], -side_scores[side][2], side))
        side_rank = {side: rank for rank, side in enumerate(side_order)}
        door_frontier = [(x, y) for x, y in door_tiles
                         if _room_at(plan, x, y) == idx]

        def slot_order(slot):
            x, y, facing = slot
            distance = min((abs(x - dx) + abs(y - dy) for dx, dy in door_frontier),
                           default=0)
            return side_rank[facing], -distance, y, x

        floor_slots = sorted(slots, key=slot_order)
        # Boxes are not a wall of them: a few, apart, some stacked two high.
        crates: set[tuple[int, int]] = set()
        crate_cap = max(2, len(floor_slots) // CRATE_ONE_IN)

        def centre():
            # The middle, with an aisle round it the wall pieces must leave
            # free; placed after them, it almost never found room.
            before = len(plan.furniture)
            if not office and not eatery:
                _furnish_middle(plan, idx, r, occupied, keep_clear, pal, keeps_open)
            # The center group already supplied its focal pieces; do not add
            # them again from the room wishlist.
            for role, *_ in plan.furniture[before:]:
                consumed = (_once(role)
                            or (r.kind == "church" and role == "table")
                            or (r.kind == "livingroom" and role.startswith("armchair"))
                         or (r.kind in ("clinic", "medical") and role.startswith("bed"))
                         or (r.kind == "motelroom" and role == "sidetable")
                            or (r.kind == "lobby"
                                and (plan.kind in CIVIC_KINDS or plan.kind == "apartment")
                                and role == "shop_counter"))
                if role in wishlist and consumed:
                    wishlist.remove(role)

        def place(role):
            if role == "bath_mat":
                # A mat is walked over, so it may lie on the walkway.
                mat = _bath_mat_spot(plan, idx, r, occupied, door_tiles | stair_tiles)
                if mat is not None:
                    mx, my, mat_orient, mat_cells = mat
                    plan.furniture.append((role, mx, my, mat_orient))
                    occupied.update(mat_cells)
                return
            if role == "mirror" and r.kind == "bathroom":
                basin = next(((x, y, orient) for basin_role, x, y, orient
                              in plan.furniture
                              if _is_sink(basin_role) and _room_at(plan, x, y) == idx),
                             None)
                if basin is not None:
                    bx, by, facing = basin
                    near_basin = sorted(
                        (slot for slot in slots if slot[2] == facing),
                        key=lambda slot: abs(slot[0] - bx) + abs(slot[1] - by))
                    for slot in near_basin:
                        if not hang("mirror", *slot):
                            continue
                        mirror_orient = _facing("mirror", slot[2])
                        occupied.update(_cells_for("mirror", slot[0], slot[1],
                                                   mirror_orient))
                        return
            if _is_wall_piece(role):
                for x, y, facing in sorted(floor_slots, key=on_facade):
                    if hang(role, x, y, facing):
                        break
                return
            for (x, y, wanted) in floor_slots:
                if role in NORTH_WEST_ONLY and wanted in ("S", "E"):
                    continue
                orient = _facing(role, wanted)
                ax, ay = _wall_anchor(role, x, y, orient, wanted)
                cells = _cells_for(role, ax, ay, orient)
                if any(c in occupied or c in no_go for c in cells):
                    continue
                if any(_room_at(plan, cx, cy) != idx for cx, cy in cells):
                    continue
                front = set()
                if _needs_front(role):
                    # A fridge, a stove or a wardrobe is opened from the tile
                    # in front of it; that tile stays floor.
                    fx, fy = {"N": (0, 1), "S": (0, -1), "W": (1, 0), "E": (-1, 0)}[wanted]
                    front = {(cx + fx, cy + fy) for cx, cy in cells} - set(cells)
                    if any(c in occupied or _room_at(plan, *c) != idx for c in front):
                        continue
                if role == "crate" and (len(crates) >= crate_cap or any(
                        n in crates for cx, cy in cells
                        for n in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)))):
                    continue
                # Nothing standing that shuts off a patch of the floor.
                if _blocks(role) and not keeps_open(cells):
                    continue
                occupied.update(cells)
                occupied.update(front)
                plan.furniture.append((role, ax, ay, orient))
                if role == "crate":
                    crates.update(cells)
                    if rng.random() < CRATE_STACKED:
                        plan.furniture.append(("crate_top", ax, ay, orient))
                return

        # Most important first, so a plant cannot take the fridge's place:
        # the whiteboard, the centre group if it holds an essential (the
        # sofa), the bed, the other essentials, the centre group otherwise,
        # then the rest, secondary before decoration.
        if r.kind == "classroom" and "whiteboard" in wishlist:
            preferred = "N" if r.w >= r.h else "W"
            board_slots = sorted(
                (s for s in slots if s[2] == preferred),
                key=lambda s: (on_facade(s),
                               abs(s[0] - (r.x0 + r.x1) / 2)
                               + abs(s[1] - (r.y0 + r.y1) / 2)))
            for slot in board_slots:
                if hang("whiteboard", *slot):
                    wishlist.remove("whiteboard")
                    break
        centre_first = any(
            FR.priority(pal.get(role, role), r.kind) == FR.ESSENTIAL
            for role, *_ in CENTRE_GROUPS.get(r.kind, ((), 0))[0])
        if centre_first:
            centre()
        # A bed goes head to a wall between its bedside tables.
        if r.kind in ("bedroom", "kidsbedroom"):
            bed = next((role for role in wishlist if role in (pal.get("double_bed"), pal.get("bed"))
                        or role.startswith(("double_bed", "bed"))), None)
            if bed and interiors.bed_against_wall(plan, idx, r, slots, occupied, no_go,
                                                  bed, "sidetable", keeps_open):
                wishlist.remove(bed)
                if "sidetable" in wishlist:
                    wishlist.remove("sidetable")
        for role in [x for x in wishlist if FR.priority(x, r.kind) == FR.ESSENTIAL]:
            place(role)
        if not centre_first:
            centre()
        for role in FR.in_priority_order(
                [x for x in wishlist if FR.priority(x, r.kind) != FR.ESSENTIAL], r.kind):
            place(role)

        if commercial_kitchen:
            # Steel counters, and no wall cupboards or microwave. A working
            # kitchen really is worktop wall to wall, so it keeps no budget.
            _counter_runs(plan, idx, slots, occupied, no_go, stair_tiles,
                          "counter_2", cabinets=False, keeps_open=keeps_open)
        elif r.kind in KITCHENS:
            _counter_runs(plan, idx, slots, occupied, no_go, stair_tiles,
                          pal.get("counter", "counter"), area=r.area, rng=rng,
                          keeps_open=keeps_open)
        _stand_on_something(plan, idx, r, pal)


# Pieces drawn at worktop height: a sink, a television, a table lamp, a pot
# plant. Put down on their own they float over bare floor - a sink plumbed into
# the ground - so each gets something to stand on first, the way the game's
# own houses have them. Found by the height of their sprites (a floating
# piece's lowest pixel sits well above the floor diamond); the television is
# drawn standing, but no home keeps one on the carpet.
# Pieces drawn with their base part-way up the tile, so they need something
# under them. Sinks are matched by name as well: three more were added with
# the sink variety and every one of them hung in the air, because the set was
# a list of the two that existed at the time.
SURFACE_ROLES = {"kitchen_sink", "sink", "lamp", "tv", "register"}


def _is_sink(role: str) -> bool:
    return role != "sink_public" and role.startswith(("sink", "kitchen_sink"))
WORKTOP_ROOMS = ({"kitchen", "bathroom", "laundry", "breakroom", "openplan"}
                 | KITCHENS)
# Opened from the front: the tile before them is kept clear.
FRONT_CLEAR_ROLES = {"fridge", "stove", "stove_alt", "washer", "dryer", "wardrobe",
                     "bookshelf", "dresser", "dresser_alt", "filing_cabinet"}
DOOR_CLEAR_DEPTH = 2


def _needs_front(role: str) -> bool:
    return role in FRONT_CLEAR_ROLES or role.startswith(("wardrobe", "dresser", "fridge"))


def _needs_surface(role: str) -> bool:
    return role in SURFACE_ROLES or _is_sink(role) or role.startswith("erika_plant")


# Sprite geometry, read off the tiles themselves. A small thing is drawn with
# its base part-way up its 256-pixel tile, and whatever it stands on has to
# reach that high or it hangs in the air: a lamp's base is 153 pixels down and
# a pot plant's 151, a bedside chest's top edge is at 97 and a counter's at
# 125, but a coffee table's is at 172. A lamp on a coffee table floated a
# quarter of a tile above it. Knox County stands 180 of its 270 table lamps on
# furniture_storage_01, a bedside chest, and not one of them on a low table.
LOW_TABLES = {"table", "sidetable", "coffee_table"}
# What goes under one instead. Both of these are tiles the game itself puts
# lamps on (furniture_storage_01 8 and 12).
NIGHTSTANDS = ("dresser", "dresser_alt")


def _stand_on_something(plan: Plan, idx: int, room: Room, palette: dict) -> None:
    """A counter, a chest or a table under every piece of this room that needs
    one and does not have one - and a taller one under anything left standing
    on a piece too low to reach it."""
    standing: set[tuple[int, int]] = set()
    low: dict[tuple[int, int], int] = {}
    mine = []
    for n, (role, x, y, o) in enumerate(plan.furniture):
        if _room_at(plan, x, y) != idx or _is_wall_piece(role):
            continue
        mine.append(n)
        if _needs_surface(role):
            continue
        cells = _cells_for(role, x, y, o)
        if role in LOW_TABLES:
            for cell in cells:
                low[cell] = n
        else:
            standing.update(cells)
    added, swapped = [], []
    for n in mine:
        role, x, y, o = plan.furniture[n]
        if not _needs_surface(role) or (x, y) in standing:
            continue
        if room.kind in WORKTOP_ROOMS or _is_sink(role) or role == "register":
            support = palette.get("counter", "counter")
        elif role == "tv":
            support = "dresser"
        else:
            support = ("filing_cabinet"
                       if plan.kind in CIVIC_KINDS
                       and "filing_cabinet" in C.FURNITURE
                       else NIGHTSTANDS[(x + y) % len(NIGHTSTANDS)])
        if support not in C.FURNITURE:
            continue
        # A lamp already sitting on a coffee table: the table goes, the chest
        # takes its place, rather than two pieces on the one tile.
        under = low.pop((x, y), None)
        if under is not None:
            swapped.append((under, (support, x, y, _facing(support, o))))
        else:
            added.append((n, (support, x, y, _facing(support, o))))
        standing.add((x, y))
    for n, piece in swapped:
        plan.furniture[n] = piece
    # Each support goes in just before its piece, so it is drawn underneath.
    for n, piece in sorted(added, reverse=True):
        plan.furniture.insert(n, piece)


# Counter and cupboard are the same tileset (fixtures_counters_01: the wall
# cupboards are 24-27), so Knox County's kitchens are counted together: 3.9
# pieces over a median 21 m2, which is the rate below. Filling both long walls
# end to end instead put 7.1 in ours - a galley of worktop with a gangway down
# the middle. The figure this was first tuned against, 12 per 10 m2, was every
# piece of furniture in the room, not the counters.
COUNTER_PER_M2 = 0.186
# Counters come first out of that budget and cupboards take what is left, so a
# small kitchen is worktop rather than cupboard doors.
CABINET_SHARE = 0.4
# Knox County cooks on 1.2 appliances and the stove is one of them, so a
# microwave is the exception rather than the rule.
MICROWAVE_SHARE = 0.2
# How often a house keeps its washing machine in the kitchen rather than a
# laundry, a bathroom or the garage. Knox County: 16% of kitchens.
LAUNDRY_IN_KITCHEN = 0.16

# What a room kind's floor may be, in the shares Knox County lays them. Each
# building draws once per kind, so a town has variety between houses while one
# house stays coherent. Measured over 86,045 interior tiles: a bedroom is
# tilesandwood_01_42 a third of the time and carpet the rest, a bathroom is
# almost always hard tile, a hall has its own runner.
FLOOR_CHOICES = {
    "bedroom":     ["wood_pale", "carpet_brown", "carpet_grey",
                    "carpet_green", "carpet_beige"],
    "kidsbedroom": ["carpet_grey", "carpet_brown", "carpet_green",
                    "wood_pale", "carpet_red"],
    "livingroom":  ["wood_pale", "wood_pale", "carpet_brown", "wood_mid",
                    "carpet_grey"],
    "openplan":    ["wood_pale", "wood_mid", "carpet_brown", "wood_dark"],
    "dining":      ["wood_pale", "wood_pale", "wood_mid", "carpet_grey"],
    "diningroom":  ["wood_pale", "wood_pale", "wood_mid", "carpet_grey"],
    "kitchen":     ["wood_pale", "wood_mid", "tile_small", "tile_grey"],
    "bathroom":    ["tile_white", "tile_white", "tile_grey", "tile_cream",
                    "wood_mid"],
    # No hall_runner (tilesandwood_01_28). It was picked because it is 44% of
    # the hall *tiles* in Knox County - but that is a handful of big halls,
    # and by room it is 2 of 33. The halls the game actually builds are
    # tilesandwood 42, 45, 44 and 17, which are plain; _28 has a line through
    # it that tiles into a grid across a floor.
    "hall":        ["wood_pale", "wood_mid", "office_grey", "civic_pale"],
    "closet":      ["wood_pale", "wood_pale", "wood_pale", "wood_dark"],
    "office":      ["wood_mid", "carpet_red", "carpet_brown", "carpet_grey"],
}

# Floors for the rooms of a particular kind of building, where they differ
# from the house ones above. A station's hall is not somebody's hallway, and
# the runner measured over houses looked like carpet down the middle of a
# police station. Knox County floors its stations hard throughout - its cells
# are one tile and nothing else - and the offices it does carpet are left
# uncarpeted here on purpose.
KIND_FLOOR_CHOICES = {
    "garage": {
        "garage": ["tile_grey", "civic_scuff"],
        "mechanic": ["tile_grey", "civic_scuff"],
    },
    "school": {
        "classroom":    ["wood_pale", "school_pale", "school_warm"],
        "secondaryclassroom": ["wood_pale", "school_pale"],
        "schoollab":    ["wood_pale", "school_pale"],
        "gym":          ["wood_pale"],
        "library":      ["school_wood", "wood_pale"],
        "lobby":        ["school_pale", "school_warm", "wood_mid",
                         "school_wood"],
        "hall":         ["school_pale", "wood_pale", "school_warm"],
        "diningroom":   ["wood_pale", "school_pale"],
        "schoolstorage": ["school_warm", "wood_pale"],
        "sportstorage": ["school_warm", "wood_pale"],
        "office":       ["school_wood", "wood_mid"],
        "janitor":      ["civic_scuff", "school_warm"],
        "bathroom":     ["tile_white", "tile_cream", "civic_pale"],
    },
    "police": {
        "hall":              ["civic_hall", "civic_pale", "civic_grey"],
        "prisoncells":       ["civic_hall"],
        "policeoffice":      ["civic_pale", "civic_grey", "civic_hall"],
        "policehall":        ["civic_hall", "civic_pale"],
        "policelocker":      ["civic_pale", "civic_scuff"],
        "policegunstorage":  ["civic_pale", "civic_grey", "civic_scuff"],
        "policeoutfitstorage": ["civic_pale", "civic_scuff"],
        "policearchive":     ["civic_pale", "civic_grey"],
        "officestorage":     ["civic_pale", "civic_scuff"],
        "interrogationroom": ["civic_pale", "civic_grey"],
        "security":          ["civic_pale", "civic_grey"],
        "breakroom":         ["civic_pale", "civic_worn"],
        "janitor":           ["civic_scuff", "civic_worn"],
        "bathroom":          ["civic_pale", "civic_worn"],
        "office":            ["civic_pale", "civic_grey"],
        "storage":           ["civic_scuff", "civic_pale"],
    },
}
# The most counters a wishlist may ask for however big the room; past this the
# budget above decides.
WISHLIST_COUNTERS = 2
# Boxes against a wall: at most one wall slot in this many, never two side by
# side, and this share of them with another box on top.
CRATE_ONE_IN = 6
CRATE_STACKED = 0.5


def _counter_runs(plan: Plan, idx: int, slots, occupied: set,
                  door_tiles: set, stair_tiles: set, counter: str = "counter",
                  cabinets: bool = True, area: int = 0,
                  rng: random.Random | None = None, keeps_open=None) -> None:
    """Fitted counters along a kitchen's two longest walls, up to what the
    floor is worth.

    Knox County sets the sink and stove into a run of worktop rather than
    standing them against bare wall, so the gaps along the two longest walls
    fill with counters - but only as far as COUNTER_PER_M2, and never in front
    of a door. Whatever the wishlist placed stays and counts against the same
    budget.
    """
    rng = rng or random.Random(idx)
    # One budget for the whole tileset, counters and cupboards together, since
    # that is how the 3.9 was counted. Spending it on counters first and then
    # hanging cupboards on top of it is what left ours at 6.6.
    budget = max(3, round(area * COUNTER_PER_M2)) if area else 99
    room_cabinets = max(1, round(budget * CABINET_SHARE)) if area else 99
    already = sum(1 for role, x, y, _o in plan.furniture
                  if role.startswith("counter") and _room_at(plan, x, y) == idx)
    left = max(0, budget - room_cabinets - already)
    placed = []
    by_wall: dict[str, list[tuple[int, int, str]]] = {}
    for x, y, facing in slots:
        by_wall.setdefault(facing, []).append((x, y, facing))
    for facing in sorted(by_wall, key=lambda f: -len(by_wall[f]))[:2]:
        for x, y, _f in by_wall[facing]:
            if len(placed) >= left:
                break
            orient = _facing(counter, facing)
            ax, ay = _wall_anchor(counter, x, y, orient, facing)
            cells = _cells_for(counter, ax, ay, orient)
            if any(c in occupied or c in door_tiles or c in stair_tiles for c in cells):
                continue
            if any(_room_at(plan, cx, cy) != idx for cx, cy in cells):
                continue
            if keeps_open and not keeps_open(cells):
                continue
            # A corner tile is on two walls; one counter is enough.
            occupied.update(cells)
            plan.furniture.append((counter, ax, ay, orient))
            placed.append((ax, ay, orient))

    # Cupboards on the wall above the counters, and sometimes a microwave on
    # one. North and west walls only, as for everything fixed to a wall; the
    # windows then keep off those tiles.
    if not cabinets:
        return
    hung = 0
    microwave = rng.random() >= MICROWAVE_SHARE      # True means: already done
    for role, x, y, orient in list(plan.furniture):
        if hung >= room_cabinets:
            break
        if role != counter or orient not in ("N", "W") or _room_at(plan, x, y) != idx:
            continue
        edge = _wall_edge(x, y, orient)
        if edge in plan.wall_pieces or _room_at(plan, *((x, y - 1) if orient == "N" else (x - 1, y))) == idx:
            continue
        plan.furniture.append(("wall_cabinet", x, y, _facing("wall_cabinet", orient)))
        plan.wall_pieces.add(edge)
        hung += 1
        if not microwave:
            plan.furniture.append(("microwave", x, y, _facing("microwave", orient)))
            microwave = True


@dataclass
class Building:
    """One or more storeys stacked into a single .tbx.

    A .tbx holds a list of <floor> elements and one building-wide room list; a
    floor's grid indexes into that shared list. So each storey is laid out as
    its own plan and the room lists are concatenated, with every storey's grid
    shifted by the rooms that came before it.
    """
    width: int
    height: int
    storeys: list[Plan] = field(default_factory=list)
    # Per storey below the top: where its staircase rises from.
    stairs: list[tuple[int, int, str]] = field(default_factory=list)
    # Where a mall's escalators stand, in this building's own tiles: the top
    # of the run, the end that lands on the upper floor. They are packed as
    # their own lot (knoxbuild/structures.pack_loose), not written into this
    # .tbx, because a square of one carries two tiles.
    escalators: list[tuple[int, int]] = field(default_factory=list)
    profile: object | None = None

    @property
    def rooms(self) -> list[Room]:
        return [r for s in self.storeys for r in s.rooms]

    def grid_for(self, level: int) -> list[list[int]]:
        """That storey's grid, renumbered into the shared room list."""
        offset = sum(len(s.rooms) for s in self.storeys[:level])
        grid = self.storeys[level].grid
        return [[v + offset if v else 0 for v in row] for row in grid]


STAIR_RUN = 5      # tiles a staircase occupies, from Stairs::bounds
MANY = 1 << 30     # further than any search goes
# How many places a door stuck on a corner may be offered before it stays put.
DOOR_SPOTS_TRIED = 40
CORE_WIDE = 3      # the shaft is the flight plus a landing beside it


CORRIDOR_WIDE = 3   # a landing wide enough to be circulation, not a cupboard
# How wide a corridor is, in the shares Knox County builds them: of its 259
# school corridor rectangles the narrow side is 3 in 101, 4 in 45, 2 in 43
# and 6 in 23. Ours was always exactly 3, which is the commonest but the
# only one we ever built.
CORRIDOR_WIDTHS = (2, 3, 3, 3, 4, 4, 6)
# Every other building with a corridor keeps to what a corridor is. A clinic or
# a station with one six tiles wide was a third hall.
NARROW_CORRIDOR_WIDTHS = (2, 3, 3, 3, 4)


def _pick_corridor(width: int, height: int, mask: list[list[bool]] | None,
                   rng: random.Random, widths=CORRIDOR_WIDTHS
                   ) -> tuple[int, int, int, int] | None:
    """A corridor through the floor, with room for the stairs inside it.

    Flats need something to open onto, and it has to reach all of them: a
    compact shaft in the middle leaves the flats in the corners touching
    nothing. A strip along the building's length touches the flats either side
    of it by construction.

    The strip used to have to span the bounding box end to end. Placed on its
    real footprint, a block of flats turned 30 degrees has triangles of empty
    box at every corner, so no such strip ever fitted and the block fell back
    to one flat per floor. Now the longest strip that lies wholly inside the
    footprint is taken, as long as it runs most of the building's length;
    flats beyond its ends are folded into neighbours that do reach it.
    """
    along_y = height >= width
    span = height if along_y else width
    across = width if along_y else height
    # This building's corridor width, narrowing if the floor is too thin
    # for the one drawn.
    wide = rng.choice(widths)
    while wide > CORRIDOR_WIDE and across < wide + 2 * MIN_ROOM:
        wide -= 1
    if span < STAIR_RUN + 2 or across < wide + 2 * MIN_ROOM:
        return None

    def inside(a: int, b: int) -> bool:
        x, y = (b, a) if along_y else (a, b)
        return mask is None or mask[y][x]

    # How far the building actually extends along its length.
    extent = [a for a in range(span) if any(inside(a, b) for b in range(across))]
    if not extent:
        return None
    needed = max(STAIR_RUN + 2, int(0.6 * (extent[-1] - extent[0] + 1)))

    best = None
    for start in range(MIN_ROOM, across - wide - MIN_ROOM + 1):
        run_start = None
        for a in range(span + 1):
            ok = a < span and all(inside(a, b) for b in range(start, start + wide))
            if ok and run_start is None:
                run_start = a
            if not ok and run_start is not None:
                length = a - run_start
                if length >= needed:
                    centre = abs((start + wide / 2) - across / 2)
                    score = (-length, centre)
                    if best is None or score < best[0]:
                        if along_y:
                            rect = (start, run_start, start + wide - 1, a - 1)
                        else:
                            rect = (run_start, start, a - 1, start + wide - 1)
                        best = (score, rect)
                run_start = None
    return best[1] if best else None


def _pick_core(width: int, height: int, mask: list[list[bool]] | None,
               rng: random.Random, street: str | None = None
               ) -> tuple[int, int, int, int] | None:
    """Reserve a stair shaft: the same rectangle on every storey.

    Returned as (x0, y0, x1, y1) inclusive, oriented either way round, and
    always wholly inside the footprint - a shaft half outside an L-shaped
    building would put the flight in the garden.

    With the street known the stairs go at the back against a side wall,
    where a shop or a restaurant keeps its stairs; in the middle of the floor,
    a terrace of narrow shops had a flight of stairs in the middle of every one.
    """
    shapes = [(CORE_WIDE, STAIR_RUN + 1), (STAIR_RUN + 1, CORE_WIDE)]
    best: list[tuple[int, int, int, int]] = []
    best_score = None
    for cw, ch in shapes:
        if cw > width or ch > height:
            continue
        for y0 in range(height - ch + 1):
            for x0 in range(width - cw + 1):
                if mask is not None and not all(
                        mask[y][x]
                        for y in range(y0, y0 + ch)
                        for x in range(x0, x0 + cw)):
                    continue
                # Central, so the flight is not jammed against the windows.
                score = (abs((x0 + cw / 2) - width / 2)
                         + abs((y0 + ch / 2) - height / 2))
                if street in STEP_OF:
                    # Back and side: distance from the wall opposite the
                    # street, then from the nearer side wall.
                    back = {"S": y0, "N": height - (y0 + ch), "E": x0,
                            "W": width - (x0 + cw)}[street]
                    side = min(x0, width - (x0 + cw)) if street in ("N", "S") \
                        else min(y0, height - (y0 + ch))
                    score = back * 2 + side
                if best_score is None or score < best_score - 1e-9:
                    best_score, best = score, [(x0, y0, x0 + cw - 1,
                                                y0 + ch - 1)]
                elif abs(score - best_score) < 1e-9:
                    best.append((x0, y0, x0 + cw - 1, y0 + ch - 1))
    return rng.choice(best) if best else None


STEP_OF = {"N": (0, -1), "S": (0, 1), "W": (-1, 0), "E": (1, 0)}


# Buildings this tall get a lift. Four flights is a fair climb; a thirty-storey
# tower on stairs alone is not something anyone built.
ELEVATOR_FROM_LEVELS = 5
# ...if it is more than a townhouse: a lift in a building five tiles wide
# took half its ground floor.
ELEVATOR_MIN_SIDE = 10
SHAFT_SIZE = 2


def _pick_shaft(core: tuple[int, int, int, int], width: int, height: int,
                mask: list[list[bool]] | None, stairs: tuple[int, int, str] | None
                ) -> tuple[tuple[int, int, int, int], tuple[int, int, str]] | None:
    """A 2x2 elevator shaft beside the stair hall, and the wall its doors go in.

    The Elevators mod finds a lift by its door tiles - vanilla
    fixtures_escalators_01_48-51 - repeated at the same square on every floor
    it serves, with a small sealed box behind them. So the shaft is fixed once
    for the whole building, like the stairs, and sits against the long side of
    the stair hall so its doors open onto the landing on every storey.
    """
    cx0, cy0, cx1, cy1 = core
    s = SHAFT_SIZE
    stair_cells = set()
    if stairs is not None:
        sx, sy, d = stairs
        stair_cells = {(sx, sy + i) if d == "N" else (sx + i, sy) for i in range(STAIR_RUN)}

    def inside(x0, y0):
        if x0 < 0 or y0 < 0 or x0 + s > width or y0 + s > height:
            return False
        return mask is None or all(mask[y][x] for y in range(y0, y0 + s)
                                   for x in range(x0, x0 + s))

    options = []
    if (cy1 - cy0) >= (cx1 - cx0):
        # Hall runs north-south: shafts to its west or east, doors in a W wall.
        mid = (cy0 + cy1) / 2
        for y0 in range(cy0, cy1 - s + 2):
            for x0, door_x, side_col in ((cx0 - s, cx0, cx0), (cx1 + 1, cx1 + 1, cx1)):
                if not inside(x0, y0):
                    continue
                if any((side_col, y0 + i) in stair_cells for i in range(s)):
                    continue
                options.append((abs(y0 + s / 2 - 1 - mid), (x0, y0, x0 + s - 1, y0 + s - 1),
                                (door_x, y0, "W")))
    else:
        mid = (cx0 + cx1) / 2
        for x0 in range(cx0, cx1 - s + 2):
            for y0, door_y, side_row in ((cy0 - s, cy0, cy0), (cy1 + 1, cy1 + 1, cy1)):
                if not inside(x0, y0):
                    continue
                if any((x0 + i, side_row) in stair_cells for i in range(s)):
                    continue
                options.append((abs(x0 + s / 2 - 1 - mid), (x0, y0, x0 + s - 1, y0 + s - 1),
                                (x0, door_y, "N")))
    if not options:
        return None
    options.sort(key=lambda o: (o[0], o[1]))
    return options[0][1], options[0][2]


def _cut_off_by_the_shaft(plan: Plan) -> None:
    """Take out any part of the storey the shaft has just walled off.

    Nothing opens into a lift shaft - it is a sealed box - so where the shaft
    lands in the neck of an L or a T it is a wall across it, and the rooms up
    the arm are rooms with no door anywhere: their only neighbour is the
    shaft. One fire station in a few thousand came out with four of them.
    Those tiles are better off not being part of the storey at all, which is
    what the arm is from the outside: roof.
    """
    sealed = {i for i, r in enumerate(plan.rooms, 1) if r.is_shaft}
    if not sealed:
        return
    touching: dict[int, set[int]] = {}
    for (a, b) in _boundary_edges(plan):
        if a in sealed or b in sealed:
            continue
        touching.setdefault(a, set()).add(b)
        touching.setdefault(b, set()).add(a)
    rooms = [i for i in range(1, len(plan.rooms) + 1) if i not in sealed]
    if not rooms:
        return
    # Out from the biggest room, which is the body of the building.
    start = max(rooms, key=lambda i: plan.rooms[i - 1].area)
    seen, stack = {start}, [start]
    while stack:
        for nxt in touching.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    gone = [i for i in rooms if i not in seen]
    if not gone:
        return
    for y in range(plan.height):
        for x in range(plan.width):
            if plan.grid[y][x] in gone:
                plan.grid[y][x] = 0
    _renumber(plan)
    _refit(plan)


def _carve_shaft(plan: Plan, shaft: tuple[int, int, int, int],
                 door: tuple[int, int, str]) -> None:
    """Paint the elevator shaft over the storey as a sealed room of its own."""
    x0, y0, x1, y1 = shaft
    plan.rooms.append(Room(x0, y0, x1, y1, kind="elevator", unit=0, is_shaft=True))
    idx = len(plan.rooms)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            plan.grid[y][x] = idx
    if plan.shaft is None:
        plan.shaft = shaft
        plan.shaft_door = door
    plan.shafts.append((shaft, door))
    _renumber(plan)
    _mend_fragments(plan)
    _refit(plan)


def _stairs_in_core(core: tuple[int, int, int, int]
                    ) -> tuple[int, int, str]:
    """The flight inside a shaft. Runs along the shaft's long axis.

    Set one tile in from the end so the corridor is still walkable past it.
    """
    x0, y0, x1, y1 = core
    if (y1 - y0) >= (x1 - x0):
        start = min(y0 + 1, y1 - (STAIR_RUN - 1))
        return x0 + (x1 - x0) // 2, max(y0, start), "N"
    start = min(x0 + 1, x1 - (STAIR_RUN - 1))
    return max(x0, start), y0 + (y1 - y0) // 2, "W"


def _clear_for_stairs(plan: Plan, x: int, y: int, d: str) -> None:
    """Drop furniture standing where the staircase goes."""
    dx, dy = (0, 1) if d == "N" else (1, 0)
    blocked = {(x + dx * i, y + dy * i) for i in range(STAIR_RUN)}
    plan.furniture = [
        f for f in plan.furniture
        if _is_wall_piece(f[0])
        or not (set(_cells_for(f[0], f[1], f[2], f[3])) & blocked)
    ]


def _blocks(role: str) -> bool:
    """Whether a piece stands on the floor and stops you walking through."""
    return C.FURNITURE_LAYERS.get(role, "Furniture") == "Furniture"


def _tiles_under(role: str, x: int, y: int, orient: str):
    """Every tile a piece covers, from the offsets in its catalog entry: a
    double bed is four of them and a sofa two, not one each."""
    spots = C.FURNITURE.get(role, {}).get(orient) or {"0,0": None}
    for key in spots:
        dx, _, dy = key.partition(",")
        yield x + int(dx), y + int(dy)


def _ways_in(building: "Building", level: int, storey: "Plan") -> set:
    """The tiles a player arrives on: the outside doors on the ground floor,
    the stairs on every floor above."""
    w, h = storey.width, storey.height

    def room(x, y):
        return storey.grid[y][x] if 0 <= x < w and 0 <= y < h else 0

    out = set()
    if level == 0:
        for (x, y, d) in storey.doors:
            a = (x - 1, y) if d == "W" else (x, y - 1)
            if room(*a) and not room(x, y):
                out.add(a)
            elif room(x, y) and not room(*a):
                out.add((x, y))
    for lvl, (sx, sy, sd) in enumerate(building.stairs):
        if lvl not in (level - 1, level):
            continue
        dx, dy = (0, 1) if sd == "N" else (1, 0)
        out |= {(sx + dx * i, sy + dy * i) for i in range(STAIR_RUN)
                if room(sx + dx * i, sy + dy * i)}
    return out


# Bare floor you cannot step onto that is allowed to stay shut off: a corner
# behind a bed or at the end of a bath, rather than a part of the room.
POCKET_TILES = 2
# What may stand on the square at a window. The pass below clears that square
# so the window can be opened, climbed through and seen out of, which is right
# for a bookcase or a wardrobe and wrong for these: a bath under the bathroom
# window and a bed under the bedroom one are what Knox County does, and taking
# them out cost 78 baths and 247 beds in 200 houses.
def _under_a_window(role: str) -> bool:
    return (role in {"bath", "bath_mat", "sofa", "table", "coffee_table",
                     "sidetable", "desk", "bench"}
            or role.startswith(("bed", "double_bed", "sofa_", "counter")))


# A cost (essentials, secondary, decoration) packed into one int that sorts
# the same way: a tuple sum per step was a third of _open_up's time.
RANK_COST = (1 << 40, 1 << 20, 1)
ZERO = 0
NONE = 1 << 62


def _open_up(storey: "Plan", starts: set) -> set:
    """Which pieces have to go for every room to be walked into."""
    w, h, grid = storey.width, storey.height, storey.grid
    doors = set(storey.doors)
    at: dict = {}
    # What standing on a tile costs: the pieces that would have to go, counted
    # (essentials, secondary, decoration) by the room each one stands in, so
    # the search below gives up any number of plants before one toilet.
    weight: dict = {}
    for i, (role, fx, fy, orient) in enumerate(storey.furniture):
        if not _blocks(role):
            continue
        idx = grid[fy][fx] if 0 <= fx < w and 0 <= fy < h else 0
        rank = FR.priority(role, storey.rooms[idx - 1].kind if idx else "")
        for tile in _tiles_under(role, fx, fy, orient):
            at.setdefault(tile, set()).add(i)
            weight[tile] = weight.get(tile, ZERO) + RANK_COST[rank]

    def step(ax, ay, bx, by) -> bool:
        """Whether you can walk from one tile to the next: same room, or a
        doorway in the wall between them."""
        if not (0 <= bx < w and 0 <= by < h) or not grid[by][bx]:
            return False
        if grid[ay][ax] == grid[by][bx]:
            return True
        if bx == ax + 1:
            return (bx, by, "W") in doors
        if ax == bx + 1:
            return (ax, ay, "W") in doors
        if by == ay + 1:
            return (bx, by, "N") in doors
        return (ax, ay, "N") in doors

    # A search out from the way in: stepping onto an empty tile is free,
    # stepping onto an occupied one costs the pieces standing there. What
    # comes back is the fewest essentials, then secondary pieces, then
    # decoration that have to move for each room to open.
    best: dict = {}
    back: dict = {}
    heap: list = []
    for tile in sorted(starts):
        cost = weight.get(tile, ZERO)
        if cost < best.get(tile, NONE):
            best[tile], back[tile] = cost, None
            heapq.heappush(heap, (cost, tile))
    while heap:
        here, (x, y) = heapq.heappop(heap)
        if here != best[(x, y)]:
            continue
        for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not step(x, y, *nxt):
                continue
            cost = here + weight.get(nxt, ZERO)
            if cost < best.get(nxt, NONE):
                best[nxt], back[nxt] = cost, (x, y)
                heapq.heappush(heap, (cost, nxt))

    walked = {grid[y][x] for (x, y), cost in best.items() if cost == ZERO}
    want: dict = {}
    for (x, y), cost in best.items():
        idx = grid[y][x]
        if not idx or idx in walked or storey.rooms[idx - 1].is_shaft:
            continue
        if cost < want.get(idx, (NONE, None))[0]:
            want[idx] = (cost, (x, y))
    goals = [tile for _cost, tile in want.values()]

    # A room is not walkable just because one corner of it can be reached: the
    # floor you are left standing on should hang together, and both sides of a
    # door and the square at a window have to be reachable or they cannot be
    # used. A tile or two you cannot step onto, though - behind the bed, beside
    # the bath - is how a furnished room works, and insisting on every bare
    # square took out 78 baths and 247 beds in 200 houses, three times what
    # this pass used to clear. Only a pocket bigger than that is opened up.
    for x, y, facing in doors | set(storey.windows):
        sides = ((x - 1, y), (x, y)) if facing == "W" else ((x, y - 1), (x, y))
        for tx, ty in sides:
            if not (0 <= tx < w and 0 <= ty < h) or not grid[ty][tx]:
                continue
            if best.get((tx, ty), NONE) == ZERO:
                continue
            if (x, y, facing) not in doors and all(
                    _under_a_window(storey.furniture[n][0])
                    for n in at.get((tx, ty), ())):
                continue
            goals.append((tx, ty))
    shut = {(x, y) for y in range(h) for x in range(w)
            if grid[y][x] and (x, y) not in at and best.get((x, y), NONE) > ZERO}
    seen: set = set()
    for tile in shut:
        if tile in seen:
            continue
        seen.add(tile)
        pocket, edge = [], deque([tile])
        while edge:
            cx, cy = edge.popleft()
            pocket.append((cx, cy))
            for nxt in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if nxt in shut and nxt not in seen and step(cx, cy, *nxt):
                    seen.add(nxt)
                    edge.append(nxt)
        if len(pocket) > POCKET_TILES:
            goals.append(min(pocket, key=lambda t: best.get(t, NONE)))

    gone: set = set()
    for tile in goals:
        while tile is not None:
            gone |= at.get(tile, set())
            tile = back.get(tile)
    return gone


_STEP = {"N": (0, -1), "W": (-1, 0), "S": (0, 1), "E": (1, 0)}


def _stay_reachable(cells: set, blocked: set, walk: set, squares: set) -> bool:
    """Whether each of `squares` can still be walked to from the walkway, over
    the room's bare floor. A room with no walkway has nothing to join."""
    start = [t for t in walk if t in cells and t not in blocked]
    if not start or not squares:
        return True
    seen, todo = set(start), list(start)
    while todo:
        x, y = todo.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n in cells and n not in blocked and n not in seen:
                seen.add(n)
                todo.append(n)
    return squares <= seen


def _make_way_for_windows(storey: "Plan", stairs: tuple[int, int, str] | None) -> int:
    """Stand whatever blocks a window square against another wall of its room.

    Windows go in after the rooms are furnished, so nobody knew where they
    would land, and the square inside one had to be cleared for the window to
    be opened, climbed through and seen out of. Deleting what stood there was
    nine in ten of everything the clear-up took out. A one-tile piece, and
    what stands on it, moves to the nearest free wall tile of the same room
    that keeps the floor in one piece; with no such tile it trades places with
    a one-tile piece of the same room that may stand at a window. Only what
    cannot move is left for _open_up. Returns the number of pieces moved.

    A door slid off a corner after furnishing (_doors_off_corners) can land
    with a piece in its clearance; that clearance is cleared the same way,
    with no exception for what may stand at a window."""
    w, h, grid = storey.width, storey.height, storey.grid
    squares = set()
    for x, y, d in storey.windows:
        for tx, ty in (((x - 1, y), (x, y)) if d == "W" else ((x, y - 1), (x, y))):
            if 0 <= tx < w and 0 <= ty < h and grid[ty][tx]:
                squares.add((tx, ty))
    door_tiles = _door_tiles(storey)
    at_door = {(x, y) for x, y in door_tiles if 0 <= x < w and 0 <= y < h and grid[y][x]}
    if not squares and not at_door:
        return 0
    off = squares | door_tiles
    if stairs is not None:
        sx, sy, sd = stairs
        dx, dy = (0, 1) if sd == "N" else (1, 0)
        off |= {(sx + dx * i, sy + dy * i) for i in range(STAIR_RUN)}
    furniture = storey.furniture
    cells_of = [_cells_for(role, x, y, o) for role, x, y, o in furniture]
    on_floor: dict = {}
    for i, f in enumerate(furniture):
        if not _is_wall_piece(f[0]):
            for c in cells_of[i]:
                on_floor.setdefault(c, []).append(i)
    hung = {(f[1], f[2]) for f in furniture if f[0] in ("wall_cabinet", "microwave")}

    def fits(pieces, x, y, face) -> bool:
        """Whether each piece, turned to face that wall, still covers one tile:
        a side table is one tile one way and two the other."""
        return all(_cells_for(furniture[i][0], x, y, _facing(furniture[i][0], face))
                   == [(x, y)] for i in pieces)

    def put(pieces, x, y, face) -> None:
        for i in pieces:
            for c in cells_of[i]:
                on_floor[c].remove(i)
            role = furniture[i][0]
            furniture[i] = (role, x, y, _facing(role, face))
            cells_of[i] = [(x, y)]
            on_floor.setdefault((x, y), []).append(i)

    def wall_of(t, facings):
        return next((f for f in facings
                     if (t[0] + _STEP[f][0], t[1] + _STEP[f][1]) not in cells), None)

    def nearest(tiles):
        return sorted(tiles, key=lambda d: (abs(d[0] - t[0]) + abs(d[1] - t[1]), d[1], d[0]))

    rooms: dict = {}
    moved = 0
    for t in sorted(squares | at_door):
        stack = sorted(on_floor.get(t, ()))
        roles = [furniture[i][0] for i in stack]
        if (not any(_blocks(r) for r in roles)
                or (t not in at_door and all(_under_a_window(r) for r in roles))
                or any(len(cells_of[i]) > 1 for i in stack)
                or t in hung):
            continue
        idx = grid[t[1]][t[0]]
        if idx not in rooms:
            r = storey.rooms[idx - 1]
            cells = {(x, y) for y in range(r.y0, r.y1 + 1)
                     for x in range(r.x0, r.x1 + 1) if grid[y][x] == idx}
            rooms[idx] = cells, _room_walkway(storey, idx, door_tiles, stairs)
        cells, walk = rooms[idx]
        blocked = {c for i, f in enumerate(furniture) if _blocks(f[0])
                   for c in cells_of[i]} & cells
        blocked.discard(t)
        # The tile something is opened from stays floor.
        fronts = {(cx - _STEP[f[3]][0], cy - _STEP[f[3]][1])
                  for i, (f, cs) in enumerate(zip(furniture, cells_of))
                  if _needs_front(f[0]) and f[3] in _STEP and i not in stack
                  for cx, cy in cs}
        nw_only = any(r in NORTH_WEST_ONLY for r in roles)
        facings = ("N", "W") if nw_only else ("N", "W", "S", "E")
        front = any(_needs_front(r) for r in roles)

        def opened(d, face) -> bool:
            ahead = (d[0] - _STEP[face][0], d[1] - _STEP[face][1])
            return not front or (ahead in cells and ahead not in blocked)

        covered = {c for cs in cells_of for c in cs}
        floor = FR.OpenFloor(cells, walk, POCKET_TILES)
        floor.block(blocked)
        # Every window square of the room that is bare floor, this one once
        # it is cleared: each has to stay joined to the walkway.
        opens = (squares & cells) - blocked
        opens.add(t)
        for d in nearest(cells - off - walk - covered - fronts):
            face = wall_of(d, facings)
            if (face is None or not opened(d, face) or not fits(stack, *d, face)
                    or not floor.keeps_open({d})
                    or not _stay_reachable(cells, blocked | {d}, walk, opens - {d})):
                continue
            put(stack, *d, face)
            moved += len(stack)
            break
        else:
            # No free wall: trade places with a one-tile piece that may stand
            # at a window - a bare counter for the sink, a table for the
            # dresser. Both tiles stay taken, so the floor is as it was.
            if t in at_door:
                continue
            here = wall_of(t, "NWSE")
            # A wall cabinet keeps a counter under it.
            keep = off if any(r.startswith("counter") for r in roles) else off | hung
            for c in nearest(set(on_floor) & cells - keep):
                other = sorted(on_floor[c])
                if not any(_blocks(furniture[j][0]) for j in other) or any(
                        len(cells_of[j]) > 1 or not _under_a_window(furniture[j][0])
                        for j in other):
                    continue
                face = wall_of(c, facings)
                if (face is None or here is None or not opened(c, face)
                        or not fits(stack, *c, face) or not fits(other, *t, here)):
                    continue
                put(stack, *c, face)
                put(other, *t, here)
                moved += len(stack) + len(other)
                break
    return moved


def _doors_off_stairs(building: "Building") -> int:
    """Move a door that opens onto the steps of a flight to somewhere else on
    the same wall between the same two rooms.

    The steps between the two landings cannot be walked across, so a door
    hung on one - or on the wall beside one - leads nowhere, and the rooms
    behind it are cut off. Left where it is only when no other clean stretch
    of that boundary exists.
    """
    if not building.stairs:
        return 0
    x, y, d = building.stairs[0]
    dx, dy = (0, 1) if d == "N" else (1, 0)
    steps = {(x + dx * i, y + dy * i) for i in range(1, STAIR_RUN - 1)}

    def on_steps(door) -> bool:
        dxx, dyy, dd = door
        before = (dxx - 1, dyy) if dd == "W" else (dxx, dyy - 1)
        return (dxx, dyy) in steps or before in steps

    moved = 0
    for storey in building.storeys:
        bad = [i for i, door in enumerate(storey.doors) if on_steps(door)]
        if not bad:
            continue
        edges = {(ex, ey, ed) for _side, wall in _facade_runs(storey.grid)
                 for ex, ey, ed, _ix, _iy in wall} | _room_edges(storey.grid)
        corners = {(ex, ey) for ex, ey, ed in edges
                   if (ex, ey, "N" if ed == "W" else "W") in edges}
        keep_off = set(storey.party) | set(getattr(storey, "wall_pieces", ()))
        for i in bad:
            door = storey.doors[i]
            want = _sides_of(storey.grid, *door)
            taken = set(storey.doors)
            spots = [e for e in edges
                     if e not in taken and e not in keep_off
                     and (e[0], e[1]) not in corners and not on_steps(e)
                     and _sides_of(storey.grid, *e) == want]
            if spots:
                spots.sort(key=lambda e: (abs(e[0] - door[0]) + abs(e[1] - door[1]), e))
                storey.doors[i] = spots[0]
                moved += 1
            else:
                # Nowhere else on that wall. Where the rooms are reached
                # another way the door only has to go; where it was the one
                # way in, a door to some other neighbour takes its place.
                if not _joined_without(storey, i):
                    for e in sorted(edges, key=lambda e: (abs(e[0] - door[0]) + abs(e[1] - door[1]), e)):
                        pair = _sides_of(storey.grid, *e)
                        if (e in taken or e in keep_off or (e[0], e[1]) in corners
                                or on_steps(e) or 0 in pair or pair[0] == pair[1]
                                or not set(pair) & set(want) or set(pair) == set(want)
                                or any(storey.rooms[r - 1].is_shaft for r in pair)):
                            continue
                        ua, ub = (storey.rooms[r - 1].unit for r in pair)
                        if ua and ub and ua != ub:
                            continue
                        storey.doors.append(e)
                        if _joined_without(storey, i):
                            taken.add(e)
                            break
                        storey.doors.pop()
                if _joined_without(storey, i):
                    storey.doors[i] = None
                    moved += 1
        storey.doors = [d for d in storey.doors if d is not None]
    return moved


def _joined_without(storey, skip: int) -> bool:
    """Whether the two rooms either side of door `skip` still meet through the
    other doors and open edges, so that door can go without shutting one in."""
    adj: dict[int, set] = {}
    links = [d for j, d in enumerate(storey.doors) if j != skip and d is not None]
    for x, y, d in list(links) + list(getattr(storey, "open_edge", ())):
        a, b = _sides_of(storey.grid, x, y, d)
        if a and b and a != b:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    a, b = _sides_of(storey.grid, *storey.doors[skip])
    seen, stack = {a}, [a]
    while stack:
        for nxt in adj.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return b in seen


# The share of a room's floor its furniture may cover before the smallest
# pieces come out. A bedroom with bed, two chests, a desk and a shelf in 16
# tiles is a room you turn sideways in; Knox County's sit near a third.
CLUTTER_CAP = {"hall": 0.36, "bedroom": 0.5, "kidsbedroom": 0.5,
               "livingroom": 0.5, "bathroom": 0.62, "kitchen": 0.58,
               "dining": 0.5}


def _thin_clutter(building: "Building") -> int:
    """Take the decoration, then the secondary pieces, out of a room that is
    more furniture than floor. Essentials stay whatever the room."""
    removed = 0
    for storey in building.storeys:
        w, h, grid = storey.width, storey.height, storey.grid
        area: dict = {}
        for row in grid:
            for v in row:
                if v:
                    area[v] = area.get(v, 0) + 1
        by_room: dict = {}
        for i, (role, fx, fy, orient) in enumerate(storey.furniture):
            if not _blocks(role) or not (0 <= fx < w and 0 <= fy < h) or not grid[fy][fx]:
                continue
            by_room.setdefault(grid[fy][fx], []).append(
                (i, role, sum(1 for _ in _tiles_under(role, fx, fy, orient))))
        gone: set = set()
        for idx, pieces in by_room.items():
            room = storey.rooms[idx - 1]
            cap = CLUTTER_CAP.get(room.kind)
            if cap is None or room.is_core or area[idx] < MIN_ROOM * MIN_ROOM:
                continue
            fill = sum(t for _i, _r, t in pieces)
            order = sorted((p for p in pieces if FR.priority(p[1], room.kind) != FR.ESSENTIAL),
                           key=lambda p: (-FR.priority(p[1], room.kind), p[2], p[0]))
            for i, _role, tiles in order:
                if fill <= cap * area[idx]:
                    break
                gone.add(i)
                fill -= tiles
        if gone:
            # What stood on a piece goes with it: a lamp left over bare floor
            # hangs in the air, a cabinet over nothing is on a bare wall.
            cells = {c for i in gone
                     for c in _tiles_under(*storey.furniture[i])}
            for i, (role, fx, fy, _o) in enumerate(storey.furniture):
                if (fx, fy) in cells and (_needs_surface(role)
                                          or role in ("wall_cabinet", "microwave")):
                    gone.add(i)
            storey.furniture = [f for i, f in enumerate(storey.furniture) if i not in gone]
            removed += len(gone)
    return removed


def _clear_the_way(building: "Building") -> int:
    """Take out whatever stands between a doorway and the rooms behind it.

    Rooms are furnished one at a time, so nothing stopped a shelf landing in
    the only doorway or a counter spanning the only way through. The plan was
    connected - every audit of it passed - but the furnished building was not.
    """
    _doors_off_stairs(building)
    removed = 0
    stairs = building.stairs[0] if building.stairs else None
    for level, storey in enumerate(building.storeys):
        _make_way_for_windows(storey, stairs)
        starts = _ways_in(building, level, storey)
        if not starts:
            continue
        for _round in range(6):
            gone = _open_up(storey, starts)
            if not gone:
                break
            # What hangs over a counter goes with it: a wall cabinet left over
            # bare floor was a cupboard on a wall with nothing beneath.
            under = {(f[1], f[2]) for i, f in enumerate(storey.furniture)
                     if i in gone and f[0].startswith("counter")}
            gone |= {i for i, f in enumerate(storey.furniture)
                     if f[0] in ("wall_cabinet", "microwave") and (f[1], f[2]) in under}
            storey.furniture = [f for i, f in enumerate(storey.furniture)
                                if i not in gone]
            removed += len(gone)
    _thin_clutter(building)
    return removed


def build_building(width: int, height: int, levels: int = 1,
                   commercial: bool = False, seed: int = 0,
                   kind: str | None = None,
                   mask: list[list[bool]] | None = None,
                   settings: Settings | None = None,
                   street: str | None = None,
                   retail: bool = False,
                   uses: list[tuple[str, str]] | None = None,
                   hotel: bool = False,
                   party: dict | None = None,
                   entrances: list[tuple[float, float, dict]] | None = None,
                   profile: object | None = None,
                   mapped: list | None = None,
                   garage_door: bool = False) -> Building:
    """Lay out a building of `levels` storeys.

    `retail` puts shops on the ground floor of a block of flats, as on any
    city street; towers step back above SETBACK_FROM_LEVELS. `uses` are what
    OpenStreetMap says the ground floor is (knoxbuild/uses.py), as (front
    room, back room); `hotel` makes a block of flats' flats hotel rooms.

    Each storey is laid out separately rather than copied, because a block of
    flats whose every floor is identical reads as a rendering error; only the
    staircase has to line up, and it does because the shaft is reserved first.
    """
    levels = max(1, levels)
    rng = random.Random(seed ^ 0x5745)

    # A block of flats gets a corridor whether or not it is tall enough to
    # need stairs, because the flats have to open onto something. Everything
    # else only needs a shaft, and only once there is a floor above.
    core = None
    corridor = False
    # An office tower has its own core, the same on every storey (tower.py);
    # a footprint with no room for one is laid out as any other building.
    from . import tower as tower_mod
    tcore = None
    if tower_mod.qualifies(kind, levels, width, height):
        tcore = tower_mod.pick_core(width, height, mask,
                                    random.Random(seed ^ 0x70E2))
    if tcore is not None:
        core = tcore.stair
    elif kind == "apartment":
        core = _pick_corridor(width, height, mask, rng)
        corridor = core is not None
    elif kind in NEEDS_CORRIDOR and (
            width * height >= (4 if kind == "school" else CORRIDOR_WORTH_IT)
            * min((settings.room_size if settings else Settings().room_size)
                  * KIND_ROOM_SCALE.get(kind, 1.0), _room_cap(kind))):
        # A school or a clinic is rooms off a corridor. In Knox County a
        # school's halls are 11% of its rooms and 21% of its floor, and they
        # average 122 tiles: one long one serving a storey, not a dozen square
        # ones relabelled, which is what read as corridors all the way down.
        # Only where there are rooms enough to be worth serving - a two-room
        # library with a corridor through it is a third corridor.
        core = _pick_corridor(width, height, mask, rng,
                              CORRIDOR_WIDTHS if kind == "school" else NARROW_CORRIDOR_WIDTHS)
    if core is None and levels > 1:
        core = _pick_core(width, height, mask, rng, street)
    if levels > 1 and core is None:
        levels = 1          # nowhere to put a staircase, so one floor it is

    stairs = _stairs_in_core(core) if core is not None and levels > 1 else None
    shaft = shaft_door = None
    if tcore is not None:
        shaft, shaft_door = tcore.lifts[0]
    elif core is not None and levels >= ELEVATOR_FROM_LEVELS and min(width, height) >= ELEVATOR_MIN_SIDE:
        found = _pick_shaft(core, width, height, mask, stairs)
        if found:
            shaft, shaft_door = found
    # A tower's toilet and riser are part of its core too: the step must not
    # cut through them on the upper floors.
    lifts = ([r for r, _ in tcore.lifts] + [r for r, _ in tcore.service]
             if tcore is not None else [shaft])
    upper_mask, setback_at = _setback(width, height, mask, levels, core, lifts,
                                      corridor)
    # Shops under flats where the town is dense, and wherever the map puts a
    # shop, a restaurant or a bank in a building that is more than one.
    shops = tcore is None and kind in ("apartment", "civic") and core is not None and (
        (retail and kind == "apartment" and levels >= 3) or (bool(uses) and levels >= 2))
    # A block of flats repeats its floor plan. Looking up at one from the
    # street the windows line up all the way, because every floor above the
    # ground is the same floor - and ours did not, because each storey was
    # laid out from its own seed. Most windows landed in the same bays anyway
    # and a handful drifted, which is worse than either being aligned or
    # being obviously different. Floors that share a footprint now share a
    # seed, so they share a layout; the ground floor keeps its own (it has the
    # entrance, and the shops when there are any), and a setback starts a new
    # one because the floors above it are a different shape.
    def _plan_seed(lvl: int) -> int:
        if kind != "apartment" or lvl == 0:
            return seed + 977 * lvl
        above = bool(setback_at) and lvl >= setback_at
        return seed + 977 * (1 + int(above))

    storeys = [
        build_plan(width, height, commercial=commercial or (shops and lvl == 0),
                   seed=_plan_seed(lvl),
                   kind="retail" if shops and lvl == 0 else kind,
                   mask=upper_mask if setback_at and lvl >= setback_at else mask,
                   ground=(lvl == 0), settings=settings,
                   core=core, level=lvl, levels=levels, stairs=stairs,
                   corridor=corridor, shaft=shaft, shaft_door=shaft_door,
                   street=street, uses=uses, hotel=hotel,
                   extra_shafts=tcore.lifts[1:] if tcore is not None else None,
                   tower=tcore,
                   plant=tcore is not None and lvl == tower_mod.plant_level(levels),
                   entrances=entrances if lvl == 0 else None,
                   profile=profile, mapped=mapped,
                   party={e for e, up in (party or {}).items() if lvl < up})
        for lvl in range(levels)
    ]
    if garage_door and storeys:
        _widen_vehicle_entry(storeys[0], street)
    building = Building(width=width, height=height, storeys=storeys, profile=profile)
    if stairs is not None:
        for lvl in range(levels - 1):
            building.stairs.append(stairs)
            _clear_for_stairs(storeys[lvl], *stairs)
            _clear_for_stairs(storeys[lvl + 1], *stairs)
    # Windows last and for the whole building at once, so they stack in
    # columns instead of each floor scattering its own.
    _place_windows(building, kind, shop_ground=shops)
    if kind == "mall":
        _place_escalators(building)
    # Last of all, because it is the furnished building that has to be
    # walkable, not the plan.
    _clear_the_way(building)
    return building


# Towers step back: from this many storeys the top part is set in from the
# edges, the way tall buildings are built for light and wind. A 30-storey
# block that went straight up from its footprint was a featureless box.
SETBACK_FROM_LEVELS = 12
SETBACK_SHARE = 0.65          # the step comes this far up
SETBACK_TILES = 2
SETBACK_MIN_KEEP = 0.5        # the upper part keeps at least this much floor


def _setback(width: int, height: int, mask, levels: int, core, shafts,
             corridor: bool):
    """(the upper storeys' mask, the storey the step is at) or (None, 0)."""
    if levels < SETBACK_FROM_LEVELS or core is None:
        return None, 0
    base = mask or [[True] * width for _ in range(height)]
    k = SETBACK_TILES
    # A block of flats has a corridor end to end: it steps in along its long
    # sides only, so the corridor still reaches both ends.
    x0, y0, x1, y1 = core
    along_x = corridor and (x1 - x0) >= (y1 - y0)
    along_y = corridor and not along_x

    def kept(x, y):
        for dx in range(-k, k + 1):
            for dy in range(-k, k + 1):
                if along_x and dx:
                    continue
                if along_y and dy:
                    continue
                nx, ny = x + dx, y + dy
                if not (0 <= nx < width and 0 <= ny < height and base[ny][nx]):
                    return False
        return True

    upper = [[base[y][x] and kept(x, y) for x in range(width)] for y in range(height)]
    for rx0, ry0, rx1, ry1 in [core] + [r for r in shafts if r]:
        for y in range(ry0, ry1 + 1):
            for x in range(rx0, rx1 + 1):
                if not upper[y][x]:
                    return None, 0
    if sum(map(sum, upper)) < SETBACK_MIN_KEEP * sum(map(sum, base)):
        return None, 0
    return upper, round(levels * SETBACK_SHARE)


def _place_escalators(building: "Building") -> None:
    """A pair of escalators along the atrium, off the end of the concourse.

    They run the length of the opening rather than across it, so they sit in
    the hole instead of bridging it, and the top lands on the floor that wraps
    the end of the concourse. The railing is taken off wherever one arrives,
    or the way off it is fenced.
    """
    if len(building.storeys) < 2:
        return
    upper = building.storeys[1]
    if not upper.void:
        return
    rows = sorted({y for x, y in upper.void})
    cols = sorted({x for x, y in upper.void})
    if len(rows) < C.ESCALATOR_WEST_H or len(cols) < C.ESCALATOR_WEST_W:
        return
    # The top square sits on the floor just west of the opening; the run
    # goes east into it.
    ax = cols[0] - 1
    ay = rows[0] + (len(rows) - (2 * C.ESCALATOR_WEST_H - 1)) // 2
    if ax < 0 or ay < rows[0] or ay + 2 * C.ESCALATOR_WEST_H - 2 > rows[-1]:
        ay = rows[0]
    if ax + C.ESCALATOR_WEST_W - 1 > cols[-1]:
        return
    pair = [(ax, ay)]
    second = ay + C.ESCALATOR_WEST_H - 1
    if second + C.ESCALATOR_WEST_H - 1 <= rows[-1]:
        pair.append((ax, second))
    building.escalators = pair
    _clear_railing_at(building, pair)


def _clear_railing_at(building: "Building", pair: list) -> None:
    """Take the railing off the squares an escalator arrives on.

    The rail runs the whole edge of the opening, the landing included, which
    fenced off the one thing it is there to reach.
    """
    # Only where it arrives - the squares it puts on the upper floor - not
    # the whole length of it. Clearing the lot took six tiles of railing out
    # of each side and left the opening unfenced along the escalator well.
    taken = set()
    for ax, ay in pair:
        for dx, dy, dz, _n in C.ESCALATOR_WEST:
            if dz == 1:
                taken.add((ax + dx, ay + dy))
    for storey in building.storeys:
        if not storey.railing:
            continue
        keep, opened = set(), set()
        for x, y, d in storey.railing:
            if ((x, y) in taken or (x - 1, y) in taken
                    or (x, y - 1) in taken):
                opened.add((x, y, d))
            else:
                keep.add((x, y, d))
        storey.railing = keep
        storey.open_edge |= opened


def _shop_doors(plan: "Plan", street: str | None) -> None:
    """A street door into each shop on a block of flats' ground floor."""
    for idx, room in enumerate(plan.rooms, 1):
        if room.is_core or room.is_shaft or room.kind not in RETAIL_ROOMS | FRONT_ROOMS:
            continue
        runs = [(side, wall) for side, wall in _outside_runs(plan, idx) if len(wall) >= 3]
        if not runs:
            continue
        side, wall = max(runs, key=lambda r: (r[0] == street, len(r[1])))
        door = wall[len(wall) // 2]
        if door not in plan.doors:
            plan.doors.append(door)


def _stair_foot(stairs: tuple[int, int, str] | None) -> tuple[int, int] | None:
    if stairs is None:
        return None
    x, y, d = stairs
    return (x, y + STAIR_RUN - 1) if d == "N" else (x + STAIR_RUN - 1, y)


# Rooms scale with what the building is: a warehouse is a few great halls, a
# church one nave, a school rooms the size of classrooms.
# A great hall and a concourse are big rooms; neither building is cut into
# bedsits.
KIND_ROOM_SCALE = {"industrial": 6.0, "barn": 16.0, "shed": 20.0, "church": 12.0,
                   "castle": 14.0, "stadium": 11.0, "mall": 16.0,
                   "shop": 2.0, "school": 9.0, "civic": 2.5,
                   "restaurant": 1.5, "medical": 1.3, "offices": 3.0,
                   "police": 2.0, "library": 8.0, "fire": 4.0,
                   "military": 4.0}
# A shop's ground floor is a sales floor or a few: rooms the size of a house's
# cut a grocery into cupboards no rows of shelving fit in.
SHOP_FLOOR_SCALE = 4.0
MAX_ROOMS_PER_FLOOR = 90
# No room bigger than this, however big the building.
#
# Loot is capped per room, not per container: every entry in the game's
# Distributions.lua carries a max, which is how many containers in one room
# may be filled from it (RoomDef.proceduralSpawnedContainer counts them), and
# most of the household and office ones are 1, 2 or 4. So a room with twenty
# cabinets in it has loot in the first few and nothing in the rest - "if a
# building is too big, it just stops spawning loot in containers at some
# point". More rooms means more allowances, so no room is bigger than this
# whatever the building is, and the depth cap below has to be loose enough to
# reach it: a 200x200 building needs eleven cuts, and at eight it stopped
# with rooms of two thousand tiles.
MAX_ROOM_AREA = 120
# ...except where the game's own buildings are plainly bigger. Every room in
# Knox County, by what it is called: a church is 39 tiles at the median but
# 340 at the ninth decile and 1132 at the largest, which is one nave with
# small rooms off it; a library room is 100 at the median and 282 at the
# decile; a gym 88 and 314; a warehouse 134 and 461. Held to 120 whatever the
# building was, a church and a library came out as a grid of cubicles where
# the game has a hall. The loot allowance above is the reason for the cap, and
# these are the buildings the game itself spends it on.
KIND_MAX_ROOM = {"church": 340, "library": 280, "school": 170, "gym": 320,
                 "industrial": 460, "barn": 460, "shed": 460, "military": 150,
                 "civic": 170, "fire": 220, "medical": 140,
                 # A great hall and a concourse. Without an entry here the cap
                 # is MAX_ROOM_AREA whatever KIND_ROOM_SCALE says, which is
                 # why no room-size setting moved either of these.
                 "castle": 340, "stadium": 460,
                 # Knox County's mall units: a clothes shop is 306 tiles at
                 # the median, a department store 441, a furniture shop 379.
                 "mall": 440}


def _room_cap(kind: str | None) -> int:
    return KIND_MAX_ROOM.get(kind or "", MAX_ROOM_AREA)


def build_plan(width: int, height: int, commercial: bool = False,
               seed: int = 0, kind: str | None = None,
               mask: list[list[bool]] | None = None,
               ground: bool = True,
               settings: Settings | None = None,
               core: tuple[int, int, int, int] | None = None,
               level: int = 0, levels: int = 1,
               stairs: tuple[int, int, str] | None = None,
               corridor: bool = False,
               shaft: tuple[int, int, int, int] | None = None,
               shaft_door: tuple[int, int, str] | None = None,
               extra_shafts: list | None = None,
               street: str | None = None,
               uses: list[tuple[str, str]] | None = None,
               hotel: bool = False,
               party: set | None = None,
               entrances: list[tuple[float, float, dict]] | None = None,
               profile: object | None = None,
               mapped: list | None = None,
               tower: "TowerCore | None" = None,
               plant: bool = False) -> Plan:
    """Lay out and furnish one storey of the given tile size.

    `uses` are what OpenStreetMap says a commercial ground floor holds
    (build_building); `hotel` turns flats into hotel rooms.
    `mapped` are the rooms the mapper drew inside the building, as (ring,
    kind) in storey tiles: on the ground floor they are cut as they were
    drawn (_mapped_rooms), the floors above laid out as ever.

    `ground` gates the exterior door: a door in an upper-floor wall opens onto
    a five-metre drop, and the game will happily let a zombie walk through it.

    `tower` (knoxbuild.tower.TowerCore) lays the storey out as an office
    tower round its core instead (_tower_rooms); `uses` and `mapped` are then
    ignored, and `plant` makes it the plant floor.
    """
    settings = settings or Settings()
    rng = random.Random(seed)
    plan = Plan(width=width, height=height, mask=mask, core=core,
                corridor=corridor, kind=kind, party=set(party or ()),
                profile=profile)
    shop_floor = kind in ("shop", "retail", "restaurant") and ground and tower is None
    mix_kind = "offices" if kind in ("shop", "restaurant") and not ground else kind
    # Rooms in a flat are smaller than rooms in a house, and there have to be
    # enough of them per floor to make several dwellings out of.
    target = settings.room_size * KIND_ROOM_SCALE.get(mix_kind or "", 1.0)
    if shop_floor:
        target = settings.room_size * SHOP_FLOOR_SCALE
    if kind == "apartment":
        target = max(16, round(settings.room_size * 0.4))
    # A factory floor 160 tiles across split into house-sized rooms would be
    # hundreds of cupboards. However big the building, keep it to a number of
    # rooms a person could walk through.
    floor_tiles = sum(map(sum, mask)) if mask is not None else width * height
    target = min(max(target, floor_tiles / MAX_ROOMS_PER_FLOOR),
                 _room_cap(mix_kind))

    arms: list = []
    by_kind = None
    if tower is not None:
        arms = _tower_rooms(plan, tower, ground, plant, street)
    elif kind == "apartment":
        _apartment_rooms(plan, rng, target, HOTEL_FRONTAGE if hotel else FLAT_FRONTAGE)
    elif shop_floor and kind in ("shop", "restaurant"):
        sections = _shop_rooms(plan, rng, street,
                               gas=any(front == "gasstore" for front, _b in (uses or ())))
    elif mix_kind == "mall":
        _mall_rooms(plan, rng, target, level)
    elif mix_kind == "garage":
        room_kind = ("mechanic" if any(front == "mechanic"
                                       for front, _back in (uses or ()))
                     else "garage")
        plan.rooms.append(Room(0, 0, width - 1, height - 1, kind=room_kind))
    else:
        # Reserve one small room for a bathroom when the building's mix has one.
        house_floor = not (shop_floor or commercial
                           or (mix_kind and mix_kind in SPECIAL_MIXES))
        small_room = house_floor or shop_floor or bool(mix_kind in SPECIAL_MIXES and
                                         "bathroom" in SPECIAL_MIXES[mix_kind][0])
        if mapped and ground:
            # The rooms OpenStreetMap has for this building, on the floor the
            # mapper drew them for; the rest of that floor and every floor
            # above is cut as it always was.
            small = [small_room]
            _mapped_rooms(plan, rng, mapped, target, mask, small)
        else:
            # A house floor is cut by what it holds, each room sized by its
            # kind; one no programme fits, and anything else, as it always was.
            by_kind = _house_by_kind(plan, level, levels, rng) if house_floor else None
            if by_kind:
                plan.rooms = by_kind
            else:
                _split(0, 0, width - 1, height - 1, rng, MAX_DEPTH, plan.rooms,
                       target_area=target, mask=mask, small=[small_room])
    _paint(plan)

    # Kinds are chosen after painting, from the plan as it really is: what a
    # room is depends on what it borders, and that is only known once the
    # footprint and the shaft have had their say.
    if tower is not None:
        pass                # _tower_rooms cut them with their kinds
    elif kind == "apartment":
        _unit_touches_corridor(plan)
        # Trade a room between neighbours before the kinds are handed out, so
        # a flat that has gained or lost one is furnished for the size it
        # ended up, not the size it was cut.
        _stagger_flats(plan, rng)
        _unit_touches_corridor(plan)
        _assign_flat_kinds(plan, hotel=hotel, reception=hotel and ground, rng=rng)
    elif shop_floor:
        if kind == "restaurant" and not uses:
            uses = [("restaurantdining", "restaurantkitchen")]
        _assign_shop_floor(plan, rng, street, uses,
                           several=(kind == "retail" or (kind == "shop" and len(sections) > 1)))
        if kind == "shop" and len(sections) > 1:
            _fit_out_sections(plan, rng, sections, uses)
    elif mix_kind == "garage":
        pass
    elif mix_kind and mix_kind in SPECIAL_MIXES:
        mix, fill = SPECIAL_MIXES[mix_kind]
        # A room whose kind is already decided - the mall concourse - keeps
        # it; the mix is dealt to the rest.
        rooms = [r for r in plan.rooms if not r.is_core and not r.fixed]
        _assign_kinds(rooms, mix, fill)
        if mix_kind == "castle" and len(rooms) == 1:
            rooms[0].kind = "hall"
        if mix_kind == "stadium" and len(rooms) <= 2 and not any(r.kind == "lockerroom" for r in rooms):
            offices = [r for r in rooms if r.kind == "office"]
            if offices:
                min(offices, key=lambda r: r.area).kind = "lockerroom"
        if mix_kind == "school" and any(r.kind == "diningroom" for r in rooms) \
                and not any(r.kind == "kitchen" for r in rooms):
            classrooms = [r for r in rooms if r.kind == "classroom"]
            candidates = [r for r in rooms if r.kind in {"schoollab", "office", "schoolstorage"}
                          or (r.kind == "classroom" and len(classrooms) > 1)]
            if candidates:
                min(candidates, key=lambda r: r.area).kind = "kitchen"
        if mix_kind in NEEDS_CORRIDOR:
            _circulation(plan, rooms)
        _arrange_business_rooms(plan, mix_kind)
        if mix_kind in MERGE_CIRCULATION:
            _merge_halls(plan)
        if mix_kind == "mall":
            _merge_concourse(plan)
            _atrium_railings(plan)
    elif commercial:
        rooms = [r for r in plan.rooms if not r.is_core and not r.fixed]
        _assign_kinds(rooms, COMMERCIAL, COMMERCIAL_FILL)
        _circulation(plan, rooms)
    else:
        _assign_house_kinds(plan, level, levels, stairs, rng, by_kind=bool(by_kind))
    for room in plan.rooms:
        if room.is_core:
            room.kind = "hall"
    if shaft is not None:
        _carve_shaft(plan, shaft, shaft_door)
    for extra, extra_door in extra_shafts or ():
        _carve_shaft(plan, extra, extra_door)
    # A tower's hall arms go on after the shafts: one tile thick, the
    # _mend_fragments in _paint and _carve_shaft would fold them into the offices they are there to serve.
    for rect in arms:
        plan.rooms.append(Room(*rect, kind="hall"))
        for y in range(rect[1], rect[3] + 1):
            for x in range(rect[0], rect[2] + 1):
                if mask is None or mask[y][x]:
                    plan.grid[y][x] = len(plan.rooms)
    if arms:
        _renumber(plan)

    # A cell is a cell: rooms far bigger than their kind ever is are cut down
    # now the kind is known, before any door is placed on them.
    _split_to_size(plan, rng)
    _cut_off_by_the_shaft(plan)
    if kind == "apartment" and not hotel and tower is None:
        _flats_keep_bathrooms(plan)

    _doors(plan, rng)
    if ground and tower is not None:
        _tower_entrance(plan, rng, street, entrances)
    elif ground:
        _exterior_door(plan, rng, avoid=_stair_foot(stairs), street=street,
                       entrances=entrances)
        if kind in (None, "house"):
            _back_door(plan, street)
        if kind == "retail":
            # Each shop its own street door, before the shop is fitted out
            # round it.
            _shop_doors(plan, street)
    if mix_kind == "mall":
        # Before furnishing: the openings have to exist for _furnish to keep
        # them clear.
        _open_shopfronts(plan)
    _furnish(plan, rng, stairs, street)
    if mix_kind == "mall":
        _clear_concourse(plan)
        # Nothing hangs on a railing or on an opened shopfront: a light or a
        # picture left on the edge of an opening stood in mid-air. A piece
        # records the tile it stands on and the way it faces, so the wall it
        # hangs on is _wall_edge of the two - matching the tile itself missed
        # every piece facing east or south and left 27 of them hanging, where
        # the game's own mall has none.
        edges = plan.railing | plan.open_edge
        kept, unlit = [], set()
        for role, x, y, d in plan.furniture:
            # The lift doors stay whatever they sit on: they are the only way
            # off a floor, and a lift shaft is never on an opened shopfront.
            if role.startswith("elevator_door"):
                kept.append((role, x, y, d))
                continue
            nb = ((x - 1, y) if d == "W" else (x, y - 1) if d == "N"
                  else (x + 1, y) if d == "E" else (x, y + 1))
            # Only what hangs on a wall needs one. Most of a shop stands on
            # the floor and keeps its place whatever is behind it; requiring a
            # wall for everything threw out half the fittings in the mall.
            # The catalog says which is which - plan.wall_pieces only records
            # what _furnish hung itself, and a shop's own wishlist puts up
            # mirrors that never go through it.
            if nb not in plan.void and (
                    not _is_wall_piece(role)
                    or _hangs_on_wall(plan, role, x, y, d, edges)):
                kept.append((role, x, y, d))
                continue
            if role == SWITCH:
                unlit.add(_room_at(plan, x, y))
        plan.furniture = kept
        # The game lights a room from the switch inside it, so one that lost
        # its only switch to an opening is re-wired onto a wall it still has.
        _relight(plan, unlit, edges)
    return plan


def _tower_rooms(plan: Plan, tower, ground: bool, plant: bool,
                 street: str | None) -> list:
    """Cut an office tower's storey round its core (knoxbuild/tower.py).

    A hall one tile wide runs round the core block: the lift lobby, which the
    stair hall opens onto at its ends and the toilet and riser open off.
    Beyond it the floor is cut pinwheel-fashion into up to four large areas,
    each with a whole side on that hall, so every one gets its own door onto
    the lift lobby and none is reached through another. A side too thin for a room
    (thinner than MIN_ROOM) is no office: it joins the hall. On the ground
    floor the area facing the street is the lobby; on the plant floor every
    area is storage. The lifts are painted over the hall afterwards, by
    build_plan's shafts, and the stair hall by _paint, as plan.core.

    An office area bigger than _room_cap("civic") is cut into strips running
    away from the hall, each no bigger than the cap and each with its own end
    on the hall. Each area's far end runs on past the hall, alongside the next
    area round (N alongside W, E alongside N, S alongside E, W alongside S),
    so the strips there reach the hall down an arm: one tile of hall taken off
    that neighbour. The arms are returned, for build_plan to paint after
    _paint.
    """
    w, h = plan.width, plan.height
    rects = ([tower.stair] + [r for r, _ in tower.lifts]
             + [r for r, _ in tower.service])
    x0 = max(0, min(r[0] for r in rects) - 1)
    y0 = max(0, min(r[1] for r in rects) - 1)
    x1 = min(w - 1, max(r[2] for r in rects) + 1)
    y1 = min(h - 1, max(r[3] for r in rects) + 1)
    x0 = 0 if x0 < MIN_ROOM else x0
    y0 = 0 if y0 < MIN_ROOM else y0
    x1 = w - 1 if w - 1 - x1 < MIN_ROOM else x1
    y1 = h - 1 if h - 1 - y1 < MIN_ROOM else y1
    hall = Room(x0, y0, x1, y1, kind="hall")
    plan.rooms.append(hall)
    areas = {"N": (0, 0, x1, y0 - 1), "E": (x1 + 1, 0, w - 1, y1),
             "S": (x0, y1 + 1, w - 1, h - 1), "W": (0, y0, x0 - 1, h - 1)}
    areas = {s: r for s, r in areas.items() if r[0] <= r[2] and r[1] <= r[3]}
    size = {s: _inside(*r, plan.mask) for s, r in areas.items()}
    lobby = max(areas, default=None, key=lambda s: (
        s == street and size[s] >= MIN_ROOM * MIN_ROOM, size[s]))
    kinds = {s: "storage" if plant else "lobby" if ground and s == lobby
             else "office" for s in areas}
    cap = _room_cap("civic")
    big = [s for s in areas if kinds[s] == "office" and size[s] > cap]
    arms = []
    # The arm for each side, off the neighbour it runs alongside, and what is
    # left of that neighbour.
    beside = {"N": "W", "E": "N", "S": "E", "W": "S"}
    for side in big:
        nb = beside[side]
        if nb not in areas:
            continue
        a0, b0, a1, b1 = areas[nb]
        arm, rest = {"N": ((a0, b0, a1, b0), (a0, b0 + 1, a1, b1)),
                     "E": ((a1, b0, a1, b1), (a0, b0, a1 - 1, b1)),
                     "S": ((a0, b1, a1, b1), (a0, b0, a1, b1 - 1)),
                     "W": ((a0, b0, a0, b1), (a0 + 1, b0, a1, b1))}[side]
        arms.append(arm)
        areas[nb] = rest
    for side, rect in areas.items():
        for piece in (_strips(rect, side, cap) if side in big else [rect]):
            plan.rooms.append(Room(*piece, kind=kinds[side]))
    if ground and lobby is None:
        hall.kind = "lobby"
    for rect, kind in tower.service:
        plan.rooms.append(Room(*rect, kind=kind))
    return arms


def _strips(rect, side: str, cap: int) -> list:
    """`rect` cut across its hall `side` into strips of at most `cap` tiles."""
    x0, y0, x1, y1 = rect
    along = side in "NS"            # the hall runs along x
    lo, hi = (x0, x1) if along else (y0, y1)
    depth = (y1 - y0 + 1) if along else (x1 - x0 + 1)
    length = hi - lo + 1
    # ponytail: deeper than cap / MIN_ROOM (56 tiles off the hall, footprints
    # past ~130 across) a strip MIN_ROOM wide is still over the cap; cutting
    # along the depth too would need a corridor down the strip.
    per = max(MIN_ROOM, cap // depth)
    n = max(1, min(-(-length // per), length // MIN_ROOM))
    out = []
    for i in range(n):
        b = lo + length // n + (i < length % n) - 1
        out.append((lo, y0, b, y1) if along else (x0, lo, x1, b))
        lo = b + 1
    return out


def _tower_entrance(plan: Plan, rng: random.Random, street: str | None,
                    entrances: list | None) -> None:
    """The mapped entrances where they are, and the lobby's door to the street."""
    if entrances:
        _exterior_door(plan, rng, street=street, entrances=entrances)
    lobby = next((i for i, r in enumerate(plan.rooms, 1) if r.kind == "lobby"), None)
    if lobby is None:
        return
    for x, y, d in plan.doors:
        pair = {_room_at(plan, x, y),
                _room_at(plan, x - 1, y) if d == "W" else _room_at(plan, x, y - 1)}
        if pair == {lobby, 0}:
            return
    runs = _outside_runs(plan, lobby)
    if not runs:
        return
    wall = max(runs, key=lambda r: (r[0] == (street or "S"), len(r[1])))[1]
    front = wall[len(wall) // 2]
    plan.doors.append(front)
    if not entrances:
        _more_ways_in(plan, front)


def _hangs_on_wall(plan: Plan, role: str, x: int, y: int, d: str,
                   edges: set) -> bool:
    """Is there really a wall for a piece on (x, y) facing `d` to hang on?

    A wall stands between two different rooms, or at the building's edge.
    Matching the opened shopfronts alone was not enough: a picture hung on a
    line inside one room - where the two sides are the same room and no wall
    was ever drawn - stood in open space just the same. Every tile the piece
    covers has to have one, not just the tile it is anchored on: a two-tile
    display with a wall at one end and the opening at the other left half of
    itself hanging.
    """
    try:
        cells = _cells_for(role, x, y, d)
    except KeyError:
        cells = [(x, y)]
    for cx, cy in cells:
        ex, ey, ed = _wall_edge(cx, cy, d)
        if (ex, ey, ed) in edges:
            return False
        near = (ex, ey)
        far = (ex - 1, ey) if ed == "W" else (ex, ey - 1)
        if near in plan.void or far in plan.void:
            return False
        a, b = _room_at(plan, *near), _room_at(plan, *far)
        if a == b:
            return False
        # Two rooms of the same kind go into the game under the same name,
        # and the game merges rooms by name and draws no wall between them -
        # so a mirror hung where two shoe shops meet had nothing behind it.
        if a and b and plan.rooms[a - 1].kind == plan.rooms[b - 1].kind:
            return False
    return True


def _relight(plan: Plan, unlit: set, edges: set) -> None:
    """Hang a switch back in any room that lost its only one to an opening."""
    have = {_room_at(plan, x, y) for role, x, y, _d in plan.furniture
            if role == SWITCH}
    taken = {_wall_edge(x, y, d) for _r, x, y, d in plan.furniture}
    for idx in sorted(unlit - have):
        if not idx:
            continue
        done = False
        for y in range(plan.height):
            for x in range(plan.width):
                if done or plan.grid[y][x] != idx:
                    continue
                for facing in ("N", "W", "S", "E"):
                    edge = _wall_edge(x, y, facing)
                    if edge in edges or edge in taken:
                        continue
                    nb = ((x, y - 1) if facing == "N" else
                          (x - 1, y) if facing == "W" else
                          (x, y + 1) if facing == "S" else (x + 1, y))
                    # A wall stands where the far side is a different room or
                    # the outside; not across the hole, which has none.
                    if _room_at(plan, *nb) == idx or nb in plan.void:
                        continue
                    plan.furniture.append((SWITCH, x, y, _facing(SWITCH, facing)))
                    taken.add(edge)
                    done = True
                    break
            if done:
                break


def _largest_rectangle(todo: list[list[bool]]) -> tuple[int, int, int, int] | None:
    """Biggest all-True rectangle as (x0, y0, width, height), by histogram."""
    h = len(todo)
    w = len(todo[0]) if h else 0
    heights = [0] * w
    best = None
    best_area = 0
    for y in range(h):
        for x in range(w):
            heights[x] = heights[x] + 1 if todo[y][x] else 0
        stack: list[int] = []
        for x in range(w + 1):
            cur = heights[x] if x < w else 0
            while stack and heights[stack[-1]] >= cur:
                top = stack.pop()
                left = stack[-1] + 1 if stack else 0
                area = heights[top] * (x - left)
                if area > best_area:
                    best_area = area
                    best = (left, y - heights[top] + 1, x - left, heights[top])
            stack.append(x)
    return best


def roof_rects(grid: list[list[int]]) -> list[tuple[int, int, int, int, dict]]:
    """Flat roofs covering exactly a storey's footprint.

    A BuildingEd roof is a rectangle, and every building here used to get one
    the size of its bounding box. On an L-shaped or notched footprint that
    roof reaches out over the yard - up to 43% of it over nothing on the
    buildings measured. The footprint is covered instead by the largest
    rectangles that fit, biggest first, which keeps the count low on the
    common shapes: an L takes two roofs, a notched block three.

    Each side is capped - drawn with a rim - only where it is the edge of the
    building. Where one roof meets another the rim would draw a ridge across
    the middle of a flat roof, so that side is left open.
    """
    h = len(grid)
    w = len(grid[0]) if h else 0
    inside = [[bool(grid[y][x]) for x in range(w)] for y in range(h)]
    todo = [row[:] for row in inside]
    rects = []
    while True:
        found = _largest_rectangle(todo)
        if found is None:
            break
        x0, y0, rw, rh = found
        for y in range(y0, y0 + rh):
            for x in range(x0, x0 + rw):
                todo[y][x] = False

        def open_side(cells) -> bool:
            return all(0 <= cx < w and 0 <= cy < h and inside[cy][cx]
                       for cx, cy in cells)

        caps = {
            "cappedW": not open_side([(x0 - 1, y) for y in range(y0, y0 + rh)]),
            "cappedE": not open_side([(x0 + rw, y) for y in range(y0, y0 + rh)]),
            "cappedN": not open_side([(x, y0 - 1) for x in range(x0, x0 + rw)]),
            "cappedS": not open_side([(x, y0 + rh) for x in range(x0, x0 + rw)]),
        }
        rects.append((x0, y0, rw, rh, caps))
    return rects
