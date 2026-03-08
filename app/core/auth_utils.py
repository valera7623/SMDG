# app/core/auth_utils.py

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from pydantic import BaseModel

from app.core.config import settings


class TokenData(BaseModel):
    sub: str
    role: str = "user"


def create_access_token(
    subject: str,
    role: str = "user",
    expires_delta: Optional[timedelta] = None
) -> str:
    to_encode = {"sub": subject, "role": role}
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.jwt_access_expires_minutes))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return encoded_jwt