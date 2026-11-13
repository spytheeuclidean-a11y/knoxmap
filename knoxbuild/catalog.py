"""Tile, furniture and room data for knoxbuild.

Started from tools/make_catalog.py output (a PZ_Mapping_Tools config
folder; every name here is one BuildingEd itself loads), then extended by hand.
Sections such as GAME_WALL_STYLES and the escalators are not in the generator,
and the committed file no longer matches what it writes. Edit this file
directly; running the generator over it would drop those sections.
"""
from __future__ import annotations

# 1-based: the .tbx references these positionally.
TILE_ENTRIES = [{'category': 'exterior_walls',
  'tiles': {'West': 'walls_exterior_house_01_032',
            'North': 'walls_exterior_house_01_033',
            'NorthWest': 'walls_exterior_house_01_034',
            'SouthEast': 'walls_exterior_house_01_035',
            'WestWindow': 'walls_exterior_house_01_040',
            'NorthWindow': 'walls_exterior_house_01_041',
            'WestDoor': 'walls_exterior_house_01_042',
            'NorthDoor': 'walls_exterior_house_01_043',
            'WestWindow1': 'walls_exterior_house_06_000',
            'NorthWindow1': 'walls_exterior_house_06_001',
            'WestWindow2': 'walls_exterior_house_06_002',
            'NorthWindow2': 'walls_exterior_house_06_003',
            'WestWindow3': 'walls_exterior_house_06_004',
            'NorthWindow3': 'walls_exterior_house_06_005',
            'WestWindow4': 'walls_exterior_house_06_006',
            'NorthWindow4': 'walls_exterior_house_06_007',
            'WestWindow5': 'walls_exterior_house_06_008',
            'NorthWindow5': 'walls_exterior_house_06_009',
            'WestWindow6': 'walls_exterior_house_06_010',
            'NorthWindow6': 'walls_exterior_house_06_011',
            'WestWindow7': 'walls_exterior_house_06_012',
            'NorthWindow7': 'walls_exterior_house_06_013',
            'WestWindow8': 'walls_exterior_house_06_014',
            'NorthWindow8': 'walls_exterior_house_06_015',
            'WestWindow9': 'walls_exterior_house_06_016',
            'NorthWindow9': 'walls_exterior_house_06_017',
            'WestWindow10': 'walls_exterior_house_06_018',
            'NorthWindow10': 'walls_exterior_house_06_019',
            'WestWindow11': 'walls_exterior_house_06_020',
            'NorthWindow11': 'walls_exterior_house_06_021',
            'WestWindow12': 'walls_exterior_house_06_022',
            'NorthWindow12': 'walls_exterior_house_06_023',
            'WestWindow13': 'walls_exterior_house_06_024',
            'NorthWindow13': 'walls_exterior_house_06_025',
            'WestWindow14': 'walls_exterior_house_06_026',
            'NorthWindow14': 'walls_exterior_house_06_027',
            'WestWindow15': 'walls_exterior_house_06_028',
            'NorthWindow15': 'walls_exterior_house_06_029',
            'WestWindow16': 'walls_exterior_house_06_030',
            'NorthWindow16': 'walls_exterior_house_06_031'}},
 {'category': 'doors',
  'tiles': {'West': 'fixtures_doors_01_000',
            'North': 'fixtures_doors_01_001',
            'WestOpen': 'fixtures_doors_01_002',
            'NorthOpen': 'fixtures_doors_01_003'}},
 {'category': 'door_frames',
  'tiles': {'West': 'fixtures_doors_frames_01_000', 'North': 'fixtures_doors_frames_01_001'}},
 {'category': 'windows',
  'tiles': {'West': 'fixtures_windows_01_000', 'North': 'fixtures_windows_01_001'}},
 {'category': 'curtains',
  'tiles': {'West': 'fixtures_windows_curtains_01_032',
            'East': 'fixtures_windows_curtains_01_033',
            'North': 'fixtures_windows_curtains_01_034',
            'South': 'fixtures_windows_curtains_01_035'}},
 {'category': 'stairs',
  'tiles': {'West1': 'fixtures_stairs_01_000',
            'West2': 'fixtures_stairs_01_001',
            'West3': 'fixtures_stairs_01_002',
            'North1': 'fixtures_stairs_01_008',
            'North2': 'fixtures_stairs_01_009',
            'North3': 'fixtures_stairs_01_010'}},
 {'category': 'interior_walls',
  'tiles': {'West': 'walls_interior_house_01_016',
            'North': 'walls_interior_house_01_017',
            'NorthWest': 'walls_interior_house_01_018',
            'SouthEast': 'walls_interior_house_01_019',
            'WestWindow': 'walls_interior_house_01_024',
            'NorthWindow': 'walls_interior_house_01_025',
            'WestDoor': 'walls_interior_house_01_026',
            'NorthDoor': 'walls_interior_house_01_027',
            'WestWindow1': 'walls_interior_house_07_064',
            'NorthWindow1': 'walls_interior_house_07_065',
            'WestWindow2': 'walls_interior_house_07_066',
            'NorthWindow2': 'walls_interior_house_07_067',
            'WestWindow3': 'walls_interior_house_07_068',
            'NorthWindow3': 'walls_interior_house_07_069',
            'WestWindow4': 'walls_interior_house_07_070',
            'NorthWindow4': 'walls_interior_house_07_071',
            'WestWindow5': 'walls_interior_house_07_072',
            'NorthWindow5': 'walls_interior_house_07_073',
            'WestWindow6': 'walls_interior_house_07_074',
            'NorthWindow6': 'walls_interior_house_07_075',
            'WestWindow7': 'walls_interior_house_07_076',
            'NorthWindow7': 'walls_interior_house_07_077',
            'WestWindow8': 'walls_interior_house_07_078',
            'NorthWindow8': 'walls_interior_house_07_079',
            'WestWindow9': 'walls_interior_house_07_080',
            'NorthWindow9': 'walls_interior_house_07_081',
            'WestWindow10': 'walls_interior_house_07_082',
            'NorthWindow10': 'walls_interior_house_07_083',
            'WestWindow11': 'walls_interior_house_07_084',
            'NorthWindow11': 'walls_interior_house_07_085',
            'WestWindow12': 'walls_interior_house_07_086',
            'NorthWindow12': 'walls_interior_house_07_087',
            'WestWindow13': 'walls_interior_house_07_088',
            'NorthWindow13': 'walls_interior_house_07_089',
            'WestWindow14': 'walls_interior_house_07_090',
            'NorthWindow14': 'walls_interior_house_07_091',
            'WestWindow15': 'walls_interior_house_07_092',
            'NorthWindow15': 'walls_interior_house_07_093',
            'WestWindow16': 'walls_interior_house_07_094',
            'NorthWindow16': 'walls_interior_house_07_095',
            'WestWindow17': 'walls_interior_house_06_008',
            'NorthWindow17': 'walls_interior_house_06_010',
            'WestWindow18': 'walls_interior_house_06_009',
            'NorthWindow18': 'walls_interior_house_06_011'}},
 {'category': 'floors', 'tiles': {'Floor': 'floors_interior_carpet_01_000'}},
 {'category': 'floors', 'tiles': {'Floor': 'floors_interior_carpet_01_008'}},
 {'category': 'floors', 'tiles': {'Floor': 'floors_interior_tilesandwood_01_043'}},
 {'category': 'floors', 'tiles': {'Floor': 'floors_interior_tilesandwood_01_011'}},
 {'category': 'floors', 'tiles': {'Floor': 'floors_interior_tilesandwood_01_016'}},
 {'category': 'floors', 'tiles': {'Floor': 'floors_interior_tilesandwood_01_041'}},
 {'category': 'roof_caps',
  'tiles': {'CapRiseE1': 'walls_exterior_roofs_01_096',
            'CapRiseE2': 'walls_exterior_roofs_01_097',
            'CapRiseE3': 'walls_exterior_roofs_01_098',
            'CapFallE1': 'walls_exterior_roofs_01_104',
            'CapFallE2': 'walls_exterior_roofs_01_105',
            'CapFallE3': 'walls_exterior_roofs_01_106',
            'CapRiseS1': 'walls_exterior_roofs_01_109',
            'CapRiseS2': 'walls_exterior_roofs_01_108',
            'CapRiseS3': 'walls_exterior_roofs_01_107',
            'CapFallS1': 'walls_exterior_roofs_01_101',
            'CapFallS2': 'walls_exterior_roofs_01_100',
            'CapFallS3': 'walls_exterior_roofs_01_099',
            'PeakPt5S': 'walls_exterior_roofs_01_103',
            'PeakPt5E': 'walls_exterior_roofs_01_111',
            'PeakOnePt5S': 'walls_exterior_roofs_01_102',
            'PeakOnePt5E': 'walls_exterior_roofs_01_110',
            'PeakTwoPt5S': 'walls_exterior_roofs_01_113',
            'PeakTwoPt5E': 'walls_exterior_roofs_01_112',
            'CapGapS3': 'walls_exterior_house_02_005',
            'CapGapE3': 'walls_exterior_house_02_004',
            'CapShallowRiseS1': 'walls_exterior_roofs_01_126',
            'CapShallowRiseS2': 'walls_exterior_roofs_01_127',
            'CapShallowFallS1': 'walls_exterior_roofs_01_123',
            'CapShallowFallS2': 'walls_exterior_roofs_01_122',
            'CapShallowRiseE1': 'walls_exterior_roofs_01_120',
            'CapShallowRiseE2': 'walls_exterior_roofs_01_121',
            'CapShallowFallE1': 'walls_exterior_roofs_01_125',
            'CapShallowFallE2': 'walls_exterior_roofs_01_124'}},
 {'category': 'roof_slopes',
  'tiles': {'SlopeS1': 'roofs_01_000',
            'SlopeS2': 'roofs_01_001',
            'SlopeS3': 'roofs_01_002',
            'SlopeE1': 'roofs_01_005',
            'SlopeE2': 'roofs_01_004',
            'SlopeE3': 'roofs_01_003',
            'SlopePt5S': 'roofs_01_015',
            'SlopePt5E': 'roofs_01_014',
            'SlopeOnePt5S': 'roofs_01_015',
            'SlopeOnePt5E': 'roofs_01_014',
            'SlopeTwoPt5S': 'roofs_01_071',
            'SlopeTwoPt5E': 'roofs_01_070',
            'ShallowSlopeW1': 'roofs_01_083',
            'ShallowSlopeW2': 'roofs_01_082',
            'ShallowSlopeE1': 'roofs_01_080',
            'ShallowSlopeE2': 'roofs_01_081',
            'ShallowSlopeN1': 'roofs_01_084',
            'ShallowSlopeN2': 'roofs_01_085',
            'ShallowSlopeS1': 'roofs_01_087',
            'ShallowSlopeS2': 'roofs_01_086',
            'Inner1': 'roofs_01_011',
            'Inner2': 'roofs_01_012',
            'Inner3': 'roofs_01_013',
            'Outer1': 'roofs_01_008',
            'Outer2': 'roofs_01_009',
            'Outer3': 'roofs_01_010',
            'InnerPt5': 'roofs_01_067',
            'InnerOnePt5': 'roofs_01_068',
            'InnerTwoPt5': 'roofs_01_069',
            'OuterPt5': 'roofs_01_064',
            'OuterOnePt5': 'roofs_01_065',
            'OuterTwoPt5': 'roofs_01_066',
            'CornerSW1': 'roofs_01_024',
            'CornerSW2': 'roofs_01_025',
            'CornerSW3': 'roofs_01_026',
            'CornerNE1': 'roofs_01_029',
            'CornerNE2': 'roofs_01_028',
            'CornerNE3': 'roofs_01_027'}},
 {'category': 'roof_tops',
  'tiles': {'West1': 'roofs_01_054',
            'West2': 'roofs_01_054',
            'West3': 'roofs_01_054',
            'North1': 'roofs_01_054',
            'North2': 'roofs_01_054',
            'North3': 'roofs_01_054'}},
 {'category': 'ceiling', 'tiles': {'Ceiling': 'ceilings_01_000'}},
 {'category': 'interior_wall_trim',
  'tiles': {'West': 'walls_interior_detailing_01_004',
            'North': 'walls_interior_detailing_01_005',
            'NorthWest': 'walls_interior_detailing_01_006',
            'SouthEast': 'walls_interior_detailing_01_007',
            'WestWindow': 'walls_interior_detailing_01_012',
            'NorthWindow': 'walls_interior_detailing_01_013',
            'WestDoor': 'walls_interior_detailing_01_014',
            'NorthDoor': 'walls_interior_detailing_01_015'}},
            
 # standard grey garage door, thin frame, closed - walls_garage_02. other
 # variants on the same two sheets, same layout (closed row then open row,
 # 3 tiles each, right-side then bottom orientation):
 #   walls_garage_01: white/white frame (mansion) _0, green/grey frame
 #   (warehouse) _16, grey metal/grey frame (warehouse, concrete) _48
 #   walls_garage_02: red glazed (fire station?) _32, metal thin frame
 #   glazed (garage/workshop?) _48
 
 {'category': 'doors',
  'tiles': {'West': 'walls_garage_02_0', 'North': 'walls_garage_02_3'}},
 {'category': 'doors',
  'tiles': {'West': 'walls_garage_02_1', 'North': 'walls_garage_02_4'}},
 {'category': 'doors',
  'tiles': {'West': 'walls_garage_02_2', 'North': 'walls_garage_02_5'}}]
  
 
