// Run: node --test backend/tests/frontend/test_recap_print_theme.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const read = file => fs.readFileSync(path.join(__dirname, '../..', file), 'utf8');
const base = read('templates/base.html');
const recap = read('templates/recap.html');
const css = [read('static/style.css'), read('static/filterin-modern.css'),
  base.match(/<style>([\s\S]*?)<\/style>/)[1],
  recap.match(/<style>([\s\S]*?)<\/style>/)[1]].join('\n');
let playwright;
try { playwright = require(process.env.FILTERIN_PLAYWRIGHT_PATH || 'playwright'); } catch (_) {}

test('recap prints the same light colors from either theme and preserves screen preference',
  {skip: !playwright && 'Playwright not installed'}, async () => {
    const browser = await playwright.chromium.launch({headless: true,
      ...(process.env.FILTERIN_BROWSER_CHANNEL ? {channel: process.env.FILTERIN_BROWSER_CHANNEL} : {})});
    try {
      const page = await browser.newPage();
      // Real application styles, synthetic report data; no live server or services.
      await page.route('**/*', route => route.fulfill({contentType: 'text/html', body: `
        <!doctype html><html><head><style>${css}</style></head><body>
        <div class="content-wrapper"><div class="recap-page">
        <div class="recap-section"><div class="recap-section-title" style="background:#0b3d91;color:#fff">Report</div>
        <div class="summary-grid"><div class="summary-item"><span class="s-label">Total</span><span class="s-value s-green">3</span></div></div>
        <table class="recap-table"><thead><tr><th>Data</th><th>Total</th></tr></thead><tbody>
        <tr><td class="td-label">A</td><td class="td-total">1</td></tr>
        <tr><td>B</td><td>2</td></tr><tr><td class="td-grand">Total</td><td class="td-grand">3</td></tr>
        </tbody></table></div>
        <div class="recap-section tati-section"><table class="recap-table"><thead><tr><th>TATI</th></tr></thead>
        <tbody><tr><td class="td-total">3</td></tr><tr><td class="td-grand">3</td></tr></tbody></table></div>
        <div class="wilayah-card"><div class="wilayah-card-header">Wilayah</div><div class="wilayah-card-body">
        <div class="wilayah-item"><span class="wi-label">Label</span><span class="wi-count">3</span><div class="wi-orders">Order</div></div></div></div>
        <div class="odp-section"><table class="recap-table"><thead><tr><th>ODP</th></tr></thead><tbody><tr><td>Data</td></tr></tbody></table></div>
        <button class="btn-export-pdf">Export</button></div></div></body></html>`}));
      await page.goto('http://filterin.test/recap');
      const paint = () => page.evaluate(() => Array.from(document.querySelectorAll(
        'html, body, .content-wrapper, .recap-section, .recap-section-title, th, td, .summary-item, .s-label, .s-value, .wilayah-card, .wilayah-card-header, .wilayah-card-body, .wilayah-item, .wi-label, .wi-count, .wi-orders'
      ), el => { const s = getComputedStyle(el); return [s.backgroundColor, s.color, s.borderColor, s.colorScheme]; }));
      let lightPrint;
      for (const theme of ['light', 'dark']) {
        await page.emulateMedia({media: 'screen'});
        await page.evaluate(theme => {
          document.documentElement.dataset.theme = theme;
          localStorage.setItem('filterin-theme', theme);
        }, theme);
        // Finish the existing screen transition before comparing screen snapshots.
        await page.waitForTimeout(350);
        const screen = await paint();
        const data = await page.locator('.recap-page').innerText();
        await page.emulateMedia({media: 'print'});
        const printed = await paint();
        assert.equal(printed[0][0], 'rgb(255, 255, 255)');
        assert.equal(printed[0][3], 'light');
        assert.equal(await page.locator('.btn-export-pdf').isVisible(), false);
        if (theme === 'light') lightPrint = printed;
        else assert.deepEqual(printed, lightPrint, 'Dark mode must not change printed report colors');
        // Returning from either print or cancel must restore the unchanged screen theme.
        await page.emulateMedia({media: 'screen'});
        await page.waitForTimeout(350);
        assert.deepEqual(await paint(), screen);
        assert.equal(await page.locator('.recap-page').innerText(), data);
        assert.deepEqual(await page.evaluate(() => [document.documentElement.dataset.theme,
          localStorage.getItem('filterin-theme')]), [theme, theme]);
      }
    } finally { await browser.close(); }
  });
