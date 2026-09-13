// Knoxify — frontend.
//
// - Leaflet map with leaflet-draw for selecting the bbox.
// - Area stats update live as the rectangle is drawn/edited.
// - POSTs to /api/generate and renders results.

// Mirrors the server. Big areas are fetched as a grid of Overpass queries, so
// the cap is render memory and patience rather than one API call's limit.
const MAX_AREA_KM2 = 400.0;
const MAX_TILES_PER_SIDE = 9000;
const MAX_LANDMARK_KM2 = 40.0;
const OVERPASS_TILE_KM2 = 30.0;
const SLOW_ABOVE_KM2 = 60.0;

const map = L.map('map', { zoomControl: true }).setView([38.0406, -84.5037], 14);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '© OpenStreetMap contributors',
}).addTo(map);

const drawnItems = new L.FeatureGroup().addTo(map);
const drawControl = new L.Control.Draw({
  draw: {
    polygon: false, polyline: false, circle: false, marker: false,
    circlemarker: false,
    rectangle: { shapeOptions: { color: '#a5e266', weight: 2, fillOpacity: 0.08,
                                 className: 'sel-rect' } },
  },
  edit: { featureGroup: drawnItems, remove: true },
});
map.addControl(drawControl);

let currentRect = null;

map.on(L.Draw.Event.CREATED, (e) => {
  drawnItems.clearLayers();
  currentRect = e.layer;
  drawnItems.addLayer(currentRect);
  updateBboxFields();
});
map.on(L.Draw.Event.EDITED, () => updateBboxFields());
map.on(L.Draw.Event.DELETED, () => {
  currentRect = null;
  clearBboxFields();
});

// Leaflet reports coordinates *unwrapped* once the map has been panned across
// a world copy, so a rectangle drawn after dragging east twice comes back at
// longitude 747 rather than 27. The server folds these back too, but doing it
// here as well keeps the boxes on screen showing where the user actually is.
function wrapLon(lon) {
  return ((lon + 180) % 360 + 360) % 360 - 180;
}

function rectBounds(rect) {
  const b = rect.getBounds();
  return {
    s: b.getSouth(), n: b.getNorth(),
    w: wrapLon(b.getWest()), e: wrapLon(b.getEast()),
  };
}

