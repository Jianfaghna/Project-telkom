"""
FilterIN - Setup Dummy Google Sheets
=====================================
Script ini membuat Google Spreadsheet baru dengan data dummy
untuk halaman-halaman backlog FilterIN:
  - RECAP REPORT    (summary)
  - TATI            (tati)
  - LAP VALIDASI ODP (lapvalidasiodp)
  - PS RE TTI       (psretti)
  - WO KENDALA      (wokendala)
  - DB KENDALA (MASTER) (kendalamaster - utama)
  - DB UNSC (END STATE) (unsc)

CARA PAKAI:
  1. Pastikan file credentials.json ada di folder backend/
  2. Install: pip install gspread google-auth
  3. Jalankan dari root project:
       python setup_dummy_sheets.py
  4. Script akan print Spreadsheet ID baru -> copy ke .env

CATATAN:
  Script ini membuat 2 spreadsheet:
  - FILTERIN_KENDALA  (sheet utama kendala + laporan)
  - FILTERIN_UPLOAD   (sheet upload BIMA/KPRO)
"""

import os
import sys
import json
import time
import random
from datetime import datetime, timedelta
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("[ERROR] Library belum terinstall. Jalankan:")
    print("        pip install gspread google-auth")
    sys.exit(1)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
CREDS_PATH = Path(__file__).parent / "backend" / "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

# Nama-nama STO/datel di Witel Magelang (dummy)
DATEL_LIST = ["MAGELANG", "TEMANGGUNG", "WONOSOBO", "PURWOREJO", "KEBUMEN"]
ENGINEER_LIST = ["Budi Santoso", "Agus Prayitno", "Siti Rahayu", "Doni Kurniawan", "Wati Lestari"]
KENDALA_LIST = ["KABEL PUTUS", "ODP PENUH", "REDAMAN TINGGI", "POWER MATI", "ONT RUSAK", "SPLITTER RUSAK"]
STATUS_LIST  = ["OPEN", "ON PROGRESS", "CLOSE", "PENDING"]
TIPE_WO_LIST = ["PSTN", "INDIHOME", "INDIBIZ", "METRO"]

def random_date(start_days_ago=30, end_days_ago=0):
    base = datetime.now() - timedelta(days=random.randint(end_days_ago, start_days_ago))
    return base.strftime("%d/%m/%Y")

def random_order_id():
    return f"WO{random.randint(10000000, 99999999)}"

def random_sto():
    return random.choice(["MGL", "TMG", "WNS", "PWR", "KBM"])

# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────
def get_gc():
    if not CREDS_PATH.exists():
        print(f"[ERROR] File credentials.json tidak ditemukan di: {CREDS_PATH}")
        print("        Pastikan file credentials.json ada di folder backend/")
        sys.exit(1)

    creds = Credentials.from_service_account_file(str(CREDS_PATH), scopes=SCOPES)
    gc = gspread.authorize(creds)
    print(f"[OK] Authenticated sebagai: {creds.service_account_email}")
    print(f"     >> Share spreadsheet ke email di atas agar bisa diakses FilterIN\n")
    return gc, creds.service_account_email

# ─────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────
def write_sheet(ws, headers, rows):
    """Tulis header + rows ke worksheet sekaligus (batch)."""
    all_data = [headers] + rows
    ws.update("A1", all_data)
    # Format header row: bold + background biru Telkom
    ws.format("A1:{}1".format(chr(64 + len(headers))), {
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "backgroundColor": {"red": 0.204, "green": 0.396, "blue": 0.643},
        "horizontalAlignment": "CENTER"
    })
    print(f"    [✓] Sheet '{ws.title}' → {len(rows)} baris data dummy")

def safe_create_sheet(ss, title):
    """Buat worksheet baru, atau pakai yang sudah ada."""
    try:
        ws = ss.add_worksheet(title=title, rows=200, cols=50)
    except gspread.exceptions.APIError:
        ws = ss.worksheet(title)
    return ws

# ─────────────────────────────────────────────
# DATA GENERATORS
# ─────────────────────────────────────────────

