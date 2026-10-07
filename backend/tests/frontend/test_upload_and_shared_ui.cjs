// Run: node --test backend/tests/frontend/test_upload_and_shared_ui.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../../static/filterin-core.js'), 'utf8')
  .split('/* =========================================================')[0];

function setup(root = '') {
  const requests = [];
  const listeners = [];
  const document = {
    querySelector: selector => selector.includes('csrf-token') ? {getAttribute: () => 'test-csrf'}
      : selector.includes('app-root') ? {content: root} : null,
    querySelectorAll: () => [],
    getElementById: () => null,
    documentElement: {setAttribute() {}, getAttribute: () => 'light'},
    addEventListener: (name, fn) => listeners.push(fn),
  };
  const window = {fetch: (url, opts) => {requests.push({url, opts}); return Promise.resolve({});}};
  vm.runInNewContext(code, {window, document, URL, location: {href: 'http://localhost/api/dashboard', origin: 'http://localhost'},
    localStorage: {getItem: () => null, setItem() {}}, setTimeout() {}});
  return {window, document, requests, listeners};
}

test('root deployment and mounted /api deployment generate correct API paths', () => {
  for (const root of ['', '/api']) {
    const ctx = setup(root);
    ctx.window.fetch('/heartbeat', {method: 'POST'});
    ctx.window.fetch('/api/online_count');
    assert.equal(ctx.requests[0].url, root + '/heartbeat');
    assert.equal(ctx.requests[1].url, root + '/api/online_count');
    assert.equal(ctx.requests[0].opts.headers['X-CSRFToken'], 'test-csrf');
  }
});

test('CSRF token is not attached to third-party requests', () => {
  const ctx = setup('/api');
  ctx.window.fetch('https://example.org/upload', {method: 'POST'});
  assert.equal(ctx.requests[0].opts.headers, undefined);
});

