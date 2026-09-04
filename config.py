"""
Конфигурация бота BR | Server Manager.
"""
from __future__ import annotations

import os
from enum import IntEnum
from zoneinfo import ZoneInfo

# ------------------------------------------------------------------
# Основные настройки
# ------------------------------------------------------------------
# Секретные значения — токен, ID, ключи — БЕЗ дефолтов в коде: если переменная
# окружения не задана на Render, бот честно падает при старте, а не тихо работает
# со старым/чужим значением, зашитым прямо в исходники (которые могут попасть на
# GitHub). Настрой все переменные ниже в Render → Environment.
def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Не задана переменная окружения {name}! Добавь её в Render → Environment.")
    return value


BOT_TOKEN = _require_env("BOT_TOKEN")
CREATOR_ID = int(_require_env("CREATOR_ID"))
CREATOR_NICK = os.getenv("CREATOR_NICK", "Tommy_Card")
LOG_CHANNEL_ID = _require_env("LOG_CHANNEL_ID")

# Телеграм-аккаунт юзербота-пингера (см. userbot_ping/) — только ему отвечает /ping,
# чтобы держать бота "живым" на бесплатном хостинге с отключением по неактивности.
PINGER_TELEGRAM_ID = int(_require_env("PINGER_TELEGRAM_ID"))

# Порт для встроенного HTTP-хелсчека (см. main.py) — нужен только если твой хостинг
# засыпает по неактивности именно HTTP-порта (Render, Railway и т.п.), а не по
# отсутствию Telegram-сообщений. Render сам подставляет PORT — дефолт тут не секрет,
# это просто запасной порт для локального запуска, поэтому его можно оставить.
HEALTHCHECK_PORT = int(os.getenv("PORT", os.getenv("HEALTHCHECK_PORT", "8080")))

# Публичный адрес веб-панели (домен второго Railway-сервиса) — используется ботом
# для кнопки "🌐 Сайт" в /start и в сообщении /setpassword. Без https:// не нужно —
# добавляем сами. Не обязателен: если не задан, кнопка/ссылка просто не показываются.
WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")

# Общий секрет для внутренних запросов бот -> сайт (например, /setpassword шлёт хэш
# пароля на сайт по HTTP) — должен быть одинаковым в переменных ОБОИХ Railway-сервисов.
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET", "")

# Путь к файлу базы паролей — ТОЛЬКО у сервиса сайта (бот эту переменную не использует).
# Подключи Volume на Railway и укажи путь внутри него, иначе пароли будут слетать
# при каждом передеплое (см. webapp/README.md).
PASSWORD_DB_PATH = os.getenv("PASSWORD_DB_PATH", "webapp_passwords.db")

MSK_TZ = ZoneInfo("Europe/Moscow")

# Google Sheets
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
# Альтернатива файлу — содержимое credentials.json ЦЕЛИКОМ прямо в переменной
# окружения (для хостингов вроде Railway, где нет отдельной загрузки секретных
# файлов через панель, в отличие от Render). Если задано — используется вместо файла.
# ПРЕДПОЧИТАЙ *_BASE64: сырой JSON с переносами строк внутри private_key почти
# гарантированно ломается при вставке в поле на телефоне (переносы/автозамена) —
# base64-строка состоит только из букв/цифр/+//=, её испортить нечем.
GOOGLE_CREDENTIALS_JSON_BASE64 = os.getenv("GOOGLE_CREDENTIALS_JSON_BASE64", "")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
GOOGLE_SHEET_ID = _require_env("GOOGLE_SHEET_ID")

# Gemini (бесплатный тариф) — используется для распознавания отчётов
GEMINI_API_KEY = _require_env("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-3.6-flash")  # не секрет, дефолт ок
# Лимиты бесплатного тарифа Gemini меняются — проверяйте актуальные на
# ai.google.dev/pricing и подстройте эти два числа под свой аккаунт.
GEMINI_RPM = int(os.getenv("GEMINI_RPM", "15"))          # запросов в минуту
GEMINI_MAX_CONCURRENCY = int(os.getenv("GEMINI_MAX_CONCURRENCY", "3"))  # одновременных запросов

# Название листов внутри таблицы
SHEET_MAIN = "17.08.2026 | 23.08.2026"          # основной лист со статистикой (как на скринах)
SHEET_USERS = "Пользователи"    # верификационные данные (VK, Discord, форум, email...)
SHEET_LOG_ACCESS = "Логи_доступа"
SHEET_LOG_PUNISH = "Логи_наказаний"
SHEET_LOG_POINTS = "Логи_баллов"
SHEET_LOG_EXTRA = "Логи_доп_работ"
SHEET_LOG_MODERATION = "Логи_модераторов"
SHEET_LOG_REPORTS = "Логи_отчётов"
SHEET_APPLICATIONS = "Заявки"
SHEET_NORMS = "Нормативы"


# ------------------------------------------------------------------
# Роли (иерархия снизу вверх)
# ------------------------------------------------------------------
class Role(IntEnum):
    NONE = 0            # доступа нет
    STAFF = 1           # Старший состав
    LEADER = 2          # Лидер
    WATCHER = 3         # Следящий (за одной организацией)
    SENIOR_WATCHER = 4  # Старший следящий (за группой организаций: соц/сил/крим)
    LEADERSHIP = 5      # Руководство
    CREATOR = 6         # Создатель


