const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

test('Leaflet and both basemaps give attribution links their own browser tab', () => {
  const prefix = '<a href="https://leafletjs.com" title="Leaflet"><svg></svg> Leaflet</a>';
  const links = [];
  const handlers = {};
  const map = {
    attributionControl: { options: { prefix }, setPrefix(html) { links.push(html); } },
    eachLayer() {},
    on() {},
  };
  const context = vm.createContext({
    document: { addEventListener() {}, querySelectorAll() { return []; } },
    window: { addEventListener(event, handler) { handlers[event] = handler; } },
    map,
    L: {
      Draw: { Event: { CREATED: 'draw:created' } },
      tileLayer(_url, options) {
        links.push(options.attribution);
        return { addTo() {} };
      },
    },
  });
  const script = path.join(__dirname, '..', '..', 'static', 'js', 'fx.js');
  vm.runInContext(fs.readFileSync(script, 'utf8'), context);
  handlers.load();

  assert.equal(links.length, 3);
  assert.match(links[0], /https:\/\/leafletjs\.com/);
  assert.match(links[0], /<svg><\/svg> Leaflet/);
  for (const html of links.slice(1)) {
    assert.match(html, /https:\/\/www\.openstreetmap\.org\/copyright/);
    assert.match(html, /contributors/);
  }
  for (const html of links) {
    assert.match(html, /<a [^>]*target="_blank"/);
    assert.match(html, /<a [^>]*rel="noopener noreferrer"/);
  }
});
