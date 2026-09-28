"""
Отправка Web Push уведомлений (браузер/PWA). Подписки хранятся в webapp/db.py.

Ключи VAPID берутся из переменных VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY, а если
их нет — генерируются один раз и сохраняются в базе сайта.
"""
from __future__ import annotations

import base64
import json

from config import VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_CLAIM_EMAIL
from webapp import db as pwdb


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _generate_keys() -> tuple[str, str]:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    private_key = ec.generate_private_key(ec.SECP256R1())
    priv = private_key.private_numbers().private_value.to_bytes(32, "big")
    pub = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return _b64url(pub), _b64url(priv)


def get_vapid_keys() -> tuple[str, str]:
    if VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY:
        return VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY
    pub = pwdb.get_kv("vapid_public")
    priv = pwdb.get_kv("vapid_private")
    if not pub or not priv:
        pub, priv = _generate_keys()
        pwdb.set_kv("vapid_public", pub)
        pwdb.set_kv("vapid_private", priv)
    return pub, priv


def get_public_key() -> str:
    try:
        return get_vapid_keys()[0]
    except Exception as e:
        print(f"[push] не удалось получить ключи VAPID: {e!r}")
        return ""


def push_configured() -> bool:
    try:
        import pywebpush  # noqa: F401
        get_vapid_keys()
        return True
    except Exception as e:
        print(f"[push] push недоступен: {e!r}")
        return False


def send_push_to_user(
    telegram_id: int, title: str, body: str, url: str = "/", only_endpoint: str | None = None
) -> None:
    """Синхронная — из async-кода вызывать через asyncio.to_thread."""
    if not push_configured():
        return
    from pywebpush import webpush, WebPushException

    _, private_key = get_vapid_keys()
    payload = json.dumps({"title": title, "body": body, "url": url})
    for sub in pwdb.get_push_subscriptions(telegram_id):
        if only_endpoint and sub["endpoint"] != only_endpoint:
            continue
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": f"mailto:{VAPID_CLAIM_EMAIL}"},
            )
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            print(f"[push] ошибка отправки ({status}): {e!r}")
            if status in (404, 410):
                pwdb.remove_push_subscription(sub["endpoint"])
        except Exception as e:
            print(f"[push] ошибка отправки: {e!r}")


def broadcast_push(telegram_ids: list[int], title: str, body: str, url: str = "/") -> None:
    for tid in telegram_ids:
        send_push_to_user(tid, title, body, url)
