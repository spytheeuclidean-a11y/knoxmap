"""A picture of a finished map, ready to show somebody.

tools/render_lots.py draws a compiled map the way the game draws it, but it
draws exactly the tiles you ask for at exactly the scale you ask for, and
getting something worth looking at out of it means knowing the map's size,
picking a window on it, choosing a scale that is neither a postage stamp nor
a 300-megapixel canvas, and then trimming the empty diagonal corners off the
result. That is what this does.

    from knoxbuild.picture import picture
    picture("output/mytown", "mytown.png")                  # the whole town
    picture("output/mytown", "inside.png", roofs=False)     # every room shown

An isometric view is a diamond, so the corners of the image are always empty;
they are cropped away, and what is left is centred on the project's own
background at the size asked for.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# The background the rest of the project's art sits on.
BACKGROUND = (20, 24, 15)
SIZE = (1920, 1080)
# Drawing is done larger than the picture and shrunk down, which is what makes
# the tiles read cleanly; beyond about twice there is nothing left to gain.
OVERSAMPLE = 2.0
# A whole town at 1x is a canvas of a hundred million pixels and several
# gigabytes. Past this the scale comes down instead.
MAX_PIXELS = 60_000_000
# render_lots clamps a tile to 4 pixels wide, so there is no point asking for
# less, and 1.0 is the game at its own size.
MIN_SCALE, MAX_SCALE = 4 / 64, 1.0


def map_size(map_dir: str | Path) -> tuple[int, int]:
    """How many tiles across and down the map is."""
    map_dir = Path(map_dir)
    name = map_dir.name
    info = json.loads((map_dir / f"{name}_info.json").read_text(encoding="utf-8"))
    return int(info["width_tiles"]), int(info["height_tiles"])


def compiled(map_dir: str | Path) -> bool:
    """Whether there is anything to draw yet."""
    return any(Path(map_dir, "lots").glob("*.lotheader"))


def _pixels(w: int, h: int, scale: float) -> int:
    """How big a canvas render_lots would build for this."""
    tile = max(4, round(64 * scale))
    return ((w + h) * tile // 2 + tile) * ((w + h) * tile // 4 + 8 * tile)


def _within_budget(x: int, y: int, w: int, h: int,
                   scale: float) -> tuple[int, int, int, int]:
    """A window that can actually be drawn, keeping the middle of this one.

    The tiles cannot be made smaller than four pixels, so past a certain size
    there is no scale that helps and the only thing left is to draw less. A
    map of a whole county would otherwise ask for a canvas of several
    gigabytes and take the window down with it.
    """
    while _pixels(w, h, scale) > MAX_PIXELS and (w > 64 or h > 64):
        x, y = x + w // 8, y + h // 8
        w, h = max(64, w - w // 4), max(64, h - h // 4)
    return x, y, w, h


def _scale_for(w: int, h: int, size: tuple[int, int]) -> float:
    """A scale that fills the picture without building a canvas nothing can
    hold. The drawn width is about (w + h) * 32 * scale."""
    want = max(1.0, size[0] * OVERSAMPLE)
    scale = want / max(1, (w + h) * 32)
    scale = min(MAX_SCALE, max(MIN_SCALE, scale))
    # ...and if that is still too much canvas, come down until it is not.
    while scale > MIN_SCALE and _pixels(w, h, scale) > MAX_PIXELS:
        scale /= 1.3
    return round(max(MIN_SCALE, scale), 4)


def _trim(picture: Image.Image) -> Image.Image:
    """The diagonal border of nothing an isometric view always has."""
    if picture.mode != "RGBA":
        return picture
    box = picture.getbbox()
    return picture.crop(box) if box else picture


def _on_background(picture: Image.Image, size: tuple[int, int]) -> Image.Image:
    """The whole picture, centred, never blown up past its own size."""
    flat = Image.new("RGB", picture.size, BACKGROUND)
    flat.paste(picture, mask=picture.split()[3] if picture.mode == "RGBA" else None)
    scale = min(size[0] / flat.width, size[1] / flat.height, 1.0)
    if scale < 1.0:
        flat = flat.resize((max(1, round(flat.width * scale)),
                           max(1, round(flat.height * scale))), Image.Resampling.LANCZOS)
    out = Image.new("RGB", size, BACKGROUND)
    out.paste(flat, ((size[0] - flat.width) // 2, (size[1] - flat.height) // 2))
    return out


def picture(map_dir: str | Path, out_png: str | Path | None = None,
            box: tuple[int, int, int, int] | None = None,
            roofs: bool = True, size: tuple[int, int] = SIZE,
            scale: float | None = None) -> Image.Image:
    """A picture of the map, or of `box` (x, y, width, height) of it.

    `roofs=False` takes the top off, which is how every room and everything
    in it becomes visible - the view worth sending somebody. `scale` is
    chosen to suit the area unless you name one.

    Raises FileNotFoundError when the map has not been compiled: there is
    nothing to draw until then, and the terrain on its own is the preview
    picture the generator already writes.
    """
    from tools import render_lots

    map_dir = Path(map_dir)
    if not compiled(map_dir):
        raise FileNotFoundError(
            f"{map_dir.name} has not been compiled yet - there is nothing to draw. "
            "Run Compile first.")
    if box is None:
        box = (0, 0, *map_size(map_dir))
    x, y, w, h = (int(v) for v in box)
    w, h = max(1, w), max(1, h)
    if scale is None:
        scale = _scale_for(w, h, size)
    x, y, w, h = _within_budget(x, y, w, h, scale)

    drawn = render_lots.render(str(map_dir), x, y, w, h,
                               max_level=None if roofs else 0, scale=scale)
    if drawn is None:
        raise FileNotFoundError(
            f"nothing of {map_dir.name} is compiled at {x},{y} {w}x{h}.")
    out = _on_background(_trim(drawn), size)
    if out_png:
        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        out.save(out_png)
    return out


def pictures_of(map_dir: str | Path, into: str | Path | None = None,
                size: tuple[int, int] = SIZE) -> list[Path]:
    """The set worth having of a finished map, written into the map's folder.

    The whole town, then the middle of it close enough to see, then the same
    middle with the roofs off. A town has a middle worth looking at far more
    often than it has an interesting corner, and anyone who wants a different
    part can name a box.
    """
    map_dir = Path(map_dir)
    into = Path(into) if into else map_dir / "pictures"
    into.mkdir(parents=True, exist_ok=True)
    w, h = map_size(map_dir)
    close = min(320, max(120, min(w, h) // 3))
    middle = (max(0, w // 2 - close // 2), max(0, h // 2 - close // 2), close, close)
    wanted = [("town.png", (0, 0, w, h), True),
              ("close.png", middle, True),
              ("inside.png", middle, False)]
    made = []
    for filename, box, roofs in wanted:
        try:
            picture(map_dir, into / filename, box=box, roofs=roofs, size=size)
        except FileNotFoundError:
            continue
        made.append(into / filename)
    return made
