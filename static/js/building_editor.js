// ---- the building editor ----------------------------------------------------
//
// One building, drawn room by room on its own screen, and used by the
// generator wherever the map has a building of that kind: a police station
// somebody built is the police station on the map, not an arrangement of
// offices that happens to be called one (knoxbuild/designer.py).
//
// The drawing lives here and the geometry lives on the server: rooms may not
// overlap, which is a rule the rest of the pipeline is built on, so every
// change is sent whole and comes back cleaned up with a picture of what it
// really builds - the doors, the windows and the furniture included.
let bdMeta = null;              // {kinds, rooms, styles, limits, presets, use}
const bdMetaFor = {};           // the rooms and styles of each kind, once asked
let bdDesign = null;            // what is drawn
let bdLevel = 0;                // the storey being drawn
let bdRoom = '';                // the picked room ('' is the eraser)
let bdHistory = [];
let bdFuture = [];              // what Redo brings back
let bdBusy = false;
// The picked room, by where it is rather than by its place in the list: the
// server hands the design back cleaned up, so an index does not survive a
// round trip but a rectangle on a storey does.
let bdSel = null;               // {level, x, y, w, h} or null

function bdNote(text) {
  const box = document.getElementById('bdNote');
  if (box) box.textContent = text || '';
}

function bdApiError(data, res) {
  return apiError(data, res);
}

async function bdLoad(kind) {
  const key = kind || '';
  if (!bdMetaFor[key]) {
    const res = await fetch(`/api/builder?kind=${encodeURIComponent(key)}`);
    bdMetaFor[key] = await res.json();
  }
  bdMeta = bdMetaFor[key];
  return bdMeta;
}

// ---- the panel: which kinds are built from presets, and what there is ------

function bdPresetKind(entry) {
  const kinds = (bdMeta && bdMeta.kinds) || [];
  const found = kinds.find(k => k.id === entry.kind);
  return found ? found.label : 'Any building';
}

function drawBuiltList() {
  const box = document.getElementById('builtList');
  if (!box || !bdMeta) return;
  const presets = bdMeta.presets || [];
  box.innerHTML = presets.map(p => `<li>
      <span>${escapeHtml(p.name)}</span>
      <span class="zone-what">${p.width}×${p.height}, ${p.storeys} storey${p.storeys === 1 ? '' : 's'}
        · ${escapeHtml(bdPresetKind(p))}${p.shared
          ? ` · shipped with KnoxMap${p.author ? `, by ${escapeHtml(p.author)}` : ''}` : ''}</span>
      ${p.editable ? `<button type="button" data-open-built="${escapeHtml(p.name)}">Open</button>` : ''}
      <button type="button" data-share-built="${escapeHtml(p.name)}">Share</button>
      ${p.shared ? '' : `<button type="button" data-drop-built="${escapeHtml(p.name)}">Remove</button>`}</li>`).join('');
  runListSearch('builtList');
  const badge = document.getElementById('builtCount');
  if (badge) badge.textContent = presets.length ? `(${presets.length})` : '';
}

function drawBuiltKinds() {
  const box = document.getElementById('builtKinds');
  if (!box || !bdMeta) return;
  const on = new Set(bdMeta.use || []);
  const have = {};
  for (const p of bdMeta.presets || []) {
    have[p.kind || ''] = (have[p.kind || ''] || 0) + 1;
  }
  box.innerHTML = (bdMeta.kinds || []).map(k => `<button type="button"
      class="sketch-pick ${on.has(k.id) ? 'on' : ''}" data-use-kind="${k.id}"
      title="${have[k.id] ? have[k.id] + ' hand-built' : 'nothing hand-built for this yet'}">
      ${escapeHtml(k.label)}${have[k.id] ? ` (${have[k.id]})` : ''}</button>`).join('');
}

async function refreshBuilt() {
  try {
    bdMetaFor[''] = await (await fetch('/api/builder?kind=')).json();
    bdMeta = bdMetaFor[''];
  } catch {
    return;                       // the panel simply stays as it was
  }
  drawBuiltKinds();
  drawBuiltList();
}

