# FilterIN — Sistem Informasi Operasional

FilterIN adalah aplikasi web untuk membantu pengelolaan dan pemantauan data
kendala operasional di Unit ASO Telkom Witel Magelang. Aplikasi ini menyediakan
antarmuka terpusat untuk mencari data, memperbarui informasi kendala, memantau
KPI IndiHome, dan menyusun laporan rekapitulasi sesuai hak akses pengguna.

Repositori ini memuat **Prototipe 2**. Google Sheets tetap menjadi sumber utama
data operasional, sedangkan MySQL menyimpan akun dan data pendukung aplikasi.

## Tujuan aplikasi

FilterIN dikembangkan untuk membantu pegawai:

- Menemukan data kendala melalui pencarian dan filter.
- Memperbarui informasi melalui web dengan penguncian baris untuk mengurangi
  konflik pengeditan antarpengguna.
- Memantau ringkasan kondisi operasional dan data KPI.
- Menyiapkan rekapitulasi laporan serta menelusuri aktivitas perubahan data.

## Fitur utama

| Fitur | Kegunaan |
| --- | --- |
| Dashboard | Ringkasan dan visualisasi data operasional, pengumuman, serta daftar pantauan. |
| Data kendala | Pencarian, filter, dan pengeditan melalui Quick Edit maupun kolom tabel yang diizinkan. |
| Penguncian edit | Membatasi pengeditan pada baris yang sedang ditangani pengguna lain. |
| Upload BIMA/KPRO | Mengolah berkas unggahan untuk sumber data yang digunakan dalam alur operasional. |
| Sinkronisasi BIMA | Memperbarui atau menambahkan data Kendala Master dari sumber BIMA. |
| Pengelolaan UNSC | Menambahkan data yang memenuhi kriteria ke UNSC dan menampilkan datanya. |
| KPI IndiHome | Unggah dan lihat data TTI, FFG, serta TTR FFG. |
| Recap Report | Menampilkan rekapitulasi dan menyediakan keluaran laporan PDF. |
| Pengelolaan akun | Login, logout, perubahan password mandiri, dan pengelolaan pengguna oleh Admin. |
| Audit log dan status online | Menelusuri aktivitas yang dicatat sistem dan melihat keaktifan pengguna. |
| Preferensi tampilan | Mode terang dan gelap yang mengikuti pilihan pengguna. |

Upload sumber, Sinkronisasi BIMA, dan pembaruan cache adalah proses berbeda.
Pembaruan cache berkala membaca salinan data; tidak menjalankan sinkronisasi
BIMA atau mengunggah berkas secara otomatis.

## Peran pengguna

| Peran | Tanggung jawab utama |
| --- | --- |
| Admin | Mengelola akun, melihat audit log, dan menjalankan fungsi operasional yang diizinkan. |
| Pegawai/Operator | Menjalankan pengelolaan data operasional sesuai hak akses. |
| Viewer | Membaca informasi yang diizinkan tanpa melakukan perubahan data operasional. |

Hak akses diperiksa pada backend, bukan hanya melalui penyembunyian menu.
Rincian implementasi setiap fitur tersedia pada [Peta Fitur](docs/PETA_FITUR.md).

## Teknologi dan alur data

- **Backend:** Python dan Flask.
- **Antarmuka:** template Jinja2, HTML, CSS, JavaScript, Bootstrap, dan Chart.js.
- **Pengolahan berkas/data:** Pandas dan pustaka Excel.
- **Sumber operasional:** Google Sheets melalui Google Sheets API.
- **Penyimpanan pendukung:** MySQL untuk akun, audit log, penguncian edit,
  keaktifan pengguna, metadata sinkronisasi, cache, dan fitur pendukung lainnya.
- **Peluncur server Windows:** Waitress melalui `start_filterin.bat`.

Pengguna mengakses FilterIN melalui browser. Flask menyajikan halaman dan
memproses permintaan dengan membaca atau memperbarui Google Sheets serta
menggunakan MySQL untuk kebutuhan pendukung.

Tampilan aplikasi berada di `backend/templates/` dan `backend/static/`.
Menjalankan FilterIN tidak memerlukan aplikasi React atau server npm terpisah.

