"""What a building's surroundings say it is.

OSM rarely tags what a building is used for: in the town this was built on,
3015 of 3079 buildings were plain building=yes. The land they stand on is
tagged far more often - an industrial estate, a school's grounds, a hospital
site, a cemetery - and a building inside one of those is almost always part of
it. Reading that turns an anonymous box on an industrial estate into a works,
and the shed in a schoolyard into part of the school, instead of the suburban
house every untagged building used to become.
"""
from __future__ import annotations

import json
import os

from shapely import STRtree
from shapely.geometry import Point, Polygon

# Area category -> building kind, for buildings OSM says nothing about.
# Residential and parking are left out on purpose: a building in a
# residential area is exactly what the house and flats logic already decides,
# and one in a car park is a kiosk not worth guessing at.
KIND_FOR_AREA = {
    "industrial": "industrial",
    "commercial": "shop",
    "schoolyard": "school",
    "hospital_grounds": "medical",
    "military": "military",
    "worship_grounds": "church",
    "cemetery": "church",
    "sports": "civic",
}
# Below this many tiles, a building on institutional grounds is an outbuilding
# rather than the institution itself.
OUTBUILDING = 120


class AreaIndex:
    def __init__(self, polygons: list[tuple[Polygon, dict]]):
        self._items = polygons
        self._tree = STRtree([p for p, _ in polygons]) if polygons else None

    @classmethod
    def load(cls, out_dir: str, map_name: str, proj) -> "AreaIndex":
        path = os.path.join(out_dir, f"{map_name}_areas.geojson")
        if not os.path.exists(path):
            return cls([])
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        items = []
        for feat in data.get("features", []):
            geom = feat.get("geometry") or {}
            polys = geom.get("coordinates") or []
            if geom.get("type") == "Polygon":
                polys = [polys]
            for poly in polys:
                if not poly or len(poly[0]) < 3:
                    continue
                ring = [proj.to_px(lat, lon) for lon, lat in poly[0]]
                shape = Polygon(ring)
                if not shape.is_valid:
                    shape = shape.buffer(0)
                if shape.is_empty or shape.area <= 0:
                    continue
                items.append((shape, feat.get("properties") or {}))
        return cls(items)

    def around(self, x: float, y: float) -> dict | None:
        """The most specific area containing a point: the smallest one.

        Areas nest - a school inside a residential district - and the inner
        one is the one that says what is actually there.
        """
        if self._tree is None:
            return None
        point = Point(x, y)
        best = None
        for i in self._tree.query(point):
            shape, props = self._items[int(i)]
            if shape.contains(point) and (best is None or shape.area < best[0]):
                best = (shape.area, props)
        return best[1] if best else None

    def kind_for(self, x: float, y: float, tiles: int) -> str | None:
        props = self.around(x, y)
        if not props:
            return None
        category = props.get("category")
        kind = KIND_FOR_AREA.get(category)
        if kind in {"school", "medical"} and tiles < OUTBUILDING:
            return "civic"
        return kind

    def category_at(self, x: float, y: float) -> str | None:
        props = self.around(x, y)
        return props.get("category") if props else None
