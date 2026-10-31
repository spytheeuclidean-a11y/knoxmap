// Knoxify — frontend.
//
// - Leaflet map with leaflet-draw for selecting the bbox.
// - Area stats update live as the rectangle is drawn/edited.
// - POSTs to /api/generate and renders results.

// Mirrors the server. Big areas are fetched as a grid of Overpass queries, so
// the cap is render memory and patience rather than one API call's limit.
// Where a map stops being an easy one. None of these stops anything: the
// window says what you are in for and the button stays lit. A limit that says
// no is worth having only when the thing behind it cannot be done, and a big
// map can be done - it costs memory and patience, which are the mapper's to
// spend.
const BIG_AREA_KM2 = 1000.0;
const BIG_TILES_PER_SIDE = 20000;
// Peak memory of Generate buildings, as in BUILD_BYTES_PER_TILE in app.py.
const BUILD_BYTES_PER_TILE = 24;
const BUILD_BASE_BYTES = 300e6;
const BIG_LANDMARK_KM2 = 40.0;
const OVERPASS_TILE_KM2 = 30.0;
const SLOW_ABOVE_KM2 = 60.0;

// ---- errors -------------------------------------------------------------
// Every failure the server answers with carries an id (E-7F3A2C) that is also
// in logs/knoxmap.log beside the full error; the page shows it, so a bug
// report can point straight at the line. See knoxlog.py.
let lastErrorId = null;

function apiError(data, res) {
  const err = new Error((data && data.error) || `HTTP ${res.status}`);
  err.errorId = data && data.errorId;
  lastErrorId = err.errorId || null;
  return err;
}

// Errors in this page's own code, which otherwise vanish inside the app
// window where there is no console to see them.
function sendPageError(message, where, stack) {
  try {
    fetch('/api/client-error', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: String(message).slice(0, 500),
                             where: String(where || '').slice(0, 300),
                             stack: String(stack || '').slice(0, 4000) }),
    }).catch(() => {});
  } catch (_) { /* nothing more to do */ }
}
window.addEventListener('error', e =>
  sendPageError(e.message, `${e.filename}:${e.lineno}:${e.colno}`, e.error && e.error.stack));
window.addEventListener('unhandledrejection', e =>
  sendPageError((e.reason && e.reason.message) || e.reason, 'unhandled promise',
                e.reason && e.reason.stack));

const map = L.map('map', { zoomControl: true }).setView([38.0406, -84.5037], 14);
// Tiles through KnoxMap's own server, which follows the OSM tile policy -
// see the /tiles route in app.py.
L.tileLayer('/tiles/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '© OpenStreetMap contributors',
}).addTo(map);

const drawnItems = new L.FeatureGroup().addTo(map);
const SEL_STYLE = { color: '#a5e266', weight: 2, fillOpacity: 0.1, className: 'sel-rect' };
const drawControl = new L.Control.Draw({
  draw: {
    polyline: false, marker: false, circlemarker: false,
    rectangle: { shapeOptions: SEL_STYLE },
    // Any outline, clicked point by point: a neighbourhood, a stretch of
    // coast, the blocks either side of a high street.
    polygon: { allowIntersection: false, showArea: true, shapeOptions: SEL_STYLE },
    circle: { shapeOptions: SEL_STYLE, showRadius: true, metric: true },
  },
  edit: { featureGroup: drawnItems, remove: true },
});
map.addControl(drawControl);

let currentRect = null;
let rotateHandleMarker = null;
let rotateHandleStem = null;
let isRotatingSelection = false;

function calculatePivot(layer) {
  const crs = map.options.crs || L.CRS.EPSG3857;
  if (layer instanceof L.Circle) {
    return layer.getLatLng();
  }
  const pts = flattenLatLngs(getShapeLatLngs(layer));
  if (!pts.length) return layer.getBounds().getCenter();
  let sumX = 0, sumY = 0;
  for (const pt of pts) {
    const p = crs.project(pt);
    sumX += p.x;
    sumY += p.y;
  }
  return crs.unproject(L.point(sumX / pts.length, sumY / pts.length));
}

function setSelection(layer) {
  drawnItems.clearLayers();
  currentRect = layer;
  currentRect._rotationAngle = 0;
  currentRect._pivot = calculatePivot(layer);
  currentRect._origPoints = getShapeLatLngs(currentRect);
  makeSelectionDraggable(layer);
  drawnItems.addLayer(currentRect);
  updateBboxFields();
  updateRotateHandle();
}

// ---- rotate the selection (Photoshop style) ------------------------------------
function rotateSingleLatLng(ll, pivot, rad) {
  const crs = map.options.crs || L.CRS.EPSG3857;
  const pPivot = crs.project(pivot);
  const p = crs.project(ll);
  const dx = p.x - pPivot.x;
  const dy = p.y - pPivot.y;
  // Pure rigid clockwise rotation in projected Web Mercator coordinates:
  // Zero distortion, zero drift, center point is 100% frozen in place.
  const rx = dx * Math.cos(rad) + dy * Math.sin(rad);
  const ry = -dx * Math.sin(rad) + dy * Math.cos(rad);
  return crs.unproject(L.point(pPivot.x + rx, pPivot.y + ry));
}

function rotateShapeCoords(item, pivot, rad) {
  if (Array.isArray(item)) {
    return item.map(child => rotateShapeCoords(child, pivot, rad));
  }
  return rotateSingleLatLng(item, pivot, rad);
}

function flattenLatLngs(items) {
  const out = [];
  function walk(x) {
    if (Array.isArray(x)) {
      for (const item of x) walk(item);
    } else if (x && typeof x.lat === 'number') {
      out.push(x);
    }
  }
  walk(items);
  return out;
}

function getShapeLatLngs(layer) {
  if (layer instanceof L.Rectangle) {
    const b = layer.getBounds();
    return [
      L.latLng(b.getNorth(), b.getWest()),
      L.latLng(b.getNorth(), b.getEast()),
      L.latLng(b.getSouth(), b.getEast()),
      L.latLng(b.getSouth(), b.getWest()),
    ];
  }
  if (layer instanceof L.Circle) {
    const c = layer.getLatLng();
    const r = layer.getRadius();
    const pts = [];
    for (let i = 0; i < 64; i++) {
      const a = (i / 64) * 2 * Math.PI;
      const dLat = (r * Math.cos(a)) / 111320;
      const dLon = (r * Math.sin(a)) / (111320 * Math.cos(c.lat * Math.PI / 180));
      pts.push(L.latLng(c.lat + dLat, wrapLon(c.lng + dLon)));
    }
    return pts;
  }
  if (layer instanceof L.Polygon) {
    const raw = layer.getLatLngs();
    return Array.isArray(raw[0]) ? raw[0] : raw;
  }
  return [];
}

function getShapeTopExtentPx(origPoints, pivot) {
  const cPt = map.latLngToLayerPoint(pivot);
  let maxUpPx = 25;
  for (const pt of flattenLatLngs(origPoints)) {
    const p = map.latLngToLayerPoint(pt);
    const up = cPt.y - p.y;
    if (up > maxUpPx) maxUpPx = up;
  }
  return maxUpPx;
}

function calcRotateHandlePositions(pivot, origPoints, angle) {
  const cPt = map.latLngToLayerPoint(pivot);
  const maxUpPx = getShapeTopExtentPx(origPoints, pivot);
  const stemLen = 24;
  const handleRadius = maxUpPx + stemLen;

  const alpha = -Math.PI / 2 + angle;
  const dx = Math.cos(alpha);
  const dy = Math.sin(alpha);

  const hPt = L.point(cPt.x + handleRadius * dx, cPt.y + handleRadius * dy);
  const sPt = L.point(cPt.x + maxUpPx * dx, cPt.y + maxUpPx * dy);

  return {
    handleLatLng: map.layerPointToLatLng(hPt),
    stemStartLatLng: map.layerPointToLatLng(sPt),
    cPt, maxUpPx, stemLen, handleRadius
  };
}

function removeRotateHandle() {
  if (rotateHandleMarker) {
    map.removeLayer(rotateHandleMarker);
    rotateHandleMarker = null;
  }
  if (rotateHandleStem) {
    map.removeLayer(rotateHandleStem);
    rotateHandleStem = null;
  }
}

function updateRotateHandle() {
  if (!currentRect || !drawnItems.hasLayer(currentRect)) {
    removeRotateHandle();
    return;
  }

  if (!currentRect._pivot) {
    currentRect._pivot = calculatePivot(currentRect);
    currentRect._origPoints = getShapeLatLngs(currentRect);
    currentRect._rotationAngle = 0;
  }

  const pos = calcRotateHandlePositions(
    currentRect._pivot,
    currentRect._origPoints,
    currentRect._rotationAngle || 0
  );

  if (!rotateHandleStem) {
    rotateHandleStem = L.polyline([pos.stemStartLatLng, pos.handleLatLng], {
      color: '#a5e266',
      weight: 2,
      opacity: 0.9,
      interactive: false,
      zIndexOffset: 1900,
    }).addTo(map);
  } else {
    rotateHandleStem.setLatLngs([pos.stemStartLatLng, pos.handleLatLng]);
  }

  if (!rotateHandleMarker) {
    createRotateHandle(pos.handleLatLng);
  } else {
    rotateHandleMarker.setLatLng(pos.handleLatLng);
    attachRotateHandleEvents(rotateHandleMarker);
  }
}

function createRotateHandle(latlng) {
  if (rotateHandleMarker) {
    map.removeLayer(rotateHandleMarker);
    rotateHandleMarker = null;
  }

  const icon = L.divIcon({
    className: 'rotate-handle-icon-container',
    html: `
      <div class="rotate-handle-wrapper">
        <div class="rotate-handle-badge" style="display: none;">0°</div>
        <button type="button" class="rotate-handle-btn" title="Rotate area (drag to rotate, Shift to snap, or click to turn 45°)" aria-label="Rotate area">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.19"/>
          </svg>
        </button>
      </div>
    `,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });

  rotateHandleMarker = L.marker(latlng, {
    icon: icon,
    interactive: true,
    zIndexOffset: 2000,
  }).addTo(map);

  attachRotateHandleEvents(rotateHandleMarker);
}

function rotateSelectionBy(deg) {
  if (!currentRect) return;
  if (!currentRect._pivot) {
    currentRect._pivot = calculatePivot(currentRect);
    currentRect._origPoints = getShapeLatLngs(currentRect);
    currentRect._rotationAngle = 0;
  }
  const angle = (currentRect._rotationAngle || 0) + (deg * Math.PI / 180);
  currentRect._rotationAngle = angle;

  const rotated = rotateShapeCoords(currentRect._origPoints, currentRect._pivot, angle);

  if (currentRect instanceof L.Rectangle || currentRect instanceof L.Circle) {
    const pivot = currentRect._pivot;
    const origPoints = currentRect._origPoints;
    drawnItems.removeLayer(currentRect);
    currentRect = L.polygon(rotated, SEL_STYLE);
    currentRect._pivot = pivot;
    currentRect._origPoints = origPoints;
    currentRect._rotationAngle = angle;
    makeSelectionDraggable(currentRect);
    drawnItems.addLayer(currentRect);
  } else {
    currentRect.setLatLngs(rotated);
  }

  updateBboxFields();
  updateRotateHandle();
}

