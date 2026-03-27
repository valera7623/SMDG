# app/cli.py
import asyncio
import typer
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.core.security import get_password_hash
from sqlalchemy import select

cli = typer.Typer()

# ========== АСИНХРОННАЯ ЛОГИКА ==========

async def _create_admin_async(username: str, password: str, email: str) -> str:
    """Асинхронная логика создания администратора"""
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
            await session.commit()
            return f"Админ {username} обновлён."
        else:
            user = User(
                username=username,
                email=email,
                hashed_password=hashed,
                role="admin",
                is_active=True
            )
            session.add(user)
            await session.commit()
            return f"Админ {username} создан с email {email}."


async def _rotate_keys_async(backup_dir: str) -> str:
    """Асинхронная логика ротации ключей"""
    from app.crypto.crypto import crypto_manager
    new_pub = await crypto_manager.rotate_keys(
        backup_old_key=True, 
        backup_dir=backup_dir
    )
    return f"Ротация завершена. Новый публичный ключ: {new_pub}"


# ========== СИНХРОННЫЕ КОМАНДЫ (ОБЁРТКИ) ==========

# app/cli.py - временно добавьте print для отладки
@cli.command(name="create-admin")
def create_admin(
    username: str = typer.Argument("admin", help="Имя пользователя"),
    password: str = typer.Argument(..., help="Пароль администратора"),
    email: str = typer.Option("admin@example.com", help="Email администратора")
):
    """Создаёт или обновляет администратора"""
    try:
        # Временная отладка
        print(f"DEBUG: calling _create_admin_async with username={username}, password={password}, email={email}")
        
        output = asyncio.run(_create_admin_async(username, password, email))
        print(output)
        print("Готово. Теперь можно логиниться.")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        raise typer.Exit(code=1)


@cli.command(name="rotate-keys")
def rotate_keys(
    backup_dir: str = typer.Option(
        "/app/backups/keys",
        "--backup-dir",
        help="Директория для бэкапа старого ключа"
    )
):
    """Ротация ключей age с перешифровкой всех файлов"""
    print("Запуск ротации ключей...")
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        
        if loop and loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            result = asyncio.run_coroutine_threadsafe(
                _rotate_keys_async(backup_dir),
                loop
            )
            output = result.result()
        else:
            output = asyncio.run(_rotate_keys_async(backup_dir))
        
        print(output)
    except Exception as e:
        print(f"Ошибка ротации: {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    cli()