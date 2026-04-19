import pymysql
from werkzeug.security import generate_password_hash

# --- KONFIGURASI DATABASE ---
db_config = {
    'host': "localhost",
    'user': "root",
    'password': "", # Isi password XAMPP/MySQL Anda
    'database': "user_db",
    'cursorclass': pymysql.cursors.DictCursor
}
# ---------------------------------

print("Menghubungkan ke database...")
try:
    db = pymysql.connect(**db_config)
    cursor = db.cursor()
    
    # 1. Temukan semua user yang passwordnya BUKAN hash
    # (Hash dari Werkzeug selalu diawali dengan 'pbkdf2:')
    cursor.execute("SELECT id, username, password FROM users WHERE password NOT LIKE 'pbkdf2:%'")
    users_to_update = cursor.fetchall()

    if not users_to_update:
        print("Semua password sudah dalam format hash. Tidak ada yang perlu diubah.")
        exit()

    print(f"Ditemukan {len(users_to_update)} password yang perlu di-hash...")

    # 2. Loop dan update setiap password
    for user in users_to_update:
        user_id = user['id']
        plain_password = user['password']
        
        # Buat hash baru
        hashed_password = generate_password_hash(plain_password)
        
        # Update ke database
        cursor.execute("UPDATE users SET password = %s WHERE id = %s", (hashed_password, user_id))
        print(f"  -> Password untuk user '{user['username']}' (ID: {user_id}) telah di-hash.")
    
    # 3. Simpan perubahan
    db.commit()
    print("\nSelesai! Semua password telah diamankan.")

except Exception as e:
    db.rollback()
    print(f"\nTerjadi error: {e}")
finally:
    cursor.close()
    db.close()
