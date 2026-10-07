// Isolated browser regression tests. No Flask, MySQL, or Google Sheets requests.
// npm install --no-save playwright (or set FILTERIN_PLAYWRIGHT_PATH to an existing installation)
// FILTERIN_BROWSER_CHANNEL can select an installed browser, e.g. msedge.
// Run: node --test backend/tests/frontend/test_quick_edit_and_table_refresh.cjs
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
let playwright;
try { playwright = require(process.env.FILTERIN_PLAYWRIGHT_PATH || 'playwright'); } catch (_) {}
let browser;
before(async () => {
  if (playwright) browser = await playwright.chromium.launch({headless: true,
    ...(process.env.FILTERIN_BROWSER_CHANNEL ? {channel: process.env.FILTERIN_BROWSER_CHANNEL} : {})});
});
after(async () => { if (browser) await browser.close(); });
const coreSource = fs.readFileSync(path.join(__dirname, '../../static/filterin-core.js'), 'utf8');
const controller = coreSource.slice(coreSource.indexOf('/* ========================================================='));
const template = fs.readFileSync(path.join(__dirname, '../../templates/kendalamaster.html'), 'utf8');
const tableCSS = [...template.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n');
const row = key => ({ORDER_ID: key, WONUM: 'WO-' + key, 'NOTES ASO': 'Lama', 'ACTUAL KENDALA': '',
  'FEEDBACK ASO': '', 'TGL FEEDBACK': '', IS_ACTIVE_KENDALA: 'ACTIVE'});
const storageKey = 'filterin:recent-saves:/kendala_master';
function browserTest(name, fn) {
  test(name, {skip: !playwright && 'Playwright is not installed'}, async () => {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    try { await fn(page); assert.deepEqual(errors, []); } finally { await page.close(); }
  });
}
async function fixture(page, overrides = {}, initialStorage) {
  const calls = [];
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    calls.push(url.pathname);
    if (url.pathname === '/kendala_master') {
      await route.fulfill({contentType: 'text/html', body: `<!doctype html><html><head><style>${tableCSS}</style></head><body>
        <table class="editable-table"><tbody>${['A', 'B'].map((key, i) => `<tr data-order-id="${key}" data-row-num="${i + 3}">
          <td class="col-edit-sticky">${i + 1}<input name="__snapshot__[${i + 3}]" type="hidden"></td>
          <td data-col="ORDER_ID">${key}</td>
          <td data-col="NOTES ASO"><input name="NOTES ASO[${i + 3}]" value="Lama"></td>
          <td class="col-edit-sticky"><button class="btn-row-edit">Edit</button></td></tr>`).join('')}</tbody></table>
        <div class="controls-bar"></div></body></html>`});
      return;
    }
    if (overrides[url.pathname]) return overrides[url.pathname](route);
    const data = ['/lock', '/unlock', '/renew-lock'].includes(url.pathname) ? {ok: true, ttl_seconds: 300}
      : url.pathname.startsWith('/kendala_row/') ? {row: row(url.pathname.endsWith('/3') ? 'A' : 'B')}
      : url.pathname.startsWith('/order_history/') ? {history: []}
      : url.pathname === '/update_kendala_row' ? {ok: true, updated: 1, row_token: 'fresh-token'} : null;
    if (data === null) throw new Error('Unexpected request: ' + url.pathname);
    await route.fulfill({json: data});
  });
  await page.goto('http://filterin.test/kendala_master');
  if (initialStorage) await page.evaluate(([key, value]) => sessionStorage.setItem(key, JSON.stringify(value)), [storageKey, initialStorage]);
  await loadController(page);
  return calls;
}
async function loadController(page) {
  await page.evaluate(() => {
    window.toasts = [];
    window.toast = (...args) => window.toasts.push(args);
    window.showLoading = window.hideLoading = () => {};
    window.escapeHtml = text => String(text).replace(/[<>&"']/g, '');
  });
  await page.addScriptTag({content: controller});
  await page.evaluate(() => window.initQuickEdit({feedback_options: [], actual_options: []}));
}
async function save(page) {
  await page.evaluate(() => window.openQuickEdit(3, 'A'));
  await page.locator('#qe-notes').fill('Baru');
  await page.evaluate(() => window.saveQuickEdit());
}
function deferred() {
  let resolve;
  const promise = new Promise(r => {resolve = r;});
  return {promise, resolve};
}

async function frozenClock(page) {
  await page.clock.install({time: new Date('2026-09-17T00:00:00Z')});
  await page.clock.pauseAt(new Date('2026-09-17T00:00:01Z'));
}

// Load the shared script and the actual inline button handlers together.
// Keeping both in this fixture detects duplicate DOM click handlers.
function kendalaPollCode(revision = 'initial') {
  const start = template.indexOf('const kendalaRevision =');
  const end = template.indexOf('// 12. PAGINATION JUMP', start);
  return template.slice(start, end).replace("{{ data_revision|default('')|tojson }}", JSON.stringify(revision));
}

async function automationFixture(page, withPolling = false) {
  const template = fs.readFileSync(path.join(__dirname, '../../templates/kendalamaster.html'), 'utf8');
  const shared = fs.readFileSync(path.join(__dirname, '../../static/script.js'), 'utf8');
  const sync = template.slice(template.indexOf('async function triggerSyncBima()'), template.indexOf('window.cancelSync ='));
  const move = template.slice(template.indexOf('async function triggerMoveUnsc()'), template.indexOf('window.cancelMove ='));
  const buttons = ['syncButton', 'moveUnscButton'].map(id => {
    const match = template.match(new RegExp('<button id="' + id + '"[^>]*>[\\s\\S]*?</button>'));
    assert.ok(match, 'Missing automation button: ' + id);
    return match[0];
  }).join('');
  const visits = [];
  await page.route('**/*', route => {
    visits.push(route.request().url());
    return route.fulfill({contentType: 'text/html', body: `<!doctype html>
    <html><body>${buttons}<div id="syncStatus"></div><div id="moveUnscStatus"></div>
    <button id="cancelSyncButton"></button><button id="cancelMoveButton"></button>
    <div class="table-container"><table class="editable-table"><tbody>
      <tr id="old-row" data-row-num="3"><td>1</td><td id="today-value" data-col="ORDER_DATE"></td>
        <td data-col="ACTUAL KENDALA"><select id="edit-cell"><option>ODP JAUH</option></select></td></tr>
      <tr id="new-row" data-row-num="4" class="is-new-row"><td>2<span class="badge-new">NEW</span></td><td>01/01/2020</td></tr>
    </tbody></table></div>
    <script>
      window.requests = [];
      window.fetch = async (url, options = {}) => {
        window.requests.push({url, method: options.method});
        if (url.startsWith('/kendala_data')) return {ok: true, json: async () => ({revision: 'initial'})};
        return {json: async () => ({status: 'error', message: 'Fixture: no data written'})};
      };
      const now = new Date();
      document.getElementById('today-value').textContent =
        String(now.getDate()).padStart(2, '0') + '/' + String(now.getMonth()+1).padStart(2, '0') + '/' + now.getFullYear();
      let syncAbortController = null, moveAbortController = null;
      ${sync}
      ${move}
      ${withPolling ? `let isEditing = false;
        document.querySelector('.table-container').addEventListener('focusin', () => {isEditing = true;});
        document.querySelector('.table-container').addEventListener('focusout', () => {isEditing = false;});
        ${kendalaPollCode()}
        setInterval(fetchUpdates, 10000);` : ''}
      ${shared}
    </script></body></html>`});
  });
  await page.goto('http://filterin.test/kendala_master');
  return visits;
}

for (const [button, endpoint] of [['syncButton', '/sync-bima'], ['moveUnscButton', '/move-to-unsc']]) {
  for (const accepted of [false, true]) {
    browserTest(`${button}: confirmation ${accepted ? 'OK sends exactly one request' : 'Cancel sends no request'}`, async page => {
      await automationFixture(page);
      let dialogs = 0;
      page.on('dialog', async dialog => {
        dialogs++;
        await (accepted ? dialog.accept() : dialog.dismiss());
      });
      await page.locator('#' + button).click();
      assert.equal(dialogs, 1);
      assert.deepEqual(await page.evaluate(() => window.requests), accepted ? [{url: endpoint, method: 'POST'}] : []);
    });
  }
}

browserTest('shared script never infers NEW from dates or duplicates the server badge', async page => {
  await automationFixture(page);
  assert.equal(await page.locator('#old-row').evaluate(el => el.classList.contains('is-new-row')), false);
  assert.equal(await page.locator('#old-row .new-badge, #old-row .badge-new').count(), 0);
  assert.equal(await page.locator('#new-row').evaluate(el => el.classList.contains('is-new-row')), true);
  assert.equal(await page.locator('#new-row .new-badge, #new-row .badge-new').count(), 1);
  // Simulate a rerender after "mark seen": today's date must not restore NEW.
  await page.locator('#new-row').evaluate(el => {
    el.classList.remove('is-new-row');
    el.querySelector('.badge-new').remove();
    el.lastElementChild.textContent = document.getElementById('today-value').textContent;
  });
  await page.evaluate(() => document.dispatchEvent(new Event('DOMContentLoaded')));
  assert.equal(await page.locator('#old-row .new-badge, #old-row .badge-new').count(), 0);
  assert.equal(await page.locator('#new-row .new-badge, #new-row .badge-new').count(), 0);
  assert.equal(await page.locator('#new-row').evaluate(el => el.classList.contains('is-new-row')), false);
});

for (const accepted of [false, true]) {
  browserTest(`UNSC ${accepted ? 'OK' : 'Cancel'} after leaving an edit cell never loops reload for unchanged data`, async page => {
    await page.clock.install();
    const visits = await automationFixture(page, true);
    page.on('dialog', async dialog => { await (accepted ? dialog.accept() : dialog.dismiss()); });
    await page.locator('#edit-cell').focus();
    await page.clock.fastForward(10000);
    assert.equal(await page.evaluate(() => window.requests.length), 0);
    await page.locator('#moveUnscButton').click();
    for (let i = 0; i < 3; i++) {
      await page.clock.fastForward(10000);
      await page.evaluate(() => new Promise(resolve => queueMicrotask(resolve)));
    }
    const requests = await page.evaluate(() => window.requests);
    assert.equal(requests.filter(r => r.url === '/move-to-unsc').length, accepted ? 1 : 0);
    assert.equal(requests.filter(r => r.url.startsWith('/kendala_data')).length, 3);
    assert.equal(visits.length, 1, 'Only the initial page load is allowed');
  });
}

browserTest('slow data shows loading, hides empty context and disables all edit controls', async page => {
  const pending = deferred();
  await fixture(page, {'/kendala_row/3': async route => {await pending.promise; await route.fulfill({json: {row: row('A')}});}});
  await page.evaluate(() => {window.opening = window.openQuickEdit(3, 'A');});
  assert.equal(await page.locator('#qe-load-status').isVisible(), true);
  assert.equal(await page.locator('#qe-content').isVisible(), false);
  assert.equal(await page.locator('#qe-btn-save').isDisabled(), true);
  assert.equal(await page.locator('#qe-form :is(input, select, textarea):disabled').count(), 5);
  pending.resolve();
  await page.evaluate(() => window.opening);
  assert.equal(await page.locator('#qe-content').isVisible(), true);
  assert.equal(await page.locator('#qe-load-status').isVisible(), false);
  assert.equal(await page.locator('#qe-ctx-order-id').textContent(), 'A');
  assert.equal(await page.locator('#qe-btn-save').isEnabled(), true);
});

browserTest('row loading failure stays noneditable and retry loads fresh values', async page => {
  let attempts = 0;
  await fixture(page, {'/kendala_row/3': route => route.fulfill({json: ++attempts === 1 ? {error: 'Layanan sementara gagal'} : {row: row('A')}})});
  await page.evaluate(() => window.openQuickEdit(3, 'A'));
  assert.match(await page.locator('#qe-load-text').textContent(), /Layanan sementara gagal/);
  assert.equal(await page.locator('#qe-retry').isVisible(), true);
  assert.equal(await page.locator('#qe-content').isVisible(), false);
  assert.equal(await page.locator('#qe-btn-save').isDisabled(), true);
  await page.evaluate(() => window.retryQuickEdit());
  assert.equal(await page.locator('#qe-notes').inputValue(), 'Lama');
  assert.equal(await page.locator('#qe-btn-save').isEnabled(), true);
});

browserTest('lock owned by another user leaves loaded data read-only', async page => {
  await fixture(page, {'/lock': route => route.fulfill({status: 409, json: {ok: false, locked_by: 'other', locked_at: 'now'}})});
  await page.evaluate(() => window.openQuickEdit(3, 'A'));
  assert.equal(await page.locator('#qe-content').isVisible(), true);
  assert.equal(await page.locator('#qe-lock-warning').isVisible(), true);
  assert.equal(await page.locator('#qe-form :is(input, select, textarea):disabled').count(), 5);
  assert.equal(await page.locator('#qe-btn-save').isDisabled(), true);
});

browserTest('switching rows ignores delayed data from the previous modal', async page => {
  const pending = deferred();
  const entered = deferred();
  await fixture(page, {'/kendala_row/3': async route => {entered.resolve(); await pending.promise; await route.fulfill({json: {row: row('A')}});}});
  await page.evaluate(() => {window.oldOpening = window.openQuickEdit(3, 'A');});
  await entered.promise;
  await page.evaluate(() => window.openQuickEdit(4, 'B'));
  pending.resolve();
  await page.evaluate(() => window.oldOpening);
  assert.equal(await page.locator('#qe-ctx-order-id').textContent(), 'B');
  assert.equal(await page.locator('#qe-notes').inputValue(), 'Lama');
});

browserTest('closing before lock acquisition completes releases that lock in order', async page => {
  const pending = deferred();
  const entered = deferred();
  const calls = await fixture(page, {'/lock': async route => {entered.resolve(); await pending.promise; await route.fulfill({json: {ok: true}});}});
  await page.evaluate(() => {window.opening = window.openQuickEdit(3, 'A');});
  await entered.promise;
  await page.evaluate(() => {window.closing = window.closeQuickEdit();});
  pending.resolve();
  await page.evaluate(() => Promise.all([window.opening, window.closing]));
  assert.deepEqual(calls.filter(p => ['/lock', '/unlock'].includes(p)), ['/lock', '/unlock']);
  assert.equal(calls.includes('/kendala_row/3'), false);
  assert.equal(await page.locator('#qe-modal').evaluate(el => el.classList.contains('show')), false);
});

browserTest('successful save marks the correct row with a visible border and badge for fifteen seconds', async page => {
  await fixture(page);
  await frozenClock(page);
  await save(page);
  assert.equal(await page.locator('tr[data-order-id="A"]').evaluate(el => el.classList.contains('row-just-saved')), true);
  assert.equal(await page.locator('tr[data-order-id="B"]').evaluate(el => el.classList.contains('row-just-saved')), false);
  assert.equal(await page.locator('.qe-saved-badge').textContent(), '✓ Baru disimpan');
  const style = await page.locator('tr[data-order-id="A"] td').first().evaluate(el => ({shadow: getComputedStyle(el).boxShadow, image: getComputedStyle(el).backgroundImage}));
  assert.match(style.shadow, /inset/);
  assert.match(style.image, /linear-gradient/);
  assert.equal(await page.locator('[name="NOTES ASO[3]"]').inputValue(), 'Baru');
  assert.equal(await page.locator('[name="__snapshot__[3]"]').inputValue(), 'fresh-token');
  await page.clock.fastForward(14999);
  assert.equal(await page.locator('.row-just-saved').count(), 1);
  await page.clock.fastForward(1);
  assert.equal(await page.locator('.row-just-saved').count(), 0);
  assert.equal(await page.locator('.qe-saved-badge').count(), 0);
});

browserTest('failed save never highlights a row or changes its displayed values', async page => {
  await fixture(page, {'/update_kendala_row': route => route.fulfill({status: 409, json: {ok: false, error: 'Konflik data'}})});
  await save(page);
  assert.equal(await page.locator('.row-just-saved').count(), 0);
  assert.equal(await page.locator('[name="NOTES ASO[3]"]').inputValue(), 'Lama');
  assert.equal(await page.locator('#qe-btn-save').isEnabled(), true);
  assert.equal(await page.locator('#qe-notes').isEnabled(), true);
});

browserTest('saving prevents switching or closing the current order until the response arrives', async page => {
  const pending = deferred();
  const entered = deferred();
  await fixture(page, {'/update_kendala_row': async route => {entered.resolve(); await pending.promise; await route.fulfill({json: {ok: true, updated: 1}});}});
  await page.evaluate(() => window.openQuickEdit(3, 'A'));
  await page.locator('#qe-notes').fill('Baru');
  await page.evaluate(() => {window.saving = window.saveQuickEdit();});
  await entered.promise;
  await page.evaluate(async () => {await window.closeQuickEdit(); await window.openQuickEdit(4, 'B');});
  assert.equal(await page.locator('#qe-ctx-order-id').textContent(), 'A');
  assert.equal(await page.locator('#qe-notes').isDisabled(), true);
  pending.resolve();
  await page.evaluate(() => window.saving);
  assert.equal(await page.locator('.row-just-saved').getAttribute('data-order-id'), 'A');
});

browserTest('highlight is restored after reload by ORDER_ID without restarting its expiry', async page => {
  await fixture(page);
  await save(page);
  const expiry = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).A, storageKey);
  await page.reload();
  // Simulate changed sheet positions between page loads.
  await page.locator('tr[data-order-id="A"]').evaluate(el => {el.dataset.rowNum = '40';});
  await loadController(page);
  assert.equal(await page.locator('.row-just-saved').getAttribute('data-order-id'), 'A');
  assert.equal(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).A, storageKey), expiry);
});

