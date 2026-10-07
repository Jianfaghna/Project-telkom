# Peta Fitur FilterIN Prototipe 2

Dokumen ini merupakan indeks implementasi aktual, bukan rancangan perubahan
arsitektur. Backend tetap berada dalam satu `app_flask.py`. Pemetaan diperiksa
pada 21 September 2026; perbarui dokumen ini ketika fungsi atau route berubah.

## 1. Cara mencari fitur

1. Buka `backend/app_flask.py`.
2. Tekan **Ctrl+F**, lalu ketik nama fitur, misalnya `[FITUR] Login`.
3. Gunakan hasil berikutnya untuk melihat bagian lain fitur yang sama. Beberapa
   fitur memiliki penanda terpisah untuk logika pengolahan dan endpoint tombol.
4. Gunakan tabel di bawah untuk menemukan template dan komponen pendukungnya.
5. Untuk mencari lintas file di editor, gunakan **Ctrl+Shift+F** dengan nama
   fungsi, route, atau nama template.

`[FITUR]` menandai fungsi yang berkaitan dengan fitur pengguna. `[PENDUKUNG]`
menandai komponen bersama seperti koneksi database, cache, dan penulisan Sheets.
Gunakan nama fungsi/route sebagai acuan skripsi; nomor baris dapat bergeser.

## 2. File yang menjadi titik awal

| File/lokasi | Peran |
| --- | --- |
| `backend/app_flask.py` | Konfigurasi, pemeriksaan akses, fungsi pengolahan, dan route Flask. |
| `backend/templates/` | Halaman utama aplikasi, menggunakan template Jinja. |
| `backend/templates/base.html` | Kerangka halaman, sidebar, dan interaksi bersama seperti heartbeat. |
| `backend/static/filterin-core.js` | Interaksi bersama, termasuk Quick Edit, lock, draft, dan highlight sesudah simpan. |
| `backend/static/` | JavaScript, CSS, dan gambar pendukung. Sebagian JavaScript masih berada di template. |
| `backend/user_db.sql` | Satu file instalasi sembilan tabel MySQL; bukan backup data atau migrasi database lama. |
| `backend/tests/` | Pengujian backend dan interaksi frontend. |
| `start_filterin.bat` | Peluncur lokal melalui Waitress, memakai `app_flask:flask_app`. |
| `backend/server.py` | Pembungkus untuk deployment ASGI dengan prefix `/api`. |
| `frontend/src/App.js` | Pengarah ke `/api/`, bukan implementasi halaman utama FilterIN. |
| `backend/notes.txt` | Panduan pemasangan dan konfigurasi. |

Route di bawah adalah route yang dideklarasikan Flask. Pada deployment melalui
`server.py`, URL luar mendapat prefix `/api`; peluncur lokal tidak memakai
pembungkus tersebut. Jangan menyamakan kedua pola URL ketika melakukan pengujian.

## 3. Peta fitur ke backend dan tampilan

Semua fungsi Python pada tabel ini berada di `backend/app_flask.py`.
Nama template relatif terhadap `backend/templates/`. Daftar route gabungan
ditulis ringkas; decorator di atas fungsi adalah sumber kebenaran metode dan akses.

