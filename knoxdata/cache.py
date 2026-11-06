"""Two cache tiers, mirroring the OSM cache's lifetime rule.

Dataset-wide files (a national hospitals list, a world tile) are shared by
every map and expire on a TTL. Per-map products live beside the map and are
reused on rebuild. Cache keys carry the dataset version so an update does not
read yesterday's answer.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Big shared downloads; never inside a map folder, never copied into a mod.
DATASET_DIR = Path(os.environ.get("KNOXMAP_DATASET_CACHE") or (BASE_DIR / "cache" / "datasets"))

# Politeness and safety: the same three tries the Overpass client makes, and a
# ceiling so a wrong URL can never fill the disk.
MAX_BYTES = int(os.environ.get("KNOXMAP_DOWNLOAD_MAX_BYTES") or 2 * 1024 ** 3)
ATTEMPTS = 3
# A ceiling on the whole dataset cache, not just on one file. The per-download
# cap stops one wrong URL filling the disk; nothing stopped ten right ones -
# a few national extracts, a world raster or two, and the cache was however big
# the last month of maps made it. The oldest files go first.
MAX_CACHE_BYTES = int(os.environ.get("KNOXMAP_CACHE_MAX_BYTES") or 8 * 1024 ** 3)


def dataset_dir(*parts: str) -> Path:
    d = DATASET_DIR.joinpath(*parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def map_dir(map_folder) -> Path:
    """Per-map processed cache beside the map's other data."""
    d = Path(map_folder) / ".knoxdata"
    d.mkdir(parents=True, exist_ok=True)
    return d


def total_bytes(folder=None) -> int:
    """How much the dataset cache (or `folder`) holds."""
    folder = Path(folder or DATASET_DIR)
    total = 0
    if not folder.is_dir():
        return 0
    for p in folder.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def prune(keep_bytes: int | None = None, folder=None, keep=None) -> int:
    """Delete the oldest cached files until the cache is under its ceiling.

    `keep` - the file just downloaded - is never one of them, so a download
    that takes the cache over the limit cannot delete what it just fetched.
    Returns how many files went. Best effort: a file somebody else has open is
    left alone and counted as still there.
    """
    folder = Path(folder or DATASET_DIR)
    limit = MAX_CACHE_BYTES if keep_bytes is None else keep_bytes
    if not folder.is_dir():
        return 0
    held = Path(keep) if keep else None
    files = []
    total = 0
    for p in folder.rglob("*"):
        try:
            if not p.is_file():
                continue
            size = p.stat().st_size
            total += size
            if p != held:
                files.append((p.stat().st_mtime, size, p))
        except OSError:
            continue
    if total <= limit:
        return 0
    files.sort()
    removed = 0
    for _when, size, p in files:
        if total <= limit:
            break
        try:
            p.unlink()
        except OSError:
            continue
        total -= size
        removed += 1
    return removed


def age_days(path) -> float:
    try:
        return (time.time() - Path(path).stat().st_mtime) / 86400.0
    except OSError:
        return float("inf")


def fresh(path, ttl_days: float) -> bool:
    """True when `path` exists and is younger than `ttl_days`."""
    return Path(path).exists() and age_days(path) < ttl_days


def stamp() -> str:
    return time.strftime("%Y-%m-%d")


def write_json(path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def download(url: str, path, progress_cb=None, chunk: int = 1 << 20,
             timeout: int = 120, attempts: int = ATTEMPTS,
             max_bytes: int = MAX_BYTES) -> Path:
    """Stream `url` to `path` atomically, retrying with backoff.

    Raises on the last failure; the caller logs and skips. Retries match the
    Overpass client's politeness (three), and a size cap means a wrong URL
    cannot fill the disk.
    """
    import urllib.request

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "KnoxMap/knoxdata"})
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            done = 0
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                if total and total > max_bytes:
                    raise ValueError(f"{url} is {total} bytes, over the "
                                     f"{max_bytes}-byte cap")
                with open(part, "wb") as out:
                    while True:
                        block = resp.read(chunk)
                        if not block:
                            break
                        done += len(block)
                        if done > max_bytes:
                            raise ValueError(f"download of {url} passed the "
                                             f"{max_bytes}-byte cap")
                        out.write(block)
                        if progress_cb is not None:
                            progress_cb(done, total)
            os.replace(part, path)
            # The cache has a ceiling of its own (MAX_CACHE_BYTES): this
            # download may be the one that took it over, and the file it just
            # wrote is the one that must survive.
            gone = prune(keep=path)
            if gone:
                import knoxlog

                knoxlog.log.info("cache: removed %d older downloads; the cache is "
                                 "capped at %d bytes", gone, MAX_CACHE_BYTES)
            return path
        except Exception as exc:            # noqa: BLE001 - retried, then caller skips
            last = exc
            try:
                if part.exists():
                    part.unlink()
            except OSError:
                pass
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 30))
    raise last if last is not None else RuntimeError(f"could not download {url}")
