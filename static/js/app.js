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

// It opens on the whole world rather than one town: a place is found from
// there by the search, or zoomed into and drawn.
const map = L.map('map', { zoomControl: true, worldCopyJump: true }).setView([20, 0], 2);
// Tiles through KnoxMap's own server, which follows the OSM tile policy -
// see the /tiles route in app.py.
L.tileLayer('/tiles/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '© OpenStreetMap contributors',
}).addTo(map);

const drawnItems = new L.FeatureGroup().addTo(map);
const SEL_STYLE = { color: '#3d8bfd', weight: 2, fillOpacity: 0.1, className: 'sel-rect' };
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
// The handle that turns the area shows only while it is being reshaped
// (Reshape, in the Tools panel's Area tab); the rest of the time the area is
// just a shape on the map.
let areaReshaping = false;
map.on('draw:editstart', () => { areaReshaping = true; updateRotateHandle(); });
map.on('draw:editstop', () => { areaReshaping = false; updateRotateHandle(); });
// A corner moved: the handle turns the shape as it now is, not as it was
// before, or the next turn would put the corner back.
map.on('draw:editvertex draw:editresize draw:editmove', () => {
  if (!currentRect) return;
  currentRect._pivot = calculatePivot(currentRect);
  currentRect._origPoints = getShapeLatLngs(currentRect);
  currentRect._rotationAngle = 0;
  updateRotateHandle();
});
// Turning the area replaces its points - a box or a circle becomes a new
// polygon - and Leaflet.draw's corner markers stay on the old ones: a corner
// dragged after that moves its marker and not the shape. So a turn made
// while reshaping starts the reshape again, on the turned shape.
function restartReshape() {
  if (!areaReshaping) return;
  const edit = drawControl._toolbars.edit && drawControl._toolbars.edit._modes.edit;
  if (!edit || !edit.handler.enabled()) return;
  edit.handler.disable();
  // The polygon editor keeps the point list it was made with; give it the
  // turned one (the same call Leaflet.draw makes when an edit is undone).
  if (currentRect && currentRect.editing && currentRect.editing._updateLatLngs) {
    currentRect.editing._updateLatLngs({ layer: currentRect });
  }
  edit.handler.enable();
}
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
  if (!areaReshaping || !currentRect || !drawnItems.hasLayer(currentRect)) {
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
      color: '#3d8bfd',
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
  restartReshape();
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
      restartReshape();
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
    trail = L.polyline(points, { color: '#3d8bfd', weight: 2, dashArray: '4 4' }).addTo(map);
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

// The box at the current scale, rounded out to whole 300-tile cells.
function boxSize(s, w, n, e) {
  const mpt = readScale();
  const widthM  = haversineKm(s, w, s, e) * 1000;
  const heightM = haversineKm(s, w, n, w) * 1000;
  return {
    area: bboxAreaKm2(s, w, n, e), widthM, heightM,
    tilesX: Math.ceil(widthM / mpt / 300) * 300,
    tilesY: Math.ceil(heightM / mpt / 300) * 300,
  };
}

// How long this area will take, at the pace of the maps already made here.
// A step with no history behind it says nothing rather than guessing: a
// forecast wrong by an hour is worse than none, because somebody plans an
// evening around it.
let forecastToken = 0;
let forecastTimer = null;
function loadForecast(s, w, n, e, mpt) {
  // The selection is dragged, not clicked: wait for it to settle rather than
  // asking on every pixel.
  clearTimeout(forecastTimer);
  forecastTimer = setTimeout(() => requestForecast(s, w, n, e, mpt), 400);
}
async function requestForecast(s, w, n, e, mpt) {
  const box = document.getElementById('forecastNote');
  if (!box) return;
  const mine = ++forecastToken;
  let data;
  try {
    const res = await fetch('/api/forecast', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ south: s, west: w, north: n, east: e,
                             metersPerTile: mpt }),
    });
    data = await res.json();
    if (!res.ok) throw apiError(data, res);
  } catch (_) {
    box.hidden = true;          // no answer is not a reason to say anything
    return;
  }
  if (mine !== forecastToken) return;   // the selection moved while this was out
  const label = { generate: 'Generate', build: 'Build', compile: 'Compile' };
  const said = [];
  for (const step of ['generate', 'build', 'compile']) {
    const seconds = data.steps && data.steps[step];
    if (seconds) said.push(`${label[step]} about ${formatLeft(seconds)}`);
  }
  if (!said.length) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.textContent = `At the pace of the maps already made here: ${said.join(' · ')}.`;
}

