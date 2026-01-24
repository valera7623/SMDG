#!/bin/bash
set -euo pipefail

echo "🚀 Starting SMDG entrypoint..."

# Читаем секреты
if [ -f /run/secrets/admin_password ]; then
    export ADMIN_PASSWORD=$(cat /run/secrets/admin_password)
else
    echo "❌ ERROR: /run/secrets/admin_password not found!"
    exit 1
fi

if [ -f /run/secrets/jwt_secret_key ]; then
    export JWT_SECRET_KEY=$(cat /run/secrets/jwt_secret_key)
else
    echo "❌ ERROR: /run/secrets/jwt_secret_key not found!"
    exit 1
fi

# Для DATABASE_URL нужно сформировать строку с паролем postgres
if [ -f /run/secrets/postgres_password ]; then
    POSTGRES_PASS=$(cat /run/secrets/postgres_password)
    export DATABASE_URL="postgresql+asyncpg://smdg_user:${POSTGRES_PASS}@db:5432/smdg"
else
    echo "❌ ERROR: postgres password secret missing"
    exit 1
fi



# Ждём PostgreSQL — проверяем порт 5432
echo "⏳ Waiting for PostgreSQL port 5432..."
for i in {1..60}; do
  if nc -z db 5432 >/dev/null 2>&1; then
    echo "✅ PostgreSQL порт открыт — база готова"
    break
  fi
  echo "PostgreSQL ещё не готов, ждём 2 секунды... ($i/60)"
  sleep 2
done

if ! nc -z db 5432 >/dev/null 2>&1; then
  echo "❌ PostgreSQL не стал доступен за 120 секунд. Выход."
  exit 1
fi

# Устанавливаем пароль для psql
export PGPASSWORD="${POSTGRES_PASSWORD:-password}"

# Создаём таблицу users, если её нет
echo "🛠️ Ensuring table 'users' exists..."
psql -h db -U smdg_user -d smdg -c "
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role VARCHAR(30) NOT NULL DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE
);
" || true

unset PGPASSWORD

# Применяем миграции
echo "📦 Applying database migrations..."
alembic upgrade head

# Создаём/обновляем админа
echo "👤 Creating/updating admin user..."
python -m app.cli --username admin --password "${ADMIN_PASSWORD:-strongpass123}"

# Запускаем сервер
echo "🖥️ Starting Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info
