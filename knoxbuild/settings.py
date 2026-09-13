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
    # Living space per resident, in square metres. It is what turns a
    # building's floor area into a head count, and it varies a lot by place:
    # roughly 25 in a dense city, 35 in a typical European town, 60 or more
    # in American suburbs.
    m2_per_person: float = 35.0

    # --- terrain ---------------------------------------------------------
    # Multiplies how much of a forest polygon actually becomes trees.
    tree_density: float = 1.0

    # --- buildings -------------------------------------------------------
    seed: int = 1
    min_size: int = 5            # skip footprints smaller than this, in tiles
    # and larger than this. It was 60, which threw away the largest
    # buildings in town - the factory, the cultural centre - which are
    # exactly the landmarks a place is recognised by.
    max_size: int = 200
    # An untagged footprint at least this big is read as a block of flats,
    # this often. OSM rarely says, so these two decide a town's character.
    apartment_footprint: int = 150
    apartment_chance: float = 0.55
    max_levels: int = 6
    # Below 1 means fewer windows. A house at 1.0 gets one every five tiles of
    # wall; the old behaviour was one every three, around the whole perimeter.
    window_density: float = 1.0
    room_size: int = 56          # target room area in tiles before splitting
    # How far a neighbourhood reaches before the materials change, and how
    # often one building breaks from its block anyway.
    neighbourhood_tiles: int = 110
    style_oddity: float = 0.18

    # --- zones -----------------------------------------------------------
    # Scales how many ParkingStall zones are found. Vehicles only ever spawn
    # inside one, so this is the dial for how many cars are in the streets.
    parking_density: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Settings":
        """Build from untrusted input, ignoring junk and clamping the rest."""
        data = data or {}
        preset = PRESETS.get(str(data.get("preset", "")).lower())
        base = preset.to_dict() if preset else {}

        kept: dict = {}
        types = {f.name: f.type for f in fields(cls)}
        for name, raw in list(base.items()) + list(data.items()):
            if name not in types:
                continue          # unknown key, including "preset" itself
            try:
                value = int(raw) if types[name] == "int" else float(raw)
            except (TypeError, ValueError):
                continue          # unparseable, keep the default
            lo, hi = LIMITS[name]
            kept[name] = min(max(value, lo), hi)
        return cls(**kept)

    @property
    def window_spacing_scale(self) -> float:
        """Multiplier on the per-kind window spacing. Denser means smaller."""
        return 1.0 / self.window_density


# name -> (minimum, maximum). Wider than anyone sensibly wants, narrow enough
# that nothing here can produce a building the .tbx reader rejects.
LIMITS = {
    "spawn_density": (0, 60),
    "zombies_per_resident": (0.0, 5.0),
    "m2_per_person": (10.0, 150.0),
    "tree_density": (0.0, 3.0),
    "seed": (0, 2 ** 31 - 1),
    # MIN_ROOM in layout.py is 3, and a building has to hold at least one room
    # plus its walls. MAX_BUILDING_DIMENSION in the reader is 300.
    "min_size": (4, 40),
    "max_size": (8, 250),
    "apartment_footprint": (16, 4000),
    "apartment_chance": (0.0, 1.0),
    # Every storey is a full floor of rooms and furniture; past six the roof
    # reaches the game's ceiling and the file gets big for no visible gain.
    "max_levels": (1, 6),
    "window_density": (0.2, 3.0),
    "room_size": (16, 400),
    "neighbourhood_tiles": (20, 2000),
    "style_oddity": (0.0, 1.0),
    "parking_density": (0.0, 4.0),
}


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
                     m2_per_person=25.0),
    # Scattered farms and barns under heavy tree cover.
    "rural": Settings(apartment_footprint=2000, apartment_chance=0.0,
                      max_levels=2, spawn_density=4, tree_density=2.0,
                      m2_per_person=70.0,
                      parking_density=0.4, neighbourhood_tiles=300),
}

DEFAULT = Settings()
