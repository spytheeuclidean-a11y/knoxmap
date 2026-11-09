// What `new Function(source)` in the CI step cannot see: a name the page never
// defines. A typo'd global is not a syntax error, so the page loads, the
// handler throws on click, and only a human notices. `no-undef` catches it.
//
// No plugins and no `globals` package on purpose: the config has to work with
// nothing but `npm ci`, and the list of names the page may use is short enough
// to write down. Adding a browser API to static/js means adding it here too -
// which is the reminder that it is a browser API and not a KnoxMap one.
module.exports = [
  {
    files: ['static/js/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      // Scripts, not modules: index.html loads them in order and they share
      // globals through `window`.
      sourceType: 'script',
      globals: {
        // Libraries loaded by index.html before app.js.
        L: 'readonly',
        // The DOM and the browser.
        window: 'readonly',
        document: 'readonly',
        navigator: 'readonly',
        location: 'readonly',
        localStorage: 'readonly',
        fetch: 'readonly',
        console: 'readonly',
        alert: 'readonly',
        confirm: 'readonly',
        prompt: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        requestAnimationFrame: 'readonly',
        cancelAnimationFrame: 'readonly',
        getComputedStyle: 'readonly',
        MutationObserver: 'readonly',
        ResizeObserver: 'readonly',
        IntersectionObserver: 'readonly',
        Node: 'readonly',
        HTMLElement: 'readonly',
        Event: 'readonly',
        CustomEvent: 'readonly',
        DOMParser: 'readonly',
        URL: 'readonly',
        URLSearchParams: 'readonly',
        FormData: 'readonly',
        Blob: 'readonly',
        File: 'readonly',
        FileReader: 'readonly',
        Image: 'readonly',
        performance: 'readonly',
        structuredClone: 'readonly',
        crypto: 'readonly',
        // The browser's own CSS object: CSS.escape is used by the windows.
        CSS: 'readonly',

        // The page's own cross-script globals. index.html loads app.js,
        // shell.js, fx.js, i18n.js and draw.js into one window, in that order,
        // and they share state by name - `map`, `currentMap`, `drawWorld` and
        // friends are declared in app.js and read from shell.js. ESLint checks
        // one file at a time, so without this list every such reference is an
        // undefined name. Declared writable because the windows assign them.
        // Adding one here is deliberate: it is the page's public surface, not a
        // place to silence a typo.
        map: 'writable',
        currentMap: 'writable',
        currentRect: 'writable',
        runningMap: 'writable',
        stoppingMap: 'writable',
        drawnItems: 'writable',
        sketchLayer: 'writable',
        sketchCount: 'writable',
        zoneLayer: 'writable',
        editLayer: 'writable',
        landmarkMarkers: 'writable',
        SEL_STYLE: 'writable',
        loadMaps: 'writable',
        refreshMyMaps: 'writable',
        openMap: 'writable',
        deleteMap: 'writable',
        drawWorld: 'writable',
        drawZoneList: 'writable',
        renderResults: 'writable',
        runSearch: 'writable',
        requestStop: 'writable',
        sayIfInstallable: 'writable',
        setSelection: 'writable',
        clearBboxFields: 'writable',
        removeRotateHandle: 'writable',
        closeTab: 'writable',
        note: 'writable',
        fx: 'writable',
        i18n: 'writable',
        // Assigned as window.KnoxDraw at the bottom of draw.js.
        KnoxDraw: 'writable',
      },
    },
    rules: {
      'no-undef': 'error',
      // An unused parameter is usually a callback signature, so only flag
      // variables that are declared and never read.
      // Callbacks and `catch (_)` use parameters they never read on purpose:
      // the position is the argument, not the name.
      'no-unused-vars': ['error', { args: 'none', caughtErrors: 'none' }],
    },
  },
];
