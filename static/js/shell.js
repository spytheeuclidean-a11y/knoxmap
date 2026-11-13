// KnoxMap's workspace.
//
// The page's controls are written once, in templates/index.html, and app.js
// drives them as it always has. This file arranges them into a workspace:
//
//   menu bar   File Edit View Map Build Help, the place search, the credit
//   options    what the chosen tool can do
//   tools      a panel on the left, a tab for each way of working on the map:
//              Extent, Features, Zones, Change what is here, Build
//   tabs       Home, the maps open in this window, a new one being drawn
//   steps      Generate > Buildings > Compile > Install > Publish check, and one
//              button that does whatever comes next
//   the map    with Home over it, or the game's world for placing it
//   panels     Properties (follows the tool) and Layers, which float, dock and
//              resize
//
// Nothing here does a step's work: a step's button here presses the step's own
// button, and a step's card is the step's own card, moved. So everything app.js
// already does - progress, Stop, errors, the census, retries - works unchanged.
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const make = (tag, cls, html) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  };
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const click = id => { const b = $(id); if (b && !b.disabled) b.click(); };

  const ws = {
    home: true,              // Home is showing
    draft: false,            // a new map is being drawn, not yet generated
    tabs: [],                // maps open in this window, by name
    popped: [],              // maps popped out into their own windows
    tool: 'area',
    view: 'place',           // 'place' (the real map) or 'world' (the game's)
    pop: null,               // the step whose card is open
  };

  // =========================== the frame ===========================
  const body = document.body;
  const top = document.querySelector('header.topbar');
  const main = document.querySelector('main');
  const pane = $('map-pane');
  const controls = $('controls');
  const results = $('results');

  // Anything moved out of sight is kept here, never thrown away: its handlers
  // stay wired, and it comes back when it is wanted.
  const holder = make('div', 'ws-holder');
  holder.id = 'wsHolder';
  body.appendChild(holder);
  holder.appendChild(results);

  // Menu bar: the logo and name, the menus, the search, the credit, the rest.
  const menuSlot = make('nav', 'ws-menus');
  menuSlot.setAttribute('aria-label', 'Menus');
  menuSlot.style.display = 'flex';
  top.querySelector('h1').after(menuSlot);
  menuSlot.after($('search-box'));

  // The window's language: a small menu by the version, in each language's own
  // name. The list is i18n.js's (#language), filled once the server answers.
  const langMenu = make('div', 'ws-menu ws-langmenu');
  langMenu.innerHTML = `<button type="button" class="ws-lang" title="The window’s language">🌐 <span>English</span></button>
    <div class="ws-drop" style="left:auto;right:0;min-width:200px"></div>`;
  top.querySelector('.version-wrap').before(langMenu);
  const langSelect = $('language');
  const langShown = () => {
    const o = langSelect && langSelect.selectedOptions[0];
    langMenu.querySelector('span').textContent = o ? o.textContent : 'English';
    langMenu.hidden = !langSelect || langSelect.options.length < 2;
  };
  if (langSelect) new MutationObserver(langShown).observe(langSelect, { childList: true, subtree: true, attributes: true });
  langMenu.querySelector('button').addEventListener('click', e => {
    e.stopPropagation();
    const open = langMenu.classList.contains('open');
    closeMenusSoon();
    if (open) return;
    langMenu.querySelector('.ws-drop').innerHTML = [...(langSelect ? langSelect.options : [])].map(o =>
      `<button type="button" data-lang="${esc(o.value)}"><span class="mark">${o.selected ? '•' : ''}</span>${esc(o.textContent)}</button>`).join('')
      + '<hr><div class="label" style="text-transform:none">Missing yours? Copy lang/english.txt, translate it, and it shows up here.</div>';
    langMenu.classList.add('open');
  });
  langMenu.addEventListener('click', e => {
    const b = e.target.closest('[data-lang]');
    if (!b) return;
    langMenu.classList.remove('open');
    langSelect.value = b.dataset.lang;
    langSelect.dispatchEvent(new Event('change'));
    langShown();
  });
  document.addEventListener('click', e => { if (!e.target.closest('.ws-langmenu')) langMenu.classList.remove('open'); });
  function closeMenusSoon() { document.querySelectorAll('.ws-menu.open').forEach(m => m.classList.remove('open')); }
  langShown();

  // The setup warning, as a bar under the menus.
  top.after($('setupCard'));

  const options = make('div', 'ws-options');
  options.setAttribute('aria-label', 'Tool options');
  $('setupCard').after(options);

  // Work area: tools | tabs, steps and map | splitter | panels.
  const tools = make('section', 'ws-tools-pnl');
  tools.id = 'wsTools';
  tools.setAttribute('aria-label', 'Tools');
  tools.innerHTML = `<div class="ws-tools-head">Tools</div><div class="ws-tools-body">
    <div class="setting-tabs ws-tool-tabs" role="tablist" aria-label="Tools"></div>
    <div class="ws-tool-panes"></div></div>`;
  const center = make('div', 'ws-center');
  const tabs = make('div', 'ws-tabs');
  tabs.setAttribute('aria-label', 'Open maps');
  const flow = make('div', 'ws-flow');
  flow.setAttribute('aria-label', 'Steps');
  flow.hidden = true;
  // Redrawn as steps move; the open card beside it is never touched, so a field
  // being typed in keeps its cursor.
  const flowRow = make('div');
  flowRow.style.display = 'contents';
  flow.appendChild(flowRow);
  const upgrade = $('upgradeNote');
  upgrade.classList.add('ws-upgrade');
  main.insertBefore(tools, pane);
  main.insertBefore(center, pane);
  center.append(tabs, flow, upgrade, pane);
  const vsplit = make('div', 'ws-vsplit');
  vsplit.title = 'Drag to make the panels wider or narrower. Double-click to reset';
  main.insertBefore(vsplit, controls);

  // Home, over the map.
  const home = make('div', 'ws-home');
  home.id = 'wsHome';
  pane.appendChild(home);
  // The game's world, for placing the map, over the map too.
  const world = make('div', 'ws-world');
  world.hidden = true;
  pane.appendChild(world);
  // The 2.5D isometric in-game view over the map.
  const isoView = make('div', 'ws-iso');
  isoView.id = 'wsIso';
  isoView.hidden = true;
  pane.appendChild(isoView);
  const guideV = make('div', 'ws-guide v'), guideH = make('div', 'ws-guide h');
  pane.append(guideV, guideH);

  // Status bar.
  const status = make('footer', 'ws-status');
  status.setAttribute('aria-label', 'Status');
  const statusRight = make('span', 'right');
  status.append($('status'), statusRight);
  body.insertBefore(status, $('board'));

  // ------------------- the panels: Properties and Layers -------------------
  const sections = [...controls.children];
  const byCard = k => controls.querySelector(`.panel[data-card="${k}"]`);
  const areaCard = byCard('area'), styleCard = byCard('style'), makeCard = byCard('make'),
    genCard = byCard('generate');

  function panel(id, title) {
    const p = make('section', 'ws-pnl');
    p.id = id;
    p.innerHTML = `<div class="ws-pnl-head"><button class="tw" aria-label="Fold" type="button">▾</button>
      <span class="ttl">${title}</span><span class="acts"><button type="button" data-pop-panel title="Pop out, or dock again">
      <svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-8 8M18 14v5H5V6h5"/></svg></button></span></div>
      <div class="ws-pnl-body"></div><div class="ws-grip" title="Drag to make this panel taller or shorter. Double-click to reset"></div>`;
    return p;
  }
  const props = panel('wsProps', 'Properties');
  // Layers is a legend floating on the map, over its bottom-left corner; Home,
  // the game's world and the 2.5D view cover it, as it is only of the map.
  const layers = make('section', 'ws-legend');
  layers.id = 'wsLayers';
  layers.setAttribute('aria-label', 'Layers');
  layers.innerHTML = `<div class="ws-legend-head"><button class="tw" aria-label="Fold" type="button">▾</button>
    <span class="ttl">Layers</span></div><div class="ws-legend-body"></div>`;
  // Named places, the same, at the top right under the basemaps: the button
  // and the list it finds, folded away when it is in the way.
  const places = make('section', 'ws-legend ws-places');
  places.id = 'wsPlaces';
  places.setAttribute('aria-label', 'Named places');
  places.innerHTML = `<div class="ws-legend-head"><button class="tw" aria-label="Fold" type="button">▾</button>
    <span class="ttl">Named places</span><span class="count" id="landmarkCount"></span></div>
    <div class="ws-legend-body"></div>`;
  const propsBody = props.querySelector('.ws-pnl-body');
  // On the page before anything moves into them: app.js finds its controls by id.
  controls.prepend(props);
  pane.append(layers, places);

  // Properties, part one: the map's settings - the area is in their Map tab.
  const mapProps = make('div', 'ws-mapprops');
  mapProps.style.cssText = 'display:flex;flex-direction:column;gap:10px';
  // Part two: the tool's own panel, when a tool has one.
  propsBody.append(mapProps);
  mapProps.append(make('div', 'ws-sub-h', 'Map settings'));
  for (const node of [...styleCard.children]) {
    if (node.matches('h2') || node.id === 'steamLibraries' || node.id === 'zomboidFolderBox') continue;
    mapProps.append(node);
  }
  for (const node of [...areaCard.children]) {
    if (node.matches('h2') || node.id === 'presetsPanel') continue;
    if (node.id === 'landmark-panel') places.querySelector('.ws-legend-body').append(node);
    else if (node.id === 'coordsBox') continue;      // the Tools panel's Area tab has it
    else mapProps.append(node);
  }
  holder.append($('handBuilt'));
  // The Generate button and the drawing board's button are pressed from here.
  holder.append(genCard, makeCard);
  // Setup checks and preferences open as dialogs.
  holder.append($('healthCard'), $('overpassCard'), $('steamLibraries'), $('zomboidFolderBox'));
  // Your maps and saved areas live on Home.
  const mapsCard = $('mapsCard');
  const presets = $('presetsPanel');
  for (const s of sections) if (s.parentNode === controls) holder.append(s);

  // =========================== menus ===========================
  // Each item presses the control it stands for, and is greyed out when that
  // control is: the menu cannot drift from what the window can do.
  const MENUS = ['File', 'Edit', 'View', 'Map', 'Build', 'Tools', 'Help'];
  for (const name of MENUS) {
    const m = make('div', 'ws-menu');
    m.innerHTML = `<button type="button">${name}</button><div class="ws-drop" data-menu="${name}"></div>`;
    menuSlot.appendChild(m);
  }
  const menus = [...menuSlot.querySelectorAll('.ws-menu')];
  const closeMenus = () => menus.forEach(m => m.classList.remove('open'));
  menus.forEach(m => {
    const b = m.querySelector(':scope > button');
    b.addEventListener('click', e => {
      e.stopPropagation();
      const was = m.classList.contains('open');
      closeMenus();
      if (!was) { fillMenu(m.querySelector('.ws-drop')); m.classList.add('open'); }
    });
    b.addEventListener('mouseenter', () => {
      if (menus.some(o => o.classList.contains('open')) && !m.classList.contains('open')) {
        closeMenus(); fillMenu(m.querySelector('.ws-drop')); m.classList.add('open');
      }
    });
  });
  document.addEventListener('click', e => { if (!e.target.closest('.ws-menu')) closeMenus(); });

  const off = id => { const b = $(id); return !b || b.disabled; };
  const ACTIONS = {};
  let actionN = 0;
  function item(label, run, o = {}) {
    const id = `a${actionN++}`;
    ACTIONS[id] = run;
    return `<button type="button" data-ws-act="${id}" ${o.off ? 'disabled' : ''} title="${esc(o.title || '')}">`
      + `<span class="mark">${o.on ? (o.radio ? '•' : '✓') : ''}</span>${esc(label)}${o.key ? `<kbd>${o.key}</kbd>` : ''}</button>`;
  }
  const label = t => `<div class="label">${t}</div>`;
  let myMaps = [];
  async function refreshMyMaps() {
    try { myMaps = (await (await fetch('/api/maps')).json()).maps || []; } catch (_) { /* keep the last list */ }
  }
  function fillMenu(drop) {
    actionN = 0;
    for (const k of Object.keys(ACTIONS)) delete ACTIONS[k];
    const open = !!currentMap, busy = !!runningMap;
    const h = {
      File: () => item('New map', newMap, { key: 'Ctrl+N' })
        + item('Home', goHome, { key: 'Ctrl+H' })
        + label('Open') + (myMaps.length ? myMaps.slice(0, 12).map(m =>
            item(m.mapName, () => openTab(m.mapName), { on: m.mapName === currentMap, radio: true })).join('')
          : '<div class="label" style="text-transform:none">No maps yet</div>')
        + item('Close this map', () => closeTab(currentMap), { key: 'Ctrl+W', off: !open })
        + item('Delete this map', () => (typeof deleteMap === 'function' ? deleteMap(currentMap) : null), { off: !open })
        + '<hr>' + label('Saved areas')
        + item('Save this area…', () => { goHome(); $('presetName').focus(); }, { off: !currentRect })
        + item('Export to a file…', () => click('presetExport'), { off: !currentRect })
        + item('Import a file…', () => click('presetImport'))
        + item('Copy a link to this area', () => click('presetShare'), { off: !currentRect })
        + item('Open a link…', () => click('presetOpenLink'))
        + '<hr>' + item('Draw a map from scratch…', () => click('boardOpen'))
        + '<hr>' + item('Save everything as a zip', () => $('downloadAll').click(), { off: !open })
        + item('Single files…', () => openPop('generate'), { off: !open }),
      Edit: () => label('Draw on the map')
        + item('Extent', () => setTool('area'), { key: 'X' })
        + item('Features', () => setTool('draw'), { key: 'F' })
        + item('Zones of their own', () => setTool('zone'), { key: 'Z' })
        + item('Change what is already here', () => setTool('change'), { key: 'E' })
        + '<hr>' + label('Hand-built buildings')
        + item('Build a building by hand…', () => click('builderOpen'))
        + item('Your hand-built buildings…', () => dialog('Hand-built buildings', [$('handBuilt')]))
        + '<hr>' + label('Preferences')
        + item('Map data server…', () => dialog('Map data server', [$('overpassCard')]))
        + item('Steam libraries…', () => dialog('Steam libraries', [$('steamLibraries')]))
        + item('Where maps are installed…', () => dialog('Where maps are installed', [$('zomboidFolderBox')]))
        + item('Language…', () => setTimeout(() => langMenu.querySelector('button').click(), 0)),
      View: () => item('Real place', () => setView('place'), { on: ws.view === 'place', radio: true, off: !open })
        + item('Game world', () => setView('world'), { on: ws.view === 'world', radio: true, off: !open })
        + item('In-game 2.5D', () => setView('iso'), { on: ws.view === 'iso', radio: true, off: !open })
        + label('Basemap')
        + [...document.querySelectorAll('#basemaps button')].map(b =>
            item(b.textContent, () => b.click(), { on: b.classList.contains('is-on'), radio: true })).join('')
        + label('After building')
        + item('What was built…', () => openPop('build'), { off: !open })
        + item('Draw a picture of it', () => click('makePictures'), { off: !open || off('makePictures') })
        + label('Panels')
        + item('Properties', () => togglePanel(props), { on: !props.hidden })
        + item('Layers', () => togglePanel(layers), { on: !layers.hidden })
        + item('Named places', () => togglePanel(places), { on: !places.hidden })
        + item('Reset the layout', resetLayout),
      Map: () => label('Kind of place')
        + [...document.querySelectorAll('#presetCards .preset-card')].map(c =>
            item(c.textContent, () => c.click(), { on: c.classList.contains('is-on'), radio: true })).join('')
        + item('Reset the settings to this kind', () => click('resetSettings'))
        + '<hr>' + item('Standalone: play it without Knox County', () => { setView('world'); $('placeStandalone').click(); },
            { on: $('placeStandalone').checked, off: !open || busy })
        + item('Place it in the world…', () => setView('world'), { off: !open })
        + '<hr>' + item('List named places in the area', () => click('landmarksBtn'), { off: off('landmarksBtn') }),
      Build: () => {
        const n = nextAction();
        return item(n && n.run ? `Next: ${n.label}` : 'Next step', () => n && n.run && n.run(), { key: 'F5', off: !n || !n.run })
          + item('Stop', () => requestStop(), { off: !runningMap })
          + '<hr>'
          + item('Generate map', () => click('generateBtn'), { off: off('generateBtn') || !currentRect })
          + item('Build the buildings', () => click('buildingsBtn'), { off: !open || off('buildingsBtn') })
          + item('Recount the zombies', () => click('recountBtn'), { off: !open || off('recountBtn'),
              title: 'After a zombie setting changed: seconds, no rebuild' })
          + item('Compile', () => click('compileBtn'), { off: !open || off('compileBtn') })
          + item('Compile the cells that failed', () => click('retryCellsBtn'), { off: $('retryCellsBtn').hidden })
          + item('Open in WorldEd', () => click('worldedBtn'), { off: !open || off('worldedBtn') })
          + item('Install', () => click('installBtn'), { off: !open || off('installBtn') })
          + item('Check before publishing', () => click('publishCheckBtn'), { off: $('publishCard').hidden });
      },
      Tools: () => item('Check an OpenStreetMap extract…', () => dialog('Tools', [$('toolsBody')]))
        + item('Pick an extract file…', () => {
          dialog('Tools', [$('toolsBody')]);
          setTimeout(() => { const b = $('pbfBrowse'); if (b) b.click(); }, 0);
        })
        + item('Choose the extract by area again', () => click('pbfClear'))
        + '<hr>' + label('What the tool does')
        + '<div class="hint" style="padding:4px 8px;max-width:32em">A picked .osm.pbf is'
        + ' read by every map in place of the regional file KnoxMap would download.'
        + ' Check reports whether it is whole, what it covers, and whether there are'
        + ' roads and buildings in it. The same check runs as tools/verify_pbf.py.</div>'
        + '<hr>' + item('Map data server…', () => dialog('Map data server', [$('overpassCard')]))
        + '<hr>' + item('Road & sidewalk inspector…',
          () => window.openRoadInspector && window.openRoadInspector(currentMap), { off: !open }),
      Help: () => item('Check my setup…', () => { dialog('Check my setup', [$('healthCard')]); click('healthBtn'); })
        + item('Discord', () => { const a = top.querySelector('.byline a[href*="discord"]'); if (a) a.click(); })
        + item('Report a problem', () => click('reportLink'))
        + '<hr>' + item('About KnoxMap', about),
    };
    drop.innerHTML = h[drop.dataset.menu]();
  }
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-ws-act]');
    if (!b || b.disabled) return;
    closeMenus();
    const run = ACTIONS[b.dataset.wsAct];
    if (run) run();
  });

  // =========================== dialogs ===========================
  const dlg = make('div', 'ws-dialog');
  dlg.hidden = true;
  body.appendChild(dlg);
  let dlgNodes = [];
  function dialog(title, nodes) {
    closeDialog();
    dlg.innerHTML = `<div class="ws-card" role="dialog" aria-label="${esc(title)}"><h3>${esc(title)}
      <button type="button" class="btn btn-small" data-ws-close>Close</button></h3></div>`;
    const card = dlg.firstElementChild;
    dlgNodes = nodes.filter(Boolean);
    for (const n of dlgNodes) {
      n.hidden = false;
      card.appendChild(n);
      n.querySelectorAll('details').forEach(d => { d.open = true; });
      if (n.matches('details')) n.open = true;
    }
    dlg.hidden = false;
  }
  function closeDialog() {
    for (const n of dlgNodes) holder.appendChild(n);
    dlgNodes = [];
    dlg.hidden = true;
  }
  dlg.addEventListener('click', e => { if (e.target === dlg || e.target.closest('[data-ws-close]')) closeDialog(); });
  function about() {
    dialog('About KnoxMap', []);
    dlg.firstElementChild.insertAdjacentHTML('beforeend', `<p style="margin:0">Real places as Project Zomboid maps,
      by <b>euclid80tr</b>.</p><p class="hint" style="margin:0">Map data © OpenStreetMap contributors (ODbL).
      Project Zomboid is The Indie Stone’s.</p>`);
  }

  // =========================== tools ===========================
  // A tab each, in the Tools panel on the left; under it, that tool's own
  // controls. The map's drawing buttons, and what a drawing in progress
  // shows (Finish, Cancel, Save), are pressed from the Area tab.
  const TOOLS = [
    { id: 'area', icon: '📐', key: 'X', label: 'Extent', title: 'The extent of the map: draw it as a rectangle, a polygon, a circle or freehand, or type its corners' },
    { id: 'draw', icon: '✏️', key: 'F', label: 'Features', title: 'Features to add to the map: a street, a house, a park… built like a real one',
      panel: 'sketch' },
    { id: 'zone', icon: '🧩', key: 'Z', label: 'Zones', title: 'Zones: a part of the map with settings of its own',
      panel: 'zonesPanel' },
    { id: 'change', icon: '🔧', key: 'E', label: 'Change', title: 'Change what is already here: remove or reshape what the map was built from',
      panel: 'editMap' },
    { id: 'make', icon: '🏗️', key: 'B', label: 'Build', title: 'Build a building by hand, or draw a map from scratch' },
  ];
  const toolTabs = tools.querySelector('.ws-tool-tabs');
  const toolPanes = tools.querySelector('.ws-tool-panes');
  const TOOL_PANE = {
    area: `<p class="hint">Draw the area to make. Reshape to move its corners or turn it by the handle above it.</p>
      <div class="ws-draw-btns">
        <button type="button" class="btn" data-draw="rectangle" title="Drag out a box"><span aria-hidden="true">▭</span> Rectangle</button>
        <button type="button" class="btn" data-draw="polygon" title="Click its corners one by one; click the first again to finish"><span aria-hidden="true">⬠</span> Polygon</button>
        <button type="button" class="btn" data-draw="circle" title="Drag out from the middle"><span aria-hidden="true">◯</span> Circle</button>
        <button type="button" class="btn" data-draw="lasso" title="Drag round the area you want"><span aria-hidden="true">✎</span> Freehand</button>
      </div>
      <div class="ws-draw-acts" hidden></div>
      <div class="ws-draw-btns">
        <button type="button" class="btn btn-small" data-draw="edit" title="Drag its corners, then Save">${KnoxDraw.icon('move')}<span>Reshape</span></button>
        <button type="button" class="btn btn-small kd-danger" data-opt="clear">${KnoxDraw.icon('trash')}<span>Clear the area</span></button>
      </div>
      <div class="ws-sub-h">Corners</div>
      <p class="hint">Or type them, in degrees, and Use these corners.</p>`,
    make: `<p class="hint">A building of your own, room by room, to place on a map.</p>
      <button type="button" class="btn" data-once="builderOpen">Build a building by hand</button>
      <p class="hint">A map with nothing real under it: roads, houses and land drawn on a blank sheet.</p>
      <button type="button" class="btn" data-once="boardOpen">Draw a map from scratch</button>`,
  };
  for (const t of TOOLS) {
    const tab = make('button', 'setting-tab',
      `<span class="setting-tab-icon" aria-hidden="true">${t.icon}</span><span>${esc(t.label)}</span>`);
    tab.type = 'button';
    tab.dataset.tool = t.id;
    tab.title = `${t.title} (${t.key})`;
    tab.setAttribute('role', 'tab');
    toolTabs.appendChild(tab);
    const pane = make('div', 'ws-tool-pane ws-toolpanel', TOOL_PANE[t.id] || '');
    pane.dataset.toolPane = t.id;
    pane.setAttribute('role', 'tabpanel');
    if (t.panel) { const node = $(t.panel); node.open = true; pane.appendChild(node); }
    if (t.id === 'area') pane.appendChild($('coordsBox'));
    toolPanes.appendChild(pane);
  }
  // The Change tab's buttons get the same icons as the drawing ones.
  for (const [id, ico] of [['editLoad', 'load'], ['editShape', 'move'], ['editSave', 'save'], ['editReset', 'reset']]) {
    const b = $(id);
    if (b && !b.querySelector('.kd-ico')) b.insertAdjacentHTML('afterbegin', KnoxDraw.icon(ico));
  }
  const DRAW_BUTTON = {
    rectangle: '.leaflet-draw-draw-rectangle', polygon: '.leaflet-draw-draw-polygon',
    circle: '.leaflet-draw-draw-circle', lasso: '.lasso-btn', edit: '.leaflet-draw-edit-edit',
  };
  function areaOption(opt) {
    if (opt === 'clear') {
      drawnItems.clearLayers();
      if (typeof removeRotateHandle === 'function') removeRotateHandle();
      currentRect = null;
      if (typeof clearBboxFields === 'function') clearBboxFields();
      render();
    }
  }
  // While a shape is being drawn or reshaped, what finishes it - Finish,
  // Delete last point, Cancel, Save - is here under the drawing buttons. The
  // buttons press the map toolbar's own, which stays hidden.
  const drawActs = toolPanes.querySelector('.ws-draw-acts');
  let drawLinks = [];
  function showDrawActions() {
    requestAnimationFrame(() => {
      const list = [...map.getContainer().querySelectorAll('.leaflet-draw-actions')]
        .find(ul => ul.style.display === 'block');
      drawLinks = list ? [...list.querySelectorAll('li')]
        .filter(li => getComputedStyle(li).display !== 'none').map(li => li.querySelector('a')).filter(Boolean) : [];
      drawActs.innerHTML = drawLinks.map((a, i) => `<button type="button" class="btn btn-small${
        /finish|save/i.test(a.textContent) ? ' btn-primary' : ''}" data-act="${i}" title="${esc(a.title || '')}">${
        esc(a.textContent)}</button>`).join('');
      drawActs.hidden = !drawLinks.length;
    });
  }
  function hideDrawActions() { drawLinks = []; drawActs.innerHTML = ''; drawActs.hidden = true; }
  map.on('draw:drawstart draw:editstart draw:deletestart', showDrawActions);
  map.on('draw:drawstop draw:editstop draw:deletestop', hideDrawActions);
  tools.addEventListener('click', e => {
    const act = e.target.closest('[data-act]');
    if (act) { drawLinks[+act.dataset.act]?.click(); return; }
    const tab = e.target.closest('.ws-tool-tabs [data-tool]');
    if (tab) return setTool(tab.dataset.tool);
    const draw = e.target.closest('[data-draw]');
    if (draw) map.getContainer().querySelector(DRAW_BUTTON[draw.dataset.draw])?.click();
    const opt = e.target.closest('[data-opt]');
    if (opt) areaOption(opt.dataset.opt);
    const once = e.target.closest('[data-once]');
    if (once) click(once.dataset.once);
  });
  toolTabs.addEventListener('keydown', e => {
    const all = [...toolTabs.children], at = all.indexOf(document.activeElement);
    const to = { ArrowRight: at + 1, ArrowLeft: at - 1 }[e.key];
    if (at < 0 || to === undefined) return;
    e.preventDefault();
    const next = all[(to + all.length) % all.length];
    next.focus(); next.click();
  });
  function renderTools() {
    // Nothing to work on at Home: the panel steps aside for it.
    const atHome = !!ws.home;
    if (body.classList.contains('ws-at-home') !== atHome) {
      body.classList.toggle('ws-at-home', atHome);
      requestAnimationFrame(() => map.invalidateSize());
    }
    for (const tab of toolTabs.children) {
      const on = tab.dataset.tool === ws.tool;
      tab.classList.toggle('is-on', on);
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
    }
    const area = toolPanes.querySelector('[data-tool-pane="area"]');
    area.querySelector('[data-opt="clear"]').disabled = !currentRect;
    area.querySelector('[data-draw="edit"]').disabled = !currentRect;
  }
  function setTool(id, quiet) {
    if (ws.home && !quiet) showMap();
    if (ws.view !== 'place') setView('place');
    ws.tool = id;
    for (const pane of toolPanes.children) pane.hidden = pane.dataset.toolPane !== id;
    if (id === 'zone' && typeof drawZoneList === 'function') drawZoneList();
    render();
  }
  function renderOptions() {
    let h;
    if (ws.home) h = '<b>Home</b><span>Start a map from a real place, or open one of your maps.</span>';
    else if (ws.view === 'world') h = '<b>Game world</b><span>Where the map sits in the world every installed map shares. '
      + 'Click to put it somewhere else; Standalone plays it on its own.</span>';
    else if (ws.view === 'iso') h = '<b>In-game 2.5D</b><span>2.5D isometric view of your town and furnished buildings. Pan and zoom with the mouse.</span>';
    else h = {
      area: '<b>Extent</b><span>Draw it with the buttons under Tools on the left: rectangle, polygon, circle or freehand. Reshape to move its corners or turn it.</span>',
      draw: '<b>Features</b><span>Pick what to draw under Tools on the left, then draw it on the map.</span>',
      zone: '<b>Zones</b><span>Press Draw a zone under Tools on the left, draw it on the map, then give it its own settings.</span>',
      make: '<b>Build</b><span>Build a building by hand, or draw a map from scratch on a blank sheet.</span>',
      change: '<b>Change what is here</b><span>Load what the map was built from, then click a building to see whether it was built and why not - or anything at all to remove it or say what it really is.</span>',
    }[ws.tool];
    if (runningMap && runningMap === currentMap && ['area', 'draw', 'zone', 'change'].includes(ws.tool))
      h = `<span class="lock">This map is busy. Editing it now would not reach the step that is running.</span> ${h}`;
    options.innerHTML = h;
  }

  // =========================== tabs and Home ===========================
  function renderTabs() {
    const busyMap = runningMap;
    let h = `<div class="ws-tab home ${ws.home ? 'on' : ''}" data-tab-home title="Home: start a map, or open one you made">⌂ Home</div>`;
    for (const name of ws.tabs) {
      if (ws.popped.includes(name)) continue;
      const on = !ws.home && !ws.draft && name === currentMap;
      h += `<div class="ws-tab ${on ? 'on' : ''}" data-tab="${esc(name)}" title="${esc(name)}. Drag it down to pop it out">
        <span class="nm">${esc(name)}</span>
        <button type="button" data-tab-pop="${esc(name)}" title="Pop out into its own window" aria-label="Pop out">⧉</button>
        <button type="button" data-tab-close="${esc(name)}" title="Close this map (Ctrl+W)" aria-label="Close">✕</button>
        ${busyMap === name ? '<span class="busy"></span>' : ''}</div>`;
    }
    if (ws.draft) h += `<div class="ws-tab on" data-tab-draft title="A new map, not generated yet">
      <span class="nm">New map</span><button type="button" data-tab-close-draft title="Close" aria-label="Close">✕</button></div>`;
    h += `<button type="button" class="newtab" data-tab-new title="New map (Ctrl+N)">＋</button>`;
    if (!ws.home && currentMap && !ws.draft) {
      h += `<span class="view"><button type="button" data-view="place" class="${ws.view === 'place' ? 'on' : ''}"
          title="The real place, where you choose and edit the area">Real place</button>
        <button type="button" data-view="world" class="${ws.view === 'world' ? 'on' : ''}"
          title="Where the map sits in the game’s world">Game world</button>
        <button type="button" data-view="iso" class="${ws.view === 'iso' ? 'on' : ''}"
          title="2.5D Isometric in-game view of your buildings and town">In-game 2.5D</button></span>`;
    }
    tabs.innerHTML = h;
  }
  tabs.addEventListener('click', e => {
    const t = e.target;
    if (t.closest('[data-tab-home]')) return goHome();
    if (t.closest('[data-tab-new]')) return newMap();
    const v = t.closest('[data-view]');
    if (v) return setView(v.dataset.view);
    const pop = t.closest('[data-tab-pop]');
    if (pop) return popOut(pop.dataset.tabPop);
    const close = t.closest('[data-tab-close]');
    if (close) return closeTab(close.dataset.tabClose);
    if (t.closest('[data-tab-close-draft]')) { ws.draft = false; return ws.tabs.length ? openTab(ws.tabs[ws.tabs.length - 1]) : goHome(); }
    if (t.closest('[data-tab-draft]')) return showMap();
  });

  function showMap() { ws.home = false; home.hidden = true; map.invalidateSize(); render(); }
  function goHome() { ws.home = true; renderHome(); home.hidden = false; refreshMyMaps(); if (typeof loadMaps === 'function') loadMaps(); render(); }
  function newMap() {
    if (busyElsewhere(null)) return;
    if (currentMap) leaveMap();
    ws.draft = true;
    showMap();
    setTool('area');
    $('searchInput').focus();
  }
  // Close the open map's step cards, as the old Close button did. The map
  // stays on disk; nothing is stopped or deleted.
  function leaveMap() {
    $('resultsClose').click();
    currentMap = null;
    ws.view = 'place';
    world.hidden = true;
    isoView.hidden = true;
    if (window.closeIsoView) window.closeIsoView();
    closePop();
  }
  // One map at a time is worked on: a step reports back to the cards of the map
  // that is open, so switching while one runs would put its result on another.
  function busyElsewhere(name) {
    if (!runningMap || runningMap === name) return false;
    fx.toast('bad', 'Busy', `${runningMap} is busy. Switch maps once it has finished, or Stop it.`, 6000);
    return true;
  }
  function openTab(name) {
    if (!name || busyElsewhere(name)) return;
    ws.draft = false;
    if (name === currentMap) { showMap(); return; }
    openMap(name);
  }
  function closeTab(name) {
    if (!name) return;
    if (runningMap === name) {
      fx.toast('bad', 'Busy', `${name} is busy. Stop it first, then close it.`, 6000);
      return;
    }
    ws.tabs = ws.tabs.filter(n => n !== name);
    ws.popped = ws.popped.filter(n => n !== name);
    document.querySelector(`.ws-docwin[data-map="${CSS.escape(name)}"]`)?.remove();
    if (name === currentMap) {
      leaveMap();
      const next = ws.tabs.filter(n => !ws.popped.includes(n)).pop();
      if (next) openTab(next); else goHome();
    }
    render();
  }

  // A map opened or just made: it gets a tab, and the workspace shows it.
  // A map opened from its tab, Home or the menu shows where it is: its area on
  // the map, its scale and its kind of place - not the last map's, and not the
  // defaults. Its settings are app.js's (openMap puts them back).
  function showMapArea(data) {
    const b = data.bbox;
    if (!b || b.south == null) return;
    let layer;
    if (data.shape && data.shape.type) {
      const polys = data.shape.type === 'Polygon' ? [data.shape.coordinates] : data.shape.coordinates;
      layer = L.polygon(polys.map(rings => rings.map(ring => ring.map(([lon, lat]) => [lat, lon]))), SEL_STYLE);
    } else layer = L.rectangle([[b.south, b.west], [b.north, b.east]], SEL_STYLE);
    $('metersPerTile').value = data.metersPerTile || 1;
    setSelection(layer);
    map.fitBounds(layer.getBounds(), { padding: [20, 20] });
    const kind = data.settings && data.settings.preset;
    if (kind && [...$('preset').options].some(o => o.value === kind)) {
      $('preset').value = kind;                    // no change event: that would reset its settings
      document.querySelectorAll('.preset-card').forEach(c => {
        const on = c.dataset.preset === kind;
        c.classList.toggle('is-on', on);
        c.setAttribute('aria-checked', on ? 'true' : 'false');
      });
    }
  }
  // An install that is still current counts as done: the steps used to say
  // Install was next for a map that was already in the game.
  function showInstalled(data) {
    const inst = data.installed;
    if (!inst || !inst.upToDate) return;
    const when = (inst.at || '').replace('T', ' ').slice(0, 16);
    note('installNote', `Installed${when ? ' ' + when : ''} to ${inst.modRoot}. Install again to replace it.`, 'ok');
    $('installBtn').disabled = false;
    $('publishCard').hidden = false;
  }

  // The placement check says "Ready to install" once it has loaded, after the
  // map opened: an install that is still current is said again after it. A
  // step run since makes that install out of date, so it is forgotten then.
  const originalSay = sayIfInstallable;
  sayIfInstallable = function () {
    const ok = originalSay();
    if (ok && ws.lastData && ws.lastData.mapName === currentMap) showInstalled(ws.lastData);
    return ok;
  };

  const originalRender = renderResults;
  renderResults = function (data) {
    const opening = data.mapName !== currentMap;
    originalRender(data);
    if (opening) showMapArea(data);
    showInstalled(data);
    if (!ws.tabs.includes(data.mapName)) ws.tabs.push(data.mapName);
    ws.popped = ws.popped.filter(n => n !== data.mapName);
    document.querySelector(`.ws-docwin[data-map="${CSS.escape(data.mapName)}"]`)?.remove();
    ws.draft = false;
    ws.lastData = data;
    showMap();
    if (ws.view === 'world') setView('world');
    else if (ws.view === 'iso') setView('iso');
  };

  // Home: where a new user starts, and where every map is.
  // Find a place: a box asking for a name, Nominatim's answers under it, and
  // the one picked opened as a new map with its extent drawn (goToPlace in
  // app.js). On the map: a new map to look round and draw on.
  const findBox = make('div', 'ws-find', `<div class="ws-find-row">
      <input type="search" id="wsFindInput" autocomplete="off"
        placeholder="A town, a city, a park, a coastline…" aria-label="Find a place">
      <button type="button" class="btn btn-primary" id="wsFindGo">Find</button></div>
    <ul class="ws-find-results" id="wsFindResults"></ul>`);
  holder.append(findBox);
  let findResults = [];
  function startRealPlace() {
    dialog('Find a place', [findBox]);
    setTimeout(() => $('wsFindInput').focus(), 0);
  }
  async function findPlace() {
    const q = $('wsFindInput').value.trim();
    const list = $('wsFindResults');
    if (!q) return;
    list.innerHTML = '<li class="empty">Searching…</li>';
    try {
      const res = await fetch('/api/search?' + new URLSearchParams({ q }));
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      findResults = data.results || [];
      list.innerHTML = findResults.length ? findResults.map((r, i) => {
        const where = r.display_name.split(',').slice(1).join(',').trim();
        return `<li><button type="button" data-find="${i}"><b>${esc(r.name)}</b>
          <span>${esc(where)}</span></button>${r.outline ? `<button type="button" class="btn btn-small"
          data-find-outline="${i}" title="Its real boundary instead of a box">outline</button>` : ''}</li>`;
      }).join('') : '<li class="empty">No matches.</li>';
    } catch (err) {
      list.innerHTML = `<li class="empty">${esc(err.message)}</li>`;
    }
  }
  findBox.addEventListener('click', e => {
    if (e.target.closest('#wsFindGo')) return findPlace();
    const pick = e.target.closest('[data-find], [data-find-outline]');
    if (!pick) return;
    const outline = pick.hasAttribute('data-find-outline');
    const r = findResults[+(outline ? pick.dataset.findOutline : pick.dataset.find)];
    closeDialog();
    newMap();
    // The map has only just been shown: let it take its size first.
    setTimeout(() => { map.invalidateSize(); if (outline) goToOutline(r); else goToPlace(r); }, 60);
  });
  findBox.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'wsFindInput') findPlace(); });
  function startOnMap() {
    newMap();
    $('searchInput').blur();
  }

  function renderHome() {
    if (home.dataset.built) return;
    home.dataset.built = '1';
    home.innerHTML = `<div class="ws-home-in">
      <div class="ws-hero"><h1>Make a Project Zomboid map of a real place</h1>
        <p>Any town, city or stretch of country in the world. KnoxMap builds its streets, houses, loot and zombies.</p>
        <!-- Three ways to start, each a picture of what it does. -->
        <div class="ws-starts">
          <button type="button" class="ws-start primary" id="wsHomeFind">
            <svg viewBox="0 0 96 64" aria-hidden="true"><circle cx="40" cy="28" r="17"/><path d="M52 40l18 18"/>
              <path d="M40 18c-5 0-8.5 3.8-8.5 8.5 0 6.5 8.5 13.5 8.5 13.5s8.5-7 8.5-13.5C48.5 21.8 45 18 40 18z"/>
              <circle cx="40" cy="26.5" r="2.8"/></svg>
            <b>Find a place</b>
            <span>Type the name of a town, a city or anywhere in the world, and go straight there.</span>
          </button>
          <button type="button" class="ws-start" id="wsHomeDraw">
            <svg viewBox="0 0 96 64" aria-hidden="true"><path d="M8 14l22-6 22 6 22-6v42l-22 6-22-6-22 6z"/>
              <path d="M30 8v42M52 14v42"/><path d="M14 36c8-2 12 4 20 0s12-10 18-6"/>
              <rect x="60" y="24" width="24" height="18" stroke-dasharray="4 3"/></svg>
            <b>On the map</b>
            <span>Pan and zoom the world map to your place yourself, then draw its outline.</span>
          </button>
          <button type="button" class="ws-start" id="wsHomeBoard">
            <svg viewBox="0 0 96 64" aria-hidden="true"><rect x="16" y="6" width="54" height="52" rx="3"/>
              <path d="M16 42c10-2 16 3 26-2s18-8 28-6"/><path d="M26 26l6-5 6 5v8H26zM44 22l6-5 6 5v8H44z"/>
              <path d="M66 56l16-16 6 6-16 16-8 2z"/><path d="M78 44l6 6"/></svg>
            <b>A map from scratch</b>
            <span>Draw roads, houses and land on a blank sheet, with nothing real under it.</span>
          </button>
          <button type="button" class="ws-start" id="wsHomeBuilder">
            <svg viewBox="0 0 96 64" aria-hidden="true"><rect x="18" y="8" width="60" height="48" rx="1"/>
              <path d="M18 30h24M42 8v14M42 30v26M42 38h36M60 38v18"/>
              <path d="M42 22a8 8 0 0 1 8 8"/><path d="M28 56v-4M70 8v4"/></svg>
            <b>A building by hand</b>
            <span>Lay out one building room by room, to place on your maps.</span>
          </button>
        </div></div>
      <div class="ws-cols">
        <section><h2>Your maps</h2><div class="ws-card" id="wsHomeMaps"></div></section>
        <section style="display:grid;gap:16px">
          <div><h2>Saved areas</h2><div class="ws-card" id="wsHomePresets"></div></div>
          <div><h2>This PC</h2><div class="ws-card"><p class="hint" style="margin:0 0 8px">What is installed, what this PC
            can hold, and whether the map servers are answering.</p>
            <button type="button" class="btn btn-small" id="wsHomeSetup">Check my setup</button></div></div>
        </section></div>
      <p class="credit">KnoxMap by euclid80tr · Map data © OpenStreetMap contributors</p></div>`;
    const mapsBox = $('wsHomeMaps');
    mapsBox.append($('mapList'));
    mapsCard.hidden = true;
    holder.append(mapsCard);
    if (!$('mapList').children.length) mapsBox.insertAdjacentHTML('afterbegin', '<p class="hint" id="wsNoMaps" style="margin:0">None yet. Start from a real place above to make your first.</p>');
    presets.open = true;
    $('wsHomePresets').append(presets);
    $('wsHomeFind').addEventListener('click', startRealPlace);
    $('wsHomeDraw').addEventListener('click', startOnMap);
    $('wsHomeBoard').addEventListener('click', () => click('boardOpen'));
    $('wsHomeBuilder').addEventListener('click', () => click('builderOpen'));
    $('wsHomeSetup').addEventListener('click', () => { dialog('Check my setup', [$('healthCard')]); click('healthBtn'); });
    // "Open" in the list opens a tab; the list itself is app.js's (loadMaps).
    new MutationObserver(() => { const none = $('wsNoMaps'); if (none && $('mapList').children.length) none.remove(); })
      .observe($('mapList'), { childList: true });
  }

  // A map popped out: a window of its own with its picture, to look at beside
  // another. Docking it back opens it again.
  function popOut(name) {
    if (ws.popped.includes(name)) return;
    if (runningMap === name) { fx.toast('bad', 'Busy', `${name} is busy. Pop it out once it has finished.`, 6000); return; }
    ws.popped.push(name);
    const w = make('section', 'ws-float ws-docwin');
    w.dataset.map = name;
    w.style.left = '40px'; w.style.top = '30px';
    w.innerHTML = `<div class="ws-pnl-head"><span class="nm">${esc(name)}</span><span class="acts">
      <button type="button" data-doc-open title="Open it in the tabs again"><svg viewBox="0 0 24 24"><path d="M4 5h16v14H4zM4 9h16"/></svg></button>
      <button type="button" data-doc-close title="Close this map"><svg viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18"/></svg></button></span></div>
      <img alt="${esc(name)}" src="/output/${encodeURIComponent(name)}/${encodeURIComponent(name)}_preview.png?t=${Date.now()}">`;
    pane.appendChild(w);
    w.querySelector('[data-doc-open]').addEventListener('click', () => dockDoc(name, true));
    w.querySelector('[data-doc-close]').addEventListener('click', () => closeTab(name));
    if (name === currentMap) {
      leaveMap();
      const next = ws.tabs.filter(n => !ws.popped.includes(n)).pop();
      if (next) openTab(next); else goHome();
    }
    render();
  }
  function dockDoc(name, open) {
    ws.popped = ws.popped.filter(n => n !== name);
    document.querySelector(`.ws-docwin[data-map="${CSS.escape(name)}"]`)?.remove();
    if (open) openTab(name);
    render();
  }

  // =========================== the steps row ===========================
  const STEPS = [
    { id: 'generate', short: 'Generate', btn: 'generateBtn', note: 'status' },
    { id: 'build', short: 'Buildings', card: 'buildings', btn: 'buildingsBtn', note: 'buildingsNote' },
    { id: 'compile', short: 'Compile', card: 'compile', btn: 'compileBtn', note: 'compileNote' },
    { id: 'install', short: 'Install', card: 'install', btn: 'installBtn', note: 'installNote' },
    { id: 'publish', short: 'Publish check', card: 'publish', btn: 'publishCheckBtn', note: null, optional: true },
  ];
  const STEP_WHAT = {
    generate: 'Downloads the place and draws its ground, roads, water and trees.',
    build: 'Makes a furnished building, with loot and people, for every footprint.',
    compile: 'Turns the map into the game’s own files.',
    install: 'Copies it into your Zomboid mods folder, ready to play.',
  };
  // Wherever the card is: in its list, or open under its chip.
  const cardOf = s => s.card && document.querySelector(`.pipe-card[data-step="${s.card}"]`);
  const generating = () => !!runningMap && !currentMap;
  function stepState(s) {
    if (s.id === 'generate') {
      if (generating()) return 'running';
      return currentMap ? 'done' : currentRect ? 'ready' : 'locked';
    }
    if (!currentMap) return 'locked';
    const c = cardOf(s);
    if (!c || c.hidden) return 'hidden';
    if (c.classList.contains('is-running') || (runningMap === currentMap && $(s.btn)?.disabled && s.id === 'compile'
        && /Compiling/.test($('compileNote').textContent))) return 'running';
    if (c.classList.contains('is-error')) return 'error';
    if (c.classList.contains('is-done')) return 'done';
    return $(s.btn)?.disabled ? 'locked' : 'ready';
  }
  // What the one button does now.
  function nextAction() {
    if (runningMap && (runningMap === currentMap || generating()))
      return { label: 'Stop', stop: true, run: () => requestStop() };
    if (!currentMap) {
      if (!currentRect) return { label: 'Find a place', find: true, run: () => $('searchInput').focus() };
      return { label: 'Generate map', step: 'generate', run: () => click('generateBtn') };
    }
    for (const s of STEPS.slice(1)) {
      if (s.optional) continue;
      const st = stepState(s);
      if (st === 'ready' || st === 'error') return { label: s.id === 'build' ? 'Build' : s.short, step: s.id, run: () => click(s.btn) };
      if (st === 'locked') return null;
    }
    return { label: 'All done', done: true };
  }
  function renderFlow() {
    flow.hidden = ws.home;
    if (ws.home) return;
    const n = nextAction();
    const chips = STEPS.map((s, i) => {
      const st = stepState(s);
      if (st === 'hidden') return '';
      const cls = st === 'ready' && n && n.step === s.id ? 'next' : st;
      const ic = { done: '✓', error: '!', running: '●' }[cls] || String(i + 1);
      return (i ? '<span class="arrow">›</span>' : '')
        + `<button type="button" class="ws-chip ${cls}" data-chip="${s.id}" title="Click for this step’s details">`
        + `<span class="ic">${ic}</span>${s.short}</button>`;
    }).join('');
    let msg = '', cls = '';
    const noteOf = id => { const e = id && $(id); return e ? e.textContent.trim() : ''; };
    if (n && n.stop) {
      const s = generating() ? STEPS[0] : STEPS.find(x => stepState(x) === 'running');
      msg = s ? noteOf(s.note) || 'Working…' : 'Working…';
    } else if (n && n.find) msg = 'First, choose the area: search for a place, or draw it with the Area tool.';
    else if (n && n.step) { const s = STEPS.find(x => x.id === n.step); msg = noteOf(s.note) || STEP_WHAT[s.id]; }
    else if (n && n.done) { msg = noteOf('installNote') || 'Installed.'; cls = 'ok'; }
    if (STEPS.some(s => stepState(s) === 'error')) cls = 'bad';
    const btn = !n ? '' : n.stop
      ? `<button type="button" class="btn btn-stop go" data-flow-go>${runningMap === stoppingMap ? 'Stopping…' : 'Stop'}</button>`
      : n.done ? '<button type="button" class="btn go" disabled>All done ✓</button>'
      : `<button type="button" class="btn btn-primary go" data-flow-go>${esc(n.label)} ▶</button>`;
    flowRow.innerHTML = chips + `<span class="msg ${cls}" title="${esc(msg)}">${esc(msg)}</span>` + btn;
    if (ws.pop && !popBox.isConnected) flow.appendChild(popBox);
  }
  flow.addEventListener('click', e => {
    if (e.target.closest('[data-flow-go]')) { const n = nextAction(); if (n && n.run) n.run(); return; }
    const c = e.target.closest('[data-chip]');
    if (c) { ws.pop === c.dataset.chip ? closePop() : openPop(c.dataset.chip); }
  });

  // A step's card, shown under its chip: the step's own card, moved, so its
  // progress, census, fields and buttons are the ones app.js already keeps.
  const popBox = make('div', 'ws-pop');
  popBox.addEventListener('click', e => e.stopPropagation());
  let popNodes = [];
  function openPop(id) {
    if (ws.home) showMap();
    closePop();
    ws.pop = id;
    const s = STEPS.find(x => x.id === id);
    popBox.innerHTML = `<div class="pop-head"><b>${id === 'generate' ? 'The map' : s.short}</b>
      <button type="button" class="btn btn-small x" data-pop-close>Close</button></div>`;
    if (id === 'generate') {
      if (currentMap) popNodes = [$('results-grid')];
      else { popNodes = []; popBox.insertAdjacentHTML('beforeend', '<p class="hint">Choose the area, then Generate map draws its ground, roads, water and trees.</p>'); }
    } else popNodes = [cardOf(s)];
    for (const n of popNodes) if (n) popBox.appendChild(n);
    renderFlow();
    const chip = flow.querySelector(`[data-chip="${id}"]`);
    if (chip) popBox.style.left = Math.max(0, Math.min(chip.offsetLeft, flow.clientWidth - popBox.offsetWidth - 8)) + 'px';
  }
  function closePop() {
    for (const n of popNodes) {
      if (!n) continue;
      if (n.id === 'results-grid') results.querySelector('h2').after(n);
      else results.querySelector('.pipeline').appendChild(n);
    }
    // Keep the cards in their order, so the next open finds each where it was.
    const pipe = results.querySelector('.pipeline');
    for (const k of ['buildings', 'place', 'compile', 'install', 'publish']) {
      const c = pipe.querySelector(`.pipe-card[data-step="${k}"]`) || holder.querySelector(`.pipe-card[data-step="${k}"]`);
      if (c) pipe.appendChild(c);
    }
    popNodes = [];
    ws.pop = null;
    popBox.remove();
  }
  popBox.addEventListener('click', e => { if (e.target.closest('[data-pop-close]')) { closePop(); renderFlow(); } });
  document.addEventListener('click', e => {
    if (ws.pop && !e.target.closest('.ws-pop, .ws-chip, .ws-dialog')) { closePop(); renderFlow(); }
  });

  // =========================== the game's world ===========================
  function setView(v) {
    if ((v === 'world' || v === 'iso') && !currentMap) return;
    ws.view = v;
    const place = results.querySelector('.pipe-card[data-step="place"] .pipe-body');
    if (v === 'world') {
      isoView.hidden = true;
      world.innerHTML = '<h3 style="margin:0 0 8px">Place it in the game’s world</h3>';
      world.appendChild($('placePanel'));
      world.hidden = false;
      if (typeof drawWorld === 'function') requestAnimationFrame(drawWorld);
    } else if (v === 'iso') {
      if (place && !place.contains($('placePanel'))) place.appendChild($('placePanel'));
      world.hidden = true;
      isoView.hidden = false;
      if (window.showIsoView) window.showIsoView(currentMap);
    } else {
      if (place && !place.contains($('placePanel'))) place.appendChild($('placePanel'));
      world.hidden = true;
      isoView.hidden = true;
      map.invalidateSize();
    }
    render();
  }

  // =========================== Layers ===========================
  const LAYERS = [
    { key: 'area', label: 'The area', layer: () => drawnItems, sw: 'border:1.5px dashed var(--accent)',
      n: () => currentRect ? '' : 'not drawn' },
    { key: 'sketch', label: 'Added by hand', layer: () => sketchLayer, sw: 'background:#e08a5a',
      n: () => (typeof sketchCount === 'function' ? sketchCount() : '') },
    { key: 'zones', label: 'Zones', layer: () => zoneLayer, sw: 'background:#6fb3e0',
      n: () => ($('zoneCount') ? $('zoneCount').textContent.replace(/[()]/g, '') : '') },
    { key: 'edits', label: 'Changes to the map', layer: () => editLayer, sw: 'background:var(--bad)',
      n: () => ($('editCount') ? $('editCount').textContent.replace(/[()]/g, '') : '') },
    { key: 'places', label: 'Named places', layer: () => landmarkMarkers, sw: 'background:var(--muted)',
      n: () => '' },
  ];
  function renderLayers() {
    const b = layers.querySelector('.ws-legend-body');
    b.innerHTML = '<ul class="ws-layers">' + LAYERS.map(l => {
      const on = map.hasLayer(l.layer());
      return `<li><button type="button" class="eye ${on ? '' : 'off'}" data-layer="${l.key}"
        title="${on ? 'Hide' : 'Show'} on the map">${on ? '◉' : '○'}</button>
        <span class="sw" style="${l.sw}"></span>${l.label}<span class="n">${esc(l.n())}</span></li>`;
    }).join('') + `</ul><button type="button" class="btn btn-small" data-layer-built ${currentMap ? '' : 'disabled'}
      title="Buildings by use, or where the zombies are, after Buildings">What was built…</button>`;
  }
  layers.addEventListener('click', e => {
    const b = e.target.closest('[data-layer]');
    if (b) {
      const l = LAYERS.find(x => x.key === b.dataset.layer).layer();
      if (map.hasLayer(l)) map.removeLayer(l); else map.addLayer(l);
      renderLayers();
    }
    if (e.target.closest('[data-layer-built]')) openPop('build');
  });

  // =========================== panels: fold, float, dock, resize ===========================
  function togglePanel(p) { p.hidden = !p.hidden; }
  function floatPanel(p, x, y) {
    p.classList.add('ws-float'); p.classList.remove('shut');
    p.style.left = x + 'px'; p.style.top = y + 'px';
    pane.appendChild(p);
  }
  function dockPanel(p) { p.classList.remove('ws-float'); p.style.left = p.style.top = p.style.width = p.style.height = ''; controls.appendChild(p); }
  function resetLayout() {
    props.hidden = false; dockPanel(props);
    controls.append(props);
    for (const w of [layers, places]) { w.hidden = false; w.classList.remove('shut'); }
    document.documentElement.style.removeProperty('--dock-w');
    props.querySelector('.ws-pnl-body').style.height = '';
    for (const n of [...ws.popped]) dockDoc(n, false);
  }
  document.addEventListener('click', e => {
    const tw = e.target.closest('.ws-pnl .tw, .ws-legend .tw');
    if (tw) tw.closest('.ws-pnl, .ws-legend').classList.toggle('shut');
    const pop = e.target.closest('[data-pop-panel]');
    if (pop) { const p = pop.closest('.ws-pnl'); p.classList.contains('ws-float') ? dockPanel(p) : floatPanel(p, 40, 30); }
  });
  const SNAP = 10, GAP = 6;
  document.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    // Resizing: the panel column by its edge, a panel by its bottom edge.
    if (e.target === vsplit || e.target.classList.contains('ws-grip')) {
      e.preventDefault();
      const el = e.target, x0 = e.clientX, y0 = e.clientY;
      const w0 = controls.offsetWidth, bodyEl = el.classList.contains('ws-grip') ? el.previousElementSibling : null;
      const h0 = bodyEl ? bodyEl.offsetHeight : 0;
      el.classList.add('on');
      const move = ev => {
        if (bodyEl) bodyEl.style.height = Math.max(60, h0 + ev.clientY - y0) + 'px';
        else { document.documentElement.style.setProperty('--dock-w', Math.max(250, Math.min(700, w0 - (ev.clientX - x0))) + 'px'); map.invalidateSize(); }
      };
      const up = () => { el.classList.remove('on'); document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', up); map.invalidateSize(); };
      document.addEventListener('pointermove', move); document.addEventListener('pointerup', up);
      return;
    }
    // Dragging a panel or a popped-out map by its title, or a tab out of the row.
    const tab = e.target.closest('.ws-tab[data-tab]');
    const head = e.target.closest('.ws-pnl-head');
    if ((!tab && !head) || e.target.closest('button, input, select')) return;
    let win = tab ? null : head.closest('.ws-pnl, .ws-docwin');
    const sx = e.clientX, sy = e.clientY;
    let grab = null;
    const move = ev => {
      const r = pane.getBoundingClientRect();
      if (!grab) {
        if (tab) {
          if (ev.clientY - sy < 28) return;
          popOut(tab.dataset.tab);
          win = pane.querySelector(`.ws-docwin[data-map="${CSS.escape(tab.dataset.tab)}"]`);
          if (!win) return;
        } else {
          if (Math.hypot(ev.clientX - sx, ev.clientY - sy) < 6) return;
          if (!win.classList.contains('ws-float')) floatPanel(win, ev.clientX - r.left - 80, ev.clientY - r.top - 12);
        }
        grab = { x: ev.clientX - r.left - win.offsetLeft, y: ev.clientY - r.top - win.offsetTop };
      }
      let x = ev.clientX - r.left - grab.x, y = ev.clientY - r.top - grab.y;
      const w = win.offsetWidth, h = win.offsetHeight;
      const xs = [[0, 0], [pane.clientWidth - w, pane.clientWidth]], ys = [[0, 0], [pane.clientHeight - h, pane.clientHeight]];
      for (const o of pane.querySelectorAll('.ws-float')) {
        if (o === win) continue;
        const l = o.offsetLeft, t = o.offsetTop, rr = l + o.offsetWidth, b = t + o.offsetHeight;
        xs.push([l, l], [rr - w, rr], [rr + GAP, rr + GAP / 2], [l - w - GAP, l - GAP / 2]);
        ys.push([t, t], [b - h, b], [b + GAP, b + GAP / 2], [t - h - GAP, t - GAP / 2]);
      }
      const pick = (v, list) => list.reduce((best, c) => Math.abs(c[0] - v) < SNAP && (!best || Math.abs(c[0] - v) < Math.abs(best[0] - v)) ? c : best, null);
      const px = pick(x, xs), py = pick(y, ys);
      if (px) { x = px[0]; guideV.style.left = px[1] + 'px'; guideV.style.display = 'block'; } else guideV.style.display = 'none';
      if (py) { y = py[0]; guideH.style.top = py[1] + 'px'; guideH.style.display = 'block'; } else guideH.style.display = 'none';
      win.style.left = Math.max(-w + 60, Math.min(pane.clientWidth - 60, x)) + 'px';
      win.style.top = Math.max(0, Math.min(pane.clientHeight - 30, y)) + 'px';
      const isDoc = win.classList.contains('ws-docwin');
      controls.classList.toggle('drop-here', !isDoc && ev.clientX > controls.getBoundingClientRect().left - 20);
      tabs.classList.toggle('drop-here', isDoc && ev.clientY < tabs.getBoundingClientRect().bottom + 6);
    };
    const up = () => {
      document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', up);
      guideV.style.display = guideH.style.display = 'none';
      if (!grab && tab) { openTab(tab.dataset.tab); return; }
      if (controls.classList.contains('drop-here')) { controls.classList.remove('drop-here'); dockPanel(win); }
      if (tabs.classList.contains('drop-here')) { tabs.classList.remove('drop-here'); dockDoc(win.dataset.map, true); }
    };
    document.addEventListener('pointermove', move); document.addEventListener('pointerup', up);
  });
  document.addEventListener('dblclick', e => {
    if (e.target === vsplit) { document.documentElement.style.removeProperty('--dock-w'); map.invalidateSize(); }
    if (e.target.classList.contains('ws-grip')) e.target.previousElementSibling.style.height = '';
  });

  // =========================== status bar ===========================
  function renderStatus() {
    const facts = [];
    if (runningMap && runningMap !== currentMap) facts.push(`${runningMap} is busy`);
    if (currentMap) facts.push(currentMap);
    else if (currentRect) facts.push('Area chosen, not generated yet');
    statusRight.textContent = facts.join(' · ');
  }

  // =========================== keeping every part in step ===========================
  let queued = false;
  function render() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      renderTools(); renderOptions(); renderTabs(); renderFlow(); renderLayers(); renderStatus();
      home.hidden = !ws.home;
    });
  }
  // app.js changes the step cards, notes and buttons as steps run; the row,
  // tabs and status follow those changes rather than a second copy of them.
  const watchSteps = { subtree: true, attributes: true, attributeFilter: ['class', 'hidden', 'disabled'], childList: true, characterData: true };
  new MutationObserver(render).observe(results, watchSteps);
  new MutationObserver(render).observe(popBox, watchSteps);
  new MutationObserver(render).observe($('status'), { childList: true, characterData: true, subtree: true });
  for (const id of ['generateBtn', 'gen-overlay']) new MutationObserver(render).observe($(id), { attributes: true });
  map.on('draw:created draw:edited draw:deleted', render);
  // Polled, cheaply, for what has no event: the selection, the running map.
  let last = '';
  setInterval(() => {
    if (runningMap && runningMap === currentMap && ws.lastData) ws.lastData.installed = null;
    const now = [!!currentRect, currentMap, runningMap, stoppingMap].join('|');
    if (now !== last) { last = now; render(); }
  }, 400);

  // =========================== keys ===========================
  document.addEventListener('keydown', e => {
    if (!$('board').hidden || !$('builder').hidden) return;
    const typing = e.target.matches('input, select, textarea');
    const k = e.key.toLowerCase();
    if (e.ctrlKey && k === 'f') { e.preventDefault(); if (ws.home) startRealPlace(); else $('searchInput').focus(); return; }
    if (typing) return;
    if (e.ctrlKey && k === 'n') { e.preventDefault(); newMap(); }
    else if (e.ctrlKey && k === 'h') { e.preventDefault(); goHome(); }
    else if (e.ctrlKey && k === 'w') { e.preventDefault(); closeTab(currentMap); }
    else if (e.key === 'F5') { e.preventDefault(); const n = nextAction(); if (n && n.run) n.run(); }
    else if (e.key === 'Escape' && !dlg.hidden) closeDialog();
    else if (!e.ctrlKey && !e.altKey && !e.metaKey && !ws.home) {
      const t = TOOLS.find(x => x.key.toLowerCase() === k);
      if (t) setTool(t.id);
    }
  });

  // =========================== start ===========================
  body.classList.add('ws');
  body.classList.remove('ws-loading');
  // The old first-run tip: Home and the steps row say it now.
  if ($('map-hint')) $('map-hint').hidden = true;
  refreshMyMaps();
  setTool('area', true);
  goHome();
  // A link that opens a place (?preset= or ?q=) goes straight to the map.
  const params = new URLSearchParams(location.search);
  if (params.has('preset') || params.has('q')) newMap();
  // ?map=<name> opens one of your maps straight away.
  if (params.get('map')) openTab(params.get('map'));
  window.addEventListener('resize', () => map.invalidateSize());
  window.knoxShell = { ws, goHome, newMap, openTab, closeTab, setTool, setView, openPop, closePop, render };
})();
