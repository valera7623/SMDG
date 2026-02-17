# app/cli.py
import asyncio
import typer
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.core.security import get_password_hash
from sqlalchemy import select

cli = typer.Typer()

@cli.command(name="create-admin")
def create_admin(
    username: str = typer.Argument("admin", help="Имя пользователя"),
    password: str = typer.Argument(..., help="Пароль администратора"),
    email: str = typer.Option("admin@example.com", help="Email администратора")
):
    """Создаёт или обновляет администратора"""
    async def run():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.username == username)
            )
            user = result.scalar_one_or_none()

            hashed = get_password_hash(password)
            
            if user:
                user.hashed_password = hashed
                user.role = "admin"
                user.is_active = True
                if not user.email:
                    user.email = email
                print(f"Админ {username} обновлён.")
            else:
                user = User(
                    username=username,
                    email=email,  # ← ОБЯЗАТЕЛЬНО
                    hashed_password=hashed,
                    role="admin",
                    is_active=True
                )
                session.add(user)
                print(f"Админ {username} создан с email {email}.")

            await session.commit()
            print("Готово. Теперь можно логиниться.")

    asyncio.run(run())
    
@cli.command(name="rotate-keys")
def rotate_keys(
    backup_dir: str = typer.Option(
        "/app/backups/keys",
        "--backup-dir",
        help="Директория для бэкапа старого ключа"
    )
):
    """Ротация ключей age с перешифровкой всех файлов"""
    import asyncio
    from app.crypto.crypto import crypto_manager
    
    print("Запуск ротации ключей...")
    try:
        new_pub = asyncio.run(crypto_manager.rotate_keys(backup_old_key=True, backup_dir=backup_dir))
        print(f"Ротация завершена. Новый публичный ключ: {new_pub}")
    except Exception as e:
        print(f"Ошибка ротации: {e}")
        raise typer.Exit(code=1)
    
if __name__ == "__main__":
    cli()