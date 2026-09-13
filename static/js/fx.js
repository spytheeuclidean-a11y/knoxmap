// Knoxify — presentation layer.
//
// Everything here is decoration over app.js: it never talks to the server and
// never decides anything. app.js calls into `fx` at the moments that matter
// (area chosen, generation started, a step finished) and this makes those
// moments visible. If this file failed to load, the app would still work.

const fx = (() => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $ = (sel, root = document) => root.querySelector(sel);

  // ---- header stepper -----------------------------------------------------
  const ORDER = ['area', 'style', 'terrain', 'buildings', 'compile', 'install'];

  function step(key, state) {
    if (key === 'area') {
      // Picking a search result sets the area without a draw event, so the
      // hint and the pulsing tool are retired from here instead.
      const tool = $('.leaflet-draw-draw-rectangle');
      if (tool) tool.classList.toggle('is-beckoning', state !== 'done');
      if (state === 'done') $('#map-hint')?.remove();
    }
    const li = $(`#stepper li[data-step="${key}"]`);
    if (!li) return;
    li.classList.remove('is-active', 'is-running', 'is-done', 'is-error');
    if (state) li.classList.add(`is-${state}`);
    // The first step not yet done is the one to look at next.
    if (state === 'done') {
      const next = ORDER.slice(ORDER.indexOf(key) + 1)
        .map(k => $(`#stepper li[data-step="${k}"]`))
        .find(el => el && !el.classList.contains('is-done'));
      if (next && !next.className) next.classList.add('is-active');
    }
  }

  function resetFrom(key) {
    ORDER.slice(ORDER.indexOf(key)).forEach((k, i) => {
      const li = $(`#stepper li[data-step="${k}"]`);
      if (li) li.className = i === 0 ? 'is-active' : '';
    });
  }

  // ---- toasts -------------------------------------------------------------
  function toast(kind, title, msg, ms = 5200) {
    const box = $('#toasts');
    if (!box) return;
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    const icon = { ok: '✓', bad: '!', info: 'i' }[kind] || 'i';
    el.innerHTML = `<span class="t-ico">${icon}</span>
      <div><div class="t-title"></div><div class="t-msg"></div></div>`;
    el.querySelector('.t-title').textContent = title;
    el.querySelector('.t-msg').textContent = msg || '';
    box.appendChild(el);
    const kill = () => { el.classList.add('out'); setTimeout(() => el.remove(), 360); };
    el.addEventListener('click', kill);
    setTimeout(kill, ms);
  }

  // ---- numbers that count up ----------------------------------------------
  function countUp(root = document) {
    root.querySelectorAll('[data-count]').forEach(el => {
      const target = parseFloat(el.dataset.count);
      const decimals = parseInt(el.dataset.decimals || '0', 10);
      const fmt = v => v.toLocaleString(undefined, {
        minimumFractionDigits: decimals, maximumFractionDigits: decimals,
      });
      // Hidden pages get no animation frames, so a count-up there would sit
      // at zero until the window came back. Show the real number instead.
      if (reduced || document.hidden || !isFinite(target)) { el.textContent = fmt(target); return; }
      const start = performance.now();
      const dur = 700;
      const tick = now => {
        const t = Math.min(1, (now - start) / dur);
        const eased = 1 - Math.pow(1 - t, 3);
        el.textContent = fmt(target * eased);
        if (t < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      // And if frames stop mid-count, land on the true value regardless.
      setTimeout(() => { el.textContent = fmt(target); }, dur + 150);
    });
  }

  function tile(value, unit, label, decimals = 0) {
    return `<div class="tile"><div class="v"><span data-count="${value}"
      data-decimals="${decimals}">0</span>${unit ? `<small>${unit}</small>` : ''}</div>
      <div class="k">${label}</div></div>`;
  }

  // ---- generation overlay -------------------------------------------------
  let clockTimer = null;
  let started = 0;

  const overlay = {
    show() {
      const el = $('#gen-overlay');
      el.hidden = false;
      el.classList.remove('is-done', 'is-failed');
      $('.gen-kicker', el).textContent = 'GENERATING TERRAIN';
      $('#gen-stage').textContent = 'Contacting OpenStreetMap…';
      $('#gen-detail').textContent = '';
      $('#gen-bar').style.width = '4%';
      started = Date.now();
      clearInterval(clockTimer);
      clockTimer = setInterval(() => {
        const s = Math.floor((Date.now() - started) / 1000);
        $('#gen-clock').textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
      }, 500);
      $('#generateBtn').classList.add('is-busy');
    },
    update(p) {
      if (p.stage === 'osm') {
        const total = p.total || 1;
        const done = p.done || 0;
        $('#gen-stage').textContent = 'Downloading the real world';
        $('#gen-detail').textContent = total > 1
          ? `OpenStreetMap area ${done + 1} of ${total}` : 'One OpenStreetMap query';
        $('#gen-bar').style.width = `${Math.max(6, Math.round(8 + 62 * done / total))}%`;
      } else if (p.stage === 'render') {
        $('#gen-stage').textContent = 'Painting the map';
        $('#gen-detail').textContent =
          `${(p.features || 0).toLocaleString()} features into roads, grass, water and trees`;
        $('#gen-bar').style.width = '82%';
      }
    },
    done(summary) {
      const el = $('#gen-overlay');
      el.classList.add('is-done');
      $('.gen-kicker', el).textContent = 'TERRAIN READY';
      $('#gen-stage').textContent = summary || 'Done';
      $('#gen-detail').textContent = '';
      $('#gen-bar').style.width = '100%';
      this.hide(900);
    },
    fail(message) {
      const el = $('#gen-overlay');
      el.classList.add('is-failed');
      $('.gen-kicker', el).textContent = 'GENERATION FAILED';
      $('#gen-stage').textContent = 'Something went wrong';
      $('#gen-detail').textContent = message.length > 160 ? message.slice(0, 157) + '…' : message;
      this.hide(2600);
    },
    hide(delay = 0) {
      setTimeout(() => {
        $('#gen-overlay').hidden = true;
        clearInterval(clockTimer);
        $('#generateBtn').classList.remove('is-busy');
      }, delay);
    },
  };

  // ---- pipeline cards -----------------------------------------------------
  const NOTE_STEP = {
    buildingsNote: 'buildings', compileNote: 'compile',
    worldedNote: 'compile', installNote: 'install',
  };
  const BUSY = /generating|starting|installing|compiling|waiting|opened/i;
  const TITLES = {
    buildings: ['Buildings generated', 'Building generation failed'],
    compile: ['Map compiled', 'Compile failed'],
    install: ['Installed into Project Zomboid', 'Install failed'],
  };

  function card(key, state) {
    const el = $(`.pipe-card[data-step="${key}"]`);
    if (!el) return;
    el.classList.remove('is-running', 'is-done', 'is-error', 'is-ready');
    if (state) el.classList.add(`is-${state}`);
  }

  // Called for every status line app.js writes under a pipeline step.
  function noted(id, text, cls) {
    const key = NOTE_STEP[id];
    if (!key) return;
    if (cls === 'ok') {
      card(key, 'done');
      step(key, 'done');
      toast('ok', TITLES[key][0], text);
      if (key === 'install') confetti();
    } else if (cls === 'bad') {
      card(key, 'error');
      step(key, 'error');
      toast('bad', TITLES[key][1], text, 9000);
    } else if (BUSY.test(text)) {
      card(key, 'running');
      step(key, 'running');
    } else if (/^ready/i.test(text)) {
      card(key, 'ready');
      step(key, 'active');
    }
  }

  function progress(key, pct) {
    const bar = key === 'compile' ? $('#compileBar') : null;
    if (!bar) return;
    bar.parentElement.classList.toggle('is-indeterminate', !(pct > 0));
    if (pct > 0) bar.style.width = `${Math.min(100, pct)}%`;
  }

  // ---- confetti -----------------------------------------------------------
  function confetti() {
    if (reduced) return;
    const canvas = $('#confetti');
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    canvas.width = innerWidth * dpr;
    canvas.height = innerHeight * dpr;
    ctx.scale(dpr, dpr);
    const colours = ['#a5e266', '#d6ff85', '#ffb547', '#6ee7ff', '#ffffff'];
    const parts = Array.from({ length: 170 }, () => ({
      x: innerWidth / 2 + (Math.random() - .5) * 160,
      y: innerHeight * .45,
      vx: (Math.random() - .5) * 16,
      vy: -Math.random() * 17 - 4,
      w: 5 + Math.random() * 6, h: 3 + Math.random() * 5,
      r: Math.random() * Math.PI, vr: (Math.random() - .5) * .35,
      c: colours[Math.floor(Math.random() * colours.length)],
    }));
    const end = performance.now() + 2800;
    const frame = now => {
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      const fade = Math.max(0, Math.min(1, (end - now) / 700));
      parts.forEach(p => {
        p.vy += .42; p.vx *= .985; p.x += p.vx; p.y += p.vy; p.r += p.vr;
        ctx.save();
        ctx.globalAlpha = fade;
        ctx.translate(p.x, p.y); ctx.rotate(p.r);
        ctx.fillStyle = p.c;
        ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
        ctx.restore();
      });
      if (now < end) requestAnimationFrame(frame);
      else ctx.clearRect(0, 0, innerWidth, innerHeight);
    };
    requestAnimationFrame(frame);
  }

  // ---- map extras (need app.js's `map`, so they wait for load) -------------
  function mapExtras() {
    if (typeof map === 'undefined') return;

    const layers = {
      // The standard OSM tiles, inverted in CSS. Hosted dark basemaps come and
      // go - CARTO's started stamping "API KEY REQUIRED" across every tile -
      // and this one needs no key and no third party.
      dark: L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, className: 'tiles-dark',
        attribution: '© OpenStreetMap contributors',
      }),
      streets: L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '© OpenStreetMap contributors',
      }),
      satellite: L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
          maxZoom: 19, attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
        }),
    };
    // app.js adds a plain OSM layer; swap it for the chosen one.
    const existing = [];
    map.eachLayer(l => { if (l instanceof L.TileLayer) existing.push(l); });
    existing.forEach(l => map.removeLayer(l));
    let saved = 'dark';
    try { saved = localStorage.getItem('knoxify.base') || 'dark'; } catch (_) {}
    if (!layers[saved]) saved = 'dark';
    layers[saved].addTo(map);
    document.querySelectorAll('#basemaps button').forEach(btn => {
      btn.classList.toggle('is-on', btn.dataset.base === saved);
      btn.addEventListener('click', () => {
        Object.values(layers).forEach(l => map.removeLayer(l));
        layers[btn.dataset.base].addTo(map);
        document.querySelectorAll('#basemaps button')
          .forEach(b => b.classList.toggle('is-on', b === btn));
        try { localStorage.setItem('knoxify.base', btn.dataset.base); } catch (_) {}
      });
    });

    const lat = $('#hud-lat'), lon = $('#hud-lon'), zoom = $('#hud-zoom');
    const showZoom = () => { zoom.textContent = map.getZoom(); };
    map.on('mousemove', e => {
      lat.textContent = e.latlng.lat.toFixed(5);
      lon.textContent = (((e.latlng.lng + 180) % 360 + 360) % 360 - 180).toFixed(5);
    });
    map.on('zoomend', showZoom);
    showZoom();

    // Point at the rectangle tool until an area exists.
    const beckon = on => {
      const tool = $('.leaflet-draw-draw-rectangle');
      if (tool) tool.classList.toggle('is-beckoning', on);
    };
    beckon(true);
    map.on(L.Draw.Event.CREATED, () => {
      beckon(false);
      const hint = $('#map-hint');
      if (hint) hint.remove();
    });
    map.on(L.Draw.Event.DELETED, () => beckon(true));
  }

  // ---- presets as cards ----------------------------------------------------
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
        // app.js listens on the real select; keep it the single source of truth.
        select.dispatchEvent(new Event('change'));
        step('style', 'done');
      });
    });
  }

  // ---- sliders --------------------------------------------------------------
  function paintRange(input) {
    const lo = parseFloat(input.min), hi = parseFloat(input.max), v = parseFloat(input.value);
    const pct = hi > lo ? ((v - lo) / (hi - lo)) * 100 : 0;
    input.style.setProperty('--pct', `${pct}%`);
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
        const input = d.parentElement.querySelector('input');
        input.value = Math.floor(Math.random() * 999999) + 1;
        d.classList.remove('is-rolling');
        void d.offsetWidth;
        d.classList.add('is-rolling');
      });
    });
  }

  // ---- server heartbeat -----------------------------------------------------
  function heartbeat() {
    const pill = $('#serverPill');
    const check = async () => {
      try {
        const res = await fetch('/api/settings', { cache: 'no-store' });
        const up = res.ok;
        pill.classList.toggle('is-down', !up);
        pill.querySelector('.txt').textContent = up ? 'ONLINE' : 'OFFLINE';
      } catch (_) {
        pill.classList.add('is-down');
        pill.querySelector('.txt').textContent = 'OFFLINE';
      }
    };
    setInterval(check, 15000);
  }

  document.addEventListener('DOMContentLoaded', () => {
    presetCards();
    heartbeat();
    const close = $('.hint-close');
    if (close) close.addEventListener('click', () => $('#map-hint').remove());
  });
  window.addEventListener('load', mapExtras);

  return { step, resetFrom, toast, countUp, tile, overlay, noted, card, progress,
           confetti, wireSettings, paintRange };
})();