function builtNote(text, kind) {
  const el = document.getElementById('builtNote');
  el.textContent = text;
  el.className = kind === 'bad' ? 'hint bad' : 'hint';
}

// One file holds the whole building - the .tbx, the drawing it was made from
// and what it stands in for - so it can be sent to somebody over Discord and
// dropped into their KnoxMap (knoxbuild/share.py).
async function bdShare(name) {
  try {
    const res = await fetch(`/api/presets/buildings/${encodeURIComponent(name)}/share`,
                            { method: 'POST', headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({}) });
    if (!res.ok) throw bdApiError(await res.json(), res);
    if (IN_WINDOW) {
      const data = await res.json();
      builtNote(`Wrote ${data.name} to ${data.folder}. Send that file to anyone `
                + 'with KnoxMap, or to the KnoxMap Discord to have it shipped.');
    } else {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${name.replace(/[^A-Za-z0-9_-]+/g, '_') || 'building'}.knoxbuilding.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      builtNote(`Shared "${name}".`);
    }
  } catch (err) { builtNote(err.message, 'bad'); }
}

document.getElementById('builtImport').addEventListener('click', () =>
  document.getElementById('builtFile').click());

document.getElementById('builtFile').addEventListener('change', async ev => {
  const file = ev.target.files[0];
  ev.target.value = '';                    // so the same file can be picked again
  if (!file) return;
  try {
    if (file.size > 5000000) throw new Error('That building file is too large.');
    let building;
    try { building = JSON.parse(await file.text()); }
    catch (_) { throw new Error('That file is not a building shared from KnoxMap.'); }
    const res = await fetch('/api/presets/buildings/import', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(building) });
    const out = await res.json();
    if (!res.ok) throw bdApiError(out, res);
    await refreshBuilt();
    const who = out.author ? `, built by ${out.author}` : '';
    builtNote(`Took in "${out.saved.name}"${who}. Switch its kind on above to `
              + 'have the map use it.');
  } catch (err) { builtNote(err.message, 'bad'); }
});

document.getElementById('builtKinds').addEventListener('click', async ev => {
  const btn = ev.target.closest('[data-use-kind]');
  if (!btn) return;
  const kind = btn.dataset.useKind;
  const on = !btn.classList.contains('on');
  try {
    const res = await fetch('/api/builder/use', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, on }) });
    const out = await res.json();
    if (!res.ok) throw bdApiError(out, res);
    for (const cached of Object.values(bdMetaFor)) cached.use = out.use;
    drawBuiltKinds();
    const found = (bdMeta.kinds || []).find(k => k.id === kind);
    const name = found ? found.label : kind;
    builtNote(on
      ? `${name}: the hand-built one is used. Generate buildings again to see it.`
      : `${name}: back to buildings the generator lays out.`);
  } catch (err) {
    builtNote(err.message, 'bad');
  }
});

document.getElementById('builtList').addEventListener('click', async ev => {
  const open = ev.target.closest('[data-open-built]');
  if (open) {
    builderOpen();
    await bdOpenSaved(open.dataset.openBuilt);
    return;
  }
  const share = ev.target.closest('[data-share-built]');
  if (share) {
    await bdShare(share.dataset.shareBuilt);
    return;
  }
  const drop = ev.target.closest('[data-drop-built]');
  if (!drop) return;
  const name = drop.dataset.dropBuilt;
  try {
    const res = await fetch(`/api/presets/buildings/${encodeURIComponent(name)}`,
                            { method: 'DELETE' });
    if (!res.ok) throw bdApiError(await res.json(), res);
    await refreshBuilt();
    builtNote(`"${name}" removed.`);
  } catch (err) {
    builtNote(err.message, 'bad');
  }
});

// ---- the editor itself -----------------------------------------------------

// Drawing a rectangle over a room takes that much out of whatever is under
// it, which is right for drawing and wrong for changing your mind: nudging
// one wall of a room meant redrawing the room, and the redraw ate its
// neighbours. In adjust mode a drag on a room's edge moves that edge and a
// drag in its middle moves the whole room, keeping its kind and leaving
// everything else where it was.
let bdMode = 'draw';