## Persiapan

Siapkan:

1. Python yang kompatibel dengan dependensi pada `backend/requirements.txt`.
2. Server MySQL yang aktif, misalnya melalui XAMPP.
3. Spreadsheet dengan susunan sheet dan kolom yang sesuai konfigurasi aplikasi.
4. Kredensial Google service account dengan akses ke spreadsheet tersebut.
5. Koneksi internet untuk Google Sheets dan aset antarmuka yang dimuat dari CDN.

Perintah di bawah menggunakan PowerShell dari folder utama repositori.

## Instalasi

### 1. Siapkan lingkungan Python

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Gunakan lingkungan yang sudah tersedia apabila dependensinya telah terpasang;
tidak perlu membuat ulang `venv` setiap menjalankan aplikasi.

### 2. Isi konfigurasi

Jika `backend/.env` belum ada, salin `backend/.env.example` menjadi
`backend/.env`. Jangan menimpa konfigurasi yang sudah digunakan.

Isi konfigurasi sesuai lingkungan Anda:

- `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, dan `MYSQL_DB`.
- ID spreadsheet untuk setiap variabel `SPREADSHEET_*`.
- `GOOGLE_CREDS_PATH` dan `FLASK_SECRET_KEY` yang acak dan tidak dibagikan.
- Kontak Admin serta pengaturan cache/scheduler bila diperlukan.

Letakkan kredensial service account di `backend/credentials.json` untuk
konfigurasi standar. Berikan akun tersebut akses ke spreadsheet yang digunakan;
alur penulisan data memerlukan izin Editor. Aktifkan Google Sheets API pada
proyek Google Cloud yang digunakan.

### 3. Siapkan database dan Admin awal

Buat/pilih database dengan nama yang sama seperti `MYSQL_DB`, lalu impor
[backend/user_db.sql](backend/user_db.sql), misalnya melalui phpMyAdmin.

File ini membuat tabel pendukung, **tidak menyediakan akun atau password
bawaan**. Ikuti bagian D pada [panduan pemasangan](backend/notes.txt) untuk
membuat Admin awal dengan password yang sudah di-hash. Akun berikutnya dapat
ditambahkan melalui menu Manajemen User.

Untuk database yang sudah berisi data, buat cadangan dan periksa strukturnya
sebelum impor. File SQL tersebut bukan migrasi: `CREATE TABLE IF NOT EXISTS`
tidak memperbarui struktur tabel lama.

Pengaturan ukuran paket MySQL untuk cache sheet besar dijelaskan di
[Konfigurasi Operasional](docs/KONFIGURASI_OPERASIONAL.md).

## Menjalankan aplikasi

Pastikan MySQL aktif dan konfigurasi sudah terisi.

### Melalui terminal

Dari folder utama repositori:

```powershell
cd backend
..\venv\Scripts\python.exe app_flask.py
```

Jika virtual environment sudah aktif dan terminal berada di folder `backend`:

```powershell
python app_flask.py
```

Buka [http://127.0.0.1:5000](http://127.0.0.1:5000) pada komputer server.
Cara ini menjalankan server bawaan Flask untuk pengembangan/pengujian.

### Melalui peluncur Windows

Jalankan `start_filterin.bat` dari folder utama, atau klik dua kali berkasnya.
Peluncur menggunakan Waitress pada port 5000 dan memakai `venv` bila tersedia.

Untuk komputer lain di jaringan yang diizinkan, gunakan
`http://<IP-komputer-server>:5000`. Pastikan jalur jaringan dan firewall
mengizinkan koneksi. Komputer server dan proses aplikasi harus tetap berjalan;
pengguna di komputer lain cukup membuka browser, tidak perlu menjalankan Python.

Aplikasi mendengarkan pada semua antarmuka jaringan (`0.0.0.0`).
Batasi akses jaringan sesuai kebijakan kantor. Untuk penggunaan operasional,
gunakan peluncur Waitress, konfigurasi jaringan yang sesuai, dan HTTPS melalui
lapisan server yang dikelola administrator.

> Jika muncul `KeyError: 'MYSQL_HOST'`, periksa keberadaan dan isi
> `backend/.env`. Konfigurasi lokal tidak ikut tersalin melalui Git.

