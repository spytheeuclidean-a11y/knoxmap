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
  forest_stand_m:      ['Stand size', 'How big the clumps of forest and the clearings between them are, in metres.'],
  forest_edge_m:       ['Edge softness', 'How far a wood spills out past its edge, in metres, thinning as it goes. 0 is a hard edge.'],
  forest_thickets:     ['Thickets', 'How much of a wood is a wall of trees. 1 is a tenth of it.'],
  forest_stand_variety: ['Stand variety', 'At 0 the stands are all about one size; higher mixes big, middling and small.'],
  forest_raggedness:   ['Raggedness', 'Smooth blobs at 0, ragged and broken stands at 1.'],
  forest_edge_wobble:  ['Edge wobble', 'How irregular the line is that a wood spills out to.'],
  forest_spill_thick:  ['Spill thickness', 'How much of the spill past a wood is thick trees rather than single ones.'],
  forest_keep_meadows: ['Keep meadows open', 'How far across a clearing a wood may spill. 1 lets it fill small meadows.'],
  forest_seed:         ['Forest seed', 'Another layout of the woods with the same settings.'],
  forest_house_clearing_m: ['House clearings', 'How far the clearing round a house in the woods reaches, in metres. 0 is none.'],
  forest_big_trees:    ['Big trees', 'How many big old trees stand in the woods.'],
  forest_groves:       ['Made-up woods', 'Woods made up where there is no land cover data.'],
  forest_wild_growth:  ['Scrub on open ground', 'Trees and bushes scattered over open grass where there is no land cover data.'],
  forest_shrubland:    ['Shrubland and marsh', 'How thickly the land cover\'s shrubland, grass tufts and marsh are planted.'],
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

// The settings are drawn as tabs, one card each: what a tab is mostly used
// for on show, the rest behind its own Advanced. A key named nowhere here
// still appears, in an Other tab, so a new knob is never lost; putting it in
// its place is a table entry.
const SETTING_GROUPS = {
  gameplay: {
    title: 'Gameplay',
    main: ['zombies_per_resident', 'spawn_density', 'guaranteed_rifle'],
    advanced: [
      ['Zombies', ['m2_per_person']],
      ['Vehicles', ['parking_density']],
    ],
  },
  roads: {
    title: 'Roads',
    main: ['true_map', 'straight_roads', 'align_streets'],
    advanced: [
      ['Layout', ['rotate_degrees', 'include_proposed_roads', 'seed']],
    ],
  },
  buildings: {
    title: 'Buildings',
    main: ['max_buildings', 'fill_gaps', 'height_mix', 'max_levels', 'arch_style',
           'vanilla_tiles'],
    advanced: [
      ['Which footprints', ['min_size', 'max_size', 'fill_frontage', 'building_alignment']],
      ['Flats', ['apartment_footprint', 'apartment_chance']],
      ['Look', ['neighbourhood_tiles', 'style_oddity']],
      ['Rooms', ['room_solver', 'room_size']],
      ['Basements', ['basement_share', 'max_basement_depth']],
      ['Hospitals', ['hospitals', 'hospitals_place_missing']],
    ],
  },
  land: {
    title: 'Land',
    main: ['landcover', 'elevation', 'winter_look'],
    advanced: [
      ['Details', ['max_relief', 'climate_flavor', 'ne_context']],
    ],
  },
  forest: {
    title: 'Forest',
    preview: true,
    main: ['forest_density', 'forest_thickets', 'forest_stand_m', 'forest_stand_variety',
           'forest_edge_m'],
    advanced: [
      ['Shape', ['forest_raggedness', 'forest_edge_wobble', 'forest_spill_thick',
                 'forest_keep_meadows', 'forest_seed']],
      ['Around the woods', ['forest_house_clearing_m', 'forest_big_trees', 'forest_groves',
                            'forest_wild_growth', 'forest_shrubland']],
      ['Everywhere', ['tree_density']],
    ],
  },
};
// The preview's sample land has land cover all over it, as a map with
// WorldCover does, and these do nothing there.
const NOT_IN_PREVIEW = new Set(['forest_groves', 'forest_wild_growth']);

function groupKeys(group) {
  return [...group.main, ...group.advanced.flatMap(([, keys]) => keys)];
}

// A tooltip opened with a tap closes at a tap anywhere else: a browser that
// does not focus a clicked button (Safari) never sends the (i) a blur.
document.addEventListener('click', e => {
  for (const open of document.querySelectorAll('.setting-compact.hint-open')) {
    if (open.contains(e.target)) continue;
    open.classList.remove('hint-open');
    open.querySelector('.setting-info')?.setAttribute('aria-expanded', 'false');
  }
});

