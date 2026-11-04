"""HIFLD hospital identity: how a real facility shapes its game building.

The knoxdata layer writes a facility's fields onto the OSM building's tags
(hifld_beds, hifld_type, hifld_status, helipad). This turns them into the
numbers the builder uses: a size class, a medical occupancy scale and loot
scale, and whether the place is closed. The room-mix table is data
(knoxdata/data/hospital_types.json), the same one DATASETS.md documents.
"""
from __future__ import annotations

import json
from pathlib import Path

_DATA = (Path(__file__).resolve().parent.parent
         / "knoxdata" / "data" / "hospital_types.json")

# A 200-bed hospital holds several times the people a generic medical
# building does; clamp so a bad field cannot empty the map.
MAX_OCCUPANCY = 4.0
CLOSED_OCCUPANCY = 0.25


def _types() -> dict:
    try:
        with open(_DATA, encoding="utf-8") as fh:
            table = json.load(fh)
    except (OSError, ValueError):
        return {}
    return table if isinstance(table, dict) else {}


def _int(value) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def is_hospital(tags) -> bool:
    tags = tags or {}
    return (str(tags.get("healthcare") or "").lower() == "hospital"
            or str(tags.get("amenity") or "").lower() == "hospital")


def profile(tags) -> dict | None:
    """Per-building numbers from HIFLD tags, or None when it is not one."""
    tags = tags or {}
    if not is_hospital(tags):
        return None
    beds = _int(tags.get("hifld_beds"))
    staff = _int(tags.get("hifld_staff"))
    kind = str(tags.get("hifld_type") or "").strip().upper()
    status = str(tags.get("hifld_status") or "").strip().upper()
    table = _types()
    return {
        "beds": beds,
        "staff": staff,
        "type": kind,
        "mix": table.get(kind) or table.get("") or "generalacute",
        "status": status,
        "closed": status == "CLOSED",
        "helipad": str(tags.get("helipad") or "").lower() == "yes",
        "occupancy": round(min(MAX_OCCUPANCY, max(0.5, (beds + staff) / 400.0)), 3),
        "loot": round(min(3.0, max(0.5, 0.5 + beds / 400.0)), 3),
    }


def occupancy_kind(kind: str, prof: dict | None) -> str:
    """Encode the medical occupancy scale in the kind the spawn map reads.

    ``medical:2.5`` / ``medical:closed`` are understood by
    knoxbuild/population.occupants; every other kind is left alone.
    """
    if not prof or kind != "medical":
        return kind
    if prof.get("closed"):
        return "medical:closed"
    return f"medical:{prof.get('occupancy', 1.0)}"