function updateBboxFields() {
  if (!currentRect) return clearBboxFields();
  const { s, w, n, e } = rectBounds(currentRect);
  document.getElementById('south').value = s.toFixed(6);
  document.getElementById('west').value  = w.toFixed(6);
  document.getElementById('north').value = n.toFixed(6);
  document.getElementById('east').value  = e.toFixed(6);

  const mpt = readScale();
  const { area, widthM, heightM, tilesX, tilesY } = boxSize(s, w, n, e);
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
  const takes = durationText(generateSeconds(area, tilesX * tilesY));

  const shapeKm2 = selectionAreaKm2();
  const shapeVal = shapeKm2 !== null ? shapeKm2 : area;

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
      <div class="meter-top"><span>~${Math.round(widthM)} × ${Math.round(heightM)} m · ${bitmap} of bitmap · ~${buildGB} GB to add buildings · ${takes} to generate</span>
        <span>${fill < 1 ? '<1' : Math.round(fill)}% of limit</span></div>
      <div class="bar"><div class="bar-fill" style="width:${fill}%"></div></div>
    </div>
    <div id="forecastNote" class="stat-note" hidden></div>
    ${selectionShape() !== null && shapeKm2 !== null ? `<div class="stat-note shape">
      Only the drawn shape is built: <b>${shapeKm2.toFixed(2)} km²</b>
      (bounding box: ${area.toFixed(1)} km², ${cellsX}×${cellsY} cells). Outside it the land turns back to countryside, with the main roads and rivers running on.
    </div>` : ''}
    ${heavy.length ? `<div class="stat-note warn">${heavy.join(' ')}
      You can still build it — this is a heads-up, not a wall.
      ${fitScale ? `<button type="button" class="use-scale" data-scale="${fitScale.mpt}">Use ${fitScale.mpt} m/tile
        (${fitScale.side} tiles a side, ${fitScale.bitmap})</button>` : ''}</div>` : ''}
    ${slow ? `<div class="stat-note warn">A big map — Generate map will take ${takes},
      mostly OpenStreetMap downloads.</div>` : ''}
  `;
  fx.countUp(stats);
  loadForecast(s, w, n, e, mpt);
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
  const count = document.getElementById('landmarkCount');
  if (count) count.textContent = '';
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

// How long Generate map takes, as a range in seconds. Fitted to the timings in
// logs/knoxmap.log (Oct 2026): the OpenStreetMap download ran 3 to 45 s a km²
// depending on the server, and drawing ran 3 to 8 s per million tiles. A map
// fetched before comes from the cache and lands near the low end.
// ponytail: fixed rates from one machine, refit if the log drifts from them.
function generateSeconds(areaKm2, tiles) {
  const mTiles = tiles / 1e6;
  return [20 + areaKm2 * 3 + mTiles * 3, 20 + areaKm2 * 45 + mTiles * 8];
}

function durationText([lo, hi]) {
  const say = s => s < 90 ? `${Math.max(1, Math.round(s / 60))} min`
    : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;
  return say(lo) === say(hi) ? `about ${say(hi)}` : `${say(lo)} to ${say(hi)}`;
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

let setupChecking = false;
const SETUP_DISMISSED = 'knoxmap.setup.dismissed';
document.getElementById('setupDismiss').addEventListener('click', () => {
  const card = document.getElementById('setupCard');
  try { localStorage.setItem(SETUP_DISMISSED, card.dataset.problems || ''); } catch (_) { /* no storage */ }
  card.hidden = true;
});

async function checkSetup() {
  if (setupChecking) return;
  setupChecking = true;
  try {
    const res = await fetch('/api/setup-status');
    const data = await res.json();
    const card = document.getElementById('setupCard');
    // Named after the script this PC actually has: Setup.bat on Windows,
    // ./setup.sh on Linux and macOS.
    const script = document.getElementById('setupScript');
    if (script && data.setupCommand) script.textContent = data.setupCommand;
    if (data.ready) { card.hidden = true; return; }
    // Only what is wrong, each a heading whose fix folds open under it. A
    // dismissed card stays away until the list of what is wrong changes.
    const missing = data.checks.filter(c => !c.ok);
    const key = missing.map(c => c.label).join('|');
    let dismissed = '';
    try { dismissed = localStorage.getItem(SETUP_DISMISSED) || ''; } catch (_) { /* no storage */ }
    if (!missing.length || dismissed === key) { card.hidden = true; return; }
    card.dataset.problems = key;
    const list = document.getElementById('setupList');
    // Checked again on every return to the window: what was open stays open.
    const open = new Set([...list.querySelectorAll('details[open]')].map(d => d.dataset.check));
    list.innerHTML = missing.map(c =>
      `<li class="missing"><details data-check="${escapeHtml(c.label)}"${open.has(c.label) ? ' open' : ''}>
        <summary><span>✗</span> <b>${escapeHtml(c.label)}</b></summary>
        <p>${escapeHtml(c.fix)}</p></details></li>`).join('');
    card.hidden = false;
  } catch (_) { /* the page still works without the check */ }
  finally { setupChecking = false; }
}
checkSetup();
// Setup.bat installs into the map tools' folder from another window, and this
// card is worked out once when the page opens. A row it got wrong went on
// saying "Run Setup.bat again" long after Setup had done it, which reads as
// Setup having failed. Coming back to the window asks again, as does a
// finished health check.
window.addEventListener('focus', checkSetup);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) checkSetup();
});

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
    // The same checks the card above is built from, so it is filled in again
    // from this answer: Setup run while the window was open used to leave the
    // card saying "Run Setup.bat again" for the rest of the session.
    checkSetup();
  }
});

// ---- map data server & osm_source ----------------------------------------------

const OSM_SOURCE_DESCS = {
  overpass: {
    title: '⚡ Overpass API — Online queries',
    description: 'Downloads the selected area from the servers below. Busy servers get a limited number of retries; downloaded parts are kept. If the servers are unreachable, choose Auto or Geofabrik.',
  },
  auto: {
    title: '⚙ Auto mode',
    description: 'Reads regional Geofabrik data when pyosmium is installed. The file is downloaded once and cached. Reading reports its current stage and object count. Falls back to Overpass if the extract is unavailable.',
  },
  extract: {
    title: '📦 Geofabrik — Local data',
    description: 'Downloads and caches a Geofabrik region, then selects objects for your area. Works without Overpass after the download. The first read of a large region takes time; the current stage is shown in the window.',
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

  const info = OSM_SOURCE_DESCS[source];
  const descEl = document.getElementById('osmSourceDesc');
  if (descEl) {
    descEl.innerHTML = `<b>${escapeHtml(info.title)}</b><br>${escapeHtml(info.description)}`;
  }

  if (saveToServer) {
    fetch('/api/overpass', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ osm_source: source }),
    }).then(async r => {
      const data = await r.json();
      if (!r.ok) throw apiError(data, r);
    }).then(() => {
      const name = { overpass: 'Overpass API', auto: 'Auto', extract: 'Geofabrik' }[source];
      note('overpassNote', `Map data source set to ${name}`, 'ok');
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
    document.getElementById('pbfFile').value = d.pbf_file || '';
    setOsmSourceUI(d.osm_source || 'overpass', false);
  } catch (_) {
    setOsmSourceUI('overpass', false);
  }
})();


// ---- the extract a map developer picked -----------------------------------------

async function savePbfFile(path) {
  const res = await fetch('/api/overpass', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pbf_file: path }),
  });
  const data = await res.json();
  if (!res.ok) throw apiError(data, res);
  return data;
}

const pbfBrowseBtn = document.getElementById('pbfBrowse');
if (pbfBrowseBtn) {
  pbfBrowseBtn.addEventListener('click', async () => {
    pbfBrowseBtn.disabled = true;
    try {
      const res = await fetch('/api/tools/pbf/browse');
      const data = await res.json();
      if (!res.ok) throw apiError(data, res);
      if (data.path) {
        document.getElementById('pbfFile').value = data.path;
        note('pbfNote', 'Picked it - "Use this file" saves it for the next map.', '');
      }
    } catch (err) {
      note('pbfNote', err.message, 'bad');
    } finally {
      pbfBrowseBtn.disabled = false;
    }
  });

  document.getElementById('pbfUse').addEventListener('click', async () => {
    const path = document.getElementById('pbfFile').value.trim();
    if (!path) {
      note('pbfNote', 'Give a path first, or use Browse.', 'bad');
      return;
    }
    try {
      await savePbfFile(path);
      note('pbfNote', 'Every map now reads that file.', 'ok');
    } catch (err) {
      note('pbfNote', err.message, 'bad');
    }
  });

  document.getElementById('pbfClear').addEventListener('click', async () => {
    try {
      await savePbfFile('');
      document.getElementById('pbfFile').value = '';
      note('pbfNote', 'KnoxMap goes back to choosing an extract by area.', 'ok');
    } catch (err) {
      note('pbfNote', err.message, 'bad');
    }
  });

  document.getElementById('pbfCheck').addEventListener('click', async () => {
    const btn = document.getElementById('pbfCheck');
    const out = document.getElementById('pbfReport');
    const path = document.getElementById('pbfFile').value.trim();
    btn.disabled = true;
    note('pbfCheckNote', 'Reading the file... a large region takes a while.', '');
    out.hidden = true;
    try {
      const res = await fetch('/api/tools/pbf/check', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      const data = await res.json();
      if (!res.ok) throw apiError(data, res);
      out.textContent = data.report || '';
      out.hidden = false;
      out.classList.toggle('is-bad', !data.ok);
      note('pbfCheckNote', data.ok ? 'Usable.' : 'Not usable - see the report.',
           data.ok ? 'ok' : 'bad');
    } catch (err) {
      note('pbfCheckNote', err.message, 'bad');
    } finally {
      btn.disabled = false;
    }
  });
}

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
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'btn-danger';
    del.textContent = 'Delete';
    del.title = 'Delete this map and all its files';
    del.addEventListener('click', () => deleteMap(m.mapName));
    li.append(del);
    list.append(li);
  }
}

// Follow an install while its request is open: `tick(done, total)` with the
// files copied so far. A city is thousands of cell files and gigabytes, and the
// window used to show nothing but a greyed-out button until it was over.
// Returns the function that stops watching.
function watchInstall(mapName, tick) {
  let over = false;
  const timer = setInterval(async () => {
    try {
      const p = await (await fetch(`/api/progress?map=${encodeURIComponent(mapName)}`)).json();
      // An answer still on its way when the install ended must not write
      // "copying" over what the end said.
      if (!over && p.stage === 'install' && p.total) tick(p.done || 0, p.total);
    } catch (_) { /* the install call is the source of truth */ }
  }, 700);
  return () => { over = true; clearInterval(timer); };
}

function installSaid(done, total) {
  return `${done.toLocaleString()} of ${total.toLocaleString()} files `
    + `(${Math.floor(100 * done / total)}%)`;
}

async function updateMap(mapName, btn) {
  // The same install as the Install button, into the same mod folder under the
  // same name; the copy already there is replaced.
  btn.disabled = true;
  btn.textContent = 'Updating…';
  // Under the map's own row, so it is clear which map is being copied.
  const shown = document.createElement('li');
  shown.className = 'map-progress';
  shown.innerHTML = '<div class="bar is-indeterminate"><div class="bar-fill"></div></div>'
    + '<span class="size"></span>';
  const bar = shown.querySelector('.bar');
  const said = shown.querySelector('span');
  said.textContent = 'Starting…';
  btn.closest('li').after(shown);
  fx.toast('ok', 'Updating in the game', `Copying ${mapName} into your mods folder…`);
  const stop = watchInstall(mapName, (done, total) => {
    bar.classList.remove('is-indeterminate');
    bar.firstChild.style.width = `${Math.floor(100 * done / total)}%`;
    said.textContent = `Copying ${installSaid(done, total)}`;
  });
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
    btn.textContent = 'Update';
  } finally {
    stop();
    shown.remove();
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

async function deleteMap(mapName) {
  if (!mapName) return;
  const prompt = `Delete ${mapName} and all its files? This cannot be undone.`;
  if (!window.confirm(prompt)) return;
  try {
    const res = await fetch(`/api/maps/${encodeURIComponent(mapName)}`, {
      method: 'DELETE',
    });
    const data = await res.json();
    if (!res.ok) throw apiError(data, res);
    fx.toast('ok', 'Map deleted', mapName, 6000);
    if (typeof closeTab === 'function') {
      closeTab(mapName);
    } else {
      const results = document.getElementById('results');
      if (results) results.hidden = true;
    }
    loadMaps();
    if (typeof refreshMyMaps === 'function') refreshMyMaps();
  } catch (err) {
    fx.toast('bad', 'Could not delete that map', err.message, 8000);
  }
}
window.deleteMap = deleteMap;

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
  fx.toast('ok', 'Upgrading', `${data.mapName}: ${data.needsLabels.join(' → ')}`);
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
        let over = false;
        const watch = setInterval(async () => {
          try {
            const p = await (await fetch(
              `/api/progress?map=${encodeURIComponent(data.mapName)}`)).json();
            if (!over && p.stage === 'buildings' && p.note) {
              const pct = p.fraction != null ? ` (${Math.round(100 * p.fraction)}%)` : '';
              say(`${p.note}${pct}…`);
            }
          } catch (_) { /* the next tick will do */ }
        }, 1500);
        try {
          await post('/api/buildings', { mapName: data.mapName, settings: data.settings });
        } finally {
          over = true;
          clearInterval(watch);
        }
      } else if (step === 'compile') {
        say('Compiling…');
        await post('/api/compile', { mapName: data.mapName });
        for (;;) {
          await new Promise(r => setTimeout(r, 2000));
          const st = await (await fetch(
            `/api/compile-status?map=${encodeURIComponent(data.mapName)}`)).json();
          if (st.state === 'running' || st.state === 'stopping') {
            // The knoxlots compile names its step; the cells already in lots/
            // are the old ones, and read as done on a map compiled before.
            say(st.phase ? `Compiling — ${st.phase} (${Math.round(100 * st.fraction)}%)…`
              : `Compiling… ${st.cells || 0} of ${st.expected || '?'} cells`);
            continue;
          }
          if (st.error) throw new Error(st.error);
          // Stopped is not finished: going on would install the old lots.
          if (st.state === 'stopped') throw new Error('the compile was stopped.');
          break;
        }
      } else if (step === 'install') {
        say('Installing…');
        const stopWatching = watchInstall(data.mapName,
          (done, total) => say(`Installing — ${installSaid(done, total)}…`));
        try {
          await post('/api/install', { mapName: data.mapName, title: data.mapName,
                                       modId: data.mapName });
        } finally {
          stopWatching();
        }
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
  // Only what I draw with nothing drawn downloads nothing and builds nothing:
  // say so, rather than switching it off behind the user's back.
  if (document.getElementById('drawnOnly').checked
      && typeof sketchCount === 'function' && !sketchCount()
      && !window.confirm('Only what I draw is on, but nothing is drawn under Features: '
        + 'the map will be bare ground.\n\nGenerate it anyway?')) return;

  // A big map ties the app up for a long while, so say how big and how long
  // before starting rather than after.
  {
    const { s, w, n, e } = rectBounds(currentRect);
    const { area, tilesX, tilesY } = boxSize(s, w, n, e);
    const side = Math.max(tilesX, tilesY);
    if (area > SLOW_ABOVE_KM2 || side > BIG_TILES_PER_SIDE) {
      const takes = durationText(generateSeconds(area, tilesX * tilesY));
      if (!window.confirm(`This is a big map: ${Math.round(area)} km², `
          + `${tilesX / 300} × ${tilesY / 300} cells (${tilesX} × ${tilesY} tiles).\n\n`
          + `Generate map will take ${takes}. Adding buildings and compiling `
          + 'take longer again.\n\nGenerate it?')) return;
    }
  }

  // Name it here rather than letting the server invent one, so progress can be
  // polled under a key the page already knows.
  const nameField = document.getElementById('mapName');
  const chosen = (nameField.value.trim() || `knoxmap_${Date.now()}`)
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
    showGapFill(data, status);
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

// ---- a town that came out empty ---------------------------------------------
//
// OpenStreetMap is drawn by people, so in plenty of the world a town is the
// high street and not much else, and the two fillers that stand in for the rest
// are optional. The server says why the fill added nothing (web/generation.py);
// this says it beside the finished map, and when the reason is a package that is
// not installed, offers to install it rather than telling the player to run pip.
function showGapFill(data, status) {
  const why = String(data.gapFillWhy || '').trim();
  if (!why) return;
  status.appendChild(document.createTextNode(' ' + why));
  if (!/duckdb/i.test(why)) return;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn btn-small';
  btn.textContent = 'Install DuckDB';
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    btn.textContent = 'Installing…';
    try {
      const res = await fetch('/api/install-optional', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'overture' }),
      });
      const done = await res.json();
      if (!res.ok) throw apiError(done, res);
      btn.replaceWith(document.createTextNode(
        'DuckDB is installed. Generate this area again to fill the gaps.'));
    } catch (err) {
      btn.disabled = false;
      btn.textContent = 'Try again';
      status.appendChild(document.createTextNode(` Could not install it: ${err.message}`));
    }
  });
  status.appendChild(document.createTextNode(' '));
  status.appendChild(btn);
}

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

// " - about 12 min left", once a stage has set a pace. Compile has said
// this for a while; this is the same reading for the steps before it.
function leftText(p) {
  return p && p.etaSeconds ? ` \u2014 about ${formatLeft(p.etaSeconds)} left` : '';
}

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
            ? `Querying OpenStreetMap — area ${(p.done || 0) + 1} of ${total}`
            : 'Querying OpenStreetMap') + leftText(p) + '…';
      } else if (p.stage === 'overture') {
        // A few minutes, nearly all of it Overture's own files being sifted
        // for the handful that cover this box. Saying so beats a dead bar.
        status.textContent = 'Looking up the buildings OpenStreetMap has not got '
                           + '— this takes a few minutes the first time…';
      } else if (p.stage === 'roads') {
        status.textContent = `Routing the roads — ${(p.done || 0).toLocaleString()} of `
                           + `${(p.total || 0).toLocaleString()} stretches…`
                           + (p.slowRoads ? ' Slowly: the fast road router (knoxroute) is '
                              + 'missing. Stop, and pick another Road layout, or update KnoxMap.' : '') + leftText(p);
      } else if (p.stage === 'render') {
        status.textContent = `Rendering ${p.features.toLocaleString()} features `
                           + 'into bitmaps…' + leftText(p);
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

// Done with this map: put the page back as it was before Generate, ready for
// another area. The map itself stays on disk; nothing is stopped or deleted.
document.getElementById('resultsClose').addEventListener('click', () => {
  document.getElementById('results').hidden = true;
  document.getElementById('map').scrollIntoView({ block: 'start' });
});

function getActiveMapName() {
  const badge = document.querySelector('.map-badge');
  const name = badge ? badge.textContent.trim() : '';
  if (name && name !== '—') return name;
  return typeof currentMap !== 'undefined' && currentMap ? currentMap : '';
}

document.getElementById('resultsDelete')?.addEventListener('click', () => {
  const name = getActiveMapName();
  if (name) deleteMap(name);
});

document.getElementById('deleteMapSideBtn')?.addEventListener('click', () => {
  const name = getActiveMapName();
  if (name) deleteMap(name);
});

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
      ${data.fromStreetInfill ? fx.tile(data.fromStreetInfill, '', 'street infill') : ''}
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

// A found place on the map: there, with a box round it as the extent (and no
// pin: the box says where it is) - or
// its real boundary, when it has one and that is asked for. The search box
// at the top and Home's Find a place both end here.
function goToPlace(r) {
  const bounds = boundsForResult(r);
  map.fitBounds(bounds, { padding: [30, 30] });
  setRectFromBounds(bounds);
  hideSearchResults();
  searchInput.value = r.name;
}
function goToOutline(r) {
  const bounds = setOutline(r.outline);
  map.fitBounds(bounds, { padding: [30, 30] });
  hideSearchResults();
  searchInput.value = r.name;
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
      goToOutline(results[parseInt(btn.dataset.outline, 10)]);
    });
  });

  searchResults.querySelectorAll('li[data-i]').forEach(li => {
    li.addEventListener('click', () => goToPlace(results[parseInt(li.dataset.i, 10)]));
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
  // Its widget on the map unfolds for a new look (it may have been folded
  // away, and the menu's List named places presses this button too).
  btn.closest('.ws-legend')?.classList.remove('shut');
  const count = document.getElementById('landmarkCount');
  if (count) count.textContent = '';

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
  const count = document.getElementById('landmarkCount');
  if (count) count.textContent = items.length || '';
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
  // A subhead with nothing left under it before the next subhead goes too.
  for (const head of box.querySelectorAll('.setting-subhead')) {
    let any = false;
    for (let n = head.nextElementSibling; n && !n.matches('.setting-subhead'); n = n.nextElementSibling) {
      if (n.matches(`${found.item}:not(.out-of-search)`)
          || n.querySelector(`${found.item}:not(.out-of-search)`)) { any = true; break; }
    }
    head.classList.toggle('out-of-search', !any);
  }
  // A match inside a closed Advanced panel opens it, or it would be found
  // and not seen. The panel is marked so its toggle handler does not save
  // the search's opening as the user's own choice.
  if (found.query) {
    for (const panel of box.querySelectorAll('details.setting-group-advanced, details.palette-fold')) {
      if (!panel.open && panel.querySelector(`${found.item}:not(.out-of-search)`)) {
        panel.dataset.searchOpened = '1';
        panel.open = true;
      }
    }
  } else {
    // A folded palette section the search opened folds again when it ends.
    for (const panel of box.querySelectorAll('details.palette-fold[data-search-opened]')) {
      delete panel.dataset.searchOpened;
      panel.open = false;
    }
  }
  found.input.classList.toggle('found-nothing', Boolean(words.length) && !shown);
  // A list drawn in parts (the settings' tabs) shows its matches its own way.
  box.dispatchEvent(new CustomEvent('listsearch', { detail: { query: found.query } }));
}

// Every list in the window long enough to be worth searching. The last number
// is how many things it has to hold before the box is worth showing at all.
searchableList('settingFind', 'advanced-body', '.setting', '.setting-group', 8);
searchableList('sketchFind', 'sketchPalette', '.sketch-pick', '.palette-group', 12);
searchableList('boardFind', 'boardPalette', '.sketch-pick', '.palette-group', 12);
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
  // A map opened with its buildings already built can be compiled as it
  // stands; the button used to wake only after a build in this same window.
  if (data.buildingsReady) {
    const when = (data.builtAt || '').replace('T', ' ').slice(0, 16);
    showBuilt(`Built${when ? ' ' + when : ''} → ${data.mapName}.pzw. Build again to lay them out afresh.`);
    loadLeftOut(data.mapName);
  } else {
    showLeftOut(null);
  }
  // Whatever the last compile of this map left behind, said again now: the
  // window has been closed and reopened since, and "done" would be a lie.
  // A compile still running is followed again rather than offered twice.
  fetch(`/api/compile-status?map=${encodeURIComponent(data.mapName)}`)
    .then(r => r.json())
    .then(p => {
      if (p.state === 'running' || p.state === 'stopping') {
        document.getElementById('compileBtn').disabled = true;
        showStop(data.mapName);
        pollCompile();
        return;
      }
      showFailedCells(p.failed, p.cells);
    })
    .catch(() => { /* nothing to add if it cannot be asked */ });
}

// What the build left out, under the step that left it out, with the way to
// ask about one building right there. The counts and their wording come from
// the build (knoxbuild/why.py) so a new reason needs nothing here.
function showLeftOut(report) {
  const box = document.getElementById('leftOut');
  if (!box) return;
  if (!report || !report.total) { box.hidden = true; box.innerHTML = ''; return; }
  const lines = (report.lines || []).map(l =>
    `<li>${l.n} ${escapeHtml(l.text)}</li>`).join('');
  box.hidden = false;
  box.innerHTML = `<div class="left-out-head">${report.total} footprint${
    report.total === 1 ? '' : 's'} did not become a building</div>
    <ul>${lines}</ul>
    <button type="button" id="whyOne" class="btn btn-small">Why is my
      building missing?</button>`;
  document.getElementById('whyOne').addEventListener('click', () => {
    // Pick the Change tool, read the map's own features, and say what to
    // click: the alternative was a csv and a command line. The tool button
    // is what moves the panel to where it can be seen (shell.js); without
    // the shell the panel is where it stands.
    const tool = document.querySelector('[data-tool="change"]');
    if (tool) tool.click();
    const panel = document.getElementById('editMap');
    panel.open = true;
    if (!tool) panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
    loadEditable();
  });
}

// The same counts for a map that was built earlier and is being opened
// again, where no build just answered with them.
async function loadLeftOut(mapName) {
  if (!mapName) return;
  try {
    const res = await fetch(`/api/why/${encodeURIComponent(mapName)}`);
    const data = await res.json();
    if (res.ok) showLeftOut(data);
  } catch (err) { /* nothing to show if it cannot be asked */ }
}

// The buildings are there: Buildings is done, and both ways to compile are
// open. The WorldEd note said "Generate the buildings first" even after they
// were built.
function showBuilt(text) {
  note('buildingsNote', text, 'ok');
  document.getElementById('worldedBtn').disabled = false;
  document.getElementById('compileBtn').disabled = false;
  note('compileNote', 'Ready — runs BMP to TMX and Generate Lots for you.');
  note('worldedNote', 'Then File → BMP To TMX → All Cells… and '
                      + 'File → Generate Lots 8x8 → All Cells…');
}

document.getElementById('buildingsBtn').addEventListener('click', async () => {
  const btn = document.getElementById('buildingsBtn');
  btn.disabled = true;
  note('buildingsNote', 'Generating…');
  showLeftOut(null);          // the last build's tally is not this one's
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
        note('buildingsNote', `${p.note}${pct}${leftText(p)}…`);
      }
    } catch (_) { /* the next tick will do */ }
  }, 1500);
  try {
    const res = await fetch('/api/buildings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      // Sent again so the buildings can be regenerated with different
      // settings without re-downloading the town from OSM.
      body: JSON.stringify({ mapName: currentMap, settings: settingsForRequest(),
                             sketch: sketchGeoJSON() }),
    });
    const data = await res.json();
    if (wasStopped(data, res)) {
      note('buildingsNote', 'Stopped. The terrain and the area are still here — press Build again.');
      fx.toast('ok', 'Stopped', 'Nothing was thrown away.');
      return;
    }
    if (!res.ok) throw apiError(data, res);
    if (data.terrain) renderResults(data.terrain);
    renderCensus(data.population);
    showBuilt(`${data.count} buildings → ${data.pzw}`);
    showLeftOut(data.left_out);
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
  const installing = currentMap;
  const stopWatching = watchInstall(installing, (done, total) => {
    if (currentMap === installing) note('installNote', `Installing — ${installSaid(done, total)}…`);
  });
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
    // Build 42 draws the in-game map (M) from worldmap.xml.bin and cannot read
    // the XML, so a map without it opens the map on nothing while everything
    // else works - worth saying, and worth saying what to do about it.
    const paper = data.paperMap === false
      ? ' The in-game map (M) will be blank: this map has no paper map '
        + '(worldmap.xml.bin). Install it again, and if it still has none, send '
        + 'KnoxMap the log from that install.'
      : '';
    note('installNote',
         `Installed ${data.cells} cells to ${data.modRoot}. Enable "${data.title}" `
         + 'in the game\'s Mods menu, then start a NEW save. In a save you are '
         + 'already playing, right-click the ground and pick "Reset loot" for '
         + 'fresh loot in a building.' + lifts + paper, data.paperMap === false ? 'warn' : 'ok');
    document.getElementById('publishCard').hidden = false;
    loadMaps();
  } catch (err) {
    note('installNote', err.message, 'bad');
    btn.disabled = false;
  } finally {
    stopWatching();
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
  renderAudit(pop.audit);
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

// What knoxbuild/audit.py found in the buildings just laid out: a room with no
// way in, a door onto the stairs, a flat with no front door. Said here because
// this is the last moment it is cheap to put right - compiling takes hours, and
// finding it after that means walking the town in game.
function renderAudit(found) {
  const box = document.getElementById('censusAudit');
  if (!found || !found.buildings) {
    box.hidden = true;
    box.textContent = '';
    return;
  }
  box.hidden = false;
  const problems = Object.entries(found.problems || {});
  const checked = found.buildings.toLocaleString();
  if (!found.flagged) {
    box.className = 'census-audit';
    box.textContent = `Layout audit: ${checked} buildings checked, nothing wrong.`;
    box.title = '';
    return;
  }
  const list = problems.slice(0, 3).map(([what, n]) => `${what} \u00d7${n}`).join(', ');
  const more = problems.length > 3 ? `, and ${problems.length - 3} more` : '';
  box.className = 'census-audit bad';
  box.textContent = `Layout audit: ${found.flagged.toLocaleString()} of ${checked} `
    + `buildings need a look - ${list}${more}.`;
  box.title = problems.map(([what, n]) => `${what}: ${n}`).join('\n');
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

