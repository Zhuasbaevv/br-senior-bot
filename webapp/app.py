"""
Веб-панель BR | Server Manager.

Работает ПАРАЛЛЕЛЬНО с Telegram-ботом, не вместо него: та же Google-таблица,
та же система ролей (utils.access), тот же канал логов. Уведомления, которые
должны прийти человеку в Telegram (одобрения/отказы, алерт о повторном скрине
и т.д.), сайт отправляет через тот же bot-инстанс, что и раньше — просто
действие теперь можно инициировать и с сайта, а не только из бота.

Деплой: второй Railway-сервис из ТОГО ЖЕ репозитория, команда запуска:
    uvicorn webapp.app:app --host 0.0.0.0 --port $PORT
(см. webapp/README.md за подробностями).
"""
from __future__ import annotations

import datetime as dt
import hashlib

from aiogram import Bot
from aiogram.types import BufferedInputFile
from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, Header, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import (
    BOT_TOKEN, Role, ALL_ORGS, ROLE_NAMES, CREATOR_ID, CREATOR_TEST_NORM,
    ACTIVITY_LABELS, REPORT_STATUS_NO_NORM, PUNISHMENT_TYPES, MSK_TZ, LOG_CHANNEL_ID,
    SENIOR_GROUPS, INTERNAL_API_SECRET,
)
from utils.access import (
    get_user, set_user, all_users, load_all_users, managers_for_org, role_name, UserInfo,
)
from utils.passwords import verify_password
from services.sheets import get_sheets
from services.ai_ocr import analyze_report_album, score_report
from webapp.auth import create_session_cookie_value, SESSION_COOKIE_NAME, SESSION_MAX_AGE_SECONDS
from webapp.nav import nav_sections, get_current_user, get_optional_user, RedirectToLogin
from webapp import db as pwdb

app = FastAPI(title="BR Management")
app.mount("/static", StaticFiles(directory="webapp/static"), name="static")
templates = Jinja2Templates(directory="webapp/templates")
templates.env.globals["Role"] = Role
templates.env.globals["role_name"] = role_name


@app.exception_handler(RedirectToLogin)
async def _redirect_to_login(request: Request, exc: RedirectToLogin):
    return RedirectResponse(f"/login{exc.query}")


@app.on_event("startup")
async def on_startup():
    bot = Bot(token=BOT_TOKEN)
    app.state.bot = bot
    get_sheets(bot)  # тот же bot-инстанс -> те же логи в LOG_CHANNEL_ID, что и у самого бота
    await load_all_users()


def _ctx(request: Request, user: UserInfo | None = None, **extra) -> dict:
    base = {
        "request": request,
        "user": user,
        "nav": nav_sections(user.role) if user else [],
    }
    base.update(extra)
    return base


def _client_fingerprint(request: Request) -> tuple[str, str, str]:
    """(fingerprint, ip, user_agent) — грубая идентификация устройства/браузера
    без JS (только по IP + User-Agent). Достаточно, чтобы заметить "вход с нового
    браузера/устройства" — не защита от подмены заголовков, а сигнал для алерта."""
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
    user_agent = request.headers.get("user-agent", "unknown")
    fingerprint = hashlib.sha256(f"{ip}|{user_agent}".encode()).hexdigest()[:20]
    return fingerprint, ip, user_agent


