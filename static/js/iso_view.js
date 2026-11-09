// Isometric 2.5D game view for KnoxMap.
// Displays the dimetric in-game rendering of Project Zomboid maps with pan,
// zoom, interiors/roofs toggling, interactive box selection, and on-demand 1:1 HD sector rendering.

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
  let drawBoxBtn = null;

  // Interactive selection marquee & popover
  let selectionLayer = null;
  let selectionMarquee = null;
  let selectionBadge = null;
  let selectionPopover = null;
  let popoverDim = null;
  let popoverCoords = null;

  let isDrawModeActive = false;
  let isBoxSelecting = false;
  let boxStartX = 0;
  let boxStartY = 0;
  let currentSelection = null; // { x, y, w, h }
  let currentSector = null;    // { x, y, w, h, roofs }

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

          <!-- Draw area selection tool -->
          <button type="button" class="btn btn-small btn-draw" id="isoDrawBoxBtn"
                  title="Draw an area rectangle to render in 1:1 HD with roofs or furnished interiors (Shift + Drag)">🔲 Draw area</button>

          <!-- Quick Load HD of current view -->
          <button type="button" class="btn btn-small btn-hd" id="isoLoadHdHere"
                  title="Render this current view at 100% crystal-clear in-game resolution">🔍 Load HD here</button>

          <!-- Sector HD toolbar controls -->
          <div class="iso-bar-sector" id="isoSectorBar" hidden style="display: none;">
            <button type="button" class="btn btn-small" id="isoBackOverview"
                    title="Back to full town overview">◀ Full town</button>

            <!-- Roofs / Interiors segmented toggle for current sector -->
            <div class="iso-sector-toggle" role="group" aria-label="Sector display mode">
              <button type="button" class="btn btn-small is-on" id="isoSectorRoofsBtn"
                      title="Render this sector with roofs">🏠 Roofs</button>
              <button type="button" class="btn btn-small" id="isoSectorInteriorsBtn"
                      title="Render this sector with furnished building interiors">🪑 Interiors</button>
            </div>

            <label>Cell:
              <select id="isoCellSelect" class="iso-cell-select" title="Jump directly to any compiled cell">
                <option value="">(Select cell)</option>
              </select>
            </label>
            <label>X: <input type="number" id="isoSectorX" min="0" step="10" value="1200"></label>
            <label>Y: <input type="number" id="isoSectorY" min="0" step="10" value="1050"></label>
            <label>W: <input type="number" id="isoSectorW" min="10" max="200" step="10" value="60"></label>
            <label>H: <input type="number" id="isoSectorH" min="10" max="200" step="10" value="60"></label>
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

          <!-- Interactive Marquee Selection Layer & Floating Action Popover -->
          <div class="iso-selection-layer" id="isoSelectionLayer" hidden style="display: none;">
            <div class="iso-selection-marquee" id="isoSelectionMarquee" style="display: none;">
              <span class="iso-selection-badge" id="isoSelectionBadge">60 × 60</span>
            </div>
            <div class="iso-selection-popover" id="isoSelectionPopover" hidden style="display: none;">
              <div class="iso-popover-head">
                <span class="iso-popover-title">🔲 Selected area</span>
                <button type="button" class="iso-popover-close" id="isoPopoverClose" title="Close (Esc)">✕</button>
              </div>
              <div class="iso-popover-body">
                <div class="iso-popover-dim" id="isoPopoverDim">60 × 60 tiles</div>
                <div class="iso-popover-coords" id="isoPopoverCoords">X: 1200 · Y: 1050</div>
              </div>
              <div class="iso-popover-actions">
                <button type="button" class="btn btn-small btn-primary" id="isoPopoverRoofs"
                        title="Render selected area with roofs at native 1:1 HD">🏠 With roofs</button>
                <button type="button" class="btn btn-small btn-interiors" id="isoPopoverInteriors"
                        title="Render selected area with furnished interiors at native 1:1 HD">🪑 Furnished interiors</button>
              </div>
            </div>
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
            <span class="iso-tip">Drag to pan · Scroll to zoom · Shift+drag or [Draw area] to select HD sector · Double-click for HD</span>
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
    drawBoxBtn = document.getElementById('isoDrawBoxBtn');

    selectionLayer = document.getElementById('isoSelectionLayer');
    selectionMarquee = document.getElementById('isoSelectionMarquee');
    selectionBadge = document.getElementById('isoSelectionBadge');
    selectionPopover = document.getElementById('isoSelectionPopover');
    popoverDim = document.getElementById('isoPopoverDim');
    popoverCoords = document.getElementById('isoPopoverCoords');

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
    const durationMs = Math.max(1000, estimatedSecs * 1000);

    progressTimer = setInterval(() => {
      const elapsed = Date.now() - progressStartTime;
      const sec = Math.floor(elapsed / 1000);
      const min = Math.floor(sec / 60);
      const remSec = String(sec % 60).padStart(2, '0');
      if (progressClock) progressClock.textContent = `⏱️ ${min}:${remSec}`;

      let p = 0;
      if (elapsed < durationMs * 0.4) {
        p = Math.round((elapsed / (durationMs * 0.4)) * 50);
      } else if (elapsed < durationMs) {
        const t = (elapsed - durationMs * 0.4) / (durationMs * 0.6);
        p = Math.round(50 + t * 40);
      } else {
        const extra = (elapsed - durationMs) / 1000;
        p = Math.min(98, Math.round(90 + (1 - Math.exp(-extra / 4)) * 8));
      }

      if (progressBar) progressBar.style.width = `${p}%`;
      if (progressPercent) progressPercent.textContent = `${p}%`;

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

  // Determine current image bounding box in tile coordinates
  function getCurrentImageBox() {
    const W = mapInfo?.width_tiles || 2400;
    const H = mapInfo?.height_tiles || 2100;
    if (currentMode === 'sector' && currentSector) {
      return { x: currentSector.x, y: currentSector.y, w: currentSector.w, h: currentSector.h };
    }
    if (currentMode === 'close') {
      const close = Math.min(320, Math.max(120, Math.floor(Math.min(W, H) / 3)));
      return {
        x: Math.max(0, Math.floor(W / 2 - close / 2)),
        y: Math.max(0, Math.floor(H / 2 - close / 2)),
        w: close,
        h: close,
      };
    }
    // 'town' and 'inside' (inside_town.png)
    return { x: 0, y: 0, w: W, h: H };
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

    const box = getCurrentImageBox();
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;

    const cx = iw / 2;
    const cy = ih / 2;
    const half = iw / (box.w + box.h);
    const quarter = half / 2;

    const dx = imgX - cx;
    const dy = imgY - cy;

    const t_dx = (dx / half + dy / quarter) / 2;
    const t_dy = (dy / quarter - dx / half) / 2;

    const mapW = mapInfo.width_tiles || 2400;
    const mapH = mapInfo.height_tiles || 2100;
    const tileX = Math.max(0, Math.min(mapW, Math.round(box.x + box.w / 2 + t_dx)));
    const tileY = Math.max(0, Math.min(mapH, Math.round(box.y + box.h / 2 + t_dy)));

    return { x: tileX, y: tileY };
  }

  function getViewportCenterTile() {
    const viewport = document.getElementById('isoViewport');
    if (!viewport) return { x: 1000, y: 1000 };
    const rect = viewport.getBoundingClientRect();
    return screenPointToTile(rect.left + rect.width / 2, rect.top + rect.height / 2);
  }

  // Box selection marquee logic
  function startBoxSelect(clientX, clientY) {
    const viewport = document.getElementById('isoViewport');
    if (!viewport || !selectionLayer || !selectionMarquee) return;

    isBoxSelecting = true;
    boxStartX = clientX;
    boxStartY = clientY;
    currentSelection = null;

    if (selectionPopover) {
      selectionPopover.hidden = true;
      selectionPopover.style.display = 'none';
    }

    selectionLayer.hidden = false;
    selectionLayer.style.display = 'block';

    const rect = viewport.getBoundingClientRect();
    const vx = clientX - rect.left;
    const vy = clientY - rect.top;

    selectionMarquee.style.display = 'block';
    selectionMarquee.style.left = `${vx}px`;
    selectionMarquee.style.top = `${vy}px`;
    selectionMarquee.style.width = '0px';
    selectionMarquee.style.height = '0px';
  }

  function updateBoxSelect(clientX, clientY) {
    if (!isBoxSelecting) return;
    const viewport = document.getElementById('isoViewport');
    if (!viewport || !selectionMarquee) return;

    const rect = viewport.getBoundingClientRect();
    const minScreenX = Math.min(boxStartX, clientX);
    const maxScreenX = Math.max(boxStartX, clientX);
    const minScreenY = Math.min(boxStartY, clientY);
    const maxScreenY = Math.max(boxStartY, clientY);

    const vx = minScreenX - rect.left;
    const vy = minScreenY - rect.top;
    const vw = maxScreenX - minScreenX;
    const vh = maxScreenY - minScreenY;

    selectionMarquee.style.left = `${vx}px`;
    selectionMarquee.style.top = `${vy}px`;
    selectionMarquee.style.width = `${vw}px`;
    selectionMarquee.style.height = `${vh}px`;

    // Convert 4 screen corners to tile coordinates
    const p1 = screenPointToTile(minScreenX, minScreenY);
    const p2 = screenPointToTile(maxScreenX, minScreenY);
    const p3 = screenPointToTile(minScreenX, maxScreenY);
    const p4 = screenPointToTile(maxScreenX, maxScreenY);

    const mapW = mapInfo?.width_tiles || 2400;
    const mapH = mapInfo?.height_tiles || 2100;

    const minTx = Math.max(0, Math.min(p1.x, p2.x, p3.x, p4.x));
    const maxTx = Math.min(mapW, Math.max(p1.x, p2.x, p3.x, p4.x));
    const minTy = Math.max(0, Math.min(p1.y, p2.y, p3.y, p4.y));
    const maxTy = Math.min(mapH, Math.max(p1.y, p2.y, p3.y, p4.y));

    const selW = Math.max(10, Math.min(200, maxTx - minTx));
    const selH = Math.max(10, Math.min(200, maxTy - minTy));

    currentSelection = { x: minTx, y: minTy, w: selW, h: selH };

    if (selectionBadge) {
      selectionBadge.textContent = `${selW} × ${selH} tiles`;
    }
  }

  function finishBoxSelect(clientX, clientY) {
    if (!isBoxSelecting) return;
    isBoxSelecting = false;

    const viewport = document.getElementById('isoViewport');
    const dist = Math.hypot(clientX - boxStartX, clientY - boxStartY);
    if (dist < 15 || !currentSelection) {
      clearBoxSelection();
      return;
    }

    // Position action popover next to marquee
    if (viewport && selectionPopover) {
      const rect = viewport.getBoundingClientRect();
      const minScreenX = Math.min(boxStartX, clientX);
      const maxScreenX = Math.max(boxStartX, clientX);
      const minScreenY = Math.min(boxStartY, clientY);
      const maxScreenY = Math.max(boxStartY, clientY);

      const vx = minScreenX - rect.left;
      const vy = minScreenY - rect.top;
      const vw = maxScreenX - minScreenX;
      const vh = maxScreenY - minScreenY;

      const popWidth = 270;
      const popLeft = Math.max(12, Math.min(rect.width - popWidth - 16, vx + (vw - popWidth) / 2));
      const popTop = (vy > 140) ? (vy - 110) : (vy + vh + 12);

      selectionPopover.style.left = `${Math.round(popLeft)}px`;
      selectionPopover.style.top = `${Math.round(popTop)}px`;

      if (popoverDim) {
        popoverDim.textContent = `${currentSelection.w} × ${currentSelection.h} tiles (${(currentSelection.w * currentSelection.h).toLocaleString()} tiles)`;
      }
      if (popoverCoords) {
        popoverCoords.textContent = `X: ${currentSelection.x} · Y: ${currentSelection.y}`;
      }

      selectionPopover.hidden = false;
      selectionPopover.style.display = 'flex';
    }

    // Update sector toolbar inputs
    updateSectorInputs(currentSelection.x, currentSelection.y, currentSelection.w, currentSelection.h);

    if (isDrawModeActive) {
      toggleDrawMode(false, true);
    }
  }

  function clearBoxSelection() {
    isBoxSelecting = false;
    currentSelection = null;
    if (selectionMarquee) selectionMarquee.style.display = 'none';
    if (selectionPopover) {
      selectionPopover.hidden = true;
      selectionPopover.style.display = 'none';
    }
    if (selectionLayer) {
      selectionLayer.hidden = true;
      selectionLayer.style.display = 'none';
    }
  }

  function toggleDrawMode(forceState, keepSelection = false) {
    isDrawModeActive = typeof forceState === 'boolean' ? forceState : !isDrawModeActive;
    const viewport = document.getElementById('isoViewport');
    if (drawBoxBtn) {
      drawBoxBtn.classList.toggle('is-on', isDrawModeActive);
      drawBoxBtn.textContent = isDrawModeActive ? '✕ Cancel draw' : '🔲 Draw area';
    }
    if (viewport) {
      viewport.classList.toggle('is-drawing-tool', isDrawModeActive);
    }
    if (!isDrawModeActive && !keepSelection) {
      clearBoxSelection();
    }
  }

  function updateSectorInputs(x, y, w, h) {
    const inX = document.getElementById('isoSectorX');
    const inY = document.getElementById('isoSectorY');
    const inW = document.getElementById('isoSectorW');
    const inH = document.getElementById('isoSectorH');
    if (inX) inX.value = x;
    if (inY) inY.value = y;
    if (inW) inW.value = w;
    if (inH) inH.value = h;
  }

  function updateSectorToggle(roofs) {
    const btnRoofs = document.getElementById('isoSectorRoofsBtn');
    const btnInteriors = document.getElementById('isoSectorInteriorsBtn');
    if (btnRoofs) btnRoofs.classList.toggle('is-on', roofs === 1);
    if (btnInteriors) btnInteriors.classList.toggle('is-on', roofs === 0);
  }

  function bindEvents() {
    const viewport = document.getElementById('isoViewport');

    // Pan with mouse or start drawing box if draw tool active / Shift held
    viewport.addEventListener('mousedown', e => {
      if (e.target.closest('button, input, select, label, .iso-empty, .iso-overlay, .iso-selection-popover')) return;

      if (isDrawModeActive || e.shiftKey) {
        startBoxSelect(e.clientX, e.clientY);
        return;
      }

      isDragging = true;
      startX = e.clientX - panX;
      startY = e.clientY - panY;
      viewport.classList.add('is-dragging');
    });

    window.addEventListener('mousemove', e => {
      if (isBoxSelecting) {
        updateBoxSelect(e.clientX, e.clientY);
        return;
      }
      if (!isDragging) return;
      panX = e.clientX - startX;
      panY = e.clientY - startY;
      applyTransform();
    });

    window.addEventListener('mouseup', e => {
      if (isBoxSelecting) {
        finishBoxSelect(e.clientX, e.clientY);
        return;
      }
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
      if (e.target.closest('button, input, select, label, .iso-overlay, .iso-selection-popover')) return;
      const { x, y } = screenPointToTile(e.clientX, e.clientY);
      const w = parseInt(document.getElementById('isoSectorW')?.value || '60', 10);
      const h = parseInt(document.getElementById('isoSectorH')?.value || '60', 10);
      const roofs = currentMode === 'inside' ? 0 : (currentSector?.roofs ?? 1);
      const startX = Math.max(0, x - Math.round(w / 2));
      const startY = Math.max(0, y - Math.round(h / 2));
      renderSectorBox(startX, startY, w, h, roofs);
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
    document.getElementById('isoZoomIn')?.addEventListener('click', () => zoomBy(1.25));
    document.getElementById('isoZoomOut')?.addEventListener('click', () => zoomBy(1 / 1.25));
    document.getElementById('isoZoomFit')?.addEventListener('click', () => fitToScreen());
    document.getElementById('isoZoom100')?.addEventListener('click', () => zoomTo(1.0));

    // Draw box selection button toggle
    drawBoxBtn?.addEventListener('click', () => toggleDrawMode());

    // Popover actions
    document.getElementById('isoPopoverClose')?.addEventListener('click', () => clearBoxSelection());
    document.getElementById('isoPopoverRoofs')?.addEventListener('click', () => {
      if (!currentSelection) return;
      renderSectorBox(currentSelection.x, currentSelection.y, currentSelection.w, currentSelection.h, 1);
    });
    document.getElementById('isoPopoverInteriors')?.addEventListener('click', () => {
      if (!currentSelection) return;
      renderSectorBox(currentSelection.x, currentSelection.y, currentSelection.w, currentSelection.h, 0);
    });

    // Sector HD toggle buttons: Roofs vs Interiors
    document.getElementById('isoSectorRoofsBtn')?.addEventListener('click', () => {
      if (!currentSector) return;
      renderSectorBox(currentSector.x, currentSector.y, currentSector.w, currentSector.h, 1);
    });
    document.getElementById('isoSectorInteriorsBtn')?.addEventListener('click', () => {
      if (!currentSector) return;
      renderSectorBox(currentSector.x, currentSector.y, currentSector.w, currentSector.h, 0);
    });

    // Load HD Here button
    loadHdHereBtn?.addEventListener('click', () => {
      const { x, y } = getViewportCenterTile();
      const w = parseInt(document.getElementById('isoSectorW')?.value || '60', 10);
      const h = parseInt(document.getElementById('isoSectorH')?.value || '60', 10);
      const roofs = currentMode === 'inside' ? 0 : (currentSector?.roofs ?? 1);
      const startX = Math.max(0, x - Math.round(w / 2));
      const startY = Math.max(0, y - Math.round(h / 2));
      renderSectorBox(startX, startY, w, h, roofs);
    });

    // Back to full town overview button
    backOverviewBtn?.addEventListener('click', () => setMode('town'));

    // Jump to cell selection
    cellSelect?.addEventListener('change', e => {
      const val = e.target.value;
      if (!val) return;
      const parts = val.split('_').map(Number);
      if (parts.length === 2 && mapInfo?.cells?.length) {
        const minCx = Math.min(...mapInfo.cells.map(c => c[0]));
        const minCy = Math.min(...mapInfo.cells.map(c => c[1]));
        const targetX = (parts[0] - minCx) * 300 + 150;
        const targetY = (parts[1] - minCy) * 300 + 150;

        const w = parseInt(document.getElementById('isoSectorW')?.value || '60', 10);
        const h = parseInt(document.getElementById('isoSectorH')?.value || '60', 10);
        const startX = Math.max(0, targetX - Math.round(w / 2));
        const startY = Math.max(0, targetY - Math.round(h / 2));
        const roofs = currentSector?.roofs ?? 1;
        renderSectorBox(startX, startY, w, h, roofs);
      }
    });

    // Cancel loading button
    cancelBtn?.addEventListener('click', () => cancelProgress());

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
      btn.addEventListener('click', () => setMode(btn.dataset.isoMode));
    });

    // Sector HD Render button
    document.getElementById('isoRenderBtn')?.addEventListener('click', () => {
      const x = parseInt(document.getElementById('isoSectorX')?.value || '1200', 10);
      const y = parseInt(document.getElementById('isoSectorY')?.value || '1050', 10);
      const w = parseInt(document.getElementById('isoSectorW')?.value || '60', 10);
      const h = parseInt(document.getElementById('isoSectorH')?.value || '60', 10);
      const roofs = currentSector ? currentSector.roofs : 1;
      renderSectorBox(x, y, w, h, roofs);
    });

    // Go to Compile button. The pipeline enables Compile only once the map and
    // its buildings are done; clicking a disabled button does nothing at all,
    // which reads as the button being broken.
    document.getElementById('isoCompileNow')?.addEventListener('click', () => {
      const compileBtn = document.getElementById('compileBtn');
      const chip = document.querySelector('[data-chip="compile"]');
      if (compileBtn && compileBtn.disabled) {
        if (window.fx?.toast) {
          window.fx.toast('bad', 'Compile is not ready',
            "Generate the map and its buildings first — Compile turns them into the game's files.", 6000);
        }
        if (chip) chip.click();
        return;
      }
      if (compileBtn) compileBtn.click();
      if (chip) chip.click();
      // Ask again next time this panel opens rather than trusting an answer
      // from before the compile started.
      mapInfo = null;
    });

    // Keyboard navigation & shortcuts
    window.addEventListener('keydown', e => {
      if (e.target.closest('input, textarea, select')) return;
      if (e.key === 'Shift') {
        viewport.classList.add('is-drawing-tool');
      }
      if (e.key === 'Escape') {
        clearBoxSelection();
        if (isDrawModeActive) toggleDrawMode(false);
      }
      if (e.key === 'b' || e.key === 'B' || e.key === 'd' || e.key === 'D') {
        toggleDrawMode();
      }
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

    window.addEventListener('keyup', e => {
      if (e.key === 'Shift' && !isDrawModeActive) {
        viewport.classList.remove('is-drawing-tool');
      }
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

    if (loader.complete && loader.naturalWidth > 0) {
      img.src = src;
      activeImageLoader = null;
      finishProgress();
      fitToScreen();
    }
  }

  function setMode(mode) {
    currentMode = mode;
    clearBoxSelection();

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
      const w = parseInt(document.getElementById('isoSectorW')?.value || '60', 10);
      const h = parseInt(document.getElementById('isoSectorH')?.value || '60', 10);
      const roofs = currentSector ? currentSector.roofs : 1;
      renderSectorBox(x, y, w, h, roofs);
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

  function renderSectorBox(x, y, w, h, roofs = 1) {
    if (!activeMap) return;

    clearBoxSelection();
    currentSector = { x, y, w, h, roofs: roofs ? 1 : 0 };

    updateSectorInputs(x, y, w, h);
    updateSectorToggle(roofs ? 1 : 0);

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

    const url = `/api/iso-render/${encodeURIComponent(activeMap)}?box=${x},${y},${w},${h}&scale=1.0&roofs=${roofs ? 1 : 0}&t=${Date.now()}`;
    const roofText = roofs ? 'with roofs' : 'furnished interiors';
    loadImage(url, `Rendering HD sector ${x},${y} (${w}×${h} tiles, ${roofText})…`,
              roofs ? 'Compositing full 1:1 crystal-clear in-game sprites' : 'Compositing furnished rooms, walls and partitions',
              4);
  }

  async function showIsoView(name) {
    ensureElements();
    if (!name) return;

    // Re-ask when the last answer was "not compiled": compiling happens in the
    // pipeline behind this panel, and coming back to it must not keep saying
    // the map has no compiled cells.
    if (activeMap === name && mapInfo && mapInfo.compiled) {
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
    updateSectorInputs(midX, midY, 60, 60);

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
    currentSector = null;
    clearBoxSelection();
    if (isDrawModeActive) toggleDrawMode(false);
    finishProgress(true);
  }

  window.showIsoView = showIsoView;
  window.closeIsoView = closeIsoView;
})();
