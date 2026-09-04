"""
Структура навигации сайта и зависимости авторизации FastAPI.

nav_sections() ОСОЗНАННО зеркалит логику keyboards/menus.py бота (кто видит какую
кнопку) — один и тот же человек с одной и той же ролью должен видеть одинаковый
набор разделов что в боте, что на сайте.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Request

from config import Role
from utils.access import get_user, UserInfo
from webapp.auth import read_session_cookie_value, SESSION_COOKIE_NAME


@dataclass
class NavItem:
    label: str
    href: str
    ready: bool = True  # False = раздел виден, но функционал ещё не реализован


def nav_sections(role: Role) -> list[tuple[str, list[NavItem]]]:
    """Возвращает [(заголовок группы, [пункты]), ...] — только то, что доступно роли."""
    sections: list[tuple[str, list[NavItem]]] = []

    main = [
        NavItem("Профиль / Статистика", "/profile"),
        NavItem("Заявления", "/applications"),
    ]
    sections.append(("Главное", main))

    if role >= Role.LEADER:
        admin = [
            NavItem("Добавить пользователя", "/admin/users/add"),
            NavItem("Удалить пользователя", "/admin/users/remove", ready=False),
            NavItem("Список пользователей", "/admin/users"),
            NavItem("Заявки (одобрение)", "/admin/reviews", ready=False),
            NavItem("Отчётности", "/admin/reports", ready=False),
            NavItem("Сдать фрапс обзвона", "/admin/fraps", ready=False),
        ]
        sections.append(("Панель управления", admin))

    if role >= Role.SENIOR_WATCHER:
        logging_ = [
            NavItem("Логирование", "/admin/logs", ready=False),
            NavItem("Выдать доступ", "/admin/grant-role", ready=False),
        ]
        sections.append(("Логи и доступ", logging_))

    if role >= Role.LEADERSHIP:
        leadership = [
            NavItem("Логи модераторов", "/admin/moderation-logs", ready=False),
            NavItem("Настройки (NickName/статистика)", "/admin/settings", ready=False),
        ]
        sections.append(("Руководство", leadership))

    if role == Role.CREATOR:
        creator = [
            NavItem("Назначить руководство", "/admin/assign-leadership", ready=False),
            NavItem("Настроить нормативы", "/admin/norms", ready=False),
            NavItem("Создать лист недели", "/admin/create-week-sheet", ready=False),
            NavItem("Рассылка (/o)", "/admin/broadcast", ready=False),
            NavItem("Текст /info (/setinfo)", "/admin/set-info", ready=False),
            NavItem("Диагностика ника (/findnick)", "/admin/find-nick", ready=False),
        ]
        sections.append(("Создатель", creator))

    commands = [
        NavItem("Активные участники (/members)", "/tools/members"),
    ]
    if role >= Role.WATCHER:
        commands.append(NavItem("/ip — сравнение IP", "/tools/ip", ready=False))
    sections.append(("Инструменты", commands))

    return sections


class RedirectToLogin(Exception):
    def __init__(self, query: str = ""):
        self.query = query


async def get_current_user(
    request: Request,
    br_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> UserInfo:
    telegram_id = read_session_cookie_value(br_session)
    if telegram_id is None:
        raise RedirectToLogin()
    user = get_user(telegram_id)
    if user is None:
        # Валидная сессия, но доступ к боту с тех пор сняли — выкидываем на логин.
        raise RedirectToLogin("?revoked=1")
    request.state.user = user
    return user


async def get_optional_user(
    br_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> UserInfo | None:
    telegram_id = read_session_cookie_value(br_session)
    if telegram_id is None:
        return None
    return get_user(telegram_id)