EXTERIOR_WALL = 1
DOOR = 2
DOOR_FRAME = 3
WINDOW = 4
CURTAINS = 5
STAIRS = 6
INTERIOR_WALL = 7

FLOOR_CARPET_RED = 8
FLOOR_CARPET_BLUE = 9
FLOOR_WOOD = 10
FLOOR_TILE_PALE = 11
FLOOR_TILE_CHECK = 12
FLOOR_LINO = 13

# The floors Knox County actually lays, counted over 86,045 interior tiles in
# eight town cells: 47 different ones, against the six above. The two carpets
# above - carpet_01_000 and _008 - are not among the ones it uses at all; its
# bedroom carpets are carpet_01_9 to _12, and its commonest floor of any kind
# is tilesandwood_01_42, a third of every interior tile in the county.
# Appended to a building's own tile table by knoxbuild/tbx.py, the way a
# style's floor is, so they cost nothing in buildings that do not use them.

EXTRA_FLOORS = {
    "wood_pale":    "floors_interior_tilesandwood_01_42",
    "wood_mid":     "floors_interior_tilesandwood_01_45",
    "wood_dark":    "floors_interior_tilesandwood_01_51",
    "wood_grey":    "floors_interior_tilesandwood_01_49",
    "carpet_beige": "floors_interior_carpet_01_9",
    "carpet_green": "floors_interior_carpet_01_10",
    "carpet_brown": "floors_interior_carpet_01_11",
    "carpet_grey":  "floors_interior_carpet_01_12",
    "carpet_red":   "floors_interior_carpet_01_1",
    "carpet_blue":  "floors_interior_carpet_01_2",
    "tile_white":   "floors_interior_tilesandwood_01_11",
    "tile_grey":    "floors_interior_tilesandwood_01_5",
    "tile_cream":   "floors_interior_tilesandwood_01_12",
    "tile_small":   "floors_interior_tilesandwood_01_7",
    "hall_runner":  "floors_interior_tilesandwood_01_28",
    "office_grey":  "floors_interior_tilesandwood_01_44",
    # Bare concrete, the industrial kit's floor (the same one basements lay).
    "concrete":     "carpentry_02_056",
    # Civic floors, measured in the buildings that hold a policeoffice. A
    # station is hard floor throughout: its cells are tilesandwood_01_18 and
    # nothing else, its corridors _18 and _17, its lockers and lavatories _17.
    "civic_hall":   "floors_interior_tilesandwood_01_18",
    "civic_pale":   "floors_interior_tilesandwood_01_17",
    "civic_grey":   "floors_interior_tilesandwood_01_21",
    "civic_dark":   "floors_interior_tilesandwood_01_31",
    "civic_scuff":  "floors_interior_tilesandwood_01_15",
    "civic_worn":   "floors_interior_tilesandwood_01_3",
    # School floors, measured over its classrooms, gyms and lobbies: all
    # tilesandwood, none of them the shop tile the school style forced on
    # every room. A gym is _42 in every one; a library _41.
    "school_pale":  "floors_interior_tilesandwood_01_46",
    "school_wood":  "floors_interior_tilesandwood_01_41",
    "school_warm":  "floors_interior_tilesandwood_01_43",
}


