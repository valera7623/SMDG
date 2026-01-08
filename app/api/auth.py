# app/api/auth.py
from fastapi import APIRouter, Form, HTTPException, status
from app.core.auth import create_access_token
from datetime import timedelta

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Простая "база" пользователей (в реальности — из БД с хешами!)
USERS = {
    "admin": {"password": "admin123", "role": "admin"},
    "doctor1": {"password": "docpass1", "role": "doctor"},
    "doctor2": {"password": "docpass2", "role": "doctor"},
    "user1": {"password": "userpass", "role": "user"},
}

@router.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    user = USERS.get(username)
    if not user or user["password"] != password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль"
        )
    
    access_token = create_access_token(
        subject=username,
        role=user["role"],
        expires_delta=timedelta(minutes=60)
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user["role"],
        "username": username,
        "expires_in": 3600
    }