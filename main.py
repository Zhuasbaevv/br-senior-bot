import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from config import BOT_TOKEN, HEALTHCHECK_PORT
from middlewares.access import AccessMiddleware
from utils.access import load_all_users
from utils.runtime_settings import load_runtime_settings
from services.sheets import get_sheets

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
    в памяти (utils/access.py). Если доступ выдать на одной стороне, вторая узнает
    об этом только перезапустившись — если её не обновлять периодически. Раз в
    минуту тихо подтягиваем актуальный список из Google Sheets на КАЖДОЙ стороне —
    так изменения с сайта видны боту (и наоборот) без ручного перезапуска."""
    while True:
        await asyncio.sleep(USER_CACHE_REFRESH_SECONDS)
        try:
            await load_all_users()
        except Exception:
            logging.exception("Не удалось обновить кэш пользователей (плановое обновление)")


async def _start_healthcheck_server() -> None:
    """Отдельный лёгкий HTTP-сервер (не сам бот — бот работает через long polling,
    HTTP тут вообще не нужен для его работы). Нужен ТОЛЬКО если хостинг усыпляет
    приложение по неактивности именно HTTP-порта (Render/Railway и т.п. free tier).
    Настрой внешний пинг (UptimeRobot/cron-job.org и т.п.) на GET / раз в 10 минут —
    это и будет держать хостинг активным, независимо от /ping в личку боту."""
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

    # ВАЖНО: get_sheets() создаёт синглтон SheetsService, и именно ОТСЮДА он должен
    # получить bot — без этого self.bot внутри SheetsService остаётся None, и ВСЕ логи
    # в канал (LOG_CHANNEL_ID) молча не отправляются, даже если весь остальной код
    # написан правильно. Раньше get_sheets() нигде не вызывался с bot вообще.
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

    # Порядок важен: более специфичные роутеры — раньше.
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

    await load_all_users()  # первичная загрузка ролей/доступа из Google Sheets
    await load_runtime_settings()  # ссылка на сайт из /addhome (если уже задавалась)
    asyncio.create_task(_refresh_users_loop())  # держит кэш в актуальном состоянии, пока бот жив

    await _start_healthcheck_server()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
