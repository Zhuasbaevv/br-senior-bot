from __future__ import annotations

import asyncio
import datetime as dt
import hashlib

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from config import (
    Role, MSK_TZ, PUNISHMENT_TYPES, PUNISHMENT_SHEET_COL, REPORT_STATUS_NO_NORM,
    ACTIVITY_LABELS, CREATOR_ID, CREATOR_TEST_NORM,
)
from utils.access import get_user, managers_for_org, role_name
from keyboards.menus import (
    applications_menu_kb, cancel_kb, main_menu_kb, nick_list_kb, yes_no_kb, back_kb,
)
from states import ReportFlow, InactiveFlow, ExtraWorkFlow, RemovePunishRequestFlow, DecisionReasonFlow
from services.sheets import get_sheets, run
from services.ai_ocr import analyze_report_album, score_report

router = Router(name="applications")


# ---------------------------------------------------------------- меню
@router.callback_query(F.data == "menu_applications")
async def cb_applications_menu(callback: CallbackQuery):
    await callback.message.edit_text("Заявления:", reply_markup=applications_menu_kb())
    await callback.answer()


# ================================================================== ОТЧЁТ (альбом скринов)
# Буфер для сбора альбома (media_group_id) — Telegram присылает каждое фото
# альбома отдельным апдейтом, поэтому копим их с небольшим дебаунсом.
_album_buffers: dict[str, list[Message]] = {}
_album_tasks: dict[str, asyncio.Task] = {}
_ALBUM_DEBOUNCE_SEC = 1.5


