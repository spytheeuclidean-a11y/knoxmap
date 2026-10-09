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

# ...and where the *next* map sits, because two of them cannot sit in the
# same place. Every map used to be built at 70,0, so a player with two
# KnoxMap maps installed had both claiming the same cells: the game reads
# one cell's header and the other cell's data and falls over on the way in.
#
# So each map is given the first free run of cells east of the maps already
# installed, with a cell or two of empty ground between. They stay packed
# tight on purpose - the game lays out one grid covering every cell any map
# uses, so maps scattered across the world would be a grid mostly made of
# nothing, and the paper map draws the town smaller the further out it sits.
# A map with no other installed beside it lands on 70,0.
ORIGIN_GAP_CELLS = 2

_ORIGIN = list(WORLD_ORIGIN_CELLS)


def origin() -> tuple[int, int]:
    """Where the map being built now sits, in 300-tile cells."""
    return (_ORIGIN[0], _ORIGIN[1])


def set_origin(value) -> None:
    _ORIGIN[0], _ORIGIN[1] = int(value[0]), int(value[1])


def _project_box(pzw_path: str) -> tuple[int, int, int, int] | None:
    """(origin x, origin y, cells across, cells down) out of a .pzw."""
    import re
    try:
        with open(pzw_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    o = re.search(r'<worldOrigin origin="(-?\d+),(-?\d+)"', text)
    w = re.search(r'<world version="[^"]*" width="(\d+)" height="(\d+)"', text)
    if not (o and w):
        return None
    return int(o.group(1)), int(o.group(2)), int(w.group(1)), int(w.group(2))


def _installed_boxes() -> list[tuple[int, int, int, int]]:
    """Where the maps already installed on this PC sit, from the names of
    their compiled cells (<base>_<cell x>_<cell y>.lotheader). Compiled cells
    are 256 tiles, not 300, so they are converted back."""
    import os
    import re

    try:
        import knoxpaths
        mods = knoxpaths.zomboid_user_dir() / "mods"
    except Exception:      # noqa: BLE001 - no Zomboid folder, nothing installed
        return []
    boxes = []
    if not mods.is_dir():
        return []
    for maps in mods.glob("*/common/media/maps/*"):
        cells = []
        try:
            entries = os.listdir(maps)
        except OSError:
            continue
        for entry in entries:
            m = re.fullmatch(r".*_(\d+)_(\d+)\.lotheader", entry)
            if m:
                cells.append((int(m.group(1)), int(m.group(2))))
        if not cells:
            continue
        x0 = min(c[0] for c in cells) * 256 // CELL_SIZE
        y0 = min(c[1] for c in cells) * 256 // CELL_SIZE
        x1 = (max(c[0] for c in cells) + 1) * 256
        y1 = (max(c[1] for c in cells) + 1) * 256
        boxes.append((x0, y0, -(-x1 // CELL_SIZE) - x0, -(-y1 // CELL_SIZE) - y0))
    return boxes


def choose_origin(out_dir: str, cells_x: int, cells_y: int) -> tuple[int, int]:
    """A run of free cells for this map, keeping the one it already has.

    A map that has been built before keeps its place, so rebuilding it does
    not move a town out from under anybody's save.
    """
    import os

    here = os.path.abspath(out_dir)
    name = os.path.basename(here.rstrip(os.sep))
    mine = _project_box(os.path.join(here, f"{name}.pzw"))
    if mine:
        return mine[0], mine[1]

    # Only what is installed holds a place. Every generation makes a new
    # output folder, and those used to claim their cells for good: the tenth
    # map a PC built started ninety cells further east than the first, and the
    # paper map is one grid from cell 0, so the town drew as a speck in the
    # corner of an empty world. A folder nobody installed is a project on
    # disk, not something in anybody's game, and uninstalling a map now hands
    # its cells back.
    taken = _installed_boxes()

    ox, oy = WORLD_ORIGIN_CELLS
    for _ in range(len(taken) + 1):
        clash = [b for b in taken
                 if b[0] < ox + cells_x + ORIGIN_GAP_CELLS and ox < b[0] + b[2] + ORIGIN_GAP_CELLS
                 and b[1] < oy + cells_y + ORIGIN_GAP_CELLS and oy < b[1] + b[3] + ORIGIN_GAP_CELLS]
        if not clash:
            break
        ox = max(b[0] + b[2] for b in clash) + ORIGIN_GAP_CELLS
    return ox, oy

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
    # WorldEd lays a cell's lots down in the order this file lists them, and
    # what is laid last is drawn last. A porch light stands on the tile the
    # house wall is on, so sorted by position it went down before the wall
    # and the wall covered it. Anything that hangs on a building goes last.
    on_top: bool = False
    # Storeys. A taller building is laid after a lower one beside it: the lower one's
    # ceiling and roof tiles take the squares they are on, and that took the taller
    # one's upper-floor wall with them when it was laid first (a wall missing over a
    # neighbour's roof). Laid after, its wall is added to what is there.
    levels: int = 1

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


def _tool_path(path: str) -> str:
    """A folder as the map tools read it: forward slashes on Windows, and
    otherwise whatever the compiler in use can open - the machine's own name
    for a build made for it, a Wine name for the Windows one
    (knoxpaths.tool_path)."""
    if os.name == "nt":
        return path.replace("\\", "/")
    import knoxpaths
    return knoxpaths.tool_path(path)


def render_pzw(cells_x: int, cells_y: int, bmp_name: str,
               placements: list[Placement], map_name: str = "",
               project_dir: str = "",
               zones: list[Zone] | None = None) -> str:
    # Nothing may name a cell outside the world: WorldEd rejects the whole
    # project over one ("error reading world, invalid cell coordinates").
    def on_grid(cx: int, cy: int) -> bool:
        return 0 <= cx < cells_x and 0 <= cy < cells_y

    by_cell: dict[tuple[int, int], list[Placement]] = {}
    for p in placements:
        if on_grid(p.cell_x, p.cell_y):
            by_cell.setdefault((p.cell_x, p.cell_y), []).append(p)

    # The zombie spawn map, absolute for the same reason the export folders
    # below are.
    #
    # It sat in the same <GenerateLots> block as <exportdir> and was a bare
    # file name, so WorldEd looked for it next to its own executable, found
    # nothing, and baked a town with no zombies in it at all - "I did not
    # encounter a single one". The name is filled in further down, once the
    # project folder is known.
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
    # ...and off Windows they are what Wine calls them, because WorldEd is a
    # Windows program and "/home/you/maps" is not a path it can open.
    base = os.path.abspath(project_dir) if project_dir else ""
    tmx_dir = _tool_path(os.path.join(base, "tmx")) if base else "tmx"
    lots_dir = _tool_path(os.path.join(base, "lots")) if base else "lots"
    if base and spawn_map:
        spawn_map = _tool_path(os.path.join(base, spawn_map))

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
        f'  <worldOrigin origin="{origin()[0]},{origin()[1]}"/>',
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
        if on_grid(z.cell_x, z.cell_y):
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
        ox, oy = origin()
        # Checked on disk by its real name, written in the .pzw by the name
        # the tools use - the two differ under Wine.
        here = os.path.join(base, "tmx", f"{bmp_base}_{ox + cx}_{oy + cy}.tmx")
        return _tool_path(here) if os.path.exists(here) else ""

    # Every cell in the grid, not just the ones holding something: Generate Lots
    # needs a map on each cell it is asked to export.
    all_cells = [(cx, cy) for cy in range(cells_y) for cx in range(cells_x)]
    for (cx, cy) in sorted(set(all_cells) | set(by_cell) | set(zones_by_cell)):
        out.append(f' <cell x="{cx}" y="{cy}" map={quoteattr(cell_map(cx, cy))}>')
        for p in sorted(by_cell.get((cx, cy), []),
                        key=lambda q: (q.on_top, q.levels, q.offset_y, q.offset_x)):
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
