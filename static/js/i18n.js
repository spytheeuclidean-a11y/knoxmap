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

const i18n = (() => {
  let strings = {};            // English -> translated
  let templates = [];          // compiled once when a language is loaded
  let watching = null;

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
        values[name] = lookup(value, depth + 1) ?? value;
      });
      // Callback replacement keeps URLs, dollar signs and markup as literal
      // text. The result still goes through text nodes or attributes only.
      return translated.replace(/\{([A-Za-z_]\w*)\}/g,
                                (token, name) => values[name] ?? token);
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

  function translateNode(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      const next = say(node.nodeValue);
      if (next !== null && next !== node.nodeValue) node.nodeValue = next;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.closest && node.closest('[data-no-translate]')) return;
    for (const attr of ['placeholder', 'title', 'aria-label']) {
      const value = node.getAttribute && node.getAttribute(attr);
      const next = value && say(value);
      if (next && next !== value) node.setAttribute(attr, next);
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
      attributeFilter: ['placeholder', 'title', 'aria-label'],
    });
  }

  async function use(file, remember) {
    try {
      const res = await fetch(`/api/language/${encodeURIComponent(file)}`,
                              { method: remember ? 'POST' : 'GET' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      strings = data.strings || {};
    } catch (_) {
      strings = {};                   // no file, no harm: English it is
    }
    compileTemplates();
    if (Object.keys(strings).length) {
      translateAll();
      watch();
    } else if (remember) {
      window.location.reload();       // back to English: the simplest way back
    }
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
    if (data.current && data.current !== 'english') use(data.current, false);
  }

  document.addEventListener('DOMContentLoaded', start);
  return { use, translateAll, t: text => say(text) ?? text };
})();