def gen_kendalamaster(n=30):
    """DB KENDALA (MASTER) — sheet utama, dipakai Kendala Master & UNSC."""
    headers = [
        "NO", "ORDER_ID", "TGL WO", "STO", "DATEL", "NAMA PELANGGAN",
        "NO TELP", "ALAMAT", "TIPE WO", "SUBERRORCODE", "ENGINEERMEMO",
        "ACTUAL KENDALA", "FEEDBACK ASO", "TGL FEEDBACK",
        "NOTES ASO", "STATUS", "LAMA WO", "UMUR KENDALA",
        "VERIFIKASI", "ENGINEER", "KETERANGAN"
    ]
    rows = []
    for i in range(1, n + 1):
        tgl_wo = random_date(30, 5)
        tgl_fb = random_date(5, 0) if random.random() > 0.3 else ""
        rows.append([
            i,
            random_order_id(),
            tgl_wo,
            random_sto(),
            random.choice(DATEL_LIST),
            f"Pelanggan {i:03d}",
            f"08{random.randint(100000000, 999999999)}",
            f"Jl. Contoh No.{i}, {random.choice(DATEL_LIST)}",
            random.choice(TIPE_WO_LIST),
            f"ERR-{random.randint(100,999)}",
            random.choice(["Signal loss", "No internet", "Slow speed", "Intermittent", ""]),
            random.choice(KENDALA_LIST + [""]),
            random.choice(["Sudah dikerjakan", "Menunggu part", "Pelanggan tidak ada", ""]),
            tgl_fb,
            f"Catatan dummy {i}",
            random.choice(STATUS_LIST),
            random.randint(1, 30),
            random.randint(1, 15),
            random.choice(["YA", "TIDAK", ""]),
            random.choice(ENGINEER_LIST),
            ""
        ])
    return headers, rows

def gen_unsc(n=15):
    """DB UNSC (END STATE) — data yang sudah dipindah dari kendalamaster."""
    headers = [
        "NO", "ORDER_ID", "TGL WO", "STO", "DATEL", "NAMA PELANGGAN",
        "TIPE WO", "ACTUAL KENDALA", "FEEDBACK ASO", "TGL FEEDBACK",
        "STATUS AKHIR", "TGL CLOSE", "ENGINEER", "LAMA WO", "KETERANGAN"
    ]
    rows = []
    for i in range(1, n + 1):
        rows.append([
            i, random_order_id(), random_date(60, 10),
            random_sto(), random.choice(DATEL_LIST),
            f"Pelanggan UNSC {i:03d}",
            random.choice(TIPE_WO_LIST),
            random.choice(KENDALA_LIST),
            "Selesai dikerjakan",
            random_date(10, 1),
            "CLOSE",
            random_date(10, 1),
            random.choice(ENGINEER_LIST),
            random.randint(1, 45),
            ""
        ])
    return headers, rows

def gen_recap_report():
    """RECAP REPORT — 7 tabel ringkasan, dipakai halaman /summary."""
    tables = {}

    # Tabel 1: Rekapitulasi per Datel
    tables["t1"] = {
        "headers": ["DATEL", "TOTAL WO", "OPEN", "ON PROGRESS", "CLOSE", "% CLOSE"],
        "rows": [[d, random.randint(20,80), random.randint(2,10),
                  random.randint(5,15), random.randint(10,50),
                  f"{random.randint(60,95)}%"] for d in DATEL_LIST]
    }
    # Tabel 2: Rekapitulasi per Tipe WO
    tables["t2"] = {
        "headers": ["TIPE WO", "TOTAL", "CLOSE", "PENDING", "SLA%"],
        "rows": [[t, random.randint(10,60), random.randint(5,40),
                  random.randint(1,10), f"{random.randint(70,99)}%"] for t in TIPE_WO_LIST]
    }
    # Tabel 3: Top Kendala
    tables["t3"] = {
        "headers": ["JENIS KENDALA", "JUMLAH", "PERSENTASE"],
        "rows": [[k, random.randint(3,20), f"{random.randint(5,30)}%"] for k in KENDALA_LIST]
    }
    # Tabel 4: Rekapitulasi harian (7 hari terakhir)
    tables["t4"] = {
        "headers": ["TANGGAL", "WO MASUK", "WO SELESAI", "SISA"],
        "rows": [
            [(datetime.now() - timedelta(days=i)).strftime("%d/%m/%Y"),
             random.randint(3,15), random.randint(2,12), random.randint(1,8)]
            for i in range(7)
        ]
    }
    # Tabel 5: Kinerja Engineer
    tables["t5"] = {
        "headers": ["NAMA ENGINEER", "WO DITANGANI", "WO CLOSE", "AVG LAMA WO"],
        "rows": [[e, random.randint(5,20), random.randint(3,15),
                  f"{random.randint(1,10)} hari"] for e in ENGINEER_LIST]
    }
    # Tabel 6: SLA Summary
    tables["t6"] = {
        "headers": ["PERIODE", "TARGET SLA", "AKTUAL SLA", "STATUS"],
        "rows": [
            ["Minggu ini", "85%", f"{random.randint(80,95)}%", "✓"],
            ["Bulan ini",  "85%", f"{random.randint(75,92)}%", "✓"],
            ["Kumulatif",  "85%", f"{random.randint(78,90)}%", "✓"],
        ]
    }
    # Tabel 7: Pending > 7 hari
    tables["t7"] = {
        "headers": ["ORDER_ID", "DATEL", "LAMA WO", "KENDALA", "ENGINEER"],
        "rows": [
            [random_order_id(), random.choice(DATEL_LIST),
             random.randint(8,30), random.choice(KENDALA_LIST),
             random.choice(ENGINEER_LIST)]
            for _ in range(8)
        ]
    }
    return tables

