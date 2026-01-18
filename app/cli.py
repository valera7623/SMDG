# app/cli.py
import asyncio
import typer
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.core.security import get_password_hash
from sqlalchemy import select

cli = typer.Typer()

@cli.command()
def create_admin(
    username: str = "admin",
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True)
):
    """Создаёт или обновляет администратора"""
    async def run():
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()

            hashed = get_password_hash(password)
            
            if user:
                user.hashed_password = hashed
                user.role = "admin"
                user.is_active = True
                print(f"Админ {username} обновлён.")
            else:
                user = User(username=username, hashed_password=hashed, role="admin", is_active=True)
                session.add(user)
                print(f"Админ {username} создан.")

            await session.commit()
            print("Готово. Теперь можно логиниться.")

    asyncio.run(run())

if __name__ == "__main__":
    cli()