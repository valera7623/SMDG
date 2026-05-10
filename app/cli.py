# app/cli.py
import asyncio
import typer

from app.warnings_filters import apply_known_warning_filters

apply_known_warning_filters()

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.tenant import Tenant  # нужно будет создать
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


async def _create_tenant_async(
    name: str,
    subdomain: str,
    admin_email: str,
    admin_password: str,
) -> str:
    """Асинхронная логика создания tenant и его администратора"""
    async with AsyncSessionLocal() as session:
        # Проверка существующего tenant
        result = await session.execute(
            select(Tenant).where(Tenant.subdomain == subdomain)
        )
        existing_tenant = result.scalar_one_or_none()
        
        if existing_tenant:
            return f"❌ Tenant с subdomain '{subdomain}' уже существует (id={existing_tenant.id})"
        
        # Проверка существующего пользователя с таким email
        result = await session.execute(
            select(User).where(User.email == admin_email)
        )
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            return f"❌ Пользователь с email '{admin_email}' уже существует"
        
        # Создаём tenant
        tenant = Tenant(
            name=name,
            subdomain=subdomain,
            settings={
                "ttl_days": 30,
                "max_downloads": 5,
                "require_2fa": False,
            }
        )
        session.add(tenant)
        await session.flush()  # получаем tenant.id
        
        # Создаём администратора tenant
        admin = User(
            username=f"admin_{subdomain}",
            email=admin_email,
            hashed_password=get_password_hash(admin_password),
            role="admin",
            is_active=True,
            tenant_id=tenant.id,
        )
        session.add(admin)
        await session.commit()
        
        return f"""✅ Tenant '{name}' создан:
   - ID: {tenant.id}
   - Subdomain: {subdomain}
   - Администратор: {admin_email}
   - Логин: admin_{subdomain}"""


