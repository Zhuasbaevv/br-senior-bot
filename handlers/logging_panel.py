from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery

from config import Role, SHEET_LOG_ACCESS, SHEET_LOG_PUNISH, SHEET_LOG_POINTS, SHEET_LOG_EXTRA, SHEET_LOG_MODERATION
from utils.access import get_user, all_users
from keyboards.menus import logging_menu_kb, nick_list_kb, back_kb
from services.sheets import get_sheets, run

router = Router(name="logging_panel")

_LOG_SHEET_BY_KEY = {
    "logs_access": SHEET_LOG_ACCESS,
    "logs_punish": SHEET_LOG_PUNISH,
    "logs_points": SHEET_LOG_POINTS,
    "logs_extra": SHEET_LOG_EXTRA,
}


@router.callback_query(F.data == "admin_logging")
async def cb_logging_menu(callback: CallbackQuery):
    admin = get_user(callback.from_user.id)
    if admin.role < Role.SENIOR_WATCHER:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.message.edit_text("Логирование:", reply_markup=logging_menu_kb())
    await callback.answer()


@router.callback_query(F.data.in_(_LOG_SHEET_BY_KEY.keys()))
async def cb_pick_log_type(callback: CallbackQuery):
    nicks = sorted({u.nickname for u in all_users() if u.nickname})
    await callback.message.edit_text(
        "Укажите пользователя:", reply_markup=nick_list_kb(f"log_show:{callback.data}", nicks)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("log_show:"))
async def cb_show_logs(callback: CallbackQuery):
    _, log_key, nick = callback.data.split(":", 2)
    sheet_name = _LOG_SHEET_BY_KEY[log_key]
    sheets = get_sheets()
    logs = await run(sheets.get_logs_for, sheet_name, nick)

    if not logs:
        await callback.message.edit_text(f"Логов по {nick} не найдено.", reply_markup=back_kb())
        await callback.answer()
        return

    parts = []
    for i, log in enumerate(logs, start=1):
        lines = "\n".join(f"{k}: {v}" for k, v in log.items() if v not in ("", None))
        parts.append(f"Лог {i}\n<blockquote>{lines}</blockquote>")

    text = "\n\n".join(parts)
    if len(text) > 4000:
        text = text[:3990] + "\n…(обрезано)"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb())
    await callback.answer()


# ============================================================ Логи модераторов (руководство+)
@router.callback_query(F.data == "admin_moderation_logs")
async def cb_moderation_logs(callback: CallbackQuery):
    admin = get_user(callback.from_user.id)
    if admin.role < Role.LEADERSHIP:
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    sheets = get_sheets()
    ws = await run(sheets.ws, SHEET_LOG_MODERATION)
    records = await run(ws.get_all_records)
    records = records[-20:]  # последние 20 записей

    if not records:
        await callback.message.edit_text("Логов пока нет.", reply_markup=back_kb())
        await callback.answer()
        return

    lines = []
    for r in records:
        lines.append(
            f"{r.get('DateTime')} — {r.get('ActorNick')} → {r.get('Action')} → {r.get('TargetNick')} "
            f"({r.get('Details')})"
        )
    text = "🗂 Логи модераторов (последние 20):\n\n" + "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…(обрезано)"
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()