@router.callback_query(F.data == "app_report")
async def cb_app_report(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ReportFlow.waiting_screens)
    today = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y")
    await state.update_data(report_date=today)
    await callback.message.edit_text(
        f"Прикрепите скриншоты ваших работ за {today} ОДНИМ альбомом "
        "(поход на ВЧ, онлайн, собеседования, лекции, тренировки, РП — что относится к вашей норме).\n\n"
        "Примечание: на каждом скрине должны быть видны дата и время внизу справа, "
        "иначе он не будет засчитан.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ReportFlow.waiting_screens, F.photo)
async def report_photo(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    report_date = data.get("report_date") or dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y")

    if message.media_group_id:
        gid = message.media_group_id
        _album_buffers.setdefault(gid, []).append(message)
        if gid in _album_tasks:
            _album_tasks[gid].cancel()
        _album_tasks[gid] = asyncio.create_task(
            _flush_album(gid, state, bot, report_date)
        )
        return

    # одиночное фото — обрабатываем сразу как альбом из одного элемента
    await state.clear()
    await _process_report([message], report_date, bot)


async def _flush_album(gid: str, state: FSMContext, bot: Bot, report_date: str):
    try:
        await asyncio.sleep(_ALBUM_DEBOUNCE_SEC)
    except asyncio.CancelledError:
        return
    messages = _album_buffers.pop(gid, [])
    _album_tasks.pop(gid, None)
    if not messages:
        return
    await state.clear()
    await _process_report(messages, report_date, bot)


async def _process_report(messages: list[Message], report_date: str, bot: Bot):
    first = messages[0]

    sheets = get_sheets()
    user = get_user(first.from_user.id)

    # Лимит "раз в день" не действует на создателя — иначе тестировать бота
    # (без ожидания следующего дня) невозможно. Остальным лимит применяется как обычно.
    if user and user.role != Role.CREATOR:
        already_reported = await run(sheets.has_reported_on, user.nickname, report_date)
        if already_reported:
            await first.answer(
                f"⛔ Вы уже сдавали отчёт за {report_date}. "
                f"Отчёт можно сдавать не чаще одного раза в день — попробуйте завтра."
            )
            return

    processing = await first.answer("🤖 Вношу данные в таблицу...")

    profile = await run(sheets.get_user_row, first.from_user.id)

    images: list[tuple[bytes, str]] = []
    photo_file_ids: list[str] = []
    photo_hashes: list[str] = []
    for m in messages:
        photo = m.photo[-1]
        photo_file_ids.append(photo.file_id)
        file = await bot.get_file(photo.file_id)
        buf = await bot.download_file(file.file_path)
        data = buf.read()
        images.append((data, "image/jpeg"))
        photo_hashes.append(hashlib.sha256(data).hexdigest())

    try:
        analysis = await analyze_report_album(images, report_date)
    except Exception:
        await processing.edit_text(
            "❌ Не удалось распознать отчёт по присланным скриншотам. "
            "Свяжитесь со следящим вашей организации или пришлите скрины чётче."
        )
        return

    rank = int(float(profile.get("Rank") or 0)) if profile else 0
    norm = await run(sheets.get_norm, user.org, rank) if user and user.org and rank else None

    if norm is None and user and user.role == Role.CREATOR:
        norm = CREATOR_TEST_NORM  # см. config.py — только для тестов создателем

    if norm is None:
        await processing.edit_text(
            "⚠️ Для вашей организации и ранга норматив ещё не настроен. "
            "Обратитесь к создателю бота — он должен указать норматив через панель управления."
        )
        return

    # Антидубль: проверяем, не сдавал ли уже кто-то (в т.ч. сам чел раньше) ровно такой же
    # скрин (побайтовое совпадение). Не блокирует приём отчёта — просто сигнализирует
    # руководству, чтобы разобрались вручную.
    duplicate_matches = await run(sheets.find_duplicate_hashes, photo_hashes, first.from_user.id)
    if duplicate_matches and user:
        other_nicks = sorted({m.get("NickName", "?") for m in duplicate_matches})
        alert_text = (
            f"🚨 <b>ПОДОЗРЕНИЕ НА ПОВТОРНУЮ СДАЧУ СКРИНА</b>\n\n"
            f"{user.nickname} сдал норматив, скрин из которого ранее уже был отправлен "
            f"({', '.join(other_nicks)}) — скорее проверьте."
        )
        recipients = {u.telegram_id: u for u in managers_for_org(user.org)} if user.org else {}
        recipients[CREATOR_ID] = None  # создатель — всегда, даже без назначенной роли в кэше
        for tid in recipients:
            try:
                await bot.send_message(tid, alert_text, parse_mode="HTML")
            except Exception:
                pass

    points, status, reasons = score_report(analysis, norm)
    sheet_write_ok = False

    if user:
        # Баллы/лог пишем по нику (свежий поиск строки внутри record_daily_points_by_date/
        # log_report_submission), а НЕ по кэшированному user.row — он может быть устаревшим
        # (например, после создания нового листа недели) или пустым по другим причинам,
        # и раньше из-за проверки "if user and user.row" весь этот блок просто тихо
        # пропускался целиком — баллы не попадали в таблицу, а лог отчёта не сохранялся
        # и не улетал в канал.
        row_idx = await run(sheets.find_nick_row, user.nickname)
        old_total = await run(sheets.get_points, row_idx) if row_idx else 0.0
        new_total = await run(sheets.record_daily_points_by_date, user.nickname, report_date, float(points))
        sheet_write_ok = new_total is not None
        if new_total is None:
            new_total = old_total  # не нашли ник/дату в таблице — баллы не записались
        await sheets.log_points(
            user.nickname, f"Отчёт (авто) — {status}", points, old_total, new_total,
            "; ".join(reasons),
        )
        if status == REPORT_STATUS_NO_NORM:
            await run(sheets.bump_no_norm_day, user.nickname)

        counts = analysis.get("counts", {})
        works_parts = [f"{ACTIVITY_LABELS[k]}: {v}" for k, v in counts.items() if v and k in ACTIVITY_LABELS]
        online_h = analysis.get("online_hours_today")
        if online_h:
            works_parts.append(f"Онлайн: {online_h}ч")
        works_done = ", ".join(works_parts) if works_parts else "Ничего не распознано"

        await sheets.log_report_submission(
            first.from_user.id, user.nickname, user.org or "—", report_date, status, points,
            works_done, photo_file_ids, photo_hashes,
        )

        if not sheet_write_ok:
            # Баллы посчитаны, но записать в таблицу не удалось — не показываем "успешно
            # отправлен", а честно предупреждаем и зовём на помощь тех, кто может это
            # исправить руками, чтобы это не терялось незамеченным.
            await processing.edit_text(
                f"⚠️ Отчёт распознан (статус: {status}, баллы: {points:+d}), НО не удалось найти вас "
                f"в текущей таблице — баллы НЕ записаны. Обратитесь к следящему вашей организации, "
                f"чтобы он проверил ваш NickName в таблице и внёс баллы вручную."
            )
            managers = managers_for_org(user.org) if user.org else []
            alert = (
                f"🚨 <b>ОТЧЁТ ПРИНЯТ, НО НЕ ЗАПИСАН В ТАБЛИЦУ</b>\n\n"
                f"{user.nickname} сдал отчёт ({status}, {points:+d} баллов), но бот не нашёл "
                f"его NickName в текущем листе таблицы. Проверьте ячейку с ником вручную "
                f"(возможно, лишний пробел/опечатка) и внесите баллы за {report_date} руками."
            )
            for m in managers:
                try:
                    await bot.send_message(m.telegram_id, alert, parse_mode="HTML")
                except Exception:
                    pass
            try:
                await bot.send_message(CREATOR_ID, alert, parse_mode="HTML")
            except Exception:
                pass
            return

    reasons_text = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(reasons))
    text = (
        f"✅ Отчет успешно отправлен.\n\n"
        f"📌 Статус: {status}\n"
        f"⭐ Начислено баллов: {points:+d}\n\n"
        f"{reasons_text}"
    )

    await processing.edit_text(text)


@router.message(ReportFlow.waiting_screens)
async def report_no_photo(message: Message):
    await message.answer("Пожалуйста, прикрепите скриншот(ы) (фото), а не текст.", reply_markup=cancel_kb())


# ================================================================== НЕАКТИВ
@router.callback_query(F.data == "app_inactive")
async def cb_app_inactive(callback: CallbackQuery, state: FSMContext):
    await state.set_state(InactiveFlow.waiting_dates)
    await callback.message.edit_text(
        "Укажите период неактивности в формате DD.MM.YYYY/DD.MM.YYYY", reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(InactiveFlow.waiting_dates)
async def inactive_dates(message: Message, state: FSMContext):
    text = message.text.strip()
    if "/" not in text:
        await message.answer("Неверный формат. Пример: 04.04.2026/05.04.2026", reply_markup=cancel_kb())
        return
    await state.update_data(dates=text)
    await state.set_state(InactiveFlow.waiting_reason)
    await message.answer("Укажите причину неактива:", reply_markup=cancel_kb())


@router.message(InactiveFlow.waiting_reason)
async def inactive_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    dates = data["dates"]
    reason = message.text.strip()
    await state.clear()

    sheets = get_sheets()
    user = get_user(message.from_user.id)
    app_id = await run(
        sheets.create_application, "inactive", message.from_user.id, user.nickname, f"{dates}|{reason}"
    )

    await message.answer(
        "✅ Ваша заявка была успешно отправлена руководству!\n\n"
        "Информация о неактиве:\n\n"
        f"Даты неактива: {dates}\n"
        f"Причина: {reason}"
    )
    await _notify_managers_new_app(message.bot, user, "Неактив", app_id, f"Даты: {dates}\nПричина: {reason}")


# ================================================================== ДОП РАБОТА
@router.callback_query(F.data == "app_extra")
async def cb_app_extra(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ExtraWorkFlow.waiting_screens)
    await callback.message.edit_text("Прикрепите скриншоты выших работ:", reply_markup=cancel_kb())
    await callback.answer()


@router.message(ExtraWorkFlow.waiting_screens, F.photo)
async def extra_photo(message: Message, state: FSMContext):
    file_ids = [p.file_id for p in [message.photo[-1]]]
    await state.update_data(screenshots=file_ids)
    await state.set_state(ExtraWorkFlow.waiting_description)
    await message.answer("Опишите одним словом вашу проделанную работу за сегодня:", reply_markup=cancel_kb())


@router.message(ExtraWorkFlow.waiting_description)
async def extra_description(message: Message, state: FSMContext):
    data = await state.get_data()
    description = message.text.strip()
    await state.clear()

    sheets = get_sheets()
    user = get_user(message.from_user.id)
    proof = ",".join(data.get("screenshots", []))
    app_id = await run(
        sheets.create_application, "extra_work", message.from_user.id, user.nickname, f"{description}|{proof}"
    )

    await message.answer("✅ Ваша отчетность была успешно отправлена руководству!")
    await _notify_managers_new_app(message.bot, user, "Доп.работа", app_id, f"Работа: {description}")


# ================================================================== СНЯТИЕ НАКАЗАНИЙ
@router.callback_query(F.data == "app_remove_punish")
async def cb_app_remove_punish(callback: CallbackQuery, state: FSMContext):
    sheets = get_sheets()
    user = get_user(callback.from_user.id)
    if not user:
        await callback.answer("Профиль не найден", show_alert=True)
        return

    row_idx = await run(sheets.find_nick_row, user.nickname)
    if not row_idx:
        await callback.answer("Не нашёл вас в текущей таблице, обратитесь к следящему", show_alert=True)
        return

    strict = await run(sheets.get_punishment_count, row_idx, "L")
    warns = await run(sheets.get_punishment_count, row_idx, "M")
    verbal = await run(sheets.get_punishment_count, row_idx, "N")

    if strict + warns + verbal == 0:
        await callback.message.edit_text("У вас нет наказаний", reply_markup=back_kb())
        await callback.answer()
        return

    options = []
    if strict:
        options.append("Выговор")
    if warns:
        options.append("Предупреждение")
    if verbal:
        options.append("Устный выговор")

    from keyboards.menus import punishment_types_kb
    await state.update_data(remove_punish_flow=True)
    await callback.message.edit_text(
        "Какое наказание хотите снять?",
        reply_markup=punishment_types_kb("rmpunish_select"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rmpunish_select:"))
async def rmpunish_select_type(callback: CallbackQuery, state: FSMContext):
    ptype = callback.data.split(":", 1)[1]
    await state.update_data(punish_type=ptype)
    await state.set_state(RemovePunishRequestFlow.waiting_proof)
    await callback.message.edit_text(
        "Предоставьте доказательства проделанной работы. Загрузите их на imgur.com. или де на другие фотохостинги.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(RemovePunishRequestFlow.waiting_proof)
async def rmpunish_proof(message: Message, state: FSMContext):
    data = await state.get_data()
    ptype = data["punish_type"]
    proof = message.text.strip()
    await state.clear()

    sheets = get_sheets()
    user = get_user(message.from_user.id)
    app_id = await run(
        sheets.create_application, "remove_punish", message.from_user.id, user.nickname, f"{ptype}|{proof}"
    )

    await message.answer("✅ Заявка успешно отправлена руководству!")
    await _notify_managers_new_app(message.bot, user, "Снятие наказания", app_id, f"Наказание: {ptype}\nДоказательства: {proof}")


# ================================================================== Уведомление руководителям
async def _notify_managers_new_app(bot: Bot, user, app_label: str, app_id: int, details: str):
    sheets = get_sheets()
    await sheets.log_application_submitted(
        app_label, user.nickname if user else "?", user.org if user else "", f"#{app_id}: {details}"
    )
    if not user or not user.org:
        return
    managers = managers_for_org(user.org)
    for m in managers:
        try:
            await bot.send_message(
                m.telegram_id,
                f"📩 Новая заявка «{app_label}» #{app_id} от {user.nickname}\n\n{details}",
            )
        except Exception:
            pass