function updateBboxFields() {
  if (!currentRect) return clearBboxFields();
  const { s, w, n, e } = rectBounds(currentRect);
  document.getElementById('south').value = s.toFixed(6);
  document.getElementById('west').value  = w.toFixed(6);
  document.getElementById('north').value = n.toFixed(6);
  document.getElementById('east').value  = e.toFixed(6);

  const area = bboxAreaKm2(s, w, n, e);
  const mpt = parseFloat(document.getElementById('metersPerTile').value);
  const widthM  = haversineKm(s, w, s, e) * 1000;
  const heightM = haversineKm(s, w, n, w) * 1000;
  const tilesX = Math.ceil(widthM / mpt / 300) * 300;
  const tilesY = Math.ceil(heightM / mpt / 300) * 300;
  const cellsX = tilesX / 300;
  const cellsY = tilesY / 300;

  const queries = area > OVERPASS_TILE_KM2
    ? Math.ceil(Math.sqrt(area / OVERPASS_TILE_KM2)) ** 2 : 1;
  // Landscape and vegetation images, 3 bytes a tile each.
  const pixelsMB = (tilesX * tilesY * 3 * 2) / 1e6;

  const stats = document.getElementById('area-stats');
  const btn = document.getElementById('generateBtn');
  const side = Math.max(tilesX, tilesY);
  let blocked = null;
  if (area > MAX_AREA_KM2) {
    blocked = `Too large — the limit is ${MAX_AREA_KM2} km².`;
  } else if (side > MAX_TILES_PER_SIDE) {
    blocked = `${side} tiles a side is over the ${MAX_TILES_PER_SIDE} limit — `
            + 'raise metres per tile or shrink the area.';
  }
  const slow = !blocked && area > SLOW_ABOVE_KM2;
  const bitmap = pixelsMB < 1000 ? `${Math.round(pixelsMB)} MB`
                                 : `${(pixelsMB / 1000).toFixed(1)} GB`;
  const fill = Math.min(100, (area / MAX_AREA_KM2) * 100);

  stats.className = blocked ? 'blocked' : (slow ? 'warn' : 'ok');
  stats.innerHTML = `
    <div class="tiles">
      ${fx.tile(area, 'km²', 'area', area < 10 ? 2 : 1)}
      <div class="tile"><div class="v"><span data-count="${cellsX}">0</span><small>×</small><span
        data-count="${cellsY}">0</span></div><div class="k">cells</div></div>
      ${fx.tile(tilesX * tilesY / 1e6, 'M', 'tiles', 2)}
      ${fx.tile(queries, '', queries === 1 ? 'osm query' : 'osm queries')}
    </div>
    <div class="meter">
      <div class="meter-top"><span>~${Math.round(widthM)} × ${Math.round(heightM)} m · ${bitmap} of bitmap</span>
        <span>${fill < 1 ? '<1' : Math.round(fill)}% of limit</span></div>
      <div class="bar"><div class="bar-fill" style="width:${fill}%"></div></div>
    </div>
    ${blocked ? `<div class="stat-note bad">${blocked}</div>` : ''}
    ${slow ? `<div class="stat-note warn">A big map — roughly ${Math.ceil(queries * 12 / 60)}+ min
      of OpenStreetMap queries before rendering starts.</div>` : ''}
  `;
  fx.countUp(stats);
  btn.disabled = Boolean(blocked);
  fx.step('area', blocked ? 'error' : 'done');

  const lm = document.getElementById('landmarksBtn');
  lm.disabled = btn.disabled || area > MAX_LANDMARK_KM2;
  lm.title = area > MAX_LANDMARK_KM2
    ? `Landmark lookup is limited to ${MAX_LANDMARK_KM2} km².` : '';
}

function clearBboxFields() {
  ['south', 'west', 'north', 'east'].forEach(id => {
    document.getElementById(id).value = '';
  });
  const stats = document.getElementById('area-stats');
  stats.className = 'empty';
  stats.innerHTML = `<div class="empty-state">
    <svg viewBox="0 0 48 48" aria-hidden="true"><rect x="8" y="12" width="32" height="24" rx="2"/><path d="M8 20h32M16 12v24"/></svg>
    Draw a rectangle on the map to see what you'll get.</div>`;
  document.getElementById('generateBtn').disabled = true;
  document.getElementById('landmarksBtn').disabled = true;
  document.getElementById('landmark-results').innerHTML = '';
  fx.resetFrom('area');
}

document.getElementById('metersPerTile').addEventListener('change', updateBboxFields);

function bboxAreaKm2(s, w, n, e) {
  const hKm = (n - s) * 111.32;
  const wKm = (e - w) * 111.32 * Math.cos((s + n) / 2 * Math.PI / 180);
  return Math.abs(hKm * wKm);
}

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const toRad = d => d * Math.PI / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat/2)**2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon/2)**2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

// ---- settings ----
//
// The controls are built from /api/settings rather than written out in the
// markup, so the limits and presets live in exactly one place: a knob added to
// Settings appears here on its own, and one whose range changes cannot end up
// with the page enforcing last week's bounds.