function attachRotateHandleEvents(marker) {
  const el = marker.getElement();
  if (!el || el._rotateEventsAttached) return;
  el._rotateEventsAttached = true;

  const btn = el.querySelector('.rotate-handle-btn');
  const badge = el.querySelector('.rotate-handle-badge');
  if (!btn) return;

  L.DomEvent.disableClickPropagation(btn);
  L.DomEvent.disableScrollPropagation(btn);

  btn.addEventListener('contextmenu', (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    rotateSelectionBy(-45);
  });

  btn.addEventListener('mousedown', (ev) => {
    if (ev.button !== 0) return;
    if (!currentRect) return;
    L.DomEvent.stop(ev);
    L.DomEvent.preventDefault(ev);

    isRotatingSelection = true;
    map.dragging.disable();
    const mapBox = map.getContainer();
    mapBox.classList.add('rotate-dragging');
    document.body.classList.add('rotate-dragging');

    if (!currentRect._pivot) {
      currentRect._pivot = calculatePivot(currentRect);
      currentRect._origPoints = getShapeLatLngs(currentRect);
      currentRect._rotationAngle = 0;
    }

    const pivot = currentRect._pivot;
    const cPt = map.latLngToLayerPoint(pivot);
    const startMousePt = map.mouseEventToLayerPoint(ev);
    const startMouseAngle = Math.atan2(startMousePt.y - cPt.y, startMousePt.x - cPt.x);
    const startAngle = currentRect._rotationAngle || 0;

    const maxUpPx = getShapeTopExtentPx(currentRect._origPoints, pivot);
    const stemLen = 24;
    const handleRadius = maxUpPx + stemLen;

    let moved = false;

    const onMove = (e) => {
      const curMousePt = map.mouseEventToLayerPoint(e);
      if (!moved && Math.hypot(curMousePt.x - startMousePt.x, curMousePt.y - startMousePt.y) < 3) return;
      moved = true;

      const curMouseAngle = Math.atan2(curMousePt.y - cPt.y, curMousePt.x - cPt.x);
      let delta = curMouseAngle - startMouseAngle;

      if (e.shiftKey) {
        const snapStep = Math.PI / 12; // 15 degrees
        delta = Math.round(delta / snapStep) * snapStep;
      }

      const angle = startAngle + delta;
      currentRect._rotationAngle = angle;

      let deg = (angle * 180 / Math.PI) % 360;
      if (deg > 180) deg -= 360;
      if (deg < -180) deg += 360;

      if (badge) {
        badge.style.display = 'block';
        badge.textContent = `${deg >= 0 ? '+' : ''}${deg.toFixed(1)}°`;
      }

      const rotated = rotateShapeCoords(currentRect._origPoints, pivot, angle);

      if (currentRect instanceof L.Rectangle || currentRect instanceof L.Circle) {
        const origPivot = currentRect._pivot;
        const origPoints = currentRect._origPoints;
        drawnItems.removeLayer(currentRect);
        currentRect = L.polygon(rotated, SEL_STYLE);
        currentRect._pivot = origPivot;
        currentRect._origPoints = origPoints;
        currentRect._rotationAngle = angle;
        makeSelectionDraggable(currentRect);
        drawnItems.addLayer(currentRect);
      } else {
        currentRect.setLatLngs(rotated);
      }

      const alpha = -Math.PI / 2 + angle;
      const dx = Math.cos(alpha);
      const dy = Math.sin(alpha);

      const hPt = L.point(cPt.x + handleRadius * dx, cPt.y + handleRadius * dy);
      const sPt = L.point(cPt.x + maxUpPx * dx, cPt.y + maxUpPx * dy);

      const hLatLng = map.layerPointToLatLng(hPt);
      const sLatLng = map.layerPointToLatLng(sPt);

      marker.setLatLng(hLatLng);
      if (rotateHandleStem) {
        rotateHandleStem.setLatLngs([sLatLng, hLatLng]);
      }

      updateBboxFields();
    };

    const onUp = () => {
      window.removeEventListener('mousemove', onMove, true);
      window.removeEventListener('mouseup', onUp, true);
      map.dragging.enable();
      mapBox.classList.remove('rotate-dragging');
      document.body.classList.remove('rotate-dragging');
      isRotatingSelection = false;

      if (badge) badge.style.display = 'none';

      if (!moved) {
        rotateSelectionBy(45);
        return;
      }

      updateBboxFields();
      updateRotateHandle();
    };

    window.addEventListener('mousemove', onMove, true);
    window.addEventListener('mouseup', onUp, true);
  });
}

map.on('zoomend', updateRotateHandle);

// ---- drag the selection --------------------------------------------------------
// Press on the chosen area and drag it to somewhere else; the size and shape
// stay as they are. leaflet-draw only reshapes by the corners, so moving a
// whole rectangle, polygon, circle or a place's outline is done here. It stands
// aside while any drawing tool or the corner editor is in use.
let selDrawing = false;
map.on(L.Draw.Event.DRAWSTART, () => { selDrawing = true; });
map.on(L.Draw.Event.DRAWSTOP, () => { selDrawing = false; });

function shiftLatLngs(ll, dLat, dLng) {
  return Array.isArray(ll) ? ll.map(x => shiftLatLngs(x, dLat, dLng))
                           : L.latLng(ll.lat + dLat, ll.lng + dLng);
}

function makeSelectionDraggable(layer) {
  layer.on('mousedown', (ev) => {
    const oe = ev.originalEvent;
    if (oe && oe.button !== undefined && oe.button !== 0) return;
    if (isRotatingSelection) return;
    if (selDrawing || map.getContainer().classList.contains('lasso-armed')) return;
    if (layer.editing && layer.editing.enabled && layer.editing.enabled()) return;
    if (!drawnItems.hasLayer(layer)) return;
    L.DomEvent.stop(ev);                     // not a map pan, not a click
    if (oe) L.DomEvent.preventDefault(oe);   // and no text selection while dragging
    const isCircle = layer instanceof L.Circle;
    const startLL = ev.latlng;
    const start = isCircle ? layer.getLatLng() : layer.getLatLngs();
    const startPivot = currentRect && currentRect._pivot ? L.latLng(currentRect._pivot.lat, currentRect._pivot.lng) : null;
    const startOrigPoints = currentRect && currentRect._origPoints ? shiftLatLngs(currentRect._origPoints, 0, 0) : null;
    let moved = false;
    map.dragging.disable();
    map.getContainer().classList.add('sel-dragging');
    const move = (e) => {
      const dLat = e.latlng.lat - startLL.lat;
      const dLng = e.latlng.lng - startLL.lng;
      // A few pixels of wobble on a click is not a move.
      if (!moved && Math.hypot(e.containerPoint.x - ev.containerPoint.x,
                               e.containerPoint.y - ev.containerPoint.y) < 4) return;
      moved = true;
      if (isCircle) layer.setLatLng(L.latLng(start.lat + dLat, start.lng + dLng));
      else layer.setLatLngs(shiftLatLngs(start, dLat, dLng));
      if (currentRect && startPivot) {
        currentRect._pivot = L.latLng(startPivot.lat + dLat, startPivot.lng + dLng);
      }
      if (currentRect && startOrigPoints) {
        currentRect._origPoints = shiftLatLngs(startOrigPoints, dLat, dLng);
      }
      updateBboxFields();
      updateRotateHandle();
    };
    const up = () => {
      map.off('mousemove', move);
      document.removeEventListener('mouseup', up, true);
      map.dragging.enable();
      map.getContainer().classList.remove('sel-dragging');
      if (moved) updateBboxFields();
      updateRotateHandle();
    };
    map.on('mousemove', move);
    document.addEventListener('mouseup', up, true);
  });
}

map.on(L.Draw.Event.CREATED, (e) => {
  // The area selection and the drawing palette both finish a shape the same
  // way; which of them it belongs to is which of them armed the handler.
  if (zoneEd.claim(e.layer)) return;
  if (sketchEd.claim(e.layer)) return;
  setSelection(e.layer);
});

// One draw handler at a time on the world map: the area toolbar, the sketch
// palette and the zone tool each arm one, and two armed at once would both
// answer the same clicks. Whichever started last wins.
map.on(L.Draw.Event.DRAWSTART, () => {
  const mine = [sketchEd, zoneEd].find(e => e.kind);
  for (const e of [sketchEd, zoneEd]) if (e !== mine) e.stop();
});

// ---- freehand lasso ---------------------------------------------------------------
// Drag round what you want. The traced line is thinned to a polygon, so the
// server receives a few dozen points rather than every mouse move.
const LassoControl = L.Control.extend({
  options: { position: 'topleft' },
  onAdd() {
    const bar = L.DomUtil.create('div', 'leaflet-bar leaflet-control lasso-control');
    const a = L.DomUtil.create('a', 'lasso-btn', bar);
    a.href = '#';
    a.title = 'Draw freehand: drag round the area you want';
    a.innerHTML = '&#9998;';
    L.DomEvent.on(a, 'click', (ev) => { L.DomEvent.stop(ev); startLasso(a); });
    return bar;
  },
});
map.addControl(new LassoControl());

function startLasso(button) {
  const box = map.getContainer();
  button.classList.add('is-active');
  box.classList.add('lasso-armed');
  map.dragging.disable();
  let points = [];
  let trail = null;
  const down = (e) => {
    points = [e.latlng];
    trail = L.polyline(points, { color: '#a5e266', weight: 2, dashArray: '4 4' }).addTo(map);
    map.on('mousemove', move);
  };
  const move = (e) => { points.push(e.latlng); trail.setLatLngs(points); };
  const up = () => {
    map.off('mousedown', down); map.off('mousemove', move); map.off('mouseup', up);
    map.dragging.enable();
    button.classList.remove('is-active');
    box.classList.remove('lasso-armed');
    if (trail) map.removeLayer(trail);
    const thin = simplifyLatLngs(points, 8);
    if (thin.length >= 3) {
      setSelection(L.polygon(thin, SEL_STYLE));
      map.fire(L.Draw.Event.CREATED, { layer: currentRect, layerType: 'polygon', lasso: true });
    }
  };
  map.on('mousedown', down);
  map.on('mouseup', up);
}

// Douglas-Peucker on screen pixels, so "a few metres" means the same at every zoom.
function simplifyLatLngs(latlngs, tolerancePx) {
  if (latlngs.length < 3) return latlngs;
  const pts = latlngs.map(ll => map.latLngToLayerPoint(ll));
  const keep = new Array(pts.length).fill(false);
  keep[0] = keep[pts.length - 1] = true;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    let best = -1, bestD = tolerancePx;
    for (let i = a + 1; i < b; i++) {
      const d = L.LineUtil.pointToSegmentDistance(pts[i], pts[a], pts[b]);
      if (d > bestD) { best = i; bestD = d; }
    }
    if (best >= 0) { keep[best] = true; stack.push([a, best], [best, b]); }
  }
  return latlngs.filter((_, i) => keep[i]);
}

// The selection as GeoJSON for the server, or null for a plain rectangle.
function selectionShape() {
  if (!currentRect || currentRect instanceof L.Rectangle) return null;
  let rings;
  if (currentRect instanceof L.Circle) {
    const c = currentRect.getLatLng();
    const r = currentRect.getRadius();
    const ring = [];
    for (let i = 0; i < 64; i++) {
      const a = (i / 64) * 2 * Math.PI;
      const dLat = (r * Math.cos(a)) / 111320;
      const dLon = (r * Math.sin(a)) / (111320 * Math.cos(c.lat * Math.PI / 180));
      ring.push([wrapLon(c.lng + dLon), c.lat + dLat]);
    }
    ring.push(ring[0]);
    return { type: 'Polygon', coordinates: [ring] };
  }
  const geo = currentRect.toGeoJSON().geometry;
  const fold = coords => coords.map(ring => ring.map(([lon, lat]) => [wrapLon(lon), lat]));
  if (geo.type === 'Polygon') return { type: 'Polygon', coordinates: fold(geo.coordinates) };
  if (geo.type === 'MultiPolygon') return { type: 'MultiPolygon', coordinates: geo.coordinates.map(fold) };
  return null;
}

