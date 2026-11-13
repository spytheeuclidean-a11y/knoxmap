// ---- where the map goes in the world ----------------------------------------
//
// Project Zomboid holds one grid for every map installed, with Knox County in
// the corner of it. A generated map used to be dropped east of the vanilla map
// and east again of anything else already installed, which keeps maps off each
// other and leaves nobody any say in where their town is. This is the say.
//
// The world is drawn as it really is rather than as boxes: every map on this
// PC, cell by cell, from the compiled files themselves - Knox County is 4,065
// cells with bites out of it, not a rectangle - and this map as the picture it
// came out as (knoxbuild/placement.py).
//
// Moving one that is already built rewrites the few files that carry the world
// origin and then needs the map compiling again, because compiled cells are
// named for where they land.
let placeWorld = null;          // the layout as the server sees it
let placePicked = null;         // the corner being tried, in cells
let placeDragging = false;
let placePreview = null;        // this map's own picture, once it has loaded
const placePictures = {};       // the game's own maps, by name, once loaded
let placeRoad = [];             // a road being drawn, in world tiles
let placeDrawingRoad = false;
// What part of the world the canvas is showing: how far in, and the world
// tile at its top-left corner. Zoom 1 is the whole world.
const placeView = { zoom: 1, x: 0, y: 0 };
const PLACE_MAX_ZOOM = 24;

const PLACE_PAD = 8;            // cells of empty grid round what is drawn
const PLACE_MIN_SPAN = 110;     // never zoom in closer than this many cells
const LINK_MARGIN_CELLS = 1;    // ground either side of a link road
const LINK_MAX_CELLS = 2500;    // a link bigger than this is a map, not a road

function placeNote(text, bad) {
  const box = document.getElementById('placeNote');
  if (!box) return;
  box.textContent = text || '';
  box.classList.toggle('bad', !!bad);
}

// Everything is drawn in world tiles, because the two grids in play do not
// divide into each other: a map is placed on 300-tile cells and compiled into
// 256-tile ones, and tiles are what both of them are made of.
function placeTiles() {
  return (placeWorld && placeWorld.cellTiles) || 300;
}

function placeMine() {
  if (!placeWorld) return null;
  const at = placePicked || placeWorld.map;
  const k = placeTiles();
  return { x: at.x * k, y: at.y * k,
           w: placeWorld.map.w * k, h: placeWorld.map.h * k };
}

// The other maps in this map's world. A standalone map is the whole world, so
// there are none: Knox County went on being drawn behind one, as if it were
// still there, whenever a standalone map was opened or ticked.
function placeWorldMaps() {
  if (!placeWorld || placeWorld.standalone) return [];
  return placeWorld.maps || [];
}

// Every other map's cells as tile rectangles, one per run of cells in a row.
function placeOtherRects() {
  if (!placeWorld) return [];
  const k = placeWorld.compiledCell || 256;
  const out = [];
  for (const map of placeWorldMaps()) {
    for (const [row, first, last] of map.runs) {
      out.push({ x: first * k, y: row * k, w: (last - first + 1) * k, h: k,
                 kind: map.kind, name: map.name });
    }
  }
  return out;
}

function placeSpan() {
  // Enough of the world to show everything on it, with room to move into.
  const k = placeTiles();
  const boxes = placeOtherRects().concat(placeMine() || []);
  const right = Math.max(PLACE_MIN_SPAN * k, ...boxes.map(b => b.x + b.w));
  const down = Math.max(PLACE_MIN_SPAN * 0.62 * k, ...boxes.map(b => b.y + b.h));
  return { w: right + PLACE_PAD * k, h: down + PLACE_PAD * k };
}

function placeFitScale() {
  const canvas = document.getElementById('placeCanvas');
  const span = placeSpan();
  return Math.min(canvas.width / span.w, canvas.height / span.h);
}

// Canvas pixels per world tile, zoom included.
function placeScale() {
  return placeFitScale() * placeView.zoom;
}

