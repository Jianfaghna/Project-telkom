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

    // Sinkronisasi BIMA dan pemindahan UNSC ditangani oleh kendalamaster.html.


    // ============================================================
    // 4. LOGIKA SUBMENU ACCORDION (SIDEBAR)
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
    // 5. LOGIKA SAVE BAR (GLOBAL TRIGGER)
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
    // 6. LOGIKA MINIMIZE SIDEBAR & MAIN CONTENT
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
    // 7. LOGIKA FORM UPLOAD (PREVIEW FILE NAME)
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


    // Penanda NEW mengikuti hasil sinkronisasi dari backend, bukan tanggal isi baris.

    // --- INISIALISASI ---
    highlightActiveLink();

});