// Area inside the selection in km², on a local flat projection: plenty for
// town-sized shapes.
function selectionAreaKm2() {
  if (!currentRect) return null;
  if (currentRect instanceof L.Rectangle) {
    const b = currentRect.getBounds();
    const s = b.getSouth(), n = b.getNorth();
    const w = b.getWest(), e = b.getEast();
    return haversineKm(s, w, s, e) * haversineKm(s, w, n, w);
  }
  const shape = selectionShape();
  if (!shape) return null;
  const polys = shape.type === 'Polygon' ? [shape.coordinates] : shape.coordinates;
  let total = 0;
  for (const rings of polys) {
    rings.forEach((ring, idx) => {
      const lat0 = ring[0][1] * Math.PI / 180;
      let sum = 0;
      for (let i = 0; i < ring.length - 1; i++) {
        const [x1, y1] = [ring[i][0] * 111.32 * Math.cos(lat0), ring[i][1] * 111.32];
        const [x2, y2] = [ring[i + 1][0] * 111.32 * Math.cos(lat0), ring[i + 1][1] * 111.32];
        sum += x1 * y2 - x2 * y1;
      }
      total += (idx === 0 ? 1 : -1) * Math.abs(sum) / 2;
    });
  }
  return total;
}
map.on(L.Draw.Event.EDITED, () => {
  updateBboxFields();
  updateRotateHandle();
});
map.on(L.Draw.Event.DELETED, () => {
  currentRect = null;
  clearBboxFields();
  updateRotateHandle();
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
  const mpt = readScale();
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
  const heavy = [];
  if (area > BIG_AREA_KM2) {
    heavy.push(`${Math.round(area)} km² is bigger than maps usually are `
             + `(${BIG_AREA_KM2} km²).`);
  }
  if (side > BIG_TILES_PER_SIDE) {
    heavy.push(`${side} tiles a side is past what is comfortable `
             + `(${BIG_TILES_PER_SIDE}) — about ${bitmapFor(tilesX, tilesY)} of `
             + 'ground and greenery held in memory at once. Raising metres per '
             + 'tile is the cheapest fix: 2 m is a quarter of the memory of 1 m.');
  }
  const slow = !heavy.length && area > SLOW_ABOVE_KM2;
  const fitScale = heavy.length ? scaleThatFits(widthM, heightM, mpt) : null;
  const bitmap = bitmapFor(tilesX, tilesY);
  const buildGB = ((tilesX * tilesY * BUILD_BYTES_PER_TILE + BUILD_BASE_BYTES) / 1e9).toFixed(1);
  const fill = Math.min(100, (area / BIG_AREA_KM2) * 100);

  const shapeKm2 = selectionAreaKm2();
  const shapeVal = shapeKm2 !== null ? shapeKm2 : area;
  const isRu = (document.getElementById('language') && document.getElementById('language').value === 'russian')
    || (document.documentElement.lang === 'ru');

  stats.className = heavy.length ? 'warn' : (slow ? 'warn' : 'ok');
  stats.innerHTML = `
    <div class="tiles">
      ${fx.tile(shapeVal, 'km²', 'Shape area', shapeVal < 10 ? 2 : 1)}
      ${fx.tile(area, 'km²', 'Map area', area < 10 ? 2 : 1)}
      <div class="tile"><div class="v"><span data-count="${cellsX}">0</span><small>×</small><span
        data-count="${cellsY}">0</span></div><div class="k">Cells</div></div>
      ${fx.tile(tilesX * tilesY / 1e6, 'M', 'Tiles', 2)}
      ${fx.tile(queries, '', queries === 1 ? 'OSM query' : 'OSM queries')}
      ${fx.tile(Math.round(pixelsMB), 'MB', 'Bitmap', 0)}
    </div>
    <div class="meter">
      <div class="meter-top"><span>~${Math.round(widthM)} × ${Math.round(heightM)} m · ${bitmap} of bitmap · ~${buildGB} GB to add buildings</span>
        <span>${fill < 1 ? '<1' : Math.round(fill)}% of limit</span></div>
      <div class="bar"><div class="bar-fill" style="width:${fill}%"></div></div>
    </div>
    ${selectionShape() !== null && shapeKm2 !== null ? `<div class="stat-note shape">
      ${isRu
        ? `Застраивается только нарисованная фигура: <b>${shapeKm2.toFixed(2)} км²</b> (вся карта с сеткой ячеек: ${area.toFixed(1)} км², ${cellsX}×${cellsY} ячеек). Вне фигуры местность плавно переходит в дикую природу с продолжением основных дорог и рек.`
        : `Only the drawn shape is built: <b>${shapeKm2.toFixed(2)} km²</b> (bounding box: ${area.toFixed(1)} km², ${cellsX}×${cellsY} cells). Outside it the land turns back to countryside, with the main roads and rivers running on.`}
    </div>` : ''}
    ${heavy.length ? `<div class="stat-note warn">${heavy.join(' ')}
      You can still build it — this is a heads-up, not a wall.
      ${fitScale ? `<button type="button" class="use-scale" data-scale="${fitScale.mpt}">Use ${fitScale.mpt} m/tile
        (${fitScale.side} tiles a side, ${fitScale.bitmap})</button>` : ''}</div>` : ''}
    ${slow ? `<div class="stat-note warn">A big map — roughly ${Math.ceil(queries * 12 / 60)}+ min
      of OpenStreetMap queries before rendering starts.</div>` : ''}
  `;
  fx.countUp(stats);
  btn.disabled = false;
  fx.step('area', 'done');

  const lm = document.getElementById('landmarksBtn');
  lm.disabled = false;
  lm.title = area > BIG_LANDMARK_KM2
    ? `${Math.round(area)} km² is a lot to search for landmarks — it will take a while.`
    : '';
}

// ---- an area typed rather than drawn -----------------------------------------
// The four corner boxes are filled in by whatever is drawn on the map, and
// they also work the other way round: somebody who knows where their map ends
// - a county line, a coordinate out of another tool - types the degrees and
// gets the box, instead of nudging a rectangle until the numbers look right.
function coordsNote(text, bad) {
  const box = document.getElementById('coordsNote');
  box.textContent = text || '';
  box.classList.toggle('bad', !!bad);
}

function areaFromCoords() {
  const read = id => parseFloat(String(document.getElementById(id).value)
    .replace(',', '.'));
  const [s, w, n, e] = ['south', 'west', 'north', 'east'].map(read);
  if ([s, w, n, e].some(v => !Number.isFinite(v))) {
    coordsNote('Fill in all four corners first.', true);
    return;
  }
  // Said plainly rather than quietly swapped: a map built upside down from a
  // typo is worse than being told the typo.
  if (s >= n || w >= e) {
    coordsNote('South must be below north, and west left of east.', true);
    return;
  }
  if (Math.abs(s) > 85.05 || Math.abs(n) > 85.05 || Math.abs(w) > 180 || Math.abs(e) > 180) {
    coordsNote('Those are outside the map: 85 degrees north and south, 180 east and west.', true);
    return;
  }
  const layer = L.rectangle([[s, w], [n, e]], SEL_STYLE);
  setSelection(layer);
  map.fitBounds(layer.getBounds());
  coordsNote('Area taken from the corners you typed.');
}

document.getElementById('coordsApply').addEventListener('click', areaFromCoords);
for (const id of ['south', 'west', 'north', 'east']) {
  document.getElementById(id).addEventListener('keydown', ev => {
    if (ev.key === 'Enter') { ev.preventDefault(); areaFromCoords(); }
  });
}

function clearBboxFields() {
  ['south', 'west', 'north', 'east'].forEach(id => {
    document.getElementById(id).value = '';
  });
  const stats = document.getElementById('area-stats');
  stats.className = 'empty';
  stats.innerHTML = `<div class="empty-state">
    Draw an area on the map - rectangle, polygon, circle or freehand - to see what you'll get.</div>`;
  document.getElementById('generateBtn').disabled = true;
  document.getElementById('landmarksBtn').disabled = true;
  document.getElementById('landmark-results').innerHTML = '';
  fx.resetFrom('area');
  updateRotateHandle();
}

// The scale is typed, so it can be empty, half-typed or out of range. Whole
// metres only, 1 to 100 (MIN/MAX_METERS_PER_TILE in app.py); anything else
// becomes the nearest valid number, or 1, and the field is corrected so what
// is shown is what is used.
function readScale() {
  const el = document.getElementById('metersPerTile');
  let v = parseFloat(String(el.value).replace(',', '.'));
  if (!Number.isFinite(v)) return 1;
  // Quarter metres. Between 1 and 2 is where a scale earns its keep - a town
  // at full size, or everything in it half that - so the steps in between
  // are worth having. app.py settles it the same way (tidy_scale).
  return Math.min(100, Math.max(0.5, Math.round(v / 0.25) * 0.25));
}

function fixScaleField() {
  const el = document.getElementById('metersPerTile');
  el.value = String(readScale());
  updateBboxFields();
}

document.getElementById('metersPerTile').addEventListener('input', updateBboxFields);
document.getElementById('metersPerTile').addEventListener('change', fixScaleField);

// The smallest whole metres-per-tile, no finer than the one in use, at which
// the map is back inside the tiles-a-side warning and its bitmaps (3 bytes a
// tile, twice over) come to under 1.5 GB. Null when the scale
// is already as coarse as the window allows or nothing in range fits.
function scaleThatFits(widthM, heightM, current) {
  const MAX_BITMAP_MB = 1500;
  for (let s = Math.max(1, Math.floor(current) + 1); s <= 100; s++) {
    const tx = Math.ceil(widthM / s / 300) * 300;
    const ty = Math.ceil(heightM / s / 300) * 300;
    if (Math.max(tx, ty) <= BIG_TILES_PER_SIDE && tx * ty * 6 / 1e6 <= MAX_BITMAP_MB) {
      return { mpt: s, side: Math.max(tx, ty), bitmap: bitmapFor(tx, ty) };
    }
  }
  return null;
}

document.getElementById('area-stats').addEventListener('click', ev => {
  const btn = ev.target.closest('.use-scale');
  if (!btn) return;
  document.getElementById('metersPerTile').value = btn.dataset.scale;
  fixScaleField();
});

// Landscape and vegetation, 3 bytes a tile each, held at full size while the
// map is drawn. It is the number that decides whether a big map finishes.
function bitmapFor(tilesX, tilesY) {
  const mb = (tilesX * tilesY * 3 * 2) / 1e6;
  return mb < 1000 ? `${Math.round(mb)} MB` : `${(mb / 1000).toFixed(1)} GB`;
}

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
  m2_per_person:       ['Living space (m²)', 'Per resident. Lower = more crowded homes = more zombies. ~50 city, 45 town, 60 suburb.'],
  spawn_density:       ['Horde cap', 'Most zombies one 10×10 m spot can hold. Vanilla towns peak at 10.'],
  tree_density:        ['Woodland', 'Scales tree cover everywhere: the woods, the gardens and the scrub over open ground. Trees are cover to hide in.'],
  forest_density:      ['Forests', 'Scales the woods the mapper drew, on top of Woodland. Thick forest round a thinly planted town, or the other way about.'],
  seed:                ['Seed', 'Same seed and area gives the same town again.'],
  fill_gaps:           ['Fill gaps from Microsoft footprints', 'On adds the buildings OpenStreetMap has not got, from Microsoft’s machine-detected building footprints, same licence. Downloads about 30 MB per tile on the first run, nothing to install. Worth it where your town is half missing from OSM; elsewhere it adds sheds. Falls back to Overture (needs DuckDB) if Microsoft cannot be reached.'],
  true_map:            ['True map generation', 'On builds every address as mapped. Off keeps the real roads, rivers, woods and terrain, but leaves out half the houses and grows the rest into proper homes with yards. Named places are always built, at the game’s size.'],
  guaranteed_rifle:    ['Guaranteed rifle', 'On leaves one military rifle on the map: in an army building if there is one, else the police station, else a gun shop, else a house on the edge of town. A real town has no checkpoints for one to spawn in.'],
  min_size:            ['Smallest building', 'Buildings narrower than this many tiles are left out.'],
  align_streets:       ['Straighten streets', 'On turns the map so the main street grid runs along the tiles - no staircase roads. Off keeps north up.'],
  rotate_degrees:      ['Turn the map', 'Degrees to turn the whole area before it is built, on top of Straighten streets. Use it when the automatic angle picks the wrong grid.'],
  straight_roads:      ['Road layout', 'As mapped draws roads as they are. Knox County straight lays every road in straight runs along the tiles and on 45-degree diagonals. Vanilla curves routes them the way the game’s own B42 map draws its streets: along the tiles, 45 degrees and the 2:1 slopes, with its curves and street shapes. Built-up streets square keeps streets lined with buildings on the grid, as the buildings are, and off them. The vanilla choices take a few minutes on a town.'],
  max_size:            ['Largest building', 'Footprints above this are skipped.'],
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
}

