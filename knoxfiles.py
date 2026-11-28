"""The map's own files, written whole and read with a straight answer.

A map folder holds the ground as bitmaps and a dozen small JSON files beside
them - its buildings, its land use, its fences, what it is and how big. Each
was written straight to its own name, so a generate that was stopped, crashed
or had the window closed on it left one of them half written, and the next
Build died on the half:

    Expecting ',' delimiter: line 1 column 32790 (char 32789)

Nobody can act on that. Each file is now written beside itself and moved into
place, which is one step on every system this runs on: what is on disk is
either the file from before or the new one, never half of either. And reading
one says which file it is, what it holds and what to do about it.
"""
from __future__ import annotations

import json
import os
import time


class Damaged(ValueError):
    """A map file that is there but cannot be read."""


def _forget(part: str) -> None:
    """Take away what was half written, so the folder is left as it was."""
    try:
        os.remove(part)
    except OSError:
        pass


# On Windows a file another program has open for a moment - antivirus or the
# search indexer scanning it, or the window reading it - cannot be replaced, and
# the move fails with "Access is denied" (WinError 5). It is free again in a
# fraction of a second, so the move is tried again for a little while first.
REPLACE_TRIES = 20
REPLACE_WAIT_S = 0.1


def _move(part: str, path: str) -> None:
    """os.replace, waiting out a program that holds `path` open briefly."""
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(part, path)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(REPLACE_WAIT_S)


def write(path: str, payload, **dump) -> None:
    """Write `payload` to `path` as JSON: all of it, or none of it."""
    part = f"{path}.part"
    try:
        with open(part, "w", encoding="utf-8") as f:
            json.dump(payload, f, **dump)
        _move(part, path)
    except BaseException:
        _forget(part)
        raise


def save(image, path: str, **options) -> None:
    """The same for a bitmap: a map's ground is the biggest file it writes."""
    part = f"{path}.part"
    try:
        image.save(part, **options)
        _move(part, path)
    except BaseException:
        _forget(part)
        raise


def write_text(path: str, text: str) -> None:
    """The same for a file of text the map carries.

    Where a map stands in the world is written into the project, the paper
    map, the street lines and the labels, all four rewritten in place when a
    map is moved. Half of any one of them is a map the game will not open.
    """
    part = f"{path}.part"
    try:
        with open(part, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        _move(part, path)
    except BaseException:
        _forget(part)
        raise


def read(path: str, what: str, default=None):
    """What is in this file. `default` when there is no such file at all.

    A file that is there and will not read is not a file that is missing -
    something went wrong while it was written - so this says so instead of
    quietly building a town with no fences in it.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        raise Damaged(
            f"{os.path.basename(path)} ({what}) cannot be read: {exc}. "
            f"That happens when making the map was interrupted and the file "
            f"was left half written. Generate the map again to write it "
            f"afresh - the OpenStreetMap download beside it is kept, so it "
            f"starts from what is already on disk."
        ) from exc