## Pembaruan data

Scheduler membaca sumber Kendala Master, UNSC, TTI, FFG, dan TTR FFG saat
startup, lalu setiap lima menit selama proses dan layanan pendukung aktif.

Admin/Operator dapat melihat detail waktu pembaruan pada dashboard. Tombol
pembaruan manual hanya tersedia untuk Admin. Kegagalan baca/simpan cache dapat
menyebabkan salinan belum diperbarui; interval scheduler bukan jaminan semua
sumber selalu berhasil diperbarui tepat setiap lima menit.

Penjelasan TTL, countdown, beberapa worker, dan batas paket MySQL tersedia di
[Konfigurasi Operasional](docs/KONFIGURASI_OPERASIONAL.md).

## Struktur repositori

```text
backend/
  app_flask.py          Logika aplikasi dan route Flask
  templates/           Halaman web Jinja2
  static/              JavaScript, CSS, dan gambar
  tests/               Pengujian backend, antarmuka, dan integrasi
  user_db.sql          Struktur tabel MySQL
  .env.example         Contoh konfigurasi tanpa kredensial asli
  requirements.txt     Dependensi Python
  requirements-test.txt Dependensi tambahan pengujian integrasi
  server.py            Pembungkus ASGI untuk deployment alternatif /api
  notes.txt            Panduan teknis pemasangan
docs/
  PETA_FITUR.md         Pemetaan fitur ke implementasi
  KONFIGURASI_OPERASIONAL.md
  REVIEW_PROTOTIPE_2.md
  archive/             Dokumen historis, bukan panduan versi aktif
start_filterin.bat      Peluncur Waitress untuk Windows
README.md              Pengenalan dan panduan awal
```

## Pengujian

Dari folder utama, jalankan pengujian backend dengan layanan tiruan:

```powershell
.\venv\Scripts\python.exe -B -m pytest backend/tests/backend -q -p no:cacheprovider
```

Pengujian antarmuka memerlukan Node.js; sebagian juga memerlukan Playwright
dan browser:

```powershell
node --test "backend/tests/frontend/*.cjs"
```

Tes yang dilewati (`skip`) bukan berarti lulus. Tes otomatis lokal juga bukan
pengganti pengujian integrasi dengan layanan sebenarnya maupun UAT pengguna.

Lihat [panduan pengujian](backend/tests/README.md) untuk konfigurasi browser
dan pengujian integrasi. **Jalankan tes integrasi hanya pada server, akun,
database, dan spreadsheet uji**, karena pengujian tersebut dapat mengubah data.

## Keamanan dan kerahasiaan

- Jangan commit `.env`, `credentials.json`, kunci rahasia, atau ekspor database
  yang berisi data pengguna.
- Gunakan akun uji dan data yang sudah disamarkan untuk demonstrasi,
  tangkapan layar, dan dokumentasi publik.
- Jangan menyimpan password akun sebagai teks biasa atau menggunakan contoh
  secret key sebagai konfigurasi operasional.
- Batasi akses service account dan jaringan sesuai kebutuhan aplikasi.
- Status online dan audit log menunjukkan aktivitas akun; keduanya bukan bukti
  kehadiran fisik atau identitas orang yang mengoperasikan perangkat.
- Periksa berkas yang akan di-commit sebelum melakukan push ke repositori.

## Dokumentasi lanjutan

- [Peta fitur dan lokasi source code](docs/PETA_FITUR.md)
- [Konfigurasi database, cache, dan scheduler](docs/KONFIGURASI_OPERASIONAL.md)
- [Panduan teknis pemasangan](backend/notes.txt)
- [Panduan pengujian](backend/tests/README.md)
- [Tinjauan implementasi Prototipe 2](docs/REVIEW_PROTOTIPE_2.md)
- [Arsip dokumentasi lama](docs/archive/README.md)

Untuk menelusuri kode, cari penanda seperti `[FITUR] Login`,
`[FITUR] Upload BIMA`, atau `[FITUR] KPI IndiHome` di
`backend/app_flask.py`. Ikuti implementasi terbaru ketika menyusun uraian
teknis atau laporan pengujian.