function readSettings() {
  const out = { preset: document.getElementById('preset').value };
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

// ---- saved areas -----------------------------------------------------------------

let savedAreas = [];

function currentPortablePreset() {
  if (!currentRect) throw new Error('Draw an area first.');
  const b = rectBounds(currentRect);
  return {
    format: 'knoxmap-preset', version: 1,
    name: document.getElementById('presetName').value.trim()
      || document.getElementById('mapName').value.trim() || 'Shared area',
    south: b.s, west: b.w, north: b.n, east: b.e,
    shape: selectionShape(), metersPerTile: readScale(), settings: settingsForRequest(),
  };
}

async function validatePortablePreset(p) {
  const res = await fetch('/api/presets/validate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(p),
  });
  const data = await res.json();
  if (!res.ok) throw apiError(data, res);
  return data.preset;
}

function applyPortablePreset(p) {
  let layer;
  if (p.shape) {
    const polys = p.shape.type === 'Polygon' ? [p.shape.coordinates] : p.shape.coordinates;
    layer = L.polygon(polys.map(rings => rings.map(ring =>
      ring.map(([lon, lat]) => [lat, lon]))), SEL_STYLE);
  } else {
    layer = L.rectangle([[p.south, p.west], [p.north, p.east]], SEL_STYLE);
  }
  setSelection(layer);
  map.fitBounds(layer.getBounds());
  document.getElementById('metersPerTile').value = p.metersPerTile;
  document.getElementById('presetName').value = p.name;
  if (settingsMeta) {
    const kinds = document.getElementById('preset');
    kinds.value = [...kinds.options].some(option => option.value === p.preset)
      ? p.preset : 'town';
    buildSettingsForm({ ...settingsMeta.defaults, ...p.settings });
  }
  openedMap = null;
  importedSettings = { settings: p.settings, shown: readSettings() };
  showReapply();
  fixScaleField();
  presetNote(`Loaded "${p.name}".`);
}

async function importPortablePreset(raw) {
  if (!await settingsReady) throw new Error('Could not load the settings list.');
  const preset = await validatePortablePreset(raw);
  applyPortablePreset(preset);
  document.getElementById('presetsPanel').open = true;
}

function presetFromLink(link) {
  const url = new URL(link, location.href);
  const encoded = url.searchParams.get('preset');
  if (!encoded || encoded.length > 1000000) throw new Error('This link has no valid KnoxMap preset.');
  try { return JSON.parse(encoded); }
  catch (_) { throw new Error('This link has an unreadable KnoxMap preset.'); }
}

document.getElementById('presetExport').addEventListener('click', async () => {
  try {
    const preset = await validatePortablePreset(currentPortablePreset());
    const res = await fetch('/api/presets/export', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(preset),
    });
    if (!res.ok) throw apiError(await res.json(), res);
    if (IN_WINDOW) {
      const data = await res.json();
      presetNote(`Exported ${data.name} to ${data.folder}.`);
    } else {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${preset.name.replace(/[^A-Za-z0-9_-]+/g, '_') || 'area'}.knoxmap.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      presetNote(`Exported "${preset.name}".`);
    }
  } catch (err) { presetNote(err.message, 'bad'); }
});

document.getElementById('presetImport').addEventListener('click', () =>
  document.getElementById('presetFile').click());
document.getElementById('presetFile').addEventListener('change', async e => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    if (file.size > 1000000) throw new Error('The preset file is too large.');
    const content = await file.text();
    let preset;
    try { preset = JSON.parse(content); }
    catch (_) { throw new Error('The preset file is not valid JSON.'); }
    await importPortablePreset(preset);
  } catch (err) { presetNote(err.message, 'bad'); }
  finally { e.target.value = ''; }
});

document.getElementById('presetShare').addEventListener('click', async () => {
  try {
    const preset = await validatePortablePreset(currentPortablePreset());
    const url = new URL(location.href);
    url.search = '';
    url.hash = '';
    url.searchParams.set('preset', JSON.stringify(preset));
    if (url.href.length > 8000) {
      throw new Error('This outline makes a long link. Use Export file instead.');
    }
    let copied = false;
    if (navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(url.href); copied = true; }
      catch (_) { /* embedded windows sometimes deny the Clipboard API */ }
    }
    if (!copied) {
      const box = document.createElement('textarea');
      box.value = url.href;
      document.body.appendChild(box);
      box.select();
      const copied = document.execCommand('copy');
      box.remove();
      if (!copied) throw new Error('Clipboard unavailable. Use Export file instead.');
    }
    presetNote('Link copied. The recipient can paste it into Open link in KnoxMap.');
  } catch (err) { presetNote(err.message, 'bad'); }
});

document.getElementById('presetOpenLink').addEventListener('click', async () => {
  const link = window.prompt('Paste a KnoxMap preset link:');
  if (!link) return;
  try { await importPortablePreset(presetFromLink(link)); }
  catch (err) { presetNote(err.message, 'bad'); }
});

async function loadPresets() {
  try {
    savedAreas = (await (await fetch('/api/presets')).json()).presets || [];
  } catch (_) { savedAreas = []; }
  const list = document.getElementById('presetList');
  list.innerHTML = savedAreas.length
    ? savedAreas.map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join('')
    : '<option value="">(none saved yet)</option>';
  document.getElementById('presetsCount').textContent =
    savedAreas.length ? `(${savedAreas.length})` : '';
  for (const id of ['presetLoad', 'presetDelete']) {
    document.getElementById(id).disabled = !savedAreas.length;
  }
}

function presetNote(text, kind) {
  const el = document.getElementById('presetNote');
  el.textContent = text;
  el.className = kind === 'bad' ? 'hint bad' : 'hint';
}

document.getElementById('presetSave').addEventListener('click', async () => {
  const name = document.getElementById('presetName').value.trim()
    || document.getElementById('presetList').value;
  if (!currentRect) { presetNote('Draw an area first.', 'bad'); return; }
  if (!name) { presetNote('Give the area a name.', 'bad'); return; }
  const b = rectBounds(currentRect);
  try {
    const res = await fetch('/api/presets', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name, south: b.s, west: wrapLon(b.w), north: b.n, east: wrapLon(b.e),
        shape: selectionShape(), metersPerTile: readScale(),
        settings: settingsForRequest(),
      }),
    });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
    presetNote(`Saved "${name}".`);
    document.getElementById('presetName').value = '';
    await loadPresets();
    document.getElementById('presetList').value = name;
  } catch (err) { presetNote(err.message, 'bad'); }
});

document.getElementById('presetLoad').addEventListener('click', () => {
  const p = savedAreas.find(a => a.name === document.getElementById('presetList').value);
  if (!p) return;
  applyPortablePreset(p);
});