def floor_entry(name: str) -> dict:
    """One EXTRA_FLOORS name as a tile-table entry."""
    return {"category": "floors", "tiles": {"Floor": EXTRA_FLOORS[name]}}

ROOF_CAP = 14
ROOF_SLOPE = 15
ROOF_TOP = 16
CEILING = 17
INTERIOR_WALL_TRIM = 18
GARAGE_DOOR = (19, 20, 21)  # left, mid, right tile-table indexes, left to right across the opening

def _load_tables() -> dict:
    import gzip
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent / "data" / "catalog_tables.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


_TABLES = _load_tables()
FURNITURE = _TABLES["FURNITURE"]

# Furniture layer per role; anything but Furniture sits on a wall.
FURNITURE_LAYERS = {'armchair': 'Furniture',
 'armchair_1': 'Furniture',
 'armchair_10': 'Furniture',
 'armchair_11': 'Furniture',
 'armchair_12': 'Furniture',
 'armchair_13': 'Furniture',
 'armchair_14': 'Furniture',
 'armchair_2': 'Furniture',
 'armchair_3': 'Furniture',
 'armchair_4': 'Furniture',
 'armchair_5': 'Furniture',
 'armchair_6': 'Furniture',
 'armchair_7': 'Furniture',
 'armchair_8': 'Furniture',
 'armchair_9': 'Furniture',
 'bath': 'Furniture',
 'bath_mat': 'FloorFurniture',
 'bed': 'Furniture',
 'bed_alt': 'Furniture',
 'bed_plain': 'Furniture',
 'bookshelf': 'Furniture',
 'chair': 'Furniture',
 'clothes_rack': 'Furniture',
 'clothes_rack_small': 'Furniture',
 'coffee_table': 'Furniture',
 'corkboard': 'WallFurniture',
 'counter': 'Furniture',
 'counter_1': 'Furniture',
 'counter_2': 'Furniture',
 'counter_3': 'Furniture',
 'counter_4': 'Furniture',
 'counter_5': 'Furniture',
 'counter_6': 'Furniture',
 'counter_7': 'Furniture',
 'crate': 'Furniture',
 'crate_top': 'Furniture',
 'desk': 'Furniture',
 'desk_dark': 'Furniture',
 'desk_long': 'Furniture',
 'desk_long_pale': 'Furniture',
 'diner_booth': 'Furniture',
 'diner_counter': 'Furniture',
 'diner_table': 'Furniture',
 'dining_table': 'Furniture',
 'dishwasher': 'Furniture',
 'double_bed': 'Furniture',
 'double_bed_alt': 'Furniture',
 'double_bed_black': 'Furniture',
 'dresser': 'Furniture',
 'dresser_alt': 'Furniture',
 'dresser_black': 'Furniture',
 'dresser_tan': 'Furniture',
 'elevator_door': 'Walls',
 'erika_ad_0': 'WallFurniture',
 'erika_ad_1': 'WallFurniture',
 'erika_ad_10': 'WallFurniture',
 'erika_ad_11': 'WallFurniture',
 'erika_ad_12': 'WallFurniture',
 'erika_ad_13': 'WallFurniture',
 'erika_ad_14': 'WallFurniture',
 'erika_ad_15': 'WallFurniture',
 'erika_ad_16': 'WallFurniture',
 'erika_ad_17': 'WallFurniture',
 'erika_ad_18': 'WallFurniture',
 'erika_ad_2': 'WallFurniture',
 'erika_ad_3': 'WallFurniture',
 'erika_ad_4': 'WallFurniture',
 'erika_ad_5': 'WallFurniture',
 'erika_ad_6': 'WallFurniture',
 'erika_ad_7': 'WallFurniture',
 'erika_ad_8': 'WallFurniture',
 'erika_ad_9': 'WallFurniture',
 'erika_art_0': 'WallFurniture',
 'erika_art_1': 'WallFurniture',
 'erika_art_10': 'WallFurniture',
 'erika_art_11': 'WallFurniture',
 'erika_art_12': 'WallFurniture',
 'erika_art_13': 'WallFurniture',
 'erika_art_14': 'WallFurniture',
 'erika_art_15': 'WallFurniture',
 'erika_art_16': 'WallFurniture',
 'erika_art_17': 'WallFurniture',
 'erika_art_18': 'WallFurniture',
 'erika_art_19': 'WallFurniture',
 'erika_art_2': 'WallFurniture',
 'erika_art_20': 'WallFurniture',
 'erika_art_21': 'WallFurniture',
 'erika_art_22': 'WallFurniture',
 'erika_art_23': 'WallFurniture',
 'erika_art_24': 'WallFurniture',
 'erika_art_25': 'WallFurniture',
 'erika_art_26': 'WallFurniture',
 'erika_art_27': 'WallFurniture',
 'erika_art_28': 'WallFurniture',
 'erika_art_29': 'WallFurniture',
 'erika_art_3': 'WallFurniture',
 'erika_art_30': 'WallFurniture',
 'erika_art_31': 'WallFurniture',
 'erika_art_32': 'WallFurniture',
 'erika_art_33': 'WallFurniture',
 'erika_art_37': 'WallFurniture',
 'erika_art_38': 'WallFurniture',
 'erika_art_39': 'WallFurniture',
 'erika_art_4': 'WallFurniture',
 'erika_art_40': 'WallFurniture',
 'erika_art_41': 'WallFurniture',
 'erika_art_42': 'WallFurniture',
 'erika_art_43': 'WallFurniture',
 'erika_art_44': 'WallFurniture',
 'erika_art_45': 'WallFurniture',
 'erika_art_46': 'WallFurniture',
 'erika_art_48': 'WallFurniture',
 'erika_art_49': 'WallFurniture',
 'erika_art_5': 'WallFurniture',
 'erika_art_50': 'WallFurniture',
 'erika_art_51': 'WallFurniture',
 'erika_art_52': 'WallFurniture',
 'erika_art_53': 'WallFurniture',
 'erika_art_54': 'WallFurniture',
 'erika_art_55': 'WallFurniture',
 'erika_art_56': 'WallFurniture',
 'erika_art_57': 'WallFurniture',
 'erika_art_58': 'WallFurniture',
 'erika_art_6': 'WallFurniture',
 'erika_art_7': 'WallFurniture',
 'erika_art_8': 'WallFurniture',
 'erika_art_9': 'WallFurniture',
 'erika_plant_0': 'Furniture',
 'erika_plant_1': 'Furniture',
 'erika_plant_10': 'Furniture',
 'erika_plant_11': 'Furniture',
 'erika_plant_12': 'Furniture',
 'erika_plant_13': 'Furniture',
 'erika_plant_14': 'Furniture',
 'erika_plant_15': 'Furniture',
 'erika_plant_16': 'Furniture',
 'erika_plant_17': 'Furniture',
 'erika_plant_18': 'Furniture',
 'erika_plant_19': 'Furniture',
 'erika_plant_2': 'Furniture',
 'erika_plant_20': 'Furniture',
 'erika_plant_21': 'Furniture',
 'erika_plant_22': 'Furniture',
 'erika_plant_23': 'Furniture',
 'erika_plant_3': 'Furniture',
 'erika_plant_4': 'Furniture',
 'erika_plant_5': 'Furniture',
 'erika_plant_6': 'Furniture',
 'erika_plant_7': 'Furniture',
 'erika_plant_8': 'Furniture',
 'erika_plant_9': 'Furniture',
 'erika_shelves_0': 'Furniture',
 'erika_shelves_1': 'Furniture',
 'erika_shelves_2': 'Furniture',
 'erika_shelves_3': 'Furniture',
 'erika_shelves_4': 'Furniture',
 'erika_shelves_5': 'Furniture',
 'erika_shelves_6': 'Furniture',
 'erika_shelves_7': 'Furniture',
 'erika_shelves_8': 'Furniture',
 'erika_shelves_9': 'Furniture',
 'erika_vending_0': 'Furniture',
 'erika_vending_1': 'Furniture',
 'erika_vending_2': 'Furniture',
 'erika_vending_3': 'Furniture',
 'filing_cabinet': 'Furniture',
 'filing_cabinet_pale': 'Furniture',
 'fridge': 'Furniture',
 'fryer': 'Furniture',
 'griddle': 'Furniture',
 'hot_counter': 'Furniture',
 'kitchen_sink': 'Furniture',
 'kitchen_sink_steel': 'Furniture',
 'kitchen_sink_dark': 'Furniture',
 'lamp': 'Furniture',
 'mannequin': 'Furniture',
 'mannequin_dark': 'Furniture',
 'mannequin_male': 'Furniture',
 'metal_rack': 'Furniture',
 'microwave': 'WallFurniture',
 'mirror': 'WallFurniture',
 'office_chair': 'Furniture',
 'oven_commercial': 'Furniture',
 'oven_steel': 'Furniture',
 'oven_steel_alt': 'Furniture',
 'painting': 'WallFurniture',
 'picnic_table': 'Furniture',
 'pizza_booth': 'Furniture',
 'pizza_counter': 'Furniture',
 'pizza_display': 'Furniture',
 'pizza_table': 'Furniture',
 'plant': 'Furniture',
 'register': 'Furniture',
 'roof_ac': 'Furniture',
 'roof_chimney': 'Roof',
 'round_table': 'Furniture',
 'rug': 'FloorFurniture',
 'rug_small': 'FloorFurniture',
 'rug_wide': 'FloorFurniture',
 'shag_rug': 'FloorFurniture',
 'shelf': 'Furniture',
 'shelf_1': 'Furniture',
 'shelf_2': 'Furniture',
 'shop_aisle': 'Furniture',
 'shop_aisle_red': 'Furniture',
 'shop_bin': 'Furniture',
 'shop_case': 'Furniture',
 'shop_counter': 'Furniture',
 'shop_counter_red': 'Furniture',
 'shop_display': 'Furniture',
 'shop_display_butcher': 'Furniture',
 'shop_display_bakery': 'Furniture',
 'shop_freezer': 'Furniture',
 'shop_fridge': 'Furniture',
 'shop_fridge_double': 'Furniture',
 'shop_fridge_open': 'Furniture',
 'shop_fridge_white': 'Furniture',
 'shop_shelf': 'Furniture',
 'shop_shelf_red': 'Furniture',
 'shop_shelf_white': 'Furniture',
 'shop_shelf_wood': 'Furniture',
 'shower': 'Furniture',
 'sidetable': 'Furniture',
 'nightstand': 'Furniture',
 'sink': 'Furniture',
 'sink_cream': 'Furniture',
 'gun_locker': 'Furniture',
 'sink_public': 'Furniture',
 'sofa': 'Furniture',
 'sofa_1': 'Furniture',
 'sofa_10': 'Furniture',
 'sofa_11': 'Furniture',
 'sofa_12': 'Furniture',
 'sofa_13': 'Furniture',
 'sofa_14': 'Furniture',
 'sofa_2': 'Furniture',
 'sofa_3': 'Furniture',
 'sofa_4': 'Furniture',
 'sofa_5': 'Furniture',
 'sofa_6': 'Furniture',
 'sofa_7': 'Furniture',
 'sofa_8': 'Furniture',
 'sofa_9': 'Furniture',
 'stove': 'Furniture',
 'stove_alt': 'Furniture',
 'switch': 'WallFurniture',
 'table': 'Furniture',
 'toilet': 'Furniture',
 'tv': 'Furniture',
 'vending': 'Furniture',
 'vending_snacks': 'Furniture',
 'wall_cabinet': 'Roof',
 'wardrobe': 'Furniture',
 'wardrobe2': 'Furniture',
 'wardrobe_black': 'Furniture',
 'wardrobe_oak': 'Furniture',
 'wardrobe_pale': 'Furniture',
 'wardrobe_tan': 'Furniture',
 'washer': 'Furniture',
 'water_cooler': 'Furniture',
 'whiteboard': 'WallFurniture'}