test('HTML text rendering escapes markup and quotes from audit values', () => {
  const ctx = setup();
  assert.equal(ctx.window.escapeHtml('<img src=x onerror="alert(1)">'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
  assert.equal(ctx.window.escapeHtml("'&"), '&#39;&amp;');
});

test('bulk submit sends only modified inputs and retains the snapshot', () => {
  const ctx = setup();
  const controls = [{value: 'same'}, {value: 'old'}, {value: 'computed', readOnly: true}];
  let submit;
  const form = {querySelector: () => ({}), querySelectorAll: () => controls,
    addEventListener: (event, handler) => {submit = handler;}};
  controls.forEach(el => {el.dataset = {};});
  ctx.document.querySelectorAll = selector => selector === 'form' ? [form] : [];
  ctx.listeners.forEach(fn => fn());
  controls[1].value = 'new';
  submit();
  assert.equal(controls[0].disabled, true);
  assert.equal(controls[1].disabled, undefined);
  assert.equal(controls[2].disabled, true);
});

function setupUpload(response, failure) {
  const template = fs.readFileSync(path.join(__dirname, '../../templates/upload.html'), 'utf8');
  const script = template.match(/<script>([\s\S]*?)<\/script>/)[1]
    .replace(/\{\{ url_for\("filter_data"\) \}\}/g, '/api/filter')
    .replace(/\{\{ url_for\("hapus_kolom"\) \}\}/g, '/api/hapus_kolom');
  const elements = new Map();
  const requests = [];
  const document = {
    getElementById(id) {
      if (!elements.has(id)) {
        const classes = new Set();
        elements.set(id, {value: id.includes('kelas') ? (id.endsWith('bima') ? '06' : '05') : '',
          files: [{name: 'report.xlsx', size: 100}], textContent: '', style: {},
          classList: {add: name => classes.add(name), remove: name => classes.delete(name),
            contains: name => classes.has(name)},
          addEventListener() {}, setAttribute() {}, scrollIntoView() {}});
      }
      return elements.get(id);
    },
    createElement: () => ({}), head: {appendChild() {}},
  };
  const window = {location: {origin: 'http://localhost', href: 'http://localhost/api/upload'}};
  const context = {window, document, URL, FormData: class {append() {}},
    fetch: (url, opts) => {
      requests.push({url, opts});
      return failure ? Promise.reject(new Error('offline')) : Promise.resolve(response);
    }};
  vm.runInNewContext(script, context);
  return {context, window, document, requests};
}

test('BIMA and KPRO reject PDF at submit without sending a request', () => {
  for (const kind of ['bima', 'kpro']) {
    const ctx = setupUpload();
    ctx.document.getElementById('file-' + kind).files = [{name: 'report.pdf'}];
    ctx.context.submitUpload(kind);
    assert.equal(ctx.requests.length, 0);
    assert.match(ctx.document.getElementById('err-' + kind + '-text').textContent, /Format file tidak valid/);
  }
});

test('server validation error stays visible and does not navigate or consume a redirect', async () => {
  const ctx = setupUpload({ok: false, headers: {get: () => 'application/json'},
    json: async () => ({success: false, message: 'File rusak; data lama tidak diubah.'})});
  ctx.context.submitUpload('kpro');
  await new Promise(setImmediate);
  assert.equal(ctx.window.location.href, 'http://localhost/api/upload');
  assert.match(ctx.document.getElementById('err-kpro-text').textContent, /File rusak/);
  assert.equal(ctx.document.getElementById('btn-kpro').disabled, false);
  assert.equal(ctx.requests[0].opts.headers.Accept, 'application/json');
});

test('successful upload navigates once using mounted backend URL', async () => {
  const ctx = setupUpload({ok: true, headers: {get: () => 'application/json'},
    json: async () => ({success: true, redirect_url: '/api/tabel?kelas=06'})});
  ctx.context.submitUpload('bima');
  await new Promise(setImmediate);
  assert.equal(ctx.requests.length, 1);
  assert.equal(ctx.requests[0].url, 'http://localhost/api/filter');
  assert.equal(ctx.window.location.href, '/api/tabel?kelas=06');
});

test('non-JSON auth or CSRF response does not look like upload success', async () => {
  const ctx = setupUpload({ok: false, headers: {get: () => 'text/html'}});
  ctx.context.submitUpload('bima');
  await new Promise(setImmediate);
  assert.equal(ctx.window.location.href, 'http://localhost/api/upload');
  assert.match(ctx.document.getElementById('err-bima-text').textContent, /belum dapat dikonfirmasi/);
});

test('network failure warns about uncertain result and restores submit button', async () => {
  const ctx = setupUpload(null, true);
  ctx.context.submitUpload('kpro');
  await new Promise(setImmediate);
  assert.match(ctx.document.getElementById('err-kpro-text').textContent, /belum dapat dipastikan/);
  assert.equal(ctx.document.getElementById('btn-kpro').disabled, false);
});

for (const role of ['admin', 'operator', 'viewer', 'unknown']) {
  test(`watchlist action buttons respect role and ownership: ${role}`, async () => {
    const template = fs.readFileSync(path.join(__dirname, '../../templates/dashboard.html'), 'utf8');
    const script = template.slice(template.indexOf('function loadWatchlist()'), template.indexOf('function openAddWatchlist('));
    for (const owner of ['tester', 'another-user', null]) {
      const list = {innerHTML: ''};
      const context = {
        CURRENT_USER: 'tester', IS_ADMIN: role === 'admin', CAN_WRITE: ['admin', 'operator'].includes(role),
        document: {getElementById: () => list}, window: {escapeHtml: value => String(value || '')},
        fetch: async () => ({json: async () => ({data: owner ? [{order_id: 'A', flagged_by: owner}] : []})}),
      };
      vm.runInNewContext(script, context);
      context.loadWatchlist();
      await new Promise(setImmediate);
      const canWrite = ['admin', 'operator'].includes(role);
      assert.equal(list.innerHTML.includes('onclick="openAddWatchlist()"'), canWrite);
      assert.equal(list.innerHTML.includes('onclick="confirmRemoveWatchlist('),
        Boolean(owner && canWrite && (role === 'admin' || owner === 'tester')));
    }
  });
}
