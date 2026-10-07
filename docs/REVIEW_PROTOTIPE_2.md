# Tinjauan dan koreksi Prototipe 2 FilterIN

Tanggal: 16 September 2026. Repository lokal mempunyai remote
`https://github.com/Jianfaghna/Project-telkom.git`. Tinjauan dilakukan terhadap
checkout lokal; tidak melakukan pull, push, deployment, atau perubahan data live.

## Acuan dan batas pemeriksaan

Pembaruan 21 September 2026 untuk cache: dengan persetujuan pengguna, batas
paket server MySQL lokal dinaikkan dari 1 MB ke 16 MB, baik pada konfigurasi
persisten XAMPP maupun pengaturan global untuk koneksi baru. Konfigurasi lama
dicadangkan. Satu prefetch nyata dijalankan untuk verifikasi: kelima cache
tersimpan dan diperiksa kembali di MySQL. Tidak ada penulisan ke Google Sheets.
Ini pengecualian terhadap pemeriksaan awal yang hanya memakai layanan tiruan.
JSON Kendala saat pemeriksaan berukuran 1.496.744 byte dan UNSC 1.249.887 byte,
keduanya melampaui batas paket lama, bahkan sebelum pengutipan SQL.
Log sekarang memisahkan keberhasilan membaca sumber dan commit cache MySQL;
gagal tulis cache menyebut nama sheet dan tidak lagi dihitung sebagai cache sukses.
Data hasil baca tetap tersedia bila hanya penyimpanan cache yang gagal.

FilterIN adalah sistem informasi departemental Unit ASO untuk pengelolaan data
operasional. Google Sheets tetap sumber utama data kendala, UNSC, unggahan BIMA,
KPI, dan bahan laporan. MySQL menyimpan pengguna, penguncian aplikasi, audit,
kehadiran pengguna, penanda sinkronisasi, watchlist/pengumuman, dan cache pendukung.
Cache tidak dijadikan sumber kebenaran operasional maupun fokus penelitian.

Acuan utama adalah konteks pengguna pada percakapan ini dan implementasi repository.
`memory/PRD.md` merupakan catatan historis, bukan bukti bahwa semua fitur sudah
berfungsi: antara lain nama kolom password, umur cache, dan daftar backlog di sana
tidak seluruhnya mencerminkan implementasi sekarang. Tidak ada diagram yang
digunakan untuk memaksakan perubahan proses bisnis. Skripsi lengkap/percakapan
lain di luar konteks yang diberikan tidak diperiksa.

## Koreksi yang diterapkan

