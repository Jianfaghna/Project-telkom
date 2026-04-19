"""
FilterIN - Utility script to hash/upgrade passwords in MySQL.

Usage:
    python hash_password.py              # Hash semua plaintext yang tersisa
    python hash_password.py --reset USER NEW_PASSWORD   # Reset password user

Catatan: script ini BOLEH dijalankan kapan saja. User yang passwordnya
sudah di-hash (format pbkdf2/scrypt/argon2) akan di-skip.
"""
import os
import sys
from pathlib import Path

import pymysql
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / '.env')

CONN = dict(
    host=os.environ.get('MYSQL_HOST', 'localhost'),
    port=int(os.environ.get('MYSQL_PORT', 3306)),
    user=os.environ.get('MYSQL_USER', 'root'),
    password=os.environ.get('MYSQL_PASSWORD', ''),
    database=os.environ.get('MYSQL_DB', 'user_db'),
    cursorclass=pymysql.cursors.DictCursor,
)


def hash_all_plaintext():
    """Hash semua password plaintext yang masih ada di tabel users."""
    hashed = skipped = 0
    with pymysql.connect(**CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, password FROM users")
            rows = cur.fetchall()
            for r in rows:
                pw = r['password'] or ''
                if pw.startswith(('pbkdf2:', 'scrypt:', 'argon2')):
                    skipped += 1
                    print(f"  [SKIP] {r['username']} - sudah ter-hash")
                    continue
                new_hash = generate_password_hash(pw)
                cur.execute(
                    "UPDATE users SET password=%s WHERE id=%s",
                    (new_hash, r['id'])
                )
                hashed += 1
                print(f"  [HASH] {r['username']} - password di-hash")
        conn.commit()
    print(f"\nSelesai. Di-hash: {hashed}, dilewati: {skipped}")


def reset_password(username, new_password):
    """Reset password user spesifik (langsung di-hash)."""
    with pymysql.connect(**CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username=%s", (username,))
            r = cur.fetchone()
            if not r:
                print(f"[ERROR] User '{username}' tidak ditemukan.")
                return
            cur.execute(
                "UPDATE users SET password=%s WHERE username=%s",
                (generate_password_hash(new_password), username)
            )
        conn.commit()
    print(f"[OK] Password user '{username}' telah direset.")


if __name__ == '__main__':
    if len(sys.argv) == 1:
        hash_all_plaintext()
    elif len(sys.argv) == 4 and sys.argv[1] == '--reset':
        reset_password(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        sys.exit(1)