def gen_tati():
    """Sheet TATI — 2 range tabel (B2:O10 dan R2:AX10)."""
    # Tabel 1: B2:O10 (14 kolom, 9 baris)
    h1 = ["KATEGORI", "STO MGL", "STO TMG", "STO WNS", "STO PWR", "STO KBM",
          "TOTAL", "TARGET", "DELTA", "MTD", "YTD", "%ACHIEVE", "RANK", "KET"]
    r1 = []
    for cat in ["TTI", "FFG", "TTR", "MTTR", "AVAI", "SLA", "COMPLAINT", "REPEAT"]:
        r1.append([cat] + [random.randint(10, 99) for _ in range(5)] +
                  [sum(range(10,15))] + [random.randint(80, 100)] +
                  [random.randint(-5, 5)] + [f"{random.randint(70,99)}%"] +
                  [f"{random.randint(70,99)}%"] + [f"{random.randint(80,100)}%"] +
                  [random.randint(1, 5)] + [""])

    # Tabel 2: R2:AX10 (38 kolom, 9 baris) — breakdown per hari
    days = [(datetime.now() - timedelta(days=i)).strftime("%d/%m") for i in range(7)]
    h2 = ["INDIKATOR"] + days + [f"D{i}" for i in range(len(days), 37)]
    r2 = []
    for ind in ["TTI_IH", "TTI_IB", "FFG_IH", "FFG_IB", "TTR", "MTTR", "AVAI", "SLA"]:
        r2.append([ind] + [random.randint(1, 20) for _ in range(len(h2) - 1)])

    return (h1, r1), (h2, r2)

def gen_lapvalidasiodp():
    """LAP VALIDASI ODP — 4 range tabel."""
    # Tabel 1: O5:S20 (5 kolom, 15 baris)
    h1 = ["NAMA ODP", "KAPASITAS", "TERPAKAI", "SISA", "STATUS"]
    r1 = [[f"ODP-{random_sto()}-F{i:02d}-{random.randint(1,9)}",
           random.choice([8, 16, 32]),
           random.randint(1, 30),
           random.randint(0, 10),
           random.choice(["NORMAL", "PENUH", "KRITIS"])] for i in range(1, 16)]

    # Tabel 2: V5:V33 (1 kolom, 28 baris)
    h2 = ["CATATAN VALIDASI"]
    r2 = [[f"Validasi ODP ke-{i}: {random.choice(['OK', 'Perlu pengecekan', 'Sudah diperluas'])}"]
          for i in range(1, 29)]

    # Tabel 3: Z5:AD26 (5 kolom, 21 baris)
    h3 = ["WITEL", "DATEL", "TOTAL ODP", "ODP PENUH", "% PENUH"]
    r3 = [[random.choice(["MGL KOTA", "MGL SELATAN", "MGL UTARA"]),
           random.choice(DATEL_LIST),
           random.randint(50, 200),
           random.randint(5, 30),
           f"{random.randint(5,20)}%"] for _ in range(21)]

    # Tabel 4: AF5:AF26 (1 kolom, 21 baris)
    h4 = ["REKOMENDASI"]
    r4 = [[random.choice(["Expand ODP", "Monitor", "Prioritas expand", "OK"])]
          for _ in range(21)]

    return (h1, r1), (h2, r2), (h3, r3), (h4, r4)

def gen_psretti():
    """PS RE TTI — Housekeeping AO, data range bebas."""
    headers = [
        "NO", "DATEL", "ORDER_ID", "NAMA PELANGGAN", "TGL PS",
        "TGL RE", "ALASAN RE", "STATUS", "ENGINEER", "KETERANGAN"
    ]
    rows = []
    for i in range(1, 25):
        rows.append([
            i,
            random.choice(DATEL_LIST),
            random_order_id(),
            f"Pelanggan PS {i:03d}",
            random_date(30, 10),
            random_date(10, 1),
            random.choice(["Pelanggan pindah", "Gangguan berulang", "Permintaan sendiri", "Upgrade"]),
            random.choice(["SELESAI", "PROSES", "PENDING"]),
            random.choice(ENGINEER_LIST),
            ""
        ])
    return headers, rows

