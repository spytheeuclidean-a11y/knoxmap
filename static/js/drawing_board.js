// ---- drawing a map by hand --------------------------------------------------
//
// Pick something from the palette, draw it, and it joins the features the
// generator would have downloaded. Nothing here paints anything itself: a
// drawn shape becomes an OSM feature with real tags on the server
// (generator/sketch.py) and the renderer, the building generator and the
// compiler treat it exactly as they treat a surveyed one.
//
// The palette and its tags come from /api/sketch rather than being written out
// again here, for the same reason the settings do: a second copy drifts, and a
// tag that is wrong draws a shape on the page that is missing from the map.
const sketchLayer = new L.FeatureGroup().addTo(map);
let sketchPalette = [];
// The area toolbar's own handler, if one is armed, so a tool started from
// somewhere else does not leave it listening as well.
function disarmAreaToolbar() {
  try { drawControl._toolbars.draw.disable(); } catch { /* nothing armed */ }
}
let refreshSketchTools = () => {};
// The editor itself is static/js/draw.js, shared with the drawing board. It
// does not listen for finished shapes here: the area selection above also
// ends in a CREATED event, so the handler up there asks it to claim the shape.
const sketchEd = KnoxDraw.create(map, {
  group: sketchLayer,
  style: kind => sketchStyle(kind),
  label: kind => sketchLabel(kind),
  note: text => noteSketch(text),
  pickedBox: document.getElementById('sketchPicked'),
  emptyPicked: 'No selection',
  palette: document.getElementById('sketchPalette'),
  active: () => document.getElementById('sketch').open
                && document.getElementById('board').hidden,
  listen: false,
  onStart: () => { zoneEd.stop(); disarmAreaToolbar(); },
  onChange: () => { showSketchCount(); refreshSketchTools(); },
});
refreshSketchTools = KnoxDraw.toolbar(document.getElementById('sketchTools'), sketchEd, { rect: false });
// Draw areas as boxes: the Add tab's switch for the editor's rectangle mode.
document.getElementById('sketchRect').addEventListener('change', ev => {
  sketchEd.setRect(ev.target.checked);
  // Off unless asked for: on is a change, yellow like one.
  ev.target.closest('.setting').classList.toggle('is-changed', ev.target.checked);
});

// What each category looks like while it is being drawn. Close enough to the
// finished map to recognise, not so close it is mistaken for it.
const SKETCH_COLOURS = {
  road_major: '#e8a33d', road_medium: '#e8c33d', road_minor: '#cfcfcf',
  road_service: '#9a9a9a', paved_path: '#b8b8a0', dirt_path: '#a88c5f',
  railway: '#7a7a8c', water: '#4d8fd1', coastline: '#4d8fd1',
  forest: '#3f7a3f', scrub: '#6b8f4a', grass: '#6aa84f', park: '#5fa85f',
  farmland: '#b7a24a', sand: '#d9c88a', parking: '#8c8c8c',
  cemetery: '#6f8f6f', playground: '#c76fa8', industrial: '#9a7f6f',
  building: '#c45b4b', fence: '#8a6f4a', hedge: '#4f7a3f',
  tree_single: '#2f7a2f',
};

function sketchStyle(kind) {
  const cat = (sketchPalette.find(e => e.id === kind) || {}).category;
  const colour = SKETCH_COLOURS[cat] || '#3d8bfd';
  return { color: colour, weight: 3, fillColor: colour, fillOpacity: 0.3 };
}

function sketchLabel(kind) {
  return (sketchPalette.find(e => e.id === kind) || {}).label || kind;
}

// Under headings, in the server's order. Thirty-four tools in one run is a
// wall to read, and nobody hunting for "Hedge" wants to scan past "Motorway".
const SKETCH_TIPS = {
  coastline: 'Sea shore (natural=coastline) — floods everything to the right of the line as ocean. Use River or Lake or pond for inland water.',
};

// Folded, each heading is a section that starts closed (the Add tab); the
// search opens the ones it finds something in.
function paletteMarkup(folded = false) {
  const groups = [];
  for (const entry of sketchPalette) {
    const name = entry.group || 'Other';
    const last = groups[groups.length - 1];
    if (!last || last.name !== name) groups.push({ name, items: [entry] });
    else last.items.push(entry);
  }
  const tip = e => SKETCH_TIPS[e.id]
    || Object.entries(e.tags).map(([k, v]) => k + '=' + v).join(', ');
  const picks = g => g.items.map(e => `<button type="button" class="sketch-pick"
        data-kind="${e.id}" data-geometry="${e.geometry}"
        title="${escapeHtml(tip(e))}">
        <span class="swatch" style="background:${SKETCH_COLOURS[e.category] || '#3d8bfd'}"></span>
        ${escapeHtml(e.label)}</button>`).join('');
  if (folded) {
    return groups.map(g => `<details class="palette-group palette-fold">
        <summary><span>${escapeHtml(g.name)}</span><span class="count">${g.items.length}</span></summary>
        <div class="palette-items">${picks(g)}</div>
      </details>`).join('');
  }
  return groups.map(g => `<div class="palette-group">
      <span class="palette-head">${escapeHtml(g.name)}</span>
      ${picks(g)}
    </div>`).join('');
}

async function loadSketchPalette() {
  let data;
  try {
    data = await (await fetch('/api/sketch')).json();
  } catch {
    return;                       // the panel simply stays empty
  }
  sketchPalette = (data.palette || []).map(
    e => ({ ...e, category: (data.categories || {})[e.id] }));
  const box = document.getElementById('sketchPalette');
  if (!box) return;
  box.innerHTML = paletteMarkup(true);
  runListSearch('sketchPalette');
}

function noteSketch(text) {
  const box = document.getElementById('sketchNote');
  if (box) box.textContent = text || '';
}

document.getElementById('sketchPalette')?.addEventListener('click', ev => {
  const btn = ev.target.closest('.sketch-pick');
  if (!btn) return;
  const tip = SKETCH_TIPS[btn.dataset.kind];
  if (tip) noteSketch(tip);
});

function sketchCount() {
  return sketchEd.count;
}

function showSketchCount() {
  const badge = document.getElementById('sketchCount');
  const n = sketchCount();
  if (badge) badge.textContent = n ? `(${n})` : '';
}

// What is drawn, as GeoJSON with the palette id on it.
function sketchGeoJSON() {
  const features = [];
  sketchEd.each((layer, kind) => {
    features.push({ type: 'Feature', properties: { kind },
                    geometry: layer.toGeoJSON().geometry });
  });
  return { type: 'FeatureCollection', features };
}

function loadSketchGeoJSON(drawn) {
  const items = [];
  for (const f of (drawn && drawn.features) || []) {
    const kind = (f.properties || {}).kind;
    const geo = f.geometry || {};
    if (!kind || !geo.type) continue;
    let layer = null;
    if (geo.type === 'LineString') {
      layer = L.polyline(geo.coordinates.map(([lon, lat]) => [lat, lon]));
    } else if (geo.type === 'Polygon') {
      layer = L.polygon((geo.coordinates[0] || []).map(([lon, lat]) => [lat, lon]));
    } else if (geo.type === 'Point') {
      layer = L.marker([geo.coordinates[1], geo.coordinates[0]]);
    }
    if (layer) items.push({ kind, layer });
  }
  sketchEd.replace(items);
}


loadSketchPalette();

// ---- editing what a map was built from --------------------------------------
//
// A generated map is a reading of OpenStreetMap, and a reading is sometimes
// wrong: a shed the survey calls a house, a road through where a square should
// be. The features come back here as shapes; what is changed about them is
// kept as a short list of changes keyed by each one's own OSM id, so a town of
// a hundred thousand features costs a few lines, the download is never
// rewritten, and an edit can be taken back by dropping its line.
const editLayer = new L.FeatureGroup().addTo(map);
let mapEdits = { removed: [], moved: {}, tags: {} };
let editShaper = null;
let editSelected = null;

