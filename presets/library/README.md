# Hand-built buildings that ship with KnoxMap

Buildings people built themselves and sent in. Every KnoxMap release carries
this folder, so what is here can be used on any map: switch a kind of building
on under **Hand-built buildings** and the ones built for that kind are stamped
onto the map instead of generated ones.

## Sending one in

Build it in KnoxMap (**Hand-built buildings → Build a building by hand**, or
drop a `.tbx` from BuildingEd into `presets/buildings/`), then press **Share**.
That writes one file, `<name>.knoxbuilding.json`, holding the building, the
drawing it was made from and what it stands in for. Send that file — the
KnoxMap Discord is the place: <https://discord.gg/ePM8dSxPm7>.

Anyone can take one in the same way: **Take one in**, pick the file, and it is
theirs to use and to change.

## Adding one here

```bash
python tools/add_shared_building.py submitted.knoxbuilding.json
```

It checks the file, copies the building in and records what it is in
`library.json`. `--check` looks without adding, `--list` shows what is here and
`--remove "A Name"` takes one out. Then commit the `.tbx`, the drawing beside
it and `library.json`.

Look at a building before adding it: a `.tbx` names tiles, and one naming tiles
Build 42 does not have is not dangerous but is full of holes. Open the file in
KnoxMap and build a small map with it.

## What is in a name

The file name is the building's name, so it is what people see in the list.
`library.json` records, for each: what kind of building it stands in for, who
built it, their note about it, and the date it was added. Credit stays with the
building — it is shown in the window beside it.
