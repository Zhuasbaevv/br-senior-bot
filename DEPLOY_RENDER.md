# Деплой на Render

## 1. Переменные окружения (Render → Environment)

Обязательные (без них бот не запустится — упадёт с понятной ошибкой):

| Переменная | Что это |
|---|---|
| `BOT_TOKEN` | Токен бота от @BotFather |
| `CREATOR_ID` | Твой Telegram ID |
| `LOG_CHANNEL_ID` | ID канала логов (с минусом, например `-100...`) |
| `PINGER_TELEGRAM_ID` | ID аккаунта юзербота-пингера |
| `GOOGLE_SHEET_ID` | ID гугл-таблицы (из её URL) |
| `GEMINI_API_KEY` | Ключ Gemini API |

Необязательные (есть безопасные дефолты в коде, менять не обязательно):
`CREATOR_NICK`, `GEMINI_MODEL`, `GEMINI_RPM`, `GEMINI_MAX_CONCURRENCY`, `GOOGLE_CREDENTIALS_PATH`.

`PORT` — Render подставляет сам, руками задавать не нужно.

## 2. credentials.json (сервис-аккаунт Google)

Файл в `.gitignore` — в GitHub он не попадёт. Render для таких файлов не подходят
обычные env-переменные (это JSON, а не одна строка). Используй встроенную фичу
**Render → твой сервис → Environment → Secret Files**:
- Filename: `credentials.json`
- Contents: вставь содержимое своего файла целиком
- Render сам положит его в корень проекта при деплое — путь совпадает с
  `GOOGLE_CREDENTIALS_PATH` (по умолчанию `credentials.json`), ничего в коде менять не надо.

## 3. HTTP-сервер и пинг

Уже добавлено в проект:
- В `main.py` поднимается лёгкий HTTP-сервер (aiohttp, он и так тянется как
  зависимость aiogram — отдельно ставить не нужно) на порту из `PORT`
  (Render передаёт его автоматически), отвечает `ok` на `GET /`.
- Команда `/ping` в самом боте — отвечает только `PINGER_TELEGRAM_ID`.
- `userbot_ping/ping_bot.py` — отдельный скрипт (Telethon), шлёт `/ping` каждые
  10 минут. Держать хостинг «в тонусе» этим способом или через HTTP-пинг (см.
  `userbot_ping/README.md`) — зависит от того, по какому именно триггеру у Render
  засыпает конкретно твой тип сервиса (Web Service usually по HTTP-неактивности).

**Важно для Render**: у Web Service (в отличие от Background Worker) сон именно по
неактивности HTTP-порта — значит тебе, скорее всего, нужен именно внешний HTTP-пинг
на `https://<твой-сервис>.onrender.com/` (например через uptimerobot.com, раз в
10 минут), а не `/ping` в личку боту. `/ping` в личку полезен отдельно как способ
самому вручную/по расписанию проверить, что бот вообще жив и отвечает.