| Area | Temuan sebelumnya | Koreksi |
|---|---|---|
| Identitas baris | Template Kendala dan UNSC menghitung baris berdasarkan posisi hasil filter, bukan posisi asli sheet. | Gunakan `__SHEET_ROW__` yang dibawa sampai ke template dan JSON. |
| Konflik pengeditan | ORDER_ID yang dikirim tidak dicocokkan dengan baris yang akan ditulis. | Baca sumber terbaru dan cocokkan ORDER_ID; posisi berubah ditolak. |
| Perubahan bersamaan | Nilai lama tidak diperiksa sehingga data yang telah berubah bisa tertimpa. | Quick Edit mengirim nilai awal; form bulk memakai snapshot bertanda tangan. Perubahan kolom yang konflik ditolak sebelum batch ditulis. |
| Form bulk | Form mengirim kembali semua input, termasuk yang tidak berubah dan kolom hasil perhitungan. | Browser mengirim input yang berubah; backend hanya mengizinkan kolom editable. LAMA WO/UMUR KENDALA tidak ditulis dari form. |
| Lock | Kegagalan pemeriksaan MySQL bisa membuat penyimpanan tetap berjalan. | Penyimpanan wajib berhasil memperoleh lock; gagal/terkunci menyebabkan penolakan. Semua lock penyimpanan dilepas dalam `finally`. |
| Beberapa worker | Edit, sinkronisasi, transfer dan upload dapat menulis spreadsheet bersamaan. | MySQL named lock per spreadsheet menyerialkan penulisan FilterIN. Pengambilan data untuk mengisi cache memakai guard yang sama agar snapshot lama tidak dipublikasikan setelah invalidasi. |
| Audit edit | Quick Edit mencatat sebelum Google berhasil; bulk/UNSC hanya mencatat jumlah baris. | Audit dibuat setelah keberhasilan penulisan, per ORDER_ID dan kolom, dengan nilai lama/baru. |
| Kegagalan audit | Kegagalan pencatatan hanya dicetak ke log proses. | Respons JSON/flash memberi peringatan jika data sudah tersimpan tetapi audit gagal. Nilai audit tidak lagi dipotong menjadi 500 karakter. |
| Riwayat audit | Grup dapat mencampur sheet berbeda dan nama historis mengikuti perubahan profil. | Kunci grouping mencakup sheet; riwayat order mengutamakan nama yang disimpan pada audit. |
| Hapus audit | Input hari salah dikonversi menjadi nol dan dapat menghapus semua log. | Input bukan angka atau negatif ditolak tanpa DELETE. Nol eksplisit tetap mempertahankan perilaku lama. |
| Satu baris data | Kendala dengan hanya satu baris data dianggap kosong. | Header baris kedua dan data mulai baris ketiga ditangani konsisten. |
| Baris kosong/pendek | Pembentukan DataFrame dan indeks setelah penyaringan dapat tidak konsisten. | Helper membuang baris tanpa identitas, melengkapi sel kosong, dan mempertahankan indeks sheet. |
| Filter/refresh | Filter tanggal membaca kolom yang telah dibuang; endpoint polling tidak mendukung semua filter halaman. | Tanggal helper disimpan selama perhitungan/filter; halaman dan JSON menggunakan helper filter yang sama. Kolom helper tidak ditampilkan. |
| Pencarian | Input seperti `[` ditafsirkan sebagai regular expression. | Pencarian literal untuk Kendala dan UNSC. |
| Umur/status | Default kolom kosong bukan Series; indeks fallback tidak selalu selaras; manual override diterapkan setelah umur dihitung. | Default Series memakai indeks DataFrame; status manual dipertimbangkan sebelum memilih tanggal akhir perhitungan umur. |
| Dashboard | Label kelompok umur tidak sama dengan hasil perhitungan; grafik tren kehilangan kolom tanggal. | Label diselaraskan dan tanggal helper tersedia untuk agregasi. Ejaan lama VERIVIKASI UNSC diterima. |
| Recap | WO baru selalu nol karena tanggal helper hilang; baris TOTAL TATI bisa dijumlahkan lagi; baris pendek dapat menyebabkan exception. | Gunakan tanggal yang dipertahankan, abaikan baris total, validasi panjang baris, dan jumlah hari sesuai bulan sistem. |
| BIMA sync | ORDER_ID duplikat dapat ditambahkan dua kali; baris pendek dilewati; update dan append terpisah. | Tolak identitas duplikat sebelum menulis, lengkapi baris pendek, gabungkan update/append ke satu batch. Pemetaan B:K divalidasi sebelum penulisan. |
| Metadata sync | ID batch berbasis detik dapat bertabrakan; penanda sudah dibaca tidak memengaruhi daftar NEW. | ID batch UUID; pembacaan NEW memeriksa `seen_by` untuk pengguna aktif. |
| Transfer UNSC | Hanya mengandalkan CEK DB UNSC yang dapat terlambat dihitung, sehingga transfer berulang bisa duplikat. | Bandingkan ORDER_ID langsung dengan sheet tujuan, deduplikasi batch, dan invalidasi kedua sheet. Sumber tetap dipertahankan. |
| Upload | Sheet dikosongkan sebelum pengganti dikirim; gagal kirim dapat meninggalkan sheet kosong. | Kirim data pengganti beserta sel kosong untuk sisa rentang dalam satu request update. Tidak menjalankan clear terlebih dahulu. |
| Upload kelas 06 | Alur hapus kolom selalu menulis A3, meskipun header kelas 06 di baris 1. | Data kelas 06 mulai baris 2; kelas 04/05 tetap baris 3. |
| KPI | Signature positional update tidak sesuai pemakaian gspread 6; cache tidak dihapus setelah upload; NOT COMPLY berwarna COMPLY. | Argumen update eksplisit, invalidasi dalam `finally`, serta pengecekan NOT/NC sebelum COMP. |
| Cache | TTL konfigurasi diabaikan; memory worker dapat mengalahkan cache bersama; force refresh mengembalikan stale tanpa penanda. | Cache MySQL bersama mengikuti `SHEET_CACHE_TTL`; memory hanya fallback; force refresh wajib berhasil dari sumber; stale maksimal 24 jam diberi penanda UI/JSON. |
| Startup | Thread scheduler dimulai sebelum fungsi pendukung selesai didefinisikan. | Mulai di akhir modul; tersedia `FILTERIN_SCHEDULER_ENABLED=0` untuk tes/worker non-scheduler. |
| Sesi/hak akses | Perubahan role, penghapusan akun, dan reset password tidak mengubah cookie login lama. | Verifikasi akun/role serta fingerprint password ke MySQL tiap request login. Sesi lama tidak diterima setelah password berubah. |
| Kehadiran | Logout/penghapusan akun meninggalkan presence dan lock; nama halaman KPI tertangkap oleh prefix /kpi. | Bersihkan presence/lock dan cocokkan nama halaman dari path paling spesifik, termasuk mount prefix. |
| API roles | API pengumuman/cache menggunakan redirect HTML; auto-clean watchlist tidak dibatasi role. | API memberikan 401/403 JSON, auto-clean hanya admin/operator. |
| Watchlist | Auto-clean membaca header baris pertama dan cache untuk menentukan penghapusan. | Gunakan header baris kedua dan pembacaan sumber fresh; dukung STATUS_RESUME; catat penghapusan dalam audit. |
| Mount /api | Fetch hardcoded dari root tidak mengikuti mount server.py. | Fetch internal memakai `request.script_root`; rute internal yang memang diawali /api tetap dipertahankan. |
| Rendering | Tabel upload menonaktifkan HTML escaping; toast menggabungkan teks menjadi HTML. | Aktifkan escaping dan gunakan textContent pada toast. |
| Skema | Skema awal tidak mencakup semua tabel yang digunakan aplikasi. | Lengkapi user_sessions, sheet_cache, watchlist, announcements; seluruh struktur kini tersedia dalam user_db.sql tanpa memaksakan nama database. |
| Tes lama | Tes HTTP menggunakan akun hardcoded dan dapat menulis ke layanan nyata. | Kredensial melalui environment; suite live hanya aktif dengan opt-in dan server uji yang ditentukan. |

## Alur setelah koreksi

### Indikator pembaruan data pada dashboard

- Umur cache yang melewati TTL baca tidak lagi disebut kegagalan pembaruan.
  Detail menampilkan waktu salinan tiap sumber; salinan lebih dari 10 menit
  tetap diberi peringatan. TTL baca tidak diubah.