const EDIT_STYLE = { color: '#f0b429', weight: 2, fillOpacity: 0.12 };
const EDIT_PICKED = { color: '#ff5f5f', weight: 4, fillOpacity: 0.3 };

function editCountNow() {
  return mapEdits.removed.length + Object.keys(mapEdits.moved).length
       + Object.keys(mapEdits.tags).length;
}

function showEditCount() {
  const badge = document.getElementById('editCount');
  const n = editCountNow();
  if (badge) badge.textContent = n ? `(${n})` : '';
  document.getElementById('editSave').disabled = !n;
  document.getElementById('editReset').disabled = !n;
}

function noteEdit(text) {
  const box = document.getElementById('editNote');
  if (box) box.textContent = text || '';
}

function editReady(mapName) {
  document.getElementById('editLoad').disabled = !mapName;
}

// What a feature is, in the palette's words where the palette has a word for
// it, so "Street" and "House" rather than highway=residential.
function describeTags(tags) {
  for (const entry of sketchPalette) {
    if (Object.entries(entry.tags).every(([k, v]) => tags[k] === v)) return entry.label;
  }
  // Its name before any tag of its own: "Manhattan New York Temple" is what
  // somebody is looking for, and "addr:city=New York" is the first tag in
  // alphabetical order rather than anything about the building.
  const t = tags || {};
  if (t.name) return t.name;
  for (const key of ['building', 'amenity', 'shop', 'highway', 'landuse',
                     'leisure', 'natural', 'waterway']) {
    if (t[key]) return `${key}=${t[key]}`;
  }
  const first = Object.entries(t)[0];
  return first ? `${first[0]}=${first[1]}` : 'something';
}

// Why the building that was just clicked is not on the map - the question
// everybody asks about a gap where their own house should be. The build keeps
// the answer per footprint; this is only the asking (web/zones.py, and
// tools/why_no_building.py for a whole area at once).
async function showWhy(layer, tags) {
  const box = document.getElementById('editWhy');
  if (!box || !openedMap || !(tags || {}).building) return;
  box.hidden = false;
  box.textContent = 'Looking up what the build did with it...';
  let data;
  try {
    const res = await fetch(`/api/why/${encodeURIComponent(openedMap.mapName)}`
                            + `?osm=${encodeURIComponent(layer.osmId)}`);
    data = await res.json();
    if (!res.ok) throw apiError(data, res);
  } catch (err) {
    // A building that cannot be explained is not worth an error in the way
    // of removing it, which is what this panel is really for.
    if (editSelected === layer) box.hidden = true;
    return;
  }
  // Clicked away while it was being read: the answer is about the other one.
  if (editSelected !== layer) return;
  if (data.state === 'left out') {
    box.className = 'why why-out';
    box.innerHTML = `<strong>Not built:</strong> ${escapeHtml(data.why || data.reason)}.
      <br><span class="hint">${escapeHtml(data.fix || '')}</span>`;
  } else if (data.state === 'built') {
    box.className = 'why why-in';
    box.textContent = 'This one was built.';
  } else {
    box.className = 'why';
    box.textContent = 'This map was generated before KnoxMap kept these '
      + 'records. Generate it again and clicking a building says why it is '
      + 'missing.';
  }
}

function pickEdit(layer) {
  if (editSelected && editSelected.setStyle) editSelected.setStyle(EDIT_STYLE);
  editSelected = layer;
  const box = document.getElementById('editSelected');
  if (!layer) { box.hidden = true; box.innerHTML = ''; return; }
  layer.setStyle(EDIT_PICKED);
  const tags = mapEdits.tags[layer.osmId] || layer.osmTags || {};
  box.hidden = false;
  box.innerHTML = `<span class="hint">${escapeHtml(describeTags(tags))}
      <small>#${layer.osmId}</small></span>
    <button type="button" id="editDelete" class="btn">Remove it</button>
    <select id="editRetag"><option value="">Say what it is...</option>
      ${sketchPalette.filter(e => e.geometry !== 'point').map(e =>
        `<option value="${e.id}">${escapeHtml(e.label)}</option>`).join('')}
    </select>
    <div class="why" id="editWhy" hidden></div>`;
  // The panel is taller than the window; what was just clicked is no use
  // sitting a couple of thousand pixels below the fold.
  box.scrollIntoView({ block: 'center', behavior: 'smooth' });
  showWhy(layer, tags);
  document.getElementById('editDelete').addEventListener('click', () => {
    mapEdits.removed.push(layer.osmId);
    delete mapEdits.moved[layer.osmId];
    delete mapEdits.tags[layer.osmId];
    editLayer.removeLayer(layer);
    pickEdit(null);
    showEditCount();
    noteEdit('Removed. It will be gone the next time the map is generated.');
  });
  document.getElementById('editRetag').addEventListener('change', ev => {
    const entry = sketchPalette.find(e => e.id === ev.target.value);
    if (!entry) return;
    mapEdits.tags[layer.osmId] = { ...entry.tags };
    layer.osmTags = { ...entry.tags };
    showEditCount();
    pickEdit(layer);
    noteEdit(`Now a ${entry.label.toLowerCase()}.`);
  });
}

function addEditable(feature) {
  const geo = feature.geometry || {};
  const flip = ring => ring.map(([lon, lat]) => [lat, lon]);
  let layer = null;
  if (geo.type === 'Polygon') layer = L.polygon(flip(geo.coordinates[0] || []), EDIT_STYLE);
  else if (geo.type === 'LineString') layer = L.polyline(flip(geo.coordinates), EDIT_STYLE);
  if (!layer) return;
  layer.osmId = feature.id;
  layer.osmTags = (feature.properties || {}).tags || {};
  // What it looked like when it arrived, so only a shape that really moved is
  // recorded as moved.
  layer.wasAt = JSON.stringify(layer.toGeoJSON().geometry.coordinates);
  layer.on('click', ev => { L.DomEvent.stop(ev); pickEdit(layer); });
  editLayer.addLayer(layer);
}

async function loadEditable() {
  if (!openedMap) return;
  const b = map.getBounds();
  const q = new URLSearchParams({
    south: b.getSouth(), west: b.getWest(),
    north: b.getNorth(), east: b.getEast(),
  });
  noteEdit('Reading what this map was built from...');
  let data;
  try {
    const res = await fetch(`/api/features/${encodeURIComponent(openedMap.mapName)}?${q}`);
    data = await res.json();
    if (!res.ok) throw apiError(data, res);
  } catch (err) {
    noteEdit(err.message);
    return;
  }
  editLayer.clearLayers();
  pickEdit(null);
  mapEdits = { removed: [], moved: {}, tags: {}, ...(data.edits || {}) };
  mapEdits.removed = mapEdits.removed || [];
  const gone = new Set(mapEdits.removed);
  for (const f of data.features || []) {
    if (!gone.has(f.id)) addEditable(f);
  }
  document.getElementById('editShape').disabled = !editLayer.getLayers().length;
  showEditCount();
  // Say what is on the map, not what came down: the two differ by whatever
  // has already been taken out, and "5 features" over four shapes reads as a
  // bug in the counting.
  const hidden = (data.features || []).length - editLayer.getLayers().length;
  const capped = data.shown < data.total
    ? `${data.shown} of ${data.total} here - the biggest. Zoom in for the rest. ` : '';
  const already = hidden ? ` ${hidden} already removed.` : '';
  noteEdit(`${capped}${editLayer.getLayers().length} to edit.${already}`
    + ' Click one to remove it or say what it is.');
}

