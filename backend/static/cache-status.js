// [FITUR] Cache - status pembaruan sumber dan hasil proses manual/otomatis.
document.addEventListener('DOMContentLoaded', function () {
    const badge = document.getElementById('cache-status-badge');
    if (!badge) return;
    const button = document.getElementById('btn-refresh-cache');
    const sources = document.getElementById('cache-source-list');
    const schedule = document.getElementById('cache-schedule');
    let timer, inFlight = false, posting = false, pending = null, running = false;
    let automatic = null, scheduleDeadline = null, automaticRunning = false;

    function renderSchedule() {
        if (!automatic) {
            schedule.textContent = 'Jadwal otomatis belum dapat diperiksa.';
        } else if (!automatic.running) {
            schedule.textContent = 'Jadwal otomatis belum terkonfirmasi aktif pada proses server ini.';
        } else if (automaticRunning) {
            schedule.textContent = 'Pembaruan otomatis sedang berjalan...';
        } else if (scheduleDeadline === null) {
            schedule.textContent = 'Waktu pembaruan otomatis berikutnya belum tersedia.';
        } else {
            const remaining = Math.max(0, Math.ceil((scheduleDeadline - performance.now()) / 1000));
            if (!remaining) {
                schedule.textContent = 'Menunggu proses pembaruan otomatis dimulai...';
                return;
            }
            const countdown = document.createElement('strong');
            countdown.textContent = String(Math.floor(remaining / 60)).padStart(2, '0') + ':'
                + String(remaining % 60).padStart(2, '0');
            schedule.replaceChildren(document.createTextNode('Pembaruan otomatis aktif setiap '
                + Math.round(automatic.interval_seconds / 60) + ' menit. Berikutnya dalam '), countdown, '.');
        }
    }

    function show(text, tone) {
        badge.textContent = text;
        badge.dataset.tone = tone || 'neutral';
    }

    function setButton() {
        if (!button) return;
        button.disabled = Boolean(posting || pending || running);
        button.textContent = button.disabled ? 'Memperbarui...' : 'Perbarui Data';
    }

    async function request(url, options) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15000);
        try {
            const response = await fetch(url, {...options, signal: controller.signal});
            if (!response.ok) throw new Error('Status tidak tersedia');
            const data = await response.json();
            if (data.error) throw new Error('Status tidak tersedia');
            return data;
        } finally {
            clearTimeout(timeout);
        }
    }

    function render(data) {
        if (!Array.isArray(data.cache) || !data.automatic) throw new Error('Respons tidak lengkap');
        const refresh = data.refresh;
        running = Boolean(refresh && refresh.state === 'running');
        const items = refresh && Array.isArray(refresh.items) ? refresh.items : [];
        const labels = {
            saved: 'Pembaruan terakhir berhasil', cache_failed: 'Data terbaca, tetapi salinan gagal disimpan',
            fetch_failed: 'Data terbaru belum berhasil diambil', unconfigured: 'Sumber belum dikonfigurasi'
        };
        sources.replaceChildren();
        data.cache.forEach(function (source) {
            const li = document.createElement('li');
            const title = document.createElement('strong');
            title.textContent = source.sheet_name;
            const time = document.createElement('span');
            time.textContent = source.status === 'missing' ? 'Salinan data belum tersedia'
                : 'Terakhir diperbarui: ' + source.fetched_at;
            li.append(title, time);
            const outcome = items.find(item => item.sheet_name === source.sheet_name);
            if (outcome || running) {
                const result = document.createElement('span');
                result.textContent = outcome ? (labels[outcome.status] || 'Hasil belum diketahui')
                    : 'Menunggu giliran pembaruan';
                li.append(result);
            }
            sources.append(li);
        });
        automatic = data.automatic;
        automaticRunning = running && refresh.trigger === 'automatic';
        const nextRun = Date.parse(automatic.next_run_at);
        const serverTime = Date.parse(automatic.server_time);
        // Gunakan selisih waktu server agar jam perangkat pengguna tidak menggeser hitungan.
        scheduleDeadline = Number.isFinite(nextRun) && Number.isFinite(serverTime)
            ? performance.now() + Math.max(0, nextRun - serverTime) : null;
        renderSchedule();

        if (pending && refresh && (pending.runId ? refresh.run_id === pending.runId
                : refresh.run_id !== pending.previousRunId)) {
            if (['complete', 'partial', 'interrupted'].includes(refresh.state)) pending = null;
        }
        if (running) {
            show('Sedang mengambil data terbaru (' + items.length + '/' + refresh.total + ')...', 'busy');
        } else if (posting || pending) {
            if (pending && Date.now() - pending.since > 120000) {
                pending = null;
                show('Hasil pembaruan belum dapat dipastikan. Periksa kembali statusnya.', 'warning');
            } else show('Menunggu proses pembaruan dimulai...', 'busy');
        } else if (refresh && refresh.state === 'interrupted') {
            show('Proses pembaruan terhenti sebelum selesai. Silakan coba kembali.', 'warning');
        } else if (refresh && refresh.state === 'partial') {
            show('Pembaruan terakhir belum lengkap (' + refresh.cached + '/' + refresh.total + ' berhasil)', 'warning');
        } else if (!data.cache.length || data.cache.some(source => source.status === 'missing')) {
            show('Sebagian salinan data belum tersedia. Lihat detail pembaruan.', 'warning');
        } else if (data.cache.some(source => source.age_seconds > automatic.interval_seconds * 2)) {
            show('Salinan data belum diperbarui lebih dari 10 menit. Lihat detail.', 'warning');
        } else if (refresh && refresh.state === 'complete') {
            show('Pembaruan terakhir selesai - ' + refresh.cached + '/' + refresh.total + ' sumber berhasil', 'ok');
        } else {
            show('Data tersedia - lihat waktu pembaruan tiap sumber');
        }
        setButton();
    }

    async function checkStatus() {
        if (inFlight) return;
        clearTimeout(timer);
        inFlight = true;
        try {
            render(await request('/api/cache_status'));
        } catch (_) {
            show('Status pembaruan belum dapat diperiksa. Akan dicoba kembali.', 'warning');
            automatic = null;
            scheduleDeadline = null;
            automaticRunning = false;
            renderSchedule();
            if (pending && Date.now() - pending.since > 120000) pending = null;
            running = false;
            setButton();
        } finally {
            inFlight = false;
            timer = setTimeout(checkStatus, pending || running ? 2000 : 30000);
        }
    }

    if (button) button.addEventListener('click', async function () {
        if (button.disabled) return;
        posting = true;
        setButton();
        show('Mengirim permintaan pembaruan...', 'busy');
        try {
            const data = await request('/api/cache_refresh', {method: 'POST',
                headers: {'Content-Type': 'application/json'}});
            if (data.status !== 'accepted') throw new Error('Permintaan ditolak');
            pending = {runId: data.run_id, previousRunId: data.previous_run_id, since: Date.now()};
            show('Permintaan diterima; menunggu hasil pembaruan...', 'busy');
        } catch (_) {
            show('Permintaan belum dapat dikonfirmasi. Periksa status sebelum mencoba lagi.', 'warning');
        } finally {
            posting = false;
            setButton();
            // Tidak menyatakan sukses berdasarkan timer; tunggu hasil run dari backend.
            if (pending) checkStatus();
        }
    });
    checkStatus();
    // Hanya menggambar hitungan; permintaan status tetap memakai interval polling di atas.
    setInterval(renderSchedule, 1000);
});