| Kata pencarian Ctrl+F | Fungsi utama / route | Tampilan atau interaksi |
| --- | --- | --- |
| `[FITUR] Halaman Awal` | `home()` — GET `/` | Pengalihan ke login/dashboard. |
| `[FITUR] Login` | `login()` — GET/POST `/login` | `login.html`. |
| `[FITUR] Hak Akses` | `login_required`, `api_login_required`, `role_required`, `api_role_required` | `base.html` mengatur menu; decorator menjaga akses backend. |
| `[FITUR] Sesi Pengguna` | `inject_globals()`, `_log_session_ping()` — hook setiap request | Role/nama untuk template dan validasi ulang akun. |
| `[FITUR] Ganti Password` | `ganti_password()` — GET/POST `/ganti_password` | `ganti_password.html`. |
| `[FITUR] Dashboard` | `_compute_dashboard_stats()`, `dashboard()`, `dashboard_stats()` — GET `/dashboard`, `/dashboard_stats` | `dashboard.html`. |
| `[FITUR] Upload Data` | `upload()` — GET `/upload` | `upload.html`, formulir BIMA/KPRO. |
| `[FITUR] Upload BIMA` | `filter_data()` — POST `/filter`; validasi bersama `_read_source_upload()`, `_align_source_upload()` | `upload.html`. |
| `[FITUR] Upload KPRO` | `hapus_kolom()` — POST `/hapus_kolom`; validasi bersama upload | `upload.html`. |
| `[FITUR] Data Spreadsheet` | `tabel()` — GET `/tabel` | `tabel.html`. |
| `[FITUR] Sinkronisasi BIMA` | `sync_bima_to_kendala()`, `api_sync_bima()` — POST `/sync-bima` | `kendalamaster.html`, `triggerSyncBima()`. |
| `[FITUR] Kendala Master` | `kendala_master()`, `api_kendala_data()`, `update_kendala()` — GET `/kendala_master`, `/kendala_data`; POST `/update_kendala` | `kendalamaster.html`, `static/filterin-core.js` untuk penyimpanan form. |
| `[FITUR] Quick Edit` | `api_kendala_row()` — GET `/kendala_row/<int:row_num>`; `api_update_kendala_row()` — POST `/update_kendala_row`; `_save_sheet_changes()` | `kendalamaster.html`, `static/filterin-core.js`; termasuk loading modal dan highlight 15 detik. |
| `[FITUR] Riwayat Order` | `order_history()` — GET `/order_history/<path:order_id>` | Riwayat pada Quick Edit, `static/filterin-core.js`. |
| `[FITUR] Penguncian Edit` | `acquire_lock()`, `renew_lock()`, `release_lock()`, `get_active_locks()`; POST `/lock`, `/renew-lock`, `/unlock`; GET `/api/kendala_locks` | `static/filterin-core.js`, `kendalamaster.html`, `unsc.html`. |
| `[FITUR] Data Baru` | `_get_new_order_ids()`, `api_mark_new_seen()` — POST `/mark_new_seen`; filter GET `/kendala_master?new_only=1` | `kendalamaster.html`, penanda NEW dan tombol Lihat Data Baru. |
| `[FITUR] UNSC` | `move_kendala_to_unsc()`, `api_move_to_unsc()` — POST `/move-to-unsc`; `unsc()`, `api_unsc_data()` — GET `/unsc`, `/unsc_data`; `update_unsc()` — POST `/update_unsc` | `unsc.html`; tombol pemindahan di `kendalamaster.html`. |
| `[FITUR] User Online` | `heartbeat()` — POST `/heartbeat`; `api_online_count()`, `online_users()` — GET `/api/online_count`, `/online`; `_page_name()` | `online_users.html`, `base.html`. |
| `[FITUR] Manajemen Pengguna` | `admin_users()` — GET `/admin/users`; `admin_add_user()`, `admin_edit_user()`, `admin_reset_password()`, `admin_delete_user()` — POST `/admin/users/add`, `/edit`, `/reset_password`, `/delete` (semuanya di bawah `/admin/users`) | `admin_users.html`. |
| `[FITUR] Audit Log` | `audit()`; `audit_log_view()` — GET `/audit_log`; `audit_log_clear()` — POST `/audit_log/clear` | `audit_log.html`. |
| `[FITUR] KPI IndiHome` | `kpi_index()`, `kpi_detail()` — GET `/kpi`, `/kpi/<kpi_type>`; `kpi_upload()` — POST `/kpi/<kpi_type>/upload`; helper validasi `_prepare_kpi_upload()`, `_align_kpi_upload()` | `kpi_index.html`, `kpi_detail.html`; TTI, FFG, TTR FFG. |
| `[FITUR] Recap Report` | `recap()` — GET `/recap`; helper `_pivot_2d()` | `recap.html`. |
| `[FITUR] Watchlist` | `watchlist_get()` — GET `/api/watchlist`; `watchlist_add()`, `watchlist_remove()`, `watchlist_auto_clean()` — POST `/api/watchlist/add`, `/remove`, `/auto_clean` (di bawah `/api/watchlist`) | `dashboard.html`. |
| `[FITUR] Pengumuman` | `announcements_get()` — GET `/api/announcements`; `announcements_add()`, `announcements_delete()` — POST `/api/announcements/add`, `/delete` (di bawah `/api/announcements`) | `dashboard.html`. |
| `[FITUR] Verifikasi ODP` | `verifikasi_odp_full()` — GET `/verifikasi_odp_full` | `verifikasi_odp_full.html`; **masih placeholder**, jangan disebut sudah mengolah data operasional. |
| `[FITUR] Logout` | `logout()` — GET `/logout` | Menghapus sesi Flask, membersihkan status online dan lock pengguna, lalu kembali ke login. |

