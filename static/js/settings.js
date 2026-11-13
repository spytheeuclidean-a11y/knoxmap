// ---- settings ----
//
// The controls are built from /api/settings rather than written out in the
// markup, so the limits and presets live in exactly one place: a knob added to
// Settings appears here on its own, and one whose range changes cannot end up
// with the page enforcing last week's bounds.

const SETTING_LABELS = {
  zombies_per_resident:['Zombies per person', 'Each person who lived or worked here becomes this many zombies.'],
  m2_per_person:       ['Living space (m²)', 'Per resident. Less space means more crowded homes, so more zombies. About 50 in a city, 45 in a town, 60 in a suburb.'],
  spawn_density:       ['Horde cap', 'Most zombies one 10×10 m spot can hold. Vanilla towns peak at 10.'],
  tree_density:        ['Woodland', 'Scales tree cover everywhere: the woods, the gardens and the scrub over open ground. Trees are cover to hide in.'],
  forest_density:      ['Forests', 'Scales every wood, on top of Woodland: the ones the mapper drew and the tree cover WorldCover finds. Thick forest round a thinly planted town, or the other way about.'],
  forest_clustering:   ['Forest clustering', 'Size in metres of the dense stands and clearings inside forests. Larger values make bigger groves and wider meadows.'],
  forest_openness:     ['Forest openness', 'Share of a mapped forest that opens up into clearings and sparse trees instead of a solid wall.'],
  forest_edge_softness:['Edge softness', 'Width in tiles of the thinned border band along forest edges.'],
  seed:                ['Seed', 'Same seed and area gives the same town again.'],
  fill_gaps:           ['Fill gaps from Microsoft footprints', 'On adds the buildings OpenStreetMap has not got, from Microsoft’s machine-detected building footprints, same licence. Downloads about 30 MB per tile on the first run, nothing to install. Worth it where your town is half missing from OSM; elsewhere it adds sheds. Falls back to Overture (needs DuckDB) if Microsoft cannot be reached.'],
  fill_frontage:       ['Fill gaps in streets', 'Builds buildings missing from a street that has buildings beside the gap, matching their neighbours (width, depth, set-back, storeys) where there is room. Choose whether to also extend the ends of rows or only fill gaps between existing buildings.'],
  true_map:            ['True map generation', 'On builds every address as mapped. Off keeps the real roads, rivers, woods and terrain, but leaves out half the houses and grows the rest into proper homes with yards. Named places are always built, at the game’s size.'],
  guaranteed_rifle:    ['Guaranteed rifle', 'On leaves one military rifle on the map: in an army building if there is one, else the police station, else a gun shop, else a house on the edge of town. A real town has no checkpoints for one to spawn in.'],
  min_size:            ['Smallest building', 'Buildings narrower than this many tiles are left out.'],
  align_streets:       ['Straighten streets', 'On turns the map so the main street grid runs along the tiles - no staircase roads. Off keeps north up.'],
  rotate_degrees:      ['Turn the map', 'Degrees to turn the whole area before it is built, on top of Straighten streets. Use it when the automatic angle picks the wrong grid.'],
  straight_roads:      ['Road layout', 'As mapped draws roads as they are. Knox County straight lays every road in straight runs along the tiles and on 45-degree diagonals, squaring off the short kinks between runs so a street stays on one grid line or one diagonal - the default. Vanilla curves routes them the way the game’s own B42 map draws its streets: along the tiles, 45 degrees and the 2:1 slopes, with its curves and street shapes. Built-up streets square keeps streets lined with buildings on the grid, as the buildings are, and off them. The vanilla choices take a few minutes on a town.'],
  include_proposed_roads: ['Proposed roads', 'On includes roads marked as proposed in OpenStreetMap, even though they may not exist yet. Off leaves them out.'],
  max_size:            ['Largest building', 'Footprints above this are skipped.'],
  max_buildings:       ['Most buildings', 'The most buildings the whole map may hold. 0 is no ceiling. Set it and the landmarks are kept - the police station, the school, the shops - while the houses are spaced out over the whole map until the count fits, so a big map is one worth driving across rather than one paved with houses. Fewer buildings is also the surest way to make a map quicker to build and lighter to play. It is a ceiling, not a quota: the finished map can come out a little under it, because some footprints are skipped for other reasons as well - too small to furnish, off the edge, under a road. Click a building under Change what is here to see which.'],
  apartment_footprint: ['Flats above', 'An untagged footprint this big reads as flats.'],
  apartment_chance:    ['Flats chance', 'How often such a footprint really becomes flats.'],
  vanilla_tiles:       ['Vanilla tiles only', 'On builds with the game’s own art only, leaving Erika’s Tiles out even when it is installed. A map built with the mod needs the mod to look right, so this is the one to turn on before handing a map to somebody who has not subscribed.'],
  height_mix:          ['Height mix', 'How tall the buildings OpenStreetMap says nothing about come out. As the place is lets the kind of building and the size of its footprint decide, which is the closest to the real thing. The rest shape that guess for the skyline you want. A building whose floors OSM does record keeps them whatever this says.'],
  max_levels:          ['Tallest building', 'Storeys, up to 31 - Build 42’s height limit, less the roof. OSM heights are capped to this. Tall cities take longer to compile.'],
  room_size:           ['Room size', 'Target room area in tiles before it gets split.'],
  room_solver:         ['Planned house rooms', 'On plans each house of up to four storeys as a whole: a hall from the front door, the stairs against a wall, the kitchen at the back, bedrooms and the bathroom upstairs, every room with its own window. Anything else is built as before. Needs OR-Tools (pip install ortools). The first build is slower, a few seconds a house shape; each shape is remembered after that.'],
  building_alignment:  ['Building alignment', 'Real preserves the mapped outline. Smart squares near-grid buildings. Rectilinear aligns the dominant wall direction while keeping the footprint shape. Rectangle uses a clean box.'],
  arch_style:         ['Architecture', 'Auto reads the map\u2019s own building names: a town written in Chinese gets flat-roofed masonry blocks, taller self-built houses and walk-up flats, the way it is really built there. Chinese forces that look. Default builds every town like the game\u2019s own Kentucky.'],
  neighbourhood_tiles: ['Neighbourhood', 'How far one set of materials reaches.'],
  style_oddity:        ['Odd one out', 'How often a building breaks from its block.'],
  parking_density:     ['Parking', 'Vehicles only ever spawn in a parking stall.'],
  basement_share:      ['Basements', 'The share of houses with a basement. Schools, hospitals, police stations and the like always get one.'],
  max_basement_depth:  ['Deepest basement', 'Levels a military base may go down, up to 32. 0 builds no basements at all.'],
  landcover:           ['Land cover', 'WorldCover fills ground OpenStreetMap leaves blank with what is really there: woods, scrub, meadow, fields, marsh, rock. Its data downloads once per area. OpenStreetMap only leaves that ground as grass with scattered made-up woods.'],
  elevation:           ['Terrain relief', 'USGS 3DEP adds real relief, up to Relief z-levels. Flat keeps today’s flat terrain. US only; needs rasterio.'],
  max_relief:          ['Relief', 'How many z-levels of real terrain relief to allow.'],
  ne_context:          ['Natural Earth context', 'Country, coastline fallback and place labels from Natural Earth.'],
  hospitals:           ['Hospitals', 'HIFLD names and sizes real US hospitals on the map. OpenStreetMap only uses the map’s own tags.'],
  hospitals_place_missing: ['Place missing hospitals', 'On stamps a hospital where OpenStreetMap has none, if the ground allows.'],
  climate_flavor:      ['Climate flavour', 'Tints the map for its real NOAA climate. US only; needs pyarrow.'],
  winter_look:         ['Winter look', 'Auto, on or off: snow-dusted ground and bare deciduous trees where the climate is cold.'],
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
    const choices = settingsMeta.options?.[key];
    const isChoice = Array.isArray(choices);
    // A setting that is only ever 0 or 1 is a switch, not a quantity. As a
    // slider it was two positions wide, read "1" or "0" rather than on or
    // off, and could be left halfway on a touchscreen.
    const isSwitch = !isChoice && isInt && lo === 0 && hi === 1;
    const wrap = document.createElement('div');
    wrap.className = isSwitch ? 'setting setting-switch' : 'setting';
    // A seed is an identifier, not a quantity: nobody wants to drag a slider
    // across two billion values to find one, so it gets a box and a dice.
    const control = key === 'seed'
      ? `<div class="seed-row"><input type="number" data-key="${key}" min="${lo}"
           max="${hi}" step="1" value="${values[key]}"><button type="button"
           class="dice" title="Random seed">random</button></div>`
      : isChoice
      ? `<select data-key="${key}">${choices.map(([value, name]) =>
          `<option value="${value}"${value === values[key] ? ' selected' : ''}>${name}</option>`).join('')}</select>`
      : isSwitch
      ? ''
      : `<input type="range" data-key="${key}" min="${lo}" max="${hi}"
           step="${isInt ? 1 : 0.05}" value="${values[key]}">`;
    // The switch sits in the heading, where the number used to be: the name
    // on the left, what it is set to on the right, the hint underneath.
    const head = isSwitch
      ? `<label class="switch"><input type="checkbox" role="switch"
           data-key="${key}" aria-label="${label}"${values[key] ? ' checked' : ''}>
         <span class="switch-track"></span></label>`
      : key === 'seed' || isChoice ? ''
      : `<output class="setting-val">${values[key]}</output>`;
    wrap.innerHTML = `
      <div class="setting-head"><span class="setting-name">${label}</span>
        ${head}</div>
      ${control}
      <span class="setting-hint">${hint}</span>`;
    body.appendChild(wrap);
  }
  fx.wireSettings(body);
  runListSearch('advanced-body');
  const topTerrain = document.getElementById('terrainOnlyToggle');
  if (topTerrain) topTerrain.checked = !!values.terrain_only;
}

