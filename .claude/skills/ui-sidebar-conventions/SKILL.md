---
name: ui-sidebar-conventions
description: Use when building or changing anything inside the KnoxMap Tools or Properties sidebars (settings rows, switches, tooltips, tabs, collapsible sections, warnings, selection boxes) so it matches the established look and behaviour.
---

# Sidebar conventions

Both sidebars follow the same rules. Reuse the existing classes and helpers. Don't
invent a near-copy.

## Tabs

- Each sidebar is split into tabs (`.setting-tabs` / `.setting-tab`) with an emoji
  icon (`.setting-tab-icon`) and a short name. Tabs are the main dividers; they wrap
  rather than scroll.
- Properties tabs come from `SETTING_GROUPS` in `static/js/settings.js` (`title`,
  `icon`, `main`, `advanced` with subheads). A setting not in any group falls into
  "Other". `tests/test_setting_tabs.py` checks every labelled setting is in exactly
  one tab.
- Tools tabs come from `TOOLS` in `static/js/shell.js`.

## Main and Advanced

Per tab: a few main controls, then **one** Advanced fold
(`details.setting-group-advanced`, summary with `.adv-count`), closed by default.
The settings search opens Advanced when a match is inside it.

## A setting row

- Compact, one line: `.setting.setting-compact` - name, control, value.
- The description is **not** inline. It sits behind an **(i)**:
  `button.setting-info` in the name and `span.setting-hint[role=tooltip]` in the
  row, wired with `wireSettingInfo(row)` (hover/focus shows it, click pins it, opens
  upwards near the bottom). Rows built outside `settingElement` call
  `wireSettingInfo` themselves (see the zone editor in `drawing_board.js`).
- A rule like `.zone-list button` elsewhere can restyle the (i). It must stay a
  15px circle, so check it in the browser.
- Labels and descriptions live in `SETTING_LABELS` (`[name, description]`). Reuse
  them anywhere the same setting appears (zones do).

## On/off

A 0/1 setting is a switch with explicit text, never a bare checkbox or a 0-1 slider:

```html
<label class="switch"><input type="checkbox" role="switch" ...><span class="switch-track"
  aria-hidden="true"><span class="sw-on">On</span><span class="sw-off">Off</span></span></label>
```

Place it next to its label (`.setting-switch`, grid column 2).

## Modified = yellow

Anything off its default shows `--changed` (`#f2c94c`): the label goes bold yellow,
and its slider, switch, select or box turns yellow too. Toggle `.is-changed` on the
row (`markChangedTabs` in Properties; `markZoneEditor`, `drawZoneList` and the
sketch switch on the left). Tabs on the right get a dot; tabs on the left do not.

## Collapsible sections

Use `<details>`/`<summary>` (or `.zone-caret` on a custom heading). All of them
share one large rotating chevron (`summary::before` in `app.css`), so don't add
another arrow. Groups in a long palette start collapsed (`.palette-fold`).

## Warnings and messages

- **Warnings go at the top of their sidebar**, unless they are about one nearby
  control (the corners note under the corner boxes, the "not in the picture" marks
  in the Forest tab).
  - Properties: `#zonesNotice`, `#areaWarnings`, `#reapply` come first in
    `.ws-mapprops`.
  - Tools: each tab's note (`PANE_NOTE` in `shell.js`, class `.pane-note`) is the
    first thing under the tabs.
- The setup bar at the top shows only problems. Each problem is a fold with its fix
  inside, and the bar can be dismissed.
- A long notice is a fold, and its summary line must open it.

## Selection and toolbars (left)

- A selection box always shows, at the top of its tab, prominent when something is
  picked and faint "No selection" otherwise (`emptyPicked` in `KnoxDraw`).
- Toolbars are grouped icon buttons from `KnoxDraw.toolbar` / `KnoxDraw.icon`
  (history, shape, clear). The toolbar sits above the selection box.
- Buttons that finish a drawing (Finish, Save, Cancel) are mirrored into the tab
  (`.ws-draw-acts`). The map's own Leaflet toolbar stays hidden.

## Gotcha

Panes in `shell.js` are built off-page and appended at the end of the loop. Inside
that loop, `document.getElementById` cannot find their children yet, so look them up
inside the pane instead: `pane.querySelector('#id')`.