// Leaflet's own corner-dragging, over the whole layer at once.
function toggleShaping() {
  const btn = document.getElementById('editShape');
  if (editShaper) {
    editShaper.save();
    editShaper.disable();
    editShaper = null;
    btn.textContent = 'Move and reshape';
    // Only what really moved counts as moved.
    editLayer.eachLayer(layer => {
      const now = JSON.stringify(layer.toGeoJSON().geometry.coordinates);
      if (now !== layer.wasAt) {
        const geo = layer.toGeoJSON().geometry;
        const ring = geo.type === 'Polygon' ? geo.coordinates[0] : geo.coordinates;
        mapEdits.moved[layer.osmId] = ring.map(([lon, lat]) => [lat, lon]);
      }
    });
    showEditCount();
    noteEdit('Shapes saved. Press Save changes to keep them.');
    return;
  }
  pickEdit(null);
  editShaper = new L.EditToolbar.Edit(map, { featureGroup: editLayer });
  editShaper.enable();
  btn.textContent = 'Done moving';
  noteEdit('Drag the corners. Press Done moving when finished.');
}

document.getElementById('editLoad').addEventListener('click', loadEditable);
document.getElementById('editShape').addEventListener('click', toggleShaping);

document.getElementById('editSave').addEventListener('click', async () => {
  if (!openedMap) return;
  const btn = document.getElementById('editSave');
  btn.disabled = true;
  try {
    const res = await fetch(`/api/edits/${encodeURIComponent(openedMap.mapName)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(mapEdits),
    });
    const out = await res.json();
    if (!res.ok) throw apiError(out, res);
    noteEdit(`${out.changes} change${out.changes === 1 ? '' : 's'} saved. `
      + 'Generate map again to build them in.');
    fx.toast('ok', 'Changes saved',
             `${openedMap.mapName}: generate the map again to see them.`);
  } catch (err) {
    noteEdit(err.message);
  } finally {
    showEditCount();
  }
});

document.getElementById('editReset').addEventListener('click', async () => {
  if (!openedMap) return;
  mapEdits = { removed: [], moved: {}, tags: {} };
  await fetch(`/api/edits/${encodeURIComponent(openedMap.mapName)}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(mapEdits),
  }).catch(() => {});
  showEditCount();
  await loadEditable();
  noteEdit('Every change undone. The map is back to what was downloaded.');
});

// ---- the drawing board ------------------------------------------------------
//
// The editor's own screen: a blank sheet measured in metres, with no world
// under it, for laying out a town that does not exist anywhere. It is a
// Leaflet map with L.CRS.Simple and no tiles, which buys the panning, the
// zooming, the drawing and the corner-dragging that are already working on
// the world map, without pretending the sheet is a place.
//
// A point on the sheet is (x, y) in metres from the bottom-left corner, which
// is how somebody laying out a town thinks. Leaflet wants (lat, lng), so the
// two are swapped at the edges here and nowhere else; the server turns metres
// into the world when it builds (generator/sketch.py, design_to_drawn).
let boardMap = null;
let boardEd = null;             // the shared drawing editor (static/js/draw.js)
let boardSheet = null;          // the rectangle showing the edge of the sheet
let boardGrid = null;
// A picture laid over the sheet to draw on top of: a screenshot of a town
// plan, a sketch on paper, the map of somewhere that is not on OpenStreetMap.
// It is only ever something to trace, so it is not saved with the drawing -
// what gets built is what was drawn over it.
let boardTrace = null;
let boardFitted = false;        // whether the sheet has been framed on screen

const BOARD_GRID_M = 100;
// How near a point has to come to something before it is taken to mean it:
// the street of the map next door, or a corner of what is already drawn.
// Over about a tile and a half the map reads as joined up.
const BOARD_SNAP_M = 14;

let boardJoin = null;           // the map this sheet is drawn to join
let boardJoinLayers = null;     // its picture, its outline and its streets

function boardSize() {
  const w = parseFloat(document.getElementById('boardWidth').value) || 900;
  const h = parseFloat(document.getElementById('boardHeight').value) || 900;
  return { w: Math.min(Math.max(w, 100), 40000), h: Math.min(Math.max(h, 100), 40000) };
}

function boardNote(text) {
  const box = document.getElementById('boardNote');
  if (box) box.textContent = text || '';
}

// The game stores a map in cells of 300 tiles and nothing finer: two maps are
// neighbours on a cell boundary or not at all (knoxbuild/world.py, CELL_SIZE).
// A sheet that is not whole cells is built with empty ground round it - the
// drawing is centred in what the cells leave - so its streets stop short of
// the edge and nothing of the map next door lines up with them.
const BOARD_CELL_TILES = 300;

function boardCellMetres() {
  return BOARD_CELL_TILES * readScale();
}

// The sheet in cells, and whether it comes out exactly: {x, y, exact}.
function boardCells() {
  const { w, h } = boardSize();
  const cell = boardCellMetres();
  const across = w / cell;
  const down = h / cell;
  return { x: Math.ceil(across - 1e-6), y: Math.ceil(down - 1e-6),
           exact: Math.abs(across - Math.round(across)) < 1e-6
                  && Math.abs(down - Math.round(down)) < 1e-6 };
}

function boardShowCount() {
  const n = boardEd ? boardEd.count : 0;
  const badge = document.getElementById('boardCount');
  const { w, h } = boardSize();
  const cells = boardCells();
  const fit = document.getElementById('boardFitCells');
  if (fit) fit.hidden = cells.exact;
  if (badge) {
    badge.textContent = `${w} × ${h} m · ${n} thing${n === 1 ? '' : 's'} · `
      + (cells.exact ? `${cells.x} × ${cells.y} cells`
                     : `built as ${cells.x} × ${cells.y} cells with empty `
                       + 'ground round it');
  }
}

// The sheet's edge and a grid every hundred metres, so a street can be put
// somewhere on purpose rather than somewhere about right.
function boardDrawSheet() {
  const { w, h } = boardSize();
  if (boardSheet) boardMap.removeLayer(boardSheet);
  if (boardGrid) boardMap.removeLayer(boardGrid);
  // Both go in the pane under the drawing rather than being shuffled there
  // afterwards: bringToBack() reaches for the renderer's container, which on
  // a map that has only just been given a size does not exist yet, and it
  // threw before a single line of the sheet was drawn.
  boardSheet = L.rectangle([[0, 0], [h, w]], {
    pane: 'tilePane', color: '#3d8bfd', weight: 2, fill: true,
    fillColor: '#0b0d0b', fillOpacity: 1, interactive: false }).addTo(boardMap);
  const lines = [];
  for (let x = BOARD_GRID_M; x < w; x += BOARD_GRID_M) lines.push([[0, x], [h, x]]);
  for (let y = BOARD_GRID_M; y < h; y += BOARD_GRID_M) lines.push([[y, 0], [y, w]]);
  boardGrid = L.polyline(lines, { pane: 'boardGridPane', color: '#2b3326',
                                  weight: 1, interactive: false }).addTo(boardMap);
  // The picture being traced covers the sheet, so it is stretched to it
  // whenever the sheet changes size.
  if (boardTrace) boardTrace.setBounds([[0, 0], [h, w]]);
  boardMap.setMaxBounds([[-h * 0.1, -w * 0.1], [h * 1.1, w * 1.1]]);
  boardShowCount();
}

function boardFit() {
  const { w, h } = boardSize();
  // Not on the next animation frame: those do not come at all while the
  // window is behind another one, and the board would open unfitted - a map
  // the browser still thinks is nothing wide fits at the closest zoom there
  // is, leaving the sheet thousands of pixels off every edge. A timeout runs
  // either way, and the resize below catches the case where the panel is laid
  // out later still.
  setTimeout(() => {
    boardMap.invalidateSize();
    if (boardMap.getSize().x > 0) {
      boardMap.fitBounds([[0, 0], [h, w]], { padding: [24, 24] });
    }
  }, 0);
}

