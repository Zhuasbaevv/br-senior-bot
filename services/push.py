"""
Отправка Web Push уведомлений (браузер/PWA) — независимо от Telegram.
Подписки хранятся в webapp/db.py (push_subscriptions), собираются на
странице профиля (webapp/static/push.js).

Если VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY не заданы — все функции тихо
ничего не делают (push — не обязательная часть системы).
"""
from __future__ import annotations

from config import VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_CLAIM_EMAIL
from webapp import db as pwdb


def push_configured() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def send_push_to_user(telegram_id: int, title: str, body: str, url: str = "/") -> None:
    """Синхронная функция (pywebpush сам по себе синхронный) — вызывать через
    asyncio.to_thread(...) из async-кода, не блокируя event loop."""
    if not push_configured():
        return
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return  # pywebpush не установлен - просто нет push, без падения всего сайта

    import json

    payload = json.dumps({"title": title, "body": body, "url": url})
    for sub in pwdb.get_push_subscriptions(telegram_id):
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{VAPID_CLAIM_EMAIL}"},
            )
        except WebPushException as e:
            # 404/410 = подписка больше не действительна (юзер снёс сайт/отписался) - чистим.
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                pwdb.remove_push_subscription(sub["endpoint"])
        except Exception:
            continue


def broadcast_push(telegram_ids: list[int], title: str, body: str, url: str = "/") -> None:
    for tid in telegram_ids:
        send_push_to_user(tid, title, body, url)