# Roles from Erika's Tiles (workshop 3346506593), used only when that mod
# is installed; see knoxpaths.erikas_tiles_ready.
ERIKA_WALL_ART = ['erika_art_0',
 'erika_art_1',
 'erika_art_2',
 'erika_art_3',
 'erika_art_4',
 'erika_art_5',
 'erika_art_6',
 'erika_art_7',
 'erika_art_8',
 'erika_art_9',
 'erika_art_10',
 'erika_art_11',
 'erika_art_12',
 'erika_art_13',
 'erika_art_14',
 'erika_art_15',
 'erika_art_16',
 'erika_art_17',
 'erika_art_18',
 'erika_art_19',
 'erika_art_20',
 'erika_art_21',
 'erika_art_22',
 'erika_art_23',
 'erika_art_24',
 'erika_art_25',
 'erika_art_26',
 'erika_art_27',
 'erika_art_28',
 'erika_art_29',
 'erika_art_30',
 'erika_art_31',
 'erika_art_32',
 'erika_art_33',
 'erika_art_37',
 'erika_art_38',
 'erika_art_39',
 'erika_art_40',
 'erika_art_41',
 'erika_art_42',
 'erika_art_43',
 'erika_art_44',
 'erika_art_45',
 'erika_art_46',
 'erika_art_48',
 'erika_art_49',
 'erika_art_50',
 'erika_art_51',
 'erika_art_52',
 'erika_art_53',
 'erika_art_54',
 'erika_art_55',
 'erika_art_56',
 'erika_art_57',
 'erika_art_58']
ERIKA_PLANTS = ['erika_plant_0',
 'erika_plant_1',
 'erika_plant_2',
 'erika_plant_3',
 'erika_plant_4',
 'erika_plant_5',
 'erika_plant_6',
 'erika_plant_7',
 'erika_plant_8',
 'erika_plant_9',
 'erika_plant_10',
 'erika_plant_11',
 'erika_plant_12',
 'erika_plant_13',
 'erika_plant_14',
 'erika_plant_15',
 'erika_plant_16',
 'erika_plant_17',
 'erika_plant_18',
 'erika_plant_19',
 'erika_plant_20',
 'erika_plant_21',
 'erika_plant_22',
 'erika_plant_23']
ERIKA_SHOP_ADS = ['erika_ad_0',
 'erika_ad_1',
 'erika_ad_2',
 'erika_ad_3',
 'erika_ad_4',
 'erika_ad_5',
 'erika_ad_6',
 'erika_ad_7',
 'erika_ad_8',
 'erika_ad_9',
 'erika_ad_10',
 'erika_ad_11',
 'erika_ad_12',
 'erika_ad_13',
 'erika_ad_14',
 'erika_ad_15',
 'erika_ad_16',
 'erika_ad_17',
 'erika_ad_18']