- Proses startup, terjadwal, dan manual memakai `_prefetch_job()` yang sama,
  dengan MySQL named lock agar tidak bersamaan. Status run, progres, dan hasil
  tiap sumber dicatat pada entri khusus `sheet_cache`, sehingga dapat dibaca
  lintas worker. Jika lock proses hilang sebelum status selesai, UI melaporkan
  proses terhenti, bukan terus berputar atau menyatakan sukses.
- Respons POST manual menyatakan permintaan diterima. UI mencocokkan run baru
  atau run yang sudah berjalan dan menunggu status terminal, bukan timer 8 detik.
  Kesalahan status/database menghasilkan HTTP 503 dan pesan tidak tersedia.
- Jadwal membaca lima sumber (Kendala, UNSC, TTI, FFG, TTR FFG) saat startup dan
  setiap 300 detik. Status scheduler/next run pada dashboard merujuk worker
  yang melayani request. Pengujian memakai scheduler dan layanan tiruan;
  siklus live lima menit belum diamati pada perubahan ini karena proses Flask
  tidak terlihat berjalan saat pemeriksaan. Tidak ada data live yang ditulis.
- Tampilan diuji melalui browser terisolasi untuk data tersedia, progres,
  hasil parsial, sumber belum tersedia, error layanan, proses terhenti,
  hak Operator, dan penolakan respons POST. Kontrak backend diuji untuk status,
  penguncian proses, pelepasan lock saat gagal, dan interval scheduler.

### Tambahan: pencegahan penggantian data oleh upload BIMA/KPRO yang tidak valid

- Kedua endpoint memeriksa ekstensi `.xlsx`/`.xls` dan isi file di server, bukan
  hanya mengandalkan atribut accept atau JavaScript. CSV tidak lagi diterima di
  endpoint KPRO agar konsisten dengan antarmuka dan permintaan Excel saja.
  Parser tabel HTML `.xls` yang ketat digunakan bersama dengan KPI.
- Header file asli dibaca sebelum pandas mengganti nama kosong/duplikat.
  File kosong, hanya header, nama kolom kosong/duplikat, atau tidak dapat dibaca
  ditolak sebelum mengakses worksheet. Identitas teks berawalan nol dipertahankan.
- BIMA hanya menulis ke kelas 06, KPRO hanya kelas 05 sesuai pilihan antarmuka.
  Hasil filter BIMA kosong ditolak untuk mencegah pengosongan seluruh data lama.
  Pengosongan operasional yang memang disengaja memerlukan alur tersendiri.
- Header area tujuan menjadi acuan: kolom yang hilang tidak lagi diisi kosong
  diam-diam. Khusus BIMA, `no kode` boleh tidak ada di file sumber: kolom tujuan
  tersebut dilewati dengan nilai null saat update, termasuk pada sisa baris lama,
  sehingga isi/formulanya tidak ditimpa dan posisi kolom lain tidak bergeser.
  Jika tersedia di file, `no kode` tetap diimpor sesuai pemetaan biasa.
  Pengecualian eksplisit proses KPRO lama (CRMORDERTYPE, REGIONAL LAMA,
  DISTRICT LAMA, DATEL LAMA) tetap dipertahankan. Struktur acuan kosong/duplikat
  atau seluruh hasil pemetaan kosong ditolak. Ekstra kolom sumber tetap boleh
  karena proses ini memang melakukan pemilihan kolom, berbeda dari KPI.
- Tulis data dan pengosongan sisa baris dalam satu update, tanpa clear terpisah.
  Gunakan RAW agar teks ID dan nilai berawalan `=` tidak diinterpretasi sebagai
  angka/formula. Area lama tetap: BIMA maksimal A:Z mulai baris 2; KPRO maksimal
  56 kolom mulai baris 3. Header tidak ditulis ulang.
- Respons AJAX berupa JSON. Error tetap muncul pada kartu upload; hanya hasil
  sukses yang menavigasi ke tabel, sehingga flash tidak habis oleh fetch redirect
  sebelum pengguna melihatnya. Form biasa tetap mendapat flash dan redirect.
  Respons non-JSON (misalnya sesi/CSRF) dan koneksi terputus tidak dianggap sukses.
- PDF langsung belum terbukti sebagai penyebab screenshot KPRO kosong: endpoint
  KPRO sebelumnya sudah menolak ekstensi PDF. Celah pemetaan kolom kosong dan
  hilangnya notifikasi terbukti dari kode; perlu file kejadian/log/versi aplikasi
  untuk memastikan penyebab historis. Perbaikan lokal tidak memulihkan data live.
- Sheet upload yang dibagikan meminta login di browser pemeriksaan. Sheet Kendala
  & UNSC dapat dibaca; tab IMPORT BIMA (FRESH) menunjukkan #REF! pada A2 dan
  dilindungi. Penyebab #REF! belum dipastikan, rumus/izin tidak diubah. Contoh
  ekspor asli BIMA/KPRO dan header tujuan perlu diverifikasi sebelum penerapan.

### Tambahan: validasi struktur upload KPI

Unggahan TTI/FFG/TTR dibandingkan dengan header **area impor** pada baris pertama
sheet upload masing-masing, dibaca langsung dari Google Sheets di dalam guard penulisan.
Repository belum menyediakan template resmi untuk menetapkan daftar kolom statis;
karena itu header sheet tujuan yang sudah benar menjadi acuan, bukan nama kolom
yang ditebak dari label KPI atau dari file pengguna.

