from __future__ import annotations

import datetime as dt

from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Role, ALL_ORGS, CREATOR_ID, SHEET_MAIN, GOOGLE_SHEET_ID, MSK_TZ
from utils.access import get_user, all_users, set_user, role_name, users_in_org
from keyboards.menus import cancel_kb, admin_panel_kb, nick_list_kb
from states import SettingsFlow
from services.sheets import get_sheets, run
from handlers.common import _in_game, set_info_text

router = Router(name="leadership_creator")


# ============================================================ /members
@router.message(Command("members"))
async def cmd_members(message: Message):
    user = get_user(message.from_user.id)
    if user is None or user.role < Role.STAFF:
        return

    online_users = [u for u in all_users() if u.telegram_id in _in_game]

    if user.role >= Role.LEADERSHIP:
        text_parts = ["👮 Активные участники:\n"]
        for org in ALL_ORGS:
            org_online = [u for u in online_users if u.org == org]
            if not org_online:
                continue
            lines = "\n".join(f" • {u.nickname}" for u in org_online)
            text_parts.append(f"{org}:\n<blockquote>{lines}</blockquote>")
        text = "\n\n".join(text_parts) if len(text_parts) > 1 else "👮 Активные участники:\n\nНикого нет в игре."
    else:
        org_online = [u for u in online_users if u.org == user.org]
        if not org_online:
            text = "👮 Активные участники\n\nНикого нет в игре."
        else:
            lines = "\n".join(f" • {u.nickname}" for u in org_online)
            text = f"👮 Активные участники\n\n<blockquote>{lines}</blockquote>"

    await message.reply(text, parse_mode="HTML")


# ============================================================ /settings (руководство+)
@router.message(Command("settings"))
async def cmd_settings(message: Message, command: CommandObject):
    user = get_user(message.from_user.id)
    if user is None or user.role < Role.LEADERSHIP:
        return

    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /settings [Telegram ID]")
        return

    target_id = int(command.args.strip())
    target = get_user(target_id)
    if not target:
        await message.answer("Пользователь не найден.")
        return

    b = InlineKeyboardBuilder()
    b.button(text="NickName", callback_data=f"settings_nick:{target_id}")
    b.button(text="Статистика", callback_data=f"settings_stat:{target_id}")
    b.row(cancel_kb().inline_keyboard[0][0])
    b.adjust(2, 1)
    await message.answer("Что настроить?", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("settings_nick:"))
async def settings_nick_start(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split(":", 1)[1])
    await state.update_data(settings_target_id=target_id)
    await state.set_state(SettingsFlow.waiting_new_nick)
    await callback.message.edit_text("Укажите новый NickName пользователя:", reply_markup=cancel_kb())
    await callback.answer()


@router.message(SettingsFlow.waiting_new_nick)
async def settings_nick_apply(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data["settings_target_id"]
    new_nick = message.text.strip()
    await state.clear()

    target = get_user(target_id)
    if not target:
        await message.answer("Пользователь не найден.")
        return

    sheets = get_sheets()
    row_idx = await run(sheets.find_nick_row, target.nickname)
    if row_idx:
        # Раньше тут было sheets.ws(SHEET_MAIN) — жёстко зашитый лист вместо текущей
        # недели, плюс кэшированный target.row. Меняем ник в реальном текущем листе.
        ws = sheets.ws(sheets.current_sheet_title)
        await run(ws.update_cell, row_idx, 2, new_nick)
    await run(sheets.upsert_user, target_id, NickName=new_nick)
    set_user(target_id, new_nick, target.role, target.org, row_idx)

    admin = get_user(message.from_user.id)
    await message.answer(f"✅ NickName обновлён на {new_nick}.", reply_markup=admin_panel_kb(admin.role))


@router.callback_query(F.data.startswith("settings_stat:"))
async def settings_stat_verify(callback: CallbackQuery, state: FSMContext):
    """Руководство проходит верификацию за пользователя — используем тот же Verification flow."""
    target_id = int(callback.data.split(":", 1)[1])
    from states import Verification
    await state.update_data(verification_for=target_id)
    await state.set_state(Verification.vk)
    await callback.message.edit_text(
        f"Верификация для пользователя {target_id}.\nУкажите его VK ID:", reply_markup=cancel_kb()
    )
    await callback.answer()


# ============================================================ /reset (руководство+) и /allreset (создатель)
async def _reset_user(telegram_id: int) -> None:
    """Сбрасывает контакты/возраст/верификацию, сохраняя баллы, наказания, дату назначения."""
    sheets = get_sheets()
    await run(
        sheets.upsert_user,
        telegram_id,
        VK="", DiscordID="", Forum="", Age="", Timezone="", TelegramUsername="", Email="",
    )


@router.message(Command("reset"))
async def cmd_reset(message: Message, command: CommandObject):
    user = get_user(message.from_user.id)
    if user is None or user.role < Role.LEADERSHIP:
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /reset [Telegram ID]")
        return
    target_id = int(command.args.strip())
    await _reset_user(target_id)
    await message.answer(f"✅ Статистика верификации пользователя {target_id} сброшена.")


@router.message(Command("allreset"))
async def cmd_allreset(message: Message):
    user = get_user(message.from_user.id)
    if user is None or user.role != Role.CREATOR:
        return
    for u in all_users():
        if u.telegram_id == message.from_user.id:
            continue
        await _reset_user(u.telegram_id)
    await message.answer("✅ Статистика верификации сброшена у всех пользователей.")


# ============================================================ /o (создатель)
@router.message(Command("o"))
async def cmd_broadcast(message: Message, command: CommandObject, bot: Bot):
    user = get_user(message.from_user.id)
    if user is None or user.role != Role.CREATOR:
        return
    if not command.args:
        await message.answer("Использование: /o [текст]")
        return
    text = f"❗️ Новое уведомление от Разработчика.\n\n{command.args}"
    sent, failed = 0, 0
    for u in all_users():
        try:
            await bot.send_message(u.telegram_id, text)
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"✅ Разослано: {sent}, ошибок: {failed}")


