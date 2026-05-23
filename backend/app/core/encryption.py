"""Fernet-based at-rest encryption for credentials.

Used to wrap IMAP passwords, OAuth refresh tokens, Bexio API keys, etc.
ENCRYPTION_KEY must be a valid Fernet key (urlsafe base64, 32 bytes).
"""
from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _cipher() -> Fernet:
    key = settings.encryption_key.encode() if isinstance(settings.encryption_key, str) else settings.encryption_key
    return Fernet(key)


def encrypt_str(plain: str) -> str:
    if plain is None:
        return ""
    return _cipher().encrypt(plain.encode()).decode()


def decrypt_str(token: str) -> str:
    if not token:
        return ""
    try:
        return _cipher().decrypt(token.encode()).decode()
    except InvalidToken:
        # Allow plain-text legacy values to pass through during migrations.
        return token


def encrypt_json(value: Any) -> str:
    return encrypt_str(json.dumps(value, ensure_ascii=False, default=str))


def decrypt_json(token: str) -> Any:
    if not token:
        return None
    raw = decrypt_str(token)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
