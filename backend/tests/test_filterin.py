"""
FilterIN Backend Tests
Tests for authentication, CSRF, rate limiting, dashboard, kendala master, lock/unlock, audit log, etc.
Note: Tests use Referer header to bypass Cloudflare protection
"""
import pytest
import requests
import os
import re
import time
from bs4 import BeautifulSoup

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials from test_credentials.md
ADMIN_USER = 'dava234'
ADMIN_PASS = 'dava123'
OPERATOR_USER = 'wadaw'
OPERATOR_PASS = 'wadaw123'

# Common headers to bypass Cloudflare
COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}


def get_session_with_headers():
    """Create a session with proper headers"""
    session = requests.Session()
    session.headers.update(COMMON_HEADERS)
    return session


def login_session(username, password):
    """Create an authenticated session"""
    session = get_session_with_headers()
    
    # Get login page to extract CSRF token
    login_page = session.get(f"{BASE_URL}/api/login")
    if login_page.status_code != 200:
        return None
    
    soup = BeautifulSoup(login_page.text, 'html.parser')
    csrf_input = soup.find('input', {'name': 'csrf_token'})
    if not csrf_input:
        return None
    csrf_token = csrf_input.get('value')
    
    # Add Referer header for POST
    session.headers['Referer'] = f"{BASE_URL}/api/login"
    
    # Submit login
    response = session.post(
        f"{BASE_URL}/api/login",
        data={
            'username': username,
            'password': password,
            'csrf_token': csrf_token
        },
        allow_redirects=True
    )
    
    # Get fresh CSRF token from dashboard/any authenticated page
    dashboard = session.get(f"{BASE_URL}/api/dashboard")
    soup = BeautifulSoup(dashboard.text, 'html.parser')
    meta = soup.find('meta', {'name': 'csrf-token'})
    if meta:
        session.csrf_token = meta.get('content')
    else:
        session.csrf_token = csrf_token
    
    return session


class TestHealthAndBasics:
    """Basic health check and connectivity tests"""
    
    def test_health_endpoint(self):
        """Health endpoint should return 200 with status ok"""
        session = get_session_with_headers()
        response = session.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'
        assert data['service'] == 'FilterIN'
        print(f"Health check passed: {data}")
    
    def test_login_page_loads(self):
        """Login page should load and contain CSRF token"""
        session = get_session_with_headers()
        response = session.get(f"{BASE_URL}/api/login")
        assert response.status_code == 200
        assert 'csrf_token' in response.text or 'csrf-token' in response.text
        print("Login page loads with CSRF token")


class TestAuthentication:
    """Authentication flow tests"""
    
    def test_login_success_admin(self):
        """Login with valid admin credentials should succeed"""
        session = get_session_with_headers()
        
        # Get login page to extract CSRF token
        login_page = session.get(f"{BASE_URL}/api/login")
        assert login_page.status_code == 200
        
        # Extract CSRF token from form
        soup = BeautifulSoup(login_page.text, 'html.parser')
        csrf_input = soup.find('input', {'name': 'csrf_token'})
        assert csrf_input is not None, "CSRF token input not found in login form"
        csrf_token = csrf_input.get('value')
        
        # Add Referer header
        session.headers['Referer'] = f"{BASE_URL}/api/login"
        
        # Submit login
        response = session.post(
            f"{BASE_URL}/api/login",
            data={
                'username': ADMIN_USER,
                'password': ADMIN_PASS,
                'csrf_token': csrf_token
            },
            allow_redirects=False
        )
        
        # Should redirect to dashboard on success
        assert response.status_code in [302, 303], f"Expected redirect, got {response.status_code}"
        location = response.headers.get('Location', '')
        assert 'dashboard' in location or response.status_code == 302
        print(f"Admin login successful, redirected to: {location}")
    
    def test_login_failure_wrong_password(self):
        """Login with wrong password should fail"""
        session = get_session_with_headers()
        
        # Get CSRF token
        login_page = session.get(f"{BASE_URL}/api/login")
        soup = BeautifulSoup(login_page.text, 'html.parser')
        csrf_input = soup.find('input', {'name': 'csrf_token'})
        csrf_token = csrf_input.get('value')
        
        # Add Referer header
        session.headers['Referer'] = f"{BASE_URL}/api/login"
        
        # Submit with wrong password
        response = session.post(
            f"{BASE_URL}/api/login",
            data={
                'username': ADMIN_USER,
                'password': 'wrongpassword',
                'csrf_token': csrf_token
            },
            allow_redirects=True
        )
        
        # Should stay on login page with error
        assert 'salah' in response.text.lower() or 'error' in response.text.lower() or 'Login' in response.text
        print("Login with wrong password correctly rejected")
    
    def test_login_without_csrf_fails(self):
        """POST to login without CSRF token should fail"""
        session = get_session_with_headers()
        
        # Get login page first to establish session
        session.get(f"{BASE_URL}/api/login")
        session.headers['Referer'] = f"{BASE_URL}/api/login"
        
        # Try to login without CSRF token
        response = session.post(
            f"{BASE_URL}/api/login",
            data={
                'username': ADMIN_USER,
                'password': ADMIN_PASS
            },
            allow_redirects=True
        )
        
        # Should fail with 400 or show error
        assert response.status_code == 400 or 'csrf' in response.text.lower() or 'token' in response.text.lower()
        print("Login without CSRF token correctly rejected")


