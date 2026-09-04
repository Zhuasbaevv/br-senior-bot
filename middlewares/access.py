from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from utils.access import has_access

ALWAYS_ALLOWED_COMMANDS = {"/id", "/ping"}


class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if isinstance(event, Message) and event.text:
            cmd = event.text.split()[0].split("@")[0]
            if cmd in ALWAYS_ALLOWED_COMMANDS:
                return await handler(event, data)

        if has_access(user.id):
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer("❌️Доступ к боту закрыт")
        elif isinstance(event, CallbackQuery):
            await event.answer("❌️Доступ к боту закрыт", show_alert=True)
        return None
