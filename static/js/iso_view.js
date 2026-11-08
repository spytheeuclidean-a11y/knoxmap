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
  let emptyBox = null;
  let titleEl = null;
  let sectorBar = null;
  let loadHdHereBtn = null;
  let backOverviewBtn = null;
  let cellSelect = null;

  // Progress overlay elements and state
  let overlay = null;
  let progressKicker = null;
  let progressTitle = null;
  let progressSub = null;
  let progressBar = null;
  let progressPercent = null;
  let progressClock = null;
  let cancelBtn = null;

  let progressTimer = null;
  let progressStartTime = 0;
  let activeImageLoader = null;
  let isCancelled = false;

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
                      title="Full town view with all furnished building interiors and roofs removed">Interiors (All)</button>
              <button type="button" class="btn btn-small" data-iso-mode="sector"
                      title="Render a specific sector at 100% native in-game resolution">HD Sector 1:1</button>
            </div>
          </div>

          <!-- Quick Load HD of current view -->
          <button type="button" class="btn btn-small btn-hd" id="isoLoadHdHere"
                  title="Render this current view at 100% crystal-clear in-game resolution">🔍 Load HD here</button>

          <!-- Sector HD toolbar controls -->
          <div class="iso-bar-sector" id="isoSectorBar" hidden style="display: none;">
            <button type="button" class="btn btn-small" id="isoBackOverview"
                    title="Back to full town overview">◀ Full town</button>
            <label>Cell:
              <select id="isoCellSelect" class="iso-cell-select" title="Jump directly to any compiled cell">
                <option value="">(Select cell)</option>
              </select>
            </label>
            <label>X: <input type="number" id="isoSectorX" min="0" step="50" value="1200"></label>
            <label>Y: <input type="number" id="isoSectorY" min="0" step="50" value="1050"></label>
            <label>Size:
              <select id="isoSectorSize">
                <option value="40">40 × 40</option>
                <option value="60" selected>60 × 60</option>
                <option value="80">80 × 80</option>
                <option value="120">120 × 120</option>
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

          <!-- Progress overlay with progress bar, clock & cancel button -->
          <div class="iso-overlay" id="isoOverlay" hidden style="display: none;">
            <div class="iso-progress-box">
              <div class="iso-progress-kicker" id="isoProgressKicker">Project Zomboid 2.5D View</div>
              <div class="iso-progress-title" id="isoProgressTitle">Preparing isometric view…</div>
              <div class="iso-progress-sub" id="isoProgressSub">Processing tiles & building lots</div>
              <div class="bar">
                <div class="bar-fill" id="isoProgressBar" style="width: 0%;"></div>
              </div>
              <div class="iso-progress-footer">
                <span class="iso-progress-percent" id="isoProgressPercent">0%</span>
                <span class="iso-progress-clock" id="isoProgressClock">⏱️ 0:00</span>
                <button type="button" class="btn btn-small" id="isoCancelBtn">Cancel</button>
              </div>
            </div>
          </div>

          <div class="iso-hud">
            <span class="iso-tip">Drag to pan · Scroll to zoom · Double-click anywhere to view in HD 1:1</span>
          </div>

          <div class="iso-empty" id="isoEmpty" hidden style="display: none;">
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
    emptyBox = document.getElementById('isoEmpty');
    titleEl = document.getElementById('isoTitle');
    sectorBar = document.getElementById('isoSectorBar');
    loadHdHereBtn = document.getElementById('isoLoadHdHere');
    backOverviewBtn = document.getElementById('isoBackOverview');
    cellSelect = document.getElementById('isoCellSelect');

    overlay = document.getElementById('isoOverlay');
    progressKicker = document.getElementById('isoProgressKicker');
    progressTitle = document.getElementById('isoProgressTitle');
    progressSub = document.getElementById('isoProgressSub');
    progressBar = document.getElementById('isoProgressBar');
    progressPercent = document.getElementById('isoProgressPercent');
    progressClock = document.getElementById('isoProgressClock');
    cancelBtn = document.getElementById('isoCancelBtn');

    bindEvents();
  }

  function startProgress(title, sub, estimatedSecs = 4) {
    ensureElements();
    isCancelled = false;
    if (progressTimer) clearInterval(progressTimer);

    if (progressTitle) progressTitle.textContent = title || 'Loading isometric view…';
    if (progressSub) progressSub.textContent = sub || 'Reading map data…';
    if (progressBar) progressBar.style.width = '0%';
    if (progressPercent) progressPercent.textContent = '0%';
    if (progressClock) progressClock.textContent = '⏱️ 0:00';

    if (overlay) {
      overlay.hidden = false;
      overlay.style.display = 'flex';
    }

    progressStartTime = Date.now();

    progressTimer = setInterval(() => {
      const elapsed = (Date.now() - progressStartTime) / 1000;
      const mins = Math.floor(elapsed / 60);
      const secs = Math.floor(elapsed % 60);
      if (progressClock) {
        progressClock.textContent = `⏱️ ${mins}:${String(secs).padStart(2, '0')}`;
      }

      // Smooth simulated progress curve approaching 92% at estimatedSecs
      let p = 0;
      if (elapsed <= estimatedSecs) {
        p = Math.round((elapsed / estimatedSecs) * 85);
      } else {
        const extra = elapsed - estimatedSecs;
        p = Math.min(96, Math.round(85 + (extra / (extra + 5)) * 11));
      }

      if (progressBar) progressBar.style.width = `${p}%`;
      if (progressPercent) progressPercent.textContent = `${p}%`;

      // Update descriptive subtitles as time progresses
      if (progressSub) {
        if (p < 25) {
          progressSub.textContent = 'Loading building data…';
        } else if (p < 60) {
          progressSub.textContent = 'Rendering tiles and isometric projection…';
        } else if (p < 85) {
          progressSub.textContent = 'Compositing furniture, walls and layers…';
        } else {
          progressSub.textContent = 'Finalizing image…';
        }
      }
    }, 120);
  }

  function finishProgress(isError = false) {
    if (progressTimer) {
      clearInterval(progressTimer);
      progressTimer = null;
    }

    if (isError) {
      if (overlay) {
        overlay.hidden = true;
        overlay.style.display = 'none';
      }
      return;
    }

    if (progressBar) progressBar.style.width = '100%';
    if (progressPercent) progressPercent.textContent = '100%';
    if (progressSub) progressSub.textContent = 'Done!';

    setTimeout(() => {
      if (overlay) {
        overlay.hidden = true;
        overlay.style.display = 'none';
      }
    }, 180);
  }

  function cancelProgress() {
    isCancelled = true;
    if (activeImageLoader) {
      activeImageLoader.src = '';
      activeImageLoader = null;
    }
    finishProgress(true);
    if (window.fx?.toast) {
      window.fx.toast('bad', 'Cancelled', 'Loading cancelled.', 3000);
    }
  }

  // Convert current screen coordinates to map tile coordinates (X, Y)
  function screenPointToTile(clientX, clientY) {
    const viewport = document.getElementById('isoViewport');
    if (!viewport || !img || !img.naturalWidth || !mapInfo) {
      return { x: 1000, y: 1000 };
    }

    const rect = viewport.getBoundingClientRect();
    const vcx = clientX - rect.left;
    const vcy = clientY - rect.top;

    const imgX = (vcx - panX) / scale;
    const imgY = (vcy - panY) / scale;

    const W = mapInfo.width_tiles || 2400;
    const H = mapInfo.height_tiles || 2100;
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;

    const cx = iw / 2;
    const cy = ih / 2;
    const half = iw / (W + H);
    const quarter = half / 2;

    const dx = imgX - cx;
    const dy = imgY - cy;

    const t_dx = (dx / half + dy / quarter) / 2;
    const t_dy = (dy / quarter - dx / half) / 2;

    const tileX = Math.max(0, Math.min(W, Math.round(W / 2 + t_dx)));
    const tileY = Math.max(0, Math.min(H, Math.round(H / 2 + t_dy)));

    return { x: tileX, y: tileY };
  }

  function getViewportCenterTile() {
    const viewport = document.getElementById('isoViewport');
    if (!viewport) return { x: 1000, y: 1000 };
    const rect = viewport.getBoundingClientRect();
    return screenPointToTile(rect.left + rect.width / 2, rect.top + rect.height / 2);
  }

  function bindEvents() {
    const viewport = document.getElementById('isoViewport');

    // Pan with mouse
    viewport.addEventListener('mousedown', e => {
      if (e.target.closest('button, input, select, label, .iso-empty, .iso-overlay')) return;
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
      const newScale = Math.max(0.08, Math.min(8.0, scale * factor));
      if (newScale === scale) return;

      panX = cx - (cx - panX) * (newScale / scale);
      panY = cy - (cy - panY) * (newScale / scale);
      scale = newScale;
      applyTransform();
    }, { passive: false });

    // Double-click on any building/street renders that sector in HD 1:1
    viewport.addEventListener('dblclick', e => {
      if (e.target.closest('button, input, select, label, .iso-overlay')) return;
      const { x, y } = screenPointToTile(e.clientX, e.clientY);
      const size = parseInt(document.getElementById('isoSectorSize')?.value || '60', 10);
      const roofs = currentMode === 'inside' ? 0 : 1;
      renderSectorAt(x, y, size, roofs);
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
        scale = Math.max(0.08, Math.min(8.0, touchStartScale * factor));
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

    // Load HD Here button
    loadHdHereBtn?.addEventListener('click', () => {
      const { x, y } = getViewportCenterTile();
      const size = parseInt(document.getElementById('isoSectorSize')?.value || '60', 10);
      const roofs = currentMode === 'inside' ? 0 : (document.getElementById('isoSectorRoofs')?.checked ? 1 : 0);
      renderSectorAt(x, y, size, roofs);
    });

    // Back to full town overview button
    backOverviewBtn?.addEventListener('click', () => {
      setMode('town');
    });

    // Jump to cell selection
    cellSelect?.addEventListener('change', e => {
      const val = e.target.value;
      if (!val) return;
      const parts = val.split('_').map(Number);
      if (parts.length === 2 && mapInfo?.cells?.length) {
        // Calculate cell center tile in map coordinates
        const minCx = Math.min(...mapInfo.cells.map(c => c[0]));
        const minCy = Math.min(...mapInfo.cells.map(c => c[1]));
        const targetX = (parts[0] - minCx) * 300 + 150;
        const targetY = (parts[1] - minCy) * 300 + 150;

        const size = parseInt(document.getElementById('isoSectorSize')?.value || '60', 10);
        const roofs = document.getElementById('isoSectorRoofs')?.checked ? 1 : 0;
        renderSectorAt(targetX, targetY, size, roofs);
      }
    });

    // Cancel loading button
    cancelBtn?.addEventListener('click', () => {
      cancelProgress();
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
      const x = parseInt(document.getElementById('isoSectorX')?.value || '1200', 10);
      const y = parseInt(document.getElementById('isoSectorY')?.value || '1050', 10);
      const size = parseInt(document.getElementById('isoSectorSize')?.value || '60', 10);
      const roofs = document.getElementById('isoSectorRoofs')?.checked ? 1 : 0;
      renderSectorAt(x, y, size, roofs);
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
      else if (e.key === 'h' || e.key === 'H') { loadHdHereBtn?.click(); e.preventDefault(); }
      else if (e.key === 'ArrowLeft') { panX += 50; applyTransform(); e.preventDefault(); }
      else if (e.key === 'ArrowRight') { panX -= 50; applyTransform(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { panY += 50; applyTransform(); e.preventDefault(); }
      else if (e.key === 'ArrowDown') { panY -= 50; applyTransform(); e.preventDefault(); }
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
    const newScale = Math.max(0.08, Math.min(8.0, scale * factor));
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
    const newScale = Math.max(0.08, Math.min(8.0, targetScale));
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

  function loadImage(src, title, sub, estimatedSecs = 3) {
    startProgress(title, sub, estimatedSecs);

    const loader = new Image();
    activeImageLoader = loader;

    loader.onload = () => {
      if (isCancelled || activeImageLoader !== loader) return;
      img.src = src;
      activeImageLoader = null;
      finishProgress();
      fitToScreen();
    };

    loader.onerror = () => {
      if (isCancelled || activeImageLoader !== loader) return;
      activeImageLoader = null;
      finishProgress(true);
      if (window.fx?.toast) {
        window.fx.toast('bad', 'Error', 'Could not load isometric view.', 5000);
      }
    };

    loader.src = src;

    // In case image is already in browser cache
    if (loader.complete && loader.naturalWidth > 0) {
      img.src = src;
      activeImageLoader = null;
      finishProgress();
      fitToScreen();
    }
  }

  function setMode(mode) {
    currentMode = mode;
    el.querySelectorAll('[data-iso-mode]').forEach(b => {
      b.classList.toggle('is-on', b.dataset.isoMode === mode);
    });

    const isSector = mode === 'sector';
    if (sectorBar) {
      sectorBar.hidden = !isSector;
      sectorBar.style.display = isSector ? 'flex' : 'none';
    }
    if (loadHdHereBtn) {
      loadHdHereBtn.hidden = isSector;
      loadHdHereBtn.style.display = isSector ? 'none' : 'inline-flex';
    }

    if (mode === 'sector') {
      const x = parseInt(document.getElementById('isoSectorX')?.value || '1200', 10);
      const y = parseInt(document.getElementById('isoSectorY')?.value || '1050', 10);
      const size = parseInt(document.getElementById('isoSectorSize')?.value || '60', 10);
      const roofs = document.getElementById('isoSectorRoofs')?.checked ? 1 : 0;
      renderSectorAt(x, y, size, roofs);
      return;
    }

    if (!mapInfo || !mapInfo.pictures) return;

    let src = mapInfo.pictures[mode];
    const modeLabels = {
      town: 'Town overview',
      close: 'Town center',
      inside: 'Interiors (All)',
    };
    const title = `Loading ${modeLabels[mode] || mode}…`;

    if (src) {
      loadImage(src, title, 'Reading generated town picture', 2);
    } else {
      const roofs = mode !== 'inside';
      const fallbackUrl = `/api/iso-render/${encodeURIComponent(activeMap)}?roofs=${roofs ? 1 : 0}&scale=0.5`;
      loadImage(fallbackUrl, title, 'Rendering preview on demand…', 5);
    }
  }

  function renderSectorAt(x, y, size, roofs) {
    if (!activeMap) return;

    // Update inputs
    const inX = document.getElementById('isoSectorX');
    const inY = document.getElementById('isoSectorY');
    const inRoofs = document.getElementById('isoSectorRoofs');
    if (inX) inX.value = x;
    if (inY) inY.value = y;
    if (inRoofs) inRoofs.checked = !!roofs;

    // Switch mode to sector
    currentMode = 'sector';
    el.querySelectorAll('[data-iso-mode]').forEach(b => {
      b.classList.toggle('is-on', b.dataset.isoMode === 'sector');
    });
    if (sectorBar) {
      sectorBar.hidden = false;
      sectorBar.style.display = 'flex';
    }
    if (loadHdHereBtn) {
      loadHdHereBtn.hidden = true;
      loadHdHereBtn.style.display = 'none';
    }

    const url = `/api/iso-render/${encodeURIComponent(activeMap)}?box=${x},${y},${size},${size}&scale=1.0&roofs=${roofs}&t=${Date.now()}`;
    const roofText = roofs ? 'with roofs' : 'furnished interiors';
    loadImage(url, `Rendering HD sector ${x},${y} (${size}×${size} tiles, ${roofText})…`,
              'Compositing full 1:1 crystal-clear in-game sprites', 4);
  }

  async function showIsoView(name) {
    ensureElements();
    if (!name) return;

    if (activeMap === name && mapInfo) {
      fitToScreen();
      return;
    }

    activeMap = name;
    startProgress('Loading map data…', 'Fetching compiled isometric details', 2);

    try {
      const res = await fetch(`/api/iso-info/${encodeURIComponent(name)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      mapInfo = await res.json();
    } catch (err) {
      finishProgress(true);
      if (window.fx?.toast) {
        window.fx.toast('bad', 'Error', `Could not load isometric info: ${err.message}`, 5000);
      }
      return;
    }

    if (!mapInfo.compiled) {
      finishProgress(true);
      if (emptyBox) {
        emptyBox.hidden = false;
        emptyBox.style.display = 'flex';
      }
      if (stage) {
        stage.hidden = true;
        stage.style.display = 'none';
      }
      if (titleEl) titleEl.textContent = `${name} · Uncompiled`;
      return;
    }

    if (emptyBox) {
      emptyBox.hidden = true;
      emptyBox.style.display = 'none';
    }
    if (stage) {
      stage.hidden = false;
      stage.style.display = 'block';
    }

    // Set map title details
    const bldCount = mapInfo.building_count ? ` · ${mapInfo.building_count} buildings` : '';
    const dims = mapInfo.width_tiles && mapInfo.height_tiles
      ? ` · ${mapInfo.width_tiles} × ${mapInfo.height_tiles} tiles (${mapInfo.cells_x}×${mapInfo.cells_y} cells)`
      : '';
    if (titleEl) titleEl.textContent = `${name}${dims}${bldCount}`;

    // Populate cell dropdown if available
    if (cellSelect && Array.isArray(mapInfo.cells)) {
      cellSelect.innerHTML = '<option value="">(Select cell)</option>' +
        mapInfo.cells.map(([cx, cy]) => `<option value="${cx}_${cy}">Cell ${cx}, ${cy}</option>`).join('');
    }

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
      if (mapInfo.pictures?.inside) initialMode = 'inside';
      else if (mapInfo.pictures?.close) initialMode = 'close';
      else initialMode = 'sector';
    }

    setMode(initialMode);
  }

  function closeIsoView() {
    activeMap = null;
    mapInfo = null;
    finishProgress(true);
  }

  window.showIsoView = showIsoView;
  window.closeIsoView = closeIsoView;
})();
