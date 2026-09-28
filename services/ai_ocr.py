"""
Разбор альбома скриншотов отчёта через Google Gemini Vision (бесплатный тариф).

Категории активностей (ОПГ):
  vch        — поход на военную часть (на фото машина с надписью "Военная часть" сверху)
  online     — окно "BLACK RUSSIA | Точное время" со строкой "Время в игре сегодня: Xч Yмин"
  interview  — переписка в чате: "начинаю/провожу/заканчиваю собеседование" + счётчик вида 30/30, 0/30, 30/60
  lecture    — переписка в чате: "начну лекцию" / "проведу лекцию" и т.п.
  training   — переписка в чате: "начну/проведу тренировку" + фиолетовые action-сообщения
               (присел, отжался и т.д.)
  rp         — переписка в чате: "проведу РП ситуацию" + фиолетовые action-сообщения о работе
               (моет машину, убирается на хате и т.д.)

Общие правила проверки, которые модель обязана применить:
  - У каждого скрина внизу по центру-справа обязательно должны быть время (жёлтым)
    и дата (синим), например "16:32:49" / "27.01.2026". Если дата не совпадает
    с датой отчёта — скрин отклоняется целиком (date_mismatch).
  - Если по норме нужно несколько единиц одной категории (например 2 тренировки),
    их отметки времени на скринах должны отличаться минимум на
    MIN_MINUTES_BETWEEN_SAME_ACTIVITY минут — иначе повторный скрин не засчитывается
    как отдельная активность (защита от накрутки одной и той же ситуации).
  - Если собеседующий заканчивает одно собеседование и сразу начинает новое —
    это 2 отдельных собеседования (считаем оба, если для обоих есть starts/ends).

Использует google-generativeai (Gemini API). Нужен ключ GEMINI_API_KEY в
переменных окружения — бесплатный, получается на aistudio.google.com без карты.

Так как у бесплатного тарифа Gemini есть лимит запросов в минуту, все вызовы
идут через общий RateLimiter + семафор на количество одновременных запросов
(config.GEMINI_RPM / config.GEMINI_MAX_CONCURRENCY) — при пиковой нагрузке
(много сотрудников сдают отчёт одновременно) запросы просто встают в очередь
и обрабатываются по мере освобождения лимита, вместо падения с ошибкой 429.
"""
from __future__ import annotations

import asyncio
import json

import google.generativeai as genai

from config import (
    GEMINI_API_KEY, GEMINI_MODEL, GEMINI_RPM, GEMINI_MAX_CONCURRENCY,
    MIN_MINUTES_BETWEEN_SAME_ACTIVITY,
)
from utils.rate_limiter import RateLimiter
from google.generativeai.types import HarmCategory, HarmBlockThreshold

_configured = False
_model: "genai.GenerativeModel | None" = None
_rate_limiter = RateLimiter(max_calls=GEMINI_RPM, period_seconds=60.0)
_semaphore = asyncio.Semaphore(GEMINI_MAX_CONCURRENCY)


def _get_model() -> "genai.GenerativeModel":
    global _configured, _model
    if not _configured:
        genai.configure(api_key=GEMINI_API_KEY)
        _configured = True
    if _model is None:
        _model = genai.GenerativeModel(GEMINI_MODEL, system_instruction=_SYSTEM_PROMPT)
    return _model