// ---- the map next door ------------------------------------------------------
// A sheet is nowhere until it is put somewhere, and a street drawn on one
// stops dead at the edge. Pick a map already built and the sheet is drawn
// against it: that map beside this one at the right size, and the streets
// that reach the border they share marked on this sheet's own edge. Draw a
// road to one of those and it snaps onto it, and the built map is put beside
// its neighbour in the world, so the two really do join.

function boardJoinSide() {
  return document.getElementById('boardJoinSide').value || 'E';
}

// Where the neighbour's sheet lies, in the board's own metres: beside this
// one, corners lined up on the side they share.
function boardNeighbourBounds(data) {
  const { w, h } = boardSize();
  const side = boardJoinSide();
  const nw = data.widthM || 0;
  const nh = data.heightM || 0;
  if (side === 'E') return [[h - nh, -nw], [h, 0]];
  if (side === 'W') return [[h - nh, w], [h, w + nw]];
  if (side === 'N') return [[-nh, 0], [0, nw]];
  return [[h, 0], [h + nh, nw]];          // this sheet is south of it
}

function boardClearJoin() {
  if (boardJoinLayers) boardMap.removeLayer(boardJoinLayers);
  boardJoinLayers = null;
}

function boardDrawJoin() {
  boardClearJoin();
  if (!boardJoin) return;
  const group = L.layerGroup().addTo(boardMap);
  const bounds = boardNeighbourBounds(boardJoin);
  if (boardJoin.preview) {
    L.imageOverlay(boardJoin.preview, bounds,
                   { pane: 'boardTracePane', opacity: 0.75, interactive: false })
      .addTo(group);
  }
  L.rectangle(bounds, { color: '#6fa8dc', weight: 1, dashArray: '6,4',
                        fill: !boardJoin.preview, fillColor: '#16202a',
                        fillOpacity: 0.5, interactive: false }).addTo(group);
  for (const join of boardJoin.joins || []) {
    L.circleMarker([join.y, join.x], {
      radius: 5, color: '#ffd37a', weight: 2, fillColor: '#ffd37a',
      fillOpacity: 0.9, interactive: false,
    }).addTo(group).bindTooltip(`a street of ${escapeHtml(boardJoin.name)} `
      + `arrives here, ${join.width} m wide`, { sticky: true });
  }
  boardJoinLayers = group;
}

async function boardLoadJoin() {
  const name = document.getElementById('boardJoin').value;
  const note = document.getElementById('boardJoinNote');
  document.getElementById('boardMatchEdge').disabled = !name;
  if (!name) {
    boardJoin = null;
    boardClearJoin();
    note.textContent = 'A map of its own, with nothing beside it.';
    return;
  }
  const { w, h } = boardSize();
  try {
    const res = await fetch(`/api/board/join/${encodeURIComponent(name)}`
      + `?side=${boardJoinSide()}&w=${w}&h=${h}`);
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
    boardJoin = data;
    boardDrawJoin();
    // A sheet that is not whole cells is built with empty ground round it and
    // the drawing centred in that, so every street it marks here ends up
    // short of the border - the one thing a joined sheet must not do.
    const padded = !boardCells().exact
      ? ' This sheet is not whole cells, so it is built with empty ground '
        + 'round it and its streets stop short of the border: use Fit to '
        + 'cells before building.'
      : '';
    const n = (data.joins || []).length;
    // A map made before KnoxMap kept a picture of its roads cannot say where
    // its streets reach the border, which is not the same as having none
    // there - saying so sent people looking for a street that was drawn.
    note.textContent = (n
      ? `${n} street${n === 1 ? '' : 's'} of ${name} reach${n === 1 ? 'es' : ''} `
        + 'this sheet. Draw a road to one and it joins up.'
      : data.roadsKnown === false
        ? `${name} was made before KnoxMap kept a picture of a map's roads, so `
          + 'it cannot say where its streets reach this sheet. Generate that '
          + 'map again to put them on the edge. The sheet still goes beside it.'
        : `${name} has no street on that side. The sheet still goes beside it.`)
      + padded;
  } catch (err) {
    boardJoin = null;
    boardClearJoin();
    note.textContent = err.message;
  }
}

// The streets of the map next door, which a road drawn to the border should
// meet. The editor adds the corners of what is already on the sheet.
function boardJoinPoints() {
  return ((boardJoin && boardJoin.joins) || []).map(j => [j.y, j.x]);
}

function boardPaletteInto(box) {
  box.innerHTML = paletteMarkup();
  runListSearch(box.id);
}

// What is on the sheet, in metres, as the server stores and reads it.
function boardDesign() {
  const { w, h } = boardSize();
  const features = [];
  boardEd.each((layer, kind) => {
    const geo = layer.toGeoJSON().geometry;
    let ring;
    if (geo.type === 'Polygon') ring = geo.coordinates[0];
    else if (geo.type === 'LineString') ring = geo.coordinates;
    else if (geo.type === 'Point') ring = [geo.coordinates];
    else return;
    // GeoJSON from a CRS.Simple map is [lng, lat] = [x, y] already. Kept on
    // the sheet: it can be drawn past the edge, and a road at x = 1342 on a
    // 900 m sheet is simply off the map, which is not what somebody dragging
    // a street to the edge of the page meant.
    const clamp = (v, hi) => Math.min(Math.max(v, 0), hi);
    features.push({ kind,
                    points: ring.map(([x, y]) => [clamp(x, w), clamp(y, h)]) });
  });
  return { width_m: w, height_m: h,
           anchor: { lat: 0.0, lon: 0.0 }, features };
}

function boardLoadDesign(design) {
  if (!design) { boardEd.replace([]); boardShowCount(); return; }
  document.getElementById('boardWidth').value = design.width_m || 900;
  document.getElementById('boardHeight').value = design.height_m || 900;
  boardDrawSheet();
  const items = [];
  for (const f of design.features || []) {
    const entry = sketchPalette.find(e => e.id === f.kind);
    if (!entry) continue;
    const pts = (f.points || []).map(([x, y]) => [y, x]);   // back to (lat, lng)
    let layer = null;
    if (entry.geometry === 'area' && pts.length >= 3) layer = L.polygon(pts);
    else if (entry.geometry === 'line' && pts.length >= 2) layer = L.polyline(pts);
    else if (entry.geometry === 'point' && pts.length) layer = L.marker(pts[0]);
    if (layer) items.push({ kind: f.kind, layer });
  }
  boardEd.replace(items);
  boardFit();
  boardShowCount();
}

