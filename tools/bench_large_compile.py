"""Expand exported real knoxlots cell sources into a repeatable large compile benchmark.

Run `knoxlots export <existing lots> <source> --keep-zombie` first, then:
    python tools/bench_large_compile.py <source> <destination> 51 48

Only the KCEL header coordinates change; the existing cell contents and room
tables are kept, so this measures compilation, not realistic town planning.
"""
import argparse
from pathlib import Path
import re
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("width", type=int)
    parser.add_argument("height", type=int)
    args = parser.parse_args()
    if args.width < 1 or args.height < 1:
        parser.error("width and height must be positive")
    if args.destination.exists() and any(args.destination.iterdir()):
        parser.error("destination must be new or empty")
    templates = []
    for path in sorted(args.source.glob("cell_*.kcell")):
        match = re.fullmatch(r"cell_(\d+)_(\d+)\.kcell", path.name)
        if match:
            templates.append((int(match[1]), int(match[2]), path.read_bytes()))
    if not templates:
        parser.error("no exported cell sources")
    for x, y, data in templates:
        if data[:4] != b"KCEL" or struct.unpack_from("<II", data, 8) != (x, y):
            parser.error(f"invalid source header: cell_{x}_{y}.kcell")
    x0, y0 = min(t[0] for t in templates), min(t[1] for t in templates)
    args.destination.mkdir(parents=True, exist_ok=True)
    (args.destination / "source.txt").write_text(
        "format = knoxlots-source 1\norigin_x = 0\norigin_y = 0\n", encoding="utf-8")
    for row in range(args.height):
        for col in range(args.width):
            x, y = x0 + col, y0 + row
            original = templates[(row * args.width + col) % len(templates)][2]
            data = bytearray(original)
            struct.pack_into("<II", data, 8, x, y)
            (args.destination / f"cell_{x}_{y}.kcell").write_bytes(data)
        print(f"prepared row {row + 1}/{args.height}", flush=True)
    print(f"prepared {args.width * args.height} cells from {len(templates)} real cell templates")


if __name__ == "__main__":
    main()
