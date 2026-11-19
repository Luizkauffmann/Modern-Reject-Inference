/* Modern Reject Inference – browser demo runtime.
   Runs the unchanged Python backend of the Explorer in Pyodide (Python compiled to WebAssembly) and
   routes the page's /api calls to it, so the whole app works in the page: no server, and no data
   leaves the browser. Copyright 2026 Luiz Kauffmann – Apache License 2.0. */
(function () {
  'use strict';
  var PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';
  var READY = 'Ready · everything runs in your browser – no data leaves this page';
  var py = null, backend = null, haveSklearn = false;

  function status(text, err) {
    var s = document.getElementById('mriStatus');
    if (s) { s.textContent = text; s.className = 'mri-status' + (err ? ' err' : ''); }
    var m = document.querySelector('#mriLoading .msg');
    if (m) m.textContent = text;
  }
  function download(name, text) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
  }

  // The Explorer's front end calls fetch('/api/...'): answer those calls with Python.
  var nativeFetch = window.fetch.bind(window);
  window.fetch = function (url, opt) {
    if (typeof url !== 'string' || url.indexOf('/api/') !== 0) return nativeFetch(url, opt);
    return new Promise(function (resolve, reject) {
      setTimeout(async function () {     // let the page repaint ("Working…") before Python runs
        try {
          if (url === '/api/lasso' && !haveSklearn) {   // only the lasso needs scikit-learn (a decision tree)
            status('Loading scikit-learn for the lasso (one time, about 20 MB)…');
            await py.loadPackage('scikit-learn');
            haveSklearn = true; status(READY);
          }
          var out = backend.dispatch(url, (opt && opt.body) || null);
          var r = out.toJs(); out.destroy();
          if (url === '/api/export' && r[1] === 200) {   // no server to save on: hand the strategy tree to the user
            try {
              var j = JSON.parse(r[0]);
              if (j.ok) download(j.name + '.json', py.FS.readFile('/app/strategies/trees/' + j.name + '.json', { encoding: 'utf8' }));
            } catch (e) { console.error(e); }
          }
          resolve(new Response(r[0], { status: r[1], headers: { 'Content-Type': r[2] } }));
        } catch (e) { reject(e); }
      }, 30);
    });
  };

  async function text(path) {
    var r = await nativeFetch(path);
    if (!r.ok) throw new Error('Could not load ' + path + ' (' + r.status + ')');
    return r.text();
  }

  window.MRI = {
    start: async function () {
      try {
        status('Starting Python in your browser (the first visit downloads about 15 MB, then it is cached)…');
        py = await loadPyodide({ indexURL: PYODIDE });
        status('Loading numpy and pandas…');
        await py.loadPackage(['numpy', 'pandas']);
        status('Loading the app…');
        py.FS.mkdirTree('/app/data');
        py.FS.writeFile('/app/flask.py', await text('py/flask.py'));
        py.FS.writeFile('/app/demo_backend.py', await text('py/demo_backend.py'));
        py.FS.writeFile('/app/explorer.py', await text('app/explorer.py'));
        status('Loading the synthetic sample (20,000 applications)…');
        py.FS.writeFile('/app/data/ri_scored.csv', await text('data/ri_scored.csv'));
        py.FS.writeFile('/app/data/ri_map.csv', await text('data/ri_map.csv'));
        py.runPython("import os, sys\nos.environ['RI_DATA_DIR'] = '/app/data'\nos.environ['RI_STRATEGY_DIR'] = '/app/strategies'\nsys.path.insert(0, '/app')\nimport demo_backend\ndemo_backend.register('explorer')");
        backend = py.globals.get('demo_backend');
        status('Computing the overview…');
        var css = document.createElement('link'); css.rel = 'stylesheet'; css.href = 'app/ui/app.css'; document.head.appendChild(css);
        document.getElementById('root').innerHTML = await text('app/ui/index.html');
        new Function(await text('app/ui/app.js'))();
        status(READY);
      } catch (e) {
        console.error(e);
        status('Could not start the demo: ' + e.message, true);
      }
    }
  };
})();
