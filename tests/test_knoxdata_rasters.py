"""Real processing tests for the raster/parquet layers, using tiny fixtures.

Skipped when rasterio/pyarrow are not installed, so the suite runs on a bare
machine. These exercise build_layer end to end; only fetch is mocked.
"""
import tempfile
import unittest
from pathlib import Path

import numpy as np

import knoxdata
from knoxbuild.settings import Settings

try:
    import rasterio  # noqa: F401
    HAS_RASTERIO = True
except Exception:       # noqa: BLE001
    HAS_RASTERIO = False

try:
    import pyarrow  # noqa: F401
    HAS_PYARROW = True
except Exception:       # noqa: BLE001
    HAS_PYARROW = False


@unittest.skipUnless(HAS_RASTERIO, "rasterio not installed")
class WorldCoverProcessing(unittest.TestCase):
    def test_class_fractions(self):
        import rasterio
        from rasterio.transform import from_bounds
        from knoxdata import worldcover

        s, w, n, e = 32.0, -87.0, 32.5, -86.5
        tmp = Path(tempfile.mkdtemp())
        name = worldcover.tile_names((s, w, n, e))[0]
        data = np.full((10, 10), 10, dtype="uint8")
        data[:5, :] = 30          # grassland
        data[:2, :] = 50          # built-up
        with rasterio.open(tmp / name, "w", driver="GTiff", height=10, width=10,
                           count=1, dtype="uint8", crs="EPSG:4326",
                           transform=from_bounds(w, s, e, n, 10, 10)) as dst:
            dst.write(data, 1)

        src = worldcover.WorldCover()
        src.fetch = lambda bbox, cache_dir=None, progress_cb=None: tmp
        ctx = knoxdata.MapContext(bbox=(s, w, n, e), settings=Settings(), map_dir=".")
        fractions = src.build_layer(ctx).data["fractions"]
        self.assertAlmostEqual(fractions["Built-up"], 0.20, places=3)
        self.assertAlmostEqual(fractions["Grassland"], 0.30, places=3)
        self.assertAlmostEqual(fractions["Tree cover"], 0.50, places=3)

    def test_rasterise_returns_one_class_per_tile(self):
        import rasterio
        from rasterio.transform import from_bounds
        from knoxdata import worldcover

        s, w, n, e = 32.0, -87.0, 32.5, -86.5
        tmp = Path(tempfile.mkdtemp())
        name = worldcover.tile_names((s, w, n, e))[0]
        data = np.full((10, 10), 10, dtype="uint8")
        data[:, :5] = 30
        with rasterio.open(tmp / name, "w", driver="GTiff", height=10, width=10,
                           count=1, dtype="uint8", crs="EPSG:4326",
                           transform=from_bounds(w, s, e, n, 10, 10)) as dst:
            dst.write(data, 1)
        src = worldcover.WorldCover()
        src.tile_dir = lambda: tmp
        src.fetch = lambda *a, **k: self.fail("rasterise must not download")
        grid = src.rasterise((s, w, n, e), 10, 10)
        self.assertEqual(grid.shape, (10, 10))
        self.assertTrue(set(np.unique(grid).tolist()) <= {10, 30})

    def _tile(self, data, s=32.0, w=-87.0, n=32.5, e=-86.5):
        import rasterio
        from rasterio.transform import from_bounds
        from knoxdata import worldcover

        tmp = Path(tempfile.mkdtemp())
        name = worldcover.tile_names((s, w, n, e))[0]
        h, wd = data.shape
        with rasterio.open(tmp / name, "w", driver="GTiff", height=h, width=wd,
                           count=1, dtype="uint8", crs="EPSG:4326",
                           transform=from_bounds(w, s, e, n, wd, h)) as dst:
            dst.write(data, 1)
        src = worldcover.WorldCover()
        src.tile_dir = lambda: tmp
        return src

    def test_speckle_is_filtered_at_10_m_not_at_map_tiles(self):
        # A lone 10 m pixel of cropland in a wood: noise, gone however finely
        # the map samples it. Filtered after the stretch, it survived.
        data = np.full((20, 20), 10, dtype="uint8")
        data[10, 10] = 40
        src = self._tile(data)
        grid = src.rasterise((32.0, -87.0, 32.5, -86.5), 200, 200)
        self.assertEqual(set(np.unique(grid).tolist()), {10})

    def test_area_past_the_tile_is_left_empty_not_stretched(self):
        # The east half of the box has no tile on disk: it stays 0 (no data),
        # and the west half keeps the tile's own split at its own place.
        data = np.full((20, 20), 10, dtype="uint8")
        data[:, :10] = 30
        src = self._tile(data, s=32.0, w=-87.0, n=32.5, e=-86.5)
        grid = src.rasterise((32.0, -86.75, 32.5, -86.25), 100, 50)
        self.assertTrue((grid[:, :45] == 10).all())
        self.assertTrue((grid[:, 55:] == 0).all())