const SETTING_LABELS = {
  zombies_per_resident:['Zombies per person', 'Each person who lived or worked here becomes this many zombies.'],
  m2_per_person:       ['Living space (m²)', 'Per resident. Lower = more crowded homes = more zombies. ~25 city, 35 town, 60 suburb.'],
  spawn_density:       ['Horde cap', 'Most zombies one 10×10 m spot can hold. Vanilla towns peak at 10.'],
  tree_density:        ['Woodland', 'Scales tree cover. Trees are cover to hide in.'],
  seed:                ['Seed', 'Same seed and area gives the same town again.'],
  min_size:            ['Smallest building', 'Footprints below this many tiles are skipped.'],
  max_size:            ['Largest building', 'Footprints above this are skipped.'],
  apartment_footprint: ['Flats above', 'An untagged footprint this big reads as flats.'],
  apartment_chance:    ['Flats chance', 'How often such a footprint really becomes flats.'],
  max_levels:          ['Tallest building', 'Storeys. OSM heights are capped to this.'],
  window_density:      ['Windows', 'Below 1 means fewer. 1 is about one per five tiles of wall.'],
  room_size:           ['Room size', 'Target room area in tiles before it gets split.'],
  neighbourhood_tiles: ['Neighbourhood', 'How far one set of materials reaches.'],
  style_oddity:        ['Odd one out', 'How often a building breaks from its block.'],
  parking_density:     ['Parking', 'Vehicles only ever spawn in a parking stall.'],
};

let settingsMeta = null;

async function loadSettings() {
  const res = await fetch('/api/settings');
  settingsMeta = await res.json();
  buildSettingsForm(settingsMeta.current);
}

function buildSettingsForm(values) {
  const body = document.getElementById('advanced-body');
  body.innerHTML = '';
  for (const [key, [label, hint]] of Object.entries(SETTING_LABELS)) {
    if (!(key in settingsMeta.defaults)) continue;   // knob has been removed
    const [lo, hi] = settingsMeta.limits[key];
    const isInt = settingsMeta.types
      ? settingsMeta.types[key] === 'int'
      : Number.isInteger(settingsMeta.defaults[key]);
    const wrap = document.createElement('div');
    wrap.className = 'setting';
    // A seed is an identifier, not a quantity: nobody wants to drag a slider
    // across two billion values to find one, so it gets a box and a dice.
    const control = key === 'seed'
      ? `<div class="seed-row"><input type="number" data-key="${key}" min="${lo}"
           max="${hi}" step="1" value="${values[key]}"><button type="button"
           class="dice" title="Random seed">🎲</button></div>`
      : `<input type="range" data-key="${key}" min="${lo}" max="${hi}"
           step="${isInt ? 1 : 0.05}" value="${values[key]}">`;
    wrap.innerHTML = `
      <div class="setting-head"><span class="setting-name">${label}</span>
        ${key === 'seed' ? '' : `<output class="setting-val">${values[key]}</output>`}</div>
      ${control}
      <span class="setting-hint">${hint}</span>`;
    body.appendChild(wrap);
  }
  fx.wireSettings(body);
}

function readSettings() {
  const out = { preset: document.getElementById('preset').value };
  for (const el of document.querySelectorAll('#advanced-body input[data-key]')) {
    // Blank means "whatever the preset says" rather than zero.
    if (el.value.trim() !== '') out[el.dataset.key] = parseFloat(el.value);
  }
  return out;
}

document.getElementById('preset').addEventListener('change', () => {
  if (!settingsMeta) return;
  const preset = settingsMeta.presets[document.getElementById('preset').value];
  if (preset) buildSettingsForm(preset);
});

document.getElementById('resetSettings').addEventListener('click', () => {
  if (!settingsMeta) return;
  const preset = settingsMeta.presets[document.getElementById('preset').value];
  buildSettingsForm(preset || settingsMeta.defaults);
});

// ---- setup check -----------------------------------------------------------------

async function checkSetup() {
  try {
    const res = await fetch('/api/setup-status');
    const data = await res.json();
    const card = document.getElementById('setupCard');
    if (data.ready) { card.hidden = true; return; }
    document.getElementById('setupList').innerHTML = data.checks.map(c =>
      `<li class="${c.ok ? 'ok' : 'missing'}"><span>${c.ok ? '✓' : '✗'}</span>
        <b>${escapeHtml(c.label)}</b>${c.ok ? '' : ` — ${escapeHtml(c.fix)}`}</li>`).join('');
    card.hidden = false;
  } catch (_) { /* the page still works without the check */ }
}
checkSetup();