class TestDashboard:
    """Dashboard tests"""
    
    def test_dashboard_requires_auth(self):
        """Dashboard should redirect to login if not authenticated"""
        session = get_session_with_headers()
        response = session.get(f"{BASE_URL}/api/dashboard", allow_redirects=False)
        assert response.status_code in [302, 303]
        location = response.headers.get('Location', '')
        assert 'login' in location
        print("Dashboard correctly requires authentication")
    
    def test_dashboard_loads_when_authenticated(self):
        """Dashboard should load when authenticated"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        response = session.get(f"{BASE_URL}/api/dashboard")
        assert response.status_code == 200
        assert 'Dashboard' in response.text or 'dashboard' in response.text.lower() or 'Selamat' in response.text
        print("Dashboard loads successfully when authenticated")
    
    def test_dashboard_stats_api(self):
        """Dashboard stats API should return JSON with stats"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        response = session.get(f"{BASE_URL}/api/dashboard_stats")
        assert response.status_code == 200
        data = response.json()
        
        # Check expected fields
        assert 'total' in data
        assert 'done' in data
        assert 'pending' in data
        assert 'unsc' in data
        assert 'active' in data
        assert 'inactive' in data
        print(f"Dashboard stats: {data}")
    
    def test_dashboard_stats_requires_auth(self):
        """Dashboard stats API should require authentication"""
        session = get_session_with_headers()
        response = session.get(f"{BASE_URL}/api/dashboard_stats")
        assert response.status_code == 401
        print("Dashboard stats API correctly requires authentication")