function bdRoomAt(x, y) {
  const rooms = (bdDesign && bdDesign.rooms) || [];
  for (let i = rooms.length - 1; i >= 0; i -= 1) {
    const r = rooms[i];
    if (r.level === bdLevel && x >= r.x && x < r.x + r.w
        && y >= r.y && y < r.y + r.h) return { i, r };
  }
  return null;
}

// Which part of a room was taken hold of: a side, a corner, or the middle.
// The band is a quarter of the shorter side, up to two tiles, so a small room
// is not all edge and a big one does not need the pointer on the pixel.
function bdGrip(r, x, y) {
  const near = Math.max(1, Math.min(2, Math.floor(Math.min(r.w, r.h) / 4)));
  let edge = '';
  if (y - r.y < near) edge += 'n';
  else if (r.y + r.h - 1 - y < near) edge += 's';
  if (x - r.x < near) edge += 'w';
  else if (r.x + r.w - 1 - x < near) edge += 'e';
  return edge;
}

const BD_CURSOR = { n: 'ns-resize', s: 'ns-resize', e: 'ew-resize',
                    w: 'ew-resize', nw: 'nwse-resize', se: 'nwse-resize',
                    ne: 'nesw-resize', sw: 'nesw-resize', '': 'move' };

function bdResized(r, edge, dx, dy) {
  let { x, y, w, h } = r;
  if (!edge) {
    x += dx;
    y += dy;
  }
  if (edge.includes('w')) { const by = Math.min(dx, w - 1); x += by; w -= by; }
  if (edge.includes('e')) { w = Math.max(1, w + dx); }
  if (edge.includes('n')) { const by = Math.min(dy, h - 1); y += by; h -= by; }
  if (edge.includes('s')) { h = Math.max(1, h + dy); }
  x = Math.min(Math.max(x, 0), bdDesign.width - 1);
  y = Math.min(Math.max(y, 0), bdDesign.height - 1);
  return { x, y, w: Math.min(w, bdDesign.width - x),
           h: Math.min(h, bdDesign.height - y) };
}

// The room goes back on top of the pile: a room dragged over its neighbour
// takes that ground, the same as drawing it there would.
function bdApplyEdit(idx, rect) {
  if (!bdDesign || bdBusy) return;
  bdRemember();
  const next = JSON.parse(JSON.stringify(bdDesign));
  const room = next.rooms[idx];
  if (!room) return;
  next.rooms.splice(idx, 1);
  next.rooms.push({ level: room.level, x: rect.x, y: rect.y,
                    w: rect.w, h: rect.h, kind: room.kind });
  bdSel = { level: room.level, x: rect.x, y: rect.y, w: rect.w, h: rect.h };
  bdRefresh(next);
}

function bdSelIndex() {
  if (!bdSel || !bdDesign) return -1;
  const rooms = bdDesign.rooms || [];
  for (let i = rooms.length - 1; i >= 0; i -= 1) {
    const r = rooms[i];
    if (r.level === bdSel.level && r.x === bdSel.x && r.y === bdSel.y
        && r.w === bdSel.w && r.h === bdSel.h) return i;
  }
  return -1;
}

function bdRoomLabel(id) {
  const found = ((bdMeta && bdMeta.rooms) || []).find(r => r.id === id);
  return found ? found.label : (id || 'Cut away');
}

// A box over the plan in tile coordinates; shared by the drag outline and the
// outline of the picked room.
function bdPlaceBox(el, x0, y0, w, h) {
  const plan = document.getElementById('bdPlan');
  const img = document.getElementById('bdImage');
  const box = img.getBoundingClientRect();
  if (!bdDesign || !box.width) { el.hidden = true; return; }
  const plot = plan.getBoundingClientRect();
  const tw = box.width / bdDesign.width;
  const th = box.height / bdDesign.height;
  el.hidden = false;
  el.style.left = `${box.left - plot.left + x0 * tw}px`;
  el.style.top = `${box.top - plot.top + y0 * th}px`;
  el.style.width = `${w * tw}px`;
  el.style.height = `${h * th}px`;
}

function bdShowSel() {
  const el = document.getElementById('bdSelBox');
  const i = bdSelIndex();
  if (i < 0 || bdSel.level !== bdLevel) {
    if (i < 0) bdSel = null;
    el.hidden = true;
    return;
  }
  bdPlaceBox(el, bdSel.x, bdSel.y, bdSel.w, bdSel.h);
}