ERIKA_VENDING = ['erika_vending_0', 'erika_vending_1', 'erika_vending_2', 'erika_vending_3']
ERIKA_SHELVES = ['erika_shelves_0',
 'erika_shelves_1',
 'erika_shelves_2',
 'erika_shelves_3',
 'erika_shelves_4',
 'erika_shelves_5',
 'erika_shelves_6',
 'erika_shelves_7',
 'erika_shelves_8',
 'erika_shelves_9']
# Shop glass: [exterior wall, interior wall, glass door] entries per design.
ERIKA_STOREFRONTS = _TABLES["ERIKA_STOREFRONTS"]
# Shop signs by the wall they hang on, as strips of tiles.
ERIKA_SIGNS = {'N': [['signs_erika_01_000',
        'signs_erika_01_001',
        'signs_erika_01_002',
        'signs_erika_01_003',
        'signs_erika_01_004'],
       ['signs_erika_01_005', 'signs_erika_01_006', 'signs_erika_01_007'],
       ['signs_erika_01_010', 'signs_erika_01_011', 'signs_erika_01_012'],
       ['signs_erika_01_013', 'signs_erika_01_014', 'signs_erika_01_015'],
       ['signs_erika_01_016', 'signs_erika_01_017', 'signs_erika_01_018'],
       ['signs_erika_01_024', 'signs_erika_01_025', 'signs_erika_01_026'],
       ['signs_erika_01_048', 'signs_erika_01_049', 'signs_erika_01_050'],
       ['signs_erika_02_008', 'signs_erika_02_009', 'signs_erika_02_010', 'signs_erika_02_011'],
       ['signs_erika_02_020', 'signs_erika_02_021', 'signs_erika_02_022', 'signs_erika_02_023']],
 'W': [['signs_erika_01_058', 'signs_erika_01_057', 'signs_erika_01_056'],
       ['signs_erika_02_019', 'signs_erika_02_018', 'signs_erika_02_017', 'signs_erika_02_016'],
       ['signs_erika_02_027', 'signs_erika_02_026', 'signs_erika_02_025', 'signs_erika_02_024']]}

# The game's own shop signs: four tiles wide, hung on the wall above the glass
# (BuildingFurniture.txt, "Signs - Advertising - Wall"). The strips read west
# to east on a north wall and north to south on a west one, which is the order
# they are listed in - and the W strip runs the other way along the wall from
# the N one, so the letters come out the right way round.
GAME_SIGNS = {
    'N': [['walls_decoration_03_000', 'walls_decoration_03_001',
           'walls_decoration_03_002', 'walls_decoration_03_003'],
          ['walls_decoration_03_032', 'walls_decoration_03_033',
           'walls_decoration_03_034', 'walls_decoration_03_035'],
          ['walls_decoration_03_064', 'walls_decoration_03_065',
           'walls_decoration_03_066', 'walls_decoration_03_067'],
          ['walls_decoration_03_096', 'walls_decoration_03_097',
           'walls_decoration_03_098', 'walls_decoration_03_099'],
          ['walls_decoration_03_128', 'walls_decoration_03_129',
           'walls_decoration_03_130', 'walls_decoration_03_131'],
          ['walls_decoration_03_160', 'walls_decoration_03_161',
           'walls_decoration_03_162', 'walls_decoration_03_163'],
          ['walls_decoration_04_000', 'walls_decoration_04_001',
           'walls_decoration_04_002', 'walls_decoration_04_003']],
    'W': [['walls_decoration_03_011', 'walls_decoration_03_010',
           'walls_decoration_03_009', 'walls_decoration_03_008'],
          ['walls_decoration_03_043', 'walls_decoration_03_042',
           'walls_decoration_03_041', 'walls_decoration_03_040'],
          ['walls_decoration_03_075', 'walls_decoration_03_074',
           'walls_decoration_03_073', 'walls_decoration_03_072'],
          ['walls_decoration_03_107', 'walls_decoration_03_106',
           'walls_decoration_03_105', 'walls_decoration_03_104'],
          ['walls_decoration_03_139', 'walls_decoration_03_138',
           'walls_decoration_03_137', 'walls_decoration_03_136'],
          ['walls_decoration_03_171', 'walls_decoration_03_170',
           'walls_decoration_03_169', 'walls_decoration_03_168'],
          ['walls_decoration_04_011', 'walls_decoration_04_010',
           'walls_decoration_04_009', 'walls_decoration_04_008']],
}

# Awnings over the shop glass, from the tools' "Walls - Decoration - Awnings":
# one tile per square of shop front, in the facing that square's wall runs.
AWNINGS = [{'W': 'walls_decoration_01_069', 'N': 'walls_decoration_01_068'},
           {'W': 'walls_decoration_01_071', 'N': 'walls_decoration_01_070'},
           {'W': 'walls_decoration_01_113', 'N': 'walls_decoration_01_112'},
           {'W': 'walls_decoration_01_115', 'N': 'walls_decoration_01_114'},
           {'W': 'walls_decoration_01_121', 'N': 'walls_decoration_01_120'},
           {'W': 'walls_decoration_01_123', 'N': 'walls_decoration_01_122'}]

# Official room colours, straight from the tools' RoomNames.txt.
ROOM_COLORS = {
               "armysurplus": "101 23 238", "hunting": "249 118 5",
               "artstore": "133 240 196", "petstore": "121 147 198",
               # The rooms Knox County's own mall is made of (Muldraugh cell
               # 54_22, 325 rooms). Every unit in it has a back storeroom of
               # its own, and the food court is ringed by kitchens.
               'concourse': '170 170 170',
               'foodcourt': '236 156 92',
               'clothesstore': '198 140 196',
               'clothesstorage': '150 110 150',
               'shoestore': '176 124 160',
               'electronicsstore': '110 150 186',
               'housewarestore': '156 170 130',
               'sewingstore': '186 150 170',
               'cornerstore': '200 180 120',
               'optometrist': '140 190 190',
               'dressingrooms': '214 180 214',
               'departmentstorage': '140 130 120',
               'giftstorage': '150 140 130',
               'toystorage': '145 135 125',
               'bookstorage': '135 130 120',
               'armory': '120 120 140',
               'lockerroom': '120 140 150',
               'evidenceroom': '130 125 115',
               'openplan': '233 112 19',
               'livingroom': '233 112 19',
 'kitchen': '246 172 101',
 'bedroom': '26 26 52',
 'bathroom': '15 66 251',
 'dining': '140 232 128',
 'hall': '37 228 228',
 'storage': '254 236 60',
 'office': '167 237 202',
 'classroom': '124 133 52',
 'church': '181 113 9',
 'warehouse': '80 35 46',
 'garage': '20 179 103',
 'clinic': '157 252 219',
 'bar': '166 30 246',
 'restaurant': '241 222 118',
 'lobby': '22 126 102',
 'gym': '231 186 87',
 'library': '177 28 237',
 'medical': '9 184 97',
 'shed': '95 115 162',
 'elevator': '23 241 127',
 'kidsbedroom': '171 48 2',
 'closet': '36 18 234',
 'laundry': '50 109 111',
 'generalstore': '188 183 80',
 'conveniencestore': '168 79 81',
 'clothingstore': '93 138 94',
 'cafe': '38 164 232',
 'grocery': '28 150 176',
 'liquorstore': '131 114 164',
 'pharmacy': '176 92 195',
 'bookstore': '41 204 240',
 'toolstore': '149 206 37',
 'breakroom': '211 65 176',
 'grocerystorage': '95 4 144',
 'restaurantdining': '60 133 139',
 'italianrestaurant': '94 81 89',
 'chineserestaurant': '174 111 140',
 'icecream': '69 6 192',
 'restaurantkitchen': '105 200 96',
 'pizzakitchen': '241 135 141',
 'burgerkitchen': '141 159 168',
 'dinerkitchen': '94 126 166',
 'chinesekitchen': '144 67 147',
 'sushikitchen': '17 240 204',
 'mexicankitchen': '226 57 129',
 'seafoodkitchen': '154 106 21',
 'cafekitchen': '151 153 128',
 'bakerykitchen': '23 42 198',
 'icecreamkitchen': '137 222 249',
 'barstorage': '7 9 158',
 'bank': '189 175 129',
 'post': '141 135 160',
 'aesthetic': '71 138 72',
 'dentist': '6 78 47',
 'medicaloffice': '168 57 224',
 'theatre': '159 77 127',
 'policeoffice': '111 145 228',
 'daycare': '127 58 98',
 'mechanic': '129 112 193',
 'motelroom': '102 153 7',
 'bakery': '248 158 129',
 'gasstore': '82 133 106',
 'giftstore': '229 227 188',
 'toystore': '173 14 129',
 'candystore': '192 156 37',
 'butcher': '92 24 227',
 'departmentstore': '187 115 199',
 'jewelrystore': '99 141 61',
 'camerastore': '98 5 41',
 'musicstore': '43 190 47',
 'movierental': '107 1 254',
 'gunstore': '192 36 215',
 'sportstore': '5 122 91',
 'gardenstore': '175 115 8',
 'furniturestore': '82 31 164',
 'armystorage': '66 148 182',
 'policehall': '171 217 174',
 'policelocker': '211 74 9',
 'policeoutfitstorage': '102 164 69',
 'policestorage': '110 118 246',
 'policegunstorage': '10 198 66',
 'policearchive': '138 108 71',
 'interrogationroom': '218 41 17',
 # BuildingEd wants a colour for every room name, and a missing one throws
 # while the .tbx is written - which quietly dropped the school and the
 # police station from a town rather than failing loudly.
 'prisoncells': '141 215 71',
 'diningroom': '150 232 138',
 'schoollab': '96 206 196',
 'schoolstorage': '214 206 80',
 'sportstorage': '196 176 60',
 'janitor': '120 150 110',
 'security': '70 130 180',
 'officestorage': '204 186 90',
 'firegarage': '102 145 188',
 'firestorage': '21 177 44'}

