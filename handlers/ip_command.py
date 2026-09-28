"""
Команда /ip — доступна следящим и выше.

По условиям заказчика у него уже есть рабочий код в файле ip.py.
Положите ip.py в корень проекта (рядом с main.py) и определите в нём
функцию `async def handle_ip(message: Message) -> None` (или синхронную
`handle_ip(message)`- обе поддерживаются ниже). Этот хендлер лишь
проверяет права доступа и передаёт вызов в ваш ip.py.
"""
from __future__ import annotations

import asyncio
import importlib

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Role
from utils.access import get_user

router = Router(name="ip_command")


@router.message(Command("ip"))
async def cmd_ip(message: Message):
    user = get_user(message.from_user.id)
    if user is None or user.role < Role.WATCHER:
        return

    try:
        ip_module = importlib.import_module("ip")
    except ModuleNotFoundError:
        await message.answer(
            "⚠️ Файл ip.py не найден в корне проекта. Добавьте его и определите функцию handle_ip(message)."
        )
        return

    handler = getattr(ip_module, "handle_ip", None)
    if handler is None:
        await message.answer("⚠️ В ip.py не найдена функция handle_ip(message).")
        return

    if asyncio.iscoroutinefunction(handler):
        await handler(message)
    else:
        await asyncio.to_thread(handler, message)
