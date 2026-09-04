from __future__ import annotations

import datetime as dt

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Role, ALL_ORGS, SENIOR_GROUPS, PUNISHMENT_TYPES, MSK_TZ, WEBAPP_URL

CANCEL_BTN = InlineKeyboardButton(text="❌️ Отменить процесс", callback_data="cancel_process")


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[CANCEL_BTN]])


def main_menu_kb(role: Role) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📊 Статистика", callback_data="menu_stats")
    b.button(text="Заявления", callback_data="menu_applications")
    b.adjust(2)
    if role >= Role.LEADER:
        b.row(InlineKeyboardButton(text="🔴 Панель управления", callback_data="menu_admin_panel"))
    if WEBAPP_URL:
        b.row(InlineKeyboardButton(text="🌐 Сайт", url=f"{WEBAPP_URL}/login"))
    return b.as_markup()


def applications_menu_kb() -> InlineKeyboardMarkup:
    today = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y")
    b = InlineKeyboardBuilder()
    b.button(text=f"Отчет {today}", callback_data="app_report")
    b.button(text="Снятие наказаний", callback_data="app_remove_punish")
    b.button(text="Неактив", callback_data="app_inactive")
    b.button(text="Доп баллы", callback_data="app_extra")
    b.button(text="На главную", callback_data="menu_main")
    b.adjust(1)
    return b.as_markup()


def admin_panel_kb(role: Role) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕️ Добавить пользователя", callback_data="admin_add_user")
    b.button(text="➖️ Удалить пользователя", callback_data="admin_remove_user")
    b.button(text="👥️ Список пользователей", callback_data="admin_list_users")
    b.button(text="Заявки", callback_data="admin_reports")
    if role >= Role.LEADER:
        b.button(text="Отчётности", callback_data="admin_view_norms")
        b.button(text="🎥 Сдать фрапс обзвона", callback_data="admin_fraps")
    if role >= Role.SENIOR_WATCHER:
        b.button(text="Логирование", callback_data="admin_logging")
        b.button(text="Выдать доступ", callback_data="admin_grant_role")
        b.button(text="🔑 Сбросить пароль (моё направление)", callback_data="admin_reset_password_scoped")
    if role >= Role.LEADERSHIP:
        b.button(text="Логи модераторов", callback_data="admin_moderation_logs")
    if role == Role.CREATOR:
        b.button(text="Назначить руководство", callback_data="admin_assign_leadership")
        b.button(text="Настроить нормативы", callback_data="admin_set_norms")
        b.button(text="📅 Создать лист недели", callback_data="admin_create_week_sheet")
        b.button(text="🔑 Сбросить пароль (любому)", callback_data="admin_reset_password_any")
    b.button(text="На главную", callback_data="menu_main")
    b.adjust(2)
    return b.as_markup()


def orgs_kb(prefix: str, orgs: list[str] | None = None) -> InlineKeyboardMarkup:
    orgs = orgs or ALL_ORGS
    b = InlineKeyboardBuilder()
    for org in orgs:
        b.button(text=org, callback_data=f"{prefix}:{org}")
    b.row(CANCEL_BTN)
    b.adjust(1)
    return b.as_markup()


def senior_groups_kb(prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for name in SENIOR_GROUPS:
        b.button(text=name, callback_data=f"{prefix}:{name}")
    b.row(CANCEL_BTN)
    b.adjust(1)
    return b.as_markup()


def roles_kb(prefix: str, allow_senior_watcher: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Старший состав", callback_data=f"{prefix}:{Role.STAFF.value}")
    b.button(text="Лидер", callback_data=f"{prefix}:{Role.LEADER.value}")
    b.button(text="Следящий", callback_data=f"{prefix}:{Role.WATCHER.value}")
    if allow_senior_watcher:
        b.button(text="Старший Следящий", callback_data=f"{prefix}:{Role.SENIOR_WATCHER.value}")
    b.row(CANCEL_BTN)
    b.adjust(1)
    return b.as_markup()


def nick_list_kb(prefix: str, nicks: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for nick in nicks:
        b.button(text=nick, callback_data=f"{prefix}:{nick}")
    b.row(CANCEL_BTN)
    b.adjust(1)
    return b.as_markup()


def yes_no_kb(prefix: str, entity_id: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅️Одобрить", callback_data=f"{prefix}_approve:{entity_id}")
    b.button(text="❌️Отказать", callback_data=f"{prefix}_reject:{entity_id}")
    b.adjust(2)
    return b.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Вернуться назад", callback_data="menu_main")]])


def punishment_types_kb(prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in PUNISHMENT_TYPES:
        short = {"Выговор": "Выговор", "Предупреждение": "Пред", "Устный выговор": "Устник"}[t]
        b.button(text=short, callback_data=f"{prefix}:{t}")
    b.row(CANCEL_BTN)
    b.adjust(1)
    return b.as_markup()


def points_punish_actions_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="+/- баллы", callback_data="user_points")
    b.button(text="+/-наказание", callback_data="user_punish")
    b.row(CANCEL_BTN)
    b.adjust(2)
    return b.as_markup()


def give_remove_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Выдать", callback_data="punish_give")
    b.button(text="Снять", callback_data="punish_remove")
    b.row(CANCEL_BTN)
    b.adjust(2)
    return b.as_markup()


def logging_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Логи доступа", callback_data="logs_access")
    b.button(text="Логи наказаний", callback_data="logs_punish")
    b.button(text="Логи баллов", callback_data="logs_points")
    b.button(text="Логи доп работ", callback_data="logs_extra")
    b.row(CANCEL_BTN)
    b.adjust(2)
    return b.as_markup()
