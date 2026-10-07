// Run: node --test backend/tests/frontend/test_dashboard_cache_status.cjs
// Dashboard cache UI, using intercepted requests only; no live services.
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
let playwright, browser;
try { playwright = require(process.env.FILTERIN_PLAYWRIGHT_PATH || 'playwright'); } catch (_) {}
before(async () => {
  if (playwright) browser = await playwright.chromium.launch({headless: true,
    ...(process.env.FILTERIN_BROWSER_CHANNEL ? {channel: process.env.FILTERIN_BROWSER_CHANNEL} : {})});
});
after(async () => { if (browser) await browser.close(); });
const script = fs.readFileSync(path.join(__dirname, '../../static/cache-status.js'), 'utf8');
const template = fs.readFileSync(path.join(__dirname, '../../templates/dashboard.html'), 'utf8');
const panel = template.match(/<div class="cache-panel"[\s\S]*?<\/details>\s*<\/div>/)[0]
  .replace(/{%[\s\S]*?%}/g, '');
const css = [...template.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n');
const baseCSS = fs.readFileSync(path.join(__dirname, '../../static/style.css'), 'utf8').replace(/^\s*@import[^\r\n]+/gm, '');
const themeCSS = fs.readFileSync(path.join(__dirname, '../../static/filterin-modern.css'), 'utf8');
function snapshot(refresh = null) {
  return {cache: ['Kendala Master', 'UNSC', 'TTI', 'FFG', 'TTR FFG'].map(sheet_name => ({
    sheet_name, status: 'stale', age_seconds: 120, fetched_at: '21/09/2026 17:00:00'})),
    refresh, automatic: {running: true, interval_seconds: 300,
      next_run_at: '2026-09-21T17:05:00+07:00', server_time: '2026-09-21T17:01:36+07:00'}};
}
function check(name, fn) {
  test(name, {skip: !playwright && 'Playwright not installed'}, async () => {
    const page = await browser.newPage({viewport: {width: 1000, height: 650}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    try { await fn(page); assert.deepEqual(errors, []); } finally { await page.close(); }
  });
}
async function fixture(page, data = snapshot(), operator = false) {
  const state = {data, status: 200, posts: 0, gets: 0, postStatus: 200,
    accepted: {status: 'accepted', run_id: null, previous_run_id: 'old'}};
  await page.addInitScript(() => {
    window.cacheClock = 0;
    Object.defineProperty(performance, 'now', {value: () => window.cacheClock});
    const originalInterval = window.setInterval;
    window.setInterval = function (fn, ms, ...args) {
      if (ms === 1000) { window.cacheTick = () => fn(...args); return 900002; }
      return originalInterval(fn, ms, ...args);
    };
    const original = window.setTimeout;
    window.setTimeout = function (fn, ms, ...args) {
      if (ms === 2000 || ms === 30000) { window.cachePoll = () => fn(...args); return 900001; }
      return original(fn, ms, ...args);
    };
  });
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/dashboard') {
      const markup = operator ? panel.replace(/<button[\s\S]*?<\/button>/, '') : panel;
      return route.fulfill({contentType: 'text/html', body: `<!doctype html><html><head><style>${baseCSS}\n${themeCSS}\n${css}</style></head>
        <body><div class="dash-wrap"><div class="dash-greeting"><h1>Dashboard FilterIN</h1>${markup}</div></div>
        <script>${script}</script></body></html>`});
    }
    if (url.pathname === '/api/cache_status') {
      state.gets++;
      return route.fulfill({status: state.status, json: state.data});
    }
    if (url.pathname === '/api/cache_refresh') {
      state.posts++;
      return route.fulfill({status: state.postStatus, json: state.accepted});
    }
    throw new Error('Unexpected request: ' + url.pathname);
  });
  await page.goto('http://filterin.test/dashboard');
  await page.waitForFunction(() => Boolean(window.cachePoll));
  return state;
}
const badge = page => page.locator('#cache-status-badge');
async function poll(page) { await page.evaluate(() => window.cachePoll()); }

check('expired read TTL alone is not a failed update; details show source timestamps', async page => {
  await fixture(page);
  assert.match(await badge(page).innerText(), /Data tersedia/);
  assert.equal(await badge(page).getAttribute('data-tone'), 'neutral');
  for (const selector of ['#cache-status-badge', '#btn-refresh-cache', '.cache-details summary']) {
    assert.equal(await page.locator(selector).evaluate(el => getComputedStyle(el).fontWeight), '600');
  }
  await page.locator('summary').click();
  assert.equal(await page.locator('#cache-source-list li').count(), 5);
  assert.match(await page.locator('#cache-schedule').innerText(), /aktif setiap 5 menit/);
  assert.match(await page.locator('#cache-source-list').innerText(), /21\/09\/2026 17:00:00/);
  if (process.env.FILTERIN_CACHE_SCREENSHOT) await page.screenshot({path: process.env.FILTERIN_CACHE_SCREENSHOT});
});

