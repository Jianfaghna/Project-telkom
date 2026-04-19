// LISTENER UTAMA SETELAH HALAMAN SELESAI DIMUAT
document.addEventListener('DOMContentLoaded', function() {

    // ============================================================
    // 1. LOGIKA HIGHLIGHT LINK AKTIF (SIDEBAR)
    // ============================================================
    function highlightActiveLink() {
        const currentPath = window.location.pathname;
        const navLinks = document.querySelectorAll('.menu-items > .item > a, .menu-items > .item > .submenu-item');
        const submenuLinks = document.querySelectorAll('.submenu a');
        const submenuHeaders = document.querySelectorAll('.submenu-item');

        // Reset semua link
        navLinks.forEach(link => link.classList.remove('active'));
        submenuLinks.forEach(link => link.classList.remove('active'));
        submenuHeaders.forEach(header => header.classList.remove('active'));

        let linkFoundInSubmenu = false;
        submenuLinks.forEach(link => {
            if (link.getAttribute('href') === currentPath) {
                link.classList.add('active'); 
                const parentLi = link.closest('.item'); 
                if (parentLi) {
                    parentLi.classList.add('show'); 
                    // Highlight header menu parent-nya juga
                    const header = parentLi.querySelector('.submenu-item');
                    if(header) header.classList.add('active');
                }
                linkFoundInSubmenu = true;
            }
        });

        if (!linkFoundInSubmenu) {
            navLinks.forEach(link => {
                if (link.getAttribute('href') === currentPath) {
                    link.classList.add('active');
                }
            });
        }
    }

    // ============================================================
    // 2. LOGIKA FLASH MESSAGE (NOTIFIKASI)
    // ============================================================
    const allFlashMessages = document.querySelectorAll('.flash-messages .flash');
    allFlashMessages.forEach((message, index) => {
        const delay = 3000 + (index * 500); 
        setTimeout(() => {
            message.style.opacity = '0';
            message.style.transform = 'translateX(100%)'; 
            setTimeout(() => { message.remove(); }, 400); 
        }, delay);
    });

    // ============================================================
    // 3. LOGIKA KONFIRMASI LOGOUT (MODAL)
    // ============================================================
    const logoutLink = document.querySelector('a[href*="logout"]'); 
    const modalOverlay = document.getElementById('logout-modal-overlay');
    const cancelBtn = document.getElementById('logout-cancel-btn');
    const confirmBtn = document.getElementById('logout-confirm-btn');

    if (logoutLink && modalOverlay && cancelBtn && confirmBtn) {
        logoutLink.addEventListener('click', function(e) {
            e.preventDefault();
            modalOverlay.classList.add('show');
        });

        cancelBtn.addEventListener('click', () => modalOverlay.classList.remove('show'));
        modalOverlay.addEventListener('click', (e) => {
            if (e.target === modalOverlay) modalOverlay.classList.remove('show');
        });
        confirmBtn.addEventListener('click', () => {
            window.location.href = logoutLink.href;
        });
    }

    // ============================================================
    // 4. LOGIKA TOMBOL OTOMATISASI (SYNC BIMA & UNSC)
    // ============================================================
    // Fungsi reusable untuk tombol fetch API
    function setupAutomationButton(btnId, statusId, url, loadingMsg, successMsg) {
        const btn = document.getElementById(btnId);
        const status = document.getElementById(statusId);

        if (btn && status) {
            btn.addEventListener('click', () => {
                const originalText = btn.innerHTML; 
                
                status.style.color = '#007bff'; // Biru
                status.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${loadingMsg}`;
                btn.disabled = true;
                btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Memproses...`;

                fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        status.style.color = '#28a745'; // Hijau
                        status.innerHTML = `<i class="fas fa-check-circle"></i> ${successMsg} (${data.message})`;
                        setTimeout(() => window.location.reload(), 2000); // Auto refresh
                    } else {
                        status.style.color = '#dc3545'; // Merah
                        status.textContent = 'Error: ' + data.message;
                        btn.disabled = false;
                        btn.innerHTML = originalText;
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    status.style.color = '#dc3545';
                    status.textContent = 'Gagal terhubung ke server.';
                    btn.disabled = false;
                    btn.innerHTML = originalText;
                });
            });
        }
    }

    setupAutomationButton('syncButton', 'syncStatus', '/sync-bima', 'Sedang sinkronisasi BIMA...', 'Sinkronisasi Berhasil!');
    setupAutomationButton('moveUnscButton', 'moveUnscStatus', '/move-to-unsc', 'Memindahkan data ke UNSC...', 'Data Berhasil Dipindah!');


    // ============================================================
    // 5. LOGIKA SUBMENU ACCORDION (SIDEBAR)
    // ============================================================
    const sidebar = document.querySelector('.sidebar');
    const submenuItems = document.querySelectorAll('.submenu-item');

    const closeAllSubmenus = (exceptThisOne = null) => {
        document.querySelectorAll('.item.show').forEach(openItem => {
            if (openItem !== exceptThisOne) {
                openItem.classList.remove('show');
            }
        });
    };

    submenuItems.forEach(item => {
        item.addEventListener('click', (event) => {
            event.stopPropagation(); 
            // Jangan buka submenu jika sidebar sedang collapse (opsional)
            if (sidebar.classList.contains('collapsed')) return;

            const parentItem = item.parentElement;
            const isAlreadyOpen = parentItem.classList.contains('show');
            
            closeAllSubmenus(parentItem); 
            
            if (!isAlreadyOpen) {
                parentItem.classList.add('show');
            } else {
                parentItem.classList.remove('show');
            }
        });
    });

    // ============================================================
    // 6. LOGIKA SAVE BAR (GLOBAL TRIGGER)
    // ============================================================
    const saveBar = document.querySelector('.controls-bar');
    
    // Event Delegation: Mendeteksi perubahan pada input/select di tabel manapun
    document.body.addEventListener('change', function(e) {
        if (e.target.matches('.editable-table select, .editable-table input')) {
            const row = e.target.closest('tr');
            if (row) row.classList.add('is-dirty');
            if (saveBar) saveBar.style.display = 'block';
        }
    });

    // Khusus input teks agar tombol muncul saat mengetik
    document.body.addEventListener('input', function(e) {
        if (e.target.matches('.editable-table input[type="text"]')) {
            const row = e.target.closest('tr');
            if (row) row.classList.add('is-dirty');
            if (saveBar) saveBar.style.display = 'block';
        }
    });


    // ============================================================
    // 7. LOGIKA MINIMIZE SIDEBAR & MAIN CONTENT
    // ============================================================
    const toggleBtn = document.getElementById('sidebar-toggle');
    const mainContainer = document.getElementById('main-container');

    if (toggleBtn && mainContainer && sidebar) {
        // Cek LocalStorage
        if (localStorage.getItem('sidebarCollapsed') === 'true') {
            sidebar.classList.add('collapsed');
            mainContainer.classList.add('collapsed');
        }

        toggleBtn.addEventListener('click', function(event) {
            event.preventDefault(); 
            event.stopPropagation();
                
            sidebar.classList.toggle('collapsed');
            mainContainer.classList.toggle('collapsed');
                
            if (sidebar.classList.contains('collapsed')) {
                localStorage.setItem('sidebarCollapsed', 'true');
                closeAllSubmenus(); // Tutup submenu agar rapi
            } else {
                localStorage.setItem('sidebarCollapsed', 'false');
            }
        });
    }

    // ============================================================
    // 8. LOGIKA FORM UPLOAD (PREVIEW FILE NAME)
    // ============================================================
    function setupUploadForm(formId, inputId) {
        const form = document.getElementById(formId);
        const fileInput = inputId ? document.getElementById(inputId) : (form ? form.querySelector('input[type="file"]') : null);
        
        if (form && fileInput) {
            const fileNameDisplay = form.querySelector('.upload-filename');
            const errorDisplay = form.querySelector('.upload-error');

            fileInput.addEventListener('change', function() {
                if (fileInput.files.length > 0) {
                    if(fileNameDisplay) fileNameDisplay.textContent = fileInput.files[0].name;
                    if(errorDisplay) errorDisplay.style.display = 'none';
                }
            });

            form.addEventListener('submit', function(event) {
                if (fileInput.files.length === 0) {
                    event.preventDefault();
                    if (errorDisplay) {
                        errorDisplay.textContent = 'Harap pilih file terlebih dahulu.';
                        errorDisplay.style.display = 'block';
                    }
                }
            });
        }
    }
    setupUploadForm('form-bima', null);
    setupUploadForm('form-kpro', null);


    // ============================================================
    // 9. LOGIKA PENANDA DATA BARU (NEW BADGE) - [UPDATE TERBARU]
    // ============================================================
    function highlightNewRows() {
        // 1. Dapatkan Tanggal Hari Ini (Format: DD/MM/YYYY)
        const now = new Date();
        const d = String(now.getDate()).padStart(2, '0');
        const m = String(now.getMonth() + 1).padStart(2, '0');
        const y = now.getFullYear();
        const todayStr = `${d}/${m}/${y}`; // Contoh: 30/11/2025

        // 2. Cari semua baris di tabel
        const rows = document.querySelectorAll('.editable-table tbody tr');

        rows.forEach(row => {
            let isNew = false;
            
            // 3. Cek setiap sel di baris tersebut
            const cells = row.querySelectorAll('td');
            cells.forEach(cell => {
                // Cek teks murni atau value dari input jika ada
                const text = cell.innerText.trim() || cell.querySelector('input')?.value || '';
                
                // Jika sel mengandung tanggal hari ini
                if (text.includes(todayStr)) {
                    isNew = true;
                }
            });

            // 4. Jika baris ini baru (ada tanggal hari ini)
            if (isNew) {
                row.classList.add('is-new-row'); // Tambah background kuning (CSS)
                
                // Tambahkan Badge "NEW" di kolom pertama (biasanya ID/No)
                const firstCell = row.querySelector('td:nth-child(1)');
                // Cek apakah badge sudah ada supaya tidak duplikat
                if (firstCell && !firstCell.querySelector('.new-badge')) {
                    const badge = document.createElement('span');
                    badge.className = 'new-badge';
                    badge.innerText = 'NEW';
                    firstCell.appendChild(badge);
                }
            }
        });
    }

    // --- INISIALISASI ---
    highlightActiveLink();
    highlightNewRows(); // Jalankan fungsi penanda data baru

});