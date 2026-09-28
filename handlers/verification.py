from __future__ import annotations

import datetime as dt

from aiogram import Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from states import Verification
from keyboards.menus import cancel_kb, main_menu_kb
from services.sheets import get_sheets, run
from utils.access import get_user
from config import MSK_TZ

router = Router(name="verification")


@router.message(Verification.vk)
async def v_vk(message: Message, state: FSMContext):
    await state.update_data(vk=message.text.strip())
    await state.set_state(Verification.discord)
    await message.answer(
        "Укажите ваш Discord ID(Цифрами) Пример: 1141704695354753096",
        reply_markup=cancel_kb(),
    )


@router.message(Verification.discord)
async def v_discord(message: Message, state: FSMContext):
    await state.update_data(discord=message.text.strip())
    await state.set_state(Verification.forum)
    await message.answer("Укажите ссылку на ваш форумный аккаунт.", reply_markup=cancel_kb())


@router.message(Verification.forum)
async def v_forum(message: Message, state: FSMContext):
    await state.update_data(forum=message.text.strip())
    await state.set_state(Verification.age)
    await message.answer("Напишите свой возраст:", reply_markup=cancel_kb())


@router.message(Verification.age)
async def v_age(message: Message, state: FSMContext):
    await state.update_data(age=message.text.strip())
    await state.set_state(Verification.timezone)
    await message.answer("Укажите ваш часовой пояс", reply_markup=cancel_kb())


@router.message(Verification.timezone)
async def v_timezone(message: Message, state: FSMContext):
    await state.update_data(timezone=message.text.strip())
    await state.set_state(Verification.tg_username)
    await message.answer("Ваш Telegram @UserName:", reply_markup=cancel_kb())


@router.message(Verification.tg_username)
async def v_tg_username(message: Message, state: FSMContext):
    await state.update_data(tg_username=message.text.strip())
    await state.set_state(Verification.email)
    await message.answer("Укажите свою почту:", reply_markup=cancel_kb())


@router.message(Verification.email)
async def v_email(message: Message, state: FSMContext):
    data = await state.get_data()
    data["email"] = message.text.strip()
    await state.clear()

    sheets = get_sheets()
    user = get_user(message.from_user.id)
    await run(
        sheets.upsert_user,
        message.from_user.id,
        VK=data.get("vk", ""),
        DiscordID=data.get("discord", ""),
        Forum=data.get("forum", ""),
        Age=data.get("age", ""),
        Timezone=data.get("timezone", ""),
        TelegramUsername=data.get("tg_username", ""),
        Email=data.get("email", ""),
    )

    await message.answer("Вы попали в Главное Меню!", reply_markup=main_menu_kb(user.role if user else 0))