function settingElement(key, label, hint, values, compact = false) {
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
  // A seed is an identifier, not a quantity: nobody wants to drag a slider
  // across a million values to find one, so it gets a box and a dice.
  const isSeed = key === 'seed' || key === 'forest_seed';
  // A slider whose whole range is 1 or less steps by 0.01, so a default such
  // as 0.33 is a position it can hold; at 0.05 the browser snapped it to 0.35
  // and the page sent that. Wider ranges keep 0.05. The same rule is checked
  // against every default in tests/test_forest_card.py.
  const floatStep = hi - lo <= 1 ? 0.01 : 0.05;
  const wrap = document.createElement('div');
  wrap.className = isSwitch ? 'setting setting-switch' : 'setting';
  const control = isSeed
    ? `<div class="seed-row"><input type="number" data-key="${key}" min="${lo}"
         max="${hi}" step="1" value="${values[key]}"><button type="button"
         class="dice" title="Random seed">random</button></div>`
    : isChoice
    ? `<select data-key="${key}">${choices.map(([value, name]) =>
        `<option value="${value}"${value === values[key] ? ' selected' : ''}>${name}</option>`).join('')}</select>`
    : isSwitch
    ? ''
    : `<input type="range" data-key="${key}" min="${lo}" max="${hi}"
         step="${isInt ? 1 : floatStep}" value="${values[key]}">`;
  // The switch sits in the heading, where the number used to be: the name
  // on the left, what it is set to on the right, the hint underneath.
  const head = isSwitch
    ? `<label class="switch"><input type="checkbox" role="switch"
         data-key="${key}" aria-label="${label}"${values[key] ? ' checked' : ''}>
       <span class="switch-track"></span></label>`
    : isSeed || isChoice ? ''
    : `<output class="setting-val">${values[key]}</output>`;
  if (compact) {
    // A card's settings are one line each - name, slider, number - so the
    // whole card and its picture fit on the screen together. What a setting
    // does is behind the (i), shown on hover, focus or a tap; it stays in
    // the page so the settings search still finds a setting by it.
    wrap.classList.add('setting-compact');
    if (isSeed || isChoice) wrap.classList.add('setting-wide');
    wrap.innerHTML = `
      <span class="setting-name">${label}<button type="button" class="setting-info"
        aria-label="About ${label}" aria-expanded="false">i</button></span>
      ${control}
      ${head}
      <span class="setting-hint" role="tooltip">${hint}</span>`;
    const info = wrap.querySelector('.setting-info');
    // Opened near the bottom of its scrolling panel, the tooltip would run
    // out of sight, so there it opens upwards.
    const aim = () => {
      const pane = wrap.closest('.ws-pnl-body') || document.documentElement;
      const below = pane.getBoundingClientRect().bottom - wrap.getBoundingClientRect().bottom;
      wrap.classList.toggle('hint-up', below < 110);
    };
    info.addEventListener('mouseenter', aim);
    info.addEventListener('focus', aim);
    info.addEventListener('click', () => {
      const open = wrap.classList.toggle('hint-open');
      info.setAttribute('aria-expanded', String(open));
    });
    info.addEventListener('blur', () => {
      wrap.classList.remove('hint-open');
      info.setAttribute('aria-expanded', 'false');
    });
    return wrap;
  }
  wrap.innerHTML = `
    <div class="setting-head"><span class="setting-name">${label}</span>
      ${head}</div>
    ${control}
    <span class="setting-hint">${hint}</span>`;
  return wrap;
}

