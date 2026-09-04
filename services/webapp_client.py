"""
Клиент бота для внутреннего API сайта (только установка пароля). Пароли хранятся
ТОЛЬКО на сайте (webapp/db.py, SQLite) — бот в Google-таблицу их не пишет вообще,
поэтому единственный способ "установить пароль" для бота — попросить об этом сайт
по HTTP, с общим секретом, который знают оба сервиса (INTERNAL_API_SECRET).
"""
from __future__ import annotations

import aiohttp

from config import WEBAPP_URL, INTERNAL_API_SECRET


async def set_password_on_webapp(telegram_id: int, password_hash: str) -> tuple[bool, str]:
    """Возвращает (успех, сообщение_об_ошибке_если_не_успех)."""
    if not WEBAPP_URL:
        return False, "WEBAPP_URL не настроен у бота — сайт ещё не подключён."
    if not INTERNAL_API_SECRET:
        return False, "INTERNAL_API_SECRET не настроен — задай одинаковый секрет в переменных бота И сайта."

    url = f"{WEBAPP_URL}/internal/set-password"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"telegram_id": telegram_id, "password_hash": password_hash},
                headers={"X-Internal-Secret": INTERNAL_API_SECRET},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return True, ""
                body = await resp.text()
                return False, f"Сайт ответил {resp.status}: {body[:200]}"
    except Exception as e:
        return False, f"Не удалось достучаться до сайта: {e}"
