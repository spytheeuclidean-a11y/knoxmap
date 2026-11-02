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

import os

import knoxfiles
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


def parts(shape) -> list[Polygon]:
    """Every plain polygon in a geometry.

    A ring that touches or crosses itself - a landuse boundary drawn as one
    way round two yards, or a relation the download cut in half - is mended
    with buffer(0), and what comes back is then several polygons rather than
    one. Kept whole, a shape with no outline of its own sat in the index, and
    whatever asked it for one fell over; the parts go in as themselves.
    """
    if shape is None or shape.is_empty:
        return []
    if isinstance(shape, Polygon):
        return [shape]
    out = []
    for part in getattr(shape, "geoms", ()) or ():
        out.extend(parts(part))
    return out


class AreaIndex:
    def __init__(self, polygons: list[tuple[Polygon, dict]]):
        self._items = polygons
        self._tree = STRtree([p for p, _ in polygons]) if polygons else None
        # How big each area is all told. An outline that came in in several
        # pieces is still one area, and "the smallest one here wins" has to
        # weigh the whole of it: half an industrial estate is smaller than
        # the school inside it, and would have answered for its ground.
        self._whole: dict[int, float] = {}
        for shape, props in polygons:
            self._whole[id(props)] = self._whole.get(id(props), 0.0) + shape.area

    @classmethod
    def load(cls, out_dir: str, map_name: str, proj) -> "AreaIndex":
        path = os.path.join(out_dir, f"{map_name}_areas.geojson")
        data = knoxfiles.read(path, "the land use")
        if not data:
            return cls([])
        items = []
        for feat in data.get("features", []):
            # One table of properties for every piece of this feature, so the
            # pieces are known below to be pieces of one area.
            props = feat.get("properties") or {}
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
                for part in parts(shape):
                    if part.area <= 0:
                        continue
                    items.append((part, props))
        return cls(items)

    def around(self, x: float, y: float) -> dict | None:
        """The most specific area containing a point: the smallest one.

        Areas nest - a school inside a residential district - and the inner
        one is the one that says what is actually there.
        """
        best = self._smallest(x, y)
        return best[1] if best else None

    def shape_around(self, x: float, y: float):
        """The polygon around() reads its answer from: the site a military
        base's basement spreads under (knoxbuild/basements.py)."""
        best = self._smallest(x, y)
        return best[0] if best else None

    def _smallest(self, x: float, y: float):
        if self._tree is None:
            return None
        point = Point(x, y)
        best = None
        for i in self._tree.query(point):
            shape, props = self._items[int(i)]
            size = self._whole.get(id(props), shape.area)
            if shape.contains(point) and (best is None or size < best[0]):
                best = (size, shape, props)
        return best[1:] if best else None

    def kind_for(self, x: float, y: float, tiles: int) -> str | None:
        props = self.around(x, y)
        if not props:
            return None
        category = props.get("category")
        kind = KIND_FOR_AREA.get(category)
        if kind in {"school", "medical"} and tiles < OUTBUILDING:
            return "civic"
        return kind

    def mask(self, categories: set[str], width: int, height: int):
        """These areas as a bitmap of the map, for asking about ground rather
        than about one point. Nothing drawn is an empty mask, not no mask."""
        import numpy as np
        from PIL import Image, ImageDraw

        sheet = Image.new("1", (width, height), 0)
        pen = ImageDraw.Draw(sheet)
        for shape, props in self._items:
            if props.get("category") not in categories:
                continue
            # An outline mended with buffer(0) can be several polygons.
            for part in parts(shape):
                ring = [(float(x), float(y)) for x, y in part.exterior.coords]
                if len(ring) >= 3:
                    pen.polygon(ring, fill=1)
        return np.asarray(sheet, dtype=bool)

    def category_at(self, x: float, y: float) -> str | None:
        props = self.around(x, y)
        return props.get("category") if props else None