function bdSelect(room) {
  bdSel = room ? { level: room.level, x: room.x, y: room.y, w: room.w, h: room.h } : null;
  bdShowSel();
  if (room) {
    bdNote(`${bdRoomLabel(room.kind)}, ${room.w}×${room.h} tiles. Arrow keys move it `
      + '(Shift for five tiles), Delete removes it, Ctrl+D copies it, Escape lets go.');
  }
}

function bdDeleteSel() {
  const i = bdSelIndex();
  if (i < 0 || bdBusy) return;
  bdRemember();
  const next = JSON.parse(JSON.stringify(bdDesign));
  next.rooms.splice(i, 1);
  bdSel = null;
  bdRefresh(next);
}

function bdDuplicateSel() {
  const i = bdSelIndex();
  if (i < 0 || bdBusy) return;
  bdRemember();
  const next = JSON.parse(JSON.stringify(bdDesign));
  const r = next.rooms[i];
  const at = bdResized(r, '', 2, 2);
  next.rooms.push({ level: r.level, x: at.x, y: at.y, w: at.w, h: at.h, kind: r.kind });
  bdSel = { level: r.level, ...at };
  bdRefresh(next);
}

function bdNudgeSel(dx, dy) {
  const i = bdSelIndex();
  if (i < 0 || bdBusy) return;
  const r = bdDesign.rooms[i];
  const to = bdResized(r, '', dx, dy);
  if (to.x === r.x && to.y === r.y) return;
  bdApplyEdit(i, to);
}

// Copy this floor onto the one above it, adding the floor if there is not one.
function bdCopyFloorUp() {
  if (!bdDesign || bdBusy) return;
  const to = bdLevel + 1;
  if (to >= 8) { bdNote('That is the top: a building has up to eight storeys.'); return; }
  bdRemember();
  const next = JSON.parse(JSON.stringify(bdDesign));
  if (to >= next.storeys) next.storeys = to + 1;
  const copy = next.rooms.filter(r => r.level === bdLevel)
    .map(r => ({ ...r, level: to }));
  next.rooms = next.rooms.filter(r => r.level !== to).concat(copy);
  bdSel = null;
  bdRefresh(next, to);
  bdNote(`This floor copied up to ${to === 0 ? 'the ground floor' : 'floor ' + to}.`);
}

function bdRoomsMarkup() {
  const groups = [];
  for (const entry of (bdMeta && bdMeta.rooms) || []) {
    const last = groups[groups.length - 1];
    if (!last || last.name !== entry.group) {
      groups.push({ name: entry.group, items: [entry] });
    } else {
      last.items.push(entry);
    }
  }
  const adjust = `<div class="palette-group">
      <span class="palette-head">Change what is drawn</span>
      <button type="button" class="sketch-pick ${bdMode === 'adjust' ? 'on' : ''}"
        data-mode="adjust" title="Drag a room's edge to move it, its middle to move the room">
        Adjust rooms</button></div>`;
  const eraser = `<div class="palette-group">
      <span class="palette-head">The eraser</span>
      <button type="button" class="sketch-pick ${bdRoom === '' ? 'on' : ''}"
        data-room="" title="Takes what is under it out of the building">
        <span class="swatch" style="background:#e8e7e2"></span>
        Nothing - cut it away</button></div>`;
  return adjust + eraser + groups.map(g => `<div class="palette-group">
      <span class="palette-head">${escapeHtml(g.name)}</span>
      ${g.items.map(e => `<button type="button"
        class="sketch-pick ${e.id === bdRoom ? 'on' : ''}" data-room="${e.id}"
        title="${escapeHtml(e.id)}">
        <span class="swatch" style="background:${e.colour}"></span>
        ${escapeHtml(e.label)}</button>`).join('')}
    </div>`).join('');
}

function drawBdRooms() {
  const box = document.getElementById('bdRooms');
  if (!box) return;
  box.innerHTML = bdRoomsMarkup();
  runListSearch('bdRooms');
}