class TestKendalaMaster:
    """Kendala Master page tests"""
    
    def test_kendala_master_loads(self):
        """Kendala Master page should load"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        response = session.get(f"{BASE_URL}/api/kendala_master")
        assert response.status_code == 200
        assert 'KENDALA' in response.text.upper() or 'kendala' in response.text.lower()
        print("Kendala Master page loads successfully")
    
    def test_kendala_master_has_quick_edit_modal(self):
        """Kendala Master should have Quick Edit Modal elements"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        response = session.get(f"{BASE_URL}/api/kendala_master")
        assert response.status_code == 200
        # Check for Quick Edit related elements
        assert 'openQuickEdit' in response.text or 'qe-modal' in response.text or 'Quick Edit' in response.text or 'Edit Cepat' in response.text
        print("Quick Edit Modal elements found in Kendala Master")
    
    def test_kendala_row_api(self):
        """Kendala row API should return row data"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        # Try to get row 3 (first data row after headers)
        response = session.get(f"{BASE_URL}/api/kendala_row/3")
        
        if response.status_code == 200:
            data = response.json()
            assert 'row' in data
            assert 'row_num' in data
            print(f"Kendala row API returned data for row 3")
        elif response.status_code == 404:
            print("Row 3 not found - this is acceptable if sheet has less data")
        else:
            pytest.fail(f"Unexpected status code: {response.status_code}")


class TestLockUnlock:
    """Row lock/unlock API tests"""
    
    def test_lock_api(self):
        """Lock API should acquire lock on a row"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        test_row_key = 'TEST_ORDER_123'
        
        session.headers['Referer'] = f"{BASE_URL}/api/kendala_master"
        
        response = session.post(
            f"{BASE_URL}/api/lock",
            json={
                'sheet_name': 'DB KENDALA (MASTER)',
                'row_key': test_row_key
            },
            headers={'X-CSRFToken': session.csrf_token}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert 'ok' in data
        assert 'locked_by' in data
        print(f"Lock API response: {data}")
        
        # Cleanup - unlock
        session.post(
            f"{BASE_URL}/api/unlock",
            json={
                'sheet_name': 'DB KENDALA (MASTER)',
                'row_key': test_row_key
            },
            headers={'X-CSRFToken': session.csrf_token}
        )
    
    def test_unlock_api(self):
        """Unlock API should release lock"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        test_row_key = 'TEST_ORDER_456'
        session.headers['Referer'] = f"{BASE_URL}/api/kendala_master"
        
        # First acquire lock
        session.post(
            f"{BASE_URL}/api/lock",
            json={
                'sheet_name': 'DB KENDALA (MASTER)',
                'row_key': test_row_key
            },
            headers={'X-CSRFToken': session.csrf_token}
        )
        
        # Then unlock
        response = session.post(
            f"{BASE_URL}/api/unlock",
            json={
                'sheet_name': 'DB KENDALA (MASTER)',
                'row_key': test_row_key
            },
            headers={'X-CSRFToken': session.csrf_token}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data.get('ok') == True
        print(f"Unlock API response: {data}")
    
    def test_lock_requires_auth(self):
        """Lock API should require authentication"""
        session = get_session_with_headers()
        session.headers['Referer'] = f"{BASE_URL}/api/kendala_master"
        
        response = session.post(
            f"{BASE_URL}/api/lock",
            json={
                'sheet_name': 'DB KENDALA (MASTER)',
                'row_key': 'TEST'
            }
        )
        assert response.status_code == 401
        print("Lock API correctly requires authentication")


class TestSyncAndMove:
    """Sync BIMA and Move to UNSC tests"""
    
    def test_sync_bima_requires_auth(self):
        """Sync BIMA API should require authentication"""
        session = get_session_with_headers()
        session.headers['Referer'] = f"{BASE_URL}/api/kendala_master"
        response = session.post(f"{BASE_URL}/api/sync-bima")
        assert response.status_code == 401
        print("Sync BIMA API correctly requires authentication")
    
    def test_move_to_unsc_requires_auth(self):
        """Move to UNSC API should require authentication"""
        session = get_session_with_headers()
        session.headers['Referer'] = f"{BASE_URL}/api/kendala_master"
        response = session.post(f"{BASE_URL}/api/move-to-unsc")
        assert response.status_code == 401
        print("Move to UNSC API correctly requires authentication")
    
    # Note: Not actually calling sync-bima or move-to-unsc as they modify Google Sheets
    # Just testing that endpoints exist and require auth


class TestMarkNewSeen:
    """Mark new rows as seen tests"""
    
    def test_mark_new_seen_api(self):
        """Mark new seen API should work"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        session.headers['Referer'] = f"{BASE_URL}/api/kendala_master"
        
        response = session.post(
            f"{BASE_URL}/api/mark_new_seen",
            headers={'X-CSRFToken': session.csrf_token}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert 'ok' in data
        print(f"Mark new seen API response: {data}")


class TestAuditLog:
    """Audit log tests"""
    
    def test_audit_log_accessible_by_admin(self):
        """Audit log should be accessible by admin"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        response = session.get(f"{BASE_URL}/api/audit_log")
        assert response.status_code == 200
        assert 'Audit Log' in response.text or 'audit' in response.text.lower()
        print("Audit log accessible by admin")
    
    def test_audit_log_forbidden_for_operator(self):
        """Audit log should redirect/forbid for non-admin"""
        session = login_session(OPERATOR_USER, OPERATOR_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        response = session.get(f"{BASE_URL}/api/audit_log", allow_redirects=False)
        # Should redirect to dashboard with error message
        assert response.status_code in [302, 303, 403]
        print("Audit log correctly restricted for operator")


class TestGantiPassword:
    """Change password tests"""
    
    def test_ganti_password_page_loads(self):
        """Ganti password page should load"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        response = session.get(f"{BASE_URL}/api/ganti_password")
        assert response.status_code == 200
        assert 'password' in response.text.lower()
        print("Ganti password page loads successfully")


class TestLogout:
    """Logout tests"""
    
    def test_logout_clears_session(self):
        """Logout should clear session and redirect to login"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        # Verify logged in
        dashboard = session.get(f"{BASE_URL}/api/dashboard")
        assert dashboard.status_code == 200
        
        # Logout
        logout_response = session.get(f"{BASE_URL}/api/logout", allow_redirects=False)
        assert logout_response.status_code in [302, 303]
        location = logout_response.headers.get('Location', '')
        assert 'login' in location
        
        # Verify session cleared - dashboard should redirect to login
        dashboard_after = session.get(f"{BASE_URL}/api/dashboard", allow_redirects=False)
        assert dashboard_after.status_code in [302, 303]
        print("Logout correctly clears session")


class TestUpload:
    """Upload page tests"""
    
    def test_upload_page_loads(self):
        """Upload page should load with CSRF token"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        response = session.get(f"{BASE_URL}/api/upload")
        assert response.status_code == 200
        assert 'upload' in response.text.lower() or 'Upload' in response.text
        print("Upload page loads successfully")


class TestCSRFProtection:
    """CSRF protection tests"""
    
    def test_post_without_csrf_rejected(self):
        """POST requests without CSRF token should be rejected"""
        session = get_session_with_headers()
        
        # Get login page to establish session
        session.get(f"{BASE_URL}/api/login")
        session.headers['Referer'] = f"{BASE_URL}/api/login"
        
        # Try POST without CSRF
        response = session.post(
            f"{BASE_URL}/api/login",
            data={
                'username': ADMIN_USER,
                'password': ADMIN_PASS
            }
        )
        
        # Should be rejected (400 Bad Request or similar)
        assert response.status_code == 400 or 'csrf' in response.text.lower()
        print("POST without CSRF correctly rejected")


class TestUNSC:
    """UNSC page tests"""
    
    def test_unsc_page_loads(self):
        """UNSC page should load"""
        session = login_session(ADMIN_USER, ADMIN_PASS)
        assert session is not None, "Failed to create authenticated session"
        
        response = session.get(f"{BASE_URL}/api/unsc")
        assert response.status_code == 200
        assert 'UNSC' in response.text.upper()
        print("UNSC page loads successfully")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