ROLE_NAMES = {
    Role.NONE: "Нет доступа",
    Role.STAFF: "Старший состав",
    Role.LEADER: "Лидер",
    Role.WATCHER: "Следящий",
    Role.SENIOR_WATCHER: "Старший следящий",
    Role.LEADERSHIP: "Руководство",
    Role.CREATOR: "Создатель",
}

# ------------------------------------------------------------------
# Организации и группы (соц / силовые / крим)
# ------------------------------------------------------------------
ORG_ARZAMAS = "Арзамасская ОПГ"
ORG_BATYREVO = "Батыревская ОПГ"
ORG_LYTKARINO = "Лыткаринская ОПГ"
ORG_GOV = "Правительство"
ORG_FSB = "ФСБ"
ORG_UMVD = "УМВД"
ORG_GIBDD = "ГИБДД"
ORG_ARMY = "Армия"
ORG_HOSPITAL = "Больница"
ORG_FSIN = "ФСИН"
ORG_SMI = "СМИ"

ALL_ORGS = [
    ORG_ARZAMAS, ORG_BATYREVO, ORG_LYTKARINO,
    ORG_GOV, ORG_FSB, ORG_UMVD, ORG_GIBDD, ORG_ARMY,
    ORG_HOSPITAL, ORG_FSIN, ORG_SMI,
]

CRIME_ORGS = [ORG_ARZAMAS, ORG_BATYREVO, ORG_LYTKARINO]
POWER_ORGS = [ORG_FSB, ORG_UMVD, ORG_GIBDD, ORG_FSIN, ORG_ARMY]
SOCIAL_ORGS = [ORG_SMI, ORG_HOSPITAL, ORG_GOV]

SENIOR_GROUPS = {
    "Соц организации": SOCIAL_ORGS,
    "Силовые органы": POWER_ORGS,
    "ОПГ": CRIME_ORGS,
}

# Должности внутри блока ОПГ / силовых и т.д. (соответствуют строкам таблицы)
POSITIONS_BY_ORG = {
    ORG_ARZAMAS: ["Положенец", "Положенец", "Положенец", "Смотрящий", "Смотрящий", "Браток"],
    ORG_BATYREVO: ["Положенец", "Положенец", "Положенец", "Смотрящий", "Смотрящий", "Смотрящий"],
    ORG_LYTKARINO: ["Положенец", "Положенец", "Положенец", "Смотрящий", "Смотрящий", "Смотрящий"],
}

PUNISHMENT_TYPES = ["Выговор", "Предупреждение", "Устный выговор"]
PUNISHMENT_SHEET_COL = {
    "Выговор": "L",
    "Предупреждение": "M",
    "Устный выговор": "N",
}

# ------------------------------------------------------------------
# Отчётность: категории активностей и ранги (7/8/9 — пример, расширяемо)
# ------------------------------------------------------------------
ACTIVITY_TYPES = ["vch", "interview", "lecture", "training", "rp"]
ACTIVITY_LABELS = {
    "vch": "Поход на ВЧ",
    "interview": "Собеседование",
    "lecture": "Лекция",
    "training": "Тренировка",
    "rp": "РП ситуация",
}
RANKS = [7, 8, 9]

# Баллы начисляются ОДНИМ статусом на весь день (не по категориям отдельно):
#   Норматив   — норма выполнена ровно (все нужные категории/онлайн закрыты)   -> +3
#   Перенорма  — норма выполнена, и хотя бы что-то сделано сверх неё          -> +6
#   Натяг      — что-то сделано, но норма целиком не закрыта                   -> 0
#   Нет нормы  — отчёт пустой, вообще ничего не распознано                     -> -2
#   Неактив    — выставляется не отчётом, а одобренной заявкой на неактив
#                (см. review.py); баллов не начисляет и не списывает.
REPORT_STATUS_NORM = "Норматив"
REPORT_STATUS_OVER = "Перенорма"
REPORT_STATUS_STRETCH = "Натяг"
REPORT_STATUS_NO_NORM = "Нет нормы"
REPORT_STATUS_INACTIVE = "Неактив"

REPORT_STATUS_POINTS = {
    REPORT_STATUS_NORM: 3,
    REPORT_STATUS_OVER: 6,
    REPORT_STATUS_STRETCH: 0,
    REPORT_STATUS_NO_NORM: -2,
}

# У создателя нет организации/ранга, поэтому под него никогда не настроен реальный
# норматив — без этого он не смог бы протестировать сдачу отчёта вообще (бот всегда
# отвечал бы "норматив не настроен"). Этот норматив подставляется ТОЛЬКО для роли
# CREATOR, когда для его org/rank ничего не найдено — на реальных сотрудников не влияет.
CREATOR_TEST_NORM = {
    "VCH": 0, "Interview": 1, "Lecture": 1, "Training": 1, "RP": 0, "OnlineHours": 0,
}

MIN_MINUTES_BETWEEN_SAME_ACTIVITY = 30  # анти-дубли (тренировка/лекция и т.д.)
