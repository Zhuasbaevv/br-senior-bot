"""
Обёртка над Google Sheets API (gspread).
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
from typing import Any

import gspread
from aiogram import Bot
from google.oauth2.service_account import Credentials

from config import (
    GOOGLE_CREDENTIALS_PATH,
    GOOGLE_CREDENTIALS_JSON_BASE64,
    GOOGLE_CREDENTIALS_JSON,
    GOOGLE_SHEET_ID,
    SHEET_MAIN,
    SHEET_USERS,
    SHEET_APPLICATIONS,
    SHEET_LOG_ACCESS,
    SHEET_LOG_PUNISH,
    SHEET_LOG_POINTS,
    SHEET_LOG_EXTRA,
    SHEET_LOG_MODERATION,
    SHEET_LOG_REPORTS,
    SHEET_NORMS,
    MSK_TZ,
    LOG_CHANNEL_ID,
    CREATOR_ID,
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Название листа-шаблона, с которого копируется структура при создании
# новой недели. Должен существовать в таблице как есть (создайте вручную).
TEMPLATE_SHEET_NAME = "Шаблон"

_SHEET_HEADERS = {
    SHEET_USERS: [
        "TelegramID", "NickName", "VK", "DiscordID", "Forum",
        "Age", "Timezone", "TelegramUsername", "Email",
        "Role", "Org", "AddedBy", "AddedDate",
        "NormOnline", "NormReport", "Rank",
    ],
    SHEET_APPLICATIONS: [
        "ID", "Type", "TelegramID", "NickName", "Data",
        "Status", "DecidedBy", "DecisionReason", "CreatedAt", "DecidedAt",
    ],
    SHEET_LOG_ACCESS: [
        "TargetNick", "AdminNick", "DateTime", "Status", "Reason",
    ],
    SHEET_LOG_PUNISH: [
        "TargetNick", "IssuedBy", "Type", "IssuedAt", "RemovedAt",
        "Reason", "RemoveReason", "RemovedBy", "Status", "Proof",
    ],
    SHEET_LOG_POINTS: [
        "TargetNick", "ChangedBy", "Delta", "OldValue", "NewValue",
        "Reason", "DateTime",
    ],
    SHEET_LOG_EXTRA: [
        "TargetNick", "ApprovedBy", "Work", "Date", "Screenshots",
    ],
    SHEET_LOG_MODERATION: [
        "ActorNick", "Action", "TargetNick", "Details", "DateTime",
    ],
    SHEET_LOG_REPORTS: [
        "TelegramID", "NickName", "Org", "ReportDate", "Status", "Points",
        "WorksDone", "PhotoFileIDs", "PhotoHashes", "CreatedAt",
    ],
    SHEET_NORMS: [
        "Org", "Rank", "VCH", "Interview", "Lecture", "Training", "RP", "OnlineHours",
    ],
}

# Статические диапазоны строк по блокам организаций на листе-шаблоне.
# ВНИМАНИЕ: это должно 1-в-1 соответствовать реальной раскладке строк
# в листе "Шаблон" (см. TEMPLATE_SHEET_NAME) — если в шаблоне у организации
# другое количество строк, поправь диапазон здесь.
ORG_ROW_RANGES = {
    "Арзамасская ОПГ": (5, 10),
    "Батыревская ОПГ": (12, 17),
    "Лыткаринская ОПГ": (19, 24),
    "Правительство": (27, 32),
    "ФСБ": (35, 40),
    "УМВД": (43, 48),
    "ГИБДД": (51, 56),
    "Армия": (59, 64),
    "ФСИН": (67, 72),
    "СМИ": (75, 80),
    "Больница": (83, 88),
}


def _load_google_credentials(scopes: list[str]) -> Credentials:
    """Credentials для сервис-аккаунта — пробуем по порядку:
    1) GOOGLE_CREDENTIALS_JSON_BASE64 — credentials.json целиком в base64 (САМЫЙ
       надёжный вариант для вставки через веб-панель хостинга на телефоне: base64
       состоит только из букв/цифр/+//=, его нечем испортить автозаменой/переносами
       строк — в отличие от сырого JSON, где \\n внутри private_key легко ломается);
    2) GOOGLE_CREDENTIALS_JSON — тот же JSON, но НЕ закодированный (проще завести
       руками, но более хрупко при вставке с телефона);
    3) файл GOOGLE_CREDENTIALS_PATH — для локального запуска и хостингов с
       нормальной загрузкой секретных файлов (Render Secret Files и т.п.)."""
    if GOOGLE_CREDENTIALS_JSON_BASE64:
        try:
            raw = base64.b64decode(GOOGLE_CREDENTIALS_JSON_BASE64).decode("utf-8")
            info = json.loads(raw)
        except Exception as e:
            raise ValueError(
                "GOOGLE_CREDENTIALS_JSON_BASE64 задан, но не расшифровывается в валидный JSON — "
                "проверь, что скопирована ВСЯ base64-строка целиком, без пропусков."
            ) from e
        return Credentials.from_service_account_info(info, scopes=scopes)
    if GOOGLE_CREDENTIALS_JSON:
        try:
            info = json.loads(GOOGLE_CREDENTIALS_JSON)
        except json.JSONDecodeError as e:
            raise ValueError(
                "GOOGLE_CREDENTIALS_JSON задан, но не парсится как JSON — проверь, что "
                "содержимое credentials.json вставлено ЦЕЛИКОМ и без искажений. Если вставка "
                "с телефона регулярно ломается — используй GOOGLE_CREDENTIALS_JSON_BASE64 вместо неё."
            ) from e
        return Credentials.from_service_account_info(info, scopes=scopes)
    return Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)


class SheetsService:
    def __init__(self, bot: Bot | None = None) -> None:
        creds = _load_google_credentials(SCOPES)
        self._client = gspread.authorize(creds)
        self._spreadsheet = self._client.open_by_key(GOOGLE_SHEET_ID)
        self.bot = bot
        self._creator_warned = False
        self._ensure_sheets()

    # -- Вспомогательные методы для отправки логов в канал --
    async def _warn_creator_once(self, reason: str) -> None:
        """Если лог не удалось отправить в канал (или self.bot вообще не задан),
        шлём один раз в личку создателю — чтобы это не терялось молча в консоли,
        которую по факту никто не читает постоянно."""
        if self._creator_warned:
            return
        self._creator_warned = True
        if not self.bot:
            return
        try:
            await self.bot.send_message(
                CREATOR_ID,
                f"⚠️ Логи в канал (LOG_CHANNEL_ID) не отправляются.\n\nПричина: {reason}\n\n"
                f"Проверь: бот добавлен в канал админом с правом постить сообщения, "
                f"и LOG_CHANNEL_ID в config.py указан верно.",
            )
        except Exception:
            pass  # даже создателю не достучаться — дальше только консоль

    async def _send_log_msg(self, text: str) -> None:
        if not self.bot:
            print("[LOG ERROR] self.bot не задан — SheetsService создан без get_sheets(bot). Лог не отправлен.")
            await self._warn_creator_once("self.bot не задан (get_sheets() вызван без bot)")
            return
        if not LOG_CHANNEL_ID:
            print("[LOG ERROR] LOG_CHANNEL_ID пустой в config.py. Лог не отправлен.")
            return
        try:
            await self.bot.send_message(LOG_CHANNEL_ID, text, parse_mode="HTML")
        except Exception as e:
            print(f"[LOG ERROR] Не удалось отправить текстовый лог в канал {LOG_CHANNEL_ID}: {e}")
            await self._warn_creator_once(str(e))

    async def _send_log_photo(self, photo: str, caption: str) -> None:
        if not self.bot:
            print("[LOG ERROR] self.bot не задан — SheetsService создан без get_sheets(bot). Лог не отправлен.")
            await self._warn_creator_once("self.bot не задан (get_sheets() вызван без bot)")
            return
        if not LOG_CHANNEL_ID:
            print("[LOG ERROR] LOG_CHANNEL_ID пустой в config.py. Лог не отправлен.")
            return
        try:
            await self.bot.send_photo(LOG_CHANNEL_ID, photo=photo, caption=caption, parse_mode="HTML")
        except Exception as e:
            print(f"[LOG ERROR] Не удалось отправить фото-лог в канал {LOG_CHANNEL_ID}: {e}")
            await self._warn_creator_once(str(e))
            fallback_text = f"{caption}\n\n🔗 <b>Медиа/Пруф:</b> {photo}"
            await self._send_log_msg(fallback_text)

    async def _send_log_album(self, photo_file_ids: list[str], caption: str) -> None:
        """Отправляет несколько фото одним альбомом в канал, с подписью на первом фото.
        Telegram альбом — максимум 10 фото за раз, режем на группы при необходимости."""
        if not self.bot:
            print("[LOG ERROR] self.bot не задан — SheetsService создан без get_sheets(bot). Лог не отправлен.")
            await self._warn_creator_once("self.bot не задан (get_sheets() вызван без bot)")
            return
        if not LOG_CHANNEL_ID:
            print("[LOG ERROR] LOG_CHANNEL_ID пустой в config.py. Лог не отправлен.")
            return
        if not photo_file_ids:
            await self._send_log_msg(caption)
            return
        from aiogram.types import InputMediaPhoto
        try:
            for i in range(0, len(photo_file_ids), 10):
                chunk = photo_file_ids[i:i + 10]
                media = [
                    InputMediaPhoto(media=fid, caption=caption if j == 0 and i == 0 else None, parse_mode="HTML")
                    for j, fid in enumerate(chunk)
                ]
                await self.bot.send_media_group(LOG_CHANNEL_ID, media=media)
        except Exception as e:
            print(f"[LOG ERROR] Не удалось отправить альбом лога: {e}")
            await self._send_log_msg(caption)

    # -- Автоматическое определение текущего листа недели ----------------
    @property
    def current_sheet_title(self) -> str:
        """Лист недели по СЕГОДНЯШНЕЙ дате (Пн-Вс), если такой лист уже существует,
        иначе — SHEET_MAIN (например, пока новый лист недели ещё не создан)."""
        expected_title = self._week_title_for(dt.datetime.now(MSK_TZ))
        if expected_title in self._existing_titles():
            return expected_title
        return SHEET_MAIN

    @staticmethod
    def _week_title_for(target_date: dt.datetime) -> str:
        monday = target_date - dt.timedelta(days=target_date.weekday())
        sunday = monday + dt.timedelta(days=6)
        return f"{monday.strftime('%d.%m.%Y')} | {sunday.strftime('%d.%m.%Y')}"

    def _existing_titles(self) -> set[str]:
        return {ws.title for ws in self._spreadsheet.worksheets()}

    # -- инициализация -------------------------------------------------
    def _ensure_sheets(self) -> None:
        existing = self._existing_titles()
        for name, headers in _SHEET_HEADERS.items():
            if name not in existing:
                ws = self._spreadsheet.add_worksheet(title=name, rows=1000, cols=len(headers) + 2)
                ws.append_row(headers)
        if SHEET_MAIN not in existing:
            raise RuntimeError(
                f"Лист '{SHEET_MAIN}' не найден в таблице. "
                f"Доступные листы: {sorted(existing)}. "
                f"Переименуйте свой лист со статистикой в '{SHEET_MAIN}' "
                f"или поменяйте SHEET_MAIN в config.py на точное название вашего листа."
            )
        if TEMPLATE_SHEET_NAME not in existing:
            print(
                f"[WARNING] Лист-шаблон '{TEMPLATE_SHEET_NAME}' не найден в таблице. "
                f"Автосоздание нового листа недели (create_week_sheet_manual) работать не будет, "
                f"пока вы не добавите лист с этим названием (или не поменяете TEMPLATE_SHEET_NAME "
                f"в services/sheets.py на название своего листа-шаблона)."
            )

    def ws(self, name: str):
        return self._spreadsheet.worksheet(name)

    # -- generic helpers -------------------------------------------------
    @staticmethod
    def _normalize_header(s) -> str:
        """Заголовки в основном листе печатались вручную и там реально встречаются
        хвостовые пробелы ('NickName ') и переносы строк внутри ('Строгие\\nвыговоры')
        — визуально в таблице это не видно, а точное сравнение строк из-за этого
        ломалось (колонка как бы 'не находилась'). Схлопываем любые пробелы/переносы
        в один пробел и убираем края — 'Строгие\\nвыговоры' -> 'Строгие выговоры'."""
        import re
        return re.sub(r"\s+", " ", str(s)).strip()

    def _header_index(self, headers: list[str], name: str) -> int | None:
        """0-based индекс колонки по нормализованному совпадению имени заголовка."""
        target = self._normalize_header(name)
        for i, h in enumerate(headers):
            if self._normalize_header(h) == target:
                return i
        return None

    @staticmethod
    def _normalize_for_match(s) -> str:
        """Убирает обычные и неразрывные/нулевой-ширины пробелы по краям — с телефона
        (автокоррекция, копипаст) в NickName иногда прилетает невидимый мусор, из-за
        которого точное сравнение строк давало 'не найден' для реально существующей строки."""
        return (
            str(s).strip()
            .replace("\xa0", " ")
            .replace("\u200b", "")
            .strip()
        )

    def _find_row_by(self, sheet_name: str, col_name: str, value: str) -> int | None:
        ws = self.ws(sheet_name)
        headers = ws.row_values(1)
        header_idx = self._header_index(headers, col_name)
        if header_idx is None:
            return None
        col_idx = header_idx + 1
        col_values = ws.col_values(col_idx)
        target = self._normalize_for_match(value)
        for i, v in enumerate(col_values[1:], start=2):
            if self._normalize_for_match(v) == target:
                return i
        return None

    # ================= Пользователи (верификация/доступ) =================
    def get_user_row(self, telegram_id: int) -> dict | None:
        ws = self.ws(SHEET_USERS)
        row_idx = self._find_row_by(SHEET_USERS, "TelegramID", str(telegram_id))
        if row_idx is None:
            return None
        headers = [self._normalize_header(h) for h in ws.row_values(1)]
        values = ws.row_values(row_idx)
        values += [""] * (len(headers) - len(values))
        return dict(zip(headers, values)) | {"_row": row_idx}

    def find_user_by_vk(self, vk_id: str) -> dict | None:
        """Для входа на веб-панель по VK ID + паролю. ВНИМАНИЕ: для работы нужно,
        чтобы в листе 'Пользователи' были колонки PasswordHash и (опционально)
        LoginFingerprint — если их там ещё нет, добавь заголовками руками, автосоздание
        только для новых листов, не для уже существующего 'Пользователи'."""
        ws = self.ws(SHEET_USERS)
        row_idx = self._find_row_by(SHEET_USERS, "VK", vk_id)
        if row_idx is None:
            return None
        headers = [self._normalize_header(h) for h in ws.row_values(1)]
        values = ws.row_values(row_idx)
        values += [""] * (len(headers) - len(values))
        return dict(zip(headers, values)) | {"_row": row_idx}

    def upsert_user(self, telegram_id: int, **fields: Any) -> None:
        ws = self.ws(SHEET_USERS)
        headers = ws.row_values(1)
        row_idx = self._find_row_by(SHEET_USERS, "TelegramID", str(telegram_id))
        if row_idx is None:
            row = ["" for _ in headers]
            tid_idx = self._header_index(headers, "TelegramID")
            if tid_idx is not None:
                row[tid_idx] = str(telegram_id)
            for k, v in fields.items():
                idx = self._header_index(headers, k)
                if idx is not None:
                    row[idx] = str(v)
            ws.append_row(row)
        else:
            for k, v in fields.items():
                idx = self._header_index(headers, k)
                if idx is not None:
                    ws.update_cell(row_idx, idx + 1, str(v))

    def delete_user(self, telegram_id: int) -> None:
        row_idx = self._find_row_by(SHEET_USERS, "TelegramID", str(telegram_id))
        if row_idx:
            self.ws(SHEET_USERS).delete_rows(row_idx)

    def list_users(self, role: str | None = None, org: str | None = None) -> list[dict]:
        ws = self.ws(SHEET_USERS)
        records = ws.get_all_records()
        if role:
            records = [r for r in records if str(r.get("Role")) == role]
        if org:
            records = [r for r in records if str(r.get("Org")) == org]
        return records

    # ================= Основной лист статистики =================
    def find_nick_row(self, nickname: str, sheet_title: str | None = None) -> int | None:
        return self._find_row_by(sheet_title or self.current_sheet_title, "NickName", nickname)

    def debug_find_nick(self, nickname: str) -> str:
        """Диагностика 'бот не находит человека, хотя он явно есть в таблице'. Возвращает
        построчный repr() искомого ника и КАЖДОГО непустого значения из колонки NickName
        на текущем листе — это вскрывает невидимые символы, разный регистр и т.п.,
        которые визуально в таблице выглядят одинаково, а строкой не совпадают."""
        sheet_title = self.current_sheet_title
        ws = self.ws(sheet_title)
        headers = ws.row_values(1)
        header_idx = self._header_index(headers, "NickName")
        if header_idx is None:
            return f"На листе '{sheet_title}' вообще нет колонки NickName в шапке: {headers}"
        col_idx = header_idx + 1
        col_values = ws.col_values(col_idx)

        target_norm = self._normalize_for_match(nickname)
        lines = [
            f"Лист: {sheet_title}",
            f"Заголовок колонки (сырой): {headers[header_idx]!r}",
            f"Искомый ник: {nickname!r} (нормализован: {target_norm!r})",
            "",
            "Непустые значения в колонке NickName:",
        ]
        found_row = None
        for i, v in enumerate(col_values[1:], start=2):
            if not v.strip():
                continue
            v_norm = self._normalize_for_match(v)
            match = "✅ СОВПАДЕНИЕ" if v_norm == target_norm else ""
            if match:
                found_row = i
            lines.append(f"  строка {i}: {v!r} (нормализован: {v_norm!r}) {match}")

        lines.append("")
        lines.append(f"Итог: {'найдено в строке ' + str(found_row) if found_row else 'НЕ найдено'}")
        return "\n".join(lines)

    def find_first_empty_slot(self, org: str) -> int | None:
        """Находит первую пустую строку (без NickName) в блоке организации по точным диапазонам."""
        if org not in ORG_ROW_RANGES:
            return None

        start_row, end_row = ORG_ROW_RANGES[org]
        ws = self.ws(self.current_sheet_title)

        for row in range(start_row, end_row + 1):
            cell_val = ws.cell(row, 2).value
            if not cell_val or not str(cell_val).strip():
                return row

        return None

    def assign_nick_to_org(self, org: str, nickname: str, date_str: str) -> int | None:
        row = self.find_first_empty_slot(org)
        if row is None:
            return None
        ws = self.ws(self.current_sheet_title)
        ws.update_cell(row, 2, nickname)   # NickName -> столбец B
        ws.update_cell(row, 3, date_str)   # Дата назначения -> столбец C
        return row

    def clear_nick_slot(self, row: int) -> None:
        ws = self.ws(self.current_sheet_title)
        ws.update_cell(row, 2, "")
        ws.update_cell(row, 3, "")

    def get_stat_by_row(self, row: int) -> dict:
        ws = self.ws(self.current_sheet_title)
        headers = [self._normalize_header(h) for h in ws.row_values(1)]
        values = ws.row_values(row)
        values += [""] * (len(headers) - len(values))
        return dict(zip(headers, values))

    def get_points(self, row: int) -> float:
        val = self.ws(self.current_sheet_title).cell(row, 11).value or "0"  # столбец K
        try:
            return float(val)
        except ValueError:
            return 0.0

    def set_points(self, row: int, value: float) -> None:
        self.ws(self.current_sheet_title).update_cell(row, 11, value)

    def add_points(self, row: int, delta: float) -> tuple[float, float]:
        old = self.get_points(row)
        new = old + delta
        self.set_points(row, new)
        return old, new

    def _find_day_column(self, ws, target_date_str: str) -> int | None:
        """Ищет колонку из диапазона D-J (4-10), чья шапка совпадает с датой."""
        target_date = target_date_str.split()[0].strip()
        for c in range(4, 11):
            cell_val = ws.cell(1, c).value
            if not cell_val:
                continue
            clean_cell_val = str(cell_val).strip().split()[0]
            if clean_cell_val == target_date or clean_cell_val == target_date[:5]:
                return c
        return None

    def record_daily_points_by_date(self, nickname: str, report_date_str: str, points: float) -> float | None:
        """Записывает баллы в ячейку на пересечении строки сотрудника и колонки конкретной
        даты (D-J), пересчитывает итог (K) и возвращает новый итог (или None при ошибке)."""
        ws = self.ws(self.current_sheet_title)
        row_idx = self.find_nick_row(nickname)
        if not row_idx:
            print(f"[DEBUG] Ник '{nickname}' не найден в таблице!")
            return None

        col_idx = self._find_day_column(ws, report_date_str)
        if col_idx is None:
            print(f"[DEBUG] Не нашли колонку для даты {report_date_str} в диапазоне D-J!")
            return None

        ws.update_cell(row_idx, col_idx, points)
        return self._recalc_total(ws, row_idx)

    def bump_no_norm_day(self, nickname: str) -> int | None:
        """+1 к колонке P ('Дни неактив/нет нормы') — вызывается, когда статус отчёта
        за день оказался 'Нет нормы' (пустой отчёт). Возвращает новое значение счётчика."""
        ws = self.ws(self.current_sheet_title)
        row_idx = self.find_nick_row(nickname)
        if not row_idx:
            return None
        current = ws.cell(row_idx, 16).value or "0"  # столбец P
        try:
            new_val = int(float(str(current).replace(",", ".") or 0)) + 1
        except ValueError:
            new_val = 1
        ws.update_cell(row_idx, 16, new_val)
        return new_val

    def mark_inactive_day(self, nickname: str, date_obj: dt.date) -> bool:
        """Для одобренной заявки на неактив: ставит '-' в клетку конкретного дня (D-J,
        чтобы он не учитывался в сумме баллов K) и +1 к колонке P ('Дни неактив/нет нормы')
        на листе НЕДЕЛИ, к которой относится date_obj (может быть не текущая неделя)."""
        target_date = dt.datetime.combine(date_obj, dt.time())
        week_title = self.get_or_create_week_sheet(target_date)
        if not week_title:
            print(f"[ERROR] Не удалось получить/создать лист недели для {date_obj}")
            return False

        ws = self.ws(week_title)
        row_idx = self.find_nick_row(nickname, sheet_title=week_title)
        if not row_idx:
            print(f"[DEBUG] Ник '{nickname}' не найден в листе '{week_title}'!")
            return False

        date_str = date_obj.strftime("%d.%m.%Y")
        col_idx = self._find_day_column(ws, date_str)
        if col_idx is not None:
            ws.update_cell(row_idx, col_idx, "-")

        current = ws.cell(row_idx, 16).value or "0"  # столбец P
        try:
            new_val = int(float(str(current).replace(",", ".") or 0)) + 1
        except ValueError:
            new_val = 1
        ws.update_cell(row_idx, 16, new_val)
        return True

    def _recalc_total(self, ws, row_idx: int) -> float:
        total_points = 0.0
        for c in range(4, 11):
            val = ws.cell(row_idx, c).value
            if val is not None and str(val).strip() != "":
                try:
                    total_points += float(str(val).replace(",", "."))
                except ValueError:
                    pass
        ws.update_cell(row_idx, 11, total_points)
        return total_points

    def get_daily_points(self, nickname: str, sheet_title: str | None = None) -> list[dict]:
        """Возвращает список {date, points, status} по каждому из 7 дней недели для сотрудника."""
        sheet_title = sheet_title or self.current_sheet_title
        ws = self.ws(sheet_title)
        row_idx = self.find_nick_row(nickname, sheet_title=sheet_title)
        if not row_idx:
            return []

        daily_points = []
        for c in range(4, 11):
            date_val = ws.cell(1, c).value
            points_val = ws.cell(row_idx, c).value
            daily_points.append({
                "date": date_val or "",
                "points": points_val or "",
            })
        return daily_points

    def get_punishment_count(self, row: int, col_letter: str) -> int:
        col_map = {"L": 12, "M": 13, "N": 14}
        val = self.ws(self.current_sheet_title).cell(row, col_map[col_letter]).value or "0"
        try:
            return int(float(val))
        except ValueError:
            return 0

    def change_punishment_count(self, row: int, col_letter: str, delta: int) -> int:
        col_map = {"L": 12, "M": 13, "N": 14}
        current = self.get_punishment_count(row, col_letter)
        new_val = max(0, current + delta)
        self.ws(self.current_sheet_title).update_cell(row, col_map[col_letter], new_val)
        return new_val

    # ================= Заявки =================
    def next_application_id(self) -> int:
        ws = self.ws(SHEET_APPLICATIONS)
        ids = ws.col_values(1)[1:]
        nums = [int(x) for x in ids if x.isdigit()]
        return (max(nums) + 1) if nums else 1000

    def create_application(self, app_type: str, telegram_id: int, nickname: str, data: str) -> int:
        ws = self.ws(SHEET_APPLICATIONS)
        app_id = self.next_application_id()
        now = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S")
        ws.append_row([app_id, app_type, telegram_id, nickname, data, "pending", "", "", now, ""])
        return app_id

    def decide_application(self, app_id: int, status: str, decided_by: str, reason: str = "") -> dict | None:
        ws = self.ws(SHEET_APPLICATIONS)
        row_idx = self._find_row_by(SHEET_APPLICATIONS, "ID", str(app_id))
        if row_idx is None:
            return None
        headers = ws.row_values(1)
        now = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S")
        ws.update_cell(row_idx, headers.index("Status") + 1, status)
        ws.update_cell(row_idx, headers.index("DecidedBy") + 1, decided_by)
        ws.update_cell(row_idx, headers.index("DecisionReason") + 1, reason)
        ws.update_cell(row_idx, headers.index("DecidedAt") + 1, now)
        values = ws.row_values(row_idx)
        values += [""] * (len(headers) - len(values))
        return dict(zip(headers, values))

    def get_pending_applications(self, app_type: str | None = None) -> list[dict]:
        ws = self.ws(SHEET_APPLICATIONS)
        records = ws.get_all_records()
        out = [r for r in records if str(r.get("Status")) == "pending"]
        if app_type:
            out = [r for r in out if str(r.get("Type")) == app_type]
        return out

    # ================= Логи (с дублированием абсолютно всего в канал) =================
    async def log_access(self, target_nick: str, admin_nick: str, status: str, reason: str = "") -> None:
        now = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S")
        self.ws(SHEET_LOG_ACCESS).append_row([target_nick, admin_nick, now, status, reason])
        text = (
            f"🔐 <b>ЛОГ ДОСТУПА</b>\n"
            f"👤 <b>Кого:</b> {target_nick}\n"
            f"👮‍♂️ <b>Админ:</b> {admin_nick}\n"
            f"📌 <b>Статус:</b> {status}\n"
            f"📝 <b>Причина:</b> {reason or 'Не указана'}\n"
            f"⏱ <b>Время:</b> {now}"
        )
        await self._send_log_msg(text)

    async def log_punishment_issue(self, target_nick: str, issued_by: str, ptype: str, reason: str) -> None:
        now = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S")
        self.ws(SHEET_LOG_PUNISH).append_row(
            [target_nick, issued_by, ptype, now, "", reason, "", "", "🔴 Еще активен", ""]
        )
        text = (
            f"⚠️ <b>ВЫДАЧА НАКАЗАНИЯ</b>\n"
            f"👤 <b>Нарушитель:</b> {target_nick}\n"
            f"⚖️ <b>Тип:</b> {ptype}\n"
            f"👮‍♂️ <b>Выдал:</b> {issued_by}\n"
            f"📝 <b>Причина:</b> {reason}\n"
            f"⏱ <b>Время:</b> {now}"
        )
        await self._send_log_msg(text)

    async def log_punishment_remove(
        self, target_nick: str, ptype: str, remove_reason: str, removed_by: str, proof: str = ""
    ) -> None:
        ws = self.ws(SHEET_LOG_PUNISH)
        headers = ws.row_values(1)
        records = ws.get_all_records()
        now = ""
        for i in range(len(records) - 1, -1, -1):
            r = records[i]
            if r.get("TargetNick") == target_nick and r.get("Type") == ptype and r.get("Status") == "🔴 Еще активен":
                row_idx = i + 2
                now = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S")
                ws.update_cell(row_idx, headers.index("RemovedAt") + 1, now)
                ws.update_cell(row_idx, headers.index("RemoveReason") + 1, remove_reason)
                ws.update_cell(row_idx, headers.index("RemovedBy") + 1, removed_by)
                ws.update_cell(row_idx, headers.index("Status") + 1, "🟢 Снят")
                ws.update_cell(row_idx, headers.index("Proof") + 1, proof)
                break

        caption = (
            f"🟢 <b>СНЯТИЕ НАКАЗАНИЯ</b>\n"
            f"👤 <b>С кого:</b> {target_nick}\n"
            f"⚖️ <b>Тип:</b> {ptype}\n"
            f"👮‍♂️ <b>Снял:</b> {removed_by}\n"
            f"📝 <b>Причина снятия:</b> {remove_reason}\n"
            f"⏱ <b>Время:</b> {now or dt.datetime.now(MSK_TZ).strftime('%d.%m.%Y %H:%M:%S')}"
        )
        if proof:
            await self._send_log_photo(proof, caption)
        else:
            await self._send_log_msg(caption)

    async def log_points(self, target_nick: str, changed_by: str, delta: float, old: float, new: float, reason: str) -> None:
        now = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S")
        self.ws(SHEET_LOG_POINTS).append_row([target_nick, changed_by, delta, old, new, reason, now])
        sign = "+" if delta > 0 else ""
        text = (
            f"⭐ <b>ИЗМЕНЕНИЕ БАЛЛОВ</b>\n"
            f"👤 <b>Сотрудник:</b> {target_nick}\n"
            f"⚖️ <b>Изменение:</b> <code>{sign}{delta}</code> (Было: {old} ➡️ Стало: {new})\n"
            f"👮‍♂️ <b>Кто изменил:</b> {changed_by}\n"
            f"📝 <b>Причина:</b> {reason}\n"
            f"⏱ <b>Время:</b> {now}"
        )
        await self._send_log_msg(text)

    async def log_extra_work(self, target_nick: str, approved_by: str, work: str, screenshots: str) -> None:
        now = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y")
        self.ws(SHEET_LOG_EXTRA).append_row([target_nick, approved_by, work, now, screenshots])
        caption = (
            f"📂 <b>ДОПОЛНИТЕЛЬНАЯ РАБОТА</b>\n"
            f"👤 <b>Сотрудник:</b> {target_nick}\n"
            f"📋 <b>Работа:</b> {work}\n"
            f"✅ <b>Одобрил:</b> {approved_by}\n"
            f"⏱ <b>Дата:</b> {now}"
        )
        if screenshots:
            await self._send_log_photo(screenshots, caption)
        else:
            await self._send_log_msg(caption)

    async def log_moderation(self, actor_nick: str, action: str, target_nick: str, details: str) -> None:
        now = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S")
        self.ws(SHEET_LOG_MODERATION).append_row([actor_nick, action, target_nick, details, now])
        text = (
            f"🛡 <b>МОДЕРАЦИЯ / ДЕЙСТВИЕ</b>\n"
            f"👤 <b>Админ:</b> {actor_nick}\n"
            f"⚡ <b>Действие:</b> {action}\n"
            f"🎯 <b>Цель:</b> {target_nick or 'Не указана'}\n"
            f"📋 <b>Детали:</b> {details}\n"
            f"⏱ <b>Время:</b> {now}"
        )
        await self._send_log_msg(text)

    def get_logs_for(self, sheet_name: str, nick: str) -> list[dict]:
        ws = self.ws(sheet_name)
        records = ws.get_all_records()
        return [r for r in records if r.get("TargetNick") == nick]

    # ================= Логи отчётов (для просмотра "Отчётности" + антидубль) =================
    async def log_report_submission(
        self, telegram_id: int, nickname: str, org: str, report_date: str, status: str,
        points: int, works_done: str, photo_file_ids: list[str], photo_hashes: list[str],
    ) -> None:
        """Сохраняет полную запись об отчёте (для последующего просмотра в 'Отчётности')
        и дублирует её со скринами в канал логов."""
        now = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S")
        self.ws(SHEET_LOG_REPORTS).append_row([
            telegram_id, nickname, org, report_date, status, points,
            works_done, ",".join(photo_file_ids), ",".join(photo_hashes), now,
        ])
        caption = (
            f"📋 <b>НОВЫЙ ОТЧЁТ (НОРМАТИВ)</b>\n"
            f"👤 <b>NickName:</b> {nickname}\n"
            f"🏢 <b>Организация:</b> {org}\n"
            f"📅 <b>Дата отчёта:</b> {report_date}\n"
            f"📌 <b>Статус:</b> {status}\n"
            f"⭐ <b>Баллы:</b> {points:+d}\n"
            f"📝 <b>Работы:</b> {works_done}\n"
            f"⏱ <b>Время:</b> {now}"
        )
        await self._send_log_album(photo_file_ids, caption)

    def find_duplicate_hashes(self, hashes: list[str], exclude_telegram_id: int | None = None) -> list[dict]:
        """Ищет среди ВСЕХ ранее сохранённых отчётов совпадение хотя бы одного хэша скрина
        (защита от повторной сдачи чужого/старого скрина). Возвращает список записей
        (строк из Логи_отчётов), с которыми найдено совпадение."""
        if not hashes:
            return []
        ws = self.ws(SHEET_LOG_REPORTS)
        records = ws.get_all_records()
        hash_set = set(hashes)
        matches = []
        for r in records:
            if exclude_telegram_id is not None and str(r.get("TelegramID")) == str(exclude_telegram_id):
                continue
            existing_hashes = set((r.get("PhotoHashes") or "").split(","))
            if hash_set & existing_hashes:
                matches.append(r)
        return matches

    def get_reports_for(self, nickname: str, limit: int = 15) -> list[dict]:
        """Последние N сохранённых отчётов конкретного человека (для просмотра в 'Отчётности')."""
        ws = self.ws(SHEET_LOG_REPORTS)
        records = ws.get_all_records()
        records = [r for r in records if r.get("NickName") == nickname]
        return records[-limit:][::-1]

    def has_reported_on(self, nickname: str, report_date_str: str) -> bool:
        """Сдавал ли человек уже отчёт за эту дату — чтобы разрешить сдачу не чаще
        одного раза в день. Дата сравнивается по первому "слову" (без времени)."""
        target_date = report_date_str.split()[0].strip()
        ws = self.ws(SHEET_LOG_REPORTS)
        records = ws.get_all_records()
        for r in records:
            if r.get("NickName") == nickname and str(r.get("ReportDate", "")).split()[0] == target_date:
                return True
        return False

    # ================= Генерический лог заявок (доп.работа/неактив/снятие — сам факт подачи) =================
    async def log_application_submitted(self, app_label: str, nickname: str, org: str, details: str) -> None:
        now = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S")
        text = (
            f"📩 <b>НОВАЯ ЗАЯВКА — {app_label.upper()}</b>\n"
            f"👤 <b>От кого:</b> {nickname}\n"
            f"🏢 <b>Организация:</b> {org or '—'}\n"
            f"📋 <b>Детали:</b> {details}\n"
            f"⏱ <b>Время:</b> {now}"
        )
        await self._send_log_msg(text)

    # ================= Фрапс обзвона (только лог в канал, ничего не хранится) =================
    async def log_fraps(self, candidate_nick: str, submitted_by_nick: str, submitted_by_role: str, org: str, link: str) -> None:
        now = dt.datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S")
        text = (
            f"🎥 <b>ФРАПС ОБЗВОНА</b>\n"
            f"1. <b>NickName кандидата:</b> {candidate_nick}\n"
            f"2. <b>Кто сдал отчёт:</b> {submitted_by_nick}\n"
            f"3. <b>Должность:</b> {submitted_by_role}\n"
            f"4. <b>Организация:</b> {org}\n"
            f"5. <b>Ссылка:</b> {link}\n"
            f"⏱ <b>Время:</b> {now}"
        )
        await self._send_log_msg(text)

    # ================= Нормативы (по организации и рангу) =================
    def get_norm(self, org: str, rank: int) -> dict | None:
        ws = self.ws(SHEET_NORMS)
        records = ws.get_all_records()
        for r in records:
            if str(r.get("Org")) == org and str(r.get("Rank")) == str(rank):
                return r
        return None

    def set_norm(
        self, org: str, rank: int, vch: int, interview: int, lecture: int,
        training: int, rp: int, online_hours: float,
    ) -> None:
        ws = self.ws(SHEET_NORMS)
        records = ws.get_all_records()
        row_idx = None
        for i, r in enumerate(records, start=2):
            if str(r.get("Org")) == org and str(r.get("Rank")) == str(rank):
                row_idx = i
                break
        row = [org, rank, vch, interview, lecture, training, rp, online_hours]
        if row_idx is None:
            ws.append_row(row)
        else:
            ws.update(f"A{row_idx}:H{row_idx}", [row])

    # ================= Создание листа новой недели =================
    def get_or_create_week_sheet(self, target_date: dt.datetime | None = None) -> str:
        """Возвращает название листа недели, которой принадлежит target_date
        (по умолчанию — сегодня), создавая его из шаблона при необходимости."""
        return self.get_or_create_week_sheet_status(target_date)[0]

    def get_or_create_week_sheet_status(self, target_date: dt.datetime | None = None) -> tuple[str, bool]:
        """То же самое, что get_or_create_week_sheet, но дополнительно говорит,
        был ли лист только что создан (True) или уже существовал (False) —
        удобно вызывать ОДНИМ run()-вызовом из хендлера, вместо того чтобы
        сначала отдельно проверять список листов (см. cb_create_week_sheet)."""
        if target_date is None:
            target_date = dt.datetime.now(MSK_TZ)
        week_title = self._week_title_for(target_date)
        if week_title in self._existing_titles():
            return week_title, False
        created_title = self.create_week_sheet_manual(target_date)
        return created_title, bool(created_title)

    def _previous_week_sheet(self) -> str | None:
        """Ищет последний по дате существующий лист недели (название формата ДД.ММ.ГГГГ | ДД.ММ.ГГГГ)."""
        import re
        existing = self._existing_titles()
        pattern = re.compile(r"^(\d{2}\.\d{2}\.\d{4}) \| \d{2}\.\d{2}\.\d{4}$")
        candidates = []
        for title in existing:
            m = pattern.match(title)
            if m:
                start = dt.datetime.strptime(m.group(1), "%d.%m.%Y")
                candidates.append((start, title))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[-1][1]

    def create_week_sheet_manual(self, target_date: dt.datetime | None = None) -> str:
        """Создаёт лист новой недели (Пн-Вс, включающей target_date, по умолчанию — сегодня)
        из листа-шаблона TEMPLATE_SHEET_NAME, переносит в него актуальный список
        сотрудников (из листа Пользователи) и накопленную статистику с предыдущего
        активного листа недели."""
        if target_date is None:
            target_date = dt.datetime.now(MSK_TZ)

        # Фиксируем "старый" лист ДО создания нового — иначе current_sheet_title
        # может после создания нового листа начать указывать уже на него самого.
        old_week_title = self._previous_week_sheet()

        week_title = self._week_title_for(target_date)
        existing = self._existing_titles()
        if week_title in existing:
            return week_title

        if TEMPLATE_SHEET_NAME not in existing:
            print(
                f"[ERROR] Не удалось создать лист '{week_title}': "
                f"не найден лист-шаблон '{TEMPLATE_SHEET_NAME}'."
            )
            return ""

        template_ws = self.ws(TEMPLATE_SHEET_NAME)
        try:
            new_ws = self._spreadsheet.duplicate_sheet(template_ws.id, new_sheet_name=week_title)
        except Exception as e:
            print(f"[ERROR] Не удалось скопировать шаблон '{TEMPLATE_SHEET_NAME}': {e}")
            return ""

        monday = target_date - dt.timedelta(days=target_date.weekday())
        batch: list[dict] = []
        self._collect_week_dates_update(new_ws, monday, batch)
        self._collect_employees_update(old_week_title, batch)

        if batch:
            # Один HTTP-запрос на ВСЮ таблицу разом (values.batchUpdate), вместо
            # сотен отдельных update_cell — иначе на реальном составе сотрудников
            # это почти гарантированно упирается в лимит Google Sheets
            # "60 write requests per minute per user" (см. traceback с 429).
            try:
                new_ws.batch_update(batch)
            except Exception as e:
                print(f"[ERROR] batch_update при создании листа '{week_title}': {e}")

        print(f"[INFO] Создан новый лист недели: {week_title} (шаблон: {TEMPLATE_SHEET_NAME})")
        return week_title

    def _collect_week_dates_update(self, ws, monday: dt.datetime, batch: list[dict]) -> None:
        dates = [(monday + dt.timedelta(days=i)).strftime("%d.%m.%Y") for i in range(7)]
        # Ищем строку в первых 4 строках, где в колонке D уже стоит что-то похожее на дату —
        # именно туда шаблон ожидает даты недели. Это единственные "живые" чтения
        # перед сборкой батча (4 ячейки), сам список дат пишем одним range.
        date_row = 1
        for row in range(1, 5):
            cell_val = ws.cell(row, 4).value
            if cell_val and any(ch.isdigit() for ch in str(cell_val)):
                date_row = row
                break
        start_a1 = gspread.utils.rowcol_to_a1(date_row, 4)
        end_a1 = gspread.utils.rowcol_to_a1(date_row, 10)
        batch.append({"range": f"{start_a1}:{end_a1}", "values": [dates]})

    def _collect_employees_update(self, old_week_title: str | None, batch: list[dict]) -> None:
        """Готовит диапазоны для батч-записи: актуальный список сотрудников
        (из листа Пользователи, только те, у кого сейчас есть доступ) и перенос
        накопленных баллов/наказаний со старого листа недели, если он есть.
        Ничего не пишет сама — только добавляет {"range", "values"} в batch."""
        users_ws = self.ws(SHEET_USERS)
        records = users_ws.get_all_records()
        users_by_org: dict[str, list[dict]] = {}
        for r in records:
            org = r.get("Org")
            nick = r.get("NickName")
            if not org or not nick:
                continue
            users_by_org.setdefault(org, []).append({
                "nick": nick,
                "added_date": r.get("AddedDate", ""),
            })

        # Всю статистику старого листа читаем ОДНИМ запросом и индексируем в памяти,
        # вместо чтения по ячейке на каждого сотрудника.
        stats_by_nick: dict[str, tuple[float, int, int, int, int]] = {}
        if old_week_title:
            old_ws = self.ws(old_week_title)
            all_values = old_ws.get_all_values()  # 1 API-запрос на чтение всего листа
            for row in all_values[1:]:
                row = row + [""] * (16 - len(row))
                nick = (row[1] or "").strip()
                if not nick:
                    continue

                def _num(v, cast=float):
                    try:
                        return cast(str(v).replace(",", ".") or 0)
                    except ValueError:
                        return cast(0)

                stats_by_nick[nick] = (
                    _num(row[10], float),   # K — общие баллы
                    _num(row[11], int),     # L — строгие выговоры
                    _num(row[12], int),     # M — предупреждения
                    _num(row[13], int),     # N — устные выговоры
                    _num(row[15], int),     # P — дни неактив/нет нормы (накопительно)
                )

        for org, (start_row, end_row) in ORG_ROW_RANGES.items():
            users = users_by_org.get(org, [])
            block_size = end_row - start_row + 1
            if len(users) > block_size:
                print(
                    f"[WARNING] В организации '{org}' сотрудников больше ({len(users)}), "
                    f"чем строк в шаблоне ({block_size}) — лишние не поместятся."
                )

            nick_date_rows = []
            stats_rows = []
            inactive_days_rows = []
            for i in range(block_size):
                if i < len(users):
                    user = users[i]
                    nick_date_rows.append([user["nick"], user["added_date"]])
                    total, strict, warns, verbal, inactive_days = stats_by_nick.get(
                        user["nick"], (0.0, 0, 0, 0, 0)
                    )
                    stats_rows.append([total, strict, warns, verbal])
                    inactive_days_rows.append([inactive_days])
                else:
                    # Пустой слот — чистим (на случай, если раньше тут кто-то был).
                    nick_date_rows.append(["", ""])
                    stats_rows.append(["", "", "", ""])
                    inactive_days_rows.append([""])

            batch.append({
                "range": f"B{start_row}:C{end_row}",
                "values": nick_date_rows,
            })
            batch.append({
                "range": f"K{start_row}:N{end_row}",
                "values": stats_rows,
            })
            batch.append({
                "range": f"P{start_row}:P{end_row}",
                "values": inactive_days_rows,
            })

    # ================= Доступ к самой Google-таблице (Drive API) =================
    def share_sheet_with_user(self, user_email: str, role: str = "writer") -> bool:
        """Выдаёт доступ к таблице по email (роль writer = редактор).
        Требует пакет google-api-python-client (см. requirements.txt)."""
        try:
            from googleapiclient.discovery import build
        except ImportError:
            print(
                "[ERROR] share_sheet_with_user: не установлен google-api-python-client. "
                "Добавьте его в requirements.txt и переустановите зависимости."
            )
            return False
        try:
            creds = _load_google_credentials(["https://www.googleapis.com/auth/drive"])
            drive_service = build("drive", "v3", credentials=creds)
            permission = {"type": "user", "role": role, "emailAddress": user_email}
            drive_service.permissions().create(
                fileId=GOOGLE_SHEET_ID, body=permission, sendNotificationEmail=False
            ).execute()
            return True
        except Exception as e:
            print(f"[ERROR] Не удалось выдать доступ к таблице для {user_email}: {e}")
            return False

    def remove_sheet_access(self, user_email: str) -> bool:
        try:
            from googleapiclient.discovery import build
        except ImportError:
            print(
                "[ERROR] remove_sheet_access: не установлен google-api-python-client. "
                "Добавьте его в requirements.txt и переустановите зависимости."
            )
            return False
        try:
            creds = _load_google_credentials(["https://www.googleapis.com/auth/drive"])
            drive_service = build("drive", "v3", credentials=creds)
            permissions = drive_service.permissions().list(fileId=GOOGLE_SHEET_ID).execute()
            for permission in permissions.get("permissions", []):
                if permission.get("emailAddress") == user_email:
                    drive_service.permissions().delete(
                        fileId=GOOGLE_SHEET_ID, permissionId=permission["id"]
                    ).execute()
                    return True
            return False
        except Exception as e:
            print(f"[ERROR] Не удалось убрать доступ к таблице для {user_email}: {e}")
            return False


# Singleton, инициализируется лениво при первом обращении (см. get_sheets()).
_sheets_instance: SheetsService | None = None


def get_sheets(bot: Bot | None = None) -> SheetsService:
    global _sheets_instance
    if _sheets_instance is None:
        _sheets_instance = SheetsService(bot=bot)
    elif bot is not None and _sheets_instance.bot is None:
        _sheets_instance.bot = bot
    return _sheets_instance


async def run(fn, *args, **kwargs):
    """Выполнить синхронный вызов gspread в отдельном потоке."""
    return await asyncio.to_thread(fn, *args, **kwargs)
