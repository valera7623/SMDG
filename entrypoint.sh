#!/bin/bash
set -euo pipefail

echo "🚀 Starting SMDG entrypoint..."

# ────────────────────────────────────────────────────────────────
# Чтение секретов
# ────────────────────────────────────────────────────────────────
echo "⏳ Чтение Docker Secrets..."

if [ -f /run/secrets/jwt_secret_key ]; then
    export JWT_SECRET_KEY=$(cat /run/secrets/jwt_secret_key | tr -d '\n\r')
    echo "✅ JWT_SECRET_KEY прочитан"
else
    echo "❌ /run/secrets/jwt_secret_key не найден!" && exit 1
fi



if [ -z "$JWT_SECRET_KEY" ] || [ ${#JWT_SECRET_KEY} -lt 48 ]; then
    echo "❌ JWT_SECRET_KEY отсутствует или слишком короткий (минимум 48 символов)!"
    exit 1
fi


if echo "$JWT_SECRET_KEY" | grep -q "change-me"; then
    echo "❌ JWT_SECRET_KEY выглядит как дефолтный плейсхолдер! Установите настоящий секрет."
    exit 1
fi

if [ -f /run/secrets/admin_password ]; then
    export ADMIN_PASSWORD=$(cat /run/secrets/admin_password | tr -d '\n\r')
    echo "✅ ADMIN_PASSWORD прочитан"
else
    echo "❌ /run/secrets/admin_password не найден!" && exit 1
fi

if [ -f /run/secrets/postgres_password ]; then
    POSTGRES_PASS=$(cat /run/secrets/postgres_password | tr -d '\n\r')
    export DATABASE_URL="postgresql+asyncpg://smdg_user:${POSTGRES_PASS}@db:5432/smdg"
    export PGPASSWORD="$POSTGRES_PASS"
    echo "✅ DATABASE_URL и PGPASSWORD сформированы"
else
    echo "❌ /run/secrets/postgres_password не найден!" && exit 1
fi

if [ ! -f /app/keys/age.key ]; then
    echo "❌ Приватный ключ /app/keys/age.key отсутствует!" && exit 1
fi
echo "✅ Приватный ключ age найден"

# ────────────────────────────────────────────────────────────────
# Инициализация S3/MinIO (если включено)
# ────────────────────────────────────────────────────────────────
if [ "${S3_ENABLED:-false}" = "true" ]; then
    echo "🪣 S3 режим включён — инициализация бакетов..."
    bash /app/scripts/init_s3_buckets.sh

    echo "⏳ Ожидание готовности MinIO/S3..."
    # Ждём S3 endpoint
    for i in {1..30}; do
        if curl -sf "${S3_ENDPOINT_URL:-http://minio:9000}/minio/health/live" >/dev/null 2>&1; then
            echo "✅ S3 endpoint доступен"
            break
        fi
        echo "S3 ещё не готов... ($i/30)"
        sleep 2
    done
else
    echo "ℹ️  S3 отключён — используется локальное хранилище"
fi

# ────────────────────────────────────────────────────────────────
# Ждём PostgreSQL
# ────────────────────────────────────────────────────────────────
echo "⏳ Waiting for PostgreSQL port 5432..."
for i in {1..60}; do
  if nc -z db 5432 >/dev/null 2>&1; then
    echo "✅ PostgreSQL порт открыт"
    break
  fi
  echo "PostgreSQL ещё не готов... ($i/60)"
  sleep 2
done

if ! nc -z db 5432 >/dev/null 2>&1; then
  echo "❌ PostgreSQL не доступен за 120 сек" && exit 1
fi

# ────────────────────────────────────────────────────────────────
# ТОЛЬКО МИГРАЦИИ - никаких ручных созданий таблиц!
# ────────────────────────────────────────────────────────────────
echo "🛠️ Applying database migrations..."
alembic upgrade head

# ────────────────────────────────────────────────────────────────
# Создаём админа (уже через миграции данные должны быть)
# ────────────────────────────────────────────────────────────────
echo "👤 Creating/updating admin user..."
python -m app.cli create-admin admin "${ADMIN_PASSWORD}" --email admin@example.com

# ────────────────────────────────────────────────────────────────
# Автоматическая ротация ключей (каждые 90 дней)
# ────────────────────────────────────────────────────────────────
echo "Проверка необходимости ротации ключей..."
LAST_ROTATION_FILE="/app/keys/last_rotation.txt"
ROTATION_INTERVAL_DAYS=90
CURRENT_TIME=$(date +%s 2>/dev/null || echo "0")

if [ -f "$LAST_ROTATION_FILE" ]; then
    LAST_ROTATION=$(cat "$LAST_ROTATION_FILE" 2>/dev/null || echo "1970-01-01")
    LAST_TIME=$(date -d "$LAST_ROTATION" +%s 2>/dev/null || echo "0")

    DAYS_SINCE=$(( (CURRENT_TIME - LAST_TIME) / 86400 ))

    if [ "$DAYS_SINCE" -ge "$ROTATION_INTERVAL_DAYS" ]; then
        echo "Прошло $DAYS_SINCE дней → ротация"

        # Создаём директорию бэкапов
        mkdir -p /app/backups/keys

        # Запускаем ротацию (без --no-backup)
        python -m app.cli rotate-keys >> /app/audit_logs/key_rotation.log 2>&1 \
            && echo "Ротация OK" && date --iso-8601=seconds > "$LAST_ROTATION_FILE" \
            || { echo "ОШИБКА ротации (см. /app/audit_logs/key_rotation.log)"; exit 1; }
    else
        echo "Ротация не нужна (прошло $DAYS_SINCE дней)"
    fi
else
    echo "Первый запуск — ротацию пропускаем"
    date --iso-8601=seconds > "$LAST_ROTATION_FILE"
fi

./generate_cert.sh

# Проверка директории бэкапов
BACKUP_DIR="/app/backups"

if [ ! -d "$BACKUP_DIR" ]; then
    echo "❌ Директория бэкапов $BACKUP_DIR не существует!"
    echo "   Создаём..."
    mkdir -p "$BACKUP_DIR"
    chmod 750 "$BACKUP_DIR"
    chown $(whoami) "$BACKUP_DIR"  # или конкретный uid, если нужно
fi

# Проверка прав на запись
if [ ! -w "$BACKUP_DIR" ]; then
    echo "❌ Нет прав на запись в $BACKUP_DIR!"
    exit 1
fi

echo "✅ Директория бэкапов $BACKUP_DIR готова"

# ────────────────────────────────────────────────────────────────
# Информация о режиме хранилища
# ────────────────────────────────────────────────────────────────
if [ "${S3_ENABLED:-false}" = "true" ]; then
    echo "🪣 Режим хранилища: S3/MinIO (${S3_ENDPOINT_URL:-unknown})"
    echo "   Бакет encrypted: ${S3_BUCKET_ENCRYPTED:-smdg-encrypted}"
else
    echo "💾 Режим хранилища: Локальная файловая система"
    echo "   Директория encrypted: /app/encrypted"
fi

# ────────────────────────────────────────────────────────────────
# Запуск приложения
# ────────────────────────────────────────────────────────────────
echo "🖥️ Starting Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info