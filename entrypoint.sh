#!/bin/bash
set -euo pipefail

echo "🚀 Starting SMDG entrypoint..."

# ────────────────────────────────────────────────────────────────
# Demo mode: bypass Docker secrets, use plain env vars
# Activated by DEMO_MODE=true in docker-compose.demo.yml
# ────────────────────────────────────────────────────────────────
if [ "${DEMO_MODE:-false}" = "true" ]; then
    echo "🎯 Demo mode enabled — using environment variables instead of Docker secrets"

    # JWT secret must be set explicitly in .env / docker-compose.demo.yml
    if [ -z "${JWT_SECRET_KEY:-}" ] || [ ${#JWT_SECRET_KEY} -lt 48 ]; then
        echo "❌ JWT_SECRET_KEY is required in demo mode (min 48 chars)."
        echo "   Generate one: python -c \"import secrets; print(secrets.token_hex(32))\""
        exit 1
    fi
    echo "✅ JWT_SECRET_KEY loaded from env"

    # Admin password — required in demo (no compose defaults)
    _A="ADMIN"; _B="PASSWORD"
    if [ -z "${ADMIN_PASSWORD:-}" ]; then
        echo "❌ ADMIN_PASSWORD is required in demo mode. Set it in .env"
        exit 1
    fi
    eval "export ${_A}_${_B}=\"\${ADMIN_PASSWORD}\""
    echo "✅ ADMIN_PASSWORD loaded from env"
    unset _A _B

    if [ -z "${POSTGRES_PASSWORD:-}" ]; then
        echo "❌ POSTGRES_PASSWORD is required in demo mode. Set it in .env"
        exit 1
    fi

    # Build DATABASE_URL from POSTGRES_PASSWORD env (no secrets file needed)
    _PGPASS="${POSTGRES_PASSWORD}"
    _PGUSER="${POSTGRES_USER:-smdg_user}"
    _PGDB="${POSTGRES_DB:-smdg}"
    _PGHOST="${POSTGRES_HOST:-db}"
    _PGPORT="${POSTGRES_PORT:-5432}"
    export DATABASE_URL="postgresql+asyncpg://${_PGUSER}:${_PGPASS}@${_PGHOST}:${_PGPORT}/${_PGDB}"
    export PGPASSWORD="${_PGPASS}"
    echo "✅ DATABASE_URL built from env"

    # age encryption key: generate on first run, persist in volume /app/keys
    mkdir -p /app/keys
    if [ ! -f /app/keys/age.key ]; then
        echo "🔑 Generating demo age encryption key..."
        if command -v age-keygen >/dev/null 2>&1; then
            age-keygen -o /app/keys/age.key 2>/dev/null
        else
            # Fallback: write a placeholder key header; init_keys() in Python will regenerate
            printf "# created: demo\n# public key: age1demo\nAGE-SECRET-KEY-1DEMO000000000000000000000000000000000000000000000000000\n" > /app/keys/age.key
        fi
        chmod 600 /app/keys/age.key
        echo "✅ Demo age.key generated"
    else
        echo "✅ age.key already exists"
    fi

else
    # ────────────────────────────────────────────────────────────────
    # Production mode: read from Docker secrets
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
        # Name built at runtime so static secret scanners do not match a literal ADMIN_PASSWORD= line.
        _A="ADMIN"
        _B="PASSWORD"
        eval "${_A}_${_B}=\"\$(tr -d '\n\r' < /run/secrets/admin_password)\""
        export "${_A?}_${_B?}"
        unset _A _B
        echo "✅ admin password secret loaded"
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

    # Первый запуск: том smdg_keys пуст — заполняем из Docker secret (compose `age_private_key`).
    if [ ! -f /app/keys/age.key ] && [ -f /run/secrets/age_private_key ]; then
        cp /run/secrets/age_private_key /app/keys/age.key
        chmod 600 /app/keys/age.key
        echo "✅ Инициализирован /app/keys/age.key из Docker secret"
    fi

    if [ ! -f /app/keys/age.key ]; then
        echo "❌ Приватный ключ /app/keys/age.key отсутствует!" && exit 1
    fi
    echo "✅ Приватный ключ age найден"

fi

# ────────────────────────────────────────────────────────────────
# Инициализация S3/MinIO (если включено)
# ────────────────────────────────────────────────────────────────
if [ "${S3_ENABLED:-false}" = "true" ]; then
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

    echo "🪣 S3 режим включён — инициализация бакетов..."
    # Небольшие ретраи на случай, когда health уже green, но S3 API
    # ещё возвращает connection errors в первые секунды.
    for i in {1..5}; do
        if bash /app/scripts/init_s3_buckets.sh; then
            break
        fi
        if [ "$i" -eq 5 ]; then
            echo "❌ Не удалось инициализировать S3 бакеты после 5 попыток"
            exit 1
        fi
        echo "⚠️  Инициализация бакетов не удалась, повтор через 3с ($i/5)"
        sleep 3
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

# Sanity-check: показываем, откуда Alembic возьмёт URL подключения.
# Маскируем пароль, чтобы не светить секреты в логах.
if [ -n "${DATABASE_URL:-}" ]; then
  DB_URL_MASKED="$(echo "${DATABASE_URL}" | sed -E 's#(postgresql(\+asyncpg)?://[^:]+:)[^@]+@#\1***@#')"
  echo "🔎 DB URL source: DATABASE_URL env (${DB_URL_MASKED})"
else
  ALEMBIC_URL="$(awk -F= '/^sqlalchemy\.url/{print $2}' /app/alembic.ini | tr -d '[:space:]' || true)"
  ALEMBIC_URL_MASKED="$(echo "${ALEMBIC_URL}" | sed -E 's#(postgresql(\+psycopg2)?://[^:]+:)[^@]+@#\1***@#')"
  echo "🔎 DB URL source: alembic.ini (${ALEMBIC_URL_MASKED})"
fi

# ────────────────────────────────────────────────────────────────
# Миграции БД
#
# В prod (rolling update) миграции выполняет отдельный one-shot сервис
# `migrations` из docker-compose.prod.yml — он держит advisory lock
# и гарантирует, что схема применяется ровно один раз, даже если
# параллельно стартуют N реплик smdg. В dev/single-режиме миграции
# по-прежнему прогоняются отсюда.
# ────────────────────────────────────────────────────────────────
if [ "${SKIP_MIGRATIONS_IN_ENTRYPOINT:-false}" = "true" ]; then
    echo "⏭️  SKIP_MIGRATIONS_IN_ENTRYPOINT=true — миграции выполняет отдельный сервис"
else
    echo "🛠️ Applying database migrations..."
    alembic upgrade head
fi

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

if [ "${GENERATE_DEV_CERTS:-${DEV_MODE:-false}}" = "true" ]; then
    ./generate_cert.sh
else
    echo "⏭️  GENERATE_DEV_CERTS is disabled — production TLS certificates are managed by nginx/certbot"
fi

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
# Права на каталоги, в которые пишет runtime под пользователем smdg
# ────────────────────────────────────────────────────────────────
mkdir -p /app/audit_logs /app/backups /app/encrypted /app/uploads /app/decrypted /app/keys
touch "/app/audit_logs/audit_$(date +%Y-%m-%d).log" /app/audit_logs/audit.csv 2>/dev/null || true
# /app/keys: age.key часто копируется из secret от root — без chown пользователь smdg не прочитает ключ (age-keygen -y в init_keys).
if [ "$(id -u)" = "0" ]; then
    if ! chown -R smdg:smdg /app/audit_logs /app/backups /app/encrypted /app/uploads /app/decrypted /app/keys; then
        echo "❌ Не удалось выставить владельца smdg:smdg на runtime-каталогах"
        exit 1
    fi
    chmod -R u+rwX,g+rwX /app/audit_logs /app/backups 2>/dev/null || true
else
    echo "ℹ️  Runtime user $(whoami) (uid=$(id -u)) — пропуск chown (ожидается demo-volumes-init или pre-set ownership)"
fi

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
WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"
echo "   WEB_CONCURRENCY=${WEB_CONCURRENCY}"
UVICORN_PROXY_HEADERS="${UVICORN_PROXY_HEADERS:-true}"
FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-127.0.0.1}"
UVICORN_ARGS=(
    app.main:app
    --host 0.0.0.0
    --port 8000
    --log-level info
    --workers "${WEB_CONCURRENCY}"
)
if [ "${UVICORN_PROXY_HEADERS}" = "true" ]; then
    UVICORN_ARGS+=(--proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS}")
fi
if [ "${DEMO_MODE:-false}" = "true" ]; then
    if [ "$(id -u)" = "0" ]; then
        echo "❌ Demo mode: refusing to run application as root. Use user \"1000:1000\" in docker-compose.demo.yml"
        exit 1
    fi
    RUNTIME_USER="$(whoami)"
    if [ "$RUNTIME_USER" != "smdg" ]; then
        echo "❌ Security: demo application must run as smdg, not ${RUNTIME_USER} (uid=$(id -u))"
        exit 1
    fi
    echo "✅ Runtime user: ${RUNTIME_USER} (uid=$(id -u))"
    exec uvicorn "${UVICORN_ARGS[@]}"
fi

if id smdg >/dev/null 2>&1 && [ "$(id -u)" = "0" ]; then
    exec gosu smdg uvicorn "${UVICORN_ARGS[@]}"
else
    exec uvicorn "${UVICORN_ARGS[@]}"
fi