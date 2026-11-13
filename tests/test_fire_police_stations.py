"""Fire stations, police stations, and combined stations."""
import random
import unittest

from knoxbuild import build as B
from knoxbuild import layout as L
from knoxbuild.settings import Settings


class FirePoliceStations(unittest.TestCase):
    def test_classify_combined_and_named_stations(self):
        self.assertEqual(
            B.classify_building({
                "amenity": "fire_station",
                "building": "yes",
                "name": "Stanford Fire Department/Police Station",
            }),
            "fire_police",
        )
        self.assertEqual(
            B.classify_building({"amenity": "fire_station;police"}),
            "fire_police",
        )
        self.assertEqual(
            B.classify_building({"building": "house", "name": "Stanford Fire Department"}),
            "fire",
        )
        self.assertEqual(
            B.classify_building({"amenity": "police", "name": "Lincoln County Sheriff's Office"}),
            "police",
        )

    def test_stations_use_distinct_institutional_styles(self):
        settings = Settings()
        for kind in ("fire", "police", "fire_police"):
            for i in range(6):
                style = B.pick_style(kind, 100 + i * 37, 200 + i * 53, random.Random(i), settings)
                ext = style["exterior"]["tiles"].get("West", "")
                interior = style["interior"]["tiles"].get("West", "")
                self.assertFalse(
                    interior.startswith("walls_interior_house_"),
                    f"{kind} picked house interior {interior}",
                )
                self.assertFalse(
                    ext.startswith("industry_01_"),
                    f"{kind} picked industrial tin {ext}",
                )

    def test_garage_door_never_widens_hall_or_lobby_in_multi_room_station(self):
        for kind in ("fire", "fire_police"):
            for seed in range(5):
                b = L.build_building(33, 22, levels=2, kind=kind, commercial=True,
                                     street="W", garage_door=True, seed=seed)
                ground = b.storeys[0]
                for x, y, d in getattr(ground, "garage_door_tiles", ()):
                    rid = L._room_at(ground, x, y)
                    if not rid:
                        rid = L._room_at(ground, x, y - 1) if d == "N" else L._room_at(ground, x - 1, y)
                    room_kind = ground.rooms[rid - 1].kind
                    self.assertIn(room_kind, L.openings.VEHICLE_BAY_ROOMS)
                if kind == "fire_police":
                    kinds = {r.kind for s in b.storeys for r in s.rooms}
                    self.assertIn("firegarage", kinds)
                    self.assertIn("policeoffice", kinds)


if __name__ == "__main__":
    unittest.main()
