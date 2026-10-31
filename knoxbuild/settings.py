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
    # How the roads are laid: as mapped (0); in straight runs along the tiles
    # and on 45-degree diagonals, like Knox County's (1); routed in vanilla
    # B42's sixteen directions with its own street shapes and curves (2); or
    # that, with built-up streets kept on the grid and off the buildings (3).
    # 2 and 3 take minutes on a town (generator/roadgraph).
    straight_roads: int = 1

    # --- terrain ---------------------------------------------------------
    # Multiplies how much tree cover the map gets: the woods the mapper drew,
    # the trees in gardens, and the scrub scattered over open ground.
    tree_density: float = 1.0
    # ...and this scales the woods on top of it, so the two can differ. A
    # mapped forest and a tree in somebody's garden are not the same thing to
    # play in - one is cover for miles, the other is a yard with a tree in it
    # - and a map wanted thick woods round a thinly planted town had no way
    # to say so.
    forest_density: float = 1.0

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
    # Build into the gaps along a street that has buildings either side of
    # them (generator/rendering/infill.py): the shop missing from a row of
    # shops, the houses missing from a run of houses, built like the ones
    # beside them. It needs no data from anywhere, only the streets and
    # buildings already on the map.
    fill_frontage: int = 0
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
    # 1 builds with the game's own tiles only, leaving Erika's Tiles out
    # even when it is installed.
    vanilla_tiles: int = 0
    # Legacy Smart-mode threshold, retained for existing settings files.
    square_buildings: int = 15
    # Target room area in tiles before splitting. Knox County's rooms are 16 m2
    # at the median; 56 made them twice that, big bare halls.
    room_size: int = 24
    # 1 lays each house out as a whole with a constraint solver (OR-Tools
    # CP-SAT, knoxbuild/room_solver.py): hall, stairs, kitchen at the back,
    # bedrooms upstairs, each room its own windows. Slower on a first build
    # (layouts are cached by footprint); without OR-Tools it does nothing.
    room_solver: int = 0
    # How far a neighbourhood reaches before the materials change, and how
    # often one building breaks from its block anyway.
    neighbourhood_tiles: int = 110
    style_oddity: float = 0.18
    # What the housing is built like. "auto" reads the map's own building
    # names: a town written in Chinese gets flat-roofed masonry blocks and
    # taller self-built houses, the way it is really built there (see
    # knoxbuild/regional.py). "cn" forces that regardless of what the names
    # say, and "off" builds every town the way the game's own Knox County is
    # built, which is what every map did before this knob existed.
    arch_style: str = "auto"

    # How tall the buildings OpenStreetMap says nothing about come out.
    # "auto" is what the generator has always done: the kind of building and
    # the size of its footprint decide (knoxbuild/regional.py), which is as
    # close to the real thing as a guess gets. The rest shape that guess for
    # a map somebody wants a particular skyline from - "low" for a town of
    # one- and two-storey buildings with the odd taller one, "middle" for a
    # town that leans to the middle of its range, "tall" for mostly tall with
    # a few small, and "even" for every height between one and the tallest
    # equally often.
    #
    # A building whose height OpenStreetMap does record is never touched by
    # this: a mapper counting the floors of a tower beats any distribution.
    height_mix: str = "auto"

    # --- zones -----------------------------------------------------------
    # Scales how many ParkingStall zones are found. Vehicles only ever spawn
    # inside one, so this is the dial for how many cars are in the streets.
    parking_density: float = 1.0
    # How each building outline is fitted to the tile grid: the dominant wall direction, keeping the shape.
    building_alignment: str = "rectilinear"

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
        enum_options = {"building_alignment": BUILDING_ALIGNMENT_OPTIONS,
                        "arch_style": ARCH_STYLE_OPTIONS,
                        "height_mix": HEIGHT_MIX_OPTIONS}
        for name, raw in list(base.items()) + list(data.items()):
            if name not in types:
                continue          # unknown key, including "preset" itself
            if name in enum_options:
                value = str(raw).strip().lower()
                if value in enum_options[name]:
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
        # Only a settings file from before building_alignment existed names these; anything
        # else, a preset or a bare request, takes the default as it stands.
        if "building_alignment" not in data and ("square_buildings" in data
                                                  or "straight_roads" in data):
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
    "forest_density": (0.0, 3.0),
    "seed": (0, 2 ** 31 - 1),
    "true_map": (0, 1),
    "fill_gaps": (0, 1),
    "fill_frontage": (0, 1),
    "guaranteed_rifle": (0, 1),
    # MIN_ROOM in layout.py is 3, and a building has to hold at least one room
    # plus its walls. MAX_BUILDING_DIMENSION in the reader is 300.
    "min_size": (3, 40),
    "align_streets": (0, 1),
    # Past 45 either way it is the same grid again, a quarter turn round.
    "rotate_degrees": (-45.0, 45.0),
    "straight_roads": (0, 3),
    "max_size": (8, 250),
    "apartment_footprint": (16, 4000),
    "apartment_chance": (0.0, 1.0),
    # Build 42 has 32 levels above ground (WorldEd's MAX_WORLD_LEVELS is 64,
    # -32 to 31), and the vanilla map's tallest tower reaches level 29. tbx.py
    # always puts a roof floor on top of the last storey, and the roof takes
    # one of the 32 levels, so 31 storeys is the most that fits. Every storey
    # is a full floor of rooms and furniture, so tall towns cost build and
    # compile time - the presets stay low.
    "max_levels": (1, 31),
    "vanilla_tiles": (0, 1),
    "room_size": (16, 400),
    "room_solver": (0, 1),
    "building_alignment": (0, 3),
    "square_buildings": (0, 45),
    "neighbourhood_tiles": (20, 2000),
    "style_oddity": (0.0, 1.0),
    "parking_density": (0.0, 4.0),
    # Not a range at all - the page asks /api/settings for the options -
    # but every knob gets an entry so the settings form can be built blind.
    "arch_style": (0, 3),
    "height_mix": (0, 4),
}

BUILDING_ALIGNMENT_OPTIONS = ("real", "smart", "rectilinear", "rectangle")
ARCH_STYLE_OPTIONS = ("auto", "cn", "off")
HEIGHT_MIX_OPTIONS = ("auto", "low", "middle", "tall", "even")


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
