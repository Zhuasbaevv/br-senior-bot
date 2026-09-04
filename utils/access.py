"""
Кэш ролей/доступа пользователей + проверки прав.

Читать Google Sheets на каждое сообщение слишком медленно, поэтому держим
in-memory кэш {telegram_id: {role, org, nickname, row}}, который обновляется
при выдаче/снятии доступа и лениво подгружается при старте.
"""
from __future__ import annotations

from dataclasses import dataclass

from config import Role, ROLE_NAMES, CREATOR_ID, CREATOR_NICK
from services.sheets import get_sheets, run


@dataclass
class UserInfo:
    telegram_id: int
    nickname: str
    role: Role
    org: str | None
    row: int | None  # строка в основном листе "Список"


_cache: dict[int, UserInfo] = {}


async def load_all_users() -> None:
    """Полная перезагрузка кэша из листа 'Пользователи'. Вызывать при старте бота."""
    sheets = get_sheets()
    records = await run(sheets.list_users)
    _cache.clear()
    for r in records:
        try:
            tid = int(r["TelegramID"])
        except (KeyError, ValueError):
            continue
        role_str = r.get("Role", "")
        role = next((rl for rl in Role if ROLE_NAMES[rl] == role_str), Role.NONE)
        row = None
        nick = r.get("NickName", "")
        if nick:
            row = await run(sheets.find_nick_row, nick)
        _cache[tid] = UserInfo(
            telegram_id=tid,
            nickname=nick,
            role=role,
            org=r.get("Org") or None,
            row=row,
        )
    _cache[CREATOR_ID] = UserInfo(
        telegram_id=CREATOR_ID,
        nickname=CREATOR_NICK,
        role=Role.CREATOR,
        org=None,
        row=None,
    )


def get_user(telegram_id: int) -> UserInfo | None:
    if telegram_id == CREATOR_ID:
        return _cache.get(CREATOR_ID)
    return _cache.get(telegram_id)


def has_access(telegram_id: int) -> bool:
    return get_user(telegram_id) is not None


def set_user(telegram_id: int, nickname: str, role: Role, org: str | None, row: int | None = None) -> None:
    _cache[telegram_id] = UserInfo(telegram_id, nickname, role, org, row)


def remove_user(telegram_id: int) -> None:
    _cache.pop(telegram_id, None)


def all_users() -> list[UserInfo]:
    return list(_cache.values())


def users_in_org(org: str) -> list[UserInfo]:
    return [u for u in _cache.values() if u.org == org]


def managers_for_org(org: str) -> list[UserInfo]:
    """Кто должен получать заявки/уведомления по этой организации:
    следящий/старший следящий/руководство/создатель, относящиеся к org."""
    from config import SENIOR_GROUPS

    group_name = None
    for g_name, orgs in SENIOR_GROUPS.items():
        if org in orgs:
            group_name = g_name
            break

    result = []
    for u in _cache.values():
        if u.role >= Role.LEADERSHIP:
            result.append(u)
        elif u.role == Role.SENIOR_WATCHER and u.org == group_name:
            result.append(u)
        elif u.role in (Role.WATCHER, Role.LEADER) and u.org == org:
            result.append(u)
    return result


def role_name(role: Role) -> str:
    return ROLE_NAMES[role]