// The forest card draws a sample of land as its sliders move, from the same
// code the map is drawn with (/api/forest-preview), so what is seen is what
// is got. The old picture stays until the new one has loaded.
function forestPreview(card, group) {
  const fig = document.createElement('figure');
  fig.className = 'forest-preview';
  // Sticky: it stays at the top of the panel while the card's own sliders
  // scroll under it, so a slider far down Advanced still has its picture.
  fig.innerHTML = `<img alt="A sample of forest with these settings" width="300" height="300"
    title="300 m of woods, a road, houses and a field, as these settings draw them.">`;
  const img = fig.querySelector('img');
  const keys = groupKeys(group).filter(k => !NOT_IN_PREVIEW.has(k));
  let timer = null;
  const refresh = () => {
    const q = new URLSearchParams();
    for (const key of keys) {
      const el = card.querySelector(`[data-key="${key}"]`);
      if (el && el.value !== '') q.set(key, el.value);
    }
    const next = new Image();
    next.onload = () => { img.src = next.src; };
    next.src = `/api/forest-preview?${q}`;
  };
  card.addEventListener('input', e => {
    if (!keys.includes(e.target.dataset?.key)) return;
    clearTimeout(timer);
    timer = setTimeout(refresh, 150);
  });
  setTimeout(refresh, 0);       // once the card's sliders are in it
  // Pinned at the top of the panel, the picture would leave a short panel
  // no room for the sliders it shows, so it takes at most under half the
  // panel's height, never less than 120 px; a taller panel gets a bigger one.
  if (typeof ResizeObserver === 'function') {
    let pane = null;
    const fit = () => {
      if (!pane || !pane.clientHeight) return;
      const size = Math.max(120, Math.min(300, Math.round(pane.clientHeight * 0.45)));
      img.style.maxWidth = `${size}px`;
    };
    const watch = new ResizeObserver(fit);
    const attach = () => {
      pane = fig.closest('.ws-pnl-body');
      if (pane) { watch.observe(pane); fit(); } else setTimeout(attach, 200);
    };
    setTimeout(attach, 0);
  }
  return fig;
}

function settingGroup(name, group, values) {
  const card = document.createElement('section');
  card.className = 'setting-group';
  card.dataset.group = name;
  card.innerHTML = `<div class="setting-group-head"><span class="setting-group-title">${group.title}</span>
    <button type="button" class="linkish group-reset">Reset</button></div>`;
  const add = (parent, key) => {
    if (!(key in settingsMeta.defaults) || !SETTING_LABELS[key]) return;
    const [label, hint] = SETTING_LABELS[key];
    const el = settingElement(key, label, hint, values, true);
    if (NOT_IN_PREVIEW.has(key)) {
      el.classList.add('not-in-preview');
      el.querySelector('.setting-hint').insertAdjacentHTML('beforeend',
        ' <span class="setting-note">Not shown in the picture.</span>');
    }
    parent.appendChild(el);
  };
  if (group.preview) card.appendChild(forestPreview(card, group));
  group.main.forEach(key => add(card, key));
  const advanced = document.createElement('details');
  advanced.className = 'setting-group-advanced';
  advanced.innerHTML = '<summary>Advanced</summary>';
  for (const [title, keys] of group.advanced) {
    const head = document.createElement('div');
    head.className = 'setting-subhead';
    head.textContent = title;
    advanced.appendChild(head);
    keys.forEach(key => add(advanced, key));
  }
  // Open or closed is remembered in this browser; a private window that
  // refuses storage just starts closed.
  const remember = `knoxmap.${name}.advanced`;
  try { advanced.open = localStorage.getItem(remember) === '1'; } catch (e) { /* no storage */ }
  advanced.addEventListener('toggle', () => {
    // A search that opened the panel is not the user choosing it open.
    if (advanced.dataset.searchOpened) { delete advanced.dataset.searchOpened; return; }
    try { localStorage.setItem(remember, advanced.open ? '1' : '0'); } catch (e) { /* no storage */ }
  });
  if (group.advanced.length) card.appendChild(advanced);
  card.querySelector('.group-reset').addEventListener('click', () => resetGroup(card, group));
  return card;
}

