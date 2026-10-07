# Pengujian otomatis FilterIN

Folder ini berisi skrip untuk memeriksa aplikasi, bukan kode yang menjalankan fitur website. File di sini tidak dijalankan ketika server FilterIN dinyalakan.

## Kelompok pengujian

| Folder / file | Yang diperiksa |
| --- | --- |
| `backend/test_backend_regressions.py` | Logika backend, hak akses, sesi, pengeditan, upload, sinkronisasi, dan laporan. Koneksi MySQL dan Google Sheets diganti dengan objek uji. |
| `frontend/test_dashboard_cache_status.cjs` | Indikator pembaruan data, status cache, dan countdown dashboard. |
| `frontend/test_upload_and_shared_ui.cjs` | Validasi upload, respons gagal/berhasil, CSRF, dan fungsi antarmuka bersama. |
| `frontend/test_change_password_notifications.cjs` | Notifikasi berhasil/gagal mengganti password dan waktu tampilnya. |
| `frontend/test_quick_edit_and_table_refresh.cjs` | Quick Edit, highlight baris, draft, dan pembaruan tabel. |
| `frontend/test_light_dark_theme.cjs` | Preferensi Light/Dark Mode, tombol tema, dan penerapan tema sebelum halaman tampil. |
| `integration/test_live_server.py` | Pengujian melalui HTTP ke server uji yang dikonfigurasi khusus. Dapat mengubah data pada server tujuan. |

File berawalan `test_` adalah skrip pengujian. Folder `__pycache__` yang mungkin muncul adalah cache Python, bukan fitur aplikasi atau laporan hasil pengujian.

## Menjalankan pengujian lokal

Jalankan dari folder utama `Project-telkom`, menggunakan lingkungan Python yang sudah memiliki dependensi `backend/requirements.txt`:

```powershell
python -B -m pytest backend/tests/backend -q -p no:cacheprovider
node --test "backend/tests/frontend/*.cjs"
```

Pengujian frontend tidak mengakses MySQL atau Google Sheets. Sebagian memerlukan Playwright beserta browser yang tersedia. Jika Playwright tidak ditemukan, bagian tersebut ditandai **skip**, bukan lulus. `FILTERIN_PLAYWRIGHT_PATH` dapat menunjuk instalasi Playwright yang sudah tersedia, dan `FILTERIN_BROWSER_CHANNEL` dapat memilih browser terpasang seperti `msedge`.

## Pengujian ke server

Pengujian dalam `integration/` tidak dijalankan otomatis oleh aplikasi. Suite ini juga dilewati oleh pytest kecuali `FILTERIN_RUN_LIVE_TESTS=1` dan `REACT_APP_BACKEND_URL` telah diisi. Akun uji menggunakan variabel `FILTERIN_TEST_ADMIN_USER`, `FILTERIN_TEST_ADMIN_PASSWORD`, `FILTERIN_TEST_OPERATOR_USER`, dan `FILTERIN_TEST_OPERATOR_PASSWORD`.

Gunakan hanya server dan data uji yang boleh diubah, bukan server operasional. Dependensi tambahannya ada di `backend/requirements-test.txt`. Jangan menuliskan kredensial asli di file pengujian.

Memindahkan atau mengganti nama skrip pengujian tidak mengubah fitur aplikasi. Namun, referensi ke `templates/` dan `static/`, serta perintah pengujian di dokumentasi, harus mengikuti lokasi file yang baru.
