# app/core/auth.py
import os
from fastapi import Header, HTTPException, status, Depends
from .config import settings

# Единственное место определения API-ключей
def get_api_keys() -> set[str]:
    raw = os.getenv("API_KEYS", "test-token-123")
    return {k.strip() for k in raw.split(",") if k.strip()}


API_KEYS = get_api_keys()
API_KEY_HEADER = "X-API-KEY"


async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key not in API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )
    return x_api_key
