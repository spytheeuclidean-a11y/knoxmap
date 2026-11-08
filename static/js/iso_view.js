// Isometric 2.5D game view for KnoxMap.
// Displays the dimetric in-game rendering of Project Zomboid maps with pan,
// zoom, interiors/roofs toggling, and on-demand 1:1 HD sector rendering.

(() => {
  let activeMap = null;
  let mapInfo = null;
  let currentMode = 'town'; // 'town' | 'close' | 'inside' | 'sector'
  let scale = 1.0;
  let panX = 0;
  let panY = 0;
  let isDragging = false;
  let startX = 0;
  let startY = 0;
  let touchStartDist = 0;
  let touchStartScale = 1.0;

  let el = null;
  let stage = null;
  let img = null;
  let badge = null;
  let spinner = null;
  let spinnerText = null;
  let emptyBox = null;
  let titleEl = null;
  let sectorBar = null;

  function ensureElements() {
    const root = document.getElementById('wsIso');
    if (!root) return;
    if (el) return;

    root.innerHTML = `
      <div class="iso-container">
        <header class="iso-bar">
          <div class="iso-bar-left">
            <span class="iso-title" id="isoTitle"></span>
            <div class="iso-modes" role="radiogroup" aria-label="View mode">
              <button type="button" class="btn btn-small is-on" data-iso-mode="town"
                      title="Panoramic overview of the whole town with roofs">Town overview</button>
              <button type="button" class="btn btn-small" data-iso-mode="close"
                      title="Close-up view of the town center with roofs">Town center</button>
              <button type="button" class="btn btn-small" data-iso-mode="inside"
                      title="Furnished building interiors with roofs removed">Interiors</button>
              <button type="button" class="btn btn-small" data-iso-mode="sector"
                      title="Render a specific sector at 100% native in-game resolution">HD Sector 1:1</button>
            </div>
          </div>

          <div class="iso-bar-sector" id="isoSectorBar" hidden>
            <label>X: <input type="number" id="isoSectorX" min="0" step="50" value="1000"></label>
            <label>Y: <input type="number" id="isoSectorY" min="0" step="50" value="1000"></label>
            <label>Size:
              <select id="isoSectorSize">
                <option value="30">30 × 30</option>
                <option value="50" selected>50 × 50</option>
                <option value="80">80 × 80</option>
              </select>
            </label>
            <label class="iso-check">
              <input type="checkbox" id="isoSectorRoofs" checked> Roofs
            </label>
            <button type="button" class="btn btn-small btn-primary" id="isoRenderBtn">Render HD</button>
          </div>

          <div class="iso-bar-right">
            <div class="iso-zoom-controls">
              <button type="button" class="btn btn-small" id="isoZoomOut" title="Zoom out (Wheel down)">−</button>
              <span class="iso-zoom-badge" id="isoZoomBadge">100%</span>
              <button type="button" class="btn btn-small" id="isoZoomIn" title="Zoom in (Wheel up)">+</button>
              <button type="button" class="btn btn-small" id="isoZoomFit" title="Fit to screen">Fit</button>
              <button type="button" class="btn btn-small" id="isoZoom100" title="Real in-game 1:1 scale">1:1</button>
            </div>
            <button type="button" class="btn btn-small" id="isoDownload" title="Save current image">Save picture</button>
          </div>
        </header>

        <div class="iso-viewport" id="isoViewport" tabindex="0">
          <div class="iso-stage" id="isoStage">
            <img id="isoImg" class="iso-img" alt="Isometric game view" draggable="false" />
          </div>
          <div class="iso-spinner" id="isoSpinner" hidden>
            <div class="iso-spinner-box">
              <div class="spinner"></div>
              <span id="isoSpinnerText">Loading isometric view…</span>
            </div>
          </div>
          <div class="iso-hud">
            <span class="iso-tip">Drag to pan · Scroll to zoom · Double-click to zoom in</span>
          </div>
          <div class="iso-empty" id="isoEmpty" hidden>
            <div class="iso-empty-card">
              <h3>Map has not been compiled yet</h3>
              <p>To view the 2.5D isometric in-game representation of your buildings and town, compile your map first in the top pipeline.</p>
              <button type="button" class="btn btn-primary" id="isoCompileNow">Compile now</button>
            </div>
          </div>
        </div>
      </div>
    `;

    el = root.querySelector('.iso-container');
    stage = document.getElementById('isoStage');
    img = document.getElementById('isoImg');
    badge = document.getElementById('isoZoomBadge');
    spinner = document.getElementById('isoSpinner');
    spinnerText = document.getElementById('isoSpinnerText');
    emptyBox = document.getElementById('isoEmpty');
    titleEl = document.getElementById('isoTitle');
    sectorBar = document.getElementById('isoSectorBar');

    bindEvents();
  }

  function bindEvents() {
    const viewport = document.getElementById('isoViewport');

    // Pan with mouse
    viewport.addEventListener('mousedown', e => {
      if (e.target.closest('button, input, select, label, .iso-empty')) return;
      isDragging = true;
      startX = e.clientX - panX;
      startY = e.clientY - panY;
      viewport.classList.add('is-dragging');
    });

    window.addEventListener('mousemove', e => {
      if (!isDragging) return;
      panX = e.clientX - startX;
      panY = e.clientY - startY;
      applyTransform();
    });

    window.addEventListener('mouseup', () => {
      if (!isDragging) return;
      isDragging = false;
      viewport.classList.remove('is-dragging');
    });

    // Zoom with mouse wheel centered on cursor
    viewport.addEventListener('wheel', e => {
      e.preventDefault();
      const rect = viewport.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;

      const factor = e.deltaY < 0 ? 1.15 : (1 / 1.15);
      const newScale = Math.max(0.08, Math.min(6.0, scale * factor));
      if (newScale === scale) return;

      panX = cx - (cx - panX) * (newScale / scale);
      panY = cy - (cy - panY) * (newScale / scale);
      scale = newScale;
      applyTransform();
    }, { passive: false });

    // Double-click zoom in
    viewport.addEventListener('dblclick', e => {
      if (e.target.closest('button, input, select, label')) return;
      const rect = viewport.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const newScale = Math.min(6.0, scale * 1.5);
      panX = cx - (cx - panX) * (newScale / scale);
      panY = cy - (cy - panY) * (newScale / scale);
      scale = newScale;
      applyTransform();
    });

    // Touch support (pinch-to-zoom and pan)
    viewport.addEventListener('touchstart', e => {
      if (e.touches.length === 1) {
        isDragging = true;
        startX = e.touches[0].clientX - panX;
        startY = e.touches[0].clientY - panY;
      } else if (e.touches.length === 2) {
        isDragging = false;
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        touchStartDist = Math.hypot(dx, dy);
        touchStartScale = scale;
      }
    }, { passive: true });

    viewport.addEventListener('touchmove', e => {
      if (e.touches.length === 1 && isDragging) {
        panX = e.touches[0].clientX - startX;
        panY = e.touches[0].clientY - startY;
        applyTransform();
      } else if (e.touches.length === 2 && touchStartDist > 0) {
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        const dist = Math.hypot(dx, dy);
        const factor = dist / touchStartDist;
        scale = Math.max(0.08, Math.min(6.0, touchStartScale * factor));
        applyTransform();
      }
    }, { passive: true });

    viewport.addEventListener('touchend', () => {
      isDragging = false;
      touchStartDist = 0;
    });

    // Zoom buttons
    document.getElementById('isoZoomIn')?.addEventListener('click', () => {
      zoomBy(1.25);
    });
    document.getElementById('isoZoomOut')?.addEventListener('click', () => {
      zoomBy(1 / 1.25);
    });
    document.getElementById('isoZoomFit')?.addEventListener('click', () => {
      fitToScreen();
    });
    document.getElementById('isoZoom100')?.addEventListener('click', () => {
      zoomTo(1.0);
    });

    // Save image
    document.getElementById('isoDownload')?.addEventListener('click', () => {
      if (!img.src) return;
      const a = document.createElement('a');
      a.href = img.src;
      a.download = `${activeMap || 'map'}_isometric_${currentMode}.png`;
      a.click();
    });

    // Mode buttons
    el.querySelectorAll('[data-iso-mode]').forEach(btn => {
      btn.addEventListener('click', () => {
        setMode(btn.dataset.isoMode);
      });
    });

    // Sector HD Render button
    document.getElementById('isoRenderBtn')?.addEventListener('click', () => {
      renderSector();
    });

    // Go to Compile button
    document.getElementById('isoCompileNow')?.addEventListener('click', () => {
      const compileBtn = document.getElementById('compileBtn');
      if (compileBtn) compileBtn.click();
      const chip = document.querySelector('[data-chip="compile"]');
      if (chip) chip.click();
    });

    // Keyboard navigation
    viewport.addEventListener('keydown', e => {
      if (e.key === '+' || e.key === '=') { zoomBy(1.2); e.preventDefault(); }
      else if (e.key === '-') { zoomBy(1 / 1.2); e.preventDefault(); }
      else if (e.key === '0') { fitToScreen(); e.preventDefault(); }
      else if (e.key === '1') { zoomTo(1.0); e.preventDefault(); }
      else if (e.key === 'ArrowLeft') { panX += 50; applyTransform(); e.preventDefault(); }
      else if (e.key === 'ArrowRight') { panX -= 50; applyTransform(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { panY += 50; applyTransform(); e.preventDefault(); }
      else if (e.key === 'ArrowDown') { panY -= 50; applyTransform(); e.preventDefault(); }
    });

    img.addEventListener('load', () => {
      hideLoading();
    });

    img.addEventListener('error', () => {
      hideLoading();
    });
  }

  function applyTransform() {
    if (!stage) return;
    stage.style.transform = `translate(${Math.round(panX)}px, ${Math.round(panY)}px) scale(${scale.toFixed(4)})`;
    if (badge) badge.textContent = `${Math.round(scale * 100)}%`;
  }

  function zoomBy(factor) {
    const viewport = document.getElementById('isoViewport');
    if (!viewport) return;
    const cx = viewport.clientWidth / 2;
    const cy = viewport.clientHeight / 2;
    const newScale = Math.max(0.08, Math.min(6.0, scale * factor));
    panX = cx - (cx - panX) * (newScale / scale);
    panY = cy - (cy - panY) * (newScale / scale);
    scale = newScale;
    applyTransform();
  }

  function zoomTo(targetScale) {
    const viewport = document.getElementById('isoViewport');
    if (!viewport) return;
    const cx = viewport.clientWidth / 2;
    const cy = viewport.clientHeight / 2;
    const newScale = Math.max(0.08, Math.min(6.0, targetScale));
    panX = cx - (cx - panX) * (newScale / scale);
    panY = cy - (cy - panY) * (newScale / scale);
    scale = newScale;
    applyTransform();
  }

  function fitToScreen() {
    const viewport = document.getElementById('isoViewport');
    if (!viewport || !img || !img.naturalWidth) return;
    const vw = viewport.clientWidth;
    const vh = viewport.clientHeight;
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;

    const fitScale = Math.min((vw - 32) / iw, (vh - 32) / ih, 1.0);
    scale = Math.max(0.08, fitScale);
    panX = (vw - iw * scale) / 2;
    panY = (vh - ih * scale) / 2;
    applyTransform();
  }

  function showLoading(msg) {
    if (spinnerText) spinnerText.textContent = msg || 'Loading…';
    if (spinner) spinner.hidden = false;
  }

  function hideLoading() {
    if (spinner) spinner.hidden = true;
  }

  function setMode(mode) {
    currentMode = mode;
    el.querySelectorAll('[data-iso-mode]').forEach(b => {
      b.classList.toggle('is-on', b.dataset.isoMode === mode);
    });

    if (sectorBar) {
      sectorBar.hidden = mode !== 'sector';
    }

    if (mode === 'sector') {
      renderSector();
      return;
    }

    if (!mapInfo || !mapInfo.pictures) return;

    let src = mapInfo.pictures[mode];
    if (src) {
      showLoading(`Loading ${mode === 'inside' ? 'interiors' : mode}…`);
      img.src = src;
      img.onload = () => {
        hideLoading();
        fitToScreen();
      };
    } else {
      // Fallback: request from api_iso_render
      const roofs = mode !== 'inside';
      showLoading('Generating preview…');
      img.src = `/api/iso-render/${encodeURIComponent(activeMap)}?roofs=${roofs ? 1 : 0}&scale=0.5`;
      img.onload = () => {
        hideLoading();
        fitToScreen();
      };
    }
  }

  function renderSector() {
    if (!activeMap) return;
    const x = parseInt(document.getElementById('isoSectorX')?.value || '1000', 10);
    const y = parseInt(document.getElementById('isoSectorY')?.value || '1000', 10);
    const size = parseInt(document.getElementById('isoSectorSize')?.value || '50', 10);
    const roofs = document.getElementById('isoSectorRoofs')?.checked ? 1 : 0;

    showLoading(`Rendering PZ sector ${x},${y} (${size}×${size}) at native 1:1 scale…`);
    const url = `/api/iso-render/${encodeURIComponent(activeMap)}?box=${x},${y},${size},${size}&scale=1.0&roofs=${roofs}&t=${Date.now()}`;

    const testImg = new Image();
    testImg.onload = () => {
      img.src = url;
      hideLoading();
      fitToScreen();
    };
    testImg.onerror = () => {
      hideLoading();
      if (window.fx?.toast) {
        window.fx.toast('bad', 'Render error', 'Could not render this sector. Ensure it is inside the map bounds.', 5000);
      }
    };
    testImg.src = url;
  }

  async function showIsoView(name) {
    ensureElements();
    if (!name) return;

    if (activeMap === name && mapInfo) {
      fitToScreen();
      return;
    }

    activeMap = name;
    showLoading('Loading map data…');

    try {
      const res = await fetch(`/api/iso-info/${encodeURIComponent(name)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      mapInfo = await res.json();
    } catch (err) {
      hideLoading();
      if (window.fx?.toast) {
        window.fx.toast('bad', 'Error', `Could not load isometric info: ${err.message}`, 5000);
      }
      return;
    }

    if (!mapInfo.compiled) {
      hideLoading();
      if (emptyBox) emptyBox.hidden = false;
      if (stage) stage.hidden = true;
      if (titleEl) titleEl.textContent = `${name} · Uncompiled`;
      return;
    }

    if (emptyBox) emptyBox.hidden = true;
    if (stage) stage.hidden = false;

    // Set map title details
    const bldCount = mapInfo.building_count ? ` · ${mapInfo.building_count} buildings` : '';
    const dims = mapInfo.width_tiles && mapInfo.height_tiles
      ? ` · ${mapInfo.width_tiles} × ${mapInfo.height_tiles} tiles (${mapInfo.cells_x}×${mapInfo.cells_y} cells)`
      : '';
    if (titleEl) titleEl.textContent = `${name}${dims}${bldCount}`;

    // Update sector default coordinates to middle
    const midX = Math.round((mapInfo.width_tiles || 1000) / 2);
    const midY = Math.round((mapInfo.height_tiles || 1000) / 2);
    const inX = document.getElementById('isoSectorX');
    const inY = document.getElementById('isoSectorY');
    if (inX) inX.value = midX;
    if (inY) inY.value = midY;

    // Pick initial mode: 'town' if available, otherwise 'close', 'inside', or 'sector'
    let initialMode = 'town';
    if (!mapInfo.pictures?.town) {
      if (mapInfo.pictures?.close) initialMode = 'close';
      else if (mapInfo.pictures?.inside) initialMode = 'inside';
      else initialMode = 'sector';
    }

    setMode(initialMode);
  }

  function closeIsoView() {
    activeMap = null;
    mapInfo = null;
    hideLoading();
  }

  window.showIsoView = showIsoView;
  window.closeIsoView = closeIsoView;
})();