def gen_wokendala():
    """WO KENDALA — 2 range tabel (K24:R59 dan T23:AL59)."""
    # Tabel 1: K24:R59 (8 kolom, 35 baris)
    h1 = ["TANGGAL", "STO", "TOTAL WO", "OPEN", "PROGRESS", "CLOSE", "SISA", "SLA%"]
    r1 = [
        [(datetime.now() - timedelta(days=i)).strftime("%d/%m/%Y"),
         random.choice(["MGL", "TMG", "WNS"]),
         random.randint(5, 30),
         random.randint(1, 8),
         random.randint(1, 10),
         random.randint(3, 20),
         random.randint(1, 5),
         f"{random.randint(70, 99)}%"]
        for i in range(35)
    ]

    # Tabel 2: T23:AL59 (25 kolom, 36 baris) — breakdown per tipe
    tipe_cols = TIPE_WO_LIST + [f"TIPE{i}" for i in range(5, 26)]
    h2 = ["TANGGAL"] + tipe_cols[:24]
    r2 = [
        [(datetime.now() - timedelta(days=i)).strftime("%d/%m/%Y")] +
        [random.randint(0, 10) for _ in range(24)]
        for i in range(36)
    ]

    return (h1, r1), (h2, r2)

def gen_bima_master(n=20):
    """BIMA MASTER — upload sheet."""
    headers = ["ORDER_ID", "TGL WO", "STO", "NAMA PELANGGAN",
               "TIPE WO", "SUBERRORCODE", "ENGINEERMEMO", "STATUS"]
    rows = [[random_order_id(), random_date(10, 0), random_sto(),
             f"Pelanggan BIMA {i}", random.choice(TIPE_WO_LIST),
             f"ERR-{random.randint(100,999)}", "Signal loss", "OPEN"]
            for i in range(1, n + 1)]
    return headers, rows

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  FilterIN — Setup Dummy Google Sheets")
    print("=" * 60)

    gc, svc_email = get_gc()

    # ── Spreadsheet 1: KENDALA ──────────────────────────────────
    print("[1/2] Membuat spreadsheet FILTERIN_DUMMY_KENDALA ...")
    ss_kendala = gc.create("FILTERIN_DUMMY_KENDALA")
    ss_kendala.share(svc_email, perm_type="user", role="writer", notify=False)
    print(f"      ID: {ss_kendala.id}")

    # Sheet: DB KENDALA (MASTER)
    ws = safe_create_sheet(ss_kendala, "DB KENDALA (MASTER)")
    h, r = gen_kendalamaster(30)
    write_sheet(ws, h, r)
    time.sleep(1)

    # Sheet: DB UNSC (END STATE)
    ws = safe_create_sheet(ss_kendala, "DB UNSC (END STATE)")
    h, r = gen_unsc(15)
    write_sheet(ws, h, r)
    time.sleep(1)

    # Sheet: RECAP REPORT (7 tabel, tulis berurutan ke kolom berbeda)
    ws = safe_create_sheet(ss_kendala, "RECAP REPORT")
    tables = gen_recap_report()
    row_offset = 1
    for tkey, tval in tables.items():
        ws.update(f"A{row_offset}", [tval["headers"]] + tval["rows"])
        row_offset += len(tval["rows"]) + 3  # gap antar tabel
        time.sleep(0.5)
    print(f"    [✓] Sheet 'RECAP REPORT' → 7 tabel dummy")
    time.sleep(1)

    # Sheet: TATI
    ws = safe_create_sheet(ss_kendala, "TATI")
    (h1, r1), (h2, r2) = gen_tati()
    ws.update("B2", [h1] + r1)
    ws.update("R2", [h2] + r2)
    print(f"    [✓] Sheet 'TATI' → 2 range tabel dummy (B2 & R2)")
    time.sleep(1)

    # Sheet: LAP VALIDASI ODP
    ws = safe_create_sheet(ss_kendala, "LAP VALIDASI ODP")
    (h1,r1),(h2,r2),(h3,r3),(h4,r4) = gen_lapvalidasiodp()
    ws.update("O5", [h1] + r1)
    ws.update("V5", [h2] + r2)
    ws.update("Z5", [h3] + r3)
    ws.update("AF5",[h4] + r4)
    print(f"    [✓] Sheet 'LAP VALIDASI ODP' → 4 range tabel dummy")
    time.sleep(1)

    # Sheet: NEW SUMMARY (newsummarykendala)
    ws = safe_create_sheet(ss_kendala, "NEW SUMMARY")
    h_ns = ["TANGGAL", "TOTAL KENDALA", "SELESAI", "SISA", "SLA%", "KETERANGAN"]
    r_ns = [[(datetime.now()-timedelta(days=i)).strftime("%d/%m/%Y"),
              random.randint(10,50), random.randint(5,40),
              random.randint(1,15), f"{random.randint(75,99)}%", ""]
             for i in range(14)]
    write_sheet(ws, h_ns, r_ns)
    time.sleep(1)

    # Hapus sheet default "Sheet1"
    try:
        ss_kendala.del_worksheet(ss_kendala.worksheet("Sheet1"))
    except Exception:
        pass

    # ── Spreadsheet 2: UPLOAD ───────────────────────────────────
    print("\n[2/2] Membuat spreadsheet FILTERIN_DUMMY_UPLOAD ...")
    ss_upload = gc.create("FILTERIN_DUMMY_UPLOAD")
    ss_upload.share(svc_email, perm_type="user", role="writer", notify=False)
    print(f"      ID: {ss_upload.id}")

    ws = safe_create_sheet(ss_upload, "BIMA MASTER")
    h, r = gen_bima_master(20)
    write_sheet(ws, h, r)
    time.sleep(1)

    ws = safe_create_sheet(ss_upload, "KPRO")
    h_kpro = ["ORDER_ID", "TGL", "STO", "PELANGGAN", "STATUS", "CATATAN"]
    r_kpro = [[random_order_id(), random_date(5,0), random_sto(),
               f"Pelanggan KPRO {i}", "OPEN", ""] for i in range(1,16)]
    write_sheet(ws, h_kpro, r_kpro)
    time.sleep(1)

    ws = safe_create_sheet(ss_upload, "BIMA")
    write_sheet(ws, h, r[:10])

    try:
        ss_upload.del_worksheet(ss_upload.worksheet("Sheet1"))
    except Exception:
        pass

    # ── Spreadsheet 3: PS RE (PSRE) ─────────────────────────────
    print("\n[3/3] Membuat spreadsheet FILTERIN_DUMMY_PSRE ...")
    ss_psre = gc.create("FILTERIN_DUMMY_PSRE")
    ss_psre.share(svc_email, perm_type="user", role="writer", notify=False)
    print(f"      ID: {ss_psre.id}")

    # Sheet PS RE TTI
    ws = ss_psre.sheet1
    ws.update_title("PSRE_TTI")
    h, r = gen_psretti()
    write_sheet(ws, h, r)
    time.sleep(1)

    # Sheet WO KENDALA (di dalam PSRE spreadsheet)
    ws_wo = safe_create_sheet(ss_psre, "WO KENDALA")
    (h1,r1),(h2,r2) = gen_wokendala()
    ws_wo.update("K24", [h1] + r1)
    ws_wo.update("T23", [h2] + r2)
    print(f"    [✓] Sheet 'WO KENDALA' → 2 range tabel dummy (K24 & T23)")

    # ── Print hasil ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  SELESAI! Copy ID berikut ke file backend/.env:")
    print("=" * 60)
    print(f"""
SPREADSHEET_KENDALA={ss_kendala.id}
SPREADSHEET_UPLOAD={ss_upload.id}
SPREADSHEET_PSRE={ss_psre.id}

# Tambahkan juga ODP & KPI jika diperlukan:
# SPREADSHEET_ODP=<buat manual atau jalankan lagi>
# SPREADSHEET_KPI=<buat manual atau jalankan lagi>
""")
    print("  PENTING: Spreadsheet sudah otomatis di-share ke service account.")
    print("  Tidak perlu share manual lagi.\n")

    # Simpan ke file untuk referensi
    output = {
        "SPREADSHEET_KENDALA": ss_kendala.id,
        "SPREADSHEET_UPLOAD":  ss_upload.id,
        "SPREADSHEET_PSRE":    ss_psre.id,
        "service_account_email": svc_email,
        "created_at": datetime.now().isoformat()
    }
    out_path = Path(__file__).parent / "dummy_spreadsheet_ids.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"  ID juga disimpan di: {out_path}")

if __name__ == "__main__":
    main()