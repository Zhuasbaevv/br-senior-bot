from __future__ import annotations

import datetime as dt

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from config import Role, MSK_TZ, ALL_ORGS, CRIME_ORGS, POWER_ORGS, SOCIAL_ORGS, RANKS
from utils.access import (
    get_user, set_user, remove_user as cache_remove_user, all_users, users_in_org, role_name,
)
from keyboards.menus import (
    admin_panel_kb, cancel_kb, main_menu_kb, orgs_kb, nick_list_kb, back_kb,
    points_punish_actions_kb,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from states import AddUserFlow, RemoveUserFlow, DecisionReasonFlow, FrapsFlow, ResetPasswordFlow
from services.sheets import get_sheets, run

router = Router(name="admin_panel")


def _ranks_kb(prefix: str):
    b = InlineKeyboardBuilder()
    for r in RANKS:
        b.button(text=f"Ранг {r}", callback_data=f"{prefix}:{r}")
    b.row(cancel_kb().inline_keyboard[0][0])
    b.adjust(len(RANKS))
    return b.as_markup()


def _orgs_for(role: Role, org: str | None) -> list[str]:
    if role >= Role.LEADERSHIP:
        return ALL_ORGS
    if role == Role.SENIOR_WATCHER:
        group_map = {"Соц организации": SOCIAL_ORGS, "Силовые органы": POWER_ORGS, "ОПГ": CRIME_ORGS}
        return group_map.get(org, ALL_ORGS)
    if org:
        return [org]
    return ALL_ORGS


@router.callback_query(F.data == "menu_admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or user.role < Role.LEADER:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.message.edit_text("🔴 Панель управления", reply_markup=admin_panel_kb(user.role))
    await callback.answer()


# ============================================================ ДОБАВИТЬ ПОЛЬЗОВАТЕЛЯ
@router.callback_query(F.data == "admin_add_user")
async def cb_add_user_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddUserFlow.waiting_id)
    await callback.message.edit_text("Укажите Telegram ID в формате цифр.", reply_markup=cancel_kb())
    await callback.answer()


@router.message(AddUserFlow.waiting_id)
async def add_user_id(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("Нужны только цифры. Повторите:", reply_markup=cancel_kb())
        return
    await state.update_data(new_id=int(message.text.strip()))
    await state.set_state(AddUserFlow.waiting_nick)
    await message.answer("Укажите его NickName:", reply_markup=cancel_kb())


@router.message(AddUserFlow.waiting_nick)
async def add_user_nick(message: Message, state: FSMContext):
    # \xa0/\u200b — неразрывный/нулевой-ширины пробел, которые изредка прилетают с
    # мобильной автокоррекции и которые .strip() сам по себе не убирает; из-за них
    # бот потом не находил в таблице человека, которого сам же туда и вписал.
    clean_nick = message.text.strip().replace("\xa0", " ").replace("\u200b", "").strip()
    await state.update_data(new_nick=clean_nick)
    admin = get_user(message.from_user.id)
    orgs = _orgs_for(admin.role, admin.org)

    if admin.role in (Role.LEADER, Role.WATCHER):
        # человек автоматически становится старшим составом организации того, кто его добавил
        await state.update_data(new_org=admin.org)
        await state.set_state(AddUserFlow.waiting_rank)
        await message.answer("Укажите ранг сотрудника:", reply_markup=_ranks_kb("add_user_rank"))
        return

    await state.set_state(AddUserFlow.waiting_org)
    await message.answer("Укажите его организацию:", reply_markup=orgs_kb("add_user_org", orgs))


@router.callback_query(AddUserFlow.waiting_org, F.data.startswith("add_user_org:"))
async def add_user_org(callback: CallbackQuery, state: FSMContext):
    org = callback.data.split(":", 1)[1]
    await state.update_data(new_org=org)
    await state.set_state(AddUserFlow.waiting_rank)
    await callback.message.edit_text("Укажите ранг сотрудника:", reply_markup=_ranks_kb("add_user_rank"))
    await callback.answer()


@router.callback_query(AddUserFlow.waiting_rank, F.data.startswith("add_user_rank:"))
async def add_user_rank(callback: CallbackQuery, state: FSMContext):
    rank = int(callback.data.split(":", 1)[1])
    await state.update_data(new_rank=rank)
    data = await state.get_data()
    await _finish_add_user(callback.message, state, data["new_org"], rank, from_callback=callback)


async def _finish_add_user(
    message_or_cb, state: FSMContext, org: str, rank: int, from_callback: CallbackQuery | None = None
):
    data = await state.get_data()
    new_id = data["new_id"]
    new_nick = data["new_nick"]
    await state.clear()

    admin_id = from_callback.from_user.id if from_callback else message_or_cb.chat.id
    admin = get_user(admin_id)
    sheets = get_sheets()

    today = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y")
    row = await run(sheets.assign_nick_to_org, org, new_nick, today)

    await run(
        sheets.upsert_user,
        new_id,
        NickName=new_nick,
        Role=role_name(Role.STAFF),
        Org=org,
        AddedBy=admin.nickname if admin else "",
        AddedDate=today,
        Rank=rank,
    )
    set_user(new_id, new_nick, Role.STAFF, org, row)
    await sheets.log_access(new_nick, admin.nickname if admin else "", "🟢 Выдано")

    text = f"✅ Пользователь {new_nick} добавлен в организацию {org} (ранг {rank}). Все, человеку выдано доступ."
    if from_callback:
        await from_callback.message.edit_text(text, reply_markup=admin_panel_kb(admin.role))
        await from_callback.answer()
    else:
        await message_or_cb.answer(text, reply_markup=admin_panel_kb(admin.role))


# ============================================================ УДАЛИТЬ ПОЛЬЗОВАТЕЛЯ
def _visible_targets(admin) -> list:
    if admin.role >= Role.LEADERSHIP:
        return all_users()
    if admin.role == Role.SENIOR_WATCHER:
        orgs = _orgs_for(admin.role, admin.org)
        return [u for u in all_users() if u.org in orgs]
    return users_in_org(admin.org) if admin.org else []


@router.callback_query(F.data == "admin_remove_user")
async def cb_remove_user_start(callback: CallbackQuery, state: FSMContext):
    admin = get_user(callback.from_user.id)
    targets = [u for u in _visible_targets(admin) if u.telegram_id != admin.telegram_id]
    if not targets:
        await callback.answer("Список пуст", show_alert=True)
        return
    await state.set_state(RemoveUserFlow.waiting_user)
    await callback.message.edit_text(
        "Укажите пользователя:", reply_markup=nick_list_kb("rm_user", [u.nickname for u in targets])
    )
    await callback.answer()


@router.callback_query(RemoveUserFlow.waiting_user, F.data.startswith("rm_user:"))
async def remove_user_pick(callback: CallbackQuery, state: FSMContext):
    nick = callback.data.split(":", 1)[1]
    await state.update_data(target_nick=nick)
    await state.set_state(RemoveUserFlow.waiting_reason)
    await callback.message.edit_text("Напишите причину снятия:", reply_markup=cancel_kb())
    await callback.answer()


@router.message(RemoveUserFlow.waiting_reason)
async def remove_user_reason(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    nick = data["target_nick"]
    reason = message.text.strip()
    await state.clear()

    admin = get_user(message.from_user.id)
    target = next((u for u in all_users() if u.nickname == nick), None)
    sheets = get_sheets()

    if target:
        row_idx = await run(sheets.find_nick_row, target.nickname)
        if row_idx:
            await run(sheets.clear_nick_slot, row_idx)
        await run(sheets.delete_user, target.telegram_id)
        cache_remove_user(target.telegram_id)
        await sheets.log_access(nick, admin.nickname, "🔴 Снят", reason)
        try:
            await bot.send_message(
                target.telegram_id, f"Вы были сняты с должности, администратором {admin.nickname}.\nПричина: {reason}"
            )
        except Exception:
            pass

    await message.answer(f"✅ Пользователь {nick} удалён.", reply_markup=admin_panel_kb(admin.role))


# ============================================================ СПИСОК ПОЛЬЗОВАТЕЛЕЙ
@router.callback_query(F.data == "admin_list_users")
async def cb_list_users(callback: CallbackQuery):
    admin = get_user(callback.from_user.id)
    targets = _visible_targets(admin)
    if not targets:
        await callback.answer("Список пуст", show_alert=True)
        return
    await callback.message.edit_text(
        "Укажите пользователя:", reply_markup=nick_list_kb("view_user", [u.nickname for u in targets])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("view_user:"))
async def cb_view_user(callback: CallbackQuery, state: FSMContext):
    nick = callback.data.split(":", 1)[1]
    admin = get_user(callback.from_user.id)
    target = next((u for u in all_users() if u.nickname == nick), None)
    if not target:
        await callback.answer("Не найден", show_alert=True)
        return

    await state.update_data(active_target_nick=nick)

    from handlers.stats import render_stats_text
    text = await render_stats_text(target.telegram_id)

    kb = back_kb()
    if admin.role >= Role.WATCHER:
        kb = points_punish_actions_kb()
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ============================================================ СДАТЬ ФРАПС ОБЗВОНА (Лидер+)
@router.callback_query(F.data == "admin_fraps")
async def cb_fraps_start(callback: CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    if not user or user.role < Role.LEADER:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.set_state(FrapsFlow.waiting_nick)
    await callback.message.edit_text("Напишите ник кандидата:", reply_markup=cancel_kb())
    await callback.answer()


@router.message(FrapsFlow.waiting_nick)
async def fraps_nick(message: Message, state: FSMContext):
    await state.update_data(fraps_candidate_nick=message.text.strip())
    await state.set_state(FrapsFlow.waiting_org)
    await message.answer(
        "Выберите организацию, который человек прошел обзвон:", reply_markup=orgs_kb("fraps_org")
    )


@router.callback_query(FrapsFlow.waiting_org, F.data.startswith("fraps_org:"))
async def fraps_org(callback: CallbackQuery, state: FSMContext):
    org = callback.data.split(":", 1)[1]
    await state.update_data(fraps_org=org)
    await state.set_state(FrapsFlow.waiting_link)
    await callback.message.edit_text(
        "Скиньте ссылку на видео вложенный в YouTube:", reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(FrapsFlow.waiting_link)
async def fraps_link(message: Message, state: FSMContext):
    data = await state.get_data()
    candidate_nick = data["fraps_candidate_nick"]
    org = data["fraps_org"]
    link = message.text.strip()
    await state.clear()

    admin = get_user(message.from_user.id)
    sheets = get_sheets()
    # Ничего не сохраняем в таблицы/кэш — только пересылаем в канал логов, как и просили.
    await sheets.log_fraps(candidate_nick, admin.nickname, role_name(admin.role), org, link)

    await message.answer("Отчет успешно принят", reply_markup=admin_panel_kb(admin.role))


# ============================================================ СБРОС ПАРОЛЯ (веб-панель)
@router.callback_query(F.data == "admin_reset_password_scoped")
async def cb_reset_password_scoped_start(callback: CallbackQuery, state: FSMContext):
    admin = get_user(callback.from_user.id)
    if not admin or admin.role < Role.SENIOR_WATCHER:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    targets = [u for u in _visible_targets(admin) if u.telegram_id != admin.telegram_id]
    if not targets:
        await callback.answer("Список пуст", show_alert=True)
        return
    await state.set_state(ResetPasswordFlow.waiting_user)
    await callback.message.edit_text(
        "Кому сбросить пароль от сайта?", reply_markup=nick_list_kb("reset_pwd_user", [u.nickname for u in targets])
    )
    await callback.answer()


@router.callback_query(F.data == "admin_reset_password_any")
async def cb_reset_password_any_start(callback: CallbackQuery, state: FSMContext):
    admin = get_user(callback.from_user.id)
    if not admin or admin.role != Role.CREATOR:
        await callback.answer("Только для создателя", show_alert=True)
        return
    targets = [u for u in all_users() if u.telegram_id != admin.telegram_id]
    if not targets:
        await callback.answer("Список пуст", show_alert=True)
        return
    await state.set_state(ResetPasswordFlow.waiting_user)
    await callback.message.edit_text(
        "Кому сбросить пароль от сайта?", reply_markup=nick_list_kb("reset_pwd_user", [u.nickname for u in targets])
    )
    await callback.answer()


@router.callback_query(ResetPasswordFlow.waiting_user, F.data.startswith("reset_pwd_user:"))
async def reset_password_pick_user(callback: CallbackQuery, state: FSMContext):
    nick = callback.data.split(":", 1)[1]
    await state.update_data(reset_pwd_target_nick=nick)
    await state.set_state(ResetPasswordFlow.waiting_password)
    await callback.message.edit_text(
        "Напишите новый пароль для этого человека (минимум 4 символа):", reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(ResetPasswordFlow.waiting_password)
async def reset_password_apply(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    nick = data["reset_pwd_target_nick"]
    new_password = message.text.strip()
    await state.clear()

    admin = get_user(message.from_user.id)
    if len(new_password) < 4:
        await message.answer("Пароль слишком короткий (минимум 4 символа). Попробуйте ещё раз через меню.", reply_markup=admin_panel_kb(admin.role))
        return

    target = next((u for u in all_users() if u.nickname == nick), None)
    if not target:
        await message.answer("Пользователь не найден.", reply_markup=admin_panel_kb(admin.role))
        return

    from utils.passwords import hash_password
    from services.webapp_client import set_password_on_webapp

    password_hash = hash_password(new_password)
    ok, error = await set_password_on_webapp(target.telegram_id, password_hash)

    if not ok:
        await message.answer(f"❌ Не удалось сбросить пароль: {error}", reply_markup=admin_panel_kb(admin.role))
        return

    sheets = get_sheets()
    await sheets.log_moderation(admin.nickname, "reset_password", target.nickname, "Пароль от сайта сброшен")

    await message.answer(
        f"✅ Пароль для {target.nickname} сброшен.", reply_markup=admin_panel_kb(admin.role)
    )
    try:
        await bot.send_message(
            target.telegram_id,
            f"🔑 Администратор {admin.nickname} сбросил ваш пароль от веб-панели.\n\n"
            f"Новый пароль: {new_password}\n\n"
            f"Рекомендуем сразу сменить его на свой через /setpassword.",
        )
    except Exception:
        pass
