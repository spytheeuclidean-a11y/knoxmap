---
name: ui-placement
description: Use when adding, moving or reorganising any control, panel, notice or button in the KnoxMap web UI - decides whether it belongs in the left Tools sidebar, the right Properties sidebar, a floating widget on the map, or a menu/dialog.
---

# Where a control belongs

KnoxMap's workspace (`static/js/shell.js`) has four homes for UI. Decide which one
before writing any markup.

| Home | What goes there | Built in |
|---|---|---|
| **Left: Tools sidebar** (`#wsTools`) | Changes to **specific places on this map**: the extent, drawn features, zones, changes to what is already there, hand-built buildings, drawing a map from scratch | `TOOLS` and `TOOL_PANE` in `shell.js`; the panels in `templates/index.html` (`#sketch`, `#zonesPanel`, `#editMap`, `#coordsBox`) |
| **Right: Properties sidebar** (`#wsProps`) | **Generation properties**: settings that apply to the whole map when it is generated (unless a zone overrides them), the map's name, scale, kind of place, and what the extent comes to | `SETTING_GROUPS` / `SETTING_LABELS` in `static/js/settings.js`; page fields in `#settingsParts` (`.tab-part`) |
| **Map canvas widgets** (`.ws-legend`) | **Viewing aids** that do not change the map: Layers, Named places | `shell.js` (`#wsLayers`, `#wsPlaces`) |
| **Menus and dialogs** | **App setup and preferences**: Steam libraries, where maps are installed, setup checks, Home's start buttons | `shell.js` menus and `dialog()`; the setup bar at the top |

## The test

Ask: **does this act on a spot on the map, or on how everything is generated?**

- Acts on a spot (you point at the map, draw, pick or edit something there) -> **left**.
- Changes how the generator treats the whole map -> **right**, in the tab of
  `SETTING_GROUPS` it is about (Map, Gameplay, Roads, Buildings, Land, Forest), in
  `main` if most people want it, otherwise in that tab's `advanced`.
- Only changes what you see -> **map widget**.
- About the app or this computer, not this map -> **menu/dialog**.

A zone's settings are the edge case that proves the rule: the *values* are generation
settings, but they apply to one drawn place, so zones live on the **left** and take
their names, descriptions and placeholder values from Properties.

## No cross-panel coupling

One side may **mention** the other and link to it (the zones notice at the top of
Properties opens a zone in Tools -> Zones), but it never **holds** the other side's
controls, and changing something on one side never silently changes a value on the
other. When text on one side refers to the other, name it by its real place
("in Properties, on the Gameplay tab", "under Tools, Zones").

When something moves, grep for its old location in visible text (`templates/index.html`,
`static/js/*.js`, `web/system.py`, `lang/*.txt`) and update every reference.

## Related

- `ui-sidebar-conventions` - how things look once they are placed.
- `ui-strings` - translation of any new or changed text.
- `ui-verify` - checking the result in the running app.
