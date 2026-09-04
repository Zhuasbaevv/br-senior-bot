from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import Role, PINGER_TELEGRAM_ID, WEBAPP_URL
from utils.access import get_user, role_name
from utils.passwords import hash_password
from services.webapp_client import set_password_on_webapp
from keyboards.menus import main_menu_kb, cancel_kb
from states import Verification
from services.sheets import get_sheets, run
from aiogram.filters import CommandObject

router = Router(name="common")

# telegram_id -> True если сейчас "в игре" (после /join)
_in_game: set[int] = set()

# путь, где хранится текст для команды /info
_INFO_TEXT_HOLDER = {"text": "Информация о боте появится позже."}


def get_info_text() -> str:
    return _INFO_TEXT_HOLDER["text"]


def set_info_text(text: str) -> None:
    _INFO_TEXT_HOLDER["text"] = text


@router.message(Command("id"))
async def cmd_id(message: Message):
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>", parse_mode="HTML")


@router.message(Command("setpassword"))
async def cmd_setpassword(message: Message, command: CommandObject):
    """Самостоятельная установка/смена пароля для входа на веб-панель.
    Пароль храним ТОЛЬКО на сайте (webapp/db.py, локальная SQLite) — бот сам его
    нигде не хранит, а хэширует и передаёт сайту по внутреннему API. В Google-таблицу
    пароль не попадает вообще, даже в виде хэша."""
    user = get_user(message.from_user.id)
    if user is None:
        return
    if not command.args or len(command.args.strip()) < 4:
        await message.answer("Использование: /setpassword ваш_новый_пароль (минимум 4 символа)")
        return

    password = command.args.strip()
    password_hash = hash_password(password)
    ok, error = await set_password_on_webapp(message.from_user.id, password_hash)

    if not ok:
        await message.answer(f"❌ Не удалось установить пароль: {error}")
        return

    login_url = f"{WEBAPP_URL}/login" if WEBAPP_URL else "(адрес сайта ещё не настроен)"
    await message.answer(
        f"✅ Пароль для веб-панели установлен\n\n"
        f"🔑 Пароль: {password}\n"
        f"🌐 Войти: {login_url}"
    )
    # Само сообщение с паролем удалять не пытаемся — Telegram API не даёт ботам
    # удалять сообщения старше 48ч у собеседника, и это его личный чат с ботом,
    # так что не критично, но стоит посоветовать почистить чат вручную.


@router.message(Command("ping"))
async def cmd_ping(message: Message):
    """Держит бота 'живым' на бесплатном хостинге с отключением по неактивности —
    юзербот-пингер (см. userbot_ping/) шлёт эту команду раз в 10 минут в личку.
    Отвечает ТОЛЬКО пингеру (PINGER_TELEGRAM_ID в config.py); от всех остальных —
    молчим, чтобы не плодить лишние сообщения/логи."""
    if message.from_user.id != PINGER_TELEGRAM_ID:
        return
    await message.answer("pong")


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if user is None:
        return  # перехвачено AccessMiddleware

    sheets = get_sheets()
    row = await run(sheets.get_user_row, message.from_user.id)
    verified = bool(row and row.get("VK"))

    if not verified:
        await state.set_state(Verification.vk)
        await message.answer(
            "Укажите ваш VK ID. Пример: 708084365\n\nДля отмены действия нажмите на кнопку ниже",
            reply_markup=cancel_kb(),
        )
        return

    await message.answer("Вы попали в Главное Меню!", reply_markup=main_menu_kb(user.role))


@router.message(Command("join"))
async def cmd_join(message: Message):
    user = get_user(message.from_user.id)
    if user is None or user.role < Role.STAFF:
        return
    if message.from_user.id in _in_game:
        await message.reply("❌ Вы и так находитесь в игре. Используйте /leave чтобы выйти.")
        return
    _in_game.add(message.from_user.id)
    await message.reply("✅ Вы успешно вошли в игру. Используйте /leave чтобы выйти.")


@router.message(Command("leave"))
async def cmd_leave(message: Message):
    user = get_user(message.from_user.id)
    if user is None or user.role < Role.STAFF:
        return
    if message.from_user.id not in _in_game:
        await message.reply("❌ Вы не в игре. Используйте /join чтобы войти.")
        return
    _in_game.discard(message.from_user.id)
    await message.reply("✅ Вы успешно вышли из игры.")


@router.message(Command("info"))
async def cmd_info(message: Message):
    await message.answer(get_info_text())


@router.callback_query(F.data == "menu_main")
async def cb_menu_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = get_user(callback.from_user.id)
    await callback.message.edit_text("Вы попали в Главное Меню!", reply_markup=main_menu_kb(user.role))
    await callback.answer()


@router.callback_query(F.data == "cancel_process")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = get_user(callback.from_user.id)
    if user is None:
        await callback.answer()
        return
    await callback.message.edit_text("Процесс отменён. Вы попали в Главное Меню!", reply_markup=main_menu_kb(user.role))
    await callback.answer()
