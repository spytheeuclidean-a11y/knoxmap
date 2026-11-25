const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function workspace(inWindow = false) {
  const fields = new Map();
  function field(id) {
    if (!fields.has(id)) fields.set(id, {
      value: '', classList: { toggle() {} }, addEventListener() {},
      querySelectorAll: () => [], dispatchEvent() {},
    });
    return fields.get(id);
  }
  const layer = { addTo() {} };
  const ctx = vm.createContext({
    window: { addEventListener() {} }, location: { search: '' }, URLSearchParams,
    document: { body: { dataset: { inWindow: inWindow ? '1' : '0' } },
      getElementById: field, querySelectorAll: () => [], addEventListener() {} },
    L: { map: () => ({ setView: () => ({ on() {}, addControl() {} }) }),
      tileLayer: () => layer, layerGroup: () => layer,
      FeatureGroup: class { addTo() {} }, Draw: { Event: {} },
      Control: { Draw: class {}, extend: () => class {} } },
    CustomEvent: class {}, fetch: () => new Promise(() => {}), loadSettings: async () => {},
  });
  const run = code => vm.runInContext(code, ctx);
  run(fs.readFileSync(path.join(__dirname, '../../static/js/app.js'), 'utf8'));
  return { ctx, field, run };
}

test('rewiring a desktop download saves once and a browser keeps its native link', () => {
  for (const desktop of [true, false]) {
    const { ctx } = workspace(desktop);
    const saved = [];
    ctx.saveFile = name => saved.push(name);
    const listeners = [];
    const link = { href: '/download/B.zip', download: 'B.zip',
      addEventListener: (_, handler) => listeners.push(handler),
      removeAttribute(key) { delete this[key]; } };
    ctx.wireDownload(link, 'first', 'first file');
    ctx.wireDownload(link, 'zip', 'the zip');
    const event = { preventDefault() {} };
    for (const handler of listeners) handler(event);
    link.onclick?.(event);
    assert.deepEqual(saved, desktop ? ['zip'] : []);
    assert.equal(link.href, desktop ? '#' : '/download/B.zip');
    assert.equal(link.download, desktop ? undefined : 'B.zip');
  }
});
