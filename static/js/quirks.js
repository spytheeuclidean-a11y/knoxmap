// Knoxify — the silly layer.
//
// Jokes, zombies and easter eggs. Nothing here does real work: it only reacts
// to things app.js and fx.js already do, and every piece is safe to lose.
// Sound is off until asked for, and reduced-motion users keep the jokes but
// not the shambling.

(() => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $ = s => document.querySelector(s);
  const pick = list => list[Math.floor(Math.random() * list.length)];
  const store = {
    get(k, d) { try { const v = localStorage.getItem('knoxify.' + k); return v === null ? d : JSON.parse(v); } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem('knoxify.' + k, JSON.stringify(v)); } catch (_) {} },
  };

  // ---- words ------------------------------------------------------------------

  const QUIPS = {
    osm: [
      'Asking OpenStreetMap nicely',
      'Counting every fence post, twice',
      'Downloading streets, skipping the zombies',
      'Measuring rooftops for sniping',
      'Politely ignoring the admin boundaries',
      'Checking which pharmacies are still open',
      'Negotiating with three Overpass servers',
    ],
    render: [
      'Painting roads you will crash on',
      'Planting trees for you to hide behind',
      'Filling the swimming pools (not with water)',
      'Parking cars. Removing their keys.',
      'Sweeping the pavements, leaving the blood',
      'Placing hedges exactly where you will get stuck',
      'Mowing lawns for the last time ever',
    ],
    cta: [
      'Warning: map may contain zombies.',
      'No refunds for bites.',
      'Terms and conditions: survive.',
      'Batteries not included. Or found.',
      'Side effects include being eaten.',
      'Now with 100% more light switches.',
    ],
    tips: [
      'Zombies cannot open doors. You, however, will forget to close them.',
      'Every room has a light switch now. The power will not last.',
      'A fence is just a wall that believes in you.',
      'Schoolyards are fenced. Remember that when you need to leave quickly.',
      'The factory is the biggest building in town. It is also full.',
      'Parking lots have cars. Cars have alarms. Choose wisely.',
      'Hedges look like cover. They are not cover.',
      'Upstairs flats have no front door to the street. That is the point.',
      'Orchards grow in rows. So do zombies, when they chase you.',
      'The staircase always leads somewhere now. Usually somewhere worse.',
      'Draw a smaller area first. Your CPU has feelings.',
      'Bathrooms are the smallest room in the flat. Do not hide there.',
      'Real-world maps: because you already know where the supermarket is.',
      'Cemeteries have flowers now. The residents are not impressed.',
    ],
    poke: [
      'Stop poking the logo.',
      'The logo has feelings too.',
      'Poke it again. I dare you.',
      'You have unlocked: nothing.',
      'That tickles. Please stop.',
    ],
    splat: ['Splat.', 'Headshot.', 'One less neighbour.', 'Clean-up on aisle map.', 'Thwack.', 'Bonk.'],
    // Only jokes that blame nobody: these sit in front of real error messages,
    // and one suggesting the server is at fault misleads when it is not.
    fail: ['Bitten!', 'Uh oh.', 'Well, that went south.', 'Not today.'],
    win: ['Knox County welcomes you. Try not to die.', 'Your new home is ready. Lock the doors.',
          'Installed. The zombies have been notified.'],
  };

  // ---- sound (synthesised, opt-in) -----------------------------------------------

  let audio = null;
  let soundOn = store.get('sound', false);

  function ctx() {
    if (!audio) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return null;
      audio = new Ctx();
    }
    return audio;
  }

  function tone({ freq = 200, to = null, dur = 0.3, type = 'sine', vol = 0.12, delay = 0 }) {
    if (!soundOn) return;
    const a = ctx();
    if (!a) return;
    const t0 = a.currentTime + delay;
    const osc = a.createOscillator();
    const gain = a.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    if (to) osc.frequency.exponentialRampToValueAtTime(to, t0 + dur);
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(vol, t0 + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(gain).connect(a.destination);
    osc.start(t0);
    osc.stop(t0 + dur + 0.05);
  }

  const sfx = {
    groan() { tone({ freq: 140, to: 70, dur: 0.7, type: 'sawtooth', vol: 0.05 }); tone({ freq: 95, to: 60, dur: 0.8, type: 'triangle', vol: 0.06, delay: 0.05 }); },
    splat() { tone({ freq: 320, to: 40, dur: 0.18, type: 'square', vol: 0.08 }); },
    win() { [523, 659, 784, 1046].forEach((f, i) => tone({ freq: f, dur: 0.18, type: 'triangle', vol: 0.08, delay: i * 0.09 })); },
    fail() { tone({ freq: 220, to: 110, dur: 0.45, type: 'sawtooth', vol: 0.06 }); },
    siren() { for (let i = 0; i < 4; i++) tone({ freq: 600, to: 900, dur: 0.45, type: 'sine', vol: 0.05, delay: i * 0.5 }); },
    boop() { tone({ freq: 880, dur: 0.08, type: 'sine', vol: 0.05 }); },
  };

  function paintSound() {
    const btn = $('#soundBtn');
    if (!btn) return;
    btn.textContent = soundOn ? '🔊' : '🔇';
    btn.setAttribute('aria-pressed', String(soundOn));
  }

  // ---- header chips ---------------------------------------------------------------

  let kills = store.get('kills', 0);
  let days = store.get('days', 1);

  function paintChips(bump) {
    const k = $('#killChip'), d = $('#dayChip');
    if (k) k.textContent = `🧟 ${kills.toLocaleString()}`;
    if (d) d.textContent = `DAY ${days}`;
    if (bump && !reduced) {
      const el = bump === 'kill' ? k : d;
      el?.classList.remove('bump'); void el?.offsetWidth; el?.classList.add('bump');
    }
  }

  // ---- the shambling -------------------------------------------------------------

  const ZOMBIE_SVG = `
    <svg viewBox="0 0 40 56" aria-hidden="true">
      <g class="z-body">
        <ellipse cx="20" cy="54" rx="11" ry="2" fill="rgba(0,0,0,.35)"/>
        <g class="z-leg z-leg-a"><rect x="14" y="36" width="5" height="16" rx="2" fill="#3d4a5c"/><rect x="12.5" y="50" width="7" height="3.5" rx="1.5" fill="#2a2a2a"/></g>
        <g class="z-leg z-leg-b"><rect x="21" y="36" width="5" height="16" rx="2" fill="#34404f"/><rect x="20.5" y="50" width="7" height="3.5" rx="1.5" fill="#2a2a2a"/></g>
        <rect x="12" y="20" width="16" height="18" rx="4" fill="#6b5a45"/>
        <path d="M13 26 l3 4 M24 24 l2 5" stroke="#8a1c1c" stroke-width="1.6" stroke-linecap="round"/>
        <g class="z-arm"><rect x="24" y="22" width="15" height="4.5" rx="2" fill="#7fae5a"/><rect x="24" y="28" width="13" height="4.5" rx="2" fill="#739f50"/></g>
        <circle cx="20" cy="13" r="8.5" fill="#8cbf63"/>
        <path d="M13 9 q7 -6 14 0" stroke="#4f6b35" stroke-width="2.2" fill="none" stroke-linecap="round"/>
        <circle cx="23" cy="12" r="2" fill="#fff6c9"/><circle cx="23.5" cy="12.3" r=".9" fill="#b3261e"/>
        <circle cx="17.5" cy="12.5" r="1.4" fill="#fff6c9"/>
        <path d="M17 17.5 q3 2 6 0" stroke="#3a1d1d" stroke-width="1.4" fill="none" stroke-linecap="round"/>
      </g>
    </svg>`;

  const GROANS = ['Braaains', 'Mrrrgh', 'Hnnngh', '...hungry', 'Uuurgh', 'Have you tried turning it off?'];

  function spawnZombie({ fast = false, quiet = false } = {}) {
    const lane = $('#shamble-lane');
    if (!lane || reduced) return;
    const z = document.createElement('button');
    z.type = 'button';
    z.className = 'zombie';
    z.title = 'Splat me';
    z.setAttribute('aria-label', 'A zombie. Click to splat it.');
    const leftToRight = Math.random() < 0.5;
    const dur = fast ? 7 + Math.random() * 4 : 22 + Math.random() * 14;
    z.style.setProperty('--dur', `${dur}s`);
    z.style.setProperty('--bottom', `${40 + Math.random() * 90}px`);
    z.style.setProperty('--scale', (0.85 + Math.random() * 0.4).toFixed(2));
    z.classList.add(leftToRight ? 'ltr' : 'rtl');
    z.innerHTML = ZOMBIE_SVG + `<span class="z-say">${pick(GROANS)}</span>`;
    lane.appendChild(z);
    if (!quiet && Math.random() < 0.5) sfx.groan();

    const done = () => z.remove();
    z.addEventListener('animationend', e => { if (e.animationName.startsWith('walk')) done(); });
    z.addEventListener('click', e => {
      e.stopPropagation();
      if (z.classList.contains('dead')) return;
      z.classList.add('dead');
      kills += 1;
      store.set('kills', kills);
      paintChips('kill');
      sfx.splat();
      const rect = z.getBoundingClientRect();
      splatAt(rect.left + rect.width / 2, rect.top + rect.height * 0.6);
      if (kills === 1 || kills % 25 === 0) {
        fx.toast('ok', kills === 1 ? 'First blood' : `${kills} zombies splatted`,
                 kills === 1 ? 'The first of many.' : pick(QUIPS.splat));
      }
      setTimeout(done, 650);
    });
  }

  function splatAt(x, y) {
    const s = document.createElement('div');
    s.className = 'splat';
    s.style.left = `${x}px`;
    s.style.top = `${y}px`;
    s.textContent = pick(QUIPS.splat);
    document.body.appendChild(s);
    setTimeout(() => s.remove(), 1200);
  }

  function shambleForever() {
    if (reduced) return;
    const next = 25000 + Math.random() * 40000;
    setTimeout(() => {
      if (!document.hidden && !$('#gen-overlay:not([hidden])')) spawnZombie();
      shambleForever();
    }, next);
  }

  // ---- generation overlay quips ---------------------------------------------------

  let quipTimer = null;
  let stage = 'osm';

  function rollQuip() {
    const el = $('#gen-quip');
    if (!el) return;
    el.classList.remove('in'); void el.offsetWidth;
    el.textContent = pick(QUIPS[stage] || QUIPS.osm) + '…';
    el.classList.add('in');
  }

  const overlay = fx.overlay;
  const origShow = overlay.show.bind(overlay);
  const origUpdate = overlay.update.bind(overlay);
  const origHide = overlay.hide.bind(overlay);
  overlay.show = function () {
    origShow();
    stage = 'osm';
    rollQuip();
    clearInterval(quipTimer);
    quipTimer = setInterval(rollQuip, 3200);
  };
  overlay.update = function (p) {
    origUpdate(p);
    if (p.stage && p.stage !== stage && QUIPS[p.stage]) { stage = p.stage; rollQuip(); }
  };
  overlay.hide = function (delay = 0) {
    origHide(delay);
    setTimeout(() => clearInterval(quipTimer), delay);
  };

  // ---- toasts get a sense of humour ----------------------------------------------------

  const origToast = fx.toast;
  fx.toast = function (kind, title, msg, ms) {
    if (kind === 'bad') { title = `${pick(QUIPS.fail)} ${title}`; sfx.fail(); }
    if (kind === 'ok') sfx.boop();
    return origToast(kind, title, msg, ms);
  };

  // Each finished map is another day survived; installing one gets a party.
  const origNoted = fx.noted;
  fx.noted = function (id, text, cls) {
    origNoted(id, text, cls);
    if (id === 'installNote' && cls === 'ok') {
      sfx.win();
      emojiBurst();
      setTimeout(() => fx.toast('info', 'Welcome home', pick(QUIPS.win), 7000), 900);
    }
  };
  const origStep = fx.step;
  fx.step = function (key, state) {
    origStep(key, state);
    if (key === 'terrain' && state === 'done') {
      days += 1;
      store.set('days', days);
      paintChips('day');
      if (Math.random() < 0.7) setTimeout(() => spawnZombie({ fast: true }), 1400);
    }
  };

  function emojiBurst() {
    if (reduced) return;
    const faces = ['🧟', '🧠', '🔦', '🪓', '🥫', '🧟', '💀'];
    for (let i = 0; i < 26; i++) {
      const e = document.createElement('div');
      e.className = 'emoji-rain';
      e.textContent = pick(faces);
      e.style.left = `${Math.random() * 100}vw`;
      e.style.setProperty('--fall', `${2.2 + Math.random() * 2.2}s`);
      e.style.setProperty('--delay', `${Math.random() * 0.8}s`);
      e.style.setProperty('--spin', `${(Math.random() - .5) * 720}deg`);
      document.body.appendChild(e);
      setTimeout(() => e.remove(), 5200);
    }
  }

  // ---- a zombie headcount for the selection ----------------------------------------------

  // People per km² of a whole map area, before any buildings are counted:
  // built-up blocks, roads, parks and yards together. Scaled by the living
  // space setting, since that is what the real count divides floor area by.
  // Residents plus people at work, per km2 of selection, as the census counts
  // them on test maps at each preset's own living space: a Tokyo or Kadikoy
  // core runs 30,000-60,000, Levittown 3,000, a French village centre 6,000
  // (mostly fields around it, so rural sits far lower).
  const PEOPLE_PER_KM2 = { town: 10000, suburb: 3000, city: 30000, rural: 800 };
  const PRESET_SPACE = { town: 45, suburb: 60, city: 50, rural: 70 };

  function setting(key, fallback) {
    const el = document.querySelector(`#advanced-body input[data-key="${key}"]`);
    const v = el ? parseFloat(el.value) : NaN;
    return Number.isFinite(v) ? v : fallback;
  }

  function zombieEstimate(force) {
    const stats = $('#area-stats');
    if (!stats || stats.classList.contains('empty')) return;
    const existing = stats.querySelector('.z-estimate');
    if (existing && !force) return;
    existing?.remove();
    const areaTile = stats.querySelector('.tile [data-count]');
    const km2 = areaTile ? parseFloat(areaTile.dataset.count) : 0;
    if (!km2) return;
    const preset = ($('#preset') || {}).value || 'town';
    const perPerson = setting('zombies_per_resident', 1);
    const space = setting('m2_per_person', 45);
    const people = km2 * (PEOPLE_PER_KM2[preset] || 10000) * ((PRESET_SPACE[preset] || 45) / space);
    const guess = Math.max(1, Math.round(people * perPerson));
    // Judged per km², so a big quiet area does not read as scarier than a
    // small packed one.
    const perKm2 = guess / km2;
    const mood = perKm2 < 800 ? 'a quiet neighbourhood' : perKm2 < 3500 ? 'a lively crowd'
               : perKm2 < 9000 ? 'bring a bigger bat' : 'absolutely not';
    const div = document.createElement('div');
    div.className = 'z-estimate';
    div.innerHTML = `<span class="z-emoji">🧟</span><span>Roughly <b>${guess.toLocaleString()}</b>
      undead residents — ${mood}. <i>A guess until the buildings are counted.</i></span>`;
    stats.appendChild(div);
  }

  // ---- survival tips ticker ---------------------------------------------------------------

  let tipIndex = Math.floor(Math.random() * QUIPS.tips.length);
  let tipNumber = store.get('tipNumber', 1);

  function typeTip() {
    const el = $('#tipText');
    const num = $('#tipNum');
    if (!el) return;
    const text = QUIPS.tips[tipIndex % QUIPS.tips.length];
    tipIndex += 1;
    if (num) num.textContent = tipNumber;
    tipNumber += 1;
    store.set('tipNumber', tipNumber);
    if (reduced) { el.textContent = text; return; }
    el.textContent = '';
    let i = 0;
    const tick = () => {
      el.textContent = text.slice(0, i) + (i < text.length ? '▌' : '');
      i += 1;
      if (i <= text.length) setTimeout(tick, 22);
    };
    tick();
  }

  // ---- easter eggs -----------------------------------------------------------------------

  function knoxEvent() {
    if (document.body.classList.contains('knox-event')) return;
    document.body.classList.add('knox-event');
    sfx.siren();
    // Straight to the original toast: the failure wrapper would prefix it with
    // "The server got scratched", which reads as a real error.
    origToast('bad', 'THE KNOX EVENT HAS BEGUN', 'Please remain calm and proceed to the nearest map.', 7000);
    for (let i = 0; i < 9; i++) setTimeout(() => spawnZombie({ fast: true, quiet: i > 0 }), i * 420);
    setTimeout(() => document.body.classList.remove('knox-event'), 8500);
  }

  const KONAMI = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
                  'ArrowLeft', 'ArrowRight', 'b', 'a'];
  let konami = 0;
  let typed = '';
  document.addEventListener('keydown', e => {
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    konami = e.key === KONAMI[konami] ? konami + 1 : (e.key === KONAMI[0] ? 1 : 0);
    if (konami === KONAMI.length) { konami = 0; knoxEvent(); }
    typed = (typed + e.key.toLowerCase()).slice(-8);
    if (typed.endsWith('knox')) knoxEvent();
    if (typed.endsWith('brains')) { spawnZombie({ fast: true }); fx.toast('info', 'You called?', 'One zombie, delivered.'); }
  });

  let pokes = 0;
  let pokeTimer = null;
  function logoPoke() {
    const mark = $('.brand-mark');
    mark.classList.remove('wobble'); void mark.offsetWidth; mark.classList.add('wobble');
    sfx.boop();
    pokes += 1;
    clearTimeout(pokeTimer);
    pokeTimer = setTimeout(() => { pokes = 0; }, 1500);
    if (pokes === 5) { fx.toast('info', pick(QUIPS.poke), 'Five pokes. Impressive dedication.'); }
    if (pokes === 12) { pokes = 0; knoxEvent(); }
  }

  // Idle for a while? Something peeks in to check on you.
  let idleTimer = null;
  function resetIdle() {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(peek, 75000);
  }
  function peek() {
    const pane = $('#map-pane');
    if (!pane || reduced || document.hidden) return;
    const p = document.createElement('div');
    p.className = 'peeker';
    p.innerHTML = ZOMBIE_SVG + '<span class="z-say">still there?</span>';
    pane.appendChild(p);
    sfx.groan();
    setTimeout(() => p.remove(), 5200);
  }

  // ---- wire up -----------------------------------------------------------------------------

  paintChips();
  paintSound();

  $('#soundBtn')?.addEventListener('click', () => {
    soundOn = !soundOn;
    store.set('sound', soundOn);
    paintSound();
    if (soundOn) { ctx()?.resume(); sfx.boop(); fx.toast('info', 'Sound on', 'Groans, splats and the occasional siren.'); }
  });
  $('.brand-mark')?.addEventListener('click', logoPoke);
  $('#killChip')?.addEventListener('click', () => spawnZombie({ fast: true }));

  document.querySelectorAll('.preset-card[data-quip]').forEach(card => {
    card.addEventListener('mouseenter', () => {
      const note = $('#ctaQuip');
      if (note) note.textContent = card.dataset.quip;
    });
    card.addEventListener('mouseleave', () => {
      const note = $('#ctaQuip');
      if (note) note.textContent = pick(QUIPS.cta);
    });
  });

  setInterval(() => {
    const note = $('#ctaQuip');
    if (note && !document.querySelector('.preset-card:hover')) {
      note.classList.remove('in'); void note.offsetWidth;
      note.textContent = pick(QUIPS.cta);
      note.classList.add('in');
    }
  }, 9000);

  const stats = $('#area-stats');
  if (stats) new MutationObserver(() => zombieEstimate(false)).observe(stats, { childList: true });
  // Re-guess as the zombie dials or the kind of place change.
  document.addEventListener('input', e => {
    const key = e.target?.dataset?.key;
    if (key === 'zombies_per_resident' || key === 'm2_per_person') zombieEstimate(true);
  });
  $('#preset')?.addEventListener('change', () => setTimeout(() => zombieEstimate(true), 0));

  typeTip();
  setInterval(typeTip, 11000);

  ['mousemove', 'keydown', 'wheel', 'touchstart'].forEach(ev =>
    document.addEventListener(ev, resetIdle, { passive: true }));
  resetIdle();

  // A first visitor gets an early zombie, so they know it is there to be clicked.
  setTimeout(() => spawnZombie(), store.get('kills', 0) ? 20000 : 6000);
  shambleForever();
})();
