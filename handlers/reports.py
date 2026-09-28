from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InputMediaPhoto

from config import Role, ALL_ORGS, SENIOR_GROUPS
from utils.access import get_user, all_users
from keyboards.menus import orgs_kb, nick_list_kb, back_kb, cancel_kb
from services.sheets import get_sheets, run

router = Router(name="reports")


def _visible_orgs(viewer) -> list[str]:
    if viewer.role >= Role.LEADERSHIP:
        return ALL_ORGS
    if viewer.role == Role.SENIOR_WATCHER:
        return SENIOR_GROUPS.get(viewer.org, [])
    if viewer.org:
        return [viewer.org]
    return []


@router.callback_query(F.data == "admin_view_norms")
async def cb_view_norms_start(callback: CallbackQuery):
    viewer = get_user(callback.from_user.id)
    if not viewer or viewer.role < Role.LEADER:
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    orgs = _visible_orgs(viewer)
    if not orgs:
        await callback.answer("Нет доступных организаций", show_alert=True)
        return

    if len(orgs) == 1:
        await _show_nick_list(callback, orgs[0])
        return

    await callback.message.edit_text(
        "По какой организации посмотреть отчётности?", reply_markup=orgs_kb("view_norms_org", orgs)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("view_norms_org:"))
async def cb_view_norms_org(callback: CallbackQuery):
    org = callback.data.split(":", 1)[1]
    await _show_nick_list(callback, org)


async def _show_nick_list(callback: CallbackQuery, org: str) -> None:
    nicks = sorted({u.nickname for u in all_users() if u.org == org and u.nickname})
    if not nicks:
        await callback.message.edit_text(f"В организации «{org}» пока никого нет.", reply_markup=back_kb())
        await callback.answer()
        return
    await callback.message.edit_text(
        f"Отчётности — {org}.\nВыберите сотрудника:", reply_markup=nick_list_kb("view_norms_nick", nicks)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("view_norms_nick:"))
async def cb_view_norms_nick(callback: CallbackQuery, bot: Bot):
    nick = callback.data.split(":", 1)[1]
    sheets = get_sheets()
    reports = await run(sheets.get_reports_for, nick)

    if not reports:
        await callback.message.edit_text(f"У {nick} пока нет сданных отчётов.", reply_markup=back_kb())
        await callback.answer()
        return

    await callback.message.edit_text(f"Последние отчёты — {nick} (найдено: {len(reports)}):", reply_markup=back_kb())
    await callback.answer()

    for r in reports:
        caption = (
            f"1. NickName пользователя: {r.get('NickName')}\n"
            f"2. Дата который был сдан отчет: {r.get('ReportDate')}\n"
            f"3. Статус норматива: {r.get('Status')}\n"
            f"4. Какие работы были выполнены: {r.get('WorksDone')}"
        )
        file_ids = [f for f in (r.get("PhotoFileIDs") or "").split(",") if f]
        if not file_ids:
            await callback.message.answer(caption)
            continue
        try:
            media = [
                InputMediaPhoto(media=fid, caption=caption if i == 0 else None)
                for i, fid in enumerate(file_ids[:10])
            ]
            await bot.send_media_group(callback.from_user.id, media=media)
        except Exception:
            await callback.message.answer(caption)
