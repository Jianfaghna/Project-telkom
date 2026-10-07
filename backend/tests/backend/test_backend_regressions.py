"""Regresi lokal Prototipe 2. Semua akses MySQL/Google diganti fake; tanpa data live."""
import importlib
import calendar
import io
import os
import sys
import re
import shutil
import subprocess
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

os.environ['FILTERIN_SCHEDULER_ENABLED'] = '0'
for key in ('MYSQL_HOST', 'MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_DB',
            'SPREADSHEET_UPLOAD', 'SPREADSHEET_KENDALA', 'SPREADSHEET_ODP',
            'SPREADSHEET_PSRE', 'SPREADSHEET_KPI', 'FLASK_SECRET_KEY'):
    os.environ[key] = 'test-only-' + key
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
app = importlib.import_module('app_flask')
REAL_SHEET_GUARD = app.sheet_write_guard

USER = {'id': 1, 'username': 'tester', 'nama': 'Tester', 'role': 'admin', 'password': 'test-hash'}
HEADERS = ['ORDER_ID', 'STO', 'ORDER_DATE', 'STATUS_RESUME', 'ACTUAL KENDALA',
           'FEEDBACK ASO', 'NOTES ASO', 'IS_ACTIVE_KENDALA', 'CURRENT_UIC']


def sheet_row(oid='A', sto='MGL', age=2, **changes):
    vals = dict.fromkeys(HEADERS, '')
    vals.update(ORDER_ID=oid, STO=sto, ORDER_DATE=(datetime.now() - timedelta(days=age)).strftime('%d/%m/%Y'),
                STATUS_RESUME='WORKFAIL')
    vals.update(changes)
    return [vals[h] for h in HEADERS]


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Live service access forbidden in regression tests')
    monkeypatch.setattr(app.pymysql, 'connect', blocked)
    monkeypatch.setattr(app, 'gs_client', blocked)
    app._sheet_cache.clear()
    app.flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
    cursor = MagicMock()
    cursor.fetchone.return_value = dict(USER)
    cursor.fetchall.return_value = []
    cursor.rowcount = 1

    @contextmanager
    def db():
        yield MagicMock(), cursor
    monkeypatch.setattr(app, 'db_cursor', db)
    monkeypatch.setattr(app, 'sheet_write_guard', lambda *_: nullcontext())
    monkeypatch.setattr(app, 'invalidate_sheet_cache', MagicMock())
    monkeypatch.setattr(app, 'audit', MagicMock(return_value=True))
    monkeypatch.setattr(app, 'get_active_locks', lambda *_: {})
    monkeypatch.setattr(app, '_get_new_order_ids', lambda *_: {})
    monkeypatch.setattr(app, 'acquire_lock', lambda *_: (True, {}))
    monkeypatch.setattr(app, 'release_lock', MagicMock())
    return cursor


@pytest.fixture
def client():
    client = app.flask_app.test_client()
    with client.session_transaction() as s:
        s['user'] = dict(USER)
        s['auth_stamp'] = app.hashlib.sha256(USER['password'].encode()).hexdigest()
    return client


@pytest.fixture
def worksheet(monkeypatch):
    ws = MagicMock()
    ws.row_count = 100
    ws.col_count = len(HEADERS)
    ws.get_all_values.return_value = [['title'], HEADERS, sheet_row()]
    ws.row_values.side_effect = lambda rn: ws.get_all_values.return_value[rn - 1]
    monkeypatch.setattr(app, 'get_worksheet', lambda *_: ws)
    return ws


def test_formula_missing_columns_and_sparse_index():
    df = pd.DataFrame({'ORDER_DATE': ['01/09/2026', '2026-09-02']}, index=[3, 8])
    result = app.hitung_rumus_otomatis(df, keep_dates=True)
    assert result.index.tolist() == [3, 8]
    assert result['ORDER_DATE_DT'].notna().all()
    assert result['LAMA WO'].notna().all()


def test_manual_active_override_controls_age():
    df = pd.DataFrame({'ORDER_DATE': ['01/01/2026'], 'LAST_UPDATED_DATE': ['02/01/2026'],
                       'STATUS_RESUME': ['DONE'], 'IS_ACTIVE_KENDALA': ['ACTIVE']})
    result = app.hitung_rumus_otomatis(df)
    assert result.iloc[0]['LAMA WO'] > 1
    assert result.iloc[0]['IS_ACTIVE_KENDALA'] == 'ACTIVE'


def test_frame_pads_short_rows_and_keeps_source_identity():
    df = app._sheet_frame([['title'], HEADERS, sheet_row('A'), [], ['B']])
    assert df['__SHEET_ROW__'].tolist() == [3, 5]
    assert df['ORDER_ID'].tolist() == ['A', 'B']


@pytest.mark.parametrize('path', ['/kendala_master', '/kendala_data'])
def test_filtered_single_row_uses_sheet_row(client, monkeypatch, worksheet, path):
    data = [['title'], HEADERS, sheet_row('A', 'KBM'), [], sheet_row('B[', 'MGL')]
    monkeypatch.setattr(app, 'get_sheet_values', lambda *_: data)
    response = client.get(path + '?sto=MGL&search=B%5B&is_active=ACTIVE')
    assert response.status_code == 200
    if response.is_json:
        assert response.json['sheet_rows'] == [5]
        assert response.json['data'][0][0] == 'B['
    else:
        html = response.get_data(as_text=True)
        assert 'data-row-num="5"' in html
        assert '__snapshot__[5]' in html
        assert 'ORDER_DATE_DT' not in html


def test_date_filter_matches_html_and_polling(client, monkeypatch, worksheet):
    data = [['title'], HEADERS, sheet_row('TODAY', age=0), sheet_row('OLD', age=5)]
    monkeypatch.setattr(app, 'get_sheet_values', lambda *_: data)
    today = datetime.now().strftime('%Y-%m-%d')
    response = client.get('/kendala_data?date_from=' + today + '&date_to=' + today)
    assert response.json['total'] == 1
    assert response.json['data'][0][0] == 'TODAY'
    html = client.get('/kendala_master?date_from=' + today).get_data(as_text=True)
    assert 'data-order-id="TODAY"' in html
    assert 'data-order-id="OLD"' not in html


@pytest.mark.parametrize('new_ids', [{}, {'FRESH': {'time': 'test', 'batch': 'test'}}])
def test_new_badge_and_filter_follow_sync_metadata_not_row_dates(client, monkeypatch, new_ids):
    data = [['title'], HEADERS, sheet_row('OLD-TODAY', age=0), sheet_row('FRESH', age=5)]
    monkeypatch.setattr(app, 'get_sheet_values', lambda *_: data)
    monkeypatch.setattr(app, '_get_new_order_ids', lambda *_: new_ids)

    response = client.get('/kendala_data')
    assert response.status_code == 200
    assert response.json['is_new_flags'] == [False, bool(new_ids)]
    html = client.get('/kendala_master').get_data(as_text=True)
    for oid, expected in [('OLD-TODAY', False), ('FRESH', bool(new_ids))]:
        row = re.search(r'<tr\b[^>]*data-order-id="' + oid + r'"[\s\S]*?</tr>', html)
        assert row is not None
        assert ('is-new-row' in row.group()) == expected
        assert row.group().count('class="badge-new"') == int(expected)

    filtered = client.get('/kendala_data?new_only=1').json
    assert filtered['total'] == int(bool(new_ids))
    assert [row[0] for row in filtered['data']] == (['FRESH'] if new_ids else [])
    filtered_html = client.get('/kendala_master?new_only=1').get_data(as_text=True)
    assert 'data-order-id="OLD-TODAY"' not in filtered_html
    assert ('data-order-id="FRESH"' in filtered_html) == bool(new_ids)


def test_mark_seen_removes_new_badge_without_removing_order(client, monkeypatch, isolate):
    data = [['title'], HEADERS, sheet_row('FRESH', age=0)]
    new_ids = {'FRESH': {'time': 'test', 'batch': 'test'}}
    monkeypatch.setattr(app, 'get_sheet_values', lambda *_: data)
    monkeypatch.setattr(app, '_get_new_order_ids', lambda *_: dict(new_ids))

    def execute(query, params=None):
        if 'UPDATE sync_new_rows' in query:
            assert params == ('tester', 'tester')
            assert 'JSON_CONTAINS' in query
            new_ids.clear()

    isolate.execute.side_effect = execute
    assert client.get('/kendala_data').json['is_new_flags'] == [True]
    assert client.post('/mark_new_seen').json['ok'] is True
    response = client.get('/kendala_data').json
    assert response['is_new_flags'] == [False]
    assert response['total'] == 1
    assert response['data'][0][0] == 'FRESH'
    assert client.get('/kendala_data?new_only=1').json['total'] == 0
    html = client.get('/kendala_master').get_data(as_text=True)
    assert 'data-order-id="FRESH"' in html
    assert 'class="badge-new"' not in html


@pytest.mark.parametrize('query', ['', '?p=2', '?search=ORDER-10', '?new_only=1'])
def test_kendala_html_and_poll_share_stable_revision(client, monkeypatch, query):
    data = [['title'], HEADERS] + [sheet_row('ORDER-' + str(i), **{'NOTES ASO': 'Catatan  '}) for i in range(105)]
    monkeypatch.setattr(app, 'get_sheet_values', lambda *_: data)
    monkeypatch.setattr(app, '_get_new_order_ids', lambda *_: {'ORDER-104': {}})
    html = client.get('/kendala_master' + query).get_data(as_text=True)
    match = re.search(r'const kendalaRevision = ("[a-f0-9]+")', html)
    assert match is not None
    initial = app.json.loads(match.group(1))
    for _ in range(2):
        response = client.get('/kendala_data' + query)
        assert response.status_code == 200
        assert response.json['revision'] == initial