# ============================================================ Авторизация (VK ID + пароль)
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", _ctx(request))


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    vk_id: str = Form(...),
    password: str = Form(...),
):
    sheets = get_sheets()
    profile = await _run(sheets.find_user_by_vk, vk_id.strip())
    error = None

    if not profile:
        error = "Неверный VK ID или пароль."
    else:
        telegram_id = int(profile.get("TelegramID", 0) or 0)
        user = get_user(telegram_id)
        if not user:
            error = "У этого аккаунта нет доступа к системе — обратитесь к следящему."
        elif not pwdb.has_password(telegram_id):
            error = "Пароль для сайта ещё не установлен — задайте его в боте командой /setpassword."
        else:
            stored_hash = pwdb.get_password_hash(telegram_id)
            if not verify_password(password, stored_hash):
                error = "Неверный VK ID или пароль."

    if error:
        return templates.TemplateResponse("login.html", _ctx(request, error=error))

    fingerprint, ip, user_agent = _client_fingerprint(request)
    is_new_device = not pwdb.is_known_device(telegram_id, fingerprint)
    pwdb.remember_device(telegram_id, fingerprint, ip, user_agent)

    if is_new_device:
        try:
            bot: Bot = app.state.bot
            await bot.send_message(
                telegram_id,
                f"🔐 Обнаружен вход в веб-панель с нового устройства/браузера.\n\n"
                f"IP: {ip}\nUser-Agent: {user_agent}\n\n"
                f"Если это были не вы — срочно смените пароль через /setpassword "
                f"или сообщите создателю, чтобы он сбросил вам пароль.",
            )
        except Exception:
            pass

    resp = RedirectResponse("/profile", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_cookie_value(telegram_id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login")
    resp.delete_cookie(SESSION_COOKIE_NAME)
    return resp


# ============================================================ Внутренний API (только бот -> сайт)
@app.post("/internal/set-password")
async def internal_set_password(request: Request, x_internal_secret: str = Header(default="")):
    if not INTERNAL_API_SECRET or x_internal_secret != INTERNAL_API_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")
    body = await request.json()
    telegram_id = int(body["telegram_id"])
    password_hash = str(body["password_hash"])
    pwdb.set_password_hash(telegram_id, password_hash)
    return JSONResponse({"ok": True})


@app.get("/")
async def root(user: UserInfo | None = Depends(get_optional_user)):
    return RedirectResponse("/profile" if user else "/login")


# ============================================================ Профиль
@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, user: UserInfo = Depends(get_current_user)):
    sheets = get_sheets()
    profile_row = await _run(sheets.get_user_row, user.telegram_id)
    profile_row = profile_row or {}

    stat = {}
    row_idx = await _run(sheets.find_nick_row, user.nickname)
    if row_idx:
        stat = await _run(sheets.get_stat_by_row, row_idx)

    position = role_name(Role.CREATOR) if user.role == Role.CREATOR else stat.get("Должность", "—")

    return templates.TemplateResponse(
        "profile.html",
        _ctx(
            request, user,
            position=position,
            profile=profile_row,
            stat=stat,
            added_date=profile_row.get("AddedDate") or stat.get("Дата назначения", "—"),
        ),
    )


async def _run(fn, *args, **kwargs):
    import asyncio
    return await asyncio.to_thread(fn, *args, **kwargs)


# ============================================================ Заявления
@app.get("/applications", response_class=HTMLResponse)
async def applications_menu(request: Request, user: UserInfo = Depends(get_current_user)):
    today = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y")
    return templates.TemplateResponse("applications_menu.html", _ctx(request, user, today=today))


@app.get("/applications/report", response_class=HTMLResponse)
async def report_form(request: Request, user: UserInfo = Depends(get_current_user)):
    return templates.TemplateResponse("report_form.html", _ctx(request, user, result=None))


@app.post("/applications/report", response_class=HTMLResponse)
async def report_submit(
    request: Request,
    user: UserInfo = Depends(get_current_user),
    photos: list[UploadFile] = File(...),
):
    sheets = get_sheets()
    bot: Bot = app.state.bot
    report_date = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y")

    if user.role != Role.CREATOR:
        already = await _run(sheets.has_reported_on, user.nickname, report_date)
        if already:
            return templates.TemplateResponse(
                "report_form.html",
                _ctx(request, user, result={"error": f"Вы уже сдавали отчёт за {report_date}."}),
            )

    images: list[tuple[bytes, str]] = []
    photo_hashes: list[str] = []
    raw_files: list[bytes] = []
    for f in photos:
        data = await f.read()
        if not data:
            continue
        images.append((data, f.content_type or "image/jpeg"))
        photo_hashes.append(hashlib.sha256(data).hexdigest())
        raw_files.append(data)

    if not images:
        return templates.TemplateResponse(
            "report_form.html", _ctx(request, user, result={"error": "Прикрепите хотя бы один скриншот."})
        )

    try:
        analysis = await analyze_report_album(images, report_date)
    except Exception:
        return templates.TemplateResponse(
            "report_form.html",
            _ctx(request, user, result={"error": "Не удалось распознать отчёт. Попробуйте скрины чётче."}),
        )

    profile_row = await _run(sheets.get_user_row, user.telegram_id) or {}
    rank = int(float(profile_row.get("Rank") or 0)) if profile_row else 0
    norm = await _run(sheets.get_norm, user.org, rank) if user.org and rank else None
    if norm is None and user.role == Role.CREATOR:
        norm = CREATOR_TEST_NORM
    if norm is None:
        return templates.TemplateResponse(
            "report_form.html",
            _ctx(request, user, result={"error": "Для вашей организации и ранга норматив ещё не настроен."}),
        )

    # Заливаем скрины в Telegram (в канал логов), чтобы получить file_id — дальше отчёт
    # хранится и просматривается ("Отчётности" в боте) той же логикой, что и отчёты,
    # сданные прямо в Telegram, независимо от того, откуда он реально пришёл.
    photo_file_ids: list[str] = []
    for i, data in enumerate(raw_files):
        try:
            msg = await bot.send_photo(
                LOG_CHANNEL_ID,
                BufferedInputFile(data, filename=f"web_report_{i}.jpg"),
            )
            photo_file_ids.append(msg.photo[-1].file_id)
        except Exception:
            pass

    # Антидубль — та же проверка и тот же формат алерта, что при сдаче через бота.
    duplicate_matches = await _run(sheets.find_duplicate_hashes, photo_hashes, user.telegram_id)
    if duplicate_matches:
        other_nicks = sorted({m.get("NickName", "?") for m in duplicate_matches})
        alert_text = (
            f"🚨 <b>ПОДОЗРЕНИЕ НА ПОВТОРНУЮ СДАЧУ СКРИНА</b>\n\n"
            f"{user.nickname} сдал норматив (через сайт), скрин из которого ранее уже "
            f"был отправлен ({', '.join(other_nicks)}) — скорее проверьте."
        )
        recipients = {u.telegram_id: u for u in managers_for_org(user.org)} if user.org else {}
        recipients[CREATOR_ID] = None
        for tid in recipients:
            try:
                await bot.send_message(tid, alert_text, parse_mode="HTML")
            except Exception:
                pass

    points, status, reasons = score_report(analysis, norm)

    row_idx = await _run(sheets.find_nick_row, user.nickname)
    old_total = await _run(sheets.get_points, row_idx) if row_idx else 0.0
    new_total = await _run(sheets.record_daily_points_by_date, user.nickname, report_date, float(points))
    sheet_write_ok = new_total is not None
    if new_total is None:
        new_total = old_total

    await sheets.log_points(
        user.nickname, f"Отчёт (сайт) — {status}", points, old_total, new_total, "; ".join(reasons),
    )
    if status == REPORT_STATUS_NO_NORM:
        await _run(sheets.bump_no_norm_day, user.nickname)

    counts = analysis.get("counts", {})
    works_parts = [f"{ACTIVITY_LABELS[k]}: {v}" for k, v in counts.items() if v and k in ACTIVITY_LABELS]
    online_h = analysis.get("online_hours_today")
    if online_h:
        works_parts.append(f"Онлайн: {online_h}ч")
    works_done = ", ".join(works_parts) if works_parts else "Ничего не распознано"

    await sheets.log_report_submission(
        user.telegram_id, user.nickname, user.org or "—", report_date, status, points,
        works_done, photo_file_ids, photo_hashes,
    )

    result = {
        "status": status, "points": points, "reasons": reasons,
        "sheet_write_ok": sheet_write_ok,
    }
    return templates.TemplateResponse("report_form.html", _ctx(request, user, result=result))


@app.get("/applications/inactive", response_class=HTMLResponse)
async def inactive_form(request: Request, user: UserInfo = Depends(get_current_user)):
    return templates.TemplateResponse("inactive_form.html", _ctx(request, user, result=None))


@app.post("/applications/inactive", response_class=HTMLResponse)
async def inactive_submit(
    request: Request,
    user: UserInfo = Depends(get_current_user),
    start_date: str = Form(...),
    end_date: str = Form(...),
    reason: str = Form(...),
):
    sheets = get_sheets()
    dates = f"{start_date}/{end_date}"
    app_id = await _run(sheets.create_application, "inactive", user.telegram_id, user.nickname, f"{dates}|{reason}")
    await sheets.log_application_submitted("Неактив", user.nickname, user.org or "", f"#{app_id}: Даты: {dates}, Причина: {reason}")

    bot: Bot = app.state.bot
    for m in (managers_for_org(user.org) if user.org else []):
        try:
            await bot.send_message(
                m.telegram_id, f"📩 Новая заявка «Неактив» #{app_id} от {user.nickname}\n\nДаты: {dates}\nПричина: {reason}"
            )
        except Exception:
            pass

    result = {"app_id": app_id, "dates": dates, "reason": reason}
    return templates.TemplateResponse("inactive_form.html", _ctx(request, user, result=result))


@app.get("/applications/extra-work", response_class=HTMLResponse)
async def extra_work_form(request: Request, user: UserInfo = Depends(get_current_user)):
    return templates.TemplateResponse("extra_work_form.html", _ctx(request, user, result=None))


@app.post("/applications/extra-work", response_class=HTMLResponse)
async def extra_work_submit(
    request: Request,
    user: UserInfo = Depends(get_current_user),
    description: str = Form(...),
    photo: UploadFile = File(...),
):
    sheets = get_sheets()
    bot: Bot = app.state.bot
    data = await photo.read()
    proof_file_id = ""
    if data:
        try:
            msg = await bot.send_photo(
                LOG_CHANNEL_ID, BufferedInputFile(data, filename="web_extra.jpg")
            )
            proof_file_id = msg.photo[-1].file_id
        except Exception:
            pass

    app_id = await _run(
        sheets.create_application, "extra_work", user.telegram_id, user.nickname, f"{description}|{proof_file_id}"
    )
    await sheets.log_application_submitted("Доп.работа", user.nickname, user.org or "", f"#{app_id}: {description}")

    for m in (managers_for_org(user.org) if user.org else []):
        try:
            await bot.send_message(m.telegram_id, f"📩 Новая заявка «Доп.работа» #{app_id} от {user.nickname}\n\nРабота: {description}")
        except Exception:
            pass

    result = {"app_id": app_id, "description": description}
    return templates.TemplateResponse("extra_work_form.html", _ctx(request, user, result=result))


@app.get("/applications/remove-punishment", response_class=HTMLResponse)
async def remove_punish_form(request: Request, user: UserInfo = Depends(get_current_user)):
    sheets = get_sheets()
    row_idx = await _run(sheets.find_nick_row, user.nickname)
    counts = {"L": 0, "M": 0, "N": 0}
    if row_idx:
        for col in counts:
            counts[col] = await _run(sheets.get_punishment_count, row_idx, col)
    options = []
    if counts["L"]:
        options.append("Выговор")
    if counts["M"]:
        options.append("Предупреждение")
    if counts["N"]:
        options.append("Устный выговор")
    return templates.TemplateResponse(
        "remove_punish_form.html", _ctx(request, user, options=options, result=None)
    )


@app.post("/applications/remove-punishment", response_class=HTMLResponse)
async def remove_punish_submit(
    request: Request,
    user: UserInfo = Depends(get_current_user),
    punishment_type: str = Form(...),
    proof_url: str = Form(...),
):
    sheets = get_sheets()
    app_id = await _run(
        sheets.create_application, "remove_punish", user.telegram_id, user.nickname, f"{punishment_type}|{proof_url}"
    )
    await sheets.log_application_submitted(
        "Снятие наказания", user.nickname, user.org or "", f"#{app_id}: {punishment_type}"
    )

    bot: Bot = app.state.bot
    for m in (managers_for_org(user.org) if user.org else []):
        try:
            await bot.send_message(
                m.telegram_id,
                f"📩 Новая заявка «Снятие наказания» #{app_id} от {user.nickname}\n\nНаказание: {punishment_type}\nДоказательства: {proof_url}",
            )
        except Exception:
            pass

    result = {"app_id": app_id, "punishment_type": punishment_type}
    return templates.TemplateResponse("remove_punish_form.html", _ctx(request, user, options=[], result=result))


# ============================================================ Админ: пользователи
@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_list(request: Request, user: UserInfo = Depends(get_current_user)):
    if user.role < Role.LEADER:
        return RedirectResponse("/profile")

    if user.role >= Role.LEADERSHIP:
        targets = all_users()
    elif user.role == Role.SENIOR_WATCHER:
        orgs = SENIOR_GROUPS.get(user.org, [])
        targets = [u for u in all_users() if u.org in orgs]
    else:
        targets = [u for u in all_users() if u.org == user.org]

    return templates.TemplateResponse("admin_users_list.html", _ctx(request, user, targets=targets))


@app.get("/admin/users/add", response_class=HTMLResponse)
async def admin_add_user_form(request: Request, user: UserInfo = Depends(get_current_user)):
    if user.role < Role.LEADER:
        return RedirectResponse("/profile")
    show_org_picker = user.role >= Role.LEADERSHIP or user.role == Role.SENIOR_WATCHER
    orgs = ALL_ORGS
    if user.role == Role.SENIOR_WATCHER:
        orgs = SENIOR_GROUPS.get(user.org, ALL_ORGS)
    return templates.TemplateResponse(
        "admin_add_user.html",
        _ctx(request, user, show_org_picker=show_org_picker, orgs=orgs, result=None),
    )


@app.post("/admin/users/add", response_class=HTMLResponse)
async def admin_add_user_submit(
    request: Request,
    user: UserInfo = Depends(get_current_user),
    telegram_id: int = Form(...),
    nickname: str = Form(...),
    org: str = Form(None),
    rank: int = Form(...),
):
    if user.role < Role.LEADER:
        return RedirectResponse("/profile")

    clean_nick = nickname.strip().replace("\xa0", " ").replace("\u200b", "").strip()
    target_org = user.org if user.role in (Role.LEADER, Role.WATCHER) else org

    sheets = get_sheets()
    today = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y")
    row = await _run(sheets.assign_nick_to_org, target_org, clean_nick, today)
    await _run(
        sheets.upsert_user, telegram_id,
        NickName=clean_nick, Role=role_name(Role.STAFF), Org=target_org,
        AddedBy=user.nickname, AddedDate=today, Rank=rank,
    )
    set_user(telegram_id, clean_nick, Role.STAFF, target_org, row)
    await sheets.log_access(clean_nick, user.nickname, "🟢 Выдано")

    orgs = ALL_ORGS
    show_org_picker = user.role >= Role.LEADERSHIP or user.role == Role.SENIOR_WATCHER
    result = {"nickname": clean_nick, "org": target_org, "rank": rank}
    return templates.TemplateResponse(
        "admin_add_user.html",
        _ctx(request, user, show_org_picker=show_org_picker, orgs=orgs, result=result),
    )


# ============================================================ Инструменты / команды
@app.get("/tools/members", response_class=HTMLResponse)
async def tools_members(request: Request, user: UserInfo = Depends(get_current_user)):
    # На сайте нет живого /join-состояния из Telegram (это чисто внутренняя память бота) —
    # показываем состав по организациям вместо "кто сейчас в игре".
    if user.role >= Role.LEADERSHIP:
        grouped = {org: [u for u in all_users() if u.org == org] for org in ALL_ORGS}
    else:
        grouped = {user.org: [u for u in all_users() if u.org == user.org]} if user.org else {}
    return templates.TemplateResponse("tools_members.html", _ctx(request, user, grouped=grouped))


# ============================================================ Заглушки для "в разработке"
@app.get("/admin/{page}", response_class=HTMLResponse)
async def admin_placeholder(page: str, request: Request, user: UserInfo = Depends(get_current_user)):
    return templates.TemplateResponse("placeholder.html", _ctx(request, user, page=page))


@app.get("/tools/{page}", response_class=HTMLResponse)
async def tools_placeholder(page: str, request: Request, user: UserInfo = Depends(get_current_user)):
    return templates.TemplateResponse("placeholder.html", _ctx(request, user, page=page))
