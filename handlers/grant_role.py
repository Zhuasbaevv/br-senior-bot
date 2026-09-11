from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from config import Role, ALL_ORGS, CRIME_ORGS, POWER_ORGS, SOCIAL_ORGS, ROLE_NAMES
from utils.access import get_user, set_user, all_users, role_name
from keyboards.menus import (
    cancel_kb, admin_panel_kb, nick_list_kb, roles_kb, orgs_kb, senior_groups_kb,
)
from states import GrantRoleFlow, LeadershipAssignFlow
from services.sheets import get_sheets, run

router = Router(name="grant_role")

_GROUP_ORGS = {"Соц организации": SOCIAL_ORGS, "Силовые органы": POWER_ORGS, "ОПГ": CRIME_ORGS}


def _candidates_for(admin) -> list:
    if admin.role >= Role.LEADERSHIP:
        return [u for u in all_users() if u.role < Role.LEADERSHIP]
    if admin.role == Role.SENIOR_WATCHER:
        orgs = _GROUP_ORGS.get(admin.org, [])
        return [u for u in all_users() if u.org in orgs and u.role < Role.SENIOR_WATCHER]
    return []


@router.callback_query(F.data == "admin_grant_role")
async def cb_grant_role_start(callback: CallbackQuery, state: FSMContext):
    admin = get_user(callback.from_user.id)
    candidates = _candidates_for(admin)
    if not candidates:
        await callback.answer("Некому выдавать доступ", show_alert=True)
        return
    await state.set_state(GrantRoleFlow.waiting_user)
    await callback.message.edit_text(
        "Укажите пользователя:", reply_markup=nick_list_kb("grant_user", [u.nickname for u in candidates])
    )
    await callback.answer()


@router.callback_query(GrantRoleFlow.waiting_user, F.data.startswith("grant_user:"))
async def grant_pick_user(callback: CallbackQuery, state: FSMContext):
    nick = callback.data.split(":", 1)[1]
    admin = get_user(callback.from_user.id)
    await state.update_data(target_nick=nick)
    await state.set_state(GrantRoleFlow.waiting_role)
    allow_senior = admin.role >= Role.LEADERSHIP
    await callback.message.edit_text("Выберите роль:", reply_markup=roles_kb("grant_role", allow_senior))
    await callback.answer()


@router.callback_query(GrantRoleFlow.waiting_role, F.data.startswith("grant_role:"))
async def grant_pick_role(callback: CallbackQuery, state: FSMContext):
    role_val = int(callback.data.split(":", 1)[1])
    role = Role(role_val)
    admin = get_user(callback.from_user.id)
    await state.update_data(target_role=role_val)

    if role == Role.SENIOR_WATCHER:
        await state.set_state(GrantRoleFlow.waiting_org_or_group)
        await callback.message.edit_text("Список организаций:", reply_markup=senior_groups_kb("grant_group"))
    else:
        orgs = ALL_ORGS if admin.role >= Role.LEADERSHIP else _GROUP_ORGS.get(admin.org, ALL_ORGS)
        await state.set_state(GrantRoleFlow.waiting_org_in_group)
        await callback.message.edit_text("Список организаций:", reply_markup=orgs_kb("grant_org", orgs))
    await callback.answer()


@router.callback_query(GrantRoleFlow.waiting_org_or_group, F.data.startswith("grant_group:"))
async def grant_pick_group(callback: CallbackQuery, state: FSMContext, bot: Bot):
    group = callback.data.split(":", 1)[1]
    await _finalize_grant(callback, state, bot, org_or_group=group)


@router.callback_query(GrantRoleFlow.waiting_org_in_group, F.data.startswith("grant_org:"))
async def grant_pick_org(callback: CallbackQuery, state: FSMContext, bot: Bot):
    org = callback.data.split(":", 1)[1]
    await _finalize_grant(callback, state, bot, org_or_group=org)


async def _finalize_grant(callback: CallbackQuery, state: FSMContext, bot: Bot, org_or_group: str):
    data = await state.get_data()
    nick = data["target_nick"]
    role = Role(data["target_role"])
    await state.clear()

    admin = get_user(callback.from_user.id)
    target = next((u for u in all_users() if u.nickname == nick), None)
    if not target:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    sheets = get_sheets()
    await run(sheets.upsert_user, target.telegram_id, Role=role_name(role), Org=org_or_group)
    set_user(target.telegram_id, target.nickname, role, org_or_group, target.row)
    await sheets.log_moderation(admin.nickname, "grant_role", target.nickname, f"{role_name(role)} / {org_or_group}")

    await callback.message.edit_text(
        f"✅ {target.nickname} назначен(а) на роль «{role_name(role)}» ({org_or_group}).",
        reply_markup=admin_panel_kb(admin.role),
    )
    await callback.answer()
    try:
        await bot.send_message(
            target.telegram_id,
            f"Вам выдана роль «{role_name(role)}» ({org_or_group}) администратором {admin.nickname}.",
        )
    except Exception:
        pass


# ============================================================ НАЗНАЧИТЬ РУКОВОДСТВО (создатель)
@router.callback_query(F.data == "admin_assign_leadership")
async def cb_assign_leadership_start(callback: CallbackQuery, state: FSMContext):
    admin = get_user(callback.from_user.id)
    if admin.role != Role.CREATOR:
        await callback.answer("Только для создателя", show_alert=True)
        return
    candidates = [u for u in all_users() if u.role < Role.LEADERSHIP]
    await state.set_state(LeadershipAssignFlow.waiting_user)
    await callback.message.edit_text(
        "Укажите нового руководство:", reply_markup=nick_list_kb("assign_lead", [u.nickname for u in candidates])
    )
    await callback.answer()


@router.callback_query(LeadershipAssignFlow.waiting_user, F.data.startswith("assign_lead:"))
async def assign_leadership_pick(callback: CallbackQuery, state: FSMContext, bot: Bot):
    nick = callback.data.split(":", 1)[1]
    await state.clear()

    admin = get_user(callback.from_user.id)
    target = next((u for u in all_users() if u.nickname == nick), None)
    if not target:
        await callback.answer("Не найден", show_alert=True)
        return

    sheets = get_sheets()
    await run(sheets.upsert_user, target.telegram_id, Role=role_name(Role.LEADERSHIP))
    set_user(target.telegram_id, target.nickname, Role.LEADERSHIP, target.org, target.row)
    await sheets.log_moderation(admin.nickname, "assign_leadership", target.nickname, "")

    await callback.message.edit_text(
        f"✅ {target.nickname} назначен(а) руководством.", reply_markup=admin_panel_kb(admin.role)
    )
    await callback.answer()
    try:
        await bot.send_message(target.telegram_id, f"Вы назначены руководством администратором {admin.nickname}.")
    except Exception:
        pass