document.getElementById('presetDelete').addEventListener('click', async () => {
  const name = document.getElementById('presetList').value;
  if (!name) return;
  try {
    const res = await fetch(`/api/presets/${encodeURIComponent(name)}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
    presetNote(`Deleted "${name}".`);
    await loadPresets();
  } catch (err) { presetNote(err.message, 'bad'); }
});

loadPresets();

// ---- setup check -----------------------------------------------------------------

async function checkSetup() {
  try {
    const res = await fetch('/api/setup-status');
    const data = await res.json();
    const card = document.getElementById('setupCard');
    // Named after the script this PC actually has: Setup.bat on Windows,
    // ./setup.sh on Linux and macOS.
    const script = document.getElementById('setupScript');
    if (script && data.setupCommand) script.textContent = data.setupCommand;
    if (data.ready) { card.hidden = true; return; }
    document.getElementById('setupList').innerHTML = data.checks.map(c =>
      `<li class="${c.ok ? 'ok' : 'missing'}"><span>${c.ok ? '✓' : '✗'}</span>
        <b>${escapeHtml(c.label)}</b>${c.ok ? '' : ` — ${escapeHtml(c.fix)}`}</li>`).join('');
    card.hidden = false;
  } catch (_) { /* the page still works without the check */ }
}
checkSetup();

// ---- health check ----------------------------------------------------------------
//
// The same checks as the setup card, but always there, plus what this PC can
// hold and a test of the OpenStreetMap servers, which costs a few seconds.

document.getElementById('healthBtn').addEventListener('click', async () => {
  const btn = document.getElementById('healthBtn');
  const out = document.getElementById('healthOut');
  btn.disabled = true;
  out.innerHTML = '<p class="hint">Checking…</p>';
  try {
    const d = await (await fetch('/api/health?network=1')).json();
    const row = (ok, label, extra) =>
      `<li class="${ok ? 'ok' : 'missing'}"><span>${ok ? '✓' : '✗'}</span>
        <b>${escapeHtml(label)}</b>${extra ? ` — ${escapeHtml(extra)}` : ''}</li>`;
    const r = d.resources || {};
    const facts = [];
    if (r.ramTotalGB != null) {
      facts.push(`${r.ramFreeGB} of ${r.ramTotalGB} GB memory free`);
      facts.push(`room to draw about ${r.drawKm2} km² and add buildings to `
                 + `about ${r.buildKm2} km² at 1 m a tile`);
    }
    if (r.cores) facts.push(`${r.cores} processor threads, compiling ${r.compileWorkers} `
                            + `batch${r.compileWorkers === 1 ? '' : 'es'} at a time`);
    if (r.diskFreeGB != null) facts.push(`${r.diskFreeGB} GB free where maps are kept`);
    out.innerHTML = '<ul class="setup-list">'
      + d.checks.map(c => row(c.ok, c.label, c.ok ? '' : c.fix)).join('')
      + (d.overpass || []).map(o => row(o.ok, `OpenStreetMap server ${o.host}`,
          o.ok ? `${o.seconds} s` : 'not answering')).join('')
      + '</ul>'
      + (facts.length ? `<ul class="health-facts">${
          facts.map(f => `<li>${escapeHtml(f)}</li>`).join('')}</ul>` : '')
      + (d.overpass && d.overpass.every(o => !o.ok)
          ? '<p class="hint">No OpenStreetMap server answered. Check the internet '
            + 'connection; a download will not work until one does.</p>' : '');
  } catch (err) {
    out.innerHTML = `<p class="hint">Could not check: ${escapeHtml(err.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
});

// ---- map data server & osm_source ----------------------------------------------

const OSM_SOURCE_DESCS = {
  overpass: {
    title_ru: '⚡ Overpass API — Онлайн-запросы',
    desc_ru: 'Скачивает выделенный фрагмент с серверов ниже. При перегрузке делает ограниченное число повторов и сохраняет полученные части карты. Если серверы недоступны, выбери Auto или Geofabrik.',
    title_en: '⚡ Overpass API — Online queries',
    desc_en: 'Downloads the selected area from the servers below. Busy servers get a limited number of retries; downloaded parts are kept. If the servers are unreachable, choose Auto or Geofabrik.',
  },
  auto: {
    title_ru: '⚙ Авто (Auto)',
    desc_ru: 'Читает региональные данные Geofabrik, если установлен pyosmium. Файл скачивается один раз и сохраняется. Во время чтения показан текущий этап и число проверенных объектов. Если этот источник недоступен, используется Overpass.',
    title_en: '⚙ Auto mode',
    desc_en: 'Reads regional Geofabrik data when pyosmium is installed. The file is downloaded once and cached. Reading reports its current stage and object count. Falls back to Overpass if the extract is unavailable.',
  },
  extract: {
    title_ru: '📦 Geofabrik — Локальные данные',
    desc_ru: 'Скачивает и сохраняет файл региона Geofabrik, затем выбирает из него объекты для выделенной области. После загрузки работает без Overpass. Первое чтение большого региона требует времени; текущий этап отображается в окне.',
    title_en: '📦 Geofabrik — Local data',
    desc_en: 'Downloads and caches a Geofabrik region, then selects objects for your area. Works without Overpass after the download. The first read of a large region takes time; the current stage is shown in the window.',
  },
};

let currentOsmSource = 'overpass';

function setOsmSourceUI(source, saveToServer = true) {
  if (!OSM_SOURCE_DESCS[source]) source = 'overpass';
  currentOsmSource = source;

  const cards = document.querySelectorAll('.osm-source-card');
  cards.forEach(card => {
    const isThis = card.dataset.source === source;
    card.classList.toggle('is-on', isThis);
    card.setAttribute('aria-checked', isThis ? 'true' : 'false');
  });

  const isRu = (document.getElementById('language') && document.getElementById('language').value === 'russian')
    || (document.documentElement.lang === 'ru');
  const info = OSM_SOURCE_DESCS[source];
  const descEl = document.getElementById('osmSourceDesc');
  if (descEl) {
    descEl.innerHTML = `<b>${escapeHtml(isRu ? info.title_ru : info.title_en)}</b><br>${escapeHtml(isRu ? info.desc_ru : info.desc_en)}`;
  }

  if (saveToServer) {
    fetch('/api/overpass', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ osm_source: source }),
    }).then(r => r.json()).then(() => {
      note('overpassNote', isRu ? `Режим данных карты: ${source}` : `Map data source set to ${source}`, 'ok');
    }).catch(err => {
      note('overpassNote', err.message, 'bad');
    });
  }
}

document.querySelectorAll('.osm-source-card').forEach(card => {
  card.addEventListener('click', () => {
    setOsmSourceUI(card.dataset.source, true);
  });
});

(async function loadOverpass() {
  try {
    const d = await (await fetch('/api/overpass')).json();
    document.getElementById('overpassList').value = (d.endpoints || []).join('\n');
    setOsmSourceUI(d.osm_source || 'overpass', false);
  } catch (_) {
    setOsmSourceUI('overpass', false);
  }
})();

document.getElementById('overpassSave').addEventListener('click', async () => {
  const btn = document.getElementById('overpassSave');
  btn.disabled = true;
  try {
    const res = await fetch('/api/overpass', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        endpoints: document.getElementById('overpassList').value,
        osm_source: currentOsmSource,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
    note('overpassNote', data.endpoints.length
         ? `Downloads now use ${data.endpoints.length} server${data.endpoints.length === 1 ? '' : 's'} of yours.`
         : 'Downloads use the public servers.', 'ok');
  } catch (err) {
    note('overpassNote', err.message, 'bad');
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('overpassPublic').addEventListener('click', async () => {
  try {
    const d = await (await fetch('/api/overpass')).json();
    document.getElementById('overpassList').value = (d.public || []).join('\n');
    note('overpassNote', 'Edit the list, then press Save.', 'ok');
  } catch (err) { note('overpassNote', err.message, 'bad'); }
});

document.getElementById('overpassTest').addEventListener('click', async () => {
  const btn = document.getElementById('overpassTest');
  const out = document.getElementById('overpassStatus');
  btn.disabled = true;
  out.innerHTML = '<p class="hint">Asking each server…</p>';
  try {
    const d = await (await fetch('/api/overpass/status')).json();
    out.innerHTML = '<ul class="setup-list">' + d.servers.map(s =>
      `<li class="${s.ok ? 'ok' : 'missing'}"><span>${s.ok ? '✓' : '✗'}</span>
        <b>${escapeHtml(s.host)}</b> — ${s.ok ? `${s.seconds} s` : 'not answering'}${
          s.regional ? ' (one region only)' : ''}${s.resting ? ', resting' : ''}</li>`).join('')
      + '</ul>' + (d.servers.some(s => s.ok && !s.regional) ? ''
        : '<p class="hint">No server with worldwide data answered. Downloads will wait '
          + 'and retry; a server of your own avoids this.</p>');
  } catch (err) {
    out.innerHTML = `<p class="hint">Could not test: ${escapeHtml(err.message)}</p>`;
  } finally { btn.disabled = false; }
});

// A server of your own in Docker.
let localTimer = null;
async function localCall(action, extra) {
  const res = await fetch('/api/local-overpass', extra === undefined && !action
    ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action, ...extra }) });
  const data = await res.json();
  if (!res.ok) throw apiError(data, res);
  return data;
}
function showLocal(d) {
  const text = !d.docker ? 'Docker was not found. Install Docker Desktop and start it.'
    : { none: 'Not set up.', stopped: 'Stopped.', ready: 'Running and ready.',
        loading: 'Loading the region' + (d.log ? ` — ${d.log}` : '…') }[d.state];
  note('localNote', text, d.state === 'ready' ? 'ok' : '');
  const show = (id, on) => { document.getElementById(id).hidden = !on; };
  document.getElementById('localExtract').hidden = d.state !== 'none';
  show('localStart', d.docker && d.state !== 'loading' && d.state !== 'ready');
  show('localUse', d.state === 'ready');
  show('localStop', d.state === 'ready' || d.state === 'loading');
  show('localRemove', d.docker && d.state !== 'none');
  clearTimeout(localTimer);
  if (d.state === 'loading') localTimer = setTimeout(refreshLocal, 15000);
}
async function refreshLocal() {
  try { showLocal(await localCall()); } catch (_) { /* leave it as it was */ }
}
for (const [id, action] of [['localStart', 'start'], ['localUse', 'use'],
                            ['localStop', 'stop'], ['localRemove', 'remove']]) {
  document.getElementById(id).addEventListener('click', async () => {
    try {
      if (action === 'remove' && !confirm('Remove the local server and its loaded map data?')) return;
      showLocal(await localCall(action, { extract: document.getElementById('localExtract').value }));
      if (action === 'use') note('localNote', 'Downloads now try your server first.', 'ok');
    } catch (err) { note('localNote', err.message, 'bad'); }
  });
}
document.getElementById('overpassPanel').addEventListener('toggle', e => {
  if (e.target.open) refreshLocal(); else clearTimeout(localTimer);
});

// ---- before publishing -----------------------------------------------------------

document.getElementById('publishCheckBtn').addEventListener('click', async () => {
  const btn = document.getElementById('publishCheckBtn');
  const out = document.getElementById('publishOut');
  btn.disabled = true;
  out.innerHTML = '<p class="hint">Checking…</p>';
  try {
    const q = new URLSearchParams({
      modId: document.getElementById('modId').value.trim(), map: currentMap || '' });
    const res = await fetch('/api/workshop-check?' + q);
    const d = await res.json();
    if (!res.ok) throw apiError(d, res);
    const mark = { ok: '✓', warn: '!', bad: '✗' };
    out.innerHTML = '<ul class="setup-list">' + d.results.map(r =>
      `<li class="${r.level === 'ok' ? 'ok' : 'missing'}"><span>${mark[r.level]}</span>
        <b>${escapeHtml(r.what)}</b>${r.fix ? ` — ${escapeHtml(r.fix)}` : ''}</li>`).join('')
      + '</ul>' + `<p class="hint">${d.ready
        ? (d.warn ? 'Nothing stops you publishing; the warnings above are worth a look.'
                  : 'Ready to publish.')
        : `${d.bad} thing${d.bad === 1 ? '' : 's'} to fix before publishing.`}</p>`;
  } catch (err) {
    out.innerHTML = `<p class="hint">Could not check: ${escapeHtml(err.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
});

// ---- Steam libraries -------------------------------------------------------------
//
// Found on their own; a drive that was missed (or that Steam still lists after
// it is gone) can be named here instead of running Setup again.

function showSteamLibraries(data) {
  document.getElementById('steamList').innerHTML = data.libraries.length
    ? data.libraries.map(l => `<li class="ok"><span>✓</span>${escapeHtml(l.path)}${
        l.chosen ? ' <i>(chosen)</i>' : ''}</li>`).join('')
    : '<li class="missing"><span>✗</span>No Steam library found</li>';
  const field = document.getElementById('steamFolders');
  if (document.activeElement !== field) field.value = (data.chosen || []).join('; ');
  document.getElementById('steamNote').className = 'hint';
  document.getElementById('steamNote').textContent =
    data.game ? `Project Zomboid: ${data.game}` : 'Project Zomboid was not found in these.';
}

async function loadSteamLibraries() {
  try {
    showSteamLibraries(await (await fetch('/api/steam-libraries')).json());
  } catch (_) { /* optional */ }
}

document.getElementById('steamLibraries').addEventListener('toggle', e => {
  if (e.target.open) loadSteamLibraries();
});

document.getElementById('steamSave').addEventListener('click', async () => {
  const folders = document.getElementById('steamFolders').value
    .split(';').map(s => s.trim()).filter(Boolean);
  try {
    const res = await fetch('/api/steam-libraries', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folders }),
    });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
    showSteamLibraries(data);
    checkSetup();
  } catch (err) {
    note('steamNote', err.message, 'bad');
  }
});

// ---- Zomboid folder --------------------------------------------------------------

function showZomboidFolder(data) {
  const field = document.getElementById('zomboidFolder');
  if (document.activeElement !== field) field.value = data.chosen ? data.folder : '';
  document.getElementById('zomboidNote').className = 'hint';
  document.getElementById('zomboidNote').textContent = `Maps go into ${data.mods}`;
}

document.getElementById('zomboidFolderBox').addEventListener('toggle', async e => {
  if (!e.target.open) return;
  try {
    showZomboidFolder(await (await fetch('/api/zomboid-folder')).json());
  } catch (_) { /* optional */ }
});

document.getElementById('zomboidSave').addEventListener('click', async () => {
  try {
    const res = await fetch('/api/zomboid-folder', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: document.getElementById('zomboidFolder').value }),
    });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
    showZomboidFolder(data);
    checkSetup();
    loadMaps();
  } catch (err) {
    note('zomboidNote', err.message, 'bad');
  }
});

const settingsReady = loadSettings().then(() => true).catch(() => {
  document.getElementById('advanced-body').textContent =
    'Could not load the settings list.';
  return false;
});

// ---- maps already made -----------------------------------------------------------
//
// A map does not have to be drawn again when KnoxMap is updated: each step
// records the version that ran it (knoxbuild/mapstate.py), so opening one an
// older release made says which steps are out of date - usually Install alone -
// and offers to run just those.

async function loadMaps() {
  let data;
  try {
    data = await (await fetch('/api/maps')).json();
  } catch (_) { return; }
  const list = document.getElementById('mapList');
  const card = document.getElementById('mapsCard');
  if (!data.maps || !data.maps.length) { card.hidden = true; return; }
  card.hidden = false;
  document.getElementById('mapsCount').textContent = `(${data.maps.length})`;
  list.innerHTML = '';
  for (const m of data.maps) {
    const li = document.createElement('li');
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = m.mapName;
    const size = document.createElement('span');
    size.className = 'size';
    size.textContent = `${m.cellsX}×${m.cellsY} cells`;
    li.append(name, size);
    if (m.needs.length) {
      const tag = document.createElement('span');
      tag.className = 'old';
      tag.textContent = m.madeWith === 'an early release' ? 'older release'
        : `made with ${m.madeWith}`;
      li.append(tag);
    }
    const install = document.createElement('span');
    if (!m.installed) {
      install.className = 'size';
      install.textContent = 'not installed';
    } else {
      install.className = m.installed.upToDate ? 'size' : 'old';
      install.textContent = m.installed.upToDate ? 'installed' : 'installed before last compile';
      install.title = m.installed.modRoot;
    }
    li.append(install);
    const open = document.createElement('button');
    open.type = 'button';
    open.textContent = 'Open';
    open.addEventListener('click', () => openMap(m.mapName));
    li.append(open);
    if (m.installed) {
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = 'Uninstall';
      remove.addEventListener('click', () => uninstallMap(m.mapName));
      const update = document.createElement('button');
      update.type = 'button';
      update.textContent = 'Update';
      update.title = 'Install the latest compile over the installed copy';
      if (!m.installed.upToDate) update.className = 'btn-primary';
      update.addEventListener('click', () => updateMap(m.mapName, update));
      li.append(update, remove);
    }
    list.append(li);
  }
}

async function updateMap(mapName, btn) {
  // The same install as the Install button, into the same mod folder under the
  // same name; the copy already there is replaced.
  btn.disabled = true;
  try {
    const res = await fetch('/api/install', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mapName }),
    });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
    fx.toast('ok', 'Updated in the game', `${mapName}: ${data.cells} cells`, 6000);
    loadMaps();
  } catch (err) {
    fx.toast('bad', 'Could not update that map', err.message, 8000);
    btn.disabled = false;
  }
}

async function uninstallMap(mapName) {
  // Only the copy in the game's mods folder goes; the map's own files stay, and
  // so do the player's saves.
  if (!window.confirm(`Remove ${mapName} from the game's mods folder? Its files in `
      + 'KnoxMap stay, and your saves are not touched.')) return;
  try {
    const res = await fetch('/api/uninstall', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mapName }),
    });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
    fx.toast('ok', 'Removed from the game', mapName, 6000);
    loadMaps();
  } catch (err) {
    fx.toast('bad', 'Could not remove that map', err.message, 8000);
  }
}