# Houses draw from these, picked per neighbourhood block so a
# street stays coherent while the next one differs.
HOUSE_STYLES = _TABLES["HOUSE_STYLES"]

# Every interior wall set the house styles carry, one of each. Knox County
# paints 4.48 different ones into a single building - a kitchen is not the
# colour of the bedroom next door - and has 9 in all, which is what these are.
# tbx.py deals a few of them out per room kind (INTERIOR_WALLS_PER_BUILDING).
def _complete_window_cutouts(entry: dict | None) -> None:
      """Give every wall style a cutout tile for each alternate window sprite."""
      if not entry or entry.get("category") not in ("exterior_walls", "interior_walls"):
            return
      tiles = entry.get("tiles", {})
      for side in ("West", "North"):
            fallback = tiles.get(f"{side}Window") or tiles.get(side)
            if fallback:
                  for index in range(1, 20):
                        tiles.setdefault(f"{side}Window{index}", fallback)


for _entry in TILE_ENTRIES:
    _complete_window_cutouts(_entry)
for _style in HOUSE_STYLES:
    _complete_window_cutouts(_style.get("exterior"))
    _complete_window_cutouts(_style.get("interior"))


def _interior_walls() -> list[dict]:
    out, seen = [], set()
    for style in HOUSE_STYLES:
        entry = style.get("interior")
        if not entry:
            continue
        key = entry["tiles"].get("West")
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


# The interior wall styles Knox County itself uses, read off its compiled
# cells rather than guessed at: a style is four tiles (west, north, and the
# two corners) at a base that falls on a 16, with its window and door tiles
# eight and ten further on. Only the ones whose whole set the game uses are
# here - a style with no window or door tile in it would leave a hole in a
# wall. Its mall alone paints 117 different wall tiles where we managed 27.
#
# walls_commercial_02 at 16 and 32 are not here: those are see-through
# partitions (WallWTrans/WallNTrans in the game's tile definitions, no north-west
# corner, no door or window piece at +10/+11), which came out as half walls and
# missing walls. Found by Zombaxx.
#
# walls_commercial_01 at 32 is not here either: those are glass storefront panes
# (MaterialType Glass, GrimeType FullWindow, WindowW/WindowN in the tile
# definitions) - a room given them as its interior wall came out walled in glass
# (a garage, a bedroom...). Found by Zombaxx.
GAME_WALL_STYLES = [
    ("walls_commercial_03", 16),
    ("walls_interior_house_01", 0), ("walls_interior_house_01", 16),
    ("walls_interior_house_01", 32), ("walls_interior_house_01", 48),
    ("walls_interior_house_02", 0), ("walls_interior_house_02", 16),
    ("walls_interior_house_02", 48),
    ("walls_interior_house_03", 0), ("walls_interior_house_03", 16),
    ("walls_interior_house_03", 32), ("walls_interior_house_03", 48),
    ("walls_interior_house_04", 0), ("walls_interior_house_04", 16),
    ("walls_interior_house_04", 32),
]


def _wall_style(sheet: str, base: int) -> dict:
    """One (sheet, base) as an interior-wall tile-table entry."""
    def t(n: int) -> str:
        return f"{sheet}_{base + n:03d}"
    entry = {"category": "interior_walls",
             "tiles": {"West": t(0), "North": t(1), "NorthWest": t(2),
                       "SouthEast": t(3), "WestWindow": t(8), "NorthWindow": t(9),
                       "WestDoor": t(10), "NorthDoor": t(11)}}
    _complete_window_cutouts(entry)
    return entry


# Wall sheets whose plain wall tiles are glass panes, not walls: never an interior
# wall style (a guard for GAME_WALL_STYLES and the house styles alike).
GLASS_WALL_TILES = {f"walls_commercial_01_{n:03d}" for n in range(32, 48)}


def _is_glass_wall(entry: dict) -> bool:
    tiles = entry.get("tiles", {})
    return any(tiles.get(k) in GLASS_WALL_TILES for k in ("West", "North", "NorthWest", "SouthEast"))


def _all_interior_walls() -> list[dict]:
    out = [e for e in _interior_walls() if not _is_glass_wall(e)]
    seen = {e["tiles"]["West"] for e in out}
    for sheet, base in GAME_WALL_STYLES:
        entry = _wall_style(sheet, base)
        if _is_glass_wall(entry):
            continue
        if entry["tiles"]["West"] not in seen:
            seen.add(entry["tiles"]["West"])
            out.append(entry)
    return out


INTERIOR_WALLS = _all_interior_walls()

# The railing round a gallery over a mall floor: fencing_01, the black metal
# rail (the same one generator/structures.py rails its bridges with). Written
# as a wall run, so it reads as a balcony edge rather than a glazed wall.
# BuildingEd wants a wall object's own Tile out of exterior_walls and its
# InteriorTile out of interior_walls, so the railing is registered as both.
# One escalator, read square by square off Knox County's own mall (Muldraugh
# 54_22, the pair at x117-121 y153-158) rather than guessed at from tile
# numbers. Offsets are (dx, dy) from the top of the run, which is the end that
# lands on the upper floor; it climbs northwards, so dy grows downwards to the
# floor below. Two of its squares carry a second tile, which is why this
# cannot go through the .tbx's own loose-tile layer - that writes one tile to
# a square - and is packed as its own lot instead, the way the bridges are.
ESCALATOR_UP = [
    # (dx, dy, level, tile number in fixtures_escalators_01)
    (0, 0, 1, 45), (1, 0, 1, 13), (2, 0, 1, 37),
    (0, 1, 1, 44), (2, 1, 1, 36),
    (0, 1, 0, 43), (1, 1, 0, 10),
    (0, 2, 0, 42), (1, 2, 0, 9), (2, 2, 0, 34),
    (0, 3, 0, 41), (1, 3, 0, 8), (2, 3, 0, 33),
    (0, 4, 0, 40), (1, 4, 0, 12), (2, 4, 0, 32),
    (1, 5, 0, 11),
]
ESCALATOR_W, ESCALATOR_H = 3, 6