function readSettings() {
  const out = { preset: document.getElementById('preset').value };
  const topTerrain = document.getElementById('terrainOnlyToggle');
  if (topTerrain) out.terrain_only = topTerrain.checked ? 1 : 0;
  for (const el of document.querySelectorAll('#advanced-body [data-key]')) {
    // A switch is on or off, and sends the 1 or 0 the generator reads.
    if (el.type === 'checkbox') {
      out[el.dataset.key] = el.checked ? 1 : 0;
      continue;
    }
    // Blank means "whatever the preset says" rather than zero.
    if (el.value.trim() !== '') {
      out[el.dataset.key] = el.tagName === 'SELECT' ? el.value : parseFloat(el.value);
    }
  }
  return out;
}

// ---- putting a changed setting into a map that already exists ---------------
// Changing the woodland used to mean drawing the box again, naming it again and
// setting every other knob again, because nothing remembered what a map was
// made from. All of it is saved beside the map; this hands it back. Only the
// steps a change really needs are run - most knobs are read when the buildings
// are laid out, and those go onto the ground that is already drawn - and the
// Overpass download is kept next to the map, so even a redraw does not fetch
// the town again (generator/osm.py, save_cache).
let openedMap = null;
let importedSettings = null;

function rememberMap(map) {
  importedSettings = null;
  openedMap = map;
  if (map && map.settings) {
    openedMap.settings = { ...map.settings };
    delete openedMap.settings.preset;
  }
  // What the panel reads back once it has been filled in, which is not always
  // what was saved: the sliders step in hundredths, so a style_oddity of 0.18
  // comes back as 0.20 and would be reported as a change nobody made. The
  // knobs are measured against what they were showing, and only the ones that
  // really move are sent, so the rest keep the value the map was made with.
  openedMap.shown = readSettings();
  showReapply();
  // Editing is about a map that exists, so it waits for one to be open. The
  // shapes of whichever map was open before are cleared rather than left to
  // be edited into a map they do not belong to.
  if (typeof editReady === 'function') {
    editReady(map && openedMap ? openedMap.mapName : null);
    editLayer.clearLayers();
    pickEdit(null);
    mapEdits = { removed: [], moved: {}, tags: {} };
    document.getElementById('editShape').disabled = true;
    showEditCount();
    noteEdit('');
  }
}

