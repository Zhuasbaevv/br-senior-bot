from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery

from utils.access import get_user, role_name
from services.sheets import get_sheets, run

router = Router(name="stats")


def _vk_link(vk_id: str) -> str:
    vk_id = (vk_id or "").strip()
    if not vk_id:
        return "—"
    if vk_id.startswith("http"):
        return f'<a href="{vk_id}">VK</a>'
    return f'<a href="https://vk.com/id{vk_id}">VK</a>'


def _discord_link(discord_id: str) -> str:
    discord_id = (discord_id or "").strip()
    if not discord_id:
        return "—"
    return f'<a href="https://discordapp.com/users/{discord_id}/">Открыть</a>'


def _forum_link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return "—"
    return f'<a href="{url}">Forum</a>'


async def render_stats_text(telegram_id: int) -> str:
    user = get_user(telegram_id)
    sheets = get_sheets()
    profile = await run(sheets.get_user_row, telegram_id)
    profile = profile or {}

    stat = {}
    if user:
        # Свежий поиск строки по нику, а не user.row из кэша — кэш может быть устаревшим
        # (например, сразу после создания нового листа недели), из-за чего наказания/баллы
        # в самом боте показывали 0, хотя в таблице всё было верно.
        row_idx = await run(sheets.find_nick_row, user.nickname)
        if row_idx:
            stat = await run(sheets.get_stat_by_row, row_idx)

    added_by = profile.get("AddedBy", "—")
    added_date = profile.get("AddedDate") or stat.get("Дата назначения", "—")
    total_days = stat.get("Общее количество дней", "0")
    points = stat.get("Баллы", "0")
    strict = stat.get("Строгие выговоры", "0")
    warns = stat.get("Предупреждения", "0")
    verbal = stat.get("Устные выговоры", "0")

    # У создателя в таблице может лежать что угодно в ячейке "Должность" (например,
    # дефолт шаблона той строки, куда его вписали вручную) — показываем роль честно,
    # а не то, что случайно осталось в таблице.
    from config import Role
    position = role_name(Role.CREATOR) if (user and user.role == Role.CREATOR) else stat.get("Должность", "—")

    text = (
        "👱‍♂️ Моя статистика\n\n"
        "📌 Основная информация:\n"
        "<blockquote>"
        f"┃ Должность: {position}\n"
        f"┃ Добавил: {added_by}\n"
        f"┃ Дата назначения: {added_date}\n"
        f"┃ Общее количество дней: {total_days}\n"
        f"┃ Организация: {user.org if user else '—'}\n"
        f"┃ Возраст: {profile.get('Age', '—')}\n"
        f"┃ Часовой пояс: {profile.get('Timezone', '—')}"
        "</blockquote>\n\n"
        "📞 Контакты:\n"
        "<blockquote>"
        f"┃ ВК: {_vk_link(profile.get('VK', ''))}\n"
        f"┃ Форум: {_forum_link(profile.get('Forum', ''))}\n"
        f"┃ Почта: {profile.get('Email', '—')}\n"
        f"┃ Discord ID: {profile.get('DiscordID', '—')}\n"
        f"┃ Discord (профиль): {_discord_link(profile.get('DiscordID', ''))}\n"
        f"┃ Telegram ID: {telegram_id}\n"
        f"┃ Telegram Username: {profile.get('TelegramUsername', '—')}"
        "</blockquote>\n\n"
        "🏃‍♀️ Успеваемость\n"
        f"<blockquote>┃ Баллы: {points}</blockquote>\n\n"
        "😡 Наказания:\n"
        "<blockquote>"
        f"┃ Выговоры: {strict}\n"
        f"┃ Предупреждения: {warns}\n"
        f"┃ Устники: {verbal}"
        "</blockquote>"
    )
    return text


@router.callback_query(F.data == "menu_stats")
async def cb_stats(callback: CallbackQuery):
    text = await render_stats_text(callback.from_user.id)
    from keyboards.menus import back_kb
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb())
    await callback.answer()
