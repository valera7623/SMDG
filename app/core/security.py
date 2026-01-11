# app/core/security.py
from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["argon2"],           # ← основной
          
    argon2__time_cost=2,          # можно подкрутить под производительность
    argon2__memory_cost=102400,
    argon2__parallelism=8,
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)