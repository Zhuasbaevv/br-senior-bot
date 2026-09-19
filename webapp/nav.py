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
            NavItem("Удалить пользователя", "/admin/users/remove"),
            NavItem("Список пользователей", "/admin/users"),
            NavItem("Заявки (одобрение)", "/admin/reviews"),
            NavItem("Отчётности", "/admin/reports"),
            NavItem("Сдать фрапс обзвона", "/admin/fraps"),
        ]
        sections.append(("Панель управления", admin))

    if role >= Role.SENIOR_WATCHER:
        logging_ = [
            NavItem("Логирование", "/admin/logs"),
            NavItem("Выдать доступ", "/admin/grant-role"),
        ]
        sections.append(("Логи и доступ", logging_))

    if role >= Role.WATCHER:
        tests = [
            NavItem("Создать тест", "/admin/quizzes/create"),
            NavItem("Результаты тестов", "/admin/quizzes/results"),
        ]
        sections.append(("Тесты", tests))

    if role >= Role.LEADERSHIP:
        leadership = [
            NavItem("Логи модераторов", "/admin/moderation-logs"),
            NavItem("Настройки (NickName/статистика)", "/admin/settings"),
        ]
        sections.append(("Руководство", leadership))

    if role == Role.CREATOR:
        creator = [
            NavItem("Назначить руководство", "/admin/assign-leadership"),
            NavItem("Настроить нормативы", "/admin/norms"),
            NavItem("Создать лист недели", "/admin/create-week-sheet"),
            NavItem("Рассылка (/o)", "/admin/broadcast"),
            NavItem("Текст /info (/setinfo)", "/admin/set-info"),
            NavItem("Диагностика ника (/findnick)", "/admin/find-nick"),
        ]
        sections.append(("Создатель", creator))

    commands = [
        NavItem("Активные участники (/members)", "/tools/members"),
    ]
    if role >= Role.WATCHER:
        commands.append(NavItem("/ip — сравнение IP", "/tools/ip"))
    sections.append(("Инструменты", commands))

    return sections


class RedirectToLogin(Exception):
    def __init__(self, query: str = ""):
        self.query = query


class RedirectToQuiz(Exception):
    """Поднимается, когда человеку назначен непройденный тест — сайт не даёт
    пользоваться ничем, кроме страницы теста, пока он не нажмёт "Готово"."""
    def __init__(self, quiz_id: int):
        self.quiz_id = quiz_id


# Роли, которым тест может быть назначен как обязательный к прохождению — сам
# следящий+ (создатель теста) и выше тест проходить не обязаны, они его создают
# и смотрят результаты. Если требование поменяется — правьте только этот кортеж.
QUIZ_REQUIRED_ROLES = (Role.STAFF, Role.LEADER)

# Пути, которые ДОЛЖНЫ оставаться доступными, даже если на пользователе висит
# непройденный тест — иначе он не смог бы даже открыть сам тест или выйти.
_QUIZ_EXEMPT_PREFIXES = ("/quiz", "/logout", "/static", "/media/tg")


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

    if user.role in QUIZ_REQUIRED_ROLES and not any(
        request.url.path.startswith(p) for p in _QUIZ_EXEMPT_PREFIXES
    ):
        from services.sheets import get_sheets, run
        sheets = get_sheets()
        pending = await run(sheets.pending_quiz_for, user.telegram_id, user.org)
        if pending:
            raise RedirectToQuiz(int(pending["ID"]))

    return user


async def get_optional_user(
    br_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> UserInfo | None:
    telegram_id = read_session_cookie_value(br_session)
    if telegram_id is None:
        return None
    return get_user(telegram_id)
