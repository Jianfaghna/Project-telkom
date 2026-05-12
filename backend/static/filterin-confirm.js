/* ============================================================
   FilterIN - Custom Confirm Modal (Promise-based)
   Pengganti window.confirm() yang block proses sampai user klik.

   Cara pakai:
       const ok = await showConfirm({
           title: 'Sinkronisasi Data BIMA',
           message: 'Proses ini akan menarik data baru...',
           confirmText: 'Ya, Sinkronkan',
           cancelText: 'Batal',
           icon: 'fa-sync-alt',
           warning: 'Pastikan sheet IMPORT BIMA (FRESH) sudah berisi data terbaru.',
       });
       if (!ok) return;   // user klik Batal
       // ... lanjut proses
   ============================================================ */
(function () {
    // Build modal HTML once on script load
    let modalEl = null;
    let resolveCb = null;

    function buildModal() {
        if (document.getElementById('filterin-confirm-modal')) {
            modalEl = document.getElementById('filterin-confirm-modal');
            return;
        }
        const html = `
            <div class="fc-modal-overlay" id="filterin-confirm-modal" role="dialog" aria-modal="true" data-testid="confirm-modal">
                <div class="fc-modal-panel">
                    <div class="fc-icon-wrap">
                        <i class="fas fa-sync-alt" id="fc-icon"></i>
                    </div>
                    <h2 id="fc-title">Konfirmasi</h2>
                    <p id="fc-message">Apakah Anda yakin?</p>
                    <div class="fc-warning" id="fc-warning" style="display:none;">
                        <i class="fa-solid fa-triangle-exclamation"></i>
                        <span id="fc-warning-text"></span>
                    </div>
                    <div class="fc-actions">
                        <button type="button" class="fc-btn fc-btn-cancel" id="fc-btn-cancel" data-testid="confirm-cancel">
                            <i class="fa-solid fa-xmark"></i> <span id="fc-cancel-text">Batal</span>
                        </button>
                        <button type="button" class="fc-btn fc-btn-confirm" id="fc-btn-confirm" data-testid="confirm-yes">
                            <i class="fa-solid fa-check"></i> <span id="fc-confirm-text">Ya, Lanjutkan</span>
                        </button>
                    </div>
                </div>
            </div>
        `;
        const wrap = document.createElement('div');
        wrap.innerHTML = html;
        document.body.appendChild(wrap.firstElementChild);
        modalEl = document.getElementById('filterin-confirm-modal');

        // Event listeners
        document.getElementById('fc-btn-cancel').addEventListener('click', () => closeModal(false));
        document.getElementById('fc-btn-confirm').addEventListener('click', () => closeModal(true));
        // Click backdrop to cancel
        modalEl.addEventListener('click', (e) => {
            if (e.target === modalEl) closeModal(false);
        });
        // ESC to cancel, Enter to confirm
        document.addEventListener('keydown', (e) => {
            if (!modalEl.classList.contains('show')) return;
            if (e.key === 'Escape') closeModal(false);
            else if (e.key === 'Enter') {
                e.preventDefault();
                closeModal(true);
            }
        });
    }

    function closeModal(result) {
        if (!modalEl) return;
        modalEl.classList.remove('show');
        if (resolveCb) {
            const cb = resolveCb;
            resolveCb = null;
            cb(result);
        }
    }

    window.showConfirm = function (opts) {
        buildModal();
        opts = opts || {};
        document.getElementById('fc-title').textContent       = opts.title || 'Konfirmasi';
        document.getElementById('fc-message').innerHTML       = opts.message || 'Apakah Anda yakin?';
        document.getElementById('fc-confirm-text').textContent = opts.confirmText || 'Ya, Lanjutkan';
        document.getElementById('fc-cancel-text').textContent  = opts.cancelText  || 'Batal';

        const icon = document.getElementById('fc-icon');
        icon.className = 'fas ' + (opts.icon || 'fa-circle-question');

        // Warning box
        const warnBox = document.getElementById('fc-warning');
        if (opts.warning) {
            warnBox.style.display = 'flex';
            document.getElementById('fc-warning-text').innerHTML = opts.warning;
        } else {
            warnBox.style.display = 'none';
        }

        // Variant (danger / primary)
        const confirmBtn = document.getElementById('fc-btn-confirm');
        confirmBtn.classList.remove('danger', 'success');
        if (opts.variant === 'danger') confirmBtn.classList.add('danger');
        else if (opts.variant === 'success') confirmBtn.classList.add('success');

        modalEl.classList.add('show');
        setTimeout(() => document.getElementById('fc-btn-confirm').focus(), 100);

        return new Promise((resolve) => {
            resolveCb = resolve;
        });
    };
})();