Pemeriksaan sheet pengerjaan yang dibagikan pengguna menunjukkan bahwa TTI dimulai
di A (`org_1`) sampai AG (`f_tti`), sedangkan FFG/TTR memiliki kolom A `XCEK`
berisi rumus ARRAYFORMULA/VLOOKUP di A2, dan data sumber berada di B–AH.
Karena itu aturan sebelumnya yang mencocokkan seluruh header dan mengganti dari
A1 dikoreksi: TTI mulai A2, FFG/TTR mulai B2. Header referensi dibatasi maksimal
33 kolom area impor; kolom di luar area ini tidak menjadi persyaratan file.
FFG/TTR ditolak jika header kolom A bukan `XCEK`, agar perubahan layout tidak
diam-diam menggeser data.

- Menerima workbook `.xlsx`/`.xls` serta ekspor tabel HTML berakhiran `.xls`
  dari portal KPI. HTML dibaca sebagai teks dengan parser lokal, tanpa eksekusi
  skrip, browser, atau pengambilan resource eksternal. Harus tepat satu tabel;
  tabel bersarang, sel gabungan, elemen aktif, jumlah kolom antarbaris berbeda,
  dan sel/baris yang tidak lengkap ditolak. Ekspor asli TTI berakhir pada
  `</tbody>` tanpa `</table>`; hanya kekurangan penutup tabel luar dengan pola
  akhir tersebut yang ditoleransi. XML dan HTML bernama `.xlsx` tetap ditolak.
- Baris pertama harus berisi 1–33 nama kolom teks, tanpa nama kosong/duplikat.
- Semua nama kolom harus cocok dengan acuan area impor, tidak termasuk `XCEK`.
  Kolom kurang atau tambahan ditolak
  dengan rincian pesan; tidak lagi memangkas kolom setelah AG secara diam-diam.
- Perbedaan huruf besar dan spasi diabaikan dalam pencocokan. Urutan input boleh
  berbeda; data diurutkan ulang sesuai posisi header sheet tujuan.
- Workbook kosong, hanya header, atau hanya baris kosong/spasi ditolak. Baris
  kosong di antara data dibuang. Teks seperti `NA` dan ID teks `00123` dipertahankan.
- Jika header acuan kosong, duplikat, tidak valid, atau tidak dapat dibaca, unggahan
  ditolak. Validasi tidak menghapus data, mengubah ukuran sheet, menginvalidasi
  cache, atau mencatat audit keberhasilan.
- Setelah validasi dan persiapan seluruh data, satu permintaan update mengganti
  isi area impor sekaligus mengosongkan sisa baris lama. Tidak ada clear terpisah.
  Baris header, rumus XCEK, dan kolom di luar area impor tidak ditulis ulang.
  Jumlah kolom yang ditulis mengikuti header area impor yang telah divalidasi,
  bukan seluruh lebar grid sheet.
- Kegagalan penulisan tetap menginvalidasi cache dan tidak mencatat audit sukses.
  Pembacaan ulang untuk memastikan hasil setelah write/timeout belum ditambahkan;
  pesan gagal koneksi tidak membuktikan bahwa server belum menerima perubahan.

Validasi ini memeriksa struktur dan keberadaan data, belum memeriksa kebenaran
bisnis setiap nilai/angka/tanggal. Jika dua jenis KPI mempunyai struktur identik,
jenisnya tidak bisa dibedakan dari nama kolom saja. Header acuan yang sebelumnya
sudah salah juga perlu diperbaiki berdasarkan template resmi oleh pengelola.
Aturan nilai per kolom dapat ditambahkan setelah definisi resmi tersedia.

Pembacaan operasional: browser → Flask → cache MySQL yang masih berlaku, atau
Google Sheets bila cache habis → pengolahan/filter → HTML/JSON. Jika sumber gagal,
cache lama hanya boleh untuk tampilan dan disertai penanda. Pengambilan untuk
keputusan mutasi/validasi edit tidak mengandalkan fallback stale.

Pengeditan: autentikasi dan role terbaru → guard penulis per spreadsheet → baca
sheet terbaru → cocokkan baris/ORDER_ID → lock baris → cek kolom dan nilai awal →
tulis perubahan → invalidasi cache → audit → lepas lock → respons. Konflik ditemukan
sebelum penulisan, bukan setelah sebagian input sengaja diterapkan.

Upload: validasi/parse file → susun data pengganti → siapkan ukuran sheet bila
diperlukan → satu request update untuk rentang data dan sisa data lama → invalidasi
cache → audit. Tidak ada operasi clear terpisah sebelum penulisan.

Transfer UNSC tetap merupakan penyalinan order yang memenuhi syarat, dengan
pencegahan duplikasi. Tidak ada penghapusan data Kendala Master secara otomatis.

## Perbedaan implementasi dan keputusan yang belum diubah

1. **Arti pindah UNSC.** Kode asli hanya menyalin; ia tidak menghapus sumber.
   Jika proses bisnis mewajibkan pemindahan fisik, diperlukan keputusan eksplisit
   tentang retensi sumber, formula, dan riwayat order sebelum mengimplementasikan
   penghapusan. Koreksi ini mempertahankan sumber.
2. **Kriteria ACTIVE/INACTIVE.** Aturan lama menganggap keyword DONE, CANCEL,
   REVOKE, PS COMPLETED, COMPLETED PS, MATI LISTRIK, serta umur >180 hari sebagai
   alasan INACTIVE; manual override menang. Khusus MATI LISTRIK dan cutoff 180 hari
   perlu divalidasi bersama Unit ASO. Kriteria bisnis tersebut tidak diubah.