## 4. Penyimpanan dan komponen bersama

Google Sheets tetap sumber utama data operasional. MySQL mendukung aplikasi,
bukan menggantikan seluruh data operasional Google Sheets.

| Penyimpanan | Digunakan untuk |
| --- | --- |
| MySQL `users`, `login_attempts` | Akun, role, hash password, dan percobaan login. |
| MySQL `user_sessions` | Informasi keaktifan/halaman pengguna; berbeda dari session autentikasi Flask. |
| MySQL `edit_locks` | Kepemilikan dan masa berlaku penguncian edit. |
| MySQL `audit_log` | Aktivitas yang dicatat melalui `audit()`, termasuk riwayat perubahan per order. |
| MySQL `sync_new_rows` | Metadata ORDER_ID baru dan status dilihat oleh pengguna. |
| MySQL `sheet_cache` | Salinan sementara hasil pembacaan Sheets; entri `filterin:prefetch:status` mencatat progres/hasil refresh lintas worker. |
| MySQL `watchlist`, `announcements` | Daftar pantauan dan pengumuman. |
| Sheets sumber upload (`SHEET_NAMES['upload']`) | Area BIMA/KPRO; dicari melalui `[FITUR] Upload BIMA` / `Upload KPRO`. |
| Sheets pengerjaan (`SHEET_NAMES['kendala']`) | `IMPORT BIMA (FRESH)`, `DB KENDALA (MASTER)`, `DB UNSC (END STATE)`, dan sheet pendukung. |
| Sheets KPI (`SHEET_NAMES['kpi']`) | Area upload dan hasil untuk setiap jenis KPI. |
| `backend/last_sync_time.txt` | Metadata waktu sinkronisasi melalui `save_last_sync_time()` / `get_last_sync_time()`. |

Komponen bersama yang dapat dicari: `[PENDUKUNG] Database`, `[PENDUKUNG] Google
Sheets`, `[PENDUKUNG] Cache`, `[PENDUKUNG] Serialisasi Penulisan Google Sheets`,
`[PENDUKUNG] Penggantian Data Upload`, dan `[PENDUKUNG] Pengolahan Tabel`.

Catatan penting untuk menjelaskan alur:

- Upload sumber dan Sinkronisasi BIMA adalah proses berbeda. Sinkronisasi backend
  membaca `IMPORT BIMA (FRESH)` dan memperbarui/menambah Kendala Master berdasarkan
  ORDER_ID; jangan menganggap backend langsung menggabungkan BIMA dan KPRO.
  Rumus penghubung spreadsheet perlu diperiksa pada spreadsheet itu sendiri.
- Scheduler cache membaca data secara berkala; bukan menjalankan Sinkronisasi BIMA.
- Indikator pembaruan dashboard: `dashboard.html` dan `static/cache-status.js`;
  GET `/api/cache_status`, POST `/api/cache_refresh`, `_prefetch_job()`,
  `_run_prefetch()`, `_read_prefetch_status()`. Jadwal startup dan setiap 300 detik;
  hasil baca sumber dipisahkan dari hasil commit cache. Tes UI:
  `backend/tests/frontend/test_dashboard_cache_status.cjs` (request dicegat, tidak memakai layanan live).