_SYSTEM_PROMPT = f"""Ты — модератор игрового Telegram-бота, который проверяет отчёты сотрудников \
криминальной организации в игре BLACK RUSSIA. Тебе присылают набор изображений за один отчётный день. \
ВНИМАНИЕ: Каждое переданное изображение МОЖЕТ БЫТЬ КОЛЛАЖЕМ, состоящим из нескольких скриншотов, склеенных вместе. \
Внимательно просматривай каждую картинку, визуально разделяй её на отдельные кадры (если это коллаж) \
и анализируй каждый кадр по отдельности так, будто это самостоятельный скриншот! \
Дата отчёта, за которую сдаётся отчёт, будет указана отдельно в тексте запроса.

На каждом отдельном кадре (или скриншоте) нужно определить:
1. Есть ли внизу изображения по центру-справа время (жёлтым цветом, формат HH:MM:SS) и дата \
(синим цветом, формат DD.MM.YYYY)? Если этих меток нет вообще — пометь как "no_timestamp".
   Если дата на кадре НЕ совпадает с датой отчёта — пометь как "date_mismatch".
2. К какой из категорий относится кадр:
   - "vch" — на фото транспортное средство (обычно грузовик/фургон), над которым отображается \
   надпись с названием "Военная часть" (или похожая про воинскую часть/захват контейнера).
   - "online" — скриншот игрового окна "BLACK RUSSIA | Точное время" со строками \
   "Время в игре за час", "Время в игре сегодня: X ч Y мин", "Время в игре вчера". Извлеки число часов \
   и минут из строки "Время в игре сегодня".
   - "interview" — игровой чат с сообщением о начале/проведении/завершении собеседования \
   (например "начинаю собеседование", "провожу собеседование") рядом со счётчиком "N/M" (например 30/30). \
   Если на одном кадре видно завершение одного и начало другого — это 2 отдельных собеседования.
   - "lecture" — сообщение в чате о начале/проведении лекции ("начну лекцию", "проведу лекцию" и т.п.)
   - "training" — сообщение в чате о начале/проведении тренировки ("начну тренировку", "проведу \
   тренировку"), ЛИБО фиолетовые/розовые action-сообщения о физических упражнениях ("присел", "отжался").
   - "rp" — сообщение в чате о проведении РП ситуации ("проведу РП ситуацию"), ЛИБО \
   фиолетовые/розовые action-сообщения о выполняемой работе ("моет машину", "убирается на хате").
   - "unrecognized" — если кадр не подходит ни под одну категорию.
3. Точное время события с этого кадра (HH:MM:SS из метки внизу) — понадобится для поиска дубликатов.

После разбора всех кадров (включая части коллажей) посчитай итоговые валидные количества по категориям \
vch / interview / lecture / training / rp, и суммарные "Время в игре сегодня" в часах (online_hours_today, \
бери максимальное значение среди online-скринов).

Если среди кадров одной категории (training/lecture/rp/interview) есть два с временными метками, \
разница между которыми МЕНЬШЕ {MIN_MINUTES_BETWEEN_SAME_ACTIVITY} минут — считай это ОДНОЙ активностью \
и отметь дубликат в поле "duplicates".

Верни СТРОГО JSON без пояснений и без markdown-обёртки, в следующем формате:
{{
  "photos": [
    {{
      "index": 0,
      "category": "vch|online|interview|lecture|training|rp|unrecognized",
      "status": "ok|date_mismatch|no_timestamp",
      "timestamp": "HH:MM:SS DD.MM.YYYY или null",
      "note": "краткое пояснение (если это часть коллажа, укажи положение, например 'верхний кадр коллажа')"
    }}
  ],
  "counts": {{"vch": 0, "interview": 0, "lecture": 0, "training": 0, "rp": 0}},
  "online_hours_today": 0.0,
  "duplicates": [{{"category": "training", "indices": [2, 4], "reason": "..."}}],
  "rejected_photos": [{{"index": 1, "reason": "date_mismatch: на кадре 26.01.2026, а нужен 27.01.2026"}}]
}}"""


def _build_content(images: list[tuple[bytes, str]], report_date: str) -> list:
    content: list = [f"Дата отчёта: {report_date}. Всего скриншотов: {len(images)}. Верни JSON по описанной схеме."]
    for i, (data, media_type) in enumerate(images):
        content.append(f"Скриншот #{i}:")
        content.append({"mime_type": media_type, "data": data})
    return content


# Настройки безопасности, чтобы Gemini не блокировал игровые скриншоты
_SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

async def _generate_with_retry(model, content, max_retries: int = 4):
    delay = 2.0
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        await _rate_limiter.acquire()
        async with _semaphore:
            try:
                # Передаем safety_settings в запрос
                response = await model.generate_content_async(
                    content, 
                    safety_settings=_SAFETY_SETTINGS
                )
                
                # Проверяем, не заблокировал ли контент фильтр безопасности Google
                if not response.text:
                    feedback = getattr(response, "prompt_feedback", "Нет данных")
                    raise ValueError(f"Gemini вернул пустой ответ. Возможная блокировка безопасности: {feedback}")
                    
                return response
            except Exception as exc:  # noqa: BLE001 — ретраим любые сетевые/квото-ошибки
                last_exc = exc
                message = str(exc).lower()
                is_rate_error = "429" in message or "quota" in message or "rate" in message
                
                # Если это не ошибка лимита и не блокировка безопасности — сразу пробрасываем
                if not is_rate_error and "блокировка безопасности" not in message and attempt == max_retries - 1:
                    raise
                
                print(f"[GEMINI WARNING] Попытка {attempt + 1} не удалась: {exc}. Повтор через {delay}с...")
                await asyncio.sleep(delay)
                delay *= 2
    raise last_exc  # pragma: no cover