browserTest('expired marker does not reappear', async page => {
  await fixture(page, {}, {A: Date.now() - 1});
  assert.equal(await page.locator('.row-just-saved').count(), 0);
});

browserTest('a second save of the same row resets the timer without duplicate badges', async page => {
  await fixture(page);
  await frozenClock(page);
  await save(page);
  await page.clock.fastForward(10000);
  await save(page);
  assert.equal(await page.locator('.qe-saved-badge').count(), 1);
  await page.clock.fastForward(5000);
  assert.equal(await page.locator('.row-just-saved').count(), 1);
  await page.clock.fastForward(10000);
  assert.equal(await page.locator('.row-just-saved').count(), 0);
});

browserTest('delayed history for a closed order cannot overwrite the new order history', async page => {
  const pending = deferred();
  const entered = deferred();
  const finished = deferred();
  await fixture(page, {'/order_history/A': async route => {
    entered.resolve(); await pending.promise;
    await route.fulfill({json: {history: [{timestamp: 'yesterday', username: 'old-user', old_value: '', new_value: 'OLD HISTORY'}]}});
    finished.resolve();
  }});
  await page.evaluate(() => window.openQuickEdit(3, 'A'));
  await entered.promise;
  await page.evaluate(() => window.openQuickEdit(4, 'B'));
  await page.locator('#qe-history-list').getByText('Belum ada riwayat perubahan untuk order ini.').waitFor();
  pending.resolve();
  await finished.promise;
  await page.waitForLoadState('networkidle');
  assert.doesNotMatch(await page.locator('#qe-history-list').textContent(), /OLD HISTORY/);
});

