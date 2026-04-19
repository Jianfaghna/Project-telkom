@echo off
TITLE FilterIN Server Launcher
COLOR 0B

echo.
echo ============================================================
echo    FILTERIN v2.0 - Server Launcher
echo    Telkom ASO Magelang - Unit Kendala
echo ============================================================
echo.

REM Pindah ke folder backend
cd /d "%~dp0backend"
if errorlevel 1 (
    echo [ERROR] Folder 'backend' tidak ditemukan!
    pause
    exit /b 1
)

REM Aktifkan virtual environment kalau ada
if exist "..\venv\Scripts\activate.bat" (
    echo [INFO] Mengaktifkan virtual environment...
    call ..\venv\Scripts\activate.bat
) else (
    echo [WARN] Virtual env tidak ditemukan. Pakai Python system.
    echo        Disarankan bikin venv dulu, lihat notes.txt bagian C.4
)

REM Cek credentials.json
if not exist "credentials.json" (
    echo.
    echo [ERROR] File credentials.json tidak ditemukan di folder backend!
    echo         File ini WAJIB ada untuk koneksi Google Sheets.
    echo.
    pause
    exit /b 1
)

REM Cek .env
if not exist ".env" (
    echo.
    echo [ERROR] File .env tidak ditemukan di folder backend!
    echo         Lihat notes.txt bagian E untuk isi yang benar.
    echo.
    pause
    exit /b 1
)

REM Cek apakah XAMPP MySQL running
echo.
echo [INFO] Pastikan XAMPP MySQL sudah di-Start.
echo.

REM Jalankan waitress
echo ============================================================
echo  Server berjalan di:
echo    http://127.0.0.1:5000        (lokal)
echo    http://%COMPUTERNAME%:5000   (jaringan)
echo.
echo  Tekan Ctrl+C untuk stop.
echo ============================================================
echo.

waitress-serve --host=0.0.0.0 --port=5000 app_flask:flask_app

echo.
echo [INFO] Server berhenti.
pause
