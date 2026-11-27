// KnoxMap in another language, from a plain text file.
//
// lang/english.txt lists every line the window says, as "English = English".
// Copy it to lang/<language>.txt, translate the right-hand side, and the
// language is in the menu at the top - no code, no rebuild. Anything left in
// English stays English, so a half-translated file is fine.
//
// The page itself is written in English, so translating means swapping the
// text as it is shown: every text node and every placeholder, title and label
// now, and anything the app writes later - a note under a button, a toast, the
// settings it builds from the server - through a MutationObserver. Matching is
// on the whole string, which is what the translator sees in the file.

/* exported i18n */
// Read by app.js and shell.js. A linter checking one script cannot see that
// anybody uses it, so the line above says so.
const i18n = (() => {
  let strings = {};            // English -> translated
  let templates = [];          // compiled once when a language is loaded
  let watching = null;
  let pending = Promise.resolve();
  const originals = new WeakMap();
  const attributes = ['placeholder', 'title', 'aria-label', 'label', 'alt'];
  const languages = { english: 'en', espanol: 'es', portugues_brasil: 'pt-BR',
                      russian: 'ru', turkce: 'tr' };
  const verbatim = new Set(['map', 'mapName', 'currentMap', 'name', 'title', 'modId',
                            'path', 'folder', 'modRoot', 'fromMap', 'server', 'file',
                            'filename', 'who', 'maps']);

  const clean = s => s.replace(/\s+/g, ' ').trim();

  function compileTemplates() {
    templates = [];
    for (const [english, translated] of Object.entries(strings)) {
      const names = [];
      const pieces = english.split(/(\{[A-Za-z_]\w*\})/g);
      if (pieces.length === 1) continue;
      const escape = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const pattern = pieces.map(piece => {
        if (!/^\{[A-Za-z_]\w*\}$/.test(piece)) return escape(piece);
        names.push(piece.slice(1, -1));
        return '(.+?)';
      }).join('');
      templates.push({ regex: new RegExp(`^${pattern}$`), names, translated,
                       specificity: pieces.filter((_, i) => i % 2 === 0).join('').length });
    }
    templates.sort((a, b) => b.specificity - a.specificity);
  }

  function fill(message, values) {
    return message.replace(/\{([A-Za-z_]\w*)\}/g, (token, name) =>
      Object.hasOwn(values, name) ? values[name] : token);
  }

  function lookup(text, depth = 0) {
    const source = clean(text);
    if (Object.hasOwn(strings, source)) return strings[source];
    if (depth >= 4) return null;
    for (const { regex, names, translated } of templates) {
      const match = regex.exec(source);
      if (!match) continue;
      const values = Object.create(null);
      names.forEach((name, i) => {
        const value = match[i + 1];
        values[name] = verbatim.has(name) ? value : (lookup(value, depth + 1) ?? value);
      });
      return fill(translated, values);
    }
    return null;
  }

  function say(text) {
    if (!text) return null;
    const hit = lookup(text);
    if (hit === null) return null;
    // Keep the spacing around it: the page lays text out with it.
    const [, before, , after] = text.match(/^(\s*)([\s\S]*?)(\s*)$/);
    return before + hit + after;
  }

  function translateValue(node, key, current) {
    if (current == null) return current;
    const values = originals.get(node) || {};
    const previous = values[key];
    // A fresh update from the app replaces the original. Our own translated
    // value keeps its English source so it can be rendered in another language.
    const source = previous?.rendered === current ? previous.source : current;
    const rendered = say(source) ?? source;
    if (rendered !== source) {
      values[key] = { source, rendered };
      originals.set(node, values);
    } else {
      delete values[key];
    }
    return rendered;
  }

  function translateNode(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (node.parentElement?.closest('[data-no-translate]')) return;
      const next = translateValue(node, 'text', node.nodeValue);
      if (next !== node.nodeValue) node.nodeValue = next;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE || node.closest?.('[data-no-translate]')) return;
    for (const attr of attributes) {
      const value = node.getAttribute && node.getAttribute(attr);
      const next = translateValue(node, attr, value);
      if (next !== value) node.setAttribute(attr, next);
    }
    for (const child of node.childNodes) translateNode(child);
  }

  function translateAll() {
    translateNode(document.body);
  }

  function watch() {
    if (watching) return;
    watching = new MutationObserver(records => {
      watching.disconnect();          // our own changes must not re-trigger it
      for (const record of records) {
        if (record.type === 'characterData') translateNode(record.target);
        for (const node of record.addedNodes) translateNode(node);
        if (record.type === 'attributes' && record.target) translateNode(record.target);
      }
      observe();
    });
    observe();
  }

  function observe() {
    watching.observe(document.body, {
      subtree: true, childList: true, characterData: true,
      attributeFilter: attributes,
    });
  }

  async function load(file, remember) {
    try {
      const res = await fetch(`/api/language/${encodeURIComponent(file)}`,
                              { method: remember ? 'POST' : 'GET' });
      const data = await res.json();
      if (!res.ok) return;
      strings = data.strings || {};
    } catch (_) {
      return;
    }
    compileTemplates();
    if (document.documentElement) document.documentElement.lang = languages[file] || '';
    watching?.disconnect();
    translateAll();
    if (watching) observe();
    else watch();
    document.dispatchEvent?.(new Event('knoxmap:language'));
  }

  function use(file, remember) {
    // Apply and persist selections in the same order.
    pending = pending.then(() => load(file, remember));
    return pending;
  }

  async function start() {
    const menu = document.getElementById('language');
    if (!menu) return;
    let data;
    try {
      data = await (await fetch('/api/languages')).json();
    } catch (_) { return; }
    const languages = data.languages || [];
    // With nothing to choose from, the menu only gets in the way; the file
    // that explains how to add one is named in its tooltip.
    if (languages.length < 2) {
      menu.hidden = true;
      return;
    }
    menu.hidden = false;
    menu.innerHTML = '';
    for (const language of languages) {
      const option = document.createElement('option');
      option.value = language.file;
      option.textContent = language.name;
      option.selected = language.file === data.current;
      menu.append(option);
    }
    menu.addEventListener('change', () => use(menu.value, true));
    use(data.current || 'english', false);
  }

  document.addEventListener('DOMContentLoaded', start);
  return { use, translateAll, t(text, values) {
    // Explicit arguments carry literal data. Translate a nested label before
    // passing it in if it also comes from the interface.
    return values ? fill(strings[text] ?? text, values) : (say(text) ?? text);
  } };
})();