@pytest.mark.parametrize('change', ['value', 'row_order', 'new_flag', 'off_page_append', 'header'])
def test_kendala_revision_detects_meaningful_server_changes(client, monkeypatch, change):
    data = [['title'], HEADERS.copy()] + [sheet_row('ORDER-' + str(i)) for i in range(101)]
    new_ids = {}
    monkeypatch.setattr(app, 'get_sheet_values', lambda *_: data)
    monkeypatch.setattr(app, '_get_new_order_ids', lambda *_: new_ids)
    initial = client.get('/kendala_data').json['revision']
    if change == 'value':
        data[2][HEADERS.index('NOTES ASO')] = 'Diperbarui pengguna lain'
    elif change == 'row_order':
        data[2], data[3] = data[3], data[2]
    elif change == 'new_flag':
        new_ids['ORDER-0'] = {}
    elif change == 'off_page_append':
        data.append(sheet_row('ORDER-101'))
    else:
        data[1].append('EXTRA')
    assert client.get('/kendala_data').json['revision'] != initial


def test_dashboard_age_buckets_and_trend(monkeypatch):
    data = [['title'], HEADERS] + [sheet_row(str(age), age=age) for age in (0, 2, 5, 9, 18, 25, 35)]
    monkeypatch.setattr(app, 'get_sheet_values', lambda *_: data)
    stats = app._compute_dashboard_stats()
    assert stats['total'] == 7
    assert sum(stats['chart_umur']['values']) == 7
    assert stats['chart_trend']['values'][-1] == 1


def test_recap_today_and_total_not_double_counted(client, monkeypatch, worksheet):
    tati = [[], [], []] + [['', 'MAGELANG', '3'], ['', 'TOTAL', '3']] + [[]] * 5
    monkeypatch.setattr(app, 'get_sheet_values', lambda sp, sheet: tati if sheet == 'TATI'
                        else [['title'], HEADERS, sheet_row(age=0)])
    worksheet.get.return_value = []
    captured = {}
    monkeypatch.setattr(app, 'render_template', lambda name, **kw: captured.update(kw) or 'ok')
    assert client.get('/recap').status_code == 200
    assert captured['stats']['new_wo'] == 1
    assert captured['tati_bulanan_total']['_total'] == 3
    assert len(captured['tati_days']) == calendar.monthrange(datetime.now().year, datetime.now().month)[1]


def payload(worksheet, **kwargs):
    result = {'row_num': 3, 'row_key': 'A', 'updates': {'NOTES ASO': 'baru'},
              'original_values': dict(zip(HEADERS, worksheet.get_all_values.return_value[2]))}
    result.update(kwargs)
    return result


def test_quick_edit_audit_after_success(client, worksheet, monkeypatch):
    events = []
    worksheet.update_cells.side_effect = lambda *a, **kw: events.append('write')
    monkeypatch.setattr(app, 'audit', lambda *a, **kw: events.append('audit'))
    response = client.post('/update_kendala_row', json=payload(worksheet))
    assert response.status_code == 200
    assert events == ['write', 'audit']
    assert worksheet.update_cells.call_args.kwargs['value_input_option'] == 'RAW'
    snapshot = app.URLSafeSerializer(app.flask_app.secret_key, salt='sheet-row').loads(response.json['row_token'])
    assert snapshot['values']['NOTES ASO'] == 'baru'


def test_failed_write_does_not_audit(client, worksheet):
    worksheet.update_cells.side_effect = RuntimeError('Google unavailable')
    assert client.post('/update_kendala_row', json=payload(worksheet)).status_code == 500
    app.audit.assert_not_called()
    app.invalidate_sheet_cache.assert_called()


@pytest.mark.parametrize('case', ['moved', 'concurrent', 'protected', 'header', 'missing_snapshot', 'bad_number'])
def test_edit_rejects_invalid_or_conflicting_changes(client, worksheet, case):
    data = payload(worksheet)
    expected = 400
    if case == 'moved':
        data['row_key'] = 'OTHER'
        data['original_values']['ORDER_ID'] = 'OTHER'
        expected = 409
    elif case == 'concurrent':
        worksheet.get_all_values.return_value[2][6] = 'external edit'
        expected = 409
    elif case == 'protected':
        data['updates'] = {'ORDER_ID': 'OTHER'}
    elif case == 'header':
        data['row_num'] = 2
    elif case == 'missing_snapshot':
        data.pop('original_values')
    elif case == 'bad_number':
        data['row_num'] = 'invalid'
    assert client.post('/update_kendala_row', json=data).status_code == expected
    worksheet.update_cells.assert_not_called()
    app.audit.assert_not_called()


def test_lock_failure_blocks_write(client, worksheet, monkeypatch):
    monkeypatch.setattr(app, 'acquire_lock', lambda *_: (False, None))
    assert client.post('/update_kendala_row', json=payload(worksheet)).status_code == 409
    worksheet.update_cells.assert_not_called()


@pytest.mark.parametrize('outcome,status', [(True, 200), (False, 409), ('offline', 503)])
def test_renew_lock_api_never_reacquires_lock(client, monkeypatch, outcome, status):
    renew = MagicMock(return_value=outcome)
    if outcome == 'offline':
        renew.side_effect = RuntimeError('db unavailable')
    acquire = MagicMock(side_effect=AssertionError('Renewal must not acquire a lock'))
    monkeypatch.setattr(app, 'renew_lock', renew)
    monkeypatch.setattr(app, 'acquire_lock', acquire)
    response = client.post('/renew-lock', json={'sheet_name': app.SHEET_NAMES['kendala']['kendalamaster'], 'row_key': 'A'})
    assert response.status_code == status
    assert response.json['ok'] is (status == 200)
    acquire.assert_not_called()
    if status == 200:
        assert response.json['ttl_seconds'] == app.EDIT_LOCK_TTL_MINUTES * 60


@pytest.mark.parametrize('data', [[], None, {}, {'sheet_name': 'unrecognized', 'row_key': 'A'},
                                  {'sheet_name': 'DB KENDALA (MASTER)', 'row_key': ''}])
def test_renew_lock_rejects_invalid_payload(client, data):
    assert client.post('/renew-lock', json=data).status_code == 400


@pytest.mark.parametrize('changed,found,expected', [(1, None, True), (0, {'owned': 1}, True), (0, None, False)])
def test_renewal_sql_checks_current_owner_and_expiry(isolate, changed, found, expected):
    isolate.rowcount = changed
    isolate.fetchone.return_value = found
    with app.flask_app.test_request_context():
        app.session['user'] = dict(USER)
        assert app.renew_lock('sheet', 'A') is expected
    for call in isolate.execute.call_args_list:
        sql, args = call.args
        assert 'locked_by=%s' in sql
        assert 'locked_at >=' in sql
        assert args == ('sheet', 'A', USER['username'], app.EDIT_LOCK_TTL_MINUTES)
        assert 'INSERT' not in sql


def test_renewal_requires_edit_role(client, isolate):
    isolate.fetchone.return_value = {**USER, 'role': 'viewer'}
    response = client.post('/renew-lock', json={'sheet_name': 'DB KENDALA (MASTER)', 'row_key': 'A'})
    assert response.status_code == 403


@pytest.mark.parametrize('route,sheet_key', [('/update_kendala', 'kendalamaster'), ('/update_unsc', 'unsc')])
@pytest.mark.parametrize('conflict', [True, False])
def test_bulk_ajax_response_keeps_conflicts_on_page(client, worksheet, route, sheet_key, conflict):
    headers = ['ORDER_ID', 'STATUS']
    worksheet.get_all_values.return_value = [['title'], headers, ['A', 'old' if not conflict else 'other-user']]
    sheet = app.SHEET_NAMES['kendala'][sheet_key]
    if sheet_key == 'kendalamaster':
        headers[1] = 'NOTES ASO'
    token = app._row_token(sheet, 3, headers, ['A', 'old'])
    response = client.post(route, headers={'Accept': 'application/json'},
                           data={headers[1] + '[3]': 'mine', '__snapshot__[3]': token})
    assert response.status_code == (409 if conflict else 200)
    assert response.json['ok'] is not conflict
    assert 'Location' not in response.headers
    if conflict:
        worksheet.update_cells.assert_not_called()
    else:
        assert response.json['row_tokens']['3']
        worksheet.update_cells.assert_called_once()


def test_bulk_snapshot_rejects_moved_order(client, worksheet):
    token = app._row_token(app.SHEET_NAMES['kendala']['kendalamaster'], 3, HEADERS, sheet_row('OLD'))
    client.post('/update_kendala', data={'NOTES ASO[3]': 'new', '__snapshot__[3]': token})
    worksheet.update_cells.assert_not_called()


def test_bulk_success_has_per_column_audit(client, worksheet):
    token = app._row_token(app.SHEET_NAMES['kendala']['kendalamaster'], 3, HEADERS, sheet_row())
    response = client.post('/update_kendala', data={'NOTES ASO[3]': 'new', '__snapshot__[3]': token})
    assert response.status_code == 302
    assert app.audit.call_args.kwargs['row_key'] == 'A'
    assert app.audit.call_args.kwargs['old_value'] == ''


@pytest.mark.parametrize('value', ['typo', '', '-1'])
def test_invalid_audit_retention_never_deletes(client, isolate, value):
    client.post('/audit_log/clear', data={'keep_days': value})
    assert not any('DELETE FROM audit_log' in str(c) for c in isolate.execute.call_args_list)


@pytest.mark.parametrize('path', ['/update_kendala_row', '/api/watchlist/auto_clean', '/api/announcements/add'])
def test_role_change_applies_to_existing_session(client, isolate, path):
    isolate.fetchone.return_value = dict(USER, role='viewer')
    response = client.post(path, json={})
    assert response.status_code == 403
    assert response.is_json