loadSettings().catch(() => {
  document.getElementById('advanced-body').textContent =
    'Could not load the settings list.';
});

// ---- generation ----

document.getElementById('generateBtn').addEventListener('click', async () => {
  if (!currentRect) return;
  const b = currentRect.getBounds();

  // Name it here rather than letting the server invent one, so progress can be
  // polled under a key the page already knows.
  const nameField = document.getElementById('mapName');
  const chosen = (nameField.value.trim() || `knoxify_${Date.now()}`)
    .replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '');
  nameField.value = chosen;

  const bb = rectBounds(currentRect);
  const body = {
    south: bb.s,
    west: bb.w,
    north: bb.n,
    east: bb.e,
    metersPerTile: parseFloat(document.getElementById('metersPerTile').value),
    mapName: chosen,
    settings: readSettings(),
  };

  const btn = document.getElementById('generateBtn');
  const status = document.getElementById('status');
  btn.disabled = true;
  status.className = '';
  status.textContent = 'Starting…';
  fx.step('style', 'done');
  fx.step('terrain', 'running');
  fx.overlay.show();
  startProgress(chosen);

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

    status.className = 'success';
    status.textContent = `Done in ${data.osmSeconds}s (OSM query). ${data.featureCount} features rendered.`;
    fx.overlay.done(`${data.featureCount.toLocaleString()} features on the map`);
    fx.step('terrain', 'done');
    fx.toast('ok', 'Terrain generated',
             `${data.cellsX} × ${data.cellsY} cells from ${data.featureCount.toLocaleString()} features.`);
    renderResults(data);
  } catch (err) {
    status.className = 'error';
    status.textContent = `Error: ${err.message}`;
    fx.overlay.fail(err.message);
    fx.step('terrain', 'error');
    fx.toast('bad', 'Generation failed', err.message, 12000);
  } finally {
    stopProgress();
    btn.disabled = false;
  }
});

// ---- progress for long generations ----
//
// A 400 km² map is dozens of Overpass queries and minutes of rendering. The
// request itself stays open the whole time, so the page polls a side channel
// to show what stage it is at rather than sitting on a dead spinner.

let progressTimer = null;

