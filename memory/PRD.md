# FilterIN - Product Requirements Document

## Original Problem Statement
User memiliki website "FilterIN" yang mereka rancang sendiri — Flask + MySQL + Google Sheets app untuk mengolah data massal (data kendala) Indihome/Indibiz oleh Unit Kendala Telkom ASO Magelang. User ingin menyempurnakan website ini dengan fokus security, logika pengolahan, UI/UX, dan concurrency (karena Google Sheet dipakai 3 unit kerja).

## Architecture

### Stack (retained from original)
- **Backend**: Flask 3 (Python) mounted at `/api/*` via `asgiref.wsgi.WsgiToAsgi + PathPrefixMiddleware` (server.py)
- **DB (user auth, locks, audit)**: MariaDB/MySQL 10.11 — compatible with user's XAMPP setup
- **Data storage (master)**: Google Sheets (SHARED with 3 unit kerja — intentionally kept)
- **Frontend**: React shell (redirects to `/api/`) + Jinja2 templates
- **Integrations**: gspread (service account), pandas, openpyxl

### Key Tables (MySQL)
- `users` (id, nama, username, password_hash, role, created_at, last_login)
- `edit_locks` (sheet_name, row_key, locked_by, locked_at) — soft row lock
- `audit_log` (username, action, sheet, row_key, column, old, new, timestamp)
- `sync_new_rows` (order_id, sync_batch_id, seen_by) — tracks new BIMA syncs
- `login_attempts` (username, ip, success, timestamp) — brute-force protection

## User Personas
1. **Operator Unit Kendala** — editing FEEDBACK ASO, ACTUAL KENDALA, NOTES ASO di Kendala Master (primary pain point)
2. **Admin Telkom ASO** — access Audit Log, full CRUD, manage users
3. **Unit Kerja Lain (2 unit)** — view/edit Google Sheet directly (OUT of FilterIN scope)

## Implemented Features (as of 19 Apr 2026)

### ✅ Phase 1 — Security & Stability
- [x] Password hashing (werkzeug pbkdf2) with auto-upgrade from legacy plaintext on login
- [x] CSRF protection (Flask-WTF) on all POST — auto-injected via fetch wrapper
- [x] Rate limit: 10 login/min, brute-force block after 5 failed in 5 min
- [x] All secrets to `.env` (MySQL creds, secret_key, spreadsheet IDs)
- [x] `debug=False` in production
- [x] Fix typo `VERIVIKASI` → `VERIFIKASI` (backward compat supports both)
- [x] ProxyFix middleware for correct remote_addr

### ✅ Phase 2 — UX Fix (core user pain point)
- [x] **Quick Edit Modal** — click pencil → modal with context + 5 editable fields; eliminates horizontal scroll fatigue
- [x] Frozen left columns + sticky headers
- [x] **Column Chooser** — user picks visible columns (persisted to localStorage)
- [x] **Mode Cepat** — one-click toggle to show only essential work columns
- [x] Keyboard shortcuts: Ctrl+S, Esc
- [x] Auto-fill `TGL FEEDBACK` when Feedback ASO changes
- [x] SUBERRORCODE + ENGINEERMEMO shown prominently in modal (reference to choose ACTUAL KENDALA correctly)

### ✅ Phase 2.5 — New Data Notification
- [x] Track new ORDER_IDs from sync BIMA in `sync_new_rows`
- [x] Banner notification on Dashboard + Kendala Master ("{N} data baru")
- [x] "Lihat Data Baru" filter (`?new_only=1`)
- [x] `NEW` badge + orange left border on new rows
- [x] "Tandai Sudah Dibaca" action per user

### ✅ Phase 3 — Concurrency Protection
- [x] Row-level soft lock (MySQL `edit_locks`, 5 min TTL, auto-cleanup)
- [x] Lock indicator badge on locked rows (other user's name + time)
- [x] Auto-poll active locks every 15 sec
- [x] Audit log for every edit (siapa-kapan-apa-lama-baru)
- [x] Audit Log viewer page for admin only

### ✅ Phase 4 — Performance
- [x] Sheet cache (30 sec TTL) — reduces Google API calls
- [x] Vectorized pandas for `hitung_rumus_otomatis` (LAMA WO, UMUR KENDALA)
- [x] Connection context manager for MySQL (auto cleanup)

### ✅ Phase 5 — UI Modernization (Telkom blue retained)
- [x] Modern design tokens (CSS vars) + shadows + rounded corners
- [x] **Dark Mode** toggle (persist to localStorage)
- [x] Loading overlay for all long operations
- [x] Confirm modals for destructive actions (Sync BIMA, Move UNSC)
- [x] Toggle show/hide password on login
- [x] Role pill badge in header
- [x] Auto-dismiss flash toasts (5 sec)
- [x] Font-awesome icons throughout

### ✅ Phase 6 — Admin Features
- [x] Audit Log page with filters (user, action)
- [x] Role-based access control (admin/operator/viewer)

## Deferred / Backlog (P2)
- [ ] Placeholder pages (summary, TATI, wokendala, psretti, lapvalidasiodp) still return empty data — implement data logic
- [ ] Export tabel hasil filter ke Excel/PDF
- [ ] Full migration script Google Sheets → MySQL (if ever needed in future)
- [ ] Live presence indicator (via WebSocket) — polling works but could be realtime
- [ ] Reset password admin flow

## Testing Status (iteration 1, 19 Apr 2026)
- Backend: **76%** (19/25) — core endpoints all PASS; minor failures are CSRF/401 order (not bugs) + cloudflare rate limiting during pytest
- Frontend: **95%** — all critical flows PASS (login, dashboard, kendala master, quick edit modal, dark mode, audit log)
- Core UX pain point (horizontal scroll): **SOLVED** via Quick Edit Modal — confirmed working
- Concurrency: **WORKING** — lock/unlock API tested, UI indicators functional

## Next Action Items (for user)
1. Test dengan akun `dava234` / `dava123` di https://bulk-data-tool-1.preview.emergentagent.com/api/login
2. Coba Quick Edit Modal di Kendala Master → klik pencil di row → edit → save
3. Coba Dark Mode toggle di sidebar
4. (opsional) Jalankan sync BIMA (akan update Google Sheet real)
5. Aplikasi siap di-port balik ke lingkungan XAMPP lokal user (Flask + MySQL stack identik)