function boardOpen(mapName) {
  const panel = document.getElementById('board');
  panel.hidden = false;
  if (!boardMap) {
    boardMap = L.map('boardMap', {
      crs: L.CRS.Simple, minZoom: -6, maxZoom: 4, zoomControl: true,
      attributionControl: false });
    // Three layers under the drawing: the sheet, then the picture being
    // traced, then the grid over both so its hundred-metre squares are still
    // readable against the picture.
    boardMap.createPane('boardTracePane').style.zIndex = 210;
    boardMap.createPane('boardGridPane').style.zIndex = 220;
    for (const name of ['boardTracePane', 'boardGridPane']) {
      boardMap.getPane(name).style.pointerEvents = 'none';
    }
    // A Leaflet map needs somewhere to be looking before anything can be put
    // on it or measured against it; fitting the sheet refines this a moment
    // later, once the panel it lives in has a size.
    boardMap.setView([450, 450], 0);
    let refreshBoardTools = () => {};
    boardEd = KnoxDraw.create(boardMap, {
      style: kind => sketchStyle(kind),
      label: kind => sketchLabel(kind),
      note: boardNote,
      pickedBox: document.getElementById('boardPicked'),
      palette: document.getElementById('boardPalette'),
      active: () => !document.getElementById('board').hidden,
      snapOn: () => document.getElementById('boardSnap').checked,
      snapDist: BOARD_SNAP_M,
      snapExtra: boardJoinPoints,
      onChange: () => { boardShowCount(); refreshBoardTools(); },
    });
    refreshBoardTools = KnoxDraw.toolbar(document.getElementById('boardTools'), boardEd);
    // The first size the map gets may arrive after it was opened, if the
    // window was behind another one at the time.
    boardMap.on('resize', () => {
      if (!boardFitted && boardMap.getSize().x > 0) {
        boardFitted = true;
        boardFit();
      }
    });
    boardPaletteInto(document.getElementById('boardPalette'));
    for (const id of ['boardWidth', 'boardHeight']) {
      document.getElementById(id).addEventListener('change', () => {
        boardDrawSheet();
        boardFit();
        boardLoadJoin();           // the sheet moved under its neighbour
      });
    }
    // Which map this sheet is drawn against, and which way round.
    for (const id of ['boardJoin', 'boardJoinSide']) {
      document.getElementById(id).addEventListener('change', boardLoadJoin);
    }
  }
  boardMap.invalidateSize();     // it was created inside a hidden panel
  boardDrawSheet();
  boardFitted = boardMap.getSize().x > 0;
  boardFit();
  if (mapName) document.getElementById('boardName').value = mapName;
  boardFillJoins(mapName);
  boardNote('Pick a tool and draw. Nothing is downloaded: this is your own map.');
}

document.getElementById('boardOpen').addEventListener('click', async () => {
  const name = openedMap && openedMap.mapName;
  boardOpen(name);
  // A map that was drawn on a sheet before opens on that sheet again.
  if (name) {
    try {
      const res = await fetch(`/api/design/${encodeURIComponent(name)}`);
      if (res.ok) {
        boardLoadDesign(await res.json());
        boardNote(`${name} as it was drawn. Change it and build it again.`);
      }
    } catch { /* a map with no sheet simply opens an empty one */ }
  }
});

// Every map already built is somewhere this sheet could go next to - except
// the one being drawn, which cannot be its own neighbour.
async function boardFillJoins(mine) {
  const box = document.getElementById('boardJoin');
  const was = box.value;
  try {
    const data = await (await fetch('/api/maps')).json();
    const names = (data.maps || []).map(m => m.mapName || m.name)
      .filter(n => n && n !== mine);
    box.innerHTML = ['<option value="">nothing - a map of its own</option>']
      .concat(names.map(n =>
        `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`)).join('');
    if (names.includes(was)) box.value = was;
  } catch {
    /* no maps to join: the sheet is simply a map of its own */
  }
  boardLoadJoin();
}

document.getElementById('boardFitCells').addEventListener('click', () => {
  // Up to the next whole cell, never down: rounding down would cut off
  // whatever is drawn out there.
  const cell = boardCellMetres();
  const cells = boardCells();
  document.getElementById('boardWidth').value = Math.round(cells.x * cell);
  document.getElementById('boardHeight').value = Math.round(cells.y * cell);
  boardDrawSheet();
  boardFit();
  boardLoadJoin();
  boardNote(`Sheet is ${cells.x} × ${cells.y} whole cells now, so its edges `
    + 'are the edges of the built map and a street can run right up to one.');
});

document.getElementById('boardMatchEdge').addEventListener('click', () => {
  // The sheet made as long as the border it shares, so nothing of the
  // neighbour is left looking out onto nothing.
  if (!boardJoin) return;
  const side = boardJoinSide();
  const across = side === 'E' || side === 'W' ? 'boardHeight' : 'boardWidth';
  const metres = side === 'E' || side === 'W' ? boardJoin.heightM : boardJoin.widthM;
  if (!metres) return;
  document.getElementById(across).value = Math.round(metres);
  boardDrawSheet();
  boardFit();
  boardLoadJoin();
  boardNote(`Sheet matched to ${boardJoin.name}: ${Math.round(metres)} m along `
    + 'the side they share.');
});

document.getElementById('boardClose').addEventListener('click', () => {
  boardEd.stop();
  if (boardEd.editing) boardEd.setEditing(false);
  document.getElementById('board').hidden = true;
});

// ---- a picture to trace ------------------------------------------------------
// Asked for by somebody drawing a town that only exists on paper: the sheet
// has no world map under it, which is the point of it, and also means there
// is nothing to go by. A picture laid under the drawing gives them something
// to follow. It stays in the window - nothing is uploaded and nothing is
// saved with the sheet - because what is built is what was drawn over it.
const BOARD_TRACE_MAX_MB = 12;

function boardTraceShow(on) {
  document.getElementById('boardTraceFade').hidden = !on;
  document.getElementById('boardTraceOff').hidden = !on;
}

document.getElementById('boardTrace').addEventListener('click', () =>
  document.getElementById('boardTraceFile').click());

document.getElementById('boardTraceFile').addEventListener('change', ev => {
  const file = ev.target.files[0];
  ev.target.value = '';
  if (!file) return;
  if (file.size > BOARD_TRACE_MAX_MB * 1e6) {
    boardNote(`That picture is ${(file.size / 1e6).toFixed(0)} MB. `
      + `Something under ${BOARD_TRACE_MAX_MB} MB is plenty to trace.`);
    return;
  }
  const reader = new FileReader();
  reader.onerror = () => boardNote('That picture could not be read.');
  reader.onload = () => {
    const { w, h } = boardSize();
    if (boardTrace) boardMap.removeLayer(boardTrace);
    boardTrace = L.imageOverlay(reader.result, [[0, 0], [h, w]], {
      pane: 'boardTracePane', interactive: false,
      opacity: parseFloat(document.getElementById('boardTraceOpacity').value),
    }).addTo(boardMap);
    boardTraceShow(true);
    boardNote('Picture laid over the sheet. Draw on top of it; it is not part '
      + 'of the map and is not saved with the sheet.');
  };
  reader.readAsDataURL(file);
});

document.getElementById('boardTraceOpacity').addEventListener('input', ev => {
  if (boardTrace) boardTrace.setOpacity(parseFloat(ev.target.value));
});

document.getElementById('boardTraceOff').addEventListener('click', () => {
  if (boardTrace) boardMap.removeLayer(boardTrace);
  boardTrace = null;
  boardTraceShow(false);
  boardNote('Picture removed.');
});

function boardMapName() {
  const typed = document.getElementById('boardName').value.trim();
  const clean = typed.replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '');
  return clean || `drawn_${Date.now()}`;
}