async function openMap(mapName) {
  let data;
  try {
    const res = await fetch(`/api/maps/${encodeURIComponent(mapName)}`);
    data = await res.json();
    if (!res.ok) throw apiError(data, res);
  } catch (err) {
    fx.toast('bad', 'Could not open that map', err.message, 8000);
    return;
  }
  renderResults(data);
  showUpgrade(data);
  // The settings this map was made with, back in the panel, so one of them can
  // be changed and put into it without setting all the others again.
  if (data.settings && settingsMeta) buildSettingsForm(data.settings);
  // Whatever was drawn for this map, back on the map to be added to or changed.
  loadZones(data.mapName);
  fetch(`/api/sketch/${encodeURIComponent(data.mapName)}`)
    .then(r => r.json())
    .then(loadSketchGeoJSON)
    .catch(() => { /* a map with nothing drawn simply has none */ });
  rememberMap({ mapName: data.mapName, bbox: data.bbox,
                metersPerTile: data.metersPerTile, shape: data.shape,
                settings: data.settings });
}

function showUpgrade(data) {
  const box = document.getElementById('upgradeNote');
  if (!box) return;
  if (!data.needs || !data.needs.length) { box.hidden = true; box.innerHTML = ''; return; }
  const steps = data.needsLabels.join(' → ');
  box.hidden = false;
  box.innerHTML = '<span></span>';
  // A map this KnoxMap made itself is not "from an earlier release": it is
  // simply a step short, usually the install it has never had.
  box.querySelector('span').textContent = data.madeWith === data.current
    ? `This map still needs: ${steps}.`
    : `This map was made with ${data.madeWith === 'an early release'
        ? 'an earlier release' : 'KnoxMap ' + data.madeWith}. `
      + `Do you want to upgrade it to ${data.current}? It needs: ${steps}.`;
  const go = document.createElement('button');
  go.type = 'button';
  go.textContent = 'Upgrade';
  go.addEventListener('click', () => upgradeMap(data, go));
  const later = document.createElement('button');
  later.type = 'button';
  later.className = 'later';
  later.textContent = 'Not now';
  later.addEventListener('click', () => { box.hidden = true; });
  box.append(go, later);
}

// ---- a picture of the finished map ------------------------------------------------
// Drawn from the compiled cells the game itself loads, so it is the map rather
// than an impression of it - which is why it needs the map compiled, and why
// it takes the better part of a minute and runs on its own thread.
function wirePictures(mapName) {
  const button = document.getElementById('makePictures');
  const note = document.getElementById('pictureNote');
  const shots = document.getElementById('pictureShots');
  if (!button) return;
  button.hidden = false;
  note.textContent = '';
  shots.hidden = true;
  shots.innerHTML = '';

  const show = files => {
    shots.innerHTML = '';
    const names = { 'town.png': 'The whole map', 'close.png': 'Close up',
                    'inside.png': 'With the roofs off' };
    for (const url of files) {
      const file = url.split('/').pop();
      const link = document.createElement('a');
      link.href = url;
      link.target = '_blank';
      link.title = names[file] || file;
      const img = document.createElement('img');
      img.src = `${url}?t=${Date.now()}`;   // a redraw replaces the same file
      img.alt = link.title;
      link.append(img);
      shots.append(link);
    }
    shots.hidden = files.length === 0;
  };

  button.onclick = async () => {
    button.disabled = true;
    note.className = 'hint';
    note.textContent = 'Drawing the map — this takes a minute…';
    try {
      const res = await fetch('/api/pictures', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mapName }),
      });
      const started = await res.json();
      if (!res.ok) throw apiError(started, res);
      for (;;) {
        await new Promise(r => setTimeout(r, 1500));
        const st = await (await fetch(
          `/api/pictures-status?map=${encodeURIComponent(mapName)}`)).json();
        if (st.state === 'running') continue;
        if (st.error) throw new Error(st.error);
        show(st.files || []);
        note.textContent = 'Click one to see it full size.';
        break;
      }
    } catch (err) {
      note.className = 'hint error';
      note.textContent = err.message || String(err);
    } finally {
      button.disabled = false;
      button.textContent = 'Draw it again';
    }
  };
}


async function upgradeMap(data, button) {
  const box = document.getElementById('upgradeNote');
  const say = text => { box.querySelector('span').textContent = text; };
  for (const b of box.querySelectorAll('button')) b.disabled = true;
  const post = async (url, body) => {
    const res = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const out = await res.json();
    if (!res.ok) throw apiError(out, res);
    return out;
  };
  try {
    for (const step of data.needs) {
      if (step === 'generate') {
        say(`Drawing ${data.mapName} again…`);
        const b = data.bbox || {};
        await post('/api/generate', {
          south: b.south, west: b.west, north: b.north, east: b.east,
          metersPerTile: data.metersPerTile, mapName: data.mapName,
          settings: data.settings, shape: data.shape,
        });
      } else if (step === 'build') {
        say('Building the buildings again…');
        await post('/api/buildings', { mapName: data.mapName, settings: data.settings });
      } else if (step === 'compile') {
        say('Compiling…');
        await post('/api/compile', { mapName: data.mapName });
        for (;;) {
          await new Promise(r => setTimeout(r, 5000));
          const st = await (await fetch(
            `/api/compile-status?map=${encodeURIComponent(data.mapName)}`)).json();
          if (st.state === 'running') {
            say(`Compiling… ${st.cells || 0} of ${st.expected || '?'} cells`);
            continue;
          }
          if (st.error) throw new Error(st.error);
          break;
        }
      } else if (step === 'install') {
        say('Installing…');
        await post('/api/install', { mapName: data.mapName, title: data.mapName,
                                     modId: data.mapName });
      }
    }
    box.innerHTML = '<span></span>';
    box.querySelector('span').textContent =
      `${data.mapName} is up to date with KnoxMap ${data.current}.`;
    fx.toast('ok', 'Map upgraded', `${data.needsLabels.join(', ')} ran again.`);
    loadMaps();
  } catch (err) {
    say(`Could not upgrade it: ${err.message}`);
    for (const b of box.querySelectorAll('button')) b.disabled = false;
    if (button) button.textContent = 'Try again';
  }
}

loadMaps();

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
    metersPerTile: readScale(),
    mapName: chosen,
    settings: settingsForRequest(),
    shape: selectionShape(),
    // What was drawn by hand, and whether it is the whole map.
    sketch: sketchGeoJSON(),
    drawnOnly: document.getElementById('drawnOnly').checked,
  };

  const btn = document.getElementById('generateBtn');
  const status = document.getElementById('status');
  btn.disabled = true;
  status.className = '';
  status.textContent = 'Starting…';
  fx.step('style', 'done');
  fx.step('terrain', 'running');
  fx.overlay.show();
  showStop(chosen);
  startProgress(chosen);

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (wasStopped(data, res)) {
      status.className = '';
      status.textContent = 'Stopped. The area is still drawn - press Generate map to start again.';
      fx.overlay.hide();
      fx.step('terrain', '');
      fx.toast('ok', 'Stopped', 'The area and the settings are as you left them.');
      return;
    }
    if (!res.ok) throw apiError(data, res);

    status.className = 'success';
    status.textContent = `Done in ${data.osmSeconds}s (OSM query). ${data.featureCount} features rendered.`;
    fx.overlay.done(`${data.featureCount.toLocaleString()} features on the map`);
    fx.step('terrain', 'done');
    fx.toast('ok', 'Terrain generated',
             `${data.cellsX} × ${data.cellsY} cells from ${data.featureCount.toLocaleString()} features.`);
    renderResults(data);
    // What it was just made from, so a knob can be moved and put into it
    // without drawing the box again.
    rememberMap({ mapName: chosen,
                  bbox: { south: bb.s, west: bb.w, north: bb.n, east: bb.e },
                  metersPerTile: body.metersPerTile, shape: body.shape,
                  settings: data.settings || body.settings });
    loadMaps();
  } catch (err) {
    status.className = 'error';
    status.textContent = `Error: ${err.message}`;
    fx.overlay.fail(err.message);
    fx.step('terrain', 'error');
    fx.problem('Generation failed', err.message, err.errorId);
  } finally {
    stopProgress();
    showStop(null);
    btn.disabled = false;
  }
});

// ---- stopping a long step ----
//
// Generating, building and compiling take minutes, and the only way out of
// one used to be closing the window - which threw the drawn rectangle away
// with it. The Stop button asks the server to drop the job where it can be
// dropped safely; nothing here touches the selection, the settings or the
// map name, so pressing the step again starts the same map over.

let stoppingMap = null;

function showStop(mapName) {
  stoppingMap = null;
  document.querySelectorAll('[data-stop]').forEach(b => {
    b.hidden = !mapName;
    b.disabled = false;
    b.textContent = 'Stop';
  });
  runningMap = mapName;
}

let runningMap = null;

async function requestStop() {
  if (!runningMap || stoppingMap === runningMap) return;
  stoppingMap = runningMap;
  document.querySelectorAll('[data-stop]').forEach(b => {
    b.disabled = true;
    b.textContent = 'Stopping…';
  });
  try {
    await fetch('/api/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mapName: runningMap }),
    });
  } catch (_) { /* the step's own reply is the source of truth */ }
}

document.addEventListener('click', ev => {
  if (ev.target.closest('[data-stop]')) requestStop();
});

// A reply the server sends when a step was stopped on purpose. Not an error:
// no red, no problem report, and the area stays drawn.
function wasStopped(data, res) {
  return res.status === 409 && data && data.stopped;
}

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
        // A retry waits a minute or two with nothing moving; say so, or it
        // reads as a hang and gets killed just before the pass that works.
        status.textContent = p.note
          ? p.note
          : (total > 1
            ? `Querying OpenStreetMap — area ${(p.done || 0) + 1} of ${total}…`
            : 'Querying OpenStreetMap…');
      } else if (p.stage === 'overture') {
        // A few minutes, nearly all of it Overture's own files being sifted
        // for the handful that cover this box. Saying so beats a dead bar.
        status.textContent = 'Looking up the buildings OpenStreetMap has not got '
                           + '— this takes a few minutes the first time…';
      } else if (p.stage === 'roads') {
        status.textContent = `Routing the roads — ${(p.done || 0).toLocaleString()} of `
                           + `${(p.total || 0).toLocaleString()} stretches…`;
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

// In the app window a download link does nothing: it is a WebView, with
// nowhere to put a file. Everything is on disk already, so there the links
// ask the server to save the file and show it in Explorer instead.
const IN_WINDOW = document.body.dataset.inWindow === '1';

async function saveFile(name, label) {
  const note = document.getElementById('saveNote');
  if (note) { note.className = 'hint'; note.textContent = `Saving ${label}…`; }
  try {
    const res = await fetch('/api/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mapName: currentMap, name }),
    });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
    if (note) note.textContent = `Saved ${data.name} in ${data.folder} (shown in Explorer).`;
  } catch (err) {
    if (note) { note.className = 'hint bad'; note.textContent = err.message; }
    fx.toast('bad', 'Could not save that file', err.message, 8000);
  }
}

function wireDownload(link, name, label) {
  if (!IN_WINDOW) return;
  link.removeAttribute('download');
  link.href = '#';
  link.addEventListener('click', e => { e.preventDefault(); saveFile(name, label); });
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
  all.textContent = IN_WINDOW ? 'Save everything as a .zip' : 'Download everything (.zip)';
  wireDownload(all, 'zip', 'the zip');
  const note = document.getElementById('saveNote');
  if (note) { note.className = 'hint'; note.textContent = ''; }
  wirePictures(data.mapName);

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
  ul.querySelectorAll('a').forEach((link, i) => {
    const href = entries[i][1];
    wireDownload(link, href.split('/').pop(), entries[i][0]);
  });
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
  setSelection(L.rectangle(bounds, SEL_STYLE));
}