// The knobs moved since the panel was filled in, by name.
function changedSettings() {
  if (!openedMap || !openedMap.shown) return [];
  return changedFrom(openedMap.shown, readSettings());
}

function changedFrom(was, now) {
  const out = [];
  for (const [key, value] of Object.entries(now)) {
    if (key === 'preset' || !(key in was)) continue;
    const before = was[key];
    const same = typeof value === 'number' && typeof before === 'number'
      ? Math.abs(value - before) < 1e-9
      : String(value) === String(before);
    if (!same) out.push(key);
  }
  return out;
}

// Slider controls cannot always represent the exact saved number (e.g. 0.18
// on a 0.05-step slider). Keep imported and opened-map values until a knob moves.
function settingsForRequest() {
  const now = readSettings();
  const saved = importedSettings || openedMap;
  if (!saved || !saved.shown || !saved.settings) return now;
  const out = { ...saved.settings, preset: now.preset };
  for (const key of changedFrom(saved.shown, now)) out[key] = now[key];
  return out;
}

// The map's own settings with the moved knobs put in: a setting the panel
// cannot show exactly is left exactly as it was.
function settingsToApply(changed) {
  const now = readSettings();
  const out = { ...(openedMap.settings || {}) };
  for (const key of changed) out[key] = now[key];
  return out;
}