# The same thing running the other way, off Muldraugh 16_37 at (208,245).
# It is a different block of the sheet entirely - 0-5, 16-21, 24-29 against
# 8-13, 32-45 - not the north-south one turned round, which is why it had to
# be read rather than derived. It climbs west, so dx grows away from the top.
ESCALATOR_WEST = [
    (0, 0, 1, 24), (1, 0, 1, 25),
    (0, 1, 1, 5),
    (0, 2, 1, 16), (1, 2, 1, 17),
    (1, 0, 0, 26), (2, 0, 0, 27), (3, 0, 0, 28), (4, 0, 0, 29),
    (1, 1, 0, 2), (2, 1, 0, 1), (3, 1, 0, 0), (4, 1, 0, 3), (5, 1, 0, 4),
    (2, 2, 0, 19), (3, 2, 0, 20), (4, 2, 0, 21),
]
ESCALATOR_WEST_W, ESCALATOR_WEST_H = 6, 3


def escalator_tiles(x: int, y: int, base_level: int = 0,
                    west: bool = False) -> list:
    """One escalator at (x, y), as (x, y, level, layer, tile) squares.

    `west` is the one that runs along the building rather than across it; its
    (x, y) is the end that lands on the upper floor either way.
    """
    return [(x + dx, y + dy, base_level + dz, "Floor",
             f"fixtures_escalators_01_{n}")
            for dx, dy, dz, n in (ESCALATOR_WEST if west else ESCALATOR_UP)]


RAILING_TILES = {"West": "fencing_01_002", "North": "fencing_01_001",
                 "NorthWest": "fencing_01_003", "SouthEast": "fencing_01_003",
                 "WestWindow": "fencing_01_002", "NorthWindow": "fencing_01_001",
                 "WestDoor": "fencing_01_002", "NorthDoor": "fencing_01_001"}
RAILING_EXT = {"category": "exterior_walls", "tiles": dict(RAILING_TILES)}
RAILING = {"category": "interior_walls",
           "tiles": {"West": "fencing_01_002", "North": "fencing_01_001",
                     "NorthWest": "fencing_01_003", "SouthEast": "fencing_01_003",
                     "WestWindow": "fencing_01_002", "NorthWindow": "fencing_01_001",
                     "WestDoor": "fencing_01_002", "NorthDoor": "fencing_01_001"}}


# Materials for buildings OSM tags as something particular.
SPECIAL_STYLES = _TABLES["SPECIAL_STYLES"]

SPECIAL_STYLE_VARIANTS = _TABLES["SPECIAL_STYLE_VARIANTS"]