- Data Baru adalah penanda hasil sinkronisasi dari `sync_new_rows`: ORDER_ID
  tercatat dalam 24 jam terakhir dan belum ditandai dibaca oleh pengguna tersebut.
  Tanggal order/feedback hari ini tidak otomatis membuat baris menjadi NEW.
  Penanda dirender melalui `is_new_flags` di `kendalamaster.html`, bukan ditambahkan
  oleh `static/script.js`. Ini berbeda dari highlight Quick Edit selama 15 detik.
- Tombol Sinkronisasi BIMA dan Pindah ke UNSC ditangani hanya oleh
  `triggerSyncBima()` dan `triggerMoveUnsc()` di `kendalamaster.html`.
  `static/script.js` tidak memasang penangan klik tambahan pada kedua tombol itu.
- Pembaruan tabel Kendala Master menggunakan `_kendala_view_revision()` untuk
  membandingkan versi data awal halaman dengan respons `/kendala_data`.
  Pembanding mencakup kolom, isi data halaman, nomor baris sheet, penanda NEW,
  dan total hasil filter; bukan teks tampilan atau nilai dropdown di browser.
  Pemeriksaan tetap setiap 10 detik, tetapi request tidak ditumpuk dan reload
  ditahan ketika ada edit, modal Quick Edit, proses simpan/sinkronisasi/pemindahan,
  atau highlight setelah simpan yang masih aktif.
- Pembatasan sidebar bukan pengganti decorator akses pada backend. Saat menelusuri
  suatu aksi, periksa decorator route POST-nya, bukan hanya halaman GET.

## 5. Menelusuri alur dari login sampai logout

1. `home()` memilih halaman awal. `login()` memvalidasi akun, mencatat percobaan,
   dan membentuk session dengan identitas/role dari MySQL jika berhasil.
2. `_log_session_ping()` memvalidasi ulang akun pada request berikutnya;
   decorator login/role menentukan akses ke fitur.
3. Pengguna membuka halaman fitur. Template mengirim form atau request JavaScript
   ke route; backend memvalidasi dan membaca/menulis penyimpanan terkait.
4. Untuk perubahan data, telusuri juga pemeriksaan konflik/lock, invalidasi cache,
   dan pemanggilan `audit()` jika digunakan oleh aksi tersebut.
5. Heartbeat mengelola informasi online selama pengguna memakai halaman aplikasi.
6. `logout()` mencoba membersihkan `user_sessions` dan `edit_locks` pengguna,
   mengosongkan session Flask, lalu mengarahkan pengguna ke login.

## 6. Menghubungkan fitur dengan pengujian skripsi

Pengujian otomatis menjadi bukti pendukung, bukan pengganti pengujian Black Box
melalui UI dan integrasi dengan layanan sebenarnya. Keberadaan sebuah test tidak
berarti seluruh variasi fitur sudah diuji; baca isi dan layanan tiruannya.

| Area | Titik awal pengujian yang tersedia |
| --- | --- |
| Role dan sesi | `backend/tests/backend/test_backend_regressions.py`: `test_role_change_applies_to_existing_session`, `test_operational_metadata_read_roles`, `test_logout_removes_presence_and_locks`. |
| Upload BIMA/KPRO | File yang sama: `test_source_upload_invalid_files_never_access_sheets`, `test_source_upload_validates_before_replacement`. |
| Sinkronisasi BIMA | File yang sama: `test_sync_rejects_duplicate_source_before_any_write`, `test_sync_combines_updates_and_appends`. |
| UNSC | File yang sama: `test_unsc_transfer_is_idempotent_even_with_stale_marker`, `test_unsc_transfer_writes_only_missing_ids`. |
| Edit dan Audit Log | File yang sama: `test_quick_edit_audit_after_success`, `test_failed_write_does_not_audit`, `test_edit_rejects_invalid_or_conflicting_changes`. |
| KPI | File yang sama: `test_invalid_kpi_files_never_access_or_write_sheets`, `test_kpi_schema_rejection_preserves_old_data`, `test_kpi_accepts_matching_header_and_reorders_without_losing_ids`. |
| Recap Report | File yang sama: `test_recap_today_and_total_not_double_counted`. |
| Interaksi frontend | `backend/tests/frontend/test_upload_and_shared_ui.cjs`, `backend/tests/frontend/test_quick_edit_and_table_refresh.cjs`; perhatikan dependensi browser dan kondisi skip. |

