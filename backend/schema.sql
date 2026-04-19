-- FilterIN database schema
USE user_db;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nama VARCHAR(100) NOT NULL,
    username VARCHAR(50) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role ENUM('admin', 'operator', 'viewer') NOT NULL DEFAULT 'operator',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Row-level soft lock (per sheet & row_key/ORDER_ID)
CREATE TABLE IF NOT EXISTS edit_locks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sheet_name VARCHAR(100) NOT NULL,
    row_key VARCHAR(100) NOT NULL,
    locked_by VARCHAR(50) NOT NULL,
    locked_by_nama VARCHAR(100) NOT NULL,
    locked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_lock (sheet_name, row_key),
    INDEX idx_locked_at (locked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Audit log: siapa edit apa kapan
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    nama VARCHAR(100),
    sheet_name VARCHAR(100),
    row_key VARCHAR(100),
    column_name VARCHAR(100),
    old_value TEXT,
    new_value TEXT,
    action VARCHAR(50) NOT NULL,
    ip_address VARCHAR(45),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_timestamp (timestamp),
    INDEX idx_user_time (username, timestamp),
    INDEX idx_row (sheet_name, row_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tracking data baru dari sync BIMA
CREATE TABLE IF NOT EXISTS sync_new_rows (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id VARCHAR(100) NOT NULL,
    sheet_name VARCHAR(100) NOT NULL DEFAULT 'kendalamaster',
    sync_batch_id VARCHAR(50) NOT NULL,
    sync_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    seen_by JSON,
    INDEX idx_batch (sync_batch_id),
    INDEX idx_sync_time (sync_time),
    UNIQUE KEY uniq_order_batch (order_id, sync_batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Brute-force protection log
CREATE TABLE IF NOT EXISTS login_attempts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50),
    ip_address VARCHAR(45),
    success BOOLEAN DEFAULT FALSE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username_time (username, timestamp),
    INDEX idx_ip_time (ip_address, timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
