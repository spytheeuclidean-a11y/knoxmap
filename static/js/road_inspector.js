// Developer Road & Sidewalk Inspector: pan and zoom over the generated ground
// and road-detail bitmaps (<map>.bmp and <map>_veg.bmp) without opening PZ.
(function () {
  'use strict';

  let overlay = null;
  let canvas = null;
  let ctx = null;
  let groundImg = null;
  let detailsImg = null;
  let showDetails = true;
  let showGrid = true;
  let scale = 1.0;
  let panX = 0;
  let panY = 0;
  let dragging = false;
  let dragX = 0;
  let dragY = 0;
  let currentName = null;
  let groundReadCtx = null;
  let detailsReadCtx = null;

  function sampleTileLabel(tx, ty) {
    const parts = [];
    if (groundReadCtx) {
      const p = groundReadCtx.getImageData(tx, ty, 1, 1).data;
      const hex = ((p[0] << 16) | (p[1] << 8) | p[2]);
      if (hex === 0x646464 || hex === 0x505050 || hex === 0x464646 || hex === 0x3c3c3c || hex === 0x6e6e6e) {
        parts.push('Asphalt');
      } else if (hex === 0x787878) {
        parts.push('Sidewalk');
      } else if (hex === 0x75752f || hex === 0x5a6423 || hex === 0x8f883c) {
        parts.push('Grass');
      } else if (hex === 0x008aff) {
        parts.push('Water');
      } else {
        parts.push(`Ground rgb(${p[0]},${p[1]},${p[2]})`);
      }
    }
    if (showDetails && detailsReadCtx) {
      const d = detailsReadCtx.getImageData(tx, ty, 1, 1).data;
      if (d[3] > 0 && (d[0] || d[1] || d[2])) {
        const hex = ((d[0] << 16) | (d[1] << 8) | d[2]);
        if (hex === 0x00e6ff) parts.push('Straight kerb');
        else if (hex === 0x50aaff) parts.push('Diag kerb');
        else if (hex === 0xffffff) parts.push('White line / crossing');
        else if (hex === 0xffdc28) parts.push('Yellow line');
        else if (hex === 0xff821e) parts.push('Street prop');
        else parts.push(`Detail rgb(${d[0]},${d[1]},${d[2]})`);
      }
    }
    return parts.join(' + ');
  }

  function makeReadCtx(img) {
    const c = document.createElement('canvas');
    c.width = img.naturalWidth;
    c.height = img.naturalHeight;
    const g = c.getContext('2d', { willReadFrequently: true });
    g.drawImage(img, 0, 0);
    return g;
  }

  function ensureOverlay() {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.id = 'roadInspectorOverlay';
    overlay.hidden = true;
    overlay.style.cssText = [
      'position:fixed', 'inset:0', 'z-index:1200', 'background:#0d0f11',
      'display:none', 'flex-direction:column', 'color:#e6e8eb',
      'font-family:inherit',
    ].join(';');

    overlay.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 14px;background:#16191d;border-bottom:1px solid #2b3036;flex-wrap:wrap">
        <div style="display:flex;align-items:center;gap:12px">
          <strong style="font-size:13px">Road &amp; sidewalk inspector</strong>
          <span id="riDims" style="font-size:12px;color:#9aa3ad"></span>
          <label style="display:inline-flex;align-items:center;gap:5px;font-size:12px;cursor:pointer">
            <input type="checkbox" id="riDetails" checked> Kerbs, lines &amp; props
          </label>
          <label style="display:inline-flex;align-items:center;gap:5px;font-size:12px;cursor:pointer">
            <input type="checkbox" id="riGrid" checked> Tile grid (&ge;4x)
          </label>
        </div>
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <input type="number" id="riJumpX" placeholder="x" title="Jump to tile X" style="width:62px;padding:3px 6px;background:#0d0f11;color:#e6e8eb;border:1px solid #2b3036;border-radius:4px;font-size:12px">
          <input type="number" id="riJumpY" placeholder="y" title="Jump to tile Y" style="width:62px;padding:3px 6px;background:#0d0f11;color:#e6e8eb;border:1px solid #2b3036;border-radius:4px;font-size:12px">
          <button type="button" class="btn btn-small" id="riJumpBtn">Go</button>
          <button type="button" class="btn btn-small" id="riZoomOut">-</button>
          <span id="riZoomBadge" style="min-width:52px;text-align:center;font-size:12px;font-variant-numeric:tabular-nums">100%</span>
          <button type="button" class="btn btn-small" id="riZoomIn">+</button>
          <button type="button" class="btn btn-small" id="riFit">Fit</button>
          <button type="button" class="btn btn-small" id="ri100">1:1</button>
          <button type="button" class="btn btn-small" id="ri400">4x</button>
          <button type="button" class="btn btn-small" id="ri800">8x</button>
          <button type="button" class="btn btn-small" id="riRefresh" title="Reload bitmaps">Refresh</button>
          <button type="button" class="btn btn-small" id="riClose">Close</button>
        </div>
      </div>
      <div id="riViewport" style="position:relative;flex:1;overflow:hidden;cursor:grab">
        <canvas id="riCanvas" style="display:block;width:100%;height:100%"></canvas>
        <div id="riStatus" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:13px;color:#9aa3ad;pointer-events:none"></div>
      </div>
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:6px 14px;background:#16191d;border-top:1px solid #2b3036;font-size:11px;color:#9aa3ad;flex-wrap:wrap">
        <span id="riCoords">Hover over the map · Drag to pan · Scroll to zoom</span>
        <span style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <span><i style="display:inline-block;width:10px;height:10px;background:#646464;border:1px solid #444;vertical-align:middle"></i> Asphalt</span>
          <span><i style="display:inline-block;width:10px;height:10px;background:#787878;border:1px solid #444;vertical-align:middle"></i> Sidewalk</span>
          <span><i style="display:inline-block;width:10px;height:10px;background:#75752f;border:1px solid #444;vertical-align:middle"></i> Grass</span>
          <span><i style="display:inline-block;width:10px;height:10px;background:#00e6ff;vertical-align:middle"></i> Straight kerb</span>
          <span><i style="display:inline-block;width:10px;height:10px;background:#50aaff;vertical-align:middle"></i> Diag kerb</span>
          <span><i style="display:inline-block;width:10px;height:10px;background:#ffffff;vertical-align:middle"></i> White line / crossing</span>
          <span><i style="display:inline-block;width:10px;height:10px;background:#ffdc28;vertical-align:middle"></i> Yellow line</span>
          <span><i style="display:inline-block;width:10px;height:10px;background:#ff821e;vertical-align:middle"></i> Street prop</span>
        </span>
      </div>
    `;
    document.body.appendChild(overlay);

    canvas = document.getElementById('riCanvas');
    ctx = canvas.getContext('2d');
    const viewport = document.getElementById('riViewport');

    function resizeCanvas() {
      const r = viewport.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(r.width * dpr));
      canvas.height = Math.max(1, Math.round(r.height * dpr));
      draw();
    }

    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(resizeCanvas).observe(viewport);
    } else {
      window.addEventListener('resize', resizeCanvas);
    }

    viewport.addEventListener('mousedown', e => {
      if (e.button !== 0) return;
      dragging = true;
      dragX = e.clientX - panX;
      dragY = e.clientY - panY;
      viewport.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', e => {
      if (dragging) {
        panX = e.clientX - dragX;
        panY = e.clientY - dragY;
        draw();
      }
      if (!overlay.hidden && groundImg && groundImg.complete && groundImg.naturalWidth) {
        const r = viewport.getBoundingClientRect();
        const tx = Math.floor((e.clientX - r.left - panX) / scale);
        const ty = Math.floor((e.clientY - r.top - panY) / scale);
        const el = document.getElementById('riCoords');
        if (tx >= 0 && ty >= 0 && tx < groundImg.naturalWidth && ty < groundImg.naturalHeight) {
          const info = sampleTileLabel(tx, ty);
          el.textContent = `Tile (${tx}, ${ty})${info ? ' · ' + info : ''} · Drag to pan · Scroll to zoom`;
        } else {
          el.textContent = 'Hover over the map · Drag to pan · Scroll to zoom';
        }
      }
    });

    window.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      viewport.style.cursor = 'grab';
    });

    viewport.addEventListener('wheel', e => {
      e.preventDefault();
      const r = viewport.getBoundingClientRect();
      const cx = e.clientX - r.left;
      const cy = e.clientY - r.top;
      const factor = e.deltaY < 0 ? 1.25 : 1 / 1.25;
      zoomAt(cx, cy, scale * factor);
    }, { passive: false });

    document.getElementById('riDetails').addEventListener('change', e => {
      showDetails = e.target.checked;
      draw();
    });
    document.getElementById('riGrid').addEventListener('change', e => {
      showGrid = e.target.checked;
      draw();
    });
    function jumpToInputs() {
      if (!groundImg || !groundImg.naturalWidth) return;
      const xEl = document.getElementById('riJumpX');
      const yEl = document.getElementById('riJumpY');
      const tx = Number(xEl.value);
      const ty = Number(yEl.value);
      if (!Number.isFinite(tx) || !Number.isFinite(ty)) return;
      const nextScale = Math.max(scale, 6);
      scale = Math.max(0.05, Math.min(24, nextScale));
      panX = viewport.clientWidth / 2 - (tx + 0.5) * scale;
      panY = viewport.clientHeight / 2 - (ty + 0.5) * scale;
      draw();
    }

    document.getElementById('riJumpBtn').addEventListener('click', jumpToInputs);
    document.getElementById('riJumpX').addEventListener('keydown', e => {
      if (e.key === 'Enter') jumpToInputs();
    });
    document.getElementById('riJumpY').addEventListener('keydown', e => {
      if (e.key === 'Enter') jumpToInputs();
    });
    document.getElementById('riZoomIn').addEventListener('click', () => zoomCenter(scale * 1.4));
    document.getElementById('riZoomOut').addEventListener('click', () => zoomCenter(scale / 1.4));
    document.getElementById('riFit').addEventListener('click', fit);
    document.getElementById('ri100').addEventListener('click', () => zoomCenter(1));
    document.getElementById('ri400').addEventListener('click', () => zoomCenter(4));
    document.getElementById('ri800').addEventListener('click', () => zoomCenter(8));
    document.getElementById('riRefresh').addEventListener('click', () => {
      if (currentName) window.openRoadInspector(currentName);
    });
    document.getElementById('riClose').addEventListener('click', close);

    window.addEventListener('knoxmap:generated', e => {
      const name = e && e.detail && e.detail.mapName;
      if (overlay && !overlay.hidden && currentName && (!name || name === currentName)) {
        window.openRoadInspector(currentName);
      }
    });

    document.addEventListener('keydown', e => {
      if (overlay.hidden) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
      } else if (e.key === '+' || e.key === '=') zoomCenter(scale * 1.3);
      else if (e.key === '-') zoomCenter(scale / 1.3);
      else if (e.key === '0') fit();
    }, true);
  }

  function zoomAt(cx, cy, nextScale) {
    const clamped = Math.max(0.05, Math.min(24, nextScale));
    panX = cx - (cx - panX) * (clamped / scale);
    panY = cy - (cy - panY) * (clamped / scale);
    scale = clamped;
    draw();
  }

  function zoomCenter(nextScale) {
    const viewport = document.getElementById('riViewport');
    if (!viewport) return;
    zoomAt(viewport.clientWidth / 2, viewport.clientHeight / 2, nextScale);
  }

  function fit() {
    const viewport = document.getElementById('riViewport');
    if (!viewport || !groundImg || !groundImg.naturalWidth) return;
    const vw = viewport.clientWidth;
    const vh = viewport.clientHeight;
    if (vw <= 16 || vh <= 16) return;
    const iw = groundImg.naturalWidth;
    const ih = groundImg.naturalHeight;
    scale = Math.max(0.05, Math.min((vw - 24) / iw, (vh - 24) / ih));
    panX = (vw - iw * scale) / 2;
    panY = (vh - ih * scale) / 2;
    draw();
  }

  function draw() {
    if (!ctx || !canvas || overlay.hidden) return;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = '#0d0f11';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const badge = document.getElementById('riZoomBadge');
    if (badge) badge.textContent = `${Math.round(scale * 100)}%`;

    if (!groundImg || !groundImg.complete || !groundImg.naturalWidth) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = false;

    const iw = groundImg.naturalWidth;
    const ih = groundImg.naturalHeight;
    ctx.drawImage(groundImg, panX, panY, iw * scale, ih * scale);
    if (showDetails && detailsImg && detailsImg.complete && detailsImg.naturalWidth) {
      ctx.drawImage(detailsImg, panX, panY, iw * scale, ih * scale);
    }

    if (showGrid && scale >= 4) {
      const vw = canvas.width / dpr;
      const vh = canvas.height / dpr;
      const xStart = Math.max(0, Math.floor(-panX / scale));
      const xEnd = Math.min(iw, Math.ceil((vw - panX) / scale));
      const yStart = Math.max(0, Math.floor(-panY / scale));
      const yEnd = Math.min(ih, Math.ceil((vh - panY) / scale));
      ctx.strokeStyle = 'rgba(255,255,255,0.12)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = xStart; x <= xEnd; x++) {
        const sx = Math.round(panX + x * scale) + 0.5;
        ctx.moveTo(sx, Math.max(0, panY));
        ctx.lineTo(sx, Math.min(vh, panY + ih * scale));
      }
      for (let y = yStart; y <= yEnd; y++) {
        const sy = Math.round(panY + y * scale) + 0.5;
        ctx.moveTo(Math.max(0, panX), sy);
        ctx.lineTo(Math.min(vw, panX + iw * scale), sy);
      }
      ctx.stroke();
    }
  }

  function close() {
    dragging = false;
    const viewport = document.getElementById('riViewport');
    if (viewport) viewport.style.cursor = 'grab';
    if (overlay) {
      overlay.hidden = true;
      overlay.style.display = 'none';
    }
  }

  window.openRoadInspector = function (name) {
    if (!name) return;
    ensureOverlay();
    currentName = name;
    overlay.hidden = false;
    overlay.style.display = 'flex';
    const status = document.getElementById('riStatus');
    const dims = document.getElementById('riDims');
    status.textContent = 'Loading generated road & ground bitmaps…';
    dims.textContent = name;

    const bust = Date.now();
    const g = new Image();
    const d = new Image();
    groundImg = g;
    detailsImg = d;

    groundReadCtx = null;
    detailsReadCtx = null;
    g.onload = () => {
      if (groundImg !== g) return;
      groundReadCtx = makeReadCtx(g);
      status.textContent = '';
      dims.textContent = `${name} · ${g.naturalWidth} × ${g.naturalHeight} tiles`;
      fit();
    };
    g.onerror = () => {
      if (groundImg !== g) return;
      status.textContent = `No generated bitmap found for ${name} yet. Run Generate map first.`;
    };
    d.onload = () => {
      if (detailsImg === d) {
        detailsReadCtx = makeReadCtx(d);
        draw();
      }
    };

    const enc = encodeURIComponent(name);
    g.src = `/api/road-inspector/${enc}?layer=ground&t=${bust}`;
    d.src = `/api/road-inspector/${enc}?layer=details&t=${bust}`;
  };
})();