browserTest('saved marker is independent of visible editable inputs and works without session storage', async page => {
  await fixture(page);
  await page.evaluate(() => {
    document.querySelector('[name="NOTES ASO[3]"]').remove();
    Storage.prototype.setItem = () => {throw new Error('Storage blocked');};
  });
  await save(page);
  assert.equal(await page.locator('.row-just-saved').getAttribute('data-order-id'), 'A');
  assert.equal(await page.locator('tr[data-order-id="A"] td:last-child .qe-saved-badge').count(), 1);
});

browserTest('non-JSON loading response keeps stale data hidden and exposes retry', async page => {
  await fixture(page, {'/kendala_row/3': route => route.fulfill({status: 503, contentType: 'text/html', body: 'Unavailable'})});
  await page.evaluate(() => window.openQuickEdit(3, 'A'));
  assert.equal(await page.locator('#qe-content').isVisible(), false);
  assert.equal(await page.locator('#qe-retry').isVisible(), true);
  assert.equal(await page.locator('#qe-btn-save').isDisabled(), true);
});

test('automatic refresh protects the saved marker both before and after an in-flight poll', async () => {
  const vm = require('node:vm');
  const poll = kendalaPollCode();
  let highlighted = true;
  let fetched = 0;
  let reloaded = 0;
  let finish;
  const ctx = {isEditing: false, syncAbortController: null, moveAbortController: null,
    URLSearchParams, window: {location: {search: ''}},
    location: {reload: () => reloaded++},
    document: {querySelector: () => highlighted ? {} : null, querySelectorAll: () => []},
    fetch: () => {fetched++; return new Promise(resolve => {finish = () => resolve({ok: true, json: async () => ({revision: 'changed'})});});}};
  vm.runInNewContext(poll, ctx);
  ctx.fetchUpdates();
  assert.equal(fetched, 0);
  highlighted = false;
  ctx.fetchUpdates();
  assert.equal(fetched, 1);
  highlighted = true;
  finish();
  await new Promise(setImmediate);
  assert.equal(reloaded, 0);
  highlighted = false;
  ctx.fetchUpdates();
  finish();
  await new Promise(setImmediate);
  assert.equal(reloaded, 1);
});

