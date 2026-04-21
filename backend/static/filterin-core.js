/* FilterIN Core JS
 * - CSRF integration for fetch
 * - Dark mode toggle
 * - Global loading overlay helpers
 * - Quick Edit Modal controller (invoked from kendalamaster.html)
 */
(function () {
  const meta = document.querySelector('meta[name="csrf-token"]');
  window.FILTERIN_CSRF = meta ? meta.getAttribute('content') : '';

  // Wrap fetch to auto-include CSRF on non-GET same-origin requests
  const origFetch = window.fetch.bind(window);
  window.fetch = function (url, opts) {
    opts = opts || {};
    const method = (opts.method || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD') {
      opts.headers = opts.headers || {};
      if (typeof opts.headers.set === 'function') {
        if (!opts.headers.get('X-CSRFToken')) opts.headers.set('X-CSRFToken', window.FILTERIN_CSRF);
      } else {
        if (!opts.headers['X-CSRFToken']) opts.headers['X-CSRFToken'] = window.FILTERIN_CSRF;
      }
      opts.credentials = opts.credentials || 'same-origin';
    }
    return origFetch(url, opts);
  };

  // ---------- Dark mode ----------
  const THEME_KEY = 'filterin-theme';
  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem(THEME_KEY, t);
    const label = document.getElementById('theme-label');
    const icon = document.getElementById('theme-icon');
    if (label) label.textContent = t === 'dark' ? 'Light Mode' : 'Dark Mode';
    if (icon) {
      icon.classList.remove('fa-sun', 'fa-moon');
      icon.classList.add(t === 'dark' ? 'fa-sun' : 'fa-moon');
    }
  }
  applyTheme(localStorage.getItem(THEME_KEY) || 'light');
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) btn.addEventListener('click', (e) => {
      e.preventDefault();
      const cur = document.documentElement.getAttribute('data-theme');
      applyTheme(cur === 'dark' ? 'light' : 'dark');
    });
  });

  // ---------- Loading overlay ----------
  window.showLoading = function (text) {
    const o = document.getElementById('global-loading-overlay');
    const t = document.getElementById('global-loading-text');
    if (t && text) t.textContent = text;
    if (o) o.classList.add('show');
  };
  window.hideLoading = function () {
    const o = document.getElementById('global-loading-overlay');
    if (o) o.classList.remove('show');
  };

  // ---------- Toast notification ----------
  window.toast = function (msg, type) {
    type = type || 'info';
    let holder = document.querySelector('.flash-messages');
    if (!holder) {
      holder = document.createElement('div');
      holder.className = 'flash-messages';
      document.body.appendChild(holder);
    }
    const el = document.createElement('div');
    el.className = 'flash ' + type;
    el.innerHTML = '<span>' + msg + '</span><button class="flash-close" onclick="this.parentElement.remove()">&times;</button>';
    holder.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 350);
    }, 5000);
  };

  // ---------- Auto-dismiss flash after 5s ----------
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.flash').forEach((f, i) => {
      setTimeout(() => {
        if (f.parentNode) {
          f.style.opacity = '0';
          setTimeout(() => f.remove(), 400);
        }
      }, 5000 + i * 300);
    });
  });
})();


/* =========================================================
 * QUICK EDIT MODAL CONTROLLER
 * usage from HTML: window.openQuickEdit(rowNum, rowKey)
 * ========================================================= */
