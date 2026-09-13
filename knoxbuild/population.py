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

import json
import os

import numpy as np
from PIL import Image

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
# 14 people at 35 m2 each - reaches 10, the densest value vanilla Knox County
# uses anywhere. Everything else scales down from there.
VALUE_PER_PERSON = 0.7

# Share of each chunk's people who are out in the chunks around it rather
# than indoors, as a light blur. Without it the map is dotted with isolated
# hot spots exactly the shape of buildings, and the streets between them empty.
SPILL = 0.3


def occupants(kind: str, tiles: int, levels: int, metres_per_tile: float,
              m2_per_person: float) -> tuple[float, float]:
    """(residents, daytime occupants) for one building."""
    floor = tiles * metres_per_tile * metres_per_tile * max(1, levels)
    if kind in RESIDENTIAL:
        return floor / m2_per_person, 0.0
    return 0.0, floor / DAYTIME_M2_PER_PERSON.get(kind, 25)


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
                    landscape_path: str | None, settings) -> tuple[Image.Image, dict]:
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

    # No zombies standing in rivers and lakes.
    if landscape_path and os.path.exists(landscape_path):
        land = Image.open(landscape_path).convert("RGB").resize((gw, gh), Image.Resampling.NEAREST)
        water = np.all(np.array(land) == np.array(C.WATER), axis=2)
        density[water] = 0.0

    value = density * VALUE_PER_PERSON * settings.zombies_per_resident
    cap = settings.spawn_density
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
        "people": int(round(residents_total + daytime_total)),
        "zombies_per_resident": settings.zombies_per_resident,
        "m2_per_person": settings.m2_per_person,
        "horde_cap": cap,
        "chunks": int(value.size),
        "chunks_with_zombies": populated,
        "share_with_zombies": round(populated / value.size, 4) if value.size else 0,
        "peak_value": int(value.max()) if value.size else 0,
        "chunks_at_cap": int((value >= cap).sum()) if cap else 0,
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
    with open(os.path.join(out_dir, f"{map_name}_info.json")) as f:
        info = json.load(f)
    img, summary = build_spawn_map(load_footprints(fp_path), info["width_tiles"],
                                   info["height_tiles"], info["meters_per_tile"],
                                   os.path.join(out_dir, f"{map_name}.bmp"), settings)
    img.save(os.path.join(out_dir, f"{map_name}_ZombieSpawnMap.bmp"), format="BMP")
    summary["official"] = [p for p in official_population(out_dir, map_name)
                           if p.get("inside")][:5]
    with open(os.path.join(out_dir, f"{map_name}_population.json"), "w",
              encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return summary


def official_population(out_dir: str, map_name: str) -> list[dict]:
    """Places OpenStreetMap gives a population for, largest first."""
    path = os.path.join(out_dir, f"{map_name}_places.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            places = json.load(f)
    except (OSError, ValueError):
        return []
    return sorted(places, key=lambda p: -p.get("population", 0))