3. **KPI upload vs hasil.** Halaman KPI membaca `upload DB ..._Total`, bukan sheet
   `MGL_NC ..._REG_FM` yang juga ada dalam konfigurasi. Tidak ada perhitungan KPI
   baru di Python. Perlu dipastikan apakah halaman dimaksudkan untuk mengelola
   unggahan atau juga menampilkan hasil penghitungan dari sheet result.
4. **Recap lokal vs sheet RECAP REPORT.** Route menyusun laporan dari Kendala,
   TATI dan LAP VALIDASI ODP; ia tidak membaca sheet RECAP REPORT yang terdaftar
   dalam konfigurasi. Ini dipertahankan karena mengubah sumber dapat mengubah
   isi laporan. Label periode TATI mengikuti kalender server, bukan sel periode
   pada sheet. Lokasi sel periode dan cakupan baris TATI perlu dikonfirmasi jika
   sheet dapat berisi bulan/tahun selain bulan berjalan.
5. **Verifikasi ODP Full.** Route masih merender header/data kosong. Implementasi
   belum lengkap. Pemetaan kolom/range dan aturan validasi belum cukup jelas untuk
   diisi dengan asumsi. Ini bukan fitur yang boleh dilaporkan telah selesai.
6. **AO/PDA dan CURRENT_UIC.** Recap memakai TA→AO dan TIF→PDA. Nilai TSEL tidak
   masuk kedua kelompok, sehingga subtotal AO/PDA tidak selalu sama dengan total
   aktif. Pemetaan lama dipertahankan menunggu definisi bisnis.

## Keterbatasan teknis yang tetap harus dijelaskan

- MySQL named lock hanya mengoordinasikan penulis FilterIN yang memakai guard.
  Ia tidak mengunci pengguna Google Sheets langsung. Snapshot mendeteksi perubahan
  yang sudah terjadi saat pembacaan, tetapi tidak menutup celah perubahan eksternal
  di antara pembacaan dan request penulisan Google. Jangan menyebutnya transaksi
  atomik lintas Google Sheets dan MySQL.
- Audit dan metadata sinkronisasi merupakan transaksi terpisah dari penulisan
  Google. Peringatan audit gagal mencegah klaim keberhasilan diam-diam, tetapi
  belum merupakan outbox/retry persisten. Gangguan atau crash setelah Sheets
  berhasil tetap dapat menyisakan audit/metadata yang belum tercatat.
- Timeout jaringan saat penulisan dapat mempunyai hasil ambigu. Pengguna harus
  memuat ulang dan memeriksa sumber sebelum mengulang operasi. Hilangnya respon
  bukan bukti bahwa Google tidak menulis.
- Pengelompokan audit masih memakai timestamp presisi detik. Dua operasi pengguna
  yang sama pada sheet/order yang sama dalam satu detik dapat tampil dalam satu
  grup; event ID transaksi tersendiri belum ditambahkan.
- `user_sessions` merepresentasikan kehadiran per username, bukan inventaris sesi
  per perangkat. Logout satu perangkat bisa menghilangkan presence sampai heartbeat
  perangkat lainnya tiba. Heartbeat juga mempertahankan sesi login selama tab aktif.
- Tampilan waktu sinkronisasi terakhir masih memakai `last_sync_time.txt`, sedangkan
  batch/order baru memakai MySQL. Ini perlu disatukan jika deployment berkembang
  menjadi beberapa host dengan filesystem terpisah. Tabel status eksekusi sinkronisasi
  yang mencatat kegagalan/rekonsiliasi belum ditambahkan.
- Rentang BIMA B:K, transfer UNSC A:I, TATI baris 4–10, dan ODP O5:S20 masih terikat
  struktur sheet yang ada. Guard BIMA/identitas UNSC menolak struktur yang tidak
  cocok, tetapi tidak menggantikan verifikasi skema sumber.
- Dependensi requirements.txt masih mencakup banyak paket dari lingkungan lama
  yang tidak digunakan langsung oleh Flask. Tidak dilakukan upgrade/penghapusan
  massal agar lingkungan yang ada tidak berubah tanpa verifikasi deployment.
- Beberapa rendering dinamis lama di template masih memakai innerHTML. Perbaikan
  tabel upload, toast, riwayat audit, watchlist, dan pengumuman bukan audit keamanan
  menyeluruh seluruh antarmuka.

## Verifikasi dan penerapan

Hasil verifikasi lokal terakhir setelah validasi upload BIMA/KPRO: **240 tes Python lulus, 9 tes JavaScript lulus,
1 modul integrasi live dilewati**. `git diff --check` tidak menemukan kesalahan
whitespace. Pemeriksaan JavaScript mencakup sintaks script dari tujuh halaman
hasil render, selain tes perilaku fetch, CSRF, escaping, dan form bulk.

Suite regresi memakai fake MySQL dan fake Google Sheets, termasuk jalur kegagalan.
Seluruh akses koneksi live ditolak di fixture. Scheduler dimatikan untuk tes.
Tes mencakup identitas baris setelah filter, tanggal, statistik, konflik, urutan
audit, upload tanpa clear, sinkronisasi, idempotensi transfer, hak akses/sesi,
stale cache, rendering template, dan sintaks JavaScript hasil render.
Tes KPI tambahan memakai grid simulasi dengan 33 kolom sumber, XCEK sesuai jenis
KPI, serta rumus pendukung di sebelah kanan. Upload lebih sedikit/sama banyak/lebih
banyak dan upload berulang memverifikasi data baru, pengosongan sisa data lama,
serta header dan rumus yang tetap utuh. File Excel uji dibuat di memory; data
operasional tidak digunakan. Validasi nilai bisnis dan kecocokan file unduhan
asli masih perlu diverifikasi dengan contoh file resmi.

