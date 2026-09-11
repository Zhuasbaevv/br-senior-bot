"""
Подписанная сессионная cookie для входа на сайт (ВК ID + пароль, см. webapp/app.py
и webapp/db.py). Сама cookie не хранит ничего, кроме telegram_id, и подделать её
без секретного ключа сервера нельзя (itsdangerous, HMAC-подпись).
"""
from __future__ import annotations

from itsdangerous import BadSignature, URLSafeTimedSerializer

from config import BOT_TOKEN

# Секрет для подписи cookie сессии. По-хорошему — отдельная SESSION_SECRET
# в переменных окружения, но раз BOT_TOKEN и так секретный и уникальный —
# используем его как основу, чтобы не плодить ещё одну обязательную переменную.
_serializer = URLSafeTimedSerializer(BOT_TOKEN, salt="br-webapp-session")

SESSION_COOKIE_NAME = "br_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 дней


def create_session_cookie_value(telegram_id: int) -> str:
    return _serializer.dumps({"telegram_id": telegram_id})


def read_session_cookie_value(value: str | None) -> int | None:
    if not value:
        return None
    try:
        data = _serializer.loads(value, max_age=SESSION_MAX_AGE_SECONDS)
    except BadSignature:
        return None
    return data.get("telegram_id")
