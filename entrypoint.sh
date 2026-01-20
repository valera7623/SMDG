#!/bin/bash
set -e  # Выходим при первой ошибке

echo "🚀 Starting SMDG entrypoint..."

# Применяем миграции Alembic
echo "📦 Applying database migrations..."
alembic upgrade head

# Создаём/обновляем админа (если нужно, добавь --password из env)
echo "👤 Creating/updating admin user..."
python -m app.cli create_admin --username admin --password "${ADMIN_PASSWORD:-password}"

# Запускаем основной сервер
echo "🖥️ Starting Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info