File unduhan asli TTI `data_detail_202512.xls` diuji terpisah di endpoint lokal
dengan MySQL/Google Sheets diganti simulasi. Seluruh 258 baris x 33 kolom hasil
upload cocok dengan pembacaan pembanding independen. Simulasi 300 baris lama
menjadi 258 baris baru mengosongkan 42 baris sisanya dalam satu update A2:AG301,
tanpa menyentuh header atau kolom pendukung. File sumber tidak diubah/disalin
ke repository. Kasus struktur HTML portal direpresentasikan oleh fixture sintetis
agar tes rutin tidak bergantung pada file pribadi.

Kolom TTI, FFG, dan TTR tidak disamakan: masing-masing tetap mengikuti header
area impor sheet tujuannya. Hanya contoh asli TTI yang tersedia dan sudah diuji;
FFG/TTR baru diuji menggunakan data sintetis, bukan file unduhan portal asli.
Pemetaan lengkap dan batas maksimal 33 kolom sumber untuk FFG/TTR masih perlu
dicocokkan dengan contoh ekspor aslinya sebelum menyatakan kompatibilitas penuh.

Suite HTTP live yang lama memerlukan dependensi tambahan pada
`backend/requirements-test.txt`. Ketika live test tidak diaktifkan, suite dilewati
sebelum memuat dependensi opsional tersebut.

```powershell
.\venv\Scripts\python.exe -m pytest backend/tests/backend/test_backend_regressions.py -q
node --test backend/tests/frontend/test_upload_and_shared_ui.cjs
```

Sebelum penerapan, pilih database sesuai `MYSQL_DB` dan jalankan
`backend/user_db.sql` di lingkungan uji. Skrip menggunakan CREATE TABLE IF NOT EXISTS;
tidak menghapus/mengisi ulang tabel yang sudah ada dan tidak memperbaiki otomatis
struktur tabel lama yang berbeda. `user_db.sql` sekarang menjadi satu-satunya
file instalasi SQL; isinya telah menggantikan dump lama dan skema tambahan.
File ini tidak berisi seed akun/password dan bukan migrasi database lama.

Deploy backend, template, dan JavaScript bersamaan. Sesi sebelum perubahan belum
memiliki auth_stamp dan akan diminta login ulang. Browser yang masih memakai modal
lama tanpa original_values akan diminta memuat ulang; server tidak menebak snapshot.

Untuk beberapa worker, aktifkan scheduler hanya pada satu proses terpilih.
Uji integrasi pada salinan spreadsheet/database: edit setelah filter, dua pengguna
bersamaan, edit langsung Google Sheets saat modal terbuka, upload lebih pendek,
role/password berubah saat login, serta uji mount root dan /api. Suite live lama
memerlukan FILTERIN_RUN_LIVE_TESTS=1, REACT_APP_BACKEND_URL, dan kredensial test melalui
environment; jangan menunjuk data produksi.

Tidak ada DDL, transfer UNSC, sinkronisasi BIMA, maupun upload yang dijalankan
terhadap layanan operasional dalam pekerjaan ini. Kelulusan unit/regresi tidak
menyatakan integrasi live, kuota Google API, hak named lock MySQL, atau layout sheet
aktual telah tervalidasi.

### Quick Edit: pemuatan dan penanda baris tersimpan (17 September 2026)

- Modal semula ditampilkan sebelum respons lock dan pembacaan baris selesai,
  sehingga terlihat placeholder strip atau nilai modal sebelumnya. Sekarang isi
  modal disembunyikan selama pemuatan, dengan status yang eksplisit. Form dan
  tombol Simpan baru diaktifkan setelah data terbaru tersedia dan lock diperoleh.
  Kegagalan pemuatan menyediakan pesan dan tombol Coba lagi. Pembacaan langsung
  Google Sheets tetap dipertahankan; perubahan ini memperjelas waktu tunggu,
  bukan mengklaim menghilangkan latensi jaringan/API.
- Respons data/riwayat lama diabaikan setelah modal ditutup atau berganti order.
  Operasi lock/unlock diurutkan agar penutupan sebelum lock selesai tetap
  melepaskan lock tersebut. Selama penyimpanan, modal tidak bisa berganti order.
- Highlight lama memakai deklarasi `!important` di keyframe animasi, yang diabaikan
  browser, serta bersaing dengan latar sel tabel. Penggantinya memakai tint hijau,
  garis batas dalam sel, dan label `✓ Baru disimpan` pada kolom tombol edit.
  Penanda aktif 15 detik setelah respons simpan sukses, berdasarkan ORDER_ID,
  tanpa bergantung pada ditemukannya input yang diubah.
- Pemuatan ulang otomatis ditunda selama penanda aktif, termasuk respons polling
  yang sedang berjalan. Waktu kedaluwarsa disimpan di sessionStorage agar reload
  manual dapat mengembalikan sisa durasinya; reload tidak mengulang 15 detik.
  Kegagalan akses sessionStorage tidak menghalangi highlight pada halaman aktif.
- Tes browser memakai respons API sintetis dan CSS tabel aktual, bukan layanan
  operasional. Cakupannya meliputi pemuatan lambat/gagal, retry, lock pengguna lain,
  respons data/riwayat terlambat, penutupan saat lock belum selesai, simpan
  sukses/gagal, penguncian UI saat simpan, computed style highlight, kedaluwarsa,
  reload, simpan ulang, storage tidak tersedia, dan perlindungan polling.
  Hasil: 24 tes JavaScript lolos (9 sebelumnya + 15 baru), 240 tes Python lolos,
  1 suite live dilewati. Tampilan pada aplikasi yang sedang digunakan pengguna
  tetap perlu dicoba setelah browser memuat JavaScript terbaru.

