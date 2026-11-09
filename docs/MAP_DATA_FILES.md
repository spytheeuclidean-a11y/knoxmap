# Choosing and checking the map data file

KnoxMap reads OpenStreetMap data out of a regional `.osm.pbf` extract
(Geofabrik's country and state files, or one you cut yourself). Two things are
worth knowing: which file gets read, and whether it will do.

## Which file

By default KnoxMap asks Geofabrik's index which extract covers the area you
drew, downloads it once into `cache/extracts`, and reads that. It is a guess
about what you meant - sometimes a map near a state line wants the neighbouring
file, and sometimes you have already cut a county-sized file for the job.

Name a file and that guess goes away:

- **In the app**: `Tools` → *Extract file* → **Browse…**, then **Use this file**.
  **Choose by area** puts it back to guessing.
- **From a console**: `python tools/verify_pbf.py my-county.osm.pbf --use`
  (and `--forget` to stop).
- **In `knoxmap_config.json`**: `"pbf_file": "C:/maps/my-county.osm.pbf"`, or
  the environment variable `KNOXMAP_PBF_FILE` for one run.

With a file named, every map reads it - both the *Auto* and *Geofabrik* data
sources. If the file has moved, is empty or cannot be parsed, the map **stops**
and says so. It does not fall back to the public Overpass servers: a file you
picked is the answer, not a suggestion, and a map silently built from a
different area is worse than a map that did not build.

## Checking a file first

`Tools` → *Check it*, or on the command line:

```
python tools/verify_pbf.py my-county.osm.pbf
python tools/verify_pbf.py my-county.osm.pbf --bbox 37.33,-84.37,37.41,-84.32
python tools/verify_pbf.py my-county.osm.pbf --json
```

The report says whether the file is whole, what it covers, and what is in it. It
fails (exit code 1) on:

- a file that is not there, is empty, or is not an `.osm.pbf` at all
- a file that breaks off part way - what a download stopped with
- a file with no roads (`highway`) or no buildings (`building`), which would
  give a map of empty fields
- a file that does not overlap the area being drawn, when `--bbox` is given

and warns about the rest: an area that runs past the file's edge, a file
Geofabrik rebuilt long ago, a sample count on a very large file, and tags that
are absent so that part of the map will be plain.

The same check runs in the app (`POST /api/tools/pbf/check`), so the panel and
the console cannot drift apart: both are `generator/pbfcheck.py`.
