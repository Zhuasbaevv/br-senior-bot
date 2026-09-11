from __future__ import annotations

import datetime as dt

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Role, PUNISHMENT_SHEET_COL
from utils.access import get_user, all_users, role_name
from keyboards.menus import cancel_kb, admin_panel_kb, yes_no_kb, back_kb
from states import DecisionReasonFlow
from services.sheets import get_sheets, run

router = Router(name="review")

_TYPE_LABELS = {
    "extra_work": "Доп работа",
    "inactive": "Неактив",
    "remove_punish": "Снятие наказаний",
}


def _visible_applications(admin_org, admin_role, apps: list[dict]) -> list[dict]:
    if admin_role >= Role.LEADERSHIP:
        return apps
    visible_nicks = {u.nickname for u in all_users() if u.org == admin_org} if admin_org else set()
    return [a for a in apps if a.get("NickName") in visible_nicks]


@router.callback_query(F.data == "admin_reports")
async def cb_applications_root(callback: CallbackQuery):
    admin = get_user(callback.from_user.id)
    sheets = get_sheets()
    counts = {}
    for t in _TYPE_LABELS:
        pending = await run(sheets.get_pending_applications, t)
        pending = _visible_applications(admin.org, admin.role, pending)
        counts[t] = len(pending)

    b = InlineKeyboardBuilder()
    b.button(text=f"Доп работа {counts['extra_work']}", callback_data="apps_list:extra_work")
    b.button(text=f"Неактив {counts['inactive']}", callback_data="apps_list:inactive")
    b.button(text=f"Снятие наказаний {counts['remove_punish']}", callback_data="apps_list:remove_punish")
    b.row(cancel_kb().inline_keyboard[0][0])
    b.adjust(1, 2, 1)
    await callback.message.edit_text("Выберите категорию заявок:", reply_markup=b.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("apps_list:"))
async def cb_apps_list(callback: CallbackQuery):
    app_type = callback.data.split(":", 1)[1]
    admin = get_user(callback.from_user.id)
    sheets = get_sheets()
    pending = await run(sheets.get_pending_applications, app_type)
    pending = _visible_applications(admin.org, admin.role, pending)

    if not pending:
        await callback.message.edit_text("Заявок нет.", reply_markup=back_kb())
        await callback.answer()
        return

    b = InlineKeyboardBuilder()
    for a in pending:
        label = f"{a.get('NickName')} | {a.get('Data', '')[:40]}"
        b.button(text=label, callback_data=f"apps_view:{a['ID']}")
    b.row(cancel_kb().inline_keyboard[0][0])
    b.adjust(1)
    await callback.message.edit_text(f"Заявки — {_TYPE_LABELS[app_type]}:", reply_markup=b.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("apps_view:"))
async def cb_apps_view(callback: CallbackQuery):
    app_id = callback.data.split(":", 1)[1]
    sheets = get_sheets()
    all_pending = await run(sheets.get_pending_applications)
    app = next((a for a in all_pending if str(a["ID"]) == str(app_id)), None)
    if not app:
        await callback.answer("Заявка не найдена или уже обработана", show_alert=True)
        return

    target = next((u for u in all_users() if u.nickname == app.get("NickName")), None)
    org = target.org if target else "—"
    role = role_name(target.role) if target else "—"
    app_type = app.get("Type")
    data_raw = app.get("Data", "") or ""

    # Для доп.работы в Data лежит "описание|file_id,file_id,..." — раньше сырой file_id
    # (нечитаемый набор символов) просто выводился текстом вместо самого скрина.
    # Показываем описание текстом, а сами скрины шлём отдельным альбомом ниже.
    photo_file_ids: list[str] = []
    if app_type == "extra_work":
        work, _, proof = data_raw.partition("|")
        photo_file_ids = [f for f in proof.split(",") if f]
        data_line = work or "—"
    else:
        data_line = data_raw

    text = (
        f"1. NickName пользователя: {app.get('NickName')}\n"
        f"2. Тип заявки: {_TYPE_LABELS.get(app_type, app_type)}\n"
        f"3. Данные: {data_line}\n"
        f"4. Фракция: {org}\n"
        f"5. Должность: {role}\n"
        f"6. Подана: {app.get('CreatedAt')}"
    )
    await callback.message.edit_text(text, reply_markup=yes_no_kb("apps", app_id))

    if photo_file_ids:
        try:
            from aiogram.types import InputMediaPhoto
            media = [InputMediaPhoto(media=fid) for fid in photo_file_ids[:10]]
            await callback.message.answer_media_group(media=media)
        except Exception as e:
            print(f"[WARNING] Не удалось показать скрины доп.работы для заявки #{app_id}: {e}")

    await callback.answer()