@unittest.skipUnless(HAS_RASTERIO, "rasterio not installed")
class GroundPaint(unittest.TestCase):
    def test_classes_become_ground_colours(self):
        import numpy as np
        from PIL import Image

        from generator import pz_colors as C
        from generator import renderer

        image = Image.new("RGB", (4, 4), (1, 2, 3))
        grid = np.array([[10, 10, 80, 80]] * 4, dtype="uint8")
        renderer._paint_landcover(image, grid)
        self.assertEqual(image.getpixel((0, 0)), C.DARK_GRASS)   # tree cover
        self.assertEqual(image.getpixel((3, 0)), C.WATER)        # permanent water


class ClimateTint(unittest.TestCase):
    def test_arid_dries_the_ground(self):
        from PIL import Image

        from generator import renderer

        image = Image.new("RGB", (2, 2), (100, 100, 100))
        renderer._paint_climate(image, {"class": "arid"}, "auto")
        red, _green, blue = image.getpixel((0, 0))
        self.assertGreater(red, blue)

    def test_temperate_is_left_alone(self):
        from PIL import Image

        from generator import renderer

        image = Image.new("RGB", (2, 2), (100, 100, 100))
        renderer._paint_climate(image, {"class": "temperate"}, "auto")
        self.assertEqual(image.getpixel((0, 0)), (100, 100, 100))

    def test_winter_on_lightens(self):
        from PIL import Image

        from generator import renderer

        image = Image.new("RGB", (2, 2), (100, 100, 100))
        renderer._paint_climate(image, {"class": "temperate"}, "on")
        self.assertGreater(image.getpixel((0, 0))[0], 100)


class ReliefPaint(unittest.TestCase):
    def test_relief_shades_the_ground(self):
        import numpy as np
        from PIL import Image

        from generator import renderer

        metres = np.tile(np.linspace(0, 1000, 8), (8, 1)).astype("float32")
        image = Image.new("RGB", (8, 8), (100, 140, 80))
        renderer._paint_relief(image, metres, (0.0, 1000.0))
        self.assertNotEqual(image.getpixel((0, 0)), (100, 140, 80))

    def test_flat_ground_is_left_alone(self):
        import numpy as np
        from PIL import Image

        from generator import renderer

        flat = np.full((8, 8), 100.0, dtype="float32")
        image = Image.new("RGB", (8, 8), (100, 140, 80))
        renderer._paint_relief(image, flat, (100.0, 110.0))
        self.assertEqual(image.getpixel((0, 0)), (100, 140, 80))


@unittest.skipUnless(HAS_RASTERIO, "rasterio not installed")
class ElevationProcessing(unittest.TestCase):
    def test_normalised_and_clamped(self):
        import rasterio
        from rasterio.transform import from_bounds
        from knoxdata import elevation_3dep

        s, w, n, e = 40.0, -75.0, 40.01, -74.99
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "dem.tif"
        data = np.tile(np.linspace(100, 200, 10, dtype="float32"), (10, 1))
        with rasterio.open(path, "w", driver="GTiff", height=10, width=10,
                           count=1, dtype="float32", crs="EPSG:4326",
                           transform=from_bounds(w, s, e, n, 10, 10)) as dst:
            dst.write(data, 1)

        src = elevation_3dep.Elevation3DEP()
        src.fetch = lambda bbox, cache_dir=None, progress_cb=None: path
        ctx = knoxdata.MapContext(bbox=(s, w, n, e),
                                  settings=Settings(max_relief=4), map_dir=".")
        layer = src.build_layer(ctx)
        metres = layer.data["metres"]
        self.assertAlmostEqual(float(metres.min()), 0.0, places=3)
        self.assertAlmostEqual(float(metres.max()), 4.0, places=3)
        self.assertEqual(tuple(round(v, 1) for v in layer.data["span"]), (100.0, 200.0))


@unittest.skipUnless(HAS_PYARROW, "pyarrow not installed")
class ClimateProcessing(unittest.TestCase):
    def test_nearest_station_profile(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        from knoxdata import climate_normals

        tmp = Path(tempfile.mkdtemp())
        path = tmp / "normals.parquet"
        table = pa.table({
            "LATITUDE": [40.0, 45.0],
            "LONGITUDE": [-75.0, -80.0],
            "JAN_MEAN_TMP": [0.0, -10.0],
            "JUL_MEAN_TMP": [25.0, 20.0],
            "MLY-PRCP-NORMAL": [1200.0, 600.0],
        })
        pq.write_table(table, path)

        src = climate_normals.ClimateNormals()
        src.fetch = lambda bbox, cache_dir=None, progress_cb=None: path
        ctx = knoxdata.MapContext(bbox=(40.0, -75.0, 40.1, -74.9),
                                  settings=Settings(), map_dir=".")
        profile = src.build_layer(ctx).data["profile"]
        self.assertEqual(profile["class"], "humid")
        self.assertAlmostEqual(profile["jan_c"], 0.0, delta=0.5)
        self.assertAlmostEqual(profile["jul_c"], 25.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
