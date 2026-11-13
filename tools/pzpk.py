"""PZPK reader: atlases, their tile lists, and the image each one carries.

A pack is one header, then a block per atlas: its name, how many tiles it
holds, the tiles, and the PNG they are cut from. The tile's rect in the fields
is in that PNG's pixels, which is what makes a pack readable without the game.
"""
from __future__ import annotations

import io
import struct
from dataclasses import dataclass

from PIL import Image


@dataclass
class Tile:
    name: str
    atlas: int
    x: int
    y: int
    w: int
    h: int
    offset_x: int
    offset_y: int
    tex_w: int
    tex_h: int


def read_pack(path) -> tuple[list[Tile], list[Image.Image]]:
    data = open(path, "rb").read()
    if data[:4] != b"PZPK":
        raise ValueError("not a PZPK pack")
    atlases, = struct.unpack_from("<I", data, 8)
    pos = 12

    tiles: list[Tile] = []
    images: list[Image.Image] = []
    for index in range(atlases):
        length, = struct.unpack_from("<I", data, pos)
        pos += 4
        name = data[pos:pos + length].decode("ascii")
        pos += length
        # the atlas number is written after the base name, so "Tiles2x" + "0"
        while pos < len(data) and data[pos:pos + 1].isdigit():
            name += data[pos:pos + 1].decode("ascii")
            pos += 1
        count, = struct.unpack_from("<I", data, pos)
        pos += 4
        pos += 4                                   # a flag, always 1 so far
        for _ in range(count):
            n, = struct.unpack_from("<I", data, pos)
            pos += 4
            tile_name = data[pos:pos + n].decode("ascii")
            pos += n
            fields = struct.unpack_from("<8I", data, pos)
            pos += 32
            tiles.append(Tile(tile_name, index, *fields))
        start = data.find(b"\x89PNG", pos)
        end = data.find(b"IEND", start) + 8
        images.append(Image.open(io.BytesIO(data[start:end])).convert("RGBA"))
        pos = end
    return tiles, images


if __name__ == "__main__":
    import sys

    tiles, images = read_pack(sys.argv[1])
    print("atlases", len(images), "sizes", [im.size for im in images][:4])
    print("tiles", len(tiles))
    missing = 0
    for tile in tiles:
        image = images[tile.atlas]
        if tile.x + tile.w > image.width or tile.y + tile.h > image.height:
            missing += 1
            continue
        art = image.crop((tile.x, tile.y, tile.x + tile.w, tile.y + tile.h))
        if not art.getbbox():
            missing += 1
    print("tiles with no art where they say they are:", missing)
    diag = [t for t in tiles if t.name.startswith("street_curbs_01_diag")]
    print("diag tiles", len(diag), "atlases", sorted({t.atlas for t in diag}))