function drawBdStoreys() {
  const box = document.getElementById('bdStoreyTabs');
  if (!box || !bdDesign) return;
  const names = [];
  for (let i = 0; i < bdDesign.storeys; i += 1) {
    names.push(`<button type="button" class="sketch-pick ${i === bdLevel ? 'on' : ''}"
      data-storey="${i}">${i === 0 ? 'Ground floor' : 'Floor ' + i}</button>`);
  }
  box.innerHTML = names.join('');
}

function bdFields() {
  if (!bdDesign) return;
  document.getElementById('bdName').value = bdDesign.name || '';
  document.getElementById('bdWidth').value = bdDesign.width;
  document.getElementById('bdHeight').value = bdDesign.height;
  document.getElementById('bdStoreys').value = bdDesign.storeys;
  const kinds = (bdMeta && bdMeta.kinds) || [];
  document.getElementById('bdKind').innerHTML =
    ['<option value="">Any building</option>'].concat(kinds.map(k =>
      `<option value="${k.id}"${k.id === bdDesign.kind ? ' selected' : ''}>${escapeHtml(k.label)}</option>`)).join('');
  const styles = (bdMeta && bdMeta.styles) || [];
  document.getElementById('bdStyle').innerHTML =
    ['<option value="">Whatever suits it</option>'].concat(styles.map(s =>
      `<option value="${s}"${s === bdDesign.style ? ' selected' : ''}>${escapeHtml(s)}</option>`)).join('');
}

// What the picture is drawn at, so a drag can be read back in tiles however
// the picture is scaled to fit the screen.
function bdTileAt(ev) {
  const img = document.getElementById('bdImage');
  const box = img.getBoundingClientRect();
  if (!box.width || !box.height || !bdDesign) return null;
  const x = Math.floor((ev.clientX - box.left) / box.width * bdDesign.width);
  const y = Math.floor((ev.clientY - box.top) / box.height * bdDesign.height);
  return { x: Math.min(Math.max(x, 0), bdDesign.width - 1),
           y: Math.min(Math.max(y, 0), bdDesign.height - 1) };
}

function bdShow(data) {
  bdDesign = data.design;
  bdLevel = data.level;
  const img = document.getElementById('bdImage');
  img.hidden = !data.image;
  if (data.image) img.src = data.image;
  document.getElementById('bdEmpty').hidden = data.painted > 0;
  document.getElementById('bdUndo').disabled = !bdHistory.length;
  document.getElementById('bdRedo').disabled = !bdFuture.length;
  drawBdStoreys();
  bdShowSel();
  bdFields();

  const tally = document.getElementById('bdTally');
  tally.innerHTML = (data.tally || []).map(t => `<li>
      <span class="swatch" style="background:${t.colour}"></span>
      ${escapeHtml(t.label)}<span class="how-much">${t.tiles} tiles</span></li>`).join('')
    || '<li class="hint">Nothing drawn on this floor yet.</li>';
  const tiles = document.getElementById('bdTiles');
  tiles.innerHTML = (data.tiles || []).map(t => `<li>
      <b>${escapeHtml(t.what)}</b>
      ${t.tiles && t.tiles.length ? `<br><code>${escapeHtml(t.tiles.join(', '))}</code>` : ''}
      ${t.fittings && t.fittings.length
        ? `<br><span class="hint">${escapeHtml(t.fittings.join(', '))}</span>` : ''}
      </li>`).join('');

  const b = data.built || {};
  bdNote(`${b.rooms || 0} rooms, ${b.doors || 0} doorways, ${b.windows || 0} windows, `
    + `${b.furniture || 0} things in them - as it will be built.`
    + (data.oneStoreyAtATime
      ? ' A building this big is drawn a floor at a time; the rest are built when it is saved.'
      : ''));
}

async function bdRefresh(design, level) {
  if (bdBusy) return;
  bdBusy = true;
  document.getElementById('bdPlan').style.opacity = '0.6';
  try {
    const res = await fetch('/api/builder/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ design: design || bdDesign,
                             level: level === undefined ? bdLevel : level }) });
    const out = await res.json();
    if (!res.ok) throw bdApiError(out, res);
    bdShow(out);
  } catch (err) {
    bdNote(err.message);
  } finally {
    bdBusy = false;
    document.getElementById('bdPlan').style.opacity = '';
  }
}