# ============================================================ /setinfo (создатель)
@router.message(Command("setinfo"))
async def cmd_setinfo(message: Message, command: CommandObject):
    user = get_user(message.from_user.id)
    if user is None or user.role != Role.CREATOR:
        return
    if not command.args:
        await message.answer("Использование: /setinfo [текст]")
        return
    set_info_text(command.args)
    await message.answer("✅ Текст команды /info обновлён.")


# ============================================================ СОЗДАТЬ НОВЫЙ ЛИСТ НЕДЕЛИ (создатель)
@router.callback_query(F.data == "admin_create_week_sheet")
async def cb_create_week_sheet(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if user is None or user.role != Role.CREATOR:
        await callback.answer("❌ Только для создателя!", show_alert=True)
        return

    # Отвечаем на callback СРАЗУ, до любых обращений к Google Sheets.
    # answerCallbackQuery живёт ограниченное время с момента нажатия кнопки —
    # если сначала уйти в долгий (пусть и в фоновом потоке) запрос к Sheets API,
    # к моменту вызова callback.answer() Telegram уже считает запрос устаревшим
    # ("query is too old"). Редактирование сообщения (edit_text) этим лимитом
    # не ограничено, поэтому его по-прежнему можно делать по ходу работы.
    await callback.answer()

    msg = await callback.message.edit_text(
        "🔄 Создаю новый лист недели...\n\n"
        "📅 Будет создан лист с понедельника по воскресенье\n"
        "📋 Структура будет скопирована с предыдущего листа\n"
        "⏳ Пожалуйста, подождите..."
    )

    try:
        sheets = get_sheets()
        now = dt.datetime.now(MSK_TZ)

        # Раньше здесь было 2 отдельных СИНХРОННЫХ обращения к gspread
        # (sheets._spreadsheet.worksheets() напрямую и sheets.get_or_create_week_sheet(now)
        # без run()) — оба блокировали весь event loop бота целиком на время
        # запроса к Google (то есть замирал вообще весь бот, для всех пользователей),
        # из-за чего и не успевал уложиться answerCallbackQuery. Теперь один-единственный
        # вызов, и он идёт через run() (asyncio.to_thread) — не блокирует event loop.
        week_title, created = await run(sheets.get_or_create_week_sheet_status, now)

        if not week_title:
            await msg.edit_text(
                "❌ Не удалось создать лист — проверьте, что в таблице есть лист-шаблон "
                "(см. TEMPLATE_SHEET_NAME в services/sheets.py) и логи бота в консоли."
            )
            return

        if not created:
            await msg.edit_text(
                f"⚠️ Лист '{week_title}' уже существует!\n\n"
                f"📅 Текущая неделя: {week_title}\n"
                f"💡 Если нужно создать новый лист — подождите следующей недели.",
            )
            return

        await msg.edit_text(
            f"✅ Новый лист успешно создан!\n\n"
            f"📅 Название: {week_title}\n"
            f"📋 Структура скопирована с предыдущего листа\n"
            f"📅 Даты обновлены (Пн-Вс)\n\n"
            f"🔗 <a href='https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}'>Открыть таблицу</a>",
            parse_mode="HTML",
        )

        await sheets.log_moderation(
            user.nickname,
            "create_week_sheet",
            "",
            f"Создан лист {week_title}",
        )

    except Exception as e:
        await msg.edit_text(
            f"❌ Ошибка при создании листа:\n\n"
            f"<code>{str(e)}</code>\n\n"
            f"🔄 Попробуйте ещё раз или создайте лист вручную.",
            parse_mode="HTML",
        )
        print(f"[ERROR] create_week_sheet: {e}")


# ============================================================ /findnick (диагностика поиска по нику)
@router.message(Command("findnick"))
async def cmd_findnick(message: Message, command: CommandObject):
    user = get_user(message.from_user.id)
    if user is None or user.role != Role.CREATOR:
        return
    if not command.args or not command.args.strip():
        await message.answer("Использование: /findnick НикЧеловека")
        return

    sheets = get_sheets()
    result = await run(sheets.debug_find_nick, command.args.strip())
    if len(result) > 4000:
        result = result[:3990] + "\n…(обрезано)"
    await message.answer(f"<code>{result}</code>", parse_mode="HTML")
