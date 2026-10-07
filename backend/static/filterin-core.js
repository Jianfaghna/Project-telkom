/* FilterIN Core JS
 * - CSRF integration for fetch
 * - Dark mode toggle
 * - Global loading overlay helpers
 * - Quick Edit Modal controller (invoked from kendalamaster.html)
 */
(function () {
  const meta = document.querySelector('meta[name="csrf-token"]');
  window.FILTERIN_CSRF = meta ? meta.getAttribute('content') : '';
  window.escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));

  // Wrap fetch to auto-include CSRF on non-GET same-origin requests
  const origFetch = window.fetch.bind(window);
  window.fetch = function (url, opts) {
    opts = opts || {};
    const root = document.querySelector('meta[name="app-root"]')?.content || '';
    if (typeof url === 'string' && url.startsWith('/') && !url.startsWith('//')) {
      url = root + url;
    }
    const method = (opts.method || 'GET').toUpperCase();
    const target = new URL(typeof url === 'string' ? url : url.url, location.href);
    if (target.origin === location.origin && method !== 'GET' && method !== 'HEAD') {
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
  function applyTheme(t, persist = true) {
    t = t === 'dark' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', t);
    if (persist) {
      try { localStorage.setItem(THEME_KEY, t); }
      catch (_) { /* Tombol tetap berfungsi bila penyimpanan browser diblokir. */ }
    }
    const label = document.getElementById('theme-label');
    const icon = document.getElementById('theme-icon');
    if (label) label.textContent = t === 'dark' ? 'Light Mode' : 'Dark Mode';
    if (icon) {
      icon.classList.remove('fa-sun', 'fa-moon');
      icon.classList.add(t === 'dark' ? 'fa-sun' : 'fa-moon');
    }
  }
  // Tema sudah diterapkan di head; di sini sinkronkan label dan ikon tombol saja.
  applyTheme(document.documentElement.getAttribute('data-theme'), false);
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
    const text = document.createElement('span');
    text.textContent = msg;
    const close = document.createElement('button');
    close.className = 'flash-close';
    close.textContent = '×';
    close.onclick = () => el.remove();
    el.append(text, close);
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

  // Hanya input yang benar-benar diubah yang dikirim bersama snapshot bertanda tangan.
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('form').forEach(form => {
      if (!form.querySelector('input[name^="__snapshot__["]')) return;
      const controls = Array.from(form.querySelectorAll('input:not([type="hidden"]), select, textarea'));
      controls.forEach(el => { el.dataset.initialValue = el.value; });
      if (form.hasAttribute?.('data-preserve-draft')) {
        form.addEventListener('submit', async event => {
          event.preventDefault();
          if (form.dataset.saving === 'true') return;
          const notice = form.querySelector('[data-save-notice]');
          const report = (message, error = true) => {
            if (notice) { notice.hidden = false; notice.textContent = message; notice.setAttribute('role', error ? 'alert' : 'status'); }
          };
          if (form.querySelector('tr.is-dirty.row-locked-by-other')) {
            report('Belum disimpan: ada baris yang sedang diedit pengguna lain. Input Anda tetap tersedia. Tunggu penguncian selesai sebelum mencoba lagi.');
            return;
          }
          if (document.querySelector('#qe-modal.show')) {
            report('Selesaikan atau tutup Quick Edit sebelum menyimpan edit tabel.');
            return;
          }
          const payload = new FormData(form);
          let changed = 0;
          controls.forEach(el => {
            if (!el.name) return;
            if (el.value === el.dataset.initialValue || el.disabled ||
                (el.readOnly && !el.name.startsWith('TGL FEEDBACK['))) payload.delete(el.name);
            else changed++;
          });
          if (!changed) { report('Tidak ada perubahan untuk disimpan.', false); return; }
          form.dataset.saving = 'true';
          // Freeze values during this request without changing the submitted FormData.
          const states = controls.map(el => [el, el.disabled]);
          controls.forEach(el => { el.disabled = true; });
          report('Menyimpan perubahan…', false);
          try {
            const response = await fetch(form.action, {method: 'POST', headers: {Accept: 'application/json'}, body: payload});
            if (!(response.headers.get('content-type') || '').includes('application/json')) {
              throw new Error('Server tidak mengonfirmasi penyimpanan. Periksa sesi/koneksi; input Anda tetap tersedia.');
            }
            const result = await response.json();
            if (!response.ok || !result.ok) throw new Error(result.error || 'Penyimpanan belum berhasil.');
            controls.forEach(el => { el.dataset.initialValue = el.value; });
            Object.entries(result.row_tokens || {}).forEach(([rowNum, token]) => {
              const snapshot = form.elements.namedItem(`__snapshot__[${rowNum}]`);
              if (snapshot) snapshot.value = token;
            });
            form.querySelectorAll('tr.is-dirty').forEach(tr => tr.classList.remove('is-dirty'));
            if (result.audit_warning) {
              report('Data tersimpan, tetapi Audit Log gagal dicatat. Hubungi admin.');
            } else window.location.reload();
          } catch (error) {
            report(error.message + ' Input tidak dihapus. Jika koneksi terputus, periksa data terbaru sebelum mencoba lagi.');
          } finally {
            states.forEach(([el, disabled]) => { el.disabled = disabled; });
            delete form.dataset.saving;
          }
        });
        return;
      }
      form.addEventListener('submit', () => {
        controls.forEach(el => { if (el.readOnly || el.value === el.dataset.initialValue) el.disabled = true; });
      });
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
  let originalValues = null;
  let modalEl = null;
  let feedbackOpts = [];
  let actualOpts = [];
  let requestVersion = 0;
  let isSaving = false;
  let lockReady = false;
  let renewalTimer = null;
  let renewalDelay = 30000;
  // Keep lock/unlock ordering even when a modal is closed and reopened quickly.
  let lockQueue = Promise.resolve();
  function lockRequest(endpoint, rowKey) {
    const task = lockQueue.then(() => fetch(endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sheet_name: SHEET_NAME, row_key: rowKey })
    }));
    lockQueue = task.catch(() => {});
    return task;
  }

  function stopRenewal() { clearTimeout(renewalTimer); renewalTimer = null; }
  function scheduleRenewal(version) {
    stopRenewal();
    renewalTimer = setTimeout(async () => {
      if (version !== requestVersion || currentRowKey === null) return;
      if (!isSaving) await checkEditLock(false);
      if (version === requestVersion && lockReady) scheduleRenewal(version);
    }, renewalDelay);
  }
  function setLockState(ok, message) {
    lockReady = ok;
    setFormDisabled(!ok || isSaving);
    document.getElementById('qe-btn-save').disabled = !ok || isSaving || !originalValues;
    document.getElementById('qe-lock-warning').style.display = ok ? 'none' : 'flex';
    if (!ok) {
      document.getElementById('qe-lock-text').textContent = message + ' Input Anda tetap dipertahankan.';
      stopRenewal();
    }
  }
  async function checkEditLock(reacquire) {
    if (currentRowKey === null || !originalValues) return false;
    const version = requestVersion;
    // An outstanding check must never allow an unverified save.
    document.getElementById('qe-btn-save').disabled = true;
    try {
      const response = await lockRequest(reacquire ? '/lock' : '/renew-lock', currentRowKey);
      const result = await response.json();
      if (version !== requestVersion) return false;
      if (!response.ok || !result.ok) {
        setLockState(false, result.error || `Hak edit belum tersedia${result.locked_by_nama || result.locked_by ? ' (digunakan ' + (result.locked_by_nama || result.locked_by) + ')' : ''}.`);
        return false;
      }
      renewalDelay = Math.max(1000, Math.min(30000, (Number(result.ttl_seconds) || 300) * 1000 / 3));
      setLockState(true);
      scheduleRenewal(version);
      return true;
    } catch (_) {
      if (version === requestVersion) setLockState(false, 'Koneksi pemeriksaan hak edit gagal. Periksa akses edit sebelum menyimpan.');
      return false;
    }
  }
  window.recheckQuickEditLock = () => isSaving ? Promise.resolve(false) : checkEditLock(true);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && originalValues && !isSaving) checkEditLock(false);
  });

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
            <div id="qe-load-status" role="status" aria-live="polite" style="padding:28px 12px;text-align:center;">
              <i id="qe-load-spinner" class="fa-solid fa-spinner fa-spin" aria-hidden="true"></i>
              <span id="qe-load-text">Memuat data terbaru dan memeriksa akses edit…</span>
              <button type="button" id="qe-retry" class="qe-btn" hidden onclick="window.retryQuickEdit()">Coba lagi</button>
            </div>
            <div id="qe-content" hidden>
            <div id="qe-lock-warning" class="qe-lock-warning" style="display:none;">
              <i class="fa-solid fa-triangle-exclamation"></i>
              <span id="qe-lock-text">...</span>
              <button type="button" class="qe-btn" id="qe-recheck-lock" onclick="window.recheckQuickEditLock()">Periksa akses edit</button>
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

            <!-- ── RIWAYAT PERUBAHAN ── -->
            <div class="qe-history-section" id="qe-history-section">
              <div class="qe-history-header">
                <i class="fa-solid fa-clock-rotate-left"></i>
                <span>Riwayat Perubahan Order Ini</span>
                <button type="button" class="qe-history-toggle" id="qe-history-toggle"
                        onclick="toggleHistory()" title="Tampilkan/sembunyikan">
                  <i class="fa-solid fa-chevron-down" id="qe-history-chevron"></i>
                </button>
              </div>
              <div class="qe-history-body" id="qe-history-body">
                <div class="qe-history-loading" id="qe-history-loading">
                  <i class="fa-solid fa-spinner fa-spin"></i> Memuat riwayat…
                </div>
                <div id="qe-history-list"></div>
              </div>
            </div>
            </div>
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
    if (isSaving) return;
    const draftRow = Array.from(document.querySelectorAll('.editable-table tbody tr'))
      .find(tr => tr.dataset.orderId === String(rowKey));
    if (draftRow?.classList.contains('is-dirty') || document.querySelector('form[data-saving="true"]')) {
      window.toast('Selesaikan penyimpanan edit tabel terlebih dahulu. Input tabel belum dihapus.', 'warning');
      return;
    }
    if (!modalEl) buildModal();
    if (currentRowKey !== null) window.closeQuickEdit();
    const version = ++requestVersion;
    currentRowNum = rowNum;
    currentRowKey = rowKey;
    document.getElementById('qe-sub-title').textContent = `Order ID: ${rowKey}  •  Baris #${rowNum}`;
    document.getElementById('qe-lock-warning').style.display = 'none';
    originalValues = null;
    lockReady = false;
    stopRenewal();
    fillForm({});
    document.getElementById('qe-history-list').innerHTML = '';
    document.getElementById('qe-content').hidden = true;
    document.getElementById('qe-load-status').hidden = false;
    document.getElementById('qe-load-spinner').hidden = false;
    document.getElementById('qe-load-text').textContent = 'Memuat data terbaru dan memeriksa akses edit…';
    document.getElementById('qe-retry').hidden = true;
    modalEl.setAttribute('aria-busy', 'true');
    setFormDisabled(true);
    document.getElementById('qe-btn-save').disabled = true;
    modalEl.classList.add('show');

    try {
      // Acquire lock
      const lockResponse = await lockRequest('/lock', rowKey);
      if (version !== requestVersion) return;
      const lockRes = await lockResponse.json();
      if (version !== requestVersion) return;
      if (!lockRes.ok && !lockRes.locked_by && !lockRes.locked_by_nama) {
        throw new Error(lockRes.error || 'Gagal memeriksa akses edit. Silakan coba lagi.');
      }
      if (!lockRes.ok) {
        const warn = document.getElementById('qe-lock-warning');
        warn.style.display = 'flex';
        document.getElementById('qe-lock-text').textContent =
          `Row sedang diedit oleh ${lockRes.locked_by_nama || lockRes.locked_by} (sejak ${lockRes.locked_at}). Save dinonaktifkan untuk mencegah tabrakan.`;
        document.getElementById('qe-btn-save').disabled = true;
      }
      // Fetch row data
      const rowResponse = await fetch(`/kendala_row/${rowNum}`);
      const res = await rowResponse.json();
      if (version !== requestVersion) return;
      if (!rowResponse.ok || res.error) throw new Error(res.error || 'Gagal mengambil data terbaru.');
      if (String(res.row?.ORDER_ID || '').trim() !== String(rowKey).trim()) {
        throw new Error('Posisi order berubah. Tutup modal dan muat ulang halaman.');
      }
      originalValues = res.row;
      fillForm(res.row || {});
      document.getElementById('qe-load-status').hidden = true;
      document.getElementById('qe-content').hidden = false;
      modalEl.setAttribute('aria-busy', 'false');
      setFormDisabled(!lockRes.ok);
      document.getElementById('qe-btn-save').disabled = !lockRes.ok;
      lockReady = !!lockRes.ok;
      renewalDelay = Math.max(1000, Math.min(30000, (Number(lockRes.ttl_seconds) || 300) * 1000 / 3));
      if (lockReady) scheduleRenewal(version);

      // ── Fetch history riwayat perubahan ──
      loadOrderHistory(rowKey, version);

    } catch (e) {
      if (version !== requestVersion) return;
      modalEl.setAttribute('aria-busy', 'false');
      document.getElementById('qe-load-spinner').hidden = true;
      document.getElementById('qe-load-text').textContent = 'Data belum dapat dimuat. ' + e.message;
      document.getElementById('qe-retry').hidden = false;
    }
  };

  function setFormDisabled(disabled) {
    document.querySelectorAll('#qe-form input, #qe-form select, #qe-form textarea').forEach(el => {
      el.disabled = disabled;
    });
  }

  window.retryQuickEdit = function () {
    if (currentRowNum !== null) return window.openQuickEdit(currentRowNum, currentRowKey);
  };

  // ═══════════════════════════════════════════════════════
  // Optimistic UI update — perbarui baris tabel setelah Quick Edit
  // save. PENTING: JANGAN dispatch 'change' event native karena akan
  // trigger handleInputChange → mark row is-dirty → memunculkan
  // floating "Simpan Perubahan" bar (yang khusus untuk inline edit).
  // Sebagai gantinya, panggil color-update function langsung.
  // ═══════════════════════════════════════════════════════
  function updateRowInTable(rowNum, updates) {
    if (!rowNum || !updates) return;

    const table = document.querySelector('.editable-table');
    if (!table) return;

    const suffix = `[${rowNum}]`;

    Object.entries(updates).forEach(([col, val]) => {
      const name = `${col}${suffix}`;
      const el = table.querySelector(`[name="${CSS.escape(name)}"]`);
      if (!el) return;

      // Set value langsung tanpa fire event
      el.value = val;

      // Kalau select, panggil color updater manual (tanpa trigger handleInputChange)
      if (el.tagName === 'SELECT') {
        const nameAttr = el.getAttribute('name') || '';
        if (nameAttr.startsWith('FEEDBACK ASO') && typeof window.applyColor === 'function') {
          window.applyColor(el);
        } else if (nameAttr.startsWith('CURRENT_UIC') && typeof window.updateUicColor === 'function') {
          window.updateUicColor(el);
        }
      }
    });

    const tr = table.querySelector(`tr[data-row-num="${rowNum}"]`);
    if (tr) tr.classList.remove('is-dirty');

    // Kalau tidak ada baris dirty lagi, sembunyikan floating save bar
    if (!document.querySelector('.editable-table tr.is-dirty')) {
      const bar = document.querySelector('.controls-bar');
      if (bar) bar.style.display = 'none';
    }
  }

  // Highlight is independent of editable inputs and survives an automatic reload.
  // ORDER_ID is stable; the row number can change after sorting/synchronization.
  const savedStorageKey = 'filterin:recent-saves:' + window.location.pathname;
  const SAVED_HIGHLIGHT_MS = 15000;
  const savedTimers = new Map();
  let recentSaves = {};
  try {
    const stored = JSON.parse(sessionStorage.getItem(savedStorageKey) || '{}');
    if (stored && typeof stored === 'object' && !Array.isArray(stored)) recentSaves = stored;
  } catch (_) { /* Storage may be unavailable; the in-page marker still works. */ }

  function persistSavedRows() {
    try { sessionStorage.setItem(savedStorageKey, JSON.stringify(recentSaves)); } catch (_) {}
  }

  function showSavedRow(orderKey, expiresAt) {
    const row = Array.from(document.querySelectorAll('.editable-table tbody tr'))
      .find(tr => tr.dataset.orderId === String(orderKey));
    if (!row || expiresAt <= Date.now()) return;
    row.classList.add('row-just-saved');
    const anchor = row.querySelector('.btn-row-edit')?.closest('td') || row.querySelector('.col-edit-sticky');
    if (anchor && !anchor.querySelector('.qe-saved-badge')) {
      const badge = document.createElement('span');
      badge.className = 'qe-saved-badge';
      badge.textContent = '✓ Baru disimpan';
      badge.setAttribute('role', 'status');
      anchor.appendChild(badge);
    }
    clearTimeout(savedTimers.get(orderKey));
    savedTimers.set(orderKey, setTimeout(() => {
      row.classList.remove('row-just-saved');
      const badge = row.querySelector('.qe-saved-badge');
      if (badge) badge.remove();
      delete recentSaves[orderKey];
      savedTimers.delete(orderKey);
      persistSavedRows();
    }, expiresAt - Date.now()));
  }

  function markSavedRow(orderKey) {
    const expiresAt = Date.now() + SAVED_HIGHLIGHT_MS;
    // Define an own property safely even for an unusual order identifier.
    Object.defineProperty(recentSaves, orderKey, { value: expiresAt, writable: true, enumerable: true, configurable: true });
    persistSavedRows();
    showSavedRow(orderKey, expiresAt);
  }

  function restoreSavedRows() {
    Object.entries(recentSaves).forEach(([key, expiry]) => {
      if (!Number.isFinite(expiry) || expiry <= Date.now() || expiry > Date.now() + SAVED_HIGHLIGHT_MS) delete recentSaves[key];
      else showSavedRow(key, expiry);
    });
    persistSavedRows();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', restoreSavedRows);
  else restoreSavedRows();

  // Static styles: !important inside animation keyframes is ignored by browsers.
  // A tint and inset border remain visible above the table's existing cell colors.
  if (!document.getElementById('row-saved-style')) {
    const style = document.createElement('style');
    style.id = 'row-saved-style';
    style.textContent = `
      .editable-table tr.row-just-saved td {
        background-image: linear-gradient(rgba(34,197,94,.16), rgba(34,197,94,.16)) !important;
        box-shadow: inset 0 2px #16a34a, inset 0 -2px #16a34a !important;
      }
      .editable-table .qe-saved-badge {
        display: block; margin-top: 3px; padding: 2px 4px;
        border-radius: 4px; background: #166534; color: #fff;
        font-size: 10px; font-weight: 700; white-space: nowrap;
      }
      #qe-modal [hidden] { display: none !important; }
    `;
    document.head.appendChild(style);
  }

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

    [['qe-actual', 'ACTUAL KENDALA'], ['qe-feedback', 'FEEDBACK ASO']].forEach(([id, col]) => {
      const select = document.getElementById(id);
      const value = g(col);
      if (!Array.from(select.options).some(option => option.value === value)) select.add(new Option(value, value));
      select.value = value;
    });
    document.getElementById('qe-tgl-fb').value = g('TGL FEEDBACK');
    document.getElementById('qe-notes').value = g('NOTES ASO');
    const ia = g('IS_ACTIVE_KENDALA');
    document.getElementById('qe-is-active').value = ['ACTIVE', 'INACTIVE'].includes(ia) ? ia : '';
  }

  window.closeQuickEdit = async function () {
    if (!modalEl || isSaving) return;
    const rowKey = currentRowKey;
    ++requestVersion;
    stopRenewal();
    lockReady = false;
    modalEl.classList.remove('show');
    currentRowNum = null; currentRowKey = null; originalValues = null;
    if (rowKey !== null) {
      try { await lockRequest('/unlock', rowKey); } catch (_) {}
    }
  };

  window.saveQuickEdit = async function () {
    if (!currentRowNum || !originalValues) return;
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
    updates['IS_ACTIVE_KENDALA'] = ia;
    Object.keys(updates).forEach(col => {
      if (updates[col] === String(originalValues[col] ?? '')) delete updates[col];
    });
    if (!Object.keys(updates).length) { btn.disabled = false; return; }

    isSaving = true;
    setFormDisabled(true);
    window.showLoading('Menyimpan ke Google Sheets…');
    try {
      // Browser timers can be suspended in background tabs. Verify ownership again.
      if (!await checkEditLock(false)) return;
      const res = await (await fetch('/update_kendala_row', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          row_num: currentRowNum,
          row_key: currentRowKey,
          updates: updates,
          original_values: originalValues
        })
      })).json();
      if (res.ok) {
        if (res.audit_warning) window.toast('Data tersimpan, tetapi Audit Log gagal dicatat. Hubungi admin.', 'warning');
        const skipped = res.skipped || [];
        if (skipped.length > 0) {
          window.toast(`Tersimpan ${res.updated} kolom. Kolom tidak ditemukan di sheet: ${skipped.join(', ')}`, 'warning');
        } else {
          window.toast(`Berhasil menyimpan ${res.updated} kolom untuk Order ${currentRowKey}`, 'success');
        }

        // ═══ OPTIMISTIC UI UPDATE ═══
        // Langsung update sel di tabel tanpa reload halaman
        try {
          updateRowInTable(currentRowNum, updates);
          const row = document.querySelector(`tr[data-row-num="${currentRowNum}"]`);
          if (row && res.row_token) {
            const snapshot = row.querySelector('input[name^="__snapshot__["]');
            if (snapshot) snapshot.value = res.row_token;
            row.querySelectorAll('td[data-col]').forEach(cell => {
              if (!(cell.dataset.col in updates)) return;
              const input = cell.querySelector('input, select, textarea');
              if (input) input.dataset.initialValue = input.value;
            });
          }
        } catch (e) { console.warn('Row update failed:', e); }
        markSavedRow(currentRowKey);

        // Trigger refresh kartu dashboard kalau halaman punya updateStats()
        if (typeof window.updateStats === 'function') {
          try { window.updateStats(); } catch (e) { /* silent */ }
        }

        modalEl.classList.remove('show');
        ++requestVersion;
        stopRenewal();
        lockReady = false;
        currentRowNum = null; currentRowKey = null; originalValues = null;
      } else {
        window.toast('Gagal: ' + (res.error || 'Unknown error'), 'error');
        btn.disabled = false;
      }
    } catch (e) {
      window.toast('Error: ' + e.message, 'error');
      btn.disabled = false;
    } finally {
      isSaving = false;
      setFormDisabled(!lockReady);
      btn.disabled = !lockReady;
      window.hideLoading();
    }
  };

  // ── HISTORY ──────────────────────────────────────────
  let historyOpen = true;

  async function loadOrderHistory(orderKey, version) {
    const body    = document.getElementById('qe-history-body');
    const loading = document.getElementById('qe-history-loading');
    const list    = document.getElementById('qe-history-list');
    if (!body || !list) return;

    body.style.display = 'block';
    loading.style.display = 'flex';
    list.innerHTML = '';
    historyOpen = true;
    const chevron = document.getElementById('qe-history-chevron');
    if (chevron) chevron.style.transform = 'rotate(0deg)';

    try {
      const res  = await fetch(`/order_history/${encodeURIComponent(orderKey)}`);
      const data = await res.json();
      if (version !== requestVersion) return;
      loading.style.display = 'none';

      if (!data.history || data.history.length === 0) {
        list.innerHTML = `
          <div class="qe-history-empty">
            <i class="fa-solid fa-inbox"></i>
            <span>Belum ada riwayat perubahan untuk order ini.</span>
          </div>`;
        return;
      }

      // Kelompokkan by timestamp + username
      const groups = [];
      let cur = null;
      data.history.forEach(h => {
        const key = h.timestamp + '||' + h.username;
        if (!cur || cur.key !== key) {
          cur = { key, timestamp: h.timestamp, username: h.username,
                  nama: h.nama || h.username, changes: [] };
          groups.push(cur);
        }
        cur.changes.push(h);
      });

      list.innerHTML = groups.map((g, idx) => `
        <div class="qe-history-item ${idx === 0 ? 'latest' : ''}">
          <div class="qe-history-meta">
            <span class="qh-avatar">${window.escapeHtml((g.nama || g.username || '?')[0].toUpperCase())}</span>
            <span class="qh-name">${window.escapeHtml(g.nama)}</span>
            <span class="qh-uname">@${window.escapeHtml(g.username)}</span>
            <span class="qh-time">${window.escapeHtml(g.timestamp)}</span>
            ${idx === 0 ? '<span class="qh-latest-badge">Terbaru</span>' : ''}
          </div>
          <div class="qh-changes">
            ${g.changes.map(c => `
              <div class="qh-change-row">
                <span class="qh-col">${window.escapeHtml(c.column_name || '—')}</span>
                <span class="qh-old">${window.escapeHtml(c.old_value || '(kosong)')}</span>
                <span class="qh-to">→</span>
                <span class="qh-new">${window.escapeHtml(c.new_value || '(kosong)')}</span>
              </div>`).join('')}
          </div>
        </div>`).join('');

    } catch (e) {
      if (version !== requestVersion) return;
      loading.style.display = 'none';
      list.innerHTML = `<div class="qe-history-empty">
        <i class="fa-solid fa-circle-exclamation"></i>
        <span>Gagal memuat riwayat.</span></div>`;
    }
  }

  window.toggleHistory = function() {
    const body    = document.getElementById('qe-history-body');
    const chevron = document.getElementById('qe-history-chevron');
    if (!body) return;
    historyOpen = !historyOpen;
    body.style.display = historyOpen ? 'block' : 'none';
    if (chevron) chevron.style.transform = historyOpen ? 'rotate(0deg)' : 'rotate(-90deg)';
  };

})();
