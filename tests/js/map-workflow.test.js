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

test('generation uses the same nonempty name for the request, progress and Stop', async () => {
  const { ctx, field, run } = workspace();
  run('currentRect = {}');
  ctx.rectBounds = () => ({ s: 0, w: 0, n: 1, e: 1 });
  ctx.readScale = () => 1;
  ctx.settingsForRequest = ctx.selectionShape = ctx.sketchGeoJSON = () => ({});
  ctx.fx = { step() {}, overlay: { show() {} } };
  ctx.stopProgress = () => {};
  const stops = [], progress = [], requests = [];
  ctx.showStop = name => stops.push(name);
  ctx.startProgress = name => progress.push(name);
  ctx.wasStopped = () => true;
  ctx.fx.overlay.hide = ctx.fx.toast = () => {};
  ctx.fetch = async (_, options) => {
    requests.push(JSON.parse(options.body).mapName);
    return { json: async () => ({}) };
  };
  for (const [typed, expected] of [
    ['Город', /^knoxmap_\d+$/], ['', /^knoxmap_\d+$/], ['___', /^knoxmap_\d+$/],
    ['Town_42-west', /^Town_42-west$/], ['East Город 2', /^East_2$/],
  ]) {
    field('mapName').value = typed;
    await ctx.runGenerate({ skipBigConfirm: true });
    const name = field('mapName').value;
    assert.match(name, expected);
    assert.equal(requests.at(-1), name);
    assert.equal(progress.at(-1), name);
    assert.deepEqual(stops.slice(-2), [name, null]);
  }
});

test('opening a draft discards a pending map response', async () => {
  const { ctx, field, run } = workspace();
  run(fs.readFileSync(path.join(__dirname, '../../static/js/settings.js'), 'utf8'));
  run("currentMap = 'A'; openedMap = { mapName: 'A' }");
  field('mapName').value = field('boardName').value = 'A';
  const rendered = [];
  let finish;
  ctx.fetch = () => new Promise(resolve => { finish = resolve; });
  ctx.renderResults = data => rendered.push(data.mapName);
  ctx.loadZones = () => {};
  ctx.loadSketchGeoJSON = () => {};
  const opening = ctx.openMap('A');
  ctx.clearOpenedMap();
  finish({ ok: true, json: async () => ({ mapName: 'A' }) });
  await opening;
  assert.deepEqual(rendered, []);
  assert.equal(run('currentMap'), null);
  assert.equal(run('openedMap'), null);
  assert.equal(field('mapName').value, '');
  assert.equal(field('boardName').value, '');
  assert.equal(field('upgradeNote').hidden, true);
  assert.equal(field('reapply').hidden, true);

  // A portable preset keeps the exact values that its sliders rounded for display.
  run('importedSettings = { settings: { density: 0.18 }, shown: { density: 0.2 } }');
  ctx.readSettings = () => ({ density: 0.2 });
  ctx.clearOpenedMap();
  assert.equal(ctx.settingsForRequest().density, 0.18);
});