# Pieces read off the game's own tile definitions (tools/game_pieces.py).
FURNITURE.update({'pew': {'W': {'0,2': 'location_community_church_small_01_048',
               '0,1': 'location_community_church_small_01_049',
               '0,0': 'location_community_church_small_01_050'},
         'N': {'0,0': 'location_community_church_small_01_051',
               '1,0': 'location_community_church_small_01_052',
               '2,0': 'location_community_church_small_01_053'},
         'S': {'0,0': 'location_community_church_small_01_056',
               '1,0': 'location_community_church_small_01_057',
               '2,0': 'location_community_church_small_01_058'},
         'E': {'0,2': 'location_community_church_small_01_059',
               '0,1': 'location_community_church_small_01_060',
               '0,0': 'location_community_church_small_01_061'}},
 'altar': {'N': {'0,0': 'location_community_church_small_01_040',
                 '1,0': 'location_community_church_small_01_041'},
           'W': {'0,1': 'location_community_church_small_01_042',
                 '0,0': 'location_community_church_small_01_043'}},
 'bar_counter': {'S': {'0,0': 'location_restaurant_bar_01_001'},
                 'E': {'0,0': 'location_restaurant_bar_01_003'},
                 'N': {'0,0': 'location_restaurant_bar_01_005'},
                 'W': {'0,0': 'location_restaurant_bar_01_007'}},
 'bar_shelf': {'N': {'0,0': 'location_restaurant_bar_01_030'},
               'W': {'0,0': 'location_restaurant_bar_01_038'}},
 'pool_table': {'N': {'0,0': 'recreational_01_002', '1,0': 'recreational_01_003'},
                'W': {'0,1': 'recreational_01_006', '0,0': 'recreational_01_007'}},
 'jukebox': {'W': {'0,0': 'recreational_01_000'}, 'N': {'0,0': 'recreational_01_001'}},
 'arcade': {'N': {'0,0': 'recreational_01_020'},
            'W': {'0,0': 'recreational_01_021'},
            'E': {'0,0': 'recreational_01_022'},
            'S': {'0,0': 'recreational_01_023'}},
 'coin_washer': {'N': {'0,0': 'appliances_laundry_01_004'},
                 'W': {'0,0': 'appliances_laundry_01_005'},
                 'S': {'0,0': 'appliances_laundry_01_006'},
                 'E': {'0,0': 'appliances_laundry_01_007'}},
 'coin_dryer': {'N': {'0,0': 'appliances_laundry_01_012'},
                'W': {'0,0': 'appliances_laundry_01_013'},
                'S': {'0,0': 'appliances_laundry_01_014'},
                'E': {'0,0': 'appliances_laundry_01_015'}},
 'salon_chair': {'E': {'0,0': 'location_services_beauty_01_000'},
                 'W': {'0,0': 'location_services_beauty_01_001'},
                 'N': {'0,0': 'location_services_beauty_01_002'},
                 'S': {'0,0': 'location_services_beauty_01_003'}},
 'hair_dryer': {'E': {'0,0': 'location_services_beauty_01_008'},
                'W': {'0,0': 'location_services_beauty_01_009'},
                'S': {'0,0': 'location_services_beauty_01_010'},
                'N': {'0,0': 'location_services_beauty_01_011'}},
 'treadmill': {'E': {'0,0': 'recreational_sports_01_028', '1,0': 'recreational_sports_01_029'},
               'S': {'0,1': 'recreational_sports_01_030', '0,0': 'recreational_sports_01_031'}},
 'weight_machine': {'N': {'0,1': 'recreational_sports_01_040', '0,0': 'recreational_sports_01_041'},
                    'W': {'0,0': 'recreational_sports_01_042',
                          '1,0': 'recreational_sports_01_043'}},
 'weight_machine_alt': {'S': {'0,1': 'recreational_sports_01_044',
                              '0,0': 'recreational_sports_01_045'},
                        'E': {'0,0': 'recreational_sports_01_046',
                              '1,0': 'recreational_sports_01_047'}},
 'bunk_bed': {'N': {'0,1': 'furniture_bedding_01_084', '0,0': 'furniture_bedding_01_085'},
              'W': {'0,0': 'furniture_bedding_01_086', '1,0': 'furniture_bedding_01_087'}},
 'low_table_tan': {'W': {'0,0': 'furniture_tables_low_01_016'},
                   'N': {'0,0': 'furniture_tables_low_01_017'}},
 'low_table_black': {'W': {'0,0': 'furniture_tables_low_01_018'},
                     'N': {'0,0': 'furniture_tables_low_01_019'}},
 'low_table_white': {'N': {'0,0': 'furniture_tables_low_01_020'},
                     'W': {'0,0': 'furniture_tables_low_01_021'}},
 'dining_table_white': {'N': {'0,0': 'furniture_tables_high_01_044',
                              '1,0': 'furniture_tables_high_01_045'},
                        'W': {'0,1': 'furniture_tables_high_01_046',
                              '0,0': 'furniture_tables_high_01_047'}},
 'dining_table_oak': {'N': {'0,0': 'furniture_tables_high_01_060',
                            '1,0': 'furniture_tables_high_01_061'},
                      'W': {'0,1': 'furniture_tables_high_01_062',
                            '0,0': 'furniture_tables_high_01_063'}},
 'coffee_maker': {'N': {'0,0': 'appliances_cooking_01_056'},
                  'W': {'0,0': 'appliances_cooking_01_057'},
                  'E': {'0,0': 'appliances_cooking_01_058'},
                  'S': {'0,0': 'appliances_cooking_01_059'}},
 'toaster': {'S': {'0,0': 'appliances_cooking_01_032'}, 'E': {'0,0': 'appliances_cooking_01_033'}},
 'radio': {'N': {'0,0': 'appliances_radio_01_000'},
           'W': {'0,0': 'appliances_radio_01_001'},
           'S': {'0,0': 'appliances_radio_01_002'},
           'E': {'0,0': 'appliances_radio_01_003'}},
 'vanity': {'E': {'0,0': 'furniture_storage_01_040'},
            'S': {'0,0': 'furniture_storage_01_041'},
            'W': {'0,0': 'furniture_storage_01_042'},
            'N': {'0,0': 'furniture_storage_01_043'}},
 'crib': {'E': {'0,0': 'furniture_bedding_01_088', '1,0': 'furniture_bedding_01_089'},
          'S': {'0,1': 'furniture_bedding_01_090', '0,0': 'furniture_bedding_01_091'}},
 'mirror_small': {'N': {'0,0': 'walls_decoration_01_010'}, 'W': {'0,0': 'walls_decoration_01_011'}},
 'clock': {'W': {'0,0': 'walls_decoration_01_104'}, 'N': {'0,0': 'walls_decoration_01_105'}},
 # A parlour grand, recreational_01_8-9 (Facing S), _12-13 (E), _28-29 (N),
 # _30-31 (W): two tiles, its keyboard end at the 0,0 corner. Keyed by the wall
 # it backs onto, as FACING_TO_ORIENT has it.
 'piano': {'N': {'0,0': 'recreational_01_008', '1,0': 'recreational_01_009'},
           'S': {'0,0': 'recreational_01_028', '1,0': 'recreational_01_029'},
           'W': {'0,0': 'recreational_01_013', '0,1': 'recreational_01_012'},
           'E': {'0,0': 'recreational_01_031', '0,1': 'recreational_01_030'}},
 'phone': {'W': {'0,0': 'location_business_office_generic_02_000'},
           'N': {'0,0': 'location_business_office_generic_02_001'},
           'E': {'0,0': 'location_business_office_generic_02_002'},
           'S': {'0,0': 'location_business_office_generic_02_003'}},
 'coat_rack': {'N': {'0,0': 'location_community_school_01_036'},
               'W': {'0,0': 'location_community_school_01_037'},
               'S': {'0,0': 'location_community_school_01_038'},
               'E': {'0,0': 'location_community_school_01_039'}},
 'box': {'N': {'0,0': 'trashcontainers_01_024'}, 'W': {'0,0': 'trashcontainers_01_025'}},
 'box_battered': {'N': {'0,0': 'trashcontainers_01_026'}, 'W': {'0,0': 'trashcontainers_01_027'}},
 'hamper': {'S': {'0,0': 'appliances_laundry_01_024'}, 'E': {'0,0': 'appliances_laundry_01_025'}},
 'wall_vent': {'W': {'0,0': 'rooftop_furniture_034'}, 'N': {'0,0': 'rooftop_furniture_035'}},
 'sale_sign': {'W': {'0,0': 'location_shop_generic_01_070'},
               'N': {'0,0': 'location_shop_generic_01_071'}},
 'bar_stool': {'W': {'0,0': 'location_restaurant_bar_01_26'},
               'N': {'0,0': 'location_restaurant_bar_01_26'},
               'E': {'0,0': 'location_restaurant_bar_01_26'},
               'S': {'0,0': 'location_restaurant_bar_01_26'}},
 'bin': {'W': {'0,0': 'trashcontainers_01_20'},
         'N': {'0,0': 'trashcontainers_01_20'},
         'E': {'0,0': 'trashcontainers_01_20'},
         'S': {'0,0': 'trashcontainers_01_20'}},
 'door_mat': {'W': {'0,0': 'floors_rugs_01_059', '0,1': 'floors_rugs_01_058'},
              'N': {'0,0': 'floors_rugs_01_056', '1,0': 'floors_rugs_01_057'}},
 'plant': {'W': {'0,0': 'vegetation_indoor_01_012'},
           'N': {'0,0': 'vegetation_indoor_01_010'},
           'E': {'0,0': 'vegetation_indoor_01_009'},
           'S': {'0,0': 'vegetation_indoor_01_011'}},
 'poster_0': {'N': {'0,0': 'walls_decoration_05_000'}, 'W': {'0,0': 'walls_decoration_05_008'}},
 'poster_1': {'N': {'0,0': 'walls_decoration_05_001'}, 'W': {'0,0': 'walls_decoration_05_009'}},
 'poster_2': {'N': {'0,0': 'walls_decoration_05_002'}, 'W': {'0,0': 'walls_decoration_05_010'}},
 'poster_3': {'N': {'0,0': 'walls_decoration_05_003'}, 'W': {'0,0': 'walls_decoration_05_011'}},
 'poster_4': {'N': {'0,0': 'walls_decoration_05_004'}, 'W': {'0,0': 'walls_decoration_05_012'}},
 'poster_5': {'N': {'0,0': 'walls_decoration_05_005'}, 'W': {'0,0': 'walls_decoration_05_013'}},
 'poster_6': {'N': {'0,0': 'walls_decoration_05_006'}, 'W': {'0,0': 'walls_decoration_05_014'}},
 'poster_7': {'N': {'0,0': 'walls_decoration_05_007'}, 'W': {'0,0': 'walls_decoration_05_015'}}})
FURNITURE_LAYERS.update({'altar': 'Furniture',
 'arcade': 'Furniture',
 'bar_counter': 'Furniture',
 'bar_shelf': 'Furniture',
 'bar_stool': 'Furniture',
 'bin': 'Furniture',
 'box': 'Furniture',
 'box_battered': 'Furniture',
 'bunk_bed': 'Furniture',
 'clock': 'WallFurniture',
 'coat_rack': 'Furniture',
 'coffee_maker': 'Furniture',
 'coin_dryer': 'Furniture',
 'coin_washer': 'Furniture',
 'crib': 'Furniture',
 'dining_table_oak': 'Furniture',
 'dining_table_white': 'Furniture',
 'door_mat': 'FloorFurniture',
 'hair_dryer': 'Furniture',
 'hamper': 'Furniture',
 'jukebox': 'Furniture',
 'low_table_black': 'Furniture',
 'low_table_tan': 'Furniture',
 'low_table_white': 'Furniture',
 'mirror_small': 'WallFurniture',
 'pew': 'Furniture',
 'phone': 'Furniture',
 'piano': 'Furniture',
 'plant': 'Furniture',
 'pool_table': 'Furniture',
 'poster_0': 'WallFurniture',
 'poster_1': 'WallFurniture',
 'poster_2': 'WallFurniture',
 'poster_3': 'WallFurniture',
 'poster_4': 'WallFurniture',
 'poster_5': 'WallFurniture',
 'poster_6': 'WallFurniture',
 'poster_7': 'WallFurniture',
 'radio': 'Furniture',
 'sale_sign': 'Furniture',
 'salon_chair': 'Furniture',
 'toaster': 'Furniture',
 'treadmill': 'Furniture',
 'vanity': 'Furniture',
 'wall_vent': 'WallFurniture',
 'weight_machine': 'Furniture',
 'weight_machine_alt': 'Furniture'})
POSTERS = ['poster_0', 'poster_1', 'poster_2', 'poster_3', 'poster_4', 'poster_5', 'poster_6', 'poster_7']
