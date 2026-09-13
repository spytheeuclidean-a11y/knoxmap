"""Write a WorldEd project (.pzw) with every generated building pre-placed.

Schema from WorldWriter in timbaker/pzworlded. A <lot>'s x/y are relative to
the cell that holds it, so a building at map tile (tx, ty) lands in cell
(tx // 300, ty // 300) at offset (tx % 300, ty % 300).

Only <bmp> and <cell> are emitted. WorldEd's reader routes anything it does not
recognise through readUnknownElement() and applies defaults for the settings
blocks we leave out, so a minimal project opens cleanly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from xml.sax.saxutils import quoteattr

CELL_SIZE = 300

# Where the generated map sits in the shared world, in source (300-tile) cells.
#
# Vanilla "Muldraugh, KY" occupies compiled cells 0..77 x 0..62 — the whole of
# Knox County. A map generated at origin 0,0 lands on top of it: a tiny one can
# get away with it by landing in an empty corner, but anything the size of a
# real town collides and the region never shows up. 70 source cells is 21000
# tiles, which starts past vanilla's eastern edge (77 * 256 = 19712) with room
# to spare.
WORLD_ORIGIN_CELLS = (70, 0)

# Lot-export worker threads.
#
# WorldEd defaults to one per core, up to 16. Each worker holds a whole
# combined cell - four source cells and every building map placed on them -
# so on a real town the count is a memory multiplier, not just a speed dial:
# 16 workers on downtown Pergamon reached 11 GB inside a single batch. Four
# keeps the peak near a gigabyte and still saturates the disk.
GENERATE_LOTS_THREADS = 4


# Zones the game reads out of the world: ParkingStall is where vehicles spawn,
# TownZone marks built-up ground. Vanilla Knox County carries 9694 parking
# stalls and 2715 town zones - without them the streets are bare tarmac and
# nothing drives or parks anywhere.
ZONE_GROUPS = [
    ("ParkingStall", "#ff007f"),
    ("TownZone", "#aa0000"),
]


@dataclass
class Zone:
    kind: str          # "ParkingStall" | "TownZone"
    tile_x: int        # absolute tile coords
    tile_y: int
    width: int
    height: int

    @property
    def cell_x(self) -> int:
        return self.tile_x // CELL_SIZE

    @property
    def cell_y(self) -> int:
        return self.tile_y // CELL_SIZE

    @property
    def offset_x(self) -> int:
        return self.tile_x % CELL_SIZE

    @property
    def offset_y(self) -> int:
        return self.tile_y % CELL_SIZE


@dataclass
class Placement:
    tbx_path: str      # relative to the .pzw
    tile_x: int        # absolute tile coords in the whole map
    tile_y: int
    width: int
    height: int

    @property
    def cell_x(self) -> int:
        return self.tile_x // CELL_SIZE

    @property
    def cell_y(self) -> int:
        return self.tile_y // CELL_SIZE

    @property
    def offset_x(self) -> int:
        return self.tile_x % CELL_SIZE

    @property
    def offset_y(self) -> int:
        return self.tile_y % CELL_SIZE


def render_pzw(cells_x: int, cells_y: int, bmp_name: str,
               placements: list[Placement], map_name: str = "",
               project_dir: str = "",
               zones: list[Zone] | None = None) -> str:
    by_cell: dict[tuple[int, int], list[Placement]] = {}
    for p in placements:
        by_cell.setdefault((p.cell_x, p.cell_y), []).append(p)

    spawn_map = f"{map_name}_ZombieSpawnMap.bmp" if map_name else ""

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<world version="1.0" width="{cells_x}" height="{cells_y}">']

    # Pre-fill the conversion settings so BMP -> TMX and Generate Lots are
    # ready to run without visiting their dialogs first. Element order and
    # names mirror WorldWriter and a real vanilla project (Kentucky.pzw).
    # assign-maps-to-world is on so the generated TMX files attach themselves
    # to the cells, which start out with no map.
    # Absolute paths: WorldEd resolves a relative export dir against its own
    # working directory, not the project, so a relative "tmx" silently writes
    # nowhere useful when it is launched from its bin folder.
    base = os.path.abspath(project_dir) if project_dir else ""
    tmx_dir = os.path.join(base, "tmx").replace("\\", "/") if base else "tmx"
    lots_dir = os.path.join(base, "lots").replace("\\", "/") if base else "lots"

    out += [
        " <BMPToTMX>",
        f'  <tmxexportdir path={quoteattr(tmx_dir)}/>',
        '  <rulesfile path=""/>',
        '  <blendsfile path=""/>',
        '  <mapbasefile path=""/>',
        '  <assign-maps-to-world checked="true"/>',
        '  <warn-unknown-colors checked="true"/>',
        '  <compress checked="true"/>',
        '  <copy-pixels checked="true"/>',
        # Must be false on a first run: with it on, BMPToTMX writes to each
        # cell's existing map path, and a freshly generated project has none.
        '  <update-existing checked="false"/>',
        " </BMPToTMX>",
        " <TMXToBMP>",
        '  <mainImage generate="true"/>',
        '  <vegetationImage generate="true"/>',
        '  <buildingsImage path="" generate="false"/>',
        " </TMXToBMP>",
        " <GenerateLots>",
        f'  <exportdir path={quoteattr(lots_dir)}/>',
        f'  <ZombieSpawnMap path={quoteattr(spawn_map)}/>',
        '  <TileDefFolder path=""/>',
        f'  <worldOrigin origin="{WORLD_ORIGIN_CELLS[0]},{WORLD_ORIGIN_CELLS[1]}"/>',
        f'  <numberOfThreads count="{GENERATE_LOTS_THREADS}"/>',
        " </GenerateLots>",
        " <LuaSettings>",
        '  <spawnPointsFile path="spawnpoints.lua"/>',
        '  <worldObjectsFile path="objects.lua"/>',
        " </LuaSettings>",
    ]

    # Types must be declared before groups, and both before any object
    # references them - WorldReader errors out otherwise.
    for name, _colour in ZONE_GROUPS:
        out.append(f'  <objecttype name={quoteattr(name)}/>')
    for name, colour in ZONE_GROUPS:
        out.append(f'  <objectgroup name={quoteattr(name)}'
                   f' color={quoteattr(colour)}'
                   f' defaulttype={quoteattr(name)}/>')

    out.append(f' <bmp path={quoteattr(bmp_name)} x="0" y="0"'
               f' width="{cells_x}" height="{cells_y}"/>')

    zones_by_cell: dict[tuple[int, int], list[Zone]] = {}
    for z in zones or []:
        zones_by_cell.setdefault((z.cell_x, z.cell_y), []).append(z)

    # Point each cell at its TMX when that file already exists.
    #
    # BMP to TMX assigns these in memory and they are only persisted when the
    # project is saved; a headless run that dies before saving leaves every
    # cell at map="" and Generate Lots then refuses with "missing reference".
    # Writing the paths here means a re-run can skip conversion entirely and go
    # straight to compiling. The name is WorldEd's own convention from
    # tmxNameForCell: <bmp base>_<originX + x>_<originY + y>.tmx
    bmp_base = os.path.splitext(os.path.basename(bmp_name))[0]

    def cell_map(cx: int, cy: int) -> str:
        if not base:
            return ""
        path = os.path.join(tmx_dir, f"{bmp_base}_"
                            f"{WORLD_ORIGIN_CELLS[0] + cx}_"
                            f"{WORLD_ORIGIN_CELLS[1] + cy}.tmx")
        return path.replace("\\", "/") if os.path.exists(path) else ""

    # Every cell in the grid, not just the ones holding something: Generate Lots
    # needs a map on each cell it is asked to export.
    all_cells = [(cx, cy) for cy in range(cells_y) for cx in range(cells_x)]
    for (cx, cy) in sorted(set(all_cells) | set(by_cell) | set(zones_by_cell)):
        out.append(f' <cell x="{cx}" y="{cy}" map={quoteattr(cell_map(cx, cy))}>')
        for p in sorted(by_cell.get((cx, cy), []),
                        key=lambda q: (q.offset_y, q.offset_x)):
            out.append(
                f'  <lot x="{p.offset_x}" y="{p.offset_y}" level="0"'
                f' width="{p.width}" height="{p.height}"'
                f' map={quoteattr(p.tbx_path)}/>')
        for z in zones_by_cell.get((cx, cy), []):
            out.append(
                f'  <object name="" group={quoteattr(z.kind)}'
                f' type={quoteattr(z.kind)}'
                f' x="{z.offset_x}" y="{z.offset_y}" level="0"'
                f' width="{z.width}" height="{z.height}"/>')
        out.append(" </cell>")

    out.append("</world>")
    return "\n".join(out) + "\n"
