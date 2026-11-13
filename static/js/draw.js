// The one drawing editor behind every place KnoxMap lets you draw shapes by
// hand: the sketch palette over the world map and the drawing board. It owns
// what used to be copied into each of them - arming a Leaflet draw handler,
// picking, removing, duplicating, dragging corners, snapping - and adds what
// neither had: undo and redo of anything (not just the last shape added),
// a rectangle tool, nudging with the arrow keys, and one toolbar.
//
//   const ed = KnoxDraw.create(map, { group, style, label, ... });
//   KnoxDraw.toolbar(container, ed);
//   ed.start('house', 'area');
//
// Every shape carries `layer.kdKind`, the palette id the server knows it by.
// Undo works by snapshot: the whole set of shapes is cheap to copy (a drawn
// map is hundreds of shapes, not millions), and one mechanism covers adding,
// removing, reshaping, nudging, duplicating and clearing alike.
(function () {
  const PICKED = { color: '#ff5f5f', weight: 4 };
  const NUDGE_PX = 4;

  const ringOf = layer => {
    const ll = layer.getLatLngs();
    return Array.isArray(ll[0]) ? ll[0] : ll;
  };
  const typeOf = layer => (layer instanceof L.Polygon ? 'area'
    : layer instanceof L.Polyline ? 'line' : 'point');

  function create(map, opts) {
    const o = Object.assign({
      group: null,          // the FeatureGroup shapes live in
      style: () => ({}),    // kind -> Leaflet path style
      label: k => k,        // kind -> words
      note: () => {},       // status line
      onChange: () => {},   // called with {count, canUndo, canRedo, picked, editing}
      onPick: null,         // called with the picked layer or null
      pickedBox: null,      // element the picked shape's details go in
      emptyPicked: null,    // what that box says with nothing picked; null hides it
      active: () => true,   // whether the keyboard belongs to this editor now
      snapOn: () => false,  // whether finished shapes snap
      snapDist: 14,         // in map units (metres on the drawing board)
      snapExtra: () => [],  // more points to snap to: [[lat, lng], ...]
      listen: true,         // false when the owner forwards CREATED to claim()
      palette: null,        // element whose .sketch-pick buttons start tools
      pickedStyle: PICKED,  // how the picked shape looks
      tooltip: null,        // layer -> tooltip html; default is the label
      tooltipOptions: { sticky: true },
      newMeta: null,        // kind -> data a new shape carries (kept by undo)
      cloneMeta: m => m,    // data -> the data a duplicate carries
      onAttach: null,       // called with each shape put on the map
      onClaimed: null,      // called with a shape the user has just drawn
      onStart: null,        // called when a tool is armed
    }, opts);
    const group = o.group || new L.FeatureGroup().addTo(map);
    const crsSimple = map.options.crs === L.CRS.Simple;

    let kind = null, handler = null, picked = null, editing = false;
    let rect = false, geometry = null;
    let history = [], at = -1, rev = 0;

    // ---- measuring ---------------------------------------------------------
    const dist = (a, b) => (crsSimple ? Math.hypot(a.lat - b.lat, a.lng - b.lng)
                                       : map.distance(a, b));
    function measure(layer) {
      if (layer.getLatLng) return '';
      const ring = ringOf(layer);
      if (ring.length < 2) return '';
      if (layer instanceof L.Polygon) {
        // Local flat projection: exact on the sheet, close enough on the world
        // map for shapes of a town's size.
        const lat0 = ring[0].lat;
        const kx = crsSimple ? 1 : 111320 * Math.cos(lat0 * Math.PI / 180);
        const ky = crsSimple ? 1 : 110540;
        let twice = 0;
        for (let i = 0; i < ring.length; i += 1) {
          const a = ring[i], b = ring[(i + 1) % ring.length];
          twice += (a.lng * kx) * (b.lat * ky) - (b.lng * kx) * (a.lat * ky);
        }
        const area = Math.abs(twice) / 2;
        return area >= 10000 ? `${(area / 10000).toFixed(2)} ha`
                             : `${Math.round(area)} m²`;
      }
      let run = 0;
      for (let i = 1; i < ring.length; i += 1) run += dist(ring[i], ring[i - 1]);
      return `${Math.round(run)} m long`;
    }

    // ---- history -----------------------------------------------------------
    const snapshot = () => {
      const out = [];
      group.eachLayer(l => {
        if (!l.kdKind) return;
        const type = typeOf(l);
        out.push({ kind: l.kdKind, type, meta: l.kdMeta,
                   pts: type === 'point' ? [[l.getLatLng().lat, l.getLatLng().lng]]
                                         : ringOf(l).map(p => [p.lat, p.lng]) });
      });
      return JSON.stringify(out);
    };

    function state() {
      return { count: group.getLayers().length, rev, canUndo: at > 0,
               canRedo: at < history.length - 1, picked, editing };
    }
    const changed = () => o.onChange(state());

    function commit() {
      const snap = snapshot();
      if (snap === history[at]) return;
      rev += 1;
      history = history.slice(0, at + 1);
      history.push(snap);
      if (history.length > 200) history.shift();
      at = history.length - 1;
      changed();
    }

    function build(item) {
      const pts = item.pts;
      if (item.type === 'area' && pts.length >= 3) return L.polygon(pts);
      if (item.type === 'line' && pts.length >= 2) return L.polyline(pts);
      if (item.type === 'point' && pts.length) return L.marker(pts[0]);
      return null;
    }

    function restore(snap) {
      pick(null);
      group.clearLayers();
      for (const item of JSON.parse(snap)) {
        const layer = build(item);
        if (layer) attach(item.kind, layer, item.meta);
      }
      rev += 1;
      changed();
    }

    function undo() {
      if (at <= 0) return;
      at -= 1;
      restore(history[at]);
      o.note('Undone.');
    }
    function redo() {
      if (at >= history.length - 1) return;
      at += 1;
      restore(history[at]);
      o.note('Redone.');
    }

    // ---- shapes ------------------------------------------------------------
    function drag(layer, on) {
      const h = layer.editing || layer.dragging;
      if (!h) return;
      if (on) h.enable(); else h.disable();
    }

    function snapPoints(skip) {
      const out = o.snapExtra().slice();
      group.eachLayer(l => {
        if (l === skip || !l.kdKind) return;
        if (l.getLatLng) { const p = l.getLatLng(); out.push([p.lat, p.lng]); }
        else for (const p of ringOf(l)) out.push([p.lat, p.lng]);
      });
      return out;
    }

    // Move the ends of a shape onto whatever they were aimed at.
    function snap(layer) {
      if (!o.snapOn() || layer.getLatLng) return 0;
      const targets = snapPoints(layer);
      if (!targets.length) return 0;
      const lls = layer.getLatLngs();
      const ring = Array.isArray(lls[0]) ? lls[0] : lls;
      let moved = 0;
      for (const p of ring) {
        let best = null, far = o.snapDist;
        for (const [lat, lng] of targets) {
          const d = Math.hypot(p.lat - lat, p.lng - lng);
          if (d > 0 && d <= far) { far = d; best = [lat, lng]; }
        }
        if (best) { p.lat = best[0]; p.lng = best[1]; moved += 1; }
      }
      if (moved) layer.setLatLngs(lls);
      return moved;
    }

    // Tag a layer and put it on the map, without touching history.
    function attach(k, layer, meta) {
      layer.kdKind = k;
      if (meta !== undefined) layer.kdMeta = meta;
      if (layer.setStyle) layer.setStyle(o.style(k));
      layer.bindTooltip(o.tooltip ? o.tooltip(layer) : o.label(k), o.tooltipOptions);
      layer.on('click', ev => {
        if (handler) return;               // a click while drawing is a vertex
        L.DomEvent.stop(ev);
        pick(layer);
      });
      // Corner dragged, or a marker let go: that is one undoable step, and
      // snapping applies to it as it does to a new shape.
      layer.on('edit dragend', () => {
        if (editing && layer.editing && o.snapOn()) {
          layer.editing.disable();
          snap(layer);
          layer.editing.enable();
        }
        commit();
      });
      group.addLayer(layer);
      if (editing) drag(layer, true);
      if (o.onAttach) o.onAttach(layer);
      return layer;
    }

    function add(k, layer, silent, meta) {
      attach(k, layer, meta);
      commit();
      if (!silent) o.note(`${o.label(k)} added.`);
      return layer;
    }

    function remove(layer) {
      if (!layer) return;
      if (picked === layer) pick(null);
      group.removeLayer(layer);
      commit();
      o.note('Removed.');
    }

    function clear() {
      if (!group.getLayers().length) return;
      pick(null);
      group.clearLayers();
      commit();
      o.note('Cleared. Undo brings it back.');
    }

    // Replace everything, as when a saved map opens; undo does not reach back
    // past it.
    function replace(items) {
      pick(null);
      group.clearLayers();
      for (const { kind: k, layer, meta } of items) attach(k, layer, meta);
      history = [snapshot()];
      at = 0;
      rev += 1;
      changed();
    }

    function each(fn) {
      group.eachLayer(l => { if (l.kdKind) fn(l, l.kdKind); });
    }

    function duplicate() {
      if (!picked) return;
      const k = picked.kdKind;
      const off = ([lat, lng]) => {
        // A fixed few pixels, so it lands visibly beside the original at any
        // zoom, in the world's degrees or the sheet's metres alike.
        const pt = map.latLngToLayerPoint([lat, lng]).add([20, 20]);
        const q = map.layerPointToLatLng(pt);
        return [q.lat, q.lng];
      };
      const item = { type: typeOf(picked),
                     pts: (picked.getLatLng ? [picked.getLatLng()] : ringOf(picked))
                       .map(p => off([p.lat, p.lng])) };
      const copy = build(item);
      if (!copy) return;
      add(k, copy, true, picked.kdMeta === undefined ? undefined
        : o.cloneMeta(JSON.parse(JSON.stringify(picked.kdMeta))));
      pick(copy);
      o.note(`${o.label(k)} copied. Drag it by its corners, or nudge with the arrow keys.`);
    }

    // ---- picking -----------------------------------------------------------
    function renderPicked() {
      const box = o.pickedBox;
      if (!box) return;
      box.classList.toggle('is-empty', !picked);
      if (!picked) {
        box.innerHTML = '';
        box.hidden = !o.emptyPicked;
        if (o.emptyPicked) {
          const none = document.createElement('span');
          none.className = 'hint';
          none.textContent = o.emptyPicked;
          box.append(none);
        }
        return;
      }
      const size = measure(picked);
      box.hidden = false;
      box.innerHTML = '';
      const text = document.createElement('span');
      text.className = 'hint';
      text.textContent = o.label(picked.kdKind) + (size ? ` · ${size}` : '');
      const del = document.createElement('button');
      del.type = 'button'; del.className = 'btn'; del.textContent = 'Remove';
      del.addEventListener('click', () => remove(picked));
      box.append(text, del);
    }

    function pick(layer) {
      if (picked && picked.setStyle && picked.kdKind) picked.setStyle(o.style(picked.kdKind));
      picked = layer || null;
      if (picked && picked.setStyle) picked.setStyle(o.pickedStyle);
      renderPicked();
      if (o.onPick) o.onPick(picked);
      changed();
    }

    // ---- tools -------------------------------------------------------------
    function stop() {
      if (handler) { handler.disable(); handler = null; }
      kind = null;
      if (o.palette) {
        for (const b of o.palette.querySelectorAll('.sketch-pick')) b.classList.remove('on');
      }
      changed();
    }

    function start(k, geom) {
      if (o.onStart) o.onStart();
      stop();
      pick(null);
      if (editing) setEditing(false);
      kind = k;
      geometry = geom;
      const shapeOptions = o.style(k);
      if (geom === 'line') handler = new L.Draw.Polyline(map, { shapeOptions });
      else if (geom === 'area' && rect) handler = new L.Draw.Rectangle(map, { shapeOptions });
      else if (geom === 'area') {
        handler = new L.Draw.Polygon(map, { allowIntersection: false, shapeOptions });
      } else handler = new L.Draw.Marker(map, {});
      handler.enable();
      if (o.palette) {
        for (const b of o.palette.querySelectorAll('.sketch-pick')) {
          b.classList.toggle('on', b.dataset.kind === k);
        }
      }
      o.note(`Drawing ${o.label(k)}. ${geom === 'point' ? 'Click to place it.'
        : rect && geom === 'area' ? 'Drag a rectangle.'
        : 'Click each corner; double-click or click the last point to finish.'}`);
      changed();
    }

    function setRect(on) {
      rect = !!on;
      if (kind && geometry === 'area') start(kind, geometry);
      changed();
    }

    // A finished draw handler's layer. Returns true if it was ours.
    function claim(layer) {
      if (!kind) return false;
      const k = kind;
      const geom = geometry;
      stop();
      // A rectangle comes back as L.Rectangle; the server wants plain corners.
      const shape = layer instanceof L.Rectangle
        ? L.polygon(layer.getLatLngs()[0]) : layer;
      const joined = snap(shape);
      add(k, shape, true, o.newMeta ? o.newMeta(k) : undefined);
      o.note(`${o.label(k)} added${joined ? `, ${joined} end${joined === 1 ? '' : 's'} joined up` : ''}.`
        + (geom ? ' Pick another tool to keep going.' : ''));
      if (o.onClaimed) o.onClaimed(shape);
      return true;
    }

    function setEditing(on) {
      editing = !!on;
      if (on) { stop(); pick(null); }
      group.eachLayer(l => drag(l, on));
      o.note(on ? 'Drag a corner to move it, or the middle of a line to add one. '
                  + 'Press Move and reshape again to stop.'
                : 'Back to drawing.');
      changed();
    }

    function nudge(dx, dy) {
      if (!picked) return;
      const shift = p => {
        const q = map.layerPointToLatLng(map.latLngToLayerPoint(p).add([dx, dy]));
        return q;
      };
      const wasEditing = editing && picked.editing;
      if (wasEditing) picked.editing.disable();
      if (picked.getLatLng) picked.setLatLng(shift(picked.getLatLng()));
      else {
        const lls = picked.getLatLngs();
        const ring = Array.isArray(lls[0]) ? lls[0] : lls;
        picked.setLatLngs(Array.isArray(lls[0]) ? [ring.map(shift)] : ring.map(shift));
      }
      if (wasEditing) picked.editing.enable();
      renderPicked();
    }

    // ---- keyboard ----------------------------------------------------------
    document.addEventListener('keydown', ev => {
      if (!o.active()) return;
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName || '')) return;
      const mod = ev.ctrlKey || ev.metaKey;
      if (mod && ev.key.toLowerCase() === 'z') {
        ev.preventDefault();
        if (ev.shiftKey) redo(); else undo();
      } else if (mod && ev.key.toLowerCase() === 'y') {
        ev.preventDefault();
        redo();
      } else if (ev.key === 'Escape') {
        if (kind) { stop(); o.note('Stopped drawing.'); }
        else if (picked) pick(null);
      } else if ((ev.key === 'Delete' || ev.key === 'Backspace') && picked) {
        ev.preventDefault();
        remove(picked);
      } else if (picked && ev.key.startsWith('Arrow')) {
        ev.preventDefault();
        const n = ev.shiftKey ? NUDGE_PX * 5 : NUDGE_PX;
        nudge(ev.key === 'ArrowLeft' ? -n : ev.key === 'ArrowRight' ? n : 0,
              ev.key === 'ArrowUp' ? -n : ev.key === 'ArrowDown' ? n : 0);
      }
    });
    document.addEventListener('keyup', ev => {
      if (o.active() && picked && ev.key.startsWith('Arrow')) commit();
    });

    if (o.listen) {
      map.on(L.Draw.Event.CREATED, ev => { claim(ev.layer); });
    }
    if (o.palette) {
      o.palette.addEventListener('click', ev => {
        const btn = ev.target.closest('.sketch-pick');
        if (btn) start(btn.dataset.kind, btn.dataset.geometry);
      });
    }

    history = [snapshot()];
    at = 0;

    return {
      group, start, stop, claim, commit, add, remove, clear, replace, each, duplicate,
      undo, redo, pick, setEditing, setRect, nudge, measure,
      get kind() { return kind; },
      get picked() { return picked; },
      get editing() { return editing; },
      get rect() { return rect; },
      get count() { return group.getLayers().length; },
      state,
    };
  }

  // The same row of buttons everywhere. They follow the editor's state, so
  // Undo is dimmed when there is nothing to undo and Duplicate when nothing is
  // picked, wherever the row happens to be.
  // With { rect: false } the row leaves out Rectangle, for a page that offers
  // it as a switch of its own (the Add tab's Draw areas as boxes).
  function toolbar(container, ed, { rect = true } = {}) {
    const defs = [
      ['undo', 'Undo', 'Ctrl+Z', () => ed.undo()],
      ['redo', 'Redo', 'Ctrl+Shift+Z', () => ed.redo()],
      ...(rect ? [['rect', 'Rectangle', 'Draw areas as a rectangle by dragging',
        () => ed.setRect(!ed.rect)]] : []),
      ['edit', 'Move and reshape', 'Drag corners; arrow keys nudge a picked shape',
        () => ed.setEditing(!ed.editing)],
      ['dupe', 'Duplicate', 'Copy the picked shape', () => ed.duplicate()],
      ['clear', 'Clear', 'Remove everything (Undo brings it back)', () => ed.clear()],
    ];
    container.classList.add('kd-bar');
    const buttons = {};
    for (const [id, text, title, run] of defs) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'btn kd-' + id; b.textContent = text;
      b.title = title;
      b.addEventListener('click', run);
      container.appendChild(b);
      buttons[id] = b;
    }
    function refresh() {
      const s = ed.state();
      buttons.undo.disabled = !s.canUndo;
      buttons.redo.disabled = !s.canRedo;
      buttons.dupe.disabled = !s.picked;
      buttons.clear.disabled = !s.count;
      buttons.edit.classList.toggle('on', s.editing);
      if (buttons.rect) buttons.rect.classList.toggle('on', ed.rect);
    }
    return refresh;
  }

  window.KnoxDraw = { create, toolbar };
})();