function bdRemember() {
  bdHistory.push(JSON.stringify(bdDesign));
  if (bdHistory.length > 40) bdHistory.shift();
  bdFuture = [];              // a new change ends the road forward
}

function bdUndo() {
  const was = bdHistory.pop();
  if (!was || bdBusy) { if (was) bdHistory.push(was); return; }
  bdFuture.push(JSON.stringify(bdDesign));
  bdRefresh(JSON.parse(was));
}

function bdRedo() {
  const next = bdFuture.pop();
  if (!next || bdBusy) { if (next) bdFuture.push(next); return; }
  bdHistory.push(JSON.stringify(bdDesign));
  bdRefresh(JSON.parse(next));
}

function bdDraw(x0, y0, x1, y1) {
  if (!bdDesign) return;
  bdRemember();
  const next = JSON.parse(JSON.stringify(bdDesign));
  next.rooms.push({ level: bdLevel, x: Math.min(x0, x1), y: Math.min(y0, y1),
                    w: Math.abs(x1 - x0) + 1, h: Math.abs(y1 - y0) + 1,
                    kind: bdRoom });
  bdRefresh(next);
}

function builderOpen() {
  document.getElementById('builder').hidden = false;
}

async function bdStart() {
  await bdLoad('');
  if (!bdDesign) {
    bdDesign = { name: '', kind: '', style: '', width: 20, height: 16,
                 storeys: 1, rooms: [] };
    bdHistory = [];
    bdFuture = [];
  }
  bdSel = null;
  drawBdRooms();
  await bdRefresh(bdDesign, 0);
  bdNote('Pick a room, then drag a rectangle on the plan. Adjust rooms moves the walls of one already drawn.');
}

async function bdOpenSaved(name) {
  try {
    const res = await fetch(`/api/builder/design/${encodeURIComponent(name)}`);
    const out = await res.json();
    if (!res.ok) throw bdApiError(out, res);
    bdHistory = [];
    bdFuture = [];
    bdSel = null;
    bdShow(out);
    await bdLoad(out.design.kind || '');
    drawBdRooms();
    bdFields();
    bdNote(`"${name}" as it was drawn. Change it and save it again.`);
  } catch (err) {
    bdNote(err.message);
  }
}

document.getElementById('builderOpen').addEventListener('click', () => {
  builderOpen();
  bdStart();
});

document.getElementById('bdClose').addEventListener('click', () => {
  document.getElementById('builder').hidden = true;
  refreshBuilt();
});

document.getElementById('bdRooms').addEventListener('click', ev => {
  const tool = ev.target.closest('[data-mode]');
  if (tool) {
    bdMode = bdMode === 'adjust' ? 'draw' : 'adjust';
    drawBdRooms();
    bdNote(bdMode === 'adjust'
      ? 'Drag the edge of a room to move that wall, or its middle to move the '
        + 'whole room. Pick a room from the list to go back to drawing.'
      : 'Back to drawing: drag a rectangle on the plan.');
    return;
  }
  const btn = ev.target.closest('[data-room]');
  if (!btn) return;
  bdRoom = btn.dataset.room;
  bdMode = 'draw';
  drawBdRooms();
  bdNote(bdRoom ? `Drag on the plan to draw a ${btn.textContent.trim()}.`
                : 'Drag on the plan to cut that part out of the building.');
});

document.getElementById('bdStoreyTabs').addEventListener('click', ev => {
  const btn = ev.target.closest('[data-storey]');
  if (btn) bdRefresh(bdDesign, parseInt(btn.dataset.storey, 10));
  bdShowSel();
});