Tes baru memerlukan Playwright dan browser pengujian yang tersedia. Jika belum
terpasang, tes browser dilewati secara eksplisit. Instalasi Playwright yang sudah
ada dapat dipilih melalui `FILTERIN_PLAYWRIGHT_PATH`; browser lokal seperti Edge
dapat dipilih melalui `FILTERIN_BROWSER_CHANNEL=msedge`.

```powershell
node --test backend/tests/frontend/test_upload_and_shared_ui.cjs backend/tests/frontend/test_quick_edit_and_table_refresh.cjs
```

### Pengeditan beberapa pengguna: lease dan perlindungan input

- Quick Edit memperpanjang lock maksimal setiap 30 detik (menyesuaikan TTL yang
  diberikan server), memeriksanya saat tab kembali aktif dan sebelum menyimpan.
  Endpoint `/renew-lock` hanya memperpanjang lock pengguna yang masih berlaku;
  tidak membuat lock baru atau mengambil lock pengguna lain. Jika akses tidak
  bisa dipastikan, Simpan dinonaktifkan dan input tetap berada di modal. Tombol
  `Periksa akses edit` melakukan permintaan penguncian ulang secara eksplisit,
  tanpa mengganti snapshot/nilai awal atau menghapus draft pengguna.
- Edit inline tetap menggunakan pemeriksaan konflik/lock pada saat simpan, bukan
  memperoleh lease sejak fokus masuk ke input. Jika baris draft dikunci pengguna
  lain, nilai dipertahankan, peringatan ditampilkan, dan pengiriman form diblokir
  agar input disabled tidak diam-diam terlewat. Setelah lock dilepas, status
  readonly/disabled awal dipulihkan, termasuk TGL FEEDBACK yang harus readonly.
  Kegagalan polling lock tidak lagi dianggap sebagai semua lock sudah dilepas.
- Form bulk Kendala Master/UNSC memakai respons JSON untuk menyimpan tanpa
  meninggalkan halaman ketika gagal. Hanya field berubah dan snapshot asli yang
  dikirim; konflik tidak menyebabkan reload atau rebase snapshot otomatis. Input
  dibekukan selama request, submit ganda dicegah, dan kegagalan jaringan tetap
  menyisakan draft dengan peringatan bahwa hasil simpan harus diperiksa.
  Keberhasilan biasa memuat ulang halaman dengan filter tetap; jika Audit Log
  gagal, peringatan tetap terlihat dan snapshot baris yang berhasil diperbarui.
- Quick Edit tidak dibuka untuk baris yang memiliki draft inline agar penyimpanan
  modal tidak menghapus penanda perubahan inline. Polling data dan lock ditahan
  selama bulk save; UNSC memeriksa ulang status edit/draft saat respons tiba.
- Pengujian menggunakan layanan tiruan, termasuk dua sesi browser dengan pemilik
  lock berbeda dan draft lama setelah pengguna pertama menyimpan. Tidak ada
  perubahan schema/database atau data operasional. Lock masih berbasis username
  sebagaimana desain sebelumnya, bukan token unik per tab/perangkat. Editor
  langsung Google Sheets tetap tidak terikat lock FilterIN. Draft dipertahankan
  pada halaman aktif; menutup atau me-refresh halaman secara manual masih dapat
  menghilangkannya. Ini bukan fitur penyimpanan draft permanen.
- Verifikasi akhir perubahan ini: 256 tes Python lolos, 1 suite live dilewati,
  dan 35 tes JavaScript lolos. Tes durasi menggunakan jam browser yang dibekukan
  agar batas 15 detik tidak bergantung pada lama proses pemeriksaan test runner.
  Backend, JavaScript, dan kedua template harus diterapkan bersama; restart
  backend dan muat ulang browser agar endpoint pembaruan lock tersedia.

### Penyelarasan role setelah audit (18 September 2026)

- GET `/order_history/<order_id>` dan GET `/api/cache_status` sekarang memakai
  `api_login_required` dan `api_role_required('admin', 'operator')`. Viewer
  mendapat 403 JSON, termasuk ketika mengetik URL secara langsung atau ketika
  role akun pada sesi lama telah diturunkan di database. Tanpa login: 401 JSON.
  Query isi riwayat/cache tidak dijalankan untuk role yang ditolak.
- Tombol hapus watchlist hanya tampil jika role diizinkan menulis DAN pengguna
  merupakan Admin atau pemilik flag. Viewer tidak mendapat tombol hapus meskipun
  masih memiliki flag yang dibuat sebelum perubahan role. Daftar watchlist tetap
  bisa dibaca Viewer; pembatasan kepemilikan di endpoint hapus tidak diubah.
- Halaman Audit Log keseluruhan dan POST `/api/cache_refresh` tetap khusus Admin;
  izin membaca status cache tidak memberikan izin menjalankan refresh.
- Tes: 273 tes Python lolos, 1 suite live dilewati; 13 tes JavaScript frontend core
  lolos. Cakupan tambahan meliputi role Admin/Operator/Viewer/tidak dikenal,
  sesi lama, akses tanpa login, refresh tetap khusus Admin, serta tombol pada flag
  sendiri/milik pengguna lain dan watchlist kosong. Layanan operasional tidak
  diakses; tidak ada perubahan schema/database atau data Google Sheets.

