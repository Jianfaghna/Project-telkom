"""
FilterIN - Flask application (refactored)
Dibuat untuk Unit Kendala Telkom Magelang
Mount: /api/*  (di-wrap oleh server.py sebagai ASGI)
"""
# PANDUAN PENCARIAN FITUR FILTERIN
# Ctrl+F gabungan penanda [FITUR] dan nama fitur untuk langsung ke bagiannya.
# Penanda [FITUR] dapat muncul di logika proses dan route fitur yang sama.
# Penanda [PENDUKUNG] menunjukkan komponen bersama, bukan menu aplikasi.
# Nama pencarian: Login, Logout, Ganti Password, Hak Akses, Sesi Pengguna,
# Dashboard, Kendala Master, Quick Edit, Riwayat Order, Penguncian Edit,
# Data Baru, UNSC, Sinkronisasi BIMA, Upload BIMA, Upload KPRO,
# User Online, Manajemen Pengguna, Audit Log, KPI IndiHome, Recap Report,
# Watchlist, Pengumuman, Verifikasi ODP, Cache, Google Sheets, Database.
# Peta fitur, template, penyimpanan, dan pengujian: docs/PETA_FITUR.md.
# File tetap satu modul; penanda ini tidak mengubah alur aplikasi.

import os
import re
import json
import time
import uuid
import hashlib
import traceback
from datetime import datetime, timedelta
from functools import wraps
from contextlib import contextmanager
from pathlib import Path
from html.parser import HTMLParser