// Dragging a rectangle on the plan. The outline follows the pointer as a box
// over the picture; the room itself is only drawn when the drag is let go,
// because every change is a round trip to have the geometry worked out.
(() => {
  const plan = document.getElementById('bdPlan');
  const ghost = document.getElementById('bdDrag');
  let from = null;                // where a drawing drag started
  let grab = null;                // the room being adjusted, and where by

  function placeBox(x0, y0, w, h) {
    bdPlaceBox(ghost, x0, y0, w, h);
    // How big it is, as it is dragged: tiles are what the sheet is measured in.
    ghost.dataset.size = `${w} × ${h}`;
  }

  function place(a, b) {
    placeBox(Math.min(a.x, b.x), Math.min(a.y, b.y),
             Math.abs(b.x - a.x) + 1, Math.abs(b.y - a.y) + 1);
  }

  function dragged(now) {
    return bdResized(grab.r, grab.edge, now.x - grab.at.x, now.y - grab.at.y);
  }

  plan.addEventListener('pointerdown', ev => {
    if (!bdDesign || bdBusy) return;
    const at = bdTileAt(ev);
    if (!at) return;
    ev.preventDefault();          // dragging the picture itself, otherwise
    if (bdMode === 'adjust') {
      const found = bdRoomAt(at.x, at.y);
      if (!found) {
        bdNote('Take hold of a room that is already drawn: its edge to move '
               + 'that wall, its middle to move the room.');
        return;
      }
      bdSelect(found.r);
      grab = { idx: found.i, r: found.r, at,
               edge: bdGrip(found.r, at.x, at.y) };
      placeBox(found.r.x, found.r.y, found.r.w, found.r.h);
      return;
    }
    from = at;
    place(at, at);
  });

  // What the pointer would take hold of, before it does.
  plan.addEventListener('pointermove', ev => {
    const hover = document.getElementById('bdHover');
    const here = bdDesign && bdTileAt(ev);
    if (here) {
      const found = bdRoomAt(here.x, here.y);
      hover.textContent = `${here.x}, ${here.y}`
        + (found ? ` · ${bdRoomLabel(found.r.kind)} ${found.r.w}×${found.r.h}` : '');
    }
    if (grab || from || !bdDesign) return;
    if (bdMode !== 'adjust') { plan.style.cursor = ''; return; }
    const at = bdTileAt(ev);
    const found = at && bdRoomAt(at.x, at.y);
    plan.style.cursor = found
      ? BD_CURSOR[bdGrip(found.r, at.x, at.y)] : 'not-allowed';
  });
  // The rest of the drag is watched on the window rather than on the plan:
  // letting go past the edge of the picture is how anyone draws a room that
  // reaches the wall, and on the plan alone that release never arrived - the
  // room was never drawn and the outline stayed on the screen.
  window.addEventListener('pointermove', ev => {
    if (grab) {
      const now = bdTileAt(ev);
      if (now) {
        const rect = dragged(now);
        placeBox(rect.x, rect.y, rect.w, rect.h);
      }
      return;
    }
    if (!from) return;
    const now = bdTileAt(ev);
    if (now) place(from, now);
  });
  window.addEventListener('pointerup', ev => {
    if (grab) {
      const now = bdTileAt(ev) || grab.at;
      const held = grab;
      grab = null;
      ghost.hidden = true;
      const to = bdResized(held.r, held.edge,
                           now.x - held.at.x, now.y - held.at.y);
      // A click that moved nothing is a click: the room stays as it was.
      if (to.x !== held.r.x || to.y !== held.r.y
          || to.w !== held.r.w || to.h !== held.r.h) {
        bdApplyEdit(held.idx, to);
      }
      return;
    }
    if (!from) return;
    const now = bdTileAt(ev) || from;
    ghost.hidden = true;
    const started = from;
    from = null;
    bdDraw(started.x, started.y, now.x, now.y);
  });
  window.addEventListener('resize', bdShowSel);
  window.addEventListener('pointercancel', () => {
    from = null;
    grab = null;
    ghost.hidden = true;
  });
})();