check('manual update waits for a new completed run, never old success or an eight-second timer', async page => {
  const state = await fixture(page, snapshot({run_id: 'old', state: 'complete', cached: 5, total: 5, items: []}));
  await page.locator('#btn-refresh-cache').click();
  await page.waitForFunction(() => document.getElementById('cache-status-badge').textContent.includes('Menunggu'));
  for (let i = 0; i < 6; i++) await poll(page);
  assert.equal(await page.locator('#btn-refresh-cache').isDisabled(), true);
  assert.match(await badge(page).innerText(), /Menunggu/);
  state.data.refresh = {run_id: 'new', state: 'running', total: 5, items: [{sheet_name: 'Kendala Master', status: 'saved'}]};
  await poll(page);
  assert.match(await badge(page).innerText(), /Sedang mengambil data terbaru \(1\/5\)/);
  state.data.refresh = {run_id: 'new', state: 'complete', cached: 5, total: 5, items: []};
  await poll(page);
  assert.match(await badge(page).innerText(), /5\/5 sumber berhasil/);
  assert.equal(await page.locator('#btn-refresh-cache').isDisabled(), false);
  assert.equal(state.posts, 1);
});

check('partial failure exposes the actual failed source', async page => {
  await fixture(page, snapshot({state: 'partial', cached: 4, total: 5,
    items: [{sheet_name: 'UNSC', status: 'cache_failed'}]}));
  assert.match(await badge(page).innerText(), /4\/5 berhasil/);
  await page.locator('summary').click();
  assert.match(await page.locator('#cache-source-list').innerText(), /salinan gagal disimpan/);
});

check('missing cache is not falsely reported as an active loading job', async page => {
  const data = snapshot(); data.cache[0].status = 'missing';
  await fixture(page, data);
  assert.match(await badge(page).innerText(), /belum tersedia/);
  assert.equal(await page.locator('#btn-refresh-cache').isDisabled(), false);
});

check('service failure and interrupted runs do not show success', async page => {
  const state = await fixture(page);
  state.status = 503; state.data = {error: 'unavailable'};
  await poll(page);
  assert.match(await badge(page).innerText(), /belum dapat diperiksa/);
  state.status = 200; state.data = snapshot({state: 'interrupted', items: []});
  await poll(page);
  assert.match(await badge(page).innerText(), /terhenti/);
});

check('operator has details but no administrative refresh; source labels are escaped', async page => {
  const data = snapshot(); data.cache[0].sheet_name = '<img src=x onerror=alert(1)>';
  const state = await fixture(page, data, true);
  assert.equal(await page.locator('#btn-refresh-cache').count(), 0);
  assert.equal(await page.locator('img').count(), 0);
  assert.equal(state.posts, 0);
});

check('post failure restores control and explains uncertainty', async page => {
  const state = await fixture(page);
  state.postStatus = 503; state.accepted = {status: 'error'};
  await page.locator('#btn-refresh-cache').click();
  await page.waitForFunction(() => document.getElementById('cache-status-badge').textContent.includes('belum dapat dikonfirmasi'));
  assert.equal(await page.locator('#btn-refresh-cache').isDisabled(), false);
});

check('old copies and inactive local scheduler are disclosed', async page => {
  const data = snapshot(); data.cache[0].age_seconds = 1200; data.automatic.running = false;
  await fixture(page, data);
  assert.match(await badge(page).innerText(), /lebih dari 10 menit/);
  await page.locator('summary').click();
  assert.match(await page.locator('#cache-schedule').innerText(), /belum terkonfirmasi/);
});

