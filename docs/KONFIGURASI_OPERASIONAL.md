# Konfigurasi Database dan Pembaruan Data

Panduan teknis pendamping [README FilterIN](../README.md).

## Instalasi database

Gunakan hanya [backend/user_db.sql](../backend/user_db.sql) untuk membuat sembilan
tabel pendukung FilterIN. Buat/pilih database sesuai `MYSQL_DB` di `backend/.env`
sebelum mengimpor. File SQL tidak berisi akun atau password bawaan.

Panduan pembuatan Admin awal dengan password hash tersedia pada bagian D
[backend/notes.txt](../backend/notes.txt). Untuk database yang sudah dipakai,
cadangkan dan periksa strukturnya terlebih dahulu: file ini bukan migrasi,
dan `CREATE TABLE IF NOT EXISTS` tidak memperbarui kolom/index tabel lama.

### Batas paket untuk cache

Cache menyimpan JSON satu sheet dalam satu perintah MySQL. Gunakan
`max_allowed_packet=16M` pada bagian `[mysqld]` konfigurasi server (XAMPP:
`C:\xampp\mysql\bin\my.ini`), bukan hanya pada bagian `[mysqldump]`.
Batas 1 MB dapat memutus koneksi saat menyimpan sheet Kendala/UNSC yang besar.
Perubahan file berlaku setelah restart MySQL. Administrator dapat menerapkan
`SET GLOBAL max_allowed_packet = 16777216` untuk koneksi baru tanpa restart;
tetap ubah file konfigurasi agar pengaturan bertahan setelah restart.
Periksa nilai aktif dengan `SELECT @@max_allowed_packet` dari koneksi baru.

Log prefetch membedakan jumlah sumber yang berhasil dibaca dan cache MySQL
yang benar-benar tersimpan. Jika cache gagal, data sumber yang berhasil dibaca
tetap dapat ditampilkan; kegagalan itu tidak mengubah isi Google Sheets.

### Status pembaruan pada dashboard

Admin/Operator dapat membuka **Lihat detail pembaruan** untuk melihat waktu
salinan tiap sumber dan hasil proses terakhir. Tombol **Perbarui Data** tetap
khusus Admin. Respons permintaan hanya berarti diterima; UI memantau hasil
proses, bukan menganggap selesai setelah delapan detik.

Scheduler membaca Kendala Master, UNSC, TTI, FFG, dan TTR FFG sekali saat startup
lalu setiap 300 detik selama proses aplikasi dan layanan pendukung aktif.
`FILTERIN_SCHEDULER_ENABLED=0` menonaktifkan scheduler pada proses tersebut.
Detail dashboard menampilkan status scheduler pada worker yang melayani request
dan countdown jadwal berikutnya. Hitungan memakai selisih jadwal dengan waktu
server, bergerak lokal setiap detik tanpa request tambahan, dan tidak direset
oleh refresh manual atau pemuatan ulang halaman. Saat nol, UI menunggu konfirmasi
backend sebelum menyatakan proses berjalan. Waktu pembaruan tiap sumber tetap
berupa tanggal dan jam. Pada deployment beberapa worker, aktifkan scheduler
hanya di worker yang ditunjuk; status tidak aktif di worker lain tidak membuktikan
bahwa seluruh scheduler mati. Proses refresh memakai named lock MySQL agar tidak
berjalan bersamaan, dan metadata hasil dibagikan melalui satu entri khusus pada
`sheet_cache`; tidak diperlukan tabel baru.

Indikator ketersediaan tidak menyamakan habisnya TTL baca (`SHEET_CACHE_TTL`,
bawaan 30 detik) dengan kegagalan proses. Waktu tiap salinan tetap ditampilkan;
salinan lebih dari dua interval scheduler (10 menit) mendapat peringatan.
TTL pengambilan data tidak diperpanjang. Prefetch ini bukan Sinkronisasi BIMA,
bukan mengunggah file BIMA/KPRO, dan tidak menulis ke sumber Google Sheets.

