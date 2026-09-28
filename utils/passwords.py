"""
Хэширование паролей для веб-панели. Пароль НИКОГДА не хранится и не показывается
в открытом виде — только соль+хэш через scrypt (встроен в hashlib, без сторонних
зависимостей). Даже создателю доступен только СБРОС (установить новый), а не
просмотр старого пароля — так таблица не превращается в хранилище паролей.
"""
from __future__ import annotations

import hashlib
import hmac
import os


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or ":" not in stored:
        return False
    try:
        salt_hex, hash_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return hmac.compare_digest(dk.hex(), hash_hex)
