"""Generate a small, repeatable 1-cell in-game test map for open verification questions.

Usage:
    python tools/make_ingame_test_map.py
    python tools/make_ingame_test_map.py --compile
    python tools/make_ingame_test_map.py --out output/ingame_test_map

Places four test cases near one spawn point:
1. Kerb orientation (90-degree and angled street corners)
2. Drivable overpass (bridge=yes, layer=1 over a ground-level road)
3. Multi-storey building with lift (5-storey office for the Elevators mod)
4. Non-Latin place labels (Japanese, Arabic, Cyrillic)
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generator.osm import OSMFeature  # noqa: E402
from generator import renderer  # noqa: E402
from knoxbuild.build import build as build_buildings  # noqa: E402
from knoxbuild.settings import Settings  # noqa: E402

SOUTH, WEST = 40.0, 20.0
SIZE_M = 260.0
LAT_PER_M = 1.0 / 111320.0
LON_PER_M = 1.0 / (111320.0 * math.cos(math.radians(SOUTH)))
NORTH = SOUTH + SIZE_M * LAT_PER_M
EAST = WEST + SIZE_M * LON_PER_M
SEED = 424242

ROUTE_GUIDE = """In-game verification route (map: ingame_test_map, 1 cell = 300x300 tiles)

Spawn is placed near the central avenue (south-west of the crossroads).

Stop 1 - Kerb orientation (walk east from spawn to the first corner & diagonal turn)
  Expected: Raised kerb tiles face outward from the pavement onto the road on both
  the 90-degree corner and the angled side-street turn, with no inverted edges.

Stop 2 - Drivable overpass (drive east along the overpass approaches from Stop 1)
  Expected: A car can drive smoothly up the first ramp, across the elevated deck
  over the north-south secondary road, and down the far ramp without hitting an
  invisible wall or falling through.

Stop 3 - Lift in 5-storey office (north-west of the crossroads, beside the avenue)
  Expected: With the Elevators mod enabled, the lift doors open and carry the
  player between floors 0-4. Without the mod, the shaft doors remain closed.

Stop 4 - Non-Latin in-game map labels (press M anywhere in the cell)
  Expected: The three neighbourhood labels render legibly on the in-game map:
  テスト駅 (Japanese), الاختبار (Arabic), Тест (Cyrillic).
"""


def test_map_features() -> list[OSMFeature]:
    """Deterministic OSMFeature set covering kerbs, overpass, lift, and non-Latin labels."""
    feats: list[OSMFeature] = []

    def add(kind: str, tags: dict, points: list[tuple[float, float]]) -> None:
        latlons = [(SOUTH + y * LAT_PER_M, WEST + x * LON_PER_M) for x, y in points]
        feats.append(OSMFeature(len(feats) + 1, kind, tags, latlons))

    def rect(tags: dict, x: float, y: float, w: float, h: float) -> None:
        add("way", tags, [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)])

    # Ground-level north-south secondary road (crossed by the overpass)
    add("way", {"highway": "secondary", "name": "Cross Road"}, [(150, 20), (150, 240)])
    # Main east-west avenue with a bridge=yes, layer=1 overpass over Cross Road
    add("way", {"highway": "primary", "name": "Test Avenue"}, [(20, 120), (110, 120)])
    add("way", {"highway": "primary", "name": "Test Overpass", "bridge": "yes", "layer": "1"},
        [(110, 120), (190, 120)])
    add("way", {"highway": "primary", "name": "Test Avenue"}, [(190, 120), (240, 120)])
    # Side street with a 90-degree turn and a 45-degree diagonal segment for kerb checks
    add("way", {"highway": "residential", "name": "Kerb Lane"},
        [(65, 120), (65, 60), (105, 35)])

    # 5-storey office building near spawn for lift testing
    rect({"building": "office", "building:levels": "5", "name": "Lift Tower"}, 25, 145, 36, 30)
    # Small house near spawn so spawn_density has a residential anchor
    rect({"building": "house", "name": "Spawn Cottage"}, 30, 70, 16, 14)

    # Non-Latin place labels
    add("node", {"place": "neighbourhood", "name": "テスト駅", "population": "1000"}, [(75, 195)])
    add("node", {"place": "neighbourhood", "name": "الاختبار", "population": "1000"}, [(195, 195)])
    add("node", {"place": "neighbourhood", "name": "Тест", "population": "1000"}, [(195, 65)])
    return feats


def build_test_map(out_dir: str | Path, map_name: str = "ingame_test_map",
                   *, do_compile: bool = False) -> Path:
    """Render, furnish, write ROUTE.txt, and optionally Rust-compile the test map."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_dict({
        "preset": "town",
        "seed": SEED,
        "straight_roads": 0,
        "flyovers": 1,
    })
    feats = test_map_features()
    renderer.render(
        feats, SOUTH, WEST, NORTH, EAST,
        meters_per_tile=1.0, output_dir=str(out), map_name=map_name,
        straight_roads=0, terrain_only=0,
    )
    build_buildings(str(out), settings=settings)
    (out / "ROUTE.txt").write_text(ROUTE_GUIDE, encoding="utf-8")
    if do_compile:
        from tools.compile_map import compile_rust
        compile_rust(str(out), map_name)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "output" / "ingame_test_map"),
                        help="Output directory for the generated test map")
    parser.add_argument("--compile", action="store_true",
                        help="Also run Rust knoxlots compile")
    args = parser.parse_args()
    out = build_test_map(args.out, do_compile=args.compile)
    print(f"Generated in-game test map in {out}")
    print(f"Route guide written to {out / 'ROUTE.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
