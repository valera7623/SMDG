# app/core/auth.py
from fastapi import Header, HTTPException, status

# Список валидных токенов (для простоты, потом можно хранить в БД)
API_TOKENS = {
    "test-token-123": "Alice",
    "test-token-456": "Bob"
}

async def verify_api_token(x_api_key: str = Header(...)):
    if x_api_key not in API_TOKENS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )
    return API_TOKENS[x_api_key]  # возвращаем имя пользователя