// renderKeys comes from /api/settings so the page is not a second, drifting
// copy of which knob belongs to which step.
function stepsFor(changed) {
  if (!changed.length) return [];
  const redraw = (settingsMeta && settingsMeta.renderKeys) || [];
  return changed.some(k => redraw.includes(k)) ? ['generate', 'build'] : ['build'];
}

function showReapply() {
  const box = document.getElementById('reapply');
  if (!box) return;
  if (!openedMap) { box.hidden = true; box.innerHTML = ''; return; }
  const changed = changedSettings();
  const steps = stepsFor(changed);
  box.hidden = false;
  if (!steps.length) {
    box.innerHTML = `<span class="hint">${escapeHtml(openedMap.mapName)} already has these settings.</span>`;
    return;
  }
  const names = changed.map(k => (SETTING_LABELS[k] || [k])[0]);
  const what = steps.length === 2
    ? 'draws the map again and lays the buildings out again'
    : 'lays the buildings out again, on the ground already drawn';
  box.innerHTML = `<span class="hint">Changed since ${escapeHtml(openedMap.mapName)} was made:
      ${escapeHtml(names.join(', '))}. Applying it ${what} - the area, the scale and the name stay as they are.</span>
    <button type="button" id="reapplyBtn" class="btn">Apply to ${escapeHtml(openedMap.mapName)}</button>`;
  document.getElementById('reapplyBtn').addEventListener('click', reapply);
}

async function reapply() {
  const box = document.getElementById('reapply');
  const btn = document.getElementById('reapplyBtn');
  const changed = changedSettings();
  const steps = stepsFor(changed);
  if (!steps.length || !openedMap) return;
  const settings = settingsToApply(changed);
  const say = text => {
    const line = box.querySelector('.hint');
    if (line) line.textContent = text;
  };
  const post = async (url, body) => {
    const res = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const out = await res.json();
    if (wasStopped(out, res)) return null;
    if (!res.ok) throw apiError(out, res);
    return out;
  };
  btn.disabled = true;
  showStop(openedMap.mapName);
  try {
    if (steps.includes('generate')) {
      say(`Drawing ${openedMap.mapName} again - the town is not downloaded twice.`);
      startProgress(openedMap.mapName);
      const b = openedMap.bbox || {};
      const drawn = await post('/api/generate', {
        south: b.south, west: b.west, north: b.north, east: b.east,
        metersPerTile: openedMap.metersPerTile, mapName: openedMap.mapName,
        settings, shape: openedMap.shape,
      });
      if (!drawn) { say('Stopped. Nothing was thrown away.'); return; }
      renderResults(drawn);
    }
    say('Laying the buildings out again...');
    const built = await post('/api/buildings',
                             { mapName: openedMap.mapName, settings });
    if (!built) { say('Stopped. Nothing was thrown away.'); return; }
    renderCensus(built.population);
    document.getElementById('worldedBtn').disabled = false;
    document.getElementById('compileBtn').disabled = false;
    note('compileNote', 'Ready - compile to put the change in the game.');
    rememberMap({ ...openedMap, settings });
    fx.toast('ok', 'Settings applied',
             `${openedMap.mapName}: ${built.count} buildings. Compile it to put the change in the game.`);
  } catch (err) {
    say(err.message);
  } finally {
    btn.disabled = false;
    showStop(null);
  }
}

// The box is rebuilt by buildSettingsForm, so the listener goes on the
// container, which is not.
document.getElementById('advanced-body').addEventListener('input', showReapply);
document.getElementById('advanced-body').addEventListener('change', showReapply);
const topTerrainEl = document.getElementById('terrainOnlyToggle');
if (topTerrainEl) topTerrainEl.addEventListener('change', showReapply);

document.getElementById('preset').addEventListener('change', () => {
  if (!settingsMeta) return;
  importedSettings = null;
  const preset = settingsMeta.presets[document.getElementById('preset').value];
  if (preset) buildSettingsForm(preset);
  showReapply();
});

document.getElementById('resetSettings').addEventListener('click', () => {
  if (!settingsMeta) return;
  importedSettings = null;
  const preset = settingsMeta.presets[document.getElementById('preset').value];
  buildSettingsForm(preset || settingsMeta.defaults);
  showReapply();
});