async def analyze_report_album(images: list[tuple[bytes, str]], report_date: str) -> dict:
    """images: список (bytes, media_type) скриншотов одного отчёта.
    report_date: дата отчёта в формате DD.MM.YYYY.

    Возвращает словарь по схеме из промпта. Бросает исключение при сбое запроса
    или если ответ не парсится как JSON — вызывающий код должен обработать это
    как "не удалось распознать отчёт". Запрос автоматически встаёт в очередь
    и ждёт, если исчерпан лимит запросов/минуту бесплатного тарифа.
    """
    model = _get_model()
    content = _build_content(images, report_date)
    response = await _generate_with_retry(model, content)

    text = (response.text or "").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    print(f"\n[DEBUG GEMINI RESPONSE]:\n{text}\n")
    
    return json.loads(text)


def score_report(analysis: dict, norm: dict) -> tuple[int, str, list[str]]:
    """Сравнивает результат анализа с нормативом (get_norm() из sheets.py) и
    определяет ОДИН статус на весь день + баллы за него (см. REPORT_STATUS_POINTS
    в config.py), плюс список причин/пояснений для сообщения пользователю.

    norm ожидается в виде {"VCH": int, "Interview": int, "Lecture": int,
    "Training": int, "RP": int, "OnlineHours": float}.

    Возвращает (points, status, reasons).
    """
    from config import (
        REPORT_STATUS_NORM, REPORT_STATUS_OVER, REPORT_STATUS_STRETCH, REPORT_STATUS_NO_NORM,
        REPORT_STATUS_POINTS, ACTIVITY_LABELS,
    )

    counts = analysis.get("counts", {})
    online_hours = float(analysis.get("online_hours_today") or 0)

    norm_map = {
        "vch": int(float(norm.get("VCH") or 0)),
        "interview": int(float(norm.get("Interview") or 0)),
        "lecture": int(float(norm.get("Lecture") or 0)),
        "training": int(float(norm.get("Training") or 0)),
        "rp": int(float(norm.get("RP") or 0)),
    }
    norm_online = float(norm.get("OnlineHours") or 0)

    total_done = sum(counts.get(k, 0) for k in norm_map)

    reasons = []
    for rej in analysis.get("rejected_photos", []):
        reasons.append(f"Скрин #{rej.get('index')} отклонён: {rej.get('reason')}")
    for dup in analysis.get("duplicates", []):
        reasons.append(
            f"Дубликат по категории {ACTIVITY_LABELS.get(dup.get('category'), dup.get('category'))}: "
            f"засчитан только один раз ({dup.get('reason')})"
        )

    if total_done == 0 and online_hours == 0:
        status = REPORT_STATUS_NO_NORM
        points = REPORT_STATUS_POINTS[status]
        reasons.insert(0, "Отчёт пустой — ни одна активность не распознана")
        reasons.append(f"Итоговый статус: {status} ({points:+d} баллов)")
        return points, status, reasons

    fully_met = True
    over_any = False

    for key, required in norm_map.items():
        done = counts.get(key, 0)
        label = ACTIVITY_LABELS[key]
        if required == 0:
            continue
        if done >= required:
            over = done - required
            if over > 0:
                over_any = True
                reasons.append(f"{label}: {done}/{required} — перевыполнено")
            else:
                reasons.append(f"{label}: {done}/{required} — норма выполнена")
        else:
            fully_met = False
            reasons.append(f"{label}: {done}/{required} — недостаточно")

    if norm_online > 0:
        if online_hours >= norm_online:
            if online_hours > norm_online:
                over_any = True
            reasons.append(f"Онлайн: {online_hours:.1f}ч/{norm_online:.1f}ч — норма выполнена")
        else:
            fully_met = False
            reasons.append(f"Онлайн: {online_hours:.1f}ч/{norm_online:.1f}ч — недостаточно")

    if fully_met:
        status = REPORT_STATUS_OVER if over_any else REPORT_STATUS_NORM
    else:
        # что-то сделано, но норма целиком не закрыта — "натяг", 0 баллов
        status = REPORT_STATUS_STRETCH

    points = REPORT_STATUS_POINTS[status]
    reasons.append(f"Итоговый статус: {status} ({points:+d} баллов)")
    return points, status, reasons
