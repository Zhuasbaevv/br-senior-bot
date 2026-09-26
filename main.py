import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from config import BOT_TOKEN, HEALTHCHECK_PORT, MSK_TZ
from middlewares.access import AccessMiddleware
from utils.access import load_all_users, all_users
from utils.runtime_settings import load_runtime_settings
from services.sheets import get_sheets, run as sheets_run
from services.webapp_client import send_push_via_webapp

from handlers import (
    common,
    verification,
    stats,
    applications,
    admin_panel,
    points_punish,
    review,
    grant_role,
    logging_panel,
    leadership_creator,
    ip_command,
    norms,
    reports,
)

logging.basicConfig(level=logging.INFO)

USER_CACHE_REFRESH_SECONDS = 60


async def _refresh_users_loop() -> None:
    """Бот и сайт — два разных процесса, у каждого своя копия кэша ролей/доступа
    в памяти (utils/access.py). Раз в минуту тихо подтягиваем актуальный список
    из Google Sheets — так изменения с сайта видны боту (и наоборот) без
    ручного перезапуска."""
    while True:
        await asyncio.sleep(USER_CACHE_REFRESH_SECONDS)
        try:
            await load_all_users()
        except Exception:
            logging.exception("Не удалось обновить кэш пользователей (плановое обновление)")


async def _sleep_until(hour: int, minute: int, weekday: int | None = None) -> None:
    """Спит до ближайшего момента hour:minute МСК (weekday: 0=понедельник, None=каждый день)."""
    import datetime as dt
    now = dt.datetime.now(MSK_TZ)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if weekday is not None:
        days_ahead = (weekday - now.weekday()) % 7
        target += dt.timedelta(days=days_ahead)
        if target <= now:
            target += dt.timedelta(days=7)
    else:
        if target <= now:
            target += dt.timedelta(days=1)
    await asyncio.sleep((target - now).total_seconds())


async def _auto_week_sheet_loop() -> None:
    """Каждый понедельник в 00:05 МСК сам создаёт лист новой недели — раньше
    это делалось только вручную командой /createweeksheet."""
    while True:
        await _sleep_until(hour=0, minute=5, weekday=0)
        try:
            sheets = get_sheets()
            title = await sheets_run(sheets.create_week_sheet_manual)
            logging.info(f"Автоматически создан лист новой недели: {title}")
        except Exception:
            logging.exception("Не удалось автоматически создать лист новой недели")


async def _norm_reminder_loop(bot: Bot) -> None:
    """Каждый день в 21:00 МСК проверяет, кто ещё не сдал отчёт за сегодня,
    и напоминает в Telegram + push (см. services/push.py, webapp_client.py)."""
    while True:
        await _sleep_until(hour=21, minute=0)
        try:
            sheets = get_sheets()
            missing = await sheets_run(sheets.rows_missing_today_report)
            if not missing:
                continue
            by_nick = {u.nickname: u for u in all_users()}
            for row in missing:
                user = by_nick.get(row["NickName"])
                if not user:
                    continue
                text = "⚠️ Напоминание: вы ещё не сдали отчёт за сегодня. Норма закрывается до конца дня."
                try:
                    await bot.send_message(user.telegram_id, text)
                except Exception:
                    pass
                await send_push_via_webapp(user.telegram_id, "Норма не выполнена", text, "/profile")
        except Exception:
            logging.exception("Ошибка при проверке невыполненной нормы")


async def _start_healthcheck_server() -> None:
    """Отдельный лёгкий HTTP-сервер (не сам бот — бот работает через long polling,
    HTTP тут вообще не нужен для его работы). Нужен, если хостинг усыпляет
    приложение по неактивности именно HTTP-порта (Render/Railway и т.п. free tier).
    Настрой внешний пинг (UptimeRobot/cron-job.org и т.п.) на GET / раз в 10 минут."""
    app = web.Application()
    app.router.add_get("/", lambda request: web.Response(text="ok"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HEALTHCHECK_PORT)
    await site.start()
    logging.info(f"Healthcheck HTTP-сервер запущен на порту {HEALTHCHECK_PORT}")


async def main() -> None:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    get_sheets(bot)

    @dp.errors()
    async def on_error(event: ErrorEvent):
        logging.exception("Необработанная ошибка при обработке апдейта", exc_info=event.exception)
        update = event.update
        chat_id = None
        if update.message:
            chat_id = update.message.chat.id
        elif update.callback_query and update.callback_query.message:
            chat_id = update.callback_query.message.chat.id
        if chat_id:
            try:
                await bot.send_message(chat_id, "⚠️ Произошла ошибка при обработке запроса. Попробуйте ещё раз.")
            except Exception:
                pass
        return True

    dp.message.middleware(AccessMiddleware())
    dp.callback_query.middleware(AccessMiddleware())

    dp.include_router(common.router)
    dp.include_router(verification.router)
    dp.include_router(stats.router)
    dp.include_router(applications.router)
    dp.include_router(admin_panel.router)
    dp.include_router(points_punish.router)
    dp.include_router(review.router)
    dp.include_router(grant_role.router)
    dp.include_router(logging_panel.router)
    dp.include_router(leadership_creator.router)
    dp.include_router(ip_command.router)
    dp.include_router(norms.router)
    dp.include_router(reports.router)

    await load_all_users()
    await load_runtime_settings()
    asyncio.create_task(_refresh_users_loop())
    asyncio.create_task(_auto_week_sheet_loop())
    asyncio.create_task(_norm_reminder_loop(bot))

    await _start_healthcheck_server()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
