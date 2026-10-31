// No browser or extra packages: exercise the actual language loader and matcher.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');

function dictionary(file) {
  const result = {};
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    if (line.trim().startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq < 0) continue;
    const key = line.slice(0, eq).trim(), value = line.slice(eq + 1).trim();
    if (key && value && key !== value) result[key] = value;
  }
  return result;
}

const russian = dictionary(path.join(root, 'lang', 'russian.txt'));
let reply = russian;
let reloads = 0;
const text = { nodeType: 3, nodeValue: 'reading the map data: 11,763,000 tagged nodes and ways checked' };
const context = vm.createContext({
  Node: { TEXT_NODE: 3, ELEMENT_NODE: 1 },
  document: { addEventListener() {}, body: { nodeType: 1, childNodes: [text] } },
  MutationObserver: class { observe() {} disconnect() {} },
  window: { location: { reload() { reloads++; } } },
  fetch: async () => ({ ok: true, json: async () => ({ strings: reply }) }),
});
vm.runInContext(fs.readFileSync(path.join(root, 'static', 'js', 'i18n.js'), 'utf8'), context);

(async () => {
  await vm.runInContext("i18n.use('russian', false)", context);
  const t = s => vm.runInContext(`i18n.t(${JSON.stringify(s)})`, context);
  assert.equal(t('Shape area'), 'Площадь фигуры');
  assert.equal(t('Map area'), 'Площадь карты');
  assert.equal(t('Map data source set to auto'), 'Источник данных карты: auto');
  assert.equal(t('Map data source set to Auto'), 'Источник данных карты: Авто');
  assert.equal(text.nodeValue, 'Читаю данные карты: проверено 11,763,000 точек с тегами и линий');
  assert.equal(t('  reading the map data  '), '  Читаю данные карты  ');
  assert.equal(t('downloading the Volga (test) extract from Geofabrik, 50 of 777 MB'),
               'Скачиваю регион Volga (test) с Geofabrik: 50 из 777 МБ');
  assert.equal(t('the Overpass servers are busy — waiting 45s, then trying again (2 of 3)'),
               'Серверы Overpass заняты — подожду 45 с и повторю запрос (попытка 2 из 3)');
  assert.equal(t('Lookup failed: invalid Overpass JSON: missing elements list'),
               'Не удалось найти объекты: неверный ответ Overpass: отсутствует список объектов elements');
  assert.equal(t('"https://host/$&/x" is not an http(s) server address.'),
               '«https://host/$&/x» — неверный адрес сервера HTTP(S).');
  assert.equal(t('<img src=x onerror=alert(1)>'), '<img src=x onerror=alert(1)>');
  assert.equal(t('Unknown English message'), 'Unknown English message');
  reply = {};
  await vm.runInContext("i18n.use('english', true)", context);
  assert.equal(t('Map data source set to auto'), 'Map data source set to auto');
  assert.equal(reloads, 1);
  console.log('i18n template checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