document.addEventListener('keydown', ev => {
  if (document.getElementById('builder').hidden) return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName || '')) return;
  const mod = ev.ctrlKey || ev.metaKey;
  const key = ev.key.toLowerCase();
  if (mod && key === 'z') { ev.preventDefault(); if (ev.shiftKey) bdRedo(); else bdUndo(); }
  else if (mod && key === 'y') { ev.preventDefault(); bdRedo(); }
  else if (mod && key === 'd') { ev.preventDefault(); bdDuplicateSel(); }
  else if (ev.key === 'Escape') { bdSelect(null); }
  else if ((ev.key === 'Delete' || ev.key === 'Backspace') && bdSel) {
    ev.preventDefault();
    bdDeleteSel();
  } else if (bdSel && ev.key.startsWith('Arrow')) {
    ev.preventDefault();
    const n = ev.shiftKey ? 5 : 1;
    bdNudgeSel(ev.key === 'ArrowLeft' ? -n : ev.key === 'ArrowRight' ? n : 0,
               ev.key === 'ArrowUp' ? -n : ev.key === 'ArrowDown' ? n : 0);
  }
});

for (const id of ['bdWidth', 'bdHeight', 'bdStoreys']) {
  document.getElementById(id).addEventListener('change', () => {
    if (!bdDesign) return;
    bdRemember();
    const next = JSON.parse(JSON.stringify(bdDesign));
    next.width = parseInt(document.getElementById('bdWidth').value, 10) || next.width;
    next.height = parseInt(document.getElementById('bdHeight').value, 10) || next.height;
    next.storeys = parseInt(document.getElementById('bdStoreys').value, 10) || 1;
    bdRefresh(next, Math.min(bdLevel, next.storeys - 1));
  });
}

document.getElementById('bdName').addEventListener('input', ev => {
  if (bdDesign) bdDesign.name = ev.target.value;
});

document.getElementById('bdKind').addEventListener('change', async ev => {
  if (!bdDesign) return;
  bdDesign.kind = ev.target.value;
  // The rooms offered and the walls available both depend on what is being
  // built, so both are asked for again.
  await bdLoad(bdDesign.kind);
  if (bdRoom && !(bdMeta.rooms || []).some(r => r.id === bdRoom)) bdRoom = '';
  drawBdRooms();
  bdRefresh(bdDesign);
});

document.getElementById('bdStyle').addEventListener('change', ev => {
  if (!bdDesign) return;
  bdDesign.style = ev.target.value;
  bdRefresh(bdDesign);
});

document.getElementById('bdFill').addEventListener('click', async () => {
  if (!bdDesign || bdBusy) return;
  bdRemember();
  bdBusy = true;
  bdNote('Laying it out...');
  try {
    const res = await fetch('/api/builder/autofill', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ design: bdDesign, level: bdLevel }) });
    const out = await res.json();
    if (!res.ok) throw bdApiError(out, res);
    bdShow(out);
    bdNote('Laid out as the generator would have. Change whatever you like.');
  } catch (err) {
    bdNote(err.message);
  } finally {
    bdBusy = false;
  }
});

document.getElementById('bdUndo').addEventListener('click', bdUndo);
document.getElementById('bdRedo').addEventListener('click', bdRedo);
document.getElementById('bdCopyUp').addEventListener('click', bdCopyFloorUp);

document.getElementById('bdClear').addEventListener('click', () => {
  if (!bdDesign) return;
  bdRemember();
  bdRefresh({ ...bdDesign, rooms: bdDesign.rooms.filter(r => r.level !== bdLevel) });
  bdNote('This floor cleared.');
});

document.getElementById('bdSave').addEventListener('click', async () => {
  if (!bdDesign) return;
  const name = document.getElementById('bdName').value.trim();
  if (!name) { bdNote('Give the building a name first.'); return; }
  try {
    const res = await fetch('/api/builder/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, design: { ...bdDesign, name } }) });
    const out = await res.json();
    if (!res.ok) throw bdApiError(out, res);
    for (const cached of Object.values(bdMetaFor)) cached.presets = out.presets;
    drawBuiltKinds();
    drawBuiltList();
    const kept = out.saved;
    bdNote(`Saved as "${kept.name}": ${kept.width}×${kept.height}, `
      + `${kept.storeys} storey${kept.storeys === 1 ? '' : 's'}. `
      + (bdDesign.kind
        ? 'Switch its kind on in "Hand-built buildings" to have it used.'
        : 'It can stand in for any building a zone draws from.'));
    fx.toast('ok', 'Building saved', `${kept.name} is ready to be used.`);
  } catch (err) {
    bdNote(err.message);
    fx.toast('bad', 'Not saved', err.message);
  }
});

refreshBuilt();