@pytest.mark.parametrize('path,field', [('/order_history/A', 'history'), ('/api/cache_status', 'cache')])
@pytest.mark.parametrize('role', ['admin', 'operator', 'viewer', 'unknown'])
def test_operational_metadata_read_roles(client, isolate, path, field, role):
    # The fixture session starts as Admin; the database role must override it.
    isolate.fetchone.return_value = dict(USER, role=role)
    response = client.get(path)
    allowed = role in ('admin', 'operator')
    assert response.status_code == (200 if allowed else 403)
    assert response.is_json
    if allowed:
        assert field in response.json
        isolate.fetchall.assert_called_once()
    else:
        assert response.json['error'] == 'forbidden'
        assert field not in response.json
        isolate.fetchall.assert_not_called()
        # Only the session validation query is permitted, not the feature query.
        assert isolate.execute.call_count == 1


@pytest.mark.parametrize('path', ['/order_history/A', '/api/cache_status'])
def test_operational_metadata_requires_login(isolate, path):
    response = app.flask_app.test_client().get(path)
    assert response.status_code == 401
    isolate.execute.assert_not_called()


@pytest.mark.parametrize('role', ['admin', 'operator', 'viewer'])
def test_cache_refresh_stays_admin_only(client, isolate, monkeypatch, role):
    isolate.fetchone.return_value = dict(USER, role=role)
    thread = MagicMock()
    monkeypatch.setattr('threading.Thread', thread)
    response = client.post('/api/cache_refresh', json={})
    assert response.status_code == (200 if role == 'admin' else 403)
    if role == 'admin':
        thread.assert_called_once_with(target=app._prefetch_job, kwargs={'trigger': 'manual'}, daemon=True)
        thread.return_value.start.assert_called_once()
        assert response.json['status'] == 'accepted'
    else:
        thread.assert_not_called()
        app.audit.assert_not_called()


@pytest.mark.parametrize('role,can_write,is_admin', [
    ('admin', True, True), ('operator', True, False), ('viewer', False, False), ('unknown', False, False)])
def test_watchlist_template_uses_explicit_role_allowlist(role, can_write, is_admin):
    template = (Path(__file__).resolve().parents[2] / 'templates' / 'dashboard.html').read_text(encoding='utf-8')
    declarations = template[template.index('const CURRENT_USER'):template.index('function loadWatchlist()')]
    rendered = app.flask_app.jinja_env.from_string(declarations).render(session={'user': {'role': role, 'username': 'tester'}})
    assert re.search(r'const CAN_WRITE\s*=\s*' + str(can_write).lower() + ';', rendered)
    assert re.search(r'const IS_ADMIN\s*=\s*' + str(is_admin).lower() + ';', rendered)


def test_deleted_account_loses_access(client, isolate):
    isolate.fetchone.return_value = None
    assert client.get('/kendala_data').status_code == 401


def test_logout_removes_presence_and_locks(client, isolate):
    assert client.get('/logout').status_code == 302
    queries = str(isolate.execute.call_args_list)
    assert 'DELETE FROM user_sessions' in queries and 'DELETE FROM edit_locks' in queries


def test_replace_one_request_and_clear_tail(worksheet):
    worksheet.get_all_values.return_value = [['old', 'extra']] * 4
    app.replace_sheet_values(worksheet, [['new']], 1, 2)
    worksheet.clear.assert_not_called()
    worksheet.update.assert_called_once()
    assert worksheet.update.call_args.kwargs['values'] == [['new', ''], ['', ''], ['', ''], ['', '']]


@pytest.mark.parametrize('extension', ['xlsx', 'xls'])
def test_kpi_upload_invalidates_and_does_not_clear_first(client, worksheet, monkeypatch, extension):
    parser = MagicMock(return_value=pd.DataFrame([['ORDER_ID'], ['001']]))
    monkeypatch.setattr(app.pd, 'read_excel', parser)
    worksheet.get_all_values.return_value = [['ORDER_ID'], ['OLD']]
    response = client.post('/kpi/tti/upload', data={'file': (io.BytesIO(b'Excel placeholder'), f'test.{extension}')})
    assert response.status_code == 302
    assert parser.call_args.kwargs['engine'] == ('xlrd' if extension == 'xls' else 'openpyxl')
    assert parser.call_args.kwargs['header'] is None
    assert parser.call_args.kwargs['keep_default_na'] is False
    worksheet.clear.assert_not_called()
    worksheet.update.assert_called_once()
    assert worksheet.update.call_args.kwargs['values'] == [['001']]
    assert worksheet.update.call_args.kwargs['range_name'] == 'A2:A2'
    app.invalidate_sheet_cache.assert_called_with(app.SPREADSHEET_IDS['kpi'], app.SHEET_NAMES['kpi']['tti_upload'])


@pytest.mark.parametrize('kpi_type', ['tti', 'ffg', 'ttr'])
@pytest.mark.parametrize('filename, content', [
    ('report.pdf', b'%PDF-1.7 invalid KPI content'),
    ('report.docx', b'Word document'),
    ('report.txt', b'plain text'),
    ('report.csv', b'ORDER_ID,STATUS\nA,DONE'),
    ('report.xlsx.pdf', b'%PDF-1.7 disguised extension'),
    ('report.xlsx', b'%PDF-1.7 renamed PDF'),
    ('report.xls', b'%PDF-1.7 renamed PDF'),
    ('report.xlsx', b'Word document renamed as Excel'),
    ('report.xls', b'<html><table><tr><td>A</td></tr></table></html>'),
    ('report.xlsx', b'PK\x03\x04 truncated ZIP workbook'),
    ('report.xls', b''),
])
def test_invalid_kpi_files_never_access_or_write_sheets(client, monkeypatch, kpi_type, filename, content):
    get_ws = MagicMock(side_effect=AssertionError('Invalid files must be rejected before Sheets access'))
    monkeypatch.setattr(app, 'get_worksheet', get_ws)
    response = client.post(f'/kpi/{kpi_type}/upload',
                           data={'file': (io.BytesIO(content), filename)})
    assert response.status_code == 302
    assert response.headers['Location'].endswith(f'/kpi/{kpi_type}')
    with client.session_transaction() as s:
        messages = s.get('_flashes', [])
    assert any(category == 'error' for category, _ in messages)
    assert not any(category == 'success' for category, _ in messages)
    get_ws.assert_not_called()
    app.audit.assert_not_called()
    app.invalidate_sheet_cache.assert_not_called()