test('poll revisions ignore display formatting and failed responses, and reload once for real changes', async () => {
  const vm = require('node:vm');
  let reloaded = 0, fetched = 0, finish;
  const ctx = {isEditing: false, syncAbortController: null, moveAbortController: null,
    URLSearchParams, window: {location: {search: ''}}, location: {reload: () => reloaded++},
    document: {querySelector: () => null, querySelectorAll: () => {throw Error('Must not compare formatted cells');}},
    fetch: () => {fetched++; return new Promise(resolve => {finish = resolve;});}};
  vm.runInNewContext(kendalaPollCode(), ctx);
  for (const response of [
    {ok: true, json: async () => ({revision: 'initial'})},
    {ok: false, json: async () => ({revision: 'changed'})},
    {ok: true, json: async () => ({error: 'unavailable'})},
    {ok: true, json: async () => {throw Error('not JSON');}},
  ]) {
    ctx.fetchUpdates();
    const count = fetched;
    ctx.fetchUpdates();
    assert.equal(fetched, count, 'No overlapping poll');
    finish(response);
    await new Promise(setImmediate);
    assert.equal(reloaded, 0);
  }
  ctx.fetchUpdates();
  finish({ok: true, json: async () => ({revision: 'changed'})});
  await new Promise(setImmediate);
  assert.equal(reloaded, 1);
  const count = fetched;
  ctx.fetchUpdates();
  assert.equal(fetched, count, 'Do not start another poll while reloading');
});