@router.callback_query(F.data.startswith("apps_approve:"))
async def cb_apps_approve(callback: CallbackQuery, bot: Bot):
    app_id = callback.data.split(":", 1)[1]
    admin = get_user(callback.from_user.id)
    sheets = get_sheets()
    app = await run(sheets.decide_application, int(app_id), "approved", admin.nickname)
    if not app:
        await callback.answer("Не найдено", show_alert=True)
        return

    target = next((u for u in all_users() if u.nickname == app.get("NickName")), None)
    app_type = app.get("Type")
    data_raw = app.get("Data", "")
    nick = app.get("NickName", "?")

    if app_type == "extra_work":
        work = data_raw.split("|", 1)[0]
        proof = data_raw.split("|", 1)[-1] if "|" in data_raw else ""
        work_date = (app.get("CreatedAt") or "").split()[0] or "—"
        if target:
            await sheets.log_extra_work(target.nickname, admin.nickname, work, proof)
        target_msg = f"Ваша заявка на доп.работу под номером #{app_id} была одобрена администратором {admin.nickname}."
        admin_msg = f"✅️Доп работа {nick} за {work_date} была одобрена."
    elif app_type == "inactive":
        dates_part = data_raw.split("|", 1)[0]
        start_str, _, end_str = dates_part.partition("/")
        if target:
            try:
                start_date = dt.datetime.strptime(start_str.strip(), "%d.%m.%Y").date()
                end_date = dt.datetime.strptime(end_str.strip(), "%d.%m.%Y").date()
                if end_date < start_date:
                    start_date, end_date = end_date, start_date
                day = start_date
                while day <= end_date:
                    # Отмечаем "-" в клетке дня (не считается в сумму баллов) и +1 к счётчику
                    # "Дни неактив/нет нормы" (P) — на листе той недели, к которой относится день
                    # (период неактива может захватывать сразу несколько недель).
                    await run(sheets.mark_inactive_day, target.nickname, day)
                    day += dt.timedelta(days=1)
            except ValueError:
                print(f"[WARNING] Не удалось разобрать даты неактива в заявке #{app_id}: '{dates_part}'")
        target_msg = f"Ваша заявка на неактив под номером #{app_id} была одобрена администратором {admin.nickname}"
        admin_msg = f"✅️Неактив {nick} за {dates_part} была одобрена."
    elif app_type == "remove_punish":
        ptype, proof = (data_raw.split("|", 1) + [""])[:2]
        if target:
            row_idx = await run(sheets.find_nick_row, target.nickname)
            col = PUNISHMENT_SHEET_COL.get(ptype)
            if row_idx and col:
                await run(sheets.change_punishment_count, row_idx, col, -1)
            await sheets.log_punishment_remove(target.nickname, ptype, "system", admin.nickname, proof)
        target_msg = f"Ваша заявка на снятие наказаний под номером #{app_id} была одобрена администратором {admin.nickname}"
        admin_msg = f"✅️Заявка на снятие {ptype} {nick} была одобрена."
    else:
        target_msg = f"Ваша заявка #{app_id} была одобрена администратором {admin.nickname}"
        admin_msg = f"✅️Заявка #{app_id} одобрена."

    if target:
        try:
            await bot.send_message(target.telegram_id, target_msg)
        except Exception:
            pass

    await sheets.log_moderation(admin.nickname, f"approve_{app_type}", nick, f"#{app_id}: {data_raw}")
    await callback.message.edit_text(admin_msg, reply_markup=admin_panel_kb(admin.role))
    await callback.answer()


@router.callback_query(F.data.startswith("apps_reject:"))
async def cb_apps_reject(callback: CallbackQuery, state: FSMContext):
    app_id = callback.data.split(":", 1)[1]
    await state.update_data(reject_app_id=app_id)
    await state.set_state(DecisionReasonFlow.waiting_reason)
    await callback.message.edit_text("Напишите причину отказа:", reply_markup=back_kb())
    await callback.answer()


@router.message(DecisionReasonFlow.waiting_reason)
async def apps_reject_reason(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    app_id = data["reject_app_id"]
    reason = message.text.strip()
    await state.clear()

    admin = get_user(message.from_user.id)
    sheets = get_sheets()
    app = await run(sheets.decide_application, int(app_id), "rejected", admin.nickname, reason)
    if not app:
        await message.answer("Заявка не найдена.", reply_markup=admin_panel_kb(admin.role))
        return

    target = next((u for u in all_users() if u.nickname == app.get("NickName")), None)
    app_type = app.get("Type")
    data_raw = app.get("Data", "")
    nick = app.get("NickName", "?")

    if app_type == "extra_work":
        work_date = (app.get("CreatedAt") or "").split()[0] or "—"
        target_msg = (
            f"Ваша заявка на доп.работу под номером #{app_id} была отказана администратором "
            f"{admin.nickname}\n\nПричина отказа: {reason}"
        )
        admin_msg = f"❌️Доп работа {nick} за {work_date} была отказана.\n\nПричина отказа: {reason}"
    elif app_type == "inactive":
        dates_part = data_raw.split("|", 1)[0]
        target_msg = (
            f"Ваша заявка на неактив под номером #{app_id} была отказана администратором "
            f"{admin.nickname}\n\nПричина отказа: {reason}"
        )
        admin_msg = f"❌️Неактив {nick} за {dates_part} была отказана.\n\nПричина отказа: {reason}"
    elif app_type == "remove_punish":
        ptype = data_raw.split("|", 1)[0]
        target_msg = (
            f"Ваша заявка на снятие наказаний под номером #{app_id} была отказана администратором "
            f"{admin.nickname}\n\nПричина отказа: {reason}"
        )
        admin_msg = f"❌️Заявка на снятие {ptype} {nick} была отказана.\n\nПричина отказа: {reason}"
    else:
        target_msg = f"Ваша заявка #{app_id} была отказана администратором {admin.nickname}\n\nПричина отказа: {reason}"
        admin_msg = f"❌️Заявка #{app_id} отклонена.\n\nПричина отказа: {reason}"

    if target:
        try:
            await bot.send_message(target.telegram_id, target_msg)
        except Exception:
            pass

    await sheets.log_moderation(admin.nickname, f"reject_{app_type}", nick, f"#{app_id}: {reason}")
    await message.answer(admin_msg, reply_markup=admin_panel_kb(admin.role))
