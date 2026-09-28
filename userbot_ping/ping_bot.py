"""
Юзербот-пингер.

Логинится в ТВОЙ личный Telegram-аккаунт (через официальный Telegram API, тот же
способ, которым работают официальные клиенты) и раз в 10 минут шлёт команду /ping
в личку боту — чтобы бот не засыпал на бесплатном хостинге с отключением по
неактивности.

ВАЖНО:
1. api_id/api_hash — это как пароль от аккаунта, не выкладывай их никуда публично.
2. Первый запуск попросит номер телефона, код из Telegram (и пароль двухфакторки,
   если она включена) — после этого создастся файл ping_session.session, и повторный
   вход больше не понадобится. Держи этот файл тоже в секрете — он даёт доступ к
   аккаунту без пароля.
3. Этот скрипт НЕЛЬЗЯ запускать на том же бесплатном хостинге, что и сам бот — если
   хостинг заснёт, заснёт и пингер, пинговать станет некому. Запускай на своём ПК
   (который постоянно включён), на отдельном always-on сервисе, или на любом другом
   месте, которое не засыпает.
4. Если бот засыпает у хостинга именно по неактивности HTTP-порта (Render/Railway
   free tier и т.п.) — одного /ping в личку может быть недостаточно, там нужен
   отдельный внешний HTTP-пинг (см. HEALTHCHECK_PORT в config.py бота + сервис вроде
   UptimeRobot/cron-job.org).
"""
import asyncio

from telethon import TelegramClient

API_ID = 31063656
API_HASH = "45f6b278605b45ff90db200547b3387e"

# Юзернейм бота БЕЗ "@". Проверь, что это точно актуальный юзернейм — при желании
# можно передать TelegramID бота вместо юзернейма (7963460886), Telethon поймёт оба.
BOT_USERNAME = "brleader_bot"

PING_INTERVAL_SECONDS = 10 * 60  # 10 минут

client = TelegramClient("ping_session", API_ID, API_HASH)


async def ping_loop() -> None:
    print("Юзербот-пингер запущен. Буду слать /ping в личку боту каждые 10 минут.")
    while True:
        try:
            await client.send_message(BOT_USERNAME, "/ping")
            print("Отправлен /ping")
        except Exception as e:
            print(f"Ошибка при отправке /ping: {e}")
        await asyncio.sleep(PING_INTERVAL_SECONDS)


async def main() -> None:
    await client.start()  # при первом запуске попросит номер телефона + код
    await ping_loop()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
