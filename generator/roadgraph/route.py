"""The roads routed on vanilla's lattice, for the renderer: the "Road layout"
setting's vanilla choices (straight_roads 2 and 3).

    route(features, proj, mode) -> graph

1. The road graph from the map's OSM ways (network.py): junction-to-junction
   links with a class and a width; dual carriageways made one road, lanes that
   hug a bigger road folded into it, turning loops dropped.
2. Every link routed on the tile-corner lattice in vanilla B42's sixteen
   directions - along the grid, 2:1, 45 and 1:2 - fitted where it can be to
   one of the street shapes vanilla's own map draws between junctions
   (snap.py, templates.py). Main roads first and whole; streets straight in
   OSM squared exactly.
3. The graph octilinear.apply_road_graph reads: each OSM way's new line (cut
   to its corners), the ways the graph dropped, and points along the roads
   before and after, by which everything else moves with the roads near it.

"graph" routes every road the same way; "cost" keeps built-up streets on the
grid, as the buildings along them are, and off the buildings (modes.py).

It is slow beside straightening - minutes on a town of a few hundred streets,
the time going on the search for each link (snap.MAX_STATES) - so it runs
once, in Generate, and the result is saved beside the map for every later
step.
"""
from __future__ import annotations

import math
import threading

import numpy as np
import shapely
from PIL import Image, ImageDraw

from . import modes, network, raster, snap

TOWN_REACH = 40              # tiles from a building: in town (the narrower band)
SHIFT_EVERY = 4              # tiles between the points along a road that say how far it moved
# snap and modes keep the routing's settings in module globals: one routing at a time.
_LOCK = threading.Lock()


def town_mask(rings, H: int, W: int, reach: int = TOWN_REACH) -> np.ndarray:
    """Within `reach` tiles of a building's centre."""
    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)
    for pts in rings:
        x = sum(p[0] for p in pts) / len(pts)
        y = sum(p[1] for p in pts) / len(pts)
        if 0 <= x < W and 0 <= y < H:
            cx, cy = int(x) + 0.5, int(y) + 0.5
            d.ellipse((cx - reach, cy - reach, cx + reach, cy + reach), fill=1)
    return np.array(img, bool)


def shift_samples(links, paths, proj) -> list:
    """[[lat, lon, lat, lon]]: points every SHIFT_EVERY tiles along each routed
    link, where they really are and where the routed road put them (the same
    share of the way along it)."""
    out = []
    for i, path in paths.items():
        real, snapped = shapely.LineString(links[i].pts), shapely.LineString(path)
        if real.length == 0 or snapped.length == 0:
            continue
        for t in np.linspace(0.0, 1.0, max(1, int(real.length // SHIFT_EVERY)) + 1):
            p, q = real.interpolate(t, normalized=True), snapped.interpolate(t, normalized=True)
            out.append([*proj.to_latlon(p.x, p.y), *proj.to_latlon(q.x, q.y)])
    return out


def route(features: list, proj, mode: str = "graph", shape: dict | None = None, log=print,
          tick=None) -> dict:
    """The map's roads routed (see the module's notes). `features` is not changed.
    tick(done, total) is called as links are routed (it may raise to stop)."""
    with _LOCK:
        H, W = proj.height, proj.width
        nodes, links, pins = network.build(features, proj, shape)
        rings = modes.building_rings(features, proj)
        town = town_mask(rings, H, W)
        used = modes.prepare(mode, rings, H, W)
        try:
            paths, _corner, _merged, failed = snap.snap(nodes, links, town, log=log, pins=pins, tick=tick)
        finally:
            modes.reset()
            snap.close_router()             # one search process per map: none left behind on a stop
    log(f"roads routed ({mode}): {len(paths)} of {len(links)} links, {len(failed)} left as drawn")
    road = network.road_ways(features)
    real = {f.osm_id: [proj.to_px(la, lo) for la, lo in f.geometry] for f in road}
    lines = network.way_lines(links, paths, real)
    # Each way cut to its corners, keeping every point another way ends on: a side
    # road's end is a node of the road it joins, as in OSM.
    ends = {tuple(geo[k]) for geo, _l in lines.values() for k in (0, -1)}
    ways = {}
    for w, (geo, l) in lines.items():
        corners = set(raster.vertices(geo))
        keep = [p for k, p in enumerate(geo) if (p in corners or tuple(p) in ends)
                and (k == 0 or p != geo[k - 1])]
        # A dual carriageway's two ways share the one line and are drawn at their own
        # width: one ordinary road, as vanilla draws most of its own.
        ways[str(w)] = {"geometry": [list(proj.to_latlon(x, y)) for x, y in keep], "tags": {}}
    # Roundabouts as drawn; a road routed into one ends exactly on its node (the
    # route ends on the tile corner nearest it).
    ring_nodes = []
    for f in network.roundabouts(features):
        ways[str(f.osm_id)] = {"geometry": [list(p) for p in f.geometry], "tags": {}}
        ring_nodes += [(proj.to_px(*p), list(p)) for p in f.geometry]
    for g in ways.values():
        for k in (0, -1):
            at = proj.to_px(*g["geometry"][k])
            near = min(ring_nodes, key=lambda n: math.dist(n[0], at), default=None)
            if near is not None and 0 < math.dist(near[0], at) <= 1.0:
                g["geometry"][k] = near[1]
    # The ways the graph left out (folded into another road, a turning loop) go;
    # a link that could not be routed keeps its ways as drawn.
    unrouted = {w for i in failed for w in links[i].ways}
    drop = [f.osm_id for f in road if str(f.osm_id) not in ways and f.osm_id not in unrouted]
    return {"ways": ways, "drop": drop, "shift": shift_samples(links, paths, proj), "road_mode": used}
