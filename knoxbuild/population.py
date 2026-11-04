"""A zombie spawn map drawn from who actually lived and worked there.

The first spawn map was painted from ground colour alone: tarmac got crowds,
grass got stragglers. That treats a car park and a street of five-storey flats
as the same place, and a town's busiest blocks no busier than its bypass.

Every building has already been placed on its real footprint with a storey
count and a kind by the time this runs, which is enough to estimate how many
people were in it. Homes are counted by floor area over the living space one
person has. Everything else - shops, schools, clinics, works - by how crowded
that kind of place is during the day, because the outbreak did not wait for
people to go home. Those people are spread over the map's 10x10-tile chunks,
softened a little so zombies spill into the streets around busy blocks, and
scaled into the spawn values the game reads.

What the game does with a spawn value is not something this can see: the
game's own Zombie Population sandbox setting multiplies everything again.
So the scale is anchored to the one thing that can be checked - vanilla Knox
County, whose spawn map runs 1 to 10 - and left adjustable.
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image
import knoxfiles

from generator import pz_colors as C

CHUNK = C.SPAWN_MAP_SCALE     # tiles per spawn-map pixel, each way

# People per square metre of floor, for buildings nobody lives in. Daytime
# figures: a school is packed, a warehouse nearly empty.
DAYTIME_M2_PER_PERSON = {
    "school": 8, "restaurant": 10, "church": 6, "shop": 15, "medical": 15,
    "civic": 20, "industrial": 60, "barn": 250,
}
RESIDENTIAL = {"house", "apartment"}

# Spawn value per person in a chunk, before the zombies-per-person dial. Set so
# a chunk wholly covered by five storeys of flats - about 500 m2 of floor, or
# 11 people at the default 45 m2 each - reaches 10, the densest value vanilla
# Knox County uses anywhere. Everything else scales down from there.
#
# Living space was 35 m2 (25 for a city), which is floor per person as a
# census counts it - net, in homes. Footprint floor area is gross: stairs,
# walls, shops and offices on the ground floor. Measured against real
# densities the old figures counted two to seven times the people: central
# Paris at 140,000 a km2 where the 4th arrondissement has 17,000, Kadikoy at
# 76,000, Tokyo's Nakano at 50,000 against 21,000. At 45 and 50 the census
# lands within reach of the real numbers, and this value moved with it so a
# town's zombies are exactly what they were.
VALUE_PER_PERSON = 0.9

# Share of each chunk's people who are out in the chunks around it rather
# than indoors, as a light blur. Without it the map is dotted with isolated
# hot spots exactly the shape of buildings, and the streets between them empty.
SPILL = 0.3

# People out on the street, per chunk of made ground, before the dials.
#
# Every zombie used to come from a building, so a town OpenStreetMap has the
# roads of but not the houses - which is most of the world outside Europe and
# the cities - came out empty: "there's not really any zombies where there
# aren't any houses, and all the zombies are heavily concentrated inside".
# The streets themselves say a place was lived in, so paved ground carries
# its own few, in proportion to how much of the chunk is made ground.
STREET_PEOPLE_PER_CHUNK = 1.3
# What counts as made ground: carriageway, pavement, car park, plaza.
STREET_COLOURS = (C.MEDIUM_ASPHALT, C.DARKEST_ASPHALT, C.DARK_ASPHALT,
                  C.LIGHT_ASPHALT, C.DARK_POTHOLE, C.LIGHT_POTHOLE,
                  C.PALE_CONCRETE, C.PAVING)
# Rows of the map measured at a time, so a town's bitmap is never held in
# memory twice over (see renderer.BOX_STRIP_ROWS).
GROUND_STRIP_CHUNKS = 64


def _ground_shares(path: str, gw: int, gh: int) -> tuple[np.ndarray, np.ndarray]:
    """(paved share, water share) of every chunk, 0..1."""
    from .bitmaps import read_rgb_rows, same_colour

    paved = np.zeros((gh, gw), dtype=float)
    water = np.zeros((gh, gw), dtype=float)
    for top in range(0, gh, GROUND_STRIP_CHUNKS):
        rows = min(GROUND_STRIP_CHUNKS, gh - top)
        # Only this strip is read. The picture used to be opened and converted
        # whole first, which held it twice over - what the strips were there
        # to avoid.
        strip = read_rgb_rows(path, top * CHUNK, (top + rows) * CHUNK, gw * CHUNK)
        if strip.shape[:2] != (rows * CHUNK, gw * CHUNK):
            continue
        is_paved = np.zeros(strip.shape[:2], dtype=bool)
        for colour in STREET_COLOURS:
            is_paved |= same_colour(strip, colour)
        is_water = same_colour(strip, C.WATER)
        shape = (rows, CHUNK, gw, CHUNK)
        paved[top:top + rows] = is_paved.reshape(shape).mean(axis=(1, 3))
        water[top:top + rows] = is_water.reshape(shape).mean(axis=(1, 3))
        del strip, is_paved, is_water
    return paved, water


def _split_scale(kind: str) -> tuple[str, float]:
    """('medical', 2.5) from 'medical:2.5'; ('medical', 0.25) from '...:closed'.

    Set by knoxbuild/hospitals.py from HIFLD BEDS, so a real hospital is
    stocked with more or fewer people than a generic medical building.
    """
    if ":" not in kind:
        return kind, 1.0
    base, _, suffix = kind.partition(":")
    if base != "medical":
        return kind, 1.0
    if suffix == "closed":
        return base, 0.25
    try:
        return base, max(0.1, float(suffix))
    except ValueError:
        return base, 1.0


def occupants(kind: str, tiles: int, levels: int, metres_per_tile: float,
              m2_per_person: float) -> tuple[float, float]:
    """(residents, daytime occupants) for one building."""
    if kind == "shed":
        return 0.0, 0.0
    kind, scale = _split_scale(kind)
    floor = tiles * metres_per_tile * metres_per_tile * max(1, levels)
    if kind in RESIDENTIAL:
        return floor / m2_per_person, 0.0
    return 0.0, scale * floor / DAYTIME_M2_PER_PERSON.get(kind, 25)


def _soften(grid: np.ndarray) -> np.ndarray:
    """A small separable blur, [1 4 6 4 1] each way, that keeps the total."""
    k = np.array([1, 4, 6, 4, 1], dtype=float) / 16.0
    padded = np.pad(grid, 2, mode="constant")
    rows = sum(k[i] * padded[:, i:i + grid.shape[1]] for i in range(5))
    cols = sum(k[i] * rows[i:i + grid.shape[0], :] for i in range(5))
    total = grid.sum()
    return cols * (total / cols.sum()) if cols.sum() > 0 else cols


def build_spawn_map(buildings: list[tuple[int, int, np.ndarray, int, str]],
                    map_w: int, map_h: int, metres_per_tile: float,
                    landscape_path: str | None, settings,
                    zoning=None) -> tuple[Image.Image, dict]:
    """Spawn map image and a summary, from placed buildings.

    `buildings` holds (x0, y0, mask, levels, kind) in tiles.
    """
    gw, gh = map_w // CHUNK, map_h // CHUNK
    people = np.zeros((gh, gw), dtype=float)
    residents_total = 0.0
    daytime_total = 0.0

    for x0, y0, mask, levels, kind in buildings:
        tiles = int(mask.sum())
        if not tiles:
            continue
        res, day = occupants(kind, tiles, levels, metres_per_tile,
                             settings.m2_per_person)
        residents_total += res
        daytime_total += day
        per_tile = (res + day) / tiles
        ys, xs = np.nonzero(mask)
        cx = np.clip((x0 + xs) // CHUNK, 0, gw - 1)
        cy = np.clip((y0 + ys) // CHUNK, 0, gh - 1)
        np.add.at(people, (cy, cx), per_tile)

    density = (1 - SPILL) * people + SPILL * _soften(people)

    street_total = 0.0
    if landscape_path and os.path.exists(landscape_path):
        paved, water = _ground_shares(landscape_path, gw, gh)
        # The people who were out when it happened, wherever there is a
        # street to be out on - even where nobody drew the buildings.
        street = STREET_PEOPLE_PER_CHUNK * paved
        street_total = float(street.sum())
        density = density + street
        # No zombies standing in rivers and lakes.
        density[water > 0.5] = 0.0

    # How many zombies each person becomes, and the most one chunk may hold -
    # both per chunk, because a zone may say something different about its own
    # part of the map. Outside every zone these are the map's own numbers
    # repeated, so a map with no zones gets exactly what it always did.
    per_resident = settings.zombies_per_resident
    cap = settings.spawn_density
    if zoning is not None and len(zoning):
        dials = zoning.chunk_values(("zombies_per_resident", "spawn_density"),
                                    gw, gh, CHUNK)
        per_resident = dials["zombies_per_resident"]
        cap = dials["spawn_density"]
    value = density * VALUE_PER_PERSON * per_resident
    # Round at random in proportion to the fraction, so a quiet street worth
    # 0.3 of a zombie still gets one now and then instead of never.
    rng = np.random.default_rng(settings.seed)
    whole = np.floor(value)
    value = whole + (rng.random(value.shape) < (value - whole))
    value = np.clip(value, 0, cap).astype(np.uint8)

    img = Image.fromarray(np.stack([value] * 3, axis=2), mode="RGB")
    populated = int((value > 0).sum())
    summary = {
        "residents": int(round(residents_total)),
        "daytime_occupants": int(round(daytime_total)),
        "on_the_street": int(round(street_total)),
        "people": int(round(residents_total + daytime_total + street_total)),
        "zombies_per_resident": settings.zombies_per_resident,
        "m2_per_person": settings.m2_per_person,
        "horde_cap": settings.spawn_density,
        "chunks": int(value.size),
        "chunks_with_zombies": populated,
        "share_with_zombies": round(populated / value.size, 4) if value.size else 0,
        "peak_value": int(value.max()) if value.size else 0,
        "chunks_at_cap": int((value >= cap).sum()),
        "spawn_total": int(value.sum()),
        # A person-for-zombie reading of the dial, for the page. The game
        # scales the real number again with its Zombie Population setting.
        "zombie_estimate": int(round((residents_total + daytime_total)
                                     * settings.zombies_per_resident)),
    }
    return img, summary


def save_footprints(path: str, buildings: list[tuple[int, int, np.ndarray, int, str]]) -> None:
    """Keep every building's footprint, so zombies can be recounted alone.

    Redrawing the spawn map needs nothing but where the buildings are, how tall
    and what they are - but getting that again meant rebuilding every building
    in town, minutes of work, to change one small image. Masks are packed to
    bits and stored end to end.
    """
    header = np.array([(x0, y0, m.shape[1], m.shape[0], lv) for x0, y0, m, lv, _k in buildings],
                      dtype=np.int32).reshape(-1, 5)
    bits = np.packbits(np.concatenate([b[2].ravel() for b in buildings])
                       if buildings else np.zeros(0, dtype=bool))
    kinds = np.array([k for *_, k in buildings])
    np.savez_compressed(path, header=header, bits=bits, kinds=kinds)


def load_footprints(path: str) -> list[tuple[int, int, np.ndarray, int, str]]:
    data = np.load(path, allow_pickle=False)
    header, kinds = data["header"], data["kinds"]
    total = int(sum(int(w) * int(h) for _x, _y, w, h, _l in header))
    flat = np.unpackbits(data["bits"])[:total].astype(bool)
    out, at = [], 0
    for (x0, y0, w, h, lv), kind in zip(header, kinds):
        n = int(w) * int(h)
        out.append((int(x0), int(y0), flat[at:at + n].reshape(int(h), int(w)), int(lv), str(kind)))
        at += n
    return out


def recount(out_dir: str, settings) -> dict:
    """Redraw a built map's spawn map from its saved footprints, in seconds."""
    names = [f for f in os.listdir(out_dir) if f.endswith("_info.json")]
    if not names:
        raise FileNotFoundError("not a generated map folder")
    map_name = names[0][: -len("_info.json")]
    fp_path = os.path.join(out_dir, f"{map_name}_footprints.npz")
    if not os.path.exists(fp_path):
        raise FileNotFoundError("generate the buildings first")
    info = knoxfiles.read(os.path.join(out_dir, f"{map_name}_info.json"),
                          "what the map is") or {}
    img, summary = build_spawn_map(load_footprints(fp_path), info["width_tiles"],
                                   info["height_tiles"], info["meters_per_tile"],
                                   os.path.join(out_dir, f"{map_name}.bmp"), settings)
    knoxfiles.save(img, os.path.join(out_dir, f"{map_name}_ZombieSpawnMap.bmp"),
                   format="BMP")
    summary["official"] = [p for p in official_population(out_dir, map_name)
                           if p.get("inside")][:5]
    knoxfiles.write(os.path.join(out_dir, f"{map_name}_population.json"),
                    summary, indent=2, ensure_ascii=False)
    return summary


def official_population(out_dir: str, map_name: str) -> list[dict]:
    """Places OpenStreetMap gives a population for, largest first."""
    path = os.path.join(out_dir, f"{map_name}_places.json")
    places = knoxfiles.read(path, "the towns and villages on the map", default=[])
    if not places:
        return []
    return sorted(places, key=lambda p: -p.get("population", 0))
