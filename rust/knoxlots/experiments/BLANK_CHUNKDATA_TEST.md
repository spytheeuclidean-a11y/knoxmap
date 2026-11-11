# Blank chunkdata test

Question: does Project Zomboid (Build 42) need the real `chunkdata_*.bin` files
that WorldEd writes, or does it work with blank ones? If blank files work, a
compiler of our own does not have to reproduce that file.

## What was made

A copy of your installed Worthville map (25 cells), changed in two ways:

- `C:\Users\TheTaZe\Zomboid\mods\worthville_blankchunks` is a separate mod
  (id `worthville_blankchunks`, name "Worthville (blank chunkdata test)").
  Your original `worthville` mod is untouched.
- Every `chunkdata_*.bin` in it is a blank file: the bytes `00 01` and 1024 zeros
  (1026 bytes). 17 of the 25 originals held real data (extra 64-byte blocks).
- The KnoxMap Lua extras (Spawn Selector, gun cache) were left out of the copy so
  only the map data is being tested.

## Test

1. In the game's Mods screen, **turn off the normal Worthville** and turn on
   "Worthville (blank chunkdata test)" (and Erika's Tiles, which it requires, same
   as the original).
2. Start a **new** game on the Worthville map, in the town.
3. Walk around the buildings. Check, and compare with the normal Worthville if
   you can:
   - Do the buildings, walls, doors and roofs look the same?
   - Can you enter buildings; are rooms furnished and is there loot?
   - Do zombies spawn, inside and outside?
   - Can you walk and drive everywhere you can in the normal copy?
   - Any lag spikes, black squares, or chunks that do not load?
4. Quit, then open `C:\Users\TheTaZe\Zomboid\console.txt` and search for
   `chunkdata`, `lotheader`, `lotpack`, `Exception`. Send me anything it says
   about those, or the whole file.

## Reading the result

- **Everything looks and plays the same:** the game does not need the real
  chunkdata for this; our compiler can write blank files.
- **Something is wrong** (no zombies, buildings missing, errors): tell me what.
  It says what the file is for, and the experiments continue from there.

## Undo

Delete the folder `C:\Users\TheTaZe\Zomboid\mods\worthville_blankchunks`.
Nothing else was changed.