// The card's own keys back to the chosen kind of place's values, and nothing
// else: Reset at the bottom of the list still does every setting.
function resetGroup(card, group) {
  const preset = settingsMeta.presets[document.getElementById('preset').value]
    || settingsMeta.defaults;
  for (const key of groupKeys(group)) {
    const el = card.querySelector(`[data-key="${key}"]`);
    if (!el || !(key in preset)) continue;
    if (el.type === 'checkbox') el.checked = !!preset[key];
    else el.value = preset[key];
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
}

// Which tab is open is remembered in this browser, as each Advanced is.
const TAB_KEY = 'knoxmap.settings.tab';

function settingTabs() {
  const tabs = Object.entries(SETTING_GROUPS);
  const listed = new Set(tabs.flatMap(([, group]) => groupKeys(group)));
  const rest = Object.keys(SETTING_LABELS)
    .filter(key => key in settingsMeta.defaults && !listed.has(key));
  if (rest.length) tabs.push(['other', { title: 'Other', main: rest, advanced: [] }]);
  return tabs;
}

function buildSettingsForm(values) {
  const body = document.getElementById('advanced-body');
  body.innerHTML = '';
  const bar = document.createElement('div');
  bar.className = 'setting-tabs';
  bar.setAttribute('role', 'tablist');
  bar.setAttribute('aria-label', 'Settings');
  body.appendChild(bar);
  for (const [name, group] of settingTabs()) {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'setting-tab';
    tab.id = `setting-tab-${name}`;
    tab.dataset.tab = name;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', `setting-panel-${name}`);
    tab.innerHTML = `<span class="setting-tab-name">${group.title}</span>`
      + '<span class="setting-tab-dot" title="Changed from the defaults for this kind of place" hidden></span>'
      + '<span class="setting-tab-count"></span>';
    tab.addEventListener('click', () => {
      // A tab picked mid-search is the user done searching.
      const find = document.getElementById('settingFind');
      if (find && find.value) {
        find.value = '';
        find.dispatchEvent(new Event('input'));
      }
      openSettingTab(name, true);
    });
    bar.appendChild(tab);
    const card = settingGroup(name, group, values);
    card.id = `setting-panel-${name}`;
    card.setAttribute('role', 'tabpanel');
    card.setAttribute('aria-labelledby', tab.id);
    body.appendChild(card);
  }
  bar.addEventListener('keydown', e => {
    const tabs = [...bar.querySelectorAll('.setting-tab')];
    const at = tabs.indexOf(document.activeElement);
    if (at < 0) return;
    const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    const next = tabs[(to + tabs.length) % tabs.length];
    next.focus();
    next.click();
  });
  let open = null;
  try { open = localStorage.getItem(TAB_KEY); } catch (e) { /* no storage */ }
  openSettingTab(body.querySelector(`[data-tab="${open}"]`) ? open : settingTabs()[0][0]);
  fx.wireSettings(body);
  markChangedTabs();
  runListSearch('advanced-body');
  const topTerrain = document.getElementById('terrainOnlyToggle');
  if (topTerrain) topTerrain.checked = !!values.terrain_only;
}

function openSettingTab(name, remember = false) {
  const body = document.getElementById('advanced-body');
  for (const tab of body.querySelectorAll('.setting-tab')) {
    const on = tab.dataset.tab === name;
    tab.classList.toggle('is-on', on);
    tab.setAttribute('aria-selected', String(on));
    tab.tabIndex = on ? 0 : -1;
  }
  for (const card of body.querySelectorAll('.setting-group')) {
    card.classList.toggle('is-on', card.dataset.group === name);
  }
  if (remember) {
    try { localStorage.setItem(TAB_KEY, name); } catch (e) { /* no storage */ }
  }
}

// A dot on a tab that holds a setting moved off the kind of place's value, so
// a change is not lost behind a tab or a closed Advanced.
function differs(el, want) {
  if (want === undefined) return false;
  if (el.type === 'checkbox') return el.checked !== !!want;
  if (el.tagName === 'SELECT') return el.value !== String(want);
  if (el.value.trim() === '') return false;
  return Math.abs(parseFloat(el.value) - Number(want)) > 1e-9;
}

function markChangedTabs() {
  if (!settingsMeta) return;
  const body = document.getElementById('advanced-body');
  const preset = settingsMeta.presets[document.getElementById('preset').value]
    || settingsMeta.defaults;
  for (const card of body.querySelectorAll('.setting-group')) {
    const moved = [...card.querySelectorAll('[data-key]')]
      .some(el => differs(el, preset[el.dataset.key] ?? settingsMeta.defaults[el.dataset.key]));
    const dot = body.querySelector(`#setting-tab-${card.dataset.group} .setting-tab-dot`);
    if (dot) dot.hidden = !moved;
  }
}

// While the settings are searched every tab shows what it matched, with a
// count on its tab; an empty box is back to the one open tab.
function showSearchAcrossTabs(query) {
  const body = document.getElementById('advanced-body');
  const searching = Boolean(query.trim());
  body.classList.toggle('searching', searching);
  for (const card of body.querySelectorAll('.setting-group')) {
    const count = body.querySelector(`#setting-tab-${card.dataset.group} .setting-tab-count`);
    if (!count) continue;
    const n = card.querySelectorAll('.setting:not(.out-of-search)').length;
    count.textContent = searching ? String(n) : '';
    count.parentElement.classList.toggle('found-none', searching && !n);
  }
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
document.getElementById('advanced-body').addEventListener('input', markChangedTabs);
document.getElementById('advanced-body').addEventListener('change', markChangedTabs);
document.getElementById('advanced-body').addEventListener('listsearch',
  e => showSearchAcrossTabs(e.detail.query));
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