async def _create_user_async(
    username: str,
    password: str,
    email: str,
    role: str = "user",
    tenant_id: int = None,
) -> str:
    """Асинхронная логика создания обычного пользователя"""
    async with AsyncSessionLocal() as session:
        # Проверка существующего пользователя
        result = await session.execute(
            select(User).where(User.username == username)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            return f"❌ Пользователь с именем '{username}' уже существует"
        
        # Проверка email
        result = await session.execute(
            select(User).where(User.email == email)
        )
        existing_email = result.scalar_one_or_none()
        
        if existing_email:
            return f"❌ Пользователь с email '{email}' уже существует"
        
        # Если указан tenant_id — проверить, что tenant существует
        if tenant_id:
            result = await session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
            tenant = result.scalar_one_or_none()
            if not tenant:
                return f"❌ Tenant с id={tenant_id} не существует"
        
        # Создаём пользователя
        user = User(
            username=username,
            email=email,
            hashed_password=get_password_hash(password),
            role=role,
            is_active=True,
            tenant_id=tenant_id,
        )
        session.add(user)
        await session.commit()
        
        tenant_info = f", tenant_id={tenant_id}" if tenant_id else ""
        return f"✅ Пользователь '{username}' создан (role={role}, email={email}{tenant_info})"


async def _list_users_async(tenant_id: int = None) -> str:
    """Асинхронная логика списка пользователей"""
    async with AsyncSessionLocal() as session:
        query = select(User)
        if tenant_id:
            query = query.where(User.tenant_id == tenant_id)
        
        result = await session.execute(query)
        users = result.scalars().all()
        
        if not users:
            return "Нет зарегистрированных пользователей"
        
        lines = ["\n📋 Список пользователей:"]
        lines.append("-" * 80)
        for u in users:
            tenant_info = f" (tenant={u.tenant_id})" if u.tenant_id else ""
            lines.append(f"  ID: {u.id} | {u.username} | {u.email} | role: {u.role} | active: {u.is_active}{tenant_info}")
        return "\n".join(lines)


# ========== СИНХРОННЫЕ КОМАНДЫ (добавить) ==========

@cli.command(name="create-user")
def create_user(
    username: str = typer.Option(..., help="Имя пользователя"),
    password: str = typer.Option(..., help="Пароль пользователя"),
    email: str = typer.Option(..., help="Email пользователя"),
    role: str = typer.Option("user", help="Роль: admin, doctor, user"),
    tenant_id: int = typer.Option(None, help="ID tenant (организации)"),
):
    """
    Создаёт нового пользователя.
    
    Пример:
    python -m app.cli create-user \\
      --username doctor_ivanov \\
      --password Doctor123! \\
      --email ivanov@clinic.ru \\
      --role doctor
    """
    try:
        output = asyncio.run(_create_user_async(
            username=username,
            password=password,
            email=email,
            role=role,
            tenant_id=tenant_id,
        ))
        print(output)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        raise typer.Exit(code=1)


@cli.command(name="list-users")
def list_users(
    tenant_id: int = typer.Option(None, help="Фильтр по tenant ID"),
):
    """
    Показывает список всех пользователей.
    
    Пример:
    python -m app.cli list-users
    python -m app.cli list-users --tenant-id 1
    """
    try:
        output = asyncio.run(_list_users_async(tenant_id=tenant_id))
        print(output)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        raise typer.Exit(code=1)





async def _rotate_keys_async(backup_dir: str) -> str:
    """Асинхронная логика ротации ключей"""
    from app.crypto.crypto import crypto_manager
    new_pub = await crypto_manager.rotate_keys(
        backup_old_key=True, 
        backup_dir=backup_dir
    )
    return f"Ротация завершена. Новый публичный ключ: {new_pub}"


async def _list_tenants_async() -> str:
    """Асинхронная логика списка tenants"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Tenant))
        tenants = result.scalars().all()
        
        if not tenants:
            return "Нет зарегистрированных организаций (tenants)"
        
        lines = ["\n📋 Список организаций (tenants):"]
        lines.append("-" * 60)
        for t in tenants:
            lines.append(f"  ID: {t.id} | {t.name} | subdomain: {t.subdomain}")
        return "\n".join(lines)


# ========== СИНХРОННЫЕ КОМАНДЫ (ОБЁРТКИ) ==========

@cli.command(name="create-admin")
def create_admin(
    username: str = typer.Argument("admin", help="Имя пользователя"),
    password: str = typer.Argument(..., help="Пароль администратора"),
    email: str = typer.Option("admin@example.com", help="Email администратора")
):
    """Создаёт или обновляет администратора"""
    try:
        print(f"DEBUG: creating admin with username={username}, email={email}")
        output = asyncio.run(_create_admin_async(username, password, email))
        print(output)
        print("Готово. Теперь можно логиниться.")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        raise typer.Exit(code=1)


@cli.command(name="create-tenant")
def create_tenant(
    name: str = typer.Option(..., help="Название организации"),
    subdomain: str = typer.Option(..., help="Уникальный subdomain (например, 'alpha')"),
    admin_email: str = typer.Option(..., help="Email администратора tenant"),
    admin_password: str = typer.Option(..., help="Пароль администратора"),
):
    """
    Создаёт нового tenant (организацию) и его администратора.
    
    Пример:
    python -m app.cli create-tenant \
      --name "Клиника Альфа" \
      --subdomain alpha \
      --admin-email admin@alpha.com \
      --admin-password Admin123!
    """
    try:
        output = asyncio.run(_create_tenant_async(
            name=name,
            subdomain=subdomain,
            admin_email=admin_email,
            admin_password=admin_password,
        ))
        print(output)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        raise typer.Exit(code=1)


@cli.command(name="list-tenants")
def list_tenants():
    """Показывает список всех tenants (организаций)"""
    try:
        output = asyncio.run(_list_tenants_async())
        print(output)
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


@cli.command(name="feature-info")
def feature_info():
    """Показать профиль развёртывания и включённые фичи."""
    from app.core.feature_flags import get_deployment_info
    import json

    info = get_deployment_info()
    print(json.dumps(info, ensure_ascii=False, indent=2))


@cli.command(name="feature-check")
def feature_check(
    feature: str = typer.Option(..., "--feature", help="Имя фичи, например DICOM_VIEWER"),
):
    """Проверить, включена ли указанная фича для текущего DEPLOYMENT_TYPE."""
    from app.core.feature_flags import Feature, is_enabled

    try:
        f = Feature[feature.strip().upper()]
    except KeyError:
        try:
            f = Feature(feature.strip().lower())
        except ValueError:
            print(f"Неизвестная фича: {feature}")
            raise typer.Exit(code=2)

    ok = is_enabled(f)
    print(f"{f.value}: {'enabled' if ok else 'disabled'}")
    raise typer.Exit(code=0 if ok else 1)


if __name__ == "__main__":
    cli()