browserTest('active modal renews its lease and stops after closing', async page => {
  const calls = await fixture(page);
  await frozenClock(page);
  await page.evaluate(() => window.openQuickEdit(3, 'A'));
  const renewed = page.waitForResponse('**/renew-lock');
  await page.clock.fastForward(30000);
  await renewed;
  await page.waitForFunction(() => !document.getElementById('qe-btn-save').disabled);
  assert.equal(calls.filter(p => p === '/renew-lock').length, 1);
  await page.evaluate(() => window.closeQuickEdit());
  await page.clock.fastForward(60000);
  assert.equal(calls.filter(p => p === '/renew-lock').length, 1);
});

browserTest('lost lease preserves draft, blocks saving and requires explicit reacquisition', async page => {
  let available = false;
  const calls = await fixture(page, {'/renew-lock': route => route.fulfill({status: available ? 200 : 409,
    json: {ok: available, error: 'Hak edit berakhir'}})});
  await frozenClock(page);
  await page.evaluate(() => window.openQuickEdit(3, 'A'));
  await page.locator('#qe-notes').fill('Draft saya');
  await page.clock.fastForward(30000);
  await page.locator('#qe-lock-warning').waitFor({state: 'visible'});
  assert.equal(await page.locator('#qe-notes').inputValue(), 'Draft saya');
  assert.equal(await page.locator('#qe-btn-save').isDisabled(), true);
  await page.evaluate(() => window.saveQuickEdit());
  assert.equal(calls.includes('/update_kendala_row'), false);
  available = true;
  await page.evaluate(() => window.recheckQuickEditLock());
  assert.equal(await page.locator('#qe-notes').inputValue(), 'Draft saya');
  assert.equal(await page.locator('#qe-btn-save').isEnabled(), true);
});