document.getElementById('boardSave').addEventListener('click', async () => {
  const name = boardMapName();
  document.getElementById('boardName').value = name;
  try {
    const res = await fetch(`/api/design/${encodeURIComponent(name)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(boardDesign()),
    });
    const out = await res.json();
    if (!res.ok) throw apiError(out, res);
    boardNote(`Saved as ${name}: ${out.usable} of ${out.saved} will be built.`);
  } catch (err) {
    boardNote(err.message);
  }
});

document.getElementById('boardBuild').addEventListener('click', async () => {
  const btn = document.getElementById('boardBuild');
  const name = boardMapName();
  document.getElementById('boardName').value = name;
  const design = boardDesign();
  if (!design.features.length) {
    boardNote('There is nothing on the sheet yet.');
    return;
  }
  btn.disabled = true;
  boardNote('Building…');
  startProgress(name);
  try {
    const res = await fetch('/api/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      // A sheet is already square with the tile grid - that is what drawing
      // on a grid means - so there is no street angle to find and turning the
      // map only costs size: a 900 m sheet came out 1200 tiles instead of
      // 900, because a square turned needs the circle round it. Somebody who
      // draws their streets at an angle meant them at that angle.
      body: JSON.stringify({ mapName: name, design,
                             metersPerTile: readScale(),
                             settings: { ...readSettings(), align_streets: 0,
                                         rotate_degrees: 0 } }),
    });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
    let note = `${name} built: ${data.width} × ${data.height} tiles.`;
    const beside = document.getElementById('boardJoin').value;
    if (beside) {
      // Drawn against a map, so it is put beside that map rather than
      // wherever there happened to be room.
      try {
        const put = await fetch('/api/board/place-beside', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ map: name, neighbour: beside,
                                 side: boardJoinSide() }) });
        const where = await put.json();
        if (!put.ok) throw apiError(where, put);
        note += ` Put beside ${beside}, at cell ${where.map.x},${where.map.y}.`;
      } catch (err) {
        note += ` It could not be put beside ${beside}: ${err.message}`;
      }
    }
    boardNote(note);
    fx.toast('ok', 'Map built', `${name}: ${data.width} × ${data.height} tiles.`);
    document.getElementById('board').hidden = true;
    renderResults(data);
    rememberMap({ mapName: name, bbox: data.bbox || null,
                  metersPerTile: readScale(), shape: null,
                  settings: data.settings || readSettings() });
    loadMaps();
  } catch (err) {
    boardNote(err.message);
  } finally {
    btn.disabled = false;
  }
});

// ---- zones with settings of their own ---------------------------------------
//
// A part of the map, drawn, with a few settings written on it: a town centre
// that is taller and thick with zombies, an estate all in one brick. Anything
// outside every zone is built to the map's own settings, and the smallest zone
// containing a building is the one that answers (knoxbuild/zones.py).
//
// Which settings a zone may set comes from the server, like the palette and
// the knobs themselves: a dial the window offers that the generator does not
// read is a dial that does nothing.
const zoneLayer = new L.FeatureGroup().addTo(map);
let zoneMeta = null;            // {settings: [...], styles: [...]}
// [{name, ring, settings, wall_style, presets, layer}], always in the order of
// the shapes on the map: the editor (static/js/draw.js) owns the shapes, and
// each carries its zone as `layer.kdMeta`, so undo brings back a zone's
// settings with its outline. zoneList is rebuilt from them (zonesSync).
let zoneList = [];
let zonePicked = -1;

const ZONE_STYLE = { color: '#8f7ad6', weight: 2, dashArray: '5,4', fillOpacity: 0.12 };
const ZONE_PICKED = { color: '#c9a8ff', weight: 3, dashArray: null, fillOpacity: 0.25 };
// Every zone is drawn in the same purple, which is right - a zone is a zone -
// and leaves four of them on one town impossible to tell apart. The one under
// the pointer lights up and says which it is.
const ZONE_HOVER = { color: '#efe4ff', weight: 3, dashArray: null, fillOpacity: 0.32 };

// How a zone is drawn now: under the pointer, picked, or neither.
function zoneDress(zone, hover) {
  if (!zone || !zone.layer) return;
  zone.layer.setStyle(hover ? ZONE_HOVER
    : zoneList[zonePicked] === zone ? ZONE_PICKED : ZONE_STYLE);
}

// What it says when the pointer is on it: its name, and what it does
// differently - which is the thing being looked for when a map has several.
function zoneTip(zone, i) {
  return `<b>${escapeHtml(zone.name || 'Zone ' + (i + 1))}</b>`
    + `<br><span class="zone-tip-what">${escapeHtml(zoneSummary(zone))}</span>`;
}

let zonePresets = [];      // the hand-built buildings a zone can draw from

async function loadZoneMeta() {
  if (zoneMeta) return zoneMeta;
  try {
    zoneMeta = await (await fetch('/api/zones')).json();
  } catch {
    zoneMeta = { settings: [], styles: [] };
  }
  try {
    zonePresets = (await (await fetch('/api/presets/buildings')).json()).presets || [];
  } catch {
    zonePresets = [];
  }
  return zoneMeta;
}

function zoneNote(text) {
  const box = document.getElementById('zoneNote');
  if (box) box.textContent = text || '';
}

let zoneCommitTimer = null;
function zoneDirty(on) {
  document.getElementById('zoneSave').disabled = !on;
  // A name or a setting changed: that is an undoable step too, but only once
  // the typing stops rather than once a keystroke.
  if (on) {
    clearTimeout(zoneCommitTimer);
    zoneCommitTimer = setTimeout(() => zoneEd.commit(), 600);
  }
}

function showZoneCount() {
  const badge = document.getElementById('zoneCount');
  if (badge) badge.textContent = zoneList.length ? `(${zoneList.length})` : '';
}

// How many of its own settings a zone carries, for the list.
function zoneSummary(zone) {
  const n = Object.keys(zone.settings || {}).length;
  const bits = [];
  if (zone.presets && zone.presets.length) {
    bits.push(`${zone.presets.length} hand-built`);
  }
  if (zone.wall_style) bits.push(zone.wall_style);
  bits.push(n ? `${n} setting${n === 1 ? '' : 's'}` : 'nothing set yet');
  return bits.join(' · ');
}

// Each zone a foldable item: its heading (name, what is different, Remove)
// and, when open, its settings - the one zone editor, moved into it. The
// list is redrawn for every keystroke in a zone's name, so a row that is
// already there is updated in place: rebuilding it would take the editor,
// and the box being typed in, out of the page.
// The zones that set something of their own, said over the settings in
// Properties: they are what those settings are not, in parts of the map.
// Opened, it lists each one and what it sets; a zone there opens it in the
// Zones tab.
function zoneSets(zone) {
  const bits = Object.entries(zone.settings || {}).map(([k, v]) => {
    const name = SETTING_LABELS[k] ? SETTING_LABELS[k][0] : k;
    const meta = (zoneMeta && zoneMeta.settings || []).find(s => s.id === k);
    return `${name} ${meta && zoneSwitchable(meta) ? (v ? 'On' : 'Off') : v}`;
  });
  if (zone.wall_style) bits.push(`Walls ${zone.wall_style}`);
  if ((zone.presets || []).length) bits.push(`${zone.presets.length} hand-built`);
  return bits;
}
function showZonesNotice() {
  const note = document.getElementById('zonesNotice');
  if (!note) return;
  const setting = zoneList.map((z, i) => [z, i]).filter(([z]) => zoneSets(z).length);
  note.hidden = !setting.length;
  note.querySelector('.zones-notice-what').textContent = setting.length === 1
    ? 'One zone changes settings in part of the map'
    : `${setting.length} zones change settings in parts of the map`;
  note.querySelector('.zones-notice-list').innerHTML = setting.map(([z, i]) =>
    `<li><button type="button" data-zone-open="${i}" title="Open it under Tools, Zones">
       <b>${escapeHtml(z.name || 'Zone ' + (i + 1))}</b>
       <span>${escapeHtml(zoneSets(z).join(' · '))}</span></button></li>`).join('');
}
document.getElementById('zonesNotice').addEventListener('click', ev => {
  const open = ev.target.closest('[data-zone-open]');
  if (!open) return;
  document.querySelector('.ws-tool-tabs [data-tool="zone"]')?.click();
  zonePick(parseInt(open.dataset.zoneOpen, 10));
});

function drawZoneList() {
  showZonesNotice();
  const box = document.getElementById('zoneList');
  const editor = document.getElementById('zoneEditor');
  if (box.children.length !== zoneList.length) {
    box.after(editor);                       // parked while the rows are rebuilt
    box.innerHTML = zoneList.map((z, i) => `<li data-i="${i}" class="zone-item">
        <div class="zone-head" role="button" tabindex="0" aria-expanded="false">
          <span class="zone-caret" aria-hidden="true"></span>
          <span class="zone-name"></span><span class="zone-what"></span>
          <button type="button" data-drop="${i}">Remove</button></div></li>`).join('');
  }
  zoneList.forEach((z, i) => {
    const li = box.children[i];
    // A zone that sets anything is a change from the map, so yellow like one.
    li.classList.toggle('is-changed', zoneSets(z).length > 0);
    li.querySelector('.zone-name').textContent = z.name || 'Zone ' + (i + 1);
    li.querySelector('.zone-what').textContent = zoneSummary(z);
    li.classList.toggle('on', i === zonePicked);
    li.querySelector('.zone-head').setAttribute('aria-expanded', String(i === zonePicked));
  });
  const open = box.children[zonePicked];
  if (open && editor.parentElement !== open) open.appendChild(editor);
  else if (!open && editor.parentElement !== box.parentElement) box.after(editor);
  // The list is redrawn for every change a zone has in it, so this is where
  // what the map says about it is kept up to date.
  zoneList.forEach((z, i) => {
    if (z.layer) z.layer.setTooltipContent(zoneTip(z, i));
  });
  showZoneCount();
}

function zonePick(i) {
  zonePicked = i;
  for (const z of zoneList) if (z.layer) z.layer.setStyle(ZONE_STYLE);
  const zone = zoneList[i];
  if (zone && zone.layer) zone.layer.setStyle(ZONE_PICKED);
  const layer = zone && zone.layer ? zone.layer : null;
  if (zoneEd.picked !== layer) zoneEd.pick(layer);
  drawZoneList();
  drawZoneEditor();
}

// What the map itself is set to, in Properties: what a zone's empty box means.
function zoneMapValue(setting) {
  const el = document.querySelector(`#advanced-body [data-key="${setting.id}"]`);
  if (!el) return setting.default;
  if (el.type === 'checkbox') return el.checked ? 1 : 0;
  return el.value.trim() === '' ? setting.default : el.value;
}
function zoneMapWord(setting) {
  return Number(zoneMapValue(setting)) ? 'As the map is (On)' : 'As the map is (Off)';
}
// Properties changed: the open zone's empty boxes show the new values.
function refreshZonePlaceholders() {
  if (!zoneMeta) return;
  for (const s of zoneMeta.settings) {
    const el = document.querySelector(`#zoneEditor [data-zone-key="${s.id}"]`);
    if (!el) continue;
    if (el.tagName === 'SELECT') el.options[0].textContent = zoneMapWord(s);
    else el.placeholder = zoneMapValue(s);
  }
}
for (const ev of ['input', 'change']) {
  document.getElementById('advanced-body').addEventListener(ev, refreshZonePlaceholders);
}
document.getElementById('preset').addEventListener('change', () => setTimeout(refreshZonePlaceholders, 0));

// A zone setting that is only ever 0 or 1: it gets on, off, or nothing at
// all, rather than a box to type 1 into.
function zoneSwitchable(setting) {
  return setting.int && setting.min === 0 && setting.max === 1;
}

// In the open zone, what it sets is yellow: the setting's name and its box,
// its walls, the hand-built buildings ticked - as a setting moved off its
// default is in Properties.
// A zone setting's name with an (i), and the description it shows - the
// same markup and behaviour as a setting in Properties (wireSettingInfo).
function zoneInfoName(name, about) {
  return `<span class="zone-label">${escapeHtml(name)}${about
    ? `<button type="button" class="setting-info" aria-label="About ${escapeHtml(name)}"
        aria-expanded="false">i</button>` : ''}</span>`;
}
function zoneInfoHint(about) {
  return about ? `<span class="setting-hint" role="tooltip">${escapeHtml(about)}</span>` : '';
}

function markZoneEditor() {
  const box = document.getElementById('zoneEditor');
  for (const row of box.querySelectorAll('label, .zone-setting')) {
    const field = row.querySelector('[data-zone-key], #zoneStyle, [data-building-preset]');
    if (!field) continue;
    const set = field.matches('[data-building-preset]') ? field.checked
      : field.matches('#zoneStyle') ? !!field.value : field.classList.contains('zone-set');
    row.classList.toggle('is-changed', set);
  }
}
document.getElementById('zoneEditor').addEventListener('input', () => setTimeout(markZoneEditor, 0));
document.getElementById('zoneEditor').addEventListener('change', () => setTimeout(markZoneEditor, 0));

function drawZoneEditor() {
  const box = document.getElementById('zoneEditor');
  const zone = zoneList[zonePicked];
  if (!zone || !zoneMeta) {
    box.hidden = true;
    box.innerHTML = '';
    return;
  }
  box.hidden = false;
  const styles = ['<option value="">(whatever the map uses)</option>'].concat(
    zoneMeta.styles.map(s =>
      `<option value="${s}"${s === zone.wall_style ? ' selected' : ''}>${escapeHtml(s)}</option>`));
  // Hand-built buildings this zone stamps instead of generated ones. A plot
  // nothing fits still gets a generated building, so ticking one is never a
  // way to end up with a hole in the town.
  const chosen = new Set(zone.presets || []);
  const presetBox = zonePresets.length
    ? `<p class="hint">Hand-built buildings to use here. A plot none of them
         fits gets a generated building as usual.</p>
       ${zonePresets.map(p => `<label class="zone-preset zone-row">
         <input type="checkbox" data-building-preset="${escapeHtml(p.name)}"
           ${chosen.has(p.name) ? 'checked' : ''}>
         <span>${escapeHtml(p.name)}</span>
         <small>${p.width}×${p.height}, ${p.storeys} storey${p.storeys === 1 ? '' : 's'}</small>
       </label>`).join('')}`
    : `<p class="hint">No hand-built buildings yet. Put a BuildingEd
         <code>.tbx</code> in <code>presets/buildings</code> beside KnoxMap and
         it can be used here.</p>`;
  box.innerHTML = `
    <label><span>Name</span>
      <input type="text" id="zoneName" value="${escapeHtml(zone.name || '')}"></label>
    <div class="zone-row zone-setting">${zoneInfoName('Walls',
        'Every building made in this zone gets these walls. Left as it is, the map\'s own choice is used.')}
      <select id="zoneStyle" aria-label="Walls">${styles.join('')}</select>${zoneInfoHint(
        'Every building made in this zone gets these walls. Left as it is, the map\'s own choice is used.')}</div>
    ${presetBox}
    <p class="hint">Leave a box empty and the map's own setting is used there.</p>
    ${zoneMeta.settings.map(s => `<div class="zone-row zone-setting"
      data-find="${escapeHtml(s.id)}">${zoneInfoName(SETTING_LABELS[s.id]
        ? SETTING_LABELS[s.id][0] : s.id, SETTING_LABELS[s.id] && SETTING_LABELS[s.id][1])}
      ${zoneSwitchable(s)
        // On or off, and a third state the number box could not say: leave it
        // to the map. A zone sets what is different about it, not everything.
        ? `<select data-zone-key="${s.id}" aria-label="${escapeHtml(SETTING_LABELS[s.id] ? SETTING_LABELS[s.id][0] : s.id)}"
             class="${zone.settings[s.id] !== undefined ? 'zone-set' : ''}">
           <option value="">${zoneMapWord(s)}</option>
           <option value="1"${zone.settings[s.id] === 1 ? ' selected' : ''}>On</option>
           <option value="0"${zone.settings[s.id] === 0 ? ' selected' : ''}>Off</option>
           </select>`
        : `<input type="number" data-zone-key="${s.id}" aria-label="${escapeHtml(SETTING_LABELS[s.id] ? SETTING_LABELS[s.id][0] : s.id)}" min="${s.min}" max="${s.max}"
             step="${s.int ? 1 : 0.05}" placeholder="${zoneMapValue(s)}"
             class="${zone.settings[s.id] !== undefined ? 'zone-set' : ''}"
             value="${zone.settings[s.id] !== undefined ? zone.settings[s.id] : ''}">`}
      ${zoneInfoHint(SETTING_LABELS[s.id] && SETTING_LABELS[s.id][1])}</div>`).join('')}`;
  // Each setting's description behind its (i), as in Properties.
  box.querySelectorAll('.zone-setting').forEach(wireSettingInfo);

  document.getElementById('zoneName').addEventListener('input', ev => {
    zone.name = ev.target.value; zoneDirty(true); drawZoneList();
  });
  document.getElementById('zoneStyle').addEventListener('change', ev => {
    zone.wall_style = ev.target.value || undefined;
    zoneDirty(true); drawZoneList();
  });
  for (const tick of box.querySelectorAll('[data-building-preset]')) {
    tick.addEventListener('change', ev => {
      const name = ev.target.dataset.buildingPreset;
      const have = new Set(zone.presets || []);
      if (ev.target.checked) have.add(name); else have.delete(name);
      zone.presets = [...have];
      if (!zone.presets.length) delete zone.presets;
      zoneDirty(true);
      drawZoneList();
    });
  }
  markZoneEditor();
  for (const input of box.querySelectorAll('[data-zone-key]')) {
    input.addEventListener(input.tagName === 'SELECT' ? 'change' : 'input', ev => {
      const key = ev.target.dataset.zoneKey;
      if (ev.target.value.trim() === '') delete zone.settings[key];
      else zone.settings[key] = parseFloat(ev.target.value);
      ev.target.classList.toggle('zone-set', zone.settings[key] !== undefined);
      zoneDirty(true);
      drawZoneList();
    });
  }
}

// The editor owns the outline; this is what the page adds to it. The zone is
// kept off the data the editor snapshots (its layer would be a loop).
const zoneEd = KnoxDraw.create(map, {
  group: zoneLayer,
  style: () => ZONE_STYLE,
  pickedStyle: ZONE_PICKED,
  label: () => 'Zone',
  note: text => zoneNote(text),
  // Sticky, so where zones overlap the label follows the pointer and names
  // the one it is actually over rather than the one it started on.
  tooltip: layer => zoneTip(layer.kdMeta || {}, zoneList.indexOf(layer.kdMeta)),
  tooltipOptions: { sticky: true, className: 'zone-tip' },
  newMeta: () => ({ name: `Zone ${zoneList.length + 1}`, settings: {} }),
  cloneMeta: m => Object.assign(m, { name: `${m.name || 'Zone'} copy` }),
  active: () => document.getElementById('zonesPanel').open
                && document.getElementById('board').hidden,
  listen: false,
  onStart: () => { sketchEd.stop(); disarmAreaToolbar(); },
  onAttach: layer => {
    layer.on('mouseover', () => zoneDress(layer.kdMeta, true));
    layer.on('mouseout', () => zoneDress(layer.kdMeta, false));
  },
  onPick: layer => {
    const i = layer ? zoneList.indexOf(layer.kdMeta) : -1;
    if (i !== zonePicked) zonePick(i);
  },
  onClaimed: layer => {
    zonePick(zoneList.indexOf(layer.kdMeta));
    zoneNote('Zone drawn. Set what is different about it, then save.');
  },
  onChange: state => {
    refreshZoneTools();
    if (state.rev === zoneRev) return;
    zoneRev = state.rev;
    zonesSync();
    if (!zoneLoading) zoneDirty(true);
  },
});
let refreshZoneTools = () => {};
let zoneRev = 0;
let zoneLoading = false;
refreshZoneTools = KnoxDraw.toolbar(document.getElementById('zoneTools'), zoneEd);

// zoneList from the shapes, after any change to them.
function zonesSync() {
  const was = zoneList[zonePicked];
  zoneList = [];
  zoneEd.each(layer => {
    const zone = layer.kdMeta;
    Object.defineProperty(zone, 'layer', { value: layer, writable: true,
                                           configurable: true, enumerable: false });
    // Off the enumerable data too: the editor snapshots it for undo, and the
    // outline is already there.
    Object.defineProperty(zone, 'ring', { value: layer.toGeoJSON().geometry.coordinates[0],
                                          writable: true, configurable: true,
                                          enumerable: false });
    zoneList.push(zone);
  });
  zonePicked = zoneList.indexOf(was);
  drawZoneList();
  drawZoneEditor();
}

async function loadZones(mapName) {
  await loadZoneMeta();
  const items = [];
  if (mapName) {
    try {
      const data = await (await fetch(`/api/zones/${encodeURIComponent(mapName)}`)).json();
      for (const z of data.zones || []) {
        items.push({
          kind: 'zone',
          layer: L.polygon(z.ring.map(([lon, lat]) => [lat, lon])),
          meta: { name: z.name, settings: z.settings || {},
                  wall_style: z.wall_style, presets: z.presets },
        });
      }
    } catch { /* a map with no zones simply has none */ }
  }
  zoneLoading = true;
  zoneEd.replace(items);
  zoneLoading = false;
  zoneDirty(false);
}

document.getElementById('zoneDraw').addEventListener('click', () => {
  loadZoneMeta().then(() => {
    zoneEd.start('zone', 'area');
    zoneNote('Draw round the part of the map this zone covers; double-click to finish.');
  });
});

document.getElementById('zoneList').addEventListener('click', ev => {
  const drop = ev.target.closest('[data-drop]');
  if (drop) {
    zoneEd.remove(zoneList[parseInt(drop.dataset.drop, 10)].layer);
    return;
  }
  // The heading opens its zone, or folds it if it is the open one; a click in
  // the open zone's settings is not a click on the zone.
  const head = ev.target.closest('.zone-head');
  if (!head) return;
  const i = parseInt(head.parentElement.dataset.i, 10);
  zonePick(i === zonePicked ? -1 : i);
});
document.getElementById('zoneList').addEventListener('keydown', ev => {
  const head = ev.target.closest('.zone-head');
  if (!head || (ev.key !== 'Enter' && ev.key !== ' ')) return;
  ev.preventDefault();
  head.click();
});

// ...and the other way round: the row under the pointer lights its zone up on
// the map, which is how you find out where a zone in the list actually is.
for (const [event, on] of [['mouseover', true], ['mouseout', false]]) {
  document.getElementById('zoneList').addEventListener(event, ev => {
    const row = ev.target.closest('li[data-i]');
    if (row) zoneDress(zoneList[parseInt(row.dataset.i, 10)], on);
  });
}

document.getElementById('zoneSave').addEventListener('click', async () => {
  if (!openedMap) {
    zoneNote('Open or generate a map first: zones are saved beside one.');
    return;
  }
  try {
    const res = await fetch(`/api/zones/${encodeURIComponent(openedMap.mapName)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ zones: zoneList.map(z => ({
        name: z.name, ring: z.ring, settings: z.settings,
        wall_style: z.wall_style, presets: z.presets })) }),
    });
    const out = await res.json();
    if (!res.ok) throw apiError(out, res);
    zoneDirty(false);
    zoneNote(`${out.saved} zone${out.saved === 1 ? '' : 's'} saved. `
      + 'Generate buildings again to build them in.');
    fx.toast('ok', 'Zones saved',
             `${openedMap.mapName}: build the buildings again to see them.`);
  } catch (err) {
    zoneNote(err.message);
  }
});

loadZoneMeta();

