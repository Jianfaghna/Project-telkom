-- ============================================================
-- FilterIN — Database Dump Lengkap
-- Host: 127.0.0.1 (XAMPP/MariaDB)
-- Database: user_db
-- Dibuat: 2026
-- ============================================================

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

-- ============================================================
-- Database: `user_db`
-- ============================================================

-- --------------------------------------------------------
-- Tabel: users
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `users` (
  `id`         int(11)      NOT NULL AUTO_INCREMENT,
  `nama`       varchar(100) NOT NULL,
  `username`   varchar(50)  NOT NULL,
  `password`   varchar(255) NOT NULL,
  `role`       enum('admin','operator','viewer') NOT NULL DEFAULT 'operator',
  `created_at` timestamp    NULL DEFAULT CURRENT_TIMESTAMP,
  `last_login` timestamp    NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Data default users
-- Password semua masih plain text, jalankan hash_password.py setelah import
INSERT INTO `users` (`id`, `nama`, `username`, `password`, `role`) VALUES
(1,  'devanda',         'wadaw',      'wadaw123',      'operator'),
(2,  'ludfi arfiani',   'Aleshapark', 'parkjisung',    'operator'),
(3,  'Telkom Magelang', 'TelkomASO',  'TelkomASO001',  'admin'),
(6,  'devanda adrian',  'dava234',    'dava123',        'operator');

ALTER TABLE `users` MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=8;

-- --------------------------------------------------------
-- Tabel: audit_log
-- Menyimpan riwayat semua perubahan data oleh user
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `audit_log` (
  `id`          bigint(20)   NOT NULL AUTO_INCREMENT,
  `username`    varchar(50)  NOT NULL,
  `nama`        varchar(100) DEFAULT NULL,
  `sheet_name`  varchar(100) DEFAULT NULL,
  `row_key`     varchar(100) DEFAULT NULL,
  `column_name` varchar(100) DEFAULT NULL,
  `old_value`   text         DEFAULT NULL,
  `new_value`   text         DEFAULT NULL,
  `action`      varchar(50)  NOT NULL,
  `ip_address`  varchar(45)  DEFAULT NULL,
  `timestamp`   timestamp    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_timestamp`  (`timestamp`),
  KEY `idx_user_time`  (`username`, `timestamp`),
  KEY `idx_row`        (`sheet_name`, `row_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Tabel: edit_locks
-- Row-level soft lock saat user sedang mengedit baris
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `edit_locks` (
  `id`          int(11)      NOT NULL AUTO_INCREMENT,
  `sheet_name`  varchar(100) NOT NULL,
  `row_key`     varchar(100) NOT NULL,
  `locked_by`   varchar(50)  NOT NULL,
  `locked_at`   timestamp    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `expires_at`  timestamp    NOT NULL DEFAULT (CURRENT_TIMESTAMP + INTERVAL 5 MINUTE),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_lock` (`sheet_name`, `row_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Tabel: sync_new_rows
-- Melacak baris baru hasil sinkronisasi BIMA
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `sync_new_rows` (
  `id`        int(11)      NOT NULL AUTO_INCREMENT,
  `order_id`  varchar(100) NOT NULL,
  `sync_time` timestamp    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `seen_by`   json         DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_sync_time` (`sync_time`),
  KEY `idx_order_id`  (`order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Tabel: login_attempts
-- Melacak percobaan login (rate limiting)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `login_attempts` (
  `id`         int(11)     NOT NULL AUTO_INCREMENT,
  `username`   varchar(50) NOT NULL,
  `ip_address` varchar(45) DEFAULT NULL,
  `attempted_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `success`    tinyint(1)  DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_username_time` (`username`, `attempted_at`),
  KEY `idx_ip_time`       (`ip_address`, `attempted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------
-- Tabel: user_sessions
-- Melacak user yang sedang online (heartbeat)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `user_sessions` (
  `username`     varchar(50)  NOT NULL,
  `current_page` varchar(100) DEFAULT 'Dashboard',
  `last_seen`    timestamp    NOT NULL DEFAULT CURRENT_TIMESTAMP
                              ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`username`),
  KEY `idx_last_seen` (`last_seen`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- ============================================================
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;

-- ============================================================
-- CATATAN SETELAH IMPORT:
-- 1. Jalankan hash_password.py untuk hash semua password plain text
-- 2. Akun admin default: TelkomASO / TelkomASO001
-- 3. Semua akun lain role-nya 'operator' by default
-- ============================================================