browserTest('save checks ownership even before the next renewal timer and never writes on renewal failure', async page => {
  const calls = await fixture(page, {'/renew-lock': route => route.fulfill({status: 503, json: {ok: false, error: 'Layanan tidak tersedia'}})});
  await save(page);
  assert.equal(calls.includes('/renew-lock'), true);
  assert.equal(calls.includes('/update_kendala_row'), false);
  assert.equal(await page.locator('#qe-notes').inputValue(), 'Baru');
  assert.equal(await page.locator('#qe-btn-save').isDisabled(), true);
});

browserTest('two user sessions cannot take each others lock; a stale draft is rejected after the owner saves', async first => {
  const second = await browser.newPage();
  let owner = null;
  let sharedNote = 'Lama';
  const endpoints = user => ({
    '/lock': route => {
      if (owner === null || owner === user) owner = user;
      return route.fulfill({json: {ok: owner === user, locked_by: owner, ttl_seconds: 300}});
    },
    '/renew-lock': route => route.fulfill({status: owner === user ? 200 : 409, json: {ok: owner === user}}),
    '/unlock': route => {if (owner === user) owner = null; return route.fulfill({json: {ok: true}});},
    '/kendala_row/3': route => route.fulfill({json: {row: {...row('A'), 'NOTES ASO': sharedNote}}}),
    '/update_kendala_row': route => {
      const body = route.request().postDataJSON();
      if (owner !== user || body.original_values['NOTES ASO'] !== sharedNote) {
        return route.fulfill({status: 409, json: {ok: false, error: 'NOTES ASO telah berubah. Muat ulang data.'}});
      }
      sharedNote = body.updates['NOTES ASO']; owner = null;
      return route.fulfill({json: {ok: true, updated: 1}});
    }
  });
  try {
    await fixture(first, endpoints('User A'));
    await fixture(second, endpoints('User B'));
    await first.evaluate(() => window.openQuickEdit(3, 'A'));
    await second.evaluate(() => window.openQuickEdit(3, 'A'));
    assert.equal(await second.locator('#qe-btn-save').isDisabled(), true);
    await second.evaluate(() => window.recheckQuickEditLock());
    assert.equal(owner, 'User A');
    await first.locator('#qe-notes').fill('Disimpan A');
    await first.evaluate(() => window.saveQuickEdit());
    await second.evaluate(() => window.recheckQuickEditLock());
    await second.locator('#qe-notes').fill('Draft B');
    await second.evaluate(() => window.saveQuickEdit());
    assert.equal(sharedNote, 'Disimpan A');
    assert.equal(await second.locator('#qe-notes').inputValue(), 'Draft B');
    assert.match(await second.evaluate(() => window.toasts.at(-1)[0]), /telah berubah/);
  } finally { await second.close(); }
});

