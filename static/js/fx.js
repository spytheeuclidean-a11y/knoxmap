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

  // An error worth reporting: the message, its id in the log, and two ways to
  // pass it on - the details copied for a Discord message, or the whole
  // report zip saved into the logs folder and shown in Explorer.
  function problem(title, msg, errorId) {
    const box = $('#toasts');
    if (!box) return;
    const el = document.createElement('div');
    el.className = 'toast bad problem';
    el.innerHTML = '<b></b> <span class="msg"></span><div class="eid"></div>'
      + '<div class="toast-actions"><button type="button" class="copy">Copy details</button>'
      + '<button type="button" class="report">Save report</button>'
      + '<button type="button" class="dismiss">Dismiss</button></div>';
    el.querySelector('b').textContent = title;
    el.querySelector('.msg').textContent = msg || '';
    el.querySelector('.eid').textContent = errorId ? `Error ${errorId}` : '';
    el.querySelector('.dismiss').addEventListener('click', () => el.remove());
    el.querySelector('.copy').addEventListener('click', async (e) => {
      const version = $('#appVersion')?.textContent || '';
      const text = [`KnoxMap ${version}: ${title}`, msg || '', errorId || ''].filter(Boolean).join('\n');
      try { await navigator.clipboard.writeText(text); e.target.textContent = 'Copied'; }
      catch (_) { e.target.textContent = 'Could not copy'; }
    });
    el.querySelector('.report').addEventListener('click', saveReport);
    box.appendChild(el);
  }

  async function saveReport() {
    try {
      const res = await fetch('/api/report-save', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      toast('ok', 'Report saved',
            `${data.name} is in KnoxMap's logs folder. Post it in #bug-reports on the Discord.`,
            15000);
    } catch (_) {
      // In a plain browser rather than the app window: download it instead.
      window.location.href = '/api/report';
    }
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
      $('#gen-bar').parentElement.classList.remove('is-indeterminate');
      $('#gen-bar').style.width = '4%';
      started = Date.now();
      clearInterval(clockTimer);
      clockTimer = setInterval(() => {
        const s = Math.floor((Date.now() - started) / 1000);
        $('#gen-clock').textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
      }, 500);
    },
    update(p) {
      $('#gen-bar').parentElement.classList.toggle('is-indeterminate', p.stage === 'osm' && p.total === 0);
      if (p.stage === 'osm') {
        const total = p.total || 1;
        const done = p.done || 0;
        $('#gen-stage').textContent = 'Downloading map data';
        $('#gen-detail').textContent = p.note || (total > 1 ? `Part ${done + 1} of ${total}` : '');
        $('#gen-bar').style.width = p.total === 0 ? '35%'
          : `${Math.max(6, Math.round(8 + 62 * done / total))}%`;
      } else if (p.stage === 'roads') {
        $('#gen-stage').textContent = 'Routing the roads';
        $('#gen-detail').textContent = `${(p.done || 0).toLocaleString()} of ${(p.total || 0).toLocaleString()} stretches`;
        $('#gen-bar').style.width = `${Math.round(70 + 12 * (p.done || 0) / Math.max(1, p.total || 1))}%`;
      } else if (p.stage === 'render') {
        $('#gen-stage').textContent = 'Drawing the terrain';
        $('#gen-detail').textContent = `${(p.features || 0).toLocaleString()} features`;
        $('#gen-bar').style.width = '82%';
      }
    },
    done(summary) {
      $('#gen-bar').parentElement.classList.remove('is-indeterminate');
      $('.gen-kicker').textContent = 'Done';
      $('#gen-stage').textContent = summary || '';
      $('#gen-detail').textContent = '';
      $('#gen-bar').style.width = '100%';
      this.hide(600);
    },
    fail(message) {
      $('#gen-bar').parentElement.classList.remove('is-indeterminate');
      $('.gen-kicker').textContent = 'Failed';
      const shown = i18n.t(message);
      $('#gen-stage').textContent = shown.length > 160 ? shown.slice(0, 157) + '…' : shown;
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
    // 'warn' is a step that finished and still needs attention - a compile
    // that stepped over a batch of cells. It has stopped, so the card must
    // not go on saying it is running.
    else if (cls === 'bad' || cls === 'warn') card(key, 'error');
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

  // ---- updates ------------------------------------------------------------
  // updater.py downloads a newer release in the background; once it is
  // ready the header offers a restart, which installs it.
  // A dot beside the version in the top bar: green when a newer release
  // exists, amber once it has downloaded and only a restart is left. The
  // menu is behind a click, so without this nothing on screen said an
  // update was waiting.
  function versionDot(state, version) {
    const dot = $('#versionDot');
    if (!dot) return;
    dot.hidden = !state;
    dot.classList.toggle('ready', state === 'ready');
    dot.title = state === 'ready'
      ? `KnoxMap ${version} is downloaded - restart to use it`
      : `KnoxMap ${version} is out`;
  }

  async function watchUpdates(round = 0) {
    const box = $('#updateNote');
    if (!box) return;
    let st;
    try { st = await (await fetch('/api/update')).json(); } catch (_) { return; }
    versionDot(st.state === 'ready' ? 'ready'
               : (st.latest && st.latest !== st.current ? 'new' : ''), st.latest);
    if (st.state === 'ready') {
      box.hidden = false;
      box.innerHTML = '<span></span> <button type="button">Restart to update</button>';
      box.querySelector('span').textContent = `KnoxMap ${st.latest} is ready.`;
      box.querySelector('button').addEventListener('click', async (e) => {
        e.target.disabled = true;
        e.target.textContent = 'Restarting...';
        try {
          const res = await fetch('/api/update/restart', { method: 'POST' });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        } catch (err) {
          e.target.disabled = false;
          e.target.textContent = 'Restart to update';
          toast('bad', 'Could not restart', err.message, 8000);
        }
      });
      return;
    }
    if (st.state === 'downloading') {
      box.hidden = false;
      box.textContent = `Downloading KnoxMap ${st.latest}...`;
    }
    // The first check runs a few seconds after the window opens and the
    // download takes a moment, so ask often to begin with and settle down
    // afterwards: one poll every ten minutes meant the banner could be ten
    // minutes late on a window somebody only had open for five.
    const gap = st.state === 'downloading' || round < 12 ? 5000
                : round < 20 ? 30 * 1000
                : 10 * 60 * 1000;
    setTimeout(() => watchUpdates(round + 1), gap);
  }

  // ---- version menu ---------------------------------------------------------------
  // Click the version at the top for every release on GitHub. The one chosen
  // downloads now (updater.py checks it against GitHub's fingerprint) and goes
  // in on restart - older ones too, for when a new release breaks something.

  const VERSION_MENU_SINCE = [1, 3, 5];   // the first release with this menu

  const versionParts = v => (String(v).match(/\d+/g) || []).map(Number);
  function versionBefore(a, b) {
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) < (b[i] || 0);
    }
    return false;
  }

  function versionNote(text, cls) {
    const note = $('#versionNote');
    note.className = 'hint' + (cls ? ' ' + cls : '');
    note.textContent = text;
  }

  async function waitForVersion(version) {
    let st;
    for (;;) {
      await new Promise(r => setTimeout(r, 1500));
      try { st = await (await fetch('/api/update')).json(); } catch (_) { continue; }
      if (st.state === 'downloading') continue;
      break;
    }
    if (st.state !== 'ready' || st.latest !== version) {
      throw new Error(st.error || `KnoxMap ${version} could not be downloaded.`);
    }
    const note = $('#versionNote');
    note.className = 'hint';
    note.innerHTML = '<span></span> <button type="button">Restart now</button>';
    note.querySelector('span').textContent = `KnoxMap ${version} is ready.`;
    note.querySelector('button').addEventListener('click', async (e) => {
      e.target.disabled = true;
      e.target.textContent = 'Restarting...';
      try {
        const res = await fetch('/api/update/restart', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      } catch (err) {
        e.target.disabled = false;
        e.target.textContent = 'Restart now';
        versionNote(err.message, 'bad');
      }
    });
    watchUpdates();
  }

  async function chooseVersion(item, button, current) {
    const older = versionBefore(versionParts(item.version), versionParts(current));
    if (older && versionBefore(versionParts(item.version), VERSION_MENU_SINCE)) {
      const ok = window.confirm(
        `KnoxMap ${item.version} has no version menu. To come back, download the newest ` +
        'KnoxMap from GitHub, or set "auto_update" to true in knoxmap_config.json. ' +
        `Go back to ${item.version}?`);
      if (!ok) return;
    }
    for (const b of document.querySelectorAll('#versionList button')) b.disabled = true;
    button.textContent = 'Downloading...';
    versionNote(`Downloading KnoxMap ${item.version} from GitHub...`);
    try {
      const res = await fetch('/api/versions/install', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: item.version }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      await waitForVersion(item.version);
      button.textContent = 'Downloaded';
    } catch (err) {
      versionNote(err.message, 'bad');
      openVersions(true);
    }
  }

  async function openVersions(keepNote) {
    const list = $('#versionList');
    list.innerHTML = '<li class="hint">Asking GitHub…</li>';
    if (!keepNote) versionNote('');
    let data;
    try {
      const res = await fetch('/api/versions');
      data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    } catch (err) {
      list.innerHTML = '';
      versionNote(err.message, 'bad');
      return;
    }
    list.innerHTML = '';
    const newest = data.releases.find(r => r.latest);
    if (data.managed && newest && !newest.current && !keepNote) {
      // The one thing most people opened this menu to do, before the list of
      // every release there has ever been.
      versionNote('');
      const note = $('#versionNote');
      note.className = 'hint update-ready';
      note.innerHTML = '<span></span> ';
      note.querySelector('span').textContent = `KnoxMap ${newest.version} is out.`;
      const go = document.createElement('button');
      go.type = 'button';
      go.textContent = 'Update';
      go.addEventListener('click', () => chooseVersion(newest, go, data.current));
      note.append(go);
    } else if (!data.managed) {
      versionNote('This copy of KnoxMap is a git checkout: switch versions with git.');
    } else if (!data.auto_update && !keepNote) {
      versionNote('Automatic updates are off while you are on an older version. ' +
                  'Choose the newest to turn them back on.');
    }
    for (const item of data.releases) {
      const li = document.createElement('li');
      const row = document.createElement('div');
      row.className = 'version-row';
      const v = document.createElement('span');
      v.className = 'v';
      v.textContent = `v${item.version}`;
      const date = document.createElement('span');
      date.className = 'date';
      date.textContent = item.date;
      row.append(v, date);
      if (item.current) {
        const tag = document.createElement('span');
        tag.className = 'tag now';
        tag.textContent = 'this one';
        row.append(tag);
      } else if (item.latest) {
        const tag = document.createElement('span');
        tag.className = 'tag';
        tag.textContent = 'newest';
        row.append(tag);
      }
      if (!item.current) {
        const older = versionBefore(versionParts(item.version), versionParts(data.current));
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = older ? 'Go back' : 'Update';
        if (older) button.classList.add('older');
        button.disabled = !data.managed;
        button.addEventListener('click', () => chooseVersion(item, button, data.current));
        row.append(button);
      }
      li.append(row);
      if (item.notes) {
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = "What's in it";
        const pre = document.createElement('pre');
        pre.textContent = item.notes;
        details.append(summary, pre);
        li.append(details);
      }
      list.append(li);
    }
  }

  function versionMenu() {
    const badge = $('#appVersion');
    const menu = $('#versionMenu');
    if (!badge || !menu) return;
    const close = () => { menu.hidden = true; badge.setAttribute('aria-expanded', 'false'); };
    badge.addEventListener('click', () => {
      if (!menu.hidden) { close(); return; }
      menu.hidden = false;
      badge.setAttribute('aria-expanded', 'true');
      openVersions();
    });
    menu.querySelector('.version-menu-close').addEventListener('click', close);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    document.addEventListener('click', e => {
      if (!menu.hidden && !menu.contains(e.target) && e.target !== badge) close();
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    versionMenu();
    setTimeout(watchUpdates, 8000);
    presetCards();
    $('.hint-close')?.addEventListener('click', () => $('#map-hint')?.remove());
    $('#reportLink')?.addEventListener('click', e => { e.preventDefault(); saveReport(); });
  });
  window.addEventListener('load', mapExtras);

  return { step, resetFrom, toast, problem, saveReport, countUp, tile, overlay, noted, card, progress,
           confetti() {}, wireSettings, paintRange };
})();
