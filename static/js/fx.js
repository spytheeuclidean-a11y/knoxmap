// KnoxMap - the small bits of UI glue app.js calls into.
//
// It never talks to the server or decides anything: app.js calls `fx` when an
// area is chosen, a step starts or finishes, and this shows it. If this file
// failed to load, the app would still work.

const fx = (() => {
  const $ = (sel, root = document) => root.querySelector(sel);

  // Steps used to light up in a header bar; the panels now say it themselves.
  function step(key, state) {
    if (key === 'area' && state === 'done') $('#map-hint')?.remove();
  }
  function resetFrom() {}

  // ---- messages -----------------------------------------------------------
  function toast(kind, title, msg, ms = 5000) {
    const box = $('#toasts');
    if (!box) return;
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.innerHTML = '<b></b> <span></span>';
    el.querySelector('b').textContent = title;
    el.querySelector('span').textContent = msg || '';
    box.appendChild(el);
    const kill = () => el.remove();
    el.addEventListener('click', kill);
    setTimeout(kill, ms);
  }

  // ---- numbers ------------------------------------------------------------
  function countUp(root = document) {
    root.querySelectorAll('[data-count]').forEach(el => {
      const value = parseFloat(el.dataset.count);
      const decimals = parseInt(el.dataset.decimals || '0', 10);
      el.textContent = isFinite(value) ? value.toLocaleString(undefined, {
        minimumFractionDigits: decimals, maximumFractionDigits: decimals,
      }) : '';
    });
  }

  function tile(value, unit, label, decimals = 0) {
    return `<div class="tile"><div class="v"><span data-count="${value}"
      data-decimals="${decimals}">0</span>${unit ? ` <small>${unit}</small>` : ''}</div>
      <div class="k">${label}</div></div>`;
  }

  // ---- terrain progress ---------------------------------------------------
  let clockTimer = null;
  let started = 0;

  const overlay = {
    show() {
      const el = $('#gen-overlay');
      el.hidden = false;
      $('.gen-kicker', el).textContent = 'Generating terrain';
      $('#gen-stage').textContent = 'Contacting OpenStreetMap…';
      $('#gen-detail').textContent = '';
      $('#gen-bar').style.width = '4%';
      started = Date.now();
      clearInterval(clockTimer);
      clockTimer = setInterval(() => {
        const s = Math.floor((Date.now() - started) / 1000);
        $('#gen-clock').textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
      }, 500);
    },
    update(p) {
      if (p.stage === 'osm') {
        const total = p.total || 1;
        const done = p.done || 0;
        $('#gen-stage').textContent = 'Downloading map data';
        $('#gen-detail').textContent = total > 1 ? `Part ${done + 1} of ${total}` : '';
        $('#gen-bar').style.width = `${Math.max(6, Math.round(8 + 62 * done / total))}%`;
      } else if (p.stage === 'render') {
        $('#gen-stage').textContent = 'Drawing the terrain';
        $('#gen-detail').textContent = `${(p.features || 0).toLocaleString()} features`;
        $('#gen-bar').style.width = '82%';
      }
    },
    done(summary) {
      $('.gen-kicker').textContent = 'Done';
      $('#gen-stage').textContent = summary || '';
      $('#gen-detail').textContent = '';
      $('#gen-bar').style.width = '100%';
      this.hide(600);
    },
    fail(message) {
      $('.gen-kicker').textContent = 'Failed';
      $('#gen-stage').textContent = message.length > 160 ? message.slice(0, 157) + '…' : message;
      $('#gen-detail').textContent = '';
      this.hide(2500);
    },
    hide(delay = 0) {
      setTimeout(() => {
        $('#gen-overlay').hidden = true;
        clearInterval(clockTimer);
      }, delay);
    },
  };

  // ---- the build / compile / install steps --------------------------------
  const NOTE_STEP = {
    buildingsNote: 'buildings', compileNote: 'compile',
    worldedNote: 'compile', installNote: 'install',
  };
  const BUSY = /generating|starting|installing|compiling|waiting|opened/i;

  function card(key, state) {
    const el = $(`.pipe-card[data-step="${key}"]`);
    if (!el) return;
    el.classList.remove('is-running', 'is-done', 'is-error', 'is-ready');
    if (state) el.classList.add(`is-${state}`);
  }

  function noted(id, text, cls) {
    const key = NOTE_STEP[id];
    if (!key) return;
    if (cls === 'ok') card(key, 'done');
    else if (cls === 'bad') card(key, 'error');
    else if (BUSY.test(text)) card(key, 'running');
    else if (/^ready/i.test(text)) card(key, 'ready');
  }

  function progress(key, pct) {
    const bar = key === 'compile' ? $('#compileBar') : null;
    if (!bar) return;
    bar.parentElement.classList.toggle('is-indeterminate', !(pct > 0));
    if (pct > 0) bar.style.width = `${Math.min(100, pct)}%`;
  }

  // ---- basemaps -------------------------------------------------------------
  function mapExtras() {
    if (typeof map === 'undefined') return;
    const attribution = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
    const layers = {
      streets: L.tileLayer('/tiles/{z}/{x}/{y}.png', { maxZoom: 19, attribution }),
      // The same tiles, darkened in CSS.
      dark: L.tileLayer('/tiles/{z}/{x}/{y}.png', { maxZoom: 19, className: 'tiles-dark', attribution }),
    };
    const existing = [];
    map.eachLayer(l => { if (l instanceof L.TileLayer) existing.push(l); });
    existing.forEach(l => map.removeLayer(l));
    let saved = 'dark';
    try { saved = localStorage.getItem('knoxmap.base') || 'dark'; } catch (_) {}
    if (!layers[saved]) saved = 'dark';
    layers[saved].addTo(map);
    document.querySelectorAll('#basemaps button').forEach(btn => {
      btn.classList.toggle('is-on', btn.dataset.base === saved);
      btn.addEventListener('click', () => {
        Object.values(layers).forEach(l => map.removeLayer(l));
        layers[btn.dataset.base].addTo(map);
        document.querySelectorAll('#basemaps button')
          .forEach(b => b.classList.toggle('is-on', b === btn));
        try { localStorage.setItem('knoxmap.base', btn.dataset.base); } catch (_) {}
      });
    });
    map.on(L.Draw.Event.CREATED, () => $('#map-hint')?.remove());
  }

  // ---- kind of place ----------------------------------------------------------
  function presetCards() {
    const select = $('#preset');
    document.querySelectorAll('.preset-card').forEach(card => {
      card.addEventListener('click', () => {
        document.querySelectorAll('.preset-card').forEach(c => {
          const on = c === card;
          c.classList.toggle('is-on', on);
          c.setAttribute('aria-checked', on ? 'true' : 'false');
        });
        select.value = card.dataset.preset;
        // app.js listens on the real select; it stays the single source of truth.
        select.dispatchEvent(new Event('change'));
      });
    });
  }

  // ---- settings form ------------------------------------------------------------
  function paintRange(input) {
    const v = parseFloat(input.value);
    const out = input.closest('.setting')?.querySelector('.setting-val');
    if (out) out.textContent = input.step && parseFloat(input.step) < 1 ? v.toFixed(2) : String(v);
  }

  function wireSettings(root) {
    root.querySelectorAll('input[type="range"]').forEach(r => {
      paintRange(r);
      r.addEventListener('input', () => paintRange(r));
    });
    root.querySelectorAll('.dice').forEach(d => {
      d.addEventListener('click', () => {
        d.parentElement.querySelector('input').value = Math.floor(Math.random() * 999999) + 1;
      });
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    presetCards();
    $('.hint-close')?.addEventListener('click', () => $('#map-hint')?.remove());
  });
  window.addEventListener('load', mapExtras);

  return { step, resetFrom, toast, countUp, tile, overlay, noted, card, progress,
           confetti() {}, wireSettings, paintRange };
})();