// A place's own boundary from the search result, as the selection.
function setOutline(geojson) {
  const flip = rings => rings.map(ring => ring.map(([lon, lat]) => [lat, lon]));
  const latlngs = geojson.type === 'Polygon' ? flip(geojson.coordinates)
                                             : geojson.coordinates.map(flip);
  setSelection(L.polygon(latlngs, SEL_STYLE));
  return currentRect.getBounds();
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
  if (km2 <= BIG_AREA_KM2 && widthKm >= MIN_BOX_KM && heightKm >= MIN_BOX_KM) {
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
      ${r.outline ? `<button type="button" class="r-outline" data-outline="${i}"
        title="Select its real boundary instead of a box">outline</button>` : ''}
      <span class="r-where">${escapeHtml(rest)}</span>
    </li>`;
  }).join('');
  searchResults.hidden = false;

  searchResults.querySelectorAll('button[data-outline]').forEach(btn => {
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const r = results[parseInt(btn.dataset.outline, 10)];
      const bounds = setOutline(r.outline);
      map.fitBounds(bounds, { padding: [30, 30] });
      hideSearchResults();
      searchInput.value = r.name;
    });
  });

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
    if (!res.ok) throw apiError(data, res);
    renderSearchResults(data.results);
  } catch (err) {
    searchResults.innerHTML = `<li class="empty">${escapeHtml(err.message)}</li>`;
  }
}

// Search runs when you press Enter, never as you type. Nominatim's usage
// policy forbids autocomplete-style searching on its public server
// (https://operations.osmfoundation.org/policies/nominatim/).
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
  out.innerHTML = '<div class="hint">Looking…</div>';

  try {
    const res = await fetch('/api/landmarks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        south: bb.s, west: bb.w, north: bb.n, east: bb.e,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
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

// ---- finding something in a long list -------------------------------------
//
// The palettes run to 113 rooms and 63 things to draw, the settings to
// twenty-six, and a map can carry any number of zones and hand-built
// buildings. Reading one of those by eye to find the one thing wanted is the
// slowest part of using the window, so each gets a box that narrows it to
// what matches as it is typed.
//
// Nothing is removed, only hidden, so emptying the box puts the list back
// exactly as it was - and the search is run again every time the list is
// drawn, because all of these are rebuilt from scratch whenever anything in
// them changes.
const LIST_SEARCHES = {};

function searchableList(inputId, boxId, item, group, least = 8) {
  const input = document.getElementById(inputId);
  if (!input || !document.getElementById(boxId)) return;
  LIST_SEARCHES[boxId] = { input, item, group, least, query: '' };
  input.addEventListener('input', () => {
    LIST_SEARCHES[boxId].query = input.value;
    runListSearch(boxId);
  });
  input.addEventListener('keydown', ev => {
    // Escape empties it, as it does in any search box.
    if (ev.key === 'Escape' && input.value) {
      ev.stopPropagation();
      input.value = '';
      LIST_SEARCHES[boxId].query = '';
      runListSearch(boxId);
    }
  });
  runListSearch(boxId);
}

// What a line of a list can be found by: what it says, what its tooltip says
// - the palettes keep the OpenStreetMap tags there - and anything the list
// put in data-find itself.
function listHaystack(el) {
  return (`${el.textContent} ${el.getAttribute('title') || ''} `
          + `${el.dataset.find || ''}`).toLowerCase();
}

function runListSearch(boxId) {
  const found = LIST_SEARCHES[boxId];
  const box = document.getElementById(boxId);
  if (!found || !box) return;
  const items = [...box.querySelectorAll(found.item)];
  // A list short enough to read at a glance is one nobody needs to search.
  found.input.hidden = items.length < found.least;
  if (found.input.hidden && found.query) {
    found.input.value = '';
    found.query = '';
  }
  const words = found.query.toLowerCase().split(/\s+/).filter(Boolean);
  let shown = 0;
  for (const el of items) {
    const hay = listHaystack(el);
    const hit = words.every(word => hay.includes(word));
    el.classList.toggle('out-of-search', !hit);
    shown += hit ? 1 : 0;
  }
  if (found.group) {
    // A heading with nothing left under it goes with its things.
    for (const head of box.querySelectorAll(found.group)) {
      head.classList.toggle('out-of-search',
        !head.querySelector(`${found.item}:not(.out-of-search)`));
    }
  }
  found.input.classList.toggle('found-nothing', Boolean(words.length) && !shown);
}

// Every list in the window long enough to be worth searching. The last number
// is how many things it has to hold before the box is worth showing at all.
searchableList('settingFind', 'advanced-body', '.setting', null, 8);
searchableList('sketchFind', 'sketchPalette', '.sketch-pick', '.palette-group', 12);
searchableList('boardFind', 'boardPalette', '.sketch-pick', '.palette-group', 12);
searchableList('zoneFind', 'zoneList', 'li', null, 6);
searchableList('zoneSettingFind', 'zoneEditor', 'label.zone-row', null, 6);
searchableList('builtFind', 'builtList', 'li', null, 6);
searchableList('bdFind', 'bdRooms', '.sketch-pick', '.palette-group', 12);


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
  if (cls === 'bad') {
    const what = { buildingsNote: 'Building failed', compileNote: 'Compile failed',
                   worldedNote: 'WorldEd failed', installNote: 'Install failed',
                   censusNote: 'Recount failed' }[id] || 'Something went wrong';
    fx.problem(what, text, lastErrorId);
    lastErrorId = null;
  }
}

function setupPipeline(data) {
  currentMap = data.mapName;
  const upgrade = document.getElementById('upgradeNote');
  if (upgrade) { upgrade.hidden = true; upgrade.innerHTML = ''; }
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
  // Reset with the rest of them: opening another map used to leave whatever
  // the last compile said sitting under the new one's Compile button.
  note('compileNote', "Turns the map into the game's files. "
                      + 'Takes a few minutes.');
  note('worldedNote', 'Generate the buildings first.');
  note('installNote', 'Copies the compiled map into ~/Zomboid/mods.');
  renderCensus(null);
  document.getElementById('retryCellsBtn').hidden = true;
  // Where this one stands in the world, and whether it has been moved since
  // it was compiled.
  loadPlacement(data.mapName);
  checkLots();
  // Whatever the last compile of this map left behind, said again now: the
  // window has been closed and reopened since, and "done" would be a lie.
  fetch(`/api/compile-status?map=${encodeURIComponent(data.mapName)}`)
    .then(r => r.json())
    .then(p => { if (p.state !== 'running') showFailedCells(p.failed, p.cells); })
    .catch(() => { /* nothing to add if it cannot be asked */ });
}

document.getElementById('buildingsBtn').addEventListener('click', async () => {
  const btn = document.getElementById('buildingsBtn');
  btn.disabled = true;
  note('buildingsNote', 'Generating…');
  showStop(currentMap);
  // The request answers only when the whole step is over, so what it is up to
  // comes from /api/progress meanwhile.
  const watching = currentMap;
  let over = false;
  const watch = setInterval(async () => {
    try {
      const p = await (await fetch(
        `/api/progress?map=${encodeURIComponent(watching)}`)).json();
      if (!over && p.stage === 'buildings' && p.note) {
        const pct = p.fraction != null ? ` (${Math.round(100 * p.fraction)}%)` : '';
        note('buildingsNote', `${p.note}${pct}…`);
      }
    } catch (_) { /* the next tick will do */ }
  }, 1500);
  try {
    const res = await fetch('/api/buildings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      // Sent again so the buildings can be regenerated with different
      // settings without re-downloading the town from OSM.
      body: JSON.stringify({ mapName: currentMap, settings: settingsForRequest() }),
    });
    const data = await res.json();
    if (wasStopped(data, res)) {
      note('buildingsNote', 'Stopped. The terrain and the area are still here — press Build again.');
      fx.toast('ok', 'Stopped', 'Nothing was thrown away.');
      return;
    }
    if (!res.ok) throw apiError(data, res);
    note('buildingsNote', `${data.count} buildings → ${data.pzw}`, 'ok');
    renderCensus(data.population);
    document.getElementById('worldedBtn').disabled = false;
    document.getElementById('compileBtn').disabled = false;
    note('compileNote', 'Ready — runs BMP to TMX and Generate Lots for you.');
  } catch (err) {
    note('buildingsNote', err.message, 'bad');
  } finally {
    over = true;
    clearInterval(watch);
    showStop(null);
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
    if (!res.ok) throw apiError(data, res);
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
      sayIfInstallable();
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
    if (!res.ok) throw apiError(data, res);
    let lifts = '';
    try {
      const status = await (await fetch('/api/setup-status')).json();
      const elevators = (status.optional || []).find(c => c.id === 'elevators');
      lifts = elevators && elevators.ok
        ? ' Enable "Elevators" too, for working lifts in tall buildings.'
        : ' Tall buildings have lifts: subscribe to the Elevators mod on the Steam Workshop to make them work.';
      const selector = (status.optional || []).find(c => c.id === 'spawn_selector');
      if (selector && selector.ok) {
        lifts += ' With "Spawn Selector" enabled you can start at any landmark of the map.';
      }
    } catch (_) { /* the install itself worked; the tip is optional */ }
    note('installNote',
         `Installed ${data.cells} cells to ${data.modRoot}. Enable "${data.title}" `
         + 'in the game\'s Mods menu, then start a NEW save. In a save you are '
         + 'already playing, right-click the ground and pick "Reset loot" for '
         + 'fresh loot in a building.' + lifts, 'ok');
    document.getElementById('publishCard').hidden = false;
    loadMaps();
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

// The picture of the finished layout. The address changes every time so the
// browser does not show the one from before a rebuild or a recount.
function refreshLayoutPreview() {
  const box = document.getElementById('layoutPreview');
  if (!currentMap) { box.hidden = true; return; }
  const layer = document.getElementById('layoutLayer').value;
  const url = `/api/layout-preview?map=${encodeURIComponent(currentMap)}`
    + `&layer=${layer}&t=${Date.now()}`;
  const img = document.getElementById('layoutImg');
  img.onerror = () => { box.hidden = true; };
  img.onload = () => { box.hidden = false; };
  img.src = url;
  document.getElementById('layoutLink').href = url;
}
document.getElementById('layoutLayer').addEventListener('change', refreshLayoutPreview);

function renderCensus(pop) {
  const box = document.getElementById('census');
  if (!pop) {
    box.hidden = true;
    document.getElementById('layoutPreview').hidden = true;
    return;
  }
  refreshLayoutPreview();
  box.hidden = false;
  const tiles = document.getElementById('censusTiles');
  tiles.innerHTML = `
    ${fx.tile(pop.residents, '', 'residents')}
    ${fx.tile(pop.daytime_occupants, '', 'at work or school')}
    ${fx.tile(pop.on_the_street || 0, '', 'out on the street')}
    ${fx.tile(pop.zombie_estimate, '', 'zombies, roughly')}
    ${fx.tile(pop.share_with_zombies * 100, '%', 'of the map has zombies', 0)}`;
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
      body: JSON.stringify({ mapName: currentMap, settings: settingsForRequest() }),
    });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
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

// A batch WorldEd could not do is tried three times and then stepped over, so
// a compile can finish with a hole in it rather than throwing away the hours
// already spent. `onlyFailed` asks for just those cells back.
async function startCompile(onlyFailed) {
  const btn = document.getElementById('compileBtn');
  const retry = document.getElementById('retryCellsBtn');
  btn.disabled = true;
  retry.hidden = true;
  note('compileNote', 'Starting…');
  showStop(currentMap);
  try {
    const res = await fetch('/api/compile', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mapName: currentMap, onlyFailed: !!onlyFailed }),
    });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
    pollCompile();
  } catch (err) {
    note('compileNote', err.message, 'bad');
    showStop(null);
    btn.disabled = false;
  }
}

document.getElementById('compileBtn')
  .addEventListener('click', () => startCompile(false));
document.getElementById('retryCellsBtn')
  .addEventListener('click', () => startCompile(true));

// A compile that stepped over a batch is finished but not whole: installing it
// gives a map with a hole where those cells should be. Say so wherever that is
// noticed - at the end of a compile, and again when the map is opened later,
// because by then nobody remembers which one it was.
function showFailedCells(failed, cells) {
  const retry = document.getElementById('retryCellsBtn');
  failed = failed || [];
  retry.hidden = !failed.length;
  if (!failed.length) return false;
  const where = failed.map(f => `${f.cells[0]},${f.cells[1]}`).join('  ');
  const many = failed.length === 1 ? 'batch' : 'batches';
  note('compileNote',
       `${cells} cells compiled, but ${failed.length} ${many} would not compile `
       + `after 3 tries (at ${where}). The map has a hole in it until those are done.`,
       'warn');
  note('installNote', 'You can install it, but those cells will be missing.');
  return true;
}

// The compile runs on the server's own thread; this just watches it. Blocking
// the request instead froze the whole window for the length of a town.
let compileTimer = null;

// "about 12 min", "about 1 h 5 min": rounded, because a pace measured over a few
// batches is not good to the second.
function formatLeft(seconds) {
  const mins = Math.max(1, Math.round(seconds / 60));
  if (mins < 60) return `${mins} min`;
  return `${Math.floor(mins / 60)} h ${mins % 60} min`;
}

function pollCompile() {
  clearInterval(compileTimer);
  compileTimer = setInterval(async () => {
    try {
      const res = await fetch(
        `/api/compile-status?map=${encodeURIComponent(currentMap)}`);
      const p = await res.json();
      if (p.state === 'stopping') {
        note('compileNote', 'Stopping — waiting for WorldEd to close…');
        return;
      }
      if (p.state === 'running' && p.phase) {
        // The Rust compile: no batches, so it says where it is.
        fx.progress('compile', Math.round(100 * p.fraction));
        note('compileNote', `Compiling — ${p.phase} (${Math.round(100 * p.fraction)}%)…`);
        return;
      }
      if (p.state === 'running') {
        const pct = p.expected ? Math.floor(100 * p.cells / p.expected) : 0;
        // The batch counter is the honest one on a big map: cell files land in
        // bursts and stay flat for minutes inside a batch, which reads as a
        // hang. Batches tick over steadily.
        const batch = p.batches ? ` — batch ${p.batch}/${p.batches}` : '';
        fx.progress('compile', p.batches ? Math.max(pct, 100 * (p.batch - 1) / p.batches) : pct);
        // Time left, once a few batches have set the pace; and the number
        // running at once when WorldEd made the compile ease off.
        const left = p.etaSeconds ? ` — about ${formatLeft(p.etaSeconds)} left` : '';
        const eased = p.workers && p.workersStart && p.workers < p.workersStart
          ? ` — ${p.workers} at a time, down from ${p.workersStart} after WorldEd errors` : '';
        // A map compiled before only redoes what has changed since.
        const inc = p.incremental && p.incremental.batches < p.incremental.of
          ? ` (only the ${p.incremental.changed} changed cell${p.incremental.changed === 1 ? '' : 's'}`
            + ` and what touches them: ${p.incremental.batches} of ${p.incremental.of} batches)` : '';
        note('compileNote',
             `Compiling${batch}${inc}${left} — ${p.tmx} cells converted, `
             + `${p.cells}/${p.expected || '?'} compiled (${pct}%)${eased}…`);
        return;
      }
      clearInterval(compileTimer);
      showStop(null);
      document.getElementById('compileBtn').disabled = false;
      if (p.state === 'stopped') {
        fx.progress('compile', 0);
        note('compileNote', 'Stopped. The cells already compiled are kept — '
                            + 'press Compile to carry on from there.');
        fx.toast('ok', 'Stopped', 'Compiling picks up where it left off.');
        return;
      }
      if (p.state === 'error') {
        lastErrorId = p.errorId || null;
        note('compileNote', p.error || 'Compile failed.', 'bad');
        return;
      }
      if (p.state === 'done') {
        fx.progress('compile', 100);
        document.getElementById('installBtn').disabled = false;
        if (showFailedCells(p.failed, p.cells)) return;
        note('compileNote', `${p.cells} cells compiled.`, 'ok');
        note('installNote', 'Ready to install.');
      }
    } catch (_) { /* keep watching */ }
  }, 2000);
}

// ---- links straight to a place ----------------------------------------------------
// ?preset=<JSON> restores an exact area and settings, while ?q= and &outline=1
// still search for a place. A pasted link works when the app's local port differs.
(async function openFromLink() {
  const params = new URLSearchParams(location.search);
  if (params.has('preset')) {
    try { await importPortablePreset(presetFromLink(location.href)); }
    catch (err) {
      document.getElementById('presetsPanel').open = true;
      presetNote(err.message, 'bad');
    }
    return;
  }
  const q = params.get('q');
  if (!q) return;
  searchInput.value = q;
  const wantOutline = params.get('outline') === '1';
  const watch = new MutationObserver(() => {
    const outline = wantOutline && searchResults.querySelector('button[data-outline]');
    const first = searchResults.querySelector('li[data-i]');
    if (!outline && !first) return;
    watch.disconnect();
    (outline || first).click();
  });
  watch.observe(searchResults, { childList: true });
  runSearch(q);
})();

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
  palette: document.getElementById('sketchPalette'),
  active: () => document.getElementById('sketch').open
                && document.getElementById('board').hidden,
  listen: false,
  onStart: () => { zoneEd.stop(); disarmAreaToolbar(); },
  onChange: () => { showSketchCount(); refreshSketchTools(); },
});
refreshSketchTools = KnoxDraw.toolbar(document.getElementById('sketchTools'), sketchEd);

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
  const colour = SKETCH_COLOURS[cat] || '#a5e266';
  return { color: colour, weight: 3, fillColor: colour, fillOpacity: 0.3 };
}

function sketchLabel(kind) {
  return (sketchPalette.find(e => e.id === kind) || {}).label || kind;
}

// Under headings, in the server's order. Thirty-four tools in one run is a
// wall to read, and nobody hunting for "Hedge" wants to scan past "Motorway".
function paletteMarkup() {
  const groups = [];
  for (const entry of sketchPalette) {
    const name = entry.group || 'Other';
    const last = groups[groups.length - 1];
    if (!last || last.name !== name) groups.push({ name, items: [entry] });
    else last.items.push(entry);
  }
  return groups.map(g => `<div class="palette-group">
      <span class="palette-head">${escapeHtml(g.name)}</span>
      ${g.items.map(e => `<button type="button" class="sketch-pick"
        data-kind="${e.id}" data-geometry="${e.geometry}"
        title="${escapeHtml(Object.entries(e.tags)
          .map(([k, v]) => k + '=' + v).join(', '))}">
        <span class="swatch" style="background:${SKETCH_COLOURS[e.category] || '#a5e266'}"></span>
        ${escapeHtml(e.label)}</button>`).join('')}
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
  box.innerHTML = paletteMarkup();
  runListSearch('sketchPalette');
}

function noteSketch(text) {
  const box = document.getElementById('sketchNote');
  if (box) box.textContent = text || '';
}

function sketchCount() {
  return sketchEd.count;
}

function showSketchCount() {
  const badge = document.getElementById('sketchCount');
  const n = sketchCount();
  if (badge) badge.textContent = n ? `(${n})` : '';
  const only = document.getElementById('drawnOnly');
  if (only && !n) only.checked = false;
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

document.getElementById('drawnOnly').addEventListener('change', ev => {
  noteSketch(ev.target.checked
    ? 'Nothing will be downloaded: the map is only what you have drawn.'
    : 'What you draw goes in on top of what is on OpenStreetMap.');
});

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
  const first = Object.entries(tags || {})[0];
  return first ? `${first[0]}=${first[1]}` : 'something';
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
    </select>`;
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
let boardOpened = null;         // the map whose sheet this is, once it has one
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
    pane: 'tilePane', color: '#a5e266', weight: 2, fill: true,
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
  boardOpened = mapName || null;
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
    boardOpened = name;
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

function drawZoneList() {
  const box = document.getElementById('zoneList');
  box.innerHTML = zoneList.map((z, i) => `<li data-i="${i}" class="${i === zonePicked ? 'on' : ''}">
      <span>${escapeHtml(z.name || 'Zone ' + (i + 1))}</span>
      <span class="zone-what">${escapeHtml(zoneSummary(z))}</span>
      <button type="button" data-drop="${i}">Remove</button></li>`).join('');
  runListSearch('zoneList');
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

// A zone setting that is only ever 0 or 1: it gets on, off, or nothing at
// all, rather than a box to type 1 into.
function zoneSwitchable(setting) {
  return setting.int && setting.min === 0 && setting.max === 1;
}

function drawZoneEditor() {
  const box = document.getElementById('zoneEditor');
  const zone = zoneList[zonePicked];
  if (!zone || !zoneMeta) {
    box.hidden = true;
    box.innerHTML = '';
    runListSearch('zoneEditor');     // and its search box goes with it
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
    <label><span>Walls</span><select id="zoneStyle">${styles.join('')}</select></label>
    ${presetBox}
    <p class="hint">Leave a box empty and the map's own setting is used there.</p>
    ${zoneMeta.settings.map(s => `<label class="zone-row"
      data-find="${escapeHtml(s.id)}"><span>${escapeHtml(SETTING_LABELS[s.id]
        ? SETTING_LABELS[s.id][0] : s.id)}</span>
      ${zoneSwitchable(s)
        // On or off, and a third state the number box could not say: leave it
        // to the map. A zone sets what is different about it, not everything.
        ? `<select data-zone-key="${s.id}"
             class="${zone.settings[s.id] !== undefined ? 'zone-set' : ''}">
           <option value="">As the map is</option>
           <option value="1"${zone.settings[s.id] === 1 ? ' selected' : ''}>On</option>
           <option value="0"${zone.settings[s.id] === 0 ? ' selected' : ''}>Off</option>
           </select>`
        : `<input type="number" data-zone-key="${s.id}" min="${s.min}" max="${s.max}"
             step="${s.int ? 1 : 0.05}" placeholder="${s.default}"
             class="${zone.settings[s.id] !== undefined ? 'zone-set' : ''}"
             value="${zone.settings[s.id] !== undefined ? zone.settings[s.id] : ''}">`}
      </label>`).join('')}`;

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
  runListSearch('zoneEditor');
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
  const row = ev.target.closest('li[data-i]');
  if (row) zonePick(parseInt(row.dataset.i, 10));
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

// Every other map's cells as tile rectangles, one per run of cells in a row.
function placeOtherRects() {
  if (!placeWorld) return [];
  const k = placeWorld.compiledCell || 256;
  const out = [];
  for (const map of placeWorld.maps || []) {
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
  for (const map of placeWorld.maps || []) {
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
  for (const map of placeWorld.maps || []) {
    const c = placeWorld.compiledCell || 256;
    ctx.fillStyle = map.kind === 'vanilla' ? '#d6dcc8' : '#92a8c4';
    ctx.fillText(map.name, map.x * c * k + 3, (map.y * c + map.h * c) * k + 14);
  }

  if (mineNow) {
    const clash = placeClashes(placePicked || placeWorld.map);
    const edge = clash.length ? '#dc5046' : '#a5e266';
    if (placePreview && placePreview.complete && placePreview.naturalWidth) {
      ctx.globalAlpha = 0.95;
      ctx.drawImage(placePreview, mineNow.x * k, mineNow.y * k,
                    mineNow.w * k, mineNow.h * k);
      ctx.globalAlpha = 1;
    } else {
      ctx.fillStyle = clash.length ? 'rgba(220,80,70,0.35)' : 'rgba(165,226,102,0.35)';
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
  // The game's own maps, each fetched once and kept for the next draw.
  for (const map of placeWorld.maps || []) {
    if (!map.picture || placePictures[map.name]) continue;
    const shot = new Image();
    shot.onload = drawWorld;
    shot.onerror = () => { delete placePictures[map.name]; };
    shot.src = `/api/world-picture/${encodeURIComponent(map.name)}`;
    placePictures[map.name] = shot;
  }
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