### Konsolidasi file SQL (20 September 2026)

- `backend/user_db.sql` menjadi satu-satunya file instalasi, berisi sembilan tabel
  dari skema terbaru. Semua definisi CREATE TABLE dibandingkan dan sama persis
  dengan skema terbaru sebelum konsolidasi; dump lama dan seed akun plaintext
  tidak dipertahankan sebagai instruksi instalasi.
- File `backend/schema.sql` dan `backend/watchlist_announcement.sql` dihapus dari
  working tree karena isinya telah tercakup. Versi yang pernah dicommit tetap
  dapat dipulihkan melalui Git; struktur terbaru dipertahankan di user_db.sql.
- README, panduan instalasi, dan tes diarahkan ke file tunggal. Panduan Admin awal
  menggunakan hash password dari Werkzeug dan tidak menyediakan akun bawaan.
- Penggabungan ini hanya mengubah file repository, bukan menjalankan SQL. Database
  aktif tetap utuh. Untuk database lama, backup dan pemeriksaan struktur tetap
  diperlukan: CREATE TABLE IF NOT EXISTS tidak memigrasikan kolom/index lama.
- Verifikasi lokal: 276 tes Python lolos, 1 suite live dilewati. Tes memastikan
  sembilan tabel unik, kolom sinkronisasi/login/lock yang sesuai, tidak ada seed
  atau perintah penghapusan data, serta referensi instalasi yang konsisten.
  Import ke server MySQL/MariaDB sungguhan belum dijalankan pada perubahan ini.

### Penangan tombol sinkronisasi dan penanda NEW (21 September 2026)

- Ditemukan dua penangan klik untuk tombol Sinkronisasi BIMA dan Pindah ke UNSC:
  `onclick` pada template dan listener tambahan dalam `static/script.js`.
  Tes browser terisolasi mereproduksi satu permintaan meskipun konfirmasi ditolak,
  serta dua permintaan ketika disetujui. Penangan tambahan di `script.js` dihapus;
  alur konfirmasi dan pengiriman pada `kendalamaster.html` dipertahankan.
- `highlightNewRows()` lama menebak data baru dari tanggal hari ini di sel mana pun.
  Fungsi dan pemanggilannya dihapus. Penanda NEW sekarang hanya mengikuti
  `is_new_flags` dari metadata sinkronisasi backend; tanggal order/feedback tidak
  menjadi acuan. Highlight Quick Edit selama 15 detik tidak diubah.
- Tes tambahan mencakup konfirmasi Batal/OK pada kedua tombol, data lama dengan
  tanggal hari ini, data baru dengan tanggal order lama, filter `new_only`, dan
  hilangnya penanda setelah ditandai dibaca tanpa menghapus order.
- Verifikasi: 279 tes Python dan 44 tes JavaScript/frontend lolos; satu suite
  integrasi langsung dilewati. Pengujian browser memakai Edge headless dengan
  layanan tiruan. Database dan Google Sheets operasional tidak diakses.
- Batal pada dialog konfirmasi berarti permintaan belum dikirim. Ini berbeda
  dari tombol Cancel ketika proses sudah berjalan: menghentikan penantian browser
  tidak menjamin pembatalan pekerjaan yang telah diterima server.

### Deteksi perubahan Kendala Master tanpa reload palsu (21 September 2026)

- Pemeriksaan tabel setiap 10 detik sebelumnya membandingkan data API dengan
  teks sel/nilai dropdown di browser. Nilai kosong yang tampil sebagai pilihan
  pertama, atau spasi yang dipangkas dari teks, dapat dianggap perubahan setiap
  kali pemeriksaan meskipun data sumber tidak berubah.
- Pengujian browser terisolasi juga mereproduksi urutan fokus di kolom edit,
  klik Pindah ke UNSC, lalu Cancel/OK: ketika fokus keluar, pemeriksaan yang
  tertahan aktif kembali. Ini menjelaskan kemungkinan munculnya gejala setelah
  tombol diklik tanpa harus ada pemindahan data ketika konfirmasi ditolak.
- `_kendala_view_revision()` sekarang membuat hash deterministik dari kolom,
  data halaman, nomor baris sheet, penanda NEW, dan total hasil filter. HTML dan
  `/kendala_data` memakai helper yang sama. Hash ini pembanding versi tampilan,
  bukan token otorisasi atau pengganti snapshot pengendalian konflik edit.
- Frontend membandingkan versi tersebut, bukan isi DOM. Pemeriksaan tetap 10
  detik, tidak menumpuk request, mengabaikan respons gagal/tidak lengkap, dan
  tidak memulai reload kedua saat navigasi masih berlangsung. Kondisi edit,
  modal Quick Edit, draft, simpan, highlight, serta sinkronisasi/pemindahan aktif
  diperiksa sebelum request dan sebelum reload.
- Tes tambahan memeriksa kesamaan versi HTML/API pada halaman/filter berbeda,
  perubahan data/kolom/urutan/NEW/jumlah, serta tiga siklus pemeriksaan setelah
  Cancel maupun OK tanpa reload ketika data tetap sama. Semua layanan operasional
  diganti tiruan; tidak ada penulisan ke MySQL atau Google Sheets asli.
- Penerapan memerlukan restart proses Flask/Waitress karena backend ikut berubah,
  kemudian muat ulang halaman browser agar versi awal berasal dari kode terbaru.
- Verifikasi akhir: 288 tes Python lolos (satu suite live dilewati), serta 47 tes
  JavaScript/frontend lolos, termasuk pengujian Edge headless terisolasi.
