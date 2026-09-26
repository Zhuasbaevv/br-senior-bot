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
CREATE TABLE IF NOT EXISTS login_attempts (
    vk_id TEXT PRIMARY KEY,
    fail_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT
);
CREATE TABLE IF NOT EXISTS login_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    ip TEXT,
    user_agent TEXT,
    at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
    telegram_id INTEGER NOT NULL,
    endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (telegram_id, endpoint)
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


# ---------------------------------------------------------------------------
# Лимит попыток входа — ключ ВК ID (проверяем ДО того, как узнаём telegram_id,
# чтобы не дать перебирать сами VK ID). После MAX_FAILS неудачных попыток
# подряд блокируем на LOCKOUT_MINUTES.
# ---------------------------------------------------------------------------
MAX_FAILS = 5
LOCKOUT_MINUTES = 15


def check_login_lock(vk_id: str) -> int | None:
    """Если сейчас заблокировано — вернёт, сколько минут осталось ждать. Иначе None."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT locked_until FROM login_attempts WHERE vk_id = ?", (vk_id,)
        ).fetchone()
        if not row or not row[0]:
            return None
        remaining = conn.execute(
            "SELECT CAST((julianday(?) - julianday('now')) * 1440 AS INTEGER)", (row[0],)
        ).fetchone()[0]
        return remaining if remaining and remaining > 0 else None


def register_login_fail(vk_id: str) -> None:
    with _conn() as conn:
        row = conn.execute("SELECT fail_count FROM login_attempts WHERE vk_id = ?", (vk_id,)).fetchone()
        fails = (row[0] if row else 0) + 1
        locked_until = None
        if fails >= MAX_FAILS:
            locked_until = conn.execute(
                "SELECT datetime('now', ?)", (f"+{LOCKOUT_MINUTES} minutes",)
            ).fetchone()[0]
            fails = 0  # после блокировки счётчик обнуляем — следующая серия начнётся с нуля
        conn.execute(
            "INSERT INTO login_attempts (vk_id, fail_count, locked_until) VALUES (?, ?, ?) "
            "ON CONFLICT(vk_id) DO UPDATE SET fail_count=excluded.fail_count, locked_until=excluded.locked_until",
            (vk_id, fails, locked_until),
        )


def reset_login_fails(vk_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM login_attempts WHERE vk_id = ?", (vk_id,))


# ---------------------------------------------------------------------------
# История входов — показывается в профиле ("последний вход: дата, устройство"),
# чтобы человек сам заметил, если зашёл кто-то не он.
# ---------------------------------------------------------------------------
def add_login_history(telegram_id: int, ip: str, user_agent: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO login_history (telegram_id, ip, user_agent) VALUES (?, ?, ?)",
            (telegram_id, ip, user_agent),
        )
        # Не даём таблице расти бесконечно — оставляем последние 20 записей на человека.
        conn.execute(
            "DELETE FROM login_history WHERE telegram_id = ? AND id NOT IN ("
            "  SELECT id FROM login_history WHERE telegram_id = ? ORDER BY id DESC LIMIT 20"
            ")",
            (telegram_id, telegram_id),
        )


def get_last_logins(telegram_id: int, limit: int = 5) -> list[sqlite3.Row]:
    with _conn() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT ip, user_agent, at FROM login_history WHERE telegram_id = ? ORDER BY id DESC LIMIT ?",
            (telegram_id, limit),
        ).fetchall()


# ---------------------------------------------------------------------------
# Web Push подписки (см. webapp/push.py) — для уведомлений прямо на телефон
# ("вам назначен тест", "не сдан норматив" и т.п.), независимо от Telegram.
# ---------------------------------------------------------------------------
def save_push_subscription(telegram_id: int, endpoint: str, p256dh: str, auth: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO push_subscriptions (telegram_id, endpoint, p256dh, auth) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(telegram_id, endpoint) DO UPDATE SET p256dh=excluded.p256dh, auth=excluded.auth",
            (telegram_id, endpoint, p256dh, auth),
        )


def remove_push_subscription(endpoint: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


def get_push_subscriptions(telegram_id: int) -> list[sqlite3.Row]:
    with _conn() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE telegram_id = ?", (telegram_id,)
        ).fetchall()


def get_all_push_subscriptions() -> list[sqlite3.Row]:
    with _conn() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT telegram_id, endpoint, p256dh, auth FROM push_subscriptions").fetchall()
