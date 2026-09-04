"""
Локальное хранилище паролей веб-панели — ТОЛЬКО хэши (см. utils/passwords.py),
живёт исключительно на сайте, в Google-таблицу не попадает вообще.

ВАЖНО ПРО RAILWAY: файловая система сервиса на Railway по умолчанию эфемерная —
при каждом передеплое содержимое диска сбрасывается. Чтобы пароли не терялись,
к сервису сайта нужно подключить Volume (постоянный диск) и указать его путь
через переменную PASSWORD_DB_PATH (см. webapp/README.md). Без Volume пароли
будут слетать при каждом обновлении кода — не критично (можно попросить всех
заново выставить /setpassword), но неудобно, так что Volume лучше подключить сразу.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from config import PASSWORD_DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS passwords (
    telegram_id INTEGER PRIMARY KEY,
    password_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS login_devices (
    telegram_id INTEGER NOT NULL,
    device_fingerprint TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (telegram_id, device_fingerprint)
);
"""


@contextmanager
def _conn():
    conn = sqlite3.connect(PASSWORD_DB_PATH)
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def set_password_hash(telegram_id: int, password_hash: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO passwords (telegram_id, password_hash, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(telegram_id) DO UPDATE SET password_hash=excluded.password_hash, updated_at=excluded.updated_at",
            (telegram_id, password_hash),
        )


def get_password_hash(telegram_id: int) -> str | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM passwords WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return row[0] if row else None


def has_password(telegram_id: int) -> bool:
    return get_password_hash(telegram_id) is not None


def is_known_device(telegram_id: int, fingerprint: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM login_devices WHERE telegram_id = ? AND device_fingerprint = ?",
            (telegram_id, fingerprint),
        ).fetchone()
        return row is not None


def remember_device(telegram_id: int, fingerprint: str, ip: str, user_agent: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO login_devices (telegram_id, device_fingerprint, ip, user_agent) "
            "VALUES (?, ?, ?, ?)",
            (telegram_id, fingerprint, ip, user_agent),
        )