def test_docx_zip_renamed_xlsx_is_rejected(client, monkeypatch):
    import zipfile
    content = io.BytesIO()
    with zipfile.ZipFile(content, 'w') as archive:
        archive.writestr('[Content_Types].xml',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>')
        archive.writestr('word/document.xml', '<document/>')
    content.seek(0)
    get_ws = MagicMock()
    monkeypatch.setattr(app, 'get_worksheet', get_ws)
    response = client.post('/kpi/tti/upload', data={'file': (content, 'renamed.xlsx')})
    assert response.status_code == 302
    with client.session_transaction() as s:
        assert any(category == 'error' for category, _ in s.get('_flashes', []))
    get_ws.assert_not_called()
    app.audit.assert_not_called()


def excel_content(rows):
    # Workbook sungguhan di memory, tanpa file pengguna atau layanan eksternal.
    from openpyxl import Workbook
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


SOURCE_UPLOADS = [('/filter', '06'), ('/hapus_kolom', '05')]


@pytest.mark.parametrize('route,kelas', SOURCE_UPLOADS)
@pytest.mark.parametrize('filename,content', [
    ('file.pdf', b'%PDF-1.7'), ('file.docx', b'Word'), ('file.csv', b'ID\n123'),
    ('file.xlsx.pdf', b'%PDF-1.7'), ('file.xlsx', b'%PDF-1.7'),
    ('file.xls', b'%PDF-1.7'), ('file.xls', b'Word'),
    ('file.xlsx', b'PK\x03\x04 damaged'), ('file.xls', b''),
])
def test_source_upload_invalid_files_never_access_sheets(client, monkeypatch, route, kelas, filename, content):
    get_ws = MagicMock()
    monkeypatch.setattr(app, 'get_worksheet', get_ws)
    response = client.post(route, headers={'Accept': 'application/json'}, data={
        'kelas': kelas, 'file': (io.BytesIO(content), filename)})
    assert response.status_code == 400
    assert response.json['success'] is False
    assert 'data lama tidak diubah' in response.json['message']
    get_ws.assert_not_called()
    app.audit.assert_not_called()
    app.invalidate_sheet_cache.assert_not_called()


@pytest.mark.parametrize('route,kelas', SOURCE_UPLOADS)
@pytest.mark.parametrize('rows', [[], [['ID']], [['ID', '']], [['ID', 'id'], ['A', 'B']],
                                [['ID', 'Status'], [' ', '\t']]])
def test_source_empty_and_invalid_headers_blocked(client, monkeypatch, route, kelas, rows):
    get_ws = MagicMock()
    monkeypatch.setattr(app, 'get_worksheet', get_ws)
    response = client.post(route, headers={'Accept': 'application/json'}, data={
        'kelas': kelas, 'file': (excel_content(rows), 'file.xlsx')})
    assert response.status_code == 400
    get_ws.assert_not_called()
    app.audit.assert_not_called()


@pytest.mark.parametrize('route,kelas', SOURCE_UPLOADS)
def test_source_upload_rejects_cross_target(client, worksheet, route, kelas):
    response = client.post(route, headers={'Accept': 'application/json'}, data={
        'kelas': '05' if kelas == '06' else '06',
        'file': (excel_content([['ID'], ['A']]), 'file.xlsx')})
    assert response.status_code == 400
    worksheet.get_all_values.assert_not_called()
    worksheet.update.assert_not_called()


@pytest.mark.parametrize('route,kelas', SOURCE_UPLOADS)
@pytest.mark.parametrize('case', ['missing_column', 'empty_result', 'bad_reference', 'read_error', 'write_error', 'success'])
def test_source_upload_validates_before_replacement(client, worksheet, route, kelas, case):
    if kelas == '06':
        headers = ['SC Order No/Track ID/CSRM No', 'CRM Order Type', 'Status', 'Workorder']
        row = ['WSA-001', 'CREATE', 'WORKFAIL', '00123']
        prefix, start = [], 'A2:D4'
    else:
        headers = ['SCORDERNO', 'NO KODE', 'STO', 'CRMORDERTYPE']
        row = ['00123', '00007', 'MGL', 'CREATE']
        prefix, start = [['TITLE']], 'A3:D5'
    worksheet.get_all_values.return_value = prefix + [headers] + [['OLD'] * 4 for _ in range(3)]
    file_headers, file_row = headers[:], row[:]
    if case == 'missing_column':
        file_headers, file_row = headers[:3], row[:3]
        if kelas == '05':
            file_headers, file_row = ['Barang', 'Harga'], ['Buku', 1000]
    elif case == 'empty_result':
        if kelas == '06':
            file_row[2] = 'COMPLETED'
        else:
            file_headers, file_row = ['CRMORDERTYPE'], ['CREATE']
    elif case == 'bad_reference':
        worksheet.get_all_values.return_value[len(prefix)] = ['DUPLICATE', 'duplicate']
    elif case == 'read_error':
        worksheet.get_all_values.side_effect = RuntimeError('read failed')
    elif case == 'write_error':
        worksheet.update.side_effect = RuntimeError('write uncertain')
    response = client.post(route, headers={'Accept': 'application/json'}, data={
        'kelas': kelas, 'file': (excel_content([file_headers, file_row]), 'file.xlsx')})
    if case == 'success':
        assert response.status_code == 200, response.json
        assert response.json['success'] is True
        result = worksheet.update.call_args.kwargs
        expected = row if kelas == '06' else row[:3] + ['']
        assert result['values'] == [expected, [''] * 4, [''] * 4]
        assert result['range_name'] == start
        assert result['value_input_option'] == 'RAW'
        app.audit.assert_called_once()
        # AJAX response does not consume the flash; it survives until navigation.
        with client.session_transaction() as session:
            assert any(category == 'success' for category, _ in session.get('_flashes', []))
    else:
        assert response.status_code in (400, 503)
        assert response.json['success'] is False
        app.audit.assert_not_called()
        if case == 'write_error':
            worksheet.update.assert_called_once()
            app.invalidate_sheet_cache.assert_called_once()
            assert 'belum dapat dipastikan' in response.json['message']
        else:
            worksheet.update.assert_not_called()
            app.invalidate_sheet_cache.assert_not_called()
            assert 'data lama tidak diubah' in response.json['message'].lower()
    worksheet.clear.assert_not_called()
    worksheet.add_rows.assert_not_called()
    worksheet.add_cols.assert_not_called()


@pytest.mark.parametrize('position', [0, 2, 4])
@pytest.mark.parametrize('code_header', ['no kode', ' NO   KODE '])
def test_bima_missing_no_kode_preserves_column_and_clears_only_import_tail(
        client, worksheet, position, code_header):
    headers = ['SC Order No/Track ID/CSRM No', 'CRM Order Type', 'Status', 'Workorder']
    source_row = ['WSA-001', 'CREATE', 'WORKFAIL', '00123']
    target_headers = headers[:]
    target_headers.insert(position, code_header)
    old_rows = []
    for code in ['=ROW()', '00007', '=ROW()']:
        row = ['OLD'] * 4
        row.insert(position, code)
        old_rows.append(row)
    worksheet.get_all_values.return_value = [target_headers] + old_rows

    response = client.post('/filter', headers={'Accept': 'application/json'}, data={
        'kelas': '06', 'file': (excel_content([headers, source_row]), 'bima.xlsx')})

    assert response.status_code == 200, response.json
    worksheet.update.assert_called_once()
    update = worksheet.update.call_args.kwargs
    expected_row = source_row[:]
    expected_row.insert(position, None)
    expected_tail = [''] * 4
    expected_tail.insert(position, None)
    assert update['values'] == [expected_row, expected_tail, expected_tail]
    assert update['range_name'] == 'A2:E4'
    assert update['value_input_option'] == 'RAW'
    # Simulasikan kontrak Sheets API: null tidak menulis sel, '' mengosongkan sel.
    applied = [[old if new is None else new for old, new in zip(old_row, new_row)]
               for old_row, new_row in zip(old_rows, update['values'])]
    assert [row[position] for row in applied] == ['=ROW()', '00007', '=ROW()']
    assert applied[0][:position] + applied[0][position + 1:] == source_row
    worksheet.clear.assert_not_called()
    worksheet.batch_clear.assert_not_called()
    app.audit.assert_called_once()


def test_bima_provided_no_kode_is_still_imported(client, worksheet):
    headers = ['SC Order No/Track ID/CSRM No', 'CRM Order Type', 'Status', 'NO KODE']
    row = ['WSA-001', 'MIGRATE', 'WORKFAIL', '00007']
    worksheet.get_all_values.return_value = [headers, ['OLD'] * 4, ['OLD'] * 4]
    response = client.post('/filter', headers={'Accept': 'application/json'}, data={
        'kelas': '06', 'file': (excel_content([headers, row]), 'bima.xlsx')})
    assert response.status_code == 200, response.json
    assert worksheet.update.call_args.kwargs['values'] == [row, [''] * 4]


def test_bima_no_kode_exception_does_not_allow_other_missing_columns(client, worksheet):
    headers = ['SC Order No/Track ID/CSRM No', 'CRM Order Type', 'Status']
    worksheet.get_all_values.return_value = [headers + ['no kode', 'Workorder'], ['OLD'] * 5]
    response = client.post('/filter', headers={'Accept': 'application/json'}, data={
        'kelas': '06', 'file': (excel_content([
            headers, ['WSA-001', 'CREATE', 'WORKFAIL']]), 'bima.xlsx')})
    assert response.status_code == 400
    assert 'Workorder' in response.json['message']
    assert 'no kode' not in response.json['message']
    worksheet.update.assert_not_called()
    app.audit.assert_not_called()


def test_kpro_still_rejects_missing_no_kode(client, worksheet):
    worksheet.get_all_values.return_value = [
        ['TITLE'], ['SCORDERNO', 'NO KODE', 'STO'], ['OLD'] * 3]
    response = client.post('/hapus_kolom', headers={'Accept': 'application/json'}, data={
        'kelas': '05', 'file': (excel_content([
            ['SCORDERNO', 'STO'], ['00123', 'MGL']]), 'kpro.xlsx')})
    assert response.status_code == 400
    assert 'NO KODE' in response.json['message']
    worksheet.update.assert_not_called()
    app.audit.assert_not_called()


def test_source_upload_regular_form_keeps_error_flash(client, worksheet):
    response = client.post('/hapus_kolom', data={
        'kelas': '05', 'file': (io.BytesIO(b'%PDF'), 'report.pdf')}, follow_redirects=True)
    assert 'Format file tidak valid' in response.get_data(as_text=True)
    worksheet.update.assert_not_called()


# Header sintetis untuk menguji kontrak per sheet; bukan definisi kolom KPI produksi.
KPI_TEST_HEADERS = {
    'tti': ['ORDER_ID', 'f_tti'],
    'ffg': ['TICKET_ID', 'f_ffg'],
    'ttr': ['TICKET_ID', 'f_ttr'],
}


def kpi_sheet_rows(kind, rows):
    """Tiru posisi kolom live: XCEK hanya ada pada FFG/TTR, bukan file sumber."""
    if kind == 'tti':
        return rows
    return [['XCEK'] + rows[0]] + [
        ['=ARRAYFORMULA(IFNA(VLOOKUP(I2:I,Result!I:I,1,0),""))' if i == 0 else ''] + row
        for i, row in enumerate(rows[1:])]


def html_kpi_content(rows):
    from html import escape
    header = '<thead><tr>' + ''.join(f'<th>{escape(str(v))}</th>' for v in rows[0]) + '</tr></thead>'
    body = '<tbody>' + ''.join('<tr>' + ''.join(
        f'<td class="str">{escape(str(v))}</td>' for v in row) + '</tr>' for row in rows[1:]) + '</tbody>'
    return ('<style>.str{ mso-number-format:\\@; }</style><table border="1">'
            + header + body + '</table>').encode('utf-8')


@pytest.mark.parametrize('route,kelas', SOURCE_UPLOADS)
def test_source_html_export_is_supported_without_formula_execution(client, worksheet, route, kelas):
    if kelas == '06':
        headers = ['SC Order No/Track ID/CSRM No', 'CRM Order Type', 'Status', 'Workorder']
        row = ['WSA-001', 'CREATE', 'WORKFAIL', '=literal']
        worksheet.get_all_values.return_value = [headers, ['OLD'] * 4]
    else:
        headers, row = ['SCORDERNO', 'STO'], ['000123', '=literal']
        worksheet.get_all_values.return_value = [['TITLE'], headers, ['OLD', 'OLD']]
    response = client.post(route, headers={'Accept': 'application/json'}, data={
        'kelas': kelas, 'file': (io.BytesIO(html_kpi_content([headers, row])), 'report.xls')})
    assert response.status_code == 200, response.json
    assert worksheet.update.call_args.kwargs['values'] == [row]
    assert worksheet.update.call_args.kwargs['value_input_option'] == 'RAW'


@pytest.mark.parametrize('kind', ['tti', 'ffg', 'ttr'])
@pytest.mark.parametrize('prefix', [b'', b'\xef\xbb\xbf \n', b'<!DOCTYPE html>', b'portal-missing-table-close'])
def test_html_xls_export_keeps_text_and_uses_kpi_import_area(client, worksheet, kind, prefix):
    headers = KPI_TEST_HEADERS[kind]
    worksheet.get_all_values.return_value = kpi_sheet_rows(kind, [headers, ['OLD', 'OLD'], ['STALE', 'OLD']])
    rows = [headers[::-1], ['NA', '00123'], ['NOT COMPLY', '00045'],
            ['A & B < C', '=literal-not-a-formula']]
    content = html_kpi_content(rows)
    content = content.removesuffix(b'</table>') if prefix == b'portal-missing-table-close' else prefix + content
    response = client.post(f'/kpi/{kind}/upload', data={
        'file': (io.BytesIO(content), 'download.XLS')})
    assert response.status_code == 302
    written = worksheet.update.call_args.kwargs
    assert written['values'] == [['00123', 'NA'], ['00045', 'NOT COMPLY'],
                                 ['=literal-not-a-formula', 'A & B < C']]
    assert written['range_name'] == ('A2:B4' if kind == 'tti' else 'B2:C4')
    assert written['value_input_option'] == 'RAW'
    worksheet.clear.assert_not_called()
    app.audit.assert_called_once()
    with client.session_transaction() as session:
        assert any(category == 'success' for category, _ in session.get('_flashes', []))


@pytest.mark.parametrize('payload', [
    b'<html><body>No data</body></html>',
    b'<table><tr><th>ID</th></tr><tr><td>1</td></tr>',  # missing table close
    b'<table><tr><th>ID</th></tr><tr><td>1</tr></table>',
    b'<table><tbody><tr><th>ID</th></tr><tr><td>1</tbody>',
    b'<table><tbody><tr><th>ID</th></tr><tr><td>1</td></tbody>',
    b'<table><tr><th>ID</th></tr><tr><td>1</td><td>extra</td></tr></table>',
    b'<table><tr><th colspan="2">ID</th></tr><tr><td>1</td></tr></table>',
    b'<table><tr><th>ID</th></tr><tr><td rowspan="2">1</td></tr></table>',
    b'<table><tr><td><table><tr><td>nested</td></tr></table></td></tr></table>',
    b'<table><tr><td>one</td></tr></table><table><tr><td>two</td></tr></table>',
    b'<script>alert(1)</script><table><tr><td>ID</td></tr></table>',
    b'<table onclick="alert(1)"><tr><td>ID</td></tr></table>',
    b'<iframe src="https://example.invalid"></iframe>',
    b'<img src="https://example.invalid/pixel">',
    b'<?xml version="1.0"?><Workbook/>',
    b'<!DOCTYPE html [<!ENTITY x SYSTEM "file:///secret">]><table></table>',
    b'<table><tr><td>\xff</td></tr></table>',
])
def test_malformed_or_active_html_export_is_rejected_before_sheet_access(client, monkeypatch, payload):
    get_ws = MagicMock()
    monkeypatch.setattr(app, 'get_worksheet', get_ws)
    client.post('/kpi/tti/upload', data={'file': (io.BytesIO(payload), 'download.xls')})
    with client.session_transaction() as session:
        assert any(category == 'error' for category, _ in session.get('_flashes', []))
    get_ws.assert_not_called()
    app.audit.assert_not_called()
    app.invalidate_sheet_cache.assert_not_called()


@pytest.mark.parametrize('kind', ['tti', 'ffg', 'ttr'])
@pytest.mark.parametrize('case', ['wrong_header', 'duplicate', 'empty_header', 'no_data', 'xlsx_extension'])
def test_html_export_still_requires_matching_kpi_schema(client, worksheet, kind, case):
    headers = KPI_TEST_HEADERS[kind]
    worksheet.get_all_values.return_value = kpi_sheet_rows(kind, [headers, ['OLD', 'OLD']])
    rows = [headers[:], ['NEW', 'COMPLY']]
    filename = 'download.xls'
    if case == 'wrong_header':
        rows[0] = ['Barang', 'Harga']
    elif case == 'duplicate':
        rows[0] = ['ID', 'id']
    elif case == 'empty_header':
        rows[0][0] = ''
    elif case == 'no_data':
        rows = rows[:1]
    else:
        filename = 'download.xlsx'
    client.post(f'/kpi/{kind}/upload', data={'file': (io.BytesIO(html_kpi_content(rows)), filename)})
    with client.session_transaction() as session:
        assert any(category == 'error' for category, _ in session.get('_flashes', []))
    worksheet.update.assert_not_called()
    worksheet.clear.assert_not_called()
    worksheet.add_rows.assert_not_called()
    worksheet.add_cols.assert_not_called()
    app.audit.assert_not_called()


@pytest.mark.parametrize('kind', ['tti', 'ffg', 'ttr'])
@pytest.mark.parametrize('case', ['missing', 'extra', 'wrong_kind', 'blank_header',
                                  'duplicate_header', 'numeric_header', 'too_many_columns',
                                  'header_only', 'whitespace_data', 'unrelated_workbook'])
def test_kpi_schema_rejection_preserves_old_data(client, worksheet, kind, case):
    expected = KPI_TEST_HEADERS[kind]
    worksheet.get_all_values.return_value = kpi_sheet_rows(kind, [expected, ['OLD-ID', 'OLD-VALUE']])
    header, row = expected[:], ['NEW-ID', 'NEW-VALUE']
    if case == 'missing':
        header, row = header[:1], row[:1]
    elif case == 'extra':
        header.append('UNRECOGNIZED')
        row.append('new')
    elif case == 'wrong_kind':
        header = KPI_TEST_HEADERS['ffg' if kind != 'ffg' else 'tti']
    elif case == 'blank_header':
        header[1] = None
    elif case == 'duplicate_header':
        header[1] = '  ' + header[0].lower() + '  '
    elif case == 'numeric_header':
        header[1] = 123
    elif case == 'too_many_columns':
        header = [f'COLUMN_{i}' for i in range(34)]
        row = ['value'] * 34
    elif case == 'whitespace_data':
        row = [' ', '\t']
    elif case == 'unrelated_workbook':
        header, row = ['Nama Barang', 'Harga'], ['Buku', 10000]
    rows = [header] if case == 'header_only' else [header, row]
    response = client.post(f'/kpi/{kind}/upload', data={'file': (excel_content(rows), 'report.xlsx')})
    assert response.status_code == 302
    with client.session_transaction() as s:
        assert any(category == 'error' and 'data lama tidak diubah' in message
                   for category, message in s.get('_flashes', []))
    worksheet.update.assert_not_called()
    worksheet.clear.assert_not_called()
    worksheet.add_rows.assert_not_called()
    worksheet.add_cols.assert_not_called()
    app.invalidate_sheet_cache.assert_not_called()
    app.audit.assert_not_called()


@pytest.mark.parametrize('kind', ['tti', 'ffg', 'ttr'])
def test_kpi_accepts_matching_header_and_reorders_without_losing_ids(client, worksheet, kind):
    expected = KPI_TEST_HEADERS[kind]
    worksheet.get_all_values.return_value = kpi_sheet_rows(kind, [expected, ['OLD', 'OLD']])
    rows = [[expected[1].upper(), '  ' + expected[0].lower() + ' '],
            ['COMPLY', '00123'], [' ', ' '], ['NA', '00456']]
    response = client.post(f'/kpi/{kind}/upload', data={'file': (excel_content(rows), 'report.xlsx')})
    assert response.status_code == 302
    worksheet.row_values.assert_called_once_with(1)
    written = worksheet.update.call_args.kwargs['values']
    assert written == [['00123', 'COMPLY'], ['00456', 'NA']]
    assert worksheet.update.call_args.kwargs['range_name'] == ('A2:B3' if kind == 'tti' else 'B2:C3')
    worksheet.clear.assert_not_called()
    app.audit.assert_called_once()


@pytest.mark.parametrize('reference', [[], ['ORDER_ID', ''], ['ORDER_ID', 'order_id'], ['ORDER_ID'] * 34])
def test_kpi_invalid_reference_header_blocks_upload(client, worksheet, reference):
    worksheet.row_values.side_effect = lambda rn: reference
    response = client.post('/kpi/tti/upload', data={'file': (
        excel_content([['ORDER_ID', 'f_tti'], ['123', 'COMPLY']]), 'report.xlsx')})
    assert response.status_code == 302
    with client.session_transaction() as s:
        assert any('Header acuan' in message for _, message in s.get('_flashes', []))
    worksheet.update.assert_not_called()
    worksheet.clear.assert_not_called()
    app.audit.assert_not_called()


def test_kpi_reference_read_failure_preserves_old_sheet(client, worksheet):
    worksheet.row_values.side_effect = RuntimeError('Google unavailable')
    response = client.post('/kpi/tti/upload', data={'file': (
        excel_content([['ORDER_ID', 'f_tti'], ['123', 'COMPLY']]), 'report.xlsx')})
    assert response.status_code == 302
    worksheet.update.assert_not_called()
    worksheet.clear.assert_not_called()
    app.audit.assert_not_called()


@pytest.mark.parametrize('kind', ['tti', 'ffg', 'ttr'])
@pytest.mark.parametrize('new_count', [1, 3, 5])
def test_kpi_replacement_preserves_headers_formulas_and_clears_only_import_area(
        client, worksheet, kind, new_count):
    from copy import deepcopy
    from openpyxl.utils.cell import range_boundaries

    # 33 kolom impor + kolom pendukung kanan. Untuk FFG/TTR ditambah XCEK kiri.
    headers = ['org_1'] + [f'source_{i}' for i in range(2, 33)] + [f'f_{kind}']
    source = [headers] + [[f'OLD-{i}'] * 33 for i in range(3)]
    grid = [row + ['SUPPORT' if i == 0 else '=SUM(1,2)']
            for i, row in enumerate(kpi_sheet_rows(kind, source))]
    original = deepcopy(grid)
    worksheet.row_count = len(grid)
    worksheet.col_count = len(grid[0])
    worksheet.get_all_values.side_effect = lambda: deepcopy(grid)
    worksheet.row_values.side_effect = lambda rn: grid[rn - 1][:]

    def apply_update(*, values, range_name, value_input_option):
        assert value_input_option == 'RAW'
        first_col, first_row, last_col, last_row = range_boundaries(range_name)
        assert first_row == 2
        assert first_col == (1 if kind == 'tti' else 2)
        assert last_col == first_col + 32
        assert len(values) == last_row - first_row + 1
        while len(grid) < last_row:
            grid.append([''] * worksheet.col_count)
        for offset, row in enumerate(values):
            grid[first_row - 1 + offset][first_col - 1:last_col] = row

    worksheet.update.side_effect = apply_update
    # Reversed file headers exercise alignment across the complete 33-column area.
    data = [[f'NEW-{r}-{c}' for c in range(33)] for r in range(new_count)]
    file_rows = [headers[::-1]] + [row[::-1] for row in data]
    # Repeat the exact upload: replace, never append; headers/formulas stay untouched.
    for attempt in range(2):
        response = client.post(f'/kpi/{kind}/upload', data={
            'file': (excel_content(file_rows), 'latest.xlsx')})
        assert response.status_code == 302
        with client.session_transaction() as session:
            flashes = session.pop('_flashes', [])
        assert any(category == 'success' for category, _ in flashes), flashes
        assert not any(category == 'error' for category, _ in flashes)
        start = 0 if kind == 'tti' else 1
        assert grid[0] == original[0]
        assert [row[start:start + 33] for row in grid[1:1 + new_count]] == data
        assert all(row[start:start + 33] == [''] * 33 for row in grid[1 + new_count:])
        assert [row[-1] for row in grid[:len(original)]] == [row[-1] for row in original]
        if kind != 'tti':
            assert [row[0] for row in grid[:len(original)]] == [row[0] for row in original]
        assert worksheet.update.call_count == attempt + 1
    worksheet.clear.assert_not_called()
    worksheet.add_cols.assert_not_called()
    assert app.audit.call_count == 2


@pytest.mark.parametrize('kind', ['ffg', 'ttr'])
@pytest.mark.parametrize('prefix', ['', 'org_1', 'OTHER'])
def test_kpi_missing_xcek_layout_is_rejected_before_write(client, worksheet, kind, prefix):
    headers = KPI_TEST_HEADERS[kind]
    worksheet.get_all_values.return_value = [[prefix] + headers, ['', 'OLD', 'OLD']]
    client.post(f'/kpi/{kind}/upload', data={
        'file': (excel_content([headers, ['NEW', 'COMPLY']]), 'report.xlsx')})
    with client.session_transaction() as session:
        assert any('kolom A harus XCEK' in message for _, message in session.get('_flashes', []))
    worksheet.update.assert_not_called()
    worksheet.add_rows.assert_not_called()
    worksheet.add_cols.assert_not_called()
    app.audit.assert_not_called()


@pytest.mark.parametrize('kind', ['ffg', 'ttr'])
def test_kpi_file_must_not_include_sheet_helper_column(client, worksheet, kind):
    headers = KPI_TEST_HEADERS[kind]
    worksheet.get_all_values.return_value = kpi_sheet_rows(kind, [headers, ['OLD', 'OLD']])
    client.post(f'/kpi/{kind}/upload', data={
        'file': (excel_content([['XCEK'] + headers, ['', 'NEW', 'COMPLY']]), 'report.xlsx')})
    with client.session_transaction() as session:
        assert any('Kolom tidak dikenal: XCEK' in message for _, message in session.get('_flashes', []))
    worksheet.update.assert_not_called()
    app.audit.assert_not_called()


@pytest.mark.parametrize('kind', ['tti', 'ffg', 'ttr'])
def test_failed_kpi_write_invalidates_cache_without_success_audit(client, worksheet, kind):
    headers = KPI_TEST_HEADERS[kind]
    worksheet.get_all_values.return_value = kpi_sheet_rows(kind, [headers, ['OLD', 'OLD']])
    worksheet.update.side_effect = RuntimeError('Google unavailable')
    client.post(f'/kpi/{kind}/upload', data={
        'file': (excel_content([headers, ['NEW', 'COMPLY']]), 'report.xlsx')})
    worksheet.update.assert_called_once()
    worksheet.clear.assert_not_called()
    app.invalidate_sheet_cache.assert_called_once()
    app.audit.assert_not_called()
    with client.session_transaction() as session:
        flashes = session.get('_flashes', [])
        assert any(category == 'error' for category, _ in flashes)
        assert not any(category == 'success' for category, _ in flashes)


@pytest.mark.parametrize('failure', [None, 'execute', 'commit'])
def test_cache_write_reports_committed_result(monkeypatch, capsys, failure):
    cursor = MagicMock()
    if failure == 'execute':
        cursor.execute.side_effect = RuntimeError('packet too large')

    @contextmanager
    def cache_db():
        yield MagicMock(), cursor
        if failure == 'commit':
            raise RuntimeError('commit failed')

    monkeypatch.setattr(app, 'db_cursor', cache_db)
    assert app._write_mysql_cache('sp', 'TEST SHEET', [['data']]) is (failure is None)
    output = capsys.readouterr().out
    if failure:
        assert 'Gagal tulis cache TEST SHEET:' in output
    else:
        assert 'Gagal' not in output


@pytest.mark.parametrize('cache_saved', [True, False])
def test_fresh_sheet_remains_available_when_cache_write_fails(monkeypatch, cache_saved):
    values = [['ORDER_ID'], ['A']]
    gs = MagicMock()
    gs.open_by_key.return_value.worksheet.return_value.get_all_values.return_value = values
    monkeypatch.setattr(app, 'gs_client', lambda: gs)
    writer = MagicMock(return_value=cache_saved)
    monkeypatch.setattr(app, '_write_mysql_cache', writer)
    assert app.get_sheet_values('sp', 'sheet', force_refresh=True) == values
    assert app._sheet_cache[('sp', 'sheet')]['data'] == values
    writer.assert_called_once_with('sp', 'sheet', values)


def test_prefetch_distinguishes_fetch_success_and_cache_success(monkeypatch, capsys):
    monkeypatch.setattr(app, 'PREFETCH_SHEETS', [('test', name) for name in ('a', 'b', 'c', 'd')])
    monkeypatch.setattr(app, 'SPREADSHEET_IDS', {'test': 'sp'})
    monkeypatch.setattr(app, 'SHEET_NAMES', {'test': {'a': 'SAVED', 'b': 'NOT SAVED', 'c': 'UNREADABLE'}})

    def fetch(sp, sheet):
        assert sp == 'sp'
        if sheet == 'UNREADABLE':
            raise RuntimeError('read failed')
        return [['data']], sheet == 'SAVED'

    monkeypatch.setattr(app, '_fetch_sheet_values', fetch)
    app._run_prefetch({'items': []}, lambda: None)
    output = capsys.readouterr().out
    assert 'OK SAVED' in output
    assert 'PERINGATAN NOT SAVED' in output
    assert 'Gagal mengambil UNREADABLE' in output
    assert 'Dilewati d' in output
    assert 'sumber terbaca 2/4; cache MySQL tersimpan 1/4' in output


def test_prefetch_reports_all_caches_saved(monkeypatch, capsys):
    monkeypatch.setattr(app, '_fetch_sheet_values', lambda *_: ([['data']], True))
    app._run_prefetch({'items': []}, lambda: None)
    output = capsys.readouterr().out
    assert 'sumber terbaca 5/5; cache MySQL tersimpan 5/5' in output


def test_cache_force_refresh_never_falls_back(monkeypatch):
    monkeypatch.setattr(app, '_read_mysql_cache', lambda *a, **kw: [['stale']])
    app._sheet_cache[('sp', 'sheet')] = {'ts': app.time.time(), 'data': [['stale']]}
    with pytest.raises(AssertionError, match='Live service'):
        app.get_sheet_values('sp', 'sheet', force_refresh=True)


def test_prefetch_records_progress_and_releases_global_lock(monkeypatch, isolate):
    isolate.fetchone.return_value = {'acquired': 1}
    monkeypatch.setattr(app, '_fetch_sheet_values', lambda *_: ([['data']], True))
    saved = []
    monkeypatch.setattr(app, '_save_prefetch_status', lambda conn, cur, state:
                        saved.append(app.json.loads(app.json.dumps(state))))
    app._prefetch_job(trigger='manual')
    assert saved[0]['state'] == 'running'
    assert saved[0]['trigger'] == 'manual'
    assert saved[0]['items'] == []
    assert saved[-1]['state'] == 'complete'
    assert saved[-1]['cached'] == 5
    assert len(saved[-1]['items']) == 5
    assert saved[-1]['finished_at']
    assert 'RELEASE_LOCK' in isolate.execute.call_args.args[0]


def test_prefetch_duplicate_run_does_not_fetch_or_replace_status(monkeypatch, isolate):
    isolate.fetchone.return_value = {'acquired': 0}
    fetch = MagicMock()
    save = MagicMock()
    monkeypatch.setattr(app, '_fetch_sheet_values', fetch)
    monkeypatch.setattr(app, '_save_prefetch_status', save)
    app._prefetch_job()
    fetch.assert_not_called()
    save.assert_not_called()


def test_prefetch_status_failure_releases_lock(monkeypatch, isolate):
    isolate.fetchone.return_value = {'acquired': 1}
    save = MagicMock(side_effect=RuntimeError('status database failed'))
    monkeypatch.setattr(app, '_save_prefetch_status', save)
    app._prefetch_job()
    assert 'RELEASE_LOCK' in isolate.execute.call_args.args[0]


@pytest.mark.parametrize('final_state', ['running', 'complete'])
def test_prefetch_detects_interruption_without_misreporting_finished_run(isolate, final_state):
    first = {'run_id': 'test', 'state': 'running', 'items': []}
    final = dict(first, state=final_state)
    isolate.fetchone.side_effect = [
        {'data_json': app.json.dumps(first)}, {'owner': None}, {'data_json': app.json.dumps(final)}]
    state = app._read_prefetch_status()
    assert state['state'] == ('interrupted' if final_state == 'running' else 'complete')


def test_manual_cache_refresh_reuses_running_job(client, monkeypatch):
    monkeypatch.setattr(app, '_read_prefetch_status', lambda: {'state': 'running', 'run_id': 'current'})
    thread = MagicMock()
    monkeypatch.setattr('threading.Thread', thread)
    response = client.post('/api/cache_refresh', json={})
    assert response.status_code == 200
    assert response.json['status'] == 'accepted'
    assert response.json['run_id'] == 'current'
    thread.assert_not_called()


def test_manual_cache_refresh_returns_previous_run_not_false_success(client, monkeypatch):
    monkeypatch.setattr(app, '_read_prefetch_status', lambda: {'state': 'complete', 'run_id': 'old'})
    monkeypatch.setattr('threading.Thread', MagicMock())
    response = client.post('/api/cache_refresh', json={})
    assert response.json['status'] == 'accepted'
    assert response.json['previous_run_id'] == 'old'


def test_cache_status_database_failure_returns_service_error(client, monkeypatch):
    monkeypatch.setattr(app, '_read_prefetch_status', MagicMock(side_effect=RuntimeError('private detail')))
    response = client.get('/api/cache_status')
    assert response.status_code == 503
    assert 'private detail' not in response.get_data(as_text=True)


def test_cache_status_exposes_progress_and_actual_scheduler(client, monkeypatch):
    state = {'state': 'running', 'run_id': 'current', 'items': []}
    monkeypatch.setattr(app, '_read_prefetch_status', lambda: state)
    scheduler = MagicMock(running=True)
    scheduler.get_job.return_value.next_run_time = datetime(2026, 9, 21, 17, 0)
    monkeypatch.setattr(app, '_cache_scheduler', scheduler)
    response = client.get('/api/cache_status')
    assert response.status_code == 200
    assert response.json['refresh'] == state
    automatic = response.json['automatic'].copy()
    assert datetime.fromisoformat(automatic.pop('server_time')).tzinfo is not None
    assert automatic == {
        'running': True, 'interval_seconds': 300, 'next_run_at': '2026-09-21T17:00:00'}


def test_scheduler_prefetches_at_startup_and_every_five_minutes(monkeypatch):
    scheduler = MagicMock()
    thread = MagicMock()
    monkeypatch.setattr(app, '_ensure_cache_table', lambda: True)
    monkeypatch.setattr(app, 'BackgroundScheduler', lambda **kw: scheduler)
    monkeypatch.setattr(app.atexit, 'register', MagicMock())
    monkeypatch.setattr(app, '_cache_scheduler', None)
    monkeypatch.setattr('threading.Thread', thread)
    app._start_scheduler()
    thread.assert_called_once_with(target=app._prefetch_job, daemon=True)
    thread.return_value.start.assert_called_once()
    added = scheduler.add_job.call_args.kwargs
    assert added['func'] is app._prefetch_job
    assert added['trigger'].interval.total_seconds() == 300
    scheduler.start.assert_called_once()
    assert app._cache_scheduler is scheduler


def test_cache_uses_shared_value_not_old_worker_memory(monkeypatch):
    monkeypatch.setattr(app, '_read_mysql_cache', lambda *a, **kw: [['fresh']])
    app._sheet_cache[('sp', 'sheet')] = {'ts': app.time.time(), 'data': [['old']]}
    assert app.get_sheet_values('sp', 'sheet') == [['fresh']]


def test_stale_cache_is_visible(monkeypatch):
    monkeypatch.setattr(app, '_read_mysql_cache', lambda *a, **kw: None)
    app._sheet_cache[('sp', 'sheet')] = {'ts': app.time.time(), 'data': [['stale']]}
    with app.flask_app.test_request_context('/'):
        assert app.get_sheet_values('sp', 'sheet') == [['stale']]
        assert app.g.stale_sheets == {'sheet'}


def test_unsc_filtered_rows_keep_identity(client, monkeypatch, worksheet):
    data = [['title'], HEADERS, sheet_row('A', 'KBM'), sheet_row('B', 'MGL')]
    monkeypatch.setattr(app, 'get_sheet_values', lambda *_: data)
    assert client.get('/unsc_data?sto=MGL').json['sheet_rows'] == [4]
    assert 'data-row-num="4"' in client.get('/unsc?sto=MGL').get_data(as_text=True)


def test_all_jinja_templates_compile():
    for name in app.flask_app.jinja_env.list_templates():
        app.flask_app.jinja_env.get_template(name)


def test_password_reset_invalidates_session(client, isolate):
    isolate.fetchone.return_value = dict(USER, password='changed-hash')
    assert client.get('/kendala_data').status_code == 401


def test_presence_page_name_respects_specific_kpi_and_mount():
    with app.flask_app.test_request_context('/heartbeat', environ_overrides={'SCRIPT_NAME': '/api'}):
        assert app._page_name('/api/kpi/tti') == 'KPI — TTI'
        assert app._page_name('/api/online') == 'User Online'


def test_schema_contains_all_support_tables():
    schema = (Path(app.ROOT_DIR) / 'user_db.sql').read_text(encoding='utf-8')
    tables = re.findall(r'CREATE TABLE IF NOT EXISTS (\w+) \(', schema)
    expected = {'users', 'edit_locks', 'audit_log', 'sync_new_rows', 'login_attempts',
                'user_sessions', 'sheet_cache', 'watchlist', 'announcements'}
    assert set(tables) == expected
    assert len(tables) == len(expected)


def test_single_sql_installer_has_no_seed_or_destructive_statements():
    assert sorted(p.name for p in Path(app.ROOT_DIR).glob('*.sql')) == ['user_db.sql']
    schema = (Path(app.ROOT_DIR) / 'user_db.sql').read_text(encoding='utf-8')
    sql = re.sub(r'--[^\n]*', '', schema)
    statements = [s.strip() for s in sql.split(';') if s.strip()]
    assert len(statements) == 9
    assert all(s.startswith('CREATE TABLE IF NOT EXISTS ') for s in statements)
    assert not re.search(r'\b(INSERT|REPLACE|DELETE|DROP|TRUNCATE|ALTER|USE)\b', sql, re.I)


def test_sql_installer_matches_current_sync_lock_and_login_columns():
    schema = (Path(app.ROOT_DIR) / 'user_db.sql').read_text(encoding='utf-8')
    tables = dict(re.findall(r'CREATE TABLE IF NOT EXISTS (\w+) \(([\s\S]*?)\) ENGINE=', schema))
    assert 'sync_batch_id VARCHAR(50) NOT NULL' in tables['sync_new_rows']
    assert 'sheet_name VARCHAR(100) NOT NULL' in tables['sync_new_rows']
    assert 'UNIQUE KEY uniq_order_batch (order_id, sync_batch_id)' in tables['sync_new_rows']
    assert 'timestamp TIMESTAMP' in tables['login_attempts']
    assert 'attempted_at' not in tables['login_attempts']
    assert 'INDEX idx_locked_at (locked_at)' in tables['edit_locks']
    assert 'expires_at' not in tables['edit_locks']
    assert "role ENUM('admin', 'operator', 'viewer')" in tables['users']


def test_installation_guides_point_to_single_installer():
    root = Path(app.ROOT_DIR)
    for guide in (root / 'notes.txt', root.parent / 'README.md'):
        text = guide.read_text(encoding='utf-8')
        assert 'user_db.sql' in text
        assert 'schema.sql' not in text
        assert 'watchlist_announcement.sql' not in text


SYNC_HEADERS = ['NO', 'WONUM', 'ORDER_ID', 'DEVICE_ID', 'STO', 'DATEL',
                'STATUS_RESUME', 'SUBERRORCODE', 'ENGINEERMEMO', 'ORDER_DATE',
                'LAST_UPDATED_DATE', 'FEEDBACK ASO', 'CEK DB UNSC']
BIMA_HEADERS = ['Workorder', 'HELPER ORDER ID', 'SC Order No/Track ID/CSRM No',
                'Workzone', 'Status', 'SUBERRORCODE', 'ENGINEERMEMO', 'TGL_CREATE', 'TGL_UPDATE_STATUS']


@pytest.fixture
def sync_sheets(monkeypatch):
    sheets = {key: MagicMock() for key in ('bima_fresh', 'kendalamaster', 'unsc')}
    sheets['bima_fresh'].get_all_values.return_value = [BIMA_HEADERS, ['W1', 'A', 'D1', 'MGL', 'WORKFAIL', '', '', '', '']]
    sheets['kendalamaster'].get_all_values.return_value = [['title'], SYNC_HEADERS]
    sheets['kendalamaster'].row_count = 100
    sheets['unsc'].get_all_values.return_value = [['title'], ['NO'] + SYNC_HEADERS[2:10]]
    sheets['unsc'].row_count = 100
    ss = MagicMock()
    ss.worksheet.side_effect = lambda name: next(ws for key, ws in sheets.items() if app.SHEET_NAMES['kendala'][key] == name)
    client = MagicMock()
    client.open_by_key.return_value = ss
    monkeypatch.setattr(app, 'gs_client', lambda: client)
    monkeypatch.setattr(app, 'save_last_sync_time', MagicMock())
    return sheets


def test_sync_rejects_duplicate_source_before_any_write(sync_sheets):
    source = sync_sheets['bima_fresh'].get_all_values.return_value
    source.append(source[1][:])
    result = app.sync_bima_to_kendala()
    assert result['status'] == 'error' and 'duplikat' in result['message']
    sync_sheets['kendalamaster'].batch_update.assert_not_called()


def test_sync_rejects_wrong_layout_before_any_write(sync_sheets):
    sync_sheets['kendalamaster'].get_all_values.return_value[1] = ['ORDER_ID', 'NOTES ASO']
    assert app.sync_bima_to_kendala()['status'] == 'error'
    sync_sheets['kendalamaster'].batch_update.assert_not_called()


def test_sync_combines_updates_and_appends(sync_sheets):
    master = sync_sheets['kendalamaster']
    master.get_all_values.return_value.append(['', 'old', 'A'] + [''] * 8 + ['keep', ''])
    sync_sheets['bima_fresh'].get_all_values.return_value.append(['W2', 'B', 'D2', 'MGL', 'WORKFAIL'])
    result = app.sync_bima_to_kendala()
    assert result['status'] == 'success'
    assert result['updates'] == 1 and result['appends'] == 1
    master.batch_update.assert_called_once()
    ranges = [item['range'] for item in master.batch_update.call_args.args[0]]
    assert ranges == ['B3:K3', 'A4:K4']


def test_unsc_transfer_is_idempotent_even_with_stale_marker(sync_sheets):
    master = sync_sheets['kendalamaster']
    master.get_all_values.return_value.append(['', 'W1', 'A', 'D1', 'MGL', 'MAGELANG',
                                             'WORKFAIL', '', '', '', '', 'VERIFIKASI UNSC', 'BELUM ADA'])
    destination = sync_sheets['unsc']
    destination.get_all_values.return_value.append(['', 'A'])
    result = app.move_kendala_to_unsc()
    assert result['status'] == 'success'
    destination.update.assert_not_called()


def test_unsc_transfer_writes_only_missing_ids(sync_sheets):
    master = sync_sheets['kendalamaster']
    row = ['', 'W1', 'A', 'D1', 'MGL', 'MAGELANG', 'WORKFAIL', '', '', '', '', 'VERIVIKASI UNSC', 'BELUM ADA']
    master.get_all_values.return_value.extend([row, row[:]])
    assert app.move_kendala_to_unsc()['status'] == 'success'
    values = sync_sheets['unsc'].update.call_args.kwargs['values']
    assert len(values) == 1 and values[0][1] == 'A'


def test_watchlist_cleanup_reads_live_header_row_two(client, monkeypatch, isolate):
    read = MagicMock(return_value=[['title'], ['ORDER_ID', 'STATUS_RESUME'], ['A', 'CLOSE'], ['B', 'WORKFAIL']])
    monkeypatch.setattr(app, 'get_sheet_values', read)
    response = client.post('/api/watchlist/auto_clean', json={})
    assert response.status_code == 200
    assert read.call_args.kwargs['force_refresh'] is True
    deletes = [c for c in isolate.execute.call_args_list if 'DELETE FROM watchlist' in c.args[0]]
    assert deletes[0].args[1] == ('A',)


@pytest.mark.parametrize('path', ['/kendala_master', '/unsc', '/kpi/tti', '/recap', '/dashboard', '/online', '/audit_log'])
def test_rendered_inline_javascript_parses(client, worksheet, monkeypatch, path):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for rendered JavaScript syntax checks')
    monkeypatch.setattr(app, 'get_sheet_values', lambda *_: [['title'], HEADERS, sheet_row()])
    worksheet.get.return_value = []
    response = client.get(path)
    assert response.status_code == 200
    scripts = re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>', response.get_data(as_text=True), re.S)
    result = subprocess.run([node, '--check'], input='\n'.join(scripts), text=True,
                            encoding='utf-8', capture_output=True)
    assert result.returncode == 0, result.stderr


def test_not_comply_badge_is_not_green(client, monkeypatch):
    monkeypatch.setattr(app, 'get_sheet_values', lambda *_: [['result'], ['NOT COMPLY']])
    html = client.get('/kpi/tti').get_data(as_text=True)
    assert '<span class="kpi-badge-nc">NOT COMPLY</span>' in html


def test_dashboard_failure_is_not_silently_reported_as_zero(client, monkeypatch):
    def fail(*args):
        raise RuntimeError('Unavailable')
    monkeypatch.setattr(app, 'get_sheet_values', fail)
    assert client.get('/dashboard_stats').json['error']
    assert 'Data dashboard belum dapat dimuat' in client.get('/dashboard').get_data(as_text=True)


def test_empty_kendala_with_header_is_valid(client, worksheet, monkeypatch):
    monkeypatch.setattr(app, 'get_sheet_values', lambda *_: [['title'], HEADERS])
    response = client.get('/kendala_data')
    assert response.status_code == 200, response.json
    assert response.json['data'] == []
    assert client.get('/kendala_master').status_code == 200


def test_csrf_is_enforced_on_write(client, worksheet):
    app.flask_app.config['WTF_CSRF_ENABLED'] = True
    try:
        response = client.post('/update_kendala_row', json=payload(worksheet))
        assert response.status_code == 400
        worksheet.update_cells.assert_not_called()
    finally:
        app.flask_app.config['WTF_CSRF_ENABLED'] = False


def test_mounted_routes_and_script_root(client, worksheet, monkeypatch):
    monkeypatch.setattr(app, 'get_sheet_values', lambda *_: [['title'], HEADERS, sheet_row()])
    original = app.flask_app.wsgi_app
    try:
        server = importlib.import_module('server')
        app.flask_app.wsgi_app = server.PathPrefixMiddleware(original, '/api')
        response = client.get('/api/kendala_master')
        assert response.status_code == 200
        assert '<meta name="app-root" content="/api">' in response.get_data(as_text=True)
        assert client.get('/api/kendala_data').json['sheet_rows'] == [3]
    finally:
        app.flask_app.wsgi_app = original


def test_named_lock_releases_even_if_google_write_fails(isolate):
    isolate.fetchone.return_value = {'acquired': 1}
    with pytest.raises(RuntimeError, match='Google failed'):
        with REAL_SHEET_GUARD('sheet-id'):
            raise RuntimeError('Google failed')
    queries = [call.args[0] for call in isolate.execute.call_args_list]
    assert queries == ['SELECT GET_LOCK(%s, 10) AS acquired', 'SELECT RELEASE_LOCK(%s)']


@pytest.mark.parametrize('acquired', [0, None])
def test_named_lock_timeout_or_failure_never_enters_writer(isolate, acquired):
    isolate.fetchone.return_value = {'acquired': acquired}
    with pytest.raises(RuntimeError, match='Proses lain'):
        with REAL_SHEET_GUARD('sheet-id'):
            pytest.fail('Writer must not execute without lock')


@pytest.mark.parametrize('role', ['admin', 'operator', 'viewer'])
def test_change_password_form_keeps_contract_and_accessible_help(client, isolate, role):
    isolate.fetchone.return_value = dict(USER, role=role)
    response = client.get('/ganti_password')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Masukkan password lama dan tentukan password baru.' in html
    assert 'Keamanan akun Anda adalah prioritas kami' not in html
    assert 'method="POST" action="/ganti_password"' in html
    assert 'name="csrf_token"' in html
    assert 'name="old_password"' in html and 'name="new_password"' in html
    assert 'minlength="6"' in html
    assert 'aria-describedby="new-password-help"' in html
    assert 'id="new-password-help">Gunakan minimal 6 karakter.' in html
    assert 'aria-label="Tampilkan password lama"' in html
    assert 'aria-label="Tampilkan password baru"' in html


@pytest.mark.parametrize('role', ['admin', 'operator', 'viewer'])
def test_password_success_stays_on_form_with_single_notice(client, isolate, monkeypatch, role):
    user = dict(USER, role=role)
    isolate.fetchone.side_effect = lambda: dict(user)
    monkeypatch.setattr(app, 'generate_password_hash', lambda _: 'test-updated-hash')

    def execute(query, params=None):
        if query.startswith('UPDATE users SET password='):
            user['password'] = params[0]

    isolate.execute.side_effect = execute
    response = client.post('/ganti_password', data={
        'old_password': USER['password'], 'new_password': 'new-secret-123',
    })
    assert response.status_code == 302
    assert response.headers['Location'] == '/ganti_password'
    response = client.get(response.headers['Location'])
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.count('Password berhasil diubah.') == 1
    assert 'Gunakan password baru saat login berikutnya.' in html
    assert html.index('class="gp-body"') < html.index('data-testid="flash-success"') < html.index('<form')
    assert 'role="status"' in html
    assert 'new-secret-123' not in html
    for field in ('old_password', 'new_password'):
        input_tag = re.search(r'<input\b[^>]*id="' + field + r'"[^>]*>', html).group()
        assert 'value=' not in input_tag
    with client.session_transaction() as session:
        assert session['user']['username'] == USER['username']
        assert session['auth_stamp'] == app.hashlib.sha256(user['password'].encode()).hexdigest()
    app.audit.assert_called_once_with('change_password')
    assert 'Password berhasil diubah.' not in client.get('/ganti_password').get_data(as_text=True)


@pytest.mark.parametrize('old_password,new_password,message', [
    ('wrong-password', 'new-secret-123', 'Password lama salah.'),
    (USER['password'], '123', 'Password baru minimal 6 karakter.'),
])
def test_password_failure_shows_error_in_card_without_success(client, isolate, old_password, new_password, message):
    response = client.post('/ganti_password', data={
        'old_password': old_password, 'new_password': new_password,
    }, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert html.count(message) == 1
    assert html.index('class="gp-body"') < html.index('data-testid="flash-error"') < html.index('<form')
    assert 'role="alert"' in html
    assert 'Password berhasil diubah.' not in html
    assert not any('UPDATE users SET password=' in call.args[0] for call in isolate.execute.call_args_list)
    app.audit.assert_not_called()