Untuk setiap fitur dalam skripsi, catat: kebutuhan pengguna, nama fungsi/route,
input, role penguji, hasil yang diharapkan, hasil aktual, dan bukti pengujian.
Diagram dan uraian laporan mengikuti implementasi yang sudah diverifikasi,
bukan mengubah kode semata-mata agar sesuai diagram lama.

## 7. Menelusuri bagian tampilan

Di folder `backend/templates`, cari `[FITUR]` untuk fitur dan `[BAGIAN]` untuk
bagian halaman. Penanda HTML menggunakan komentar Jinja `{# ... #}` yang tidak
dikirim ke browser; penanda dalam JavaScript menggunakan komentar `//`.
CSS dan JavaScript tetap di lokasi semula.

| Template | Contoh kata pencarian |
| --- | --- |
| `base.html` | `[BAGIAN] Sidebar`, `[BAGIAN] Notifikasi`, `[FITUR] Logout`, `[FITUR] User Online` |
| `login.html`, `ganti_password.html` | `[FITUR] Login`, `[BAGIAN] Form Ganti Password` |
| `dashboard.html` | `[BAGIAN] Ringkasan Statistik`, `[FITUR] Pengumuman`, `[FITUR] Watchlist` |
| `upload.html` | `[BAGIAN] Upload BIMA`, `[BAGIAN] Upload KPRO`, `[BAGIAN] Pengiriman Upload` |
| `tabel.html` | `[BAGIAN] Pilihan Sheet dan Pencarian`, `[BAGIAN] Tabel Data Spreadsheet` |
| `kendalamaster.html` | `[BAGIAN] Filter Pencarian`, `[BAGIAN] Tabel Kendala`, `[FITUR] Quick Edit`, `[FITUR] Sinkronisasi BIMA`, `[BAGIAN] Pagination` |
| `unsc.html` | `[BAGIAN] Tabel UNSC`, `[BAGIAN] Pembaruan Tabel` |
| `kpi_index.html`, `kpi_detail.html` | `[FITUR] KPI IndiHome`, `[BAGIAN] Upload KPI`, `[BAGIAN] Tabel Hasil KPI` |
| `admin_users.html` | `[BAGIAN] Tambah Pengguna`, `[BAGIAN] Edit Pengguna`, `[BAGIAN] Reset Password`, `[BAGIAN] Hapus Pengguna` |
| `audit_log.html` | `[BAGIAN] Filter Audit Log`, `[BAGIAN] Tabel Audit Log`, `[BAGIAN] Bersihkan Audit Log` |
| `online_users.html` | `[BAGIAN] Pengguna Online`, `[BAGIAN] Pengguna Offline` |
| `recap.html` | `[BAGIAN] Header Cetak`, `[BAGIAN] Feedback ASO per Datel`, `[BAGIAN] TATI Bulanan Izin NOK` |
| `verifikasi_odp_full.html` | `[FITUR] Verifikasi ODP` — tetap berstatus placeholder |

Modal Quick Edit dibuat oleh `backend/static/filterin-core.js`, bukan ditulis
langsung di template. Cari `qe-modal` dalam file tersebut; penanda di
`kendalamaster.html` menunjukkan tombol pembukanya. Konfirmasi logout berada
di `base.html`, sedangkan aksi tombolnya ditangani `backend/static/script.js`.

Untuk mengikuti sebuah tombol, mulai dari `action`, `onclick`, atau `fetch`
di sekitarnya, lalu cari nama fungsi/route tujuannya di `app_flask.py`. Penanda
ditaruh pada batas bagian penting, bukan pada setiap elemen HTML.