check('cache controls and all badge states stay readable across live light/dark switches', async page => {
  await fixture(page, snapshot({run_id: 'done', state: 'complete', cached: 5, total: 5, items: []}));
  const contrast = (fg, bg) => {
    const luminance = color => color.match(/[\d.]+/g).slice(0, 3).map(Number).map(v => {
      v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
    }).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
    const a = luminance(fg), b = luminance(bg);
    return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
  };
  for (const theme of ['light', 'dark', 'light']) {
    await page.evaluate(value => document.documentElement.dataset.theme = value, theme);
    for (const disabled of [false, true]) {
      const colors = await page.locator('#btn-refresh-cache').evaluate((el, value) => {
        el.disabled = value;
        const style = getComputedStyle(el);
        return {fg: style.color, bg: style.backgroundColor, opacity: style.opacity};
      }, disabled);
      assert.equal(colors.opacity, '1');
      assert.ok(contrast(colors.fg, colors.bg) >= 4.5, JSON.stringify({theme, disabled, colors}));
      if (theme === 'dark') assert.notEqual(colors.bg, 'rgb(255, 255, 255)');
    }
    for (const tone of ['neutral', 'ok', 'busy', 'warning']) {
      const colors = await badge(page).evaluate((el, value) => {
        el.dataset.tone = value;
        const style = getComputedStyle(el);
        return {fg: style.color, bg: style.backgroundColor};
      }, tone);
      assert.ok(contrast(colors.fg, colors.bg) >= 4.5, JSON.stringify({theme, tone, colors}));
    }
  }
  await page.evaluate(() => {
    document.documentElement.dataset.theme = 'dark';
    document.getElementById('cache-status-badge').dataset.tone = 'ok';
    document.getElementById('btn-refresh-cache').disabled = false;
  });
  if (process.env.FILTERIN_CACHE_DARK_SCREENSHOT) {
    await page.locator('summary').click();
    await page.screenshot({path: process.env.FILTERIN_CACHE_DARK_SCREENSHOT, animations: 'disabled'});
  }
});

async function tick(page, milliseconds) {
  await page.evaluate(elapsed => { window.cacheClock += elapsed; window.cacheTick(); }, milliseconds);
}

check('countdown uses server schedule, ticks locally, and keeps source timestamps', async page => {
  const state = await fixture(page);
  await page.locator('summary').click();
  const schedule = page.locator('#cache-schedule');
  assert.match(await schedule.innerText(), /Berikutnya dalam 03:24/);
  const originalSources = await page.locator('#cache-source-list').innerText();
  const originalGets = state.gets;
  await tick(page, 1000);
  assert.match(await schedule.innerText(), /03:23/);
  await tick(page, 60000);
  assert.match(await schedule.innerText(), /02:23/);
  assert.equal(state.gets, originalGets);
  assert.equal(await page.locator('#cache-source-list').innerText(), originalSources);
});

check('zero countdown waits for backend confirmation instead of inventing a running job', async page => {
  const state = await fixture(page);
  await page.locator('summary').click();
  await tick(page, 204000);
  assert.match(await page.locator('#cache-schedule').innerText(), /Menunggu proses/);
  assert.equal(await page.locator('#btn-refresh-cache').isDisabled(), false);
  state.data.refresh = {run_id: 'auto', trigger: 'automatic', state: 'running', total: 5, items: []};
  await poll(page);
  assert.match(await page.locator('#cache-schedule').innerText(), /otomatis sedang berjalan/);
  state.data.refresh = {run_id: 'auto', trigger: 'automatic', state: 'complete', total: 5, cached: 5, items: []};
  state.data.automatic.server_time = '2026-09-21T17:05:10+07:00';
  state.data.automatic.next_run_at = '2026-09-21T17:10:00+07:00';
  await poll(page);
  assert.match(await page.locator('#cache-schedule').innerText(), /04:50/);
});

check('manual refresh and page reload do not reset the automatic schedule to five minutes', async page => {
  const state = await fixture(page);
  await page.locator('summary').click();
  state.data.refresh = {run_id: 'manual', trigger: 'manual', state: 'running', total: 5, items: []};
  state.data.automatic.server_time = '2026-09-21T17:02:00+07:00';
  await poll(page);
  assert.match(await page.locator('#cache-schedule').innerText(), /03:00/);
  await page.reload();
  await page.waitForFunction(() => Boolean(window.cachePoll));
  await page.locator('summary').click();
  assert.match(await page.locator('#cache-schedule').innerText(), /03:00/);
});

check('invalid schedule and status failure stop the countdown without extra requests', async page => {
  const state = await fixture(page);
  await page.locator('summary').click();
  state.data.automatic.next_run_at = 'invalid';
  await poll(page);
  assert.match(await page.locator('#cache-schedule').innerText(), /berikutnya belum tersedia/);
  state.status = 503;
  await poll(page);
  const gets = state.gets;
  await tick(page, 60000);
  assert.match(await page.locator('#cache-schedule').innerText(), /belum dapat diperiksa/);
  assert.equal(state.gets, gets);
});
