-- ============================================================
-- FilterIN v2.0 — Tambahan Schema
-- Watchlist (Opsi 3) + Announcement Board (Opsi 4)
-- Jalankan di phpMyAdmin atau MySQL CLI:
--   USE user_db;
--   source add_watchlist_announcement.sql;
-- ============================================================

USE user_db;

-- ── Opsi 3: Watchlist ────────────────────────────────────────
-- Operator bisa flag order tertentu untuk dipantau khusus
CREATE TABLE IF NOT EXISTS watchlist (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id    VARCHAR(100) NOT NULL,
    sheet_name  VARCHAR(100) NOT NULL DEFAULT 'kendalamaster',
    flagged_by  VARCHAR(50)  NOT NULL,          -- username
    flagged_nama VARCHAR(100),                  -- nama lengkap
    catatan     VARCHAR(255) DEFAULT '',        -- alasan/catatan singkat
    flagged_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_flag (order_id, flagged_by),
    INDEX idx_flagged_by (flagged_by),
    INDEX idx_order (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Opsi 4: Announcement Board ───────────────────────────────
-- Admin post pengumuman, muncul sebagai banner di dashboard
CREATE TABLE IF NOT EXISTS announcements (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    judul       VARCHAR(200) NOT NULL,
    isi         TEXT NOT NULL,
    label       ENUM('PENTING','INFO','REMINDER') DEFAULT 'INFO',
    posted_by   VARCHAR(50)  NOT NULL,
    posted_nama VARCHAR(100),
    expires_at  DATETIME NULL,                  -- NULL = tidak expire
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_expires (expires_at),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;