function startProgress(mapName) {
  clearInterval(progressTimer);
  progressTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/progress?map=${encodeURIComponent(mapName)}`);
      const p = await res.json();
      fx.overlay.update(p);
      const status = document.getElementById('status');
      if (p.stage === 'osm') {
        const total = p.total || 1;
        status.textContent = total > 1
          ? `Querying OpenStreetMap — area ${(p.done || 0) + 1} of ${total}…`
          : 'Querying OpenStreetMap…';
      } else if (p.stage === 'render') {
        status.textContent = `Rendering ${p.features.toLocaleString()} features `
                           + 'into bitmaps…';
      }
    } catch (_) { /* the generate call is the source of truth */ }
  }, 1500);
}

function stopProgress() {
  clearInterval(progressTimer);
  progressTimer = null;
}

function renderResults(data) {
  const section = document.getElementById('results');
  section.hidden = false;
  document.getElementById('previewImg').src = data.files.preview + '?t=' + Date.now();
  document.getElementById('previewLink').href = data.files.preview;

  const info = document.getElementById('results-info');
  info.innerHTML = `<div class="tiles">
      ${fx.tile(data.width, '', 'tiles wide')}
      ${fx.tile(data.height, '', 'tiles tall')}
      <div class="tile"><div class="v"><span data-count="${data.cellsX}">0</span><small>×</small><span
        data-count="${data.cellsY}">0</span></div><div class="k">cells</div></div>
      ${fx.tile(data.featureCount, '', 'osm features')}
    </div>`;
  fx.countUp(info);

  // One click gets the lot; the individual files stay available but folded away.
  const all = document.getElementById('downloadAll');
  all.href = data.files.zip;
  all.setAttribute('download', `${data.mapName}.zip`);

  document.querySelectorAll('#results .ph').forEach(el => {
    el.textContent = data.mapName;
  });

  const entries = [
    ['Landscape BMP', data.files.landscape],
    ['Vegetation BMP', data.files.vegetation],
    ['Zombie spawn BMP', data.files.spawn],
    ['Preview PNG', data.files.preview],
    ['Building footprints (GeoJSON)', data.files.buildings],
    ['Meta (JSON)', data.files.meta],
    ['README', data.files.readme],
  ];
  const ul = document.getElementById('downloads');
  ul.innerHTML = entries.map(([label, href]) =>
    `<li>→ <a href="${href}" target="_blank" download>${label}</a></li>`
  ).join('');
  setupPipeline(data);
  section.scrollIntoView({ behavior: 'smooth' });
}

// ---- place search ---------------------------------------------------------
//
// Nominatim finds a place by name; picking a result both flies the map there
// and drops a selection rectangle, so "school -> map" is two clicks. A result's
// own bounding box is used when it is a sensible size, otherwise we centre a
// default-sized box on it - searching a whole city should not hand you a
// 200 km² selection the generator will refuse.

const DEFAULT_BOX_KM = 1.2;
const MIN_BOX_KM = 0.4;

const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('search-results');
const searchHere = document.getElementById('searchHere');
let searchTimer = null;
let searchMarker = null;

function setRectFromBounds(bounds) {
  drawnItems.clearLayers();
  currentRect = L.rectangle(bounds, { color: '#a5e266', weight: 2,
                                    fillOpacity: 0.08, className: 'sel-rect' });
  drawnItems.addLayer(currentRect);
  updateBboxFields();
}

function boundsAround(lat, lon, km) {
  const dLat = km / 111.32 / 2;
  const dLon = km / (111.32 * Math.cos(lat * Math.PI / 180)) / 2;
  return L.latLngBounds([lat - dLat, lon - dLon], [lat + dLat, lon + dLon]);
}

function boundsForResult(r) {
  const [s, w, n, e] = r.bbox;
  const km2 = bboxAreaKm2(s, w, n, e);
  const widthKm = haversineKm(s, w, s, e);
  const heightKm = haversineKm(s, w, n, w);
  if (km2 <= MAX_AREA_KM2 && widthKm >= MIN_BOX_KM && heightKm >= MIN_BOX_KM) {
    return L.latLngBounds([s, w], [n, e]);
  }
  return boundsAround(r.lat, r.lon, DEFAULT_BOX_KM);
}

function hideSearchResults() {
  searchResults.hidden = true;
  searchResults.innerHTML = '';
}

function renderSearchResults(results) {
  if (!results.length) {
    searchResults.innerHTML = '<li class="empty">No matches.</li>';
    searchResults.hidden = false;
    return;
  }
  searchResults.innerHTML = results.map((r, i) => {
    const kind = [r.type, r.category].filter(Boolean)[0] || '';
    const rest = r.display_name.split(',').slice(1).join(',').trim();
    return `<li data-i="${i}">
      <span class="r-name">${escapeHtml(r.name)}</span>
      ${kind ? `<span class="r-kind">${escapeHtml(kind.replace(/_/g, ' '))}</span>` : ''}
      <span class="r-where">${escapeHtml(rest)}</span>
    </li>`;
  }).join('');
  searchResults.hidden = false;

  searchResults.querySelectorAll('li[data-i]').forEach(li => {
    li.addEventListener('click', () => {
      const r = results[parseInt(li.dataset.i, 10)];
      const bounds = boundsForResult(r);
      map.fitBounds(bounds, { padding: [30, 30] });
      setRectFromBounds(bounds);
      if (searchMarker) map.removeLayer(searchMarker);
      searchMarker = L.marker([r.lat, r.lon]).addTo(map)
        .bindPopup(escapeHtml(r.name)).openPopup();
      hideSearchResults();
      searchInput.value = r.name;
    });
  });
}

async function runSearch(q) {
  if (!q.trim()) return hideSearchResults();
  searchResults.innerHTML = '<li class="empty">Searching…</li>';
  searchResults.hidden = false;
  const params = new URLSearchParams({ q });
  if (searchHere.checked) {
    const b = map.getBounds();
    // Zoomed far enough out, the viewport spans more than a whole world and
    // wrapping it would describe a sliver instead. Search globally then.
    if (b.getEast() - b.getWest() < 360) {
      params.set('south', b.getSouth());
      params.set('west', wrapLon(b.getWest()));
      params.set('north', b.getNorth());
      params.set('east', wrapLon(b.getEast()));
      params.set('bounded', '1');
    }
  }
  try {
    const res = await fetch('/api/search?' + params.toString());
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    renderSearchResults(data.results);
  } catch (err) {
    searchResults.innerHTML = `<li class="empty">${escapeHtml(err.message)}</li>`;
  }
}

searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  // Nominatim allows one request a second; don't fire on every keystroke.
  searchTimer = setTimeout(() => runSearch(searchInput.value), 500);
});
searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { clearTimeout(searchTimer); runSearch(searchInput.value); }
  if (e.key === 'Escape') hideSearchResults();
});
document.addEventListener('click', (e) => {
  if (!document.getElementById('search-box').contains(e.target)) hideSearchResults();
});

// ---- landmarks inside the selection ---------------------------------------

let landmarkMarkers = L.layerGroup().addTo(map);

document.getElementById('landmarksBtn').addEventListener('click', async () => {
  if (!currentRect) return;
  const bb = rectBounds(currentRect);
  const btn = document.getElementById('landmarksBtn');
  const out = document.getElementById('landmark-results');
  btn.disabled = true;
  out.innerHTML = '<div class="hint">Asking Overpass…</div>';

  try {
    const res = await fetch('/api/landmarks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        south: bb.s, west: bb.w, north: bb.n, east: bb.e,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    renderLandmarks(data.landmarks);
  } catch (err) {
    out.innerHTML = `<div class="error">${escapeHtml(err.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
});

function renderLandmarks(items) {
  const out = document.getElementById('landmark-results');
  landmarkMarkers.clearLayers();
  if (!items.length) {
    out.innerHTML = '<div class="hint">Nothing named in this area.</div>';
    return;
  }
  const groups = {};
  items.forEach(it => { (groups[it.value] ||= []).push(it); });
  const order = Object.keys(groups).sort((a, b) =>
    groups[b].length - groups[a].length || a.localeCompare(b));

  out.innerHTML = `<div class="hint">${items.length} named landmarks</div>` +
    order.map(k => `
      <details>
        <summary>${escapeHtml(k.replace(/_/g, ' '))}
          <span class="count">${groups[k].length}</span></summary>
        <ul class="landmark-list">
          ${groups[k].map(it =>
            `<li data-lat="${it.lat}" data-lon="${it.lon}">${escapeHtml(it.name)}</li>`
          ).join('')}
        </ul>
      </details>`).join('');

  out.querySelectorAll('li[data-lat]').forEach(li => {
    li.addEventListener('click', () => {
      const lat = parseFloat(li.dataset.lat), lon = parseFloat(li.dataset.lon);
      map.setView([lat, lon], Math.max(map.getZoom(), 17));
      landmarkMarkers.clearLayers();
      L.circleMarker([lat, lon], {
        radius: 8, color: '#ffd23c', weight: 2, fillOpacity: 0.4,
      }).addTo(landmarkMarkers).bindPopup(li.textContent).openPopup();
    });
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// ---- steps 3-5: buildings, compile, install -------------------------------
//
// Everything after terrain generation, driven from this one window. The only
// part that is not automated is WorldEd's BMP to TMX and Generate Lots, which
// exist solely as menu commands - so we launch WorldEd on the project and then
// poll for the compiled cells instead of asking the user to report back.

let currentMap = null;
let lotsPoll = null;

function note(id, text, cls) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = 'step-note' + (cls ? ' ' + cls : '');
  fx.noted(id, text, cls);
}

function setupPipeline(data) {
  currentMap = data.mapName;
  document.getElementById('mapTitle').value = data.mapName;
  document.getElementById('modId').value = data.mapName;
  document.getElementById('buildingsBtn').disabled = false;
  document.getElementById('worldedBtn').disabled = true;
  document.getElementById('compileBtn').disabled = true;
  document.getElementById('installBtn').disabled = true;
  ['buildings', 'compile', 'install'].forEach(k => fx.card(k, null));
  fx.card('buildings', 'ready');
  fx.resetFrom('buildings');
  document.getElementById('compileBar').style.width = '0%';
  note('buildingsNote', 'Turns every OSM footprint into a furnished building.');
  note('worldedNote', 'Generate the buildings first.');
  note('installNote', 'Copies the compiled map into ~/Zomboid/mods.');
  renderCensus(null);
  checkLots();
}

document.getElementById('buildingsBtn').addEventListener('click', async () => {
  const btn = document.getElementById('buildingsBtn');
  btn.disabled = true;
  note('buildingsNote', 'Generating…');
  try {
    const res = await fetch('/api/buildings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      // Sent again so the buildings can be regenerated with different
      // settings without re-downloading the town from OSM.
      body: JSON.stringify({ mapName: currentMap, settings: readSettings() }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    note('buildingsNote', `${data.count} buildings → ${data.pzw}`, 'ok');
    renderCensus(data.population);
    document.getElementById('worldedBtn').disabled = false;
    document.getElementById('compileBtn').disabled = false;
    note('compileNote', 'Ready — runs BMP to TMX and Generate Lots for you.');
  } catch (err) {
    note('buildingsNote', err.message, 'bad');
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('worldedBtn').addEventListener('click', async () => {
  try {
    const res = await fetch('/api/worlded', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mapName: currentMap }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    note('worldedNote', 'WorldEd opened. File > BMP To TMX > All Cells…, then '
                        + 'File > Generate Lots 8x8 > All Cells… — waiting…');
    startLotsPoll();
  } catch (err) {
    note('worldedNote', err.message, 'bad');
  }
});

function startLotsPoll() {
  clearInterval(lotsPoll);
  lotsPoll = setInterval(checkLots, 4000);
}

async function checkLots() {
  if (!currentMap) return;
  try {
    const res = await fetch(`/api/lots?map=${encodeURIComponent(currentMap)}`);
    const data = await res.json();
    if (data.compiled) {
      clearInterval(lotsPoll);
      note('worldedNote', `${data.cells} cells compiled.`, 'ok');
      document.getElementById('installBtn').disabled = false;
      note('installNote', 'Ready to install.');
    }
  } catch (_) { /* keep polling quietly */ }
}

document.getElementById('installBtn').addEventListener('click', async () => {
  const btn = document.getElementById('installBtn');
  btn.disabled = true;
  note('installNote', 'Installing…');
  try {
    const res = await fetch('/api/install', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mapName: currentMap,
        title: document.getElementById('mapTitle').value.trim(),
        modId: document.getElementById('modId').value.trim(),
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    note('installNote',
         `Installed ${data.cells} cells to ${data.modRoot}. Enable "${data.title}" `
         + 'in the game\'s Mods menu, then start a NEW save.', 'ok');
  } catch (err) {
    note('installNote', err.message, 'bad');
    btn.disabled = false;
  }
});

// ---- zombie census ------------------------------------------------------------
//
// Where the zombies go is worked out from the people in the buildings, so the
// build reports a head count. Recounting redraws only the spawn map from the
// saved footprints - a fraction of a second - so the zombie settings can be
// tried without regenerating a single building.

function renderCensus(pop) {
  const box = document.getElementById('census');
  if (!pop) { box.hidden = true; return; }
  box.hidden = false;
  const tiles = document.getElementById('censusTiles');
  tiles.innerHTML = `
    ${fx.tile(pop.residents, '', 'residents')}
    ${fx.tile(pop.daytime_occupants, '', 'at work or school')}
    ${fx.tile(pop.zombie_estimate, '', 'zombies, roughly')}
    ${fx.tile(pop.share_with_zombies * 100, '%', 'of the map infested', 0)}`;
  fx.countUp(tiles);
  const official = document.getElementById('censusOfficial');
  official.innerHTML = (pop.official || []).length
    ? 'OpenStreetMap lists ' + pop.official.map(p =>
        `<b>${escapeHtml(p.name || p.place)}</b> at ${p.population.toLocaleString()} people`
      ).join(', ') + ' — official figures can cover a whole district, not just what is on the map.'
    : '';
}

document.getElementById('recountBtn').addEventListener('click', async () => {
  const btn = document.getElementById('recountBtn');
  btn.disabled = true;
  try {
    const res = await fetch('/api/zombies', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mapName: currentMap, settings: readSettings() }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    renderCensus(data.population);
    const censusNote = document.getElementById('censusNote');
    censusNote.textContent = 'Recounted. Compile the map again so the game sees the new zombies.';
    censusNote.className = 'step-note ok';
    // The compiled lots hold the old spawn map until they are rebuilt.
    document.getElementById('installBtn').disabled = true;
    document.getElementById('compileBtn').disabled = false;
    note('compileNote', 'Ready — compile again to bake in the new zombie counts.');
  } catch (err) {
    const censusNote = document.getElementById('censusNote');
    censusNote.textContent = err.message;
    censusNote.className = 'step-note bad';
  } finally {
    btn.disabled = false;
  }
});

// ---- automatic compile (patched WorldEd) ---------------------------------
//
// Stock WorldEd exposes BMP to TMX and Generate Lots only as menu items. The
// rebuilt PZWorldEd_cli.exe adds a --generate-map switch that runs both, so
// this step needs no clicking; the manual route stays available underneath.

document.getElementById('compileBtn').addEventListener('click', async () => {
  const btn = document.getElementById('compileBtn');
  btn.disabled = true;
  note('compileNote', 'Starting…');
  try {
    const res = await fetch('/api/compile', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mapName: currentMap }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    pollCompile();
  } catch (err) {
    note('compileNote', err.message, 'bad');
    btn.disabled = false;
  }
});

// The compile runs on the server's own thread; this just watches it. Blocking
// the request instead froze the whole window for the length of a town.
let compileTimer = null;

function pollCompile() {
  clearInterval(compileTimer);
  compileTimer = setInterval(async () => {
    try {
      const res = await fetch(
        `/api/compile-status?map=${encodeURIComponent(currentMap)}`);
      const p = await res.json();
      if (p.state === 'running') {
        const pct = p.expected ? Math.floor(100 * p.cells / p.expected) : 0;
        // The batch counter is the honest one on a big map: cell files land in
        // bursts and stay flat for minutes inside a batch, which reads as a
        // hang. Batches tick over steadily.
        const batch = p.batches ? ` — batch ${p.batch}/${p.batches}` : '';
        fx.progress('compile', p.batches ? Math.max(pct, 100 * (p.batch - 1) / p.batches) : pct);
        note('compileNote',
             `Compiling${batch} — ${p.tmx} cells converted, `
             + `${p.cells}/${p.expected || '?'} compiled (${pct}%)…`);
        return;
      }
      clearInterval(compileTimer);
      document.getElementById('compileBtn').disabled = false;
      if (p.state === 'error') {
        note('compileNote', p.error || 'Compile failed.', 'bad');
        return;
      }
      if (p.state === 'done') {
        fx.progress('compile', 100);
        note('compileNote', `${p.cells} cells compiled.`, 'ok');
        document.getElementById('installBtn').disabled = false;
        note('installNote', 'Ready to install.');
      }
    } catch (_) { /* keep watching */ }
  }, 2000);
}