async function inlineFixture(page, overrides = {}) {
  const calls = await fixture(page, overrides);
  await page.evaluate(() => {
    const table = document.querySelector('.editable-table');
    const form = document.createElement('form');
    form.action = '/update_kendala'; form.method = 'POST'; form.setAttribute('data-preserve-draft', '');
    table.before(form); form.appendChild(table);
    form.insertAdjacentHTML('afterbegin', '<div data-save-notice hidden></div><div id="inline-lock-notice" hidden></div>');
    document.querySelector('tr[data-order-id="A"] td[data-col="NOTES ASO"]').insertAdjacentHTML('beforeend',
      '<input name="TGL FEEDBACK[3]" value="old-date" readonly>');
  });
  await page.addScriptTag({content: coreSource.slice(0, coreSource.indexOf('/* ========================================================='))});
  const start = template.indexOf('function applyLockedStateToRow(');
  const end = template.indexOf('// Initial state pada page load', start);
  await page.addScriptTag({content: template.slice(start, end).replace(/\{%[\s\S]*?%\}/g, '')});
  await page.evaluate(() => document.dispatchEvent(new Event('DOMContentLoaded')));
  return calls;
}

browserTest('locked inline draft is retained, never silently omitted, and original readonly state is restored', async page => {
  const calls = await inlineFixture(page);
  await page.locator('[name="NOTES ASO[3]"]').fill('Draft tabel');
  await page.evaluate(() => {
    const tr = document.querySelector('tr[data-order-id="A"]');
    tr.classList.add('is-dirty'); window.applyLockedStateToRow(tr, 'Pengguna B');
    document.querySelector('form[data-preserve-draft]').requestSubmit();
  });
  assert.equal(calls.includes('/update_kendala'), false);
  assert.match(await page.locator('[data-save-notice]').textContent(), /Input Anda tetap/);
  assert.equal(await page.locator('[name="NOTES ASO[3]"]').inputValue(), 'Draft tabel');
  assert.equal(await page.locator('[name="__snapshot__[3]"]').isDisabled(), false);
  await page.evaluate(() => window.removeLockedStateFromRow(document.querySelector('tr[data-order-id="A"]')));
  assert.equal(await page.locator('[name="NOTES ASO[3]"]').isEnabled(), true);
  assert.equal(await page.locator('[name="TGL FEEDBACK[3]"]').evaluate(el => el.readOnly), true);
  assert.equal(await page.locator('#inline-lock-notice').isVisible(), false);
});

browserTest('server conflict on bulk save keeps the draft and sends only changed fields plus snapshot', async page => {
  let submitted;
  await inlineFixture(page, {'/update_kendala': route => {
    submitted = route.request().postData();
    return route.fulfill({status: 409, json: {ok: false, error: 'Data telah berubah'}});
  }});
  await page.locator('[name="NOTES ASO[3]"]').fill('Draft tetap ada');
  await page.evaluate(() => {
    document.querySelector('tr[data-order-id="A"]').classList.add('is-dirty');
    document.querySelector('form[data-preserve-draft]').requestSubmit();
  });
  await page.waitForFunction(() => document.querySelector('[data-save-notice]').textContent.includes('Data telah berubah'));
  assert.match(submitted, /name="NOTES ASO\[3\]"/);
  assert.match(submitted, /name="__snapshot__\[3\]"/);
  assert.doesNotMatch(submitted, /name="NOTES ASO\[4\]"/);
  assert.equal(await page.locator('[name="NOTES ASO[3]"]').inputValue(), 'Draft tetap ada');
  assert.equal(await page.locator('[name="NOTES ASO[3]"]').isEnabled(), true);
  assert.equal(await page.locator('tr.is-dirty').count(), 1);
  assert.equal(page.url(), 'http://filterin.test/kendala_master');
});