// Keep the view on the world: not scrolled past its edges.
function placeClampView() {
  const canvas = document.getElementById('placeCanvas');
  const span = placeSpan();
  const k = placeScale();
  placeView.x = Math.max(0, Math.min(placeView.x, span.w - canvas.width / k));
  placeView.y = Math.max(0, Math.min(placeView.y, span.h - canvas.height / k));
  if (placeView.zoom <= 1) { placeView.x = 0; placeView.y = 0; }
}

// Zoom by `factor`, keeping the world tile under (px, py) - canvas pixels -
// where it is, so the wheel zooms into what the pointer is on.
function placeZoomBy(factor, px, py) {
  const canvas = document.getElementById('placeCanvas');
  if (px === undefined) { px = canvas.width / 2; py = canvas.height / 2; }
  const before = placeScale();
  const tx = px / before + placeView.x;
  const ty = py / before + placeView.y;
  placeView.zoom = Math.max(1, Math.min(PLACE_MAX_ZOOM, placeView.zoom * factor));
  const after = placeScale();
  placeView.x = tx - px / after;
  placeView.y = ty - py / after;
  placeClampView();
  drawWorld();
}

function hits(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w
      && a.y < b.y + b.h && b.y < a.y + a.h;
}

function placeClashes(corner) {
  if (!placeWorld || placeWorld.standalone) return [];
  const k = placeTiles();
  const mine = { x: corner.x * k, y: corner.y * k,
                 w: placeWorld.map.w * k, h: placeWorld.map.h * k };
  const names = new Set();
  for (const rect of placeOtherRects()) {
    // Knox County under the map is not a clash: it is what the map replaces.
    if (rect.kind === 'vanilla') continue;
    if (hits(mine, rect)) names.add(rect.name);
  }
  return [...names];
}

// The vanilla cells this map would stand on, which it replaces. A standalone
// map has no vanilla world to replace.
function placeReplaces(corner) {
  if (!placeWorld || placeWorld.standalone) return [];
  const k = placeTiles();
  const mine = { x: corner.x * k, y: corner.y * k,
                 w: placeWorld.map.w * k, h: placeWorld.map.h * k };
  return placeOtherRects().some(r => r.kind === 'vanilla' && hits(mine, r))
    ? [placeWorld.vanilla.name] : [];
}