(function () {
  const SHEET_NAME = 'DB KENDALA (MASTER)';
  let currentRowNum = null;
  let currentRowKey = null;
  let modalEl = null;
  let feedbackOpts = [];
  let actualOpts = [];

  window.initQuickEdit = function (opts) {
    feedbackOpts = opts.feedback_options || [];
    actualOpts = opts.actual_options || [];
    buildModal();
  };

  function buildModal() {
    if (document.getElementById('qe-modal')) return;
    const html = `
      <div class="qe-modal-overlay" id="qe-modal" role="dialog" aria-modal="true" data-testid="qe-modal">
        <div class="modal-panel">
          <div class="qe-modal-header">
            <h2><i class="fa-solid fa-pen-to-square"></i> Edit Cepat Data Kendala</h2>
            <p class="qe-sub" id="qe-sub-title">Memuat…</p>
            <button type="button" class="qe-close" onclick="window.closeQuickEdit()" aria-label="Close" data-testid="qe-close">&times;</button>
          </div>
          <div class="qe-modal-body">
            <div id="qe-lock-warning" class="qe-lock-warning" style="display:none;">
              <i class="fa-solid fa-triangle-exclamation"></i>
              <span id="qe-lock-text">...</span>
            </div>
            <div class="qe-context-box">
              <h3><i class="fa-solid fa-circle-info"></i> Informasi Order (read-only)</h3>
              <div class="qe-context-grid">
                <div><span>Order ID</span><strong id="qe-ctx-order-id">—</strong></div>
                <div><span>WONUM</span><strong id="qe-ctx-wonum">—</strong></div>
                <div><span>Device ID</span><strong id="qe-ctx-device-id">—</strong></div>
                <div><span>STO / DATEL</span><strong id="qe-ctx-sto">—</strong></div>
                <div class="qe-context-emphasize">
                  <span>Sub Error Code (referensi utama)</span>
                  <strong id="qe-ctx-suberror">—</strong>
                </div>
                <div class="qe-context-emphasize">
                  <span>Engineer Memo (referensi utama)</span>
                  <strong id="qe-ctx-memo">—</strong>
                </div>
                <div><span>Status Resume</span><strong id="qe-ctx-status">—</strong></div>
                <div><span>Order Date</span><strong id="qe-ctx-odate">—</strong></div>
              </div>
            </div>

            <form id="qe-form" onsubmit="return false;">
              <div class="qe-form-group">
                <label for="qe-actual">Actual Kendala <span class="req">*</span></label>
                <select id="qe-actual" data-testid="qe-actual"></select>
              </div>
              <div class="qe-form-group">
                <label for="qe-feedback">Feedback ASO <span class="req">*</span></label>
                <select id="qe-feedback" data-testid="qe-feedback"></select>
              </div>
              <div class="qe-form-group">
                <label for="qe-tgl-fb">Tgl Feedback</label>
                <input type="text" id="qe-tgl-fb" placeholder="Otomatis terisi saat feedback diubah" data-testid="qe-tgl-fb">
              </div>
              <div class="qe-form-group">
                <label for="qe-notes">Notes ASO</label>
                <textarea id="qe-notes" rows="3" placeholder="Catatan tambahan..." data-testid="qe-notes"></textarea>
              </div>
              <div class="qe-form-group">
                <label for="qe-is-active">Is Active Kendala</label>
                <select id="qe-is-active" data-testid="qe-is-active">
                  <option value="">(otomatis)</option>
                  <option value="ACTIVE">ACTIVE</option>
                  <option value="INACTIVE">INACTIVE</option>
                </select>
              </div>
            </form>
          </div>
          <div class="qe-modal-footer">
            <div class="qe-footer-hint">
              Tekan <span class="kbd">Ctrl</span>+<span class="kbd">S</span> untuk simpan,
              <span class="kbd">Esc</span> untuk batal
            </div>
            <div class="qe-footer-actions">
              <button type="button" class="qe-btn qe-btn-cancel" onclick="window.closeQuickEdit()" data-testid="qe-btn-cancel">Batal</button>
              <button type="button" class="qe-btn qe-btn-save" id="qe-btn-save" onclick="window.saveQuickEdit()" data-testid="qe-btn-save">
                <i class="fa-solid fa-floppy-disk"></i> Simpan Perubahan
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
    const wrap = document.createElement('div');
    wrap.innerHTML = html;
    document.body.appendChild(wrap.firstElementChild);
    modalEl = document.getElementById('qe-modal');
    modalEl.addEventListener('click', (e) => { if (e.target === modalEl) window.closeQuickEdit(); });
    // ESC & Ctrl+S
    document.addEventListener('keydown', (e) => {
      if (!modalEl.classList.contains('show')) return;
      if (e.key === 'Escape') window.closeQuickEdit();
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault(); window.saveQuickEdit();
      }
    });

    // Auto-fill Tgl Feedback when Feedback ASO changes
    setTimeout(() => {
      const fb = document.getElementById('qe-feedback');
      fb.addEventListener('change', () => {
        const tgl = document.getElementById('qe-tgl-fb');
        if (!tgl.value) tgl.value = nowStr();
      });
    }, 0);

    // Populate dropdowns
    populate('qe-actual', actualOpts, true);
    populate('qe-feedback', feedbackOpts, true);
  }

  function populate(id, opts, prepend_blank) {
    const sel = document.getElementById(id);
    sel.innerHTML = '';
    if (prepend_blank) {
      const o = document.createElement('option'); o.value = ''; o.textContent = '-- Pilih --';
      sel.appendChild(o);
    }
    opts.forEach(v => {
      const o = document.createElement('option');
      o.value = v; o.textContent = v;
      sel.appendChild(o);
    });
  }

  function nowStr() {
    const n = new Date();
    const pad = x => String(x).padStart(2, '0');
    return `${pad(n.getDate())}/${pad(n.getMonth() + 1)}/${n.getFullYear()} ${pad(n.getHours())}:${pad(n.getMinutes())}`;
  }

  window.openQuickEdit = async function (rowNum, rowKey) {
    if (!modalEl) buildModal();
    currentRowNum = rowNum;
    currentRowKey = rowKey;
    document.getElementById('qe-sub-title').textContent = `Order ID: ${rowKey}  •  Baris #${rowNum}`;
    document.getElementById('qe-lock-warning').style.display = 'none';
    document.getElementById('qe-btn-save').disabled = false;
    modalEl.classList.add('show');

    try {
      // Acquire lock
      const lockRes = await (await fetch('/lock', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sheet_name: SHEET_NAME, row_key: rowKey })
      })).json();
      if (!lockRes.ok) {
        const warn = document.getElementById('qe-lock-warning');
        warn.style.display = 'flex';
        document.getElementById('qe-lock-text').textContent =
          `Row sedang diedit oleh ${lockRes.locked_by_nama || lockRes.locked_by} (sejak ${lockRes.locked_at}). Save dinonaktifkan untuk mencegah tabrakan.`;
        document.getElementById('qe-btn-save').disabled = true;
      }
      // Fetch row data
      const res = await (await fetch(`/kendala_row/${rowNum}`)).json();
      if (res.error) {
        window.toast('Gagal ambil data: ' + res.error, 'error');
        return;
      }
      fillForm(res.row || {});
    } catch (e) {
      window.toast('Error: ' + e.message, 'error');
    }
  };

  function fillForm(row) {
    const g = k => (row[k] != null ? String(row[k]) : '');
    document.getElementById('qe-ctx-order-id').textContent = g('ORDER_ID') || '—';
    document.getElementById('qe-ctx-wonum').textContent = g('WONUM') || '—';
    document.getElementById('qe-ctx-device-id').textContent = g('DEVICE_ID') || '—';
    const sto = g('STO'); const datel = g('DATEL');
    document.getElementById('qe-ctx-sto').textContent = (sto ? sto : '—') + (datel ? ` / ${datel}` : '');
    document.getElementById('qe-ctx-suberror').textContent = 
        g('SUB ERROR CODE') || g('SUBERRORCODE') || g('SUB_ERROR_CODE') || '—';
    document.getElementById('qe-ctx-memo').textContent = 
        g('ENGINEER MEMO') || g('ENGINEERMEMO') || g('ENGINEER_MEMO') || '—';
    document.getElementById('qe-ctx-status').textContent = g('STATUS_RESUME') || g('STATUS') || '—';
    document.getElementById('qe-ctx-odate').textContent = g('ORDER_DATE') || '—';

    document.getElementById('qe-actual').value = g('ACTUAL KENDALA');
    document.getElementById('qe-feedback').value = g('FEEDBACK ASO');
    document.getElementById('qe-tgl-fb').value = g('TGL FEEDBACK');
    document.getElementById('qe-notes').value = g('NOTES ASO');
    const ia = g('IS_ACTIVE_KENDALA');
    document.getElementById('qe-is-active').value = ['ACTIVE', 'INACTIVE'].includes(ia) ? ia : '';
  }

  window.closeQuickEdit = async function () {
    if (!modalEl) return;
    modalEl.classList.remove('show');
    if (currentRowKey) {
      try {
        await fetch('/unlock', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sheet_name: SHEET_NAME, row_key: currentRowKey })
        });
      } catch (_) {}
    }
    currentRowNum = null; currentRowKey = null;
  };

  window.saveQuickEdit = async function () {
    if (!currentRowNum) return;
    const btn = document.getElementById('qe-btn-save');
    if (btn.disabled) return;
    btn.disabled = true;
    const updates = {
      'ACTUAL KENDALA': document.getElementById('qe-actual').value,
      'FEEDBACK ASO':   document.getElementById('qe-feedback').value,
      'TGL FEEDBACK':   document.getElementById('qe-tgl-fb').value,
      'NOTES ASO':      document.getElementById('qe-notes').value,
    };
    const ia = document.getElementById('qe-is-active').value;
    if (ia) updates['IS_ACTIVE_KENDALA'] = ia;

    window.showLoading('Menyimpan ke Google Sheets…');
    try {
      const res = await (await fetch('/update_kendala_row', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          row_num: currentRowNum,
          row_key: currentRowKey,
          updates: updates
        })
      })).json();
      if (res.ok) {
        window.toast(`Berhasil menyimpan ${res.updated} kolom untuk Order ${currentRowKey}`, 'success');
        modalEl.classList.remove('show');
        currentRowNum = null; currentRowKey = null;
        // Optionally: refresh table inline
        if (typeof window.refreshKendalaTable === 'function') window.refreshKendalaTable();
      } else {
        window.toast('Gagal: ' + (res.error || 'Unknown error'), 'error');
        btn.disabled = false;
      }
    } catch (e) {
      window.toast('Error: ' + e.message, 'error');
      btn.disabled = false;
    } finally {
      window.hideLoading();
    }
  };
})();