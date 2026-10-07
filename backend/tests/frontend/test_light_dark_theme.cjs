// Run: node --test backend/tests/frontend/test_light_dark_theme.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const template = fs.readFileSync(path.join(__dirname, '../../templates/base.html'), 'utf8');
const bootstrap = template.match(/<script id="filterin-theme-init">([\s\S]*?)<\/script>/)[1];
const core = fs.readFileSync(path.join(__dirname, '../../static/filterin-core.js'), 'utf8');
const theme = core.slice(core.indexOf('  // ---------- Dark mode'), core.indexOf('  // ---------- Loading overlay'));

function setup(saved, blocked = false) {
  let current = 'light', click, ready;
  const writes = [];
  const classes = new Set();
  const label = {textContent: ''};
  const icon = {classList: {remove: (...names) => names.forEach(n => classes.delete(n)), add: n => classes.add(n)}};
  const document = {
    documentElement: {setAttribute: (_, value) => {current = value;}, getAttribute: () => current},
    getElementById: id => ({'theme-label': label, 'theme-icon': icon,
      'theme-toggle-btn': {addEventListener: (_, fn) => {click = fn;}}}[id]),
    addEventListener: (_, fn) => {ready = fn;},
  };
  const localStorage = {
    getItem(key) {assert.equal(key, 'filterin-theme'); if (blocked) throw Error('blocked'); return saved;},
    setItem(key, value) {if (blocked) throw Error('blocked'); writes.push([key, value]);},
  };
  const ctx = vm.createContext({document, localStorage});
  vm.runInContext(bootstrap, ctx);
  return {get current() {return current;}, label, classes, writes,
    loadCore() {vm.runInContext(theme, ctx); ready();},
    toggle() {click({preventDefault() {}});}};
}

test('theme bootstrap and canvas colors precede external styles and body', () => {
  const index = template.indexOf('id="filterin-theme-init"');
  assert.ok(index < template.indexOf('<link rel="stylesheet"'));
  assert.ok(index < template.indexOf('<body'));
  assert.match(template.slice(0, template.indexOf('<body')), /html\[data-theme="dark"\].*background-color: #0f1624; color-scheme: dark/);
});

for (const [saved, expected] of [['dark', 'dark'], ['light', 'light'], [null, 'light'], ['invalid', 'light']]) {
  test(`saved theme ${saved} is applied before core loads and retained afterwards`, () => {
    const ctx = setup(saved);
    assert.equal(ctx.current, expected);
    ctx.loadCore();
    assert.equal(ctx.current, expected);
    assert.deepEqual(ctx.writes, []);
    assert.equal(ctx.label.textContent, expected === 'dark' ? 'Light Mode' : 'Dark Mode');
  });
}

test('theme toggle works both ways and persists across navigation', () => {
  const ctx = setup('light');
  ctx.loadCore();
  ctx.toggle();
  assert.equal(ctx.current, 'dark');
  assert.ok(ctx.classes.has('fa-sun'));
  const next = setup(ctx.writes.at(-1)[1]);
  assert.equal(next.current, 'dark');
  next.loadCore();
  next.toggle();
  assert.equal(next.current, 'light');
  assert.ok(next.classes.has('fa-moon'));
  assert.deepEqual(next.writes, [['filterin-theme', 'light']]);
});

test('blocked storage does not stop page initialization or theme toggle', () => {
  const ctx = setup('dark', true);
  assert.equal(ctx.current, 'light');
  ctx.loadCore();
  ctx.toggle();
  assert.equal(ctx.current, 'dark');
  ctx.toggle();
  assert.equal(ctx.current, 'light');
});

let playwright;
try { playwright = require(process.env.FILTERIN_PLAYWRIGHT_PATH || 'playwright'); } catch (_) {}
test('browser paints saved theme while footer script is still loading, including navigation',
  {skip: !playwright && 'Playwright not installed'}, async () => {
    const browser = await playwright.chromium.launch({headless: true,
      ...(process.env.FILTERIN_BROWSER_CHANNEL ? {channel: process.env.FILTERIN_BROWSER_CHANNEL} : {})});
    try {
      const page = await browser.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const criticalStyle = template.match(/<style>([\s\S]*?)<\/style>/)[1];
      const css = fs.readFileSync(path.join(__dirname, '../../static/filterin-modern.css'), 'utf8');
      let release;
      await page.route('**/*', async route => {
        if (new URL(route.request().url()).pathname === '/core.js') {
          await new Promise(resolve => {release = resolve;});
          return route.fulfill({contentType: 'text/javascript', body: `(function(){${theme}})();`});
        }
        return route.fulfill({contentType: 'text/html', body: `<!doctype html><html data-theme="light"><head>
          <script>${bootstrap}</script><style>${criticalStyle}\n${css}</style></head><body>
          <button id="theme-toggle-btn"><span id="theme-label"></span><i id="theme-icon"></i></button>
          <div id="content">FilterIN</div><script src="/core.js"></script></body></html>`});
      });
      await page.addInitScript(() => {
        if (!localStorage.getItem('filterin-theme')) localStorage.setItem('filterin-theme', 'dark');
      });
      for (const [url, expected, color] of [
        ['/dashboard', 'dark', 'rgb(15, 22, 36)'],
        ['/kpi', 'dark', 'rgb(15, 22, 36)'],
        ['/recap', 'light', 'rgb(245, 247, 250)'],
      ]) {
        const navigation = page.goto('http://filterin.test' + url);
        await page.waitForSelector('#content');
        const paint = await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve({
          theme: document.documentElement.dataset.theme,
          root: getComputedStyle(document.documentElement).backgroundColor,
          body: getComputedStyle(document.body).backgroundColor,
          ready: document.readyState,
        })))));
        assert.equal(paint.theme, expected);
        assert.equal(paint.root, color);
        assert.equal(paint.body, color);
        assert.equal(paint.ready, 'loading');
        release();
        await navigation;
        if (url === '/kpi') {
          await page.click('#theme-toggle-btn');
          assert.equal(await page.evaluate(() => localStorage.getItem('filterin-theme')), 'light');
        }
      }
      assert.deepEqual(errors, []);
    } finally { await browser.close(); }
  });
