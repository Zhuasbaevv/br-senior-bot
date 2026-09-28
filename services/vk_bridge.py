"""
Клиент для внутреннего API VK-бота модерации (vk_moderation_bot) — шлёт туда
объявления о назначениях ролей и наказаниях/баллах, чтобы VK-бот разослал их
в нужные "инфо-беседы" (см. bot_app/announce_server.py в том проекте).

Используется и из Telegram-бота (handlers/grant_role.py, points_punish.py), и
из сайта (webapp/app.py) — поэтому вынесен сюда как общий модуль, а не
продублирован в обоих местах.

Мост не обязателен: если VK_BOT_API_URL/SITE_BRIDGE_SECRET не заданы —
функция просто ничего не делает (без ошибок и без блокировки основного
действия — назначение роли/наказания на сайте/в боте должно срабатывать
даже если VK-бот сейчас недоступен или мост ещё не настроен).
"""
from __future__ import annotations

import aiohttp

from config import VK_BOT_API_URL, SITE_BRIDGE_SECRET, ALL_ORGS, SENIOR_GROUPS, Role, ROLE_NAMES


async def _send_announce(orgs: list[str], text: str) -> None:
    if not VK_BOT_API_URL or not SITE_BRIDGE_SECRET:
        print(f"[vk_bridge] пропускаю отправку - VK_BOT_API_URL/SITE_BRIDGE_SECRET не заданы (orgs={orgs})")
        return
    if not orgs:
        print(f"[vk_bridge] пропускаю отправку - пустой список организаций (текст: {text[:60]!r})")
        return
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(
                f"{VK_BOT_API_URL}/internal/announce",
                json={"orgs": orgs, "text": text},
                headers={"X-Bridge-Secret": SITE_BRIDGE_SECRET},
            ) as resp:
                body = await resp.text()
                print(f"[vk_bridge] POST {VK_BOT_API_URL}/internal/announce orgs={orgs} -> {resp.status} {body[:200]}")
    except Exception as e:
        # Мост — не критичный путь: если VK-бот сейчас недоступен, назначение
        # роли/наказания на сайте/в Telegram-боте всё равно должно применяться.
        print(f"[vk_bridge] ОШИБКА при отправке в VK-бот: {e!r}")


def _orgs_for_role_scope(role: Role, org_or_group: str | None) -> list[str]:
    """Какие организации должны увидеть объявление, в зависимости от
    НОВОЙ роли: Лидер/Следящий — только своя организация, Старший следящий —
    всё направление, Руководство (и выше) — все организации."""
    if role >= Role.LEADERSHIP:
        return ALL_ORGS
    if role == Role.SENIOR_WATCHER:
        # org_or_group здесь — название направления (ключ SENIOR_GROUPS), а не
        # конкретной организации — так же, как это уже используется в
        # handlers/grant_role.py при выдаче роли "Старший следящий".
        return SENIOR_GROUPS.get(org_or_group, [])
    if role in (Role.WATCHER, Role.LEADER) and org_or_group:
        return [org_or_group]
    return []


async def announce_role_assigned(nickname: str, vk_id: int | None, role: Role, org_or_group: str | None) -> None:
    role_title = ROLE_NAMES.get(role, "")
    orgs = _orgs_for_role_scope(role, org_or_group)
    if not orgs:
        return

    who = f"@id{vk_id}({nickname})" if vk_id else nickname
    scope_word = "направлением" if role == Role.SENIOR_WATCHER else "организацией" if role != Role.LEADERSHIP else None

    if role == Role.LEADERSHIP:
        text = f"@all {who} был(а) назначен(а) на должность «{role_title}».\nПоздравим его(её) во FLOOD."
    else:
        text = (
            f"@all {who} был(а) назначен(а) на должность «{role_title}» "
            f"за «{org_or_group}» {scope_word}.\nПоздравим его(её) во FLOOD."
        )
    await _send_announce(orgs, text)


async def announce_punishment(nickname: str, vk_id: int | None, org: str | None, punishment_type: str, reason: str) -> None:
    if not org:
        return
    who = f"@id{vk_id}({nickname})" if vk_id else nickname
    text = f'{who} получает "{punishment_type}".\nПричина: {reason or "-"}'
    await _send_announce([org], text)


async def announce_points(nickname: str, vk_id: int | None, org: str | None, amount: float, reason: str = "") -> None:
    if not org:
        return
    who = f"@id{vk_id}({nickname})" if vk_id else nickname
    amount_num = int(amount) if float(amount).is_integer() else amount
    sign = "+" if amount_num >= 0 else ""
    text = f"{who} получает {sign}{amount_num} баллов."
    if reason:
        text += f"\nПричина: {reason}"
    await _send_announce([org], text)
