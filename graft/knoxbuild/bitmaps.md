# knoxbuild/bitmaps.py

- _bmp_header · function · L25-L39 — def _bmp_header(path: str)
- _fast · function · L42-L92 — def _fast(path: str, bits_wanted: int, crop, step: int = 1)
- read_rgb · function · L95-L105 — def read_rgb(path: str, crop: tuple[int, int] | None = None, step: int = 1) -> np.ndarray
- read_gray · function · L108-L121 — def read_gray(path: str, crop: tuple[int, int] | None = None) -> np.ndarray
- same_colour · function · L124-L131 — def same_colour(rgb: np.ndarray, colour) -> np.ndarray
- cell_hashes · function · L134-L171 — def cell_hashes(path: str, cell: int) -> dict[tuple[int, int], str]
- read_rgb_rows · function · L174-L198 — def read_rgb_rows(path: str, top: int, bottom: int, width: int | None = None) -> np.ndarray