from dotenv import load_dotenv
import pymysql
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from flask import (
    Flask, render_template, request, redirect, session, url_for,
    flash, jsonify, g, abort, make_response, send_from_directory, has_request_context
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from itsdangerous import URLSafeSerializer, BadSignature
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# =====================================================================
# [PENDUKUNG] Konfigurasi - environment, nama Google Sheets, dan batas waktu
# =====================================================================
MYSQL = dict(
    host=os.environ['MYSQL_HOST'],
    port=int(os.environ.get('MYSQL_PORT', 3306)),
    user=os.environ['MYSQL_USER'],
    password=os.environ['MYSQL_PASSWORD'],
    database=os.environ['MYSQL_DB'],
    cursorclass=pymysql.cursors.DictCursor,
    autocommit=False,
    charset='utf8mb4',
)

SPREADSHEET_IDS = {
    'upload':  os.environ['SPREADSHEET_UPLOAD'],
    'kendala': os.environ['SPREADSHEET_KENDALA'],
    'ODP':     os.environ['SPREADSHEET_ODP'],
    'PSRE':    os.environ['SPREADSHEET_PSRE'],
    'kpi':     os.environ.get('SPREADSHEET_KPI', '1HU7lSt0ZiZNN9PpjMwcVhl1Sw8FWOGfFvNS6tng7nwQ'),
}

SHEET_NAMES = {
    'upload':  {'04': 'BIMA MASTER', '05': 'KPRO', '06': 'BIMA'},
    'kendala': {
        'bima_fresh':    'IMPORT BIMA (FRESH)',
        'kendalamaster': 'DB KENDALA (MASTER)',
        'unsc':          'DB UNSC (END STATE)',
        'laporan':       'NEW SUMMARY',
        'tabsum':        'RECAP REPORT',
        'tati':          'TATI',
        'lapodp':        'LAP VALIDASI ODP',
    },
    'ODP': {'validasi': 'MONITORING EXPAND 1:2'},
    'kpi': {
        'tti_upload':  'upload DB TTI_Total',
        'ffg_upload':  'upload DB FFG_Total',
        'ttr_upload':  'upload DB TTR FFG_Total',
        'tti_result':  'MGL_NC TTI_REG_FM',
        'ffg_result':  'MGL_NC FFG_REG_FM',
        'ttr_result':  'MGL_NC TTR FFG_REG_FM',
    },
}

SHEET_CACHE_TTL = int(os.environ.get('SHEET_CACHE_TTL', 30))
EDIT_LOCK_TTL_MINUTES = int(os.environ.get('EDIT_LOCK_TTL_MINUTES', 5))
SYNC_LOG_FILE = str(ROOT_DIR / 'last_sync_time.txt')

# =====================================================================
# [PENDUKUNG] Inisialisasi Aplikasi - session, CSRF, dan pembatasan request
# =====================================================================
flask_app = Flask(
    __name__,
    template_folder=str(ROOT_DIR / 'templates'),
    static_folder=str(ROOT_DIR / 'static'),
    static_url_path='/static',
)
flask_app.secret_key = os.environ['FLASK_SECRET_KEY']
flask_app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
flask_app.config['SESSION_COOKIE_HTTPONLY'] = True
flask_app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
flask_app.config['WTF_CSRF_TIME_LIMIT'] = None
flask_app.config['TEMPLATES_AUTO_RELOAD'] = True
flask_app.jinja_env.auto_reload = True
flask_app.jinja_env.globals.update(min=min, max=max)

# Trust reverse proxy (Emergent ingress) so request.remote_addr is correct
flask_app.wsgi_app = ProxyFix(flask_app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

csrf = CSRFProtect(flask_app)

limiter = Limiter(
    get_remote_address,
    app=flask_app,
    default_limits=[],
    storage_uri="memory://",
)

# Jalankan background scheduler setelah app siap
import threading as _threading
def _deferred_start():
    import time as _time
    # Tunggu sampai MySQL siap (max 30 detik)
    for i in range(10):
        try:
            with flask_app.app_context():
                with db_cursor() as (conn, cur):
                    cur.execute("SELECT 1")
            break  # MySQL siap
        except Exception:
            _time.sleep(3)
    # Mulai scheduler
    with flask_app.app_context():
        _start_scheduler()

# Scheduler dimulai setelah seluruh fungsi terdefinisi (lihat akhir modul).

# =====================================================================
# [PENDUKUNG] Database MySQL - koneksi dan transaksi
# =====================================================================
@contextmanager
def db_cursor():
    conn = pymysql.connect(**MYSQL)
    try:
        yield conn, conn.cursor()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
# [PENDUKUNG] Serialisasi Penulisan Google Sheets - mencegah proses tulis bersamaan
def sheet_write_guard(spreadsheet_id):
    """Serialisasi penulis FilterIN lintas worker; bukan lock editor Google Sheets."""
    name = 'filterin:' + hashlib.sha256(spreadsheet_id.encode()).hexdigest()[:48]
    with db_cursor() as (conn, cur):
        cur.execute('SELECT GET_LOCK(%s, 10) AS acquired', (name,))
        if (cur.fetchone() or {}).get('acquired') != 1:
            raise RuntimeError('Proses lain sedang menulis spreadsheet. Coba kembali.')
        try:
            yield
        finally:
            cur.execute('SELECT RELEASE_LOCK(%s)', (name,))


def serialized_sheet_write(group):
    def decorate(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            try:
                with sheet_write_guard(SPREADSHEET_IDS[group]):
                    return func(*args, **kwargs)
            except Exception as exc:
                flask_app.logger.exception('Penulisan spreadsheet gagal')
                if not has_request_context():
                    raise
                if request.is_json or request.accept_mimetypes.best == 'application/json' or request.endpoint in ('api_sync_bima', 'api_move_to_unsc'):
                    return jsonify(ok=False, status='error', error=str(exc), message=str(exc)), 503
                flash(f'Penulisan belum berhasil: {exc}', 'error')
                return redirect(url_for('dashboard'))
        return wrapped
    return decorate

# =====================================================================
# [PENDUKUNG] Google Sheets - klien API
# =====================================================================
_gs_client = None
_sheet_cache = {}   # key: (spreadsheet_key, sheet_name) -> {'ts':..., 'data':...}

def gs_client():
    """Lazy-init Google Sheets client."""
    global _gs_client
    if _gs_client is None:
        creds_path = ROOT_DIR / os.environ.get('GOOGLE_CREDS_PATH', 'credentials.json')
        creds = Credentials.from_service_account_file(
            str(creds_path),
            scopes=['https://www.googleapis.com/auth/spreadsheets'],
        )
        _gs_client = gspread.authorize(creds)
    return _gs_client

# =====================================================================
# [PENDUKUNG] Cache - penyimpanan sementara Google Sheets di MySQL
# =====================================================================

# Sheet yang di-pre-fetch oleh background job
PREFETCH_SHEETS = [
    ('kendala', 'kendalamaster'),
    ('kendala', 'unsc'),
    ('kpi',     'tti_upload'),
    ('kpi',     'ffg_upload'),
    ('kpi',     'ttr_upload'),
]

def _ensure_cache_table():
    """Buat tabel sheet_cache di MySQL kalau belum ada — dengan retry."""
    for attempt in range(5):
        try:
            with db_cursor() as (conn, cur):
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS sheet_cache (
                        cache_key    VARCHAR(255) NOT NULL PRIMARY KEY,
                        data_json    LONGTEXT     NOT NULL,
                        fetched_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                     ON UPDATE CURRENT_TIMESTAMP,
                        row_count    INT          DEFAULT 0,
                        INDEX idx_fetched (fetched_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
            print('[CACHE] Tabel sheet_cache siap.')
            return True
        except Exception as e:
            wait = (attempt + 1) * 3
            print(f'[CACHE] Gagal buat tabel (attempt {attempt+1}/5): {e} — retry {wait}s')
            time.sleep(wait)
    print('[CACHE] Gagal buat tabel sheet_cache setelah 5 percobaan.')
    return False


def _cache_key(spreadsheet_key, sheet_name):
    raw = f'{spreadsheet_key}::{sheet_name}'
    return hashlib.md5(raw.encode()).hexdigest()


def _read_mysql_cache(spreadsheet_key, sheet_name, max_age_seconds=300):
    """Baca cache dari MySQL. Return data atau None kalau expired/tidak ada."""
    key = _cache_key(spreadsheet_key, sheet_name)
    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT data_json, fetched_at,
                       TIMESTAMPDIFF(SECOND, fetched_at, NOW()) AS age_seconds
                FROM sheet_cache
                WHERE cache_key = %s
            """, (key,))
            row = cur.fetchone()
            if not row:
                return None
            if row['age_seconds'] > max_age_seconds:
                return None
            return json.loads(row['data_json'])
    except Exception:
        return None


def _write_mysql_cache(spreadsheet_key, sheet_name, data):
    """Return True hanya jika penulisan cache dan commit berhasil."""
    key = _cache_key(spreadsheet_key, sheet_name)
    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                INSERT INTO sheet_cache (cache_key, data_json, row_count)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    data_json  = VALUES(data_json),
                    row_count  = VALUES(row_count),
                    fetched_at = NOW()
            """, (key, json.dumps(data, ensure_ascii=False), len(data)))
        return True
    except Exception as e:
        print(f'[CACHE] Gagal tulis cache {sheet_name}: {e}')
        return False


def _fetch_sheet_values(spreadsheet_key, sheet_name):
    """Baca sumber terbaru; pisahkan hasil baca dari status penyimpanan cache."""
    with sheet_write_guard(spreadsheet_key):
        ws = gs_client().open_by_key(spreadsheet_key).worksheet(sheet_name)
        values = ws.get_all_values()
        _sheet_cache[(spreadsheet_key, sheet_name)] = {'ts': time.time(), 'data': values}
        cache_saved = _write_mysql_cache(spreadsheet_key, sheet_name, values)
    return values, cache_saved


def get_sheet_values(spreadsheet_key, sheet_name, force_refresh=False):
    """
    Baca cache bersama sesuai SHEET_CACHE_TTL, lalu sumber Google Sheets.
    Cache lama maksimal 24 jam hanya untuk tampilan; force_refresh harus fresh.
    """
    key = (spreadsheet_key, sheet_name)
    now = time.time()

    # Cache MySQL dibaca lebih dulu agar invalidasi terlihat oleh semua worker.
    # Memory hanya cadangan baca saat layanan tidak tersedia.
    if not force_refresh:
        mysql_data = _read_mysql_cache(spreadsheet_key, sheet_name, max_age_seconds=SHEET_CACHE_TTL)
        if mysql_data is not None:
            # Simpan juga ke memory cache
            _sheet_cache[key] = {'ts': now, 'data': mysql_data}
            return mysql_data

    # Level 3: Fetch dari Google Sheets
    try:
        values, _ = _fetch_sheet_values(spreadsheet_key, sheet_name)
        return values
    except Exception as e:
        if force_refresh:
            raise
        # Kalau fetch gagal, coba pakai cache lama meski expired
        stale = _sheet_cache.get(key)
        if stale and now - stale['ts'] <= 86400:
            if has_request_context():
                g.stale_sheets = getattr(g, 'stale_sheets', set()) | {sheet_name}
            print(f'[CACHE] Fetch gagal ({e}), pakai stale cache untuk {sheet_name}')
            return stale['data']
        stale_mysql = _read_mysql_cache(spreadsheet_key, sheet_name, max_age_seconds=86400)
        if stale_mysql is not None:
            if has_request_context():
                g.stale_sheets = getattr(g, 'stale_sheets', set()) | {sheet_name}
            print(f'[CACHE] Fetch gagal ({e}), pakai stale MySQL cache untuk {sheet_name}')
            return stale_mysql
        raise


def invalidate_sheet_cache(spreadsheet_key=None, sheet_name=None):
    global _sheet_cache
    if spreadsheet_key is None:
        _sheet_cache.clear()
        # Hapus semua MySQL cache juga
        try:
            with db_cursor() as (conn, cur):
                cur.execute("DELETE FROM sheet_cache")
        except Exception:
            pass
        return
    key = (spreadsheet_key, sheet_name)
    _sheet_cache.pop(key, None)
    # Hapus dari MySQL cache
    try:
        cache_key = _cache_key(spreadsheet_key, sheet_name)
        with db_cursor() as (conn, cur):
            cur.execute("DELETE FROM sheet_cache WHERE cache_key = %s", (cache_key,))
    except Exception:
        pass


def get_worksheet(spreadsheet_key, sheet_name):
    return gs_client().open_by_key(spreadsheet_key).worksheet(sheet_name)


# [PENDUKUNG] Penggantian Data Upload - menulis area impor dan membersihkan sisa lama
def replace_sheet_values(ws, rows, start_row, width, user_entered=False, start_col=1,
                         preserve_columns=()):
    """Ganti rentang dalam satu request, termasuk mengosongkan sisa data lama."""
    if width < 1 or start_col < 1:
        raise ValueError('Header sheet tujuan kosong.')
    old = ws.get_all_values()
    end_row = max(len(old), start_row + len(rows) - 1)
    if end_row < start_row:
        return
    if end_row > ws.row_count:
        ws.add_rows(end_row - ws.row_count)
    end_col = start_col + width - 1
    if end_col > ws.col_count:
        ws.add_cols(end_col - ws.col_count)
    padded = [(list(r) + [''] * width)[:width] for r in rows]
    padded.extend([[''] * width for _ in range(end_row - start_row + 1 - len(padded))])
    # Sheets API melewati null; kolom ini tetap utuh, termasuk pada sisa baris lama.
    for row in padded:
        for index in preserve_columns:
            row[index] = None
    ws.update(values=padded,
              range_name=f'{gspread.utils.rowcol_to_a1(start_row, start_col)}:{gspread.utils.rowcol_to_a1(end_row, end_col)}',
              value_input_option='USER_ENTERED' if user_entered else 'RAW')


# =====================================================================
# [PENDUKUNG] Cache - scheduler pembacaan berkala, bukan Sinkronisasi BIMA
# =====================================================================

PREFETCH_INTERVAL_SECONDS = 300
PREFETCH_STATUS_KEY = 'filterin:prefetch:status'
PREFETCH_LOCK_NAME = 'filterin:prefetch'
_cache_scheduler = None


def _save_prefetch_status(conn, cur, state):
    # Metadata proses memakai tabel cache yang sudah ada, bukan data operasional.
    cur.execute('''INSERT INTO sheet_cache (cache_key, data_json, row_count)
                   VALUES (%s, %s, 0) ON DUPLICATE KEY UPDATE
                   data_json=VALUES(data_json), fetched_at=NOW()''',
                (PREFETCH_STATUS_KEY, json.dumps(state)))
    conn.commit()


def _read_prefetch_status():
    with db_cursor() as (conn, cur):
        cur.execute('SELECT data_json FROM sheet_cache WHERE cache_key=%s', (PREFETCH_STATUS_KEY,))
        row = cur.fetchone()
        state = json.loads(row['data_json']) if row and row.get('data_json') else None
        if state and state.get('state') == 'running':
            cur.execute('SELECT IS_USED_LOCK(%s) AS owner', (PREFETCH_LOCK_NAME,))
            if not (cur.fetchone() or {}).get('owner'):
                # Baca ulang untuk membedakan proses selesai dari proses terhenti.
                conn.commit()
                cur.execute('SELECT data_json FROM sheet_cache WHERE cache_key=%s', (PREFETCH_STATUS_KEY,))
                row = cur.fetchone()
                state = json.loads(row['data_json']) if row and row.get('data_json') else None
                if state and state.get('state') == 'running':
                    state['state'] = 'interrupted'
        return state


def _prefetch_job(trigger='automatic'):
    """Satu proses lintas worker; statusnya dapat dipantau dari dashboard."""
    try:
        with db_cursor() as (conn, cur):
            cur.execute('SELECT GET_LOCK(%s, 0) AS acquired', (PREFETCH_LOCK_NAME,))
            if (cur.fetchone() or {}).get('acquired') != 1:
                print('[PREFETCH] Dilewati: pembaruan lain masih berjalan')
                return
            try:
                state = {'run_id': uuid.uuid4().hex, 'state': 'running', 'trigger': trigger,
                         'started_at': datetime.now().isoformat(timespec='seconds'),
                         'finished_at': None, 'total': len(PREFETCH_SHEETS), 'items': []}
                _save_prefetch_status(conn, cur, state)
                _run_prefetch(state, lambda: _save_prefetch_status(conn, cur, state))
            finally:
                cur.execute('SELECT RELEASE_LOCK(%s)', (PREFETCH_LOCK_NAME,))
    except Exception:
        flask_app.logger.exception('Proses pembaruan cache terhenti')


def _run_prefetch(state, save_status):
    """
    Background job — fetch sheet yang paling sering diakses
    dan simpan ke MySQL cache. Jalan tiap 5 menit.
    """
    print(f'[PREFETCH] Mulai pre-fetch {len(PREFETCH_SHEETS)} sheets...')
    fetched = cached = 0
    for sp_key, sh_key in PREFETCH_SHEETS:
        sh_name = SHEET_NAMES.get(sp_key, {}).get(sh_key, sh_key)
        try:
            sp_id   = SPREADSHEET_IDS.get(sp_key)
            if not sp_id or not SHEET_NAMES.get(sp_key, {}).get(sh_key):
                print(f'[PREFETCH] Dilewati {sh_name}: konfigurasi sheet belum lengkap')
                outcome = 'unconfigured'
            else:
                values, cache_saved = _fetch_sheet_values(sp_id, sh_name)
                fetched += 1
                if cache_saved:
                    cached += 1
                    outcome = 'saved'
                    print(f'[PREFETCH] OK {sh_name} - {len(values)} baris; cache MySQL tersimpan')
                else:
                    outcome = 'cache_failed'
                    print(f'[PREFETCH] PERINGATAN {sh_name} - {len(values)} baris terbaca; cache MySQL gagal disimpan')
        except Exception as e:
            outcome = 'fetch_failed'
            print(f'[PREFETCH] Gagal mengambil {sh_name}: {e}')
        state['items'].append({'sheet_name': sh_name, 'status': outcome})
        save_status()
    total = len(PREFETCH_SHEETS)
    state.update(state='complete' if cached == total else 'partial', fetched=fetched,
                 cached=cached, total=total, finished_at=datetime.now().isoformat(timespec='seconds'))
    save_status()
    print(f'[PREFETCH] Selesai - sumber terbaca {fetched}/{total}; cache MySQL tersimpan {cached}/{total}')


def _start_scheduler():
    """Mulai background scheduler saat Flask start."""
    global _cache_scheduler
    try:
        _ensure_cache_table()

        # Fetch pertama kali langsung saat start (non-blocking di thread terpisah)
        import threading
        t = threading.Thread(target=_prefetch_job, daemon=True)
        t.start()

        # Jadwalkan ulang setiap 5 menit
        scheduler = BackgroundScheduler(timezone='Asia/Jakarta')
        scheduler.add_job(
            func    = _prefetch_job,
            trigger = IntervalTrigger(seconds=PREFETCH_INTERVAL_SECONDS),
            id      = 'prefetch_sheets',
            name    = 'Pre-fetch Google Sheets ke MySQL cache',
            replace_existing = True,
        )
        scheduler.start()
        _cache_scheduler = scheduler
        atexit.register(lambda: scheduler.shutdown(wait=False))
        print('[SCHEDULER] Background pre-fetch dimulai (interval: 5 menit)')
    except Exception as e:
        print(f'[SCHEDULER] Gagal start: {e}')


# =====================================================================
# [PENDUKUNG] Pengolahan Data - format nilai, tanggal, status, dan metadata sinkronisasi
def prepare_dataframe_for_sheets(df):
    for col in df.select_dtypes(include=['datetime64[ns]']).columns:
        df[col] = df[col].dt.strftime('%Y-%m-%d')
    return df.fillna("")

STO_DATEL_MAP = {
    'GOM': 'KEBUMEN', 'KAK': 'KEBUMEN', 'KBM': 'KEBUMEN', 'KTW': 'KEBUMEN',
    'MGE': 'MAGELANG', 'MTY': 'MAGELANG',
    'SWT': 'MUNTILAN', 'MUN': 'MUNTILAN',
    'PWJ': 'PWREJO', 'KTA': 'PWREJO',
    'TEM': 'TMNGGUNG', 'PRN': 'TMNGGUNG',
    'WOS': 'WONOSOBO',
}

def map_sto_to_datel(sto):
    return STO_DATEL_MAP.get(str(sto).strip().upper(), '')

def handle_status_resume(status):
    s = str(status).strip()
    if s in ('OSS - FALLOUT', '7 | OSS - FALLOUT'): return 'FALLOUT'
    if s == 'MIA - INVALID SURVEY': return 'INVALID SURVEY'
    return s

def format_date_for_sheets(d):
    try:
        dt = pd.to_datetime(d, errors='coerce')
        if not pd.isna(dt):
            return dt.strftime('%d/%m/%Y')
    except Exception:
        pass
    return str(d)

def clean_headers(headers):
    seen = {}
    out = []
    for i, h in enumerate(headers):
        h = str(h).strip()
        if h == '':
            out.append(f'UNUSED_COLUMN_{i}')
        elif h in seen:
            seen[h] += 1
            out.append(f'{h}_{seen[h]}')
        else:
            seen[h] = 0
            out.append(h)
    return out

def save_last_sync_time():
    with open(SYNC_LOG_FILE, 'w') as f:
        f.write(datetime.now().strftime("%d/%m/%Y %H:%M"))

def get_last_sync_time():
    if os.path.exists(SYNC_LOG_FILE):
        with open(SYNC_LOG_FILE) as f:
            return f.read().strip()
    return "Belum ada data"

# =====================================================================
# [FITUR] Hak Akses - pemeriksaan login dan role pada halaman maupun API
# =====================================================================
def login_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        if 'user' not in session:
            if request.path.startswith('/api/') and request.headers.get('Accept', '').startswith('application/json'):
                return jsonify({'error': 'Unauthorized'}), 401
            return redirect(url_for('login'))
        return f(*a, **kw)
    return wrap

def api_login_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        if 'user' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*a, **kw)
    return wrap

def role_required(*roles):
    def deco(f):
        @wraps(f)
        def wrap(*a, **kw):
            if 'user' not in session:
                return redirect(url_for('login'))
            if session['user'].get('role') not in roles:
                flash("Akses ditolak. Anda tidak memiliki izin untuk halaman ini.", "error")
                return redirect(url_for('dashboard'))
            return f(*a, **kw)
        return wrap
    return deco

def api_role_required(*roles):
    """Variant JSON untuk endpoint AJAX/API. Return 403 JSON, bukan redirect."""
    def deco(f):
        @wraps(f)
        def wrap(*a, **kw):
            if 'user' not in session:
                return jsonify(success=False, error='unauthenticated',
                               message='Sesi Anda telah berakhir. Silakan login ulang.'), 401
            if session['user'].get('role') not in roles:
                return jsonify(success=False, error='forbidden',
                               message='Akses ditolak. Peran Anda tidak diizinkan melakukan aksi ini.'), 403
            return f(*a, **kw)
        return wrap
    return deco

# =====================================================================
# [FITUR] Audit Log - pencatatan aktivitas (halaman dan hapus log ada di bawah)
# =====================================================================
def audit(action, sheet_name=None, row_key=None, column_name=None,
          old_value=None, new_value=None):
    try:
        user = (session.get('user') or {}) if has_request_context() else {}
        with db_cursor() as (conn, cur):
            cur.execute(
                """INSERT INTO audit_log
                   (username, nama, sheet_name, row_key, column_name,
                    old_value, new_value, action, ip_address)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (user.get('username', 'SYSTEM'), user.get('nama', ''),
                 sheet_name, row_key, column_name,
                 (str(old_value) if old_value is not None else None),
                 (str(new_value) if new_value is not None else None),
                 action, request.remote_addr if has_request_context() else None)
            )
        return True
    except Exception as e:
        print(f"[AUDIT ERROR] {e}")
        if has_request_context():
            g.audit_failed = True
        return False

# =====================================================================
# [FITUR] Penguncian Edit - kepemilikan, masa berlaku, dan perpanjangan lock
# =====================================================================
def cleanup_expired_locks():
    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                "DELETE FROM edit_locks WHERE locked_at < (NOW() - INTERVAL %s MINUTE)",
                (EDIT_LOCK_TTL_MINUTES,)
            )
    except Exception:
        pass

def acquire_lock(sheet_name, row_key):
    """Try to acquire a soft lock for (sheet,row). Returns (ok, lock_info)."""
    cleanup_expired_locks()
    if not row_key or not str(row_key).strip():
        return False, None
    user = session['user']
    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                """INSERT IGNORE INTO edit_locks (sheet_name, row_key, locked_by, locked_by_nama, locked_at)
                   VALUES (%s,%s,%s,%s,NOW())""",
                (sheet_name, row_key, user['username'], user.get('nama', ''))
            )
            cur.execute(
                "SELECT locked_by, locked_by_nama, locked_at FROM edit_locks WHERE sheet_name=%s AND row_key=%s",
                (sheet_name, row_key)
            )
            row = cur.fetchone()
            if row and row['locked_by'] == user['username']:
                cur.execute(
                    "UPDATE edit_locks SET locked_at=NOW() WHERE sheet_name=%s AND row_key=%s AND locked_by=%s",
                    (sheet_name, row_key, user['username'])
                )
                return True, row
            return False, row
    except Exception as e:
        print(f"[LOCK ERROR] {e}")
        return False, None

def release_lock(sheet_name, row_key):
    user = session.get('user') or {}
    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                "DELETE FROM edit_locks WHERE sheet_name=%s AND row_key=%s AND locked_by=%s",
                (sheet_name, row_key, user.get('username', ''))
            )
    except Exception as e:
        print(f"[UNLOCK ERROR] {e}")


def renew_lock(sheet_name, row_key):
    """Extend an existing, unexpired lock only; never acquire another user's lock."""
    username = session['user']['username']
    with db_cursor() as (conn, cur):
        cur.execute(
            """UPDATE edit_locks SET locked_at=NOW()
               WHERE sheet_name=%s AND row_key=%s AND locked_by=%s
                 AND locked_at >= (NOW() - INTERVAL %s MINUTE)""",
            (sheet_name, row_key, username, EDIT_LOCK_TTL_MINUTES))
        if cur.rowcount:
            return True
        # MySQL can report zero changed rows for a renewal in the same second.
        cur.execute(
            """SELECT 1 AS owned FROM edit_locks
               WHERE sheet_name=%s AND row_key=%s AND locked_by=%s
                 AND locked_at >= (NOW() - INTERVAL %s MINUTE)""",
            (sheet_name, row_key, username, EDIT_LOCK_TTL_MINUTES))
        return bool(cur.fetchone())

def get_active_locks(sheet_name):
    """Return dict {row_key: {locked_by, locked_by_nama, locked_at}} for active locks."""
    cleanup_expired_locks()
    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                "SELECT row_key, locked_by, locked_by_nama, locked_at FROM edit_locks WHERE sheet_name=%s",
                (sheet_name,)
            )
            rows = cur.fetchall() or []
        return {r['row_key']: {
            'locked_by': r['locked_by'],
            'nama': r['locked_by_nama'],
            'locked_at': r['locked_at'].strftime('%H:%M') if r['locked_at'] else ''
        } for r in rows}
    except Exception:
        return {}

# =====================================================================
# [FITUR] Sinkronisasi BIMA - logika IMPORT BIMA (FRESH) ke DB KENDALA (MASTER)
# =====================================================================
def sync_bima_to_kendala():
    """Sync IMPORT BIMA (FRESH) -> DB KENDALA (MASTER). Track new ORDER_IDs."""
    try:
        kendala_ss = gs_client().open_by_key(SPREADSHEET_IDS['kendala'])
        bima_sheet = kendala_ss.worksheet(SHEET_NAMES['kendala']['bima_fresh'])
        kendala_sheet = kendala_ss.worksheet(SHEET_NAMES['kendala']['kendalamaster'])

        bima_data = bima_sheet.get_all_values()
        kendala_data = kendala_sheet.get_all_values()

        if len(kendala_data) < 2:
            return {'status': 'error', 'message': 'Header DB KENDALA pada baris 2 tidak tersedia.'}

        if not bima_data or len(bima_data) < 2:
            return {"status": "success", "message": "Tidak ada data di IMPORT BIMA (FRESH).",
                    "updates": 0, "appends": 0, "new_order_ids": []}

        kendala_headers = [str(h).strip() for h in kendala_data[1]]
        try:
            order_id_col_idx = kendala_headers.index('ORDER_ID')
        except ValueError:
            return {"status": "error", "message": "Kolom 'ORDER_ID' tidak ditemukan di Baris 2 DB KENDALA."}

        expected = [ {'WONUM'}, {'ORDER_ID'}, {'DEVICE_ID'}, {'STO'}, {'DATEL'},
                     {'STATUS_RESUME'}, {'SUBERRORCODE', 'SUB_ERROR_CODE'},
                     {'ENGINEERMEMO', 'ENGINEER_MEMO'}, {'ORDER_DATE'},
                     {'LAST_UPDATED_DATE', 'TGL_UPDATE_STATUS'} ]
        target = [h.upper().replace(' ', '_') for h in kendala_headers[1:11]]
        if len(target) != 10 or any(h not in choices for h, choices in zip(target, expected)):
            return {'status': 'error', 'message': 'Susunan kolom B:K Kendala Master tidak sesuai pemetaan sinkronisasi. Tidak ada data ditulis.'}

        existing_order_map = {}
        for i in range(2, len(kendala_data)):
            if len(kendala_data[i]) > order_id_col_idx:
                oid = str(kendala_data[i][order_id_col_idx]).strip()
                if oid:
                    if oid in existing_order_map:
                        return {'status': 'error', 'message': f'ORDER_ID duplikat di Kendala Master: {oid}'}
                    existing_order_map[oid] = i + 1

        bh = [str(h).strip() for h in bima_data[0]]
        try:
            bi_wonum   = bh.index('Workorder')
            bi_orderid = bh.index('HELPER ORDER ID')
            bi_devid   = bh.index('SC Order No/Track ID/CSRM No')
            bi_sto     = bh.index('Workzone')
            bi_status  = bh.index('Status')
            bi_suberr  = bh.index('SUBERRORCODE')
            bi_memo    = bh.index('ENGINEERMEMO')
            bi_odate   = bh.index('TGL_CREATE')
            bi_udate   = bh.index('TGL_UPDATE_STATUS')
        except ValueError as e:
            return {"status": "error", "message": f"Header BIMA hilang: {e}"}

        updates, appends, new_ids = [], [], []
        source_ids = set()
        for row in bima_data[1:]:
            row = row + [''] * (len(bh) - len(row))
            oid = str(row[bi_orderid]).strip()
            if not oid:
                continue
            if oid in source_ids:
                return {'status': 'error', 'message': f'ORDER_ID duplikat di BIMA: {oid}. Periksa sumber sebelum sinkronisasi.'}
            source_ids.add(oid)
            new_vals = [
                row[bi_wonum], oid, row[bi_devid], row[bi_sto],
                map_sto_to_datel(row[bi_sto]), handle_status_resume(row[bi_status]),
                str(row[bi_suberr]).upper(), row[bi_memo],
                format_date_for_sheets(row[bi_odate]), format_date_for_sheets(row[bi_udate]),
            ]
            if oid in existing_order_map:
                row_num = existing_order_map[oid]
                updates.append({'range': f"B{row_num}:K{row_num}", 'values': [new_vals]})
            else:
                appends.append([''] + new_vals)
                new_ids.append(oid)

        if appends:
            required_rows = len(kendala_data) + len(appends)
            if required_rows > kendala_sheet.row_count:
                kendala_sheet.add_rows(required_rows - kendala_sheet.row_count)
            append_ups = []
            next_row = len(kendala_data) + 1
            for i, r in enumerate(appends):
                current = next_row + i
                append_ups.append({'range': f"A{current}:K{current}", 'values': [r]})
            updates.extend(append_ups)

        if updates:
            try:
                kendala_sheet.batch_update(updates, value_input_option='USER_ENTERED')
            finally:
                invalidate_sheet_cache(SPREADSHEET_IDS['kendala'], SHEET_NAMES['kendala']['kendalamaster'])

        save_last_sync_time()
        invalidate_sheet_cache(SPREADSHEET_IDS['kendala'], SHEET_NAMES['kendala']['kendalamaster'])

        # Track new order_ids for user notification
        batch_id = None
        if new_ids:
            batch_id = uuid.uuid4().hex
            try:
                with db_cursor() as (conn, cur):
                    cur.executemany(
                        "INSERT IGNORE INTO sync_new_rows (order_id, sync_batch_id) VALUES (%s,%s)",
                        [(oid, batch_id) for oid in new_ids]
                    )
            except Exception as e:
                print(f"[SYNC TRACK ERROR] {e}")

        audit('sync_bima', sheet_name=SHEET_NAMES['kendala']['kendalamaster'],
              new_value=f"updates={len(updates) - len(appends)}, appends={len(appends)}, new_ids={len(new_ids)}")

        return {
            "status": "success",
            "message": f"Sukses! Update: {len(updates) - len(appends)}, Tambah: {len(appends)}",
            "updates": len(updates) - len(appends),
            "appends": len(appends),
            "new_order_ids": new_ids[:200],   # cap to keep payload small
            "batch_id": batch_id,
        }
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


# [FITUR] UNSC - logika pemindahan dari Kendala Master
def move_kendala_to_unsc():
    """Pindahkan baris VERIFIKASI UNSC + BELUM ADA dari DB KENDALA ke UNSC."""
    try:
        kendala_ss = gs_client().open_by_key(SPREADSHEET_IDS['kendala'])
        kendala_sheet = kendala_ss.worksheet(SHEET_NAMES['kendala']['kendalamaster'])
        unsc_sheet = kendala_ss.worksheet(SHEET_NAMES['kendala']['unsc'])

        kendala_values = kendala_sheet.get_all_values()
        if len(kendala_values) < 3:
            return {"status": "success", "message": "DB KENDALA kosong."}

        kendala_headers = clean_headers(kendala_values[1])
        df = _sheet_frame(kendala_values)

        feedback_col = 'FEEDBACK ASO'
        cek_db_col = 'CEK DB UNSC'
        if feedback_col not in df.columns or cek_db_col not in df.columns:
            return {"status": "error", "message": "Kolom filter tidak ditemukan."}

        fb = df[feedback_col].str.strip().str.upper()
        # Fix typo backward-compat: accept both VERIFIKASI & VERIVIKASI
        mask_fb = fb.isin(['VERIFIKASI UNSC', 'VERIVIKASI UNSC'])
        mask_cek = df[cek_db_col].str.strip().str.upper() == 'BELUM ADA'
        df_move = df[mask_fb & mask_cek].copy()

        if df_move.empty:
            return {"status": "success", "message": "Tidak ada data untuk dipindah."}

        # CEK DB UNSC dapat terlambat dihitung Google Sheets: cek tujuan langsung.
        unsc_values = unsc_sheet.get_all_values()
        if len(unsc_values) < 2 or 'ORDER_ID' not in clean_headers(unsc_values[1]):
            return {'status': 'error', 'message': 'Header ORDER_ID UNSC tidak tersedia.'}
        dest_idx = clean_headers(unsc_values[1]).index('ORDER_ID')
        if dest_idx != 1 or len(kendala_headers) < 10 or kendala_headers[2] != 'ORDER_ID':
            return {'status': 'error', 'message': 'Susunan kolom transfer UNSC berubah. Periksa pemetaan sumber/tujuan.'}
        existing_ids = {str(r[dest_idx]).strip() for r in unsc_values[2:] if len(r) > dest_idx}
        df_move = df_move[df_move['ORDER_ID'].astype(str).str.strip().ne('') &
                          ~df_move['ORDER_ID'].astype(str).str.strip().isin(existing_ids)]
        df_move = df_move.drop_duplicates(subset=['ORDER_ID'])
        if df_move.empty:
            return {'status': 'success', 'message': 'Seluruh order sudah ada di UNSC.'}

        cols_idx = list(range(2, 10))
        cols_names = [kendala_headers[i] for i in cols_idx]
        data_move = df_move[cols_names].copy()
        data_move.insert(0, 'EMPTY_A', '')
        values = data_move.values.tolist()

        start_row = max(len(unsc_values) + 1, 3)
        num_rows = len(values)
        cur_max = unsc_sheet.row_count
        if start_row + num_rows > cur_max:
            unsc_sheet.add_rows((start_row + num_rows) - cur_max)

        try:
            unsc_sheet.update(
                values=values,
                range_name=f"A{start_row}:I{start_row + num_rows - 1}",
                value_input_option='RAW',
            )
        finally:
            invalidate_sheet_cache(SPREADSHEET_IDS['kendala'], SHEET_NAMES['kendala']['unsc'])
            invalidate_sheet_cache(SPREADSHEET_IDS['kendala'], SHEET_NAMES['kendala']['kendalamaster'])
        audit('move_to_unsc', sheet_name=SHEET_NAMES['kendala']['unsc'],
              new_value=f"{len(df_move)} baris dipindah")

        return {"status": "success", "message": f"Sukses! {len(df_move)} data dipindahkan."}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


# [PENDUKUNG] Pengolahan Tabel - identitas baris, filter, dan perhitungan tampilan
def _sheet_frame(values):
    """Header baris 2, identitas baris asli tetap utuh setelah filter."""
    if len(values) < 2:
        return pd.DataFrame()
    headers = [str(h).strip().upper() for h in values[1]]
    rows = [(r + [''] * len(headers))[:len(headers)] for r in values[2:]]
    df = pd.DataFrame(rows, columns=headers).fillna('')
    df['__SHEET_ROW__'] = range(3, 3 + len(df))
    keys = [c for c in ('ORDER_ID', 'WONUM') if c in df.columns]
    cols = keys or headers
    return df[df[cols].astype(str).apply(lambda s: s.str.strip()).ne('').any(axis=1)].copy()


DATE_HELPERS = ['ORDER_DATE_DT', 'LAST_UPDATED_DATE_DT', 'TGL_UPDATE_STATUS_DT']
AGE_LABELS = ['A. <1 HARI', 'B. 1 - 3 HARI', 'C. >3 HARI',
              'D. >1 MINGGU', 'E. >2 MINGGU', 'F. >3 MINGGU', 'G. >1 BULAN']


def _filter_kendala(df, args):
    for arg, col in [('sto', 'STO'), ('feedback', 'FEEDBACK ASO'),
                     ('is_active', 'IS_ACTIVE_KENDALA'), ('umur', 'UMUR KENDALA'),
                     ('status', 'STATUS' if 'STATUS' in df.columns else 'STATUS_RESUME')]:
        value = args.get(arg, '').strip()
        if value and col in df.columns:
            df = df[df[col].astype(str).str.strip().str.upper() == value.upper()]
    if args.get('new_only') == '1':
        df = df[df['__IS_NEW__']]
    query = args.get('search', '').strip().lower()
    if query:
        mask = pd.Series(False, index=df.index)
        for col in ('WONUM', 'ORDER_ID', 'DEVICE_ID'):
            if col in df.columns:
                mask |= df[col].astype(str).str.lower().str.contains(query, regex=False, na=False)
        df = df[mask]
    if 'ORDER_DATE_DT' in df.columns:
        for arg, upper in [('date_from', False), ('date_to', True)]:
            date = pd.to_datetime(args.get(arg, ''), format='%Y-%m-%d', errors='coerce')
            if pd.notna(date):
                df = df[df['ORDER_DATE_DT'] < date + pd.Timedelta(days=1)] if upper else df[df['ORDER_DATE_DT'] >= date]
    return df


def hitung_rumus_otomatis(df, keep_dates=False):
    """Add LAMA WO, UMUR KENDALA, IS_ACTIVE_KENDALA columns (vectorized)."""
    df.columns = df.columns.str.strip().str.upper()

    for col in ['ORDER_DATE', 'LAST_UPDATED_DATE', 'TGL_UPDATE_STATUS']:
        if col in df.columns:
            df[col + '_DT'] = pd.to_datetime(df[col], format='mixed', dayfirst=True, errors='coerce')

    now = pd.Timestamp(datetime.now())

    # Vectorized IS_ACTIVE (hybrid keyword + manual override)
    blank = pd.Series('', index=df.index, dtype='str')
    missing_date = pd.Series(pd.NaT, index=df.index, dtype='datetime64[ns]')
    manual_val = df.get('IS_ACTIVE_KENDALA', blank).astype(str).str.strip().str.upper()
    keywords = ['PS COMPLETED', 'DONE', 'CANCEL', 'REVOKE', 'COMPLETED PS', 'MATI LISTRIK']
    combined = (
        df.get('STATUS_RESUME', blank).astype(str) + ' ' +
        df.get('FEEDBACK ASO', blank).astype(str) + ' ' +
        df.get('ACTUAL KENDALA', blank).astype(str)
    ).str.upper()

    keyword_inactive = combined.apply(lambda t: any(k in t for k in keywords))
    is_active = pd.Series(['ACTIVE'] * len(df), index=df.index)
    is_active[keyword_inactive] = 'INACTIVE'
    manual_mask = manual_val.isin(['ACTIVE', 'INACTIVE'])
    is_active[manual_mask] = manual_val[manual_mask]

    # LAMA WO
    start = df.get('ORDER_DATE_DT', missing_date)
    end_inactive = df.get('LAST_UPDATED_DATE_DT', missing_date)
    fallback_end = df.get('TGL_UPDATE_STATUS_DT', missing_date)
    end_inactive = end_inactive.fillna(fallback_end).fillna(now)
    end_series = pd.Series(now, index=df.index, dtype='datetime64[ns]')
    mask_inactive = (is_active == 'INACTIVE')
    end_series[mask_inactive] = end_inactive[mask_inactive]
    delta = (end_series - start).dt.days.fillna(0).astype(int)
    delta = delta.clip(lower=0)
    df['LAMA WO'] = delta

    # UMUR KENDALA (logic A-G, non-overlapping bins)
    def bin_age(d):
        if d > 31:  return "G. >1 BULAN"
        if d >= 22: return "F. >3 MINGGU"
        if d >= 14: return "E. >2 MINGGU"
        if d >= 7:  return "D. >1 MINGGU"
        if d >= 4:  return "C. >3 HARI"
        if d >= 1:  return "B. 1 - 3 HARI"
        return "A. <1 HARI"
    df['UMUR KENDALA'] = delta.apply(bin_age)

    # >180 days default INACTIVE, tapi manual override selalu menang
    is_active[delta > 180] = 'INACTIVE'
    is_active[manual_val.isin(['ACTIVE', 'INACTIVE'])] = manual_val[manual_val.isin(['ACTIVE', 'INACTIVE'])]
    df['IS_ACTIVE_KENDALA'] = is_active

    # cleanup helper cols
    for c in ([] if keep_dates else DATE_HELPERS):
        if c in df.columns:
            df.drop(columns=c, inplace=True)

    return df


# =====================================================================
# [FITUR] Sesi Pengguna - variabel tampilan dan validasi ulang akun setiap request
# =====================================================================
@flask_app.context_processor
def inject_globals():
    user = session.get('user')
    admin_tg_username = os.environ.get('ADMIN_TELEGRAM_USERNAME', '').strip()
    return dict(
        user_nama=user.get('nama') if user else None,
        user_role=user.get('role') if user else None,
        csrf_token=generate_csrf,
        admin_telegram_username=admin_tg_username,
    )

@flask_app.before_request
def _log_session_ping():
    # Hak akses harus mengikuti MySQL, termasuk akun yang dihapus saat masih login.
    if 'user' in session:
        try:
            with db_cursor() as (conn, cur):
                cur.execute('SELECT id, nama, username, role, password FROM users WHERE id=%s',
                            (session['user']['id'],))
                user = cur.fetchone()
            stamp = hashlib.sha256(user['password'].encode()).hexdigest() if user else None
            if not user or session.get('auth_stamp') != stamp:
                session.clear()
            else:
                user = dict(user)
                user.pop('password', None)
                session['user'] = user
        except Exception:
            return jsonify(error='Layanan pengguna tidak tersedia. Coba kembali.'), 503
        session.permanent = True

# =====================================================================
# [PENDUKUNG] Respons Layanan - pemberitahuan cache lama dan kegagalan Audit Log
# =====================================================================
@flask_app.after_request
def _report_service_warnings(response):
    stale = sorted(getattr(g, 'stale_sheets', set()))
    audit_failed = getattr(g, 'audit_failed', False)
    if stale:
        response.headers['X-FilterIN-Stale'] = '1'
    if response.is_json and (stale or audit_failed):
        payload = response.get_json()
        if isinstance(payload, dict):
            payload['stale_sheets'] = stale
            payload['audit_warning'] = audit_failed
            response.set_data(flask_app.json.dumps(payload))
    if audit_failed and not response.is_json:
        flash('Data tersimpan, tetapi Audit Log gagal dicatat. Hubungi admin.', 'warning')
    return response


# [FITUR] Halaman Awal - pengalihan ke Login atau Dashboard
@flask_app.route('/')
def home():
    return redirect(url_for('dashboard')) if 'user' in session else redirect(url_for('login'))

# [FITUR] Login - validasi akun, pembatasan percobaan, dan pembentukan sesi
# Tampilan: templates/login.html | MySQL: users, login_attempts
@flask_app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=['POST'])
def login():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        # Check brute-force: >=5 failed attempts in last 5 minutes from same username or IP
        ip = request.remote_addr
        try:
            with db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT COUNT(*) AS c FROM login_attempts
                       WHERE success=FALSE AND timestamp > (NOW() - INTERVAL 5 MINUTE)
                         AND (username=%s OR ip_address=%s)""",
                    (username, ip)
                )
                fail_count = cur.fetchone()['c']
        except Exception:
            fail_count = 0

        if fail_count >= 5:
            flash("Terlalu banyak percobaan login gagal. Coba lagi dalam 5 menit.", "error")
            return render_template("login.html")

        user = None
        try:
            with db_cursor() as (conn, cur):
                cur.execute("SELECT * FROM users WHERE username=%s", (username,))
                user = cur.fetchone()
        except Exception as e:
            flash(f"Database error: {e}", "error")
            return render_template("login.html")

        ok = False
        if user:
            stored = user['password']
            # werkzeug hashes start with "pbkdf2:" or "scrypt:" or "argon2"
            if stored.startswith(('pbkdf2:', 'scrypt:', 'argon2')):
                ok = check_password_hash(stored, password)
            else:
                # legacy plain text — compare & auto-upgrade
                if stored == password:
                    ok = True
                    try:
                        with db_cursor() as (conn, cur):
                            upgraded = generate_password_hash(password)
                            cur.execute(
                                "UPDATE users SET password=%s WHERE id=%s",
                                (upgraded, user['id'])
                            )
                        user['password'] = upgraded
                    except Exception as e:
                        print(f"[PASSWORD UPGRADE ERROR] {e}")

        # Log attempt
        try:
            with db_cursor() as (conn, cur):
                cur.execute(
                    "INSERT INTO login_attempts (username, ip_address, success) VALUES (%s,%s,%s)",
                    (username, ip, ok)
                )
                if ok and user:
                    cur.execute("UPDATE users SET last_login=NOW() WHERE id=%s", (user['id'],))
        except Exception:
            pass

        if ok:
            session.clear()
            session.permanent = True
            session['auth_stamp'] = hashlib.sha256(user['password'].encode()).hexdigest()
            session['user'] = {
                'id': user['id'],
                'nama': user['nama'],
                'username': user['username'],
                'role': user.get('role', 'operator'),
            }
            flash("Login berhasil!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Username atau password salah.", "error")
    return render_template("login.html")

# [FITUR] Logout - membersihkan sesi, status online, dan lock pengguna
@flask_app.route('/logout')
def logout():
    if 'user' in session:
        try:
            with db_cursor() as (conn, cur):
                cur.execute('DELETE FROM user_sessions WHERE username=%s', (session['user']['username'],))
                cur.execute('DELETE FROM edit_locks WHERE locked_by=%s', (session['user']['username'],))
        except Exception:
            flask_app.logger.exception('Gagal membersihkan status logout')
    session.clear()
    return redirect(url_for('login'))

# [FITUR] Ganti Password - validasi password lama dan penyimpanan hash baru
@flask_app.route('/ganti_password', methods=['GET', 'POST'])
@login_required
def ganti_password():
    if request.method == 'POST':
        username = session['user']['username']
        old_pw = request.form.get('old_password', '')
        new_pw = request.form.get('new_password', '')

        if len(new_pw) < 6:
            flash("Password baru minimal 6 karakter.", "error")
            return redirect(url_for('ganti_password'))

        try:
            with db_cursor() as (conn, cur):
                cur.execute("SELECT password FROM users WHERE username=%s", (username,))
                row = cur.fetchone()
                ok = row and (check_password_hash(row['password'], old_pw)
                              if row['password'].startswith(('pbkdf2:', 'scrypt:', 'argon2'))
                              else row['password'] == old_pw)
                if ok:
                    new_hash = generate_password_hash(new_pw)
                    cur.execute(
                        "UPDATE users SET password=%s WHERE username=%s",
                        (new_hash, username)
                    )
                else:
                    flash("Password lama salah.", "error")
            if ok:
                session['auth_stamp'] = hashlib.sha256(new_hash.encode()).hexdigest()
                flash("Password berhasil diubah.", "success")
                audit('change_password')
        except Exception as e:
            flash(f"Error: {e}", "error")
        return redirect(url_for('ganti_password'))
    return render_template("ganti_password.html")

# =====================================================================
# [FITUR] Dashboard - perhitungan ringkasan, halaman, dan pembaruan statistik
# =====================================================================
def _compute_dashboard_stats():
    """Hitung semua statistik untuk dashboard termasuk data chart."""
    from datetime import datetime, timedelta
    import collections
 
    empty = dict(
        total=0, done=0, unsc=0, pending=0, active=0, inactive=0,
        chart_sto      = {'labels': [], 'values': []},
        chart_feedback = {'labels': [], 'values': []},
        chart_umur     = {'labels': [], 'values': []},
        chart_trend    = {'labels': [], 'values': []},
        top_suberror   = [],
    )
    try:
        values = get_sheet_values(
            SPREADSHEET_IDS['kendala'],
            SHEET_NAMES['kendala']['kendalamaster']
        )
        if len(values) < 3:
            return empty
 
        df = hitung_rumus_otomatis(_sheet_frame(values), keep_dates=True)
 
        total = len(df)
        fb    = df.get('FEEDBACK ASO', pd.Series([''] * total)).astype(str).str.strip().str.upper()
        done  = int((fb == 'DONE TATI').sum())
        unsc  = int(fb.isin(['UNSC','VERIFIKASI UNSC','VERIVIKASI UNSC']).sum())
        pending = total - done - unsc
        active  = int((df.get('IS_ACTIVE_KENDALA', pd.Series()) == 'ACTIVE').sum())
 
        # ── Filter hanya ACTIVE untuk chart ──
        df_active = df[df.get('IS_ACTIVE_KENDALA', pd.Series([''] * total)) == 'ACTIVE'] \
                    if 'IS_ACTIVE_KENDALA' in df.columns else df
 
        # ── Chart 1: Kendala per STO ──
        if 'STO' in df_active.columns:
            sto_series = df_active['STO'].str.strip().str.upper()
            sto_series = sto_series[sto_series != '']   # buang STO kosong
            sto_counts = sto_series.value_counts()
            chart_sto = {
                'labels': sto_counts.index.tolist(),
                'values': sto_counts.values.tolist(),
            }
        else:
            chart_sto = {'labels': [], 'values': []}
 
        # ── Chart 2: Feedback ASO distribution ──
        if 'FEEDBACK ASO' in df_active.columns:
            fb_counts = df_active['FEEDBACK ASO'].str.strip() \
                            .replace('', '(kosong)').fillna('(kosong)') \
                            .value_counts().head(8)
            chart_feedback = {
                'labels': fb_counts.index.tolist(),
                'values': fb_counts.values.tolist(),
            }
        else:
            chart_feedback = {'labels': [], 'values': []}
 
        # ── Chart 3: Umur Kendala bins ──
        UMUR_ORDER = AGE_LABELS
        if 'UMUR KENDALA' in df_active.columns:
            umur_counts = df_active['UMUR KENDALA'].str.strip().str.upper().value_counts()
            # urutkan sesuai UMUR_ORDER
            labels = [u for u in UMUR_ORDER if u in umur_counts.index]
            values = [int(umur_counts.get(u, 0)) for u in labels]
            chart_umur = {'labels': labels, 'values': values}
        else:
            chart_umur = {'labels': [], 'values': []}
 
        # ── Chart 4: Trend order masuk 14 hari ──
        chart_trend = {'labels': [], 'values': []}
        if 'ORDER_DATE_DT' in df.columns:
            today = pd.Timestamp(datetime.now().date())
            dates = [today - timedelta(days=i) for i in range(13, -1, -1)]
            df_dt = df.dropna(subset=['ORDER_DATE_DT'])
            counts = df_dt['ORDER_DATE_DT'].dt.normalize().value_counts()
            chart_trend = {
                'labels': [d.strftime('%d/%m') for d in dates],
                'values': [int(counts.get(d, 0)) for d in dates],
            }
 
        # ── Top 5 Sub Error Code ──
        top_suberror = []
        sec_col = next((c for c in df.columns if 'SUB ERROR' in c.upper() or 'SUBERROR' in c.upper()), None)
        if sec_col:
            sec_counts = df_active[sec_col].str.strip() \
                             .replace('', None).dropna() \
                             .value_counts().head(5)
            max_count = sec_counts.max() if len(sec_counts) else 1
            top_suberror = [
                {'code': code, 'count': int(cnt), 'pct': round(cnt / max_count * 100)}
                for code, cnt in sec_counts.items()
            ]
 
        return dict(
            total=total, done=done, unsc=unsc, pending=pending,
            active=active, inactive=total - active,
            chart_sto=chart_sto, chart_feedback=chart_feedback,
            chart_umur=chart_umur, chart_trend=chart_trend,
            top_suberror=top_suberror,
        )
 
    except Exception as e:
        print(f'[DASHBOARD STATS ERROR] {e}')
        empty['error'] = 'Data dashboard belum dapat dimuat. Angka berikut bukan hasil pembacaan terbaru.'
        return empty
 
 
@flask_app.route('/dashboard')
@login_required
def dashboard():
    stats = _compute_dashboard_stats()
    if stats.get('error'):
        flash(stats['error'], 'error')
    last_sync_str = get_last_sync_time()
    unseen = 0
    try:
        user_name = session['user']['username']
        with db_cursor() as (conn, cur):
            cur.execute(
                """SELECT COUNT(*) AS c FROM sync_new_rows
                   WHERE sync_time > (NOW() - INTERVAL 24 HOUR)
                     AND (seen_by IS NULL OR NOT JSON_CONTAINS(seen_by, JSON_QUOTE(%s)))""",
                (user_name,)
            )
            unseen = cur.fetchone()['c']
    except Exception:
        pass
 
    # Format top_suberror untuk template: list of (index, item)
    top_suberror = list(enumerate(stats.get('top_suberror', []), start=1))
 
    return render_template(
        'dashboard.html',
        total   = stats['total'],
        done    = stats['done'],
        unsc    = stats['unsc'],
        pending = stats['pending'],
        active  = stats['active'],
        inactive= stats['inactive'],
        chart_sto      = stats['chart_sto'],
        chart_feedback = stats['chart_feedback'],
        chart_umur     = stats['chart_umur'],
        chart_trend    = stats['chart_trend'],
        top_suberror   = top_suberror,
        last_sync      = last_sync_str,
        user           = session['user'],
        unseen_new_rows= unseen,
    )
 
 
@flask_app.route('/dashboard_stats')
@api_login_required
def dashboard_stats():
    """Endpoint real-time polling untuk angka kartu statistik."""
    stats = _compute_dashboard_stats()
    unseen = 0
    try:
        user_name = session['user']['username']
        with db_cursor() as (conn, cur):
            cur.execute(
                """SELECT COUNT(*) AS c FROM sync_new_rows
                   WHERE sync_time > (NOW() - INTERVAL 24 HOUR)
                     AND (seen_by IS NULL OR NOT JSON_CONTAINS(seen_by, JSON_QUOTE(%s)))""",
                (user_name,)
            )
            unseen = cur.fetchone()['c']
    except Exception:
        pass
    return jsonify(
        total           = stats['total'],
        done            = stats['done'],
        unsc            = stats['unsc'],
        pending         = stats['pending'],
        active          = stats['active'],
        error           = stats.get('error'),
        unseen_new_rows = unseen,
    )

# =====================================================================
# [FITUR] Kendala Master - penyimpanan bersama, daftar data, dan endpoint pengeditan
# =====================================================================
KENDALA_EDITABLE = {'ACTUAL KENDALA', 'FEEDBACK ASO', 'TGL FEEDBACK',
                    'NOTES ASO', 'CURRENT_UIC', 'IS_ACTIVE_KENDALA'}


# [FITUR] Quick Edit - pemeriksaan snapshot dan penyimpanan (juga dipakai edit massal)
# Interaksi modal/highlight: static/filterin-core.js | Endpoint: api_update_kendala_row
def _row_token(sheet, row_num, headers, values):
    row = dict(zip([str(h).strip() for h in headers], values + [''] * (len(headers) - len(values))))
    editable = KENDALA_EDITABLE if sheet == SHEET_NAMES['kendala']['kendalamaster'] else {
        h for h in row if 'STATUS' in h or 'VALIDASI' in h}
    return URLSafeSerializer(flask_app.secret_key, salt='sheet-row').dumps({
        'sheet': sheet, 'row_num': row_num,
        'values': {key: val for key, val in row.items() if key == 'ORDER_ID' or key in editable}})


class EditConflict(ValueError):
    pass


def _save_sheet_changes(sheet, changes, snapshots, action):
    """Valider seluruh batch sebelum menulis; audit hanya setelah Sheets berhasil."""
    ws = get_worksheet(SPREADSHEET_IDS['kendala'], sheet)
    values = ws.get_all_values()
    if len(values) < 2:
        raise EditConflict('Header sheet tidak tersedia.')
    headers = [str(h).strip() for h in values[1]]
    header_map = {h: i + 1 for i, h in enumerate(headers)}
    allowed = KENDALA_EDITABLE if sheet == SHEET_NAMES['kendala']['kendalamaster'] else {
        h for h in headers if 'STATUS' in h or 'VALIDASI' in h}
    if 'ORDER_ID' not in header_map:
        raise EditConflict('Kolom ORDER_ID tidak ditemukan.')
    cells, records, locked, saved_rows = [], [], [], {}
    try:
        for rn, updates in changes.items():
            if rn < 3 or rn > len(values) or rn not in snapshots:
                raise EditConflict('Identitas baris tidak valid. Muat ulang halaman.')
            old = dict(zip(headers, values[rn - 1] + [''] * len(headers)))
            snapshot = snapshots[rn]
            oid = str(old.get('ORDER_ID', '')).strip()
            if not oid or oid != str(snapshot.get('ORDER_ID', '')).strip():
                raise EditConflict('Posisi ORDER_ID berubah. Muat ulang halaman sebelum menyimpan.')
            ok, lock = acquire_lock(sheet, oid)
            if not ok:
                raise EditConflict('Baris sedang dikunci atau layanan penguncian tidak tersedia.')
            locked.append(oid)
            for col, val in updates.items():
                if col not in allowed or col not in header_map:
                    raise ValueError(f'Kolom tidak dapat diedit: {col}')
                if not isinstance(val, str):
                    raise ValueError(f'Nilai {col} harus berupa teks.')
                if col not in snapshot or str(old.get(col, '')) != str(snapshot[col]):
                    raise EditConflict(f'{oid}: {col} telah berubah. Muat ulang data.')
                if col == 'IS_ACTIVE_KENDALA' and val not in ('', 'ACTIVE', 'INACTIVE'):
                    raise ValueError('Status aktif tidak valid.')
                if old.get(col, '') != val:
                    cells.append(gspread.Cell(rn, header_map[col], val))
                    records.append((oid, col, old.get(col, ''), val))
                    old[col] = val
            saved_rows[rn] = old
        if cells:
            try:
                ws.update_cells(cells, value_input_option='RAW')
            finally:
                invalidate_sheet_cache(SPREADSHEET_IDS['kendala'], sheet)
            for oid, col, before, after in records:
                audit(action, sheet_name=sheet, row_key=oid,
                      column_name=col, old_value=before, new_value=after)
        if has_request_context():
            g.saved_row_tokens = {
                rn: _row_token(sheet, rn, headers, [row.get(h, '') for h in headers])
                for rn, row in saved_rows.items()
            }
        return len(cells)
    finally:
        for oid in locked:
            release_lock(sheet, oid)


def _save_bulk_form(sheet, action):
    changes, snapshots = {}, {}
    for key, value in request.form.items():
        match = re.fullmatch(r'(.+?)\[(\d+)\]', key)
        if not match:
            continue
        col, rn = match.group(1), int(match.group(2))
        if col == '__snapshot__':
            try:
                payload = URLSafeSerializer(flask_app.secret_key, salt='sheet-row').loads(value)
            except BadSignature as exc:
                raise EditConflict('Identitas data tidak valid. Muat ulang halaman.') from exc
            if payload['sheet'] != sheet or payload['row_num'] != rn:
                raise EditConflict('Identitas sheet/baris tidak cocok.')
            snapshots[rn] = payload['values']
        elif col not in ('LAMA WO', 'UMUR KENDALA'):
            changes.setdefault(rn, {})[col.strip()] = value
    return _save_sheet_changes(sheet, changes, snapshots, action)
# [FITUR] Data Baru - penanda NEW berdasarkan sinkronisasi dan pengguna yang melihat
def _get_new_order_ids(hours=24):
    """Return dict {order_id: sync_time_str} of recently synced rows."""
    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                """SELECT order_id, sync_time, sync_batch_id
                   FROM sync_new_rows
                   WHERE sync_time > (NOW() - INTERVAL %s HOUR)
                     AND (seen_by IS NULL OR NOT JSON_CONTAINS(seen_by, JSON_QUOTE(%s)))
                   ORDER BY sync_time""",
                (hours, session['user']['username'])
            )
            rows = cur.fetchall() or []
        return {r['order_id']: {
            'time': r['sync_time'].strftime('%d/%m %H:%M') if r['sync_time'] else '',
            'batch': r['sync_batch_id'],
        } for r in rows}
    except Exception:
        return {}

def _kendala_view_revision(headers, data, sheet_rows, new_flags, total):
    """Versi data tampilan; tidak bergantung pada format sel atau pilihan dropdown."""
    payload = [headers, data, sheet_rows, new_flags, total]
    return hashlib.sha256(flask_app.json.dumps(payload).encode('utf-8')).hexdigest()


# [FITUR] Kendala Master - halaman, pencarian, penyaringan, dan pagination
@flask_app.route('/kendala_master')
@login_required
def kendala_master():
    error = None; pagination = {}; data_to_render = []; header_to_render = []
    feedback_options = []; actual_options = []; is_active_options = ['ACTIVE', 'INACTIVE']

    filter_sto       = request.args.get('sto', '')
    filter_status    = request.args.get('status', '')
    filter_feedback  = request.args.get('feedback', '')
    filter_new_only  = request.args.get('new_only', '0') == '1'
    search_query     = request.args.get('search', '').strip().lower()
    filter_is_active = request.args.get('is_active', '')
    filter_umur      = request.args.get('umur', '')
    filter_date_from = request.args.get('date_from', '')
    filter_date_to   = request.args.get('date_to', '')

    try:
        current_page = max(request.args.get('p', 1, type=int), 1)
        per_page = 100

        all_data = get_sheet_values(SPREADSHEET_IDS['kendala'], SHEET_NAMES['kendala']['kendalamaster'])
        if not all_data or len(all_data) < 2:
            raise ValueError("Tidak ada data di sheet Kendala Master.")

        df = hitung_rumus_otomatis(_sheet_frame(all_data), keep_dates=True)

        # Mark new rows
        new_ids_map = _get_new_order_ids(24)
        df['__IS_NEW__'] = df.get('ORDER_ID', pd.Series([''] * len(df))).astype(str).str.strip().isin(new_ids_map.keys())

        df = _filter_kendala(df, request.args)


        total_rows = len(df)
        total_pages = max((total_rows + per_page - 1) // per_page, 1)
        if current_page > total_pages:
            current_page = total_pages
        start_index = (current_page - 1) * per_page
        end_index = start_index + per_page

        df_page = df.iloc[start_index:end_index].drop(columns=DATE_HELPERS, errors='ignore').fillna("")
        sheet_rows = df_page['__SHEET_ROW__'].tolist()
        row_tokens = [_row_token(SHEET_NAMES['kendala']['kendalamaster'], rn,
                                 all_data[1], all_data[rn - 1]) for rn in sheet_rows]
        is_new_flags = df_page['__IS_NEW__'].tolist()

        # drop helper cols before render
        display_df = df_page.drop(columns=['__SHEET_ROW__', '__IS_NEW__'], errors='ignore')
        data_to_render = display_df.values.tolist()
        header_to_render = list(display_df.columns)

        # Options (soft fail) — coba Options sheet dulu, fallback ke unique values dari data
        try:
            opt_ws = get_worksheet(SPREADSHEET_IDS['kendala'], 'Options')
            feedback_options = [x for x in opt_ws.col_values(2)[1:] if x]
            actual_options = [x for x in opt_ws.col_values(1)[1:] if x]
        except Exception:
            pass
        # Fallback: extract unique values dari seluruh data sheet
        if not feedback_options and 'FEEDBACK ASO' in df.columns:
            feedback_options = sorted({
                str(v).strip() for v in df['FEEDBACK ASO'].tolist()
                if v and str(v).strip() and str(v).strip().upper() != 'NAN'
            })
        if not actual_options and 'ACTUAL KENDALA' in df.columns:
            actual_options = sorted({
                str(v).strip() for v in df['ACTUAL KENDALA'].tolist()
                if v and str(v).strip() and str(v).strip().upper() != 'NAN'
            })
        # Fallback 2: hardcoded defaults supaya dropdown tidak pernah kosong
        if not feedback_options:
            feedback_options = [
                'ANTRI TATI', 'DONE TATI', 'VERIFIKASI UNSC', 'UNSC',
                'FOLLOW UP', 'PS', 'CANCEL', 'REVOKE',
            ]
        if not actual_options:
            actual_options = [
                'GANGGUAN PERANGKAT', 'GANGGUAN KABEL', 'GANGGUAN ODP',
                'GANGGUAN OLT', 'SALAH KONFIGURASI', 'CUSTOMER TIDAK ADA',
                'MATI LISTRIK', 'PS COMPLETED',
            ]

        # Active locks for page
        active_locks = get_active_locks(SHEET_NAMES['kendala']['kendalamaster'])

        pagination = {
            'current_page': current_page, 'total_pages': total_pages,
            'total_rows': total_rows, 'per_page': per_page, 'start_index': start_index,
            'sto': filter_sto, 'status': filter_status,
            'feedback': filter_feedback, 'search': search_query,
            'new_only': '1' if filter_new_only else '',
            'is_active':  filter_is_active,
            'umur':       filter_umur,
            'date_from':  filter_date_from,
            'date_to':    filter_date_to,
        }

        return render_template(
            "kendalamaster.html",
            user=session.get('user'),
            header=header_to_render, data=data_to_render,
            sheet_rows=sheet_rows, is_new_flags=is_new_flags,
            row_tokens=row_tokens,
            active_locks=active_locks,
            error=error, pagination=pagination,
            feedback_options=feedback_options, actual_options=actual_options,
            is_active_options=is_active_options,
            total_new_today=sum(is_new_flags),
            last_sync=get_last_sync_time(),
            data_revision=_kendala_view_revision(
                header_to_render, data_to_render, sheet_rows, is_new_flags, total_rows),
        )
    except Exception as e:
        traceback.print_exc()
        return render_template(
            "kendalamaster.html",
            user=session.get('user'),
            header=[], data=[], sheet_rows=[], is_new_flags=[],
            active_locks={}, error=f"Gagal memuat data: {e}",
            pagination={}, feedback_options=[], actual_options=[],
            is_active_options=['ACTIVE', 'INACTIVE'], total_new_today=0,
        )

# [FITUR] Kendala Master - API pembaruan tabel berkala (polling)
@flask_app.route('/kendala_data')
@api_login_required
def api_kendala_data():
    """Lightweight JSON endpoint for auto-refresh without full page reload."""
    try:
        current_page = max(request.args.get('p', 1, type=int), 1)
        per_page = 100

        all_data = get_sheet_values(SPREADSHEET_IDS['kendala'], SHEET_NAMES['kendala']['kendalamaster'])
        if not all_data or len(all_data) < 2:
            return jsonify({'data': [], 'sheet_rows': [], 'is_new_flags': [], 'total': 0,
                            'revision': _kendala_view_revision([], [], [], [], 0)})

        df = hitung_rumus_otomatis(_sheet_frame(all_data), keep_dates=True)

        new_ids_map = _get_new_order_ids(24)
        df['__IS_NEW__'] = df.get('ORDER_ID', pd.Series([''] * len(df))).astype(str).str.strip().isin(new_ids_map.keys())

        df = _filter_kendala(df, request.args)

        total = len(df)
        current_page = min(current_page, max((total + per_page - 1) // per_page, 1))
        start_index = (current_page - 1) * per_page
        df_page = df.iloc[start_index:start_index + per_page].drop(columns=DATE_HELPERS, errors='ignore').fillna("")

        active_locks = get_active_locks(SHEET_NAMES['kendala']['kendalamaster'])

        display_df = df_page.drop(columns=['__SHEET_ROW__', '__IS_NEW__'], errors='ignore')
        data = display_df.values.tolist()
        sheet_rows = df_page['__SHEET_ROW__'].tolist()
        new_flags = df_page['__IS_NEW__'].tolist()
        return jsonify({
            'data': data,
            'sheet_rows': sheet_rows,
            'is_new_flags': new_flags,
            'start_index': start_index,
            'total': total,
            'active_locks': active_locks,
            'revision': _kendala_view_revision(list(display_df.columns), data, sheet_rows, new_flags, total),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# [FITUR] Quick Edit - membaca data terbaru sebelum modal diisi
@flask_app.route('/kendala_row/<int:row_num>')
@api_login_required
def api_kendala_row(row_num):
    """Get a single row by sheet row number - for quick edit modal."""
    try:
        ws = get_worksheet(SPREADSHEET_IDS['kendala'], SHEET_NAMES['kendala']['kendalamaster'])
        if row_num < 3 or row_num > ws.row_count:
            return jsonify({'error': 'Row tidak ditemukan'}), 404
        header = [str(h).strip() for h in ws.row_values(2)]
        row = ws.row_values(row_num)
        row = row + [''] * (len(header) - len(row))
        row_dict = dict(zip(header, row[:len(header)]))
        return jsonify({'row': row_dict, 'row_num': row_num, 'sheet_name': SHEET_NAMES['kendala']['kendalamaster']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# [FITUR] Riwayat Order - membaca Audit Log berdasarkan ORDER_ID
@flask_app.route('/order_history/<path:order_id>')
@api_login_required
@api_role_required('admin', 'operator')
def order_history(order_id):
    """Ambil riwayat perubahan untuk satu Order ID dari audit_log."""
    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                """SELECT
                    a.username,
                    COALESCE(NULLIF(a.nama, ''), u.nama, a.username) AS nama,
                    a.column_name,
                    a.old_value,
                    a.new_value,
                    DATE_FORMAT(a.timestamp, '%%d/%%m/%%Y %%H:%%i') AS timestamp
                FROM audit_log a
                LEFT JOIN users u ON u.username = a.username
                WHERE a.row_key = %s
                  AND a.action IN ('update_row', 'update_bulk')
                  AND a.column_name IN (
                    'ACTUAL KENDALA', 'FEEDBACK ASO',
                    'TGL FEEDBACK', 'NOTES ASO', 'IS_ACTIVE_KENDALA'
                  )
                ORDER BY a.timestamp DESC
                LIMIT 50""",
                (order_id,)
            )
            rows = cur.fetchall()
        return jsonify({'history': rows})
    except Exception as e:
        return jsonify({'history': [], 'error': str(e)}), 500


# [FITUR] Penguncian Edit - API mengambil, memperpanjang, melepas, dan melihat lock
@flask_app.route('/lock', methods=['POST'])
@api_login_required
@api_role_required('admin', 'operator')
def api_lock():
    """Acquire soft lock on a row before editing."""
    data = request.get_json() or {}
    sheet_name = data.get('sheet_name')
    row_key = str(data.get('row_key', '')).strip()
    if sheet_name not in (SHEET_NAMES['kendala']['kendalamaster'], SHEET_NAMES['kendala']['unsc']) or not row_key.strip():
        return jsonify({'error': 'sheet_name & row_key required'}), 400
    ok, lock = acquire_lock(sheet_name, row_key)
    return jsonify({
        'ok': ok,
        'ttl_seconds': EDIT_LOCK_TTL_MINUTES * 60,
        'locked_by': lock.get('locked_by') if lock else None,
        'locked_by_nama': lock.get('locked_by_nama') if lock else None,
        'locked_at': lock.get('locked_at').strftime('%H:%M') if lock and lock.get('locked_at') else None,
    })

@flask_app.route('/renew-lock', methods=['POST'])
@api_login_required
@api_role_required('admin', 'operator')
def api_renew_lock():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, error='Payload JSON tidak valid.'), 400
    sheet_name = data.get('sheet_name')
    row_key = str(data.get('row_key') or '').strip()
    if sheet_name not in (SHEET_NAMES['kendala']['kendalamaster'], SHEET_NAMES['kendala']['unsc']) or not row_key:
        return jsonify(ok=False, error='sheet_name & row_key required'), 400
    try:
        if not renew_lock(sheet_name, row_key):
            return jsonify(ok=False, error='Hak edit sudah berakhir atau baris sedang digunakan pengguna lain.'), 409
        return jsonify(ok=True, ttl_seconds=EDIT_LOCK_TTL_MINUTES * 60)
    except Exception:
        flask_app.logger.exception('Perpanjangan lock gagal')
        return jsonify(ok=False, error='Akses edit belum dapat diperiksa. Input Anda tetap dipertahankan.'), 503

@flask_app.route('/unlock', methods=['POST'])
@api_login_required
@api_role_required('admin', 'operator')
def api_unlock():
    data = request.get_json() or {}
    sheet_name = data.get('sheet_name')
    row_key = str(data.get('row_key', '')).strip()
    if sheet_name and row_key:
        release_lock(sheet_name, row_key)
    return jsonify({'ok': True})


@flask_app.route('/api/kendala_locks')
@api_login_required
def api_kendala_locks():
    """Return dict of active locks {row_key: {locked_by, nama, is_mine}}.
    Dipakai untuk polling real-time indikator lock di halaman Kendala Master.
    Response ringan (cuma query MySQL, tidak sentuh Google Sheets)."""
    cleanup_expired_locks()
    try:
        sheet = SHEET_NAMES['kendala']['kendalamaster']
        current_user = session['user']['username']
        with db_cursor() as (conn, cur):
            cur.execute(
                "SELECT row_key, locked_by, locked_by_nama FROM edit_locks WHERE sheet_name=%s",
                (sheet,)
            )
            rows = cur.fetchall()
        locks = {}
        for r in rows:
            locks[str(r['row_key'])] = {
                'nama': r['locked_by_nama'] or r['locked_by'],
                'is_mine': r['locked_by'] == current_user,
            }
        return jsonify({'locks': locks})
    except Exception as e:
        return jsonify({'locks': {}, 'error': str(e)}), 500


# [FITUR] Kendala Master - simpan perubahan melalui form edit massal
@flask_app.route('/update_kendala', methods=['POST'])
@login_required
@role_required('admin', 'operator')
@serialized_sheet_write('kendala')
def update_kendala():
    try:
        count = _save_bulk_form(SHEET_NAMES['kendala']['kendalamaster'], 'update_bulk')
        if request.accept_mimetypes.best == 'application/json':
            if not getattr(g, 'audit_failed', False):
                flash(f"Berhasil menyimpan {count} perubahan kolom.", "success")
            return jsonify(ok=True, updated=count, row_tokens=getattr(g, 'saved_row_tokens', {}),
                           audit_warning=bool(getattr(g, 'audit_failed', False)))
        flash(f"Berhasil menyimpan {count} perubahan kolom.", "success")
    except Exception as exc:
        if request.accept_mimetypes.best == 'application/json':
            return jsonify(ok=False, error=str(exc)), (409 if isinstance(exc, EditConflict) else 400 if isinstance(exc, ValueError) else 500)
        flash(f"Data belum tersimpan: {exc}", "error")
    return redirect(url_for('kendala_master'))

# [FITUR] Quick Edit - simpan perubahan satu baris
@flask_app.route('/update_kendala_row', methods=['POST'])
@api_login_required
@api_role_required('admin', 'operator')
@serialized_sheet_write('kendala')
def api_update_kendala_row():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, error='Payload JSON tidak valid.'), 400
    try:
        row_num = int(data.get('row_num', 0))
        row_key = str(data.get('row_key', '')).strip()
        updates = data.get('updates')
        original = data.get('original_values')
        if row_num < 3 or not row_key or not isinstance(updates, dict) or not updates:
            raise ValueError('row_num, row_key, dan updates wajib diisi.')
        if not isinstance(original, dict):
            raise ValueError('Data awal diperlukan. Muat ulang modal edit.')
        if str(original.get('ORDER_ID', '')).strip() != row_key:
            raise EditConflict('Identitas ORDER_ID tidak cocok.')
        count = _save_sheet_changes(
            SHEET_NAMES['kendala']['kendalamaster'], {row_num: updates},
            {row_num: original}, 'update_row')
        return jsonify(ok=True, updated=count, skipped=[],
                       row_token=getattr(g, 'saved_row_tokens', {}).get(row_num),
                       audit_warning=bool(getattr(g, 'audit_failed', False)))
    except EditConflict as exc:
        return jsonify(ok=False, error=str(exc)), 409
    except (ValueError, TypeError) as exc:
        return jsonify(ok=False, error=str(exc)), 400
    except Exception:
        flask_app.logger.exception('Quick edit gagal')
        return jsonify(ok=False, error='Penyimpanan gagal. Muat ulang untuk memeriksa data terbaru.'), 500

# [FITUR] Data Baru - tandai data baru sebagai sudah dilihat oleh pengguna saat ini
@flask_app.route('/mark_new_seen', methods=['POST'])
@api_login_required
def api_mark_new_seen():
    """Mark new rows as seen by current user."""
    try:
        user_name = session['user']['username']
        with db_cursor() as (conn, cur):
            cur.execute(
                """UPDATE sync_new_rows
                   SET seen_by = JSON_ARRAY_APPEND(
                     COALESCE(seen_by, JSON_ARRAY()), '$', %s
                   )
                   WHERE sync_time > (NOW() - INTERVAL 24 HOUR)
                     AND (seen_by IS NULL OR NOT JSON_CONTAINS(seen_by, JSON_QUOTE(%s)))""",
                (user_name, user_name)
            )
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# =====================================================================
# [FITUR] UNSC - halaman, pencarian, penyaringan, dan pagination
# =====================================================================
@flask_app.route('/unsc')
@login_required
def unsc():
    error = None; pagination = {}; data_to_render = []; header_to_render = []
    unsc_status_options = []; unsc_validasi_options = []

    filter_sto = request.args.get('sto', '')
    filter_status = request.args.get('status', '')
    filter_validasi = request.args.get('validasi', '')
    search_query = request.args.get('search', '').strip().lower()

    try:
        current_page = max(request.args.get('p', 1, type=int), 1)
        per_page = 100

        all_data = get_sheet_values(SPREADSHEET_IDS['kendala'], SHEET_NAMES['kendala']['unsc'])
        if not all_data or len(all_data) < 2:
            raise ValueError("Data UNSC kosong.")

        df = _sheet_frame(all_data)

        if filter_sto and 'STO' in df.columns:
            df = df[df['STO'] == filter_sto]
        col_status = next((c for c in df.columns if 'STATUS' in c), None)
        if filter_status and col_status:
            df = df[df[col_status] == filter_status]
        col_validasi = next((c for c in df.columns if 'VALIDASI' in c), None)
        if filter_validasi and col_validasi:
            df = df[df[col_validasi] == filter_validasi]
        if search_query:
            mask = pd.Series(False, index=df.index)
            for col in ['ORDER_ID', 'DEVICE_ID', 'NAMA SALESFORCE', 'STO']:
                if col in df.columns:
                    mask |= df[col].astype(str).str.lower().str.contains(search_query, na=False, regex=False)
            df = df[mask]

        total_rows = len(df)
        total_pages = max((total_rows + per_page - 1) // per_page, 1)
        if current_page > total_pages:
            current_page = total_pages
        start_index = (current_page - 1) * per_page
        df_page = df.iloc[start_index:start_index + per_page].fillna("")

        sheet_rows = df_page['__SHEET_ROW__'].tolist()
        row_tokens = [_row_token(SHEET_NAMES['kendala']['unsc'], rn,
                                 all_data[1], all_data[rn - 1]) for rn in sheet_rows]
        display_df = df_page.drop(columns=['__SHEET_ROW__'], errors='ignore')
        data_to_render = display_df.values.tolist()
        header_to_render = list(display_df.columns)

        try:
            opt_ws = get_worksheet(SPREADSHEET_IDS['kendala'], 'Options')
            unsc_status_options = [x for x in opt_ws.col_values(3)[1:] if x]
            unsc_validasi_options = [x for x in opt_ws.col_values(4)[1:] if x]
        except Exception:
            pass

        pagination = {
            'current_page': current_page, 'per_page': per_page,
            'total_rows': total_rows, 'total_pages': total_pages, 'start_index': start_index,
            'sto': filter_sto, 'status': filter_status, 'validasi': filter_validasi, 'search': search_query,
        }
    except Exception as e:
        error = str(e)
        traceback.print_exc()

    return render_template(
        'unsc.html',
        data=data_to_render, header=header_to_render,
        sheet_rows=locals().get('sheet_rows', []),
        row_tokens=locals().get('row_tokens', []),
        pagination=pagination,
        unsc_status_options=unsc_status_options, unsc_validasi_options=unsc_validasi_options,
        error=error,
    )

# =====================================================================
# [FITUR] UNSC - API pembaruan tabel berkala (polling)
# =====================================================================
@flask_app.route('/unsc_data')
@api_login_required
def api_unsc_data():
    filter_sto      = request.args.get('sto', '')
    filter_status   = request.args.get('status', '')
    filter_validasi = request.args.get('validasi', '')
    search_query    = request.args.get('search', '').strip().lower()
    current_page    = max(request.args.get('p', 1, type=int), 1)
    per_page        = 100

    try:
        all_data = get_sheet_values(
            SPREADSHEET_IDS['kendala'],
            SHEET_NAMES['kendala']['unsc']
        )
        if not all_data or len(all_data) < 2:
            return jsonify({'data': []})

        df = _sheet_frame(all_data)

        if filter_sto and 'STO' in df.columns:
            df = df[df['STO'] == filter_sto]

        col_status = next((c for c in df.columns if 'STATUS' in c), None)
        if filter_status and col_status:
            df = df[df[col_status] == filter_status]

        col_validasi = next((c for c in df.columns if 'VALIDASI' in c), None)
        if filter_validasi and col_validasi:
            df = df[df[col_validasi] == filter_validasi]

        if search_query:
            mask = pd.Series(False, index=df.index)
            for col in ['ORDER_ID', 'DEVICE_ID', 'NAMA SALESFORCE', 'STO']:
                if col in df.columns:
                    mask |= df[col].astype(str).str.lower().str.contains(
                        search_query, na=False, regex=False
                    )
            df = df[mask]

        current_page = min(current_page, max((len(df) + per_page - 1) // per_page, 1))
        start_index = (current_page - 1) * per_page
        df_page     = df.iloc[start_index:start_index + per_page].fillna('')

        return jsonify({
            'data':        df_page.drop(columns=['__SHEET_ROW__']).values.tolist(),
            'sheet_rows':  df_page['__SHEET_ROW__'].tolist(),
            'start_index': start_index,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500



# [FITUR] UNSC - simpan perubahan melalui form edit massal
@flask_app.route('/update_unsc', methods=['POST'])
@login_required
@role_required('admin', 'operator')
@serialized_sheet_write('kendala')
def update_unsc():
    try:
        count = _save_bulk_form(SHEET_NAMES['kendala']['unsc'], 'update_unsc')
        if request.accept_mimetypes.best == 'application/json':
            if not getattr(g, 'audit_failed', False):
                flash(f"Berhasil menyimpan {count} perubahan kolom UNSC.", "success")
            return jsonify(ok=True, updated=count, row_tokens=getattr(g, 'saved_row_tokens', {}),
                           audit_warning=bool(getattr(g, 'audit_failed', False)))
        flash(f"Berhasil menyimpan {count} perubahan kolom UNSC.", "success")
    except Exception as exc:
        if request.accept_mimetypes.best == 'application/json':
            return jsonify(ok=False, error=str(exc)), (409 if isinstance(exc, EditConflict) else 400 if isinstance(exc, ValueError) else 500)
        flash(f"Data belum tersimpan: {exc}", "error")
    return redirect(url_for('unsc'))

# =====================================================================
# [FITUR] Sinkronisasi BIMA - endpoint tombol sinkronisasi
# =====================================================================
@flask_app.route('/sync-bima', methods=['POST'])
@api_login_required
@api_role_required('admin', 'operator')
@serialized_sheet_write('kendala')
def api_sync_bima():
    result = sync_bima_to_kendala()
    return jsonify(result), (200 if result['status'] == 'success' else 500)

# [FITUR] UNSC - endpoint tombol pemindahan dari Kendala Master
@flask_app.route('/move-to-unsc', methods=['POST'])
@api_login_required
@api_role_required('admin', 'operator')
@serialized_sheet_write('kendala')
def api_move_to_unsc():
    result = move_kendala_to_unsc()
    return jsonify(result), (200 if result['status'] == 'success' else 500)

# =====================================================================
# [FITUR] Upload BIMA / Upload KPRO - validasi file dan pemetaan kolom bersama
# =====================================================================
ALLOWED_KELAS = {'04', '05', '06'}


def _upload_result(message, success=False, kelas=None, status=400):
    """AJAX menerima JSON agar flash tidak habis dikonsumsi oleh fetch redirect."""
    target = url_for('tabel', kelas=kelas) if success else url_for('upload')
    if request.accept_mimetypes.best == 'application/json':
        if success:
            flash(message, 'success')
        return jsonify(success=success, message=message, redirect_url=target), (200 if success else status)
    flash(message, 'success' if success else 'error')
    return redirect(target)


def _source_headers(headers, source):
    if not headers:
        raise KPIValidationError(f'{source} kosong.')
    names, seen = [], set()
    for value in headers:
        if not isinstance(value, str) or not value.strip():
            raise KPIValidationError(f'{source} memiliki nama kolom kosong atau bukan teks.')
        name = re.sub(r'\s+', ' ', value.strip())
        if name.casefold() in seen:
            raise KPIValidationError(f'{source} memiliki kolom duplikat: {name}.')
        seen.add(name.casefold())
        names.append(name)
    return names


def _read_source_upload(file):
    if not file or not file.filename:
        raise KPIValidationError('Harap pilih file Excel terlebih dahulu.')
    extension = file.filename.rsplit('.', 1)[-1].lower()
    if extension not in ('xlsx', 'xls'):
        raise KPIValidationError('Format file tidak valid. Gunakan .xlsx atau .xls; PDF, Word, dan CSV tidak diterima.')
    try:
        raw = _read_excel_upload(file, extension)
    except KPIValidationError:
        raise
    except Exception as exc:
        raise KPIValidationError('File tidak dapat dibaca sebagai Excel atau ekspor tabel .xls. File mungkin rusak atau hanya diganti ekstensinya.') from exc
    if raw.empty:
        raise KPIValidationError('File Excel kosong.')
    names = _source_headers(raw.iloc[0].tolist(), 'Header file')
    frame = raw.iloc[1:].copy()
    frame.columns = names
    blank = frame.apply(lambda col: col.map(
        lambda value: pd.isna(value) or (isinstance(value, str) and not value.strip())))
    frame = frame.loc[~blank.all(axis=1)].reset_index(drop=True)
    if frame.empty:
        raise KPIValidationError('File hanya berisi header atau tidak memiliki baris data.')
    return frame


def _align_source_upload(frame, headers, excluded=()):
    names = _source_headers(headers, 'Header sheet tujuan')
    lookup = {_kpi_header_key(c): c for c in frame.columns}
    excluded_keys = {_kpi_header_key(c) for c in excluded}
    missing = [c for c in names if _kpi_header_key(c) not in lookup
               and _kpi_header_key(c) not in excluded_keys]
    if missing:
        raise KPIValidationError('Kolom file tidak sesuai sheet tujuan. Kolom wajib belum ada: ' + ', '.join(missing))
    # Hanya pengecualian eksplisit yang diberi placeholder kosong. Pemanggil
    # menentukan apakah kolom tersebut dikosongkan (KPRO) atau dilewati (BIMA).
    result = pd.DataFrame(index=frame.index)
    for name in names:
        key = _kpi_header_key(name)
        result[name] = '' if key in excluded_keys else frame[lookup[key]]
    if result.apply(lambda col: col.map(lambda v: pd.isna(v) or not str(v).strip())).all(axis=None):
        raise KPIValidationError('Hasil pemetaan tidak memiliki data. Periksa file dan sheet tujuan.')
    return result

# [FITUR] Upload Data - halaman upload BIMA dan KPRO
@flask_app.route('/upload')
@login_required
@role_required('admin', 'operator')
def upload():
    return render_template("upload.html", user=session['user'])

# [FITUR] Data Spreadsheet - melihat hasil pada sheet sumber upload
@flask_app.route('/tabel')
@login_required
def tabel():
    kelas = request.args.get('kelas', '04')
    if kelas not in ALLOWED_KELAS:
        kelas = '04'
    error = None; data_html = None; pagination = {}
    search_query = request.args.get('search', '').strip()
    total_all_rows = 0  # total sebelum filter search
    try:
        current_page = max(request.args.get('p', 1, type=int), 1)
        per_page = 100
        sheet_name = SHEET_NAMES['upload'][kelas]
        all_data = get_sheet_values(SPREADSHEET_IDS['upload'], sheet_name)
        if not all_data:
            raise ValueError("Tidak ada data.")
        if kelas in ['05', '04']:
            header = all_data[1] if len(all_data) > 2 else []
            rows   = all_data[2:] if len(all_data) > 2 else []
        else:
            header = all_data[0] if len(all_data) > 1 else []
            rows   = all_data[1:] if len(all_data) > 1 else []
        if not rows:
            raise ValueError("Tidak ada baris data.")
        total_all_rows = len(rows)

        # ── Server-side search (lintas seluruh data, bukan hanya halaman ini) ──
        if search_query:
            sq_lower = search_query.lower()
            rows = [r for r in rows if any(sq_lower in str(cell).lower() for cell in r)]

        total_rows = len(rows)
        total_pages = max((total_rows + per_page - 1) // per_page, 1)
        if current_page > total_pages: current_page = 1
        start_index = (current_page - 1) * per_page
        paginated = rows[start_index:start_index + per_page]
        df = pd.DataFrame(paginated, columns=header)
        cols_drop = [c for c in df.columns if str(c).strip().upper() == 'NO']
        if cols_drop:
            df.drop(columns=cols_drop, inplace=True)
        nomor = [start_index + i + 1 for i in range(len(df))]
        df.insert(0, 'No', nomor)
        data_html = df.to_html(classes='data', index=False, border=0, escape=True)
        pagination = {
            'current_page': current_page, 'total_pages': total_pages,
            'total_rows': total_rows, 'per_page': per_page, 'start_index': start_index,
        }
    except Exception as e:
        error = f"Gagal memuat data: {e}"
    return render_template(
        "tabel.html", data={kelas: data_html}, user=session['user'],
        kelas=kelas, error=error, pagination=pagination,
        search_query=search_query, total_all_rows=total_all_rows,
    )

# [FITUR] Upload BIMA - filter data Excel dan penggantian area impor BIMA
@flask_app.route('/filter', methods=['POST'])
@login_required
@role_required('admin', 'operator')
@serialized_sheet_write('upload')
def filter_data():
    kelas = request.form.get('kelas', '')
    if kelas != '06':
        return _upload_result('Filter BIMA hanya dapat memperbarui sheet BIMA.')
    file = request.files.get('file')
    writing = False
    try:
        df = _read_source_upload(file)
        req = ['SC Order No/Track ID/CSRM No', 'CRM Order Type', 'Status']
        if not all(c in df.columns for c in req):
            raise KPIValidationError('Kolom wajib BIMA belum lengkap: ' + ', '.join(c for c in req if c not in df.columns))
        filtered = df[
            df['SC Order No/Track ID/CSRM No'].astype(str).str.contains('WSA', case=False, na=False) &
            df['CRM Order Type'].isin(['CREATE', 'MIGRATE']) &
            (df['Status'] == 'WORKFAIL')
        ]
        if filtered.empty:
            raise KPIValidationError('Tidak ada data yang memenuhi filter BIMA (WSA, CREATE/MIGRATE, WORKFAIL).')
        cleaned = prepare_dataframe_for_sheets(filtered.copy())
        ws = get_worksheet(SPREADSHEET_IDS['upload'], SHEET_NAMES['upload'][kelas])
        all_data = ws.get_all_values()
        header_row = 1 if kelas == '06' else 2
        old_header = all_data[header_row - 1] if len(all_data) >= header_row else []
        max_col = gspread.utils.a1_to_rowcol('Z1')[1]
        safe_header = old_header[:max_col]
        source_keys = {_kpi_header_key(c) for c in cleaned.columns}
        # Ekspor BIMA boleh tanpa no kode; jangan timpa isi/formula kolom tujuan itu.
        preserved = tuple(i for i, name in enumerate(safe_header)
                          if _kpi_header_key(name) == 'no kode' and 'no kode' not in source_keys)
        cleaned = _align_source_upload(cleaned, safe_header,
                                       excluded=[safe_header[i] for i in preserved])
        writing = True
        try:
            replace_sheet_values(ws, cleaned.fillna('').astype(str).values.tolist(),
                                 header_row + 1, len(safe_header), preserve_columns=preserved)
        finally:
            invalidate_sheet_cache(SPREADSHEET_IDS['upload'], SHEET_NAMES['upload'][kelas])
        audit('upload_filter_bima', sheet_name=SHEET_NAMES['upload'][kelas], new_value=f"{len(cleaned)} rows")
        return _upload_result(f'Sheet BIMA berhasil diperbarui: {len(cleaned)} baris.', True, kelas)
    except KPIValidationError as e:
        return _upload_result(f'{e} Upload ditolak; data lama tidak diubah.')
    except Exception as e:
        traceback.print_exc()
        message = ('Penyimpanan gagal atau belum dapat dipastikan. Periksa sheet sebelum mencoba kembali.'
                   if writing else 'Gagal membaca file atau sheet tujuan. Data lama tidak diubah.')
        return _upload_result(message, status=503)

# [FITUR] Upload KPRO - penyesuaian kolom Excel dan penggantian area impor KPRO
@flask_app.route('/hapus_kolom', methods=['POST'])
@login_required
@role_required('admin', 'operator')
@serialized_sheet_write('upload')
def hapus_kolom():
    kelas = request.form.get('kelas', '')
    if kelas != '05':
        return _upload_result('Filter KPRO hanya dapat memperbarui sheet KPRO.')
    file = request.files.get('file')
    writing = False
    try:
        df = _read_source_upload(file)

        cols_del = ['CRMORDERTYPE', 'REGIONAL LAMA', 'DISTRICT LAMA', 'DATEL LAMA']
        df.drop(columns=[c for c in cols_del if c in df.columns], inplace=True)
        ws = get_worksheet(SPREADSHEET_IDS['upload'], SHEET_NAMES['upload'][kelas])
        sd = ws.get_all_values()
        full_header = (sd[1] if kelas in ['04', '05'] and len(sd) > 1 else (sd[0] if len(sd) > 0 else []))
        header_limited = full_header[:56]
        aligned = _align_source_upload(df, header_limited, excluded=cols_del).fillna('').astype(str).values.tolist()
        writing = True
        try:
            replace_sheet_values(ws, aligned, 2 if kelas == '06' else 3,
                                 len(header_limited))
        finally:
            invalidate_sheet_cache(SPREADSHEET_IDS['upload'], SHEET_NAMES['upload'][kelas])
        audit('upload_hapus_kolom', sheet_name=SHEET_NAMES['upload'][kelas], new_value=f"{len(aligned)} rows")
        return _upload_result(f'Sheet KPRO berhasil diperbarui: {len(aligned)} baris.', True, kelas)
    except KPIValidationError as e:
        return _upload_result(f'{e} Upload ditolak; data lama tidak diubah.')
    except Exception as e:
        traceback.print_exc()
        message = ('Penyimpanan gagal atau belum dapat dipastikan. Periksa sheet sebelum mencoba kembali.'
                   if writing else 'Gagal membaca file atau sheet tujuan. Data lama tidak diubah.')
        return _upload_result(message, status=503)

# =====================================================================
# [FITUR] User Online - pemetaan URL ke nama halaman aktivitas
# =====================================================================

# Mapping path → nama halaman yang tampil
PAGE_NAMES = {
    '/dashboard':          'Dashboard',
    '/kendala_master':     'DB Kendala Master',
    '/unsc':               'Sheet UNSC',
    '/upload':             'Upload Data',
    '/recap':              'Recap Report',
    '/kpi':                'Data KPI',
    '/kpi/tti':            'KPI — TTI',
    '/kpi/ffg':            'KPI — FFG',
    '/kpi/ttr':            'KPI — TTR FFG',
    '/audit_log':          'Audit Log',
    '/admin/users':        'Manajemen User',
    '/online':             'User Online',
    '/ganti_password':     'Ganti Password',
    '/verifikasi_odp_full':'Verifikasi ODP Full',
    '/tabel':              'Tabel Data',
}

def _page_name(path):
    """Konversi path URL ke nama halaman yang mudah dibaca."""
    if has_request_context() and request.script_root and path.startswith(request.script_root + '/'):
        path = path[len(request.script_root):]
    for key in sorted(PAGE_NAMES, key=len, reverse=True):
        if path == key or path.startswith(key + '/'):
            return PAGE_NAMES[key]
    return path or 'FilterIN'


# =====================================================================
# [PENDUKUNG] Cache - endpoint status dan refresh manual
# =====================================================================

@flask_app.route('/api/cache_status')
@api_login_required
@api_role_required('admin', 'operator')
def api_cache_status():
    """Status cache — berapa sheet yang di-cache dan kapan terakhir fetch."""
    try:
        refresh = _read_prefetch_status()
        scheduler = _cache_scheduler
        job = scheduler.get_job('prefetch_sheets') if scheduler and scheduler.running else None
        automatic = {
            'running': bool(job),
            'interval_seconds': PREFETCH_INTERVAL_SECONDS,
            'next_run_at': job.next_run_time.isoformat() if job and job.next_run_time else None,
            'server_time': datetime.now().astimezone().isoformat(timespec='milliseconds'),
        }
        # Bangun map cache_key → nama sheet dari PREFETCH_SHEETS saja
        sheet_map   = {}
        target_keys = []
        for sp_key, sh_key in PREFETCH_SHEETS:
            sp_id   = SPREADSHEET_IDS.get(sp_key)
            sh_name = SHEET_NAMES.get(sp_key, {}).get(sh_key)
            if sp_id and sh_name:
                ck = _cache_key(sp_id, sh_name)
                sheet_map[ck]  = sh_name
                target_keys.append(ck)

        if not target_keys:
            return jsonify(cache=[], total=0, refresh=refresh, automatic=automatic)

        # Ambil hanya cache untuk sheet yang di-prefetch
        placeholders = ','.join(['%s'] * len(target_keys))
        with db_cursor() as (conn, cur):
            cur.execute(f"""
                SELECT
                    cache_key,
                    row_count,
                    fetched_at,
                    TIMESTAMPDIFF(SECOND, fetched_at, NOW()) AS age_seconds
                FROM sheet_cache
                WHERE cache_key IN ({placeholders})
                ORDER BY fetched_at DESC
            """, target_keys)
            rows = cur.fetchall()

        # Buat result — termasuk sheet yang belum di-cache sama sekali
        cached_keys = {r['cache_key'] for r in rows}
        result = []

        for r in rows:
            result.append({
                'sheet_name':  sheet_map.get(r['cache_key'], '—'),
                'row_count':   r['row_count'],
                'fetched_at':  r['fetched_at'].strftime('%d/%m/%Y %H:%M:%S') if r['fetched_at'] else '—',
                'age_seconds': r['age_seconds'],
                'status':      'fresh' if r['age_seconds'] < SHEET_CACHE_TTL else 'stale',
            })

        # Sheet yang belum pernah di-cache
        for ck in target_keys:
            if ck not in cached_keys:
                result.append({
                    'sheet_name':  sheet_map.get(ck, '—'),
                    'row_count':   0,
                    'fetched_at':  '—',
                    'age_seconds': 99999,
                    'status':      'missing',
                })

        return jsonify(cache=result, total=len(result), refresh=refresh, automatic=automatic)
    except Exception:
        flask_app.logger.exception('Status pembaruan cache tidak dapat dibaca')
        return jsonify(error='Status pembaruan belum dapat diperiksa.'), 503


@flask_app.route('/api/cache_refresh', methods=['POST'])
@api_login_required
@api_role_required('admin')
def api_cache_refresh():
    """Force refresh semua cache — admin only."""
    try:
        previous = _read_prefetch_status()
        if previous and previous.get('state') == 'running':
            return jsonify(status='accepted', run_id=previous['run_id'],
                           previous_run_id=None, message='Pembaruan masih berjalan.')
        # Pertahankan cache cadangan sampai pembacaan sumber berhasil.
        # Jalankan prefetch job di background thread
        import threading
        t = threading.Thread(target=_prefetch_job, kwargs={'trigger': 'manual'}, daemon=True)
        t.start()
        audit('cache_refresh', new_value='manual refresh by admin')
        return jsonify(status='accepted', run_id=None,
                       previous_run_id=previous.get('run_id') if previous else None,
                       message='Permintaan pembaruan diterima; menunggu proses dimulai.')
    except Exception:
        flask_app.logger.exception('Permintaan pembaruan cache gagal')
        return jsonify(status='error', message='Pembaruan belum dapat dimulai. Coba kembali.'), 503


# [FITUR] User Online - heartbeat, jumlah pengguna aktif, dan halaman daftar online
# Tampilan: templates/online_users.html | Pengirim heartbeat: templates/base.html
@flask_app.route('/heartbeat', methods=['POST'])
@api_login_required
def heartbeat():
    """Terima sinyal heartbeat dari browser user — update status online."""
    user     = session.get('user', {})
    username = user.get('username', '')
    if not username:
        return jsonify({'ok': False}), 401

    # Ambil halaman yang sedang dibuka dari Referer header
    referer  = request.headers.get('Referer', '')
    try:
        from urllib.parse import urlparse
        path = urlparse(referer).path
    except Exception:
        path = '/dashboard'

    page_name = _page_name(path)

    try:
        with db_cursor() as (conn, cur):
            # Upsert ke tabel user_sessions
            cur.execute("""
                INSERT INTO user_sessions (username, current_page, last_seen)
                VALUES (%s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    current_page = VALUES(current_page),
                    last_seen    = NOW()
            """, (username, page_name))
        return jsonify({'ok': True})
    except Exception as e:
        # Kalau tabel belum ada, buat dulu
        try:
            with db_cursor() as (conn, cur):
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_sessions (
                        username     VARCHAR(50)  NOT NULL PRIMARY KEY,
                        current_page VARCHAR(100) DEFAULT 'Dashboard',
                        last_seen    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_last_seen (last_seen)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                cur.execute("""
                    INSERT INTO user_sessions (username, current_page, last_seen)
                    VALUES (%s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        current_page = VALUES(current_page),
                        last_seen    = NOW()
                """, (username, page_name))
            return jsonify({'ok': True})
        except Exception as e2:
            return jsonify({'ok': False, 'error': str(e2)}), 500


@flask_app.route('/api/online_count')
@api_login_required
def api_online_count():
    """Jumlah user yang aktif dalam 2 menit terakhir."""
    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT COUNT(*) AS c FROM user_sessions
                WHERE last_seen >= NOW() - INTERVAL 2 MINUTE
            """)
            row = cur.fetchone()
            return jsonify({'count': row['c'] if row else 0})
    except Exception:
        return jsonify({'count': 0})


@flask_app.route('/online')
@login_required
def online_users():
    """Halaman daftar user yang sedang online."""
    current_user = session['user']
    online, all_users_list = [], []

    try:
        with db_cursor() as (conn, cur):
            # User online: heartbeat dalam 2 menit terakhir
            cur.execute("""
                SELECT
                    s.username,
                    COALESCE(u.nama, s.username) AS nama,
                    u.role,
                    u.last_login,
                    s.current_page,
                    TIMESTAMPDIFF(SECOND, s.last_seen, NOW()) AS seconds_ago
                FROM user_sessions s
                LEFT JOIN users u ON u.username = s.username
                WHERE s.last_seen >= NOW() - INTERVAL 2 MINUTE
                ORDER BY seconds_ago ASC
            """)
            online = cur.fetchall()

            # Semua user terdaftar
            cur.execute(
                "SELECT id, nama, username, role, last_login FROM users ORDER BY role, nama"
            )
            all_users_list = cur.fetchall()

    except Exception as e:
        flash(f'Gagal ambil data online: {e}', 'error')

    return render_template('online_users.html',
        online_users = online,
        all_users    = all_users_list,
        current_user = current_user,
    )


# =====================================================================

# [FITUR] Manajemen Pengguna - daftar, tambah, edit, reset password, dan hapus akun
# Tampilan: templates/admin_users.html | Role: Admin | MySQL: users
@flask_app.route('/admin/users')
@login_required
@role_required('admin')
def admin_users():
    """Halaman manajemen user — hanya admin."""
    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT u.id, u.nama, u.username, u.role, u.created_at, u.last_login,
                       CASE WHEN s.last_seen >= NOW() - INTERVAL 2 MINUTE
                            THEN 1 ELSE 0 END AS is_online
                FROM users u
                LEFT JOIN user_sessions s ON s.username = u.username
                ORDER BY u.role, u.nama
            """)
            users = cur.fetchall()
    except Exception as e:
        flash(f'Gagal ambil data user: {e}', 'error')
        users = []
    return render_template(
        'admin_users.html',
        users        = users,
        current_user = session['user'],
    )


@flask_app.route('/admin/users/add', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_user():
    """Tambah user baru."""
    nama     = request.form.get('nama', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    role     = request.form.get('role', 'operator')

    if not nama or not username or not password:
        flash('Nama, username, dan password wajib diisi.', 'error')
        return redirect(url_for('admin_users'))
    if len(password) < 6:
        flash('Password minimal 6 karakter.', 'error')
        return redirect(url_for('admin_users'))
    if role not in ('admin', 'operator', 'viewer'):
        role = 'operator'

    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                "INSERT INTO users (nama, username, password, role) VALUES (%s, %s, %s, %s)",
                (nama, username, generate_password_hash(password), role)
            )
        audit('admin_add_user', new_value=f'{username} ({role})')
        flash(f'User @{username} berhasil ditambahkan.', 'success')
    except pymysql.err.IntegrityError:
        flash(f'Username "{username}" sudah dipakai, coba yang lain.', 'error')
    except Exception as e:
        flash(f'Gagal tambah user: {e}', 'error')
    return redirect(url_for('admin_users'))


@flask_app.route('/admin/users/edit', methods=['POST'])
@login_required
@role_required('admin')
def admin_edit_user():
    """Ubah role user."""
    user_id  = request.form.get('user_id', type=int)
    new_role = request.form.get('role', 'operator')

    if new_role not in ('admin', 'operator', 'viewer'):
        flash('Role tidak valid.', 'error')
        return redirect(url_for('admin_users'))

    # Cegah admin mengubah role dirinya sendiri
    if user_id == session['user']['id']:
        flash('Tidak bisa mengubah role akun Anda sendiri.', 'error')
        return redirect(url_for('admin_users'))

    try:
        with db_cursor() as (conn, cur):
            cur.execute('SELECT username FROM users WHERE id=%s FOR UPDATE', (user_id,))
            if not cur.fetchone():
                flash('User tidak ditemukan.', 'error')
                return redirect(url_for('admin_users'))
            cur.execute(
                "UPDATE users SET role=%s WHERE id=%s",
                (new_role, user_id)
            )
            cur.execute("SELECT username FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone()
        audit('admin_edit_role', new_value=f'id={user_id} → {new_role}')
        uname = row['username'] if row else f'id={user_id}'
        flash(f'Role @{uname} diubah menjadi {new_role}.', 'success')
    except Exception as e:
        flash(f'Gagal ubah role: {e}', 'error')
    return redirect(url_for('admin_users'))


@flask_app.route('/admin/users/reset_password', methods=['POST'])
@login_required
@role_required('admin')
def admin_reset_password():
    """Reset password user oleh admin."""
    user_id      = request.form.get('user_id', type=int)
    new_password = request.form.get('new_password', '')

    if len(new_password) < 6:
        flash('Password minimal 6 karakter.', 'error')
        return redirect(url_for('admin_users'))

    try:
        with db_cursor() as (conn, cur):
            cur.execute('SELECT username FROM users WHERE id=%s FOR UPDATE', (user_id,))
            if not cur.fetchone():
                flash('User tidak ditemukan.', 'error')
                return redirect(url_for('admin_users'))
            cur.execute(
                "UPDATE users SET password=%s WHERE id=%s",
                (generate_password_hash(new_password), user_id)
            )
            cur.execute("SELECT username FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone()
        audit('admin_reset_password', new_value=f'id={user_id}')
        uname = row['username'] if row else f'id={user_id}'
        flash(f'Password @{uname} berhasil direset.', 'success')
    except Exception as e:
        flash(f'Gagal reset password: {e}', 'error')
    return redirect(url_for('admin_users'))


@flask_app.route('/admin/users/delete', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_user():
    """Hapus user."""
    user_id = request.form.get('user_id', type=int)

    # Cegah admin menghapus dirinya sendiri
    if user_id == session['user']['id']:
        flash('Tidak bisa menghapus akun Anda sendiri.', 'error')
        return redirect(url_for('admin_users'))

    try:
        with db_cursor() as (conn, cur):
            cur.execute("SELECT username, nama FROM users WHERE id=%s", (user_id,))
            row = cur.fetchone()
            if not row:
                flash('User tidak ditemukan.', 'error')
                return redirect(url_for('admin_users'))
            cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
            cur.execute('DELETE FROM user_sessions WHERE username=%s', (row['username'],))
            cur.execute('DELETE FROM edit_locks WHERE locked_by=%s', (row['username'],))
        audit('admin_delete_user', new_value=f'{row["username"]} ({row["nama"]})')
        flash(f'User @{row["username"]} berhasil dihapus.', 'success')
    except Exception as e:
        flash(f'Gagal hapus user: {e}', 'error')
    return redirect(url_for('admin_users'))


# =====================================================================
# [FITUR] Audit Log - halaman pencarian/filter dan hapus log (Admin)
# =====================================================================
@flask_app.route('/audit_log')
@login_required
@role_required('admin')
def audit_log_view():
    current_user = session.get('user', {})
    page = max(request.args.get('p', 1, type=int), 1)
    per_page = 50
    user_filter   = request.args.get('user', '')
    action_filter = request.args.get('action', '')
    try:
        with db_cursor() as (conn, cur):
            where = []
            params = []
            if user_filter:
                where.append("username=%s"); params.append(user_filter)
            if action_filter:
                where.append("action=%s"); params.append(action_filter)
            where_sql = f"WHERE {' AND '.join(where)}" if where else ""
            cur.execute(f"SELECT COUNT(*) AS c FROM audit_log {where_sql}", params)
            total = cur.fetchone()['c']
            cur.execute(
                f"""SELECT * FROM audit_log {where_sql}
                    ORDER BY timestamp DESC LIMIT %s OFFSET %s""",
                params + [per_page, (page - 1) * per_page]
            )
            raw_rows = cur.fetchall()
            cur.execute("SELECT DISTINCT username FROM audit_log ORDER BY username")
            usernames = [r['username'] for r in cur.fetchall()]
            cur.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")
            actions = [r['action'] for r in cur.fetchall()]
    except Exception as e:
        flash(f"DB error: {e}", "error")
        raw_rows = []; total = 0; usernames = []; actions = []

    # Grouping: entri dengan timestamp+username+action+row_key sama → satu baris accordion
    groups = []
    seen = {}
    for row in raw_rows:
        ts_str = row['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if row['timestamp'] else ''
        key = (ts_str, row.get('username',''), row.get('action',''), row.get('sheet_name',''), row.get('row_key',''))
        if key not in seen:
            seen[key] = len(groups)
            groups.append({
                'timestamp':  row['timestamp'],
                'username':   row.get('username',''),
                'nama':       row.get('nama',''),
                'action':     row.get('action',''),
                'sheet_name': row.get('sheet_name',''),
                'row_key':    row.get('row_key',''),
                'ip_address': row.get('ip_address',''),
                'details':    [row],
            })
        else:
            groups[seen[key]]['details'].append(row)

    total_pages = max((total + per_page - 1) // per_page, 1)
    return render_template(
        'audit_log.html', groups=groups, page=page, total_pages=total_pages, total=total,
        usernames=usernames, actions=actions,
        user_filter=user_filter, action_filter=action_filter,
        current_user=current_user,
    )


@flask_app.route('/audit_log/clear', methods=['POST'])
@login_required
@role_required('admin')
def audit_log_clear():
    """Hapus audit log. keep_days=0 → hapus semua, keep_days=N → simpan N hari terakhir."""
    keep_days = request.form.get('keep_days', '')
    try:
        keep_days = int(keep_days)
    except ValueError:
        flash('Jumlah hari tidak valid; log tidak dihapus.', 'error')
        return redirect(url_for('audit_log_view'))
    if keep_days < 0:
        flash('Jumlah hari tidak boleh negatif.', 'error')
        return redirect(url_for('audit_log_view'))
    try:
        with db_cursor() as (conn, cur):
            if keep_days > 0:
                cur.execute(
                    "DELETE FROM audit_log WHERE timestamp < NOW() - INTERVAL %s DAY",
                    (keep_days,)
                )
                deleted = cur.rowcount
                flash(f"Berhasil menghapus {deleted} entri log lebih dari {keep_days} hari lalu.", "success")
            else:
                cur.execute("DELETE FROM audit_log")
                flash("Semua audit log berhasil dihapus.", "success")
    except Exception as e:
        flash(f"Gagal menghapus log: {e}", "error")
    return redirect(url_for('audit_log_view'))

# =====================================================================
# [PENDUKUNG] Recap Report - helper pivot/cross-tab dari DataFrame
# =====================================================================
def _pivot_2d(df, row_col, col_col):
    """
    Buat pivot sederhana: {row_val: {col_val: count, '_total': n}}
    dan dict total per kolom.
    """
    result   = {}
    col_totals = {}
 
    for _, r in df.iterrows():
        rv = str(r.get(row_col, '') or '').strip() or '(kosong)'
        cv = str(r.get(col_col, '') or '').strip() or '(kosong)'
        result.setdefault(rv, {})
        result[rv][cv]        = result[rv].get(cv, 0) + 1
        result[rv]['_total']  = result[rv].get('_total', 0) + 1
        col_totals[cv]        = col_totals.get(cv, 0) + 1
 
    # Sort descending by total
    result = dict(sorted(result.items(), key=lambda x: x[1].get('_total', 0), reverse=True))
    return result, col_totals
 
 
# =====================================================================
# [FITUR] KPI IndiHome - konfigurasi TTI, FFG, TTR FFG dan validasi upload
# =====================================================================

KPI_TYPES = {
    'tti': {
        'label':       'TTI (Ps Indihome)',
        'sheet_upload': 'tti_upload',
        'import_start_col': 1,
        'icon':        'fa-chart-line',
        'color':       '#2563eb',
    },
    'ffg': {
        'label':       'FFG (Not Comply)',
        'sheet_upload': 'ffg_upload',
        'import_start_col': 2,
        'icon':        'fa-circle-exclamation',
        'color':       '#dc2626',
    },
    'ttr': {
        'label':       'TTR FFG (Jml Ggn WSA)',
        'sheet_upload': 'ttr_upload',
        'import_start_col': 2,
        'icon':        'fa-wrench',
        'color':       '#d97706',
    },
}


class KPIValidationError(ValueError):
    """File atau header acuan tidak memenuhi struktur unggahan KPI."""

    def __init__(self, message, user_message=None):
        super().__init__(message)
        self.user_message = user_message


class _KPIHTMLTableParser(HTMLParser):
    """Baca tabel ekspor sebagai teks saja, tanpa browser atau akses resource luar."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.structure = []
        self.table_count = 0
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        allowed = {'html', 'head', 'body', 'title', 'meta', 'style', 'table',
                   'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'br',
                   'span', 'b', 'strong', 'i', 'em', 'font'}
        if tag not in allowed or any(name.startswith('on') for name, _ in attrs):
            raise KPIValidationError('Ekspor HTML mengandung elemen yang tidak didukung.')
        if any(name in ('rowspan', 'colspan') and value != '1' for name, value in attrs):
            raise KPIValidationError('Tabel ekspor tidak boleh memiliki sel gabungan.')
        if tag == 'table':
            self.table_count += 1
            if self.table_count != 1 or self.structure:
                raise KPIValidationError('Ekspor harus berisi tepat satu tabel, tanpa tabel bersarang.')
            self.structure.append(tag)
        elif tag == 'tr':
            if self.structure != ['table']:
                raise KPIValidationError('Struktur baris tabel ekspor tidak valid.')
            self.structure.append(tag)
            self.row = []
        elif tag in ('td', 'th'):
            if self.structure != ['table', 'tr']:
                raise KPIValidationError('Struktur sel tabel ekspor tidak valid.')
            self.structure.append(tag)
            self.cell = []
        elif tag == 'br' and self.cell is not None:
            self.cell.append('\n')

    def handle_endtag(self, tag):
        if tag not in ('table', 'tr', 'td', 'th'):
            return
        if not self.structure or self.structure[-1] != tag:
            raise KPIValidationError('Tabel ekspor rusak atau tidak lengkap.')
        self.structure.pop()
        if tag in ('td', 'th'):
            self.row.append(''.join(self.cell).strip())
            self.cell = None
        elif tag == 'tr':
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_decl(self, decl):
        if not decl.lower().startswith('doctype html') or '[' in decl:
            raise KPIValidationError('Deklarasi dokumen ekspor tidak didukung.')

    def handle_pi(self, data):
        raise KPIValidationError('Format XML tidak didukung. Simpan ulang sebagai .xlsx.')


def _read_excel_upload(file, extension, validate_headers=None):
    head = file.read(512).decode('utf-8-sig', errors='replace').lstrip().lower()
    file.seek(0)
    if head.startswith('<'):
        if extension != 'xls':
            raise KPIValidationError('Ekspor tabel HTML harus memakai .xls, bukan .xlsx.')
        try:
            content = file.read().decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise KPIValidationError('Encoding ekspor tidak didukung. Simpan ulang sebagai .xlsx.') from exc
        parser = _KPIHTMLTableParser()
        parser.feed(content)
        parser.close()
        # Ekspor asli portal berhenti pada </tbody>, tanpa </table>.
        # Toleransi hanya penutup tabel luar yang hilang: semua sel/baris harus
        # sudah tertutup dan dokumen benar-benar berakhir setelah tbody.
        if parser.structure == ['table'] and content.rstrip().lower().endswith('</tbody>'):
            parser.handle_endtag('table')
        if parser.table_count != 1 or parser.structure or not parser.rows:
            raise KPIValidationError('Ekspor harus berisi satu tabel lengkap dengan header dan data.')
        width = len(parser.rows[0])
        if not width or any(len(row) != width for row in parser.rows):
            raise KPIValidationError('Jumlah kolom antarbaris tabel ekspor tidak sama.')
        # Jangan inferensi angka/tanggal: ID berawalan nol dan teks NA harus utuh.
        return pd.DataFrame(parser.rows, dtype=object)
    engine = 'xlrd' if extension == 'xls' else 'openpyxl'
    if validate_headers is not None:
        # Tolak struktur yang salah sebelum pandas membaca seluruh baris workbook.
        # HTML .xls tetap melewati parser lengkap di atas agar pemeriksaan
        # struktur/elemen berbahaya di akhir dokumen tidak dilewati.
        preview = pd.read_excel(file, engine=engine, header=None, dtype=object,
                                keep_default_na=False, nrows=1)
        validate_headers(preview)
        file.seek(0)
    return pd.read_excel(file, engine=engine, header=None, dtype=object, keep_default_na=False)


def _kpi_header_key(value):
    # Perbedaan huruf besar dan spasi tidak mengubah identitas kolom.
    return re.sub(r'\s+', ' ', str(value).strip()).casefold()


def _validate_kpi_headers(headers, source):
    if not headers or len(headers) > 33:
        raise KPIValidationError(f'{source} harus memiliki 1–33 kolom (A–AG).')
    cleaned, seen = [], set()
    for pos, value in enumerate(headers, start=1):
        if not isinstance(value, str) or not value.strip():
            raise KPIValidationError(f'{source}: nama kolom ke-{pos} kosong atau bukan teks.')
        name = value.strip()
        key = _kpi_header_key(name)
        if key in seen:
            raise KPIValidationError(f'{source}: nama kolom duplikat "{name}".')
        seen.add(key)
        cleaned.append(name)
    return cleaned


def _prepare_kpi_upload(raw):
    """Baca header asli, sebelum pandas sempat mengganti header kosong/duplikat."""
    if raw.empty:
        raise KPIValidationError('File Excel kosong atau tidak memiliki header.')
    headers = _validate_kpi_headers(raw.iloc[0].tolist(), 'Header file Excel')
    data = raw.iloc[1:].copy()
    data.columns = headers
    blank = data.apply(lambda col: col.map(
        lambda value: pd.isna(value) or (isinstance(value, str) and not value.strip())))
    data = data.loc[~blank.all(axis=1)].reset_index(drop=True)
    if data.empty:
        raise KPIValidationError('File Excel hanya berisi header atau tidak memiliki baris data.')
    return data


def _kpi_import_headers(sheet_headers, info):
    """Header area impor saja; XCEK dan kolom di luar area bukan isi file Excel."""
    start_col = info['import_start_col']
    if start_col == 2 and (
            not sheet_headers or _kpi_header_key(sheet_headers[0]) != 'xcek'):
        raise KPIValidationError(
            f'Header acuan {info["label"]}: kolom A harus XCEK. '
            'Struktur sheet berubah; periksa sheet tujuan sebelum upload.')
    # Maksimal 33 kolom sumber: TTI A–AG, FFG/TTR B–AH.
    # Jangan memasukkan header kolom pendukung ke kontrak file upload.
    return sheet_headers[start_col - 1:start_col - 1 + 33]


def _align_kpi_upload(data, expected_headers, label):
    """Sheet tujuan adalah acuan struktur; jangan mempercayai header dari upload."""
    expected = _validate_kpi_headers(expected_headers, f'Header acuan {label}')
    actual_by_key = {_kpi_header_key(name): name for name in data.columns}
    expected_keys = {_kpi_header_key(name) for name in expected}
    missing = [name for name in expected if _kpi_header_key(name) not in actual_by_key]
    extra = [name for name in data.columns if _kpi_header_key(name) not in expected_keys]
    if missing or extra:
        details = []
        if missing:
            details.append('Kolom wajib belum ada: ' + ', '.join(missing))
        if extra:
            details.append('Kolom tidak dikenal: ' + ', '.join(extra))
        short_label = label.split(' (', 1)[0]
        raise KPIValidationError(
            f'Format kolom tidak sesuai untuk {label}. ' + '. '.join(details),
            user_message=(f'File tidak sesuai untuk KPI {short_label}. '
                          f'Pastikan Anda memilih file {short_label} dengan header yang benar.'))
    aligned = data[[actual_by_key[_kpi_header_key(name)] for name in expected]].copy()
    aligned.columns = expected
    return aligned


def _get_kpi_last_upload(kpi_type):
    """Ambil info terakhir upload KPI dari audit_log."""
    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                """SELECT a.timestamp, a.username, COALESCE(u.nama, a.username) AS nama
                   FROM audit_log a
                   LEFT JOIN users u ON u.username = a.username
                   WHERE a.action = %s
                   ORDER BY a.timestamp DESC LIMIT 1""",
                (f'kpi_upload_{kpi_type}',)
            )
            row = cur.fetchone()
            if row:
                return {
                    'timestamp': row['timestamp'].strftime('%d/%m/%Y %H:%M') if row['timestamp'] else '—',
                    'username':  row['username'],
                    'nama':      row['nama'],
                }
    except Exception:
        pass
    return None


# [FITUR] KPI IndiHome - halaman indeks dan detail hasil
@flask_app.route('/kpi')
@login_required
def kpi_index():
    """Halaman utama KPI — pilih jenis data."""
    last_uploads = {k: _get_kpi_last_upload(k) for k in KPI_TYPES}
    return render_template('kpi_index.html',
        kpi_types    = KPI_TYPES,
        last_uploads = last_uploads,
    )


@flask_app.route('/kpi/<kpi_type>')
@login_required
def kpi_detail(kpi_type):
    """Halaman detail + tabel data KPI."""
    if kpi_type not in KPI_TYPES:
        flash('Jenis KPI tidak valid.', 'error')
        return redirect(url_for('kpi_index'))

    info        = KPI_TYPES[kpi_type]
    sheet_key   = info['sheet_upload']
    sheet_name  = SHEET_NAMES['kpi'][sheet_key]
    last_upload = _get_kpi_last_upload(kpi_type)

    # Ambil data dari sheet upload
    header, data, error = [], [], None
    try:
        all_values = get_sheet_values(SPREADSHEET_IDS['kpi'], sheet_name)
        if all_values and len(all_values) >= 1:
            header = [str(h).strip() for h in all_values[0]]
            raw    = all_values[1:]
            data   = [r + [''] * (len(header) - len(r)) for r in raw if any(str(c).strip() for c in r)]
    except Exception as e:
        error = str(e)

    return render_template('kpi_detail.html',
        kpi_type       = kpi_type,
        info           = info,
        header         = header,
        data           = data,
        error          = error,
        last_upload    = last_upload,
        total_rows     = len(data),
        SHEET_NAMES_KPI= {k: SHEET_NAMES['kpi'][v['sheet_upload']] for k,v in KPI_TYPES.items()},
        enumerate      = enumerate,
    )


# [FITUR] KPI IndiHome - endpoint upload Excel dan penggantian area impor
@flask_app.route('/kpi/<kpi_type>/upload', methods=['POST'])
@login_required
@role_required('admin', 'operator')
@serialized_sheet_write('kpi')
def kpi_upload(kpi_type):
    """Ganti area data impor KPI, tanpa menulis header atau kolom pendukung."""
    if kpi_type not in KPI_TYPES:
        flash('Jenis KPI tidak valid.', 'error')
        return redirect(url_for('kpi_index'))

    info       = KPI_TYPES[kpi_type]
    sheet_key  = info['sheet_upload']
    sheet_name = SHEET_NAMES['kpi'][sheet_key]

    # Validasi file
    f = request.files.get('file')
    if not f or f.filename == '':
        flash('Harap pilih file Excel terlebih dahulu.', 'error')
        return redirect(url_for('kpi_detail', kpi_type=kpi_type))

    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext not in ('xlsx', 'xls'):
        flash('Format file tidak valid. Gunakan .xlsx atau .xls', 'error')
        return redirect(url_for('kpi_detail', kpi_type=kpi_type))

    try:
        ws, expected_headers = None, None

        def validate_headers_first(preview):
            nonlocal ws, expected_headers
            if preview.empty:
                raise KPIValidationError('File Excel kosong atau tidak memiliki header.')
            headers = _validate_kpi_headers(preview.iloc[0].tolist(), 'Header file Excel')
            # Tetap gunakan header sumber terbaru, bukan cache atau header upload.
            ws = get_worksheet(SPREADSHEET_IDS['kpi'], sheet_name)
            expected_headers = _kpi_import_headers(ws.row_values(1), info)
            _align_kpi_upload(pd.DataFrame(columns=headers), expected_headers, info['label'])

        raw = _read_excel_upload(f, ext, validate_headers=validate_headers_first)
        # Validasi lengkap tetap diperlukan: kolom ekstra dapat muncul hanya
        # pada baris data, dan file bisa hanya berisi header/baris kosong.
        df = _prepare_kpi_upload(raw)
        if ws is None:  # Ekspor HTML .xls sudah diperiksa lengkap oleh parser.
            validate_headers_first(raw)
        df = _align_kpi_upload(df, expected_headers, info['label'])

        total_excel = len(df)

        # Siapkan data untuk Google Sheets
        # Baris pertama Excel hanya untuk validasi; header sheet tetap dipertahankan.
        data_rows  = []
        for _, row in df.iterrows():
            r = []
            for v in row:
                if pd.isna(v):
                    r.append('')
                elif isinstance(v, float) and v == int(v):
                    r.append(int(v))
                else:
                    r.append(str(v) if not isinstance(v, (int, float)) else v)
            data_rows.append(r)

        try:
            # Data baru dan pengosongan sisa data lama dalam satu update.
            # Tidak menyentuh baris 1, XCEK, atau kolom di luar area impor.
            replace_sheet_values(ws, data_rows, 2, len(df.columns),
                                 start_col=info['import_start_col'])
        finally:
            invalidate_sheet_cache(SPREADSHEET_IDS['kpi'], sheet_name)

        # Catat ke audit_log
        audit(
            f'kpi_upload_{kpi_type}',
            sheet_name = sheet_name,
            new_value  = f'{total_excel} baris dari {f.filename}'
        )

        flash(
            f'✅ Berhasil upload {total_excel} baris data {info["label"]} '
            f'ke sheet "{sheet_name}".',
            'success'
        )

    except KPIValidationError as e:
        if e.user_message:
            # Rincian kolom untuk diagnosis, bukan notifikasi panjang kepada pengguna.
            flask_app.logger.warning('Upload KPI %s ditolak: %s', kpi_type, e)
            flash(f'{e.user_message} Data lama tidak diubah.', 'error')
        else:
            flash(f'{e} Upload ditolak; data lama tidak diubah.', 'error')
    except Exception as e:
        msg = str(e).lower()
        if 'expected bof' in msg or 'unsupported format' in msg or 'corrupt' in msg:
            flash(
                '❌ File terdeteksi bukan .xls. Silakan buka di Excel lalu '
                'Save As → "Excel Workbook (*.xlsx)".',
                'error'
            )
        else:
            flash(f'❌ Gagal upload: {e}', 'error')

    return redirect(url_for('kpi_detail', kpi_type=kpi_type))


# =====================================================================
# [FITUR] Recap Report - penyusunan ringkasan laporan dan tampilan recap.html
# =====================================================================
@flask_app.route('/recap')
@login_required
def recap():
    from datetime import datetime
    import calendar
 
    now = datetime.now()
    now_str = now.strftime('%d/%m/%Y %H:%M')
 
    # ------------------------------------------------------------------
    # 1. Ambil data DB Kendala Master
    # ------------------------------------------------------------------
    try:
        all_data = get_sheet_values(SPREADSHEET_IDS['kendala'],
                                    SHEET_NAMES['kendala']['kendalamaster'])
        df = hitung_rumus_otomatis(_sheet_frame(all_data), keep_dates=True)
    except Exception as e:
        flash(f'Gagal ambil data Kendala Master: {e}', 'error')
        df = pd.DataFrame()
 
    # ------------------------------------------------------------------
    # 2. Hitung statistik summary
    # ------------------------------------------------------------------
    stats = dict(total=0, current_active=0, wo_active_ao=0,
                 wo_active_pda=0, wo_inactive_ao=0, wo_inactive_pda=0, new_wo=0)
    feedback_datel      = {}
    feedback_datel_total = {}
    actual_datel        = {}
    actual_datel_total  = {}
    datels              = []
    wilayah_report      = {}
 
    if not df.empty:
        stats['total'] = len(df)
 
        # Kolom helper
        fb_col  = 'FEEDBACK ASO'
        ak_col  = 'ACTUAL KENDALA'
        dt_col  = 'DATEL'
        ia_col  = 'IS_ACTIVE_KENDALA'
        uic_col = 'CURRENT_UIC'
        oid_col = 'ORDER_ID'
        sto_col = 'STO'
 
        # WO Active/Inactive
        df_active   = df[df[ia_col] == 'ACTIVE']  if ia_col in df.columns else df
        df_inactive = df[df[ia_col] == 'INACTIVE'] if ia_col in df.columns else pd.DataFrame()
 
        stats['current_active'] = len(df_active)
 
        # Pisah AO vs PDA berdasar CURRENT_UIC atau fallback ke semua
        if uic_col in df.columns:
            stats['wo_active_ao']   = int((df_active[uic_col].str.strip().str.upper()   == 'TA').sum())
            stats['wo_active_pda']  = int((df_active[uic_col].str.strip().str.upper()   == 'TIF').sum())
            stats['wo_inactive_ao'] = int((df_inactive[uic_col].str.strip().str.upper() == 'TA').sum()) if not df_inactive.empty else 0
            stats['wo_inactive_pda']= int((df_inactive[uic_col].str.strip().str.upper() == 'TIF').sum()) if not df_inactive.empty else 0
        else:
            stats['wo_active_ao']    = len(df_active)
            stats['wo_inactive_ao']  = len(df_inactive) if not df_inactive.empty else 0
 
        # New WO (hari ini)
        if 'ORDER_DATE_DT' in df.columns:
            today = pd.Timestamp(now.date())
            stats['new_wo'] = int((df['ORDER_DATE_DT'].dt.normalize() == today).sum())
 
        # Daftar datel unik (urut)
        DATEL_ORDER = ['MAGELANG', 'KEBUMEN', 'PWREJO', 'MUNTILAN', 'TMNGGUNG', 'WONOSOBO']
        if dt_col in df_active.columns:
            raw_datels = df_active[dt_col].str.strip().str.upper().unique().tolist()
            datels = [d for d in DATEL_ORDER if d in raw_datels]
            datels += [d for d in raw_datels if d not in DATEL_ORDER and d]
        else:
            datels = []
 
        # Pivot Feedback ASO x Datel (hanya active)
        if fb_col in df_active.columns and dt_col in df_active.columns:
            feedback_datel, feedback_datel_total = _pivot_2d(df_active, fb_col, dt_col)
 
        # Pivot Actual Kendala x Datel (hanya active)
        if ak_col in df_active.columns and dt_col in df_active.columns:
            actual_datel, actual_datel_total = _pivot_2d(df_active, ak_col, dt_col)
 
        # Report per wilayah
        WILAYAH_MAP = {
            'MGL': ['MAGELANG'],
            'KBM': ['KEBUMEN'],
            'MUN': ['MUNTILAN'],
            'PWJ': ['PWREJO'],
            'TMG': ['TMNGGUNG'],
            'WOS': ['WONOSOBO'],
        }
 
        for wil, datel_list in WILAYAH_MAP.items():
            if dt_col not in df_active.columns:
                break
            mask  = df_active[dt_col].str.strip().str.upper().isin(datel_list)
            df_wil = df_active[mask]
            if df_wil.empty:
                continue
 
            def get_orders(df_sub, fb_vals):
                if fb_col not in df_sub.columns:
                    return []
                m = df_sub[fb_col].str.strip().str.upper().isin([v.upper() for v in fb_vals])
                rows = df_sub[m]
                result = []
                for _, r in rows.iterrows():
                    oid  = str(r.get(oid_col, '') or '').strip()
                    dt   = str(r.get(dt_col,  '') or '').strip()
                    note = str(r.get('NOTES ASO', '') or '').strip()
                    result.append(f"{dt} | {oid}" + (f" — {note[:60]}" if note else ''))
                return result
 
            wilayah_report[wil] = {
                'req_remanja' : get_orders(df_wil, ['REQ REMANJA', 'FU CALANG', 'REQ IJIN TATI - TSEL', 'REQ IJIN TATI']),
                'reorder'     : get_orders(df_wil, ['RE-ORDER', 'REORDER']),
                'done_tati'   : get_orders(df_wil, ['DONE TATI']),
                'ijin_tsel'   : get_orders(df_wil, ['IJIN TSEL', 'REQ IJIN TSEL']),
                'validasi_tsel': get_orders(df_wil, ['VALIDASI ADMINISTRASI TSEL', 'VERIFIKASI UNSC', 'VERIVIKASI UNSC']),
            }
 
    # ------------------------------------------------------------------
    # 3. TATI — baca dari sheet TATI
    # ------------------------------------------------------------------
    MONTHS     = ['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Ags','Sep','Okt','Nov','Des']
    tati_year  = str(now.year)
    tati_month_name = now.strftime('%B')
    tati_days  = list(range(1, calendar.monthrange(now.year, now.month)[1] + 1))
    tati_bulanan       = {}
    tati_bulanan_total = {}
    tati_harian        = {}
    tati_harian_total  = {}
 
    try:
        tati_data = get_sheet_values(SPREADSHEET_IDS['kendala'], 'TATI')
 
        # Tabel bulanan: B2:O10 → baris 2..10 = index 1..9
        if len(tati_data) >= 10:
            # Baris header di index 2 (baris ke-3), data dari index 3
            for row in tati_data[3:10]:
                if len(row) < 2 or not row[1]: continue
                datel = str(row[1]).strip().upper()
                if 'TOTAL' in datel or datel in ('JUMLAH', 'GRAND'): continue
                tati_bulanan[datel] = {}
                total = 0
                for i, m in enumerate(MONTHS):
                    col_idx = i + 2  # B=1, data mulai C=2
                    val = 0
                    if col_idx < len(row):
                        try: val = int(str(row[col_idx]).strip() or 0)
                        except: val = 0
                    tati_bulanan[datel][m] = val
                    total += val
                    tati_bulanan_total[m]    = tati_bulanan_total.get(m, 0) + val
                tati_bulanan[datel]['_total'] = total
                tati_bulanan_total['_total']  = tati_bulanan_total.get('_total', 0) + total
 
        # Tabel harian: R2:AX10 → kolom R=17, data 31 hari
        if len(tati_data) >= 10:
            for row in tati_data[3:10]:
                if not row: continue
                # Kolom R = index 17 (0-based)
                if len(row) <= 17: continue
                datel = str(row[17]).strip().upper()
                if not datel or 'TOTAL' in datel or datel in ('JUMLAH', 'GRAND'): continue
                tati_harian[datel] = {}
                total = 0
                for day in tati_days:
                    col_idx = 17 + day  # R=17, hari 1 = index 18
                    val = 0
                    if col_idx < len(row):
                        try: val = int(str(row[col_idx]).strip() or 0)
                        except: val = 0
                    tati_harian[datel][day] = val
                    total += val
                    tati_harian_total[day]     = tati_harian_total.get(day, 0) + val
                tati_harian[datel]['_total']  = total
                tati_harian_total['_total']   = tati_harian_total.get('_total', 0) + total
 
    except Exception as e:
        print(f'[RECAP TATI ERROR] {e}')
 
    # ------------------------------------------------------------------
    # 4. Laporan Validasi ODP — baca dari LAP VALIDASI ODP
    # ------------------------------------------------------------------
    odp_header = []
    odp_data   = []
    try:
        ws_odp    = get_worksheet(SPREADSHEET_IDS['kendala'], 'LAP VALIDASI ODP')
        odp_range = ws_odp.get('O5:S20')
        if odp_range and len(odp_range) >= 2:
            odp_header = [str(h).strip() for h in odp_range[0]]
            odp_data   = [
                r + [''] * (len(odp_header) - len(r))
                for r in odp_range[1:]
                if any(str(c).strip() for c in r)
            ]
    except Exception as e:
        print(f'[RECAP ODP ERROR] {e}')
 
    # ------------------------------------------------------------------
    # 5. Render
    # ------------------------------------------------------------------
    return render_template('recap.html',
        now_str            = now_str,
        stats              = stats,
        datels             = datels,
        feedback_datel     = feedback_datel,
        feedback_datel_total = feedback_datel_total,
        actual_datel       = actual_datel,
        actual_datel_total = actual_datel_total,
        wilayah_report     = wilayah_report,
        tati_year          = tati_year,
        tati_month_name    = tati_month_name,
        months             = MONTHS,
        tati_days          = tati_days,
        tati_bulanan       = tati_bulanan,
        tati_bulanan_total = tati_bulanan_total,
        tati_harian        = tati_harian,
        tati_harian_total  = tati_harian_total,
        odp_header         = odp_header,
        odp_data           = odp_data,
    )


# =====================================================================
# [FITUR] Verifikasi ODP - placeholder tampilan, belum memuat data operasional
# =====================================================================
@flask_app.route('/verifikasi_odp_full')
@login_required
def verifikasi_odp_full(): return render_template('verifikasi_odp_full.html', header=[], data=[])

# ════════════════════════════════════════════════════════════
# [FITUR] Watchlist - daftar pantauan, tambah, hapus, dan pembersihan
# ════════════════════════════════════════════════════════════
 
@flask_app.route('/api/watchlist', methods=['GET'])
@api_login_required
def watchlist_get():
    """Ambil semua watchlist (semua operator bisa lihat untuk koordinasi)."""
    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT w.*, 
                       DATE_FORMAT(w.flagged_at, '%d/%m/%Y %H:%i') AS flagged_at_fmt
                FROM watchlist w
                ORDER BY w.flagged_at DESC
                LIMIT 50
            """)
            rows = cur.fetchall()
        return jsonify(status='ok', data=rows)
    except Exception as e:
        return jsonify(status='error', message=str(e)), 500
 
 
@flask_app.route('/api/watchlist/add', methods=['POST'])
@api_login_required
@api_role_required('admin', 'operator')
def watchlist_add():
    """Tambah order ke watchlist."""
    data       = request.get_json() or {}
    order_id   = (data.get('order_id') or '').strip()
    catatan    = (data.get('catatan') or '').strip()[:255]
    sheet_name = data.get('sheet_name', 'kendalamaster')
 
    if not order_id:
        return jsonify(status='error', message='Order ID wajib diisi'), 400

    user  = session['user']
    uname = user['username']
    nama  = user.get('nama', uname)

    # Validasi: order_id harus ada di kendala master
    try:
        sheet_data = get_sheet_values(
            SPREADSHEET_IDS['kendala'],
            SHEET_NAMES['kendala']['kendalamaster']
        )
        if sheet_data and len(sheet_data) > 2:
            # Row 0 = judul sheet, Row 1 = header kolom, Row 2+ = data
            headers = [str(h).strip().upper() for h in sheet_data[1]]
            if 'ORDER_ID' in headers:
                idx = headers.index('ORDER_ID')
                valid_ids = {
                    str(row[idx]).strip()
                    for row in sheet_data[2:]
                    if len(row) > idx and str(row[idx]).strip()
                }
                if order_id not in valid_ids:
                    return jsonify(
                        status='error',
                        message=f'Order ID "{order_id}" tidak ditemukan di Kendala Master. Periksa kembali.'
                    ), 404
        else:
            return jsonify(
                status='error',
                message='Data Kendala Master tidak dapat diakses saat ini. Coba beberapa saat lagi.'
            ), 503
    except Exception as e:
        flask_app.logger.error("watchlist_add validation error: %s", e)
        return jsonify(
            status='error',
            message='Gagal memvalidasi Order ID. Coba beberapa saat lagi.'
        ), 500

    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                INSERT INTO watchlist (order_id, sheet_name, flagged_by, flagged_nama, catatan)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    catatan    = VALUES(catatan),
                    flagged_at = CURRENT_TIMESTAMP
            """, (order_id, sheet_name, uname, nama, catatan))
        audit('watchlist_add', row_key=order_id, new_value=catatan)
        return jsonify(status='ok', message=f'Order {order_id} berhasil ditambahkan ke watchlist')
    except Exception as e:
        flask_app.logger.error("watchlist_add error: %s", e)
        return jsonify(status='error', message='Gagal menyimpan watchlist'), 500
 
 
@flask_app.route('/api/watchlist/remove', methods=['POST'])
@api_login_required
@api_role_required('admin', 'operator')
def watchlist_remove():
    """Hapus dari watchlist (hanya yang punya flag, atau admin)."""
    data     = request.get_json() or {}
    order_id = (data.get('order_id') or '').strip()
    if not order_id:
        return jsonify(status='error', message='order_id wajib diisi'), 400
 
    user  = session['user']
    uname = user['username']
    role  = user.get('role', 'operator')
 
    try:
        with db_cursor() as (conn, cur):
            if role == 'admin':
                cur.execute("DELETE FROM watchlist WHERE order_id = %s", (order_id,))
            else:
                cur.execute(
                    "DELETE FROM watchlist WHERE order_id = %s AND flagged_by = %s",
                    (order_id, uname)
                )
            affected = cur.rowcount
        if affected == 0:
            return jsonify(status='error', message='Flag tidak ditemukan atau bukan milik Anda'), 403
        audit('watchlist_remove', row_key=order_id)
        return jsonify(status='ok', message=f'Flag {order_id} dihapus')
    except Exception as e:
        return jsonify(status='error', message=str(e)), 500
 
 
@flask_app.route('/api/watchlist/auto_clean', methods=['POST'])
@api_login_required
@api_role_required('admin', 'operator')
def watchlist_auto_clean():
    """Hapus watchlist untuk order yang sudah CLOSE di kendalamaster."""
    try:
        data = get_sheet_values(
            SPREADSHEET_IDS['kendala'],
            SHEET_NAMES['kendala']['kendalamaster'], force_refresh=True
        )
        if not data or len(data) < 2:
            return jsonify(status='ok', message='Tidak ada data cache', removed=0)
 
        headers = [h.strip().upper() for h in data[1]]
        try:
            idx_order  = headers.index('ORDER_ID')
            idx_status = headers.index('STATUS' if 'STATUS' in headers else 'STATUS_RESUME')
        except ValueError:
            return jsonify(status='error', message='Kolom ORDER_ID/STATUS tidak ditemukan'), 500
 
        closed_ids = [
            row[idx_order] for row in data[2:]
            if len(row) > max(idx_status, idx_order) and
               str(row[idx_status]).strip().upper() in ('CLOSE', 'CLOSED', 'SELESAI')
        ]
 
        if not closed_ids:
            return jsonify(status='ok', message='Tidak ada WO CLOSE', removed=0)
 
        placeholders = ','.join(['%s'] * len(closed_ids))
        with db_cursor() as (conn, cur):
            cur.execute(
                f"DELETE FROM watchlist WHERE order_id IN ({placeholders})",
                tuple(closed_ids)
            )
            removed = cur.rowcount
 
        if removed:
            audit('watchlist_auto_clean', new_value=f'{removed} flag dihapus (WO CLOSE)')
        return jsonify(status='ok', message=f'{removed} flag dihapus (WO sudah CLOSE)', removed=removed)
    except Exception as e:
        return jsonify(status='error', message=str(e)), 500
 
 
# ════════════════════════════════════════════════════════════
# [FITUR] Pengumuman - baca, tambah, dan hapus pengumuman
# ════════════════════════════════════════════════════════════
 
@flask_app.route('/api/announcements', methods=['GET'])
@api_login_required
def announcements_get():
    """Ambil pengumuman yang masih aktif (belum expire)."""
    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                SELECT id, judul, isi, label, posted_by, posted_nama,
                       DATE_FORMAT(created_at, '%d/%m/%Y %H:%i') AS created_fmt,
                       expires_at
                FROM announcements
                WHERE expires_at IS NULL OR expires_at > NOW()
                ORDER BY
                    FIELD(label, 'PENTING', 'REMINDER', 'INFO'),
                    created_at DESC
                LIMIT 10
            """)
            rows = cur.fetchall()
        # Ubah expires_at jadi string agar JSON-serializable
        for r in rows:
            if r['expires_at']:
                r['expires_at'] = r['expires_at'].strftime('%d/%m/%Y %H:%M')
        return jsonify(status='ok', data=rows)
    except Exception as e:
        return jsonify(status='error', message=str(e)), 500
 
 
@flask_app.route('/api/announcements/add', methods=['POST'])
@api_login_required
@api_role_required('admin')
def announcements_add():
    """Tambah pengumuman baru (admin only)."""
    data    = request.get_json() or {}
    judul   = (data.get('judul') or '').strip()[:200]
    isi     = (data.get('isi') or '').strip()
    label   = data.get('label', 'INFO').upper()
    expires = data.get('expires_hours')   # jam sampai expire, None = tidak expire
 
    if not judul or not isi:
        return jsonify(status='error', message='Judul dan isi wajib diisi'), 400
    if label not in ('PENTING', 'INFO', 'REMINDER'):
        label = 'INFO'
 
    user  = session['user']
    uname = user['username']
    nama  = user.get('nama', uname)
 
    expires_at = None
    if expires:
        try:
            expires_at = datetime.now() + timedelta(hours=float(expires))
        except (ValueError, TypeError):
            pass
 
    try:
        with db_cursor() as (conn, cur):
            cur.execute("""
                INSERT INTO announcements (judul, isi, label, posted_by, posted_nama, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (judul, isi, label, uname, nama, expires_at))
            new_id = cur.lastrowid
        audit('announcement_add', new_value=f'[{label}] {judul}')
        return jsonify(status='ok', message='Pengumuman berhasil ditambahkan', id=new_id)
    except Exception as e:
        return jsonify(status='error', message=str(e)), 500
 
 
@flask_app.route('/api/announcements/delete', methods=['POST'])
@api_login_required
@api_role_required('admin')
def announcements_delete():
    """Hapus pengumuman (admin only)."""
    data = request.get_json() or {}
    ann_id = data.get('id')
    if not ann_id:
        return jsonify(status='error', message='id wajib diisi'), 400
    try:
        with db_cursor() as (conn, cur):
            cur.execute("DELETE FROM announcements WHERE id = %s", (ann_id,))
        audit('announcement_delete', row_key=str(ann_id))
        return jsonify(status='ok', message='Pengumuman dihapus')
    except Exception as e:
        flask_app.logger.error("announcements_delete error: %s", e)
        return jsonify(status='error', message='Gagal menghapus pengumuman'), 500


# =====================================================================
# [PENDUKUNG] Health Check - endpoint pemeriksaan respons aplikasi
# =====================================================================
@flask_app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'FilterIN', 'time': datetime.now().isoformat()})

# Exempt webhook-style endpoints from CSRF if needed (none currently)

if os.environ.get('FILTERIN_SCHEDULER_ENABLED', '1') == '1':
    _threading.Thread(target=_deferred_start, daemon=True).start()

if __name__ == '__main__':
    flask_app.run(host='0.0.0.0', port=5000, debug=False)
