"""Password hashing and JWT issuing/verification."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.config import Settings

logger = logging.getLogger(__name__)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    # bcrypt silently truncates beyond 72 bytes; reject rather than mislead.
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes.")
    return _pwd.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _pwd.verify(password, password_hash)
    except ValueError:
        return False


def create_access_token(settings: Settings, user_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(settings: Settings, token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.info("Rejected an expired access token")
        return None
    except jwt.InvalidTokenError as exc:
        logger.info("Rejected an invalid access token: %s", exc)
        return None
