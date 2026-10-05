"""Every knob the generator exposes, in one place.

These started life as module-level constants scattered across the renderer,
the layout code and the zone detector. That was fine while they were my
guesses, but they encode taste - how dense a town is, how tall, how glassy,
how many zombies - and taste belongs to whoever is building the map.

Values arriving from the UI are untrusted: `from_dict` ignores anything it does
not recognise and clamps the rest into a range that still produces a loadable
map, so a hand-edited settings file cannot turn into a WorldEd crash.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass(frozen=True)
class Settings:
    # --- zombies ---------------------------------------------------------
    # The most zombies one 10x10-tile chunk can be given. Vanilla Knox County
    # peaks at 10 and leaves 97% of its map empty; 96 here once buried a town.
    spawn_density: int = 10
    # How many zombies each person who lived or worked here becomes. The
    # spawn map is drawn from an estimate of where people were; this scales it.
    zombies_per_resident: float = 1.0
    # Floor area per resident, in square metres. It is what turns a
    # building's floor area into a head count. The floor area is gross - the
    # whole footprint on every storey, stairs and shop fronts included - so
    # this runs higher than the living space a census quotes: about 50 in a
    # dense city, 45 in a town, 60 or more in American suburbs. See
    # VALUE_PER_PERSON in population.py for how these were checked.
    m2_per_person: float = 45.0

    # Turn the map so the town's main street grid runs along the tile grid
    # (1) or keep north straight up (0). Diagonal streets become staircases of
    # tiles; turning the map straightens every street on the grid.
    align_streets: int = 1
    # Turn the map by hand, on top of whatever straightening did. A city
    # whose streets run at 30 degrees has every road as a staircase; turned
    # 30 degrees it is laid out along the tiles. Straighten streets finds the
    # angle itself where there is one grid to find; this is for the places
    # where the automatic answer is wrong, or where there are two grids and
    # the mapper wants to pick which one wins.
    rotate_degrees: float = 0.0
    # Lay every road in straight runs along the tiles and on 45-degree
    # diagonals, like Knox County's (1), or draw them as mapped (0).
    straight_roads: int = 0

    # --- terrain ---------------------------------------------------------
    # Multiplies how much of a forest polygon actually becomes trees.
    tree_density: float = 1.0

    # --- buildings -------------------------------------------------------
    seed: int = 1
    # Rebuild every address the map has (1), or read the map for what is
    # there and lay the housing out to suit the game (0).
    #
    # OpenStreetMap draws a town at its real density. At 2 m a tile that is a
    # street of five-by-four-tile houses standing shoulder to shoulder, which
    # is accurate and is not a place anyone wants to loot: a Knox County house
    # is four or five proper rooms with a yard round it. With this off, about
    # half the ordinary houses are left out and the ones that stay grow into
    # the gap. Roads, rivers, woods and the terrain are still exactly as
    # mapped - only the housing is the game's rather than the survey's.
    true_map: int = 1
    # Fill in the buildings OpenStreetMap has not got, from Overture Maps
    # (generator/overture.py). OSM is drawn by people, so how much of a town
    # is on it depends on who lives there: all of a German one, the high
    # street and little else in plenty of the world. Overture publishes
    # machine-detected roofprints under the same licence, and where OSM is
    # blank they are the difference between a town and a few streets.
    #
    # Off by default, because where OSM is complete this adds sheds and costs
    # a few minutes: measured over the same size of box, 60 buildings in
    # Gifhorn against 761 in Urgup. Needs DuckDB installed.
    fill_gaps: int = 0
    # Put one military rifle somewhere on the map, come what may. A real town
    # has no army checkpoint in it, so the game's rifles - which spawn from
    # army and police loot - may have nowhere at all to appear.
    guaranteed_rifle: int = 1
    min_size: int = 3            # skip footprints narrower than this, in tiles
    # and larger than this. It was 60, which threw away the largest
    # buildings in town - the factory, the cultural centre - which are
    # exactly the landmarks a place is recognised by.
    max_size: int = 200
    # An untagged footprint at least this big is read as a block of flats,
    # this often. OSM rarely says, so these two decide a town's character.
    apartment_footprint: int = 150
    apartment_chance: float = 0.55
    max_levels: int = 6
    # Legacy Smart-mode threshold, retained for existing settings files.
    square_buildings: int = 15
    # Target room area in tiles before splitting. Knox County's rooms are 16 m2
    # at the median; 56 made them twice that, big bare halls.
    room_size: int = 24
    # How far a neighbourhood reaches before the materials change, and how
    # often one building breaks from its block anyway.
    neighbourhood_tiles: int = 110
    style_oddity: float = 0.18

    # --- zones -----------------------------------------------------------
    # Scales how many ParkingStall zones are found. Vehicles only ever spawn
    # inside one, so this is the dial for how many cars are in the streets.
    parking_density: float = 1.0
    # How each building outline is fitted to the tile grid.
    building_alignment: str = "smart"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Settings":
        """Build from untrusted input, ignoring junk and clamping the rest."""
        data = data if isinstance(data, dict) else {}
        preset = PRESETS.get(str(data.get("preset", "")).lower())
        base = preset.to_dict() if preset else {}

        kept: dict = {}
        types = {f.name: f.type for f in fields(cls)}
        for name, raw in list(base.items()) + list(data.items()):
            if name not in types:
                continue          # unknown key, including "preset" itself
            if name == "building_alignment":
                value = str(raw).strip().lower()
                if value in BUILDING_ALIGNMENT_OPTIONS:
                    kept[name] = value
                continue
            try:
                value = int(raw) if types[name] == "int" else float(raw)
            except (TypeError, ValueError, OverflowError):
                continue          # unparseable, keep the default
            if value != value:
                continue          # NaN compares false with everything; keep the default
            lo, hi = LIMITS[name]
            kept[name] = min(max(value, lo), hi)
        if "building_alignment" not in data:
            old_square = data.get("square_buildings",
                                  base.get("square_buildings", cls().square_buildings))
            old_straight = data.get("straight_roads", base.get("straight_roads", 0))
            try:
                old_square = float(old_square)
                old_straight = int(old_straight)
            except (TypeError, ValueError, OverflowError):
                old_square, old_straight = 15.0, 0
            kept["building_alignment"] = (
                "rectangle" if old_straight or old_square >= 45 else
                "real" if old_square <= 0 else "smart")
        return cls(**kept)


# name -> (minimum, maximum). Wider than anyone sensibly wants, narrow enough
# that nothing here can produce a building the .tbx reader rejects.
LIMITS = {
    "spawn_density": (0, 60),
    "zombies_per_resident": (0.0, 5.0),
    "m2_per_person": (10.0, 150.0),
    "tree_density": (0.0, 3.0),
    "seed": (0, 2 ** 31 - 1),
    "true_map": (0, 1),
    "fill_gaps": (0, 1),
    "guaranteed_rifle": (0, 1),
    # MIN_ROOM in layout.py is 3, and a building has to hold at least one room
    # plus its walls. MAX_BUILDING_DIMENSION in the reader is 300.
    "min_size": (3, 40),
    "align_streets": (0, 1),
    # Past 45 either way it is the same grid again, a quarter turn round.
    "rotate_degrees": (-45.0, 45.0),
    "straight_roads": (0, 1),
    "max_size": (8, 250),
    "apartment_footprint": (16, 4000),
    "apartment_chance": (0.0, 1.0),
    # Build 42 has 32 levels above ground (WorldEd's MAX_WORLD_LEVELS is 64,
    # -32 to 31), and the vanilla map's tallest tower reaches level 29. Every
    # storey is a full floor of rooms and furniture, so tall towns cost build
    # and compile time - the presets stay low and this is the ceiling.
    "max_levels": (1, 30),
    "room_size": (16, 400),
    "square_buildings": (0, 45),
    "neighbourhood_tiles": (20, 2000),
    "style_oddity": (0.0, 1.0),
    "parking_density": (0.0, 4.0),
}

BUILDING_ALIGNMENT_OPTIONS = ("real", "smart", "rectilinear", "rectangle")


PRESETS = {
    # A small American-style town: detached houses, low, plenty of parking.
    "suburb": Settings(apartment_footprint=600, apartment_chance=0.1,
                       max_levels=2, parking_density=1.4,
                       neighbourhood_tiles=140, tree_density=1.3,
                       m2_per_person=60.0),
    # The default, and what a European or Turkish town centre looks like.
    "town": Settings(),
    # Dense and tall: most large footprints become blocks of flats.
    "city": Settings(apartment_footprint=90, apartment_chance=0.85,
                     max_levels=6, neighbourhood_tiles=70,
                     spawn_density=14, tree_density=0.6,
                     m2_per_person=50.0),
    # Scattered farms and barns under heavy tree cover.
    "rural": Settings(apartment_footprint=2000, apartment_chance=0.0,
                      max_levels=2, spawn_density=4, tree_density=2.0,
                      m2_per_person=70.0,
                      parking_density=0.4, neighbourhood_tiles=300),
}

DEFAULT = Settings()
