"""
Настройки, которые задаются командами в рантайме (а не через переменные окружения)
и должны переживать перезапуск бота — храним в листе "Настройки" (services/sheets.py),
но держим горячую копию в памяти, чтобы не ходить в Google Sheets на каждый рендер
кнопки/меню.
"""
from __future__ import annotations

from services.sheets import get_sheets, run

_cache: dict[str, str] = {}

WEBAPP_URL_KEY = "webapp_url"


async def load_runtime_settings() -> None:
    """Вызывать один раз при старте бота (после load_all_users())."""
    sheets = get_sheets()
    value = await run(sheets.get_setting, WEBAPP_URL_KEY)
    if value:
        _cache[WEBAPP_URL_KEY] = value


def get_webapp_url() -> str:
    """Ссылка на сайт: из /addhome (в памяти после load_runtime_settings), иначе
    из переменной окружения WEBAPP_URL как запасной вариант."""
    if WEBAPP_URL_KEY in _cache:
        return _cache[WEBAPP_URL_KEY]
    from config import WEBAPP_URL
    return WEBAPP_URL


async def set_webapp_url(url: str) -> None:
    url = url.strip().rstrip("/")
    sheets = get_sheets()
    await run(sheets.set_setting, WEBAPP_URL_KEY, url)
    _cache[WEBAPP_URL_KEY] = url
