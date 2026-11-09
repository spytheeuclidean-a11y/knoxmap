// The pieces of the language matcher that the browser test cannot reach: a
// placeholder filled from the text it replaced, and a value that is itself
// translated. Both are the difference between a translation that reads right
// and one that echoes "Map area" inside a half-translated sentence.
//
// Run with:  node --test tests/js
// No packages: the page's own i18n.js is loaded into a Node VM, as
// tests/test_i18n_templates.js already does, with only the browser pieces it
// touches at load time stubbed out.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.join(__dirname, '..', '..');

function load(strings) {
  const context = vm.createContext({
    Node: { TEXT_NODE: 3, ELEMENT_NODE: 1 },
    document: { addEventListener() {}, body: { nodeType: 1, childNodes: [] } },
    MutationObserver: class { observe() {} disconnect() {} },
    window: { location: { reload() {} } },
    fetch: async () => ({ ok: true, json: async () => ({ strings }) }),
  });
  vm.runInContext(fs.readFileSync(path.join(root, 'static', 'js', 'i18n.js'), 'utf8'), context);
  return {
    translate: async () => {
      await vm.runInContext("i18n.use('test', false)", context);
    },
    t: text => vm.runInContext(`i18n.t(${JSON.stringify(text)})`, context),
  };
}

test('a placeholder is filled from the sentence it matched', async () => {
  const language = load({ 'Shape area: {area} km²': 'Fläche: {area} km²' });
  await language.translate();
  assert.equal(language.t('Shape area: 12 km²'), 'Fläche: 12 km²');
});

test('a value that is itself translated is translated too', async () => {
  const language = load({
    'Map area': 'Kartenfläche',
    'Shape area: {name}': 'Fläche: {name}',
  });
  await language.translate();
  assert.equal(language.t('Shape area: Map area'), 'Fläche: Kartenfläche');
  assert.equal(language.t('Shape area: km'), 'Fläche: km');
});

test('the spacing around a sentence is kept', async () => {
  const language = load({ 'Map area': 'Kartenfläche' });
  await language.translate();
  assert.equal(language.t('  Map area  '), '  Kartenfläche  ');
});

test('text with no translation comes back untouched', async () => {
  const language = load({ 'Map area': 'Kartenfläche' });
  await language.translate();
  assert.equal(language.t('Nothing matches this'), 'Nothing matches this');
  assert.equal(language.t('<img src=x onerror=alert(1)>'), '<img src=x onerror=alert(1)>');
});