test('UNSC rechecks draft and focus state after an in-flight request before reloading', async () => {
  const vm = require('node:vm');
  const source = fs.readFileSync(path.join(__dirname, '../../templates/unsc.html'), 'utf8');
  const poll = source.match(/function fetchUpdates\(\) \{[\s\S]*?\n\}/)[0];
  for (const state of ['dirty', 'editing', 'saving', 'idle']) {
    let blocked = false, reloaded = 0, finish;
    const ctx = {isEditing: false, URLSearchParams, window: {location: {search: ''}},
      location: {reload: () => reloaded++},
      document: {querySelector: () => blocked ? {} : null, querySelectorAll: () => []},
      fetch: () => new Promise(resolve => {finish = () => resolve({json: async () => ({data: [['changed']], sheet_rows: [3]})});})};
    vm.runInNewContext(poll, ctx);
    ctx.fetchUpdates();
    if (state === 'editing') ctx.isEditing = true;
    if (state === 'dirty' || state === 'saving') blocked = true;
    finish(); await new Promise(setImmediate);
    assert.equal(reloaded, state === 'idle' ? 1 : 0);
  }
});

browserTest('bulk network failure restores controls and keeps unsaved input', async page => {
  await inlineFixture(page, {'/update_kendala': route => route.abort()});
  await page.locator('[name="NOTES ASO[3]"]').fill('Draft offline');
  await page.evaluate(() => {
    document.querySelector('tr[data-order-id="A"]').classList.add('is-dirty');
    document.querySelector('form[data-preserve-draft]').requestSubmit();
  });
  await page.waitForFunction(() => document.querySelector('[data-save-notice]').textContent.includes('Input tidak dihapus'));
  assert.equal(await page.locator('[name="NOTES ASO[3]"]').inputValue(), 'Draft offline');
  assert.equal(await page.locator('[name="NOTES ASO[3]"]').isEnabled(), true);
  assert.equal(await page.locator('tr.is-dirty').count(), 1);
});

browserTest('successful bulk save refreshes once and double submission sends only one write', async page => {
  const pending = deferred();
  const calls = await inlineFixture(page, {'/update_kendala': async route => {
    await pending.promise; await route.fulfill({json: {ok: true, updated: 1}});
  }});
  await page.locator('[name="NOTES ASO[3]"]').fill('Saved');
  await page.evaluate(() => {
    const form = document.querySelector('form[data-preserve-draft]');
    form.requestSubmit(); form.requestSubmit();
  });
  assert.equal(await page.locator('[name="NOTES ASO[3]"]').isDisabled(), true);
  const reloaded = page.waitForEvent('framenavigated', {predicate: frame => frame === page.mainFrame()});
  pending.resolve(); await reloaded;
  assert.equal(calls.filter(p => p === '/update_kendala').length, 1);
  assert.equal(calls.filter(p => p === '/kendala_master').length, 2);
});

browserTest('bulk audit warning preserves notice and updates snapshots for subsequent edits', async page => {
  await inlineFixture(page, {'/update_kendala': route => route.fulfill({json: {ok: true, updated: 1,
    audit_warning: true, row_tokens: {'3': 'new-signed-snapshot'}}})});
  await page.locator('[name="NOTES ASO[3]"]').fill('Saved with warning');
  await page.evaluate(() => {
    document.querySelector('tr[data-order-id="A"]').classList.add('is-dirty');
    document.querySelector('form[data-preserve-draft]').requestSubmit();
  });
  await page.waitForFunction(() => document.querySelector('[data-save-notice]').textContent.includes('Audit Log gagal'));
  assert.equal(await page.locator('[name="__snapshot__[3]"]').inputValue(), 'new-signed-snapshot');
  assert.equal(await page.locator('[name="NOTES ASO[3]"]').evaluate(el => el.dataset.initialValue), 'Saved with warning');
  assert.equal(await page.locator('tr.is-dirty').count(), 0);
});

browserTest('failed lock poll cannot unlock a row or enable its controls', async page => {
  await inlineFixture(page, {'/api/kendala_locks': route => route.fulfill({status: 503, json: {locks: {}, error: 'offline'}})});
  const start = template.indexOf('async function pollKendalaLocks()');
  const end = template.indexOf('// Polling setiap 10 detik', start);
  await page.addScriptTag({content: template.slice(start, end)});
  await page.evaluate(async () => {
    const tr = document.querySelector('tr[data-order-id="A"]');
    window.applyLockedStateToRow(tr, 'Pengguna lain');
    await window.pollKendalaLocks();
  });
  assert.equal(await page.locator('tr.row-locked-by-other').count(), 1);
  assert.equal(await page.locator('[name="NOTES ASO[3]"]').isDisabled(), true);
});
