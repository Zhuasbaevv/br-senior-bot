"""
Общая отправка "уведомление человеку" — сразу в Telegram и push (см.
services/push.py). Раньше в каждом хендлере/роуте был только bot.send_message,
push добавлялся бы отдельно и непоследовательно — теперь одна функция на оба
случая (бот-процесс/веб-процесс), чтобы НИ ОДНО действие над человеком
(роль, баллы, наказание, заявка, рассылка /o) не проходило только по одному
каналу.
"""
from __future__ import annotations

import asyncio


async def notify_from_bot(bot, telegram_id: int, text: str, push_title: str, url: str = "/") -> None:
    """Использовать из хендлеров бота (main.py процесс) — push уходит через
    HTTP-мост на сайт, т.к. подписки хранятся в базе САЙТА."""
    try:
        await bot.send_message(telegram_id, text)
    except Exception:
        pass
    from services.webapp_client import send_push_via_webapp
    await send_push_via_webapp(telegram_id, push_title, text, url)


async def notify_from_web(bot, telegram_id: int, text: str, push_title: str, url: str = "/") -> None:
    """Использовать из роутов сайта (webapp/app.py) — push уходит напрямую,
    без HTTP (сайт и есть тот процесс, где лежит база подписок)."""
    try:
        await bot.send_message(telegram_id, text)
    except Exception:
        pass
    from services import push
    await asyncio.to_thread(push.send_push_to_user, telegram_id, push_title, text, url)
