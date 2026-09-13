from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from config import PUNISHMENT_SHEET_COL
from utils.access import get_user, all_users, role_name
from keyboards.menus import cancel_kb, admin_panel_kb, give_remove_kb, punishment_types_kb, nick_list_kb
from states import PointsFlow, PunishmentFlow
from services.sheets import get_sheets, run

router = Router(name="points_punish")


def _find_target(nick: str):
    return next((u for u in all_users() if u.nickname == nick), None)


# ============================================================ БАЛЛЫ
@router.callback_query(F.data == "user_points")
async def cb_user_points(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PointsFlow.waiting_amount)
    await callback.message.edit_text(
        'Укажите сколько баллов надо добавить или минусировть к этому пользователю.\n\nНапример "+100" или "-100":',
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(PointsFlow.waiting_amount)
async def points_amount(message: Message, state: FSMContext):
    text = message.text.strip().replace(" ", "")
    try:
        amount = float(text)
    except ValueError:
        await message.answer('Неверный формат. Пример: "+100" или "-100"', reply_markup=cancel_kb())
        return
    await state.update_data(amount=amount)
    await state.set_state(PointsFlow.waiting_reason)
    await message.answer("Укажите причину:", reply_markup=cancel_kb())


@router.message(PointsFlow.waiting_reason)
async def points_reason(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    amount = data["amount"]
    reason = message.text.strip()
    target_nick = data.get("active_target_nick")
    await state.clear()

    admin = get_user(message.from_user.id)
    target = _find_target(target_nick)
    if not target:
        await message.answer("Пользователь не найден.", reply_markup=admin_panel_kb(admin.role))
        return

    sheets = get_sheets()
    row_idx = await run(sheets.find_nick_row, target.nickname)
    if not row_idx:
        await message.answer(
            f"⚠️ Не нашёл {target.nickname} в текущей таблице (лист мог обновиться) — баллы не изменены.",
            reply_markup=admin_panel_kb(admin.role),
        )
        return
    old, new = await run(sheets.add_points, row_idx, amount)
    await sheets.log_points(target.nickname, admin.nickname, amount, old, new, reason)

    await message.answer(
        f"✅️Вы успешно изменили количество баллов пользователя {target.nickname} на {amount}.\n\n"
        f"Старое значение: {old}\nПричина: {reason}",
        reply_markup=admin_panel_kb(admin.role),
    )
    try:
        await bot.send_message(
            target.telegram_id,
            f"Администратор {admin.nickname} изменил ваше количество баллов на {amount}.\n"
            f"Старое значение: {old}\nПричина: {reason}",
        )
    except Exception:
        pass


# ============================================================ НАКАЗАНИЯ
@router.callback_query(F.data == "user_punish")
async def cb_user_punish(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PunishmentFlow.waiting_action)
    await callback.message.edit_text("Выберите действие:", reply_markup=give_remove_kb())
    await callback.answer()


@router.callback_query(PunishmentFlow.waiting_action, F.data.in_({"punish_give", "punish_remove"}))
async def punish_pick_action(callback: CallbackQuery, state: FSMContext):
    action = "give" if callback.data == "punish_give" else "remove"
    await state.update_data(punish_action=action)
    await state.set_state(PunishmentFlow.waiting_type)
    await callback.message.edit_text("Выберите тип наказания:", reply_markup=punishment_types_kb("punish_type"))
    await callback.answer()


@router.callback_query(PunishmentFlow.waiting_type, F.data.startswith("punish_type:"))
async def punish_pick_type(callback: CallbackQuery, state: FSMContext):
    ptype = callback.data.split(":", 1)[1]
    data = await state.get_data()
    target_nick = data.get("active_target_nick")

    if target_nick:
        # действие уже выполняется над конкретным пользователем (пришли из карточки статистики)
        await state.update_data(punish_type=ptype)
        await state.set_state(PunishmentFlow.waiting_reason)
        await callback.message.edit_text("Напишите причину:", reply_markup=cancel_kb())
        await callback.answer()
        return

    await state.update_data(punish_type=ptype)
    await state.set_state(PunishmentFlow.waiting_user)
    nicks = [u.nickname for u in all_users() if u.nickname]
    await callback.message.edit_text("Укажите пользователя:", reply_markup=nick_list_kb("punish_user", nicks))
    await callback.answer()


@router.callback_query(PunishmentFlow.waiting_user, F.data.startswith("punish_user:"))
async def punish_pick_user(callback: CallbackQuery, state: FSMContext):
    nick = callback.data.split(":", 1)[1]
    await state.update_data(active_target_nick=nick)
    await state.set_state(PunishmentFlow.waiting_reason)
    await callback.message.edit_text("Напишите причину:", reply_markup=cancel_kb())
    await callback.answer()


@router.message(PunishmentFlow.waiting_reason)
async def punish_reason(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    ptype = data["punish_type"]
    action = data["punish_action"]
    target_nick = data["active_target_nick"]
    reason = message.text.strip()
    await state.clear()

    admin = get_user(message.from_user.id)
    target = _find_target(target_nick)
    sheets = get_sheets()

    if target:
        row_idx = await run(sheets.find_nick_row, target.nickname)
        if row_idx:
            col = PUNISHMENT_SHEET_COL[ptype]
            delta = 1 if action == "give" else -1
            await run(sheets.change_punishment_count, row_idx, col, delta)
        else:
            print(f"[WARNING] Не нашёл {target.nickname} в текущей таблице — счётчик наказания не изменён.")

        if action == "give":
            await sheets.log_punishment_issue(target.nickname, admin.nickname, ptype, reason)
        else:
            await sheets.log_punishment_remove(target.nickname, ptype, reason, admin.nickname)

    verb = "выдали" if action == "give" else "сняли"
    await message.answer(
        f"✅️Вы успешно {verb} {ptype} польвателью {target_nick}.\n\nПричина: {reason}",
        reply_markup=admin_panel_kb(admin.role),
    )

    if target:
        try:
            if action == "give":
                await bot.send_message(
                    target.telegram_id,
                    f'Вы получили «{ptype}» от администратора {admin.nickname}, причина: {reason}.',
                )
            else:
                await bot.send_message(
                    target.telegram_id,
                    f"{ptype} был снят администратором {admin.nickname}.\n\nПричина:\n{reason}",
                )
        except Exception:
            pass