function drawWorld() {
  const canvas = document.getElementById('placeCanvas');
  if (!canvas || !placeWorld) return;
  const ctx = canvas.getContext('2d');
  const k = placeScale();
  const cell = placeTiles();
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#0d100c';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  placeClampView();
  ctx.save();
  ctx.translate(-placeView.x * k, -placeView.y * k);

  // The grid, every ten cells, so distances are readable.
  const span = placeSpan();
  ctx.strokeStyle = '#1b211a';
  ctx.lineWidth = 1;
  for (let x = 0; x <= span.w; x += cell * 10) {
    ctx.beginPath(); ctx.moveTo(x * k, 0); ctx.lineTo(x * k, span.h * k); ctx.stroke();
  }
  for (let y = 0; y <= span.h; y += cell * 10) {
    ctx.beginPath(); ctx.moveTo(0, y * k); ctx.lineTo(span.w * k, y * k); ctx.stroke();
  }

  // Every map on this PC: the game's own picture of it where there is one -
  // Knox County as it really looks, down to the fields and the river - and
  // the shape of its cells where there is not.
  const mineNow = placeMine();
  const drawn = new Set();
  for (const map of placeWorldMaps()) {
    const shot = placePictures[map.name];
    if (map.pictureBox && shot && shot.complete && shot.naturalWidth) {
      const b = map.pictureBox;
      ctx.drawImage(shot, b.x * k, b.y * k, b.w * k, b.h * k);
      drawn.add(map.name);
    }
  }
  for (const rect of placeOtherRects()) {
    if (drawn.has(rect.name)) continue;
    ctx.fillStyle = rect.kind === 'vanilla'
      ? 'rgba(150,160,135,0.42)' : 'rgba(120,140,170,0.42)';
    ctx.fillRect(rect.x * k, rect.y * k, Math.max(1, rect.w * k),
                 Math.max(1, rect.h * k));
  }
  // ...labelled once each, under what they cover.
  ctx.font = '13px system-ui, sans-serif';
  for (const map of placeWorldMaps()) {
    const c = placeWorld.compiledCell || 256;
    ctx.fillStyle = map.kind === 'vanilla' ? '#d6dcc8' : '#92a8c4';
    ctx.fillText(map.name, map.x * c * k + 3, (map.y * c + map.h * c) * k + 14);
  }

  if (mineNow) {
    const clash = placeClashes(placePicked || placeWorld.map);
    const edge = clash.length ? '#dc5046' : '#3d8bfd';
    if (placePreview && placePreview.complete && placePreview.naturalWidth) {
      ctx.globalAlpha = 0.95;
      ctx.drawImage(placePreview, mineNow.x * k, mineNow.y * k,
                    mineNow.w * k, mineNow.h * k);
      ctx.globalAlpha = 1;
    } else {
      ctx.fillStyle = clash.length ? 'rgba(220,80,70,0.35)' : 'rgba(61,139,253,0.35)';
      ctx.fillRect(mineNow.x * k, mineNow.y * k, mineNow.w * k, mineNow.h * k);
    }
    ctx.strokeStyle = edge;
    ctx.lineWidth = 2;
    ctx.strokeRect(mineNow.x * k, mineNow.y * k, mineNow.w * k, mineNow.h * k);
    ctx.fillStyle = edge;
    ctx.fillText('this map', mineNow.x * k + 3, (mineNow.y + mineNow.h) * k + 14);
  }

  // The road being drawn across the gap.
  if (placeRoad.length) {
    ctx.strokeStyle = '#f0b429';
    ctx.lineWidth = 3;
    ctx.beginPath();
    placeRoad.forEach(([x, y], i) => {
      if (i) ctx.lineTo(x * k, y * k); else ctx.moveTo(x * k, y * k);
    });
    ctx.stroke();
    ctx.fillStyle = '#f0b429';
    for (const [x, y] of placeRoad) {
      ctx.beginPath();
      ctx.arc(x * k, y * k, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

function placeSummary() {
  const badge = document.getElementById('placeWhere');
  if (!badge || !placeWorld) return;
  const mine = placePicked || placeWorld.map;
  badge.textContent = `(cell ${mine.x},${mine.y})`;
}

function placeFields() {
  const mine = placePicked || (placeWorld && placeWorld.map);
  if (!mine) return;
  const box = document.getElementById('placeStandalone');
  if (box && placeWorld) box.checked = !!placeWorld.standalone;
  document.getElementById('placeX').value = mine.x;
  document.getElementById('placeY').value = mine.y;
  placeSummary();
}

function placeState() {
  if (!placeWorld) return;
  const mine = placePicked || placeWorld.map;
  const clash = placeClashes(mine);
  const tiles = placeTiles();
  const where = `Cell ${mine.x},${mine.y} - world tile `
    + `${mine.x * tiles},${mine.y * tiles}.`;
  const replaces = placeReplaces(mine);
  if (clash.length) {
    placeNote(`${where} It would sit on top of ${clash.join(' and ')}, and the `
      + 'game would read one map’s cells for the other.', true);
  } else if (!placeWorld.lotsMatch) {
    placeNote(`${where} The map has moved since it was compiled - compile it `
      + 'again before installing.', true);
  } else if (placeWorld.standalone) {
    placeNote(`${where} Standalone: the whole world is this map.`);
  } else if (replaces.length) {
    placeNote(`${where} This replaces the ${replaces[0]} cells under it. Load the `
      + 'map ahead of Muldraugh, KY: SERVER SETUP.txt has the lines.');
  } else {
    placeNote(where);
  }
}

// The game's own maps, each fetched once and kept for the next draw.
function placeFetchPictures() {
  for (const map of placeWorld.maps || []) {
    if (!map.picture || placePictures[map.name]) continue;
    const shot = new Image();
    shot.onload = drawWorld;
    shot.onerror = () => { delete placePictures[map.name]; };
    shot.src = `/api/world-picture/${encodeURIComponent(map.name)}`;
    placePictures[map.name] = shot;
  }
}

async function loadPlacement(mapName) {
  const panel = document.getElementById('placePanel');
  if (!panel || !mapName) return;
  try {
    placeWorld = await (await fetch(`/api/placement/${encodeURIComponent(mapName)}`)).json();
  } catch {
    return;                     // the step simply shows nothing about place
  }
  if (placeWorld.error) { placeWorld = null; return; }
  placePicked = null;
  placeRoad = [];
  placeDrawingRoad = false;
  placeLinkState();
  placeFetchPictures();
  // The map as it came out, drawn in its place in the world.
  placePreview = new Image();
  placePreview.onload = drawWorld;
  placePreview.onerror = () => { placePreview = null; };
  placePreview.src = `/output/${encodeURIComponent(mapName)}/`
    + `${encodeURIComponent(mapName)}_preview.png`;
  drawWorld();
  placeFields();
  placeState();
  sayIfInstallable();
}

function placeAt(ev) {
  const canvas = document.getElementById('placeCanvas');
  const rect = canvas.getBoundingClientRect();
  const k = placeScale();
  const scale = canvas.width / rect.width;   // drawn at its own size, shown scaled
  return [(ev.clientX - rect.left) * scale / k + placeView.x,
          (ev.clientY - rect.top) * scale / k + placeView.y];
}

function placeFromEvent(ev) {
  const [tx, ty] = placeAt(ev);
  const cell = placeTiles();
  // Picked by the middle of the map rather than its corner: the pointer is
  // where you want the town, not where its north-west cell happens to be.
  return {
    x: Math.max(0, Math.min(placeWorld.maxCell,
                            Math.round(tx / cell - placeWorld.map.w / 2))),
    y: Math.max(0, Math.min(placeWorld.maxCell,
                            Math.round(ty / cell - placeWorld.map.h / 2))),
  };
}

(() => {
  const canvas = document.getElementById('placeCanvas');
  if (!canvas) return;
  const pick = ev => {
    if (!placeWorld) return;
    placePicked = placeFromEvent(ev);
    drawWorld();
    placeFields();
    placeState();
  };
  // The middle button drags the view about; the left one picks where the map
  // goes. Pointer position in canvas pixels, whatever size it is shown at.
  let panning = null;
  const canvasPx = ev => {
    const box = canvas.getBoundingClientRect();
    const f = canvas.width / box.width;
    return [(ev.clientX - box.left) * f, (ev.clientY - box.top) * f];
  };
  canvas.addEventListener('pointerdown', ev => {
    if (!placeWorld) return;
    if (ev.button === 1) {
      ev.preventDefault();                  // no autoscroll circle
      const [px, py] = canvasPx(ev);
      panning = { px, py, x: placeView.x, y: placeView.y };
      canvas.setPointerCapture(ev.pointerId);
      return;
    }
    if (ev.button !== 0) return;
    canvas.focus({ preventScroll: true });
    if (placeDrawingRoad) {
      placeRoad.push(placeAt(ev).map(Math.round));
      drawWorld();
      placeLinkState();
      return;
    }
    placeDragging = true;
    canvas.setPointerCapture(ev.pointerId);
    pick(ev);
  });
  canvas.addEventListener('pointermove', ev => {
    if (panning) {
      const [px, py] = canvasPx(ev);
      const k = placeScale();
      placeView.x = panning.x - (px - panning.px) / k;
      placeView.y = panning.y - (py - panning.py) / k;
      drawWorld();
      return;
    }
    if (placeDragging) pick(ev);
  });
  const release = () => { placeDragging = false; panning = null; };
  canvas.addEventListener('pointerup', release);
  canvas.addEventListener('pointercancel', release);
  canvas.addEventListener('auxclick', ev => ev.preventDefault());
  canvas.addEventListener('wheel', ev => {
    if (!placeWorld) return;
    ev.preventDefault();                    // the page does not scroll under it
    const [px, py] = canvasPx(ev);
    placeZoomBy(ev.deltaY < 0 ? 1.25 : 1 / 1.25, px, py);
  }, { passive: false });
  // + and - zoom while the pointer is over the map or it has focus; 0 shows
  // the whole world again. Not when typing in one of the boxes.
  let over = false;
  canvas.addEventListener('pointerenter', () => { over = true; });
  canvas.addEventListener('pointerleave', () => { over = false; });
  document.addEventListener('keydown', ev => {
    if (!placeWorld || !(over || document.activeElement === canvas)) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName || '')) return;
    if (ev.key === '+' || ev.key === '=') placeZoomBy(1.4);
    else if (ev.key === '-' || ev.key === '_') placeZoomBy(1 / 1.4);
    else if (ev.key === '0') { placeView.zoom = 1; drawWorld(); }
    else return;
    ev.preventDefault();
  });
  document.getElementById('placeZoomIn').addEventListener('click', () => placeZoomBy(1.4));
  document.getElementById('placeZoomOut').addEventListener('click', () => placeZoomBy(1 / 1.4));
  document.getElementById('placeZoomFit').addEventListener('click', () => {
    placeView.zoom = 1;
    drawWorld();
  });
  canvas.addEventListener('dblclick', () => {
    if (placeDrawingRoad) stopRoad();
  });
})();

for (const id of ['placeX', 'placeY']) {
  document.getElementById(id).addEventListener('change', () => {
    if (!placeWorld) return;
    placePicked = {
      x: parseInt(document.getElementById('placeX').value, 10) || 0,
      y: parseInt(document.getElementById('placeY').value, 10) || 0,
    };
    drawWorld();
    placeSummary();
    placeState();
  });
}

// What the Install step says about being ready. A map moved after it was
// compiled cannot be installed as it stands, and the placement panel above
// the button may well be closed, so it is said here as well.
function sayIfInstallable() {
  const btn = document.getElementById('installBtn');
  if (placeWorld && placeWorld.compiled && !placeWorld.lotsMatch) {
    note('installNote', 'This map was moved after it was compiled. '
      + 'Compile it again (step 5), then install.', 'bad');
    note('compileNote', 'The map was moved on the world map since the last '
      + 'compile. Compile it again.', 'warn');
    btn.disabled = true;
    return false;
  }
  if (!btn.disabled) note('installNote', 'Ready to install.');
  return true;
}

async function putMapAt(body) {
  if (!currentMap) { placeNote('Open or generate a map first.', true); return; }
  try {
    const res = await fetch(`/api/placement/${encodeURIComponent(currentMap)}`, body);
    const out = await res.json();
    if (!res.ok) throw apiError(out, res);
    placeWorld = out;
    placePicked = null;
    placeFetchPictures();
    drawWorld();
    placeFields();
    const moved = out.moved || {};
    sayIfInstallable();
    if (moved.needsCompile) {
      placeNote(`Moved to cell ${out.map.x},${out.map.y}. `
        + `${(moved.rewrote || []).length} files re-pointed - compile the map `
        + 'again, then install.', true);
      fx.toast('ok', 'Map moved', 'Compile it again before installing.');
    } else {
      placeState();
      fx.toast('ok', 'Map placed', `It will be built at cell ${out.map.x},${out.map.y}.`);
    }
  } catch (err) {
    placeFields();      // a refused change leaves the checkbox as it really is
    placeNote(err.message, true);
  }
}

document.getElementById('placeApply').addEventListener('click', () => {
  const mine = placePicked || (placeWorld && placeWorld.map);
  if (!mine) return;
  putMapAt({ method: 'POST', headers: { 'Content-Type': 'application/json' },
             body: JSON.stringify({ cell_x: mine.x, cell_y: mine.y }) });
});

document.getElementById('placeStandalone').addEventListener('change', e => {
  putMapAt({ method: 'POST', headers: { 'Content-Type': 'application/json' },
             body: JSON.stringify({ standalone: e.target.checked }) });
});

document.getElementById('placeAuto').addEventListener('click', () =>
  putMapAt({ method: 'DELETE' }));

// ---- a road from one map to the next -----------------------------------------
//
// Two maps in the same world have empty grid between them: no ground, no road,
// nothing to drive along. A road drawn across that gap becomes a map of its own
// - a strip of ground with a road down it, pinned to the cells it crosses - so
// it is built, compiled and installed by the same steps as any other map, and
// the game joins the three of them into one world.
function linkBox() {
  if (placeRoad.length < 2) return null;
  const cell = placeTiles();
  const xs = placeRoad.map(p => p[0]), ys = placeRoad.map(p => p[1]);
  const x0 = Math.max(0, Math.floor(Math.min(...xs) / cell) - LINK_MARGIN_CELLS);
  const y0 = Math.max(0, Math.floor(Math.min(...ys) / cell) - LINK_MARGIN_CELLS);
  const x1 = Math.ceil(Math.max(...xs) / cell) + LINK_MARGIN_CELLS;
  const y1 = Math.ceil(Math.max(...ys) / cell) + LINK_MARGIN_CELLS;
  return trimLink({ x: x0, y: y0,
                    w: Math.max(1, x1 - x0), h: Math.max(1, y1 - y0) });
}

// The strip of ground a road is drawn on is a map like any other, and two maps
// may not share a cell: whichever the game reads second wins and the other's
// ground is simply not there. So the strip is trimmed back out of everything
// already on the world, cell by cell, before it is built.
//
// It can only be trimmed to whole cells of its own, and the vanilla map's
// cells are 256 tiles against this grid's 300, so a road laid up against Knox
// County stops a little short of it. Between two KnoxMap maps, both on the
// same grid, it meets them exactly.
function placeMapBoxes() {
  // Whole maps rather than their runs of cells: a strip of road is trimmed
  // out of a map, not threaded through the bites out of its edge.
  if (!placeWorld) return [];
  const c = placeWorld.compiledCell || 256;
  return (placeWorld.maps || []).map(m => ({
    x: m.x * c, y: m.y * c, w: m.w * c, h: m.h * c, name: m.name }));
}

function trimLink(box) {
  const cell = placeTiles();
  const others = placeMapBoxes().concat(placeMine() || []);
  let { x, y, w, h } = box;
  for (let pass = 0; pass < 8 && w > 0 && h > 0; pass += 1) {
    const me = { x: x * cell, y: y * cell, w: w * cell, h: h * cell };
    const hit = others.find(r => hits(me, r));
    if (!hit) break;
    // Trimmed on whichever side it pokes in least far, so a road laid along a
    // map keeps its length and one laid at its edge keeps its width.
    const sides = [
      ['left', Math.ceil((hit.x + hit.w - me.x) / cell)],
      ['right', Math.ceil((me.x + me.w - hit.x) / cell)],
      ['top', Math.ceil((hit.y + hit.h - me.y) / cell)],
      ['bottom', Math.ceil((me.y + me.h - hit.y) / cell)],
    ].filter(([, by]) => by > 0).sort((a, b) => a[1] - b[1]);
    if (!sides.length) break;
    const [side, by] = sides[0];
    if (side === 'left') { x += by; w -= by; }
    else if (side === 'right') { w -= by; }
    else if (side === 'top') { y += by; h -= by; }
    else { h -= by; }
  }
  if (w <= 0 || h <= 0) return null;
  return { x, y, w, h, trimmed: x !== box.x || y !== box.y
                                || w !== box.w || h !== box.h };
}

function placeLinkState() {
  const draw = document.getElementById('placeRoad');
  const make = document.getElementById('placeLink');
  const undo = document.getElementById('placeRoadUndo');
  if (!draw) return;
  draw.textContent = placeDrawingRoad ? 'Finish the road' : 'Draw a road';
  draw.classList.toggle('is-on', placeDrawingRoad);
  const box = linkBox();
  make.disabled = !box;
  undo.disabled = !placeRoad.length;
  if (!placeRoad.length) return;
  if (!box) {
    placeNote('Click once more: a road needs at least two points.');
    return;
  }
  const cells = box.w * box.h;
  const trimmed = box.trimmed
    ? ' Trimmed back out of the maps it crossed - two maps cannot share a cell.'
    : '';
  placeNote(`A road of ${placeRoad.length} points across ${box.w}×${box.h} `
    + `cells (${cells} in all)${cells > LINK_MAX_CELLS
      ? ' - that is a map, not a road. Draw a straighter one.' : '.'}${trimmed}`,
    cells > LINK_MAX_CELLS);
}

function stopRoad() {
  placeDrawingRoad = false;
  placeLinkState();
}

document.getElementById('placeRoad').addEventListener('click', () => {
  if (placeDrawingRoad) { stopRoad(); return; }
  placeDrawingRoad = true;
  placeRoad = [];
  drawWorld();
  placeLinkState();
  placeNote('Click along the road, from your map to the one you want to reach. '
    + 'Double-click to finish.');
});

document.getElementById('placeRoadUndo').addEventListener('click', () => {
  placeRoad.pop();
  drawWorld();
  placeLinkState();
});

document.getElementById('placeLink').addEventListener('click', async () => {
  const box = linkBox();
  if (!box || !currentMap) return;
  const btn = document.getElementById('placeLink');
  btn.disabled = true;
  placeNote('Laying out the road…');
  try {
    // The sheet is worked out on the server: the cells the road may use, the
    // scale of the map it joins, and the country either side of it.
    const res = await fetch(`/api/placement/${encodeURIComponent(currentMap)}/link`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ points: placeRoad,
                             kind: document.getElementById('placeRoadKind').value }),
    });
    const plan = await res.json();
    if (!res.ok) throw apiError(plan, res);
    placeNote(`Building ${plan.box.w}×${plan.box.h} cells of road and `
      + `country at ${plan.metersPerTile} m a tile…`);
    const made = await fetch('/api/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mapName: plan.name, design: plan.design,
                             metersPerTile: plan.metersPerTile,
                             // Drawn where it was drawn: straightened to the
                             // tile grid, a road sloping across the gap comes
                             // out flat and meets the next map in the wrong
                             // place.
                             settings: { preset: 'rural', align_streets: 0,
                                         rotate_degrees: 0,
                                         straight_roads: 0 } }),
    });
    const map = await made.json();
    if (!made.ok) throw apiError(map, made);
    // Pinned where it was drawn, or the road would be packed in beside the
    // other maps instead of between them.
    const put = await fetch(`/api/placement/${encodeURIComponent(plan.name)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cell_x: plan.box.x, cell_y: plan.box.y }) });
    if (!put.ok) throw apiError(await put.json(), put);
    placeRoad = [];
    placeDrawingRoad = false;
    drawWorld();
    placeLinkState();
    placeNote(`"${plan.name}" made: ${map.width} × ${map.height} tiles at `
      + `cell ${plan.box.x},${plan.box.y}, with ${plan.scenery} woods, fields `
      + 'and hedges along it. Open it under Your maps, generate its buildings, '
      + 'compile and install it beside this one.');
    fx.toast('ok', 'Road made', `${plan.name} is ready to build and compile.`);
    loadMaps();
  } catch (err) {
    placeNote(err.message, true);
  } finally {
    btn.disabled = false;
  }
});
