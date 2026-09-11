from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from config import Role, ALL_ORGS, RANKS
from utils.access import get_user
from keyboards.menus import cancel_kb, admin_panel_kb, orgs_kb
from aiogram.utils.keyboard import InlineKeyboardBuilder
from states import SetNormFlow
from services.sheets import get_sheets, run

router = Router(name="norms")


def _ranks_kb() -> "InlineKeyboardBuilder":
    b = InlineKeyboardBuilder()
    for r in RANKS:
        b.button(text=f"Ранг {r}", callback_data=f"norm_rank:{r}")
    b.row(cancel_kb().inline_keyboard[0][0])
    b.adjust(len(RANKS))
    return b.as_markup()


@router.callback_query(F.data == "admin_set_norms")
async def cb_set_norms_start(callback: CallbackQuery, state: FSMContext):
    admin = get_user(callback.from_user.id)
    if admin.role != Role.CREATOR:
        await callback.answer("Только для создателя", show_alert=True)
        return
    await state.set_state(SetNormFlow.waiting_org)
    await callback.message.edit_text("Для какой организации настраиваем норматив?", reply_markup=orgs_kb("norm_org"))
    await callback.answer()


@router.callback_query(SetNormFlow.waiting_org, F.data.startswith("norm_org:"))
async def norm_pick_org(callback: CallbackQuery, state: FSMContext):
    org = callback.data.split(":", 1)[1]
    await state.update_data(norm_org=org)
    await state.set_state(SetNormFlow.waiting_rank)
    await callback.message.edit_text("Для какого ранга?", reply_markup=_ranks_kb())
    await callback.answer()


@router.callback_query(SetNormFlow.waiting_rank, F.data.startswith("norm_rank:"))
async def norm_pick_rank(callback: CallbackQuery, state: FSMContext):
    rank = int(callback.data.split(":", 1)[1])
    await state.update_data(norm_rank=rank)
    await state.set_state(SetNormFlow.waiting_vch)
    await callback.message.edit_text("Сколько походов на ВЧ требуется в норме? (число, 0 если не требуется)", reply_markup=cancel_kb())
    await callback.answer()


def _parse_int(text: str) -> int | None:
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        return None


@router.message(SetNormFlow.waiting_vch)
async def norm_vch(message: Message, state: FSMContext):
    val = _parse_int(message.text)
    if val is None:
        await message.answer("Нужно число. Повторите:", reply_markup=cancel_kb())
        return
    await state.update_data(norm_vch=val)
    await state.set_state(SetNormFlow.waiting_interview)
    await message.answer("Сколько собеседований требуется в норме?", reply_markup=cancel_kb())


@router.message(SetNormFlow.waiting_interview)
async def norm_interview(message: Message, state: FSMContext):
    val = _parse_int(message.text)
    if val is None:
        await message.answer("Нужно число. Повторите:", reply_markup=cancel_kb())
        return
    await state.update_data(norm_interview=val)
    await state.set_state(SetNormFlow.waiting_lecture)
    await message.answer("Сколько лекций требуется в норме?", reply_markup=cancel_kb())


@router.message(SetNormFlow.waiting_lecture)
async def norm_lecture(message: Message, state: FSMContext):
    val = _parse_int(message.text)
    if val is None:
        await message.answer("Нужно число. Повторите:", reply_markup=cancel_kb())
        return
    await state.update_data(norm_lecture=val)
    await state.set_state(SetNormFlow.waiting_training)
    await message.answer("Сколько тренировок требуется в норме?", reply_markup=cancel_kb())


@router.message(SetNormFlow.waiting_training)
async def norm_training(message: Message, state: FSMContext):
    val = _parse_int(message.text)
    if val is None:
        await message.answer("Нужно число. Повторите:", reply_markup=cancel_kb())
        return
    await state.update_data(norm_training=val)
    await state.set_state(SetNormFlow.waiting_rp)
    await message.answer("Сколько РП ситуаций требуется в норме?", reply_markup=cancel_kb())


@router.message(SetNormFlow.waiting_rp)
async def norm_rp(message: Message, state: FSMContext):
    val = _parse_int(message.text)
    if val is None:
        await message.answer("Нужно число. Повторите:", reply_markup=cancel_kb())
        return
    await state.update_data(norm_rp=val)
    await state.set_state(SetNormFlow.waiting_online_hours)
    await message.answer("Сколько часов онлайна требуется в норме? (можно дробное, например 3.5)", reply_markup=cancel_kb())


@router.message(SetNormFlow.waiting_online_hours)
async def norm_online_hours(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", ".")
    try:
        online_hours = float(text)
    except ValueError:
        await message.answer("Нужно число, например 3.5. Повторите:", reply_markup=cancel_kb())
        return

    data = await state.get_data()
    await state.clear()

    sheets = get_sheets()
    await run(
        sheets.set_norm,
        data["norm_org"], data["norm_rank"], data["norm_vch"], data["norm_interview"],
        data["norm_lecture"], data["norm_training"], data["norm_rp"], online_hours,
    )

    admin = get_user(message.from_user.id)
    await message.answer(
        f"✅ Норматив для {data['norm_org']} / ранг {data['norm_rank']} сохранён:\n"
        f"ВЧ: {data['norm_vch']}, Собес: {data['norm_interview']}, Лекции: {data['norm_lecture']}, "
        f"Тренировки: {data['norm_training']}, РП: {data['norm_rp']}, Онлайн: {online_hours}ч",
        reply_markup=admin_panel_kb(admin.role),
    )
