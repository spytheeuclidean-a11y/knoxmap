# In-Game Test Map (`ingame_test_map`)

A small, repeatable 1-cell (`300 × 300` tiles) map that puts KnoxMap's open in-game verification questions near one spawn point.

## Generate

```powershell
.\.venv\Scripts\python.exe tools\make_ingame_test_map.py --compile
```

Omit `--compile` if you want to open and inspect the `.pzw` in WorldEd first. The script also writes `ROUTE.txt` into the output folder (`output/ingame_test_map` by default).

## Verification Route

| Stop | Location near spawn | Expected result |
|---|---|---|
| **1. Kerb orientation** | Walk east from spawn to the first 90° corner and diagonal turn on *Kerb Lane* | Raised kerb tiles face outward from the pavement onto the road on both the 90° corner and the angled turn, with no inverted edges. |
| **2. Drivable overpass** | Drive east along *Test Avenue* onto *Test Overpass* over *Cross Road* | A car drives smoothly up the first ramp, across the elevated deck, and down the far ramp without hitting an invisible wall or falling through. |
| **3. Multi-storey lift** | Enter the 5-storey *Lift Tower* just north-west of the crossroads | With the *Elevators* mod enabled, the lift doors open and carry the player between floors 0–4; without it, shaft doors stay closed. |
| **4. Non-Latin map labels** | Press `M` anywhere in the cell | All three neighbourhood labels render legibly on the in-game map: `テスト駅` (Japanese), `الاختبار` (Arabic), `Тест` (Cyrillic). |

When reporting an issue, include the stop number, what actually happened (for example, *"the car stops at the second ramp"*), a screenshot, and your Project Zomboid build number.
